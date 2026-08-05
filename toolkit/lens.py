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
    if cmd == "lift":
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
