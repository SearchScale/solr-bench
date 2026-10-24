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

[Results](#results) from two machines are at the end of this file, followed by [the changes](#how-solrluxir-got-here)
that made Solr+Luxir fast and what each one changed.

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
| luxir | `luxir-lucene` | `13c80ecc` (Luxir `8cb622ba` + the 4 patches in `luxir-lucene/luxir-patches/`) |
| luxir-lucene | `main` | `57f953d` |
| solr | `luxir-codec-c9e21f7` (`luxir-codec` has since been rebased onto a newer Solr) | `c9e21f7c6ae20a21d3e97795896127ed5e7b62f4` |

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
`suites/luxir-stress-facets-local-100m.json` (Solr+Luxir) on each of two machines, on 2026-10-23 and 2026-10-24. Each run indexes
the first 100M events of the 150M dataset, restarts each node, then runs the four query tasks from 16 concurrent
clients. Ratios are how much better Solr+Luxir is: Solr+Lucene's time ÷ Solr+Luxir's, or Solr+Luxir's throughput ÷
Solr+Lucene's, so above 1× means Solr+Luxir was faster. Throughput counts each task's warm-up queries (20, or 3 for
joins) over its whole run; latencies are over the measured queries after them. Restart times include waiting for
replicas to recover.

Both machines used the same settings, with everything built on the machine itself:

| | |
|---|---|
| Solr+Lucene | apache/solr `main` @ `63f2459` (11.0.0-SNAPSHOT), security manager on |
| Solr+Luxir | SearchScale/solr `luxir-codec` @ `c9e21f7`, with the Luxir and luxir-lucene versions given for each machine below; native library built on the machine with `-DLUXIR_CPU_TARGET=native`; `OMP_NUM_THREADS=1`; security manager off |
| JDK | Oracle JDK 22.0.2, for both Solr and the solr-bench client |
| Solr nodes | 3 on the same machine, each with `-m 16g -Dsolr.searchThreads=4` |
| Client | solr-bench (`java -Xmx12g`) on the same machine: 16 indexing threads with 50,000-document batches, 16 query threads with no rate cap |

On both machines, both runs indexed exactly 100,000,000 documents, with identical per-shard counts (33,331,737 /
33,333,346 / 33,334,917).

### Summary

| | 7950X: Solr+Luxir better by | 5950X: Solr+Luxir better by |
|---|---|---|
| Indexing | **1.84×** | **2.09×** |
| Terms facet throughput | **2.14×** | **2.03×** |
| Range facet throughput | **2.69×** | **2.83×** |
| Product facet throughput | **0.58×** | **0.55×** |
| Join throughput | **5.82×** | **6.01×** |
| All four query tasks (total time) | **2.16×** | **2.09×** |

- **Indexing:** Solr+Luxir indexed 1.8–2.1× faster.
- **Terms and range facets:** Solr+Luxir handled 2.0–2.8× the queries per second, with lower latency at every
  percentile.
- **Product facet:** Solr+Lucene was faster on this query type, with about 1.7–1.8× the throughput. Each
  query buckets about 12,000 distinct `product_id` values per shard and computes `avg(price)`; this is the query type
  left to optimize in Solr+Luxir.
- **Joins:** Solr+Luxir runs joins between string fields natively (`LuxirJoinQParserPlugin`), about 6× the throughput
  of Solr's join.
- **Overall:** the four query tasks took about 2.1× less time on Solr+Luxir.

### AMD Ryzen 9 7950X

Solr+Luxir used Luxir `8cb622ba` with the 4 patches (`13c80ecc`) and luxir-lucene `57f953d`. The same run on the
previous base (Luxir `e42cd268`, luxir-lucene `ed0bedc`) was within 1% of these numbers on every task.

| | |
|---|---|
| CPU | AMD Ryzen 9 7950X: 16 cores / 32 threads, up to 5.88 GHz, 64 MB L3, one socket |
| Memory | 128 GB DDR5 (2 × 64 GB at 6000 MT/s, non-ECC); 124 GiB usable |
| Disk | WD_BLACK SN8100 4 TB NVMe SSD, ext4. It holds the dataset, the Solr nodes and their indexes. |
| OS | Ubuntu 22.04.5 LTS, Linux 6.8.0-138-generic, transparent huge pages `madvise` |

| | Solr+Lucene | Solr+Luxir | Solr+Luxir better by |
|---|---|---|---|
| Indexing 100M documents | 716.2 s (139,600 docs/s) | 389.1 s (257,000 docs/s) | **1.84×** |
| Node restarts | 5.84 s, 5.90 s, 5.84 s | 5.77 s, 5.80 s, 5.81 s | same |

| Query task | | Solr+Lucene | Solr+Luxir | Solr+Luxir better by |
|---|---|---|---|---|
| Terms facet (6,000 queries) | throughput | 126.7 queries/s | 270.6 queries/s | **2.14×** |
| | p50 / p95 / p99 | 147.8 / 222.9 / 263.5 ms | 67.3 / 99.5 / 117.4 ms | 2.20× / 2.24× / 2.24× |
| | mean | 125.4 ms | 58.2 ms | 2.15× |
| Range facet (6,000) | throughput | 172.2 queries/s | 462.7 queries/s | **2.69×** |
| | p50 / p95 / p99 | 106.4 / 164.1 / 188.5 ms | 38.7 / 59.3 / 71.4 ms | 2.75× / 2.77× / 2.64× |
| | mean | 91.7 ms | 34.4 ms | 2.66× |
| Product facet (6,000) | throughput | 502.2 queries/s | 289.3 queries/s | **0.58×** |
| | p50 / p95 / p99 | 37.0 / 52.5 / 62.5 ms | 64.6 / 90.1 / 101.9 ms | 0.57× / 0.58× / 0.61× |
| | mean | 31.2 ms | 54.9 ms | 0.57× |
| Join (100) | throughput | 2.4 queries/s | 14.1 queries/s | **5.82×** |
| | p50 / p95 / p99 | 6,919 / 8,933 / 9,587 ms | 1,397 / 1,896 / 2,217 ms | 4.95× / 4.71× / 4.32× |
| | mean | 6,384 ms | 1,101 ms | 5.80× |
| All four tasks | total time | 137.0 s | 63.4 s | **2.16×** |

JVM metrics, sampled every 2 seconds (plus the time each sample takes) on each of the 3 nodes over the whole run:

| | Solr+Lucene | Solr+Luxir |
|---|---|---|
| Peak heap usage (of 16 GB) | 0.88–0.89 | 0.85–0.89 |
| Mean heap usage | 0.45 | 0.40–0.43 |
| Threads per node | 47–118 | 46–120 |
| Heap right after a restart (average) | 234 MB | 214 MB |

### AMD Ryzen 9 5950X

Solr+Luxir used Luxir `e42cd268` with the 4 patches (`48a10abe`) and luxir-lucene `ed0bedc`, all cloned from GitHub
on the machine. The machine's other workloads were stopped for the runs. The Luxir native library was compiled for
the 5950X's Zen 3 cores, which have no AVX-512.

| | |
|---|---|
| CPU | AMD Ryzen 9 5950X: 16 cores / 32 threads, up to 5.08 GHz, 64 MB L3, one socket |
| Memory | 128 GB DDR4 (4 × 32 GB at 3200 MT/s, non-ECC); 125 GiB usable |
| Disk | Crucial P3 1 TB NVMe SSD (CT1000P3SSD8), ext4. It holds the dataset, the Solr nodes and their indexes. |
| OS | Ubuntu 24.04.5 LTS, Linux 6.8.0-147-generic, transparent huge pages `madvise` |

| | Solr+Lucene | Solr+Luxir | Solr+Luxir better by |
|---|---|---|---|
| Indexing 100M documents | 1,198.0 s (83,500 docs/s) | 573.3 s (174,400 docs/s) | **2.09×** |
| Node restarts | 8.15 s, 8.14 s, 8.15 s | 17.38 s, 7.11 s, 7.11 s | |

Solr+Luxir's first restart, right after indexing, took 12.5 s to shut the node down; its node startups (4.85 s) were
faster than Solr+Lucene's (5.89 s).

| Query task | | Solr+Lucene | Solr+Luxir | Solr+Luxir better by |
|---|---|---|---|---|
| Terms facet (6,000 queries) | throughput | 90.0 queries/s | 182.4 queries/s | **2.03×** |
| | p50 / p95 / p99 | 208.1 / 316.7 / 383.7 ms | 101.2 / 151.1 / 175.5 ms | 2.06× / 2.10× / 2.19× |
| | mean | 176.7 ms | 86.8 ms | 2.04× |
| Range facet (6,000) | throughput | 106.5 queries/s | 302.0 queries/s | **2.83×** |
| | p50 / p95 / p99 | 174.9 / 266.6 / 315.9 ms | 59.4 / 92.9 / 111.2 ms | 2.94× / 2.87× / 2.84× |
| | mean | 148.3 ms | 52.8 ms | 2.81× |
| Product facet (6,000) | throughput | 315.0 queries/s | 172.9 queries/s | **0.55×** |
| | p50 / p95 / p99 | 60.6 / 87.3 / 102.2 ms | 108.1 / 151.9 / 174.2 ms | 0.56× / 0.57× / 0.59× |
| | mean | 50.1 ms | 92.0 ms | 0.54× |
| Join (100) | throughput | 1.7 queries/s | 10.0 queries/s | **6.01×** |
| | p50 / p95 / p99 | 9,911 / 13,181 / 14,820 ms | 1,956 / 2,728 / 2,925 ms | 5.07× / 4.83× / 5.07× |
| | mean | 9,289 ms | 1,578 ms | 5.89× |
| All four tasks | total time | 204.6 s | 98.1 s | **2.09×** |

JVM metrics, sampled the same way:

| | Solr+Lucene | Solr+Luxir |
|---|---|---|
| Peak heap usage (of 16 GB) | 0.88–0.91 | 0.88–0.91 |
| Mean heap usage | 0.45–0.47 | 0.40–0.43 |
| Threads per node | 47–104 | 46–111 |
| Heap right after a restart (average) | 221 MB | 206 MB |

## How Solr+Luxir got here

The first runs of this benchmark had Solr+Luxir indexing faster but querying slower than Solr+Lucene: on the
7950X with the earlier mixed workload (5,000 queries of all four types from 16 clients), 94.6 queries/s against
131.9. Profiling showed where the time went, and these changes, in the order they were made, turned that into
268.3 queries/s against 130.2 on the same workload. The commits below are where each change was made; the
Luxir one is `luxir-patches/0004`, which the rebased Luxir above (`13c80ecc`) carries too.

How each effect was measured, on the 7950X:

- **per shard:** one query type sent to a single shard (`distrib=false`) from one client, mean QTime over 30 queries
  after 5 warm-up queries, on a 3-node cluster with the 100M index;
- **16-client mix:** the benchmark's first 5,000 mixed queries from 16 clients against a freshly restarted 3-node
  cluster with the 100M index (Solr+Lucene: 130.3 queries/s, p99 350 ms).

Each "without → with" adds that change to the ones above it.

| Change | Where | Without → with |
|---|---|---|
| Pass Solr's filter (`fq`) to Luxir as a FILTER clause of the query, so the planner sees how selective it is and leads with it, checking the date range only on the filter's documents instead of computing the whole range | luxir-lucene `ed0bedc` (`FilterSlotQuery`) | per shard, range facet 27.5 → 25.8 ms, product facet 26.9 → 23.9 ms |
| Keep the filters Luxir computes for Solr's filter cache as bitsets, and never call `getBits()` on a `SortedIntDocSet` (it hashed every doc of the filter, twice per request: 26% of CPU on filtered queries) | solr `c9e21f7` (`LuxirCodecQueryComponent`) | per shard, range facet 25.8 → 17.5 ms, product facet 23.9 → 16.5 ms |
| Take a constant-score query's top k from the match bits of its counting pass instead of running it a second time | luxir-lucene `ed0bedc` (`lxl_multi_top_k`) | per shard, range facet 17.5 → 14.2 ms, product facet 16.5 → 10.7 ms, terms facet 25.4 → 19.7 ms |
| Run joins between string fields natively: values matched through each segment's doc-values dictionary, then one column scan, instead of Solr's join walking every term through the codec (37% of CPU under load, for 0.5% of the queries) | luxir-lucene `ed0bedc` (`LuxirJoin`), solr `c9e21f7` (`LuxirJoinQParserPlugin`) | per shard, one join 3.31 s → 0.61 s (Solr+Lucene: 2.37 s) |
| Copy match and filter bits between native memory and Java in bulk; word-by-word segment access was slow until the JIT compiled it, so the first queries after a restart took seconds | luxir-lucene `ed0bedc` (`LuxirSearch`, `NativeLeaf`) | 16-client mix, 174.1 → 229.9 queries/s, p99 1,181 → 155 ms |
| Verify a range per candidate from each column block's relation to it (wholly inside, wholly outside or crossing), reading values only in crossing blocks; and find a range facet bucket by binary search instead of testing all 300 (measured together) | luxir `48a10abe` (`luxir-patches/0004`), luxir-lucene `ed0bedc` (`lxl_facet_collect`) | per shard, range facet 14.2 → 5.3 ms, product facet 10.7 → 9.6 ms; 16-client mix, 229.9 → 275.7 queries/s, p99 155 → 142 ms |
| Set `OMP_NUM_THREADS=1` for Solr+Luxir nodes: per-query OpenMP thread teams oversubscribed the CPU under concurrency | suite configuration | full benchmark at 32 clients (before the changes above), 80.7 → 92.2 queries/s, p99 3,132 → 508 ms |

Every change returns the same results as before: on a sample of 180 facet queries the counts, top documents,
scores and facets were identical after each change, the native join matched Solr's join, and the luxir-lucene and
Solr module test suites pass, with new tests for joins and for filtered ranges.
