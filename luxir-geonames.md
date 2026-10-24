# Solr+Lucene vs Solr+Luxir on geonames

The geonames workload from luxir-lucene (`bench/geonames`), run as solr-bench suites on a 3-node
SolrCloud: `suites/geonames-local.json` (Solr+Lucene) and `suites/luxir-geonames-local.json`
(Solr+Luxir). One run of each on an AMD Ryzen 9 7950X, 2026-10-24. The setup is the same as in
[luxir.md](luxir.md), with these builds:

- **Solr+Lucene:** Apache Solr `79b23df`.
- **Solr+Luxir:** the SearchScale/solr `luxir-codec` branch at `5bad8a1`, which is Apache Solr
  `79b23df` plus the Luxir module, with Luxir `13c80ecc` (as in luxir.md) and luxir-lucene
  `d78c3df`. luxir-lucene `39eedb6` fixed native search on the catch-all `_text_` field, which
  missed documents (see
  [Fixed: catch-all text missed documents](#fixed-catch-all-text-missed-documents)), and
  `d78c3df` made sorted queries faster (see
  [Fixed: a term sorted by a field was slower](#fixed-a-term-sorted-by-a-field-was-slower)).

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
| Indexing 11.4M documents | 83.5 s (136,400 docs/s) | 48.9 s (233,200 docs/s) | **1.71×** |
| Node restarts | 5.83 s, 5.82 s, 5.83 s | 7.88 s, 5.79 s, 5.81 s | |

Queries, 16 threads (throughput includes warm-up queries):

| Category | Throughput, Solr+Lucene | Throughput, Solr+Luxir | Ratio | p50, Solr+Lucene | p50, Solr+Luxir | p99, Solr+Lucene | p99, Solr+Luxir |
|---|---|---|---|---|---|---|---|
| MatchAll* | 245 q/s | 239 q/s | *0.97×* | 62.5 ms | 63.7 ms | 99.0 ms | 96.0 ms |
| StringTerm | 8,548 q/s | 11,614 q/s | **1.36×** | 1.63 ms | 1.16 ms | 7.06 ms | 6.03 ms |
| TextTerm | 7,959 q/s | 11,852 q/s | **1.49×** | 1.91 ms | 1.28 ms | 3.48 ms | 2.14 ms |
| TextPhrase | 8,092 q/s | 11,583 q/s | **1.43×** | 1.86 ms | 1.25 ms | 3.64 ms | 2.95 ms |
| TextOr | 5,191 q/s | 9,716 q/s | **1.87×** | 2.91 ms | 1.57 ms | 5.61 ms | 2.58 ms |
| TextAnd | 8,137 q/s | 11,694 q/s | **1.44×** | 1.91 ms | 1.32 ms | 3.13 ms | 2.06 ms |
| CatchAllText | 7,694 q/s | 11,412 q/s | **1.48×** | 1.99 ms | 1.35 ms | 3.76 ms | 2.03 ms |
| TextFiltered | 7,889 q/s | 10,900 q/s | **1.38×** | 1.98 ms | 1.47 ms | 3.51 ms | 2.49 ms |
| NumRange | 1,575 q/s | 10,716 q/s | **6.80×** | 5.24 ms | 1.41 ms | 58.7 ms | 2.45 ms |
| SortPopulation | 144 q/s | 349 q/s | **2.43×** | 108.7 ms | 45.1 ms | 151.7 ms | 65.6 ms |
| SortGeonameid | 144 q/s | 347 q/s | **2.40×** | 108.5 ms | 45.3 ms | 155.5 ms | 66.1 ms |
| TermSortPop | 6,954 q/s | 8,760 q/s | **1.26×** | 2.19 ms | 1.68 ms | 3.64 ms | 2.75 ms |
| CountryFacet | 179 q/s | 413 q/s | **2.31×** | 67.9 ms | 24.6 ms | 350.7 ms | 179.7 ms |
| HiCardFacet | 10.9 q/s | 11.4 q/s | **1.05×** | 1,228 ms | 1,195 ms | 2,551 ms | 1,887 ms |
| TermsPure | 53.2 q/s | 52.0 q/s | **0.98×** | 281.2 ms | 294.6 ms | 349.0 ms | 367.0 ms |
| TermsFiltered | 102 q/s | 103 q/s | **1.01×** | 152.6 ms | 152.4 ms | 188.3 ms | 177.8 ms |
| TermsProhibited | 56.5 q/s | 53.1 q/s | **0.94×** | 277.6 ms | 296.1 ms | 331.5 ms | 362.9 ms |
| All 212, mixed (30 s) | 421 q/s | 423 q/s | **1.01×** | 6.28 ms | 6.28 ms | 432.3 ms | 555.0 ms |

\* Not settled: across five runs on these and earlier builds, MatchAll has given 1.36×, 0.77×,
0.90×, 0.76× and now 0.97×, with Solr+Lucene between 197 and 280 q/s and Solr+Luxir between 213 and
268 q/s. On one test cluster, alternating the builds before and after `d78c3df` swung it by ±10% in
both directions; the changes do not touch its path (`*:*`, ranked, no facets or sort).

- **Faster on Solr+Luxir:** indexing (1.71×), numeric ranges (6.8× throughput, 24× lower p99),
  sorting all docs (2.4×), the country facet (2.31×), the text queries (1.38–1.87×), including the
  catch-all `_text_` field (1.48×), and a term sorted by a field (1.26×).
- **Even:** the `{!terms}` sets of 45,700 names (0.94–1.01×), the same weak spot as in luxir-lucene's
  own results.
- **Mixed:** the 30-second mix of all 212 requests is even (1.01×). The `{!terms}` requests, 15 of
  212 but by far the slowest, dominate its time.
- **Heap:** peak usage was 0.80–0.93 of 16 GB on Solr+Lucene and 0.74–0.94 on Solr+Luxir.
- **Restarts:** Solr+Luxir's first restart took 7.9 s, against 5.8 s for every other restart on both
  systems, as in every run.

## Fixed: a term sorted by a field was slower

Before luxir-lucene `d78c3df`, TermSortPop (a `country_code_raw` term sorted by `population`) was the
one category clearly slower on Solr+Luxir: 6,184 q/s against 7,200 (0.86×). On a test cluster under
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
same or faster than before the fix. Sorted requests match Solr+Lucene's order, and luxir-lucene's
tests compare both sort paths with Lucene's.

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

Build Luxir and luxir-lucene as in [luxir.md](luxir.md), with luxir-lucene at `d78c3df`, then
convert the corpus and run the two suites:

```bash
curl -O https://rally-tracks.elastic.co/geonames/documents-2.json.bz2
python3 luxir-bench/geonames-jsonl.py documents-2.json.bz2 suites/datasets/geonames.json.gz

./cleanup.sh && ./stress.sh -c 79b23df58daac14b92cc35f23b8b81f72098b4ba suites/geonames-local.json
./cleanup.sh && ./stress.sh -c 5bad8a159906e65ea0e29cd8104d2d79477d3c09 suites/luxir-geonames-local.json
python3 luxir-bench/compare.py \
  suites/results/geonames-local/79b23df58daac14b92cc35f23b8b81f72098b4ba \
  suites/results/luxir-geonames-local/5bad8a159906e65ea0e29cd8104d2d79477d3c09 Solr+Lucene Solr+Luxir
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
