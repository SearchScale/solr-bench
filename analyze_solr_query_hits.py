#!/usr/bin/env python3
"""
Solr Query Hit Analyzer

This script analyzes Solr logs to extract query information and hit counts
without fully extracting compressed archives. It works with tar, tar.gz, zip files
and can process logs directly from archives. When provided with a query file,
it correlates Request IDs (RIDs) with actual query content for better analysis.

Usage:
    python3 analyze_solr_query_hits.py <log_file_or_archive> [query_file]
    
Example:
    python3 analyze_solr_query_hits.py logs-solr.tar
    python3 analyze_solr_query_hits.py logs-2025-01-01.zip suites/queries/wikipedia-queries.json
    python3 analyze_solr_query_hits.py solr.log queries.json
"""

import sys
import re
import json
import tarfile
import zipfile
import gzip
import os
import io
from collections import defaultdict
from urllib.parse import unquote

def extract_query_from_params(params_str):
    """Extract query from URL parameters string."""
    # Look for JSON query parameter
    json_match = re.search(r'"json":"([^"]*)"', params_str)
    if json_match:
        try:
            json_str = unquote(json_match.group(1))
            json_obj = json.loads(json_str)
            return json_obj.get('query', 'N/A')
        except (json.JSONDecodeError, ValueError):
            pass
    
    # Look for traditional q parameter
    q_match = re.search(r'"q":"([^"]*)"', params_str)
    if q_match:
        return unquote(q_match.group(1))
    
    # Look for q parameter without quotes
    q_match = re.search(r'q=([^&\s]+)', params_str)
    if q_match:
        return unquote(q_match.group(1))
    
    return 'N/A'

def parse_solr_log_line(line, query_order_map=None):
    """Parse a Solr log line to extract query and hit count information."""
    # Look for Solr request logs with hits= pattern
    if 'hits=' in line and ('/select' in line or '/query' in line):
        # Extract hits value
        hits_match = re.search(r'hits=(\d+)', line)
        if not hits_match:
            return None, None, None, None, None
            
        hit_count = int(hits_match.group(1))
        
        # Extract status value
        status_match = re.search(r'status=(\d+)', line)
        status = int(status_match.group(1)) if status_match else 0
        
        # Extract QTime value
        qtime_match = re.search(r'QTime=(\d+)', line)
        qtime = int(qtime_match.group(1)) if qtime_match else 0
        
        # Extract query and RID from the params section
        query, rid = extract_query_from_solr_request_log(line, query_order_map)
        
        return query, hit_count, rid, status, qtime
    
    # Also check for JSON response format logs with numFound
    elif 'numFound' in line and ('select' in line or 'query' in line):
        # Extract numFound value
        num_found_match = re.search(r'"numFound":(\d+)', line)
        if not num_found_match:
            return None, None, None, None, None
            
        hit_count = int(num_found_match.group(1))
        
        # Extract query from the log line
        query = extract_query_from_params(line)
        
        return query, hit_count, None, 0, 0
    
    return None, None, None, None, None

def load_rid_to_query_mapping(queries_file_path):
    """
    Load query mapping based on RID counter values and query file order.
    Since RIDs are generated sequentially, we can correlate RID counters 
    with query order in the file.
    """
    if not queries_file_path or not os.path.exists(queries_file_path):
        print(f"Query file not found or not provided: {queries_file_path}")
        return {}
    
    print(f"Loading queries from: {queries_file_path}")
    
    try:
        with open(queries_file_path, 'r', encoding='utf-8') as f:
            queries = [line.strip() for line in f if line.strip()]
        
        print(f"Loaded {len(queries)} queries for RID correlation")
        
        # Create mapping that can be used by RID counter values
        # The counter in RID corresponds to the query order (1-based)
        query_order_map = {}
        
        for i, query_line in enumerate(queries):
            # Store as 1-based index to match RID counter
            query_order_map[i + 1] = query_line
        
        print(f"Created order-based mapping for {len(query_order_map)} queries")
        return query_order_map
        
    except Exception as e:
        print(f"Error loading queries from {queries_file_path}: {e}")
        return {}

