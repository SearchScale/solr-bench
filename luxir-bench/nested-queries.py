#!/usr/bin/env python3
"""Correctness workloads for the "nested" collection (nested-dataset.py: country, state and place blocks):
block joins, nest paths, the [child] transformer, block-join facet domains and other features over
nested documents, for verify.py. Writes suites/queries/coverage/nested/<Category>.txt and manifest.json.
Requests ordered by values end their sort with id. Usage: luxir-bench/nested-queries.py (from solr-bench)"""
import collections
import gzip
import json
import os
import random
import urllib.parse

OUT = "suites/queries/coverage/nested"
rnd = random.Random(23)
blocks = []
with gzip.open("suites/datasets/nested.json.gz", "rt") as f:
    for line in f:
        blocks.append(json.loads(line))
places = [p for b in blocks for s in b.get("states", []) for p in s["places"]] + [p for b in blocks for p in b.get("places", [])]
words = [w for w, _ in collections.Counter(
    w.lower() for p in places[::50] for w in p["name"].split() if w.isalpha() and len(w) > 3).most_common(50)]
countries = [b["code"] for b in sorted(blocks, key=lambda b: -b["num_places"])[:40]]
states = [s["id"] for b in blocks for s in b.get("states", [])]
classes = ["P", "H", "T", "S", "L", "A", "V", "R", "U"]
ROOT = "*:* -_nest_path_:*"  # the root docs (countries), as Solr's nested-document docs advise
# Block joins need a parents filter matching every ancestor level (a place directly under a country has
# no state above it), child queries matching no parent, and parent queries matching parents only:
# otherwise which docs belong to which block depends on the order blocks were written in.
ANCESTORS = "doc_type:(country OR state)"


def q(*pairs, **params):
    out = []
    for k, v in list(pairs) + list(params.items()):
        for x in (v if isinstance(v, list) else [v]):
            out.append((k, x))
    return urllib.parse.urlencode(out)


def w(i):
    return words[i % len(words)]


cats = {}
cats["ParentBlockJoin"] = [q(q=f"{{!parent which=doc_type:country}}{c}", sort="id asc", fl="id,code") for c in [
    f"name:{w(0)}", f"name:{w(1)} AND feature_class:H", "+doc_type:place +population:[1000000 TO *]",
    "elevation:[4000 TO *]",
    f"alt:{w(2)}", "feature_class:V", "doc_type:state AND num_places:[1000 TO *]", f'name:"{w(3)} {w(4)}"~3']] + [
    q(q=f"{{!parent which=\"{ANCESTORS}\"}}{c}", sort="id asc", fl="id,name_s") for c in [
        f"name:{w(5)}", "+doc_type:place +population:[100000 TO *]", "feature_class:T AND elevation:[3000 TO *]"]] + [
    q(q=f"{{!parent which=doc_type:country score={m}}}name:{w(i)}", sort="score desc,id asc", fl="id,score")
    for i, m in enumerate(["none", "avg", "max", "min", "total"])] + [
    q(q=f"{{!parent which=\"{ROOT}\"}}+_nest_path_:\"/states/places\" +name:{w(6)}", sort="id asc", fl="id"),
    q(q="{!parent which=doc_type:country filters=$cf}name:" + w(7), cf="feature_class:H", sort="id asc", fl="id"),
    q(q="+{!parent which=doc_type:country v=$cq} +population:[10000000 TO *]", cq=f"name:{w(8)}", sort="id asc", fl="id")]
cats["ChildBlockJoin"] = [q(q=f"{{!child of=doc_type:country}}+doc_type:country +{c}", fq=fq, sort="id asc",
                             fl="id", rows=20) for c, fq in [
    ("code:US", "doc_type:state"), ("code:IN", f"name:{w(9)}"), ("population:[100000000 TO *]", "doc_type:place"),
    ("num_places:[0 TO 100]", "*:*"), (f"code:({' '.join(countries[:5])})", "feature_class:P")]] + [
    q(q=f"{{!child of=\"{ANCESTORS}\"}}+doc_type:state +{c}", sort="population desc,id asc", fl="id,population",
      rows=15) for c in [f"id:{states[10]}", "num_places:[2000 TO *]", "population:0"]] + [
    q(q=f"{{!child of=\"{ROOT}\"}}+doc_type:country +code:CN", fq="_nest_path_:\"/states\"", sort="id asc", fl="id"),
    q(q=f"{{!child of=\"{ROOT}\"}}+doc_type:country +code:NO", fq="_nest_path_:\"/places\"", rows=0)]
cats["NestPaths"] = [q(q=c, rows=0) for c in [
    '_nest_path_:"/states"', '_nest_path_:"/states/places"', '_nest_path_:"/places"', "-_nest_path_:*",
    "_nest_path_:*", f"+_nest_path_:\"/states/places\" +name:{w(10)}"]] + [
    q(q="doc_type:place", fq=['_nest_path_:"/places"', f"name:{w(11)}"], sort="id asc", fl="id,name")]
