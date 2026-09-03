#!/usr/bin/env python3
"""_hit_smoke.py — over ze HiT model sa stiahne, nacita a vrati embeddingy + normy.
Iba smoke: 3 slova, vytlac tvar a normy. Ziadne data z produkcie.
"""
import os
os.environ.pop("HF_HUB_OFFLINE", None)          # potrebujeme stiahnut
os.environ.pop("TRANSFORMERS_OFFLINE", None)
from hierarchy_transformers import HierarchyTransformer

model = HierarchyTransformer.from_pretrained("Hierarchy-Transformers/HiT-MiniLM-L12-WordNetNoun")
ents = ["dog", "animal", "poodle"]
emb = model.encode(ents, convert_to_numpy=True)
print("shape:", emb.shape)
import numpy as np
norms = np.linalg.norm(emb, axis=1)
for e, n in zip(ents, norms):
    print(f"  {e:10s} norm={n:.4f}")
# manifold vzdialenosti (subsumption uses dist + centri)
print("curvature/manifold:", getattr(model, "manifold", None))
