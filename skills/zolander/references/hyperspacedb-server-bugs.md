# HyperspaceDB — serverové bugy + mazanie (OVERENÉ 2026-08-08)

Zistené pri migrácii Zolanderovej pamäte 4 kolekcie → 1 (`zol_mem`).
Doplnok k ziak-local-ai-stack §4 (tá skill je pinned, preto detail žije tu).

## Čo (ne)funguje na tejto verzii servera (glukhota/hyperspace-db, OrbStack :50051)
- `list` (listCollections) FUNGUJE spoľahlivo → názov + count + schema. **Count ber odtiaľto.**
- `search` (hotový vektor) + `insert` FUNGUJÚ spoľahlivo.
- **`getPoints` AJ `getCollectionStats` halúcia `5 NOT_FOUND: Collection not found`**
  aj na kolekcii, ktorú `list` práve videl. To je SERVEROVÝ BUG, NIE že kolekcia chýba.
  Testované cez MCP `hyperspacedb` aj cez Node SDK (hs.mjs) — obe padajú rovnako.
  Rovnaká trieda bugu ako MCP text-write/text-search.
- Dôsledok: NEČÍTAJ vektory cez getPoints (nedajú sa spoľahlivo dostať von); stats
  rob cez `list` (nájdi kolekciu podľa name, vezmi count), nie cez getCollectionStats.

## Záloha / migrácia keď sa vektory nedajú čítať
- Vektory sa z DB nedajú vytiahnuť 1:1 (getPoints padá). Preto: **zálohuj TEXTY**
  cez `search` s neutrálnym dotazom (topK vysoké), a pri migrácii **RE-EMBEDNI text
  nanovo** — pre fakty <300 znakov je vektor prakticky identický, reálne to nevadí.
- `search` nevracia deterministicky VŠETKY záznamy naraz → na malý objem dozbieraj
  viacerými dotazmi (rôzne query) a zjednoť podľa id. (Pri migrácii 25 záznamov
  vrátil recall 22 → 3 procedurály chýbali, dozbierané ďalšími dotazmi.)

## Mazanie bodu — hs.mjs `del` (pridané 2026-08-08)
- `node hs.mjs del <collection> <id>` → SDK `client.delete(id, col)`. Maže jeden bod.
  (V hs.mjs pridaný nový príkaz `del`; SDK metóda `delete(id, collection)` existovala.)
- Server robí **SOFT-DELETE**: `count` v `list` sa PO delete NEZMENŠÍ hneď, ale `search`
  zmazaný záznam UŽ NEVRÁTI. **Over mazanie cez recall/search, NIE cez count.**
- Trvalé uvoľnenie miesta až `vacuum`.
- Pri automatickom mazaní (dedup): najprv `del`, a AŽ PO úspešnom del zapíš recovery
  stopu (trash) — inak by trash mal záznam, čo v DB ostal (false recovery).

## 4. TOMBSTONE-ON-REINSERT — `insert` cez soft-delete ID TICHO prepadne (OVERENE 2026-08-30)
Najzakernejsi z tejto triedy. Ked ID bolo raz `del`-nute (soft-delete tombstone), a ty
spravis `insert` na TO ISTE ID, server vrati `{"inserted": 1}` — ALE bod tam NIE JE.
`get`/`search` ho nenajde ani na distance 0 k vlastnemu vektoru. Insert hlasi uspech,
realita je prazdna. Namerane naostro: 472/535/541/621 sa "pridali" (`inserted:1`), ale
chybali; `del` pred insertom vratil `{"deleted": true}` (= lezal tam tombstone), a AZ
potom insert realne pristal.

**Obidenie = DEL-PRED-INSERT.** Pred kazdym insertom sprav `del` toho ID:
- na NOVOM/zivom ID je `del` lacny no-op,
- na tombstone ho vycisti, takze nasledny insert realne pristane.
Toto je zabudovane v `toolkit/mem_store.py` -> `hs_insert_clean()` (put/sync/batch add).
NIKDY nerob holy `hs insert` na pamat — vzdy cez chokepoint.

**Dosledok pre sebakontrolu:** insert-report NIE JE dokaz pritomnosti. Over cez
deterministicky per-ID self-query (nie nedeterministicky batch-search, ten falosne
hlasi "chyba"). SYNCED flag musi kontrolovat OBE strany (navyse AJ chyba).

## Chokepoint vrstva — `toolkit/mem_store.py` (postavene 2026-08-30, commit 203a57d)
JEDNA vrstva PRED oboma kolekciami, nech uz nikdy nedriftuju. Kazdy put/delete ide cez nu:
- `put(id, text, meta)` -> del-pred-insert do `zol_mem` (Lorentz, autorita) + `zol_mem_gemma`
  (cosine, cez daemon :8901) + append do indexu. Lorentz MUSI prejst; ak Gemma zlyha (daemon
  dole), zaznam ide do REPAIR fronty — NIE do ticheho `except: pass` ako kedysi.
- `delete(id)` -> del z oboch kolekcii + oznac v indexe/trash.
- `sync()` -> zosuladi obe kolekcie s indexom (INDEX = jedina autorita): zmaze duchov
  (`gem_ids - idx_ids`, resp. lor), doplni chybajuce cez del-pred-insert. Idempotentny.
- **INDEX je jedina autorita. TRASH je len archiv, NIE mazaci prikaz.** Ghost = v DB a NIE
  v indexe. Zaznam co je v indexe (zivy) sa NIKDY nemaze, aj keby historicky presiel trashom.
  (Moja chyba: `(trash & gem)` ako ghost-podmienka mi skoro zmazala identity 382/631 -> PROTECT.)
