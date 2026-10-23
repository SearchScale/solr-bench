#!/usr/bin/env python3
"""Checks every geonames request on Solr+Lucene against Solr+Luxir, and Luxir's native path against
its Java path (luxirCodec=false) over the same index:
  - numFound equal on both systems;
  - facet buckets (and their stats) equal on both systems;
  - for sorted requests, the top rows' sort values equal on both systems;
  - on Solr+Luxir, the native top rows (ids and order) equal to the Java path's.
Top rows of score-ranked requests are compared across systems for information only.
Usage: geonames-verify.py <lucene-port> <luxir-port> <requests-file>, with a geonames collection on each
system (for example suites/queries/geonames/All.txt)"""
import json, sys, urllib.parse, urllib.request
lport, xport, path = sys.argv[1:4]
def run(port, params, extra):
    p = urllib.parse.parse_qsl(params, keep_blank_values=True) + list(extra.items())
    req = urllib.request.Request(f"http://localhost:{port}/solr/geonames/select",
                                 data=urllib.parse.urlencode(p).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    return json.load(urllib.request.urlopen(req, timeout=600))
def close(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(close(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(close(x, y) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))
    return a == b
extra = {"wt": "json", "rows": "10", "fl": "id,score,population,geonameid"}
fails = []; info = 0; n = 0
for line in open(path):
    params = line.rstrip("\n")
    if not params: continue
    n += 1
    q = dict(urllib.parse.parse_qsl(params))
    label = (q.get("q", "")[:60] + (" fq=" + q["fq"][:30] if "fq" in q else "") + (" sort=" + q["sort"] if "sort" in q else "")
             + (" json.facet" if "json.facet" in q else ""))
    a, b = run(lport, params, extra), run(xport, params, extra)
    j = run(xport, params, {**extra, "luxirCodec": "false"})
    ra, rb, rj = a["response"], b["response"], j["response"]
    if ra["numFound"] != rb["numFound"]:
        fails.append(f"numFound {ra['numFound']} vs {rb['numFound']}: {label}")
    if "facets" in a and not close(a["facets"], b["facets"]):
        fails.append(f"facets differ: {label}")
    if "facets" in b and not close(b["facets"], j["facets"]):
        fails.append(f"Luxir facets native vs Java differ: {label}")
    if "sort" in q:
        f = q["sort"].split()[0]
        va, vb = [d.get(f) for d in ra["docs"]], [d.get(f) for d in rb["docs"]]
        if va != vb: fails.append(f"sort values {va} vs {vb}: {label}")
    if [d["id"] for d in rb["docs"]] != [d["id"] for d in rj["docs"]] or rb["numFound"] != rj["numFound"]:
        fails.append(f"Luxir native vs Java rows differ: {label}")
    if "sort" not in q and [d["id"] for d in ra["docs"]] != [d["id"] for d in rb["docs"]]:
        info += 1
print(f"{n} requests: {len(fails)} failures; score-ranked top rows differing across systems (info): {info}")
for f in fails[:30]: print("  FAIL", f)
sys.exit(1 if fails else 0)
