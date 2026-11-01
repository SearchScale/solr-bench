#!/usr/bin/env python3
"""Updates on both systems, checked step by step: a collection "upd" (the "types" schema, both systems'
configsets) gets the first 50K docs of types.json.gz, then the same sequence of atomic and in-place updates,
optimistic-concurrency checks, deletes and re-adds; real-time get answers alike before commits, soft
commits make the same docs visible, and at the end every doc (every field, by /export through a streaming
expression) is the same on both, as are the "types" query workloads (verify.py) over the result.
Usage: luxir-bench/verify-updates.py <lucene-port> <luxir-port>   (from the solr-bench directory; the
collection is dropped and recreated on both)"""
import gzip
import json
import os
import random
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

LPORT, XPORT = sys.argv[1], sys.argv[2]
COLL = "upd"
N = 50_000
rnd = random.Random(17)
fails = []
steps = 0


def http(port, path, body=None, params=None, ctype="application/json"):
    url = f"http://localhost:{port}/solr/{path}" + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    req = urllib.request.Request(url, data=data, headers={"Content-Type": ctype} if data else {})
    try:
        return 200, json.load(urllib.request.urlopen(req, timeout=600))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except ValueError:
            return e.code, {}


def both(path, body=None, params=None, what=""):
    """The same request to both systems; their statuses must agree. (Error messages may not: a request
    forwarded to a shard leader on another node comes back wrapped, and leaders sit on different nodes.)"""
    global steps
    steps += 1
    (sa, a), (sb, b) = http(LPORT, path, body, params), http(XPORT, path, body, params)
    ea, eb = a.get("error", {}).get("msg", ""), b.get("error", {}).get("msg", "")
    if sa != sb:
        fails.append(f"{what or path}: lucene {sa} {ea[:120]!r} vs luxir {sb} {eb[:120]!r}")
    return sa, a, b


def strip(x):
    """A response without what differs by cluster: versions, timings, headers."""
    if isinstance(x, dict):
        return {k: strip(v) for k, v in x.items() if k not in ("_version_", "responseHeader", "QTime", "RESPONSE_TIME")}
    if isinstance(x, list):
        return [strip(v) for v in x]
    return x


def same(what, a, b):
    if strip(a) != strip(b):
        fails.append(f"{what}: responses differ: {json.dumps(strip(a))[:200]} vs {json.dumps(strip(b))[:200]}")


def get(ids, fl="*"):
    _, a, b = both(f"{COLL}/get", params={"ids": ",".join(ids), "fl": fl}, what="real-time get")
    for r in (a, b):
        r.get("response", {}).get("docs", []).sort(key=lambda d: d["id"])
    same(f"real-time get {ids[:3]}", a.get("response"), b.get("response"))


def update(docs, what, **params):
    return both(f"{COLL}/update", docs, params or None, what)


# ---- the collection, on both systems
for port, conf in ((LPORT, "conf_types.zip"), (XPORT, "conf_types_luxir.zip")):
    http(port, "admin/collections", params={"action": "DELETE", "name": COLL})
    with open(f"suites/configsets/{conf}", "rb") as f:
        http(port, "admin/configs", f.read(), {"action": "UPLOAD", "name": f"{COLL}.CHECK", "overwrite": "true"},
             "application/octet-stream")
    st, r = http(port, "admin/collections", params={"action": "CREATE", "name": COLL, "collection.configName": f"{COLL}.CHECK",
                                                    "numShards": 3, "replicationFactor": 1})
    assert st == 200, r
docs = []
with gzip.open("suites/datasets/types.json.gz", "rt") as f:
    for line in f:
        docs.append(json.loads(line))
        if len(docs) == N:
            break
for i in range(0, N, 5000):
    update(docs[i:i + 5000], "index")
update(None, "commit", commit="true")
ids = [d["id"] for d in docs]

