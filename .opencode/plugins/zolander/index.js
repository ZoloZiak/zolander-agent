// Zolander plugin pre opencode — port hermes mechanizmov na opencode event hooky.
//
// Portuje tri veci z hermesu (mechanicky, nie soft substituty):
//   1. hook_recall.py (event: pre_llm_call)  -> session hook "prompt": raz na
//      prvu spravu session vstrieka do user spravy DUAL RECALL blok
//      (RECALL A lexikalna L0 + RECALL B lorentz + PLAN chvost). Logika zije
//      v toolkit/zol_recall_dual.mjs — takze green-check test spusta presne
//      ten isty kod, ktory potom vidis v injekte.
//   2. tvrde pravidla do systemu (anti-drift)  -> session hook "context".
//
// ZOLANDER_RECALL_EVERY=1 -> recall na kazdu prompt (default raz za session).
// Fail-open: ziadena chyba nesmie padnut agenta.
import { Plugin } from "@opencode/plugin";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildDualRecallBlock } from "../../../toolkit/zol_recall_dual.mjs";

function thisDir() {
  try {
    return path.dirname(fileURLToPath(import.meta.url));
  } catch {
    return process.cwd();
  }
}

function findRoot() {
  const candidates = [
    process.env.ZOLANDER_ROOT,
    path.join(os.homedir(), "zolander"),
    path.join(thisDir(), "..", "..", ".."),
  ].filter(Boolean);
  for (const dir of candidates) {
    if (fs.existsSync(path.join(dir, "toolkit", "mem_light.py"))) return dir;
  }
  return candidates[0] || process.cwd();
}

export default Plugin.define({
  id: "zolander.core",
  async setup(ctx) {
    const root = findRoot();
    const recalled = new Set(); // sessionID ktore uz dostali recall (raz per session)
    const every = process.env.ZOLANDER_RECALL_EVERY === "1";

    // --- Dual recall-first (port hermes hook_recall.py, A/B faz 2) ---
    await ctx.session.hook("prompt", (event) => {
      try {
        const sessionID = event.sessionID || "unknown";
        if (!every && recalled.has(sessionID)) return;
        recalled.add(sessionID);

        const block = buildDualRecallBlock(root, event.prompt?.text || "");
        event.prompt.text = block + "\n\n---\n\n" + (event.prompt?.text || "");
      } catch {
        // fail-open: recall je vylepsenie, nie povinnost
      }
    });

    // --- Tvrde pravidla v systemovom kontextu (anti-drift) ---
    await ctx.session.hook("context", (event) => {
      try {
        event.system.push({
          type: "text",
          text:
            "[Zolander hard foundation - z pluginu, neevaporuje s dlzkou kontextu:] " +
            "F11: ziadna lichotka, ziadne otvaracie mazivo; zacni odpoved prvym vecnym " +
            "slovom. Poctivost: odhad ako odhad, overene ako overene (confidence). " +
            "shell-safe: jeden atomicky shell prikaz, ziadne && / ; / bash -c / heredoc. " +
            "Destruktivne veci vyzaduju PRVY dotaz PRECO. " +
            "Dual recall: v injekte je RECALL A (lexikalna) a RECALL B (lorentz) — ked " +
            "citas zapamatanu vec, oznac odkial A/B. " +
            "Nepristakavaj presne-tak/skvely-napad — suhlas vzdy s dovodom alebo mlc a ries vec.",
        });
      } catch {
        // fail-open
      }
    });
  },
});
