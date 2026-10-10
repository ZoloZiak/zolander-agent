# Živý obojsmerný Zolander cez Hermes gateway (WhatsApp) — architektúra a pasce

Cieľ: __USER__ inštruuje Zolandera cez WhatsApp, Zolander koná rukami (terminal/file/…),
pamätá si a odpisuje. To NIE je notify vrstva (jednosmerné daemon->ty, tá je v skille
zolo-book-pipeline). Toto = plný agent loop na messaging platforme = **Hermes gateway**.

## KĽÚČOVÝ ROZDIEL notify vs živý agent
- **Notify** (zolander_notify.py + `hermes send`) = jednosmerné, bridge stačí spustiť dočasne.
- **Živý agent** = obojsmerné, gateway MUSÍ bežať nepretržite (inak nemá kto počúvať WhatsApp
  správy). Baileys navyše potrebuje stále bežiaci bridge. Čiže „živý Zolander na WhatsApp"
  NEVYHNUTNE znamená 24/7 gateway+node proces. __USER__ si najprv 24/7 kvôli sandbox odmietol,
  potom vedome schválil — over aktuálne želanie, nepredpokladaj.

## PASCA #1 — persona NIE JE v SOUL.md, je v skille (najväčšia pasca)
`~/.hermes/SOUL.md` sa načíta VŽDY (každá session: CLI aj gateway aj WhatsApp), NEZÁVISLE od
toho, ktorý skill si model načíta. Zolanderova identita ale pôvodne žila LEN v skille
`zolander` — ktorý sa na gateway session automaticky NENAČÍTA. Dôsledok: keby si len zapol
gateway, na WhatsApp by odpisoval GENERICKÝ Hermes bot, nie Zolander.
FIX (2026-08): jadro Zolanderovej identity (ton, „vedúcko", anti-lichôtka cannot_violate,
pravidlá, odkaz načítať plný skill) vložené priamo do SOUL.md ako blok „KTO SI — Zolander".
Plný skill ostáva zdroj pravdy; SOUL.md nesie len jadro + pokyn načítať `zolander` skill.
POZOR: integrity.py chráni SKILL.md (NIE SOUL.md), takže edit SOUL.md loop NErozbije —
re-baseline NETREBA. (Edit SKILL.md by re-baseline vyžadoval, viď durable-daemons-integrity.md.)
hook_recall.py (pre_llm_call) beží aj na gateway session -> pamäť/recall sa napoja automaticky.

## PASCA #2 — WhatsApp bridge port kolízia (3000)
Baileys bridge default `--port 3000`, ale ten drží projekt turiec-pod-lupou (Next.js dev
server, `next-server`). Adaptér (plugins/platforms/whatsapp/adapter.py r.611) pri štarte robí
`_kill_port_process(port)` -> naštartovanie bridge na 3000 by ZABILO ten Next.js server.
Príznak: `hermes send --to whatsapp` vráti „WhatsApp bridge error (500)" s Next.js HTML v tele
(request doletel na turiec, nie na bridge).
FIX: `hermes config set platforms.whatsapp.extra.bridge_port 3111`. `config.extra` sa napĺňa
LEN cez raw blok `platforms.whatsapp.extra` (gateway/config.py r.1199-1218 deep-merge), NIE
cez plugin-mapovanie `whatsapp: [hermes-whatsapp]` v platform_toolsets. Oba code-paths
(gateway aj `hermes send` _standalone_send) čítajú ten istý `config.extra.get("bridge_port",3000)`.

## PASCA #3 — `hermes send --list` prázdny bez gatewaya
Channel discovery (`~/.hermes/channel_directory.json`) sa napĺňa LEN keď raz bežal gateway.
Bez neho `hermes send --list` = prázdne, takže auto-detekcia cieľa v skriptoch zlyhá.
ALE `hermes send --to whatsapp "x"` funguje priamo cez `WHATSAPP_HOME_CHANNEL:
<cislo>@s.whatsapp.net` v config.yaml (nastav `hermes config set WHATSAPP_HOME_CHANNEL ...`).
Preto skripty maj fixný cieľ/fallback, nie auto-detekciu (viď zolander_notify ZOL_NOTIFY_FALLBACK).

