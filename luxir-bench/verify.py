#!/usr/bin/env python3
"""Checks every request of a query file on Solr+Lucene against Solr+Luxir, and Luxir's native path against
its Java path (luxirCodec=false) over the same index. Whole responses are compared, all but timings and
debug output:
  - numFound equal on both systems;
  - every section besides the result rows (facets, facet_counts, stats, grouped, expanded, spellcheck,
    terms, moreLikeThis, nextCursorMark, ...) equal on both systems, and native vs Java on Solr+Luxir
    (floats to 1e-9 relative: sums depend on the order values are added in);
  - result rows ordered by a sort that does not start with the score: every returned field equal on both
    systems; score-ranked rows: the same docs in the same order but for docs whose scores agree to float
    rounding, a failure with VERIFY_STRICT=1 and otherwise counted for information (enwiki's text
    analysis differs slightly between the systems);
  - on Solr+Luxir, the native rows (ids and order) equal to the Java path's;
  - highlighting of the docs both systems return.
Requests are lines of URL-encoded parameters, or JSON request bodies (lines starting with "{").
Usage: verify.py <lucene-port> <luxir-port> <requests-file> [collection] [fl] [handler], with the collection
(default geonames) holding the same documents on each system; fl lists the fields to return besides the
request's own (default id,score,population,geonameid; "-" for only the request's); handler defaults to
/select. For example:
  verify.py 51000 52000 suites/queries/geonames/All.txt
  verify.py 51000 52000 suites/queries/enwiki/All.json enwiki id,score,month,dayOfYear,title,lastMod"""
import json, os, sys, urllib.error, urllib.parse, urllib.request
lport, xport, path = sys.argv[1:4]
coll = sys.argv[4] if len(sys.argv) > 4 else "geonames"
fl = sys.argv[5] if len(sys.argv) > 5 else "id,score,population,geonameid"
handler = sys.argv[6] if len(sys.argv) > 6 else "/select"
strict = os.environ.get("VERIFY_STRICT") == "1"
ROWS_FREE = handler in ("/export", "/get", "/stream")  # handlers that take no rows/fl defaults of ours
def run(port, params, extra):
    url = f"http://localhost:{port}/solr/{coll}{handler}"
    if params.startswith("{"):  # a JSON body, with the extra parameters in the URL
        body = json.loads(params)
        if "fl" in extra:
            body["fields"] = ",".join(x for x in (body.get("fields"), extra["fl"]) if x)
        if "rows" in extra:
            body.setdefault("limit", int(extra["rows"]))
        rest = {k: v for k, v in extra.items() if k not in ("fl", "rows")}
        req = urllib.request.Request(url + "?" + urllib.parse.urlencode(rest), data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    else:
        p = urllib.parse.parse_qsl(params, keep_blank_values=True)
        keys = {k for k, _ in p}
        p += [(k, v) for k, v in extra.items() if not (k == "rows" and "rows" in keys)]
        req = urllib.request.Request(url, data=urllib.parse.urlencode(p).encode(),
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=600))
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            return {"error": json.loads(body).get("error", {}).get("msg", body[:300])}
        except ValueError:
            return {"error": body[:300]}
def summary(params):
    """q, fq, sort and json.facet of a request, whichever form it has."""
    if not params.startswith("{"):
        return dict(urllib.parse.parse_qsl(params))
    b = json.loads(params)
    q = {"q": b.get("query"), "sort": b.get("sort"), "json.facet": b.get("facet"),
         "fq": b.get("filter")}
    q.update(b.get("params", {}))
    return {k: v if isinstance(v, str) else json.dumps(v) for k, v in q.items() if v is not None}
def diff(a, b, at=""):
    """The first path where a and b differ beyond float rounding, or None."""
    if isinstance(a, tuple) and isinstance(b, tuple) and a[:1] == b[:1] == ("score",):
        return diff(a[1], b[1], at + ".score")
    if isinstance(a, dict) and isinstance(b, dict):
        # each cluster's own indexing time; a stream's timing
        a = {k: v for k, v in a.items() if k not in ("_version_", "RESPONSE_TIME")}
        b = {k: v for k, v in b.items() if k not in ("_version_", "RESPONSE_TIME")}
        if a.keys() != b.keys():
            return f"{at} keys {sorted(a.keys() ^ b.keys())[:5]}"
        for k in a:
            d = diff(a[k], b[k], f"{at}.{k}")
            if d: return d
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{at} length {len(a)} vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = diff(x, y, f"{at}[{i}]")
            if d: return d
        return None
    if isinstance(a, float) or isinstance(b, float):
        # scores to float rounding (the engines add BM25's parts in different orders); other values 1e-9
        tol = 1e-5 if at.endswith(("score", "maxScore")) else 1e-9
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) \
                and abs(a - b) <= tol * max(1.0, abs(a), abs(b)):
            return None
        return f"{at} {a!r} vs {b!r}"
    return None if a == b else f"{at} {str(a)[:80]!r} vs {str(b)[:80]!r}"
