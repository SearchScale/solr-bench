#!/usr/bin/env python3
"""Geonames NDJSON (bz2) to solr-bench JSONL (gz): id = geonameid, location as "lat,lon"
(Solr's form of the [lon, lat] array), as luxir-lucene's bench/geonames/encode.py does.
Usage: geonames-jsonl.py documents-2.json.bz2 suites/datasets/geonames.json.gz"""
import bz2, gzip, json, sys
n = 0
seen = set()
with bz2.open(sys.argv[1], 'rt', encoding='utf-8') as f, gzip.open(sys.argv[2], 'wt', encoding='utf-8', compresslevel=6) as o:
    for line in f:
        line = line.strip()
        if not line: continue
        d = json.loads(line)
        gid = d['geonameid']
        if gid in seen: raise SystemExit(f'duplicate geonameid {gid}')
        seen.add(gid)
        d = {'id': str(gid), **d}
        loc = d.pop('location', None)
        if loc: d['location'] = f'{loc[1]},{loc[0]}'
        o.write(json.dumps(d, ensure_ascii=False, separators=(',', ':')) + '\n'); n += 1
print(f'{n} docs')
