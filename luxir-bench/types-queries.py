#!/usr/bin/env python3
"""Correctness workloads for the "types" collection (types-dataset.py): Solr request features across
every field type and shape, for verify.py to check Solr+Luxir against Solr+Lucene. Writes
suites/queries/coverage/types/<Category>.txt, one request per line (URL-encoded, or a JSON request body),
and manifest.json there: each category's handler.

Every request fixes NOW, so date math resolves alike on both systems, and requests whose results are
ordered by values (not scores) end their sort with id, so ties do not depend on internal doc order.
Usage: luxir-bench/types-queries.py   (from the solr-bench directory)"""
import collections
import gzip
import json
import os
import random
import urllib.parse

OUT = "suites/queries/coverage/types"
NOW = "1700000000000"  # 2023-11-14
rnd = random.Random(11)

docs = []
with gzip.open("suites/datasets/types.json.gz", "rt") as f:
    for i, line in enumerate(f):
        if i % 1000 == 0:
            docs.append(json.loads(line))
words = [w for w, _ in collections.Counter(
    w.lower() for d in docs for w in d["t_s"].split() if w.isalpha() and len(w) > 3).most_common(60)]
countries = [c for c, _ in collections.Counter(d["s_s"] for d in docs).most_common(30)]
small_countries = [c for c, _ in collections.Counter(d["s_s"] for d in docs).most_common()[-40:]]
codes = [c for c, _ in collections.Counter(x for d in docs for x in d["s_m"]).most_common(40)]
places = [d for d in docs if d["ll"] != "0.0,0.0"]


def pick(seq, k=None):
    return rnd.choice(seq) if k is None else rnd.sample(seq, k)


def two_words():
    a, b = pick(words, 2)
    return a, b


def phrase():
    """Two adjacent words of a real name."""
    while True:
        w = pick(docs)["t_s"].lower().split()
        w = [x for x in w if x.isalpha()]
        if len(w) >= 2:
            i = rnd.randrange(len(w) - 1)
            return w[i], w[i + 1]


def q(*pairs, **params):
    """A form-encoded request; NOW is always fixed."""
    p = list(pairs) + list(params.items()) + [("NOW", NOW)]
    out = []
    for k, v in p:
        for x in (v if isinstance(v, list) else [v]):
            out.append((k.replace("__", "."), x))
    return urllib.parse.urlencode(out)


def jq(body):
    """A JSON request body; NOW goes in its params."""
    body.setdefault("params", {})["NOW"] = NOW
    return json.dumps(body)


def date_lit(s):
    return s  # ISO-8601 instants, as stored


def val(d, f):
    v = d.get(f)
    return pick(v) if isinstance(v, list) else v


