#!/usr/bin/env python3
"""zol_desktop_notify.py — natívna macOS notifikačná vrstva Zolandera.

Vystrelí klikateľnú macOS notifikáciu cez terminal-notifier. Ak dostane cestu
k .md reportu, vygeneruje z neho jednoduché HTML do state/reports/ a klik na
notifikáciu ho otvorí v prehliadači (-open file://...).

Použitie:
    zol_desktop_notify.py --title "Zolander" --subtitle "ranny brief" \
        --message "text..." [--report <path.md>] [--sound Glass]

Volá ju zolander_notify.py (jednotná vrstva) — netreba ju spúšťať ručne.
Fail-open: akákoľvek chyba -> exit 0, nikdy nezhodí volajúci daemon.
Stdlib only, /usr/bin/python3.
"""
import os
import sys
import html
import datetime
import subprocess

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, "zolander")
STATE = os.path.join(ROOT, "state")
LOGS = os.path.join(ROOT, "logs")
REPORTS = os.path.join(STATE, "reports")
NOTIFYLOG = os.path.join(LOGS, "notify.log")

# terminal-notifier je user-level brew bottle; launchd má orezaný PATH ->
# explicitná cesta + fallback na PATH.
TN_CANDIDATES = [
    os.path.join(HOME, "Applications", "homebrew", "bin", "terminal-notifier"),
    "/opt/homebrew/bin/terminal-notifier",
    "/usr/local/bin/terminal-notifier",
]

# Bundle ID appky ktorá sa "aktivuje" na klik keď NIE je -open (banner ostane
# klikateľný, otvorí Safari na report). Prázdne = default správanie.


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    try:
        os.makedirs(LOGS, exist_ok=True)
        with open(NOTIFYLOG, "a", encoding="utf-8") as f:
            f.write(f"{now()} | desktop | {msg}\n")
    except Exception:
        pass


def find_tn():
    for c in TN_CANDIDATES:
        if c and os.path.exists(c):
            return c
    return None


def md_to_html(md_text, title):
    """Minimalistický md->html (nadpisy, odrážky, **bold**, • odrážky).
    Žiadna knižnica — stdlib. Escapuje HTML, potom povolí pár značiek."""
    def inline(s):
        s = html.escape(s)
        # **bold**
        out = []
        i = 0
        bold = False
        while i < len(s):
            if s[i:i + 2] == "**":
                out.append("</strong>" if bold else "<strong>")
                bold = not bold
                i += 2
            else:
                out.append(s[i])
                i += 1
        if bold:
            out.append("</strong>")
        return "".join(out)

    lines = md_text.splitlines()
    body = []
    in_list = False

    def close_list():
        nonlocal in_list
        if in_list:
            body.append("</ul>")
            in_list = False

    for raw in lines:
        s = raw.rstrip()
        st = s.strip()
        if not st:
            close_list()
            continue
        if st.startswith("### "):
            close_list()
            body.append(f"<h3>{inline(st[4:])}</h3>")
        elif st.startswith("## "):
            close_list()
            body.append(f"<h2>{inline(st[3:])}</h2>")
        elif st.startswith("# "):
            close_list()
            body.append(f"<h1>{inline(st[2:])}</h1>")
        elif st.startswith("---"):
            close_list()
            body.append("<hr>")
        elif st.startswith("- ") or st.startswith("* "):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{inline(st[2:])}</li>")
        elif st.startswith("•") or st.startswith("   •"):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{inline(st.lstrip(' •'))}</li>")
        elif st.startswith("*") and st.endswith("*") and len(st) > 2:
            close_list()
            body.append(f"<p><em>{inline(st.strip('*'))}</em></p>")
        else:
            close_list()
            body.append(f"<p>{inline(st)}</p>")
    close_list()

    return f"""<!DOCTYPE html>
<html lang="sk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
  :root {{ color-scheme: dark light; }}
  body {{ font: 16px/1.6 -apple-system, "SF Pro Text", system-ui, sans-serif;
         max-width: 760px; margin: 40px auto; padding: 0 24px;
         background: #1c1c1e; color: #e8e8ea; }}
  h1 {{ font-size: 1.7em; border-bottom: 2px solid #3a3a3c; padding-bottom: .3em; }}
  h2 {{ font-size: 1.25em; color: #7aa2f7; margin-top: 1.6em; }}
  h3 {{ font-size: 1.05em; color: #9ece6a; }}
  ul {{ padding-left: 1.3em; }}
  li {{ margin: .25em 0; }}
  hr {{ border: none; border-top: 1px solid #3a3a3c; margin: 2em 0; }}
  strong {{ color: #f7768e; }}
  em {{ color: #a9a9ad; }}
  .foot {{ margin-top: 3em; font-size: .8em; color: #6a6a6e; }}
</style></head>
<body>
{chr(10).join(body)}
<p class="foot">Zolander — vygenerované {now()}</p>
</body></html>"""


def build_report(md_path, title):
    """Z .md súboru vyrobí HTML v state/reports/ a vráti file:// URL, alebo None."""
    if not md_path or not os.path.exists(md_path):
        return None
    try:
        with open(md_path, encoding="utf-8") as f:
            md_text = f.read()
        os.makedirs(REPORTS, exist_ok=True)
        base = os.path.splitext(os.path.basename(md_path))[0]
        out_path = os.path.join(REPORTS, f"{base}.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md_to_html(md_text, title))
        return "file://" + out_path
    except Exception as exc:
        log(f"report HTML zlyhal: {exc!r}")
        return None


def _guard_dash(s):
    """terminal-notifier cita hodnotu zacinajucu na '-' ako flag a zozerie ju
    (OVERENE: '-message \"-loop: OK\"' -> Message=(null)). Predsad zero-width
    space (U+200B), ktory je v banneri neviditelny ale zrusi flag-parsing."""
    if s and s.lstrip().startswith("-"):
        return "\u200b" + s
    return s


def fire(tn, title, subtitle, message, url, sound):
    cmd = [tn, "-title", _guard_dash(title), "-message", _guard_dash(message),
           "-ignoreDnD", "-group", "zolander"]
    if subtitle:
        cmd += ["-subtitle", _guard_dash(subtitle)]
    if sound:
        cmd += ["-sound", sound]
    if url:
        cmd += ["-open", url]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        log(f"banner ok (report={'ano' if url and url.startswith('file') else 'nie'})")
        return True
    except Exception as exc:
        log(f"banner exception: {exc!r}")
        return False


def parse_args(argv):
    opts = {"title": "Zolander", "subtitle": "", "message": "",
            "report": "", "sound": ""}
    i = 0
    while i < len(argv):
        a = argv[i]
        key = a[2:] if a.startswith("--") else None
        if key in opts and i + 1 < len(argv):
            opts[key] = argv[i + 1]
            i += 2
        else:
            i += 1
    return opts


def main():
    opts = parse_args(sys.argv[1:])
    if not opts["message"]:
        opts["message"] = sys.stdin.read().strip()
    if not opts["message"]:
        log("prazdna sprava — preskocene")
        return 0

    tn = find_tn()
    if not tn:
        log("terminal-notifier nenajdene -> preskocene (len inbox/push cez zolander_notify)")
        return 0

    url = build_report(opts["report"], opts["title"]) if opts["report"] else None
    fire(tn, opts["title"], opts["subtitle"], opts["message"], url, opts["sound"])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"DESKTOP NOTIFY EXCEPTION: {exc!r}")
        sys.exit(0)  # nikdy nezhod volajuci daemon
