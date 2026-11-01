#!/usr/bin/env python3
"""The "types" correctness dataset: every 5th geonames record (about 2.3M docs, all countries) with
fields of every common Solr type and shape, so that queries can check each one on both systems:

    t_s, t_m      text, ASCII (single, multi-valued)        s_s, s_m, s_sp  string (single, multi, sparse)
    i_s, i_m, i_sp  int (single, multi, sparse)       l_s, l_m        long (single, multi)
    f_s, f_m      float (single, multi)              d_s, d_sp       double (single, sparse)
    dt_s, dt_m    date (single, multi)               b_s             boolean
    ll            LatLonPointSpatialField            rpt             location_rpt
    i_dv          int with doc values only (neither indexed nor stored)

Values derive from the record (deterministically, by its id) so they spread as real data does.
Usage: luxir-bench/types-dataset.py [out]   (from the solr-bench directory; default
suites/datasets/types.json.gz)
"""
import datetime
import gzip
import json
import random
import sys

out = sys.argv[1] if len(sys.argv) > 1 else "suites/datasets/types.json.gz"
EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)


def date(r):
    t = EPOCH + datetime.timedelta(seconds=r.randrange(0, 60 * 365 * 86400))  # 1970-2029
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


n = 0
with gzip.open("suites/datasets/geonames.json.gz", "rt") as src, gzip.open(out, "wt") as dst:
    for i, line in enumerate(src):
        if i % 5:
            continue
        g = json.loads(line)
        r = random.Random(int(g["id"]))
        lat, lon = (float(x) for x in g["location"].split(",")) if g.get("location") else (0.0, 0.0)
        # ASCII text only: Luxir's word tokenizer and Solr's StandardTokenizer split some non-ASCII
        # text differently, which shifts BM25's average field length; here they agree exactly
        alt = [a for a in g.get("alternatenames", "").split(",") if a and a.isascii()][:3]
        ascii_name = g.get("asciiname") or "".join(c for c in g.get("name", "") if c.isascii())
        d = {
            "id": g["id"],
            "t_s": ascii_name,
            "t_m": [ascii_name] + alt,
            "s_s": g.get("country_code") or "XX",
            "s_m": sorted({g.get("feature_class") or "-", g.get("feature_code") or "-", g.get("admin1_code") or "00"}),
            "i_s": int(g.get("dem") or 0) if (g.get("dem") or "0").lstrip("-").isdigit() else 0,
            "i_m": [r.randrange(0, 50) for _ in range(r.randrange(0, 5))],
            "l_s": g.get("population", 0),
            "l_m": [g["geonameid"], r.randrange(-10**12, 10**12)],
            "f_s": lat,
            "f_m": [lat, lon, round(r.uniform(-1000, 1000), 3)],
            "d_s": lon,
            "dt_s": date(r),
            "dt_m": [date(r) for _ in range(r.randrange(1, 4))],
            "b_s": g.get("population", 0) > 1000 or r.random() < 0.1,
            "ll": f"{lat},{lon}",
            "rpt": f"{lat},{lon}",
            "i_dv": r.randrange(0, 1000),
        }
        if "elevation" in g:
            d["i_sp"] = g["elevation"]
        if g.get("admin2_code"):
            d["s_sp"] = g["admin2_code"]
        if r.random() < 0.3:
            d["d_sp"] = round(r.uniform(-1e6, 1e6), 6) if r.random() < 0.9 else r.choice([0.0, -0.0, 1e-300, 1e300])
        if not d["i_m"]:
            del d["i_m"]
        dst.write(json.dumps(d, ensure_ascii=False) + "\n")
        n += 1
print(f"{n} docs written to {out}")
