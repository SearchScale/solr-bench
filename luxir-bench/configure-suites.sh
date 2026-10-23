#!/usr/bin/env bash
# Points the Luxir suites at your solr-luxir directory (the .so and the luxir-lucene jar).
# Usage: luxir-bench/configure-suites.sh /path/to/solr-luxir
set -euo pipefail
root=$(cd "${1:?usage: $0 /path/to/solr-luxir}" && pwd)
cd "$(dirname "$0")/../suites"
for f in luxir-stress-facets-local*.json; do
  python3 - "$f" "$root" <<'PY'
import json, re, sys
path, root = sys.argv[1], sys.argv[2]
c = json.load(open(path))
lib = f"{root}/luxir/build/lux4j-release/bin/libluxir_lucene.so"
jar = f"{root}/luxir-lucene/build/libs/luxir-lucene-0.1.0-SNAPSHOT.jar"
env = c["cluster"]["environment"]
env["SOLR_OPTS"] = re.sub(r"-Dluxir\.lucene\.library=\S+", f"-Dluxir.lucene.library={lib}", env["SOLR_OPTS"])
for r in c["repositories"]:
    r["build-command"] = re.sub(r"-Pluxir\.lucene\.jar=\S+", f"-Pluxir.lucene.jar={jar}", r["build-command"])
json.dump(c, open(path, "w"), indent=2)
open(path, "a").write("\n")
print(f"{path}: library {lib}, jar {jar}")
PY
done
