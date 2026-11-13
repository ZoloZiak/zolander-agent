# Notify / WhatsApp cadence — dizajnove pravidlo (2026-08-09)

## Poziadavka co sa opakuje
Veducko obcas chce: "Zolander nech kazdych X minut hlasi na WhatsApp co prave robi."
(napr. "kazdych 15 minut"). NEROB to naivne ako fixny interval "hlas cinnost".

## Preco je fixny "hlas co robis" ANTI-PATTERN na tomto stacku
- `pl.zolander.loop` (StartInterval 1200s) je BEZ LLM — len integrity -> heartbeat ->
  git sken -> dennik. Nepremysla, nekona. Hlasit "spravil som heartbeat" kazdych 15 min
  = ~96 rovnakych sprav denne.
- `pl.zolander.dream` bezi 1x o 3:00. `initiative` 2x/hod a ZAMERNE mlci ked nema navrh.
- ZIVY Zolander (co realne premysla) existuje IBA pocas Hermes session / WhatsApp gateway.
  Mimo toho niet koho by "hlasil co robi".
- Dosledok fixneho intervalu: bud 90% sprav "nic nerobim, cakam" (user sa nauci ignorovat),
  alebo — horsie — model zacne VYMYSLAT cinnost aby sprava nebola prazdna = presne ta
  halucinacia proti ktorej stoji zol_guard. Nestavaj nic co ta tlaci klamat.

## Prava otazka za poziadavkou
Veducko nechce "pipanie", chce POCIT pritomneho partaka + istotu ze Zolander zije.
Rieс to informaciou, nie spamom.

## Spravne vzory (ponukni tieto, daju sa kombinovat)
1. EVENT-DRIVEN WATCHDOG — sprava LEN pri zmene stavu: loop spadol / DB dole /
   integrity fail / novy initiative navrh / dream dokoncil konsolidaciu. Ticho = OK.
2. RIEDKY PRAVDIVY BRIEF — 1x rano (a pripadne vecer) "zijem, loop OK, N tickov,
   dream spravil X". Ciastocne uz existuje v denniky/brief_*.md.
3. ZIVA 24/7 GATEWAY — ak chce Zolandera "v loope s rukami, instruovatelneho kedykolvek"
   = Hermes WhatsApp gateway obojsmerne, NIE notify ping.

## Ak veducko TRVA na fixnom intervale
Kompromis: hlas IBA holy fakticky stav daemonov (loop bezi/nie, DB up/down, cas posledneho
heartbeatu, pocet tickov) — NIKDY vymyslenu "cinnost". A radsej hodinu nez 15 min.
Notify vrstva: toolkit/zolander_notify.py (fallback WhatsApp -> inbox.md).

## STAV: POSTAVENE (2026-08-09) — vzory 1+2 su uz zive
- `zol_brief.py` + `pl.zolander.brief` (StartCalendarInterval 8:00) — vzor 2, overene naostro.
- `zol_watchdog.py` + `pl.zolander.watchdog` (StartInterval 3600) — vzor 1, zuzeny LEN na
  infra (loop/DB/integrity), dedup cez state/watchdog_ledger.txt. Overene: pri zdravom stave mlci.
- Vzor 3 (24/7 gateway) tiez zapnuty (`hermes gateway install`, PID supervised launchd).
Detail plistov + invariantov je teraz v SKILL.md sekcii durable agenti.

## Watchdog NIE je nadbytocny aj ked bezi gateway (veducko sa pytal)
Gateway je PASIVNA — caka na spravu, sama od seba NEUPOZORNI na vypadok. Presne preto nam raz
bola DB+loop 4 dni dole a nevedeli sme to, kym sme neotvorili session. Watchdog je jedina
vrstva co povie "partak oslepol" ked sa nemas ako spytat. Preto watchdog=LEN infra (loop/DB/
integrity), gateway+brief=obsah/initiative/dream. Nedupluj medzi nimi.

## VSEOBECNA LEKCIA (prenosna): fixny status-ping = takmer vzdy zly default
Ked user pyta fixny periodicky "status ping" na proces co vacsinu casu nic nerobi -> lepsi je
event-driven watchdog (ticho=OK) + jeden riedky pravdivy suhrn, nez husty fixny interval.
Fixny interval na neaktivny proces = bud spam, alebo tlak na fabrikaciu obsahu. Pomenuj to
userovi PRED stavanim (chce "preco"+kompromisy), ponukni event-driven ako default.

---

# Operacne poznamky k /start recovery (overene 2026-08-09)

## DB dole pri starte (recall zlyha ECONNREFUSED ::1:50051)
Pricina: OrbStack daemon je vypnuty (HyperspaceDB bezi v OrbStack kontajneri `hyperspace`
na porte 50051). Fix: `open -ga OrbStack`, pockaj ~10-15s (kym nabehne docker socket),
potom `docker ps --filter name=hyperspace` ma ukazat "Up", a znova spusti recall.

## Loop tichy / INTEGRITY FAIL po edite SKILL.md (stalo znovu 4 dni)
Postup: `integrity.py check` (ukaze KTORY subor nesedi — ak len `skill`, pub+fingerprint OK,
je to NAS edit, nie utok) -> `integrity.py write` (re-baseline) -> `zolander_loop.py`
(ma prejst cisto) -> over `state/heartbeat.txt` ze ts je cerstvy. Loop je fail-closed:
pri mismatch nerobi NIC (ziaden heartbeat), takze kazdy edit SKILL.md ho zmrazi az do write.

## POZOR pri curator/skill-update passe (obmedzeny kontext)
SKILL.md je integrity-chraneny. Patchnut ho v passe kde NIE je terminal (nedas integrity.py
write) = ticho rozbijes loop na INTEGRITY FAIL. Preto: nove ucenie davaj do references/
(nechranene), a jednoriadkovy pointer do SKILL.md + re-baseline rob az v zivej session
s terminalom. cmd-guard blokuje retazenie &&/||/; (jeden atomicky prikaz na volanie);
jednoduchy pipe `|` (echo '{...}' | python) je OK.
