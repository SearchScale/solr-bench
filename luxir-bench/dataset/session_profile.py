# Session structure from a contiguous slice of the time-sorted stream (stdin).
import sys, json, pickle
from collections import Counter
from datetime import datetime, timezone

sess = {}  # session -> [count, last_ts, last_pid, last_cat]
gaps = Counter(); same_prod = diff_prod_same_cat = diff_cat = 0
prev_t = ""; unsorted = 0; missing = 0
for line in sys.stdin:
    d = json.loads(line)
    t = d["event_time"]
    if t < prev_t: unsorted += 1
    prev_t = t
    ts = int(datetime(int(t[0:4]), int(t[5:7]), int(t[8:10]), int(t[11:13]), int(t[14:16]), int(t[17:19]), tzinfo=timezone.utc).timestamp())
    if "user_session" not in d: missing += 1; continue
    s = sess.get(d["user_session"])
    if s is None:
        sess[d["user_session"]] = [1, ts, d["product_id"], d["category_id"]]
        continue
    gaps[min(ts - s[1], 7200)] += 1
    if d["product_id"] == s[2]: same_prod += 1
    elif d["category_id"] == s[3]: diff_prod_same_cat += 1
    else: diff_cat += 1
    s[0] += 1; s[1] = ts; s[2] = d["product_id"]; s[3] = d["category_id"]
lengths = Counter(s[0] for s in sess.values())
pickle.dump(dict(lengths=lengths, gaps=gaps, same_prod=same_prod, same_cat=diff_prod_same_cat, diff_cat=diff_cat,
                 sessions=len(sess), unsorted=unsorted, missing=missing), open(sys.argv[1], "wb"))
print("sessions", len(sess), "same_prod", same_prod, "same_cat", diff_prod_same_cat, "diff_cat", diff_cat, "unsorted", unsorted)
