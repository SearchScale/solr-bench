# Solr+Lucene vs Solr+Luxir on geonames

The geonames workload from luxir-lucene (`bench/geonames`), run as solr-bench suites on a 3-node
SolrCloud: `suites/geonames-local.json` (Solr+Lucene) and `suites/luxir-geonames-local.json`
(Solr+Luxir). One run of each on an AMD Ryzen 9 7950X, 2026-10-25. The setup is the same as in
[luxir.md](luxir.md), with these builds:

- **Solr+Lucene:** Apache Solr `79b23df`, with Solr's security manager off, as on Solr+Luxir.
- **Solr+Luxir:** the SearchScale/solr `luxir-codec` branch at `35d1e2b`, which is Apache Solr
  `79b23df` plus the Luxir module, with Luxir `173ec324` (as in luxir.md) and luxir-lucene
  `ecd09a1`. (luxir.md's `31ae830` only adds date parsing, which this schema doesn't use.)
  luxir-lucene `39eedb6` fixed native search on the catch-all `_text_` field, which
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
| Indexing 11.4M documents | 49.2 s (231,700 docs/s) | 38.6 s (295,200 docs/s) | **1.27×** |
| Node restarts | 5.85 s, 5.86 s, 5.82 s | 9.93 s, 5.79 s, 5.94 s | |