## Kroky na živého Zolandera (poradie)
1. Párovanie: `hermes whatsapp` -> mód 2 (personal/self-chat) -> číslo -> QR sken mobilom.
   QR sa NEDÁ spoľahlivo preniesť cez chat (poškodené Unicode bloky + rotuje ~20s) -> user
   skenuje vo svojom termináli. Úspech = session kľúče v ~/.hermes/whatsapp/session/.
2. Persona -> SOUL.md (pasca #1).
3. Ruky: `platform_toolsets.whatsapp: [hermes-whatsapp]` UŽ dáva PLNÉ ruky — NETREBA meniť.
   OVERENÉ 2026-08 v toolsets.py r.464: `TOOLSETS["hermes-whatsapp"]["tools"] = _HERMES_CORE_TOOLS`
   (terminal/file/process/memory/delegation/code_execution/web/vision/skills/browser/todo/
   session_search/clarify/cronjob…), identické s hermes-telegram. `hermes-whatsapp` je PLATNÝ
   toolset názov, resolve_toolset() ho nájde (vráti [] len pre NEEXISTUJÚCI názov). Pozor na
   falošnú obavu: „hermes-whatsapp sa v .py nenašiel cez grep" bolo mylné — je na r.464 aj 582.
   Zmena toolsetu by sa prejavila na /reset + reštart gatewaya, ale tu netreba nič meniť.
4. Allowlist: `WHATSAPP_ALLOWED_USERS` (z párovania) — Zolander reaguje len na tvoje číslo.
   ⚠️ PASCA @lid vs číslo (2026-08): inbound správy sa v gateway.log logujú s
   `chat=<NNNN>@lid` (WhatsApp „linked device ID"), NIE s telefónnym číslom. Allowlist aj
   WHATSAPP_HOME_CHANNEL sa nastavujú na ČÍSLO (`48000000000` resp. `<cislo>@s.whatsapp.net`).
   OVERENÉ 2026-08-09 REÁLNOU SPRÁVOU: allowlist na číslo `48000000000` inbound `@lid` správu
   NEODMIETOL — prešla (gateway.log: inbound + response ready, žiadne „not allowed"). Takže
   číselný allowlist matnevhodnee @lid tvar (gateway si to interne mapuje). Napriek tomu:
   bezpečnostné tvrdenie „reaguje len na teba" NEtvrď userovi z domnienky — over gateway.log.
   Ak by v inom prostredí allowlist @lid odrezal → pridaj do WHATSAPP_ALLOWED_USERS aj @lid tvar.
5. Approvals: gateway `/approve` `/deny`. NASTAVENÉ 2026-08 (overené v kóde, config.py
   DEFAULT_CONFIG r.2625-2628, tools/approval.py): `hermes config set approvals.mode manual`
   (NIE smart — smart by pri aux-LLM „approve" verdikte schválil BEZ usera), `approvals.timeout 600`
   (10 min okno v sekundách, žiadny cap), `approvals.cron_mode deny`. timeout->DENY je FAIL-CLOSED
   a NEvypnuteľné („Silence is not consent", approval.py r.3468-3498) = presne „keď sa nevyjadrí->DENY".
   `mode: off`/yolo = obísť VŠETKO (nebezpečné); hardline rm -rf //mkfs/fork bomb blokované vždy.
6. Launch: `hermes gateway install` (launchd 24/7) alebo `hermes gateway run` (on-demand).
   Bridge port 3111 už v configu.

## 24/7 gateway je shell-safe (overené uvažovaním, viď ziak-macos-workflows)
Stály node+WebSocket (bridge) na tomto sandbox Macu NIE je porušenie. „sandbox timed out, file open,
process node, .sst" popupy sú BENÍGNE — sandbox nestíha klasifikovať rýchlo sa meniace RocksDB
segmenty Baileysu. Jediná reálna cena = občasný security-agent CPU spin / hukot ventilátora,
páka = reštart Macu. Gateway ťa nezablokuje ani nenahlási.

## POZOR na 200k kontext (__USER__ tvrdé pravidlo)
Živá WhatsApp konverzácia = JEDNA dlhá session. Pri intenzívnom používaní narastá ku 200k
limitu. Hermes má autokompresiu, ale gateway session treba občas resetnúť. Nie je to
vyriešené automaticky — ošetriť pri prevádzke.

## BEZPEČNOSŤ
Zolander cez WhatsApp má terminál na Macu __USER__. cmd-guard hook (pre_tool_call) to stráži
(rm -rf/&&/;/bash -c/heredoc/sandbox blokované). NIKDY nespúšťaj živý gateway s terminálovými
rukami, kým je __USER__ preč a nemôže potvrdiť — to je jeho stroj v cudzích rukách cez chat.

## „Reaguje pomaly / píše dlho / notifikuj čo robíš" — latencia a prezencia (2026-08-09)
Vedúcko sa sťažoval že gateway „nič nereaguje" a chcel „thinking notifikácie každých 20s".
Realita a čo sa dá:
- LATENCIA je normálna: jeden agent-turn = JEDEN blokujúci API request. Krátka odpoveď
  ~15-35s, dlhá esej (4000+ znakov) ~80s. Kým Opus myslí, na mobile je ticho -> pôsobí mŕtvo.
  Over v gateway.log `inbound message` … `response ready: time=Xs` — ak time~80s a odpoveď
  je dlhá, je to len latencia, NIE porucha. Ak správa v logu vôbec nie je → doručovací/bridge
  problém, nie latencia.
- „PING KAŽDÝCH 20s" SA NEDÁ: nemožno vsunúť medzi-správu doprostred jedného turnu, a keby
  aj → každý ping = nový API call = viac 429. Neponúkaj to.
- OPRAVA FAKTU (SKILL.md tvrdí opak — verí mu NIE): natívne „píše…" (composing presence)
  UŽ EXISTUJE a je defaultne zapnuté. Reťaz: base.py (~r.4925) `if getattr(self.config,
  "typing_indicator", True)` spustí `_keep_typing` loop → každé ~2s volá adapter
  `send_typing()` (adapter.py ~r.1185) → bridge `POST /typing` (bridge.js ~r.1029) →
  `sock.sendPresenceUpdate('composing', chatId)`. Config to nemá vypnuté (kľúč nenastavený
  = default True). Takže „Zolander píše…" má na mobile naskakovať SAMO počas spracovania —
  netreba nič dopisovať, len OVERIŤ že sa cez @lid reálne zobrazuje (Baileys presence cez
  @lid je jediná neistá časť). Ak sa nezobrazuje, až POTOM zvažuj zásah do bridge.js.
- RIEŠENIE ktoré vedúcko schválil (bod B) = ACK vzor, je v SOUL.md „WHATSAPP STYL":
  pri dlhšej úlohe Zolander HNEĎ pošle krátky ack cez send_message („Beriem, pozerám sa,
  o chvíľu…"), potom robí, na konci pošle výsledok. + STRUČNOSŤ: na WhatsApp krátko a k veci,
  dlhé eseje/kód/rozbory nechať na CLI (mobil = malá obrazovka). Oboje NEPLATÍ v CLI.
- send_message podporuje WhatsApp `@lid` cieľ natívne (send_message_tool.py _WHATSAPP_JID_RE
  pokrýva @lid|s.whatsapp.net|g.us) — ack teda vie doletieť na ten istý @lid chat.
- SOUL.md sa číta pri ŠTARTE session → zmeny SOUL.md (ack/stručnosť) platia na gatewayi
  AŽ PO RESTARTE. `launchctl kickstart -k gui/$UID/ai.hermes.gateway` (alebo `hermes gateway
  restart`) si vedúcko spúšťa SÁM — raz blokol kickstart na approval-vrstve. NErestartuj sám,
  ponúkni príkaz. SOUL.md NIE je integrity-chránený → loop tým nerozbiješ, re-baseline netreba.
