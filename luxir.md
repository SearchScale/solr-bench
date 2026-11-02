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

One run of each suite on 2026-11-02, comparing:

- **Stock Solr+Lucene:** Apache Solr `79b23df` as it starts by default, security manager on (the `-sm-on` suites).
- **Solr+Lucene, SM=off:** the same build with the security manager off.
- **Solr+Luxir:** the versions in [Get the code](#1-get-the-code), security manager off.

Ratios are how much faster Solr+Luxir is: above 1× means faster. For queries they compare throughput (queries/s, warm-up
included); for indexing, time. 🟢 is 1.05× or faster, 🟡 0.95–1.05× (about level), 🔴 below 0.95× (slower). Each
workload's headline compares Solr+Luxir with Solr+Lucene, SM=off. All runs of a workload indexed the same number of
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
| [E-commerce, 100M documents](#e-commerce-100m-documents) | 100,000,000 | 🟢 1.86× | 🟢 3.28× | 🟢 3.22× | 4 / 0 / 0 |
| [Geonames, 11.4M documents](#geonames-114m-documents) | 11,396,503 | 🟢 1.27× | 🟢 1.35× | 🟢 1.55× | 11 / 5 / 2 |
| [Enwiki, 25M documents](#enwiki-25m-documents) | 25,000,000 | 🟢 1.60× | 🟢 1.48× | 🟢 1.51× | 28 / 3 / 13 |
| [Coverage: geonames](#coverage-geonames) | 11,396,503 | 🟢 1.27× | 🟡 1.01× | 🟢 1.16× | 7 / 7 / 6 |
| [Coverage: enwiki](#coverage-enwiki) | 25,000,000 | 🟢 1.62× | 🟢 1.37× | 🟢 1.37× | 22 / 5 / 9 |
| [Coverage: e-commerce, 100M documents](#coverage-e-commerce-100m-documents) | 100,000,000 | 🟢 1.88× | 🟢 1.28× | 🟢 1.18× | 3 / 0 / 0 |
| [Correctness: types](#correctness-types) | 2,279,301 | 🟢 1.14× | 🟢 1.26× | 🟢 1.32× | 29 / 10 / 1 |
| [Correctness: nested documents](#correctness-nested-documents) | 574,004 | 🟢 1.05× | 🟢 1.06× | 🟢 1.23× | 4 / 1 / 2 |
| [Correctness: vectors](#correctness-vectors) | 284,913 | 🟢 1.14× | 🔴 0.74× | 🔴 0.88× | 0 / 3 / 6 |
| [Correctness: Solr's own field types](#correctness-solrs-own-field-types) | 379,884 | 🟡 1.01× | 🟢 1.07× | 🟢 1.14× | 4 / 3 / 1 |

### E-commerce, 100M documents

**Solr+Luxir indexes 1.86× faster than Solr+Lucene with SM=off and answers queries 3.28× as fast (geometric mean of 4 categories): 4 faster, 0 about level, 0 slower.**

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|--:|--:|--:|--:|--:|
| Indexing (s) | 640 | 336 | 180 | 🟢 3.55× | 🟢 1.86× |
| Terms facet | 127 | 133 | 247 | 🟢 1.96× | 🟢 1.86× |
| Range facet | 177 | 164 | 1,029 | 🟢 5.80× | 🟢 6.28× |
| Product facet | 523 | 440 | 709 | 🟢 1.35× | 🟢 1.61× |
| Join | 2.1 | 2.4 | 14.8 | 🟢 7.01× | 🟢 6.16× |
| **Geometric mean, queries** | | | | **🟢 3.22×** | **🟢 3.28×** |
| Index size after indexing | 9.33 GB, 47 segments | 10.16 GB, 69 segments | 16.19 GB, 66 segments | | 1.59× larger |

Joins on `user_session` run through `LuxirJoinQParserPlugin`, natively between string fields. Most of Solr+Luxir's indexing lead comes from parsing dates in its JSON loader instead of Solr's date processor.

### Geonames, 11.4M documents

**Solr+Luxir indexes 1.27× faster than Solr+Lucene with SM=off and answers queries 1.35× as fast (geometric mean of 18 categories): 11 faster, 5 about level, 2 slower.** Slower: MatchAll, TermsProhibited.

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|--:|--:|--:|--:|--:|
| Indexing (s) | 81.9 | 49.0 | 38.7 | 🟢 2.11× | 🟢 1.27× |
| MatchAll | 278 | 277 | 246 | 🔴 0.89× | 🔴 0.89× |
| StringTerm | 8,594 | 10,803 | 12,800 | 🟢 1.49× | 🟢 1.18× |
| TextTerm | 7,950 | 11,038 | 12,311 | 🟢 1.55× | 🟢 1.12× |
| TextPhrase | 8,081 | 10,807 | 11,792 | 🟢 1.46× | 🟢 1.09× |
| TextOr | 5,244 | 6,017 | 9,979 | 🟢 1.90× | 🟢 1.66× |
| TextAnd | 8,122 | 11,398 | 11,987 | 🟢 1.48× | 🟢 1.05× |
| CatchAllText | 7,601 | 10,963 | 11,998 | 🟢 1.58× | 🟢 1.09× |
| TextFiltered | 7,797 | 10,794 | 11,046 | 🟢 1.42× | 🟡 1.02× |
| NumRange | 1,534 | 1,640 | 10,575 | 🟢 6.89× | 🟢 6.45× |
| SortPopulation | 138 | 141 | 360 | 🟢 2.60× | 🟢 2.56× |
| SortGeonameid | 160 | 167 | 357 | 🟢 2.23× | 🟢 2.14× |
| TermSortPop | 6,953 | 9,482 | 9,708 | 🟢 1.40× | 🟡 1.02× |
| CountryFacet | 182 | 179 | 412 | 🟢 2.26× | 🟢 2.30× |
| HiCardFacet | 10.7 | 11.0 | 12.6 | 🟢 1.18× | 🟢 1.14× |
| TermsPure | 54.0 | 54.9 | 52.4 | 🟡 0.97× | 🟡 0.95× |
| TermsFiltered | 102 | 103 | 103 | 🟡 1.00× | 🟡 1.00× |
| TermsProhibited | 57.3 | 58.0 | 53.8 | 🔴 0.94× | 🔴 0.93× |
| All | 423 | 435 | 438 | 🟡 1.04× | 🟡 1.01× |
| **Geometric mean, queries** | | | | **🟢 1.55×** | **🟢 1.35×** |
| Index size after indexing | 5.10 GB, 55 segments | 4.37 GB, 57 segments | 7.40 GB, 90 segments | | 1.69× larger |

TermsPure and TermsProhibited are `{!terms}` sets of 45,700 names; MatchAll has varied from 0.76× to 1.36× across runs.

### Enwiki, 25M documents

**Solr+Luxir indexes 1.60× faster than Solr+Lucene with SM=off and answers queries 1.48× as fast (geometric mean of 44 categories): 28 faster, 3 about level, 13 slower.** Slower: LowTerm, AndHighMed, MedPhrase, LowPhrase, MedSloppyPhrase, LowSloppyPhrase, HighSpanNear, MedSpanNear, LowSpanNear, Prefix3, Fuzzy2, PKLookup, BM25MSM2.

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|--:|--:|--:|--:|--:|
| Indexing (s) | 212 | 133 | 83.0 | 🟢 2.56× | 🟢 1.60× |
| HighTerm | 611 | 605 | 1,626 | 🟢 2.66× | 🟢 2.69× |
| MedTerm | 1,893 | 1,878 | 2,770 | 🟢 1.46× | 🟢 1.47× |
| LowTerm | 3,463 | 3,745 | 2,974 | 🔴 0.86× | 🔴 0.79× |
| AndHighHigh | 1,040 | 994 | 1,361 | 🟢 1.31× | 🟢 1.37× |
| AndHighMed | 3,341 | 3,603 | 2,698 | 🔴 0.81× | 🔴 0.75× |
| AndHighLow | 5,489 | 6,109 | 5,941 | 🟢 1.08× | 🟡 0.97× |
| OrHighHigh | 377 | 357 | 1,590 | 🟢 4.22× | 🟢 4.46× |
| OrHighMed | 547 | 514 | 2,864 | 🟢 5.24× | 🟢 5.57× |
| OrHighLow | 721 | 706 | 6,779 | 🟢 9.40× | 🟢 9.60× |
| OrHighNotHigh | 320 | 315 | 821 | 🟢 2.57× | 🟢 2.61× |
| OrHighNotMed | 722 | 693 | 1,419 | 🟢 1.97× | 🟢 2.05× |
| OrHighNotLow | 1,212 | 1,183 | 2,043 | 🟢 1.69× | 🟢 1.73× |
| OrNotHighHigh | 415 | 417 | 1,110 | 🟢 2.68× | 🟢 2.66× |
| OrNotHighMed | 1,634 | 1,686 | 3,156 | 🟢 1.93× | 🟢 1.87× |
| OrNotHighLow | 6,502 | 7,301 | 8,632 | 🟢 1.33× | 🟢 1.18× |
| HighPhrase | 216 | 214 | 269 | 🟢 1.25× | 🟢 1.26× |
| MedPhrase | 738 | 740 | 671 | 🔴 0.91× | 🔴 0.91× |
| LowPhrase | 831 | 837 | 664 | 🔴 0.80× | 🔴 0.79× |
| HighSloppyPhrase | 139 | 142 | 159 | 🟢 1.15× | 🟢 1.13× |
| MedSloppyPhrase | 423 | 427 | 368 | 🔴 0.87× | 🔴 0.86× |
| LowSloppyPhrase | 876 | 891 | 665 | 🔴 0.76× | 🔴 0.75× |
| HighSpanNear | 230 | 232 | 219 | 🟡 0.95× | 🔴 0.94× |
| MedSpanNear | 794 | 804 | 680 | 🔴 0.86× | 🔴 0.85× |
| LowSpanNear | 780 | 790 | 662 | 🔴 0.85× | 🔴 0.84× |
| Prefix3 | 595 | 660 | 559 | 🔴 0.94× | 🔴 0.85× |
| Wildcard | 595 | 637 | 689 | 🟢 1.16× | 🟢 1.08× |
| Fuzzy1 | 790 | 778 | 781 | 🟡 0.99× | 🟡 1.00× |
| Fuzzy2 | 651 | 684 | 551 | 🔴 0.85× | 🔴 0.81× |
| IntNRQ | 122 | 116 | 989 | 🟢 8.10× | 🟢 8.53× |
| IntSet | 1,424 | 1,497 | 3,070 | 🟢 2.16× | 🟢 2.05× |
| PKLookup | 11,434 | 16,117 | 6,748 | 🔴 0.59× | 🔴 0.42× |
| BM25MSM2 | 76.8 | 76.2 | 67.4 | 🔴 0.88× | 🔴 0.88× |
| HighTermMonthSort | 947 | 952 | 1,582 | 🟢 1.67× | 🟢 1.66× |
| HighTermDayOfYearSort | 967 | 1,052 | 1,422 | 🟢 1.47× | 🟢 1.35× |
| HighTermTitleSort | 880 | 893 | 1,281 | 🟢 1.46× | 🟢 1.43× |
| TermDateTimeSort | 744 | 775 | 1,499 | 🟢 2.01× | 🟢 1.93× |
| BrowseMonthFacets | 28.8 | 28.8 | 37.6 | 🟢 1.31× | 🟢 1.31× |
| BrowseDayOfYearFacets | 28.6 | 28.2 | 34.4 | 🟢 1.20× | 🟢 1.22× |
| BrowseDateFacets | 25.2 | 25.0 | 35.4 | 🟢 1.41× | 🟢 1.42× |
| MedTermDayFacets | 598 | 596 | 924 | 🟢 1.54× | 🟢 1.55× |
| AndHighHighDayFacets | 203 | 204 | 495 | 🟢 2.44× | 🟢 2.42× |
| AndHighMedDayFacets | 1,253 | 1,277 | 1,245 | 🟡 0.99× | 🟡 0.97× |
| OrHighMedDayFacets | 133 | 132 | 463 | 🟢 3.48× | 🟢 3.51× |
| All | 428 | 432 | 769 | 🟢 1.80× | 🟢 1.78× |
| **Geometric mean, queries** | | | | **🟢 1.51×** | **🟢 1.48×** |
| Index size after indexing | 9.64 GB, 70 segments | 11.01 GB, 86 segments | 12.19 GB, 84 segments | | 1.11× larger |

Solr+Luxir analyzes text natively, not quite as Solr does, so some requests find slightly different counts. PKLookup and the other cheap categories finish their 3,000 queries in a second or two, so they mostly measure warm-up (in 50 times longer runs, PKLookup was 0.74×).

### Coverage: geonames

**Solr+Luxir indexes 1.27× faster than Solr+Lucene with SM=off and answers queries 1.01× as fast (geometric mean of 20 categories): 7 faster, 7 about level, 6 slower.** Slower: PopulationRangeFacet, MultiKeySort, Collapse, PivotWithStats, SpellCheck, TermsComponent.

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|--:|--:|--:|--:|--:|
| Indexing (s) | 82.5 | 49.1 | 38.7 | 🟢 2.13× | 🟢 1.27× |
| LegacyFacetPivot | 2,015 | 1,951 | 2,359 | 🟢 1.17× | 🟢 1.21× |
| LegacyFacetFields | 10,116 | 12,919 | 12,839 | 🟢 1.27× | 🟡 0.99× |
| NumBucketsPrefix | 6,740 | 7,200 | 7,738 | 🟢 1.15× | 🟢 1.07× |
| PopulationRangeFacet | 9,396 | 10,942 | 10,209 | 🟢 1.09× | 🔴 0.93× |
| SortElevation | 11,458 | 16,619 | 17,566 | 🟢 1.53× | 🟢 1.06× |
| MultiKeySort | 10,244 | 13,058 | 10,406 | 🟡 1.02× | 🔴 0.80× |
| CursorMarkFirstPage | 9,027 | 11,034 | 11,918 | 🟢 1.32× | 🟢 1.08× |
| DeepPaging | 5,311 | 5,580 | 6,048 | 🟢 1.14× | 🟢 1.08× |
| Grouping | 4,512 | 5,003 | 4,936 | 🟢 1.09× | 🟡 0.99× |
| Collapse | 10,609 | 13,842 | 12,755 | 🟢 1.20× | 🔴 0.92× |
| Highlight | 5,747 | 6,535 | 6,708 | 🟢 1.17× | 🟡 1.03× |
| EdismaxNames | 5,268 | 5,446 | 7,094 | 🟢 1.35× | 🟢 1.30× |
| Geofilt | 9,185 | 16,247 | 16,145 | 🟢 1.76× | 🟡 0.99× |
| MoreLikeThis | 1,677 | 1,684 | 1,724 | 🟡 1.03× | 🟡 1.02× |
| FacetHeatmap | 153 | 152 | 156 | 🟡 1.02× | 🟡 1.02× |
| FacetQueryNested | 9,349 | 11,025 | 11,160 | 🟢 1.19× | 🟡 1.01× |
| PivotWithStats | 2,390 | 2,480 | 2,282 | 🟡 0.95× | 🔴 0.92× |
| IntervalFacets | 9,298 | 11,163 | 13,391 | 🟢 1.44× | 🟢 1.20× |
| SpellCheck | 3,131 | 3,190 | 2,569 | 🔴 0.82× | 🔴 0.81× |
| TermsComponent | 2,151 | 2,109 | 1,929 | 🔴 0.90× | 🔴 0.91× |
| **Geometric mean, queries** | | | | **🟢 1.16×** | **🟡 1.01×** |
| Index size after indexing | 4.78 GB, 64 segments | 4.82 GB, 61 segments | 7.19 GB, 78 segments | | 1.49× larger |

### Coverage: enwiki

**Solr+Luxir indexes 1.62× faster than Solr+Lucene with SM=off and answers queries 1.37× as fast (geometric mean of 36 categories): 22 faster, 5 about level, 9 slower.** Slower: UnorderedSpanNear, Grouping, EdismaxComplex, EdismaxMinMatch, FacetTermsByAgg, FacetRangeNested, SurroundParser, PrefixTermFieldParsers, TimeAllowed.

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|--:|--:|--:|--:|--:|
| Indexing (s) | 212 | 133 | 82.2 | 🟢 2.58× | 🟢 1.62× |
| BoostedOr | 337 | 330 | 670 | 🟢 1.99× | 🟢 2.03× |
| NestedBoolean | 304 | 298 | 805 | 🟢 2.64× | 🟢 2.70× |
| DisMaxTwoFields | 257 | 255 | 306 | 🟢 1.19× | 🟢 1.20× |
| Regexp | 801 | 812 | 956 | 🟢 1.19× | 🟢 1.18× |
| UnorderedSpanNear | 546 | 530 | 462 | 🔴 0.85× | 🔴 0.87× |
| LongRange | 1,352 | 1,406 | 1,528 | 🟢 1.13× | 🟢 1.09× |
| FieldExistsFilter | 1,964 | 2,045 | 3,214 | 🟢 1.64× | 🟢 1.57× |
| Frange | 657 | 666 | 2,253 | 🟢 3.43× | 🟢 3.38× |
| NegativeFilter | 436 | 436 | 1,676 | 🟢 3.85× | 🟢 3.84× |
| SortLongFiltered | 864 | 861 | 1,346 | 🟢 1.56× | 🟢 1.56× |
| MultiKeySort | 538 | 564 | 630 | 🟢 1.17× | 🟢 1.12× |
| DeepPaging | 821 | 843 | 2,546 | 🟢 3.10× | 🟢 3.02× |
| LegacyFacetField | 714 | 747 | 1,011 | 🟢 1.42× | 🟢 1.35× |
| LegacyFacetRange | 730 | 714 | 995 | 🟢 1.36× | 🟢 1.39× |
| JsonQueryNestedFacets | 66.2 | 66.0 | 224 | 🟢 3.39× | 🟢 3.40× |
| FacetAggregations | 127 | 133 | 280 | 🟢 2.21× | 🟢 2.10× |
| Grouping | 580 | 597 | 491 | 🔴 0.85× | 🔴 0.82× |
| EdismaxComplex | 527 | 534 | 312 | 🔴 0.59× | 🔴 0.58× |
| EdismaxMinMatch | 754 | 771 | 578 | 🔴 0.77× | 🔴 0.75× |
| EdismaxPhraseBoost | 736 | 718 | 906 | 🟢 1.23× | 🟢 1.26× |
| SpellCheck | 713 | 685 | 658 | 🔴 0.92× | 🟡 0.96× |
| FacetTermsByAgg | 204 | 204 | 185 | 🔴 0.91× | 🔴 0.91× |
| FacetExcludeTags | 1,097 | 1,167 | 1,161 | 🟢 1.06× | 🟡 0.99× |
| FacetRangeNested | 286 | 286 | 252 | 🔴 0.88× | 🔴 0.88× |
| FacetRelatedness | 97.7 | 104 | 280 | 🟢 2.87× | 🟢 2.70× |
| LegacyMultiSelectFacets | 953 | 977 | 1,329 | 🟢 1.39× | 🟢 1.36× |
| StatsComponent | 75.6 | 76.3 | 102 | 🟢 1.35× | 🟢 1.33× |
| SurroundParser | 1,524 | 1,468 | 1,148 | 🔴 0.75× | 🔴 0.78× |
| BoolParser | 345 | 332 | 344 | 🟡 1.00× | 🟡 1.04× |
| ReRank | 615 | 572 | 552 | 🔴 0.90× | 🟡 0.96× |
| FunctionSort | 519 | 501 | 605 | 🟢 1.17× | 🟢 1.21× |
| PrefixTermFieldParsers | 3,984 | 4,422 | 2,718 | 🔴 0.68× | 🔴 0.61× |
| ExistsOnText | 1,789 | 1,729 | 4,842 | 🟢 2.71× | 🟢 2.80× |
| TimeAllowed | 662 | 611 | 575 | 🔴 0.87× | 🔴 0.94× |
| DebugExplain | 404 | 375 | 1,217 | 🟢 3.01× | 🟢 3.24× |
| TermsComponent | 261 | 262 | 252 | 🟡 0.97× | 🟡 0.96× |
| **Geometric mean, queries** | | | | **🟢 1.37×** | **🟢 1.37×** |
| Index size after indexing | 10.01 GB, 73 segments | 11.22 GB, 89 segments | 12.63 GB, 88 segments | | 1.13× larger |

### Coverage: e-commerce, 100M documents

**Solr+Luxir indexes 1.88× faster than Solr+Lucene with SM=off and answers queries 1.28× as fast (geometric mean of 3 categories): 3 faster, 0 about level, 0 slower.**

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|--:|--:|--:|--:|--:|
| Indexing (s) | 670 | 336 | 179 | 🟢 3.75× | 🟢 1.88× |
| FloatRangeSort | 238 | 219 | 262 | 🟢 1.10× | 🟢 1.20× |
| FloatStats | 256 | 233 | 254 | 🟡 0.99× | 🟢 1.09× |
| QueryFacets | 147 | 136 | 219 | 🟢 1.49× | 🟢 1.62× |
| **Geometric mean, queries** | | | | **🟢 1.18×** | **🟢 1.28×** |
| Index size after indexing | 9.36 GB, 52 segments | 9.75 GB, 61 segments | 14.17 GB, 55 segments | | 1.45× larger |

### Correctness: types

**Solr+Luxir indexes 1.14× faster than Solr+Lucene with SM=off and answers queries 1.26× as fast (geometric mean of 40 categories): 29 faster, 10 about level, 1 slower.** Slower: SpellCheckVariants.

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|--:|--:|--:|--:|--:|
| Indexing (s) | 20.4 | 12.4 | 10.9 | 🟢 1.87× | 🟢 1.14× |
| BooleanShapes | 1,762 | 1,849 | 2,503 | 🟢 1.42× | 🟢 1.35× |
| BoostAndFunctionQueries | 343 | 348 | 368 | 🟢 1.07× | 🟢 1.06× |
| CollapseExpand | 722 | 708 | 774 | 🟢 1.07× | 🟢 1.09× |
| DateMath | 5,664 | 6,017 | 8,877 | 🟢 1.57× | 🟢 1.48× |
| Dismax | 7,948 | 8,930 | 10,507 | 🟢 1.32× | 🟢 1.18× |
| EdismaxVariants | 4,382 | 4,812 | 6,712 | 🟢 1.53× | 🟢 1.39× |
| Elevation | 2,493 | 2,469 | 2,818 | 🟢 1.13× | 🟢 1.14× |
| Exists | 1,604 | 1,644 | 3,163 | 🟢 1.97× | 🟢 1.92× |
| FieldListFunctions | 3,281 | 3,171 | 4,394 | 🟢 1.34× | 🟢 1.39× |
| Frange | 4,555 | 4,502 | 4,597 | 🟡 1.01× | 🟡 1.02× |
| GroupingVariants | 311 | 331 | 414 | 🟢 1.33× | 🟢 1.25× |
| HighlightVariants | 3,259 | 3,300 | 3,509 | 🟢 1.08× | 🟢 1.06× |
| JoinGraphMlt | 1,528 | 1,512 | 1,556 | 🟡 1.02× | 🟡 1.03× |
| JsonAggregations | 86.6 | 85.6 | 123 | 🟢 1.42× | 🟢 1.44× |
| JsonQueryDsl | 8,187 | 9,488 | 9,591 | 🟢 1.17× | 🟡 1.01× |
| JsonRangeFacets | 1,105 | 1,100 | 3,130 | 🟢 2.83× | 🟢 2.85× |
| JsonTermsFacets | 231 | 234 | 257 | 🟢 1.11× | 🟢 1.10× |
| LegacyFacetFieldVariants | 221 | 217 | 219 | 🟡 0.99× | 🟡 1.01× |
| LegacyFacetQueryRange | 1,125 | 1,095 | 1,336 | 🟢 1.19× | 🟢 1.22× |
| LegacyPivotIntervalHeatmap | 949 | 919 | 1,002 | 🟢 1.06× | 🟢 1.09× |
| MultiTerm | 2,276 | 2,191 | 3,589 | 🟢 1.58× | 🟢 1.64× |
| NestedAndFilters | 3,208 | 3,464 | 3,606 | 🟢 1.12× | 🟡 1.04× |
| OtherParsers | 1,878 | 1,876 | 3,145 | 🟢 1.67× | 🟢 1.68× |
| Paging | 17.6 | 18.7 | 23.5 | 🟢 1.34× | 🟢 1.26× |
| Phrases | 11,353 | 17,682 | 19,873 | 🟢 1.75× | 🟢 1.12× |
| PureNegative | 1,077 | 1,025 | 1,416 | 🟢 1.31× | 🟢 1.38× |
| RangeCounts | 11,835 | 20,871 | 20,920 | 🟢 1.77× | 🟡 1.00× |
| RangePerType | 1,527 | 1,365 | 2,469 | 🟢 1.62× | 🟢 1.81× |
| RealTimeGet | 13,930 | 24,687 | 24,936 | 🟢 1.79× | 🟡 1.01× |
| RequestParams | 7,481 | 8,074 | 9,816 | 🟢 1.31× | 🟢 1.22× |
| SortFunctions | 878 | 869 | 940 | 🟢 1.07× | 🟢 1.08× |
| SortMultiValued | 418 | 406 | 400 | 🟡 0.96× | 🟡 0.99× |
| SortSingleValued | 1,033 | 1,006 | 2,053 | 🟢 1.99× | 🟢 2.04× |
| Spatial | 8,050 | 9,225 | 8,919 | 🟢 1.11× | 🟡 0.97× |
| SpellCheckVariants | 5,777 | 6,105 | 5,529 | 🟡 0.96× | 🔴 0.91× |
| StatsVariants | 196 | 196 | 268 | 🟢 1.37× | 🟢 1.37× |
| StreamingExpressions | 740 | 729 | 1,002 | 🟢 1.35× | 🟢 1.37× |
| TermPerType | 2,313 | 2,182 | 3,238 | 🟢 1.40× | 🟢 1.48× |
| TermTermsRawPrefix | 1,279 | 1,201 | 1,926 | 🟢 1.51× | 🟢 1.60× |
| TermsComponentVariants | 437 | 439 | 433 | 🟡 0.99× | 🟡 0.99× |
| **Geometric mean, queries** | | | | **🟢 1.32×** | **🟢 1.26×** |
| Index size after indexing | 1.06 GB, 35 segments | 1.11 GB, 44 segments | 1.28 GB, 30 segments | | 1.15× larger |

### Correctness: nested documents

**Solr+Luxir indexes 1.05× faster than Solr+Lucene with SM=off and answers queries 1.06× as fast (geometric mean of 7 categories): 4 faster, 1 about level, 2 slower.** Slower: BlockJoinFacets, ParentBlockJoin.

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|--:|--:|--:|--:|--:|
| Indexing (s) | 4.2 | 4.2 | 4.0 | 🟡 1.03× | 🟢 1.05× |
| BlockJoinFacets | 2,636 | 2,849 | 2,655 | 🟡 1.01× | 🔴 0.93× |
| ChildBlockJoin | 6,371 | 7,519 | 7,169 | 🟢 1.13× | 🟡 0.95× |
| ChildTransformer | 5,277 | 7,931 | 8,847 | 🟢 1.68× | 🟢 1.12× |
| FeaturesOverNested | 2,300 | 2,384 | 2,671 | 🟢 1.16× | 🟢 1.12× |
| NestPaths | 6,629 | 7,260 | 8,729 | 🟢 1.32× | 🟢 1.20× |
| ParentBlockJoin | 8,493 | 11,071 | 10,513 | 🟢 1.24× | 🔴 0.95× |
| ParentsByChildren | 923 | 948 | 1,095 | 🟢 1.19× | 🟢 1.16× |
| **Geometric mean, queries** | | | | **🟢 1.23×** | **🟢 1.06×** |
| Index size after indexing | 0.12 GB, 28 segments | 0.11 GB, 25 segments | 0.14 GB, 19 segments | | 1.25× larger |

### Correctness: vectors

**Solr+Luxir indexes 1.14× faster than Solr+Lucene with SM=off and answers queries 0.74× as fast (geometric mean of 9 categories): 0 faster, 3 about level, 6 slower.** Slower: KnnBasic, KnnExactSmallFilters, KnnFiltered, KnnHybrid, KnnParams, KnnQuantized.

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|--:|--:|--:|--:|--:|
| Indexing (s) | 24.4 | 23.9 | 21.0 | 🟢 1.16× | 🟢 1.14× |
| KnnBasic | 1,858 | 1,825 | 984 | 🔴 0.53× | 🔴 0.54× |
| KnnExactSmallFilters | 10,423 | 15,057 | 11,849 | 🟢 1.14× | 🔴 0.79× |
| KnnFiltered | 3,858 | 4,138 | 2,300 | 🔴 0.60× | 🔴 0.56× |
| KnnHybrid | 1,616 | 1,619 | 1,121 | 🔴 0.69× | 🔴 0.69× |
| KnnParams | 8,697 | 9,889 | 6,566 | 🔴 0.75× | 🔴 0.66× |
| KnnQuantized | 9,236 | 10,749 | 6,724 | 🔴 0.73× | 🔴 0.63× |
| VectorFields | 8,656 | 13,913 | 14,004 | 🟢 1.62× | 🟡 1.01× |
| VectorFunctions | 7,171 | 9,721 | 9,576 | 🟢 1.34× | 🟡 0.99× |
| VectorThreshold | 188 | 200 | 203 | 🟢 1.08× | 🟡 1.01× |
| **Geometric mean, queries** | | | | **🔴 0.88×** | **🔴 0.74×** |
| Index size after indexing | 0.83 GB, 51 segments | 0.82 GB, 51 segments | 0.89 GB, 69 segments | | 1.09× larger |

Vector search is not yet tuned in Solr+Luxir.

### Correctness: Solr's own field types

**Solr+Luxir indexes 1.01× faster than Solr+Lucene with SM=off and answers queries 1.07× as fast (geometric mean of 8 categories): 4 faster, 3 about level, 1 slower.** Slower: EnumField.

| Category | Stock Solr+Lucene | Solr+Lucene, SM=off | Solr+Luxir | Luxir vs stock | Luxir vs SM=off |
|---|--:|--:|--:|--:|--:|
| Indexing (s) | 5.5 | 4.7 | 4.6 | 🟢 1.20× | 🟡 1.01× |
| Currency | 2,205 | 2,337 | 2,254 | 🟡 1.02× | 🟡 0.96× |
| EnumField | 5,118 | 5,602 | 4,952 | 🟡 0.97× | 🔴 0.88× |
| LuceneAnalyzedText | 4,946 | 5,050 | 5,112 | 🟡 1.03× | 🟡 1.01× |
| Payloads | 9,776 | 11,938 | 13,750 | 🟢 1.41× | 🟢 1.15× |
| RankField | 1,417 | 1,449 | 1,513 | 🟢 1.07× | 🟡 1.04× |
| SortableText | 6,067 | 6,744 | 8,013 | 🟢 1.32× | 🟢 1.19× |
| TermVectorHighlighting | 4,885 | 4,737 | 5,394 | 🟢 1.10× | 🟢 1.14× |
| TermVectors | 8,507 | 8,371 | 10,561 | 🟢 1.24× | 🟢 1.26× |
| **Geometric mean, queries** | | | | **🟢 1.14×** | **🟢 1.07×** |
| Index size after indexing | 0.13 GB, 22 segments | 0.11 GB, 21 segments | 0.15 GB, 22 segments | | 1.38× larger |

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
| luxir | `luxir-lucene` | `21bfab5e` (Luxir `0791d83c` + the 4 patches in `luxir-lucene/luxir-patches/`) |
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
  stock Solr starts. The correctness datasets are generated locally first: `luxir-bench/<dataset>-dataset.py`.
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
