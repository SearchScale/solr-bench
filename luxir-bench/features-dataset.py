#!/usr/bin/env python3
"""The "features" correctness dataset: every 30th geonames record (about 380K places) with fields of Solr's
own types that a Luxir collection still indexes through Lucene's analysis and formats (see
correctness-configsets.py):

    name (Luxir text), name_txt_en (English stemming), name_nf (no freqs/positions), name_nn (no norms),
    name_sort (SortableTextField), desc_tv (term vectors with positions and offsets), tags_dpf (float
    payloads), fclass_enum (EnumFieldType), pop_rank (RankField), price_c (CurrencyFieldType),
    name_s, cc (strings), pop (long), sw (long: suggestion weight), elev (int, sparse)

Names are ASCII. Usage: luxir-bench/features-dataset.py   (from the solr-bench directory)"""
import gzip
import json
import random

OUT = "suites/datasets/features.json.gz"
WEIGHT = {"P": 3.0, "A": 2.5, "H": 2.0, "T": 1.5, "S": 1.0, "L": 0.75, "V": 0.5, "R": 0.25, "U": 0.1}
CURRENCIES = ["USD", "EUR", "GBP", "JPY"]
n = 0
with gzip.open("suites/datasets/geonames.json.gz", "rt") as src, gzip.open(OUT, "wt") as dst:
    for i, line in enumerate(src):
        if i % 30:
            continue
        g = json.loads(line)
        r = random.Random(int(g["id"]))
        name = g.get("asciiname") or "".join(c for c in g.get("name", "") if c.isascii()) or g["id"]
        fc = g.get("feature_class") or "U"
        words = [w for w in name.lower().split() if w.isalpha()][:4] or ["x"]
        tags = " ".join(f"{w}|{round(WEIGHT.get(fc, 0.1) * (k + 1), 2)}" for k, w in enumerate(words))
        d = {"id": g["id"], "name": name, "name_txt_en": name, "name_nf": name, "name_nn": name, "name_sort": name,
             "name_s": name[:200], "desc_tv": f"{name} {g.get('timezone', '').replace('/', ' ').replace('_', ' ')}",
             "tags_dpf": tags, "fclass_enum": fc if fc in WEIGHT else "U", "pop_rank": g.get("population", 0) + 1,
             "price_c": f"{r.randrange(1, 100000) / 100:.2f},{r.choice(CURRENCIES)}", "cc": g.get("country_code") or "XX",
             "pop": g.get("population", 0),
             # suggestion weight: by population, ties broken by id (equal weights merge in no fixed order);
             # within an int, as FuzzyLookup encodes weights
             "sw": min(g.get("population", 0), 2000) * 100_000 + int(g["id"]) % 100_000}
        if "elevation" in g:
            d["elev"] = g["elevation"]
        dst.write(json.dumps(d) + "\n")
        n += 1
print(f"{n} docs to {OUT}")
