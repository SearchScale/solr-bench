# Solr+Lucene vs Solr+Luxir on geonames

The geonames workload from luxir-lucene (`bench/geonames`), run as solr-bench suites on a 3-node
SolrCloud: `suites/geonames-local.json` (Solr+Lucene) and `suites/luxir-geonames-local.json`
(Solr+Luxir). One run of each on an AMD Ryzen 9 7950X, 2026-10-24. The setup is the same as in
[luxir.md](luxir.md), with these builds:

- **Solr+Lucene:** Apache Solr `79b23df`.
- **Solr+Luxir:** the SearchScale/solr `luxir-codec` branch at `11ab746`, which is Apache Solr
  `79b23df` plus the Luxir module, with Luxir `13c80ecc` (as in luxir.md) and luxir-lucene
  `39eedb6`. That luxir-lucene commit fixes native search on the catch-all `_text_` field, which
  missed documents (see
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
| Indexing 11.4M documents | 84.4 s (135,100 docs/s) | 48.4 s (235,400 docs/s) | **1.74×** |
| Node restarts | 5.87 s, 5.89 s, 5.78 s | 12.01 s, 5.84 s, 5.79 s | |

Queries, 16 threads (throughput includes warm-up queries):

| Category | Throughput, Solr+Lucene | Throughput, Solr+Luxir | Ratio | p50, Solr+Lucene | p50, Solr+Luxir | p99, Solr+Lucene | p99, Solr+Luxir |
|---|---|---|---|---|---|---|---|
| MatchAll* | 279 q/s | 251 q/s | *0.90×* | 54.2 ms | 61.1 ms | 91.9 ms | 95.1 ms |
| StringTerm | 8,480 q/s | 9,200 q/s | **1.08×** | 1.66 ms | 1.18 ms | 6.93 ms | 6.67 ms |
| TextTerm | 7,890 q/s | 10,966 q/s | **1.39×** | 1.91 ms | 1.26 ms | 3.72 ms | 2.12 ms |
| TextPhrase | 8,112 q/s | 11,154 q/s | **1.38×** | 1.85 ms | 1.25 ms | 3.61 ms | 2.99 ms |
| TextOr | 5,167 q/s | 9,169 q/s | **1.77×** | 2.93 ms | 1.57 ms | 5.59 ms | 2.54 ms |
| TextAnd | 8,150 q/s | 11,082 q/s | **1.36×** | 1.91 ms | 1.34 ms | 3.10 ms | 2.12 ms |
| CatchAllText | 7,676 q/s | 10,736 q/s | **1.40×** | 2.00 ms | 1.36 ms | 3.73 ms | 2.04 ms |
| TextFiltered | 7,893 q/s | 10,155 q/s | **1.29×** | 1.98 ms | 1.51 ms | 3.54 ms | 2.59 ms |
| NumRange | 1,683 q/s | 10,197 q/s | **6.06×** | 4.88 ms | 1.44 ms | 55.3 ms | 2.47 ms |
| SortPopulation | 146 q/s | 371 q/s | **2.54×** | 105.5 ms | 42.6 ms | 145.1 ms | 63.0 ms |
| SortGeonameid | 168 q/s | 358 q/s | **2.13×** | 93.8 ms | 43.9 ms | 133.9 ms | 64.5 ms |
| TermSortPop | 7,200 q/s | 6,184 q/s | **0.86×** | 2.12 ms | 2.15 ms | 3.52 ms | 3.42 ms |
| CountryFacet | 185 q/s | 364 q/s | **1.97×** | 66.1 ms | 28.1 ms | 324.0 ms | 191.4 ms |
| HiCardFacet | 10.8 q/s | 12.0 q/s | **1.11×** | 1,224 ms | 1,114 ms | 2,483 ms | 2,061 ms |
| TermsPure | 52.6 q/s | 51.1 q/s | **0.97×** | 283.8 ms | 297.9 ms | 369.8 ms | 387.8 ms |
| TermsFiltered | 102 q/s | 104 q/s | **1.02×** | 152.8 ms | 151.7 ms | 176.3 ms | 177.0 ms |
| TermsProhibited | 55.6 q/s | 52.8 q/s | **0.95×** | 281.3 ms | 296.9 ms | 340.6 ms | 358.6 ms |
| All 212, mixed (30 s) | 425 q/s | 426 q/s | **1.00×** | 6.12 ms | 6.15 ms | 439.3 ms | 566.6 ms |

\* Not settled: three runs have given three different results. Before the `_text_` fix (which
`*:*` does not reach), on Solr `63f2459`, it was 197 q/s on Solr+Lucene against 268 q/s on
Solr+Luxir (1.36×); after the fix, on the same Solr, 280 against 216 (0.77×); and on `79b23df`,
279 against 251 (0.90×). Every other category's ratio stayed within 0.1× across the runs after the
fix, apart from SortGeonameid (2.36× before the move to `79b23df`, when Solr+Lucene did 153 q/s).

- **Faster on Solr+Luxir:** indexing (1.74×), numeric ranges (6.1× throughput, 22× lower p99),
  sorting all docs (2.1–2.5×), the country facet (1.97×), and the text queries (1.29–1.77×),
  including the catch-all `_text_` field (1.40×).
- **Slower on Solr+Luxir:** a term sorted by a field (0.86×) and the `{!terms}` sets of 45,700
  names (0.95–1.02×). These are the same weak spots as in luxir-lucene's own results.
- **Mixed:** the 30-second mix of all 212 requests is even (1.00×). The `{!terms}` requests, 15 of
  212 but by far the slowest, dominate its time.
- **Heap:** peak usage was 0.85–0.90 of 16 GB on Solr+Lucene and 0.77–0.95 on Solr+Luxir.
- **Restarts:** Solr+Luxir's first restart took 12.0 s, against 5.8–5.9 s for every other restart
  on both systems, as in every run.

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

Build Luxir and luxir-lucene as in [luxir.md](luxir.md), with luxir-lucene at `39eedb6`, then convert the corpus and run
the two suites:

```bash
curl -O https://rally-tracks.elastic.co/geonames/documents-2.json.bz2
python3 luxir-bench/geonames-jsonl.py documents-2.json.bz2 suites/datasets/geonames.json.gz

./cleanup.sh && ./stress.sh -c 79b23df58daac14b92cc35f23b8b81f72098b4ba suites/geonames-local.json
./cleanup.sh && ./stress.sh -c 11ab746c92bf84dd6872d34d9beda64ad3d4d3bd suites/luxir-geonames-local.json
python3 luxir-bench/compare.py \
  suites/results/geonames-local/79b23df58daac14b92cc35f23b8b81f72098b4ba \
  suites/results/luxir-geonames-local/11ab746c92bf84dd6872d34d9beda64ad3d4d3bd Solr+Lucene Solr+Luxir
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
