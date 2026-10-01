#!/usr/bin/env python3
"""dedup_dream.py — SEMANTICKY dedup pamate pre nocny dream loop (P2, cesta A).

PRECO NIE embedding-vyber kandidatov: WRITE gate v zol_mem.py chyta near-exact
(d<0.15). Semanticke/parafrazove duplikaty YAR Lorentz NEODLISI od cudzieho textu
(namerane 2026-08-08: parafraza d~1.01, nesuvisiaci fakt d~0.99 — PREKRYV). Preto
sa kandidati NEVYBERAJU vzdialenostou. Namiesto toho OPUS dostane cely (maly)
zoznam pamate a najde skupiny duplikatov sam (rozum, nie geometria). Pamat je
mala (desiatky-nizke stovky faktov), opus 4.8 to zvladne v 1-2 volaniach, LLM
zadarmo, nocny automat nema kontext-limit problem.

CESTA A (odsuhlasene veduckom 2026-08-08): AUTO-MERGE s navratovou stopou.
  - opus vrati skupiny duplikatov (id-cka co hovoria to iste),
  - v kazdej skupine nechaj SILNEJSI (vyssia vrstva, potom salience),
  - slabsie najprv uloz do state/dedup_trash.jsonl (recovery), az POTOM zmaz z DB,
  - vrat zoznam merge (dream ich zapise do ranneho briefu = audit).
NIC nie je irrecoverable: kazdy zmazany je vo full-meta v dedup_trash.jsonl.
Server robi soft-delete (count sa nemeni hned; recall zmazany uz nevrati).

Vstup = state/mem_index.jsonl (lokalny index, text+id+layer+salience). Solo test:
  VPY dedup_dream.py --dry-run
"""
import os
import sys
import json
import time
import subprocess

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "projects", "zolander")
STATE = os.path.join(ROOT, "state")
IDX = os.path.join(STATE, "mem_index.jsonl")
TRASH = os.path.join(STATE, "dedup_trash.jsonl")
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser("~/projects/common"))  # infra->common (reorg 2026-09)
from zol_paths import NODE, HS, NODE_ENV  # prenositelne cesty (auto-detect)
MEM_COL = "zol_mem"
sys.path.insert(0, os.path.join(HOME, "projects", "zolo2.0", "toolkit"))

LAYER_RANK = {"L3": 3, "L2": 2, "L1": 1, "L0": 0}
# ak by pamat narastla nad tento pocet, davkuj (opus prompt by bol privelky).
BATCH = int(os.environ.get("ZOL_DEDUP_BATCH", "120"))

JUDGE_SYSTEM = (
    "Si Zolander, pamatovy konsolidator. Dostanes cislovany zoznam ulozenych "
    "spomienok. Najdi skupiny ktore hovoria TO ISTE (duplikaty toho isteho "
    "faktu/preferencie/postupu, hoci inymi slovami) — take, ze staci nechat "
    "jednu a ostatne v skupine zahodit BEZ straty informacie.\n"
    "PRISNE: ak jedna obsahuje detail navyse ktory druha nema, NIE su duplikaty. "
    "Pribuzna tema NIE je duplikat. Radsej menej skupin nez zle zlucit.\n"
    'Odpovedz LEN validny JSON: {"groups": [[id,id,...], ...], "reason": {"id": "preco duplikat"}}. '
    "Ak ziadne duplikaty niet, vrat {\"groups\": []}."
)


def load_index():
    if not os.path.exists(IDX):
        return []
    rows, seen = [], set()
    for line in open(IDX, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        rid = r.get("id")
        if rid in seen or rid is None:
            continue
        seen.add(rid)
        rows.append(r)
    return rows


def _ask_opus(rows, model):
    """Da opusovi cislovany zoznam, vrati list skupin id + reason dict.
    HARD timeout: chat s max_retries=2 (nie 6) + wall-clock alarm, aby jedno
    visiace LLM volanie nezaseklo nocny dream (2026-08-08: visel 25 min na 6x300s)."""
    import signal
    from palantir_client import chat
    listing = "\n".join(f"[{r['id']}] {r.get('text', '')}" for r in rows)
    prompt = f"Spomienky:\n{listing}\n\nNajdi skupiny duplikatov."

    class _Timeout(Exception):
        pass

    def _alarm(signum, frame):
        raise _Timeout()

    old = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(int(os.environ.get("ZOL_DEDUP_LLM_TIMEOUT", "200")))
    try:
        # max_tokens 2000: davka s prekryvom vrati o nieco viac skupin nez povodnych
        # 1200 stacilo; 2000 = rezerva aby sa JSON nikdy neusekol, bez plytvania.
        resp = chat(prompt, model=model, system=JUDGE_SYSTEM,
                    max_tokens=2000, max_retries=2).strip()
    except Exception:
        return [], {}  # fail-open: LLM timeout/chyba -> tato davka NIC nezmaze
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)
    if resp.startswith("```"):
        resp = resp.split("```", 2)[1] if "```" in resp else resp
        if resp.startswith("json"):
            resp = resp[4:]
        resp = resp.strip("` \n")
    try:
        o = json.loads(resp[resp.find("{"):resp.rfind("}") + 1])
        groups = [g for g in o.get("groups", []) if isinstance(g, list) and len(g) >= 2]
        return groups, o.get("reason", {})
    except Exception:
        return [], {}  # fail-open: pri chybe parsovania NIC nezmaz


