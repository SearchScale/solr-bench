package org.apache.solr.benchmarks;

import org.apache.commons.io.IOUtils;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * One response from Solr's /admin/metrics endpoint, in either of the formats Solr has used:
 * <ul>
 *   <li>JSON (Solr 9 and early Solr 10), read with paths like "jvm/solr.jvm/memory.heap.usage"</li>
 *   <li>Prometheus text (Solr 10+ with OpenTelemetry metrics), read with selectors like
 *       "jvm_memory_used_bytes{jvm_memory_type="heap"}", which sum every matching series</li>
 * </ul>
 * The JVM paths that suites have always used ("jvm/solr.jvm/threads.count" etc.) also work against Prometheus
 * responses: they are translated to the equivalent OpenTelemetry metrics, so one suite works across Solr versions.
 */
public class SolrMetrics {

  private static final Pattern SELECTOR = Pattern.compile("[a-zA-Z_:][a-zA-Z0-9_:]*(\\{.*\\})?");

  private final JSONObject json;
  private final List<Sample> samples;

  private SolrMetrics(JSONObject json, List<Sample> samples) {
    this.json = json;
    this.samples = samples;
  }

  /** True for a Prometheus selector, false for a JSON metrics path like "group/registry/name". */
  public static boolean isSelector(String metric) {
    return !metric.contains("/") && SELECTOR.matcher(metric).matches();
  }

  /**
   * Fetches the metrics a path or selector needs from a node (base URL ending in "/solr/"). JSON paths use the path's
   * group; selectors ask for the Prometheus format, which Solr 9 also serves (with its own metric names).
   */
  public static SolrMetrics fetch(String baseUrl, String metric) throws IOException {
    return fetchQuery(baseUrl, queryFor(metric));
  }

  /** The /admin/metrics query string that returns a path or selector; metrics sharing it can share one fetch. */
  public static String queryFor(String metric) {
    return isSelector(metric) ? "wt=prometheus" : "group=" + metric.split("(?<!\\\\)/")[0];
  }

  public static SolrMetrics fetchQuery(String baseUrl, String query) throws IOException {
    return parse(IOUtils.toString(new URL(baseUrl + "admin/metrics?" + query), StandardCharsets.UTF_8));
  }

  public static SolrMetrics parse(String body) {
    String trimmed = body.trim();
    if (trimmed.startsWith("{")) {
      return new SolrMetrics(new JSONObject(trimmed), null);
    }
    List<Sample> samples = new ArrayList<>();
    for (String line : trimmed.split("\n")) {
      line = line.trim();
      if (line.isEmpty() || line.startsWith("#")) continue;
      Sample s = Sample.parse(line);
      if (s != null) samples.add(s);
    }
    return new SolrMetrics(null, samples);
  }

  public boolean isPrometheus() {
    return samples != null;
  }

  /** The value of a JSON path or Prometheus selector, or null if this response doesn't have it. */
  public Double get(String metric) {
    if (isSelector(metric)) {
      return samples == null ? null : sum(Sample.parseSelector(metric));
    }
    if (json != null) {
      return jsonValue(metric);
    }
    return translated(metric);
  }

  private Double jsonValue(String path) {
    String[] elements = path.split("(?<!\\\\)/");
    try {
      JSONObject obj = json.getJSONObject("metrics");
      for (int i = 1; i < elements.length - 1; ++i) {
        obj = obj.getJSONObject(elements[i].replace("\\/", "/"));
      }
      return obj.getDouble(elements[elements.length - 1].replace("\\/", "/"));
    } catch (JSONException e) {
      // some keys, e.g. solr.core.fsloadtest.shard1.replica_n1, may not be available immediately
      return null;
    }
  }

