#!/usr/bin/env bash
# Builds suites/datasets/ecommerce-events-150m.json.gz (also published at
# https://huggingface.co/buckets/searchscale/solr-bench/resolve/ecommerce-events-150m.json.gz): the real 109,950,743 e-commerce events plus
# 40,049,257 synthetic ones modelled on them, merged in event_time order.
# Needs: pigz, python3 with numpy, ~30 GB RAM, ~15 GB free disk. Takes roughly 15 minutes on 32 cores.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
datasets=$(cd "$here/../../suites/datasets" && pwd)
src=$datasets/ecommerce-events.json.gz
synth=$datasets/ecommerce-events-synthetic-40m.json.gz
out=$datasets/ecommerce-events-150m.json.gz
work=${WORK_DIR:-$(mktemp -d)}
seed=${SEED:-42}
[ -f "$src" ] || { echo "Missing $src; download https://huggingface.co/buckets/searchscale/solr-bench/resolve/ecommerce-events.json.gz"; exit 1; }

echo "1/4 Profiling $src (products, users, per-minute volume, sessions) in $work"
pigz -dc "$src" | split -n r/24 --filter="python3 -I $here/profile_worker.py $work/\$FILE.pkl" - "part_"
# session structure from a contiguous 15M-event slice of the time-sorted stream
pigz -dc "$src" | sed -n '30000001,45000000p' | python3 -I "$here/session_profile.py" "$work/session.pkl"

echo "2/4 Generating 40,049,257 synthetic events (seed $seed)"
python3 -I "$here/generate.py" 40049257 "$seed" "$work"/part_*.pkl "$work/session.pkl" | pigz > "$synth.tmp"
mv "$synth.tmp" "$synth"

echo "3/4 Merging by event_time"
sort -m -s -t, -k2,2 <(pigz -dc "$src") <(pigz -dc "$synth") | pigz > "$out.tmp"
mv "$out.tmp" "$out"

echo "4/4 Checking line count and order"
pigz -dc "$out" | awk -F'"event_time": "' '{t=substr($2,1,19); if (t<p) u++; p=t} END {print "lines", NR, "out of order", u+0}'