cats["ChildTransformer"] = [q(q=qq, sort="id asc", fl=f, rows=r) for qq, f, r in [
    ("code:AD AND doc_type:country", "*,[child limit=5]", 1),
    ("code:(LI MC SM) AND doc_type:country", "id,code,[child limit=3 fl=id,name,population]", 3),
    ("doc_type:country AND num_places:[1 TO 20]", "*,[child childFilter=doc_type:place limit=10]", 5),
    ("doc_type:country AND num_places:[1 TO 50]", f"*,[child childFilter='name:{w(12)}' limit=5]", 10),
    (f"id:{states[20]}", "*,[child limit=4 fl=id,elevation]", 1),
    ("doc_type:state AND num_places:[1 TO 5]", "id,name_s,[child]", 10),
    ("doc_type:country AND code:BV", "*,[child]", 1),
    ("doc_type:country AND num_places:[1 TO 30]", "id,[child childFilter='feature_class:(H OR T)' limit=-1 fl=id]", 8)]]
cats["BlockJoinFacets"] = [q(q=qq, rows=0, **{"json.facet": json.dumps(fct)}) for qq, fct in [
    ("doc_type:country", {"fc": {"type": "terms", "field": "feature_class", "domain": {"blockChildren": "doc_type:country"},
                                 "facet": {"countries": "uniqueBlock(_root_)"}}}),
    (f"name:{w(13)}", {"cc": {"type": "terms", "field": "code", "limit": 10,
                              "domain": {"blockParent": "doc_type:country"}}}),
    (f"name:{w(14)}", {"st": {"type": "terms", "field": "name_s", "limit": 10, "domain": {"blockParent": ANCESTORS},
                              "facet": {"p": "sum(population)"}}}),
    ("doc_type:state", {"fc": {"type": "terms", "field": "feature_class", "limit": 9,
                               "domain": {"blockChildren": ANCESTORS, "filter": "population:[1 TO *]"},
                               "facet": {"states": f"uniqueBlock({{!v='{ANCESTORS}'}})", "e": "max(elevation)"}}}),
    ("code:(US CA MX) AND doc_type:country", {"tz": {"type": "terms", "field": "timezone", "limit": 8,
                                                     "domain": {"blockChildren": "doc_type:country"},
                                                     "facet": {"c": "uniqueBlock(_root_)"}}}),
    ("feature_class:V", {"c": {"type": "query", "q": "*:*", "domain": {"blockParent": "doc_type:country"},
                               "facet": {"n": "sum(num_places)", "u": "unique(code)"}}})]]
# (sorts by childfield() fail distributed on Solr alike; per shard they work)
cats["ParentsByChildren"] = [q(q=qq, sort=s, fl=f, **p) for qq, s, f, p in [
    # children scored by a function: only places, so no parent matches the child query
    ("{!parent which=doc_type:country score=max v=$cq}", "score desc,id asc", "id,score",
     {"cq": "{!bool filter=doc_type:place must=$f}", "f": "{!func}population"}),
    (f"{{!parent which=\"{ANCESTORS}\" score=total v=$cq}}", "score desc,id asc", "id,score",
     {"cq": "{!bool filter=doc_type:place must=$f}", "f": "{!func}elevation"}),
    ("{!parent which=doc_type:country score=avg v=$cq}", "score desc,id asc", "id,score",
     {"cq": "{!bool filter=doc_type:place must=$f}", "f": "{!func}log(sum(population,1))"})]]
cats["FeaturesOverNested"] = [q(q=qq, fl=f, **p) for qq, f, p in [
    ("doc_type:place", "id,population", {"fq": "{!collapse field=code sort='population desc,id asc'}", "sort": "id asc"}),
    (f"name:{w(16)}", "id", {"facet": "true", "facet.field": ["feature_class", "code"], "facet.limit": 8, "rows": 0}),
    ("doc_type:state", "id", {"stats": "true", "stats.field": ["population", "num_places"], "rows": 0}),
    ("doc_type:place AND population:[100000 TO *]", "id", {"group": "true", "group.field": "timezone",
                                                           "group.sort": "population desc,id asc", "sort": "id asc"}),
    ("doc_type:place", "id,location", {"fq": "{!geofilt sfield=location pt=48.85,2.35 d=30}", "sort": "id asc"}),
    ("doc_type:country", "id,num_places", {"sort": "num_places desc,id asc", "rows": 20}),
    ("*:*", "id", {"rows": 0, "json.facet": json.dumps({"t": {"type": "terms", "field": "doc_type"}})})]]

os.makedirs(OUT, exist_ok=True)
for name, rows in cats.items():
    with open(f"{OUT}/{name}.txt", "w") as f:
        f.write("\n".join(rows) + "\n")
with open(f"{OUT}/manifest.json", "w") as f:
    json.dump({name: "/select" for name in cats}, f, indent=1)
print(f"wrote {sum(map(len, cats.values()))} requests in {len(cats)} categories to {OUT}")