def _strength(r):
    lyr = LAYER_RANK.get(r.get("layer", "L0"), 0)
    try:
        sal = float(r.get("salience", 0) or 0)
    except Exception:
        sal = 0.0
    return (lyr, sal)


VERIFY_SYSTEM = (
    "Si prisny pamatovy audit. Dostanes dva zaznamy A (KEEPER) a B (KANDIDAT na "
    "zmazanie). Odpovedz LEN 'ANO' alebo 'NIE'.\n"
    "'ANO' = KEEPER A obsahuje VSETKY konkretne informacie z B (mena, cisla, "
    "adresy, citacie, datumy, detaily) — teda zmazat B NESPOSOBI ziadnu stratu "
    "informacie, lebo vsetko z B uz je v A.\n"
    "'NIE' = B obsahuje COKOLVEK (aj jediny detail/cislo/meno/nuansu), co v A nie je, "
    "ALEBO su to o inej veci. Pri najmensej pochybnosti odpovedz NIE.\n"
    "Len jedno slovo: ANO alebo NIE."
)


def _is_superset(keeper, cand, model):
    """Fail-closed brana: vrati True LEN ked opus potvrdi, ze keeper obsahuje VSETKO
    z kandidata (zmazanie kandidata = ziadna strata info). Akakolvek chyba/pochybnost
    -> False (rasej nezmaz nez straC fakt). Toto je poistka proti tomu, ze dedup-sudca
    zle zoskupi (2026-09-02: zmazal by bohatsi 389/494, alebo cudzi fakt 382)."""
    import signal
    from palantir_client import chat
    kt = keeper.get("text", "")
    ct = cand.get("text", "")
    if not kt or not ct:
        return False
    # trivialne bezpecne: keeper doslovne obsahuje cely text kandidata
    if ct.strip() and ct.strip() in kt:
        return True
    prompt = (f"A (KEEPER):\n{kt}\n\nB (KANDIDAT na zmazanie):\n{ct}\n\n"
              "Obsahuje A vsetky informacie z B? ANO alebo NIE:")

    class _T(Exception):
        pass

    def _al(s, f):
        raise _T()

    old = signal.signal(signal.SIGALRM, _al)
    signal.alarm(int(os.environ.get("ZOL_DEDUP_VERIFY_TIMEOUT", "60")))
    try:
        r = chat(prompt, model=model, system=VERIFY_SYSTEM,
                 max_tokens=8, max_retries=2).strip().upper()
    except Exception:
        return False  # fail-CLOSED: chyba verifikacie -> nezmaz
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)
    return r.startswith("ANO")


def _del_point(pid):
    # FIX (2026-08-30): mazat z Lorentz zol_mem AJ z zol_mem_gemma. Predtym len
    # Lorentz -> kazdy dream merge nechal ZOMBIE (mrtvy v Lorentz, zivy v Gemma,
    # BM25/Gemma ho stale serviroval). Lorentz je autorita: ked ten padne, Gemmu
    # neriesime (zaznam ostava, skusi sa nabuduce). Gemma del je fail-soft.
    try:
        p = subprocess.run([NODE, HS, "del", MEM_COL, str(pid)],
                           capture_output=True, text=True, env=NODE_ENV, timeout=30)
        lor_ok = p.returncode == 0 and '"deleted":true' in p.stdout
    except subprocess.TimeoutExpired:
        return False  # visiaci gRPC del nezhodi cely beh; zaznam ostane (dram nabuduce)
    if lor_ok:
        try:
            subprocess.run([NODE, HS, "del", "zol_mem_gemma", str(pid)],
                           capture_output=True, text=True, env=NODE_ENV, timeout=30)
        except subprocess.TimeoutExpired:
            pass  # Gemma zombie < strata; reconcile_guard ho nabuduce chyti
    return lor_ok


def _trash(r, reason, kept_id):
    os.makedirs(STATE, exist_ok=True)
    with open(TRASH, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "removed": r, "reason": reason, "merged_into": kept_id},
                           ensure_ascii=False) + "\n")