# ---- atomic updates, with real-time get before any commit (from the update log) and after
for round_ in range(6):
    batch = []
    picked = rnd.sample(ids, 300)
    for k, i in enumerate(picked):
        op = k % 12
        u = {"id": i}
        if op == 0: u["s_s"] = {"set": rnd.choice(["ZZ", "YY", "XX"])}
        elif op == 1: u["i_s"] = {"inc": rnd.randrange(-50, 50)}
        elif op == 2: u["s_m"] = {"add": ["NEW", f"N{round_}"]}
        elif op == 3: u["s_m"] = {"remove": ["PPL", "P"]}
        elif op == 4: u["s_m"] = {"removeregex": "^[0-9].*"}
        elif op == 5: u["i_m"] = {"add-distinct": [7, 8, 9]}
        elif op == 6: u["dt_s"] = {"set": "2001-02-03T04:05:06Z"}
        elif op == 7: u["b_s"] = {"set": rnd.random() < 0.5}
        elif op == 8: u["d_sp"] = {"set": None}
        elif op == 9: u["t_m"] = {"add": f"extra words {round_}"}
        elif op == 10: u["l_s"] = {"inc": 1000}
        else: u["f_m"] = {"set": [1.5, -2.25]}
        batch.append(u)
    update(batch, f"atomic updates round {round_}")
    get(picked[:40])  # from the update log
    # in-place updates of the doc-values-only field
    update([{"id": i, "i_dv": {"inc": 3}} for i in picked[::3]], f"in-place inc round {round_}")
    update([{"id": i, "i_dv": {"set": round_}} for i in picked[1::7]], f"in-place set round {round_}")
    get(picked[:40], "id,i_dv,_version_")
    update(None, "soft commit", softCommit="true")
    for qq in ("s_s:(ZZ YY XX)", "s_m:NEW", f"t_m:{round_}", "i_dv:[0 TO 5]", "dt_s:\"2001-02-03T04:05:06Z\""):
        _, a, b = both(f"{COLL}/select", params={"q": qq, "rows": 50, "sort": "id asc", "fl": "*"}, what=f"query {qq}")
        same(f"after soft commit, {qq}", a.get("response"), b.get("response"))

# ---- optimistic concurrency: the same conflicts on both
some = rnd.sample(ids, 20)
update([{"id": some[0], "s_s": "VC", "_version_": -1}], "add with _version_ -1 to an existing doc (conflict)")
update([{"id": "new-vc-1", "s_s": "VC", "_version_": 1}], "add with _version_ 1 to a missing doc (conflict)")
update([{"id": "new-vc-2", "s_s": "VC", "_version_": -1}], "add with _version_ -1 to a missing doc")
for i in some[1:6]:  # the doc's current version, from each system: matching succeeds, any other conflicts
    for port in (LPORT, XPORT):
        _, r = http(port, f"{COLL}/get", params={"id": i, "fl": "_version_"})
        v = r["doc"]["_version_"]
        st, _ = http(port, f"{COLL}/update", [{"id": i, "s_sp": {"set": "VC"}, "_version_": v}])
        st2, _ = http(port, f"{COLL}/update", [{"id": i, "s_sp": {"set": "VD"}, "_version_": v}])
        if (st, st2) != (200, 409):
            fails.append(f"versioned update on port {port}: {st}, then stale {st2} (expected 200, 409)")
get(some[:6] + ["new-vc-1", "new-vc-2"])

# ---- deletes, re-adds, overwrites
gone = rnd.sample(ids, 200)
update({"delete": gone[:100]}, "delete by ids")
update({"delete": {"query": "s_s:AD OR i_s:[3000 TO 3100]"}}, "delete by query")
update([d for d in docs if d["id"] in set(gone[:30])], "re-add deleted docs")
update([{**docs[0], "s_s": "OVER", "t_s": "overwritten doc"}], "overwrite a doc")
get(gone[:40] + [docs[0]["id"]])
update(None, "hard commit", commit="true")

# ---- the whole collection, every field, through /export
FL = "id,s_s,s_m,s_sp,i_s,i_m,i_sp,l_s,l_m,f_s,f_m,d_s,d_sp,dt_s,dt_m,b_s,i_dv"
expr = f'search({COLL},q="*:*",fl="{FL}",sort="id asc",qt="/export")'
_, a, b = both("upd/stream", params={"expr": expr}, what="export everything")
same("every doc, every field (/export)", a.get("result-set"), b.get("result-set"))
_, a, b = both(f"{COLL}/select", params={"q": "*:*", "rows": 0}, what="count")
print(f"{steps} steps; {a['response']['numFound']} docs on Lucene, {b['response']['numFound']} on Luxir")
if a["response"]["numFound"] != b["response"]["numFound"]:
    fails.append("final counts differ")

# ---- the types workloads over the updated collection
r = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "verify-coverage.py"), LPORT, XPORT, "types",
                    COLL], capture_output=True, text=True)
print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-500:])
if r.returncode:
    fails.append("types workloads over the updated collection:\n" + "\n".join(
        l for l in r.stdout.splitlines() if l.startswith(("FAIL", "        FAIL")))[:3000])
for f in fails:
    print("  FAIL", f)
sys.exit(1 if fails else 0)
