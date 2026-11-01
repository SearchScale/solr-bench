#!/usr/bin/env python3
"""Configsets for the "types" correctness collection (see types-dataset.py): the geonames ones, for
Solr+Lucene and Solr+Luxir, with the geonames fields replaced by one field of each type and shape,
spell checking on t_s, and a query elevation handler (/elevate). Writes
suites/configsets/conf_types.zip and conf_types_luxir.zip.
Usage: luxir-bench/types-configsets.py   (from the solr-bench directory)"""
import io
import re
import zipfile

FIELDS = """  <!-- Workload fields: one of each type and shape (types-dataset.py) -->
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
COPY = """  <!-- Copy field for default search -->
  <copyField source="t_s" dest="_text_" />
  <copyField source="t_m" dest="_text_" />
</schema>
"""
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


def convert(src, dst):
    zin = zipfile.ZipFile(src)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename).decode()
            if item.filename.endswith("schema.xml"):
                data = re.sub(r"  <!-- Workload fields -->.*?(?=  <!-- Unique Key -->)", FIELDS, data, flags=re.S)
                data = re.sub(r"  <!-- Copy Fields for Multi-Field Support -->.*", COPY, data, flags=re.S)
                data = data.replace("  <!-- Spatial: lat/lon point -->", LOCATION + "  <!-- Spatial: lat/lon point -->")
                assert 'name="i_dv"' in data and 'name="location"' in data and "name_raw" not in data, src
            elif item.filename.endswith("solrconfig.xml"):
                data = data.replace('<str name="field">name</str>', '<str name="field">t_s</str>')
                data = data.replace('<str name="df">name</str>', '<str name="df">t_s</str>')
                data = data.replace('  <searchComponent name="terms"', ELEVATE + '  <searchComponent name="terms"')
                assert "/elevate" in data and '<str name="field">t_s</str>' in data, src
            zout.writestr(item.filename, data)
        zout.writestr("elevate.xml", '<?xml version="1.0" encoding="UTF-8" ?>\n<elevate>\n</elevate>\n')
    open(dst, "wb").write(buf.getvalue())
    print("wrote", dst)


convert("suites/configsets/conf_geonames.zip", "suites/configsets/conf_types.zip")
convert("suites/configsets/conf_geonames_luxir.zip", "suites/configsets/conf_types_luxir.zip")
