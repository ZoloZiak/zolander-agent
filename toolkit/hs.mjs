#!/usr/bin/env node
// hs.mjs — tenký CLI most k HyperspaceDB cez oficiálne SDK.
// Rieši proto/gRPC za nás; embeddingy prichádzajú HOTOVÉ z Pythonu (fastembed).
//
// Použitie (JSON cez stdin/args):
//   node hs.mjs list
//   node hs.mjs create <collection> <dim> [metric]        (metric: cosine|l2|poincare|lorentz)
//   node hs.mjs delete <collection>
//   node hs.mjs insert <collection>                       (stdin: JSONL {id, vector, meta})
//   node hs.mjs search <collection> <topK>                (stdin: JSON {vector:[...]})
//   node hs.mjs get <collection> <id1,id2,...>
//   node hs.mjs stats <collection>
//
// ENV: HYPERSPACE_HOST (default localhost:50051), HYPERSPACE_API_KEY (default '')

import { HyperspaceClient } from '/Users/__USER__/.npm/_npx/9e13365ae4a6529c/node_modules/hyperspace-sdk-ts/dist/client.js';

const HOST = process.env.HYPERSPACE_HOST || 'localhost:50051';
const KEY = process.env.HYPERSPACE_API_KEY || '';

function readStdin() {
  return new Promise((resolve) => {
    let d = '';
    process.stdin.setEncoding('utf-8');
    process.stdin.on('data', (c) => (d += c));
    process.stdin.on('end', () => resolve(d));
    if (process.stdin.isTTY) resolve('');
  });
}

async function main() {
  const [cmd, ...args] = process.argv.slice(2);
  const c = new HyperspaceClient(HOST, KEY);
  try {
    if (cmd === 'list') {
      console.log(JSON.stringify(await c.listCollections()));
    } else if (cmd === 'create') {
      const [col, dim, metric = 'cosine'] = args;
      const schema = { components: [{ name: 'default', metric, fullDimension: Number(dim), weight: 1 }], cascadePipeline: [] };
      console.log(JSON.stringify({ created: await c.createCollection(col, schema) }));
    } else if (cmd === 'delete') {
      console.log(JSON.stringify({ deleted: await c.deleteCollection(args[0]) }));
    } else if (cmd === 'insert') {
      const col = args[0];
      const raw = await readStdin();
      const lines = raw.split('\n').map((l) => l.trim()).filter(Boolean);
      let n = 0;
      for (const line of lines) {
        const { id, vector, meta } = JSON.parse(line);
        const m = {};
        if (meta) for (const k of Object.keys(meta)) m[k] = String(meta[k]);
        await c.insert(id, vector, m, col);
        n++;
      }
      console.log(JSON.stringify({ inserted: n }));
    } else if (cmd === 'search') {
      const [col, topK = '10'] = args;
      const { vector } = JSON.parse(await readStdin());
      const res = await c.search(vector, Number(topK), col);
      console.log(JSON.stringify(res.map((r) => ({ id: r.id, distance: r.distance, meta: r.metadata }))));
    } else if (cmd === 'get') {
      const col = args[0];
      const ids = args[1].split(',').map(Number);
      console.log(JSON.stringify(await c.getPoints(ids, col)));
    } else if (cmd === 'stats') {
      console.log(JSON.stringify(await c.getCollectionStats(args[0])));
    } else {
      console.error('unknown cmd: ' + cmd);
      process.exit(2);
    }
  } catch (e) {
    console.error('ERR ' + (e && e.message ? e.message : String(e)));
    process.exit(1);
  } finally {
    c.close?.();
  }
}
main();
