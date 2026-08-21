#!/usr/bin/env python3
"""hook_skill_matcher.py — DETERMINISTICKY navigator skillov pre Zolandera.

Zapaja sa na Hermes hook `pre_llm_call` (agent/shell_hooks.py). Hermes posle na
stdin JSON; text aktualnej user spravy je v payload["extra"]["user_message"]
(overene v agent/turn_context.py:533 — invoke_hook("pre_llm_call",
user_message=original_user_message, ...) a _serialize_payload dava vsetko mimo
top-level klucov do "extra").

CO RIESI: vyber skillu je u modelu PRAVDEPODOBNOSTNY (pattern-matching nad
zoznamom popisov), nie deterministicky — model moze relevantny skill minut,
najma ked ulohu zaramuje ako "vseobecnu". Toto je TVRDY, synchronny predfilter,
co bezi PRED mojim tahom: mechanicky (keyword overlap + kuratorska mapa
spustacov) skenuje frontmatter VSETKYCH skillov a vpichne do user message
upozornenie "zvaz skill X, Y". Nie je to nahrada za moj usudok — je to poistka
proti prehliadnutiu. Ziadny LLM, ziadny subagent, takmer nulova cena tokenov.

PRECO NIE background subagent: ten by prisiel az PO akcii (async), s rovnakym
slepym miestom (rovnaky zoznam skillov). Hook bezi PRED = realne navadza.

CACHE-SAFE: vracia {"context": ...} do USER message, nie system prompt.
STAMP-GUARD: raz na distinct user spravu (nie kazdy vnutorny API call).
INDEX CACHE: podla najnovsieho mtime SKILL.md — necita 180 suborov kazdy turn.
FAIL-OPEN: akakolvek chyba -> tichy no-op (hook nesmie zhodit agenta).
Bezi pod /usr/bin/python3 (stdlib only).
"""
import sys
import os
import re
import json
import glob
import tempfile
import hashlib

SKILLS_ROOT = os.path.expanduser("~/.hermes/skills")
STAMP_DIR = os.path.join(tempfile.gettempdir(), "zol_skillmatch_stamps")
CACHE_PATH = os.path.join(tempfile.gettempdir(), "zol_skill_index.json")

# Minimalny score aby sa skill vobec navrhol, a kolko najviac navrhov.
MIN_SCORE = 3
TOP_N = 3
# Ak je najlepsi navrh vyrazne silnejsi, netlac slabsie (sum).
MIN_QUERY_TOKENS = 2  # kratsie/triviálne spravy (pozdrav) preskoc

# REFERENCES-LEVEL DISCOVERY: skilly su MENU (@skills refactor 2026-08) — telo
# detailov je v references/*.md, ktore rezidentny prompt NEVIDI. Tato vrstva
# indexuje aj ich (nazov suboru + 1-riadkovy popis z INDEXu SKILL.md / prvy
# nadpis referencie) a navrhne konkretny `skill: references/X.md` cez skill_view.
# Vyssi prah nez skilly (uzsie, presnejsie) a samostatny strop proti zaplaveniu.
REF_MIN_SCORE = 4
REF_TOP_N = 3

# Slovenske + anglicke stopwords (nenosia domenovy signal).
STOPWORDS = {
    "the", "and", "for", "with", "you", "your", "can", "how", "what", "when",
    "which", "this", "that", "are", "was", "would", "could", "should", "not",
    "ako", "aby", "ale", "alebo", "ani", "ano", "avsak", "and", "cez", "cim",
    "cize", "coho", "com", "cosi", "daj", "dako", "dat", "den", "dnes", "dobre",
    "este", "hej", "ist", "iny", "jeden", "jej", "jeho", "kde", "ked", "kedy",
    "ktora", "ktore", "ktory", "lebo", "len", "mas", "mat", "mne", "moze",
    "mozes", "na", "nam", "nas", "nech", "nejaky", "nejde", "neni", "nic",
    "nie", "nieco", "no", "o", "od", "on", "ona", "ono", "po", "pod", "pre",
    "preco", "pri", "pri", "prosim", "sa", "sam", "si", "sme", "so", "som",
    "su", "ta", "tak", "takze", "tam", "teda", "teraz", "ti", "to", "tu",
    "tvoj", "tvoja", "tvoje", "ty", "uz", "v", "vam", "vas", "vela", "viem",
    "vies", "vo", "vsak", "vzdy", "za", "zas", "ze", "aj", "ci", "co", "im",
    "moj", "moja", "moje", "mu", "vediet", "urobit", "spravit", "chcem",
    "potrebujem", "mozem", "please", "help",
}

