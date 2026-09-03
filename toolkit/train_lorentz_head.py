#!/usr/bin/env python3
"""train_lorentz_head.py — REALNY trening malej Lorentz hlavy na Gemma.

Odpoveda na veducko otazku: "keby sme dotrenovali hlavu na gemmu, mali by sme lepsie
vysledky pri porovnaniach?" Trenuje MLP: Gemma768 -> Lorentz H^d (uci SMER aj POLOMER,
nielen radialnu hlavu), contrastive na parent-child hierarchii.

KLUC NEPRIESTRELNOSTI = cross-lab protokol: train na hierarchii labu A, test na labe B,
DISJUNKTNE deti (train deti nikdy nevidi v teste). Ak aj tak bije flat cosine -> embedder
realne pomaha, ideme trenovat poriadne. Ak nie -> rozmazana ground truth je strop
(hlava sa nauci lab-specific blur, negeneralizuje). Multi-seed (nie jeden hod).

Ziadne LLM volania. Cita geom_data.json (Gemma) + gold_pairs_*.jsonl. Nic nezapisuje do produkcie.
"""
import os, sys, json, math, random
import torch
import torch.nn as nn

STATE = os.path.expanduser("~/projects/zolander/state")
data = {int(k): v for k, v in json.load(open(os.path.join(STATE, "geom_data.json"))).items() if "gemma" in v}
GEMMA = {i: torch.tensor(data[i]["gemma"], dtype=torch.float32) for i in data}
DIM_IN = len(next(iter(GEMMA.values())))

GOLDS = {"opus": "gold_pairs.jsonl", "gpt": "gold_pairs_gpt.jsonl",
         "gemini": "gold_pairs_gemini.jsonl"}

def load_gold(path):
    out = []
    for l in open(os.path.join(STATE, path), encoding="utf-8"):
        l = l.strip()
        if l:
            g = json.loads(l)
            if g.get("parents"):
                out.append(g)
    return out

# deterministicky split detI (seed=29 => vsetky laby maju rovnake deti vdaka fixnemu seedu v gold_construct)
all_children = sorted({g["child"] for g in load_gold("gold_pairs.jsonl")})
_r = random.Random(29); _r.shuffle(all_children)
n_tr = int(len(all_children) * 0.67)
TRAIN_CH = set(all_children[:n_tr]); TEST_CH = set(all_children[n_tr:])

def lorentz_from_space(x):
    x0 = torch.sqrt(1.0 + (x * x).sum(-1, keepdim=True))
    return torch.cat([x0, x], -1)

def lorentz_dist(a, b):
    prod = -a[..., 0] * b[..., 0] + (a[..., 1:] * b[..., 1:]).sum(-1)
    return torch.acosh(torch.clamp(-prod, min=1.0 + 1e-6))

class Head(nn.Module):
    def __init__(self, din, dh, dout):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(din, dh), nn.ReLU(), nn.Dropout(0.2),
                                 nn.Linear(dh, dout))
    def forward(self, x):
        return lorentz_from_space(self.net(x) * 0.3)

def auroc(pos, neg):
    if not pos or not neg: return None
    c = t = 0
    for p in pos:
        for n in neg:
            if p > n: c += 1
            elif p == n: t += 1
    return (c + 0.5 * t) / (len(pos) * len(neg))

def cos(a, b): return float((a * b).sum())

def eval_flat(gold, children):
    aus = []
    for g in gold:
        if g["child"] not in children: continue
        c = g["child"]; pool = [p for p in g["pool"] if p in GEMMA and p != c]
        gset = set(g["parents"]) & set(pool)
        if not gset or len(pool) < 2: continue
        sc = {p: cos(GEMMA[c], GEMMA[p]) for p in pool}
        a = auroc([sc[p] for p in gset], [sc[p] for p in pool if p not in gset])
        if a is not None: aus.append(a)
    return (sum(aus) / len(aus) if aus else float("nan")), len(aus)

def eval_head(head, gold, children):
    head.eval(); aus = []
    with torch.no_grad():
        for g in gold:
            if g["child"] not in children: continue
            c = g["child"]; pool = [p for p in g["pool"] if p in GEMMA and p != c]
            gset = set(g["parents"]) & set(pool)
            if not gset or len(pool) < 2: continue
            ec = head(GEMMA[c].unsqueeze(0))
            ep = head(torch.stack([GEMMA[p] for p in pool]))
            d = lorentz_dist(ec, ep)
            sc = {p: -float(d[i]) for i, p in enumerate(pool)}
            a = auroc([sc[p] for p in gset], [sc[p] for p in pool if p not in gset])
            if a is not None: aus.append(a)
    return (sum(aus) / len(aus) if aus else float("nan")), len(aus)

