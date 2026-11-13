#!/usr/bin/env python3
"""initiative.py — INICIATIVNY TIK Zolandera (zarodok "iniciativy": loop co sam
prehliadne pamat + stav projektov a rozhodne ci je nieco hodne akcie).

NAVRH odsuhlaseny veduckom 2026-08-08:
  - frekvencia: kazdych 30 min (2x/hod) cez launchd StartInterval (--once tik).
  - kanal: WhatsApp (hermes send) pre triedu 2 (navrh veduckovi).
  - autonomia: trieda 1 (ticha priprava) ZAPNUTA, ale s BEZPECNYM rozbehom =
    default DRY-RUN kym nie je ZOL_INIT_LIVE=1 (najprv sleduj AKO rozhoduje).

TRI TRIEDY AKCIE (klesajuca autonomia):
  1 TICHA PRIPRAVA — v git-projekte (zolo2.0/turiec-pod-lupou) na vetve
    zolander/auto zanechaj pripravenu pracu ako poznamku .zolander/initiative_*.md.
    NIKDY main, NIKDY push, NIKDY mimo allowlistu, NIKDY mazanie. (pravidlo __USER__)
  2 NAVRH VEDUCKOVI — hermes send --to whatsapp "vsimol som si X, navrhujem Y".
  3 NIC — ticho spi.

POISTKY:
  - DRY-RUN default (ZOL_INIT_LIVE nenastavene) — loguje, NEkona, NEposiela.
  - KILL SWITCH: subor state/INITIATIVE_OFF -> tik nic nerobi.
  - RATE: max 1 WhatsApp za RATE_HOURS (default 6h), ledger state/initiative_ledger.jsonl.
  - DEDUP: hash akcie v ledgeri; tu istu akciu nenavrhne 2x.
  - SANDBOX: trieda 1 len v ALLOWED_PROJECTS, len vetva zolander/auto, git guard.
  - AUDIT: kazdy tik -> logs/initiative.log (co videl + rozhodol).
  - LLM hard timeout (alarm) + fail-open (chyba => trieda 3, nic).

Pouzitie:
  /usr/bin/python3 initiative.py --once            # jeden tik (dry-run ak nie LIVE)
  ZOL_INIT_LIVE=1 /usr/bin/python3 initiative.py --once   # ostry tik
"""
import os
import sys
import json
import time
import hashlib
import subprocess

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "projects", "zolander")
STATE = os.path.join(ROOT, "state")
LOGS = os.path.join(ROOT, "logs")
LOG = os.path.join(LOGS, "initiative.log")
LEDGER = os.path.join(STATE, "initiative_ledger.jsonl")
KILL = os.path.join(STATE, "INITIATIVE_OFF")
PLAN = os.path.join(HOME, "projects", "refactor", "PAMAT_REFACTOR_PLAN.md")
INBOX = os.path.join(ROOT, "inbox.md")
DENNIKY = os.path.join(ROOT, "denniky")
VPY = os.path.join(ROOT, ".venv-yar", "bin", "python")
ZOL_MEM = os.path.join(ROOT, "toolkit", "zol_mem.py")
GIT = "/usr/bin/git"
HERMES = os.path.join(HOME, ".local", "bin", "hermes")  # over cestu; fallback nizsie

sys.path.insert(0, os.path.join(HOME, "projects", "zolo2.0", "toolkit"))
sys.path.insert(0, os.path.expanduser("~/projects/common"))  # infra->common (reorg 2026-09)
sys.path.insert(0, os.path.join(ROOT, "toolkit"))
try:
    from zol_events import emit, new_run
except Exception:  # event log je diagnostika, nesmie zhodit tik
    def emit(*a, **k): pass
    def new_run(s): return "adhoc"
try:
    from zol_eval import evaluate as _eval
except Exception:  # eval gate je nadstavba, nesmie zhodit tik
    _eval = None