- `zol_mem.remember()` prevleceny cez `put()`. `zolander_dream.py` vola `sync()` po kazdom
  noc­nom cykle -> drift sa dobehne sam, drzi 429/429 (lorentz/gemma) stale.

## YAR Lorentz 129d na DEDUP — len near-exact, NIE parafrázy
Namerané na reálnych dátach (zol_mem):
- presná kópia textu → Lorentz distance ~0.0
- PARAFRÁZA toho istého faktu → d ~1.0 — ĎALEJ než nesúvisiaci fakt (d ~0.99)!

### Reconcile / desync audit — pasce (memory-distillation 2026-08-30, OVERENE)
- **DELETE VZDY z Lorentz `zol_mem` AJ z `zol_mem_gemma`.** Kto maze len z jednej ->
  ZOMBIE (mrtvy v jednej, zivy v druhej; BM25/Gemma ho stale serviruje). `dedup_dream._del_point`
  mal tento bug (mazal len Lorentz) -> fixnute nech maze obe. Rovnako kazdy rescue/cleanup skript.
- **Self-search NIE JE test zivosti.** Re-embednut text zaznamu a hladat ho v Lorentz NEDOKAZE
  ze je mrtvy ked sa nevrati — YAR je slaby na parafrazu (~52%), kratky abstraktny L1/L3 princip
  sa nevrati ani na VLASTNY text (zhluk podobnych). Test zivosti = je v indexe? je v trash? (deterministicke),
  NIE self-search.
- **reconcile zombie = `gem_ids - lor_ids - trash_ids - idx_ids`.** Podmienka `- idx_ids` je
  KRITICKA: index je autorita o tom co MA zit. Ak je zaznam v indexe AJ v Gemma, je ZIVY a
  "chyba v Lorentz union" je len false-positive neuplneho nedeterministickeho searchu. Bez `- idx_ids`
  guard falosne krical zombie na zive principy pri KAZDOM behu (vlk-vlk -> bezcenny guard).
- **DB count z `list` je NAFUKNUTY soft-deletmi + medzerami.** 610 count = ~523 zivych. Realny pocet
  = index (enumerovatelny). "DB - index = N stratenych" je ILUZIA count-aritmetiky; realna strata =
  len ORPHANY (zive v DB, chybaju v indexe) = vlozene priamym `hs insert` mimo `cmd_remember`.
- Nastroj: `toolkit/reconcile_guard.py` (detektor tichého driftu, EXIT=2 pri drifte, `--fix` dopise
  orphanov do indexu). Bezi solo alebo v dream loope.

YAR rozlíši len takmer-identický text; sémantické parafrázy nie (v súlade so §10
stack-skillu: YAR slabý na význam). Dôsledok pre dedup → dve vrstvy:
1. WRITE gate cez embedding chytí LEN presné kópie (prah d<0.15).
2. Parafrázy MUSÍ riešiť LLM (opus dostane celý malý zoznam, nájde skupiny) — NIE
   vyberať kandidátov vzdialenosťou, YAR by ich minul. Opus-dedup je nedeterministický
   → postupný nočný proces, nie jednorazová čistka.

## Desync počítadiel + orphany + zombie (OVERENÉ 2026-08-30, Bug 1 z memory-distillation)

Pamäť žije v TROCH skladoch na ten istý fakt: DB `zol_mem` (Lorentz 129D), DB
`zol_mem_gemma` (cosine 768D), a `state/mem_index.jsonl` (BM25 lane + decay). Keď sa
rozejdú, časť recall lanes oslepne. Tri pasce namerane naostro:

### 1. `count` z `list` je NAFÚKNUTÝ — NIE je to počet živých záznamov
Soft-delete count neznижuje, plus `next_id()` páli ID pred dedup gate (diery). Preto
`DB count − index count` NIE je "počet stratených spomienok" — je to count-aritmetika
klamuca cez duchov. Namerané: `list` hlásil zol_mem=610, ale reálny `search` union vrátil
len ~523 živých (83 soft-deleted duchov + ~129 dier v ID). **Reálny počet živých = union
viacerých `search` dotazov, NIE count.** Neštrukturuj opravu na count-rozdiele.

### 2. Orphan = záznam v DB, ale NIE v `mem_index.jsonl` → slepý pre BM25/decay
Signatúra: priamy `hs insert` obchádza `cmd_remember` → zapíše do DB, ale preskočí
index (a HMAC podpis). Namerané: ID 397–405 boli v oboch DB kolekciách ale nie v indexe;
z toho reálny osobný fakt (gabber/hardcore) bol pre BM25 **úplne neviditelny**. Detekcia:
`toolkit/audit_desync.py` (index IDs vs DB-search union). Nikdy nepoužívaj priamy
`hs insert` na pamäť — vždy cez `cmd_remember`.

### 3. ZOMBIE — pri mazaní maz z OBOCH DB kolekcií, nie len z jednej (moja chyba 2026-08-30)
`del zol_mem <id>` NEZMAŽE z `zol_mem_gemma`. Keď zmažeš orphan len z Lorentz, ostane
živý v Gemma = zombie (mŕtvy v jednom lens, živý v druhom). Navyše nový záznam si naňho
môže natiahnuť `related` hranu kým je ešte živý → visíaca hrana po zmazaní. **Maz VŽDY z
`zol_mem` AJ `zol_mem_gemma`** (viď `toolkit/cleanup_gemma_zombies.py`), a po merge/del
prejdi `mem_edges.jsonl` či nezostali hrany na mŕtve ID.