def train(gold_train, children, seed, dim=16, hidden=128, epochs=300, lr=1e-3, wd=1e-4):
    torch.manual_seed(seed); random.seed(seed)
    head = Head(DIM_IN, hidden, dim)
    opt = torch.optim.Adam(head.parameters(), lr=lr, weight_decay=wd)
    inst = []
    for g in gold_train:
        if g["child"] not in children: continue
        c = g["child"]
        pool = [p for p in g["pool"] if p in GEMMA and p != c and p not in TEST_CH]
        gset = [p for p in g["parents"] if p in pool]
        if gset and len(pool) >= 2:
            inst.append((c, gset, pool))
    if not inst: return head, 0
    for ep in range(epochs):
        head.train(); random.shuffle(inst)
        opt.zero_grad(); loss_acc = 0.0
        for c, gset, pool in inst:
            ec = head(GEMMA[c].unsqueeze(0))
            ep_ = head(torch.stack([GEMMA[p] for p in pool]))
            logits = -lorentz_dist(ec, ep_)
            idx_pos = [pool.index(p) for p in gset]
            loss_acc = loss_acc + (torch.logsumexp(logits, 0) - torch.logsumexp(logits[idx_pos], 0))
        (loss_acc / len(inst)).backward()
        opt.step()
    return head, len(inst)

def main():
    labs = ["opus", "gpt", "gemini"]
    golds = {k: load_gold(GOLDS[k]) for k in labs}
    SEEDS = [0, 1, 2]
    print(f"DIM_IN={DIM_IN}  train_deti={len(TRAIN_CH)}  test_deti={len(TEST_CH)}  seeds={SEEDS}")

    flat = {}
    print("\n=== FLAT COSINE baseline (test split) ===")
    for tl in labs:
        a, n = eval_flat(golds[tl], TEST_CH); flat[tl] = a
        print(f"  test={tl:8s} flat_AUROC={a:.3f} (n={n})")

    # natrenuj raz per (train_lab, seed), zozbieraj AUROC pre vsetky test laby
    cell = {trl: {tel: [] for tel in labs} for trl in labs}
    ninst = {}
    for trl in labs:
        for sd in SEEDS:
            head, ni = train(golds[trl], TRAIN_CH, seed=sd)
            ninst[trl] = ni
            for tel in labs:
                a, _ = eval_head(head, golds[tel], TEST_CH)
                cell[trl][tel].append(a)

    def mean(xs): return sum(xs) / len(xs)

    print("\n=== LORENTZ HEAD AUROC (train riadok x test stlpec), priemer cez seedy ===")
    hdr = "train/test"
    print(f"{hdr:12s} " + " ".join(f"{tl:>10s}" for tl in labs))
    for trl in labs:
        print(f"{trl:12s} " + " ".join(f"{mean(cell[trl][tel]):10.3f}" for tel in labs)
              + f"   (ninst={ninst[trl]})")

    print("\n=== HEAD - FLAT (kladne = hlava bije flat cosine na tom teste) ===")
    print(f"{hdr:12s} " + " ".join(f"{tl:>10s}" for tl in labs))
    for trl in labs:
        print(f"{trl:12s} " + " ".join(f"{mean(cell[trl][tel]) - flat[tel]:+10.3f}" for tel in labs))

    print("\n=== VERDIKT ===")
    diag = [mean(cell[l][l]) - flat[l] for l in labs]            # in-lab (disjunktne deti)
    cross = [mean(cell[a][b]) - flat[b] for a in labs for b in labs if a != b]  # cross-lab
    print(f"IN-LAB (train=test lab, disjunktne deti)  priemer HEAD-FLAT = {mean(diag):+.3f}")
    print(f"CROSS-LAB (train != test lab)             priemer HEAD-FLAT = {mean(cross):+.3f}")
    if mean(cross) > 0.01:
        print("-> HLAVA GENERALIZUJE cez laby: embedder realne pomaha. Veducko ma pravdu.")
    elif mean(diag) > 0.01 >= mean(cross):
        print("-> Hlava sa nauci LAB-SPECIFIC blur (in-lab OK, cross-lab NIE): rozmazana ground truth je STROP.")
    else:
        print("-> Hlava neporazi flat ani in-lab: z tak mala dat sa metriku nenauci.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
