# Solr+Lucene vs Solr+Luxir benchmarks

This guide runs the same SolrCloud workload twice on one machine:

- **Solr+Lucene**: stock Apache Solr built from an Apache Solr commit, storing and searching its index with Lucene's
  own codecs.
- **Solr+Luxir**: the `luxir-codec` branch of [SearchScale/solr](https://github.com/SearchScale/solr), which adds the
  `luxir-codec` module. Luxir field types store their data in Luxir's native segment format, and queries and facets
  run natively through `libluxir_lucene.so`.

The workload is the `stress-facets` suite:

1. Index 100M documents of the e-commerce events dataset into a 3-node, 3-shard collection (one replica per shard),
   from 16 client threads.
2. Restart each node once.
3. Run four query tasks one after the other, each from 16 concurrent client threads with no rate cap, one per query
   type in its own file under `suites/queries/`:

   | Task | Query file | Measured queries (warm-up) | What each query does |
   |---|---|---|---|
   | `task3` | `facets-terms.json` | 6,000 (20) | terms facet on `event_type` over a 7-day `event_time` range |
   | `task4` | `facets-range.json` | 6,000 (20) | range facet on `price` (300 buckets) over purchases in a 7-day range |
   | `task5` | `facets-product.json` | 6,000 (20) | terms facet on `product_id` and `avg(price)` over purchases in a 7-day range |
   | `task6` | `facets-join.json` | 100 (3) | all docs, filtered by a join on `user_session` from a 1-day range |

   The four files are `facets2.json` split by query type, each keeping the queries' order.

It reports indexing time, restart times, query throughput and query latency percentiles.

[Results](#results) from two machines are at the end of this file.

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
| luxir | `luxir-lucene` | `48a10abe` (Luxir `e42cd268` + the 4 patches in `luxir-lucene/luxir-patches/`) |
| luxir-lucene | `main` | `ed0bedc` |
| solr | `luxir-codec` | `c9e21f7c6ae20a21d3e97795896127ed5e7b62f4` |

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

Run Solr+Lucene first, then Solr+Luxir. Both suites index 100M documents in 50,000-document batches from 16 threads,
then run the four query tasks from 16 threads each.

```bash
cd /path/to/solr-bench
./cleanup.sh && ./stress.sh -c 63f2459f3b58861de8575ecbfbefc38281482f3a suites/stress-facets-local-100m.json        # Solr+Lucene
./cleanup.sh && ./stress.sh -c c9e21f7c6ae20a21d3e97795896127ed5e7b62f4 suites/luxir-stress-facets-local-100m.json  # Solr+Luxir
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
    "OMP_NUM_THREADS": "1",
    "SOLR_SECURITY_MANAGER_ENABLED": "false",
    "SOLR_OPTS": "--enable-native-access=ALL-UNNAMED -Dluxir.lucene.library=/path/to/libluxir_lucene.so"
  }
  ```

  `OMP_NUM_THREADS=1` keeps the native library from starting an OpenMP thread team for every query. With many
  concurrent queries those teams oversubscribe the CPU: in a 32-thread test on the 7950X it raised Solr+Luxir's p99
  from 508 ms to 3.1 s and cut its throughput by 12%.

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
  suites/results/luxir-stress-facets-local-100m/c9e21f7c6ae20a21d3e97795896127ed5e7b62f4 Solr+Lucene Solr+Luxir
```

What the fields mean:

- **Indexing:** `task1[0].total-time`, in seconds.
- **Restarts:** `task2[*].total-time`, in seconds. Each covers stopping the node, starting it, and waiting for its
  replicas to recover.
- **Queries:** `task3` to `task6` (one per query type), each with `timings`: one entry per thread count in the task's
  `threads` (here just 16). Each has `qps` (queries per second over the whole run, warm-up included), and the latency
  percentiles `50th`, `90th`, `95th`, `99th` and `mean` in milliseconds, measured over the queries after the
  warm-up. `compare.py` labels them by the task's description from `config.json`.

How to read them:

- **Throughput and latency together.** With 16 concurrent clients and no rate cap, Solr is fully loaded, so a system
  that does more work per query shows it in both lower throughput and higher latencies.
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

Results from one run of `suites/stress-facets-local-100m.json` (Solr+Lucene) and
`suites/luxir-stress-facets-local-100m.json` (Solr+Luxir) on 2026-10-23. Each indexes the first 100M events of the
150M dataset, restarts each node, then runs the four query tasks from 16 concurrent clients. Ratios are how much
better Solr+Luxir is: Solr+Lucene's time ÷ Solr+Luxir's, or Solr+Luxir's throughput ÷ Solr+Lucene's, so above 1× means
Solr+Luxir was faster.

| | |
|---|---|
| Solr+Lucene | apache/solr `main` @ `63f2459` (11.0.0-SNAPSHOT), security manager on |
| Solr+Luxir | SearchScale/solr `luxir-codec` @ `c9e21f7`, with luxir `48a10abe` and luxir-lucene `ed0bedc`; native library built on this machine with `-DLUXIR_CPU_TARGET=native`; `OMP_NUM_THREADS=1`; security manager off |
| JDK | Oracle JDK 22.0.2, for both Solr and the solr-bench client |
| Solr nodes | 3 on the same machine, each with `-m 16g -Dsolr.searchThreads=4` |
| Client | solr-bench (`java -Xmx12g`) on the same machine: 16 indexing threads with 50,000-document batches, 16 query threads with no rate cap |
| CPU | AMD Ryzen 9 7950X: 16 cores / 32 threads, up to 5.88 GHz, 64 MB L3, one socket |
| Memory | 128 GB DDR5 (2 × 64 GB at 6000 MT/s, non-ECC); 124 GiB usable |
| Disk | WD_BLACK SN8100 4 TB NVMe SSD, ext4. It holds the dataset, the Solr nodes and their indexes. |
| OS | Ubuntu 22.04.5 LTS, Linux 6.8.0-138-generic, transparent huge pages `madvise` |

### Indexing and restarts

| | Solr+Lucene | Solr+Luxir | Solr+Luxir better by |
|---|---|---|---|
| Indexing 100M documents | 701.5 s (142,500 docs/s) | 390.5 s (256,100 docs/s) | **1.80×** |
| Node restarts | 5.78 s, 5.86 s, 5.79 s | 5.85 s, 5.81 s, 5.78 s | same |

Both runs indexed exactly 100,000,000 documents, with identical per-shard counts (33,331,737 / 33,333,346 /
33,334,917). Restart times include waiting for replicas to recover.

### Queries, 16 concurrent clients

| Query task | | Solr+Lucene | Solr+Luxir | Solr+Luxir better by |
|---|---|---|---|---|
| Terms facet (6,000 queries) | throughput | 129.7 queries/s | 273.3 queries/s | **2.11×** |
| | p50 / p95 / p99 | 144.0 / 217.0 / 254.6 ms | 66.8 / 99.1 / 114.3 ms | 2.16× / 2.19× / 2.23× |
| | mean | 122.3 ms | 57.8 ms | 2.12× |
| Range facet (6,000) | throughput | 172.6 queries/s | 463.5 queries/s | **2.69×** |
| | p50 / p95 / p99 | 105.6 / 162.3 / 193.0 ms | 38.9 / 58.5 / 68.6 ms | 2.71× / 2.77× / 2.82× |
| | mean | 91.4 ms | 34.3 ms | 2.66× |
| Product facet (6,000) | throughput | 501.7 queries/s | 285.9 queries/s | **0.57×** |
| | p50 / p95 / p99 | 37.2 / 53.8 / 61.8 ms | 65.3 / 89.9 / 101.9 ms | 0.57× / 0.60× / 0.61× |
| | mean | 31.4 ms | 55.4 ms | 0.57× |
| Join (100) | throughput | 2.4 queries/s | 14.2 queries/s | **5.92×** |
| | p50 / p95 / p99 | 6,967 / 9,303 / 9,612 ms | 1,384 / 1,837 / 2,013 ms | 5.04× / 5.06× / 4.77× |
| | mean | 6,449 ms | 1,102 ms | 5.85× |
| All four tasks | total time | 136.2 s | 63.3 s | **2.15×** |

Throughput counts each task's warm-up queries (20, or 3 for joins) over its whole run; latencies are over the
measured queries after them.

- **Indexing:** Solr+Luxir indexed 1.80× faster.
- **Terms and range facets:** Solr+Luxir handled 2.1× and 2.7× the queries per second, with lower latency at every
  percentile.
- **Product facet:** Solr+Lucene was faster on this query type, with 1.75× the throughput. Each query buckets about
  12,000 distinct `product_id` values per shard and computes `avg(price)`; this is the query type left to optimize in
  Solr+Luxir.
- **Joins:** Solr+Luxir runs joins between string fields natively (`LuxirJoinQParserPlugin`), 5.9× the throughput of
  Solr's join.
- **Overall:** the four tasks took 2.15× less time on Solr+Luxir.

### JVM metrics

Sampled every 2 seconds (plus the time each sample takes) on each of the 3 nodes over the whole run.

| | Solr+Lucene | Solr+Luxir |
|---|---|---|
| Peak heap usage (of 16 GB) | 0.89–0.90 | 0.85–0.90 |
| Mean heap usage | 0.44–0.45 | 0.40–0.42 |
| Threads per node | 47–116 | 46–121 |
| Heap right after a restart (average) | 235 MB | 224 MB |
