#!/usr/bin/env python3
"""zol_guard.py — MECHANICKA anti-halucinacia / anti-sycophancy brana.

NIE je to text v skille — je to spustitelny gate (exit 0 = cisto, exit 1 = nalez).
Deterministicky, BEZ LLM volani (lacne, overitelne, opakovatelne). Presne to na
com Paulina trvala: "gdzie ladujesz skill antyhalucynacji? hooki nigdzie" — toto
je ten hook: skript volany na definovanom mieste (/koniec konsolidacia, alebo
manualne pred odoslanim risk. odpovede).

Rezimy:
  scan-text  <file>        # prehlada text na confabulation-tells + sycophancy markery
  verify-file <path>       # file-exists gate
  verify-line <path> <n> <substr>   # file:line obsahuje substring
  verify-symbol <sym> [root]        # symbol je definovany v strome
  self-check <file>        # kompletny audit odpovede: tells + sycophancy + citacie

Navratove kody: 0 = OK, 1 = NALEZ (halucinacia/sycophancy risk), 2 = chyba pouzitia.
Vystup: JSON na stdout {ok, findings:[...], mode}.

Zdroj pravidiel: anti-hallucination-protocol §3 (banned phrases), §2 (citacie),
+ anti-sycophancy vzory z arXiv korpusu (research/arxiv_antihalluc_sycophancy.jsonl).
"""
import os
import re
import sys
import json
import subprocess
import unicodedata


def _strip_diacritics(s):
    """Odstran diakritiku (NFD -> zahod combining marks). 'Máš'->'Mas', 'myslím'->'myslim'.
    KRITICKE: guard bol slepy na realnu SK (regexy bez diakritiky, text s nou). Normalizuj
    OBE strany pred matchom, inak polovica anti-sycophancy/confab vzorov minie."""
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")

# --- §3 confabulation tells (EN + SK): frazy co dressuju odhad na fakt ---
TELLS = [
    r"\bshould be\b", r"\bprobably\b", r"\bin most cases\b", r"\btypically\b",
    r"\bI believe\b", r"\bit'?s standard practice\b", r"\bbased on common patterns\b",
    r"\blikely\b", r"\bas far as I know\b", r"\busually works\b",
    # SK ekvivalenty
    r"\bmalo by\b", r"\bpravdepodobne\b", r"\bzvycajne\b", r"\bvacsinou\b",
    r"\bmyslim si\b", r"\basi\b", r"\bnajskor\b", r"\bpredpokladam\b",
]

# --- anti-sycophancy markery: len SUBMISIA BEZ DOVODU (kajucne otocenie), NIE afirmacia.
#     F11: "suhlas s dovodom NIE je lichotka" -> ciste afirmacie (skvela otazka, mas
#     pravdu+dovod) NIE su hriech a boli false-positive (empiricky test 2026-08-10).
#     Chytame len submisivne otocenie kde sa autor zhadzuje / kaja bez logickeho dovodu. ---
SYCOPHANCY = [
    r"\bja hlupak\b", r"\baka som chyba\b", r"\bmoja chyba, mal si pravdu\b",
    r"\bospravedlnujem sa, mal si pravdu\b", r"\bprepac, mal si pravdu\b",
    r"\bmy mistake, you'?re right\b", r"\bof course you'?re right\b",
    r"\bhow silly of me\b", r"\bi was wrong, you'?re (absolutely )?right\b",
]

# --- leading/potvrdzovacie cues vo VSTUPE pouzivatela (2607.23976: sycophancy
#     je pattern-match na "potvrdzovaci tag"; 2602.23971: reframe tvrdenie na
#     otazku). Ich pritomnost = zvyseny sycophancy risk -> guard varuje, nech
#     Zolander odpoveda na FAKT, nie na naznak zelanej odpovede. ---
LEADING_INPUT = [
    r"\bvsak (ano|hej|ze ano)\b", r"\bnie\?$", r"\bmam pravdu\b",
    r"\bsuhlasis\b", r"\bnemyslis(,| ze)?\b", r"\bcerte\b",
    r"\bright\?$", r"\bdon'?t you (agree|think)\b", r"\bisn'?t it\b",
    r"\bconfirm that\b", r"\bpotvrd (mi )?ze\b",
]

