# StarNet station wired to Palantir Opus (port 8799)

StarNet (`androoAGI/starnet`, MIT, repo v ~/projects/starnet, branch feat/harness-backend)
bezi ako Zolo-stanica na porte **8799** (8787 = palantir-gate, nedotykat). Durable pod launchd
`pl.zolander.starnet` (plist ~/Library/LaunchAgents/, keepalive+runatload). Spusta ho
`start-zolander.js` (shell-safe launcher, cita PALANTIR_TOKEN sam z ~/.zsh_secrets, token NIKDY v argv).

## Prepoj na mozog = anthropic provider cez gate
StarNet `anthropic` provider posiela x-api-key + anthropic-version + POST {baseUrl}/messages.
Launcher nastavi env:
- `ANTHROPIC_BASE_URL=http://127.0.0.1:8787/anthropic/v1` (gate konvertuje x-api-key->Bearer,
  prepend /api/v2/llm/proxy -> Palantir Opus, ta ista cesta ako Hermes).
- `ANTHROPIC_API_KEY=<PALANTIR_TOKEN>`. Single-token passthrough: server MUSI niest token.
`providerRuntimeKey('anthropic', body.key)` (index.js:2225) padne na env ked telo nema kluc ->
server vie bezat anthropic z prehliadaca BEZ toho aby user cokolvek napisal. OVERENE: gate
_gate/stats counter modelu `ri.language-model-service..language-model.anthropic-claude-4-8-opus`
skoci +1 na kazdy /api/run aj /v1 beh.

## PASCA: cisty prehliadac = connect screen (preco "nova session nesla")
Server ma kluc, ale PREHLIADAC ma prazdny localStorage -> UI si mysli ziadny provider nie je
"connected" a nuti "connect a service", hoci sidecar vie bezat. Riesenie = **DEV fast-path**:
sidecar s `STARNET_DEV=1` injektne do index.html `window.__STARNET_DEV__={model,prov,hasKey}`
(index.js ~22745, serveStatic). harness.js cita DEV -> configured() true, hasStoredCredential
true ked DEV.prov sedi -> ziadny connect screen, fresh origin auto-resume.
POZOR: stock payload mal natvrdo `prov:'openrouter'`. Patch: cita `STARNET_DEV_PROVIDER` +
`STARNET_DEV_MODEL` z env (launcher seedne anthropic + Opus), hasKey = providerRuntimeKey(prov)!=''.

## PASCA: DEV mode odmietne canonical workspace (DEV_WORKSPACE_PROTECTED)
Zapnutie DEV=1 sposobi ze sidecar ODMIETNE default workspace (.../ai.skynet.harness/workspaces)
s kodom DEV_WORKSPACE_PROTECTED a crash-loopuje (+ pri jednom boote quarantinoval roster do
workspace-quarantine/). NUTNE dat dedikovany workspace: launcher nastavi
`STARNET_WORKSPACES=.../ai.skynet.harness/zolander-station`. Roster (agent.roster.json) zije TAM.

## Roster / tim
POST /api/roster (header `X-StarNet-Token: <STARNET_API_TOKEN>`) nahradi CELY roster; telo
`{agents:[...], updatedAt:<ms>}`, agents[0] = hero 'agent' (Overseer, nezmazatelny). Kazdy agent:
{agentId(^[A-Za-z0-9_-]{1,40}$), name, model, provider:'anthropic', role:<specialty id>,
approvalMode:'ask', executionProfile:'station-gear', skills:[], system:<prompt>}. role = id zo
shared/specialties.js (strategist/chief/researcher/analyst/treasurer/negotiator/jobhunter/
opportunist/...). Persist fsync-durable + .bak, prezije restart. GET /api/roster = 'not found'
(je POST-only); roster citaj cez `/v1/models` (bearer STARNET_API_KEY) alebo priamo subor.
Suceasny tim (7): Overseer, Zolander, Researcher, Treasurer, Negotiator, Job Hunter, Sourcing Scout.

## Connect hodnoty pre usera
- UI: http://127.0.0.1:8799 (DEV auto-resume, ziadny connect screen)
- OpenAI-compat API: POST http://127.0.0.1:8799/v1/chat/completions, `Authorization: Bearer
  <STARNET_API_KEY>` (launcher: zolander-local-v1-key-8799), model = nazov agenta (napr 'zolander').
- Interny /api token (skriptovanie /api/*): header X-StarNet-Token = STARNET_API_TOKEN
  (zolander-local-api-token-8799).
- Log: ~/.hermes/logs/starnet.log. Restart: launchctl kickstart -k gui/501/pl.zolander.starnet.

## Deps / sparse checkout
Proxy strihá dlhe git/curl streamy -> blob:none partial clone + sparse-checkout po
malych podstromoch (`sparse-checkout add`, NIE `set` s `/*`), resume z .git cache. Na disku:
sidecar shared frontend/{app,js,css,assets/{fonts,brand,sprites},*.html}. npm deps (--no-save,
cache ~/.hermes/cache/scratch/npm-cache): ajv undici node-pty — INSTALUJ VSETKY NARAZ jednym
prikazom, inak sa navzajom prunu. node-pty: prebuilt pty.node funguje pod homebrew node 26 (ABI
OK, ziadny rebuild); npm blokuje install-scripts (allowScripts policy) ale binar uz je v tarbale.
Tazke assety (industrial/agent-demo/agent-animation-0914/skin-study) = dev artefakty, zive UI ich
NEVOLA (overene: 276/276 index.html refov = 200 bez nich). node = /Users/__USER__/Applications/homebrew/bin/node
(stabilna cesta pre launchd, NIE Hermesov bundled node co zmizne pri update).
