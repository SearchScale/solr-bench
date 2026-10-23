# Solr+Lucene vs Solr+Luxir benchmarks

This guide runs the same SolrCloud workload twice on one machine:

- **Solr+Lucene**: stock Apache Solr built from an Apache Solr commit, storing and searching its index with Lucene's
  own codecs.
- **Solr+Luxir**: the `luxir-codec` branch of [SearchScale/solr](https://github.com/SearchScale/solr), which adds the
  `luxir-codec` module. Luxir field types store their data in Luxir's native segment format, and queries and facets
  run natively through `libluxir_lucene.so`.

The workload is the `stress-facets` suite:

1. Index the e-commerce events dataset into a 3-node, 3-shard collection (one replica per shard).
2. Restart each node once.
3. Run 5,000 JSON facet queries on one thread. The first 20 are warm-up queries and aren't counted.

It reports indexing time, restart times and query latency percentiles. [Results](#results) from one machine are at
the end of this file.

## What you need

| | |
|---|---|
| OS / CPU | Linux x86-64 |
| RAM | 64 GB or more. Each of the 3 Solr nodes gets a 16 GB heap, and Luxir reads its segments through the page cache. |
| Disk | About 40 GB for the dataset, the largest index and the Solr builds. Add about 15 GB to rebuild the dataset yourself. |
| JDK | 22 or later on the `PATH`, with `JAVA_HOME` set. Luxir's Java side uses the Foreign Function and Memory API. |
| Tools | `git`, `mvn`, `jq`, `curl`, `wget`, `lsof`, `pigz`, `python3` (plus `numpy` only to rebuild the dataset) |
| Docker | With BuildKit (the `docker buildx` plugin), to build the native library in Luxir's dev container |

## 1. Get the code

Clone the three Luxir repositories side by side in one directory. This guide calls it `$LUXIR_ROOT`.

```bash
export LUXIR_ROOT=$HOME/solr-luxir
mkdir -p $LUXIR_ROOT && cd $LUXIR_ROOT
git clone --recurse-submodules -b luxir-lucene https://github.com/SearchScale/luxir.git  # Luxir plus the patches luxir-lucene needs
git clone https://github.com/SearchScale/luxir-lucene.git                   # Lucene codec + native C ABI
git clone -b luxir-codec https://github.com/SearchScale/solr.git            # Solr with the luxir-codec module
```

The [results](#results) below used these versions:

| Repository | Branch | Commit |
|---|---|---|
| luxir | `luxir-lucene` | `0df0e119` (Luxir `e42cd268` + the 3 patches in `luxir-lucene/luxir-patches/`) |
| luxir-lucene | `main` | `e2c5039` |
| solr | `luxir-codec` | `d2d7cf1eddf55a4586c55ecb828a53c4c3fde738` |

## 2. Build the native library

```bash
cd /path/to/solr-bench
luxir-bench/build-native.sh $LUXIR_ROOT
```

The script first makes sure the Luxir checkout is complete: it initializes Luxir's git submodule (`deps/hpp-proto`)
and runs `deps/fetch_sources.sh`, which clones FastPFOR at its pinned tag into `deps/FastPFOR` (not kept in git). The
first run then builds Luxir's dev image (`luxir-dev:normal-deps`, about 6 GB), from the `normal-dependencies` stage of
`luxir/.devcontainer/Dockerfile`; that took about 20 minutes on a 16-core machine. Finally it builds
`libluxir_lucene.so` inside the container and writes it to `$LUXIR_ROOT/luxir/build/lux4j-release/bin/`, with the
GCC 16 `libgomp.so.1` it needs beside it.

Notes:

- The library is built with `-DLUXIR_CPU_TARGET=native`, so it uses your CPU's instruction set. Build it on the
  machine that will run the benchmark.
- `-DLUXIR_JEMALLOC=OFF` is required. jemalloc would replace the JVM's malloc.
- The build uses `-DLUXIR_STATIC_RUNTIME=OFF` because the container's static `libgomp.a` isn't position independent
  and can't be linked into a shared library. libstdc++ and libgcc are still linked statically.
- If `docker build` fails with `the --mount option requires BuildKit`, install the
  [buildx plugin](https://github.com/docker/buildx#installing) into `~/.docker/cli-plugins/`.

## 3. Build the luxir-lucene jar

```bash
cd $LUXIR_ROOT/luxir-lucene
./gradlew jar                                   # or: ./gradlew test jar, to also run its tests against the library
ls build/libs/luxir-lucene-0.1.0-SNAPSHOT.jar
```

By default the build looks for the library at `../luxir/build/lux4j-release/bin/libluxir_lucene.so`, which is
where step 2 puts it.

You don't need to build Solr yourself. solr-bench checks out the `luxir-codec` commit and runs
`../gradlew -Pluxir.lucene.jar=<jar> distTar`, which bundles the jar into `modules/luxir-codec/lib`.

## 4. Build solr-bench and point the Solr+Luxir suites at your files

```bash
cd /path/to/solr-bench
mvn clean compile assembly:single
luxir-bench/configure-suites.sh $LUXIR_ROOT
```

`configure-suites.sh` rewrites the two machine-specific paths in `suites/luxir-stress-facets-local-100m.json`: the
`.so` path in `SOLR_OPTS` and the jar path in the build command.

## 5. Get the dataset

Both suites use the 150M-event dataset (`ecommerce-events-150m.json.gz`, 8.7 GB) and index its first 100M events.
They download it into `suites/datasets/` on their first run, from the `pre-download` URL
`https://huggingface.co/buckets/searchscale/solr-bench/resolve/ecommerce-events-150m.json.gz`.

The file is built from the real 110M-event dataset (`ecommerce-events.json.gz`, in the same bucket) by
`luxir-bench/dataset/make-150m-dataset.sh`, which you can run to rebuild it locally (about 15 minutes on 32 cores,
needs about 30 GB RAM). It profiles all 109,950,743 real events, generates 40,049,257 synthetic events that follow the
same patterns, and merges them into the real stream in `event_time` order. Since the events are in time order, the
first 100M events are a mix of real and synthetic ones. The synthetic events follow:

- the real product catalog and each product's popularity, view/cart/purchase mix, category, brand and prices
- the real per-minute event volume across Oct 1 – Nov 30 2019, so the queries' date ranges include them
- real users weighted by activity, with sessions modelled on real ones: their length, the gaps between events, and
  how often the next event repeats a product or stays in its category

Their IDs are 19-digit numbers above the real ID range, so they never collide with real docs. The generator is
seeded (`SEED=42` by default), so a rerun produces the same file.

## 6. Run the benchmark

Run Solr+Lucene first, then Solr+Luxir. Both suites index 100M documents in 50,000-document batches.

```bash
cd /path/to/solr-bench
./cleanup.sh && ./stress.sh -c 63f2459f3b58861de8575ecbfbefc38281482f3a suites/stress-facets-local-100m.json        # Solr+Lucene
./cleanup.sh && ./stress.sh -c d2d7cf1eddf55a4586c55ecb828a53c4c3fde738 suites/luxir-stress-facets-local-100m.json  # Solr+Luxir
```

Things to know:

- **Choice of Solr+Lucene commit.** `-c` picks the Solr commit to build. The results below compare against Apache Solr
  `main` at `63f2459`, which is 7 commits ahead of the point where `luxir-codec` branched. For an exact
  like-for-like baseline, use the fork point instead: `-c 4422d26ac7889b7ba5f26bce1bbff0d3113cc91f`.
- **Run time.** Each run builds its Solr commit with Gradle the first time and reuses the tarball afterwards. Each run
  then takes about 20 minutes.
- **Broken IPv6.** If downloads hang (the Gradle wrapper, JDK toolchains), your machine's IPv6 route is probably broken.
  Run with `export JAVA_TOOL_OPTIONS="-Djava.net.preferIPv4Stack=true"`.
- **Harmless errors.** `stress.sh` tries to apply two old custom patches; `patch` failures in the log are harmless.
- **Ports.** `cleanup.sh` kills anything on ports 50000–50050 and ZooKeeper on 2181. Don't run it while another
  Solr is using those ports.

### What the Solr+Luxir suite changes

Only the Solr build, the configset and the node environment differ. The workload is identical.

- **Configset** `conf_ecommerce_events_luxir`, a copy of `conf_ecommerce_events` with these changes:
  - `string`, `pfloat`, `plong` and `pdate` fields switched to `LuxirStrField`, `LuxirFloatPointField`,
    `LuxirLongPointField` and `LuxirDatePointField`
  - `LuxirCodecFactory` as the codec
  - Luxir query, facet and facet-module components
  - `LuxirUpdateRequestHandler` on `/update`
- **Node environment.** It is set through the suite's `cluster.environment` map, which solr-bench passes to
  `bin/solr start`:

  ```json
  "environment": {
    "SOLR_MODULES": "luxir-codec",
    "SOLR_SECURITY_MANAGER_ENABLED": "false",
    "SOLR_OPTS": "--enable-native-access=ALL-UNNAMED -Dluxir.lucene.library=/path/to/libluxir_lucene.so"
  }
  ```

## 7. Check that Luxir is really doing the work

While the Solr+Luxir run is in its query phase, send one query with `debug=true`. Every response then reports which
path it took:

```bash
curl -s 'http://localhost:50000/solr/ecommerce-events/select?q=*:*&rows=0&debug=true' | tr -d ' \n' | grep -o '"luxirCodec".\{0,40\}'
# "luxirCodec":["path","native",...   (path "lucene" plus a "reason" means the request fell back to Solr's normal code)
```

To compare document counts between the two runs (they should be identical), query each shard:

```bash
for s in shard1 shard2 shard3; do
  curl -s "http://localhost:50000/solr/ecommerce-events/select?q=*:*&rows=0&shards=$s" | grep -o '"numFound":[0-9]*'
done
```

## 8. Compare the results

Results are written to `suites/results/<suite name>/<commit>/`. The useful files are `results.json`, which holds the
timings, and `config.json`, the suite as run. Compare a Solr+Lucene and a Solr+Luxir run with:

```bash
python3 luxir-bench/compare.py \
  suites/results/stress-facets-local-100m/63f2459f3b58861de8575ecbfbefc38281482f3a \
  suites/results/luxir-stress-facets-local-100m/d2d7cf1eddf55a4586c55ecb828a53c4c3fde738 Solr+Lucene Solr+Luxir
```

What the fields mean:

- **Indexing:** `task1[0].total-time`, in seconds.
- **Restarts:** `task2[*].total-time`, in seconds. Each covers stopping the node, starting it, and waiting for its
  replicas to recover.
- **Query latency:** `task3[0].timings[0]`, with the percentiles `50th`, `90th`, `95th` and `mean` in milliseconds,
  measured over 4,980 queries.

How to read them:

- **Latency, not throughput.** Queries run on one thread, capped at 3,000 per minute. At 100M and above, each query
  takes longer than the cap allows (20 ms), so the query phase is paced by latency.
- **Look past the percentiles.** The results don't include per-query timings. A few very slow queries above p95 can
  move the mean a lot while the percentiles barely change, so compare the mean and the percentiles together.
- **Noise.** p95 can vary by several percent between identical runs. Repeat runs before trusting small differences.

## Known caveats

- **Security manager.** The Solr+Luxir runs disable Solr's security manager (`SOLR_SECURITY_MANAGER_ENABLED=false`)
  so the native library can load; the Solr+Lucene runs keep it on. That gives Solr+Luxir a small advantage.
- **JVM metrics.** Solr 10+ serves its metrics only in Prometheus format. solr-bench reads both that and the older
  JSON format, so the suites' JVM metrics (`metrics.json`) and the heap after each restart (`heap-mb` in
  `results.json`) work on both Solr 9 and Solr 10/11. A sample taken while a node is restarting is recorded as `-1`.
- **Dataset density.** The synthetic events fall in the same Oct–Nov 2019 window as the real ones, so the first 100M
  events of the 150M file cover a shorter span of time than the first 100M real events did.

## Results

All runs used `suites/stress-facets-local-100m.json` and `suites/luxir-stress-facets-local-100m.json` on 2026-10-23,
with the same versions on both machines:

| | |
|---|---|
| Solr+Lucene | apache/solr `main` @ `63f2459` (11.0.0-SNAPSHOT), security manager on |
| Solr+Luxir | SearchScale/solr `luxir-codec` @ `d2d7cf1`, with luxir `0df0e119` and luxir-lucene `e2c5039`; native library built on the machine itself with `-DLUXIR_CPU_TARGET=native`; security manager off |
| JDK | Oracle JDK 22.0.2, for both Solr and the solr-bench client |
| Solr nodes | 3 on the same machine, each with `-m 16g -Dsolr.searchThreads=4` |
| Client | solr-bench (`java -Xmx12g`, 8 indexing threads, 50,000-document batches) on the same machine as the cluster |

Each configuration ran once on each machine. Ratios above 1× mean Solr+Luxir was faster. Latencies are over 4,980
queries, after 20 warm-up queries. Restart times include waiting for replicas to recover.

### AMD Ryzen 9 7950X

These runs indexed the first 100M events of the real 110M-event dataset, before the suites switched to the 150M
dataset, so a rerun now indexes a different 100M events. They predate the JVM metrics fix, so there are no heap or
thread numbers.

| | |
|---|---|
| CPU | AMD Ryzen 9 7950X: 16 cores / 32 threads, up to 5.88 GHz, 64 MB L3, one socket |
| Memory | 128 GB DDR5 (2 × 64 GB at 6000 MT/s, non-ECC); 124 GiB usable |
| Disk | WD_BLACK SN8100 4 TB NVMe SSD, ext4. It holds the datasets, the Solr nodes and their indexes. |
| OS | Ubuntu 22.04.5 LTS, Linux 6.8.0-138-generic, transparent huge pages `madvise` |

| | Solr+Lucene | Solr+Luxir | Solr+Lucene ÷ Solr+Luxir |
|---|---|---|---|
| Indexing | 635.2 s (157,400 docs/s) | 511.9 s (195,400 docs/s) | **1.24×** |
| Node restarts | 5.88 s, 9.90 s, 5.85 s | 5.88 s, 5.87 s, 5.81 s | |
| Query p50 | 34.02 ms | 29.78 ms | 1.14× |
| Query p90 | 68.47 ms | 47.79 ms | 1.43× |
| Query p95 | 106.69 ms | 55.00 ms | **1.94×** |
| Query mean | 48.58 ms | 48.50 ms | 1.00× |
| Query phase | 243.6 s | 242.8 s | 1.00× |

- **Indexing:** Solr+Luxir indexed 1.24× faster.
- **Query latency:** Solr+Luxir was faster at p50, p90 and p95, with the gap growing toward the tail. Its mean was the
  same as Solr+Lucene's. With a lower p95, that means a few Solr+Luxir queries above p95 are very slow and cancel out
  its gains on the rest. solr-bench records only percentiles, so finding those queries needs per-query timings.
- **Restarts:** the same, except one Solr+Lucene restart that took 9.9 s because the node took long to shut down.
- **Doc counts:** both runs indexed exactly 100,000,000 documents, with identical per-shard counts (33,332,235 /
  33,335,048 / 33,332,717).

### AMD Ryzen 9 5950X

These runs indexed the first 100M events of the 150M dataset, which the suites use now. Everything on this machine
was cloned from git and built there, including the Luxir native library (compiled for the 5950X's Zen 3 cores, which
have no AVX-512). Other workloads on the machine were stopped for the runs.

| | |
|---|---|
| CPU | AMD Ryzen 9 5950X: 16 cores / 32 threads, up to 5.08 GHz, 64 MB L3, one socket |
| Memory | 128 GB DDR4 (4 × 32 GB at 3200 MT/s, non-ECC); 125 GiB usable |
| Disk | Crucial P3 1 TB NVMe SSD (CT1000P3SSD8), ext4. It holds the datasets, the Solr nodes and their indexes. |
| OS | Ubuntu 24.04.5 LTS, Linux 6.8.0-147-generic, transparent huge pages `madvise` |

| | Solr+Lucene | Solr+Luxir | Solr+Lucene ÷ Solr+Luxir |
|---|---|---|---|
| Indexing | 1,013.0 s (98,700 docs/s) | 720.1 s (138,900 docs/s) | **1.41×** |
| Node restarts | 7.10 s, 7.11 s, 7.67 s | 7.11 s, 7.09 s, 7.09 s | |
| Query p50 | 36.51 ms | 44.81 ms | 0.81× |
| Query p90 | 110.69 ms | 62.47 ms | 1.77× |
| Query p95 | 126.49 ms | 67.33 ms | **1.88×** |
| Query mean | 59.26 ms | 61.53 ms | 0.96× |
| Query phase | 297.5 s | 308.1 s | 0.97× |

JVM metrics, sampled every 2 seconds (plus the time each sample takes) on each of the 3 nodes over the whole run:

| | Solr+Lucene | Solr+Luxir |
|---|---|---|
| Peak heap usage (of 16 GB) | 0.90–0.91 | 0.98–0.99 |
| Mean heap usage | 0.41–0.42 | 0.42–0.44 |
| Threads per node | 47–69 | 46–68 |
| Heap right after a restart (average) | 224 MB | 219 MB |

- **Indexing:** Solr+Luxir indexed 1.41× faster, a bigger lead than on the 7950X.
- **Query latency:** Solr+Luxir was much faster at p90 and p95, but its median was 19% slower and its mean slightly
  higher. On this dataset the first 100M events span fewer days, so each query's date range matches more documents
  than on the 7950X runs.
- **Heap:** Solr+Luxir came closer to filling its heap at peak.
- **Restarts:** the same for both systems.
- **Doc counts:** both runs indexed exactly 100,000,000 documents, with identical per-shard counts (33,331,737 /
  33,333,346 / 33,334,917).
