package org.apache.solr.benchmarks.beans;

import java.util.List;

import com.fasterxml.jackson.annotation.JsonProperty;

public abstract class BaseBenchmark {
  @JsonProperty("name")
  public String name;

  @JsonProperty("description")
  public String description;

  @JsonProperty("duration-secs")
  public Integer durationSecs;

  @JsonProperty ("rpm")
  public Integer rpm;

  /**
   * Thread counts to run one after the other, e.g. [32] or [1, 32]; one thread if not set.
   * For query benchmarks, each run continues through the query file where the previous one stopped, so no run
   * repeats (and gets cache hits for) queries an earlier run already sent.
   */
  @JsonProperty("threads")
  public List<Integer> threads;

  public List<Integer> threadCounts() {
    return threads == null || threads.isEmpty() ? List.of(1) : threads;
  }
}
