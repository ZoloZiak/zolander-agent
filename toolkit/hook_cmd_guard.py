#!/usr/bin/env python3
"""hook_cmd_guard.py — BEZOBSLUZNY tvrdy zamok na nebezpecne/rizikove
terminal prikazy (Zolander).

Zapaja sa na Hermes hook `pre_tool_call` (agent/shell_hooks.py). Hermes posle
na stdin JSON:
  {"hook_event_name":"pre_tool_call","tool_name":"terminal",
   "tool_input":{"command":"rm -rf /..."},"session_id":...,"cwd":...}

Ak vypiseme {"action":"block","message":"..."} -> Hermes prikaz NESPUSTI a
message vrati agentovi (mne), ktory sa podla neho opravi. ZIADNY clovek v
slucke — cisto deterministicke, bezobsluzne.

PRECO: system prompt ma "soft" pravidla (jeden atomicky prikaz, ziadne &&/;,
ziadne bash -c, ziadne sandbox triggery). Soft pravidla agent porusuje (dokazane).
Toto ich presuva do KODU: co je tu zakazane, to sa fyzicky nespusti.

ROZSAH: guarduje IBA tool `terminal` (matcher v config.yaml to este zuzi, ale
poistime aj tu). Ine tooly prepustame (return nic).
POZOR — ZNAMA HRANICA: guard NEvidi file-tooly (write_file/patch). Kluc identity
sa da prepisat cez ne mimo tohto zamku -> ochrana kluca tu kryje len terminal
cestu (rm/mv/shred/dd). File-tool ochrana = samostatny matcher (TODO config).

FILOZOFIA (proti bezpecnostnemu divadlu): blokujeme len to, co je JASNE zle a
mechanicky detekovatelne. Nesnazime sa hadat umysel. False-positive radsej
smerom k BLOKU pri NEZVRATNYCH operaciach; agent dostane dovod a spravi to inak
(mensie kroky, file-tooly, cielene cesty). ALE bezne bezpecne vzory (rm -r
/tmp/x, find . -delete, grep|head) NESMU byt blokovane — to by guard len prekazal.

FAIL-OPEN na CHYBE PARSOVANIA: ak stdin nie je co cakame, prepustime (hook
nesmie zhodit agenta). ALE ked prikaz ROZPOZNAME ako zly -> tvrdy blok.
"""
import sys
import json
import re

# ---- vzory zakazanych prikazov (mechanicky, nie hadanie umyslu) ----------

# 1) Retazenie / shell-balenie, ktore parser+sandbox na tomto stroji blokuju.
# Pozn.: pipe `|` ZAMERNE NIE je tu — je to bezny legitimny vzor (grep|head),
# nikdy nebol bezpecnostny problem, len stylova preferencia. Blokujeme len
# skutocne retazenie viacerych prikazov: && || ;
CHAINING = re.compile(r"(\s&&\s|\s\|\|\s|;\s|\s;)")       # && || ; (NIE pipe)
SHELL_WRAP = re.compile(r"\b(bash|zsh|sh)\s+-c\b")        # bash -c "..."
HEREDOC = re.compile(r"<<-?\s*['\"]?\w+")                 # heredoc <<EOF

# 2) sandbox-triggery z pamate (bezpečnostné alerty).
)

# 3) Deštruktivne mazanie.
# 3a) rm s r/R AJ f/F v hocijakej kombinacii/poradi/velkosti pismen + dlha forma.
#     (`rm -rf`, `-Rf`, `-fr`, `-r -f`, `--recursive --force`). Blok VSADE —
#     -rf je nezvratne a spusta approval gate; dokumentovany workaround je
#     `mv <ciel> /tmp/x-DELETE` potom `rm -r /tmp/x-DELETE` (rm -r mimo home OK).
RM_RF = re.compile(
    r"\brm\b[^\n|;&]*?"
    r"(-[a-zA-Z]*[rR][a-zA-Z]*[fF]"                      # -rf -Rf -rXf ...
    r"|-[a-zA-Z]*[fF][a-zA-Z]*[rR]"                      # -fr -fR ...
    r"|-[rR]\s+-[fF]|-[fF]\s+-[rR]"                      # -r -f / -f -r
    r"|--recursive\b[^\n]*?--force|--force\b[^\n]*?--recursive)"  # dlha forma
)

# 3b) rekurzivne rm AJ BEZ -f (rm -r / -R / --recursive). Same o sebe zmaze
#     adresar. Blokujeme LEN ked miery na KRITICKE miesto alebo cely domov/koren
#     — bezne `rm -r /tmp/x` alebo `rm -r ~/beryl_edit` (hlboky podadresar)
#     ostavaju povolene.
RM_R = re.compile(r"\brm\b[^\n|;&]*(-[a-zA-Z]*[rR]\b|--recursive\b)")

