#!/usr/bin/env python3
"""The "vectors" correctness dataset: every 40th geonames record (about 285K places) with dense vectors
from its name: hashed character trigrams (signed feature hashing), so similar names have near vectors.

    v      64 floats, unit length (cosine)         v_dot  the same (dot product)
    v_l2   32 floats, scaled (euclidean)           v_b    16 bytes, -128..127 (euclidean)
    v_sq   v, scalar-quantized field               v_bq   v, binary-quantized field
    name (text), cc, fclass (strings), pop (long), elev (int, sparse)

Also writes suites/datasets/vectors-sample.npz: the vectors of every 50th doc, to query with.
Usage: luxir-bench/vectors-dataset.py   (from the solr-bench directory)"""
import gzip
import hashlib
import json

import numpy as np

OUT = "suites/datasets/vectors.json.gz"
DIM = 64


def embed(text):
    v = np.zeros(DIM)
    t = f"  {text.lower()} "
    for i in range(len(t) - 2):
        h = int.from_bytes(hashlib.blake2b(t[i:i + 3].encode(), digest_size=8).digest(), "little")
        v[h % DIM] += 1.0 if (h >> 32) & 1 else -1.0
    n = np.linalg.norm(v)
    return v / n if n else np.eye(DIM)[0]


n = 0
sample_ids, sample_vecs = [], []
with gzip.open("suites/datasets/geonames.json.gz", "rt") as src, gzip.open(OUT, "wt") as dst:
    for i, line in enumerate(src):
        if i % 40:
            continue
        g = json.loads(line)
        name = g.get("asciiname") or "".join(c for c in g.get("name", "") if c.isascii()) or g["id"]
        v = embed(name)
        r = np.random.default_rng(int(g["id"]))
        v = v + r.normal(0, 0.02, DIM)  # near-duplicate names still differ a little
        v = v / np.linalg.norm(v)
        vf = [round(float(x), 6) for x in v]
        d = {"id": g["id"], "name": name, "cc": g.get("country_code") or "XX", "fclass": g.get("feature_class") or "-",
             "pop": g.get("population", 0), "v": vf, "v_dot": vf, "v_l2": [round(float(x) * 10, 5) for x in v[:32]],
             "v_b": [int(max(-128, min(127, round(x * 255)))) for x in v[:16]], "v_sq": vf, "v_bq": vf}
        if "elevation" in g:
            d["elev"] = g["elevation"]
        dst.write(json.dumps(d) + "\n")
        if n % 50 == 0:
            sample_ids.append(g["id"])
            sample_vecs.append(vf)
        n += 1
np.savez_compressed("suites/datasets/vectors-sample.npz", ids=np.array(sample_ids), vecs=np.array(sample_vecs))
print(f"{n} docs to {OUT}")