# KURATORSKA MAPA SPUSTACOV (riesi cross-language: user pise po slovensky,
# popisy skillov su casto po anglicky). Kazdy zaznam: regex -> (skill, vaha).
# Vaha 4-6 = silny signal (pridava sa k skore skillu). Rozsiruj podla potreby.
BOOST = [
    # --- lokalny AI stack (user) ---
    (r"\b(palantir|agy|bridge|fallback|embed\w*|vektor\w*|vector\w*|"
     r"hyperspace\w*|orbstack|vmlx|mlx|gpu\s*embed\w*|ssl|proxy|"
     r"brainrocket|cert\w*|rate.?limit|local.?llm|lokaln\w*\s*llm)\b",
     "ziak-local-ai-stack", 5),
    # --- Hermes shell hooky ---
    (r"\b(hook|hooky|hookov|pre_llm|pre_verify|pre_tool|shell.?hook|"
     r"allowlist|deterministick\w*\s*zamok|stamp.?guard)\b",
     "hermes-shell-hooks", 5),
    # --- konfiguracia/uprava samotneho Hermesa ---
    (r"\b(hermes\s*(config|nastav|setup|provider|model|tool|voice|gateway|"
     r"plugin)|nastav\w*\s*hermes|hermes\s*config\s*set)\b",
     "hermes-agent", 4),
    # --- zolo2.0 knizny projekt ---
    (r"\b(zolo|kapitol\w*|kniha|knihu|humaniz\w*|masterplan|ensemble|"
     r"multi.?model|write_chapter|atom\w*|ingest)\b",
     "zolo-book-pipeline", 4),
    (r"\b(atom\w*|klasifik\w*|taxonom\w*|vrstv\w*\s*l[1-4]|enrich)\b",
     "zolo-atom-enrichment", 3),
    (r"\b(zolander|persona|companion|partak|mentor|identita)\b",
     "zolander", 3),
    # --- DLP / macos workflow ---
    (r"\b(dlp|digital\s*guardian|cortex|xattr|keychain|zamknut\w*\s*mac|"
     r"locked.?down)\b",
     "ziak-dlp-macos-workflows", 4),
    # --- Zolander interne: loop/dream/brief/watchdog/decay/pamat (NIE durable-batch!) ---
    (r"\b(loop|dream|sen\b|brief|watchdog|heartbeat|decay|zabuda\w*|"
     r"zabija\s*pam\w*|pamat\w*\s*(stoji|nejde|zabuda)|integrity|"
     r"daemon\w*\s*(stoji|nejde|neposiela)|launchd|initiative|iniciativ\w*)\b",
     "zolander-ai-companion", 4),
    # --- slovenske verejne registre / zmluvy / ICO ---
    (r"\b(registr\w*|zmluv\w*|\bico\b|\bicо\b|crz|orsr|ruz|finstat|"
     r"transparen\w*|obc\w*\s*(rozpocet|vydavk)|susr|datacube|"
     r"pravnick\w*\s*osob\w*)\b",
     "slovak-public-registries", 5),
    # --- anti-bot scraping (obscura/waf/datadome/primp) ---
    (r"\b(scrap\w*|obscura|datadome|cloudflare|\bwaf\b|primp|camoufox|"
     r"scrapling|anti.?bot|tls.?fingerprint|ja3|403\s*forbidden|"
     r"impersonate|stealth\s*browser)\b",
     "antibot-scraping", 5),
    # --- OLX / prenajom bytu / inzeraty watcher ---
    (r"\b(olx|otodom|domiporta|morizon|prenaj\w*|inzerat\w*|kawalerk\w*|"
     r"byt\w*\s*(watch|sledov|prenaj)|nehnutel\w*)\b",
     "olx-scraping-and-watch", 4),
    # --- data-provenance audit (vymyslene cisla / fabrikacia) ---
    (r"\b(provenance|fabrik\w*|vymysl\w*\s*cisl\w*|vycucan\w*|hardcod\w*\s*"
     r"(data|cisl)|halucin\w*\s*(cisl|stat)|overit\s*ci\s*.*realne)\b",
     "data-provenance-audit", 4),
    # --- git / github ---
    (r"\b(commit|push|pushni|repo|repozit\w*|pull.?request|\bpr\b|merge|"
     r"github|branch|vetv\w*)\b",
     "github-pr-workflow", 3),
    (r"\b(code.?review|review\s*(kod|pr)|posud\w*\s*kod)\b",
     "github-code-review", 3),
    # --- planovanie / debug / testy (vaha >=MIN_SCORE aby prah presiel sam) ---
    (r"\b(plan\w*|rozplanuj|naplanuj|navrhni\s*postup|rozpis\s*kroky)\b", "plan", 3),
    (r"\b(debug\w*|chyb\w*|bug|zlyhav\w*|padne|pada|padnut\w*|traceback|"
     r"stack.?trace|exception|rozbit\w*|nefunguje)\b",
     "systematic-debugging", 3),
    (r"\b(test\w*|tdd|unit.?test|pokry\w*\s*test)\b",
     "test-driven-development", 3),
    # --- delegacia / subagenti ---
    (r"\b(subagent\w*|deleg\w*|paraleln\w*\s*agent|orchestr\w*)\b",
     "hermes-agent", 3),
    # --- durable / cron / watchdog ---
    (r"\b(durable|cron\w*|watchdog|daemon|na\s*pozadi\s*dlho|nocn\w*\s*beh)\b",
     "durable-unattended-batch-jobs", 3),
    # --- skill authoring ---
    (r"\b(napis\w*\s*skill|vytvor\w*\s*skill|skill\s*author|frontmatter)\b",
     "hermes-agent-skill-authoring", 4),
    # --- humanizacia textu (mimo zolo pipeline) ---
    (r"\b(humaniz\w*|neznie\s*ako\s*ai|znie\s*ako\s*ai|odai\w*|"
     r"prirodzenej\w*\s*text|menej\s*roboticky)\b",
     "humanizer", 3),
    # --- obsidian / poznamky ---
    (r"\b(obsidian\w*|vault|poznamk\w*|note\w*)\b", "obsidian", 3),
    # --- huggingface ---
    (r"\b(huggingface|hugging\s*face|\bhf\b|hf.?hub|stiahn\w*\s*model|"
     r"download\w*\s*model)\b",
     "huggingface-hub", 4),
]
BOOST = [(re.compile(rx, re.I), name, w) for rx, name, w in BOOST]

