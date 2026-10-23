#!/usr/bin/env python3
# Compares two solr-bench result directories (e.g. stock Solr and Solr with Luxir).
# Usage: luxir-bench/compare.py <results-dir-A> <results-dir-B> [label-A] [label-B]
# The ratio column is "how much better B is": A/B for times, B/A for throughput, so above 1x means B was better.
import json, sys

def load(d):
    r = json.load(open(f"{d}/results.json"))
    plan = json.load(open(f"{d}/config.json")).get("execution-plan", {})
    out = {
        "Indexing (s)": float(r["task1"][0]["total-time"]),
        "Restarts (s)": [float(t["total-time"]) for t in r.get("task2", [])],
    }
    # every query task: one entry per thread count in its "threads"
    for task in sorted((t for t in r if t.startswith("task")), key=lambda t: int(t[4:])):
        runs = r[task][0].get("timings") if r[task] else None
        if not isinstance(runs, list) or not runs or "50th" not in runs[0]:
            continue
        label = plan.get(task, {}).get("description", task)
        for t in runs:
            p = f"{label}, {t['threads']} threads"
            if "qps" in t:
                out[f"{p}: throughput (queries/s)"] = t["qps"]
            out.update({f"{p}: p50 (ms)": t["50th"], f"{p}: p90 (ms)": t["90th"], f"{p}: p95 (ms)": t["95th"]})
            if "99th" in t:
                out[f"{p}: p99 (ms)"] = t["99th"]
            out.update({f"{p}: mean (ms)": t["mean"], f"{p}: queries": t["total-queries"]})
    return out

a, b = load(sys.argv[1]), load(sys.argv[2])
la, lb = (sys.argv[3:5] + ["A", "B"])[:2]
print(f"| Metric | {la} | {lb} | {lb} better by |\n|---|---|---|---|")
for k in a:
    x, y = a[k], b.get(k)
    if y is None:
        continue
    if isinstance(x, list):
        print(f"| {k} | {', '.join(f'{v:.2f}' for v in x)} | {', '.join(f'{v:.2f}' for v in y)} | |")
    elif k.endswith(": queries"):
        print(f"| {k} | {x} | {y} | |")
    else:
        ratio = y / x if "throughput" in k else x / y
        print(f"| {k} | {x:.2f} | {y:.2f} | {ratio:.2f}x |")
