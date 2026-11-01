#!/usr/bin/env python3
"""Configsets for the correctness collections, for Solr+Lucene and Solr+Luxir: the geonames ones with the
geonames fields replaced by the dataset's, spell checking on its text, and a query elevation handler
(/elevate). Writes suites/configsets/conf_<dataset>.zip and conf_<dataset>_luxir.zip for
  types   (types-dataset.py):  one field of each type and shape
  nested  (nested-dataset.py): country, state and place blocks (_root_, _nest_path_)
  vectors (vectors-dataset.py): places with dense vectors of every kind
  features (features-dataset.py): Solr's own types (payloads, term vectors, enum, rank, currency,
          sortable text) and components (term vectors, suggesters) in a Luxir collection
Usage: luxir-bench/correctness-configsets.py   (from the solr-bench directory)"""
import io
import re
import zipfile

TYPES = """  <!-- Workload fields: one of each type and shape (types-dataset.py) -->
  <field name="t_s" type="text_general" indexed="true" stored="true" multiValued="false" />
  <field name="t_m" type="text_general" indexed="true" stored="true" multiValued="true" />
  <field name="s_s" type="string" indexed="true" stored="true" />
  <field name="s_m" type="string" indexed="true" stored="true" multiValued="true" />
  <field name="s_sp" type="string" indexed="true" stored="true" />
  <field name="i_s" type="pint" indexed="true" stored="true" />
  <field name="i_m" type="pint" indexed="true" stored="true" multiValued="true" />
  <field name="i_sp" type="pint" indexed="true" stored="true" />
  <field name="l_s" type="plong" indexed="true" stored="true" />
  <field name="l_m" type="plong" indexed="true" stored="true" multiValued="true" />
  <field name="f_s" type="pfloat" indexed="true" stored="true" />
  <field name="f_m" type="pfloat" indexed="true" stored="true" multiValued="true" />
  <field name="d_s" type="pdouble" indexed="true" stored="true" />
  <field name="d_sp" type="pdouble" indexed="true" stored="true" />
  <field name="dt_s" type="pdate" indexed="true" stored="true" />
  <field name="dt_m" type="pdate" indexed="true" stored="true" multiValued="true" />
  <field name="b_s" type="boolean" indexed="true" stored="true" docValues="true" />
  <field name="ll" type="location" indexed="true" stored="true" />
  <field name="rpt" type="location_rpt" indexed="true" stored="true" />
  <field name="i_dv" type="pint" indexed="false" stored="false" docValues="true" />

"""
TYPES_COPY = ["t_s", "t_m"]
NESTED = """  <!-- Workload fields: country, state and place blocks (nested-dataset.py) -->
  <fieldType name="nest_path" class="solr.NestPathField" />
  <field name="_nest_path_" type="nest_path" />
  <field name="doc_type" type="string" indexed="true" stored="true" />
  <field name="code" type="string" indexed="true" stored="true" />
  <field name="name" type="text_general" indexed="true" stored="true" multiValued="false" />
  <field name="name_s" type="string" indexed="true" stored="true" />
  <field name="alt" type="text_general" indexed="true" stored="true" multiValued="true" />
  <field name="feature_class" type="string" indexed="true" stored="true" />
  <field name="timezone" type="string" indexed="true" stored="true" />
  <field name="population" type="plong" indexed="true" stored="true" />
  <field name="num_places" type="pint" indexed="true" stored="true" />
  <field name="geonameid" type="plong" indexed="true" stored="true" />
  <field name="elevation" type="pint" indexed="true" stored="true" />
  <field name="location" type="location" indexed="true" stored="true" />

"""
NESTED_COPY = ["name", "alt"]
VECTORS = """  <!-- Workload fields: places with dense vectors from their names (vectors-dataset.py) -->
  <fieldType name="knn_cos" class="solr.DenseVectorField" vectorDimension="64" similarityFunction="cosine" />
  <fieldType name="knn_dot" class="solr.DenseVectorField" vectorDimension="64" similarityFunction="dot_product" />
  <fieldType name="knn_l2" class="solr.DenseVectorField" vectorDimension="32" similarityFunction="euclidean"
             hnswM="12" hnswEfConstruction="80" />
  <fieldType name="knn_b" class="solr.DenseVectorField" vectorDimension="16" similarityFunction="euclidean"
             vectorEncoding="BYTE" />
  <fieldType name="knn_sq" class="solr.ScalarQuantizedDenseVectorField" vectorDimension="64"
             similarityFunction="cosine" />
  <fieldType name="knn_bq" class="solr.BinaryQuantizedDenseVectorField" vectorDimension="64"
             similarityFunction="cosine" />
  <field name="v" type="knn_cos" indexed="true" stored="true" />
  <field name="v_dot" type="knn_dot" indexed="true" stored="false" />
  <field name="v_l2" type="knn_l2" indexed="true" stored="true" />
  <field name="v_b" type="knn_b" indexed="true" stored="true" />
  <field name="v_sq" type="knn_sq" indexed="true" stored="false" />
  <field name="v_bq" type="knn_bq" indexed="true" stored="false" />
  <field name="name" type="text_general" indexed="true" stored="true" multiValued="false" />
  <field name="cc" type="string" indexed="true" stored="true" />
  <field name="fclass" type="string" indexed="true" stored="true" />
  <field name="pop" type="plong" indexed="true" stored="true" />
  <field name="elev" type="pint" indexed="true" stored="true" />

"""
FEATURES = """  <!-- Workload fields: Solr's own types in a Luxir collection (features-dataset.py) -->
  <fieldType name="text_en" class="solr.TextField" positionIncrementGap="100">
    <analyzer>
      <tokenizer class="solr.StandardTokenizerFactory" />
      <filter class="solr.LowerCaseFilterFactory" />
      <filter class="solr.EnglishPossessiveFilterFactory" />
      <filter class="solr.PorterStemFilterFactory" />
    </analyzer>
  </fieldType>
  <fieldType name="text_sort" class="solr.SortableTextField">
    <analyzer>
      <tokenizer class="solr.StandardTokenizerFactory" />
      <filter class="solr.LowerCaseFilterFactory" />
    </analyzer>
  </fieldType>
  <fieldType name="delimited_payloads_float" class="solr.TextField" indexed="true" stored="false">
    <analyzer>
      <tokenizer class="solr.WhitespaceTokenizerFactory" />
      <filter class="solr.DelimitedPayloadTokenFilterFactory" encoder="float" />
    </analyzer>
  </fieldType>
  <fieldType name="fclass_enum" class="solr.EnumFieldType" docValues="true" enumsConfig="enumsConfig.xml" enumName="fclass" />
  <fieldType name="rank" class="solr.RankField" />
  <fieldType name="currency" class="solr.CurrencyFieldType" amountLongSuffix="_l_ns" codeStrSuffix="_s_ns"
             defaultCurrency="USD" currencyConfig="currency.xml" />
  <dynamicField name="*_txt_en" type="text_en" indexed="true" stored="true" />
  <dynamicField name="*_l_ns" type="plong" indexed="true" stored="false" />
  <dynamicField name="*_s_ns" type="string" indexed="true" stored="false" />
  <field name="name" type="text_general" indexed="true" stored="true" multiValued="false" />
  <field name="name_nf" type="text_en" indexed="true" stored="false" omitTermFreqAndPositions="true" />
  <field name="name_nn" type="text_en" indexed="true" stored="false" omitNorms="true" />
  <field name="name_sort" type="text_sort" indexed="true" stored="true" />
  <field name="name_s" type="string" indexed="true" stored="true" />
  <field name="desc_tv" type="text_en" indexed="true" stored="true" termVectors="true" termPositions="true"
         termOffsets="true" termPayloads="false" />
  <field name="tags_dpf" type="delimited_payloads_float" indexed="true" stored="false" />
  <field name="fclass_enum" type="fclass_enum" indexed="true" stored="true" />
  <field name="pop_rank" type="rank" />
  <field name="price_c" type="currency" indexed="true" stored="true" />
  <field name="cc" type="string" indexed="true" stored="true" />
  <field name="pop" type="plong" indexed="true" stored="true" />
  <field name="sw" type="plong" indexed="true" stored="true" />
  <field name="elev" type="pint" indexed="true" stored="true" />

"""
FEATURES_CONFIG = """  <searchComponent name="tvComponent" class="solr.TermVectorComponent" />
  <requestHandler name="/tvrh" class="solr.SearchHandler">
    <lst name="defaults">
      <bool name="tv">true</bool>
    </lst>
    <arr name="last-components">
      <str>tvComponent</str>
    </arr>
  </requestHandler>
  <searchComponent name="suggest" class="solr.SuggestComponent">
    <lst name="suggester">
      <str name="name">fuzzy</str>
      <str name="lookupImpl">FuzzyLookupFactory</str>
      <str name="dictionaryImpl">DocumentDictionaryFactory</str>
      <str name="field">name_s</str>
      <str name="weightField">sw</str>
      <str name="suggestAnalyzerFieldType">string</str>
      <str name="buildOnStartup">false</str>
    </lst>
    <lst name="suggester">
      <str name="name">infix</str>
      <str name="lookupImpl">AnalyzingInfixLookupFactory</str>
      <str name="dictionaryImpl">DocumentDictionaryFactory</str>
      <str name="field">name_txt_en</str>
      <str name="weightField">sw</str>
      <str name="suggestAnalyzerFieldType">text_en</str>
      <str name="buildOnStartup">false</str>
    </lst>
  </searchComponent>
  <requestHandler name="/suggest" class="solr.SearchHandler">
    <lst name="defaults">
      <str name="suggest">true</str>
      <str name="suggest.count">10</str>
    </lst>
    <arr name="components">
      <str>suggest</str>
    </arr>
  </requestHandler>
"""
USD_RATE = {"USD": 1.0, "EUR": 0.9, "GBP": 0.8, "JPY": 150.0}
FEATURES_FILES = {
    "enumsConfig.xml": '<?xml version="1.0" ?>\n<enumsConfig>\n  <enum name="fclass">\n'
                       + "".join(f"    <value>{v}</value>\n" for v in ["A", "H", "L", "P", "R", "S", "T", "U", "V"])
                       + "  </enum>\n</enumsConfig>\n",
    # every pair: Solr converts only along a rate it is given
    "currency.xml": '<?xml version="1.0" ?>\n<currencyConfig version="1.0">\n  <rates>\n'
                    + "".join(f'    <rate from="{a}" to="{b}" rate="{USD_RATE[b] / USD_RATE[a]:.6f}" />\n'
                              for a in USD_RATE for b in USD_RATE if a != b)
                    + '  </rates>\n</currencyConfig>\n',
}
# per dataset: schema fields, copyField sources, the spell checker's field, solrconfig additions, files
DATASETS = {"types": (TYPES, TYPES_COPY, "t_s", "", {}), "nested": (NESTED, NESTED_COPY, "name", "", {}),
            "vectors": (VECTORS, ["name"], "name", "", {}),
            "features": (FEATURES, ["name"], "name", FEATURES_CONFIG, FEATURES_FILES)}


