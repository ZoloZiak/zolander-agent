// toolkit/zol_recall_dual.mjs — Dual recall logika (RECALL A vs RECALL B).
//
// Pure helpers, ziadny opencode- zavise na nich plugin ZOLANDER aj
// green-check test zol_test_dual.mjs (takze test spusta presne ten isty kod,
// ktory opencode vstreka do LLM vstupu).
//
// Recall A = lexikalna L0 (mem_light.py): keyword prekryv + recencia, stdlib.
// Recall B = semanticka lorentz (zol_mem_text.py): HyperspaceDB server-side
//            embedding (YARlabs v5, dim 129), InsertText/SearchText gRPC.
// Oba nad ROVNAKYM query textom. Fail-open: kazda chyba sa premenuje na
// poctive NEDOSTUPNY znamenie v bloku, nie crash agenta.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const MAX_PLAN_CHARS = 2500;
export const MAX_BLOCK_A_CHARS = 3000;
export const MAX_BLOCK_B_CHARS = 3000;
export const RECALL_TIMEOUT_MS = 20000;
export const QUERY_MAX_CHARS = 600;
export const TOPK = 5;

export function pythonExe() {
  if (process.env.ZOLANDER_PYTHON) return process.env.ZOLANDER_PYTHON;
  const venv = path.join(os.homedir(), ".venv-zolander", "Scripts", "python.exe");
  return fs.existsSync(venv) ? venv : "python";
}

export function hsEnv(root) {
  return {
    ...process.env,
    ZOLANDER_ROOT: root,
    HS_SDK_PATH: process.env.HS_SDK_PATH || path.join(os.homedir(), "hyperspace-db", "sdks", "python"),
    HYPERSPACE_HOST: process.env.HYPERSPACE_HOST || "localhost:50051",
    HYPERSPACE_API_KEY: process.env.HYPERSPACE_API_KEY || "I_LOVE_HYPERSPACEDB",
  };
}

export function clip(text, maxChars) {
  if (!text) return null;
  const t = String(text).trim();
  if (!t) return null;
  return t.length <= maxChars ? t : t.slice(0, maxChars) + " …[orezane]";
}

function runPy(root, args, extra) {
  try {
    const stdout = execFileSync(pythonExe(), args, {
      cwd: root,
      env: hsEnv(root),
      encoding: "utf8",
      timeout: RECALL_TIMEOUT_MS,
      windowsHide: true,
      ...extra,
    });
    return { ok: true, stdout };
  } catch (err) {
    const why = String(err?.stderr || err?.message || err).slice(0, 300);
    return { ok: false, error: why };
  }
}

function parseJson(stdout) {
  try {
    return JSON.parse(stdout);
  } catch {
    return null;
  }
}

// --- RECALL A: lexicka L0 (mem_light.py recall --query) ---
export function recallA(root, query) {
  const r = runPy(root, [path.join(root, "toolkit", "mem_light.py"), "recall", "--query", query, "--topk", String(TOPK)]);
  if (!r.ok) return { header: "NEDOSTUPNY (chyba pythonu: " + (clip(r.error, 200) || "?") + ")", lines: [], engine: "light-lexical-v1" };
  const data = parseJson(r.stdout);
  if (!data) return { header: "NEDOSTUPNY (nevalidny JSON vystup)", lines: [], engine: "light-lexical-v1" };
  const hits = Array.isArray(data.hits) ? data.hits : [];
  if (!hits.length) {
    return { header: data.empty ? "PRAZDNY (ziadna L0 pamat)" : "PRAZDNY (ziaden keyword prekryv)", lines: [], engine: "light-lexical-v1" };
  }
  const lines = hits.map((h) => {
    const tag = [h.kind, h.layer, "conf " + h.confidence].join("/");
    return "• (s " + h.score + " " + tag + ") " + (h.text ?? "");
  });
  return { header: hits.length + " hitov", lines, engine: "light-lexical-v1" };
}

