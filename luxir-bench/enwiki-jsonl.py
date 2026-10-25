#!/usr/bin/env python3
"""Converts lucene-bench's enwiki-20120502-lines-1k.txt.lzma (Wikipedia articles in 1 KB chunks:
title, date and body per line) into the JSON-lines file of the enwiki suites, with the fields
luceneutil indexes for its wikimedium benchmarks (src/main/perf/LineFileDocs.java):
  id              base-36 docid of 6 characters, from 0 in file order (LineFileDocs.intToID)
  title           the article title, for sorting, cut to 255 UTF-8 bytes at a character boundary (a few
                  titles are longer, and Luxir indexes strings of at most 255 bytes; both systems get the same)
  titleTokenized  the title again, analyzed
  body            the 1 KB chunk of the article
  lastMod         the date as milliseconds since the epoch (UTC)
  timesecnum      seconds into the day (for IntNRQ)
  month           English month name (for sorting and facets)
  dayOfYear       1-366 (for sorting and facets)
  year            the date's year (the top level of luceneutil's Date facet)
Usage: enwiki-jsonl.py <lines-1k.txt.lzma> <out.json.gz> [max-docs, default 25000000; luceneutil's wikimedium10m takes 10000000]"""
import calendar, datetime, json, lzma, subprocess, sys

src, dst = sys.argv[1], sys.argv[2]
max_docs = int(sys.argv[3]) if len(sys.argv) > 3 else 25_000_000
MONTHS = {m.upper(): i for i, m in enumerate(calendar.month_abbr) if m}
NAMES = list(calendar.month_name)
B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def cut(s, limit=255):
    b = s.encode("utf-8")
    if len(b) <= limit:
        return s
    return b[:limit].decode("utf-8", errors="ignore")  # drops a character the cut splits


def to_id(n):
    s = []
    for _ in range(6):
        s.append(B36[n % 36])
        n //= 36
    return "".join(reversed(s))


out = open(dst, "wb")
gz = subprocess.Popen(["pigz", "-6"], stdin=subprocess.PIPE, stdout=out)
n = 0
longest_title = 0
cut_titles = 0
# invalid UTF-8 (a few bytes in the file) becomes U+FFFD, as Java's readers decode it for luceneutil
with lzma.open(src, "rt", encoding="utf-8", errors="replace", newline="\n") as f:
    header = f.readline()
    assert header.startswith("FIELDS_HEADER_INDICATOR###"), header
    for line in f:
        if n >= max_docs:
            break
        title, date, body = line.rstrip("\n").split("\t", 2)
        # 30-APR-2012 03:25:17.000
        d = datetime.datetime(int(date[7:11]), MONTHS[date[3:6]], int(date[0:2]),
                              int(date[12:14]), int(date[15:17]), int(date[18:20]), tzinfo=datetime.timezone.utc)
        longest_title = max(longest_title, len(title.encode("utf-8")))
        cut_titles += cut(title) != title
        doc = {"id": to_id(n), "title": cut(title), "titleTokenized": title, "body": body,
               "lastMod": int(d.timestamp()) * 1000, "timesecnum": d.hour * 3600 + d.minute * 60 + d.second,
               "month": NAMES[d.month], "dayOfYear": d.timetuple().tm_yday, "year": d.year}
        gz.stdin.write((json.dumps(doc, ensure_ascii=False) + "\n").encode("utf-8"))
        n += 1
gz.stdin.close()
gz.wait()
out.close()
print(f"{n} documents; longest title {longest_title} UTF-8 bytes, {cut_titles} cut to 255", file=sys.stderr)