def same_but_rounding(x, y):
    """Rows that differ only in the order of docs whose scores agree to float rounding."""
    if len(x) != len(y) or {d["id"] for d in x} != {d["id"] for d in y}:
        return False
    if not all("score" in d for d in x + y):
        return False
    return all(abs(a["score"] - b["score"]) <= 1e-5 * max(1.0, abs(a["score"])) for a, b in zip(x, y))
def score_ranked(q):
    s = q.get("sort", "").strip()
    return not s or s.split(",")[0].split()[0] == "score"
def rows_of(r):
    """The result rows and their count, however the handler returns them."""
    if "response" in r and isinstance(r["response"], dict):
        return r["response"].get("docs", []), r["response"].get("numFound")
    if "doc" in r:  # /get of one id
        return [r["doc"]] if r["doc"] else [], None
    return None, None
def split_top(spec):
    """A sort spec's clauses: commas outside parentheses."""
    out, depth, cur = [], 0, ""
    for ch in spec:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            out.append(cur.strip()); cur = ""
        else:
            cur += ch
    return [c for c in out + [cur.strip()] if c]
def sort_keys(q):
    """(expression, direction) of each sort clause; the score alone for a score-ranked request."""
    spec = q.get("sort", "").strip() or "score desc"
    keys = []
    for c in split_top(spec):
        expr, _, direction = c.rpartition(" ")
        keys.append((expr.strip() or direction, direction.lower() if expr else "asc"))
    return keys
MULTI = set()
if not ROWS_FREE:
    try:
        fields = json.load(urllib.request.urlopen(f"http://localhost:{lport}/solr/{coll}/schema/fields?wt=json"))["fields"]
        types = {t["name"]: t for t in json.load(urllib.request.urlopen(
            f"http://localhost:{lport}/solr/{coll}/schema/fieldtypes?wt=json"))["fieldTypes"]}
        MULTI = {f["name"] for f in fields if f.get("multiValued", types.get(f["type"], {}).get("multiValued", False))}
    except Exception:
        pass
def key_fl(keys):
    """Pseudo-fields returning each sort key's value (_k0, _k1, ...): a multi-valued field sorts by its
    least value ascending and its greatest descending."""
    fl = []
    for i, (expr, direction) in enumerate(keys):
        if expr == "score":
            fl.append("score")
        elif expr in MULTI:
            fl.append(f"_k{i}:field({expr},{'min' if direction == 'asc' else 'max'})")
        else:
            # an alias of a plain field hides the field itself unless the field is listed too
            fl.append(f"_k{i}:{expr}" + (f",{expr}" if expr.replace("_", "").isalnum() else ""))
    return ",".join(fl)
STRINGS = set()
if not ROWS_FREE:
    try:
        STRINGS = {f["name"] for f in fields if "Str" in types.get(f["type"], {}).get("class", "")
                   or "Bool" in types.get(f["type"], {}).get("class", "")}
    except Exception:
        pass
def key_of(d, keys):
    """The doc's sort keys; a numeric key the doc lacks sorts as 0, as Solr sorts missing numbers."""
    out = []
    for i, (e, _) in enumerate(keys):
        v = d.get("score") if e == "score" else d.get(f"_k{i}")
        out.append(0 if v is None and e != "score" and e not in STRINGS else v)
    return out
VOLATILE = ("responseHeader", "debug", "error")  # compared separately, or not at all
extra = {} if ROWS_FREE else {"wt": "json", "rows": "10"}
if fl != "-" and not ROWS_FREE:
    extra["fl"] = fl
