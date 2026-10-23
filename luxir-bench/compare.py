#!/usr/bin/env python3
# Compares two solr-bench result directories (e.g. stock Solr and Solr with Luxir).
# Usage: luxir-bench/compare.py <results-dir-A> <results-dir-B> [label-A] [label-B]
import json, sys

def load(d):
    r = json.load(open(f"{d}/results.json"))
    q = r["task3"][0]["timings"][0]
    return {
        "Indexing (s)": float(r["task1"][0]["total-time"]),
        "Restarts (s)": [float(t["total-time"]) for t in r.get("task2", [])],
        "Query p50 (ms)": q["50th"], "Query p90 (ms)": q["90th"],
        "Query p95 (ms)": q["95th"], "Query mean (ms)": q["mean"],
        "Queries": q["total-queries"], "Query phase (s)": float(r["task3"][0]["total-time"]) / 1000,
    }

a, b = load(sys.argv[1]), load(sys.argv[2])
la, lb = (sys.argv[3:5] + ["A", "B"])[:2]
print(f"| Metric | {la} | {lb} | {la}/{lb} |\n|---|---|---|---|")
for k in a:
    x, y = a[k], b[k]
    if isinstance(x, list):
        print(f"| {k} | {', '.join(f'{v:.2f}' for v in x)} | {', '.join(f'{v:.2f}' for v in y)} | |")
    elif k == "Queries":
        print(f"| {k} | {x} | {y} | |")
    else:
        print(f"| {k} | {x:.2f} | {y:.2f} | {x / y:.2f}x |")
