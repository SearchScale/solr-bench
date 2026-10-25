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

**Solr+Luxir indexes 1.85× faster and answers the facet and join queries 1.2–6.3× faster.**

| | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|---|---|---|---|---|
| Indexing | 684.3 s | 331.9 s | 179.0 s | **3.82×** | **1.85×** |
| Terms facet | 129 q/s, 254 ms | 130 q/s, 259 ms | 279 q/s, 114 ms | **2.16×** | **2.14×** |
| Range facet | 170 q/s, 188 ms | 163 q/s, 199 ms | 677 q/s, 55 ms | **3.98×** | **4.16×** |
| Product facet | 499 q/s, 64 ms | 435 q/s, 70 ms | 538 q/s, 58 ms | **1.08×** | **1.24×** |
| Join | 2.4 q/s, 9,598 ms | 2.2 q/s, 21,968 ms | 13.7 q/s, 2,030 ms | **5.75×** | **6.34×** |
| All four query tasks, total time | 137.2 s | 144.8 s | 49.2 s | **2.79×** | **2.94×** |

All three runs indexed exactly 100,000,000 documents, and 20M-document indexes of both systems gave identical results
for 120 facet requests. Most of Solr+Luxir's indexing lead over SM=off comes from parsing dates in its JSON
loader instead of Solr's date processor (without it, 1.04×). Native joins between string fields (`LuxirJoinQParserPlugin`) make the joins 5.8–6.3×
faster.

### Geonames, 11.4M documents

**Solr+Luxir indexes 1.25× faster, but into a 1.72× larger index. Ranges, sorts and facets are 2–6× faster; text
queries are 1.03–1.11× faster, apart from two-term OR at 1.64×.**

| | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|---|---|---|---|---|
| Indexing | 80.4 s | 48.9 s | 39.1 s | **2.06×** | **1.25×** |
| Index size after indexing | 4.61 GB, 57 segments | 4.40 GB, 50 segments | 7.56 GB, 86 segments | 1.64× larger | 1.72× larger |

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|---|---|---|---|---|
| MatchAll* | 244 q/s, 97.3 ms | 269 q/s, 94.0 ms | 280 q/s, 90.4 ms | **1.15×** | **1.04×** |
| StringTerm | 8,557 q/s, 6.39 ms | 10,511 q/s, 6.64 ms | 11,421 q/s, 5.61 ms | **1.33×** | **1.09×** |
| TextTerm | 8,004 q/s, 3.51 ms | 10,920 q/s, 2.80 ms | 11,639 q/s, 2.39 ms | **1.45×** | **1.07×** |
| TextPhrase | 8,150 q/s, 3.58 ms | 10,529 q/s, 3.03 ms | 11,676 q/s, 3.00 ms | **1.43×** | **1.11×** |
| TextOr | 5,301 q/s, 5.47 ms | 5,879 q/s, 5.05 ms | 9,662 q/s, 2.69 ms | **1.82×** | **1.64×** |
| TextAnd | 8,212 q/s, 3.11 ms | 11,096 q/s, 2.32 ms | 11,621 q/s, 2.12 ms | **1.42×** | **1.05×** |
| CatchAllText | 7,757 q/s, 3.64 ms | 10,649 q/s, 3.01 ms | 11,463 q/s, 2.04 ms | **1.48×** | **1.08×** |
| TextFiltered | 7,925 q/s, 3.52 ms | 10,615 q/s, 2.88 ms | 10,883 q/s, 2.56 ms | **1.37×** | **1.03×** |
| NumRange | 1,635 q/s, 56.1 ms | 1,624 q/s, 59.4 ms | 10,305 q/s, 2.67 ms | **6.30×** | **6.35×** |
| SortPopulation | 144 q/s, 151.2 ms | 143 q/s, 155.1 ms | 352 q/s, 65.4 ms | **2.44×** | **2.47×** |
| SortGeonameid | 157 q/s, 137.2 ms | 156 q/s, 140.6 ms | 352 q/s, 64.4 ms | **2.24×** | **2.26×** |
| TermSortPop | 7,189 q/s, 3.59 ms | 9,378 q/s, 2.81 ms | 8,541 q/s, 2.88 ms | **1.19×** | **0.91×** |
| CountryFacet | 182 q/s, 337.3 ms | 181 q/s, 333.3 ms | 429 q/s, 164.3 ms | **2.36×** | **2.37×** |
| HiCardFacet | 11.1 q/s, 2,347 ms | 10.9 q/s, 2,611 ms | 12.3 q/s, 1,655 ms | **1.11×** | **1.13×** |
| TermsPure | 54.4 q/s, 353.3 ms | 54.6 q/s, 353.7 ms | 51.0 q/s, 379.6 ms | **0.94×** | **0.93×** |
| TermsFiltered | 102 q/s, 182.7 ms | 103 q/s, 172.6 ms | 103 q/s, 174.0 ms | **1.01×** | **1.00×** |
| TermsProhibited | 57.5 q/s, 331.9 ms | 57.5 q/s, 329.6 ms | 52.4 q/s, 356.6 ms | **0.91×** | **0.91×** |
| All 212, mixed (30 s) | 427 q/s, 429.4 ms | 434 q/s, 400.4 ms | 437 q/s, 521.0 ms | **1.03×** | **1.01×** |

