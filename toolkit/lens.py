#!/usr/bin/env python3
"""lens.py — F10 dvojity pohlad + self-check konvergencie.

Dva rezimy:

1) lift  — pred vaznou odpovedou: pomenuj UROVEN abstrakcie problemu, vystup
   o jednu vyssie (X -> instancia coho Y -> meta-otazka Z), a P5 zostup spat
   ku konkretnej akcii. Vyuziva gpt/opus cez palantir_client. Vystup je
   struktura {level, up, meta, down_action} + prirodzena veta.

2) stability — Lyapunov-style self-check: dostane trajektoriu krokov uvazovania
   (zoznam textov ALEBO uz-embedovanych vektorov) a povie, ci uvazovanie
   KONVERGUJE na signal (stabilne) alebo SPIRALUJE do elegantneho nezmyslu
   (chaoticke). Sematika ako MCP analyze_thought_stability: zaporne=stabilne,
   kladne=chaoticke. Robime LOKALNE (daemon nema MCP), na NATIVNYCH 129D YAR v5
   Lorentz vektoroch, so vzdialenostou meranou v hyperbolickom priestore
   (arccosh), nie euklidovsky.

Preco vlastny Lyapunov proxy namiesto MCP:
  MCP hyperspacedb.analyze_thought_stability pouziva Mobius scitanie v Poincare
  guli a hodi "denominator too close to zero" na hranici gule; daemon aj tak
  nema MCP. Diskretny proxy dole ma tu istu interpretaciu (negativny exponent =
  kontrakcia = konvergencia), meria vzdialenost NATIVNE v Lorentz priestore.

Beh:
  VENV_YAR=~/zolander/.venv-yar/bin/python
  echo '{"problem":"..."}' | python3 lens.py lift            # dvojity pohlad (LLM)
  echo '{"steps":["krok1","krok2",...]}' | $VENV_YAR lens.py stability   # texty -> embed
  echo '{"vectors":[[...],[...]]}' | python3 lens.py stability      # uz-vektory (bez GPU)
"""
import os
import sys
import json
import math

# palantir_client (chat/LLM) zije v zolo2.0/toolkit; embedding je ODDELENY
# subprocess do VENV_YAR (torch tam, nie tu).
sys.path.insert(0, "/Users/__USER__/zolo2.0/toolkit")

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "zolander")
VENV_YAR = os.path.join(ROOT, ".venv-yar", "bin", "python")
EMBED = os.path.join(ROOT, "toolkit", "embed_yar.py")


# ---------- rezim 0: MECHANICKA brana (should_double_take) ----------
# Hermes nema event-hooky, takze double-take sa neda spravit ako callback.
# Toto je deterministicky (LLM-free) klasifikator: rozhodne CI si otazka zasluzi
# dvojity pohlad, aby lift nebezal na "ahoj". Skill-konvencia (SKILL.md) vola
# `gate` PRED vaznou odpovedou; ak SERIOUS -> lift, inak preskoc (setri cas/LLM).

# signaly vaznosti (rozhodnutie/rada/strategia/protichodne moznosti/preco)
_SERIOUS_MARKERS = [
    "mam ", "mám ", "oplati", "oplatí", "je lepsie", "je lepšie", "mal by",
    "malo by", "mala by", "rozhodn", "strateg", "preco", "prečo", "za a proti",
    "dilema", "dlhodob", "risk", "riziko", "investi", "kariér", "karier",
    "should i", "worth it", "better to", "trade-off", "tradeoff", "dôsledk",
    "dosledk", "smerovanie", "vziat", "vziať", "odist", "odísť", "zmenit prac",
    "vztah", "vzťah", "buducnost", "budúcnost", "zavazok", "záväzok",
]
# trivialne (nikdy netreba double-take)
_TRIVIAL = ["ahoj", "cau", "čau", "dik", "ďik", "dakujem", "ďakujem", "ok",
            "hej", "no", "ano", "áno", "nie", "vdaka", "vďaka", "cus", "čus"]


