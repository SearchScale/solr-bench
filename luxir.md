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
| Coverage | the geonames, enwiki and e-commerce datasets above | Solr features the main workloads leave out: other parsers, edismax, grouping, collapse, highlighting, spell checking, JSON and legacy facets, stats, paging and more (`luxir-bench/coverage-queries.py`) | `coverage-<dataset>-local*.json`, `luxir-coverage-<dataset>-local*.json` |
| Correctness | generated from geonames: `types` (2.3M places with a field of every type and shape), `nested` (252 country blocks of states and places), `vectors` (285K places with float, byte and quantized vectors), `features` (380K places with Solr's own types: payloads, term vectors, enum, rank, currency) | every query shape of each dataset (`luxir-bench/<dataset>-queries.py`), one category at a time, 10 s each; the same requests `luxir-bench/verify-coverage.py` checks for identical responses | `correctness-<dataset>-local.json`, `luxir-correctness-<dataset>-local.json` |

Jump to: [Benchmarks](#benchmarks) · [Run it yourself](#run-it-yourself) ·
[How Solr+Luxir got here](#how-solrluxir-got-here)

## Benchmarks

One run of each suite (Solr+Lucene on 2026-11-02, Solr+Luxir on 2026-11-03), comparing:

- **Stock Solr+Lucene:** Apache Solr `79b23df` as it starts by default, security manager on (the `-sm-on` suites).
- **Solr+Lucene, SM=off:** the same build with the security manager off.
- **Solr+Luxir:** the versions in [Get the code](#1-get-the-code), security manager off.

Each query cell gives throughput (queries/s, warm-up included) and p99 latency (after the warm-up). Ratios are how much
faster Solr+Luxir is: above 1× means faster. For queries they compare throughput; for indexing, time. 🟢 marks
1.05× or faster, 🟡 0.95–1.05× (about level), 🔴 below 0.95× (slower). Each workload's headline
compares Solr+Luxir with Solr+Lucene, SM=off. All runs of a workload indexed the same number of
documents, and no Solr+Luxir run had a failed request.

| | |
|---|---|
| CPU | AMD Ryzen 9 7950X: 16 cores / 32 threads, up to 5.88 GHz, 64 MB L3 |
| Memory | 128 GB DDR5 |
| Disk | WD_BLACK SN8100 4 TB NVMe SSD, ext4 |
| OS / JDK | Ubuntu 22.04.5, Linux 6.8.0-138-generic; Oracle JDK 22.0.2 |
| Solr nodes | 3 on the same machine, each with `-m 16g -Dsolr.searchThreads=4` |
| Client | solr-bench (`java -Xmx12g`) on the same machine |

| Workload | Documents | Indexing, Luxir vs SM=off | Queries, Luxir vs SM=off | Queries, Luxir vs stock | Categories 🟢 / 🟡 / 🔴 (vs SM=off) |
|---|--:|--:|--:|--:|--:|
| [E-commerce, 100M documents](#e-commerce-100m-documents) | 100,000,000 | 🟢 1.84× | 🟢 3.19× | 🟢 3.13× | 4 / 0 / 0 |
| [Geonames, 11.4M documents](#geonames-114m-documents) | 11,396,503 | 🟢 1.23× | 🟢 1.33× | 🟢 1.54× | 10 / 6 / 2 |
| [Enwiki, 25M documents](#enwiki-25m-documents) | 25,000,000 | 🟢 1.59× | 🟢 1.46× | 🟢 1.50× | 28 / 2 / 14 |
| [Coverage: geonames](#coverage-geonames) | 11,396,503 | 🟢 1.26× | 🟡 1.01× | 🟢 1.16× | 7 / 7 / 6 |
| [Coverage: enwiki](#coverage-enwiki) | 25,000,000 | 🟢 1.60× | 🟢 1.37× | 🟢 1.38× | 22 / 6 / 8 |
| [Coverage: e-commerce, 100M documents](#coverage-e-commerce-100m-documents) | 100,000,000 | 🟢 1.87× | 🟢 1.26× | 🟢 1.16× | 3 / 0 / 0 |
| [Correctness: types](#correctness-types) | 2,279,301 | 🟢 1.15× | 🟢 1.27× | 🟢 1.34× | 29 / 11 / 0 |
| [Correctness: nested documents](#correctness-nested-documents) | 574,004 | 🟡 1.04× | 🟡 1.03× | 🟢 1.20× | 3 / 2 / 2 |
| [Correctness: vectors](#correctness-vectors) | 284,913 | 🟢 1.11× | 🔴 0.75× | 🔴 0.89× | 0 / 3 / 6 |
| [Correctness: Solr's own field types](#correctness-solrs-own-field-types) | 379,884 | 🟢 1.11× | 🟡 1.03× | 🟢 1.09× | 4 / 1 / 3 |

### E-commerce, 100M documents

**Solr+Luxir indexes 1.84× faster than Solr+Lucene with SM=off and answers queries 3.19× as fast (geometric mean of 4 categories): 4 faster, 0 about level, 0 slower.**

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|--:|--:|--:|--:|--:|
| Indexing | 640 s | 336 s | 183 s | 🟢 3.51× | 🟢 1.84× |
| Terms facet | 127 q/s<br>p99 262 ms | 133 q/s<br>p99 243 ms | 247 q/s<br>p99 130 ms | 🟢 1.95× | 🟢 1.86× |
| Range facet | 177 q/s<br>p99 188 ms | 164 q/s<br>p99 197 ms | 1,023 q/s<br>p99 36.0 ms | 🟢 5.77× | 🟢 6.25× |
| Product facet | 523 q/s<br>p99 59.2 ms | 440 q/s<br>p99 71.2 ms | 686 q/s<br>p99 45.5 ms | 🟢 1.31× | 🟢 1.56× |
| Join | 2.1 q/s<br>p99 18,664 ms | 2.4 q/s<br>p99 8,928 ms | 13.7 q/s<br>p99 1,969 ms | 🟢 6.51× | 🟢 5.73× |
| **Geometric mean, queries** | | | | **🟢 3.13×** | **🟢 3.19×** |
| Index size after indexing | 9.33 GB, 47 segments | 10.16 GB, 69 segments | 11.55 GB, 57 segments | | 1.14× larger |

Joins on `user_session` run through `LuxirJoinQParserPlugin`, natively between string fields. Most of Solr+Luxir's indexing lead comes from parsing dates in its JSON loader instead of Solr's date processor.

### Geonames, 11.4M documents

**Solr+Luxir indexes 1.23× faster than Solr+Lucene with SM=off and answers queries 1.33× as fast (geometric mean of 18 categories): 10 faster, 6 about level, 2 slower.** Slower: TermsPure, TermsProhibited.

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|--:|--:|--:|--:|--:|
| Indexing | 81.9 s | 49.0 s | 39.8 s | 🟢 2.06× | 🟢 1.23× |
| MatchAll | 278 q/s<br>p99 94.5 ms | 277 q/s<br>p99 93.9 ms | 277 q/s<br>p99 93.2 ms | 🟡 1.00× | 🟡 1.00× |
| StringTerm | 8,594 q/s<br>p99 6.97 ms | 10,803 q/s<br>p99 6.60 ms | 12,618 q/s<br>p99 5.71 ms | 🟢 1.47× | 🟢 1.17× |
| TextTerm | 7,950 q/s<br>p99 3.48 ms | 11,038 q/s<br>p99 2.77 ms | 12,177 q/s<br>p99 2.34 ms | 🟢 1.53× | 🟢 1.10× |
| TextPhrase | 8,081 q/s<br>p99 3.63 ms | 10,807 q/s<br>p99 2.99 ms | 11,706 q/s<br>p99 2.92 ms | 🟢 1.45× | 🟢 1.08× |
| TextOr | 5,244 q/s<br>p99 5.55 ms | 6,017 q/s<br>p99 4.96 ms | 9,917 q/s<br>p99 2.84 ms | 🟢 1.89× | 🟢 1.65× |
| TextAnd | 8,122 q/s<br>p99 3.16 ms | 11,398 q/s<br>p99 2.29 ms | 11,508 q/s<br>p99 2.19 ms | 🟢 1.42× | 🟡 1.01× |
| CatchAllText | 7,601 q/s<br>p99 3.76 ms | 10,963 q/s<br>p99 2.91 ms | 11,876 q/s<br>p99 1.95 ms | 🟢 1.56× | 🟢 1.08× |
| TextFiltered | 7,797 q/s<br>p99 3.55 ms | 10,794 q/s<br>p99 2.83 ms | 11,013 q/s<br>p99 2.53 ms | 🟢 1.41× | 🟡 1.02× |
| NumRange | 1,534 q/s<br>p99 62.6 ms | 1,640 q/s<br>p99 58.5 ms | 10,517 q/s<br>p99 2.81 ms | 🟢 6.86× | 🟢 6.41× |
| SortPopulation | 138 q/s<br>p99 159 ms | 141 q/s<br>p99 155 ms | 347 q/s<br>p99 66.0 ms | 🟢 2.51× | 🟢 2.47× |
| SortGeonameid | 160 q/s<br>p99 139 ms | 167 q/s<br>p99 137 ms | 348 q/s<br>p99 65.2 ms | 🟢 2.17× | 🟢 2.09× |
| TermSortPop | 6,953 q/s<br>p99 3.66 ms | 9,482 q/s<br>p99 2.75 ms | 9,795 q/s<br>p99 2.51 ms | 🟢 1.41× | 🟡 1.03× |
| CountryFacet | 182 q/s<br>p99 341 ms | 179 q/s<br>p99 347 ms | 414 q/s<br>p99 182 ms | 🟢 2.27× | 🟢 2.31× |
| HiCardFacet | 10.7 q/s<br>p99 2,546 ms | 11.0 q/s<br>p99 2,549 ms | 11.7 q/s<br>p99 1,998 ms | 🟢 1.10× | 🟢 1.06× |
| TermsPure | 54.0 q/s<br>p99 359 ms | 54.9 q/s<br>p99 346 ms | 51.4 q/s<br>p99 386 ms | 🟡 0.95× | 🔴 0.94× |
| TermsFiltered | 102 q/s<br>p99 174 ms | 103 q/s<br>p99 181 ms | 103 q/s<br>p99 178 ms | 🟡 1.01× | 🟡 1.01× |
| TermsProhibited | 57.3 q/s<br>p99 326 ms | 58.0 q/s<br>p99 322 ms | 53.2 q/s<br>p99 349 ms | 🔴 0.93× | 🔴 0.92× |
| All | 423 q/s<br>p99 402 ms | 435 q/s<br>p99 426 ms | 424 q/s<br>p99 488 ms | 🟡 1.00× | 🟡 0.97× |
| **Geometric mean, queries** | | | | **🟢 1.54×** | **🟢 1.33×** |
| Index size after indexing | 5.10 GB, 55 segments | 4.37 GB, 57 segments | 7.72 GB, 75 segments | | 1.76× larger |

TermsPure and TermsProhibited are `{!terms}` sets of 45,700 names; MatchAll has varied from 0.76× to 1.36× across runs.

### Enwiki, 25M documents

**Solr+Luxir indexes 1.59× faster than Solr+Lucene with SM=off and answers queries 1.46× as fast (geometric mean of 44 categories): 28 faster, 2 about level, 14 slower.** Slower: LowTerm, AndHighMed, AndHighLow, MedPhrase, LowPhrase, MedSloppyPhrase, LowSloppyPhrase, HighSpanNear, MedSpanNear, LowSpanNear, Prefix3, Fuzzy2, PKLookup, BM25MSM2.

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|--:|--:|--:|--:|--:|
| Indexing | 212 s | 133 s | 83.4 s | 🟢 2.54× | 🟢 1.59× |
| HighTerm | 611 q/s<br>p99 57.4 ms | 605 q/s<br>p99 58.7 ms | 1,568 q/s<br>p99 25.0 ms | 🟢 2.57× | 🟢 2.59× |
| MedTerm | 1,893 q/s<br>p99 19.2 ms | 1,878 q/s<br>p99 18.3 ms | 2,623 q/s<br>p99 20.0 ms | 🟢 1.39× | 🟢 1.40× |
| LowTerm | 3,463 q/s<br>p99 9.82 ms | 3,745 q/s<br>p99 15.4 ms | 2,959 q/s<br>p99 16.1 ms | 🔴 0.85× | 🔴 0.79× |
| AndHighHigh | 1,040 q/s<br>p99 50.0 ms | 994 q/s<br>p99 51.3 ms | 1,331 q/s<br>p99 25.7 ms | 🟢 1.28× | 🟢 1.34× |
| AndHighMed | 3,341 q/s<br>p99 9.56 ms | 3,603 q/s<br>p99 8.85 ms | 2,742 q/s<br>p99 12.5 ms | 🔴 0.82× | 🔴 0.76× |
| AndHighLow | 5,489 q/s<br>p99 7.83 ms | 6,109 q/s<br>p99 6.81 ms | 5,632 q/s<br>p99 7.00 ms | 🟡 1.03× | 🔴 0.92× |
| OrHighHigh | 377 q/s<br>p99 83.0 ms | 357 q/s<br>p99 90.8 ms | 1,606 q/s<br>p99 16.9 ms | 🟢 4.26× | 🟢 4.50× |
| OrHighMed | 547 q/s<br>p99 95.2 ms | 514 q/s<br>p99 104 ms | 2,837 q/s<br>p99 14.1 ms | 🟢 5.19× | 🟢 5.52× |
| OrHighLow | 721 q/s<br>p99 43.6 ms | 706 q/s<br>p99 43.9 ms | 6,886 q/s<br>p99 4.03 ms | 🟢 9.55× | 🟢 9.75× |
| OrHighNotHigh | 320 q/s<br>p99 130 ms | 315 q/s<br>p99 134 ms | 823 q/s<br>p99 53.4 ms | 🟢 2.57× | 🟢 2.61× |
| OrHighNotMed | 722 q/s<br>p99 57.1 ms | 693 q/s<br>p99 59.1 ms | 1,429 q/s<br>p99 28.2 ms | 🟢 1.98× | 🟢 2.06× |
| OrHighNotLow | 1,212 q/s<br>p99 25.1 ms | 1,183 q/s<br>p99 26.7 ms | 2,046 q/s<br>p99 15.1 ms | 🟢 1.69× | 🟢 1.73× |
| OrNotHighHigh | 415 q/s<br>p99 69.1 ms | 417 q/s<br>p99 67.2 ms | 1,112 q/s<br>p99 26.3 ms | 🟢 2.68× | 🟢 2.66× |
| OrNotHighMed | 1,634 q/s<br>p99 18.0 ms | 1,686 q/s<br>p99 18.0 ms | 3,163 q/s<br>p99 10.4 ms | 🟢 1.94× | 🟢 1.88× |
| OrNotHighLow | 6,502 q/s<br>p99 4.49 ms | 7,301 q/s<br>p99 7.11 ms | 8,440 q/s<br>p99 3.28 ms | 🟢 1.30× | 🟢 1.16× |
| HighPhrase | 216 q/s<br>p99 279 ms | 214 q/s<br>p99 286 ms | 269 q/s<br>p99 246 ms | 🟢 1.24× | 🟢 1.26× |
| MedPhrase | 738 q/s<br>p99 70.1 ms | 740 q/s<br>p99 69.1 ms | 671 q/s<br>p99 95.7 ms | 🔴 0.91× | 🔴 0.91× |
| LowPhrase | 831 q/s<br>p99 67.0 ms | 837 q/s<br>p99 68.3 ms | 666 q/s<br>p99 88.4 ms | 🔴 0.80× | 🔴 0.79× |
| HighSloppyPhrase | 139 q/s<br>p99 676 ms | 142 q/s<br>p99 674 ms | 160 q/s<br>p99 461 ms | 🟢 1.15× | 🟢 1.13× |
| MedSloppyPhrase | 423 q/s<br>p99 205 ms | 427 q/s<br>p99 198 ms | 367 q/s<br>p99 141 ms | 🔴 0.87× | 🔴 0.86× |
| LowSloppyPhrase | 876 q/s<br>p99 71.3 ms | 891 q/s<br>p99 72.0 ms | 664 q/s<br>p99 90.1 ms | 🔴 0.76× | 🔴 0.74× |
| HighSpanNear | 230 q/s<br>p99 351 ms | 232 q/s<br>p99 353 ms | 219 q/s<br>p99 493 ms | 🟡 0.95× | 🔴 0.94× |
| MedSpanNear | 794 q/s<br>p99 59.8 ms | 804 q/s<br>p99 58.5 ms | 679 q/s<br>p99 61.5 ms | 🔴 0.85× | 🔴 0.84× |
| LowSpanNear | 780 q/s<br>p99 81.5 ms | 790 q/s<br>p99 78.6 ms | 663 q/s<br>p99 85.9 ms | 🔴 0.85× | 🔴 0.84× |
| Prefix3 | 595 q/s<br>p99 99.2 ms | 660 q/s<br>p99 92.2 ms | 564 q/s<br>p99 184 ms | 🔴 0.95× | 🔴 0.86× |
| Wildcard | 595 q/s<br>p99 59.9 ms | 637 q/s<br>p99 54.1 ms | 689 q/s<br>p99 68.9 ms | 🟢 1.16× | 🟢 1.08× |
| Fuzzy1 | 790 q/s<br>p99 38.4 ms | 778 q/s<br>p99 40.9 ms | 783 q/s<br>p99 38.3 ms | 🟡 0.99× | 🟡 1.01× |
| Fuzzy2 | 651 q/s<br>p99 55.2 ms | 684 q/s<br>p99 53.9 ms | 538 q/s<br>p99 71.8 ms | 🔴 0.83× | 🔴 0.79× |
| IntNRQ | 122 q/s<br>p99 216 ms | 116 q/s<br>p99 231 ms | 982 q/s<br>p99 29.6 ms | 🟢 8.05× | 🟢 8.47× |
| IntSet | 1,424 q/s<br>p99 16.6 ms | 1,497 q/s<br>p99 16.1 ms | 3,163 q/s<br>p99 10.4 ms | 🟢 2.22× | 🟢 2.11× |
| PKLookup | 11,434 q/s<br>p99 2.83 ms | 16,117 q/s<br>p99 1.80 ms | 6,886 q/s<br>p99 9.81 ms | 🔴 0.60× | 🔴 0.43× |
| BM25MSM2 | 76.8 q/s<br>p99 629 ms | 76.2 q/s<br>p99 619 ms | 67.5 q/s<br>p99 352 ms | 🔴 0.88× | 🔴 0.89× |
| HighTermMonthSort | 947 q/s<br>p99 32.6 ms | 952 q/s<br>p99 33.4 ms | 1,512 q/s<br>p99 21.8 ms | 🟢 1.60× | 🟢 1.59× |
| HighTermDayOfYearSort | 967 q/s<br>p99 45.2 ms | 1,052 q/s<br>p99 41.1 ms | 1,343 q/s<br>p99 28.2 ms | 🟢 1.39× | 🟢 1.28× |
| HighTermTitleSort | 880 q/s<br>p99 45.7 ms | 893 q/s<br>p99 45.8 ms | 1,241 q/s<br>p99 28.5 ms | 🟢 1.41× | 🟢 1.39× |
| TermDateTimeSort | 744 q/s<br>p99 55.4 ms | 775 q/s<br>p99 57.3 ms | 1,447 q/s<br>p99 19.3 ms | 🟢 1.95× | 🟢 1.87× |
| BrowseMonthFacets | 28.8 q/s<br>p99 713 ms | 28.8 q/s<br>p99 711 ms | 37.5 q/s<br>p99 595 ms | 🟢 1.30× | 🟢 1.30× |
| BrowseDayOfYearFacets | 28.6 q/s<br>p99 719 ms | 28.2 q/s<br>p99 703 ms | 34.5 q/s<br>p99 549 ms | 🟢 1.20× | 🟢 1.22× |
| BrowseDateFacets | 25.2 q/s<br>p99 795 ms | 25.0 q/s<br>p99 837 ms | 34.9 q/s<br>p99 546 ms | 🟢 1.39× | 🟢 1.40× |
| MedTermDayFacets | 598 q/s<br>p99 53.3 ms | 596 q/s<br>p99 55.9 ms | 923 q/s<br>p99 50.4 ms | 🟢 1.54× | 🟢 1.55× |
| AndHighHighDayFacets | 203 q/s<br>p99 278 ms | 204 q/s<br>p99 274 ms | 494 q/s<br>p99 66.8 ms | 🟢 2.44× | 🟢 2.42× |
| AndHighMedDayFacets | 1,253 q/s<br>p99 27.0 ms | 1,277 q/s<br>p99 27.0 ms | 1,221 q/s<br>p99 25.0 ms | 🟡 0.97× | 🟡 0.96× |
| OrHighMedDayFacets | 133 q/s<br>p99 394 ms | 132 q/s<br>p99 398 ms | 461 q/s<br>p99 79.6 ms | 🟢 3.46× | 🟢 3.50× |
| All | 428 q/s<br>p99 237 ms | 432 q/s<br>p99 227 ms | 766 q/s<br>p99 173 ms | 🟢 1.79× | 🟢 1.77× |
| **Geometric mean, queries** | | | | **🟢 1.50×** | **🟢 1.46×** |
| Index size after indexing | 9.64 GB, 70 segments | 11.01 GB, 86 segments | 13.71 GB, 105 segments | | 1.25× larger |

Solr+Luxir analyzes text natively, not quite as Solr does: 93 of the 1,153 requests find slightly different counts. PKLookup and the other cheap categories finish their 3,000 queries in a second or two, so they mostly measure warm-up (in 50 times longer runs, PKLookup was 0.74×).

### Coverage: geonames

**Solr+Luxir indexes 1.26× faster than Solr+Lucene with SM=off and answers queries 1.01× as fast (geometric mean of 20 categories): 7 faster, 7 about level, 6 slower.** Slower: PopulationRangeFacet, MultiKeySort, Collapse, PivotWithStats, SpellCheck, TermsComponent.

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|--:|--:|--:|--:|--:|
| Indexing | 82.5 s | 49.1 s | 39.1 s | 🟢 2.11× | 🟢 1.26× |
| LegacyFacetPivot | 2,015 q/s<br>p99 35.1 ms | 1,951 q/s<br>p99 35.2 ms | 2,353 q/s<br>p99 29.0 ms | 🟢 1.17× | 🟢 1.21× |
| LegacyFacetFields | 10,116 q/s<br>p99 3.24 ms | 12,919 q/s<br>p99 2.83 ms | 12,915 q/s<br>p99 2.66 ms | 🟢 1.28× | 🟡 1.00× |
| NumBucketsPrefix | 6,740 q/s<br>p99 6.78 ms | 7,200 q/s<br>p99 7.09 ms | 7,635 q/s<br>p99 6.74 ms | 🟢 1.13× | 🟢 1.06× |
| PopulationRangeFacet | 9,396 q/s<br>p99 4.06 ms | 10,942 q/s<br>p99 3.89 ms | 10,227 q/s<br>p99 4.30 ms | 🟢 1.09× | 🔴 0.93× |
| SortElevation | 11,458 q/s<br>p99 2.60 ms | 16,619 q/s<br>p99 2.28 ms | 17,618 q/s<br>p99 1.96 ms | 🟢 1.54× | 🟢 1.06× |
| MultiKeySort | 10,244 q/s<br>p99 3.20 ms | 13,058 q/s<br>p99 2.61 ms | 10,810 q/s<br>p99 3.42 ms | 🟢 1.06× | 🔴 0.83× |
| CursorMarkFirstPage | 9,027 q/s<br>p99 3.41 ms | 11,034 q/s<br>p99 2.86 ms | 12,098 q/s<br>p99 3.05 ms | 🟢 1.34× | 🟢 1.10× |
| DeepPaging | 5,311 q/s<br>p99 6.64 ms | 5,580 q/s<br>p99 6.62 ms | 6,262 q/s<br>p99 5.26 ms | 🟢 1.18× | 🟢 1.12× |
| Grouping | 4,512 q/s<br>p99 7.88 ms | 5,003 q/s<br>p99 7.67 ms | 4,899 q/s<br>p99 9.14 ms | 🟢 1.09× | 🟡 0.98× |
| Collapse | 10,609 q/s<br>p99 3.38 ms | 13,842 q/s<br>p99 2.97 ms | 12,778 q/s<br>p99 2.98 ms | 🟢 1.20× | 🔴 0.92× |
| Highlight | 5,747 q/s<br>p99 6.93 ms | 6,535 q/s<br>p99 6.72 ms | 6,735 q/s<br>p99 7.86 ms | 🟢 1.17× | 🟡 1.03× |
| EdismaxNames | 5,268 q/s<br>p99 10.6 ms | 5,446 q/s<br>p99 10.7 ms | 7,130 q/s<br>p99 8.64 ms | 🟢 1.35× | 🟢 1.31× |
| Geofilt | 9,185 q/s<br>p99 2.57 ms | 16,247 q/s<br>p99 1.60 ms | 16,086 q/s<br>p99 2.16 ms | 🟢 1.75× | 🟡 0.99× |
| MoreLikeThis | 1,677 q/s<br>p99 34.2 ms | 1,684 q/s<br>p99 35.6 ms | 1,727 q/s<br>p99 34.5 ms | 🟡 1.03× | 🟡 1.03× |
| FacetHeatmap | 153 q/s<br>p99 153 ms | 152 q/s<br>p99 156 ms | 154 q/s<br>p99 151 ms | 🟡 1.00× | 🟡 1.01× |
| FacetQueryNested | 9,349 q/s<br>p99 3.68 ms | 11,025 q/s<br>p99 3.22 ms | 11,528 q/s<br>p99 3.21 ms | 🟢 1.23× | 🟡 1.05× |
| PivotWithStats | 2,390 q/s<br>p99 23.2 ms | 2,480 q/s<br>p99 20.9 ms | 2,193 q/s<br>p99 26.8 ms | 🔴 0.92× | 🔴 0.88× |
| IntervalFacets | 9,298 q/s<br>p99 3.95 ms | 11,163 q/s<br>p99 3.51 ms | 13,823 q/s<br>p99 2.44 ms | 🟢 1.49× | 🟢 1.24× |
| SpellCheck | 3,131 q/s<br>p99 12.3 ms | 3,190 q/s<br>p99 11.6 ms | 2,481 q/s<br>p99 23.0 ms | 🔴 0.79× | 🔴 0.78× |
| TermsComponent | 2,151 q/s<br>p99 113 ms | 2,109 q/s<br>p99 121 ms | 1,926 q/s<br>p99 135 ms | 🔴 0.90× | 🔴 0.91× |
| **Geometric mean, queries** | | | | **🟢 1.16×** | **🟡 1.01×** |
| Index size after indexing | 4.78 GB, 64 segments | 4.82 GB, 61 segments | 6.96 GB, 86 segments | | 1.44× larger |

### Coverage: enwiki

**Solr+Luxir indexes 1.60× faster than Solr+Lucene with SM=off and answers queries 1.37× as fast (geometric mean of 36 categories): 22 faster, 6 about level, 8 slower.** Slower: UnorderedSpanNear, Grouping, EdismaxComplex, EdismaxMinMatch, FacetTermsByAgg, FacetRangeNested, SurroundParser, PrefixTermFieldParsers.

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|--:|--:|--:|--:|--:|
| Indexing | 212 s | 133 s | 83.2 s | 🟢 2.55× | 🟢 1.60× |
| BoostedOr | 337 q/s<br>p99 97.4 ms | 330 q/s<br>p99 95.6 ms | 671 q/s<br>p99 43.0 ms | 🟢 1.99× | 🟢 2.03× |
| NestedBoolean | 304 q/s<br>p99 109 ms | 298 q/s<br>p99 112 ms | 786 q/s<br>p99 37.6 ms | 🟢 2.58× | 🟢 2.64× |
| DisMaxTwoFields | 257 q/s<br>p99 155 ms | 255 q/s<br>p99 151 ms | 305 q/s<br>p99 124 ms | 🟢 1.19× | 🟢 1.19× |
| Regexp | 801 q/s<br>p99 48.5 ms | 812 q/s<br>p99 44.5 ms | 982 q/s<br>p99 38.5 ms | 🟢 1.23× | 🟢 1.21× |
| UnorderedSpanNear | 546 q/s<br>p99 88.1 ms | 530 q/s<br>p99 90.1 ms | 461 q/s<br>p99 101 ms | 🔴 0.84× | 🔴 0.87× |
| LongRange | 1,352 q/s<br>p99 51.3 ms | 1,406 q/s<br>p99 56.2 ms | 1,571 q/s<br>p99 37.7 ms | 🟢 1.16× | 🟢 1.12× |
| FieldExistsFilter | 1,964 q/s<br>p99 12.6 ms | 2,045 q/s<br>p99 22.1 ms | 3,262 q/s<br>p99 16.3 ms | 🟢 1.66× | 🟢 1.59× |
| Frange | 657 q/s<br>p99 58.5 ms | 666 q/s<br>p99 60.3 ms | 2,379 q/s<br>p99 18.8 ms | 🟢 3.62× | 🟢 3.57× |
| NegativeFilter | 436 q/s<br>p99 104 ms | 436 q/s<br>p99 108 ms | 1,621 q/s<br>p99 18.6 ms | 🟢 3.72× | 🟢 3.72× |
| SortLongFiltered | 864 q/s<br>p99 48.2 ms | 861 q/s<br>p99 52.9 ms | 1,348 q/s<br>p99 27.3 ms | 🟢 1.56× | 🟢 1.57× |
| MultiKeySort | 538 q/s<br>p99 75.7 ms | 564 q/s<br>p99 71.2 ms | 632 q/s<br>p99 55.7 ms | 🟢 1.17× | 🟢 1.12× |
| DeepPaging | 821 q/s<br>p99 53.4 ms | 843 q/s<br>p99 50.8 ms | 2,647 q/s<br>p99 11.9 ms | 🟢 3.22× | 🟢 3.14× |
| LegacyFacetField | 714 q/s<br>p99 46.9 ms | 747 q/s<br>p99 46.6 ms | 1,009 q/s<br>p99 29.1 ms | 🟢 1.41× | 🟢 1.35× |
| LegacyFacetRange | 730 q/s<br>p99 39.3 ms | 714 q/s<br>p99 37.0 ms | 939 q/s<br>p99 30.0 ms | 🟢 1.29× | 🟢 1.32× |
| JsonQueryNestedFacets | 66.2 q/s<br>p99 370 ms | 66.0 q/s<br>p99 381 ms | 228 q/s<br>p99 119 ms | 🟢 3.44× | 🟢 3.45× |
| FacetAggregations | 127 q/s<br>p99 375 ms | 133 q/s<br>p99 361 ms | 278 q/s<br>p99 101 ms | 🟢 2.19× | 🟢 2.09× |
| Grouping | 580 q/s<br>p99 45.9 ms | 597 q/s<br>p99 45.1 ms | 485 q/s<br>p99 52.1 ms | 🔴 0.84× | 🔴 0.81× |
| EdismaxComplex | 527 q/s<br>p99 65.7 ms | 534 q/s<br>p99 63.9 ms | 304 q/s<br>p99 149 ms | 🔴 0.58× | 🔴 0.57× |
| EdismaxMinMatch | 754 q/s<br>p99 39.4 ms | 771 q/s<br>p99 38.3 ms | 588 q/s<br>p99 52.1 ms | 🔴 0.78× | 🔴 0.76× |
| EdismaxPhraseBoost | 736 q/s<br>p99 34.1 ms | 718 q/s<br>p99 35.5 ms | 896 q/s<br>p99 32.8 ms | 🟢 1.22× | 🟢 1.25× |
| SpellCheck | 713 q/s<br>p99 74.9 ms | 685 q/s<br>p99 44.5 ms | 655 q/s<br>p99 80.7 ms | 🔴 0.92× | 🟡 0.96× |
| FacetTermsByAgg | 204 q/s<br>p99 124 ms | 204 q/s<br>p99 121 ms | 191 q/s<br>p99 135 ms | 🔴 0.94× | 🔴 0.94× |
| FacetExcludeTags | 1,097 q/s<br>p99 24.0 ms | 1,167 q/s<br>p99 22.6 ms | 1,172 q/s<br>p99 40.0 ms | 🟢 1.07× | 🟡 1.00× |
| FacetRangeNested | 286 q/s<br>p99 90.2 ms | 286 q/s<br>p99 92.6 ms | 257 q/s<br>p99 108 ms | 🔴 0.90× | 🔴 0.90× |
| FacetRelatedness | 97.7 q/s<br>p99 222 ms | 104 q/s<br>p99 212 ms | 280 q/s<br>p99 83.1 ms | 🟢 2.86× | 🟢 2.69× |
| LegacyMultiSelectFacets | 953 q/s<br>p99 68.4 ms | 977 q/s<br>p99 48.8 ms | 1,330 q/s<br>p99 20.5 ms | 🟢 1.40× | 🟢 1.36× |
| StatsComponent | 75.6 q/s<br>p99 643 ms | 76.3 q/s<br>p99 613 ms | 101 q/s<br>p99 363 ms | 🟢 1.33× | 🟢 1.32× |
| SurroundParser | 1,524 q/s<br>p99 21.0 ms | 1,468 q/s<br>p99 22.0 ms | 1,163 q/s<br>p99 34.1 ms | 🔴 0.76× | 🔴 0.79× |
| BoolParser | 345 q/s<br>p99 135 ms | 332 q/s<br>p99 141 ms | 334 q/s<br>p99 134 ms | 🟡 0.97× | 🟡 1.01× |
| ReRank | 615 q/s<br>p99 75.2 ms | 572 q/s<br>p99 82.1 ms | 579 q/s<br>p99 79.5 ms | 🔴 0.94× | 🟡 1.01× |
| FunctionSort | 519 q/s<br>p99 79.9 ms | 501 q/s<br>p99 85.0 ms | 602 q/s<br>p99 68.0 ms | 🟢 1.16× | 🟢 1.20× |
| PrefixTermFieldParsers | 3,984 q/s<br>p99 8.35 ms | 4,422 q/s<br>p99 7.51 ms | 2,742 q/s<br>p99 12.2 ms | 🔴 0.69× | 🔴 0.62× |
| ExistsOnText | 1,789 q/s<br>p99 14.8 ms | 1,729 q/s<br>p99 15.5 ms | 4,842 q/s<br>p99 5.33 ms | 🟢 2.71× | 🟢 2.80× |
| TimeAllowed | 662 q/s<br>p99 69.8 ms | 611 q/s<br>p99 77.6 ms | 585 q/s<br>p99 78.8 ms | 🔴 0.88× | 🟡 0.96× |
| DebugExplain | 404 q/s<br>p99 95.6 ms | 375 q/s<br>p99 103 ms | 1,194 q/s<br>p99 27.0 ms | 🟢 2.95× | 🟢 3.18× |
| TermsComponent | 261 q/s<br>p99 1,174 ms | 262 q/s<br>p99 1,291 ms | 252 q/s<br>p99 1,335 ms | 🟡 0.96× | 🟡 0.96× |
| **Geometric mean, queries** | | | | **🟢 1.38×** | **🟢 1.37×** |
| Index size after indexing | 10.01 GB, 73 segments | 11.22 GB, 89 segments | 12.50 GB, 97 segments | | 1.11× larger |

### Coverage: e-commerce, 100M documents

**Solr+Luxir indexes 1.87× faster than Solr+Lucene with SM=off and answers queries 1.26× as fast (geometric mean of 3 categories): 3 faster, 0 about level, 0 slower.**

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|--:|--:|--:|--:|--:|
| Indexing | 670 s | 336 s | 180 s | 🟢 3.73× | 🟢 1.87× |
| FloatRangeSort | 238 q/s<br>p99 184 ms | 219 q/s<br>p99 196 ms | 259 q/s<br>p99 256 ms | 🟢 1.09× | 🟢 1.18× |
| FloatStats | 256 q/s<br>p99 125 ms | 233 q/s<br>p99 136 ms | 251 q/s<br>p99 143 ms | 🟡 0.98× | 🟢 1.07× |
| QueryFacets | 147 q/s<br>p99 220 ms | 136 q/s<br>p99 231 ms | 215 q/s<br>p99 137 ms | 🟢 1.46× | 🟢 1.59× |
| **Geometric mean, queries** | | | | **🟢 1.16×** | **🟢 1.26×** |
| Index size after indexing | 9.36 GB, 52 segments | 9.75 GB, 61 segments | 14.37 GB, 73 segments | | 1.47× larger |

### Correctness: types

**Solr+Luxir indexes 1.15× faster than Solr+Lucene with SM=off and answers queries 1.27× as fast (geometric mean of 40 categories): 29 faster, 11 about level, 0 slower.**

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|--:|--:|--:|--:|--:|
| Indexing | 20.4 s | 12.4 s | 10.9 s | 🟢 1.88× | 🟢 1.15× |
| BooleanShapes | 1,762 q/s<br>p99 36.3 ms | 1,849 q/s<br>p99 35.1 ms | 2,583 q/s<br>p99 29.7 ms | 🟢 1.47× | 🟢 1.40× |
| BoostAndFunctionQueries | 343 q/s<br>p99 125 ms | 348 q/s<br>p99 125 ms | 355 q/s<br>p99 128 ms | 🟡 1.03× | 🟡 1.02× |
| CollapseExpand | 722 q/s<br>p99 55.8 ms | 708 q/s<br>p99 57.0 ms | 782 q/s<br>p99 52.0 ms | 🟢 1.08× | 🟢 1.11× |
| DateMath | 5,664 q/s<br>p99 8.01 ms | 6,017 q/s<br>p99 7.57 ms | 8,951 q/s<br>p99 5.03 ms | 🟢 1.58× | 🟢 1.49× |
| Dismax | 7,948 q/s<br>p99 4.54 ms | 8,930 q/s<br>p99 4.43 ms | 11,278 q/s<br>p99 3.18 ms | 🟢 1.42× | 🟢 1.26× |
| EdismaxVariants | 4,382 q/s<br>p99 11.3 ms | 4,812 q/s<br>p99 10.5 ms | 6,893 q/s<br>p99 7.19 ms | 🟢 1.57× | 🟢 1.43× |
| Elevation | 2,493 q/s<br>p99 12.1 ms | 2,469 q/s<br>p99 12.4 ms | 2,877 q/s<br>p99 12.0 ms | 🟢 1.15× | 🟢 1.16× |
| Exists | 1,604 q/s<br>p99 24.8 ms | 1,644 q/s<br>p99 24.8 ms | 3,220 q/s<br>p99 15.6 ms | 🟢 2.01× | 🟢 1.96× |
| FieldListFunctions | 3,281 q/s<br>p99 19.2 ms | 3,171 q/s<br>p99 22.8 ms | 4,271 q/s<br>p99 15.4 ms | 🟢 1.30× | 🟢 1.35× |
| Frange | 4,555 q/s<br>p99 9.01 ms | 4,502 q/s<br>p99 9.84 ms | 4,564 q/s<br>p99 9.65 ms | 🟡 1.00× | 🟡 1.01× |
| GroupingVariants | 311 q/s<br>p99 269 ms | 331 q/s<br>p99 232 ms | 428 q/s<br>p99 160 ms | 🟢 1.38× | 🟢 1.29× |
| HighlightVariants | 3,259 q/s<br>p99 17.9 ms | 3,300 q/s<br>p99 17.5 ms | 3,566 q/s<br>p99 16.1 ms | 🟢 1.09× | 🟢 1.08× |
| JoinGraphMlt | 1,528 q/s<br>p99 31.2 ms | 1,512 q/s<br>p99 31.1 ms | 1,620 q/s<br>p99 31.0 ms | 🟢 1.06× | 🟢 1.07× |
| JsonAggregations | 86.6 q/s<br>p99 526 ms | 85.6 q/s<br>p99 533 ms | 124 q/s<br>p99 500 ms | 🟢 1.43× | 🟢 1.45× |
| JsonQueryDsl | 8,187 q/s<br>p99 4.45 ms | 9,488 q/s<br>p99 4.03 ms | 9,822 q/s<br>p99 3.99 ms | 🟢 1.20× | 🟡 1.04× |
| JsonRangeFacets | 1,105 q/s<br>p99 28.9 ms | 1,100 q/s<br>p99 31.4 ms | 3,131 q/s<br>p99 13.6 ms | 🟢 2.83× | 🟢 2.85× |
| JsonTermsFacets | 231 q/s<br>p99 695 ms | 234 q/s<br>p99 664 ms | 255 q/s<br>p99 779 ms | 🟢 1.10× | 🟢 1.09× |
| LegacyFacetFieldVariants | 221 q/s<br>p99 465 ms | 217 q/s<br>p99 496 ms | 222 q/s<br>p99 440 ms | 🟡 1.00× | 🟡 1.02× |
| LegacyFacetQueryRange | 1,125 q/s<br>p99 70.5 ms | 1,095 q/s<br>p99 76.8 ms | 1,332 q/s<br>p99 66.5 ms | 🟢 1.18× | 🟢 1.22× |
| LegacyPivotIntervalHeatmap | 949 q/s<br>p99 40.8 ms | 919 q/s<br>p99 40.6 ms | 1,029 q/s<br>p99 38.6 ms | 🟢 1.08× | 🟢 1.12× |
| MultiTerm | 2,276 q/s<br>p99 20.1 ms | 2,191 q/s<br>p99 21.1 ms | 3,629 q/s<br>p99 14.6 ms | 🟢 1.59× | 🟢 1.66× |
| NestedAndFilters | 3,208 q/s<br>p99 22.9 ms | 3,464 q/s<br>p99 22.4 ms | 3,465 q/s<br>p99 22.7 ms | 🟢 1.08× | 🟡 1.00× |
| OtherParsers | 1,878 q/s<br>p99 37.1 ms | 1,876 q/s<br>p99 37.4 ms | 3,200 q/s<br>p99 20.8 ms | 🟢 1.70× | 🟢 1.71× |
| Paging | 17.6 q/s<br>p99 8,995 ms | 18.7 q/s<br>p99 8,896 ms | 22.5 q/s<br>p99 7,636 ms | 🟢 1.28× | 🟢 1.20× |
| Phrases | 11,353 q/s<br>p99 2.54 ms | 17,682 q/s<br>p99 1.50 ms | 20,322 q/s<br>p99 1.42 ms | 🟢 1.79× | 🟢 1.15× |
| PureNegative | 1,077 q/s<br>p99 47.4 ms | 1,025 q/s<br>p99 47.4 ms | 1,412 q/s<br>p99 35.9 ms | 🟢 1.31× | 🟢 1.38× |
| RangeCounts | 11,835 q/s<br>p99 2.23 ms | 20,871 q/s<br>p99 1.17 ms | 20,935 q/s<br>p99 1.27 ms | 🟢 1.77× | 🟡 1.00× |
| RangePerType | 1,527 q/s<br>p99 26.1 ms | 1,365 q/s<br>p99 30.1 ms | 2,486 q/s<br>p99 20.8 ms | 🟢 1.63× | 🟢 1.82× |
| RealTimeGet | 13,930 q/s<br>p99 2.01 ms | 24,687 q/s<br>p99 1.13 ms | 25,411 q/s<br>p99 1.07 ms | 🟢 1.82× | 🟡 1.03× |
| RequestParams | 7,481 q/s<br>p99 5.01 ms | 8,074 q/s<br>p99 5.17 ms | 10,109 q/s<br>p99 4.29 ms | 🟢 1.35× | 🟢 1.25× |
| SortFunctions | 878 q/s<br>p99 58.8 ms | 869 q/s<br>p99 59.6 ms | 943 q/s<br>p99 56.5 ms | 🟢 1.07× | 🟢 1.09× |
| SortMultiValued | 418 q/s<br>p99 77.4 ms | 406 q/s<br>p99 80.0 ms | 400 q/s<br>p99 77.1 ms | 🟡 0.96× | 🟡 0.99× |
| SortSingleValued | 1,033 q/s<br>p99 48.0 ms | 1,006 q/s<br>p99 49.0 ms | 2,072 q/s<br>p99 18.1 ms | 🟢 2.00× | 🟢 2.06× |
| Spatial | 8,050 q/s<br>p99 4.31 ms | 9,225 q/s<br>p99 4.23 ms | 9,358 q/s<br>p99 4.81 ms | 🟢 1.16× | 🟡 1.01× |
| SpellCheckVariants | 5,777 q/s<br>p99 6.85 ms | 6,105 q/s<br>p99 7.63 ms | 5,883 q/s<br>p99 7.02 ms | 🟡 1.02× | 🟡 0.96× |
| StatsVariants | 196 q/s<br>p99 286 ms | 196 q/s<br>p99 282 ms | 275 q/s<br>p99 160 ms | 🟢 1.40× | 🟢 1.40× |
| StreamingExpressions | 740 q/s<br>p99 72.5 ms | 729 q/s<br>p99 75.5 ms | 962 q/s<br>p99 36.8 ms | 🟢 1.30× | 🟢 1.32× |
| TermPerType | 2,313 q/s<br>p99 24.5 ms | 2,182 q/s<br>p99 26.8 ms | 3,389 q/s<br>p99 19.5 ms | 🟢 1.47× | 🟢 1.55× |
| TermTermsRawPrefix | 1,279 q/s<br>p99 30.1 ms | 1,201 q/s<br>p99 32.7 ms | 1,916 q/s<br>p99 31.2 ms | 🟢 1.50× | 🟢 1.60× |
| TermsComponentVariants | 437 q/s<br>p99 167 ms | 439 q/s<br>p99 165 ms | 442 q/s<br>p99 172 ms | 🟡 1.01× | 🟡 1.01× |
| **Geometric mean, queries** | | | | **🟢 1.34×** | **🟢 1.27×** |
| Index size after indexing | 1.06 GB, 35 segments | 1.11 GB, 44 segments | 1.51 GB, 29 segments | | 1.36× larger |

### Correctness: nested documents

**Solr+Luxir indexes 1.04× faster than Solr+Lucene with SM=off and answers queries 1.03× as fast (geometric mean of 7 categories): 3 faster, 2 about level, 2 slower.** Slower: BlockJoinFacets, ChildTransformer.

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|--:|--:|--:|--:|--:|
| Indexing | 4.2 s | 4.2 s | 4.1 s | 🟡 1.02× | 🟡 1.04× |
| BlockJoinFacets | 2,636 q/s<br>p99 25.6 ms | 2,849 q/s<br>p99 24.5 ms | 2,638 q/s<br>p99 26.2 ms | 🟡 1.00× | 🔴 0.93× |
| ChildBlockJoin | 6,371 q/s<br>p99 9.30 ms | 7,519 q/s<br>p99 9.40 ms | 7,600 q/s<br>p99 8.88 ms | 🟢 1.19× | 🟡 1.01× |
| ChildTransformer | 5,277 q/s<br>p99 6.54 ms | 7,931 q/s<br>p99 5.20 ms | 7,356 q/s<br>p99 5.33 ms | 🟢 1.39× | 🔴 0.93× |
| FeaturesOverNested | 2,300 q/s<br>p99 32.0 ms | 2,384 q/s<br>p99 29.0 ms | 2,771 q/s<br>p99 28.0 ms | 🟢 1.20× | 🟢 1.16× |
| NestPaths | 6,629 q/s<br>p99 4.74 ms | 7,260 q/s<br>p99 4.62 ms | 7,752 q/s<br>p99 4.52 ms | 🟢 1.17× | 🟢 1.07× |
| ParentBlockJoin | 8,493 q/s<br>p99 4.14 ms | 11,071 q/s<br>p99 3.34 ms | 11,178 q/s<br>p99 3.41 ms | 🟢 1.32× | 🟡 1.01× |
| ParentsByChildren | 923 q/s<br>p99 26.8 ms | 948 q/s<br>p99 24.8 ms | 1,077 q/s<br>p99 23.0 ms | 🟢 1.17× | 🟢 1.14× |
| **Geometric mean, queries** | | | | **🟢 1.20×** | **🟡 1.03×** |
| Index size after indexing | 0.12 GB, 28 segments | 0.11 GB, 25 segments | 0.17 GB, 15 segments | | 1.57× larger |

### Correctness: vectors

**Solr+Luxir indexes 1.11× faster than Solr+Lucene with SM=off and answers queries 0.75× as fast (geometric mean of 9 categories): 0 faster, 3 about level, 6 slower.** Slower: KnnBasic, KnnExactSmallFilters, KnnFiltered, KnnHybrid, KnnParams, KnnQuantized.

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|--:|--:|--:|--:|--:|
| Indexing | 24.4 s | 23.9 s | 21.6 s | 🟢 1.13× | 🟢 1.11× |
| KnnBasic | 1,858 q/s<br>p99 26.0 ms | 1,825 q/s<br>p99 26.8 ms | 979 q/s<br>p99 37.9 ms | 🔴 0.53× | 🔴 0.54× |
| KnnExactSmallFilters | 10,423 q/s<br>p99 4.91 ms | 15,057 q/s<br>p99 4.23 ms | 11,831 q/s<br>p99 5.11 ms | 🟢 1.14× | 🔴 0.79× |
| KnnFiltered | 3,858 q/s<br>p99 8.10 ms | 4,138 q/s<br>p99 7.88 ms | 2,289 q/s<br>p99 14.5 ms | 🔴 0.59× | 🔴 0.55× |
| KnnHybrid | 1,616 q/s<br>p99 21.0 ms | 1,619 q/s<br>p99 20.4 ms | 1,132 q/s<br>p99 28.0 ms | 🔴 0.70× | 🔴 0.70× |
| KnnParams | 8,697 q/s<br>p99 3.50 ms | 9,889 q/s<br>p99 2.85 ms | 6,521 q/s<br>p99 4.54 ms | 🔴 0.75× | 🔴 0.66× |
| KnnQuantized | 9,236 q/s<br>p99 3.06 ms | 10,749 q/s<br>p99 2.46 ms | 7,176 q/s<br>p99 3.83 ms | 🔴 0.78× | 🔴 0.67× |
| VectorFields | 8,656 q/s<br>p99 3.73 ms | 13,913 q/s<br>p99 2.92 ms | 13,865 q/s<br>p99 3.04 ms | 🟢 1.60× | 🟡 1.00× |
| VectorFunctions | 7,171 q/s<br>p99 5.47 ms | 9,721 q/s<br>p99 4.32 ms | 9,740 q/s<br>p99 5.03 ms | 🟢 1.36× | 🟡 1.00× |
| VectorThreshold | 188 q/s<br>p99 117 ms | 200 q/s<br>p99 110 ms | 202 q/s<br>p99 109 ms | 🟢 1.07× | 🟡 1.01× |
| **Geometric mean, queries** | | | | **🔴 0.89×** | **🔴 0.75×** |
| Index size after indexing | 0.83 GB, 51 segments | 0.82 GB, 51 segments | 0.88 GB, 69 segments | | 1.08× larger |

Vector search is not yet tuned in Solr+Luxir.

### Correctness: Solr's own field types

**Solr+Luxir indexes 1.11× faster than Solr+Lucene with SM=off and answers queries 1.03× as fast (geometric mean of 8 categories): 4 faster, 1 about level, 3 slower.** Slower: Currency, EnumField, LuceneAnalyzedText.

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|--:|--:|--:|--:|--:|
| Indexing | 5.5 s | 4.7 s | 4.2 s | 🟢 1.33× | 🟢 1.11× |
| Currency | 2,205 q/s<br>p99 32.6 ms | 2,337 q/s<br>p99 32.0 ms | 2,203 q/s<br>p99 32.6 ms | 🟡 1.00× | 🔴 0.94× |
| EnumField | 5,118 q/s<br>p99 6.53 ms | 5,602 q/s<br>p99 6.92 ms | 4,859 q/s<br>p99 8.62 ms | 🔴 0.95× | 🔴 0.87× |
| LuceneAnalyzedText | 4,946 q/s<br>p99 14.8 ms | 5,050 q/s<br>p99 14.0 ms | 4,787 q/s<br>p99 15.7 ms | 🟡 0.97× | 🔴 0.95× |
| Payloads | 9,776 q/s<br>p99 4.04 ms | 11,938 q/s<br>p99 3.38 ms | 12,768 q/s<br>p99 2.94 ms | 🟢 1.31× | 🟢 1.07× |
| RankField | 1,417 q/s<br>p99 18.2 ms | 1,449 q/s<br>p99 17.9 ms | 1,491 q/s<br>p99 18.0 ms | 🟢 1.05× | 🟡 1.03× |
| SortableText | 6,067 q/s<br>p99 5.33 ms | 6,744 q/s<br>p99 5.00 ms | 7,584 q/s<br>p99 4.27 ms | 🟢 1.25× | 🟢 1.12× |
| TermVectorHighlighting | 4,885 q/s<br>p99 15.6 ms | 4,737 q/s<br>p99 17.1 ms | 5,745 q/s<br>p99 14.7 ms | 🟢 1.18× | 🟢 1.21× |
| TermVectors | 8,507 q/s<br>p99 4.98 ms | 8,371 q/s<br>p99 5.38 ms | 9,010 q/s<br>p99 5.56 ms | 🟢 1.06× | 🟢 1.08× |
| **Geometric mean, queries** | | | | **🟢 1.09×** | **🟡 1.03×** |
| Index size after indexing | 0.13 GB, 22 segments | 0.11 GB, 21 segments | 0.13 GB, 20 segments | | 1.16× larger |

One payload query failed on Solr+Lucene with SM=off: a race in stock Solr's `IndexSchema.getPayloadDecoder` cache (`ConcurrentModificationException`), fixed in Solr+Luxir's branch.

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
| luxir | `luxir-lucene` | `e3ca3c7f` (Luxir `b0fa2856` + the 4 patches in `luxir-lucene/luxir-patches/`) |
| luxir-lucene | `main` | `5be4a2f` |
| solr | `luxir-codec` (Apache Solr `79b23df` plus the module) | `a4fbd9027af7c044e2ad54d5242326692967ffd5` |

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

L=79b23df58daac14b92cc35f23b8b81f72098b4ba   # Solr+Lucene
X=a4fbd9027af7c044e2ad54d5242326692967ffd5   # Solr+Luxir

# the main workloads: Solr+Lucene (stock, then SM=off), then Solr+Luxir
for w in "stress-facets-local-100m luxir-stress-facets-local-100m" "geonames-local luxir-geonames-local" \
         "enwiki-local luxir-enwiki-native-local"; do
  set -- $w
  ./cleanup.sh && ./stress.sh -c $L suites/$1-sm-on.json
  ./cleanup.sh && ./stress.sh -c $L suites/$1.json
  ./cleanup.sh && ./stress.sh -c $X suites/$2.json
done
# the coverage and correctness workloads in the same way: coverage-geonames-local / luxir-coverage-geonames-local,
# coverage-enwiki-local / luxir-coverage-enwiki-native-local, coverage-facets-local-100m / luxir-coverage-facets-local-100m,
# correctness-<types|nested|vectors|features>-local / luxir-correctness-<...>-local
```

- The suites download their datasets on the first run.
- Each run takes about 10 minutes after the first Gradle build of its commit. `luxir-codec` is Apache Solr `79b23df`
  plus the module, so `-c 79b23df` builds the same Solr for Solr+Lucene.
- The Solr+Lucene suites turn Solr's security manager off, as Solr+Luxir must; their `-sm-on` copies leave it on, as
  stock Solr starts. The correctness datasets were made from geonames by `luxir-bench/<dataset>-dataset.py`.
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
  suites/results/luxir-stress-facets-local-100m/a4fbd9027af7c044e2ad54d5242326692967ffd5 Solr+Lucene Solr+Luxir
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
