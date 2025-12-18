# -*- coding:utf-8 -*-
"""
Benchmark para validar otimizações SQLite no GeoPackage.

Compara:
- Time to insert 1000 tiles (before/after indexing)
- Time to query tiles (best case, worst case)
- Database file size before/after VACUUM
"""

import os
import sqlite3
import time
import tempfile
import logging
from .sqlite_optimizer import SQLiteOptimizer

log = logging.getLogger(__name__)


def benchmark_tile_writes(db_path: str, num_tiles: int = 1000) -> dict:
	"""Benchmark tile write performance.
	
	Args:
		db_path: Path to test database
		num_tiles: Number of tiles to insert
	
	Returns:
		Dict with timing results (before, after optimization)
	"""
	results = {}

	# Create test database WITHOUT optimization
	db_unoptimized = sqlite3.connect(db_path)
	db_unoptimized.execute('''
		CREATE TABLE IF NOT EXISTS gpkg_tiles (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			zoom_level INTEGER NOT NULL,
			tile_column INTEGER NOT NULL,
			tile_row INTEGER NOT NULL,
			tile_data BLOB NOT NULL,
			last_modified TIMESTAMP DEFAULT (datetime('now','localtime')),
			UNIQUE (zoom_level, tile_column, tile_row)
		)
	''')
	db_unoptimized.commit()

	# Measure unoptimized write time
	start = time.time()
	for i in range(num_tiles):
		db_unoptimized.execute(
			'INSERT OR REPLACE INTO gpkg_tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?)',
			(10 + (i % 5), i % 256, i % 256, b'x' * 5000)  # 5KB dummy tiles
		)
	db_unoptimized.commit()
	unoptimized_time = time.time() - start
	results['write_unoptimized_sec'] = unoptimized_time
	db_unoptimized.close()

	# Create new database WITH optimization
	db_optimized_path = db_path.replace('.db', '_opt.db')
	db_optimized = sqlite3.connect(db_optimized_path)
	db_optimized.execute('''
		CREATE TABLE IF NOT EXISTS gpkg_tiles (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			zoom_level INTEGER NOT NULL,
			tile_column INTEGER NOT NULL,
			tile_row INTEGER NOT NULL,
			tile_data BLOB NOT NULL,
			last_modified TIMESTAMP DEFAULT (datetime('now','localtime')),
			UNIQUE (zoom_level, tile_column, tile_row)
		)
	''')
	db_optimized.commit()
	db_optimized.close()

	# Apply optimizations
	SQLiteOptimizer.optimize_database(db_optimized_path)

	# Measure optimized write time
	db_optimized = sqlite3.connect(db_optimized_path)
	start = time.time()
	for i in range(num_tiles):
		db_optimized.execute(
			'INSERT OR REPLACE INTO gpkg_tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?)',
			(10 + (i % 5), i % 256, i % 256, b'x' * 5000)
		)
	db_optimized.commit()
	optimized_time = time.time() - start
	results['write_optimized_sec'] = optimized_time
	db_optimized.close()

	# Calculate improvement
	improvement = (unoptimized_time - optimized_time) / unoptimized_time * 100
	results['write_improvement_pct'] = improvement

	# Cleanup
	os.remove(db_optimized_path)

	return results


def benchmark_tile_queries(db_path: str, num_queries: int = 100) -> dict:
	"""Benchmark tile query performance (after warm cache).
	
	Args:
		db_path: Path to test database (must have tiles from benchmark_tile_writes)
		num_queries: Number of queries to run
	
	Returns:
		Dict with timing results
	"""
	results = {}

	db = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)

	# Warm up cache (single query)
	db.execute('SELECT tile_data FROM gpkg_tiles LIMIT 1').fetchone()

	# Measure single-tile query time
	start = time.time()
	for i in range(num_queries):
		db.execute(
			'SELECT tile_data FROM gpkg_tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?',
			(10 + (i % 5), i % 256, i % 256)
		).fetchone()
	query_time = time.time() - start
	results['single_query_time_sec'] = query_time
	results['avg_query_time_ms'] = (query_time / num_queries) * 1000

	# Measure range query (multiple tiles at zoom level)
	start = time.time()
	for _ in range(10):
		db.execute(
			'SELECT tile_column, tile_row, tile_data FROM gpkg_tiles WHERE zoom_level=? AND tile_column BETWEEN ? AND ?',
			(10, 0, 128)
		).fetchall()
	range_time = time.time() - start
	results['range_query_time_sec'] = range_time

	db.close()

	return results


def benchmark_database_size(db_path: str) -> dict:
	"""Benchmark database file size before/after VACUUM.
	
	Args:
		db_path: Path to test database
	
	Returns:
		Dict with file sizes (before, after VACUUM)
	"""
	results = {}

	size_before = os.path.getsize(db_path)
	results['size_before_mb'] = size_before / (1024 * 1024)

	db = sqlite3.connect(db_path)
	db.execute('VACUUM')
	db.close()

	size_after = os.path.getsize(db_path)
	results['size_after_mb'] = size_after / (1024 * 1024)
	results['space_saved_pct'] = (size_before - size_after) / size_before * 100

	return results


def run_full_benchmark(num_tiles: int = 1000, output: bool = True) -> dict:
	"""Run complete benchmark suite.
	
	Args:
		num_tiles: Number of tiles for write benchmark
		output: If True, log results to console
	
	Returns:
		Dict with all results
	"""
	with tempfile.TemporaryDirectory() as tmpdir:
		db_path = os.path.join(tmpdir, 'benchmark.db')

		# Run benchmarks
		write_results = benchmark_tile_writes(db_path, num_tiles)
		query_results = benchmark_tile_queries(db_path, 100)
		size_results = benchmark_database_size(db_path)

		results = {**write_results, **query_results, **size_results}

		if output:
			log.info('=== SQLite GeoPackage Benchmark Results ===')
			log.info(f'Write {num_tiles} tiles (unoptimized): {write_results["write_unoptimized_sec"]:.2f}s')
			log.info(f'Write {num_tiles} tiles (optimized):   {write_results["write_optimized_sec"]:.2f}s')
			log.info(f'Write improvement: {write_results["write_improvement_pct"]:.1f}%')
			log.info(f'Single query avg: {query_results["avg_query_time_ms"]:.2f}ms')
			log.info(f'Range query: {query_results["range_query_time_sec"]:.2f}s')
			log.info(f'Database size (before VACUUM): {size_results["size_before_mb"]:.1f}MB')
			log.info(f'Database size (after VACUUM):  {size_results["size_after_mb"]:.1f}MB')
			log.info(f'Space saved: {size_results["space_saved_pct"]:.1f}%')

		return results


if __name__ == '__main__':
	# Run benchmark when module is executed directly
	import logging
	logging.basicConfig(level=logging.INFO)
	run_full_benchmark()