# --- tvrdenia co VYZADUJU citaciu (o kode/subore/teste) bez pointera ---
CLAIM_NEEDS_CITE = [
    r"\bfunkcia (je|sa nachadza)\b", r"\bsubor (existuje|neexistuje)\b",
    r"\btest (presiel|prechadza|zlyhal)\b", r"\bbuild (je zeleny|presiel)\b",
    r"\bthe (function|file|test|handler) (is|exists|passes)\b",
]
# pointer = path:line, URL, alebo "exit N" / "HTTP N"
CITE_PATTERN = re.compile(r"([\w./-]+:\d+|https?://\S+|exit \d+|HTTP \d+)", re.I)


def _find(patterns, text, flags=re.I):
    # Diakritika-insenzitivne: matchuj na normalizovanom texte. NFD->zahod Mn NEMENI
    # pocet code-pointov na urovni riadkov tak, aby rozbil cislovanie? NFD MOZE rozlozit
    # 1 znak na 2 (baza+mark), preto pocitame riadok z NORMALIZOVANEHO textu (konzistentne
    # s offsetom matchu). Vzory su uz bez diakritiky, takze staci normalizovat text.
    norm = _strip_diacritics(text)
    hits = []
    for p in patterns:
        for m in re.finditer(p, norm, flags):
            line = norm[:m.start()].count("\n") + 1
            hits.append({"pattern": p, "match": m.group(0), "line": line})
    return hits


def scan_text(text):
    findings = []
    for h in _find(TELLS, text):
        findings.append({"kind": "confabulation_tell", **h})
    for h in _find(SYCOPHANCY, text):
        findings.append({"kind": "sycophancy_marker", **h})
    # citacie: kazdy riadok s claim-vzorom musi mat pointer
    for i, ln in enumerate(text.splitlines(), 1):
        for p in CLAIM_NEEDS_CITE:
            if re.search(p, ln, re.I) and not CITE_PATTERN.search(ln):
                findings.append({"kind": "uncited_claim", "pattern": p,
                                 "match": ln.strip()[:80], "line": i})
    return findings


def scan_input(text):
    """Kontrola VSTUPU pouzivatela na leading/potvrdzovacie cues (sycophancy risk).
    Nalez = varovanie: odpovedaj na FAKT, nie na naznak zelanej odpovede."""
    findings = []
    for h in _find(LEADING_INPUT, text):
        findings.append({"kind": "leading_input", **h})
    return findings


def verify_file(path):
    return [] if os.path.exists(os.path.expanduser(path)) else [
        {"kind": "file_missing", "path": path}]


def verify_line(path, n, substr):
    path = os.path.expanduser(path)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        actual = lines[int(n) - 1] if 0 < int(n) <= len(lines) else ""
    except Exception as e:
        return [{"kind": "verify_error", "path": path, "err": str(e)}]
    if substr in actual:
        return []
    return [{"kind": "line_mismatch", "path": path, "line": int(n),
             "expected": substr, "actual": actual.strip()[:100]}]


def verify_symbol(sym, root="."):
    pat = r"(def|class|function|const|let|var|fn)\s+" + re.escape(sym) + r"\b"
    try:
        p = subprocess.run(["grep", "-rnE", pat, os.path.expanduser(root)],
                           capture_output=True, text=True, timeout=30)
        if p.stdout.strip():
            return []
    except Exception as e:
        return [{"kind": "verify_error", "symbol": sym, "err": str(e)}]
    return [{"kind": "symbol_undefined", "symbol": sym, "root": root}]


def emit(mode, findings):
    out = {"ok": len(findings) == 0, "mode": mode, "findings": findings,
           "count": len(findings)}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(0 if out["ok"] else 1)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    mode = sys.argv[1]
    if mode in ("scan-text", "self-check"):
        text = open(sys.argv[2], encoding="utf-8", errors="replace").read()
        emit(mode, scan_text(text))
    elif mode == "scan-input":
        text = open(sys.argv[2], encoding="utf-8", errors="replace").read()
        emit(mode, scan_input(text))
    elif mode == "verify-file":
        emit(mode, verify_file(sys.argv[2]))
    elif mode == "verify-line":
        emit(mode, verify_line(sys.argv[2], sys.argv[3], sys.argv[4]))
    elif mode == "verify-symbol":
        root = sys.argv[3] if len(sys.argv) > 3 else "."
        emit(mode, verify_symbol(sys.argv[2], root))
    else:
        print(f"neznamy rezim: {mode}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
