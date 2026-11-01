#!/usr/bin/env python3
"""Correctness workloads for the "vectors" collection (vectors-dataset.py), for verify.py. Writes
suites/queries/coverage/vectors/<Category>.txt and manifest.json. HNSW search (knn, vectorSimilarity
thresholds) is approximate and each system builds its own graphs, so those categories are listed as
"_approximate" (verify.py: overlapping rows, docs both return alike); exact similarity (functions, and
knn under filters small enough for exact search) is compared as any other request.
Usage: luxir-bench/vectors-queries.py   (from the solr-bench directory)"""
import json
import os
import random
import urllib.parse

import numpy as np

OUT = "suites/queries/coverage/vectors"
rnd = random.Random(31)
sample = np.load("suites/datasets/vectors-sample.npz")
vecs = sample["vecs"]
gen = np.random.default_rng(5)


def qv(i, noise=0.05):
    """A query vector: a sampled doc's vector, moved a little, unit length."""
    v = vecs[i % len(vecs)] + gen.normal(0, noise, vecs.shape[1])
    return v / np.linalg.norm(v)


def lit(v, scale=1.0, digits=6):
    return "[" + ",".join(f"{x * scale:.{digits}f}" for x in v) + "]"


def blit(v):
    return "[" + ",".join(str(int(max(-128, min(127, round(x * 255))))) for x in v[:16]) + "]"


def q(*pairs, **params):
    out = []
    for k, v in list(pairs) + list(params.items()):
        for x in (v if isinstance(v, list) else [v]):
            out.append((k, x))
    return urllib.parse.urlencode(out)


FL = "id,score"
small = ["AD", "LI", "MC", "SM", "VA", "GI", "MT", "BH"]  # filters small enough for exact search
cats = {}
# HNSW searched wide (efSearchScaleFactor=50): on this data both systems then find the exact top k
# (recall 1.0 measured against brute force), so these are compared as exact
EF = "efSearchScaleFactor=50"
cats["KnnBasic"] = [q(q=f"{{!knn f={f} topK={k} {EF}}}{val}", fl=FL) for i, (f, k, val) in enumerate(
    [("v", 10, lit(qv(i))) for i in range(6)] + [("v_dot", 10, lit(qv(i))) for i in range(6, 9)]
    + [("v_l2", 10, lit(qv(i)[:32], 10, 5)) for i in range(9, 12)] + [("v_b", 10, blit(qv(i))) for i in range(12, 15)]
    + [("v", 50, lit(qv(i))) for i in range(21, 23)])]
# quantized fields: scores depend on each segment's quantization (its value ranges, its centroids), so the
# systems' segments give different scores and neighbours; only counts and that they answer are compared
cats["KnnQuantized"] = [q(q=f"{{!knn f={f} topK=10}}{lit(qv(i))}", fl=FL) for i, f in
                        [(15, "v_sq"), (16, "v_sq"), (17, "v_sq"), (18, "v_bq"), (19, "v_bq"), (20, "v_bq")]]
cats["KnnFiltered"] = [q(q=f"{{!knn f=v topK=10 {EF}}}{lit(qv(30 + i))}", fq=fq, fl=FL) for i, fq in enumerate(
    ["cc:US", "pop:[1000 TO *]", "fclass:P", "elev:[1000 TO *]", ["cc:(US CA)", "fclass:H"], "name:lake"])] + [
    q(q=f"{{!knn f=v topK=10 {EF} preFilter=$pf}}{lit(qv(40))}", pf="fclass:T", fl=FL),
    q(q=f"{{!knn f=v topK=10 {EF} includeTags=a}}{lit(qv(41))}", fq=["{!tag=a}cc:IN", "{!tag=b}fclass:P"], fl=FL),
    q(q=f"{{!knn f=v topK=10 {EF} excludeTags=b}}{lit(qv(42))}", fq=["{!tag=a}cc:CN", "{!tag=b}fclass:P"], fl=FL)]
cats["KnnParams"] = [q(q=f"{{!knn f=v topK=10 {p}}}{lit(qv(50 + i))}", fl=FL, **extra) for i, (p, extra) in enumerate([
    ("earlyTermination=true", {}), ("efSearchScaleFactor=2", {}), ("filteredSearchThreshold=60", {"fq": "cc:US"}),
    ("seedQuery=$sq", {"sq": "name:lake"}), ("earlyTermination=true saturationThreshold=0.99 patience=5", {})])]
