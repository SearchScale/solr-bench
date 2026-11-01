#!/usr/bin/env python3
"""The "nested" correctness dataset: geonames as blocks of nested documents, one JSON line per country:

    country (doc_type country)
      states: one per admin1 code (doc_type state)
        places: its places (doc_type place)
      places: the country's places without an admin1 code

Every 20th geonames record is a place (about 570K places, 3.9K states, 252 countries). Labelled child
relations (states, places) give Solr's _nest_path_. Countries and states carry their places' count and
summed population. Names are ASCII (geonames' asciiname), so both systems' analyzers agree.
Usage: luxir-bench/nested-dataset.py [out]   (from the solr-bench directory; default
suites/datasets/nested.json.gz)
"""
import collections
import gzip
import json
import sys

out = sys.argv[1] if len(sys.argv) > 1 else "suites/datasets/nested.json.gz"
countries = collections.OrderedDict()
with gzip.open("suites/datasets/geonames.json.gz", "rt") as src:
    for i, line in enumerate(src):
        if i % 20:
            continue
        g = json.loads(line)
        cc = g.get("country_code") or "XX"
        name = g.get("asciiname") or "".join(c for c in g.get("name", "") if c.isascii())
        place = {
            "id": f"p-{g['id']}",
            "doc_type": "place",
            "code": g.get("feature_code") or "-",
            "name": name,
            "name_s": name[:200],
            "alt": [a for a in g.get("alternatenames", "").split(",") if a and a.isascii()][:3],
            "feature_class": g.get("feature_class") or "-",
            "population": g.get("population", 0),
            "geonameid": g["geonameid"],
            "timezone": g.get("timezone") or "-",
        }
        if not place["alt"]:
            del place["alt"]
        if "elevation" in g:
            place["elevation"] = g["elevation"]
        if g.get("location"):
            place["location"] = g["location"]
        states = countries.setdefault(cc, collections.OrderedDict())
        states.setdefault(g.get("admin1_code") or "", []).append(place)

n = 0
with gzip.open(out, "wt") as dst:
    for cc, states in countries.items():
        all_places = [p for ps in states.values() for p in ps]
        country = {"id": f"c-{cc}", "doc_type": "country", "code": cc, "name": f"country {cc}", "name_s": cc,
                   "population": sum(p["population"] for p in all_places), "num_places": len(all_places)}
        kids = []
        for adm, places in states.items():
            if not adm:
                continue
            kids.append({"id": f"s-{cc}-{adm}", "doc_type": "state", "code": adm, "name": f"state {cc} {adm}",
                         "name_s": f"{cc}.{adm}", "population": sum(p["population"] for p in places),
                         "num_places": len(places), "places": places})
        if kids:
            country["states"] = kids
        if states.get(""):
            country["places"] = states[""]
        dst.write(json.dumps(country, ensure_ascii=False) + "\n")
        n += 1 + len(kids) + len(all_places)
print(f"{len(countries)} country blocks, {n} docs, to {out}")