def lit(v):
    """A value as a query literal."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return '"' + v.replace('"', '\\"') + '"'
    return f'"{v}"'


SINGLE_NUM = ["i_s", "l_s", "f_s", "d_s"]
SPARSE = ["i_sp", "d_sp", "s_sp"]
MULTI_NUM = ["i_m", "l_m", "f_m"]
DATES = ["dt_s", "dt_m"]
ALL_SORTABLE = ["i_s", "l_s", "f_s", "d_s", "dt_s", "b_s", "s_s", "i_sp", "d_sp", "s_sp", "i_dv"]
FL = "id"
cats = {}
handlers = {}

# ---- lexical shapes on every type
term_rows = []
for _ in range(36):
    d = pick(docs)
    f = pick(["s_s", "s_m", "i_s", "l_s", "f_s", "d_s", "dt_s", "b_s", "i_m", "l_m", "f_m", "dt_m", "i_sp", "s_sp", "d_sp"])
    if d.get(f) is None:
        f = "s_s"
    term_rows.append(q(q=f"{f}:{lit(val(d, f))}", sort="id asc", fl=FL))
cats["TermPerType"] = term_rows


def range_clause(f):
    d1, d2 = pick(docs), pick(docs)
    if f in ("s_s", "s_m", "s_sp"):
        a, b = sorted([pick(countries + codes), pick(countries + codes)])
    elif f in DATES:
        a, b = sorted([val(d1, f), val(d2, f)])
    else:
        a, b = sorted([val(d1, f) or 0, val(d2, f) or 0])
    lo, hi = pick(["[", "{"]), pick(["]", "}"])
    form = rnd.randrange(4)
    if form == 0:
        return f"{f}:{lo}{lit(a) if isinstance(a, str) else a} TO {lit(b) if isinstance(b, str) else b}{hi}"
    if form == 1:
        return f"{f}:[* TO {lit(b) if isinstance(b, str) else b}{hi}"
    if form == 2:
        return f"{f}:{lo}{lit(a) if isinstance(a, str) else a} TO *]"
    return f"{f}:{lo}{lit(a) if isinstance(a, str) else a} TO {lit(a) if isinstance(a, str) else a}]"


cats["RangePerType"] = [q(q=range_clause(f), sort="id asc", fl=FL)
                        for f in (SINGLE_NUM + SPARSE + MULTI_NUM + DATES + ["s_s", "s_m"]) * 3]
cats["RangeCounts"] = [q(q="*:*", fq=[range_clause(f), range_clause(g)], rows=0)
                       for f, g in zip((SINGLE_NUM + MULTI_NUM + DATES) * 3, (SPARSE + DATES + SINGLE_NUM) * 4)]
cats["DateMath"] = [q(q=c, rows=0) for c in [
    "dt_s:[NOW-30YEARS/YEAR TO NOW/DAY]", "dt_m:[* TO NOW-40YEARS]", "dt_s:{NOW/YEAR-10YEARS TO NOW/YEAR}",
    "dt_s:[1990-01-01T00:00:00Z+6MONTHS TO 1990-01-01T00:00:00Z+1YEAR]", "dt_m:[NOW-1YEAR TO *]",
    "dt_s:[1999-12-31T23:59:59.999Z TO 2000-01-01T00:00:00Z]", "dt_s:[NOW/MONTH-300MONTHS TO NOW/MONTH-299MONTHS}",
    "+dt_s:[NOW-20YEARS TO NOW] +dt_m:[* TO NOW-50YEARS]"]] + [
    q(q="dt_s:[NOW/DAY-10000DAYS TO NOW/DAY-9000DAYS]", TZ=tz, rows=0) for tz in ("America/Los_Angeles", "Asia/Kolkata")]
cats["Exists"] = [q(q=c, rows=0) for f in ["i_s", "i_sp", "d_sp", "s_sp", "i_m", "dt_m", "b_s", "i_dv", "t_s", "ll", "f_m"]
                  for c in (f"{f}:*", f"{f}:[* TO *]", f"-{f}:*")]
cats["PureNegative"] = [q(q=c, sort="id asc", fl=FL) for c in [
    "-s_s:US", "-(s_s:US OR s_s:CA)", "(-s_s:US) AND (-s_s:CN)", "NOT s_m:PPL", "*:* -b_s:true",
    "+i_s:[0 TO 10] -s_m:PPL", "-i_sp:* -s_sp:*", "-t_s:church -t_s:creek", "-(-s_s:US)",
    "t_s:church -(s_s:US -b_s:true)"]] + [q(q=f"t_s:{w}", fq="-b_s:true", sort="id asc", fl=FL) for w in words[:6]]
cats["BooleanShapes"] = [q(q=c, fl="id,score") for c in [
    f"+t_s:{words[0]} +(s_s:US s_s:CA) -b_s:false", f"t_s:({words[1]} {words[2]})^2 s_s:US^=5",
    f"(t_s:{words[3]} OR t_m:{words[3]}) AND NOT s_s:US", f"t_s:{words[0]} && s_m:PPL || t_m:{words[4]}",
    f"((t_s:{words[5]} t_s:{words[6]}) +(b_s:true^3 i_s:[0 TO 100]^0.5)) -s_s:CN",
    f"t_s:{words[7]}^0.1 t_m:{words[7]}^10", f"+(t_s:{words[8]} t_m:{words[9]}) +s_s:({' '.join(countries[:5])})",
    f"t_s:{words[10]} s_m:{codes[0]}^=0.5 s_m:{codes[1]}^=0.25"]]
cats["MultiTerm"] = [q(q=c, sort="id asc", fl=FL) for c in [
    f"t_s:{words[0][:4]}*", f"t_m:{words[1][0]}?{words[1][2:4]}*", "s_m:PP*", "s_s:U?", "s_sp:0*",
    f"t_s:/{words[2][:3]}[a-z]+/", "s_s:/[A-C][A-Z]/", f"t_s:{words[3][:-1]}x~1", f"t_m:{words[4]}~2", "s_m:PPLA~1",
    f"t_s:*{words[5][-3:]}", "t_m:/sa.*o/", f"t_s:{words[6][:3]}*^3", "s_m:[PPL TO PPLX]"]]
cats["Phrases"] = [q(q=c, fl="id,score") for c in
                   [f't_s:"{a} {b}"' for a, b in (phrase() for _ in range(5))]
                   + [f't_m:"{a} {b}"~2' for a, b in (phrase() for _ in range(4))]
                   + [f't_s:"{b} {a}"~3' for a, b in (phrase() for _ in range(3))]
                   + ["{!field f=t_s}first baptist church", "{!lucene df=t_m}\"mount hope\"~1"]]

# ---- query parsers
cats["TermTermsRawPrefix"] = [q(q=c, sort="id asc", fl=FL) for c in [
    "{!term f=s_m}PPL", "{!term f=i_s}0", "{!term f=b_s}true", f"{{!term f=dt_s}}{docs[5]['dt_s']}",
    f"{{!terms f=s_s}}{','.join(countries[:4])}", "{!terms f=i_m}1,2,3", "{!terms f=l_s separator=\" \"}0 100 1000",
    f"{{!terms f=s_m method=booleanQuery}}{','.join(codes[:5])}", f"{{!terms f=s_m method=automaton}}{','.join(codes[:5])}",
    f"{{!terms f=s_s method=docValuesTermsFilter}}{','.join(countries[5:9])}",
    f"{{!terms f=s_s method=docValuesTermsFilterTopLevel}}{','.join(countries[5:9])}",
    f"{{!terms f=s_s method=docValuesTermsFilterPerSegment}}{','.join(countries[5:9])}",
    f"{{!terms f=s_s method=termsFilter}}{','.join(countries[9:12])}",
    "{!terms f=f_m}0.0,1.5", "{!raw f=s_s}US", f"{{!prefix f=t_s}}{words[0][:3]}", "{!prefix f=s_m}PP"]]
cats["NestedAndFilters"] = [q(q=c, fl="id,score") for c in [
    f'_query_:"{{!term f=s_s}}US" AND t_s:{words[0]}', f"+filter(s_s:US) +filter(b_s:true) t_s:{words[1]}",
    f"{{!lucene q.op=AND df=t_m}}{words[2]} {words[3]}", f"filter(t_s:{words[4]}) t_m:{words[4]}",
    f"{{!cache=false}}t_s:{words[5]}", f"t_s:{words[6]} filter(i_s:[0 TO 500])"]] + [
    q(q="{!lucene df=t_s v=$qq}", qq=f"{words[7]} {words[8]}", fl="id,score"),
    q(q=f"t_s:{words[9]}", fq=["{!cache=false cost=10}s_m:PPL", "{!cost=200 cache=false}i_s:[0 TO 1000]", "b_s:true"],
      fl="id,score")]
cats["OtherParsers"] = [q(q=c, fl="id,score") for c in [
    f'{{!complexphrase inOrder=true}}t_m:"{words[0][:5]}* {words[1][:5]}*"',  # few enough terms for 1024 clauses
    f'{{!complexphrase inOrder=false df=t_s}}"{words[2][:4]}* {words[3]}"',
    f"{{!simple qf='t_s t_m'}}{words[4]} +{words[5]} -{words[6]}",
    f'{{!simple qf=t_s q.operators=AND,OR,PREFIX,PHRASE}}"{words[7]} {words[8]}" | {words[9][:3]}*',
    '{!xmlparser}<BooleanQuery fieldName="t_s"><Clause occurs="must"><TermQuery>' + words[10]
    + '</TermQuery></Clause><Clause occurs="filter"><TermQuery fieldName="s_s">US</TermQuery></Clause></BooleanQuery>',
    f'{{!xmlparser}}<SpanNear slop="2" inOrder="true"><SpanTerm fieldName="t_m">{words[11]}</SpanTerm>'
    f'<SpanTerm fieldName="t_m">{words[12]}</SpanTerm></SpanNear>',
    f'{{!xmlparser}}<UserQuery>t_s:{words[13]} -s_s:US</UserQuery>']] + [
    q(q="{!switch case.us=s_s:US case.ca=s_s:CA default=*:* v=$c}", c=c, sort="id asc", fl=FL) for c in ("us", "ca", "zz")]
cats["Dismax"] = [q(q=f"{a} {b}", defType="dismax", qf="t_s^2 t_m", mm=mm, fl="id,score", **extra)
                  for (a, b), mm, extra in zip((two_words() for _ in range(8)), ["1", "2", "1", "100%"] * 2,
                                               [{}, {"pf": "t_s^3", "ps": "1"}, {"tie": "0.3"},
                                                {"bq": "b_s:true^2"}, {"bf": "log(sum(l_s,1))"},
                                                {"qs": "1"}, {"pf": "t_m", "bq": "s_s:US"}, {}])]
cats["EdismaxVariants"] = [q(q=qq, defType="edismax", fl="id,score", **p) for qq, p in [
    (f"t_s:{words[0]} s_s:US", {"qf": "t_m", "uf": "t_s s_s"}),
    (f"{words[1]} {words[2]} {words[3]}", {"qf": "t_s t_m", "pf2": "t_s^2", "pf3": "t_m^3", "ps2": "1", "ps3": "2"}),
    (f"{words[4]} {words[5]} {words[6]} {words[7]}", {"qf": "t_s", "mm": "2<-1 5<80%"}),
    (f"{words[8]} {words[9]}", {"qf": "t_s t_m", "bf": "sqrt(i_dv)"}),
    (f"{words[10]} and {words[11]}", {"qf": "t_s", "lowercaseOperators": "true"}),
    (f"{words[12]} {words[13]}", {"qf": "t_s", "sow": "false"}),
    (f"{words[14]} {words[15]}", {"qf": "t_s t_m^0.5 s_s^10"}),
    (f"{words[16][:4]}* -{words[17]}", {"qf": "t_s"}),
    (f'"{words[18]} {words[19]}" {words[20]}', {"qf": "t_s t_m", "pf": "t_s"}),
    (f"{words[21]} {words[22]}", {"qf": "t_s", "boost": "if(b_s,2,1)"}),
    (f"{words[23]} {words[24]}", {"qf": "t_m", "mm": "1", "bq": "{!func}log(sum(l_s,1))"}),
    (f"{words[25]}~1 {words[26]}", {"qf": "t_s", "mm.autoRelax": "true"})]]
cats["BoostAndFunctionQueries"] = [q(q=c, fl="id,score", **p) for c, p in [
    (f"{{!boost b=log(sum(l_s,2))}}t_s:{words[0]}", {}), (f"{{!boost b=if(b_s,2,1)}}t_m:{words[1]}", {}),
    (f"{{!boost b=recip(ms(NOW,dt_s),3.16e-11,1,1)}}t_s:{words[2]}", {}), ("{!func}sum(i_s,1)", {}),
    ("{!func}log(sum(l_s,1))", {}), ("{!func}geodist(ll,40.7,-74.0)", {"sort": "score asc"}),
    ("{!func}if(exists(i_sp),i_sp,0)", {}), ("{!func}field(i_m,max)", {}),
    (f"{{!func}}termfreq(t_m,'{words[3]}')", {}), ("{!func}ms(dt_s,1970-01-01T00:00:00Z)", {}),
    (f"{{!func}}query($qq)", {"qq": f"t_s:{words[4]}"})]]
cats["Frange"] = [q(q=qq, fq=c, sort="id asc", fl=FL) for qq, c in [
    ("*:*", "{!frange l=100 u=200}i_s"), ("s_s:US", "{!frange l=0 u=1 incl=false incu=true}f_s"),
    ("*:*", "{!frange l=100000}l_s"), (f"t_s:{words[0]}", "{!frange l=10 cache=false cost=200}i_dv"),
    ("*:*", "{!frange l=1 u=1}exists(i_sp)"), ("s_s:CN", "{!frange l=0}sub(i_s,i_sp)"),
    ("*:*", "{!frange l=0.5}div(l_s,sum(l_s,1))"), ("s_s:IN", "{!frange l=1000 cost=150 cache=false}ms(NOW,dt_s)"),
    ("*:*", "{!frange l=40 u=45}field(i_m,max)"), ("*:*", "{!frange l=-0.001 u=0.001}d_sp"),
    ("s_m:PPL", "{!frange l=50 u=60}f_s"), ("*:*", "{!frange u=-170}field(f_m,min)")]]
cats["JoinGraphMlt"] = [q(q=c, sort="id asc", fl=FL) for c in [
    f"{{!join from=s_s to=s_s}}t_s:{words[0]}", f"{{!join from=i_s to=i_sp}}t_s:{words[1]}",
    f"{{!join from=s_sp to=s_sp}}t_s:{words[2]} AND s_s:US",
    f"{{!graph from=s_sp to=s_sp maxDepth=1}}t_s:{words[3]}",
    f"{{!graph from=s_s to=s_sp returnRoot=false maxDepth=1}}id:{docs[7]['id']}"]] + [
    q(q=f"{{!join from=s_sp to=s_sp score=max}}t_s:{words[4]}", fl="id,score")] + [
    q(q=f"{{!mlt qf=t_s,t_m mintf=1 mindf=1}}{d['id']}", fl="id,score") for d in pick(docs, 6)]
cats["JsonQueryDsl"] = [jq(b) for b in [
    {"query": {"bool": {"must": [f"t_s:{words[0]}"], "filter": ["s_s:US"], "must_not": ["b_s:false"],
                        "should": [{"lucene": {"df": "t_m", "query": words[1]}}]}}, "fields": "id,score"},
    {"query": {"boost": {"query": f"t_s:{words[2]}", "b": "log(sum(l_s,2))"}}, "fields": "id,score"},
    {"query": {"field": {"f": "t_s", "query": f"{words[3]} {words[4]}"}}, "fields": "id,score"},
    {"query": {"terms": {"f": "s_s", "terms": "US,CA"}}, "sort": "id asc", "fields": "id"},
    {"query": "*:*", "filter": [{"frange": {"query": "i_s", "l": 100, "u": 200}}, "b_s:true"], "sort": "id asc",
     "fields": "id"},
    {"queries": {"cities": "s_m:PPL"}, "query": {"bool": {"must": [{"param": "cities"}], "filter": ["s_s:FR"]}},
     "sort": "id asc", "fields": "id"},
    {"query": {"dismax": {"qf": "t_s t_m", "query": f"{words[5]} {words[6]}", "mm": 1}}, "fields": "id,score"},
    {"query": {"bool": {"should": [f"t_s:{words[7]}", f"t_s:{words[8]}", f"t_m:{words[9]}"], "mm": 2}},
     "fields": "id,score"}]]

# ---- result shaping
cats["SortSingleValued"] = [q(q=qq, sort=f"{f} {d},id asc", fl=FL) for f in ALL_SORTABLE for d, qq in
                            (("asc", pick(["*:*", "s_s:US", f"t_s:{pick(words)}"])),
                             ("desc", pick(["s_m:PPL", f"t_m:{pick(words)}", "b_s:true"])))]
cats["SortMultiValued"] = [q(q=qq, sort=s, fl=FL) for qq, s in [
    ("*:*", "i_m asc,id asc"), ("s_s:US", "i_m desc,id asc"), ("*:*", "l_m desc,id asc"), ("s_m:PPL", "f_m asc,id asc"),
    ("*:*", "dt_m asc,id asc"), ("b_s:true", "dt_m desc,id asc"), ("*:*", "s_m asc,id asc"), ("s_s:CN", "s_m desc,id asc"),
    ("*:*", "field(i_m,max) asc,id asc"), ("*:*", "field(f_m,min) desc,id asc")]]  # (field(s_m,min): a Solr bug)
cats["SortFunctions"] = [q(q=qq, sort=s, fl=FL, **p) for qq, s, p in [
    ("s_s:US", "sum(i_s,l_s) desc,id asc", {}), ("*:*", "def(i_sp,-1) asc,id asc", {}),
    ("s_m:PPL", "if(b_s,1,0) desc,l_s desc,id asc", {}), ("s_s:IN", "ms(dt_s) asc,id asc", {}),
    ("*:*", "geodist(ll,40.7,-74.0) asc,id asc", {}), ("s_s:FR", "div(l_s,sum(i_s,1)) desc,id asc", {}),
    ("*:*", "abs(d_sp) desc,id asc", {}), (f"t_s:{words[0]}", "score desc,id asc", {}),
    (f"t_s:{words[1]}", "score asc,id asc", {}), ("s_s:US", "query($qq) desc,id asc", {"qq": f"t_s:{words[2]}"}),
    ("s_s:MX", "strdist(s_sp,\"01\",edit) desc,id asc", {}), ("*:*", f"termfreq(t_m,'{words[3]}') desc,id asc", {}),
    ("s_s:RU", "geodist() asc,id asc", {"sfield": "ll", "pt": "55.75,37.6"}),
    ("*:*", "sub(f_s,d_s) asc,id asc", {}), ("s_s:DE", "i_dv desc,dt_s asc,id asc", {})]]
cats["Paging"] = [q(q=qq, sort="l_s desc,id asc", start=s, rows=r, fl="id,l_s") for qq, s, r in [
    ("*:*", 0, 50), ("*:*", 500, 10), ("s_s:US", 5000, 20), ("s_m:PPL", 100000, 5), ("s_s:AD", 10000, 10),
    ("*:*", 2279290, 20), ("s_s:CN", 0, 0)]] + [
    q(q=qq, sort=s, cursorMark="*", rows=25, fl=FL) for qq, s in [
        ("s_s:US", "l_s desc,id asc"), ("*:*", "dt_s asc,id asc"), ("s_m:PPL", "d_sp desc,id asc"),
        ("b_s:true", "f_s asc,i_s desc,id asc"), ("*:*", "s_sp asc,id asc")]]
cats["FieldListFunctions"] = [q(q=qq, sort="id asc", fl=f, **p) for qq, f, p in [
    ("s_s:US", "id,s:sum(i_s,1),l:log(sum(l_s,1)),e:exists(i_sp),d:def(d_sp,-1),m:max(f_s,d_s)", {}),
    ("s_s:CN", "id,mi:field(i_m,min),ma:field(dt_m,max),g:geodist(ll,40,-74),ms:ms(dt_s),b:if(b_s,'y','n')", {}),
    (f"t_s:{words[0]}", f"id,tf:termfreq(t_s,'{words[0]}'),df:docfreq(t_s,'{words[0]}'),"
                        f"ttf:totaltermfreq(t_s,'{words[0]}'),stf:sumtotaltermfreq(t_s),nd:numdocs(),md:maxdoc()", {}),
    ("s_s:IN", "id,str:strdist(s_s,'IN',jw),mp:map(i_s,0,100,1,0),rc:recip(i_s,1,1000,1000),q:query($qq)",
     {"qq": f"t_s:{words[1]}"}),
    ("s_s:MX", "id,a:abs(d_sp),p:pow(i_dv,2),sq:sqrt(i_dv),c:ceil(f_s),fl:floor(d_s),r:rint(f_s),sb:sub(l_s,i_s),mu:mul(i_s,f_s)", {}),
    ("s_s:AU", "*", {}), ("s_s:BR", "*,score", {}), ("s_s:NO", "id,s_*,i_*", {}), ("s_s:ID", "id,i_dv,b_s,ll,rpt", {}),
    ("s_s:CA", "id,dt_m,f_m,l_m,t_m", {}), ("s_s:TH", "id,sc:scale(i_s,0,1)", {})]]
cats["CollapseExpand"] = [q(q=qq, fq=c, sort=s, fl="id,score", **p) for qq, c, s, p in [
    # heads by score then id: by score alone, which of tied docs heads its group depends on doc order
    (f"t_s:{words[0]}", "{!collapse field=s_s sort='score desc,id asc'}", "score desc,id asc", {}),
    ("s_m:PPL", "{!collapse field=s_s min=ms(dt_s)}", "id asc", {}),
    ("s_m:PPL", "{!collapse field=s_s max=ms(dt_s)}", "l_s desc,id asc", {}),
    ("*:*", "{!collapse field=s_s sort='l_s desc,id asc'}", "id asc", {}),
    ("s_s:US", "{!collapse field=s_sp nullPolicy=expand sort='dt_s asc,id asc'}", "id asc", {}),
    ("s_s:US", "{!collapse field=s_sp nullPolicy=collapse sort='dt_s asc,id asc'}", "id asc", {}),
    ("s_s:US", "{!collapse field=s_sp nullPolicy=ignore sort='dt_s asc,id asc'}", "id asc", {}),
    ("b_s:true", "{!collapse field=i_dv sort='l_s desc,id asc'}", "id asc", {}),
    ("s_m:PPL", "{!collapse field=s_s sort='l_s desc,id asc'}", "l_s desc,id asc",
     # expand over one shard: over several, Solr reports one shard's count per group, whichever answers last
     {"expand": "true", "expand.rows": 3, "expand.sort": "l_s desc,id asc", "shards": "shard1"}),
    ("*:*", "{!collapse field=s_s sort='dt_s desc,id asc'}", "id asc",
     {"expand": "true", "expand.rows": 2, "expand.sort": "dt_s desc,id asc", "expand.q": "b_s:true",
      "shards": "shard1"})]]
cats["GroupingVariants"] = [q(q=qq, group="true", fl="id", **p) for qq, p in [
    ("s_m:PPL", {"group.field": "s_s", "sort": "l_s desc,id asc", "group.sort": "l_s desc,id asc", "group.ngroups": "true"}),
    ("*:*", {"group.field": "b_s", "sort": "id asc", "group.sort": "id asc", "group.limit": 2}),
    # (group.sort needs a sort here: without one, distributed group.query fails on Solr alike)
    ("*:*", {"group.query": ["b_s:true", "s_s:US", "i_s:[0 TO 10]"], "sort": "id asc", "group.sort": "id asc",
             "group.limit": 3}),
    ("s_s:US", {"group.func": "floor(div(i_dv,100))", "sort": "id asc", "group.sort": "id asc"}),
    ("s_s:CN", {"group.field": "s_sp", "group.limit": 3, "group.offset": 1, "sort": "id asc", "group.sort": "dt_s desc,id asc"}),
    ("s_s:IN", {"group.field": "s_s", "group.format": "simple", "group.sort": "id asc", "sort": "id asc"}),
    ("s_s:MX", {"group.field": "s_sp", "group.main": "true", "group.sort": "id asc", "sort": "id asc"}),
    ("s_m:PPL", {"group.field": "s_s", "group.facet": "true", "facet": "true", "facet.field": "b_s",
                 "sort": "id asc", "group.sort": "id asc"}),
    ("s_m:STM", {"group.field": "s_s", "group.truncate": "true", "facet": "true", "facet.field": "s_m",
                 "sort": "id asc", "group.sort": "id asc", "group.ngroups": "true"}),
    ("b_s:true", {"group.field": "dt_s", "sort": "dt_s desc,id asc", "group.sort": "id asc"})]]

# ---- facets and stats
legacy = []
for f in ["s_s", "s_m", "s_sp", "b_s", "i_s", "i_m", "dt_s", "f_s", "l_m", "i_dv"]:
    for method in ("", "enum", "fc", "fcs", "uif"):
        if method == "fcs" and f in ("s_m", "i_m", "l_m"):
            continue
        p = {"facet": "true", "facet.field": f, "facet.limit": 8, "facet.mincount": 1}
        if method:
            p["facet.method"] = method
        legacy.append(q(q=pick(["*:*", "s_m:PPL", f"t_s:{pick(words)}"]), rows=0, **p))
legacy += [q(q="*:*", rows=0, facet="true", **p) for p in [
    {"facet.field": "s_s", "facet.prefix": "C", "facet.limit": 20}, {"facet.field": "s_m", "facet.contains": "PP"},
    {"facet.field": "s_m", "facet.contains": "ppl", "facet.contains.ignoreCase": "true"},
    {"facet.field": "s_s", "facet.sort": "index", "facet.limit": 15, "facet.offset": 3},
    {"facet.field": "s_sp", "facet.missing": "true", "facet.mincount": 50},
    {"facet.field": "b_s", "facet.limit": -1}, {"facet.field": "s_s", "facet.method": "enum", "facet.exists": "true"},
    {"facet.field": "s_m", "facet.sort": "count", "facet.limit": 5, "facet.offset": 2, "facet.method": "uif"}]]
cats["LegacyFacetFieldVariants"] = legacy
cats["LegacyFacetQueryRange"] = [q(q=pick(["*:*", "s_s:US", "s_m:PPL"]), rows=0, facet="true", **p) for p in [
    {"facet.query": ["b_s:true", "i_s:[0 TO 100]", "dt_s:[NOW-30YEARS TO *]", "{!key=pop}l_s:[1000 TO *]"]},
    {"facet.range": "i_s", "facet.range.start": -500, "facet.range.end": 5000, "facet.range.gap": 500,
     "facet.range.other": "all"},
    {"facet.range": "l_s", "facet.range.start": 0, "facet.range.end": 1000000, "facet.range.gap": 100000,
     "facet.range.include": "edge", "facet.range.hardend": "true"},
    {"facet.range": "f_s", "facet.range.start": -90, "facet.range.end": 90, "facet.range.gap": 15.5,
     "facet.range.include": ["lower", "upper"], "facet.range.other": "before"},
    {"facet.range": "d_s", "facet.range.start": -180, "facet.range.end": 180, "facet.range.gap": 45,
     "facet.range.include": "outer", "facet.range.other": ["after", "between"]},
    {"facet.range": "dt_s", "facet.range.start": "NOW/YEAR-60YEARS", "facet.range.end": "NOW/YEAR+10YEARS",
     "facet.range.gap": "+5YEARS", "facet.range.other": "all"},
    {"facet.range": "dt_m", "facet.range.start": "1970-01-01T00:00:00Z", "facet.range.end": "2030-01-01T00:00:00Z",
     "facet.range.gap": "+10YEARS", "facet.range.include": "all"},
    {"facet.range": "i_m", "facet.range.start": 0, "facet.range.end": 50, "facet.range.gap": 7,
     "facet.range.method": "dv"},
    {"facet.range": "i_s", "facet.range.start": 0, "facet.range.end": 3000, "facet.range.gap": 250,
     "facet.range.method": "filter"},
    {"facet.range": "d_sp", "facet.range.start": -1e6, "facet.range.end": 1e6, "facet.range.gap": 2e5,
     "facet.range.other": "all", "facet.mincount": 1}]] + [
    q(q="s_s:US", fq="{!tag=b}b_s:true", rows=0, facet="true",
      **{"facet.query": ["{!ex=b}b_s:true", "{!ex=b key=all}*:*"], "facet.field": "{!ex=b}b_s"})]
cats["LegacyPivotIntervalHeatmap"] = [q(q=pick(["*:*", "s_m:PPL", "b_s:true"]), rows=0, facet="true", **p) for p in [
    {"facet.pivot": "s_s,b_s", "facet.pivot.mincount": 2, "facet.limit": 5},
    {"facet.pivot": "s_m,s_s", "facet.limit": 4},
    {"facet.pivot": "{!range=r1}s_s", "facet.range": "{!tag=r1}i_s", "facet.range.start": 0, "facet.range.end": 3000,
     "facet.range.gap": 1000, "facet.limit": 3},
    {"facet.pivot": "{!query=q1}s_s,b_s", "facet.query": "{!tag=q1}i_s:[0 TO 100]", "facet.limit": 3},
    {"facet.interval": "f_s", "f.f_s.facet.interval.set": ["[-90,0)", "[0,30)", "[30,90]", "(45,*]"]},
    {"facet.interval": "dt_s", "f.dt_s.facet.interval.set": ["[*,1990-01-01T00:00:00Z)",
                                                             "[1990-01-01T00:00:00Z,NOW]", "(NOW,*]"]},
    {"facet.interval": "l_m", "f.l_m.facet.interval.set": ["[*,0)", "[0,1000000000]", "(1000000000,*]"]},
    {"facet.interval": "{!key=pop}l_s", "f.l_s.facet.interval.set": ["{!key=none}[0,0]", "{!key=some}(0,*]"]},
    {"facet.heatmap": "rpt", "facet.heatmap.geom": '["-180 -90" TO "180 90"]', "facet.heatmap.gridLevel": 2},
    {"facet.heatmap": "rpt", "facet.heatmap.geom": '["0 40" TO "20 55"]', "facet.heatmap.distErrPct": 0.15}]]


def jf(query, facet, **p):
    return q(q=query, rows=0, **{"json.facet": json.dumps(facet)}, **p)


tf = []
for f in ["s_s", "s_m", "s_sp", "b_s", "i_s", "i_m", "l_s", "f_s", "d_s", "dt_s", "dt_m", "i_dv"]:
    for method in ("", "dv", "uif", "enum", "stream"):
        if method == "stream" and f not in ("s_s", "s_m", "s_sp"):
            continue
        if method == "enum" and f not in ("s_s", "s_m", "s_sp", "b_s"):
            continue
        facet = {"type": "terms", "field": f, "limit": 6, "facet": {"n": "max(l_s)"}}
        if method:
            facet["method"] = method
        if method == "stream":
            facet["sort"] = "index asc"
        tf.append(jf(pick(["*:*", "s_m:PPL", f"t_s:{pick(words)}"]), {"x": facet}))
tf += [jf(qq, fct) for qq, fct in [
    ("*:*", {"x": {"type": "terms", "field": "s_s", "sort": "index asc", "offset": 5, "limit": 5}}),
    ("*:*", {"x": {"type": "terms", "field": "s_s", "sort": "count asc", "limit": 5, "mincount": 1}}),
    ("s_s:US", {"x": {"type": "terms", "field": "s_sp", "missing": True, "allBuckets": True, "numBuckets": True,
                      "limit": 5}}),
    ("*:*", {"x": {"type": "terms", "field": "s_m", "prefix": "PP", "sort": "a desc", "limit": 4,
                   "facet": {"a": "avg(i_s)"}}}),
    ("*:*", {"x": {"type": "terms", "field": "s_s", "limit": 3, "refine": True, "overrequest": 0,
                   "facet": {"y": {"type": "terms", "field": "b_s"}}}}),
    ("s_m:PPL", {"x": {"type": "terms", "field": "s_s", "limit": 4,
                       "facet": {"y": {"type": "terms", "field": "s_sp", "limit": 2, "facet": {"m": "min(dt_s)"}}}}}),
    ("*:*", {"q": {"type": "query", "q": "b_s:true", "facet": {"s": {"type": "terms", "field": "s_m", "limit": 3}}}}),
    ("s_s:US", {"x": {"type": "terms", "field": "b_s", "domain": {"query": "*:*"}}}),
    ("s_s:US", {"x": {"type": "terms", "field": "s_s", "limit": 5, "domain": {"excludeTags": "c"}}}),
    ("*:*", {"x": {"type": "terms", "field": "s_m", "limit": 5, "domain": {"filter": ["b_s:true", "i_s:[0 TO 100]"]}}}),
    ("*:*", {"x": {"type": "terms", "field": "s_s", "limit": 5, "sort": "r desc",
                   "facet": {"r": "relatedness($fore,$back)"}}})]]
tf[-3] = q(q="s_s:US", fq="{!tag=c}s_s:US", rows=0, **{"json.facet": json.dumps(
    {"x": {"type": "terms", "field": "s_s", "limit": 5, "domain": {"excludeTags": "c"}}})})
tf[-1] = q(q="*:*", rows=0, fore="b_s:true", back="*:*", **{"json.facet": json.dumps(
    {"x": {"type": "terms", "field": "s_s", "limit": 5, "sort": "r desc", "facet": {"r": "relatedness($fore,$back)"}}})})
cats["JsonTermsFacets"] = tf
cats["JsonRangeFacets"] = [jf(pick(["*:*", "s_m:PPL", "s_s:US"]), {"r": fct}) for fct in [
    {"type": "range", "field": "i_s", "start": -500, "end": 5000, "gap": 500, "other": "all"},
    {"type": "range", "field": "l_s", "start": 0, "end": 1000000, "gap": 100000, "hardend": True, "include": "edge"},
    {"type": "range", "field": "f_s", "start": -90, "end": 90, "gap": 22.5, "include": ["lower", "upper"]},
    {"type": "range", "field": "d_s", "start": -180, "end": 180, "gap": 60, "other": ["before", "after"]},
    {"type": "range", "field": "d_sp", "start": -1e6, "end": 1e6, "gap": 2.5e5, "facet": {"a": "avg(d_sp)"}},
    {"type": "range", "field": "dt_s", "start": "NOW/YEAR-60YEARS", "end": "NOW/YEAR", "gap": "+10YEARS",
     "facet": {"u": "unique(s_s)"}},
    {"type": "range", "field": "dt_m", "start": "1970-01-01T00:00:00Z", "end": "2030-01-01T00:00:00Z", "gap": "+20YEARS"},
    {"type": "range", "field": "i_m", "start": 0, "end": 50, "gap": 10},
    {"type": "range", "field": "l_s", "ranges": [{"from": 0, "to": 1000}, {"from": 1000, "to": 100000, "inclusive_to": True},
                                                {"range": "(100000,*]"}]},
    {"type": "range", "field": "dt_s", "ranges": [{"range": "[*,1980-01-01T00:00:00Z)"},
                                                 {"range": "[1980-01-01T00:00:00Z,NOW]"}]},
    {"type": "range", "field": "i_dv", "start": 0, "end": 1000, "gap": 100, "facet": {"b": {"type": "terms", "field": "b_s"}}}]]
aggs = []
for f in ["i_s", "l_s", "f_s", "d_s", "d_sp", "i_sp", "i_m", "l_m", "f_m", "dt_s", "dt_m", "i_dv"]:
    a = {"sum": f"sum({f})", "avg": f"avg({f})", "min": f"min({f})", "max": f"max({f})", "sq": f"sumsq({f})",
         "var": f"variance({f})", "sd": f"stddev({f})", "u": f"unique({f})", "h": f"hll({f})",
         "cv": f"countvals({f})", "mi": f"missing({f})"}
    if f in ("dt_s", "dt_m"):
        a = {k: v for k, v in a.items() if k in ("min", "max", "u", "h", "cv", "mi", "avg")}
    aggs.append(jf(pick(["*:*", "s_m:PPL", "s_s:US", f"t_s:{pick(words)}"]), a))
    aggs.append(jf("*:*", {"b": {"type": "terms", "field": "s_s", "limit": 4, "facet": a}}))
# (no percentile(): Solr's t-digest answer depends on the order values arrive in, run to run)
aggs += [jf("*:*", a) for a in [
    {"f1": "sum(mul(i_s,2))", "f2": "avg(sum(i_s,l_s))", "f3": "min(ms(dt_s))", "f4": "unique(s_m)", "f5": "hll(s_sp)",
     "f6": "max(def(i_sp,-1))", "f7": "countvals(s_m)", "f8": "missing(s_sp)"}]]
cats["JsonAggregations"] = aggs
cats["StatsVariants"] = [q(q=pick(["*:*", "s_m:PPL", "s_s:US"]), rows=0, stats="true", **{"stats.field": f}) for f in [
    "{!min=true max=true count=true missing=true sum=true mean=true stddev=true sumOfSquares=true}i_s",
    "{!sum=true mean=true}l_s", "{!cardinality=true}s_s", "{!countDistinct=true calcdistinct=true}s_sp",
    "{!cardinality=0.1}i_m", "{!func key=f}sum(i_s,1)", "dt_s", "dt_m", "s_s", "s_m", "i_dv", "f_m", "d_sp", "i_sp",
    "{!tag=t min=true max=true}l_m"]] + [
    q(q="s_m:PPL", rows=0, stats="true", facet="true", **{"stats.field": "{!tag=p}l_s", "facet.pivot": "{!stats=p}s_s,b_s",
                                                          "facet.limit": 4})]

# ---- spatial, highlighting, elevation
sp = []
for d in pick(places, 6):
    lat, lon = d["ll"].split(",")
    sp += [q(q="*:*", fq=f"{{!geofilt sfield=ll pt={d['ll']} d=50}}", sort="geodist(ll,{0}) asc,id asc".format(d["ll"]),
             fl=f"id,dist:geodist(ll,{d['ll']})"),
           q(q="*:*", fq=f"{{!bbox sfield=rpt pt={d['ll']} d=80}}", sort="id asc", fl=FL),
           q(q=f"{{!geofilt sfield=ll pt={d['ll']} d=30 score=distance}}", sort="score asc,id asc", fl="id,score"),
           q(q=f"ll:[{float(lat) - 1},{float(lon) - 1} TO {float(lat) + 1},{float(lon) + 1}]", sort="id asc", fl=FL),
           q(q=f'rpt:"Intersects(ENVELOPE({float(lon) - 1}, {float(lon) + 1}, {float(lat) + 1}, {float(lat) - 1}))"',
             sort="id asc", fl=FL)]
cats["Spatial"] = sp
cats["HighlightVariants"] = [q(q=qq, sort="id asc", fl="id", hl="true", **p) for qq, p in [
    (f"t_s:{words[0]}", {"hl.fl": "t_s,t_m", "hl.method": "unified"}),
    (f"t_s:{words[1]}", {"hl.fl": "t_s,t_m", "hl.method": "original", "hl.snippets": 2, "hl.fragsize": 20}),
    (f't_m:"{words[2]} {words[3]}"~3', {"hl.fl": "t_m", "hl.method": "unified", "hl.usePhraseHighlighter": "true"}),
    (f"t_s:{words[4][:4]}*", {"hl.fl": "t_s", "hl.method": "original", "hl.highlightMultiTerm": "true"}),
    (f"t_s:{words[5]}~1", {"hl.fl": "t_s", "hl.method": "unified", "hl.tag.pre": "[", "hl.tag.post": "]"}),
    ("s_s:US", {"hl.fl": "t_s", "hl.q": f"t_s:{words[6]}", "hl.method": "unified"}),
    (f"t_s:{words[7]} t_m:{words[8]}", {"hl.fl": "t_s,t_m", "hl.requireFieldMatch": "true", "hl.method": "original"})]]
ids = [d["id"] for d in docs]
cats["Elevation"] = [q(q=qq, sort=s, fl="id,[elevated],[excluded]", **p) for qq, s, p in [
    ("s_s:US", "l_s desc,id asc", {"elevateIds": ",".join(pick(ids, 3)), "forceElevation": "true"}),
    ("s_s:CN", "id asc", {"elevateIds": ",".join(pick(ids, 2)), "excludeIds": ",".join(pick(ids, 2))}),
    (f"t_s:{words[0]}", "score desc,id asc", {"elevateIds": ",".join(pick(ids, 2))}),
    ("s_m:PPL", "id asc", {"excludeIds": ",".join(pick(ids, 5)), "markExcludes": "true"}),
    ("s_s:US", "id asc", {"elevateIds": ",".join(pick(ids, 3)), "enableElevation": "false"})]]
handlers["Elevation"] = "/elevate"
cats["RealTimeGet"] = [q(ids=",".join(pick(ids, 4) + ["no-such-id"]), fl=f) for f in
                       ["*", "id,i_s,dt_m,f_m,b_s", "id,ll,rpt,s_m", "*,i_dv", "id,t_m,l_m"]] + [
    q(id=pick(ids), fl="*")]
handlers["RealTimeGet"] = "/get"
# streaming expressions; /export through search(): /export itself answers from one shard
EXPORT_FL = "id,i_s,l_s,f_s,d_s,dt_s,b_s,s_s,s_m,i_m,dt_m,f_m,l_m,i_dv,i_sp,d_sp,s_sp"


def search(query, sort, fl=EXPORT_FL, qt="/export", **more):
    extra = "".join(f',{k}="{v}"' for k, v in more.items())
    return f'search(types,q="{query}",fl="{fl}",sort="{sort}",qt="{qt}"{extra})'


cats["StreamingExpressions"] = [q(expr=e) for e in [
    search(f"s_s:{c}", s) for c, s in zip(small_countries[:10], [
        "l_s desc,id asc", "id asc", "dt_s asc,id asc", "f_s desc,id asc", "i_dv asc,d_s desc,id asc",
        "s_sp asc,id asc", "b_s desc,id asc", "i_sp desc,id asc", "d_sp asc,id asc", "i_s asc,l_s asc,id asc"])] + [
    search("*:*", "id asc", fq="s_s:AD AND b_s:true"),
    search("s_m:PPL", "l_s desc,id asc", fl="id,l_s", qt="/select", rows=20),
    'facet(types,q="*:*",buckets="s_s",bucketSorts="count(*) desc",bucketSizeLimit=10,'
    'sum(l_s),count(*),min(i_s),max(f_s),avg(d_s))',
    'facet(types,q="s_m:PPL",buckets="s_s,b_s",bucketSorts="sum(l_s) desc",bucketSizeLimit=8,sum(l_s),count(*))',
    'stats(types,q="s_m:PPL",sum(l_s),avg(i_s),min(i_dv),max(d_sp),count(*))',
    f'rollup({search("s_s:" + small_countries[10], "s_sp asc,id asc", fl="s_sp,l_s,id")},over="s_sp",sum(l_s),count(*))',
    f'unique({search("s_s:" + small_countries[11], "s_sp asc,id asc", fl="s_sp,id")},over="s_sp")',
    f'top(n=5,{search("s_s:" + small_countries[12], "id asc", fl="id,l_s")},sort="l_s desc,id asc")',
    'timeseries(types,q="s_m:PPL",field="dt_s",start="1970-01-01T00:00:00Z",end="2030-01-01T00:00:00Z",'
    'gap="+10YEARS",format="YYYY",count(*),sum(l_s))']]
handlers["StreamingExpressions"] = "/stream"
cats["TermsComponentVariants"] = [q(**{k.replace("_", "."): v for k, v in p.items()}) for p in [
    {"terms_fl": "t_m", "terms_prefix": "sa", "terms_limit": 15},
    {"terms_fl": "s_m", "terms_lower": "P", "terms_upper": "Q", "terms_upper_incl": "false", "terms_limit": 20},
    {"terms_fl": "t_s", "terms_regex": "chu.*", "terms_limit": 10},
    {"terms_fl": "s_s", "terms_mincount": 1000, "terms_sort": "index", "terms_limit": -1},
    {"terms_fl": "t_m", "terms_prefix": words[0][:3], "terms_stats": "true", "terms_ttf": "true"},
    {"terms_fl": "t_s", "terms_list": ",".join(words[:6])},
    {"terms_fl": ["t_s", "s_m"], "terms_prefix": "s", "terms_limit": 5}]]
handlers["TermsComponentVariants"] = "/terms"
cats["SpellCheckVariants"] = [q(q=w[:2] + w[3] + w[2] + w[4:], rows=0, **p) for w, p in zip(words[:8], [
    {}, {"spellcheck.onlyMorePopular": "true"}, {"spellcheck.count": 10}, {"spellcheck.collateExtendedResults": "true"},
    {"spellcheck.alternativeTermCount": 3}, {}, {"spellcheck.maxResultsForSuggest": 5}, {}])]
handlers["SpellCheckVariants"] = "/spell"
cats["RequestParams"] = [q(q=qq, fl="id,score", **p) for qq, p in [
    (f"{words[0]} {words[1]}", {"df": "t_s", "q.op": "AND"}), (f"{words[2]} {words[3]}", {"df": "t_m", "sow": "false"}),
    (f"t_s:{words[4]}", {"rows": 0}), (f"t_s:{words[5]}", {"debugQuery": "true", "sort": "id asc"}),
    (f"t_s:{words[6]}", {"fq": ["s_m:PPL", "b_s:true", "{!cache=false}i_s:[0 TO 1000]"], "sort": "id asc"}),
    (f"t_s:{words[7]}", {"timeAllowed": "10000", "sort": "l_s desc,id asc"}),
    # re-ranking: the first pass ordered by score then id, so the re-ranked window does not depend on doc order,
    # and re-rank scores that differ doc to doc (SolrCloud merges tied re-ranked docs in no fixed order)
    (f"t_s:{words[8]}", {"rq": "{!rerank reRankQuery=$rqq reRankDocs=100 reRankWeight=2}",
                         "rqq": "{!func}div(ms(dt_s),1e12)", "sort": "score desc,id asc"}),
    (f"t_s:{words[9]}", {"rq": "{!rerank reRankQuery=$rqq reRankDocs=50 reRankOperator=multiply}",
                         "rqq": "{!func}div(ms(dt_s),1e12)", "sort": "score desc,id asc"}),
    (f"t_s:{words[10]}", {"rq": "{!rerank reRankQuery=$rqq reRankDocs=50 reRankOperator=replace}",
                          "rqq": "{!func}ms(dt_s)", "sort": "score desc,id asc"})]]

os.makedirs(OUT, exist_ok=True)
for name, rows in cats.items():
    with open(f"{OUT}/{name}.txt", "w") as f:
        f.write("\n".join(rows) + "\n")
with open(f"{OUT}/manifest.json", "w") as f:
    json.dump({name: handlers.get(name, "/select") for name in cats}, f, indent=1)
print(f"wrote {sum(map(len, cats.values()))} requests in {len(cats)} categories to {OUT}")
