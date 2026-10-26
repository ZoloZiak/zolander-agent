// Zolander plugin pre opencode — port hermes mechanizmov na opencode event hooky.
//
// Portuje dva veci z hermesu (mechanicky, nie soft substituty):
//   1. hook_recall.py (event: pre_llm_call)  -> session hook "prompt": raz na prvu
//      spravu session vstrieka do user spravy blok [Zolander auto-recall...]
//      (light pamat L0 z state/zol_memory.jsonl + chvost state/PLAN.md).
//      Vstreknuta sprava sa dalej sprava ako normalna user sprava.
//   2. tvrde pravidla do systemu (anti-drift)  -> session hook "context": do
//      systemoveho kontextu pushne kratky FOUNDATION blok — hard pravidla,
//      ktorych "zabudnutie" v strede dlhej session je znizene (zije v systeme).
//
// Faza 1: ziadna DB, ziaden embedder, len local state. Fail-open: ziadna chyba
// nesmie padnut agenta (recall je vylepsenie, nie povinnost).
import { Plugin } from "@opencode/plugin";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const MAX_MEM_CHARS = 6000;
const MAX_PLAN_CHARS = 2500;

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

function tailOf(file, maxChars) {
  if (!fs.existsSync(file)) return null;
  const text = fs.readFileSync(file, "utf8");
  if (!text.trim()) return null;
  const trimmed = text.trim();
  return trimmed.length <= maxChars ? trimmed : trimmed.slice(-maxChars);
}

export default Plugin.define({
  id: "zolander.core",
  async setup(ctx) {
    const root = findRoot();
    const recalled = new Set(); // sessionID ktore uz dostali recall (raz per session)

    // --- Recall-first (port hermes hook_recall.py) ---
    await ctx.session.hook("prompt", (event) => {
      try {
        const sessionID = event.sessionID || "unknown";
        if (recalled.has(sessionID)) return;
        recalled.add(sessionID);

        let planTail = null;
        let memTail = null;
        try {
          planTail = tailOf(path.join(root, "state", "PLAN.md"), MAX_PLAN_CHARS);
        } catch {
          planTail = null;
        }
        try {
          const lines = tailOf(path.join(root, "state", "zol_memory.jsonl"), 8000)
            ?.split("\n")
            .filter((l) => l.trim() !== "");
          if (lines && lines.length) {
            memTail = lines
              .map((l) => {
                try {
                  const o = JSON.parse(l);
                  return "• (" + [o.kind, o.layer, "conf " + o.confidence].join("/") + ") " + (o.text ?? "");
                } catch {
                  return "• " + l;
                }
              })
              .join("\n");
          }
        } catch {
          memTail = null;
        }

        if (!planTail && !memTail) {
          event.prompt.text =
            "[Zolander auto-recall] (prazdny - state/ bez pamati a planu; prva session, recall nepredstiera kontext.)\n\n" +
            event.prompt.text;
          return;
        }
        const parts = [];
        if (planTail) parts.push("PLAN.md (chvost):\n" + planTail);
        if (memTail) parts.push("Pamat L0 (posledne zapisy):\n" + memTail);
        const block =
          "[Zolander auto-recall] (light L0 lexical recall; hyperbolicka geometria YAR/" +
          "Lorentz je faz 2.)\n\n" +
          parts.join("\n\n");
        event.prompt.text = block + "\n\n---\n\n" + event.prompt.text;
      } catch {
        // fail-open
      }
    });

    // --- Tvrde pravidla v systemovom kontexte (anti-drift) ---
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
            "Nepristakavaj presne-tak/skvely-napad — suhlas vzdy s dovodom alebo mlc a ries vec.",
        });
      } catch {
        // fail-open
      }
    });
  },
});
