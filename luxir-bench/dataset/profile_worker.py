# Reads JSON lines on stdin, aggregates per-product / per-user / per-minute stats, pickles them to argv[1].
import sys, json, pickle
from collections import Counter
from datetime import datetime, timezone

EPOCH = datetime(2019, 10, 1, tzinfo=timezone.utc).timestamp()
ETYPES = {"view": 0, "cart": 1, "purchase": 2, "remove_from_cart": 3}

products = {}   # pid -> [category_id, category_code, brand, etype counts[4], Counter(price)]
users = Counter()
minutes = Counter()
id_min, id_max, n = None, None, 0
other_etypes = Counter()
for line in sys.stdin:
    d = json.loads(line)
    n += 1
    i = d["id"]
    if id_min is None or i < id_min: id_min = i
    if id_max is None or i > id_max: id_max = i
    t = d["event_time"]
    ts = datetime(int(t[0:4]), int(t[5:7]), int(t[8:10]), int(t[11:13]), int(t[14:16]), tzinfo=timezone.utc).timestamp()
    minutes[int(ts - EPOCH) // 60] += 1
    p = products.get(d["product_id"])
    if p is None:
        p = products[d["product_id"]] = [d["category_id"], d.get("category_code"), d.get("brand"), [0, 0, 0, 0], Counter()]
    et = ETYPES.get(d["event_type"])
    if et is None:
        other_etypes[d["event_type"]] += 1
    else:
        p[3][et] += 1
    p[4][d["price"]] += 1
    users[d["user_id"]] += 1
pickle.dump(dict(products=products, users=users, minutes=minutes, id_min=id_min, id_max=id_max, n=n, other=other_etypes),
            open(sys.argv[1], "wb"), protocol=5)