\* Not settled: across seven runs, MatchAll has given 0.76× to 1.36×.

All three runs indexed 11,396,503 documents with no failed request. Solr+Luxir is slower only on TermSortPop (0.91×)
and on the `{!terms}` sets of 45,700 names (0.91–1.00×), which also dominate the time of the mixed task and its p99.

### Enwiki, 25M documents

**Solr+Luxir indexes 1.51× faster and runs the full query mix 1.49× faster, but its index is 1.28× larger and phrase, span and fuzzy queries are slower.**

| | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|---|---|---|---|---|
| Indexing | 210.6 s | 133.1 s | 88.4 s | **2.38×** | **1.51×** |
| Index size after indexing | same as SM=off | 10.60 GB, 62 segments | 13.54 GB, 61 segments | | 1.28× larger |

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|---|---|---|---|---|
| HighTerm | 607 q/s, 59.3 ms | 606 q/s, 57.1 ms | 1,598 q/s, 22.8 ms | **2.63×** | **2.64×** |
| MedTerm | 1,912 q/s, 16.7 ms | 1,902 q/s, 19.4 ms | 2,834 q/s, 17.8 ms | **1.48×** | **1.49×** |
| LowTerm | 3,412 q/s, 10.1 ms | 3,741 q/s, 9.1 ms | 2,925 q/s, 11.4 ms | **0.86×** | **0.78×** |
| AndHighHigh | 1,051 q/s, 48.4 ms | 1,015 q/s, 48.7 ms | 1,364 q/s, 26.0 ms | **1.30×** | **1.34×** |
| AndHighMed | 3,507 q/s, 9.1 ms | 3,536 q/s, 9.0 ms | 2,755 q/s, 11.0 ms | **0.79×** | **0.78×** |
| AndHighLow | 5,771 q/s, 7.7 ms | 6,146 q/s, 7.0 ms | 5,771 q/s, 11.0 ms | **1.00×** | **0.94×** |
| OrHighHigh | 373 q/s, 85.2 ms | 365 q/s, 87.3 ms | 1,609 q/s, 17.2 ms | **4.32×** | **4.41×** |
| OrHighMed | 543 q/s, 98.2 ms | 526 q/s, 101.1 ms | 2,880 q/s, 9.8 ms | **5.30×** | **5.48×** |
| OrHighLow | 719 q/s, 44.2 ms | 716 q/s, 44.4 ms | 7,079 q/s, 3.8 ms | **9.85×** | **9.88×** |
| OrHighNotHigh | 327 q/s, 128.9 ms | 319 q/s, 131.6 ms | 818 q/s, 52.2 ms | **2.50×** | **2.56×** |
| OrHighNotMed | 731 q/s, 57.7 ms | 707 q/s, 58.2 ms | 1,416 q/s, 28.5 ms | **1.94×** | **2.00×** |
| OrHighNotLow | 1,275 q/s, 23.6 ms | 1,174 q/s, 27.0 ms | 2,017 q/s, 15.2 ms | **1.58×** | **1.72×** |
| OrNotHighHigh | 435 q/s, 63.3 ms | 421 q/s, 65.5 ms | 1,097 q/s, 27.5 ms | **2.52×** | **2.61×** |
| OrNotHighMed | 1,697 q/s, 17.3 ms | 1,698 q/s, 17.5 ms | 3,206 q/s, 9.6 ms | **1.89×** | **1.89×** |
| OrNotHighLow | 6,516 q/s, 8.0 ms | 7,180 q/s, 7.3 ms | 8,511 q/s, 3.2 ms | **1.31×** | **1.19×** |
| HighPhrase | 218 q/s, 274.4 ms | 217 q/s, 284.7 ms | 265 q/s, 242.4 ms | **1.21×** | **1.22×** |
| MedPhrase | 753 q/s, 66.9 ms | 749 q/s, 68.2 ms | 636 q/s, 99.0 ms | **0.84×** | **0.85×** |
| LowPhrase | 845 q/s, 65.7 ms | 847 q/s, 67.0 ms | 628 q/s, 92.7 ms | **0.74×** | **0.74×** |
| HighSloppyPhrase | 144 q/s, 655.4 ms | 144 q/s, 653.3 ms | 99 q/s, 849.2 ms | **0.69×** | **0.69×** |
| MedSloppyPhrase | 435 q/s, 197.1 ms | 441 q/s, 194.0 ms | 284 q/s, 279.7 ms | **0.65×** | **0.64×** |
| LowSloppyPhrase | 909 q/s, 71.0 ms | 920 q/s, 71.1 ms | 591 q/s, 107.7 ms | **0.65×** | **0.64×** |
| HighSpanNear | 227 q/s, 355.9 ms | 233 q/s, 343.9 ms | 152 q/s, 537.9 ms | **0.67×** | **0.65×** |
| MedSpanNear | 776 q/s, 59.7 ms | 815 q/s, 58.6 ms | 526 q/s, 90.7 ms | **0.68×** | **0.65×** |
| LowSpanNear | 761 q/s, 83.1 ms | 802 q/s, 77.8 ms | 533 q/s, 120.4 ms | **0.70×** | **0.66×** |
| Prefix3 | 653 q/s, 92.0 ms | 626 q/s, 96.6 ms | 551 q/s, 189.2 ms | **0.84×** | **0.88×** |
| Wildcard | 598 q/s, 57.6 ms | 627 q/s, 54.2 ms | 478 q/s, 91.0 ms | **0.80×** | **0.76×** |
| Fuzzy1 | 728 q/s, 38.9 ms | 802 q/s, 39.6 ms | 788 q/s, 36.4 ms | **1.08×** | **0.98×** |
| Fuzzy2 | 644 q/s, 58.0 ms | 665 q/s, 55.8 ms | 373 q/s, 109.0 ms | **0.58×** | **0.56×** |
| IntNRQ | 131 q/s, 206.8 ms | 117 q/s, 231.7 ms | 1,037 q/s, 27.8 ms | **7.89×** | **8.89×** |
| IntSet | 1,478 q/s, 16.7 ms | 1,492 q/s, 17.7 ms | 3,230 q/s, 13.1 ms | **2.19×** | **2.17×** |
| PKLookup | 11,099 q/s, 3.3 ms | 15,947 q/s, 2.2 ms | 9,127 q/s, 5.7 ms | **0.82×** | **0.57×** |
| BM25MSM2 | 78 q/s, 631.3 ms | 77 q/s, 604.5 ms | 68 q/s, 331.2 ms | **0.86×** | **0.88×** |
| HighTermMonthSort | 953 q/s, 32.9 ms | 957 q/s, 33.1 ms | 1,517 q/s, 21.8 ms | **1.59×** | **1.59×** |
| HighTermDayOfYearSort | 1,050 q/s, 40.6 ms | 1,047 q/s, 41.1 ms | 1,356 q/s, 27.8 ms | **1.29×** | **1.29×** |
| HighTermTitleSort | 903 q/s, 43.5 ms | 899 q/s, 47.6 ms | 1,209 q/s, 28.6 ms | **1.34×** | **1.35×** |
| TermDateTimeSort | 784 q/s, 51.4 ms | 777 q/s, 55.4 ms | 1,451 q/s, 20.8 ms | **1.85×** | **1.87×** |
| BrowseMonthFacets | 30 q/s, 773.2 ms | 28 q/s, 750.6 ms | 34 q/s, 584.8 ms | **1.16×** | **1.21×** |
| BrowseDayOfYearFacets | 29 q/s, 687.8 ms | 28 q/s, 754.7 ms | 32 q/s, 608.4 ms | **1.09×** | **1.14×** |
| BrowseDateFacets | 25 q/s, 784.2 ms | 24 q/s, 810.0 ms | 32 q/s, 617.5 ms | **1.28×** | **1.33×** |
| MedTermDayFacets | 601 q/s, 54.2 ms | 599 q/s, 56.8 ms | 982 q/s, 27.7 ms | **1.63×** | **1.64×** |
| AndHighHighDayFacets | 203 q/s, 276.4 ms | 204 q/s, 274.2 ms | 497 q/s, 67.2 ms | **2.45×** | **2.43×** |
| AndHighMedDayFacets | 1,263 q/s, 26.8 ms | 1,276 q/s, 27.9 ms | 1,046 q/s, 42.3 ms | **0.83×** | **0.82×** |
| OrHighMedDayFacets | 132 q/s, 392.0 ms | 130 q/s, 397.3 ms | 471 q/s, 79.6 ms | **3.56×** | **3.62×** |
| All 1,153, mixed | 436 q/s, 226.1 ms | 432 q/s, 226.8 ms | 643 q/s, 207.2 ms | **1.48×** | **1.49×** |

All three runs indexed 25,000,000 documents with no failed request. Solr+Luxir analyzes text natively, not quite as
Solr does: at 10M documents, 66 of the 1,153 requests found slightly different counts. It is much faster on disjunctions, numeric ranges and sets, facets
after an OR and the sorts. The sloppy phrases and span queries (Lucene's code over Luxir's postings) and PKLookup (the
uniqueKey stays in Lucene's format) are slower, and so are lower-frequency phrases, Fuzzy2, Wildcard and AndHighMed.

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
| luxir | `luxir-lucene` | `173ec324` (Luxir `8cb622ba` + the 5 patches in `luxir-lucene/luxir-patches/`) |
| luxir-lucene | `main` | `ecd09a1` |
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
