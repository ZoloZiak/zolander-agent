#!/usr/bin/env python3
"""zol_manifest.py — auto-generovanie anchor manifestov z TYPU ulohy (bod 2).

Problem: anchory som pisal rucne per uloha. To nekaskaduje. Recuris/OpenSkill maju
"skill invocation" co z aktualneho task-state vyberie spravnu experienciu. Tu je
deterministicky analog: z TYPU ulohy vygeneruj sadu verification anchorov, ktoru
potom zol_checker spusti. NIE LLM — cisto sablony (stdlib). LLM-vrstvu (ktora z volnej
ulohy odvodi typ+params) riesi zol_meta.py; toto je spodna deterministicka vrstva.

FILOZOFIA (aby to nebolo divadlo): generator emituje LEN anchory ktore sa daju REALNE
overit z danych parametrov. Nevymysla checky naslepo. Ked param chyba, ten anchor
NEVZNIKNE a manifest to transparentne pozamena v `_skipped` (co + preco). Radsej menej
anchorov co naozaj bezia nez kopa co zlyha na chybajucom argumente.

Kazda sablona vracia (anchors, skipped). Anchor nesie `component` (kde opravit pri
zlyhani — Recuris localization) a rozumny `on_fail` (klasifikacia — OpenSkill).

Templates (task_type):
  push       {repo, remote?, sha?/branch?, files?=[sanit+compile], test_cmd?}
  code       {path, test_cmd?, smoke_cmd?}                      # zmena jedneho .py
  refactor   {files:[...], tests:[...], python?, timeout?}      # viac suborov + viac testov
  toolkit    {files:[...], runner?, python?, timeout?}          # py zmena + green-check suite
  skill-edit {path, must?=[substr], version?, frontmatter?}     # SKILL.md / dokument
  chapter    {path, cite_pattern?, min_lines?, min_cites?, leaks?}  # Regime B, kniha
  sanitize   {path|paths, extra?}                               # verejny push leak-gate
Aliasy: book->chapter, skill->skill-edit (spatna kompatibilita s druhym generatorom).

CLI:
  zol_manifest.py gen <task_type> '<json-params>'    # vypis manifest JSON na stdout
  zol_manifest.py gen <task_type> k=v k=v ...         # params ako key=value
  zol_manifest.py types                               # zoznam sablon + povinne params
"""
import os
import sys
import json

# Default zakazane vzory pre sanitizaciu verejneho repa (zol_paths pravidlo).
# Realne cesty/uzivatelske meno NIKDY nesmu unikat do verejneho ZoloZiak repa.
_SANIT_DEFAULT = [r"/Users/__USER__", r"__USER__\.z", r"__USER__"]

# Aliasy typov (druhy generator pouzival ine mena; drzime spatnu kompatibilitu).
_ALIASES = {"book": "chapter", "skill": "skill-edit"}


def _mk(id_, type_, component, on_fail=None, **args):
    a = {"id": id_, "type": type_, "component": component}
    if on_fail:
        a["on_fail"] = on_fail
    a.update(args)
    return a


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def t_push(p):
    """Push je hotovy LEN ked remote realne ma SHA (git_pushed) + sanit + testy zelene."""
    anchors, skipped = [], []
    repo = p.get("repo") or os.path.expanduser("~/projects/zolander")
    g = _mk("remote-has-sha", "git_pushed", "artifact", repo=repo,
            remote=p.get("remote", "origin"))
    if p.get("sha"):
        g["sha"] = p["sha"]
    elif p.get("branch"):
        g["branch"] = p["branch"]
    anchors.append(g)
    files = _as_list(p.get("files"))
    if files:
        for i, f in enumerate(files):
            # sanit leak-gate na kazdy subor co ide do verejneho repa
            anchors.append(_mk(f"sanit-{i}", "not_contains", "artifact", on_fail="leak",
                               path=f, must_not=_SANIT_DEFAULT + (p.get("extra") or []),
                               regex=True))
            if f.endswith(".py"):
                anchors.append(_mk(f"compile-{i}", "py_compile", "artifact", path=f))
    else:
        skipped.append("sanit/compile: chyba 'files' (nekontrolujem leak zmenenych suborov)")
    if p.get("test_cmd"):
        anchors.append(_mk("tests-green", "cmd_exit", "artifact",
                           cmd=p["test_cmd"], expect=0, timeout=p.get("timeout", 180)))
    else:
        skipped.append("tests: chyba 'test_cmd'")
    return anchors, skipped


