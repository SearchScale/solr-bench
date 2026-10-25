# Solr+Lucene vs Solr+Luxir benchmarks

This guide runs the same SolrCloud workloads on one machine with:

- **Solr+Lucene**: stock Apache Solr built from an Apache Solr commit, storing and searching its index with Lucene's
  own codecs.
- **Solr+Luxir**: the `luxir-codec` branch of [SearchScale/solr](https://github.com/SearchScale/solr), which adds the
  `luxir-codec` module. Luxir field types store their data in Luxir's native segment format, and queries and facets
  run natively through `libluxir_lucene.so`.

There are two workloads. The main one, used in most of this guide, is the e-commerce `stress-facets` suite:

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

It reports indexing time, restart times, query throughput and query latency percentiles. The second workload,
[geonames](#geonames), indexes 11.4M places and runs 17 kinds of search request, from term and phrase queries to
sorts, facets and large `{!terms}` sets.

[Results](#results) for both workloads are at the end of this file, comparing stock Solr+Lucene, Solr+Lucene with the
security manager off and Solr+Luxir, followed by [the changes](#how-solrluxir-got-here) that made Solr+Luxir fast and
what each one changed.

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
| luxir | `luxir-lucene` | `173ec324` (Luxir `8cb622ba` + the 4 patches in `luxir-lucene/luxir-patches/` + a faster postings encoder) |
| luxir-lucene | `main` | `ecd09a1` |
| solr | `luxir-codec` (Apache Solr `79b23df` plus the module) | `31ae830a4e8cef8968769d4a9e3281562668b6c1` |

The geonames results used `luxir-codec` at `35d1e2b3871017184e90db8349c67801f898c519`, the same build without the
date parsing change, which the geonames schema does not use.

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

The e-commerce suites use the 150M-event dataset (`ecommerce-events-150m.json.gz`, 8.7 GB) and index its first 100M events.
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

The geonames suites read `suites/datasets/geonames.json.gz`, converted from the `documents-2.json.bz2` corpus of the
Rally and OpenSearch Benchmark geonames track:

```bash
curl -O https://rally-tracks.elastic.co/geonames/documents-2.json.bz2
python3 luxir-bench/geonames-jsonl.py documents-2.json.bz2 suites/datasets/geonames.json.gz
```

## 6. Run the benchmark

Run Solr+Lucene first, then Solr+Luxir. The e-commerce suites index 100M documents in 50,000-document batches from
16 threads, then run the four query tasks from 16 threads each; the [geonames](#geonames) suites are described below.

```bash
cd /path/to/solr-bench
./cleanup.sh && ./stress.sh -c 79b23df58daac14b92cc35f23b8b81f72098b4ba suites/stress-facets-local-100m.json        # Solr+Lucene
./cleanup.sh && ./stress.sh -c 31ae830a4e8cef8968769d4a9e3281562668b6c1 suites/luxir-stress-facets-local-100m.json  # Solr+Luxir

# geonames
./cleanup.sh && ./stress.sh -c 79b23df58daac14b92cc35f23b8b81f72098b4ba suites/geonames-local.json        # Solr+Lucene
./cleanup.sh && ./stress.sh -c 35d1e2b3871017184e90db8349c67801f898c519 suites/luxir-geonames-local.json  # Solr+Luxir
```

The Solr+Lucene suites run with Solr's security manager off. For stock Solr+Lucene, with it on as Solr starts by
default, remove the `environment` entry from their `cluster` section.

Things to know:

- **Choice of Solr+Lucene commit.** `-c` picks the Solr commit to build. `luxir-codec` is Apache Solr `main` at
  `79b23df` plus the module, so building `79b23df` for Solr+Lucene compares the same Solr.
- **Run time.** Each run builds its Solr commit with Gradle the first time and reuses the tarball afterwards. Each run
  then takes about 10 minutes (e-commerce) or 8 minutes (geonames).
- **Broken IPv6.** If downloads hang (the Gradle wrapper, JDK toolchains), your machine's IPv6 route is probably broken.
  Run with `export JAVA_TOOL_OPTIONS="-Djava.net.preferIPv4Stack=true"`.
- **Harmless errors.** `stress.sh` tries to apply two old custom patches; `patch` failures in the log are harmless.
- **Ports.** `cleanup.sh` kills anything on ports 50000–50050 and ZooKeeper on 2181. Don't run it while another
  Solr is using those ports.

### What the Solr+Luxir suite changes

Only the Solr build, the configset and the node environment differ. The workload is identical. Both suites disable
Solr's security manager (`SOLR_SECURITY_MANAGER_ENABLED=false` in `cluster.environment`); see
[Known caveats](#known-caveats).

- **Configset** `conf_ecommerce_events_luxir`, a copy of `conf_ecommerce_events` with these changes (geonames:
  `conf_geonames_luxir`, see [Geonames](#geonames)):
  - `string`, `pfloat`, `plong` and `pdate` fields switched to `LuxirStrField`, `LuxirFloatPointField`,
    `LuxirLongPointField` and `LuxirDatePointField`
  - `LuxirCodecFactory` as the codec
  - Luxir query, facet and facet-module components
  - `LuxirUpdateRequestHandler` on `/update`, and on `/update/json/docs` (where solr-bench posts), with Solr's
    invariants for that path (`update.contentType=application/json`, `json.command=false`)
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
  suites/results/stress-facets-local-100m/79b23df58daac14b92cc35f23b8b81f72098b4ba \
  suites/results/luxir-stress-facets-local-100m/31ae830a4e8cef8968769d4a9e3281562668b6c1 Solr+Lucene Solr+Luxir
python3 luxir-bench/compare.py \
  suites/results/geonames-local/79b23df58daac14b92cc35f23b8b81f72098b4ba \
  suites/results/luxir-geonames-local/35d1e2b3871017184e90db8349c67801f898c519 Solr+Lucene Solr+Luxir
```

What the fields mean:

- **Indexing:** `task1[0].total-time`, in seconds.
- **Restarts:** `task2[*].total-time`, in seconds. Each covers stopping the node, starting it, and waiting for its
  replicas to recover.
- **Queries:** `task3` to `task6` (one per query type; geonames: `task3` to `task20`), each with `timings`: one entry
  per thread count in the task's `threads` (here just 16). Each has `qps` (queries per second over the whole run,
  warm-up included), and the latency percentiles `50th`, `90th`, `95th`, `99th` and `mean` in milliseconds, measured
  over the queries after the warm-up. An entry with `total-errors` counts failed queries. `compare.py` labels them by the task's description from `config.json`.

How to read them:

- **Throughput and latency together.** With 16 concurrent clients and no rate cap, Solr is fully loaded, so a system
  that does more work per query shows it in both lower throughput and higher latencies.
- **Look past the percentiles.** The results don't include per-query timings. A few very slow queries above p95 can
  move the mean a lot while the percentiles barely change, so compare the mean and the percentiles together.
- **Noise.** p95 can vary by several percent between identical runs. Repeat runs before trusting small differences.

## Geonames

The geonames workload from luxir-lucene (`bench/geonames`), as solr-bench suites: `suites/geonames-local.json`
(Solr+Lucene) and `suites/luxir-geonames-local.json` (Solr+Luxir). Build, dataset and run steps are above.

- **Data:** 11,396,503 places from GeoNames (the `documents-2.json.bz2` corpus of the Rally and
  OpenSearch Benchmark geonames track), with text, string, numeric and location fields. Every text
  field is copied to a `_raw` string field and to the catch-all `_text_`.
- **Collection:** 3 shards on 3 nodes, one replica each.
- **Indexing:** 16 client threads, batches of 10,000 documents.
- **Restarts:** each node once, after indexing.
- **Queries:** luxir-lucene's 212 requests in 17 categories, one task per category, then all 212
  mixed. Each task runs for 15 seconds (the mixed one for 30) from 16 concurrent clients, sent to
  one node as POSTs (the terms-set requests are about 740 KB each). Rows are 10 and counts exact.

| Category | Requests | What it does |
|---|---|---|
| MatchAll | 1 | `*:*` |
| StringTerm | 20 | a term on a string field (`country_code_raw`) |
| TextTerm | 30 | a term on a text field (`name`) |
| TextPhrase | 30 | a two-word phrase on `name` |
| TextOr | 20 | two terms on `name`, either |
| TextAnd | 20 | two terms on `name`, both |
| CatchAllText | 20 | a term on the catch-all `_text_` |
| TextFiltered | 20 | a term on `name`, filtered on `feature_class_raw` |
| NumRange | 10 | a `population` range |
| SortPopulation | 2 | all docs sorted by `population` |
| SortGeonameid | 2 | all docs sorted by `geonameid` |
| TermSortPop | 10 | a `country_code_raw` term sorted by `population` |
| CountryFacet | 9 | terms facet on `country_code_raw` with `sum(population)` |
| HiCardFacet | 3 | terms facet on `geonameid`, limit 50,000 |
| TermsPure | 5 | a `{!terms}` set of about 45,700 names |
| TermsFiltered | 5 | a term query filtered by the `{!terms}` set |
| TermsProhibited | 5 | a term query excluding the `{!terms}` set |

**Configsets:** `conf_geonames` and `conf_geonames_luxir` share luxir-lucene's geonames schema.
The Luxir one uses Luxir field types, codec and components, keeping `alternatenames_raw` (values
over 255 bytes) on a stock string field. Both have the same `solrconfig.xml` apart from the codec
and components. They add the update log and commit settings of the e-commerce configsets (hard
commit every 30 s, soft commit every 15 s), and a 128 MB RAM buffer. Unlike luxir-lucene's own
benchmark, the Luxir side gets no 4 GB RAM buffer or parallel flush, and the indexes are not merged
to one segment.

**solr-bench changes for these suites:**

- **`http-method` for query tasks:** `POST` sends URL-parameter queries in the request body, for
  requests too long for a URL.
- **URL-parameter queries work again:** their responses are now read as a stream, as JSON queries'
  are. Before, every such query failed with `NullPointerException: inputStream`.
- **No throughput cap for fast queries:** with 10 requests pending per client thread, the
  submitter waited 100 ms before sending more, which capped any task at about 1,600 queries/s.
  It now waits 1 ms. The e-commerce suites stayed under the cap (at most about 500 queries/s), so
  their results are unaffected.

## Known caveats

- **Security manager.** Solr+Luxir needs Solr's security manager off (`SOLR_SECURITY_MANAGER_ENABLED=false`) so the
  native library can load, and since 2026-10-25 the Solr+Lucene suites turn it off too. Earlier results had it on
  for Solr+Lucene only, which was not a small advantage: every update-log write checks a permission with a stack walk
  under the log's lock, which kept Solr+Lucene's indexing to about 10 busy cores. With it off, Solr+Lucene indexed
  100M documents in 331.9 s instead of 684.3 s, and answered geonames' fast queries 23–36% faster. The
  [results](#results) show Solr+Lucene both ways.
- **Date parsing.** The e-commerce configsets parse `event_time` (`2019-10-01 00:00:00 UTC`) with Solr's
  `ParseDateFieldUpdateProcessorFactory`, which tries its 9 formats in order and throws an exception for each format
  that does not match: this value matches the 8th. That was about 45% of the indexing CPU on both systems. Solr+Luxir's
  JSON loader parses the dates of Luxir date fields itself (`LuxirDateValues`, Solr `31ae830`), with the processor's
  own code and the first format that matches values of the same shape, so the processor gets a parsed date and nothing
  throws. The dates are identical (all 3.9M distinct values in the first 100M events were checked). This is most of
  Solr+Luxir's indexing lead on this workload: without it, Solr+Luxir indexed in 320.5 s (1.04×). The same change in
  Solr's processor would give Solr+Lucene the same saving.
- **Indexing client.** solr-bench routes each document to its shard on one thread. Until 2026-10-25 it parsed every
  line in full to find the id and ran a regex compiled per line, which capped indexing at about 260,000 docs/s for any
  server; it now reads the id directly. Earlier Solr+Luxir indexing results were partly limited by the client.
- **JVM metrics.** Solr 10+ serves its metrics only in Prometheus format. solr-bench reads both that and the older
  JSON format, so the suites' JVM metrics (`metrics.json`) and the heap after each restart (`heap-mb` in
  `results.json`) work on both Solr 9 and Solr 10/11. A sample taken while a node is restarting is recorded as `-1`.
- **Dataset density.** The synthetic events fall in the same Oct–Nov 2019 window as the real ones, so the first 100M
  events of the 150M file cover a shorter span of time than the first 100M real events did.

## Results

One run of each suite on the machine below, comparing three setups:

- **Stock Solr+Lucene:** Apache Solr `79b23df` as it starts by default, with Solr's security manager on. Run on
  2026-10-24 with solr-bench before `3ae58b3`, whose client capped indexing at about 260,000 docs/s; stock
  Solr+Lucene indexed well below that.
- **Solr+Lucene, SM=off:** the same build with the security manager off (`SOLR_SECURITY_MANAGER_ENABLED=false`), as
  Solr+Luxir must run. Run on 2026-10-25.
- **Solr+Luxir:** the versions in [Get the code](#1-get-the-code), security manager off. Run on 2026-10-25.

Ratios are how much better Solr+Luxir is than each Solr+Lucene setup: its time ÷ Solr+Luxir's for indexing and total
time, Solr+Luxir's throughput ÷ its own for queries, so above 1× means Solr+Luxir was faster. Throughput counts each
task's warm-up queries over its whole run; latencies are over the measured queries after them. Restart times include
waiting for replicas to recover.

| | |
|---|---|
| CPU | AMD Ryzen 9 7950X: 16 cores / 32 threads, up to 5.88 GHz, 64 MB L3, one socket |
| Memory | 128 GB DDR5 (2 × 64 GB at 6000 MT/s, non-ECC); 124 GiB usable |
| Disk | WD_BLACK SN8100 4 TB NVMe SSD, ext4. It holds the datasets, the Solr nodes and their indexes. |
| OS | Ubuntu 22.04.5 LTS, Linux 6.8.0-138-generic, transparent huge pages `madvise` |
| Solr+Luxir | native library built on the machine with `-DLUXIR_CPU_TARGET=native`; `OMP_NUM_THREADS=1` |
| JDK | Oracle JDK 22.0.2, for both Solr and the solr-bench client |
| Solr nodes | 3 on the same machine, each with `-m 16g -Dsolr.searchThreads=4` |
| Client | solr-bench (`java -Xmx12g`) on the same machine: 16 indexing threads, 16 query threads with no rate cap |

### E-commerce, 100M documents

All three runs indexed exactly 100,000,000 documents. The stock runs of both systems had identical per-shard counts
(33,331,737 / 33,333,346 / 33,334,917); for the current builds, 20M-document indexes of both systems gave identical
results for 120 terms, range and product facet requests and for the hourly counts of `event_time`.

| | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|---|---|---|---|---|
| Indexing 100M documents | 684.3 s | 331.9 s | 179.0 s | **3.82×** | **1.85×** |
| Terms facet (6,000 queries) | 129.2 q/s | 130.1 q/s | 278.9 q/s | **2.16×** | **2.14×** |
| Range facet (6,000) | 170.0 q/s | 162.6 q/s | 677.2 q/s | **3.98×** | **4.16×** |
| Product facet (6,000) | 499.0 q/s | 434.8 q/s | 537.5 q/s | **1.08×** | **1.24×** |
| Join (100) | 2.4 q/s | 2.2 q/s | 13.7 q/s | **5.75×** | **6.34×** |
| All four query tasks, total time | 137.2 s | 144.8 s | 49.2 s | **2.79×** | **2.94×** |
| Node restarts | 5.87, 5.81, 5.77 s | 5.84, 5.87, 5.78 s | 5.85, 5.86, 5.79 s | same | same |

Latencies, p50 / p95 / p99 (ms):

| Query task | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir |
|---|---|---|---|
| Terms facet | 145.7 / 217.7 / 254.1 | 144.0 / 215.2 / 259.2 | 65.1 / 98.1 / 113.9 |
| Range facet | 107.7 / 162.2 / 187.5 | 114.4 / 170.3 / 198.7 | 25.8 / 43.7 / 55.0 |
| Product facet | 37.2 / 53.1 / 64.0 | 43.8 / 61.9 / 70.2 | 34.3 / 49.9 / 58.1 |
| Join | 6,937 / 8,507 / 9,598 | 6,350 / 21,289 / 21,968 | 1,416 / 1,976 / 2,030 |

- **Indexing:** the security manager halved Solr+Lucene's indexing speed (684.3 s against 331.9 s). Of Solr+Luxir's
  remaining 1.85×, most comes from parsing dates in its JSON loader (see [Known caveats](#known-caveats)): without
  that, Solr+Luxir indexed in 320.5 s (1.04×), and the same change in Solr's date processor would give Solr+Lucene the
  same saving.
- **Queries:** the security manager hardly affects these heavy queries. Solr+Luxir handled 2.1× the terms facet
  queries, 4.0–4.2× the range facet ones and 5.8–6.3× the joins (`LuxirJoinQParserPlugin` runs joins between string
  fields natively), with lower latency at every percentile. The product facet, once Solr+Luxir's weak spot (0.55–0.58×
  before the [change](#the-product-facet) that hands each query's matches to the facets as a doc list), is 1.08–1.24×.
- **Run to run:** Solr+Lucene with SM=off had a 13% lower product facet throughput and a much longer join tail than
  stock, which the security manager cannot explain; these are single runs. A run of Solr+Luxir at `35d1e2b` (without
  the date change) the same day gave 280.6, 730.0, 552.2 and 14.5 queries/s for the four tasks, 1–8% above this one.

JVM metrics, sampled every 2 seconds (plus the time each sample takes) on each of the 3 nodes over the whole run:

| | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir |
|---|---|---|---|
| Peak heap usage (of 16 GB) | 0.89–0.91 | 0.89–0.91 | 0.89–0.91 |
| Mean heap usage | 0.44–0.46 | 0.43–0.47 | 0.40–0.46 |
| Threads per node | 47–143 | 46–135 | 46–148 |
| Heap right after a restart (average) | 220 MB | 200 MB | 211 MB |

### Geonames, 11.4M documents

The [geonames](#geonames) suites, with Solr+Luxir at `35d1e2b`.

| | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|---|---|---|---|---|
| Indexing 11.4M documents | 83.5 s | 49.2 s | 38.6 s | **2.16×** | **1.27×** |
| Node restarts | 5.83, 5.82, 5.83 s | 5.85, 5.86, 5.82 s | 9.93, 5.79, 5.94 s | | |

Queries, 16 threads, throughput and p99:

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|---|---|---|---|---|
| MatchAll* | 245 q/s, 99.0 ms | 244 q/s, 98.0 ms | 247 q/s, 96.6 ms | *1.01×* | *1.01×* |
| StringTerm | 8,548 q/s, 7.06 ms | 10,501 q/s, 6.33 ms | 10,454 q/s, 6.76 ms | **1.22×** | **1.00×** |
| TextTerm | 7,959 q/s, 3.48 ms | 10,756 q/s, 3.08 ms | 11,412 q/s, 2.35 ms | **1.43×** | **1.06×** |
| TextPhrase | 8,092 q/s, 3.64 ms | 10,394 q/s, 3.10 ms | 11,305 q/s, 3.05 ms | **1.40×** | **1.09×** |
| TextOr | 5,191 q/s, 5.61 ms | 5,642 q/s, 5.32 ms | 9,308 q/s, 2.76 ms | **1.79×** | **1.65×** |
| TextAnd | 8,137 q/s, 3.13 ms | 10,949 q/s, 2.32 ms | 11,190 q/s, 2.22 ms | **1.38×** | **1.02×** |
| CatchAllText | 7,694 q/s, 3.76 ms | 10,450 q/s, 3.13 ms | 11,006 q/s, 2.10 ms | **1.43×** | **1.05×** |
| TextFiltered | 7,889 q/s, 3.51 ms | 10,489 q/s, 2.94 ms | 10,341 q/s, 2.73 ms | **1.31×** | **0.99×** |
| NumRange | 1,575 q/s, 58.7 ms | 1,592 q/s, 60.3 ms | 9,987 q/s, 2.75 ms | **6.34×** | **6.27×** |
| SortPopulation | 144 q/s, 151.7 ms | 143 q/s, 155.4 ms | 349 q/s, 65.8 ms | **2.43×** | **2.44×** |
| SortGeonameid | 144 q/s, 155.5 ms | 167 q/s, 134.1 ms | 349 q/s, 64.5 ms | **2.41×** | **2.08×** |
| TermSortPop | 6,954 q/s, 3.64 ms | 9,354 q/s, 2.80 ms | 8,287 q/s, 2.92 ms | **1.19×** | **0.89×** |
| CountryFacet | 179 q/s, 350.7 ms | 180 q/s, 343.9 ms | 409 q/s, 182.2 ms | **2.29×** | **2.27×** |
| HiCardFacet | 10.9 q/s, 2,551 ms | 10.9 q/s, 2,552 ms | 11.2 q/s, 1,804 ms | **1.03×** | **1.03×** |
| TermsPure | 53.2 q/s, 349.0 ms | 51.5 q/s, 372.6 ms | 49.7 q/s, 383.5 ms | **0.93×** | **0.96×** |
| TermsFiltered | 102 q/s, 188.3 ms | 103 q/s, 174.1 ms | 103 q/s, 179.9 ms | **1.01×** | **1.01×** |
| TermsProhibited | 56.5 q/s, 331.5 ms | 54.3 q/s, 355.1 ms | 50.6 q/s, 370.7 ms | **0.90×** | **0.93×** |
| All 212, mixed (30 s) | 421 q/s, 432.3 ms | 427 q/s, 413.3 ms | 419 q/s, 554.4 ms | **0.99×** | **0.98×** |

\* Not settled: across six runs on these and earlier builds, MatchAll has given 0.76× to 1.36×, with Solr+Lucene
between 197 and 280 q/s and Solr+Luxir between 213 and 268 q/s.

- **Indexing:** 2.16× faster than stock Solr+Lucene, 1.27× with its security manager off. Geonames has no dates, so
  this is Luxir's own indexing.
- **What the security manager hid:** with it off, Solr+Lucene answers 23–36% more StringTerm, TermSortPop and text
  requests per second (two-term OR: 9%). Against stock, Solr+Luxir is 1.2–1.4× faster on these; against SM=off, they
  are about even, and TermSortPop is 0.89× (see [the changes](#a-term-sorted-by-a-field-termsortpop)).
- **Faster on Solr+Luxir either way:** numeric ranges (6.3× throughput, 22× lower p99), sorting all docs
  (2.1–2.4×), the country facet (2.3×) and two-term OR (1.65–1.79×).
- **Even or slower either way:** the `{!terms}` sets of 45,700 names (0.90–1.01×), the same weak spot as in
  luxir-lucene's own results, and the 30-second mix of all 212 requests (0.98–0.99×), whose time the `{!terms}`
  requests, 15 of 212 but by far the slowest, dominate.
- **Errors:** one TextTerm request of 161,389 failed on Solr+Lucene with SM=off: the node it was sent to got an
  `EOFException` reading shard2's response. None failed in the other runs.
- **Heap:** peak usage was 0.80–0.93 of 16 GB on stock Solr+Lucene, 0.79–0.92 with SM=off and 0.77–0.86 on
  Solr+Luxir. Solr+Luxir's first restart is the slow one in every run (9.9 s here).

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

### The product facet

Those changes still left the product facet at 0.58× Solr+Lucene's throughput. With 16 clients, Solr+Luxir used twice
Solr+Lucene's CPU per request (106 ms against 53), though a single client's requests cost the same: the cost was
memory traffic, which grows with concurrency. Each request's matches, about 67,000 docs per shard, were passed from
the query to each facet as a bitset of all 33M docs (4 MB per shard), built, copied and scanned about four times.

How each effect was measured, on the 7950X: the benchmark's product facet queries from 16 clients on a 3-node cluster
with the 100M index (Solr+Lucene: 514 queries/s), and for the GC change, geonames TermSortPop requests (see
[below](#a-term-sorted-by-a-field-termsortpop)).

| Change | Where | Without → with |
|---|---|---|
| Hand matches fewer than one doc in 64 from the query to the facets as sorted doc ids (Solr's `SortedIntDocSet`, as Solr's own collector keeps a small set), and let Luxir's facet collection take a segment's matches as a doc list | luxir-lucene `d78c3df` (`DocMatches`, `lxl_facet_collect`, `lxl_column_value_counts`), solr `5bad8a1` | product facet 322 → 539 queries/s, CPU per request 93 → 55 ms; in the benchmark, the range facet (same matches) went from 2.69× to 4.04× Solr+Lucene's throughput |
| Free native objects with `NativeCleaner` instead of `java.lang.ref.Cleaner`, whose registrations form one linked list that young GCs walk serially before JDK 24 | luxir-lucene `d78c3df` | young GC pauses 96 → 18 ms (Solr+Lucene: 3 ms) |

The results match Solr+Lucene's: the counts and facets of 120 product, range and terms facet queries were
identical, and the luxir-lucene tests compare facets over doc lists and over bitsets.

### A term sorted by a field (TermSortPop)

Before luxir-lucene `d78c3df`, TermSortPop (a `country_code_raw` term sorted by `population`) was the
one category clearly slower on Solr+Luxir: 6,184 q/s against stock Solr+Lucene's 7,200 (0.86×). On a test cluster under
the same 16-client load, Solr+Luxir used 3.87 CPU-ms per request against 3.03.

**Causes.**

- **Match bits per segment:** a field sort ran the query into a bitset of every segment's docs,
  allocated and zeroed per request, then scanned each bitset for the segment's best docs by the
  column.
- **GC pauses:** native objects (terms and postings enums, doc values iterators, stored fields
  readers) were freed by `java.lang.ref.Cleaner`. Before JDK 24, its registrations form one linked
  list, which young GCs walk serially: Solr+Luxir's pauses took about 96 ms against 3 ms on
  Solr+Lucene, with the other GC threads spinning.
- **Doc values per returned doc:** every doc values iterator opened a native object, with a cleaner
  registration, even to read one doc's value.

**Fix (luxir-lucene `d78c3df`).**

- **Sorted without bits:** without facets, each segment's best k by the sort column are kept as the
  query finds its matches (`lxl_multi_top_k_sorted`), with the column's block zones pruning docs that
  cannot make it.
- **Cleaner:** native objects are freed by `NativeCleaner`, which holds its registrations in a
  concurrent set that GC threads scan in parallel. Young GC pauses fell from about 96 ms to 18 ms.
- **Doc values:** an iterator reads its first block with a one-shot native call and opens a native
  iterator only for a second block.

On the test cluster, CPU per request fell to 2.7 ms (Solr+Lucene: 3.0). The other categories are the
same or faster than before the fix. That comparison had Solr+Lucene's security manager on; with it off, as in the
results above, Solr+Lucene answers TermSortPop at 9,354 q/s and Solr+Luxir at 8,287 (0.89×), so it is again the
category where Solr+Luxir trails. Sorted requests match Solr+Lucene's order, and luxir-lucene's
tests compare both sort paths with Lucene's.

### Fixed: catch-all text missed documents

Before benchmarking, both systems' indexes were loaded with the same data (in separate test
clusters), and all 212 requests compared with `luxir-bench/geonames-verify.py`. With luxir-lucene
`57f953d`, everything matched except CatchAllText: 8 of its 20 requests returned fewer documents on
Solr+Luxir, for example `_text_:creek` 229,122 against 242,460 and `_text_:hammam` 498 against 532.
On the same index, Luxir's Java path (`luxirCodec=false`) returned the full counts.

**Cause.** A text field whose name is not a valid Luxir schema name (it must start with a letter,
as `_text_` does not) was stored under two names:

- **Flush:** `NativeIndexer` wrote it under `LuxirTextField.schemaName`, here `lx5f746578745f`.
- **Merge:** `lxl_writer_merge_field` wrote it under its own name, `_text_`.
- **One segment:** `findField` tries both names, so a search of one segment found the field
  either way.
- **Many segments:** one native call over all segments (`lxl_multi_top_k`) resolves the field name
  once for the whole index. That picked `_text_` when any segment had it, so the search found
  nothing in the flushed segments.

`name`, `asciiname` and the other fields are valid schema names, so both paths stored them under
the same name. On an index merged to one segment, which is what luxir-lucene's own geonames check
used, there is only one name, so the bug didn't show there. It was not new: it showed with upstream
Luxir `8cb622ba` without the four patches, and with the luxir-lucene and Solr module builds from
before the faster filters and native joins.

**Fix (luxir-lucene `39eedb6`).**

- **One name:** merges, and text written through Lucene's own inverter, now store text fields under
  the schema name, as native flush does.
- **Indexes written before the fix:** these mix both names. A search over a field stored under
  both names now runs through Lucene, which gets the right count, until merges rewrite the
  segments.
- **Test:** `TestNativeIndexing` covers `_text_` searched natively across flushed and merged
  segments. It fails without the fix.

**Checks after the fix.**

- **Index written before the fix:** `_text_:creek` returns 242,460, through Lucene. Other fields
  still run natively.
- **New index with flushed and merged segments:** `_text_` runs natively, and all 212 requests
  match Solr+Lucene (counts, facets and sort values) and Luxir's Java path (top rows).
- **Indexing speed:** unchanged. The results above are with the fix.

### Indexing

Made on 2026-10-25, after the security manager was turned off for Solr+Lucene too. Measured by indexing the first
20M events (and geonames' 11.4M places) into 3-shard test clusters of each system, one shard per node, from the
benchmark's client.

| Change | Where | Without → with |
|---|---|---|
| Route documents in the client without parsing each line in full (it capped both systems at about 260,000 docs/s) | solr-bench `3ae58b3` | 20M events: Solr+Lucene 77.0 → 70.5 s, Solr+Luxir 76.3 → 66.4 s; geonames: Solr+Luxir 44.1 → 38.1 s |
| Use the module's JSON loader on `/update/json/docs`, where solr-bench posts, and let it read unquoted words (the data has `"brand": Infinity`) as Solr's parser does | solr `35d1e2b`, solr-bench `b08842c` (configsets) | geonames: 48.4 → 45.6 s |
| Postings: per term, scan and clear only the norm slots its impacts use instead of four 256-slot arrays; merge single-doc terms without decoding them; field attributes looked up once per segment | luxir `173ec324`, luxir-lucene `ecd09a1` | geonames: 45.6 → 43.1–44.5 s; flush CPU −43%, merge CPU −29% |
| Parse dates of Luxir date fields in the JSON loader, with Solr's own formats, instead of in Solr's date processor, which throws an exception per format that does not match | solr `31ae830` (`LuxirDateValues`) | 20M events: 66.4 → 36–40 s, CPU 1,094 → 601–698 CPU-s |

The geonames rows before the client change were limited by the client, so they show CPU saved more than time. Each
change gives the same results: the dates of all 3.9M distinct `event_time` values in the first 100M events match
Solr's processor, both systems' 20M-event indexes gave identical results for 120 facet requests, the geonames
indexes passed all 212 requests of `luxir-bench/geonames-verify.py`, and the luxir-lucene and Solr module test suites
pass, as do Luxir's apart from one replication test that fails before these changes too.