# Rubrika pre HODNOTENIE NÁVRHU (iná než pre odpovede): je návrh hodný vyrušenia?
PROPOSAL_EVAL_SYSTEM = """Si prísny filter iniciatívnych návrhov AI asistenta. Dostaneš
ZADANIE (kontext) a ODPOVEĎ (navrhovanú akciu). Otázka: OPLATÍ sa tým vyrušiť užívateľa?
Ohodnoť 0.0-1.0:
- konkretnost: je akcia konkrétna a vykonateľná (nie vágna "mal by si pouvažovať")
- hodnota: reálne posunie prácu / rieši otvorený problém (nie busy-work)
- nacasovanie: je to relevantné TERAZ (nie niečo čo počká)
- nespam: NEotravuje trivialitou (prísne — pri pochybnosti nízko)
Vráť LEN validný JSON:
{"konkretnost":0.0,"hodnota":0.0,"nacasovanie":0.0,"nespam":0.0,"celkom":0.0,"dovod":"1 veta"}"""
# prah pod ktorý sa návrh NEPOŠLE (radšej ticho než spam). Konfigurovateľné.
PROPOSAL_GATE = float(os.environ.get("ZOL_INIT_GATE", "0.6"))

LIVE = os.environ.get("ZOL_INIT_LIVE", "") == "1"
MODEL = os.environ.get("ZOL_INIT_MODEL", "opus")
# max WhatsApp navrhov za hodinu (__USER__: "max 2x do hodiny")
RATE_PER_HOUR = int(os.environ.get("ZOL_INIT_RATE_PER_HOUR", "2"))
LLM_TIMEOUT = int(os.environ.get("ZOL_INIT_LLM_TIMEOUT", "180"))
# BUDUCA plna autonomia: ked bude ZOL_INIT_AUTO=1, nizko-rizikove navrhy vykona
# rovno gateway-side (zatial OFF — vsetko cez approval "zrob N").
AUTO = os.environ.get("ZOL_INIT_AUTO", "") == "1"
PENDING = os.path.join(STATE, "initiative_pending.jsonl")
# DEDUP AUTO-EXPIRE: pending navrh na ktory veducko N dni nereagoval prestane
# blokovat nove navrhy (inak jeden nevybaveny navrh umlci cely projekt navzdy —
# realny incident: pid=12/pid=15 udusili iniciativu 24 dni). Fail-open: ak ts
# nedaparsujem, navrh povazujem za CERSTVY (radsej blokuj duplikat nez spamuj).
PENDING_EXPIRE_DAYS = int(os.environ.get("ZOL_INIT_PENDING_EXPIRE_DAYS", "14"))
# projekty ktore smie upravovat (cez approval "zrob N" cez gateway). Uz aj MAIN
# (__USER__ schvalil: ked to approvujem, moze upravovat main). Push VZDY zvlast approve.
ALLOWED_PROJECTS = {
    "zolo2.0": os.path.join(HOME, "projects", "zolo2.0"),
    "turiec-pod-lupou": os.path.join(HOME, "projects", "turiec-pod-lupou"),
}

