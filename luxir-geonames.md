# Solr+Lucene vs Solr+Luxir on geonames

The geonames workload from luxir-lucene (`bench/geonames`), run as solr-bench suites on a 3-node
SolrCloud: `suites/geonames-local.json` (Solr+Lucene) and `suites/luxir-geonames-local.json`
(Solr+Luxir). One run of each on an AMD Ryzen 9 7950X, 2026-10-24. The setup and builds are the
same as in [luxir.md](luxir.md).

**Correctness caveat:** on a multi-segment index, Solr+Luxir's native search on the catch-all
`_text_` field misses documents, so its CatchAllText numbers are not valid. See
[Known issue](#known-issue-catch-all-text-misses-documents).

## The workload

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

## Results

| | Solr+Lucene | Solr+Luxir | Solr+Luxir better by |
|---|---|---|---|
| Indexing 11.4M documents | 83.9 s (135,900 docs/s) | 48.5 s (235,200 docs/s) | **1.73×** |
| Node restarts | 5.80 s, 5.83 s, 5.78 s | 12.01 s, 5.86 s, 5.82 s | |

Queries, 16 threads (throughput includes warm-up queries):

| Category | Throughput, Solr+Lucene | Throughput, Solr+Luxir | Ratio | p50, Solr+Lucene | p50, Solr+Luxir | p99, Solr+Lucene | p99, Solr+Luxir |
|---|---|---|---|---|---|---|---|
| MatchAll | 197 q/s | 268 q/s | **1.36×** | 79.1 ms | 57.1 ms | 112.0 ms | 91.9 ms |
| StringTerm | 8,610 q/s | 8,734 q/s | **1.01×** | 1.60 ms | 1.19 ms | 7.57 ms | 6.99 ms |
| TextTerm | 8,301 q/s | 11,004 q/s | **1.33×** | 1.83 ms | 1.28 ms | 3.46 ms | 2.06 ms |
| TextPhrase | 8,470 q/s | 11,163 q/s | **1.32×** | 1.77 ms | 1.25 ms | 3.48 ms | 2.93 ms |
| TextOr | 5,473 q/s | 9,128 q/s | **1.67×** | 2.76 ms | 1.58 ms | 5.26 ms | 2.78 ms |
| TextAnd | 8,572 q/s | 11,200 q/s | **1.31×** | 1.82 ms | 1.34 ms | 2.91 ms | 2.11 ms |
| CatchAllText* | 8,033 q/s | 11,099 q/s | *1.38×* | 1.90 ms | 1.31 ms | 3.50 ms | 1.97 ms |
| TextFiltered | 8,192 q/s | 10,216 q/s | **1.25×** | 1.90 ms | 1.50 ms | 3.36 ms | 2.60 ms |
| NumRange | 1,613 q/s | 10,511 q/s | **6.52×** | 5.12 ms | 1.39 ms | 57.55 ms | 2.54 ms |
| SortPopulation | 140 q/s | 376 q/s | **2.70×** | 111.8 ms | 41.7 ms | 153.9 ms | 63.4 ms |
| SortGeonameid | 150 q/s | 371 q/s | **2.48×** | 105.6 ms | 42.3 ms | 146.0 ms | 62.0 ms |
| TermSortPop | 7,047 q/s | 6,194 q/s | **0.88×** | 2.16 ms | 2.14 ms | 3.56 ms | 3.41 ms |
| CountryFacet | 180 q/s | 378 q/s | **2.10×** | 68.0 ms | 28.0 ms | 348.1 ms | 180.8 ms |
| HiCardFacet | 10.7 q/s | 11.9 q/s | **1.11×** | 1,166 ms | 1,141 ms | 2,091 ms | 2,051 ms |
| TermsPure | 54.6 q/s | 48.7 q/s | **0.89×** | 273.0 ms | 312.0 ms | 351.4 ms | 390.4 ms |
| TermsFiltered | 103.9 q/s | 102.6 q/s | **0.99×** | 150.4 ms | 152.7 ms | 171.3 ms | 179.2 ms |
| TermsProhibited | 57.8 q/s | 50.4 q/s | **0.87×** | 271.4 ms | 311.5 ms | 321.4 ms | 371.3 ms |
| All 212, mixed (30 s) | 427 q/s | 418 q/s | **0.98×** | 6.14 ms | 6.52 ms | 409.5 ms | 556.3 ms |

\* Not valid: Solr+Luxir returns too few documents for some of these requests (see below).

- **Faster on Solr+Luxir:** indexing (1.73×), numeric ranges (6.5× throughput, 23× lower p99),
  sorting all docs (2.5–2.7×), the country facet (2.1×), and most text queries (1.25–1.67×).
- **Slower on Solr+Luxir:** the three `{!terms}` categories with 45,700 names (0.87–0.99×) and a
  term sorted by a field (0.88×). These are the same weak spots as in luxir-lucene's own results.
- **Mixed:** the 30-second mix of all 212 requests is even (0.98×). The `{!terms}` requests, 15 of
  212 but by far the slowest, dominate its time.
- **Heap:** peak usage was 0.86–0.92 of 16 GB on Solr+Lucene and 0.78–0.95 on Solr+Luxir.
- **Restarts:** Solr+Luxir's first restart took 12.0 s, including an 8.3 s shutdown. The other
  restarts on both systems took 5.8–5.9 s.

## Known issue: catch-all text misses documents

Before benchmarking, both systems' indexes were loaded with the same data (in separate test
clusters), and all 212 requests compared with `luxir-bench/geonames-verify.py`. Everything matched
except CatchAllText: 8 of its 20 requests returned fewer documents on Solr+Luxir, for example
`_text_:creek` 229,122 against 242,460 and `_text_:hammam` 498 against 532.

