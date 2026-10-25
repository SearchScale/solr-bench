package org.apache.solr.benchmarks.indexing;

import org.apache.solr.benchmarks.readers.JsonlFileType;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.*;
import java.lang.invoke.MethodHandles;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.regex.Pattern;

/**
 * A DocReader that reads from a File.
 *
 * <p>Turning the file into lines is split across threads, as one thread could not keep up with
 * indexing (about 200,000 1 KB documents per second): one thread decompresses the file and cuts
 * it into chunks at line ends, and a few others decode the chunks into lines, which are handed
 * out in file order. Lines are the same as {@link BufferedReader#readLine()} gives (ended by
 * {@code \n}, {@code \r} or {@code \r\n}, decoded as UTF-8).
 */
public class FileDocReader implements DocReader {
  private static final int CHUNK = 4 << 20;
  private static final int DECODERS = Math.max(1, Math.min(4, Runtime.getRuntime().availableProcessors() / 4));
  private static final Object END = new Object();

  private final InputStream in;
  private final long offset;
  private long docsRead; //docs read so far from all the readDocs invocations
  private Long maxDocs; //max number of totals to be read, if docsRead >= maxDocs, it should stop reading any new docs
  private static final Logger log = LoggerFactory.getLogger(MethodHandles.lookup().lookupClass());
  private static final Pattern VERSION = Pattern.compile("\"_version_\":\\d*,*");

  private final ExecutorService decoders;
  // decoded chunks in file order (futures of their lines), then END, or an IOException
  private final BlockingQueue<Object> chunks = new ArrayBlockingQueue<>(4 * DECODERS);
  private final Thread splitter;
  private volatile boolean closed;
  private List<String> current = List.of();
  private int pos;
  private boolean done;

  public FileDocReader(File datasetFile, Long maxDocs, long offset) throws IOException {
    this.maxDocs = maxDocs;
    this.in = JsonlFileType.getInputStream(datasetFile);
    if (in == null) throw new IOException("unsupported dataset file type: " + datasetFile);
    this.offset = offset;
    this.decoders = Executors.newFixedThreadPool(DECODERS, r -> {
      Thread t = new Thread(r, "dataset-decoder");
      t.setDaemon(true);
      return t;
    });
    this.splitter = new Thread(this::split, "dataset-reader");
    splitter.setDaemon(true);
    splitter.start();
  }

  // Reads the file in chunks ending at a line end, each decoded by a decoder thread
  private void split() {
    byte[] carry = new byte[0];
    try {
      while (!closed) {
        byte[] buf = Arrays.copyOf(carry, carry.length + CHUNK);
        int end = carry.length;
        boolean eof = false;
        try {
          for (int n; end < buf.length && (n = in.read(buf, end, buf.length - end)) > 0; ) end += n;
          eof = end < buf.length;
        } catch (EOFException e) {
          log.info("Likely the Unexpected end of ZLIB input. Likely similar to https://stackoverflow.com/q/55608979. Ignoring for now. Actual exception message: " + e.getMessage());
          eof = true;
        }
        if (eof) { // the rest, ended or not
          byte[] chunk = buf;
          int len = end;
          if (len > 0) chunks.put(decoders.submit(() -> lines(chunk, len)));
          break;
        }
        int cut = end - 1;
        while (cut >= 0 && buf[cut] != '\n' && buf[cut] != '\r') cut--;
        if (cut < 0) { // no line end yet: a line longer than the chunk
          carry = Arrays.copyOf(buf, end);
          continue;
        }
        byte[] chunk = buf;
        int len = cut + 1;
        chunks.put(decoders.submit(() -> lines(chunk, len)));
        carry = Arrays.copyOfRange(buf, cut + 1, end);
      }
      chunks.put(END);
    } catch (InterruptedException e) {
      // closed
    } catch (IOException e) {
      chunks.offer(e);
    }
  }

  // The non-empty lines of a chunk, trimmed and without _version_
  private static List<String> lines(byte[] b, int len) {
    List<String> out = new ArrayList<>();
    int start = 0;
    for (int i = 0; i <= len; i++) {
      if (i < len && b[i] != '\n' && b[i] != '\r') continue;
      if (i > start) {
        String line = new String(b, start, i - start, StandardCharsets.UTF_8).trim();
        if (!line.isEmpty()) {
          // _version_ must be removed or adding doc will fail
          if (line.contains("\"_version_\":")) line = VERSION.matcher(line).replaceAll("");
          out.add(line);
        }
      }
      start = i + 1;
    }
    return out;
  }

  private String nextLine() throws IOException {
    while (pos == current.size()) {
      if (done) return null;
      Object next;
      try {
        next = chunks.take();
        if (next == END) {
          done = true;
          return null;
        }
        if (next instanceof IOException) {
          done = true;
          throw (IOException) next;
        }
        @SuppressWarnings("unchecked")
        Future<List<String>> lines = (Future<List<String>>) next;
        current = lines.get();
      } catch (InterruptedException e) {
        Thread.currentThread().interrupt();
        throw new InterruptedIOException();
      } catch (ExecutionException e) {
        throw new IOException(e.getCause());
      }
      pos = 0;
    }
    return current.get(pos++);
  }

  /**
   * Read `count` number of docs if available; otherwise return whatever remains.
   *
   * Stop reading when total number of docs read so far exceeds the maxDocs
   * @param count
   * @return
   * @throws IOException
   */
  @Override
  synchronized public List<String> readDocs(int count) throws IOException {
    if ((maxDocs != null && docsRead >= maxDocs) || count <= 0) {
      return null;
    }

    List<String> docs = new ArrayList<>();
    String line;
    while ((line = nextLine()) != null) {
      if (docsRead < offset) continue;

      docs.add(line);
      docsRead++;

      if (maxDocs != null && docsRead >= maxDocs) {
        return docs;
      }
      if (docs.size() >= count) {
        return docs;
      }
    }
    return docs.isEmpty() ? null : docs;
  }

  @Override
  public void close() throws IOException {
    closed = true;
    splitter.interrupt();
    decoders.shutdownNow();
    in.close();
  }
}