Until 2026-10-24 Solr+Lucene ran with Solr's security manager on, which slowed its indexing (83.5 s) and its fast
queries: with it off, Solr+Lucene answers 23–36% more StringTerm, TermSortPop and text requests per second (two-term
OR: 9%). With it on, Solr+Luxir looked 1.26–1.49× faster on these; now they are about even. See [luxir.md](luxir.md#known-caveats).

Queries, 16 threads (throughput includes warm-up queries):

| Category | Throughput, Solr+Lucene | Throughput, Solr+Luxir | Ratio | p50, Solr+Lucene | p50, Solr+Luxir | p99, Solr+Lucene | p99, Solr+Luxir |
|---|---|---|---|---|---|---|---|
| MatchAll* | 244 q/s | 247 q/s | *1.01×* | 62.4 ms | 61.7 ms | 98.0 ms | 96.6 ms |
| StringTerm | 10,501 q/s | 10,454 q/s | **1.00×** | 1.29 ms | 1.26 ms | 6.33 ms | 6.76 ms |
| TextTerm | 10,756 q/s | 11,412 q/s | **1.06×** | 1.38 ms | 1.32 ms | 3.08 ms | 2.35 ms |
| TextPhrase | 10,394 q/s | 11,305 q/s | **1.09×** | 1.41 ms | 1.29 ms | 3.10 ms | 3.05 ms |
| TextOr | 5,642 q/s | 9,308 q/s | **1.65×** | 2.64 ms | 1.63 ms | 5.32 ms | 2.76 ms |
| TextAnd | 10,949 q/s | 11,190 q/s | **1.02×** | 1.42 ms | 1.38 ms | 2.32 ms | 2.22 ms |
| CatchAllText | 10,450 q/s | 11,006 q/s | **1.05×** | 1.43 ms | 1.41 ms | 3.13 ms | 2.10 ms |
| TextFiltered | 10,489 q/s | 10,341 q/s | **0.99×** | 1.46 ms | 1.54 ms | 2.94 ms | 2.73 ms |
| NumRange | 1,592 q/s | 9,987 q/s | **6.27×** | 5.02 ms | 1.50 ms | 60.3 ms | 2.75 ms |
| SortPopulation | 143 q/s | 349 q/s | **2.44×** | 108.6 ms | 45.0 ms | 155.4 ms | 65.8 ms |
| SortGeonameid | 167 q/s | 349 q/s | **2.08×** | 93.3 ms | 44.9 ms | 134.1 ms | 64.5 ms |
| TermSortPop | 9,354 q/s | 8,287 q/s | **0.89×** | 1.58 ms | 1.79 ms | 2.80 ms | 2.92 ms |
| CountryFacet | 180 q/s | 409 q/s | **2.27×** | 67.1 ms | 24.6 ms | 343.9 ms | 182.2 ms |
| HiCardFacet | 10.9 q/s | 11.2 q/s | **1.03×** | 1,161 ms | 1,216 ms | 2,552 ms | 1,804 ms |
| TermsPure | 51.5 q/s | 49.7 q/s | **0.96×** | 290.7 ms | 308.3 ms | 372.6 ms | 383.5 ms |
| TermsFiltered | 103 q/s | 103 q/s | **1.01×** | 152.0 ms | 152.4 ms | 174.1 ms | 179.9 ms |
| TermsProhibited | 54.3 q/s | 50.6 q/s | **0.93×** | 288.4 ms | 309.4 ms | 355.1 ms | 370.7 ms |
| All 212, mixed (30 s) | 427 q/s | 419 q/s | **0.98×** | 5.68 ms | 6.44 ms | 413.3 ms | 554.4 ms |

\* Not settled: across six runs on these and earlier builds, MatchAll has given 1.36×, 0.77×,
0.90×, 0.76×, 0.97× and now 1.01×, with Solr+Lucene between 197 and 280 q/s and Solr+Luxir between
213 and 268 q/s. On one test cluster, alternating the builds before and after `d78c3df` swung it by ±10% in
both directions; the changes do not touch its path (`*:*`, ranked, no facets or sort).

- **Faster on Solr+Luxir:** indexing (1.27×), numeric ranges (6.3× throughput, 22× lower p99),
  sorting all docs (2.1–2.4×), the country facet (2.27×) and two-term OR (1.65×).
- **Even:** the other text queries (0.99–1.09×), string terms (1.00×), and the `{!terms}` sets of
  45,700 names (0.93–1.01×), the same weak spot as in luxir-lucene's own results.
- **Slower on Solr+Luxir:** a term sorted by a field (TermSortPop, 0.89×); see below.
- **Mixed:** the 30-second mix of all 212 requests is even (0.98×). The `{!terms}` requests, 15 of
  212 but by far the slowest, dominate its time.
- **Errors:** one TextTerm request of 161,389 failed on Solr+Lucene: the node it was sent to got an
  `EOFException` reading shard2's response. None failed on Solr+Luxir.
- **Heap:** peak usage was 0.79–0.92 of 16 GB on Solr+Lucene and 0.77–0.86 on Solr+Luxir.
- **Restarts:** Solr+Luxir's first restart took 9.9 s, against 5.8–5.9 s for every other restart on
  both systems; its first restart has been the slow one in every run.

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
same or faster than before the fix. That comparison had Solr+Lucene's security manager on; with it off, as in the
results above, Solr+Lucene answers TermSortPop at 9,354 q/s and Solr+Luxir at 8,287 (0.89×), so it is again the
category where Solr+Luxir trails. Sorted requests match Solr+Lucene's order, and luxir-lucene's
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

Build Luxir and luxir-lucene as in [luxir.md](luxir.md), with luxir-lucene at `ecd09a1`, then
convert the corpus and run the two suites:

```bash
curl -O https://rally-tracks.elastic.co/geonames/documents-2.json.bz2
python3 luxir-bench/geonames-jsonl.py documents-2.json.bz2 suites/datasets/geonames.json.gz

./cleanup.sh && ./stress.sh -c 79b23df58daac14b92cc35f23b8b81f72098b4ba suites/geonames-local.json
./cleanup.sh && ./stress.sh -c 35d1e2b3871017184e90db8349c67801f898c519 suites/luxir-geonames-local.json
python3 luxir-bench/compare.py \
  suites/results/geonames-local/79b23df58daac14b92cc35f23b8b81f72098b4ba \
  suites/results/luxir-geonames-local/35d1e2b3871017184e90db8349c67801f898c519 Solr+Lucene Solr+Luxir
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