- **Native search only.** On the same Solr+Luxir index, Luxir's Java path (`luxirCodec=false`)
  returns the full counts, so the index is right and the native query path is wrong.
- **Particular segments.** Per segment, native search misses some or all of a term's documents in
  a few segments (merged and flushed alike) and is right in the rest. A tiny index with the missed
  documents is right.
- **Gone after a full merge.** After merging the index to one segment, native and Java agree. This
  is the layout luxir-lucene's own geonames check used, which is why it passed there.
- **Not new.** It shows with upstream Luxir `8cb622ba` without the four patches, with the previous
  base (`48a10abe`), and with the luxir-lucene and Solr module builds from before the faster
  filters and native joins (luxir-lucene `e2c5039`, Solr `d2d7cf1`).

Other text fields (`name`, `asciiname`, `alternatenames`) matched on the same index.

## Reproduce

Build as in [luxir.md](luxir.md), then convert the corpus and run the two suites:

```bash
curl -O https://rally-tracks.elastic.co/geonames/documents-2.json.bz2
python3 luxir-bench/geonames-jsonl.py documents-2.json.bz2 suites/datasets/geonames.json.gz

./cleanup.sh && ./stress.sh -c 63f2459f3b58861de8575ecbfbefc38281482f3a suites/geonames-local.json
./cleanup.sh && ./stress.sh -c c9e21f7c6ae20a21d3e97795896127ed5e7b62f4 suites/luxir-geonames-local.json
python3 luxir-bench/compare.py \
  suites/results/geonames-local/63f2459f3b58861de8575ecbfbefc38281482f3a \
  suites/results/luxir-geonames-local/c9e21f7c6ae20a21d3e97795896127ed5e7b62f4 Solr+Lucene Solr+Luxir
```

## solr-bench changes for this suite

- **`http-method` for query tasks:** `POST` sends URL-parameter queries in the request body, for
  requests too long for a URL.
- **URL-parameter queries work again:** their responses are now read as a stream, as JSON queries'
  are. Before, every such query failed with `NullPointerException: inputStream`.
- **No throughput cap for fast queries:** with 10 requests pending per client thread, the
  submitter waited 100 ms before sending more, which capped any task at about 1,600 queries/s.
  It now waits 1 ms. The e-commerce suites stayed under the cap (at most about 500 queries/s), so
  their results are unaffected.