cats["VectorThreshold"] = [q(q=f"{{!vectorSimilarity f={f} minReturn={mr} minTraverse={mt}}}{val}", fl=FL, rows=20)
                           for f, mr, mt, val in [("v", 0.9, 0.3, lit(qv(60))), ("v", 0.85, 0.3, lit(qv(61))),
                                                  ("v_dot", 0.9, 0.3, lit(qv(62))), ("v", 0.95, 0.3, lit(qv(63)))]]
cats["KnnHybrid"] = [q(q="{!bool should=$lex should=$vec}", lex=f"name:{w}",
                       vec=f"{{!knn f=v topK=20 {EF}}}{lit(qv(70 + i))}", fl=FL)
                     for i, w in enumerate(["lake", "church", "creek"])] + [
    q(q=f"name:{w}", rq="{!rerank reRankQuery=$vec reRankDocs=50 reRankWeight=1}",
      vec=f"{{!knn f=v topK=50 {EF}}}{lit(qv(80 + i))}", fl=FL) for i, w in enumerate(["river", "school"])]
cats["KnnExactSmallFilters"] = [q(q=f"{{!knn f=v topK=5}}{lit(qv(90 + i))}", fq=f"cc:{c}", fl=FL)
                                for i, c in enumerate(small)] + [
    q(q=f"{{!knn f=v_b topK=5}}{blit(qv(100))}", fq="cc:AD", fl=FL),
    q(q=f"{{!knn f=v topK=20}}{lit(qv(101))}", fq="cc:(AD LI MC)", rows=0,
      **{"json.facet": json.dumps({"c": {"type": "terms", "field": "cc"}, "p": "sum(pop)"})})]


def sim(enc, fn, field, v):
    return f"vectorSimilarity({enc},{fn},{field},{v})"


cats["VectorFunctions"] = [q(q=qq, fq=fq, sort=f"{s} desc,id asc", fl=f"id,s:{s}") for qq, fq, s in [
    ("*:*", "cc:FR", sim("FLOAT32", "COSINE", "v", lit(qv(110)))),
    ("name:lake", "*:*", sim("FLOAT32", "COSINE", "v", lit(qv(111)))),
    ("*:*", "cc:JP", sim("FLOAT32", "DOT_PRODUCT", "v_dot", lit(qv(112)))),
    ("*:*", "cc:DE", sim("FLOAT32", "EUCLIDEAN", "v_l2", lit(qv(113)[:32], 10, 5))),
    ("*:*", "cc:BR", sim("BYTE", "EUCLIDEAN", "v_b", blit(qv(114)))),
    ("*:*", "cc:IT", sim("FLOAT32", "COSINE", "v", "v_sq")),
    ("fclass:H", "cc:NO", sim("FLOAT32", "COSINE", "v", lit(qv(115))))]] + [
    q(q="*:*", fq=["cc:US", f"{{!frange l=0.8}}{sim('FLOAT32', 'COSINE', 'v', lit(qv(116)))}"], sort="id asc", fl="id"),
    q(q=f"{{!func}}{sim('FLOAT32', 'COSINE', 'v', lit(qv(117)))}", fq="cc:GB", sort="score desc,id asc", fl=FL)]
cats["VectorFields"] = [q(q=f"cc:{c}", sort="id asc", fl=f, rows=5) for c, f in [
    ("AD", "id,v"), ("LI", "id,v_l2,v_b"), ("MC", "*"), ("SM", "id,name,v,v_b")]]

os.makedirs(OUT, exist_ok=True)
for name, rows in cats.items():
    with open(f"{OUT}/{name}.txt", "w") as f:
        f.write("\n".join(rows) + "\n")
with open(f"{OUT}/manifest.json", "w") as f:
    m = {name: "/select" for name in cats}
    m["_approximate"] = ["KnnParams", "VectorThreshold"]
    m["_approximate_scores"] = ["KnnQuantized"]
    json.dump(m, f, indent=1)
print(f"wrote {sum(map(len, cats.values()))} requests in {len(cats)} categories to {OUT}")
