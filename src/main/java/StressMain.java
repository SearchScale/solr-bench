import java.io.File;
import java.io.IOException;
import java.lang.invoke.MethodHandles;
import java.net.URL;
import java.nio.charset.Charset;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.Set;
import java.util.concurrent.Callable;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import org.apache.commons.io.FileUtils;
import org.apache.commons.io.IOUtils;
import org.apache.solr.benchmarks.BenchmarksMain;
import org.apache.solr.benchmarks.beans.Cluster;
import org.apache.solr.benchmarks.beans.IndexBenchmark;
import org.apache.solr.benchmarks.solrcloud.SolrCloud;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.google.common.util.concurrent.ThreadFactoryBuilder;

public class StressMain {

    private static final Logger log = LoggerFactory.getLogger(MethodHandles.lookup().lookupClass());


	public static void main(String[] args) throws Exception {
		ObjectMapper mapper = new ObjectMapper();

		Workflow workflow = mapper.readValue(FileUtils.readFileToString(new File("workflow.json"), "UTF-8"), Workflow.class);

		String solrPackagePath = "SolrNightlyBenchmarksWorkDirectory/Download/solr-d007470bda2f70ba4e1c407ac624e21288947128.tgz";
        Cluster cluster = new Cluster();
        cluster.numSolrNodes = 3;
        cluster.provisioningMethod = "local";

        SolrCloud solrCloud = new SolrCloud(cluster, solrPackagePath);
        solrCloud.init();

		executeWorkflow(workflow, solrCloud);
		
		solrCloud.shutdown(true);
	}

	private static void executeWorkflow(Workflow workflow, SolrCloud cloud) throws InterruptedException {
		Map<String, AtomicInteger> globalVariables = new ConcurrentHashMap<String, AtomicInteger>();

		for (String var: workflow.globalVariables.keySet()) {
			globalVariables.put(var, new AtomicInteger(workflow.globalVariables.get(var)));
		}

		Map<String, List<Future>> taskFutures = new HashMap<String, List<Future>>();
		Map<String, ExecutorService> taskExecutors = new HashMap<String, ExecutorService>();

		for (TaskInstance instance: workflow.executionPlan) {
			TaskType type = workflow.taskTypes.get(instance.type);
			System.out.println(instance.task+" is of type: "+type);

			taskFutures.put(instance.task, new ArrayList<Future>());

			ExecutorService executor = Executors.newFixedThreadPool(instance.concurrency, new ThreadFactoryBuilder().setNameFormat(instance.task+"-threadpool").build()); 

			taskExecutors.put(instance.task, executor);

			for (int i=1; i<=instance.instances; i++) {

				Callable c = () -> {

					if (instance.waitFor != null) {
						log.info("Waiting for "+instance.waitFor+" to finish");
						boolean await = taskExecutors.get(instance.waitFor).awaitTermination(Integer.MAX_VALUE, TimeUnit.SECONDS);
						log.info(instance.waitFor+" finished! "+await);
					}
					Map<String, Integer> copyOfGlobalVarialbes = new HashMap<String, Integer>();
					if (instance.preTaskEvals != null) {
						copyOfGlobalVarialbes = evaluate(instance.preTaskEvals, globalVariables);
					}

					Map<String, String> params = new HashMap<String, String>();
					if (instance.parameters != null) {
						for (String param: instance.parameters.keySet()) {
							params.put(param, resolveInteger(instance.parameters.get(param), copyOfGlobalVarialbes));
						}
					}
					long start = System.currentTimeMillis();
					if (type.indexBenchmark != null) {
						log.info("Running benchmarking task: "+type.indexBenchmark.datasetFile);
						/*Thread.sleep(1000);
						log.info("Running benchmarking task: "+type.indexBenchmark.datasetFile);*/
						Map<String, Map> results = new HashMap<String, Map>();
			            results.put("indexing-benchmarks", new LinkedHashMap<Map, List<Map>>());
			            try {
			            	BenchmarksMain.runIndexingBenchmarks(Collections.singletonList(type.indexBenchmark), cloud, results);
			            } catch (Exception ex) {
			            	ex.printStackTrace();
			            }
						log.info("Results: "+results);						
					} else if (type.command != null) {
						Map<String, String> solrurlMap = Map.of("SOLRURL", cloud.nodes.get(new Random().nextInt(cloud.nodes.size())).getBaseUrl());
						String command = resolveString(resolveString(resolveString(type.command, params), workflow.globalConstants), solrurlMap);
						log.info("Running in "+instance.mode+" mode: "+command);

						try {
							String output = IOUtils.toString(new URL(command).openStream(), Charset.forName("UTF-8"));
							log.info("Output: "+output);
						} catch (Exception ex) {
							ex.printStackTrace();
						}
					}
					long end = System.currentTimeMillis();
					return end-start;
				};

				taskFutures.get(instance.task).add(executor.submit(c));
			}
			executor.shutdown();
		}
		
		for (String task: taskExecutors.keySet()) {
			taskExecutors.get(task).awaitTermination(Integer.MAX_VALUE, TimeUnit.SECONDS);
		}
	}

	private static String resolveInteger(String cmd, Map<String, Integer> vars) {
		for (String var: vars.keySet()) {
			cmd = cmd.replace("${"+var+"}", String.valueOf(vars.get(var)));
		}
		return cmd;
	}

	private static String resolveString(String cmd, Map<String, String> vars) {
		for (String var: vars.keySet()) {
			cmd = cmd.replace("${"+var+"}", String.valueOf(vars.get(var)));
		}
		return cmd;
	}

	private static Map<String, Integer> evaluate(List<String> exprs, Map<String, AtomicInteger> globalVariables) {
		Map<String, Integer> ret = new HashMap<String, Integer>();

		// use nashorn etc. for script evals
		for (String ex: exprs) {
			if (ex.startsWith("inc(")) {
				String parts[] = Arrays.copyOfRange(ex.split("(inc\\()|(\\))|(,)"), 1, 3);

				int val = globalVariables.get(parts[0]).addAndGet(Integer.valueOf(parts[1]));
				ret.put(parts[0], val);
			}
		}
		return ret;
	}
}