_TOKEN_RE = re.compile(r"[a-zá-žäčďéíĺľňóôŕšťúýž0-9]{3,}", re.I)

# SK -> EN EXPANZIA (riesi ze user pise po slovensky, popisy skillov su po
# anglicky). Kluc = slovensky kmen (matchuje sa cez startswith na tokene, aby
# chytil sklonovanie), hodnota = anglicke/domenove tokeny pridane k dopytu PRED
# frontmatter-scoringom. Takto sa skill najde z jeho VLASTNYCH (anglickych) slov
# bez toho aby som pre kazdy pisal BOOST regex. Deterministicke, bez LLM.
# Rozsiruj podla toho ktore slovenske parafrazy realne minu skill.
SK2EN = {
    "prezentac": ["presentation", "slides", "deck", "powerpoint", "pptx"],
    "snimk": ["slides", "presentation"],
    "nahravk": ["audio", "speech", "transcription", "whisper", "recording"],
    "prepis": ["transcription", "transcribe", "speech", "text"],
    "piesen": ["song", "music", "songwriting", "lyrics"],
    "piesn": ["song", "music", "lyrics"],
    "hudb": ["music", "song", "audio"],
    "spievat": ["song", "music", "lyrics"],
    "sms": ["imessage", "sms", "message", "iphone"],
    "iphone": ["imessage", "apple", "iphone"],
    "sprav": ["message", "sms"],  # "sprava" = message (pozor aj "spravit"—filtrovane nizsie)
    "pripomen": ["reminder", "reminders", "todo"],
    "pripomienk": ["reminder", "reminders"],
    "heslo": ["password", "secret", "secrets", "credential", "credentials",
              "1password"],
    "hesl": ["password", "secret", "secrets", "credential", "1password"],
    "ulozit": ["store", "save", "vault"],
    "prezyvk": ["username", "handle", "social", "osint"],
    "socialk": ["social", "media", "network", "osint"],
    "socialn": ["social", "media", "network"],
    "akci": ["stock", "stocks", "market", "investing", "shares", "ticker",
             "quotes", "equity"],  # akcia=stock (aj event—slaby)
    "stoji": ["price", "quotes", "cost"],
    "burz": ["stock", "stocks", "market", "ticker", "investing"],
    "financ": ["financial", "finance", "model"],
    "vykaz": ["statement", "income", "balance", "cashflow", "financial"],
    "tabulk": ["spreadsheet", "excel", "sheet"],
    "fajntun": ["finetune", "fine-tuning", "lora", "training", "train"],
    "fajntjun": ["finetune", "fine-tuning", "lora", "training"],
    "trenovan": ["training", "train", "finetune"],
    "trenova": ["training", "train", "finetune"],
    "lora": ["lora", "peft", "finetune", "adapter"],
    "priepustn": ["throughput", "serving", "inference", "vllm"],
    "serverul": ["server", "serving", "inference"],
    "inferenc": ["inference", "serving", "vllm"],
    "kvantiz": ["quantization", "gguf", "gptq"],
    "obraz": ["image", "picture", "generation"],
    "video": ["video", "clip"],
    "diagram": ["diagram", "chart"],
    "poznamk": ["note", "notes", "obsidian"],
    "kalendar": ["calendar", "event", "schedule"],
    "email": ["email", "mail", "imap", "smtp"],
    "mail": ["email", "mail"],
    "tabul": ["spreadsheet", "sheet", "excel"],
    "kartick": ["flashcard", "flashcards", "spaced", "repetition"],
    "kartesk": ["flashcard", "flashcards", "spaced", "repetition"],
    "ucen": ["learning", "study", "flashcard"],
    "pentest": ["pentest", "penetration", "security", "vulnerability"],
    "zranitel": ["vulnerability", "security", "exploit"],
    "peniaz": ["payment", "pay", "money"],
    "platb": ["payment", "pay", "checkout"],
    "nakup": ["buy", "order"],
    "objednavk": ["order", "shop", "shopping", "checkout"],
    "objednat": ["order", "shop", "checkout"],
    "eshop": ["shop", "shopping", "ecommerce", "checkout"],
    "kosik": ["cart", "checkout", "shop", "order"],
    # --- doplnene po slepej sade (domeny co prepadli) ---
    "kalendar": ["calendar", "gmail", "google", "workspace", "schedule"],
    "rezervac": ["calendar", "schedule", "booking", "event"],
    "tunel": ["tunnel", "localhost", "ssh", "webhook", "ngrok"],
    "localhost": ["localhost", "tunnel", "ssh"],
    "spektrogram": ["spectrogram", "audio", "mel", "chroma"],
    "ethereum": ["evm", "blockchain", "wallet", "token", "defi"],
    "blockchain": ["blockchain", "evm", "wallet", "chain"],
    "blockchajn": ["blockchain", "evm", "wallet", "chain"],
    "wallet": ["wallet", "blockchain", "evm"],
    "penazenk": ["wallet", "blockchain"],
    "polymarket": ["polymarket", "markets", "prediction", "orderbook"],
    "registr": ["registry", "records", "sec", "corporate", "public"],
    "investig": ["investigation", "osint", "records", "corporate"],
    "vysetr": ["investigation", "osint", "records"],
    "clank": ["papers", "arxiv", "research", "academic"],
    "akadem": ["academic", "arxiv", "papers", "research", "science"],
    "vedeck": ["research", "science", "papers", "arxiv"],
    "svetl": ["lights", "hue", "philips", "smart"],
    "svetiel": ["lights", "hue", "philips"],
    "ziarovk": ["lights", "hue", "bulb"],
    "kontajner": ["container", "docker", "image"],
    "docker": ["docker", "container", "compose"],
    "worker": ["worker", "cloudflare", "deploy"],
    "cloudflare": ["cloudflare", "worker", "deploy", "wrangler"],
    "nasad": ["deploy", "deployment", "worker"],
    "kanban": ["kanban", "video", "orchestrator", "agents"],
    "emulator": ["emulator", "emulation", "game"],
    "minecraft": ["minecraft", "modpack", "server", "curseforge"],
    "modpack": ["modpack", "minecraft", "modrinth"],
    "sken": ["scan", "ocr", "pdf", "document"],
    "naskenov": ["scan", "ocr", "pdf", "document"],
    "diagram": ["diagram", "chart", "architecture"],
    "architekt": ["architecture", "diagram", "infra"],
    "denik": ["notion", "note", "journal", "page"],
    "notion": ["notion", "page", "database", "workspace"],
}
# tokeny ktore SK2EN NEMA expandovat aj ked zacinaju na kluc (homonyma)
SK2EN_BLOCK = {"spravit", "spravis", "spravim", "spravme", "spravi",
               "spravny", "spravne", "spravna", "akcieschopny",
               "zoznam", "zoznamu",  # "zoznam nakupu" != shop (bezny zoznam)
               "tokenom", "tokeny"}  # token samo o sebe nie je blockchain


