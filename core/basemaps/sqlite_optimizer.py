# -*- coding:utf-8 -*-
"""
SQLite performance optimization utilities for GeoPackage tile cache.

Applies:
- Strategic indexes on frequently-queried columns (zoom_level, tile_column, tile_row)
- PRAGMAs for write efficiency (WAL mode, cache size, synchronous mode)
- Connection pooling hints for multithreaded access
"""

import logging
import sqlite3
from typing import Optional

log = logging.getLogger(__name__)


class SQLiteOptimizer:
	"""Optimizes SQLite database for tile cache operations."""

	# PRAGMAs for performance (tuned for moderate-sized caches, ~500MB)
	PRAGMAS = {
		'journal_mode': 'WAL',  # Write-Ahead Logging: better concurrency
		'synchronous': 'NORMAL',  # Balance safety and speed (vs FULL/OFF)
		'cache_size': -64000,  # 64MB cache (negative = KB)
		'temp_store': 'MEMORY',  # Temp tables in RAM
		'mmap_size': 30000000,  # Memory-map I/O (30MB)
		'page_size': 4096,  # Standard SQLite page size
		'busy_timeout': 5000,  # 5s timeout for locked DB
	}

	# Indexes for tile queries (zoom_level, tile_column, tile_row)
	INDEXES = {
		'idx_tiles_zoom': (
			'gpkg_tiles',
			'zoom_level',
			'CREATE INDEX IF NOT EXISTS idx_tiles_zoom ON gpkg_tiles(zoom_level)'
		),
		'idx_tiles_zxy': (
			'gpkg_tiles',
			'zoom_level, tile_column, tile_row',
			'CREATE INDEX IF NOT EXISTS idx_tiles_zxy ON gpkg_tiles(zoom_level, tile_column, tile_row)'
		),
		'idx_tiles_time': (
			'gpkg_tiles',
			'last_modified',
			'CREATE INDEX IF NOT EXISTS idx_tiles_time ON gpkg_tiles(last_modified DESC)'
		),
	}

	@staticmethod
	def apply_pragmas(db_path: str, pragmas: Optional[dict] = None) -> bool:
		"""Apply performance PRAGMAs to database.
		
		Args:
			db_path: Path to SQLite database
			pragmas: Dict of PRAGMA name -> value (uses PRAGMAS if None)
		
		Returns:
			True if successful, False otherwise
		"""
		if pragmas is None:
			pragmas = SQLiteOptimizer.PRAGMAS

		try:
			db = sqlite3.connect(db_path)
			for pragma_name, pragma_value in pragmas.items():
				db.execute(f'PRAGMA {pragma_name} = {pragma_value}')
			db.close()
			log.debug(f'Applied {len(pragmas)} PRAGMAs to {db_path}')
			return True
		except Exception as e:
			log.warning(f'Failed to apply PRAGMAs: {e}')
			return False

	@staticmethod
	def create_indexes(db_path: str, indexes: Optional[dict] = None) -> bool:
		"""Create strategic indexes on tile cache table.
		
		Args:
			db_path: Path to SQLite database
			indexes: Dict of index_name -> (table, columns, sql) (uses INDEXES if None)
		
		Returns:
			True if successful, False otherwise
		"""
		if indexes is None:
			indexes = SQLiteOptimizer.INDEXES

		try:
			db = sqlite3.connect(db_path)
			for index_name, (table, columns, sql) in indexes.items():
				try:
					db.execute(sql)
					log.debug(f'Created index: {index_name} on {table}({columns})')
				except sqlite3.OperationalError as e:
					log.debug(f'Index {index_name} may already exist: {e}')
			db.commit()
			db.close()
			log.debug(f'Created/verified {len(indexes)} indexes in {db_path}')
			return True
		except Exception as e:
			log.warning(f'Failed to create indexes: {e}')
			return False

	@staticmethod
	def optimize_database(db_path: str, pragmas: Optional[dict] = None, indexes: Optional[dict] = None) -> bool:
		"""Apply all optimizations to database.
		
		Args:
			db_path: Path to SQLite database
			pragmas: Optional dict of PRAGMAs to apply
			indexes: Optional dict of indexes to create
		
		Returns:
			True if successful, False otherwise
		"""
		success = True
		success &= SQLiteOptimizer.apply_pragmas(db_path, pragmas)
		success &= SQLiteOptimizer.create_indexes(db_path, indexes)
		return success

	@staticmethod
	def vacuum_database(db_path: str) -> bool:
		"""Compact database file (defragment after bulk deletes).
		
		Args:
			db_path: Path to SQLite database
		
		Returns:
			True if successful, False otherwise
		"""
		try:
			db = sqlite3.connect(db_path)
			db.execute('VACUUM')
			db.close()
			log.info(f'Vacuumed database: {db_path}')
			return True
		except Exception as e:
			log.warning(f'Failed to vacuum database: {e}')
			return False

	@staticmethod
	def analyze_statistics(db_path: str) -> bool:
		"""Update query planner statistics (run after bulk inserts).
		
		Args:
			db_path: Path to SQLite database
		
		Returns:
			True if successful, False otherwise
		"""
		try:
			db = sqlite3.connect(db_path)
			db.execute('ANALYZE')
			db.close()
			log.info(f'Analyzed database statistics: {db_path}')
			return True
		except Exception as e:
			log.warning(f'Failed to analyze statistics: {e}')
			return False
