#!/usr/bin/env python3
"""Runs verify.py over every category of a coverage dataset (four categories at a time) and prints one line
per category, then each failure and each request both systems rejected.
Usage: luxir-bench/verify-coverage.py <lucene-port> <luxir-port> <dataset> [collection [category ...]]
  dataset types:    suites/queries/coverage/types (handlers from its manifest.json), collection types
  dataset geonames: suites/queries/coverage/geonames, collection geonames (or gm, the multi-segment copy)
  dataset enwiki:   suites/queries/coverage/enwiki, collection enwiki
Run from the solr-bench directory; VERIFY_STRICT=1 makes score-ranked differences failures."""
import concurrent.futures
import json
import os
import subprocess
import sys

lport, xport, dataset = sys.argv[1:4]
coll = sys.argv[4] if len(sys.argv) > 4 else dataset
only = set(sys.argv[5:])
base = f"suites/queries/coverage/{dataset}"
handlers = {"SpellCheck": "/spell", "TermsComponent": "/terms"}
if os.path.exists(f"{base}/manifest.json"):
    handlers.update(json.load(open(f"{base}/manifest.json")))
fl = {"types": "-", "enwiki": "id,score", "geonames": "id,score"}.get(dataset, "id,score")
files = sorted(f for f in os.listdir(base) if f.endswith((".txt", ".json")) and f != "manifest.json"
               and (not only or f.rsplit(".", 1)[0] in only))


def check(f):
    name = f.rsplit(".", 1)[0]
    cmd = [sys.executable, os.path.join(os.path.dirname(__file__), "verify.py"), lport, xport, f"{base}/{f}", coll, fl,
           handlers.get(name, "/select")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return name, r.returncode, (r.stdout + r.stderr).strip().splitlines()


bad = rej = 0
with concurrent.futures.ThreadPoolExecutor(4) as pool:
    for name, rc, out in pool.map(check, files):
        head = out[0] if out else "(no output)"
        print(f"{'ok  ' if rc == 0 else 'rej ' if rc == 2 else 'FAIL'} {name:28} {head}")
        for line in out[1:]:
            print("       ", line[:400])
        bad += rc == 1
        rej += rc == 2
print(f"{len(files) - bad - rej} of {len(files)} categories pass"
      + (f"; {rej} with requests both systems reject (listed above)" if rej else ""))
sys.exit(1 if bad else 0)
