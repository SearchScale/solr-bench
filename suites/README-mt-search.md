# ST vs MT search (many segments)

`multiThreaded=true` fans out over Lucene segments, so a merged index
doesn't show much. These suites disable merges and flush every 2000 docs
(`conf_ecommerce_noseg.zip`) to leave ~500 segments.

Need `solr-11.0.0-SNAPSHOT.tgz` in the repo root. Solr 11 also needs the
`--force` change in `LocalSolrNode.java` (already on this branch).

```bash
python3 suites/gen_mtbench_data.py 1000000 suites/mtbench-data.tsv
# queries are checked in; regenerate with gen_mtbench_queries.py if you want

./cleanup.sh
./stress.sh -c mt-seg-plain-false suites/mt-seg-plain-false.json
./stress.sh -c mt-seg-plain-true  suites/mt-seg-plain-true.json
./stress.sh -c mt-seg-facet-false suites/mt-seg-facet-false.json
./stress.sh -c mt-seg-facet-true  suites/mt-seg-facet-true.json
```

`plain` = range + filter. `facet` = same plus terms/avg facets.
`-Dsolr.searchThreads=-1` in all four.

Latency is in `suites/results/<name>/<name>/results.json` under
`task2[0].timings[0]`. While Solr is still up:

```bash
./suites/check-segments.sh 50000 mtbench-seg
```

Numbers from my box (1M docs, 2900 queries). Yours will differ; the
gap between ST and MT is the interesting part.

| | mean | p50 | p95 |
|---|---|---|---|
| plain ST | 4.55 | 2.75 | 21.56 |
| plain MT | 3.36 | 2.78 | 7.75 |
| facet ST | 15.79 | 12.22 | 38.28 |
| facet MT | 14.78 | 12.44 | 30.59 |