def dedup(model="opus", dry_run=False, log_fn=None):
    import time as _t
    def _log(m):
        (log_fn or (lambda x: None))(f"dedup: {m}")

    deadline = _t.time() + int(os.environ.get("ZOL_DEDUP_MAX_SEC", "600"))
    rows = load_index()
    if len(rows) < 2:
        return {"merges": [], "blocked": []}
    byid = {r["id"]: r for r in rows}

    # PREKRYVAJUCE DAVKY (empiricky zvoleny default 2026-09-02): davky s prekryvom,
    # aby duplikat na hranici padol do aspon jednej davky CELY. Dedup cez removed set
    # nizsie znesie, ze sa par objavi vo viacerych davkach.
    #
    # PRECO NIE single-pass (cely zoznam naraz): OTESTOVANE na 597 faktoch — cely
    # zoznam naraz nasiel 0 skupin, prekryvajuce davky 5. Velky kontext = opus spravi
    # PLYTKY prechod (lenivie). Mensia davka ho donuti citat pozorne. Skutocna chyba
    # povodneho kodu nebolo davkovanie ale CHYBAJUCI PREKRYV (hranica davky = slepa skvrna).
    all_groups, reasons = [], {}
    overlap = max(1, BATCH // 4)
    step = BATCH - overlap
    for i in range(0, len(rows), step):
        if _t.time() > deadline:
            _log("wall-clock strop pri opus davkach — koncim skenovanie")
            break
        chunk = rows[i:i + BATCH]
        g, rs = _ask_opus(chunk, model)
        all_groups.extend(g)
        reasons.update(rs)
        _log(f"davka @{i} (batch {BATCH}, overlap {overlap}): {len(chunk)} spomienok -> {len(g)} skupin")
        if i + BATCH >= len(rows):
            break

    removed = set()
    merges = []
    blocked = []
    for group in all_groups:
        if _t.time() > deadline:
            _log("wall-clock strop pri mazani — koncim (zvysok nabuduce)")
            break
        members = [byid[g] for g in group if g in byid and g not in removed]
        if len(members) < 2:
            continue
        # KEEPER = najBOHATSI (najdlhsi text), pri zhode vyssia vrstva/salience.
        # PRECO NIE salience: 2026-09-02 salience-vyber zmazal by bohatsi 389/494 a
        # nechal chudobnejsi. Bohatsi zaznam skoro vzdy = superset -> bezpecne nechat.
        keeper = max(members, key=lambda r: (len(r.get("text", "")), _strength(r)))
        kid = keeper["id"]
        for m in members:
            if m["id"] == kid:
                continue
            reason = reasons.get(str(m["id"])) or reasons.get(m["id"]) or "duplikat"
            merge = {"kept": kid, "removed": m["id"],
                     "removed_text": m.get("text", "")[:90], "reason": reason}
            # FAIL-CLOSED SUPERSET BRANA: zmaz LEN ked keeper dokazatelne obsahuje
            # VSETKO z kandidata. Chrani pred zlym zoskupenim sudcu (cudzi fakt /
            # bohatsi kandidat). Chyba/pochybnost/timeout -> nezmaz.
            if not _is_superset(keeper, m, model):
                _log(f"SUPERSET NIE {m['id']} !<= {kid} — NEmazem (chranim info) ({reason})")
                blocked.append({"kept": kid, "blocked": m["id"],
                                "blocked_text": m.get("text", "")[:90], "reason": reason})
                continue
            if dry_run:
                merges.append({**merge, "dry_run": True, "superset_ok": True})
                _log(f"[dry] dup {m['id']}->{kid} superset_ok ({reason})")
                continue
            # del PRV, trash az po uspesnom zmazani (inak by trash mal zaznam co
            # v DB ostal = false recovery). Poradie: over zmazanie -> potom stopa.
            if _del_point(m["id"]):
                # NAJPRV presmeruj hrany zmazaneho na keepera (deti NEOSIRIA),
                # az POTOM trash. reparent je fail-open: chyba grafu nezhodi merge.
                try:
                    import zol_graph
                    rp = zol_graph.reparent(m["id"], kid)
                    _log(f"reparent {m['id']}->{kid}: migrated={rp['migrated']} "
                         f"selfloop={rp['dropped_selfloop']} dup={rp['dropped_dup']}")
                    merge["reparent"] = rp
                except Exception as e:
                    _log(f"reparent {m['id']}->{kid} ZLYHAL (hrany ostali): {e!r}")
                _trash(m, reason, kid)
                removed.add(m["id"])
                merges.append(merge)
                _log(f"merge {m['id']}->{kid} ({reason})")
            else:
                _log(f"del zlyhal/timeout pre {m['id']} (DB nedotknuta, skusi sa nabuduce)")

    # zosynchronizuj lokalny index: vyhod zmazane (inak dream posle opusovi ducha)
    if removed and not dry_run:
        try:
            kept = [r for r in rows if r["id"] not in removed]
            with open(IDX, "w", encoding="utf-8") as f:
                for r in kept:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        except Exception as e:
            _log(f"index sync zlyhal: {e!r}")
    _log(f"HOTOVO: zlucene={len(merges)} zablokovane_branou={len(blocked)}")
    return {"merges": merges, "blocked": blocked}


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    res = dedup(model=os.environ.get("DREAM_MODEL", "opus"),
                dry_run=dry, log_fn=lambda m: print(m, file=sys.stderr))
    print(json.dumps({"merges": res["merges"], "count": len(res["merges"]),
                      "blocked": res["blocked"], "blocked_count": len(res["blocked"]),
                      "dry_run": dry},
                     ensure_ascii=False, indent=2))
