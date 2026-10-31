#!/usr/bin/env python3
"""Checks every request of a query file on Solr+Lucene against Solr+Luxir, and Luxir's native path against
its Java path (luxirCodec=false) over the same index:
  - numFound equal on both systems;
  - facet buckets (and their stats) equal on both systems;
  - for sorted requests, the top rows' values of every sort key equal on both systems;
  - legacy facet_counts, grouped results (match counts; for field-sorted groups, each group's numFound) and
    nextCursorMark equal on both systems, and all of them native vs Java on Solr+Luxir;
  - on Solr+Luxir, the native top rows (ids and order) equal to the Java path's.
Top rows of score-ranked requests are compared across systems for information only.
Requests are lines of URL-encoded parameters, or JSON request bodies (lines starting with "{").
Spell checking, the terms component, stats and highlighting (of docs both systems return) are compared
the same ways, and responses without results (/terms) as a whole.
Usage: verify.py <lucene-port> <luxir-port> <requests-file> [collection] [fl] [handler], with the collection
(default geonames) holding the same documents on each system; fl lists the fields to return, which
must include the sort fields (default id,score,population,geonameid); handler defaults to /select. For example:
  verify.py 51000 52000 suites/queries/geonames/All.txt
  verify.py 51000 52000 suites/queries/enwiki/All.json enwiki id,score,month,dayOfYear,title,lastMod"""
import json, sys, urllib.parse, urllib.request
lport, xport, path = sys.argv[1:4]
coll = sys.argv[4] if len(sys.argv) > 4 else "geonames"
fl = sys.argv[5] if len(sys.argv) > 5 else "id,score,population,geonameid"
handler = sys.argv[6] if len(sys.argv) > 6 else "/select"
def run(port, params, extra):
    url = f"http://localhost:{port}/solr/{coll}{handler}"
    if params.startswith("{"):  # a JSON body, with the extra parameters in the URL
        body = {**json.loads(params), "fields": extra["fl"], "limit": int(extra["rows"])}
        req = urllib.request.Request(url + "?" + urllib.parse.urlencode(extra), data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    else:
        p = urllib.parse.parse_qsl(params, keep_blank_values=True) + list(extra.items())
        req = urllib.request.Request(url, data=urllib.parse.urlencode(p).encode(),
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    return json.load(urllib.request.urlopen(req, timeout=600))
def summary(params):
    """q, fq, sort and json.facet of a request, whichever form it has."""
    if not params.startswith("{"):
        return dict(urllib.parse.parse_qsl(params))
    b = json.loads(params)
    q = {"q": b["query"], "sort": b.get("sort"), "json.facet": b.get("facet")}
    return {k: v for k, v in q.items() if v is not None}
def close(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(close(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(close(x, y) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))
    return a == b
def same_but_rounding(x, y):
    """Rows that differ only in the order of docs whose scores agree to float rounding."""
    if len(x) != len(y) or {d["id"] for d in x} != {d["id"] for d in y} or "score" not in fl:
        return False
    return all(abs(a["score"] - b["score"]) <= 1e-6 * max(1.0, abs(a["score"])) for a, b in zip(x, y))
extra = {"wt": "json", "rows": "10", "fl": fl}
fails = []; info = 0; n = 0; rounding = 0
for line in open(path):
    params = line.rstrip("\n")
    if not params: continue
    n += 1
    q = summary(params)
    label = (q.get("q", "")[:60] + (" fq=" + q["fq"][:30] if "fq" in q else "") + (" sort=" + q["sort"] if "sort" in q else "")
             + (" json.facet" if "json.facet" in q else ""))
    a, b = run(lport, params, extra), run(xport, params, extra)
    j = run(xport, params, {**extra, "luxirCodec": "false"})
    for key, what in (("facet_counts", "legacy facets"), ("nextCursorMark", "nextCursorMark"),
                      ("spellcheck", "spellcheck"), ("terms", "terms"), ("stats", "stats")):
        if key in a and not close(a[key], b.get(key)):
            fails.append(f"{what} differ: {label}")
        if key in b and not close(b[key], j.get(key)):
            fails.append(f"Luxir {what} native vs Java differ: {label}")
    if "grouped" in a:
        def groups(r):
            return {f: (g["matches"], g.get("ngroups"),
                        sorted((str(x["groupValue"]), x["doclist"]["numFound"]) for x in g["groups"]))
                    for f, g in r["grouped"].items()}
        if "sort" in q or "group.sort" in q:
            if groups(a) != groups(b):
                fails.append(f"groups differ: {label}")
        elif {f: g[0] for f, g in groups(a).items()} != {f: g[0] for f, g in groups(b).items()}:
            fails.append(f"group matches differ: {label}")
        elif groups(a) != groups(b):
            info += 1  # score-ranked groups: which tied groups make the page depends on doc order
        if not close(b["grouped"], j["grouped"]):
            fails.append(f"Luxir groups native vs Java differ: {label}")
        continue
    if "highlighting" in a:
        both = a["highlighting"].keys() & b["highlighting"].keys()
        if any(a["highlighting"][d] != b["highlighting"][d] for d in both):
            fails.append(f"highlighting differs: {label}")
        if b["highlighting"] != j.get("highlighting"):
            fails.append(f"Luxir highlighting native vs Java differs: {label}")
    if "response" not in a:
        continue
    ra, rb, rj = a["response"], b["response"], j["response"]
    if ra["numFound"] != rb["numFound"]:
        fails.append(f"numFound {ra['numFound']} vs {rb['numFound']}: {label}")
    if "facets" in a and not close(a["facets"], b["facets"]):
        fails.append(f"facets differ: {label}")
    if "facets" in b and not close(b["facets"], j["facets"]):
        fails.append(f"Luxir facets native vs Java differ: {label}")
    if "sort" in q:
        keys = [k.split()[0] for k in q["sort"].split(",")]
        va = [[d.get(f) for f in keys] for d in ra["docs"]]
        vb = [[d.get(f) for f in keys] for d in rb["docs"]]
        if va != vb: fails.append(f"sort values {va[:5]} vs {vb[:5]}: {label}")
    if [d["id"] for d in rb["docs"]] != [d["id"] for d in rj["docs"]] or rb["numFound"] != rj["numFound"]:
        if rb["numFound"] == rj["numFound"] and same_but_rounding(rb["docs"], rj["docs"]):
            rounding += 1
        else:
            fails.append(f"Luxir native vs Java rows differ: {label}")
    if "sort" not in q and [d["id"] for d in ra["docs"]] != [d["id"] for d in rb["docs"]]:
        info += 1
print(f"{n} requests: {len(fails)} failures; score-ranked top rows differing across systems (info): {info}; "
      f"Luxir native vs Java rows reordered among scores equal to float rounding: {rounding}")
for f in fails: print("  FAIL", f)
sys.exit(1 if fails else 0)