DECIDE_SYSTEM = """Si Zolander — perzistentny AI partak/mentor pre pouzivatela 'veducko' (__USER__).
Toto je INICIATIVNY TIK: sam si sa zobudil (nikto ta nevolal) a mas rozhodnut, ci
mas TERAZ veduckovi navrhnut konkretnu akciu. Dostanes vytah z pamate, plan, git, inbox.

Bud PRISNY: vacsinou spravna odpoved je NIC (propose=false) — neotravuj. Navrhni LEN ked
vidis nieco naozaj konkretne a hodnotne: nedotiahnuty krok, otvoreny slub, jasny dalsi
krok co posunie veduckovu pracu, alebo uprava v projekte (zolo2.0 / turiec-pod-lupou).

TELEOLOGIA (PLAN §16): sekcia 'GRADIENT (STAV -> CIEĽ)' je tvoj SMER — vypocitany z disku,
ukotveny cielom co definoval veducko (goal.json), NIE nekonecny target. NAJVACSIA zlozka
gradientu = kam sa opriet najprv. Ak navrhujes, prednostne navrhni krok co ZNIZI najvacsiu
zlozku gradientu (dotiahne nedokoncene, znizi real-outcome dlh). Berieš JEDNU zlozku za tik,
nie vsetky naraz — ohranicene.
HONESTY (F11 runtime): sekcia 'HONESTY AUDIT' hlasi nezrovnalosti tvrdenie-vs-disk (dead_ref,
tvrdi commit ale git dirty). Ak audit nieco hlasi k tvojmu navrhu, NEIGNORUJ to — bud to
zohladni (napr. najprv over/oprav dead_ref), alebo to rovno navrhni opravit. NIKDY netvrd
progres co audit na disku nenajde.

Sekcia 'CO SEN ZOSYNTETIZOVAL' je tvoja NOCNA KONSOLIDACIA — nove abstrakty a husto
prepojene temy, ktore pamat sama vytiahla (ako ked cloveku cez noc nieco docvakne).
Ber ju ako zdroj napadu: ak z novej temy/abstraktu plynie konkretny dalsi krok, navrhni
ho. Ale stale plati prisnost — cerstva tema NIE JE dovod na navrh sama o sebe, len ak z
nej plynie nieco vykonatelne a hodnotne TERAZ.

NEKONAS teraz nic — len NAVRHUJES. Vykona to az veducko ked odpovie 'zrob N'.

Vrat LEN validny JSON:
{"propose": true|false, "title": "kratky nazov navrhu", "action": "co presne by si spravil, konkretne kroky", "reason": "preco teraz", "project": "zolo2.0|turiec-pod-lupou|null", "touches_main": true|false, "risk": "low|med|high"}

Ak nic hodne niet: {"propose": false}."""


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    try:
        os.makedirs(LOGS, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{now()} | {'LIVE' if LIVE else 'DRY'} | {msg}\n")
    except Exception:
        pass


def _tail(path, n):
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return ""


def recall_mem(query, topk=6):
    try:
        p = subprocess.run([VPY, ZOL_MEM, "recall"],
                           input=json.dumps({"query": query, "topk": topk, "source": "initiative"}),
                           capture_output=True, text=True, timeout=120)
        out = p.stdout
        i = out.find("[")
        hits = json.loads(out[i:]) if i >= 0 else []
        return "\n".join(f"- {h.get('meta', {}).get('text', '')[:140]}" for h in hits)
    except Exception:
        return ""


def git_status(path):
    try:
        b = subprocess.run([GIT, "-C", path, "branch", "--show-current"],
                           capture_output=True, text=True, timeout=30).stdout.strip()
        st = subprocess.run([GIT, "-C", path, "status", "--porcelain"],
                            capture_output=True, text=True, timeout=30).stdout.strip()
        n = len([l for l in st.splitlines() if l.strip()])
        return f"vetva={b}, zmenenych suborov={n}"
    except Exception:
        return "git nedostupny"


def fresh_abstractions(max_items=6, days=3):
    """D — CO SEN ZOSYNTETIZOVAL: cerstve abstrakty (L1/L2/L3) + husto prepojene
    temy z grafu. Toto je jadro napadu 'ako clovek co cez noc docvakne': iniciativa
    nerozhoduje z naho scrapu, ale z toho, co pamat SAMA nedavno abstrahovala.
    Cita mem_index.jsonl (lokalne, bez DB/LLM) + zol_graph.communities. Fail-open."""
    parts = []
    idx = os.path.join(STATE, "mem_index.jsonl")
    try:
        rows = [json.loads(l) for l in open(idx, encoding="utf-8") if l.strip()]
    except Exception:
        rows = []
    cutoff = time.time() - days * 86400
    def _fresh(r):
        try:
            return time.mktime(time.strptime(r.get("ts", "")[:19], "%Y-%m-%dT%H:%M:%S")) > cutoff
        except Exception:
            return False
    absts = [r for r in rows if r.get("layer") in ("L1", "L2", "L3") and _fresh(r)]
    absts.sort(key=lambda r: r.get("ts", ""), reverse=True)
    if absts:
        lines = [f"- [{r.get('layer')}] {r.get('text', '')[:160]}" for r in absts[:max_items]]
        parts.append("nove abstrakty (sen ich vydestiloval z epizod/tem):\n" + "\n".join(lines))
    # husto prepojene temy z grafu (vznikajuce oblasti zaujmu)
    try:
        import zol_graph
        by_id = {r["id"]: r for r in rows}
        comms = zol_graph.communities(min_size=3, edge="related")
        # len temy BEZ strechy (has_parent < members) = este nedotiahnute na abstrakt
        open_comms = [c for c in comms if len(c.get("has_parent", [])) < len(c["members"])]
        if open_comms:
            cl = []
            for c in open_comms[:3]:
                sample = "; ".join((by_id.get(m, {}).get("text", "?"))[:60]
                                   for m in c["members"][:3])
                cl.append(f"- tema ({len(c['members'])} spomienok, density {c['density']}): {sample}")
            parts.append("\nhusto prepojene temy bez strechy (mozny dalsi krok):\n" + "\n".join(cl))
    except Exception:
        pass
    return "\n".join(parts) if parts else "(sen zatial nic nove nezosyntetizoval)"


def edge_health():
    """SEBAAUDIT parent-hran (root-cause slucka): Zolander si SAM prezrie geometriu
    pamate a ak najde hranu co je preukazatelne naopak (reverse) alebo NOVU inverziu
    oproti minulemu tiku, prida ju do kontextu ako podnet na navrh. TICHO ked cisto/
    nezmenene — znamy zvysok (surodenci/need_llm) NEspamuje. Fail-open: chyba = "".
    Cita r_opus + layer LOKALNE (ziadny LLM/DB), takze je lacne na kazdy tik."""
    try:
        import edge_selfaudit
        res = edge_selfaudit.audit(write=True)
    except Exception as e:
        log(f"edge_health: sebaaudit zlyhal (fail-open): {e!r}")
        return ""
    res.pop("_rows", None)
    proposals = res.get("proposals", [])
    reverses = [p for p in proposals if p.get("verdict") == "reverse"]
    inverted = res.get("counts", {}).get("INVERTED", 0)
    need_llm = res.get("need_llm", [])
    # watermark: porovnaj s minulym tikom (state/edge_selfaudit_seen.json) — ozvi sa
    # LEN ked pribudol reverse alebo stupla INVERTED (nova spina, nie znamy zvysok).
    seen_path = os.path.join(STATE, "edge_selfaudit_seen.json")
    prev = {}
    try:
        prev = json.load(open(seen_path, encoding="utf-8"))
    except Exception:
        prev = {}
    prev_inv = prev.get("inverted", -1)
    prev_rev = prev.get("reverses", -1)
    cur = {"inverted": inverted, "reverses": len(reverses),
           "need_llm": len(need_llm), "ts": now()}
    try:
        json.dump(cur, open(seen_path, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass
    # nic naliehave a nic sa nezmenilo -> ticho
    if not reverses and inverted <= max(prev_inv, 0) and len(reverses) <= max(prev_rev, 0):
        return ""
    lines = []
    if reverses:
        lines.append(f"pamat ma {len(reverses)} parent hran co su GEOMETRICKY NAOPAK "
                     "(dieta abstraktnejsie nez rodic) — kandidat na otocenie:")
        for p in reverses[:4]:
            lines.append(f"  - #{p['child']} '{p.get('child_txt','')[:45]}' -> "
                         f"#{p['parent']} '{p.get('parent_txt','')[:45]}' "
                         f"(delta_r={p.get('delta_r_child_minus_parent')})")
    if need_llm:
        lines.append(f"+ {len(need_llm)} hran ma KONFLIKT layer vs geometria "
                     "(treba 3-lab arbiter: edge_phase3_epistemic_3lab.py).")
    if not lines:
        return ""
    return ("SEBAAUDIT GRAFU (Zolander si sam vsimol nezrovnalost v hierarchii pamate):\n"
            + "\n".join(lines)
            + "\n(oprava: toolkit/edge_selfaudit.py + prislusny apply skript)")


def gradient_context():
    """GOAL loop: gradient STAV->CIEĽ (zol_goal.py) + HONESTY audit (zol_honesty.py).
    Toto je teleologické jadro (PLAN §16): dá tiku SMER (kam sa oprieť) + kontrolu
    (čo z toho je fabrikované/dead). Obe sú stdlib, /usr/bin/python3, fail-open —
    chyba/timeout => prázdny reťazec, tik beží ďalej ako predtým (nesmie ho zhodiť)."""
    TK = os.path.join(ROOT, "toolkit")
    out = []
    for label, script in (("GRADIENT (STAV -> CIEĽ)", "zol_goal.py"),
                          ("HONESTY AUDIT (tvrdenie -> disk)", "zol_honesty.py")):
        try:
            p = subprocess.run(["/usr/bin/python3", os.path.join(TK, script)],
                               capture_output=True, text=True, timeout=90)
            if p.returncode == 0 and p.stdout.strip():
                out.append(f"\n== {label} ==\n" + p.stdout.strip())
        except Exception as e:
            log(f"gradient_context: {script} zlyhal (fail-open): {e!r}")
    return "\n".join(out)


def gather():
    """Poskladaj vstup pre rozhodnutie."""
    parts = []
    # GOAL+HONESTY loop: teleologický gradient je PRVÝ (najdôležitejší signál — kam sa
    # oprieť). Prázdny reťazec ked zlyhá -> tik beží ako predtým (fail-open).
    gc = gradient_context()
    if gc:
        parts.append(gc)
    parts.append("\n== PAMAT (nedotiahnute/priority) ==\n" +
                 recall_mem("nedokoncene otvorene sluby dalsi krok priorita rozrobene"))
    parts.append("\n== CO SEN ZOSYNTETIZOVAL (nove abstrakty + vznikajuce temy) ==\n" +
                 fresh_abstractions())
    # SEBAAUDIT GRAFU: Zolander si sam prezrie geometriu parent-hran (root-cause slucka).
    # Prazdny retazec ked je graf cisty/nezmeneny -> ziadny sum v kontexte.
    eh = edge_health()
    if eh:
        parts.append("\n== SEBAAUDIT GRAFU (nezrovnalost v hierarchii pamate) ==\n" + eh)
    parts.append("\n== PLAN (chvost) ==\n" + _tail(PLAN, 25))
    parts.append("\n== INBOX (chvost) ==\n" + _tail(INBOX, 12))
    # dnesny brief
    day = time.strftime("%Y-%m-%d")
    parts.append("\n== RANNY BRIEF ==\n" + _tail(os.path.join(DENNIKY, f"brief_{day}.md"), 20))
    gs = []
    for name, path in ALLOWED_PROJECTS.items():
        if os.path.isdir(path):
            gs.append(f"{name}: {git_status(path)}")
    parts.append("\n== GIT PROJEKTY ==\n" + "\n".join(gs))
    return "\n".join(parts)


def decide(context):
    """OPUS rozhodne ci navrhnut. Fail-open: chyba/timeout => propose=false."""
    import signal
    from llm_client import chat

    class _T(Exception):
        pass

    def _a(s, f):
        raise _T()

    old = signal.signal(signal.SIGALRM, _a)
    signal.alarm(LLM_TIMEOUT)
    try:
        resp = chat(context, model=MODEL, system=DECIDE_SYSTEM,
                    max_tokens=700, max_retries=2).strip()
    except Exception as e:
        log(f"decide LLM chyba/timeout (fail-open -> propose=false): {e!r}")
        return {"propose": False}
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
        o.setdefault("propose", False)
        return o
    except Exception as e:
        log(f"decide parse chyba (fail-open -> propose=false): {e!r} | raw={resp[:150]}")
        return {"propose": False}


def _ledger_load():
    if not os.path.exists(LEDGER):
        return []
    try:
        return [json.loads(l) for l in open(LEDGER, encoding="utf-8") if l.strip()]
    except Exception:
        return []


def _ledger_add(rec):
    try:
        os.makedirs(STATE, exist_ok=True)
        with open(LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _seen_recently(ahash):
    for r in _ledger_load():
        if r.get("hash") == ahash:
            return True  # tu istu akciu uz sme robili -> dedup
    return False


_STOP = {"a", "az", "do", "na", "pre", "pred", "po", "z", "zo", "s", "so", "v", "vo",
         "ci", "ich", "co", "ako", "aby", "ale", "uz", "je", "su", "byt", "3", "tri",
         "uloha", "ulohy", "uloh", "navrh", "navrhu", "the", "and", "of"}


def _norm_tokens(text):
    """Normalizuj titulok na mnozinu vyznamovych tokenov (lower, bez diakritiky/cislic/
    interpunkcie, bez stopwords). Odolne voci Opus preformulaciam ('Vycistit 3 dead_ref
    ulohy pred konsolidaciou' vs '... z honesty auditu' -> rovnake jadro)."""
    import unicodedata
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    tok = []
    for w in "".join(c if c.isalnum() else " " for c in t).split():
        if len(w) >= 3 and w not in _STOP and not w.isdigit():
            tok.append(w)
    return set(tok)


def _pending_is_active(rec):
    """Je tento pending zaznam ESTE aktivny (blokuje dedup)? Aktivny = status
    'pending' A ZAROVEN nie je starsi nez PENDING_EXPIRE_DAYS. Starsie navrhy na
    ktore veducko nereagoval prestanu blokovat — inak deadlock (jeden nevybaveny
    navrh umlci projekt navzdy). Fail-open: neparsovatelny ts -> povazuj za cerstvy."""
    if rec.get("status", "pending") != "pending":
        return False
    ts = rec.get("ts", "")
    try:
        t = time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
    except Exception:
        return True  # ts sa neda precitat -> radsej blokuj (nespamuj)
    return (time.time() - t) < PENDING_EXPIRE_DAYS * 86400


def _title_dup_in_pending(title):
    """Existuje OTVORENY (status=pending) navrh s podobnym titulkom? Prekryv jadra
    (overlap koeficient = prienik / mensia mnozina tokenov) >= prah A ZAROVEN aspon 2
    spolocne vyznamove tokeny = ten isty nedotiahnuty stav pod inymi slovami.
    Overlap (nie Jaccard) preto, ze Opus meni DLZKU titulku ('Vycistit 3 dead_ref ulohy
    pred konsolidaciou' vs 'Prejst dead_ref nalezy a opravit aktivne ulohy') — Jaccard
    trestal roznu dlzku a duplikat prepustil. min_inter>=2 branka drzi nesuvisiace
    (1-token nahoda) mimo. Fail-open (chyba -> False, radsej poslat nez umlcat)."""
    keyset = _norm_tokens(title)
    if not keyset or not os.path.exists(PENDING):
        return False
    thr = float(os.environ.get("ZOL_INIT_DEDUP_OVERLAP", "0.5"))
    try:
        for l in open(PENDING, encoding="utf-8"):
            l = l.strip()
            if not l:
                continue
            r = json.loads(l)
            if not _pending_is_active(r):
                continue
            other = _norm_tokens(r.get("title", ""))
            if not other:
                continue
            inter = len(keyset & other)
            smaller = min(len(keyset), len(other))
            if smaller and inter >= 2 and inter / smaller >= thr:
                return True
    except Exception:
        pass
    return False


def _pending_open_for(project, title, ahash):
    """SEMANTICKY dedup: uz existuje NEVYBAVENY (status=pending) navrh pre to iste?
    - Ak projekt je: rovnaky projekt + otvorenost = ten isty nedotiahnuty stav.
    - Ak projekt nie je (None): Opus meni presne slova AJ action text, takze textovy
      hash zlyha (preto sme mali 10 kopii dead_ref navrhu). Dedupuj na PODOBNOST TITULKU
      (Jaccard normalizovanych tokenov) oproti otvorenym pending navrhom; fallback na
      presny textovy hash cez _seen_recently."""
    if not project:
        return _title_dup_in_pending(title) or _seen_recently(ahash)
    if not os.path.exists(PENDING):
        return False
    try:
        for l in open(PENDING, encoding="utf-8"):
            l = l.strip()
            if not l:
                continue
            r = json.loads(l)
            if r.get("project") == project and _pending_is_active(r):
                return True
    except Exception:
        pass
    return False


def _whatsapp_rate_ok():
    """max RATE_PER_HOUR navrhov za poslednu hodinu (__USER__: max 2x/hod)."""
    cutoff = time.time() - 3600
    n = 0
    for r in _ledger_load():
        if not r.get("sent"):
            continue
        try:
            t = time.mktime(time.strptime(r.get("ts", ""), "%Y-%m-%d %H:%M:%S"))
        except Exception:
            continue
        if t > cutoff:
            n += 1
    return n < RATE_PER_HOUR


def _find_hermes():
    for c in (HERMES, "/opt/homebrew/bin/hermes",
              os.path.join(HOME, "Applications/homebrew/bin/hermes")):
        if os.path.exists(c):
            return c
    return "hermes"  # PATH fallback


def _next_pid():
    """Poradove cislo navrhu (rastie cez ledger)."""
    mx = 0
    for r in _ledger_load():
        try:
            mx = max(mx, int(r.get("pid", 0)))
        except Exception:
            pass
    return mx + 1


def _pending_add(rec):
    try:
        os.makedirs(STATE, exist_ok=True)
        with open(PENDING, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        log(f"pending zapis zlyhal: {e!r}")


def _send_whatsapp(text):
    if not LIVE:
        log(f"[DRY] WhatsApp by poslal:\n{text[:300]}")
        return True
    # RETRY: rc=1/timeout su casto transientne (bridge sa prave restartoval, `hermes
    # send --list` presiahol timeout). 3 pokusy s backoffom skrotia krehkost kanala.
    attempts = int(os.environ.get("ZOL_INIT_PUSH_RETRIES", "3"))
    last = ""
    for i in range(1, attempts + 1):
        try:
            r = subprocess.run([_find_hermes(), "send", "--to", "whatsapp", text],
                               capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                log(f"WhatsApp ODOSLANE{' (pokus ' + str(i) + ')' if i > 1 else ''}")
                return True
            last = (r.stderr or "").strip()[-120:]
            log(f"WhatsApp ZLYHALO pokus {i}/{attempts} rc={r.returncode} | {last}")
        except Exception as e:
            last = repr(e)
            log(f"WhatsApp CHYBA pokus {i}/{attempts}: {last}")
        if i < attempts:
            time.sleep(3 * i)  # 3s, 6s backoff
    log(f"WhatsApp VZDAVAM po {attempts} pokusoch | {last}")
    return False


def tick():
    rid = new_run("initiative")
    if os.path.exists(KILL):
        log("KILL SWITCH (INITIATIVE_OFF) — tik preskoceny")
        emit("initiative", "kill_switch", {}, rid)
        return 0
    ctx = gather()
    d = decide(ctx)
    emit("initiative", "decision", {"propose": d.get("propose"), "title": d.get("title"),
         "project": d.get("project"), "risk": d.get("risk"),
         "reason": str(d.get("reason", ""))[:400], "live": LIVE}, rid)
    if not d.get("propose"):
        log("rozhodnutie: NIC (propose=false)")
        return 0

    action = str(d.get("action", "")).strip()
    title = str(d.get("title", "")).strip() or action[:50]
    proj = d.get("project") if d.get("project") in ALLOWED_PROJECTS else None
    ahash = hashlib.sha1((action + str(proj)).encode("utf-8", "replace")).hexdigest()[:16]
    log(f"NAVRH: '{title}' proj={proj} main={d.get('touches_main')} risk={d.get('risk')} :: "
        f"{action[:100]} | preco: {str(d.get('reason', ''))[:90]}")

    if not action:
        return 0
    if _pending_open_for(proj, title, ahash):
        log(f"DEDUP: uz existuje otvoreny navrh pre '{proj or ahash}' — nespamovat")
        emit("initiative", "dedup_skip", {"project": proj, "title": title}, rid)
        return 0
    if not _whatsapp_rate_ok():
        log(f"RATE ({RATE_PER_HOUR}/hod) — navrh '{title}' odlozeny (nezahltit veducka)")
        emit("initiative", "rate_skip", {"title": title, "limit": RATE_PER_HOUR}, rid)
        return 0

    # CROSS-MODEL EVAL GATE (zol_eval): opus navrh -> gpt+gemini ohodnotia "oplati sa
    # vyrusit?". Pod prahom NEPOSIELAJ (radsej ticho nez spam = pravidlo "neotravuj").
    # Fail-open: ak eval nedostupny/zlyha (None), navrh PREJDE (eval bug neumlci iniciativu).
    if _eval is not None:
        try:
            ev = _eval(ctx, f"{title}\n{action}\nPreco: {d.get('reason','')}", MODEL,
                       eval_system=PROPOSAL_EVAL_SYSTEM)
            gate = ev.get("celkom")
            emit("initiative", "eval_gate", {"title": title, "score": gate,
                 "threshold": PROPOSAL_GATE, "judges": ev.get("per_judge")}, rid)
            if gate is not None and gate < PROPOSAL_GATE:
                log(f"EVAL GATE: navrh '{title}' skore {gate:.2f} < {PROPOSAL_GATE} — "
                    f"NEPOSLANY (nespamovat). Judges: {ev.get('judges')}")
                return 0
            log(f"EVAL GATE: navrh '{title}' skore {gate} >= {PROPOSAL_GATE} — prechadza")
        except Exception as e:
            log(f"eval gate zlyhal (fail-open, navrh prejde): {e!r}")

    pid = _next_pid()
    # zapis do pending fronty — odtial to vezme zivy Zolander na gatewayi ked
    # veducko odpise "zrob N". Daemon SAM NEKONA (oddeleny proces).
    _pending_add({"pid": pid, "ts": now(), "title": title, "action": action,
                  "reason": d.get("reason", ""), "project": proj,
                  "touches_main": bool(d.get("touches_main")),
                  "risk": d.get("risk", "med"), "status": "pending"})

    proj_s = f" [{proj}]" if proj else ""
    msg = (f"🔧 Návrh #{pid}{proj_s}: {title}\n\n"
           f"{action}\n\n"
           f"Prečo: {d.get('reason', '')}\n\n"
           f"(Zatiaľ sa len testujem, nič som neurobil. Ak chceš, napíš 'zrob {pid}' "
           f"a spravím to. Push spravím až na samostatné 'pushni {pid}'.)")
    sent = _send_whatsapp(msg)

    _ledger_add({"ts": now(), "pid": pid, "hash": ahash, "title": title,
                 "action": action[:200], "project": proj,
                 "touches_main": bool(d.get("touches_main")),
                 "sent": sent, "live": LIVE})
    emit("initiative", "proposed", {"pid": pid, "title": title, "project": proj,
         "risk": d.get("risk", "med"), "sent": sent, "live": LIVE}, rid)
    return 0


def main():
    if "--once" in sys.argv:
        return tick()
    # --daemon rezim nateraz nepouzivame: launchd StartInterval vola --once.
    log("spustene bez --once; pouzi --once (launchd StartInterval vola tik)")
    return tick()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"INITIATIVE EXCEPTION (fail-open): {e!r}")
        sys.exit(0)  # nikdy nezhod tak aby launchd hlasil chybu spam