def t_code(p):
    """Zmena .py suboru: skompiluje sa + (volitelne) testy zelene + smoke bez traceback."""
    anchors = [
        _mk("exists", "file_exists", "artifact", on_fail="missing", path=p["path"]),
        _mk("compiles", "py_compile", "artifact", path=p["path"]),
    ]
    skipped = []
    if p.get("test_cmd"):
        anchors.append(_mk("tests-green", "cmd_exit", "artifact",
                           cmd=p["test_cmd"], expect=0, timeout=p.get("timeout", 180)))
    else:
        skipped.append("tests: chyba 'test_cmd'")
    if p.get("smoke_cmd"):
        # smoke beh NESMIE vyhodit traceback (aj ked exit 0 by mohol klamat)
        anchors.append(_mk("smoke-no-traceback", "cmd_output_lacks", "artifact",
                           cmd=p["smoke_cmd"], must_not="Traceback",
                           timeout=p.get("timeout", 120)))
    return anchors, skipped


def t_refactor(p):
    """Uprava viacerych suborov: dotknute .py sa kompiluju, ne-.py existuju, testy zelene."""
    anchors, skipped = [], []
    files = _as_list(p.get("files"))
    interp = p.get("python", "/usr/bin/python3")
    for i, f in enumerate(files):
        if f.endswith(".py"):
            anchors.append(_mk(f"compile-{i}", "py_compile", "artifact", path=f))
        else:
            anchors.append(_mk(f"exists-{i}", "file_exists", "artifact",
                               on_fail="missing", path=f))
    if not files:
        skipped.append("compile/exists: chyba 'files'")
    tests = _as_list(p.get("tests"))
    if tests:
        for i, t in enumerate(tests):
            anchors.append(_mk(f"test-{i}", "cmd_exit", "artifact",
                               cmd=[interp, t], expect=0,
                               timeout=int(p.get("timeout", 120))))
    else:
        skipped.append("tests: chyba 'tests' (bez testu je 'hotovo' iba tvrdenie)")
    return anchors, skipped


def t_toolkit(p):
    """Python zmena v toolkite: dotknute subory sa kompiluju + green-check suite zelena."""
    anchors, skipped = [], []
    files = _as_list(p.get("files"))
    for i, f in enumerate(files):
        anchors.append(_mk(f"compile-{i}", "py_compile", "artifact", path=f))
    if not files:
        skipped.append("compile: chyba 'files'")
    interp = p.get("python", "/usr/bin/python3")
    runner = p.get("runner", "~/projects/zolander/toolkit/run_tests.py")
    anchors.append(_mk("green-check", "cmd_exit", "artifact",
                       cmd=[interp, runner, "--offline"], expect=0,
                       timeout=int(p.get("timeout", 180))))
    return anchors, skipped


def t_skill_edit(p):
    """Edit skillu/dokumentu: existuje, skompiluje sa ak .py, ma frontmatter (ak SKILL.md),
    obsahuje ocakavane markery a spravnu verziu."""
    path = p["path"]
    anchors = [_mk("exists", "file_exists", "artifact", on_fail="missing", path=path)]
    skipped = []
    if path.endswith(".py"):
        anchors.append(_mk("compiles", "py_compile", "artifact", path=path))
    # YAML frontmatter (dva `---` riadky) — typicke pre SKILL.md; volitelne cez frontmatter=True
    if p.get("frontmatter") or path.endswith("SKILL.md"):
        anchors.append(_mk("frontmatter", "regex_present", "skill",
                           on_fail="implementation_bug", path=path,
                           pattern=r"^---\s*$", min=2))
    for i, m in enumerate(_as_list(p.get("must"))):
        anchors.append(_mk(f"has-{i}", "file_contains", "skill",
                           on_fail="implementation_bug", path=path, must=m))
    if p.get("version"):
        anchors.append(_mk("version", "file_contains", "skill",
                           on_fail="knowledge_gap", path=path, must=p["version"]))
    else:
        skipped.append("version: chyba 'version' (nekontrolujem bump)")
    return anchors, skipped


def t_chapter(p):
    """REGIME B (kniha/analyza — bez oracle): verification anchors z externej evidencie.
    Nehodnotia 'kvalitu', ale MOZU zlyhat: nie prazdna, cituje atomy, nula leaknutych mien."""
    path = p["path"]
    anchors = [
        _mk("exists", "file_exists", "artifact", on_fail="missing", path=path),
        _mk("not-empty", "line_count_min", "artifact", on_fail="knowledge_gap",
            path=path, min=int(p.get("min_lines", 20))),
    ]
    skipped = []
    # cituje atomy? (invariant: kapitola co tvrdi ze cerpa z atomov ich ma referencovat)
    if p.get("cite_pattern"):
        anchors.append(_mk("cites-atoms", "regex_present", "retrieval",
                           on_fail="knowledge_gap", path=path,
                           pattern=p["cite_pattern"], min=int(p.get("min_cites", 1))))
    else:
        skipped.append("cites-atoms: chyba 'cite_pattern' (nekontrolujem citacie atomov)")
    # leak-gate: ziadne realne mena/cesty/detaily z prace (gateway sanit pravidlo)
    leaks = _as_list(p.get("leaks")) + _SANIT_DEFAULT
    anchors.append(_mk("no-leak", "not_contains", "artifact", on_fail="leak",
                       path=path, must_not=leaks, regex=True))
    return anchors, skipped