fails = []; info = 0; n = 0; rounding = 0; rejected = []
for line in open(path):
    params = line.rstrip("\n")
    if not params: continue
    n += 1
    q = summary(params)
    label = (q.get("q", "")[:60] + (" fq=" + q["fq"][:40] if "fq" in q else "") + (" sort=" + q["sort"] if "sort" in q else "")
             + (" json.facet" if "json.facet" in q else ""))
    # re-ranked rows: by the new scores, ties in doc order whatever the sort's later keys
    keys = [("score", "desc")] if "rq" in q else sort_keys(q)
    ex = dict(extra)
    if not ROWS_FREE and q.get("group") != "true":
        ex["fl"] = ",".join(x for x in (extra.get("fl"), key_fl(keys)) if x)
    a, b = run(lport, params, ex), run(xport, params, ex)
    j = run(xport, params, {**ex, "luxirCodec": "false"})
    if "error" in a or "error" in b or "error" in j:
        if not ("error" in a and "error" in b):
            fails.append(f"error on one system only (lucene {a.get('error', 'ok')!s:.150} / luxir {b.get('error', 'ok')!s:.150}): {label}")
        else:
            rejected.append(f"{a['error']!s:.200}: {label}")  # both systems reject it alike
        continue
    for k in sorted(set(a) | set(b) | set(j)):
        if k in VOLATILE or k in ("response", "doc", "highlighting", "grouped"):
            continue
        d = diff(a.get(k), b.get(k), k)
        if d: fails.append(f"differ: {d}: {label}")
        d = diff(b.get(k), j.get(k), k)
        if d: fails.append(f"Luxir native vs Java differ: {d}: {label}")
    if "grouped" in a:
        def groups(r):
            return {f: (g.get("matches"), g.get("ngroups"),
                        sorted((str(x.get("groupValue")), x["doclist"]["numFound"]) for x in g.get("groups", [])),
                        g.get("doclist", {}).get("numFound"))
                    for f, g in r["grouped"].items()}
        if not score_ranked(q) and (not q.get("group.sort") or not score_ranked({"sort": q["group.sort"]})):
            d = diff(a["grouped"], b.get("grouped"), "grouped")
            if d: fails.append(f"groups differ: {d}: {label}")
        elif {f: g[0] for f, g in groups(a).items()} != {f: g[0] for f, g in groups(b).items()}:
            fails.append(f"group matches differ: {label}")
        elif groups(a) != groups(b):
            info += 1  # score-ranked groups: which tied groups make the page depends on doc order
        d = diff(b["grouped"], j.get("grouped"), "grouped")
        if d: fails.append(f"Luxir groups native vs Java differ: {d}: {label}")
    if "highlighting" in a:
        both = a["highlighting"].keys() & b["highlighting"].keys()
        if any(a["highlighting"][d] != b["highlighting"][d] for d in both):
            fails.append(f"highlighting differs: {label}")
        if b["highlighting"] != j.get("highlighting"):
            fails.append(f"Luxir highlighting native vs Java differs: {label}")
    ra, na = rows_of(a); rb, nb = rows_of(b); rj, nj = rows_of(j)
    if ra is None:
        continue
    if na != nb:
        fails.append(f"numFound {na} vs {nb}: {label}")
    if ROWS_FREE:
        if handler == "/get":  # distributed real-time get lists docs as the shards answer
            ra, rb, rj = (sorted(r, key=lambda x: str(x.get("id"))) for r in (ra, rb, rj))
        d = diff(ra, rb, "docs")
        if d: fails.append(f"rows differ: {d}: {label}")
    else:
        # The sort keys in order must agree, and any doc both return must be the same. Which of the docs
        # tied on every key fill the page depends on internal doc order, which differs with the segments
        # each system writes; a doc whose keys no other doc on the page shares, away from the page's ends,
        # must be the same doc.
        # scores compared to float rounding, by their position among the keys
        ka = [[("score", v) if e == "score" else v for v, (e, _) in zip(key_of(d, keys), keys)] for d in ra]
        kb = [[("score", v) if e == "score" else v for v, (e, _) in zip(key_of(d, keys), keys)] for d in rb]
        d = diff(ka, kb, "sort keys")
        if d and (strict or not score_ranked(q)):
            fails.append(f"rows differ: {d}: {label}")
        elif d:
            info += 1
        else:
            by_id = {x.get("id"): x for x in rb}
            for x in ra:
                if x.get("id") in by_id:
                    dd = diff(x, by_id[x.get("id")], f"doc {x.get('id')}")
                    if dd: fails.append(f"rows differ: {dd}: {label}"); break
            paged = q.get("start", "0") not in ("", "0") or q.get("cursorMark", "*") != "*" or "offset" in params
            for i, (x, y) in enumerate(zip(ra, rb)):
                tied = any(diff(ka[i], ka[k]) is None for k in (i - 1, i + 1) if 0 <= k < len(ka))
                edge = (i == 0 and paged) or i == len(ra) - 1
                if x.get("id") != y.get("id"):
                    if tied or edge: info += 1
                    else: fails.append(f"rows differ: doc {i} {x.get('id')} vs {y.get('id')} with keys {ka[i]}: {label}")
                    break
    if [d.get("id") for d in rb] != [d.get("id") for d in rj] or nb != nj:
        if nb == nj and same_but_rounding(rb, rj):
            rounding += 1
        else:
            fails.append(f"Luxir native vs Java rows differ: {label}")
print(f"{n} requests: {len(fails)} failures; score-ranked top rows differing across systems (info): {info}; "
      f"Luxir native vs Java rows reordered among scores equal to float rounding: {rounding}"
      + (f"; rejected by both systems: {len(rejected)}" if rejected else ""))
for r in rejected[:5]: print("  REJECTED", r)
for f in fails: print("  FAIL", f)
sys.exit(1 if fails else 2 if rejected else 0)  # 2: requests both systems reject
