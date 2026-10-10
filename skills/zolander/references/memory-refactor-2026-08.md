# Refactor pamäte Zolandera — meranie + rozhodnutia (2026-08-14)

Kontext: papier "Calculus of Association" (Royse 2026, ~/Downloads/FormulaForAGI.pdf) inšpiroval
refactor recallu. Plán: ~/projects/zolander/denniky/refactor_plan_2026-08-14.md. Toto je destilát meraní,
aby sa neopakovali.

## Nástroje (opakovateľné, v toolkit/)
- `mem_eval.py` — Recall@1/3/5 + MRR na gold-sete, sweep W_LEX, `--rerank` pre Opus.
- `mem_eval_goldset.py` — Opus generuje gold-set parafrázou -> state/mem_eval_gold.json.
- `mem_diff.py` — differentiation contract (D1 korelácia, D2 marginálne bity) + cross-term test, 2 lensy.
- `mem_eval3.py` — 3-lens eval (YAR+BM25+Gemma), differentiation contract pre 3.
- `embed_gemma_corpus.py` — embedne korpus+gold cez EmbeddingGemma, cache do state/gemma_corpus.npz + gemma_gold.npz.
- `zol_eval_watch.py` + plist — týždenný iniciatívny watcher (regresia MRR / rast korpusu -> návrh na WA).

## KĽÚČOVÉ MERANIA (24 parafráz. gold otázok, ~318 záznamov)
Recall@1 / MRR:
- yar solo        0.38 / 0.463   <- YAR (Lorentz 129D) je SLABÝ semantický lens
- gemma solo      0.67 / 0.758   <- EmbeddingGemma 768D cosine OVEĽA lepší než YAR
- bm25 solo       0.79 / 0.861   <- lexika ťahá ťažkú prácu na tomto korpuse
- bm25+yar (starý stav)  0.83 / 0.876
- **bm25+gemma    0.83 / 0.891**  <- NOVÝ najlepší pár (lepšie R@3/R@5 = 0.96)
- all3 (+YAR)     0.83 / 0.891   <- YAR nič nepridá k bm25+gemma
- hybrid+rerank (Opus) 0.92 / 0.938  <- rerank je jediné čo dvihne R@1 nad 0.83

Differentiation contract (Royse §5.3, prahy: |corr|>0.6 redundant, bity>=0.05 drž):
- corr YAR-BM25 0.44, YAR-Gemma 0.48 (rôznorodé) ; **BM25-Gemma 0.70 (REDUNDANTNÉ)**.
- marginálne bity nad ostatné: BM25 0.029, Gemma 0.014, YAR 0.003 (malá vzorka = indikatívne).

## ROZHODNUTIA (schválené vedúckom)
- **YAR von z recall FÚZIE** (nahradí Gemma), ALE DRŽAŤ ako Lorentz geometrickú kostru pre
  Etapu 3 (memory-to-memory linky + hierarchia). Dve rôzne roly, nevyhadzovať kľúč/DB.
- **CROSS-TERM (YAR×BM25) NEZAPÁJAŤ** — meranie: nepomáha, mierne škodí.
- **RRF NEZAPÁJAŤ** — už raz zlyhalo, min-max score-fusion je meraný optimum. (Subagenti aj papiere
  RRF odporúčajú — ignoruj, naše dáta rozhodli.)
- **Kaskáda** (schválená): BM25+Gemma nahrubo -> lokálny cross-encoder (rýchly, ON aj na štarte)
  -> Opus vrchný stupeň NA POŽIADANIE (nie namiesto, ale navyše — Opus zostáva pre špičku).
- **Dream POVÝŠIŤ** z upratovača na mysliteľa: dedup/konsolidáciu duplikátov preberie write-path
  (Mem0-style UPDATE/DELETE), dream robí L2/L3 abstrakciu + linkovanie.
- **Bitemporálnosť = SPOJIŤ s memory-to-memory linkami** (Etapa 3), NIE paralelný Zep graf. Hrana
  nesie vzťah + valid-time[od,do] + supersedes. Fakt sa NEMAŽE decayom, ale "označí neplatný od X".
- **Support-check (Self-RAG)** — samostatný krok, napojiť na zol_guard (grounding).
- NEROBIŤ: MemGPT paging (Hermes rieši kontext sám), Zep graf ako infra (over-engineering na 318 zázn.).

## PROSTREDIE (pasce zistené v tejto session)
- EmbeddingGemma beží LEN cez vMLX uv-tool python `/Users/__USER__/.local/share/uv/tools/vmlx/bin/python`
  (má mlx/mlx_embeddings), 768D L2-normalizované, GPU. `~/projects/zolander/.venv-yar` mlx NEMÁ.
- venv-yar má torch 2.13 + transformers 5.0, ale NEMÁ pip ani sentence_transformers. Cross-encoder
  by vyžadoval download modelu cez proxy (HF_HUB_DISABLE_XET=1) = nová infra, treba súhlas.
- Gemma je cosine (plochá), NEDÁ sa vložiť do Lorentz kolekcie zol_mem — pre eval samostatný numpy cache.
- Papiere overené (arXiv API funguje bez SSL problémov v subagentovi): Delétang 2309.10668,
  Huang 2404.09937, Platonic 2405.07987, Meta Co-Training 2311.18083, Vincent-Lamarre 1411.0129,
  MTEB 2210.07316, CLIP 2103.00020; RRF Cormack 2009, Luan sparse/dense 2005.00181, ColBERT 2004.12832,
  monoBERT 1901.04085, RankGPT 2304.09542, MemGPT 2310.08560, Generative Agents 2304.03442,
  Mem0 2504.19413, A-MEM 2502.12110, Zep 2501.13956, Self-RAG 2310.11511.

## PRENOSNÁ LEKCIA
Papiere/subagenti dávajú HYPOTÉZY, náš gold-set + differentiation contract sú ROZHODCA. Dvakrát
v tejto session meranie zamietlo "papierom odporúčané" vylepšenie (cross-term, RRF). Každá zmena
recallu PREJDE cez mem_eval.py PRED zapojením do zol_mem. "Pripravená na všetko" (vedúcko) =
rozšíriteľný MERANÝ panel, NIE napchať všetky lensy hneď (každý lens si miesto zaslúži bitmi).
