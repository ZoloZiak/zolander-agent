#!/usr/bin/env node
// toolkit/zol_test_dual.mjs — Zolander dual recall green-check.
//
// Importuje buildDualRecallBlock z pluginu (TEN ISTY kod, ktory opencode
// vstreka do user spravy) a vyrenderuje blok pre test query. Vystup = presny
// format injektu, takze vidis co zobrali A a co B bez spustenia session.
//
// Green-check pravidla:
//   exit 0  = format OK (hlavicka, RECALL A statovy riadok, RECALL B statovy riadok)
//   exit 1  = poruseny format (chyba v pluginu/konfiguracii)
// Poznamka: B "NEDOSTUPNY (server nedostupny...)" je LEGITIMNY stav, ked
// HyperspaceDB nebezi — test kontroluje format a pravdivost znamenia, nie
// dostupnost servra.
//
// Spustenie: node toolkit/zol_test_dual.mjs "test query"
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.dirname(here);
process.env.ZOLANDER_ROOT = root;

const { buildDualRecallBlock } = await import("./zol_recall_dual.mjs");

const query = process.argv.slice(2).join(" ") || "dual recall test query";
const block = buildDualRecallBlock(root, query || undefined);

console.log(block);

const failures = [];
if (!block.includes("[Zolander DUAL RECALL — A/B test]")) failures.push("chyba hlavicka DUAL RECALL");
if (!block.includes("--- RECALL A (")) failures.push("chyba RECALL A riadok");
if (!block.includes("--- RECALL B (")) failures.push("chyba RECALL B riadok");
if (block.includes("RECALL A") && !/(PRAZDNY|NEDOSTUPNY|\d+ hitov)/i.test(block.split("--- RECALL A (")[1].split("---")[0])) {
  failures.push("RECALL A nema statovy riadok (PRAZDNY/NEDOSTUPNY/n hitov)");
}
if (block.includes("RECALL B") && !/(PRAZDNY|NEDOSTUPNY|\d+ hitov)/i.test(block.split("--- RECALL B (")[1].split("---")[0])) {
  failures.push("RECALL B nema statovy riadok (PRAZDNY/NEDOSTUPNY/n hitov)");
}
for (const bad of ["null", "[object Object]", "undefined (s "]) {
  if (block.includes(bad)) failures.push('kontaminacia v injekte: "' + bad + '"');
}

if (failures.length) {
  console.error("\n[DUAL RECALL TEST] FAIL: " + failures.join(" | "));
  process.exit(1);
}
console.error("\n[DUAL RECALL TEST] OK — format injektu je valídny (stav B visi na serveri).");