def _expand_sk(tokens: set) -> set:
    """Prida anglicke domenove tokeny pre slovenske kmene (cross-language most)."""
    extra = set()
    for t in tokens:
        if t in SK2EN_BLOCK:
            continue
        for stem, ens in SK2EN.items():
            if t.startswith(stem):
                extra.update(ens)
                break
    return tokens | extra



def _stamp_path(key: str) -> str:
    h = hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()[:16]
    return os.path.join(STAMP_DIR, f"{h}.done")


def _tokens(text: str):
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS}


def _parse_frontmatter(head: str):
    """Vytiahni name, description, tags z YAML frontmatteru (prvy --- blok)."""
    name = desc = ""
    tags = []
    m = re.search(r"^---\s*(.*?)^---\s*", head, re.S | re.M)
    block = m.group(1) if m else head
    for line in block.splitlines():
        s = line.strip()
        if s.startswith("name:") and not name:
            name = s[5:].strip().strip("\"'")
        elif s.startswith("description:") and not desc:
            desc = s[12:].strip().strip("\"'")
        elif s.startswith("tags:"):
            raw = s[5:].strip().strip("[]")
            tags = [t.strip().strip("\"'") for t in raw.split(",") if t.strip()]
    return name, desc, tags


def _ref_desc_from_index(skill_body: str, ref_fn: str) -> str:
    """Najdi 1-riadkovy popis referencie v INDEX sekcii SKILL.md.

    INDEX riadky maju formu `- \`references/X.md\` — popis` alebo
    `- \`X.md\` — popis` (pomlcka/em-dash/dvojbodka ako oddelovac). Vrat popis
    (text za oddelovacom), inak prazdny string.
    """
    base = ref_fn[:-3] if ref_fn.endswith(".md") else ref_fn
    for line in skill_body.splitlines():
        if base not in line:
            continue
        # ber len riadky co vyzeraju ako index-polozka (bullet + nazov suboru)
        s = line.strip()
        if not (s.startswith("-") or s.startswith("*") or s.startswith("•")):
            continue
        # odseknout vsetko po nazov suboru, popis je za prvym em-dash/pomlckou/dvojbodkou
        m = re.split(r"\s[—–-]\s|:\s", s, maxsplit=1)
        if len(m) == 2 and len(m[1].strip()) > 3:
            return m[1].strip()
    return ""


