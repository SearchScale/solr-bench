# Solr+Lucene vs Solr+Luxir on geonames

The geonames workload from luxir-lucene (`bench/geonames`), run as solr-bench suites on a 3-node
SolrCloud: `suites/geonames-local.json` (Solr+Lucene) and `suites/luxir-geonames-local.json`
(Solr+Luxir). One run of each on an AMD Ryzen 9 7950X, 2026-10-24. The setup and builds are the
same as in [luxir.md](luxir.md), except luxir-lucene, which is at `39eedb6`: that commit fixes
native search on the catch-all `_text_` field, which missed documents (see
[Fixed: catch-all text missed documents](#fixed-catch-all-text-missed-documents)).

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
| Indexing 11.4M documents | 84.2 s (135,400 docs/s) | 48.4 s (235,600 docs/s) | **1.74×** |
| Node restarts | 5.82 s, 5.79 s, 5.78 s | 11.98 s, 5.78 s, 5.89 s | |

Queries, 16 threads (throughput includes warm-up queries):

| Category | Throughput, Solr+Lucene | Throughput, Solr+Luxir | Ratio | p50, Solr+Lucene | p50, Solr+Luxir | p99, Solr+Lucene | p99, Solr+Luxir |
|---|---|---|---|---|---|---|---|
| MatchAll* | 280 q/s | 216 q/s | *0.77×* | 54.5 ms | 71.2 ms | 91.5 ms | 105.3 ms |
| StringTerm | 8,603 q/s | 9,113 q/s | **1.06×** | 1.64 ms | 1.19 ms | 6.31 ms | 6.62 ms |
| TextTerm | 7,968 q/s | 11,041 q/s | **1.39×** | 1.92 ms | 1.28 ms | 3.31 ms | 2.18 ms |
| TextPhrase | 8,036 q/s | 11,100 q/s | **1.38×** | 1.87 ms | 1.25 ms | 3.62 ms | 2.94 ms |
| TextOr | 5,155 q/s | 9,129 q/s | **1.77×** | 2.94 ms | 1.57 ms | 5.52 ms | 2.77 ms |
| TextAnd | 8,100 q/s | 11,157 q/s | **1.38×** | 1.92 ms | 1.34 ms | 3.10 ms | 2.14 ms |
| CatchAllText | 7,672 q/s | 10,667 q/s | **1.39×** | 1.99 ms | 1.37 ms | 3.77 ms | 2.06 ms |
| TextFiltered | 7,898 q/s | 10,270 q/s | **1.30×** | 1.98 ms | 1.50 ms | 3.46 ms | 2.57 ms |
| NumRange | 1,616 q/s | 10,050 q/s | **6.22×** | 5.11 ms | 1.44 ms | 57.0 ms | 2.69 ms |
| SortPopulation | 142 q/s | 369 q/s | **2.61×** | 110.2 ms | 42.5 ms | 157.3 ms | 63.5 ms |
| SortGeonameid | 153 q/s | 361 q/s | **2.36×** | 104.1 ms | 43.7 ms | 141.3 ms | 63.0 ms |
| TermSortPop | 6,949 q/s | 6,140 q/s | **0.88×** | 2.18 ms | 2.18 ms | 3.61 ms | 3.43 ms |
| CountryFacet | 181 q/s | 372 q/s | **2.05×** | 67.4 ms | 27.9 ms | 337.8 ms | 183.6 ms |
| HiCardFacet | 10.8 q/s | 11.9 q/s | **1.11×** | 1,199 ms | 1,140 ms | 2,597 ms | 1,812 ms |
| TermsPure | 52.6 q/s | 51.0 q/s | **0.97×** | 283.7 ms | 301.1 ms | 366.8 ms | 383.6 ms |
| TermsFiltered | 103 q/s | 103 q/s | **1.00×** | 151.7 ms | 152.8 ms | 173.3 ms | 177.2 ms |
| TermsProhibited | 55.8 q/s | 51.9 q/s | **0.93×** | 281.4 ms | 301.8 ms | 340.4 ms | 355.7 ms |
| All 212, mixed (30 s) | 426 q/s | 419 q/s | **0.98×** | 6.20 ms | 6.35 ms | 423.0 ms | 562.5 ms |

\* Not settled: an earlier run on the same builds (apart from the `_text_` fix, which `*:*` does
not reach) gave the opposite result, 197 q/s on Solr+Lucene and 268 q/s on Solr+Luxir (1.36×).
Every other category's throughput was within 6% of that run.

- **Faster on Solr+Luxir:** indexing (1.74×), numeric ranges (6.2× throughput, 21× lower p99),
  sorting all docs (2.4–2.6×), the country facet (2.05×), and the text queries (1.30–1.77×),
  including the catch-all `_text_` field (1.39×).
- **Slower on Solr+Luxir:** a term sorted by a field (0.88×) and the `{!terms}` sets of 45,700
  names (0.93–1.00×). These are the same weak spots as in luxir-lucene's own results.
- **Mixed:** the 30-second mix of all 212 requests is even (0.98×). The `{!terms}` requests, 15 of
  212 but by far the slowest, dominate its time.
- **Heap:** peak usage was 0.79–0.91 of 16 GB on Solr+Lucene and 0.76–0.97 on Solr+Luxir.
- **Restarts:** Solr+Luxir's first restart took 12.0 s, against 5.8–5.9 s for every other restart
  on both systems.

## Fixed: catch-all text missed documents

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

## Reproduce

Build as in [luxir.md](luxir.md), with luxir-lucene at `39eedb6`, then convert the corpus and run
the two suites:

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
