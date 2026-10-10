# Toolkit — testovanie a hardening (poučenia z reálnych testov 2026-08-10)

Toolkit skripty (zol_tasks, zol_guard, zol_gc, zol_mem, writeback) sú reálne nástroje
volané z CLI aj z gateway procesu SÚČASNE. Unit test v jednom procese NESTAČÍ.

## PASCA 1 — cross-process lost-update na JSON state (NAJVÁŽNEJŠIA)
Ktorýkoľvek skript čo robí read-modify-write na zdieľanom JSON súbore
(tasks.json, mem_index.jsonl, ledgery, pending fronty) MUSÍ mať cross-process zámok.
`os.replace(tmp, target)` je atomický len na úrovni SÚBORU — NEbráni strate updatu:
proces A číta, proces B číta starší stav, obaja zapíšu, posledný prepíše prvého.
NAMERANÉ: 12 súbežných `zol_tasks.py upsert` procesov → prežilo len 7/12 úloh.
FIX (overený, 20/20 po oprave): `fcntl.flock(f, LOCK_EX)` cez lockfile okolo CELÉHO
read-modify-write cyklu, fail-open (ak lock zlyhá, bež bez neho). Vzor:
```python
import fcntl, contextlib
@contextlib.contextmanager
def _locked():
    os.makedirs(STATE, exist_ok=True)
    f = None
    try:
        f = open(LOCK, "w"); fcntl.flock(f, fcntl.LOCK_EX); yield
    finally:
        if f: 
            try: fcntl.flock(f, fcntl.LOCK_UN)
            except Exception: pass
            f.close()
```
POZOR: flock NIE je re-entrant na novom fd — ak funkcia A (v zámku) volá funkciu B
ktorá by si brala vlastný zámok → deadlock. Nechaj B volať jadro bez druhého zámku.

## PASCA 2 — thread-test maskuje cross-process race
Concurrency testovaný cez `threading` v JEDNOM procese môže prejsť zeleno a pritom
je kód rozbitý pod SAMOSTATNÝMI procesmi (GIL + zdieľaná pamäť maskujú race).
PRAVIDLO: toolkit CLI nástroje testuj cez `subprocess.run([PY, TOOL, ...])` v
ThreadPoolExecutor (N reálnych procesov naraz), NIE volaním funkcie v jednom procese.
Až to odhalí lost-update / file-lock diery.

## PASCA 3 — cp live→repo re-zanáša sanitizované cesty
Repo (`~/zolander-agent-repo`) má cesty ako `/Users/__USER__/...`; živý `~/projects/zolander/`
má `/Users/__USER__/...`. Keď skopíruješ živý súbor do repa (`cp live repo`), PREPÍŠEŠ
sanitizovanú verziu a znovu zanesieš `__USER__`. PRAVIDLO: po KAŽDOM cp live→repo znova
grep `ziak` per-súbor (priečinkový grep je flaky na tomto stroji) a re-sanitizuj na
`__USER__`, AŽ POTOM commit. Overené: stalo sa to s embed_yar.py, lens.py, zol_gc.py.

## PASCA 4 — guard regex diery na reálnej SK
- CLAIM_NEEDS_CITE regex bol príliš rigidný: `funkcia (je|sa nachadza)` nechytil
  "funkcia HANDLE sa nachadza" (slovo medzi). Fix: `\bfunkcia\b.{0,40}?\b(...)`.
- CLAIM cesta bola diakritika-slepá (nekonzistentná s TELLS/SYCOPHANCY čo cez _find
  normalizujú). Fix: `_strip_diacritics(ln)` aj v CLAIM slučke.
- Anti-sycophancy list zúžený len na SUBMISIU-bez-dôvodu; čisté afirmácie ("skvela
  otazka", "mas pravdu"+dôvod) sa VYPUSTILI — boli false-positive na legitímny súhlas.
STRESS TEST: hoď na guard desiatky REÁLNych viet (aj Zolanderov tón, nadávky,
konfrontáciu) s očakávaním clean/syco/tell/cite; cieľ = NÁJSŤ kde sa mýli, nie 100% PASS.

## Metóda: test na reálnych prípadoch > syntetický unit test
Unit test overí že mechanizmus BEŽÍ; test na reálnych vetách/procesoch/dátach overí
že sa SPRÁVA. Dnes to odhalilo 2 bugy (guard regex, tasks race) čo syntetika minula.
Vždy pusti aj beh na SKUTOČNÝCH dátach (napr. zol_gc dry-run na reálnom mem_index —
odhalilo že tam UŽ SÚ L2 uzly z dream konsolidácie, nie čisté L0 ako sme mysleli).
