#!/usr/bin/env python3
"""Coverage workloads: request features the main suites leave out, on the same three datasets.

Writes suites/queries/coverage/<dataset>/<Category>.(json|txt) from the main suites' own terms, and
coverage suites for both systems from the main suites (same cluster, indexing and restarts; only
the query tasks change):

    suites/coverage-enwiki-local.json        suites/luxir-coverage-enwiki-native-local.json
    suites/coverage-geonames-local.json      suites/luxir-coverage-geonames-local.json
    suites/coverage-facets-local-100m.json   suites/luxir-coverage-facets-local-100m.json

Usage: luxir-bench/coverage-queries.py   (from the solr-bench directory)
"""
import ast
import json
import os
import random
import urllib.parse

Q = "suites/queries"
OUT = f"{Q}/coverage"
rnd = random.Random(42)


def lines(path):
    with open(path) as f:
        return [l.strip() for l in f if l.strip()]


def enwiki_terms(name):
    return [json.loads(l)["query"] for l in lines(f"{Q}/enwiki/{name}.json")]


def write(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for r in rows:
            f.write(r + "\n")


# ---- enwiki: JSON requests, as the main enwiki suite sends them
def ej(query, **extra):
    req = {"query": query, "limit": 10, "fields": "id",
           "params": {"df": "body", "q.op": "OR", "sow": "true"}}
    params = extra.pop("params", {})
    req["params"].update(params)
    req.update(extra)
    return json.dumps(req)


high, med, low = enwiki_terms("HighTerm"), enwiki_terms("MedTerm"), enwiki_terms("LowTerm")
prefixes = [p.rstrip("*") for p in enwiki_terms("Prefix3")]
spans = enwiki_terms("MedSpanNear")
LASTMOD_LO, LASTMOD_HI = 978307200000, 1335756317000  # 2001 to the dump's last edit, ms


def lastmod_range():
    lo = rnd.randrange(LASTMOD_LO, LASTMOD_HI - 31536000000)
    return f"lastMod:[{lo} TO {lo + 31536000000}]"


def day_range():
    lo = rnd.randrange(1, 300)
    return f"dayOfYear:[{lo} TO {lo + rnd.randrange(10, 66)}]"


enwiki = {
    # scoring shapes
    "BoostedOr": [ej(f"{h}^3 {m}") for h, m in zip(high, med)],
    "NestedBoolean": [ej(f"+({h} {m}) -({l} {low[(i + 7) % 30]})")
                      for i, (h, m, l) in enumerate(zip(high, med, low))],
    "DisMaxTwoFields": [ej(f"{h} {m}", params={"defType": "edismax", "qf": "body titleTokenized^2"})
                        for h, m in zip(high, med)],
    # multi-term and positional shapes
    "Regexp": [ej(f"body:/{p}[a-z]{{2,4}}/") for p in prefixes],
    "UnorderedSpanNear": [ej(s.replace("inOrder=true", "inOrder=false")) for s in spans],
    # numeric clauses
    "LongRange": [ej(f"+{h} +{lastmod_range()}") for h in high],
    "FieldExistsFilter": [ej(m, filter="year:*") for m in med],
    "Frange": [ej(h, filter="{!frange l=100 u=200}dayOfYear") for h in high],
    "NegativeFilter": [ej(h, filter="-month:January") for h in high],
    # sorts and pages
    "SortLongFiltered": [ej(h, filter=day_range(), sort="lastMod desc") for h in high],
    "MultiKeySort": [ej(h, sort="month asc,dayOfYear desc") for h in high],
    "DeepPaging": [ej(h, offset=500) for h in high],
    # facets and grouping
    "LegacyFacetField": [ej(m, params={"facet": "true", "facet.field": "month", "facet.limit": "12"})
                         for m in med],
    "LegacyFacetRange": [ej(m, params={"facet": "true", "facet.range": "dayOfYear",
                                       "facet.range.start": "1", "facet.range.end": "367",
                                       "facet.range.gap": "30", "facet.range.other": "all"})
                         for m in med],
    "JsonQueryNestedFacets": [ej(m, limit=0, facet={
        "recent": {"type": "query", "q": "year:[2010 TO *]"},
        "m": {"type": "terms", "field": "month", "limit": 12,
              "facet": {"d": {"type": "range", "field": "dayOfYear", "start": 1, "end": 367, "gap": 61}}}})
        for m in med],
    "FacetAggregations": [ej(h, limit=0, facet={
        "mn": "min(lastMod)", "mx": "max(dayOfYear)", "v": "variance(dayOfYear)", "sd": "stddev(year)",
        "u": "unique(month)"}) for h in high],
    "Grouping": [ej(m, params={"group": "true", "group.field": "month", "group.limit": "1"}) for m in med],
}
for name, rows in enwiki.items():
    write(f"{OUT}/enwiki/{name}.json", rows)

# ---- geonames: form-encoded GET/POST parameters, as the main geonames suite sends them
names = [urllib.parse.parse_qs(l)["q"][0] for l in lines(f"{Q}/geonames/TextTerm.txt")]
countries = [urllib.parse.parse_qs(l)["q"][0] for l in lines(f"{Q}/geonames/StringTerm.txt")]


def gq(**p):
    return urllib.parse.urlencode(p)


geonames = {
    "LegacyFacetPivot": [gq(q=c, rows=0, facet="true", **{"facet.pivot": "feature_class_raw,admin1_code_raw",
                                                          "facet.limit": 20}) for c in countries],
    "LegacyFacetFields": [gq(q=c, rows=0, facet="true", **{"facet.field": "timezone_raw",
                                                          "facet.mincount": 1, "facet.limit": 20})
                          for c in countries],
    "NumBucketsPrefix": [gq(q=c, rows=0, **{"json.facet": json.dumps(
        {"a": {"type": "terms", "field": "admin1_code_raw", "numBuckets": True, "missing": True, "limit": 5},
         "f": {"type": "terms", "field": "feature_code_raw", "prefix": "PP", "limit": 10}})})
        for c in countries],
    "PopulationRangeFacet": [gq(q=n, rows=0, **{"json.facet": json.dumps(
        {"p": {"type": "range", "field": "population", "start": 0, "end": 10000000, "gap": 100000,
               "facet": {"e": "avg(elevation)"}}})}) for n in names],
    "SortElevation": [gq(q=c, sort="elevation desc", fl="id") for c in countries],
    "MultiKeySort": [gq(q=c, sort="admin1_code_raw asc,population desc", fl="id") for c in countries],
    "CursorMarkFirstPage": [gq(q=c, sort="population desc,id asc", cursorMark="*", rows=50, fl="id")
                            for c in countries],
    "DeepPaging": [gq(q=c, sort="population desc", start=1000, rows=10, fl="id") for c in countries],
    "Grouping": [gq(q=n, group="true", **{"group.field": "country_code_raw", "group.limit": 1}, fl="id")
                 for n in names],
    "Collapse": [gq(q=n, fq="{!collapse field=country_code_raw}", fl="id") for n in names],
}
for name, rows in geonames.items():
    write(f"{OUT}/geonames/{name}.txt", rows)

# ---- more request features: edismax, spell checking, the terms component, complex JSON and
# legacy facets, other query parsers, re-ranking, function sorts, highlighting, spatial, MLT.
# Categories not on /select, or form-encoded in the JSON enwiki suite, are listed in HANDLERS.
HANDLERS = {}  # (dataset, category) -> (uri, form-encoded)
rnd2 = random.Random(7)  # its own, so the categories above stay as they were


def misspell(word):
    """A likely misspelling: two letters swapped, or one doubled."""
    if len(word) < 5:
        return word + word[-1]
    i = rnd2.randrange(1, len(word) - 2)
    return word[:i] + word[i + 1] + word[i] + word[i + 2:] if rnd2.random() < 0.6 else word[:i] + word[i] + word[i:]


three = [f"{h} {m} {l}" for h, m, l in zip(high, med, low)]
enwiki_more = {
    "EdismaxComplex": [ej(f"{h} {m}", params={
        "defType": "edismax", "qf": "body titleTokenized^3", "pf": "body^2", "pf2": "titleTokenized",
        "ps": "2", "mm": "2<75%", "tie": "0.1", "bq": "month:January^2", "boost": "log(sum(dayOfYear,1))"})
        for h, m in zip(high, med)],
    "EdismaxMinMatch": [ej(t, params={"defType": "edismax", "qf": "body", "mm": "2"}) for t in three],
    "EdismaxPhraseBoost": [ej(f"{m} {l}", params={"defType": "edismax", "qf": "body", "pf": "body^3", "ps": "1"})
                           for m, l in zip(med, low)],
    "SpellCheck": [ej(f"{misspell(m)} {misspell(l)}", limit=0) for m, l in zip(med, low)],
    "FacetTermsByAgg": [ej(m, limit=0, facet={"m": {"type": "terms", "field": "month", "sort": "x desc", "limit": 6,
                                                    "facet": {"x": "max(lastMod)", "a": "avg(dayOfYear)"}}})
                        for m in med],
    "FacetExcludeTags": [ej(m, limit=0, filter="{!tag=M}month:January", facet={
        "m": {"type": "terms", "field": "month", "domain": {"excludeTags": "M"}},
        "y": {"type": "terms", "field": "year", "limit": 5}}) for m in med],
    "FacetRangeNested": [ej(m, limit=0, facet={"y": {"type": "range", "field": "year", "start": 2001, "end": 2013,
                                                     "gap": 1, "facet": {"m": {"type": "terms", "field": "month",
                                                                               "limit": 3},
                                                                         "d": "avg(dayOfYear)"}}})
                         for m in med],
    "FacetRelatedness": [ej("*:*", limit=0, params={"fore": f"body:{m}", "back": "*:*"}, facet={
        "m": {"type": "terms", "field": "month", "limit": 12,
              "facet": {"r": "relatedness($fore,$back)"}}}) for m in med],
    "LegacyMultiSelectFacets": [ej(m, filter="{!tag=t}month:March", params={
        "facet": "true", "facet.field": ["{!ex=t}month", "year"], "facet.limit": "12"}) for m in med],
    "StatsComponent": [ej(h, limit=0, params={"stats": "true", "stats.field": [
        "dayOfYear", "{!countDistinct=true}month", "lastMod"]}) for h in high],
    "SurroundParser": [ej(f"{{!surround df=body}}3w({h}, {m})") for h, m in zip(high, med)],
    "BoolParser": [ej("{!bool must=$a should=$b filter=$c}", params={"a": f"body:{h}", "b": f"body:{m}",
                                                                      "c": "dayOfYear:[1 TO 200]"})
                   for h, m in zip(high, med)],
    "ReRank": [ej(h, params={"rq": "{!rerank reRankQuery=$rqq reRankDocs=200 reRankWeight=3}", "rqq": f"body:{m}"})
               for h, m in zip(high, med)],
    "FunctionSort": [ej(h, sort="div(dayOfYear,7) desc,lastMod asc") for h in high],
    "PrefixTermFieldParsers": [ej(f"{{!prefix f=titleTokenized}}{p}", filter="{!term f=month}May") for p in prefixes],
    "ExistsOnText": [ej(m, filter="titleTokenized:*") for m in med],
    "TimeAllowed": [ej(h, params={"timeAllowed": "5000"}) for h in high],
    "DebugExplain": [ej(f"{h} {m}", params={"debugQuery": "true"}) for h, m in zip(high, med)],
}
HANDLERS[("enwiki", "SpellCheck")] = ("/spell", False)
for name, rows in enwiki_more.items():
    write(f"{OUT}/enwiki/{name}.json", rows)
enwiki_terms = {"TermsComponent": [urllib.parse.urlencode({"terms.fl": "body", "terms.prefix": p, "terms.limit": 10})
                                   for p in prefixes]}
HANDLERS[("enwiki", "TermsComponent")] = ("/terms", True)
for name, rows in enwiki_terms.items():
    write(f"{OUT}/enwiki/{name}.txt", rows)
enwiki.update(enwiki_more)
enwiki.update(enwiki_terms)

with __import__("gzip").open("suites/datasets/geonames.json.gz", "rt") as f:
    places = [json.loads(next(f)) for _ in range(20000)][::700]
places = [p for p in places if p.get("location")][:20]
geonames_more = {
    "Highlight": [gq(q=n, hl="true", **{"hl.fl": "name,asciiname", "hl.method": "unified"}, fl="id,name")
                  for n in names],
    "EdismaxNames": [gq(q=n.split(":", 1)[1] + " " + c.split(":", 1)[1].lower(), defType="edismax",
                        qf="name^3 asciiname alternatenames", pf="name", mm="1", fl="id")
                     for n, c in zip(names, countries * 2)],
    "Geofilt": [gq(q="*:*", fq="{!geofilt}", sfield="location", pt=p["location"], d=50, sort="geodist() asc",
                   fl="id") for p in places],
    "MoreLikeThis": [gq(q=f"{{!mlt qf=name,admin1_code_raw mintf=1 mindf=1}}{p['id']}", fl="id") for p in places],
    "FacetHeatmap": [gq(q=c, rows=0, **{"json.facet": json.dumps(
        {"h": {"type": "heatmap", "field": "location", "geom": '["-180 -90" TO "180 90"]', "gridLevel": 2}})})
        for c in countries],
    "FacetQueryNested": [gq(q=c, rows=0, **{"json.facet": json.dumps(
        {"pop": {"type": "query", "q": "population:[1000 TO *]",
                 "facet": {"f": {"type": "terms", "field": "feature_code_raw", "limit": 5,
                                 "facet": {"e": "max(elevation)", "p": "sum(population)"}}}}})})
        for c in countries],
    "PivotWithStats": [gq(q=c, rows=0, facet="true", stats="true", **{
        "facet.pivot": "{!stats=s}feature_class_raw,admin1_code_raw", "facet.limit": 5,
        "stats.field": "{!tag=s}population"}) for c in countries],
    "IntervalFacets": [urllib.parse.urlencode([
        ("q", c), ("rows", 0), ("facet", "true"), ("facet.interval", "population"),
        ("f.population.facet.interval.set", "[0,1000)"), ("f.population.facet.interval.set", "[1000,100000)"),
        ("f.population.facet.interval.set", "[100000,*]")]) for c in countries],
    "SpellCheck": [gq(q=misspell(n.split(":", 1)[1]), rows=0) for n in names],
    "TermsComponent": [gq(**{"terms.fl": "name", "terms.prefix": n.split(":", 1)[1][:3], "terms.limit": 10})
                       for n in names],
}
HANDLERS[("geonames", "SpellCheck")] = ("/spell", True)
HANDLERS[("geonames", "TermsComponent")] = ("/terms", True)
for name, rows in geonames_more.items():
    write(f"{OUT}/geonames/{name}.txt", rows)
geonames.update(geonames_more)

# ---- ecommerce: JSON requests on the facet suite's 7-day windows; float price clauses and stats
windows = [ast.literal_eval(l)["query"] for l in lines(f"{Q}/facets-range.json")]
ecom = {
    "FloatRangeSort": [repr({"query": w, "filter": f"price:[{lo} TO {lo + 50}]", "limit": 10,
                             "sort": "price desc"}) for w, lo in ((w, rnd.randrange(0, 500)) for w in windows[:600])],
    "FloatStats": [repr({"query": w, "filter": "event_type:purchase", "limit": 0,
                         "facet": {"mn": "min(price)", "mx": "max(price)", "sd": "stddev(price)",
                                   "b": {"type": "terms", "field": "brand", "limit": 10,
                                         "facet": {"p": "max(price)"}}}}) for w in windows[:600]],
    "QueryFacets": [repr({"query": w, "limit": 0,
                          "facet": {"cheap": {"type": "query", "q": "price:[0 TO 50]"},
                                    "cart": {"type": "query", "q": "event_type:cart",
                                             "facet": {"a": "avg(price)"}}}}) for w in windows[:600]],
}
for name, rows in ecom.items():
    write(f"{OUT}/ecommerce/{name}.json", rows)


# ---- suites: the main suites with their query tasks replaced
def suite(base, out, tasks, task_spec):
    s = json.load(open(f"suites/{base}"))
    plan = s["execution-plan"]
    keep = {k: v for k, v in plan.items() if not v["type"].startswith("querying")}
    tt = {k: v for k, v in s["task-types"].items() if not k.startswith("querying")}
    last = max(keep, key=lambda k: int(k[4:]))
    n = int(last[4:])
    new_plan = dict(keep)
    for name, spec in tasks:
        n += 1
        tt[f"querying-{name}"] = task_spec(name, spec)
        new_plan[f"task{n}"] = {"description": f"{name} queries", "type": f"querying-{name}",
                                "instances": 1, "concurrency": 1, "wait-for": f"task{n - 1}", "mode": "sync"}
    s["task-types"], s["execution-plan"] = tt, new_plan
    with open(f"suites/{out}", "w") as f:
        json.dump(s, f, indent=2)


def enwiki_task(name, _):
    uri, form = HANDLERS.get(("enwiki", name), ("/select", False))
    t = {"name": f"{name} queries", "description": f"coverage: {name}", "collection": "enwiki",
         "query-file": f"queries/coverage/enwiki/{name}.{'txt' if form else 'json'}", "threads": [16],
         "shuffle": False, "total-count": 1530, "warm-count": 30}
    t.update({"http-method": "POST"} if form else {"json-query": True})
    if uri != "/select":
        t["uri"] = uri
    return {"query-benchmark": t}


def geonames_task(name, _):
    uri, _form = HANDLERS.get(("geonames", name), ("/select", True))
    t = {"name": f"{name} queries", "description": f"coverage: {name}", "collection": "geonames",
         "query-file": f"queries/coverage/geonames/{name}.txt", "http-method": "POST", "threads": [16],
         "shuffle": False, "duration-secs": 10, "warm-count": 16}
    if uri != "/select":
        t["uri"] = uri
    return {"query-benchmark": t}


def ecom_task(name, _):
    return {"query-benchmark": {"name": f"{name} queries", "description": f"coverage: {name}",
                                "collection": "ecommerce-events", "query-file": f"queries/coverage/ecommerce/{name}.json",
                                "threads": [16], "json-query": True, "shuffle": False,
                                "total-count": 1220, "warm-count": 20}}


for base, out, data, spec in [
        ("enwiki-local.json", "coverage-enwiki-local.json", enwiki, enwiki_task),
        ("luxir-enwiki-native-local.json", "luxir-coverage-enwiki-native-local.json", enwiki, enwiki_task),
        ("geonames-local.json", "coverage-geonames-local.json", geonames, geonames_task),
        ("luxir-geonames-local.json", "luxir-coverage-geonames-local.json", geonames, geonames_task),
        ("stress-facets-local-100m.json", "coverage-facets-local-100m.json", ecom, ecom_task),
        ("luxir-stress-facets-local-100m.json", "luxir-coverage-facets-local-100m.json", ecom, ecom_task)]:
    suite(base, out, list(data.items()), spec)
print("wrote", sum(map(len, (enwiki, geonames, ecom))), "query files and 6 suites")