def copies(fields):
    return ("  <!-- Copy field for default search -->\n"
            + "".join(f'  <copyField source="{f}" dest="_text_" />\n' for f in fields) + "</schema>\n")
LOCATION = """  <!-- Spatial: lat/lon points -->
  <fieldType name="location" class="solr.LatLonPointSpatialField" docValues="true" />
"""
ELEVATE = """  <searchComponent name="elevator" class="solr.QueryElevationComponent">
    <str name="queryFieldType">string</str>
    <str name="config-file">elevate.xml</str>
  </searchComponent>
  <requestHandler name="/elevate" class="solr.SearchHandler">
    <lst name="defaults">
      <str name="echoParams">explicit</str>
    </lst>
    <arr name="last-components">
      <str>elevator</str>
    </arr>
  </requestHandler>
"""


def convert(src, dst, dataset):
    fields, copy, spell, config, files = DATASETS[dataset]
    zin = zipfile.ZipFile(src)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename).decode()
            if item.filename.endswith("schema.xml"):
                data = re.sub(r"  <!-- Workload fields -->.*?(?=  <!-- Unique Key -->)", fields, data, flags=re.S)
                data = re.sub(r"  <!-- Copy Fields for Multi-Field Support -->.*", copies(copy), data, flags=re.S)
                data = data.replace("  <!-- Spatial: lat/lon point -->", LOCATION + "  <!-- Spatial: lat/lon point -->")
                assert 'name="location"' in data and "name_raw" not in data, src
            elif item.filename.endswith("solrconfig.xml"):
                data = data.replace('<str name="field">name</str>', f'<str name="field">{spell}</str>')
                data = data.replace('<str name="df">name</str>', f'<str name="df">{spell}</str>')
                data = data.replace('  <searchComponent name="terms"', ELEVATE + config + '  <searchComponent name="terms"')
                assert "/elevate" in data and f'<str name="field">{spell}</str>' in data, src
            zout.writestr(item.filename, data)
        zout.writestr("elevate.xml", '<?xml version="1.0" encoding="UTF-8" ?>\n<elevate>\n</elevate>\n')
        for name, text in files.items():
            zout.writestr(name, text)
    open(dst, "wb").write(buf.getvalue())
    print("wrote", dst)


for dataset in DATASETS:
    convert("suites/configsets/conf_geonames.zip", f"suites/configsets/conf_{dataset}.zip", dataset)
    convert("suites/configsets/conf_geonames_luxir.zip", f"suites/configsets/conf_{dataset}_luxir.zip", dataset)
