# Generates N synthetic ecommerce events modelled on the profiled 110M dataset, sorted by event_time,
# as JSON lines on stdout. Usage: generate.py <N> <seed> part_*.pkl session.pkl
import sys, json, pickle, uuid
import numpy as np

N, seed = int(sys.argv[1]), int(sys.argv[2])
parts, session_pkl = sys.argv[3:-1], sys.argv[-1]
rng = np.random.default_rng(seed)
ETYPE_NAMES = np.array(["view", "cart", "purchase", "remove_from_cart"])
EPOCH = np.datetime64("2019-10-01T00:00:00")
WINDOW_SECS = 61 * 24 * 3600  # Oct 1 - Nov 30

# ---- merge the per-worker profiles
products, users, minutes, id_min, id_max, n_real = {}, {}, np.zeros(WINDOW_SECS // 60, np.int64), None, None, 0
for f in parts:
    p = pickle.load(open(f, "rb"))
    n_real += p["n"]
    id_min = p["id_min"] if id_min is None else min(id_min, p["id_min"])
    id_max = p["id_max"] if id_max is None else max(id_max, p["id_max"])
    for m, c in p["minutes"].items():
        if 0 <= m < len(minutes): minutes[m] += c
    for u, c in p["users"].items(): users[u] = users.get(u, 0) + c
    for pid, (cat, code, brand, et, prices) in p["products"].items():
        q = products.get(pid)
        if q is None:
            products[pid] = [cat, code, brand, list(et), prices]
        else:
            for k in range(4): q[3][k] += et[k]
            q[4].update(prices)
    del p
print(f"real docs {n_real}, products {len(products)}, users {len(users)}, ids [{id_min}, {id_max}]", file=sys.stderr)

# ---- product tables, sorted by category so a category's products are contiguous
pids = sorted(products, key=lambda k: (products[k][0], k))
cat_names = sorted({products[k][0] for k in pids})
cat_index = {c: i for i, c in enumerate(cat_names)}
P = len(pids)
p_cat = np.array([cat_index[products[k][0]] for k in pids])
p_et = np.array([products[k][3] for k in pids], dtype=np.float64)
p_weight = p_et.sum(1) + np.array([0 if sum(products[k][3]) else sum(products[k][4].values()) for k in pids])
p_et_cdf = np.cumsum(p_et / np.maximum(p_et.sum(1, keepdims=True), 1), axis=1)
p_et_cdf[p_et.sum(1) == 0] = [1, 1, 1, 1]  # products with unknown etypes only: view
# fixed JSON fragment per product: product_id, category_id, [category_code], [brand]
def frag(k):
    cat, code, brand = products[k][:3]
    s = f'"product_id": {k}, "category_id": {json.dumps(cat)}'
    if code is not None: s += f', "category_code": {json.dumps(code)}'
    if brand is not None: s += f', "brand": {json.dumps(brand)}'
    return s
p_frag = [frag(k) for k in pids]
# prices: flattened (product, price) with cdf offset by product index
pr_owner, pr_val, pr_cnt = [], [], []
for i, k in enumerate(pids):
    for v, c in products[k][4].items():
        pr_owner.append(i); pr_val.append(json.dumps(v)); pr_cnt.append(c)
pr_owner = np.array(pr_owner); pr_cnt = np.array(pr_cnt, np.float64); pr_val = np.array(pr_val)
tot = np.bincount(pr_owner, weights=pr_cnt, minlength=P)
pr_key = pr_owner + (np.cumsum(pr_cnt) - np.concatenate([[0], np.cumsum(tot)])[pr_owner]) / tot[pr_owner]
# popularity cdfs: global, and within-category (offset by category index)
g_cdf = np.cumsum(p_weight) / p_weight.sum()
c_tot = np.bincount(p_cat, weights=p_weight)
c_key = p_cat + (np.cumsum(p_weight) - np.concatenate([[0], np.cumsum(c_tot)])[p_cat]) / c_tot[p_cat]
del products

def pick_global(m): return np.minimum(np.searchsorted(g_cdf, rng.random(m), side="right"), P - 1)
def pick_in_cat(cats):
    i = np.searchsorted(c_key, cats + rng.random(len(cats)) * (1 - 1e-12), side="right")
    return np.minimum(i, P - 1)

# ---- sessions
s = pickle.load(open(session_pkl, "rb"))
lens, lw = zip(*sorted(s["lengths"].items())); lens = np.array(lens); lw = np.array(lw, np.float64) / sum(lw)
gv, gw = zip(*sorted(s["gaps"].items())); gv = np.array(gv); gw = np.array(gw, np.float64) / sum(gw)
trans = s["same_prod"] + s["same_cat"] + s["diff_cat"]
P_SAME, P_CAT = s["same_prod"] / trans, s["same_cat"] / trans
print(f"mean session len {(lens*lw).sum():.2f}, p_same_product {P_SAME:.3f}, p_same_category {P_CAT:.3f}", file=sys.stderr)

u_ids = np.fromiter(users.keys(), np.int64, len(users)); u_cdf = np.cumsum(np.fromiter(users.values(), np.float64, len(users)))
u_cdf /= u_cdf[-1]; del users
m_cdf = np.cumsum(minutes) / minutes.sum()

n_sess = int(N / (lens * lw).sum() * 1.08)
L = rng.choice(lens, n_sess, p=lw)
sess_of = np.repeat(np.arange(n_sess), L)                      # session index per event
first = np.concatenate([[0], np.cumsum(L)[:-1]])
pos = np.arange(len(sess_of)) - first[sess_of]                 # position within session
start = (np.searchsorted(m_cdf, rng.random(n_sess), side="right") * 60 + rng.integers(0, 60, n_sess))
gap = rng.choice(gv, len(sess_of), p=gw); gap[pos == 0] = 0
off = np.cumsum(gap); off -= off[first][sess_of]
ts = start[sess_of] + off
keep = ts < WINDOW_SECS
print(f"generated {len(ts)} events in {n_sess} sessions, {(~keep).sum()} past window end", file=sys.stderr)

# products per event, walking positions so each event can depend on the previous one in its session
prod = np.empty(len(ts), np.int64)
prod[first] = pick_global(n_sess)
for k in range(1, L.max()):
    idx = first[L > k] + k
    r = rng.random(len(idx)); prev = prod[idx - 1]
    out = prev.copy()
    c = (r >= P_SAME) & (r < P_SAME + P_CAT); out[c] = pick_in_cat(p_cat[prev[c]])
    g = r >= P_SAME + P_CAT; out[g] = pick_global(g.sum())
    prod[idx] = out

# trim to exactly N events, keeping ones inside the window, then sort by time
cand = np.flatnonzero(keep)
sel = np.sort(rng.choice(cand, N, replace=False)) if len(cand) > N else cand
assert len(sel) == N, (len(sel), N)
sel = sel[np.argsort(ts[sel], kind="stable")]
ts, prod, sess_of = ts[sel], prod[sel], sess_of[sel]

etype = (rng.random(N)[:, None] > p_et_cdf[prod]).sum(1).clip(0, 3)
price = pr_val[np.minimum(np.searchsorted(pr_key, prod + rng.random(N) * (1 - 1e-12), side="right"), len(pr_key) - 1)]
user_of_sess = u_ids[np.minimum(np.searchsorted(u_cdf, rng.random(n_sess), side="right"), len(u_ids) - 1)]
rb = rng.bytes(16 * n_sess)
uuids = [str(uuid.UUID(bytes=rb[i:i + 16], version=4)) for i in range(0, 16 * n_sess, 16)]
# ids above the real range, with the real dataset's average spacing
stride = max(1, (id_max - id_min) // n_real)
ids = id_max + 1 + np.arange(N, dtype=np.int64) * stride + rng.integers(0, stride, N)
rng.shuffle(ids)
times = np.char.replace(np.datetime_as_string(EPOCH + ts.astype("timedelta64[s]"), unit="s"), "T", " ")

out = sys.stdout
users_ev = user_of_sess[sess_of].tolist()
ids, times, etn, prod, price, sess_of = ids.tolist(), times.tolist(), ETYPE_NAMES[etype].tolist(), prod.tolist(), price.tolist(), sess_of.tolist()
for i in range(N):
    out.write(f'{{"id": {ids[i]}, "event_time": "{times[i]} UTC", "event_type": "{etn[i]}", '
              f'{p_frag[prod[i]]}, "price": {price[i]}, "user_id": {users_ev[i]}, "user_session": "{uuids[sess_of[i]]}"}}\n')
print("done", file=sys.stderr)
