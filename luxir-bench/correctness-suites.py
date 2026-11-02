#!/usr/bin/env python3
"""Benchmark suites over the correctness datasets (types, nested, vectors, features; see their *-dataset.py
and *-queries.py): one pair per dataset, Solr+Lucene and Solr+Luxir, from the geonames suites (cluster,
repositories, restarts), indexing the dataset with its configset, then one query task per category of
suites/queries/coverage/<dataset> (16 threads, 10 s each) on its handler.

    suites/correctness-<dataset>-local.json   suites/luxir-correctness-<dataset>-local.json
    suites/correctness-<dataset>-local-sm-on.json   (stock Solr+Lucene: the security manager left on)

The datasets download from the searchscale/solr-bench Hugging Face bucket (made by luxir-bench/<dataset>-dataset.py).

Nested blocks go to /update as JSON arrays, one block per batch (/update/json/docs would flatten them).
Suggest is left out: its suggesters are built per core after indexing, which the suites cannot do.
Usage: luxir-bench/correctness-suites.py   (from the solr-bench directory)"""
import json
import os

DATASETS = {  # dataset: (description, batch size, update path)
    "types": ("2.3M places with a field of every type and shape", 10000, None),
    "nested": ("geonames as 252 country blocks of 3.9K states and 570K places", 1, "/update"),
    "vectors": ("285K places with dense vectors (float, byte, quantized)", 2000, None),
    "features": ("380K places with Solr's own types (payloads, term vectors, enum, rank, currency)", 5000, None),
}
SKIP = {("features", "Suggest")}
BUCKET = "https://huggingface.co/buckets/searchscale/solr-bench/resolve"


def suite(base, out, dataset, luxir):
    s = json.load(open(f"suites/{base}"))
    desc, batch, path = DATASETS[dataset]
    s["pre-download"] = [f"{BUCKET}/{dataset}.json.gz"]
    ib = s["task-types"]["indexing"]["index-benchmark"]
    ib.update({"name": dataset.upper(), "description": f"{dataset}: {desc}", "dataset-file": f"datasets/{dataset}.json.gz",
               "batch-size": batch})
    if path:
        ib["update-path"] = path
    ib["setups"][0].update({"collection": dataset, "configset": f"conf_{dataset}" + ("_luxir" if luxir else "")})
    plan = {k: v for k, v in s["execution-plan"].items() if not v["type"].startswith("querying")}
    plan["task1"]["description"] = f"Indexing {dataset}"
    tt = {k: v for k, v in s["task-types"].items() if not k.startswith("querying")}
    base_dir = f"suites/queries/coverage/{dataset}"
    manifest = json.load(open(f"{base_dir}/manifest.json"))
    n = max(int(k[4:]) for k in plan)
    for f in sorted(os.listdir(base_dir)):
        name = f.rsplit(".", 1)[0]
        if f == "manifest.json" or (dataset, name) in SKIP:
            continue
        lines = [l for l in open(f"{base_dir}/{f}") if l.strip()]
        json_body = all(l.startswith("{") for l in lines)
        t = {"name": f"{name} queries", "description": f"correctness {dataset}: {name}", "collection": dataset,
             "query-file": f"queries/coverage/{dataset}/{f}", "threads": [16], "shuffle": False, "duration-secs": 10,
             "warm-count": 16}
        t.update({"json-query": True} if json_body else {"http-method": "POST"})
        if manifest.get(name, "/select") != "/select":
            t["uri"] = manifest[name]
        n += 1
        tt[f"querying-{name}"] = {"query-benchmark": t}
        plan[f"task{n}"] = {"description": f"{name} queries", "type": f"querying-{name}", "instances": 1,
                            "concurrency": 1, "wait-for": f"task{n - 1}", "mode": "sync"}
    s["task-types"], s["execution-plan"] = tt, plan
    write(out, s)
    if not luxir:  # and as stock Solr starts
        del s["cluster"]["environment"]["SOLR_SECURITY_MANAGER_ENABLED"]
        write(out.replace(".json", "-sm-on.json"), s)
    return n - 2


def write(name, s):
    with open(f"suites/{name}", "w") as fh:
        json.dump(s, fh, indent=2)
        fh.write("\n")


for dataset in DATASETS:
    k = suite("geonames-local.json", f"correctness-{dataset}-local.json", dataset, False)
    suite("luxir-geonames-local.json", f"luxir-correctness-{dataset}-local.json", dataset, True)
    print(f"{dataset}: {k} query tasks")