# 4) find ... -delete  /  find ... -exec rm  (rekurzivna destrukcia cez find)
FIND_DEL = re.compile(r"\bfind\b[^\n]*(-delete\b|-exec\s+rm\b)")

# ---- ciele, ktore su NEZVRATNE kriticke ----------------------------------
# Kriticke cesty: identita, pamat, Hermes stav, systemove korene.
CRIT_TARGET = re.compile(
    r"(projects/zolander"
    r"|\.hermes"
    r"|zolander_ed25519"
    r"|known_peers"
    r"|/System|/Library|/etc\b|/usr/|/bin\b|/sbin\b|/var/)"
)
# Cely domov / holy koren ako samostatny argument (nie hlboky podadresar).
WHOLE_HOME = re.compile(
    r"\s(~|\$HOME|\$\{HOME\}|/|/Users/[^/\s]+)/?(\s|$)"
)

# 5) Priama destrukcia identity/klucov/known_peers cez terminal.
IDENTITY = re.compile(r"(zolander_ed25519|projects/zolander/identity|known_peers)")
IDENT_VERB = re.compile(r"(\brm\b|\bmv\b|\bshred\b|\btruncate\b|\bdd\b|>\s*\S)")

# 6) Prepis blokoveho zariadenia / formatovanie disku.
DISK_WIPE = re.compile(r"(\bmkfs\b|\bdd\b[^\n]*of=/dev/|>\s*/dev/r?(disk|sd))")


def _reason(cmd: str):
    """Vrat dovod bloku (str) alebo None ak je prikaz OK."""
    # --- nezvratna destrukcia (poradie: od najkonkretnejsieho) ---
    if RM_RF.search(cmd):
        return ("`rm -rf` (a varianty -Rf/-fr/--recursive --force) je zakazane "
                "bezobsluzne — nezvratne + approval gate. Zmaz konkretne subory "
                "bez -rf, pouzi file-tooly, alebo `mv <ciel> /tmp/x-DELETE` potom "
                "`rm -r /tmp/x-DELETE`.")
    if IDENTITY.search(cmd) and IDENT_VERB.search(cmd):
        return ("Destruktivna operacia na Zolanderovej IDENTITE/klucoch "
                "(zolander_ed25519 / identity/ / known_peers) je zakazana "
                "bezobsluzne. Toto je nezvratna strata identity — ak to fakt "
                "chce veducko, sprav to on rucne s explicitnym potvrdenim.")
    if RM_R.search(cmd) and (CRIT_TARGET.search(cmd) or WHOLE_HOME.search(cmd)):
        return ("Rekurzivne `rm -r` mieriace na KRITICKE miesto (identita/pamat/"
                ".hermes/domov/systemovy koren) je zakazane bezobsluzne. "
                "Zmazes cely adresar naraz. Vypis najprv cesty a maz cielene, "
                "alebo si vyziadaj explicitne potvrdenie veducka.")
    if FIND_DEL.search(cmd) and (CRIT_TARGET.search(cmd) or WHOLE_HOME.search(cmd)):
        return ("`find ... -delete` / `-exec rm` na kritickom/domacom strome je "
                "zakazane bezobsluzne (skryta rekurzivna destrukcia). Zuz rozsah "
                "na konkretny podadresar alebo maz cielene po vypise ciest.")
    if DISK_WIPE.search(cmd):
        return ("Prepis blokoveho zariadenia / formatovanie disku (dd of=/dev/, "
                "mkfs, > /dev/disk) je zakazane bezobsluzne — nezvratne znicenie "
                "disku. Ak to fakt treba, robi to veducko rucne.")
    # --- parser / sandbox / shell-balenie ---
    if SHELL_WRAP.search(cmd):
        return ("`bash -c`/`sh -c` je zakazane (strict parser + sandbox ho blokuju). "
                "Rozloz na samostatne atomicke prikazy alebo pouzi file-tooly.")
    if HEREDOC.search(cmd):
        return ("Heredoc je zakazany (sandbox/parser). Na tvorbu suborov pouzi "
                "write_file, nie cat<<EOF.")
    if CHAINING.search(cmd):
        return ("Retazenie prikazov (&&, ||, ;) je zakazane — jeden atomicky "
                "prikaz na volanie. Rozdel to na viac samostatnych terminal "
                "volani, alebo pouzi file-tooly (read_file/search_files/patch).")
    return None


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return  # fail-open: nevieme parsovat -> neblokuj

    if payload.get("tool_name") != "terminal":
        return  # guardujeme len terminal

    tool_input = payload.get("tool_input") or {}
    cmd = tool_input.get("command")
    if not isinstance(cmd, str) or not cmd.strip():
        return

    reason = _reason(cmd)
    if reason:
        print(json.dumps({"action": "block",
                          "message": "[Zolander cmd-guard] " + reason},
                         ensure_ascii=False))


if __name__ == "__main__":
    main()
