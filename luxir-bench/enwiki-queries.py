#!/usr/bin/env python3
"""Writes the enwiki suites' query files from luceneutil's wikimedium tasks: one file per category
under <out-dir>, each line a JSON request body (Solr's JSON Request API), plus All.json mixing every
category.

The tasks file is luceneutil's tasks/wikimedium.10M.nostopwords.tasks (Apache License 2.0, copied
in luxir-bench/enwiki/), whose lines are "<Category>: <task> # comment". Each task becomes the
Solr request that runs the query luceneutil's TaskParser builds for it, over the fields of
enwiki-jsonl.py, returning the top 10 ids by score (or by the task's sort):
  terms, boolean, phrase, sloppy phrase, prefix, wildcard and fuzzy tasks:
                         the same text with the classic query parser, default field body, OR
  near//a b              {!complexphrase}: a SpanNearQuery of a then b, slop 10, in order
  nrq//f a b             f:[a TO b] (an IntPoint range)
  intSet//f v...         {!terms f=f} (an IntPoint set)
  monthdvsort//text etc. the text, sorted by month / dayOfYear / title / lastMod, ascending
  ... +facets:T:Dim      the query plus a terms facet, top 10, on month / dayOfYear / year
                         (luceneutil's Date facet's top level is the year; taxonomy and sorted-set
                         variants of a facet become one category)
  ... +minShouldMatch=2  {!edismax} on body with mm=2
PKLookup, which luceneutil generates, looks up random ids of the first 10M documents.
Left out: RandomLabel facets (the dataset has no labels), the title sort on binary doc values
(the same sort as titledvsort in Solr), and categories with no Solr query parser equivalent
(intervals, respell, doc-values range exclusion, constant-score minShouldMatch, range facets).
Usage: enwiki-queries.py <tasks-file> <out-dir> [per-category, default 30]"""
import json, os, random, re, sys

tasks_path, out = sys.argv[1], sys.argv[2]
per_cat = int(sys.argv[3]) if len(sys.argv) > 3 else 30
SORTS = {"monthdvsort": "month asc", "dayofyeardvsort": "dayOfYear asc", "titledvsort": "title asc",
         "lastmodndvsort": "lastMod asc"}
FACETS = {"Month": "month", "DayOfYear": "dayOfYear", "Date": "year"}
SKIP = re.compile(r"RandomLabel|Intervals|Respell|MustNotIODVRange|ConstMSM2|AndMissingHigh|TitleBDVSort|SSDVFacets")
B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def to_id(n):
    return "".join(B36[(n // 36 ** i) % 36] for i in reversed(range(6)))


def request(task):
    """The JSON request body of one task, or None."""
    req = {"query": None, "limit": 10, "fields": "id", "params": {"df": "body", "q.op": "OR", "sow": "true"}}
    m = re.search(r" \+facets:(taxonomy|sortedset):(\w+)", task)
    if m:
        req["facet"] = {"f": {"type": "terms", "field": FACETS[m.group(2)], "limit": 10}}
        task = (task[:m.start()] + task[m.end():]).strip()
    if " +minShouldMatch=" in task:
        task, mm = task.split(" +minShouldMatch=")
        req["params"].update({"defType": "edismax", "qf": "body", "mm": mm})
        req["query"] = task.strip()
        return req
    kind, sep, rest = task.partition("//")
    if not sep:
        req["query"] = task
    elif kind == "near":
        a, b = rest.split(" ", 1)
        req["query"] = '{!complexphrase inOrder=true}body:"%s %s"~10' % (a, b.strip())
    elif kind == "nrq":
        f, lo, hi = rest.split()
        req["query"] = f"{f}:[{lo} TO {hi}]"
    elif kind == "intSet":
        f, *vals = rest.split()
        req["query"] = "{!terms f=%s}%s" % (f, ",".join(vals))
    elif kind in SORTS:
        req["query"] = rest
        req["sort"] = SORTS[kind]
    else:
        return None
    return req


by_cat = {}
for line in open(tasks_path, encoding="utf-8"):
    if line.startswith("#") or ":" not in line:
        continue
    cat, task = line.split(":", 1)
    if not re.fullmatch(r"[A-Z][A-Za-z0-9]*", cat) or SKIP.search(cat):  # "range:" lines are range facets
        continue
    task = task.split(" #", 1)[0].strip()
    params = request(task)
    if params is None:
        continue
    cat = cat.replace("TaxoFacets", "Facets")
    by_cat.setdefault(cat, []).append(params)

rng = random.Random(42)
by_cat["PKLookup"] = [{"query": "id:" + to_id(rng.randrange(10_000_000)), "limit": 10, "fields": "id"}
                      for _ in range(per_cat)]
os.makedirs(out, exist_ok=True)
everything = []
for cat in sorted(by_cat):
    reqs = by_cat[cat]
    # a fixed sample, in the tasks file's order
    picked = sorted(rng.sample(range(len(reqs)), min(per_cat, len(reqs))))
    lines = [json.dumps(reqs[i], ensure_ascii=False) for i in picked]
    everything += lines
    with open(os.path.join(out, cat + ".json"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"{cat}: {len(lines)} of {len(reqs)}")
rng.shuffle(everything)
with open(os.path.join(out, "All.json"), "w", encoding="utf-8") as f:
    f.write("\n".join(everything) + "\n")
print(f"All: {len(everything)}")