  /** The OpenTelemetry equivalents of the JVM metrics in the old JSON format. */
  private Double translated(String path) {
    switch (path) {
      case "jvm/solr.jvm/threads.count":
        return sum(Sample.parseSelector("jvm_thread_count"));
      case "jvm/solr.jvm/memory.heap.used":
        return sum(Sample.parseSelector("jvm_memory_used_bytes{jvm_memory_type=\"heap\"}"));
      case "jvm/solr.jvm/memory.heap.committed":
        return sum(Sample.parseSelector("jvm_memory_committed_bytes{jvm_memory_type=\"heap\"}"));
      case "jvm/solr.jvm/memory.heap.max":
        return sum(Sample.parseSelector("jvm_memory_limit_bytes{jvm_memory_type=\"heap\"}"));
      case "jvm/solr.jvm/memory.heap.usage": {
        Double used = translated("jvm/solr.jvm/memory.heap.used");
        Double max = translated("jvm/solr.jvm/memory.heap.max");
        return used == null || max == null || max <= 0 ? null : used / max;
      }
      case "jvm/solr.jvm/memory.non-heap.used":
        return sum(Sample.parseSelector("jvm_memory_used_bytes{jvm_memory_type=\"non_heap\"}"));
      case "jvm/solr.jvm/memory.total.used":
        return sum(Sample.parseSelector("jvm_memory_used_bytes"));
      case "jvm/solr.jvm/os.processCpuLoad":
        return sum(Sample.parseSelector("jvm_cpu_recent_utilization"));
      default:
        return null;
    }
  }

  private Double sum(Sample selector) {
    double total = 0;
    boolean found = false;
    for (Sample s : samples) {
      if (s.name.equals(selector.name) && s.labels.entrySet().containsAll(selector.labels.entrySet())) {
        total += s.value;
        found = true;
      }
    }
    return found ? total : null;
  }

  /** One line of Prometheus text format: name{label="value",...} value [timestamp] */
  static class Sample {
    final String name;
    final Map<String, String> labels;
    final double value;

    Sample(String name, Map<String, String> labels, double value) {
      this.name = name;
      this.labels = labels;
      this.value = value;
    }

    static Sample parse(String line) {
      int i = 0;
      while (i < line.length() && line.charAt(i) != '{' && !Character.isWhitespace(line.charAt(i))) i++;
      String name = line.substring(0, i);
      Map<String, String> labels = Collections.emptyMap();
      if (i < line.length() && line.charAt(i) == '{') {
        labels = new LinkedHashMap<>();
        i = parseLabels(line, i + 1, labels);
        if (i < 0) return null;
      }
      String[] rest = line.substring(i).trim().split("\\s+");
      try {
        return new Sample(name, labels, Double.parseDouble(rest[0]));
      } catch (NumberFormatException e) {
        return null; // NaN and Inf parse fine; anything else isn't a sample
      }
    }

    /** A selector is a sample without a value: name, optionally with the labels a series must have. */
    static Sample parseSelector(String selector) {
      int brace = selector.indexOf('{');
      Map<String, String> labels = new LinkedHashMap<>();
      if (brace >= 0) parseLabels(selector, brace + 1, labels);
      return new Sample(brace >= 0 ? selector.substring(0, brace) : selector, labels, 0);
    }

    /** Parses labels from just after '{'; returns the index after '}', or -1 if malformed. */
    private static int parseLabels(String s, int i, Map<String, String> labels) {
      while (i < s.length()) {
        char c = s.charAt(i);
        if (c == '}') return i + 1;
        if (c == ',' || Character.isWhitespace(c)) { i++; continue; }
        int eq = s.indexOf('=', i);
        if (eq < 0 || eq + 1 >= s.length() || s.charAt(eq + 1) != '"') return -1;
        String key = s.substring(i, eq).trim();
        StringBuilder value = new StringBuilder();
        int j = eq + 2;
        for (; j < s.length() && s.charAt(j) != '"'; j++) {
          char v = s.charAt(j);
          if (v == '\\' && j + 1 < s.length()) {
            char next = s.charAt(++j);
            value.append(next == 'n' ? '\n' : next);
          } else {
            value.append(v);
          }
        }
        if (j >= s.length()) return -1;
        labels.put(key, value.toString());
        i = j + 1;
      }
      return -1;
    }
  }
}