// --- RECALL B: semanticka lorentz (HyperspaceDB server-side embedding) ---
function parseJsonRelaxed(stdout) {
  // SDK (client.py) pri RPC chybe printuje "RPC Error: ..." na stdout pred
  // JSON (exit 0) — parser preto ignoruje vsetko pred prvym '{'.
  const i = typeof stdout === "string" ? stdout.indexOf("{") : -1;
  if (i < 0) return null;
  try {
    return JSON.parse(stdout.slice(i));
  } catch {
    return null;
  }
}

function isServerError(text) {
  return /RPC Error|UNAVAILABLE|refused|Connect|timeout|InactiveRpcError/i.test(String(text));
}

export function recallB(root, query) {
  const r = runPy(root, [path.join(root, "toolkit", "zol_mem_text.py"), "recall"], { input: JSON.stringify({ query, topk: TOPK }) });
  if (!r.ok) {
    const flat = (r.error || "").replace(/\s+/g, " ").trim();
    const short = isServerError(flat)
      ? "server nedostupny (localhost:50051 — HyperspaceDB nebezi vo WSL?)"
      : clip(flat, 200) || "(neznama chyba)";
    return { header: "NEDOSTUPNY (" + short + ")", lines: [], engine: "lorentz-server-v1" };
  }
  const data = parseJsonRelaxed(r.stdout);
  if (!data) return { header: "NEDOSTUPNY (nevalidny JSON vystup)", lines: [], engine: "lorentz-server-v1" };
  if (data.ok === false) {
    const err = clip(data.error, 200) || "(neznama RPC chyba)";
    const short = /status = StatusCode.UNAVAILABLE|refused|Connect|timeout/i.test(err)
      ? "server nedostupny (localhost:50051 — HyperspaceDB nebezi vo WSL?)"
      : err;
    return { header: "NEDOSTUPNY (" + short + ")", lines: [], engine: "lorentz-server-v1" };
  }
  const hits = Array.isArray(data.hits) ? data.hits : [];
  if (!hits.length) return { header: "PRAZDNY (ziadne semanticke zhody)", lines: [], engine: "lorentz-server-v1" };
  const lines = hits.map((h) => {
    const tag = [h.kind, h.layer, "conf " + (h.confidence ?? "?")].join("/");
    const score = h.distance != null ? "d " + Number(h.distance).toFixed(3) : (h.score ?? h.similarity ?? "?");
    const text = h.document ?? h.text ?? "";
    if (!text) return "• (s " + score + " " + tag + ") (bez plaintextu — stary zapis pred text-in-metadata fix)";
    return "• (s " + score + " " + tag + ") " + clip(text, 220);
  });
  return { header: hits.length + " hitov", lines, engine: "lorentz-server-v1" };
}

export function tailPlan(root) {
  try {
    const p = path.join(root, "state", "PLAN.md");
    if (!fs.existsSync(p)) return null;
    const text = fs.readFileSync(p, "utf8").trim();
    if (!text) return null;
    return text.length <= MAX_PLAN_CHARS ? text : text.slice(-MAX_PLAN_CHARS);
  } catch {
    return null;
  }
}

export function buildDualRecallBlock(root, queryText) {
  const query = clip(queryText, QUERY_MAX_CHARS) || "";
  const a = recallA(root, query);
  const b = recallB(root, query);
  const linesA = a.lines.slice(0, Math.max(1, Math.floor(MAX_BLOCK_A_CHARS / 120)));
  const linesB = b.lines.slice(0, Math.max(1, Math.floor(MAX_BLOCK_B_CHARS / 120)));
  const parts = [
    '[Zolander DUAL RECALL — A/B test] Query: "' + (query || "(prazdna user sprava)") + '"',
    "",
    "--- RECALL A (lexikalna L0, engine " + a.engine + ") — " + a.header + " ---",
    ...linesA,
    "",
    "--- RECALL B (semanticka lorentz, engine " + b.engine + ") — " + b.header + " ---",
    ...linesB,
    "",
    "(Toto je VSTUP do LLM od recall-ov A/B, nie skor zapis. Pri citani zapametaneho vyznac odkial: A alebo B.)",
  ];
  const plan = tailPlan(root);
  if (plan) parts.push("", "PLAN.md (chvost):\n" + plan);
  return parts.join("\n");
}
