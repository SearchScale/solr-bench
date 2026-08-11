#!/usr/bin/env bash
# Print segment count for mtbench-seg on local solr-bench node (port 50000).
set -euo pipefail
PORT="${1:-50000}"
COL="${2:-mtbench-seg}"
URL="http://localhost:${PORT}/solr/${COL}/admin/luke?numTerms=0&show=index"
curl -sf "$URL" | python3 -c "
import json, sys
d = json.load(sys.stdin)
idx = d.get('index', {})
print('collection=%s numDocs=%s maxDoc=%s segments=%s' % (
    idx.get('name', '?'),
    idx.get('numDocs', '?'),
    idx.get('maxDoc', '?'),
    idx.get('segmentCount', '?'),
))
"
