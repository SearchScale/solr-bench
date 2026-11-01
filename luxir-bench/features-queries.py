#!/usr/bin/env python3
"""Correctness workloads for the "features" collection (features-dataset.py): Solr's own field types and
components in a Luxir collection, for verify.py. Writes suites/queries/coverage/features/<Category>.txt and
manifest.json. Requests ordered by values end their sort with id.
Usage: luxir-bench/features-queries.py   (from the solr-bench directory)"""
import collections
import gzip
import json
import os
import urllib.parse

OUT = "suites/queries/coverage/features"
names = []
with gzip.open("suites/datasets/features.json.gz", "rt") as f:
    for i, line in enumerate(f):
        if i % 200 == 0:
            names.append(json.loads(line)["name"])
words = [w for w, _ in collections.Counter(
    w.lower() for n in names for w in n.split() if w.isalpha() and len(w) > 3).most_common(40)]


def w(i):
    return words[i % len(words)]


def q(*pairs, **params):
    out = []
    for k, v in list(pairs) + list(params.items()):
        for x in (v if isinstance(v, list) else [v]):
            out.append((k, x))
    return urllib.parse.urlencode(out)


cats = {}
cats["LuceneAnalyzedText"] = [q(q=c, fl="id,score", sort=s) for c, s in [
    (f"name_txt_en:{w(0)}s", "score desc,id asc"), (f"name_txt_en:\"{w(1)} {w(2)}\"~2", "score desc,id asc"),
    (f"name_txt_en:{w(3)[:4]}*", "id asc"), (f"name_txt_en:{w(4)}~1", "score desc,id asc"),
    (f"name_nn:{w(5)} name_nn:{w(6)}", "score desc,id asc"), (f"name_nf:{w(7)}", "score desc,id asc"),
    (f"+name_nf:{w(8)} +name_txt_en:{w(8)}", "id asc"), (f"name_txt_en:({w(9)} OR {w(10)}) -name_nn:{w(11)}", "score desc,id asc"),
    (f"{{!edismax qf='name_txt_en^2 name_nn name' pf=name_txt_en mm=1}}{w(12)} {w(13)}", "score desc,id asc")]] + [
    q(q="*:*", rows=0, facet="true", **{"facet.field": "name_txt_en", "facet.limit": 15, "facet.mincount": 10}),
    q(q=f"name_txt_en:{w(14)}", rows=0, **{"json.facet": json.dumps({"t": {"type": "terms", "field": "name_nf", "limit": 10}})})]
cats["Payloads"] = [q(q=c, fl=f, sort=s) for c, f, s in [
    (f"{{!payload_score f=tags_dpf v={w(0)} func=max}}", "id,score", "score desc,id asc"),
    (f"{{!payload_score f=tags_dpf v={w(1)} func=sum}}", "id,score", "score desc,id asc"),
    (f"{{!payload_score f=tags_dpf v={w(2)} func=average includeSpanScore=true}}", "id,score", "score desc,id asc"),
    (f"{{!payload_score f=tags_dpf v={w(3)} func=min}}", "id,score", "score desc,id asc"),
    (f"{{!payload_score f=tags_dpf v='{w(4)} {w(5)}' func=max operator=or}}", "id,score", "score desc,id asc"),
    ("{!payload_check f=tags_dpf payloads='3.0' v=" + w(6) + "}", "id", "id asc"),
    ("{!payload_check f=tags_dpf payloads='1.5 3.0' op=gte v='" + f"{w(7)} {w(8)}" + "'}", "id", "id asc"),
    (f"tags_dpf:{w(9)}", f"id,p:payload(tags_dpf,{w(9)})", "id asc"),
    (f"tags_dpf:{w(10)}", "id", f"payload(tags_dpf,{w(10)},0,max) desc,id asc")]]
cats["TermVectors"] = [q(q=c, sort="id asc", rows=3, fl="id", **p) for c, p in [
    (f"desc_tv:{w(0)}", {"tv.fl": "desc_tv", "tv.tf": "true", "tv.df": "true"}),
    (f"desc_tv:{w(1)}", {"tv.fl": "desc_tv", "tv.positions": "true", "tv.offsets": "true"}),
    (f"desc_tv:{w(2)}", {"tv.fl": "desc_tv", "tv.all": "true"}),
    (f"desc_tv:{w(3)} AND cc:US", {"tv.fl": "desc_tv", "tv.tf_idf": "true", "tv.df": "true"})]]