def should_double_take(text):
    """Deterministicky (bez LLM) rozhodni ci otazka/situacia si zasluzi dvojity
    pohlad. Vrat (serious: bool, dovod: str, skore: int).

    Heuristika (zamerne konzervativna — radsej double-take navyse nez vynechat vazne):
      - trivialny pozdrav/potvrdenie sam osebe -> nikdy
      - inak skore z: dlzka, otaznik pri rozhodovacich slovach, serious markery,
        pritomnost viacerych moznosti (alebo/vs/ci). skore>=2 -> SERIOUS.
    """
    t = (text or "").strip().lower()
    if not t:
        return False, "prazdny vstup", 0
    # ciste trivialne (kratke a len pozdrav/potvrdenie)
    words = t.split()
    if len(words) <= 3 and any(t.startswith(w) for w in _TRIVIAL):
        return False, "trivialny pozdrav/potvrdenie", 0

    score = 0
    reasons = []
    n_markers = sum(1 for m in _SERIOUS_MARKERS if m in t)
    if n_markers:
        score += min(n_markers, 3)
        reasons.append(f"{n_markers} serious marker(ov)")
    # viacero moznosti = rozhodovanie
    if any(sep in t for sep in (" alebo ", " vs ", " ci ", " či ", " a/alebo ")):
        score += 1
        reasons.append("viacero moznosti (rozhodovanie)")
    # dlhsi, komplexny vstup
    if len(words) >= 25:
        score += 1
        reasons.append("dlhy/komplexny vstup")
    # otaznik + rozhodovacie slovo uz pokryte markermi; samotny otaznik pri dlzke
    if "?" in t and len(words) >= 8:
        score += 1
        reasons.append("otazka nezanedbatelnej dlzky")

    serious = score >= 2
    dovod = "; ".join(reasons) if reasons else "ziadne signaly vaznosti"
    return serious, dovod, score


def gate(problem, model="opus"):
    """Brana: klasifikuj -> ak SERIOUS spusti lift, inak preskoc.
    Vrat dict {double_take: bool, dovod, skore, lift?: {...}}."""
    serious, dovod, score = should_double_take(problem)
    res = {"double_take": serious, "dovod": dovod, "skore": score}
    if serious:
        res["lift"] = lift(problem, model=model)
    else:
        res["note"] = "trivialne — double-take preskoceny (setrim cas/LLM)"
    return res


# ---------- rezim 1: dvojity pohlad (lift) ----------

LIFT_SYSTEM = """Si Zolander — dekonstrukcny nastroj na luciditu, nie potapkavac.
Dostanes problem/situaciu veducka. Sprav DVOJITY POHLAD, strucne a vecne:
1) LEVEL: pomenuj na akej urovni abstrakcie problem lezi (konkretna instancia?
   opakujuci sa vzorec? principialna otazka?).
2) UP: vystup o JEDNU uroven vyssie — "toto X je instancia coho vseobecnejsieho Y".
3) META: otazka nad otazkou — co je ta PRAVA otazka za tou polozenou.
4) DOWN: P5 zostup spat k AKCII — "a teraz konkretne urob toto". Nadhlad je v
   sluzbe akcie, nie namiesto nej.
Ziadna lichotka, ziadny balast. Ak vidis veduckov autopilot/slepe miesto, pomenuj
ho — ale tak, aby ho to posunulo HORE.
Vrat IBA JSON: {"level":"...","up":"...","meta":"...","down_action":"..."}"""


def lift(problem, model="opus"):
    from palantir_client import chat
    raw = chat(problem, model=model, system=LIFT_SYSTEM, max_tokens=700).strip()
    s, e = raw.find("{"), raw.rfind("}")
    if s >= 0 and e > s:
        try:
            obj = json.loads(raw[s:e + 1])
        except Exception:
            obj = {"raw": raw}
    else:
        obj = {"raw": raw}
    return obj


# ---------- rezim 2: self-check konvergencie (stability) ----------