def extract_query_from_solr_request_log(line, query_order_map=None):
    """Extract query from Solr request log line format."""
    # Look for params={...} section
    params_match = re.search(r'params=\{([^}]+)\}', line)
    if not params_match:
        return 'N/A', None
    
    params_str = params_match.group(1)
    
    # Extract RID if present
    rid = None
    rid_counter = None
    rid_match = re.search(r'rid=query-(\d+)-(\d+)', params_str)
    if rid_match:
        rid = f"query-{rid_match.group(1)}-{rid_match.group(2)}"
        rid_counter = int(rid_match.group(2))
    
    # If we have a counter and query mapping, get the actual query
    if rid_counter and query_order_map and rid_counter in query_order_map:
        actual_query = query_order_map[rid_counter]
        return actual_query, rid
    
    # Look for json parameter containing the query
    json_match = re.search(r'json=([^&\s]+)', params_str)
    if json_match:
        try:
            json_str = unquote(json_match.group(1))
            # Handle URL encoding
            json_str = json_str.replace('%22', '"').replace('%7B', '{').replace('%7D', '}')
            json_obj = json.loads(json_str)
            return json_obj.get('query', 'N/A'), rid
        except (json.JSONDecodeError, ValueError):
            pass
    
    # Look for traditional q parameter
    q_match = re.search(r'q=([^&\s]+)', params_str)
    if q_match:
        return unquote(q_match.group(1)), rid
    
    # If no specific query found, check if it's a generic query
    if 'wt=json' in params_str:
        return 'generic_query', rid
    
    return 'N/A', rid

def process_log_content(content, filename="", query_order_map=None):
    """Process log content and extract query statistics."""
    query_executions = []  # Store individual query executions
    rid_stats = defaultdict(list)  # Track by RID as well
    total_queries = 0
    
    print(f"Processing log content from {filename}...")
    
    for line_num, line in enumerate(content.split('\n'), 1):
        query, hit_count, rid, status, qtime = parse_solr_log_line(line, query_order_map)
        
        if query and hit_count is not None:
            # Store each individual query execution
            query_executions.append({
                'query': query,
                'hits': hit_count,
                'status': status,
                'qtime': qtime,
                'rid': rid
            })
            if rid:
                rid_stats[rid] = (query, hit_count, status, qtime)
            total_queries += 1
            
            # Progress indicator for large files
            if total_queries % 100 == 0:
                print(f"  Processed {total_queries} queries...", end='\r')
    
    if total_queries > 0:
        print(f"  Found {total_queries} queries total")
    
    return query_executions, total_queries, rid_stats

def find_query_file_in_archive(tar):
    """Find query files in the tar archive."""
    members = tar.getmembers()
    query_files = [m for m in members if m.isfile() and 
                  (m.name.endswith('-queries.json') or 
                   m.name.endswith('queries.json') or 
                   'queries' in m.name.lower() and m.name.endswith('.json'))]
    
    if query_files:
        # Return the first query file found
        return query_files[0]
    return None

def read_from_tar(file_path, query_order_map=None):
    """Read log files from a tar archive without extracting."""
    all_executions = []
    all_rid_stats = {}
    total_queries = 0
    
    print(f"Opening tar archive: {file_path}")
    
    try:
        with tarfile.open(file_path, 'r:*') as tar:
            # If no query mapping provided, try to find query file in archive
            if query_order_map is None:
                query_file_member = find_query_file_in_archive(tar)
                if query_file_member:
                    print(f"Found query file in archive: {query_file_member.name}")
                    try:
                        query_file_obj = tar.extractfile(query_file_member)
                        if query_file_obj:
                            query_content = query_file_obj.read().decode('utf-8', errors='ignore')
                            # Create a temporary file path for the mapping function
                            import tempfile
                            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_file:
                                temp_file.write(query_content)
                                temp_file.flush()
                                query_order_map = load_rid_to_query_mapping(temp_file.name)
                                os.unlink(temp_file.name)  # Clean up temp file
                    except Exception as e:
                        print(f"  Error processing query file {query_file_member.name}: {e}")
            
            members = tar.getmembers()
            log_files = [m for m in members if m.isfile() and 
                        (m.name.endswith('.log') or 'solr' in m.name.lower())]
            
            print(f"Found {len(log_files)} potential log files in archive")
            
            for member in log_files:
                print(f"Processing: {member.name}")
                try:
                    file_obj = tar.extractfile(member)
                    if file_obj:
                        content = file_obj.read().decode('utf-8', errors='ignore')
                        file_executions, file_queries, rid_stats = process_log_content(content, member.name, query_order_map)
                        
                        # Merge executions
                        all_executions.extend(file_executions)
                        total_queries += file_queries
                        all_rid_stats.update(rid_stats)
                        
                except Exception as e:
                    print(f"  Error processing {member.name}: {e}")
                    continue
                    
    except Exception as e:
        print(f"Error opening tar file: {e}")
        return [], 0, {}
        
    return all_executions, total_queries, all_rid_stats

