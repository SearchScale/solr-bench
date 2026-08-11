#!/usr/bin/env python3
"""event_time range + event_type filter. --plain drops the facet block.

  python3 gen_mtbench_queries.py [--plain] [n] [outfile]
"""
import random
import sys
import datetime

args = [a for a in sys.argv[1:] if a != "--plain"]
PLAIN = "--plain" in sys.argv[1:]
NUM_LINES = int(args[0]) if len(args) > 0 else 300
OUT_FILE = args[1] if len(args) > 1 else (
    "mtbench-queries-plain.json" if PLAIN else "mtbench-queries.json"
)

EVENT_TYPES = ["view", "cart", "purchase", "remove_from_cart"]

random.seed(7)
start = datetime.datetime(2024, 1, 1)

lines = []
for _ in range(NUM_LINES):
    window_start = start + datetime.timedelta(seconds=random.randint(0, 60 * 60 * 24 * 170))
    window_end = window_start + datetime.timedelta(days=random.choice([1, 3, 7, 14, 30]))
    event_type = random.choice(EVENT_TYPES)
    q = (
        "{'query': 'event_time:[" + window_start.strftime("%Y-%m-%dT%H:%M:%SZ")
        + " TO " + window_end.strftime("%Y-%m-%dT%H:%M:%SZ") + "]', "
        + "'filter': 'event_type:" + event_type + "', "
        + "'limit': 10"
    )
    if not PLAIN:
        q += (
            ", 'facet': {"
            + "'avg_price': 'avg(price)', "
            + "'top_brands': {'type': 'terms', 'field': 'brand', 'limit': 25}, "
            + "'top_categories': {'type': 'terms', 'field': 'category_id', 'limit': 25}"
            + "}"
        )
    q += "}"
    lines.append(q)

with open(OUT_FILE, "w") as f:
    f.write("\n".join(lines) + "\n")

print(f"Done. Wrote {NUM_LINES} query lines to {OUT_FILE}", file=sys.stderr)