def _first_heading(path: str) -> str:
    """Fallback popis referencie: jej prvy '# ' nadpis alebo prva vecna veta."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(2048)
    except Exception:
        return ""
    for line in head.splitlines():
        s = line.strip()
        if s.startswith("#"):
            return s.lstrip("# ").strip()
    for line in head.splitlines():
        s = line.strip()
        if s and not s.startswith(("---", "```", ">")):
            return s[:120]
    return ""


def _build_index():
    """Zoznam skillov: {name, blob(name+desc+tags), name_tokens, tag_tokens}.

    Kazdy skill nesie aj 'refs': zoznam referencii {file, rel, tokens} pre
    references-level discovery (nazov suboru + popis z INDEXu / prvy nadpis).
    """
    idx = []
    for path in glob.glob(os.path.join(SKILLS_ROOT, "**", "SKILL.md"),
                           recursive=True):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                body = f.read(65536)  # cely skill (INDEX sekcia je na konci)
        except Exception:
            continue
        head = body[:4096]
        name, desc, tags = _parse_frontmatter(head)
        if not name:
            # fallback: meno adresara
            name = os.path.basename(os.path.dirname(path))
        # references-level: naskenuj references/*.md tohto skillu
        refs = []
        refdir = os.path.join(os.path.dirname(path), "references")
        for rp in sorted(glob.glob(os.path.join(refdir, "*.md"))):
            rfn = os.path.basename(rp)
            rdesc = _ref_desc_from_index(body, rfn) or _first_heading(rp)
            fn_tokens = _tokens(rfn[:-3].replace("-", " ").replace("_", " "))
            desc_tokens = _tokens(rdesc)
            refs.append({
                "file": rfn,
                "rel": "references/" + rfn,
                "desc": rdesc,
                "fn_tokens": list(fn_tokens),
                "desc_tokens": list(desc_tokens),
            })
        idx.append({
            "name": name,
            "desc": desc,
            "name_tokens": list(_tokens(name.replace("-", " ").replace("_", " "))),
            "tag_tokens": list(_tokens(" ".join(tags))),
            "desc_tokens": list(_tokens(desc)),
            "refs": refs,
        })
    return idx


def _load_index():
    """Cache podla najnovsieho mtime SKILL.md — necita 180 suborov kazdy turn."""
    try:
        paths = glob.glob(os.path.join(SKILLS_ROOT, "**", "SKILL.md"),
                          recursive=True)
        if not paths:
            return []
        newest = max(os.path.getmtime(p) for p in paths)
    except Exception:
        return []
    try:
        cst = os.path.getmtime(CACHE_PATH)
        if cst >= newest:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    idx = _build_index()
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False)
    except Exception:
        pass
    return idx


def _score(msg: str, qtokens: set, idx):
    """Vrat zoznam (score, name, desc) zoradeny zostupne.

    qtokens = povodne slovenske/anglicke tokeny z dopytu. Expandovane SK->EN
    tokeny sa pridavaju so ZNIZENOU vahou (nesmu robit sum ako povodne slova).
    """
    exp_tokens = _expand_sk(qtokens) - qtokens  # len pridane EN tokeny
    scored = {}
    descs = {}
    for sk in idx:
        name = sk["name"]
        descs[name] = sk.get("desc", "")
        s = 0
        for t in qtokens:
            if t in sk["name_tokens"]:
                s += 3
            elif t in sk["tag_tokens"]:
                s += 2
            elif t in sk["desc_tokens"]:
                s += 1
        for t in exp_tokens:  # expanzia: tag je silny domenovy signal (+2),
            if t in sk["name_tokens"]:   # meno tiez (+2); desc slabsie (+1)
                s += 2
            elif t in sk["tag_tokens"]:
                s += 2
            elif t in sk["desc_tokens"]:
                s += 1
        if s:
            scored[name] = scored.get(name, 0) + s
    # kuratorska mapa spustacov (cross-language, silny rucny signal)
    for rx, name, w in BOOST:
        if rx.search(msg):
            scored[name] = scored.get(name, 0) + w
    ranked = sorted(
        ((s, n, descs.get(n, "")) for n, s in scored.items()),
        key=lambda x: (-x[0], x[1]),
    )
    return [r for r in ranked if r[0] >= MIN_SCORE][:TOP_N]


def _score_refs(qtokens: set, idx, skill_names):
    """Vrat top references (score, skill, rel, desc) naprieč danymi skillmi.

    Skoruje LEN references skillov v `skill_names` (tie co uz maju signal na
    skill-urovni) + vzdy zolander/zolander-ai-companion (jadrove, casto nesu
    prevadzkovy detail). Tym sa nepretaza 131 refs pri kazdom dopyte a navrhy
    ostanu presne. Nazov suboru silny signal (+3), popis slabsi (+1). SK->EN
    expanzia rovnako ako pri skilloch.
    """
    exp_tokens = _expand_sk(qtokens) - qtokens
    always = {"zolander", "zolander-ai-companion"}
    want = set(skill_names) | always
    out = []
    for sk in idx:
        if sk["name"] not in want:
            continue
        for ref in sk.get("refs", []):
            s = 0
            for t in qtokens:
                if t in ref["fn_tokens"]:
                    s += 3
                elif t in ref["desc_tokens"]:
                    s += 1
            for t in exp_tokens:
                if t in ref["fn_tokens"]:
                    s += 2
                elif t in ref["desc_tokens"]:
                    s += 1
            if s >= REF_MIN_SCORE:
                out.append((s, sk["name"], ref["rel"], ref.get("desc", "")))
    out.sort(key=lambda x: (-x[0], x[1], x[2]))
    return out[:REF_TOP_N]


def _extract_message(payload) -> str:
    extra = payload.get("extra") or {}
    um = extra.get("user_message")
    if isinstance(um, str):
        return um
    if isinstance(um, list):  # multimodalne casti
        parts = []
        for p in um:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict):
                parts.append(str(p.get("text") or p.get("content") or ""))
        return " ".join(parts)
    if isinstance(um, dict):
        return str(um.get("text") or um.get("content") or "")
    return ""


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return  # fail-open

    if payload.get("hook_event_name") and \
       payload.get("hook_event_name") != "pre_llm_call":
        return

    msg = _extract_message(payload).strip()
    if not msg:
        return

    qtokens = _tokens(msg)
    if len(qtokens) < MIN_QUERY_TOKENS:
        return  # triviálna sprava (pozdrav a pod.) — neruš

    # stamp-guard: raz na distinct user spravu (chrani pred multi-fire + zaplavenim)
    stamp = _stamp_path(msg)
    if os.path.exists(stamp):
        return
    try:
        os.makedirs(STAMP_DIR, exist_ok=True)
        with open(stamp, "w") as f:
            f.write("1")
    except Exception:
        pass

    idx = _load_index()
    if not idx:
        return
    hits = _score(msg, qtokens, idx)
    # references-level: hlbsie navrhy naprieč skillmi co uz maju signal
    ref_hits = _score_refs(qtokens, idx, [h[1] for h in hits])
    if not hits and not ref_hits:
        return

    lines = [
        "[Zolander skill-matcher (deterministicky pre_llm_call hook) — "
        "mechanicky navrh, NIE prikaz. Over relevantnost; ak sedi, NACITAJ "
        "skill cez skill_view PRED konanim. Ak nesedi, ignoruj a konaj podla "
        "usudku:]"
    ]
    for s, name, desc in hits:
        d = (desc[:130] + "…") if len(desc) > 130 else desc
        lines.append(f"  • {name} (score {s}) — {d}")
    if ref_hits:
        lines.append("  konkretne referencie (skill_view file_path=…):")
        for s, name, rel, rdesc in ref_hits:
            d = (rdesc[:110] + "…") if len(rdesc) > 110 else rdesc
            lines.append(f"    → {name} / {rel} (score {s}) — {d}")
    print(json.dumps({"context": "\n".join(lines)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