def find_query_file_in_zip(zip_file):
    """Find query files in the zip archive."""
    file_list = zip_file.namelist()
    query_files = [f for f in file_list if 
                  (f.endswith('-queries.json') or 
                   f.endswith('queries.json') or 
                   ('queries' in f.lower() and f.endswith('.json'))) and not f.endswith('/')]
    
    if query_files:
        # Return the first query file found
        return query_files[0]
    return None

def read_from_zip(file_path, query_order_map=None):
    """Read log files from a zip archive without extracting."""
    all_executions = []
    all_rid_stats = {}
    total_queries = 0
    
    print(f"Opening zip archive: {file_path}")
    
    try:
        with zipfile.ZipFile(file_path, 'r') as zip_file:
            # If no query mapping provided, try to find query file in archive
            if query_order_map is None:
                query_file_name = find_query_file_in_zip(zip_file)
                if query_file_name:
                    print(f"Found query file in archive: {query_file_name}")
                    try:
                        with zip_file.open(query_file_name) as query_file_obj:
                            query_content = query_file_obj.read().decode('utf-8', errors='ignore')
                            # Create a temporary file path for the mapping function
                            import tempfile
                            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_file:
                                temp_file.write(query_content)
                                temp_file.flush()
                                query_order_map = load_rid_to_query_mapping(temp_file.name)
                                os.unlink(temp_file.name)  # Clean up temp file
                    except Exception as e:
                        print(f"  Error processing query file {query_file_name}: {e}")
            
            file_list = zip_file.namelist()
            log_files = [f for f in file_list if 
                        (f.endswith('.log') or 'solr' in f.lower()) and not f.endswith('/')]
            
            # Also look for tar files inside the zip
            tar_files = [f for f in file_list if f.endswith('.tar') and not f.endswith('/')]
            
            print(f"Found {len(log_files)} potential log files and {len(tar_files)} tar files in archive")
            
            for file_name in log_files:
                print(f"Processing: {file_name}")
                try:
                    with zip_file.open(file_name) as file_obj:
                        content = file_obj.read().decode('utf-8', errors='ignore')
                        file_executions, file_queries, rid_stats = process_log_content(content, file_name, query_order_map)
                        
                        # Merge executions
                        all_executions.extend(file_executions)
                        total_queries += file_queries
                        all_rid_stats.update(rid_stats)
                        
                except Exception as e:
                    print(f"  Error processing {file_name}: {e}")
                    continue
            
            # Process tar files found inside the zip
            for tar_name in tar_files:
                print(f"Processing nested tar file: {tar_name}")
                try:
                    with zip_file.open(tar_name) as tar_file_obj:
                        # Read the tar file data and process it
                        tar_data = tar_file_obj.read()
                        with tarfile.open(fileobj=io.BytesIO(tar_data), mode='r:*') as tar:
                            # If no query mapping provided, try to find query file in nested tar
                            if query_order_map is None:
                                query_file_member = find_query_file_in_archive(tar)
                                if query_file_member:
                                    print(f"Found query file in nested tar: {query_file_member.name}")
                                    try:
                                        query_file_obj = tar.extractfile(query_file_member)
                                        if query_file_obj:
                                            query_content = query_file_obj.read().decode('utf-8', errors='ignore')
                                            # Create a temporary file path for the mapping function
                                            import tempfile
                                            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_file:
                                                temp_file.write(query_content)
                                                temp_file.flush()
                                                query_order_map = load_rid_to_query_mapping(temp_file.name)
                                                os.unlink(temp_file.name)  # Clean up temp file
                                    except Exception as e:
                                        print(f"  Error processing query file {query_file_member.name}: {e}")
                                        
                            members = tar.getmembers()
                            tar_log_files = [m for m in members if m.isfile() and 
                                           (m.name.endswith('.log') or 'solr' in m.name.lower())]
                            
                            for member in tar_log_files:
                                print(f"  Processing tar member: {member.name}")
                                try:
                                    file_obj = tar.extractfile(member)
                                    if file_obj:
                                        content = file_obj.read().decode('utf-8', errors='ignore')
                                        file_executions, file_queries, rid_stats = process_log_content(content, f"{tar_name}/{member.name}", query_order_map)
                                        
                                        # Merge executions
                                        all_executions.extend(file_executions)
                                        total_queries += file_queries
                                        all_rid_stats.update(rid_stats)
                                        
                                except Exception as e:
                                    print(f"    Error processing {member.name}: {e}")
                                    continue
                                    
                except Exception as e:
                    print(f"  Error processing tar file {tar_name}: {e}")
                    continue
                    
    except Exception as e:
        print(f"Error opening zip file: {e}")
        return [], 0, {}
        
    return all_executions, total_queries, all_rid_stats