def _embed_many(texts):
    """Texty -> 129D Lorentz vektory cez YAR v5 embed_yar.py (JSONL in/out)."""
    import subprocess
    payload = "".join(json.dumps({"id": i, "text": t}, ensure_ascii=False) + "\n"
                      for i, t in enumerate(texts))
    p = subprocess.run(
        [VENV_YAR, EMBED], input=payload, capture_output=True, text=True,
    )
    if p.returncode != 0:
        raise RuntimeError("embed_yar zlyhal: " + p.stderr[-400:])
    by_id = {}
    for line in p.stdout.splitlines():
        line = line.strip()
        if line and line.startswith("{"):
            o = json.loads(line)
            by_id[o["id"]] = o["vector"]
    return [by_id[i] for i in range(len(texts))]


def _dist(a, b):
    """Lorentzova (hyperboloidova) vzdialenost dvoch 129D bodov: arccosh(-<a,b>_L).
    Vektory z YAR v5 lezia na hyperboloide, takze meriame NATIVNE, nie euklidovsky."""
    mink = -a[0] * b[0] + sum(x * y for x, y in zip(a[1:], b[1:]))
    val = -mink
    if val < 1.0:
        val = 1.0
    elif val > 1e6:
        val = 1e6  # fp guard (red-team #3): clip proti strate presnosti acosh pri obrom r
    return math.acosh(val)


def lyapunov(vectors):
    """Diskretny Lyapunov proxy nad krokmi uvazovania.

    d_i = vzdialenost susednych krokov. Exponent = priemer log(d_{i+1}/d_i).
    < 0  -> kroky sa zmensuju = uvazovanie KONVERGUJE (stabilne, mieri na signal).
    > 0  -> kroky rastu = SPIRALUJE (chaoticke, elegantny nezmysel).
    Vrati (exponent, label, detaily). Potrebuje >= 3 kroky.
    """
    n = len(vectors)
    if n < 3:
        return None, "NEDOSTATOK_KROKOV", {"steps": n}
    ds = [_dist(vectors[i], vectors[i + 1]) for i in range(n - 1)]
    eps = 1e-9
    ratios = []
    for i in range(len(ds) - 1):
        num = ds[i + 1] + eps
        den = ds[i] + eps
        ratios.append(math.log(num / den))
    exponent = sum(ratios) / len(ratios)
    # tolerancna zona okolo nuly: mala oscilacia nie je hned chaos
    if exponent < -0.05:
        label = "STABILNE (konverguje)"
    elif exponent > 0.05:
        label = "CHAOTICKE (spiraluje)"
    else:
        label = "NEUTRALNE (drzi vzdialenost)"
    return exponent, label, {"steps": n, "step_dists": [round(d, 4) for d in ds]}


def stability(obj):
    if "vectors" in obj:
        vecs = obj["vectors"]
    elif "steps" in obj:
        vecs = _embed_many(obj["steps"])
    else:
        raise ValueError("stability: chyba 'steps' alebo 'vectors'")
    exp, label, det = lyapunov(vecs)
    verdict = {
        "exponent": None if exp is None else round(exp, 5),
        "label": label,
        "converges": (exp is not None and exp < 0.05),
        **det,
    }
    # self-check odporucanie
    if label.startswith("CHAOTICKE"):
        verdict["advice"] = ("Uvazovanie sa rozbieha. Zastav, vrat sa k poslednemu "
                             "kroku co drzal signal, a over premisy — nekonci to na "
                             "elegantnu blbost.")
    elif label.startswith("STABILNE"):
        verdict["advice"] = "Uvazovanie konverguje. Mozes zostupit k akcii (P5)."
    else:
        verdict["advice"] = "Bez jasneho trendu; pridaj kroky alebo over ci sa krutis dokola."
    return verdict


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "lift"
    if cmd == "gate":
        obj = json.loads(sys.stdin.read())
        model = obj.get("model", "opus")
        print(json.dumps(gate(obj["problem"], model=model), ensure_ascii=False, indent=2))
    elif cmd == "lift":
        obj = json.loads(sys.stdin.read())
        model = obj.get("model", "opus")
        print(json.dumps(lift(obj["problem"], model=model), ensure_ascii=False, indent=2))
    elif cmd == "stability":
        obj = json.loads(sys.stdin.read())
        print(json.dumps(stability(obj), ensure_ascii=False, indent=2))
    else:
        print("neznamy prikaz: " + cmd, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