def t_sanitize(p):
    """Verejny push sanit-gate: subor(y) NESMU obsahovat realne cesty/meno/__USER__."""
    paths = _as_list(p.get("paths")) or ([p["path"]] if p.get("path") else [])
    pats = _SANIT_DEFAULT + (p.get("extra") or [])
    anchors = [_mk(f"clean-{i}", "not_contains", "artifact", on_fail="leak",
                   path=f, must_not=pats, regex=True) for i, f in enumerate(paths)]
    return anchors, []


TEMPLATES = {
    "push": t_push,
    "code": t_code,
    "refactor": t_refactor,
    "toolkit": t_toolkit,
    "skill-edit": t_skill_edit,
    "chapter": t_chapter,
    "sanitize": t_sanitize,
}

# Povinne params per sablona (pre validaciu + `types`).
_REQUIRED = {
    "push": [],           # repo ma default
    "code": ["path"],
    "refactor": [],        # aspon files alebo tests (kontrola nizsie)
    "toolkit": [],         # runner ma default
    "skill-edit": ["path"],
    "chapter": ["path"],
    "sanitize": [],        # path alebo paths (kontrola nizsie)
}


def generate(task_type, params):
    """Vrat manifest dict {task, task_type, anchors, _skipped?}. Fail-CLOSED: neznamy typ /
    chybajuce povinne params -> ValueError (radsej hlucne nez tichy prazdny manifest)."""
    task_type = _ALIASES.get(task_type, task_type)
    fn = TEMPLATES.get(task_type)
    if fn is None:
        raise ValueError(f"neznamy task_type: {task_type} "
                         f"(mam: {list(TEMPLATES)} + aliasy {list(_ALIASES)})")
    missing = [k for k in _REQUIRED.get(task_type, []) if k not in params]
    if missing:
        raise ValueError(f"chybajuce params pre '{task_type}': {missing}")
    if task_type == "sanitize" and not (params.get("path") or params.get("paths")):
        raise ValueError("sanitize potrebuje 'path' alebo 'paths'")
    if task_type == "refactor" and not (params.get("files") or params.get("tests")):
        raise ValueError("refactor potrebuje 'files' alebo 'tests'")
    anchors, skipped = fn(params)
    if not anchors:
        raise ValueError(f"sablona '{task_type}' vygenerovala 0 anchorov (chybaju params?)")
    task = params.get("task") or \
        f"{task_type}-{os.path.basename(str(params.get('path', 'auto')))}"
    man = {"task": task, "task_type": task_type, "anchors": anchors}
    if skipped:
        man["_skipped"] = skipped  # transparentne: co sa NEdalo overit a preco
    return man


def _parse_params(argv):
    """Params zo stdin/argv: bud jeden JSON string, alebo k=v k=v paary."""
    if len(argv) == 1 and (argv[0].startswith("{") or argv[0] == "-"):
        raw = sys.stdin.read() if argv[0] == "-" else argv[0]
        return json.loads(raw)
    out = {}
    for tok in argv:
        if "=" not in tok:
            continue
        k, v = tok.split("=", 1)
        # skus JSON (list/int/bool), inak nechaj string
        try:
            out[k] = json.loads(v)
        except Exception:
            out[k] = v
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    if cmd == "types":
        info = {t: _REQUIRED[t] for t in TEMPLATES}
        info["_aliases"] = _ALIASES
        print(json.dumps(info, indent=2, ensure_ascii=False))
        return 0
    if cmd == "gen":
        if len(sys.argv) < 3:
            print("gen <task_type> '<json>' | k=v ...", file=sys.stderr)
            return 2
        task_type = sys.argv[2]
        params = _parse_params(sys.argv[3:]) if len(sys.argv) > 3 else {}
        try:
            man = generate(task_type, params)
        except ValueError as e:
            print(f"CHYBA: {e}", file=sys.stderr)
            return 1
        print(json.dumps(man, ensure_ascii=False, indent=2))
        return 0
    print(f"neznamy prikaz: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