def read_regular_file(file_path, query_order_map=None):
    """Read a regular log file (possibly gzipped)."""
    try:
        if file_path.endswith('.gz'):
            print(f"Opening gzipped file: {file_path}")
            with gzip.open(file_path, 'rt', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        else:
            print(f"Opening regular file: {file_path}")
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                
        return process_log_content(content, file_path, query_order_map)
        
    except Exception as e:
        print(f"Error reading file: {e}")
        return [], 0, {}

def print_query_executions(query_executions, total_queries):
    """Print individual query executions."""
    if not query_executions:
        print("No query data found in the logs.")
        return
    
    print(f"\n{'='*160}")
    print(f"SOLR QUERY EXECUTION RESULTS")
    print(f"{'='*160}")
    print(f"Total query executions: {total_queries}")
    print(f"{'='*160}")
    
    # Print header
    print(f"{'Query':<90} {'Hits':<8} {'QTime':<8} {'Status':<8} {'RID':<35}")
    print(f"{'-'*90} {'-'*8} {'-'*8} {'-'*8} {'-'*35}")
    
    # Print each execution
    for execution in query_executions:
        query = execution['query']
        hits = execution['hits']
        qtime = execution['qtime']
        status = execution['status']
        rid = execution['rid'] or 'N/A'
        
        # Truncate long queries for display
        display_query = query[:87] + "..." if len(query) > 90 else query
        
        print(f"{display_query:<90} {hits:<8} {qtime:<8} {status:<8} {rid:<35}")
    
    print(f"{'='*160}")

def main():
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print("Usage: python3 analyze_solr_query_hits.py <log_file_or_archive> [query_file]")
        print("\nSupported formats:")
        print("  - Regular log files (.log)")
        print("  - Gzipped log files (.log.gz)")
        print("  - Tar archives (.tar, .tar.gz, .tgz)")
        print("  - Zip archives (.zip)")
        print("\nQuery file parameter:")
        print("  - Optional: When provided, correlates RIDs found in logs with actual query content")
        print("  - Auto-detection: Script will automatically look for query files in the log archive")
        print("  - If found automatically, the query_file parameter is not needed")
        sys.exit(1)
    
    file_path = sys.argv[1]
    query_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' not found.")
        sys.exit(1)
    
    # Load query order mapping if query file is provided
    query_order_map = None
    if query_file:
        query_order_map = load_rid_to_query_mapping(query_file)
        if query_order_map:
            print(f"Loaded query order mapping for RID correlation")
        else:
            print("Warning: Could not load query order mapping, queries may show as generic")
    
    # Determine file type and process accordingly
    if file_path.endswith(('.tar', '.tar.gz', '.tgz')):
        query_executions, total_queries, rid_stats = read_from_tar(file_path, query_order_map)
    elif file_path.endswith('.zip'):
        query_executions, total_queries, rid_stats = read_from_zip(file_path, query_order_map)
    else:
        query_executions, total_queries, rid_stats = read_regular_file(file_path, query_order_map)
    
    # Print results
    print_query_executions(query_executions, total_queries)
    
    # Print RID summary if available
    if rid_stats:
        print(f"\nRID Summary: Found {len(rid_stats)} queries with request IDs")
        if query_order_map:
            print("Query order correlation was enabled - queries should show actual content instead of 'generic_query'")
        else:
            print("For better correlation, provide the query file as second argument")

if __name__ == "__main__":
    main()