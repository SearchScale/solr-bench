#!/usr/bin/env python3
"""1M-ish TSV for conf_ecommerce_events. seed=42.

  python3 gen_mtbench_data.py [num_docs] [outfile]
"""
import random
import sys
import datetime

NUM_DOCS = int(sys.argv[1]) if len(sys.argv) > 1 else 1_000_000
OUT_FILE = sys.argv[2] if len(sys.argv) > 2 else "mtbench-data.tsv"

EVENT_TYPES = ["view", "cart", "purchase", "remove_from_cart"]
BRANDS = [f"brand{n}" for n in range(200)]
CATEGORY_CODES = [f"category.group{n}" for n in range(50)]

random.seed(42)
start = datetime.datetime(2024, 1, 1)

with open(OUT_FILE, "w") as f:
    f.write("id\tevent_time\tevent_type\tproduct_id\tcategory_id\tcategory_code\tbrand\tprice\tuser_id\tuser_session\n")
    for i in range(NUM_DOCS):
        ts = start + datetime.timedelta(seconds=random.randint(0, 60 * 60 * 24 * 180))
        event_time = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        event_type = random.choice(EVENT_TYPES)
        product_id = random.randint(1, 500_000)
        category_id = random.randint(1, 1000)
        category_code = random.choice(CATEGORY_CODES)
        brand = random.choice(BRANDS)
        price = round(random.uniform(1.0, 999.99), 2)
        user_id = random.randint(1, 200_000)
        user_session = f"sess-{random.randint(1, 1_000_000)}"
        f.write(f"{i}\t{event_time}\t{event_type}\t{product_id}\t{category_id}\t{category_code}\t{brand}\t{price}\t{user_id}\t{user_session}\n")
        if (i + 1) % 100000 == 0:
            print(f"...{i+1} docs written", file=sys.stderr)

print(f"Done. Wrote {NUM_DOCS} docs to {OUT_FILE}", file=sys.stderr)