cats["TermVectorHighlighting"] = [q(q=c, sort="id asc", fl="id", hl="true", **p) for c, p in [
    (f"desc_tv:{w(4)}", {"hl.method": "fastVector", "hl.fl": "desc_tv"}),
    (f'desc_tv:"{w(5)} {w(6)}"~3', {"hl.method": "fastVector", "hl.fl": "desc_tv", "hl.fragsize": 30}),
    (f"desc_tv:{w(7)}", {"hl.method": "unified", "hl.fl": "desc_tv", "hl.offsetSource": "TERM_VECTORS"}),
    (f"desc_tv:{w(8)} desc_tv:{w(9)}", {"hl.method": "fastVector", "hl.fl": "desc_tv", "hl.tag.pre": "[", "hl.tag.post": "]"})]]
cats["SortableText"] = [q(q=c, sort=s, fl="id,name_sort") for c, s in [
    ("*:*", "name_sort asc,id asc"), ("cc:US", "name_sort desc,id asc"), (f"name_sort:{w(10)}", "name_sort asc,id asc")]] + [
    q(q="cc:FR", rows=0, **{"json.facet": json.dumps({"n": {"type": "terms", "field": "name_sort", "limit": 10}})}),
    q(q="cc:DE", rows=0, facet="true", **{"facet.field": "name_sort", "facet.limit": 10, "facet.sort": "index"})]
cats["EnumField"] = [q(q=c, sort=s, fl="id,fclass_enum") for c, s in [
    ("fclass_enum:P", "id asc"), ("fclass_enum:[H TO S]", "id asc"), ("fclass_enum:{L TO *]", "id asc"),
    ("cc:US", "fclass_enum desc,id asc"), ("cc:IN", "fclass_enum asc,pop desc,id asc")]] + [
    q(q="*:*", rows=0, facet="true", **{"facet.field": "fclass_enum", "facet.sort": "index"}),
    q(q="cc:CN", rows=0, **{"json.facet": json.dumps({"f": {"type": "terms", "field": "fclass_enum", "facet": {"p": "sum(pop)"}}})})]
cats["RankField"] = [q(q=f"name:{w(i)} {r}", fl="id,score", sort="score desc,id asc") for i, r in enumerate([
    "{!rank f=pop_rank function=log weight=2}", "{!rank f=pop_rank function=satu pivot=1000}",
    "{!rank f=pop_rank function=sigm pivot=1000 exponent=0.6}", "{!rank f=pop_rank function=log scalingFactor=2}"])]
cats["Currency"] = [q(q=c, fl="id,price_c", sort=s) for c, s in [
    ("price_c:[10,USD TO 20,USD]", "id asc"), ("price_c:[100,EUR TO *]", "price_c asc,id asc"),
    ("cc:US AND price_c:[* TO 5,GBP]", "price_c desc,id asc"), ("cc:JP", "currency(price_c,JPY) desc,id asc")]] + [
    q(q="cc:FR", fl="id,u:currency(price_c),e:currency(price_c,EUR)", sort="id asc"),
    q(q="*:*", fq="{!frange l=900 u=950}currency(price_c,USD)", sort="id asc", fl="id"),
    q(q="cc:IT", rows=0, facet="true", **{"facet.range": "price_c", "facet.range.start": "0,USD",
                                          "facet.range.end": "1000,USD", "facet.range.gap": "100,USD"})]
cats["Suggest"] = [q(**{"suggest.q": t, "suggest.dictionary": d, "suggest.count": 8}) for t, d in [
    (w(0)[:3], "infix"), (w(1)[:4], "infix"), (w(2), "infix"), (names[3][:4], "fuzzy"), (names[7][:3], "fuzzy"),
    (names[11][:5].lower(), "fuzzy"), (f"{w(3)} {w(4)[:2]}", "infix")]]

os.makedirs(OUT, exist_ok=True)
for name, rows in cats.items():
    with open(f"{OUT}/{name}.txt", "w") as f:
        f.write("\n".join(rows) + "\n")
with open(f"{OUT}/manifest.json", "w") as f:
    m = {name: "/select" for name in cats}
    m.update({"TermVectors": "/tvrh", "Suggest": "/suggest"})
    json.dump(m, f, indent=1)
print(f"wrote {sum(map(len, cats.values()))} requests in {len(cats)} categories to {OUT}")
