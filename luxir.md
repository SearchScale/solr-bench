# Solr+Lucene vs Solr+Luxir benchmarks

This guide runs the same SolrCloud workloads on one machine with:

- **Solr+Lucene**: stock Apache Solr, storing and searching its index with Lucene's own codecs.
- **Solr+Luxir**: the `luxir-codec` branch of [SearchScale/solr](https://github.com/SearchScale/solr), whose
  `luxir-codec` module stores Luxir field types in Luxir's native segment format and runs queries and facets natively
  through `libluxir_lucene.so`.

Each workload indexes into a 3-node, 3-shard collection (one replica per shard) from 16 client threads, then runs its
queries from 16 concurrent clients with no rate cap:

| Workload | Data | Queries | Suites (Solr+Lucene, Solr+Luxir) |
|---|---|---|---|
| E-commerce | the first 100M events of `ecommerce-events-150m.json.gz`: the real 110M-event dataset plus synthetic events that follow its patterns | terms, range and product facets over 7-day ranges (6,000 each), then joins on `user_session` (100) | `stress-facets-local-100m.json`, `luxir-stress-facets-local-100m.json` |
| Geonames | 11.4M places from the Rally/OpenSearch Benchmark geonames corpus | luxir-lucene's 212 requests in 17 categories, 15 s per category, then all mixed for 30 s | `geonames-local.json`, `luxir-geonames-local.json` |
| Enwiki | the first 25M 1 KB Wikipedia chunks of lucene-bench's `enwiki-20120502-lines-1k.txt.lzma` | luceneutil's wikimedium tasks as JSON requests (`luxir-bench/enwiki-queries.py`): up to 30 per category, each category 100 times over, then all 1,153 mixed 10 times over | `enwiki-local.json`, `luxir-enwiki-native-local.json` |

Jump to: [Benchmarks](#benchmarks) · [Run it yourself](#run-it-yourself) ·
[How Solr+Luxir got here](#how-solrluxir-got-here)

## Benchmarks

One run of each suite, comparing:

- **Stock Solr+Lucene:** Apache Solr `79b23df` as it starts by default, security manager on.
- **Solr+Lucene, SM=off:** the same build with the security manager off.
- **Solr+Luxir:** the versions in [Get the code](#1-get-the-code), security manager off.

Ratios are how much faster Solr+Luxir is (above 1× means faster). Query cells give throughput and p99. The headline
under each workload compares Solr+Luxir with Solr+Lucene, SM=off.

| | |
|---|---|
| CPU | AMD Ryzen 9 7950X: 16 cores / 32 threads, up to 5.88 GHz, 64 MB L3 |
| Memory | 128 GB DDR5 |
| Disk | WD_BLACK SN8100 4 TB NVMe SSD, ext4 |
| OS / JDK | Ubuntu 22.04.5, Linux 6.8.0-138-generic; Oracle JDK 22.0.2 |
| Solr nodes | 3 on the same machine, each with `-m 16g -Dsolr.searchThreads=4` |
| Client | solr-bench (`java -Xmx12g`) on the same machine |

### E-commerce, 100M documents

**Solr+Luxir indexes 1.86× faster and answers the facet and join queries 1.15–6.0× faster.**

| | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|---|---|---|---|---|
| Indexing | 684.3 s | 331.9 s | 178.4 s | **3.84×** | **1.86×** |
| Terms facet | 129 q/s, 254 ms | 130 q/s, 259 ms | 278 q/s, 114 ms | **2.15×** | **2.14×** |
| Range facet | 170 q/s, 188 ms | 163 q/s, 199 ms | 644 q/s, 57 ms | **3.79×** | **3.95×** |
| Product facet | 499 q/s, 64 ms | 435 q/s, 70 ms | 502 q/s, 61 ms | **1.01×** | **1.15×** |
| Join | 2.4 q/s, 9,598 ms | 2.2 q/s, 21,968 ms | 13.1 q/s, 2,315 ms | **5.48×** | **5.98×** |
| All four query tasks, total time | 137.2 s | 144.8 s | 50.9 s | **2.69×** | **2.84×** |

All three runs indexed exactly 100,000,000 documents, and 20M-document indexes of both systems gave identical results
for 120 facet requests. Most of Solr+Luxir's indexing lead over SM=off comes from parsing dates in its JSON
loader instead of Solr's date processor (without it, 1.04×). Native joins between string fields (`LuxirJoinQParserPlugin`) make the joins 5.5–6.0×
faster.

### Geonames, 11.4M documents

**Solr+Luxir indexes 1.27× faster, but into a 1.76× larger index. Ranges, sorts and facets are 2.3–6.7× faster; text
queries are 1.01–1.09× faster, apart from two-term OR at 1.63×.**

| | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|---|---|---|---|---|
| Indexing | 80.4 s | 48.9 s | 38.6 s | **2.08×** | **1.27×** |
| Index size after indexing | 4.61 GB, 57 segments | 4.40 GB, 50 segments | 7.75 GB, 95 segments | 1.68× larger | 1.76× larger |

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|---|---|---|---|---|
| MatchAll* | 244 q/s, 97.3 ms | 269 q/s, 94.0 ms | 271 q/s, 91.3 ms | *1.11×* | *1.01×* |
| StringTerm | 8,557 q/s, 6.39 ms | 10,511 q/s, 6.64 ms | 10,958 q/s, 6.65 ms | **1.28×** | **1.04×** |
| TextTerm | 8,004 q/s, 3.51 ms | 10,920 q/s, 2.80 ms | 11,613 q/s, 2.46 ms | **1.45×** | **1.06×** |
| TextPhrase | 8,150 q/s, 3.58 ms | 10,529 q/s, 3.03 ms | 11,503 q/s, 3.04 ms | **1.41×** | **1.09×** |
| TextOr | 5,301 q/s, 5.47 ms | 5,879 q/s, 5.05 ms | 9,580 q/s, 2.71 ms | **1.81×** | **1.63×** |
| TextAnd | 8,212 q/s, 3.11 ms | 11,096 q/s, 2.32 ms | 11,578 q/s, 2.11 ms | **1.41×** | **1.04×** |
| CatchAllText | 7,757 q/s, 3.64 ms | 10,649 q/s, 3.01 ms | 11,362 q/s, 2.03 ms | **1.46×** | **1.07×** |
| TextFiltered | 7,925 q/s, 3.52 ms | 10,615 q/s, 2.88 ms | 10,722 q/s, 2.64 ms | **1.35×** | **1.01×** |
| NumRange | 1,635 q/s, 56.1 ms | 1,624 q/s, 59.4 ms | 10,925 q/s, 2.35 ms | **6.68×** | **6.73×** |
| SortPopulation | 144 q/s, 151.2 ms | 143 q/s, 155.1 ms | 386 q/s, 60.5 ms | **2.68×** | **2.70×** |
| SortGeonameid | 157 q/s, 137.2 ms | 156 q/s, 140.6 ms | 384 q/s, 58.7 ms | **2.45×** | **2.46×** |
| TermSortPop | 7,189 q/s, 3.59 ms | 9,378 q/s, 2.81 ms | 8,567 q/s, 2.84 ms | **1.19×** | **0.91×** |
| CountryFacet | 182 q/s, 337.3 ms | 181 q/s, 333.3 ms | 422 q/s, 174.5 ms | **2.32×** | **2.33×** |
| HiCardFacet | 11.1 q/s, 2,347 ms | 10.9 q/s, 2,611 ms | 12.5 q/s, 1,720 ms | **1.13×** | **1.15×** |
| TermsPure | 54.4 q/s, 353.3 ms | 54.6 q/s, 353.7 ms | 52.4 q/s, 393.3 ms | **0.96×** | **0.96×** |
| TermsFiltered | 102 q/s, 182.7 ms | 103 q/s, 172.6 ms | 103 q/s, 177.1 ms | **1.01×** | **1.00×** |
| TermsProhibited | 57.5 q/s, 331.9 ms | 57.5 q/s, 329.6 ms | 54.0 q/s, 342.1 ms | **0.94×** | **0.94×** |
| All 212, mixed (30 s) | 427 q/s, 429.4 ms | 434 q/s, 400.4 ms | 444 q/s, 527.3 ms | **1.04×** | **1.02×** |

\* Not settled: across seven runs, MatchAll has given 0.76× to 1.36×.

All three runs indexed 11,396,503 documents. One StringTerm request of 164,513 failed on Solr+Luxir, as one did on
Solr+Lucene with SM=off: a shard's response was cut short (`EOFException`). Solr+Luxir is slower only on TermSortPop
(0.91×) and on the `{!terms}` sets of 45,700 names (0.94–1.00×), which also dominate the time of the mixed task and its
p99.

### Enwiki, 25M documents

**Solr+Luxir indexes 1.51× faster and runs the full query mix 1.75× faster, but its index is 1.22× larger, and lower-frequency phrases and spans, conjunctions of a frequent term with a rarer one, and prefix queries are slower.**

| | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|---|---|---|---|---|
| Indexing | 210.6 s | 133.1 s | 88.4 s | **2.38×** | **1.51×** |
| Index size after indexing | same as SM=off | 10.60 GB, 62 segments | 12.94 GB, 74 segments |  | 1.22× larger |

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|---|---|---|---|---|
| HighTerm | 607 q/s, 59.3 ms | 606 q/s, 57.1 ms | 1,572 q/s, 23.9 ms | **2.59×** | **2.59×** |
| MedTerm | 1,912 q/s, 16.7 ms | 1,902 q/s, 19.4 ms | 2,861 q/s, 17.7 ms | **1.50×** | **1.50×** |
| LowTerm | 3,412 q/s, 10.1 ms | 3,741 q/s, 9.1 ms | 2,965 q/s, 10.8 ms | **0.87×** | **0.79×** |
| AndHighHigh | 1,051 q/s, 48.4 ms | 1,015 q/s, 48.7 ms | 1,339 q/s, 26.9 ms | **1.27×** | **1.32×** |
| AndHighMed | 3,507 q/s, 9.1 ms | 3,536 q/s, 9.0 ms | 2,740 q/s, 10.7 ms | **0.78×** | **0.77×** |
| AndHighLow | 5,771 q/s, 7.7 ms | 6,146 q/s, 7.0 ms | 6,222 q/s, 6.09 ms | **1.08×** | **1.01×** |
| OrHighHigh | 373 q/s, 85.2 ms | 365 q/s, 87.3 ms | 1,596 q/s, 17.7 ms | **4.28×** | **4.37×** |
| OrHighMed | 543 q/s, 98.2 ms | 526 q/s, 101.1 ms | 2,858 q/s, 10.3 ms | **5.26×** | **5.43×** |
| OrHighLow | 719 q/s, 44.2 ms | 716 q/s, 44.4 ms | 6,840 q/s, 4.05 ms | **9.51×** | **9.55×** |
| OrHighNotHigh | 327 q/s, 128.9 ms | 319 q/s, 131.6 ms | 825 q/s, 53.6 ms | **2.52×** | **2.59×** |
| OrHighNotMed | 731 q/s, 57.7 ms | 707 q/s, 58.2 ms | 1,429 q/s, 29.3 ms | **1.96×** | **2.02×** |
| OrHighNotLow | 1,275 q/s, 23.6 ms | 1,174 q/s, 27.0 ms | 2,038 q/s, 15.1 ms | **1.60×** | **1.74×** |
| OrNotHighHigh | 435 q/s, 63.3 ms | 421 q/s, 65.5 ms | 1,115 q/s, 26.2 ms | **2.56×** | **2.65×** |
| OrNotHighMed | 1,697 q/s, 17.3 ms | 1,698 q/s, 17.5 ms | 3,206 q/s, 9.65 ms | **1.89×** | **1.89×** |
| OrNotHighLow | 6,516 q/s, 8.0 ms | 7,180 q/s, 7.3 ms | 7,249 q/s, 12.8 ms | **1.11×** | **1.01×** |
| HighPhrase | 218 q/s, 274.4 ms | 217 q/s, 284.7 ms | 266 q/s, 232.8 ms | **1.22×** | **1.23×** |
| MedPhrase | 753 q/s, 66.9 ms | 749 q/s, 68.2 ms | 636 q/s, 99.4 ms | **0.84×** | **0.85×** |
| LowPhrase | 845 q/s, 65.7 ms | 847 q/s, 67.0 ms | 627 q/s, 92.2 ms | **0.74×** | **0.74×** |
| HighSloppyPhrase | 144 q/s, 655.4 ms | 144 q/s, 653.3 ms | 157 q/s, 446.8 ms | **1.09×** | **1.09×** |
| MedSloppyPhrase | 435 q/s, 197.1 ms | 441 q/s, 194.0 ms | 352 q/s, 137.2 ms | **0.81×** | **0.80×** |
| LowSloppyPhrase | 909 q/s, 71.0 ms | 920 q/s, 71.1 ms | 628 q/s, 94.7 ms | **0.69×** | **0.68×** |
| HighSpanNear | 227 q/s, 355.9 ms | 233 q/s, 343.9 ms | 214 q/s, 492.0 ms | **0.94×** | **0.92×** |
| MedSpanNear | 776 q/s, 59.7 ms | 815 q/s, 58.6 ms | 640 q/s, 65.5 ms | **0.83×** | **0.79×** |
| LowSpanNear | 761 q/s, 83.1 ms | 802 q/s, 77.8 ms | 623 q/s, 92.3 ms | **0.82×** | **0.78×** |
| Prefix3 | 653 q/s, 92.0 ms | 626 q/s, 96.6 ms | 524 q/s, 217.1 ms | **0.80×** | **0.84×** |
| Wildcard | 598 q/s, 57.6 ms | 627 q/s, 54.2 ms | 673 q/s, 74.0 ms | **1.13×** | **1.07×** |
| Fuzzy1 | 728 q/s, 38.9 ms | 802 q/s, 39.6 ms | 761 q/s, 41.3 ms | **1.05×** | **0.95×** |
| Fuzzy2 | 644 q/s, 58.0 ms | 665 q/s, 55.8 ms | 534 q/s, 70.4 ms | **0.83×** | **0.80×** |
| IntNRQ | 131 q/s, 206.8 ms | 117 q/s, 231.7 ms | 1,017 q/s, 28.3 ms | **7.76×** | **8.69×** |
| IntSet | 1,478 q/s, 16.7 ms | 1,492 q/s, 17.7 ms | 3,363 q/s, 9.27 ms | **2.28×** | **2.25×** |
| PKLookup | 11,099 q/s, 3.3 ms | 15,947 q/s, 2.2 ms | 6,704 q/s, 7.16 ms | **0.60×** | **0.42×** |
| BM25MSM2 | 78 q/s, 631.3 ms | 77 q/s, 604.5 ms | 67.8 q/s, 359.1 ms | **0.87×** | **0.88×** |
| HighTermMonthSort | 953 q/s, 32.9 ms | 957 q/s, 33.1 ms | 1,554 q/s, 21.0 ms | **1.63×** | **1.62×** |
| HighTermDayOfYearSort | 1,050 q/s, 40.6 ms | 1,047 q/s, 41.1 ms | 1,377 q/s, 27.7 ms | **1.31×** | **1.32×** |
| HighTermTitleSort | 903 q/s, 43.5 ms | 899 q/s, 47.6 ms | 1,246 q/s, 28.0 ms | **1.38×** | **1.39×** |
| TermDateTimeSort | 784 q/s, 51.4 ms | 777 q/s, 55.4 ms | 1,503 q/s, 17.7 ms | **1.92×** | **1.93×** |
| BrowseMonthFacets | 30 q/s, 773.2 ms | 28 q/s, 750.6 ms | 37.1 q/s, 558.4 ms | **1.24×** | **1.32×** |
| BrowseDayOfYearFacets | 29 q/s, 687.8 ms | 28 q/s, 754.7 ms | 33.6 q/s, 584.4 ms | **1.16×** | **1.20×** |
| BrowseDateFacets | 25 q/s, 784.2 ms | 24 q/s, 810.0 ms | 34.4 q/s, 577.3 ms | **1.38×** | **1.43×** |
| MedTermDayFacets | 601 q/s, 54.2 ms | 599 q/s, 56.8 ms | 961 q/s, 39.8 ms | **1.60×** | **1.60×** |
| AndHighHighDayFacets | 203 q/s, 276.4 ms | 204 q/s, 274.2 ms | 501 q/s, 66.0 ms | **2.47×** | **2.45×** |
| AndHighMedDayFacets | 1,263 q/s, 26.8 ms | 1,276 q/s, 27.9 ms | 1,054 q/s, 32.3 ms | **0.83×** | **0.83×** |
| OrHighMedDayFacets | 132 q/s, 392.0 ms | 130 q/s, 397.3 ms | 475 q/s, 77.0 ms | **3.60×** | **3.66×** |
| All 1,153, mixed | 436 q/s, 226.1 ms | 432 q/s, 226.8 ms | 754 q/s, 174.2 ms | **1.73×** | **1.75×** |

All three runs indexed 25,000,000 documents with no failed request. Solr+Luxir analyzes text natively, not quite as
Solr does: 93 of the 1,153 requests found slightly different counts. It is much faster on disjunctions, numeric ranges
and sets, facets after an OR and the sorts. Sloppy phrases, ordered spans (`{!complexphrase}`), wildcards and fuzzy
queries run natively, with the same results as Lucene's code over the same index. Lower-frequency phrases and spans,
AndHighMed, Prefix3 and BM25MSM2 are slower. PKLookup and the other cheap categories finish their 3,000 queries in a
second or two, so their numbers mostly measure warm-up: in 50 times longer runs, PKLookup was 0.74×.

## Run it yourself

### What you need

| | |
|---|---|
| OS / CPU | Linux x86-64 |
| RAM | 64 GB or more. Each of the 3 Solr nodes gets a 16 GB heap, and Luxir reads its segments through the page cache. |
| Disk | About 40 GB for a dataset, the largest index and the Solr builds |
| JDK | 22 or later on the `PATH`, with `JAVA_HOME` set. Luxir's Java side uses the Foreign Function and Memory API. |
| Tools | `git`, `mvn`, `jq`, `curl`, `wget`, `lsof`, `pigz`, `python3` |
| Docker | With BuildKit (the `docker buildx` plugin), to build the native library in Luxir's dev container |

### 1. Get the code

Clone the three Luxir repositories side by side in one directory, `$LUXIR_ROOT`:

```bash
export LUXIR_ROOT=$HOME/solr-luxir
mkdir -p $LUXIR_ROOT && cd $LUXIR_ROOT
git clone --recurse-submodules -b luxir-lucene https://github.com/SearchScale/luxir.git  # Luxir plus the patches luxir-lucene needs
git clone https://github.com/SearchScale/luxir-lucene.git                   # Lucene codec + native C ABI
git clone -b luxir-codec https://github.com/SearchScale/solr.git            # Solr with the luxir-codec module
```

The benchmarks used these versions:

| Repository | Branch | Commit |
|---|---|---|
| luxir | `luxir-lucene` | `78f46a4c` (Luxir `609367c5` + the 7 patches in `luxir-lucene/luxir-patches/`) |
| luxir-lucene | `main` | `86e9752` |
| solr | `luxir-codec` (Apache Solr `79b23df` plus the module) | `31ae830a4e8cef8968769d4a9e3281562668b6c1` |

### 2. Build the native library

```bash
cd /path/to/solr-bench
luxir-bench/build-native.sh $LUXIR_ROOT
```

The script completes the Luxir checkout (its `deps/hpp-proto` submodule and FastPFOR), builds Luxir's dev image
(`luxir-dev:normal-deps`, about 6 GB and 20 minutes the first time), then builds `libluxir_lucene.so` in it with
`-DLUXIR_CPU_TARGET=native`, so build it on the machine that will run the benchmark. The library and the GCC 16
`libgomp.so.1` it needs go to `$LUXIR_ROOT/luxir/build/lux4j-release/bin/`. If `docker build` fails with `the --mount
option requires BuildKit`, install the [buildx plugin](https://github.com/docker/buildx#installing).

### 3. Build the luxir-lucene jar

```bash
cd $LUXIR_ROOT/luxir-lucene
./gradlew jar                                   # or: ./gradlew test jar, to also run its tests against the library
```

solr-bench builds Solr itself: it checks out the suite's commit and runs `../gradlew -Pluxir.lucene.jar=<jar> distTar`,
which bundles the jar into `modules/luxir-codec/lib`.

### 4. Build solr-bench and point the Solr+Luxir suites at your files

```bash
cd /path/to/solr-bench
mvn clean compile assembly:single
luxir-bench/configure-suites.sh $LUXIR_ROOT
```

`configure-suites.sh` sets the `.so` path in `SOLR_OPTS` and the jar path in the build command of every Solr+Luxir suite.

### 5. Run

```bash
cd /path/to/solr-bench
export JAVA_TOOL_OPTIONS="-Djava.net.preferIPv4Stack=true"   # if downloads hang on a broken IPv6 route

# e-commerce
./cleanup.sh && ./stress.sh -c 79b23df58daac14b92cc35f23b8b81f72098b4ba suites/stress-facets-local-100m.json        # Solr+Lucene
./cleanup.sh && ./stress.sh -c 31ae830a4e8cef8968769d4a9e3281562668b6c1 suites/luxir-stress-facets-local-100m.json  # Solr+Luxir

# geonames
./cleanup.sh && ./stress.sh -c 79b23df58daac14b92cc35f23b8b81f72098b4ba suites/geonames-local.json        # Solr+Lucene
./cleanup.sh && ./stress.sh -c 31ae830a4e8cef8968769d4a9e3281562668b6c1 suites/luxir-geonames-local.json  # Solr+Luxir

# enwiki
./cleanup.sh && ./stress.sh -c 79b23df58daac14b92cc35f23b8b81f72098b4ba suites/enwiki-local.json                # Solr+Lucene
./cleanup.sh && ./stress.sh -c 31ae830a4e8cef8968769d4a9e3281562668b6c1 suites/luxir-enwiki-native-local.json   # Solr+Luxir
```

- The suites download their datasets on the first run.
- Each run takes about 10 minutes after the first Gradle build of its commit. `luxir-codec` is Apache Solr `79b23df`
  plus the module, so `-c 79b23df` builds the same Solr for Solr+Lucene.
- The Solr+Lucene suites turn Solr's security manager off, as Solr+Luxir must. For stock Solr+Lucene, remove the
  `environment` entry from their `cluster` section.
- `patch` failures in the log are harmless. `cleanup.sh` kills anything on ports 50000–50050 and 2181.

**What the Solr+Luxir suites change.** Only the Solr build, the configset and the node environment; the workload is
identical. The configsets (`conf_ecommerce_events_luxir`, `conf_geonames_luxir`, `conf_enwiki_luxir_native`) are
copies of the Solr+Lucene ones with Luxir field types (`LuxirStrField`, the Luxir point fields and, for enwiki,
`LuxirTextField`), `LuxirCodecFactory`, Luxir's query, facet and join components, and `LuxirUpdateRequestHandler` on
`/update` and `/update/json/docs`. Fields Luxir can't hold (geonames' `alternatenames_raw`, over 255 bytes) and the
uniqueKey stay on Lucene's types. The nodes get:

```json
"environment": {
  "SOLR_MODULES": "luxir-codec",
  "OMP_NUM_THREADS": "1",
  "SOLR_SECURITY_MANAGER_ENABLED": "false",
  "SOLR_OPTS": "--enable-native-access=ALL-UNNAMED -Dluxir.lucene.library=/path/to/libluxir_lucene.so"
}
```

`OMP_NUM_THREADS=1` stops the library from starting an OpenMP thread team per query, which oversubscribes the CPU
under concurrency (at 32 clients it raised p99 from 508 ms to 3.1 s).

### 6. Check and compare

During a Solr+Luxir run, a request with `debug=true` reports whether it ran natively:

```bash
curl -s 'http://localhost:50000/solr/ecommerce-events/select?q=*:*&rows=0&debug=true' | tr -d ' \n' | grep -o '"luxirCodec".\{0,40\}'
# "luxirCodec":["path","native",...   (path "lucene" plus a "reason" means it fell back to Solr's normal code)
```

`luxir-bench/verify.py` runs a workload's requests against two clusters and compares counts, facets and sort values.

Results go to `suites/results/<suite>/<commit>/results.json`. Compare two runs with:

```bash
python3 luxir-bench/compare.py \
  suites/results/stress-facets-local-100m/79b23df58daac14b92cc35f23b8b81f72098b4ba \
  suites/results/luxir-stress-facets-local-100m/31ae830a4e8cef8968769d4a9e3281562668b6c1 Solr+Lucene Solr+Luxir
```

It shows indexing time, index size and document count (read from every replica right after indexing's final commit),
and each query task's throughput (warm-up included) and latency percentiles (after the warm-up).

## How Solr+Luxir got here

The changes that made Solr+Luxir fast are on these branches:

- [SearchScale/luxir `luxir-lucene`](https://github.com/SearchScale/luxir/tree/luxir-lucene): Luxir with the patches
  luxir-lucene needs, also kept in [`luxir-patches/`](https://github.com/SearchScale/luxir-lucene/tree/main/luxir-patches)
- [SearchScale/luxir-lucene `main`](https://github.com/SearchScale/luxir-lucene/tree/main): the Lucene codec and native C ABI
- [SearchScale/solr `luxir-codec`](https://github.com/SearchScale/solr/tree/luxir-codec): the `luxir-codec` Solr module
- [SearchScale/solr-bench `master`](https://github.com/SearchScale/solr-bench/tree/master): the suites, faster
  indexing client and index size reporting
