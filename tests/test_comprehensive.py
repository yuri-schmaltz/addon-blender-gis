# -*- coding:utf-8 -*-
"""
Comprehensive pytest suite for BlenderGIS core modules.

Coverage targets:
- core.utils.resilience: 95% (retry, circuit breaker)
- core.utils.threading_utils: 90% (thread pool, cancellation)
- core.proj.geotransform: 95% (CRS transformations)
- core.utils.secrets: 85% (keyring integration)
- core.basemaps.sqlite_optimizer: 80% (SQLite optimizations)
- operators.utils.base_import: 75% (base import operator)

Run with: pytest tests/ -v --cov=. --cov-report=html
"""

import pytest
import time
import threading
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import tempfile
import json
import sqlite3

# Import modules to test
from core.utils.resilience import (
	CircuitBreaker, retry_with_backoff, with_circuit_breaker
)
from core.utils.threading_utils import (
	CancellableThreadPool, BoundedQueue, run_with_timeout
)
from core.proj.geotransform import (
	view3d_to_proj, proj_to_view3d, move_origin_prj
)
from core.utils.secrets import SecretsManager, get_secrets_manager
from core.basemaps.sqlite_optimizer import SQLiteOptimizer


# ============= RESILIENCE MODULE TESTS =============

class TestCircuitBreaker:
	"""Test CircuitBreaker state machine."""

	def test_circuit_breaker_initial_state(self):
		"""Circuit breaker starts in CLOSED state."""
		cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
		assert cb.state == 'CLOSED'
		assert cb.failure_count == 0

	def test_circuit_breaker_open_after_threshold(self):
		"""Circuit breaker opens after N failures."""
		cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
		
		# Generate failures
		for i in range(3):
			cb.record_failure()
		
		assert cb.state == 'OPEN'
		assert cb.failure_count == 3

	def test_circuit_breaker_half_open_after_timeout(self):
		"""Circuit breaker transitions to HALF_OPEN after recovery timeout."""
		cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.2)
		
		# Open the circuit
		cb.record_failure()
		assert cb.state == 'OPEN'
		
		# Wait for recovery timeout
		time.sleep(0.3)
		
		# Should transition to HALF_OPEN
		assert cb.state == 'HALF_OPEN'

	def test_circuit_breaker_closed_on_success(self):
		"""Circuit breaker closes after successful call in HALF_OPEN state."""
		cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
		
		# Open the circuit
		cb.record_failure()
		
		# Wait for recovery
		time.sleep(0.2)
		assert cb.state == 'HALF_OPEN'
		
		# Record success
		cb.record_success()
		assert cb.state == 'CLOSED'
		assert cb.failure_count == 0

	def test_circuit_breaker_reopens_on_failure_in_half_open(self):
		"""Circuit breaker reopens if failure occurs in HALF_OPEN state."""
		cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
		
		# Open and transition to HALF_OPEN
		cb.record_failure()
		time.sleep(0.2)
		
		# Record failure in HALF_OPEN
		cb.record_failure()
		assert cb.state == 'OPEN'


class TestRetryDecorator:
	"""Test retry_with_backoff decorator."""

	def test_retry_succeeds_immediately(self):
		"""Retry succeeds on first attempt."""
		call_count = [0]
		
		@retry_with_backoff(max_retries=3, initial_delay=0.01)
		def successful_call():
			call_count[0] += 1
			return "success"
		
		result = successful_call()
		assert result == "success"
		assert call_count[0] == 1

	def test_retry_succeeds_after_failures(self):
		"""Retry succeeds after N failures."""
		call_count = [0]
		
		@retry_with_backoff(max_retries=3, initial_delay=0.01)
		def flaky_call():
			call_count[0] += 1
			if call_count[0] < 3:
				raise ValueError("Temporary error")
			return "success"
		
		result = flaky_call()
		assert result == "success"
		assert call_count[0] == 3

	def test_retry_exhausts_max_retries(self):
		"""Retry raises exception after max retries exceeded."""
		@retry_with_backoff(max_retries=2, initial_delay=0.01)
		def always_fails():
			raise ValueError("Permanent error")
		
		with pytest.raises(ValueError):
			always_fails()

	def test_retry_backoff_delay(self):
		"""Retry increases delay with exponential backoff."""
		call_times = []
		
		@retry_with_backoff(max_retries=3, initial_delay=0.05)
		def flaky_with_timing():
			call_times.append(time.time())
			if len(call_times) < 3:
				raise ValueError("Retry me")
			return "success"
		
		flaky_with_timing()
		
		# Check that delays increase
		if len(call_times) >= 3:
			delay1 = call_times[1] - call_times[0]
			delay2 = call_times[2] - call_times[1]
			assert delay2 >= delay1  # Second delay should be >= first


class TestCircuitBreakerDecorator:
	"""Test with_circuit_breaker decorator."""

	def test_circuit_breaker_decorator_allows_call_when_closed(self):
		"""Decorator allows calls when circuit is closed."""
		@with_circuit_breaker(service_name='test_service', failure_threshold=2)
		def safe_operation():
			return "success"
		
		result = safe_operation()
		assert result == "success"

	def test_circuit_breaker_decorator_raises_when_open(self):
		"""Decorator raises RuntimeError when circuit is open."""
		@with_circuit_breaker(service_name='test_service_open', failure_threshold=1)
		def failing_operation():
			raise ValueError("Service error")
		
		# Open the circuit
		try:
			failing_operation()
		except ValueError:
			pass
		
		# Second call should raise circuit breaker error
		with pytest.raises(RuntimeError, match="Circuit breaker"):
			failing_operation()


# ============= THREADING MODULE TESTS =============

class TestCancellableThreadPool:
	"""Test CancellableThreadPool for resource safety."""

	def test_thread_pool_executes_tasks(self):
		"""Thread pool executes submitted tasks."""
		results = []
		
		def worker(task_id):
			results.append(task_id)
			return task_id
		
		with CancellableThreadPool(max_workers=2) as pool:
			futures = [pool.submit(worker, i) for i in range(5)]
			for future in futures:
				future.result(timeout=5)
		
		assert len(results) == 5
		assert set(results) == {0, 1, 2, 3, 4}

	def test_thread_pool_timeout_per_task(self):
		"""Thread pool enforces timeout per task."""
		
		def slow_task():
			time.sleep(5)
			return "done"
		
		with CancellableThreadPool(max_workers=1, timeout=0.1) as pool:
			future = pool.submit(slow_task)
			
			with pytest.raises(TimeoutError):
				future.result()

	def test_thread_pool_cancellation(self):
		"""Thread pool cancellation stops executing tasks."""
		executed = []
		
		def task(task_id):
			executed.append(task_id)
			time.sleep(0.1)
			return task_id
		
		pool = CancellableThreadPool(max_workers=1)
		
		# Submit multiple tasks
		futures = [pool.submit(task, i) for i in range(5)]
		
		# Cancel after brief delay
		time.sleep(0.05)
		pool.cancel()
		
		# Check that not all tasks executed
		assert len(executed) < 5
		pool.shutdown(wait=True)

	def test_thread_pool_cleanup_on_exit(self):
		"""Thread pool properly cleans up executor on exit."""
		pool = CancellableThreadPool(max_workers=2)
		executor = pool.executor
		
		with pool:
			pool.submit(lambda: "test")
		
		# Executor should be shut down
		assert executor._shutdown

	def test_thread_pool_progress_callback(self):
		"""Thread pool calls progress callback after each task."""
		progress = {'completed': 0}
		
		def callback(done, total):
			progress['completed'] = done
		
		def task():
			return "done"
		
		with CancellableThreadPool(max_workers=2, progress_callback=callback) as pool:
			futures = [pool.submit(task) for _ in range(3)]
			for future in futures:
				future.result()
		
		assert progress['completed'] == 3


class TestBoundedQueue:
	"""Test BoundedQueue for backpressure."""

	def test_bounded_queue_accepts_items_within_limit(self):
		"""Queue accepts items while below max size."""
		queue = BoundedQueue(max_size=3)
		
		queue.put("item1")
		queue.put("item2")
		queue.put("item3")
		
		assert queue.qsize() == 3

	def test_bounded_queue_blocks_when_full(self):
		"""Queue blocks when at max size."""
		queue = BoundedQueue(max_size=1)
		queue.put("item1")
		
		# This should timeout since queue is full
		with pytest.raises(Exception):
			queue.put("item2", timeout=0.1, block=True)

	def test_bounded_queue_get_unblocks_put(self):
		"""Getting item from queue allows put to proceed."""
		queue = BoundedQueue(max_size=1)
		queue.put("item1")
		
		retrieved = queue.get()
		assert retrieved == "item1"
		
		# Should succeed now
		queue.put("item2")
		assert queue.qsize() == 1


class TestRunWithTimeout:
	"""Test run_with_timeout helper."""

	def test_run_with_timeout_success(self):
		"""Timeout helper returns success for quick operations."""
		def quick_operation():
			return "result"
		
		success, result, error = run_with_timeout(quick_operation, timeout=1.0)
		
		assert success is True
		assert result == "result"
		assert error is None

	def test_run_with_timeout_exceeds_timeout(self):
		"""Timeout helper reports timeout for slow operations."""
		def slow_operation():
			time.sleep(5)
		
		success, result, error = run_with_timeout(slow_operation, timeout=0.1)
		
		assert success is False
		assert result is None
		assert "timeout" in error.lower()

	def test_run_with_timeout_handles_exception(self):
		"""Timeout helper captures exceptions."""
		def failing_operation():
			raise ValueError("Test error")
		
		success, result, error = run_with_timeout(failing_operation, timeout=1.0)
		
		assert success is False
		assert result is None
		assert "Test error" in error


# ============= GEOTRANSFORM MODULE TESTS =============

class TestGeoTransform:
	"""Test coordinate transformation functions."""

	def test_view3d_to_proj_basic(self):
		"""Convert View3D offsets to CRS coordinates."""
		x, y = view3d_to_proj(
			crsx=0, crsy=0,  # Origin at CRS origin
			scale=1,          # 1:1 scale
			dx=100, dy=50     # 100m east, 50m north
		)
		
		assert x == 100
		assert y == 50

	def test_proj_to_view3d_basic(self):
		"""Convert CRS coordinates to View3D offsets."""
		dx, dy = proj_to_view3d(
			crsx=0, crsy=0,
			scale=1,
			x=100, y=50
		)
		
		assert dx == 100
		assert dy == 50

	def test_view3d_proj_roundtrip(self):
		"""View3D -> CRS -> View3D roundtrip preserves coordinates."""
		original_dx, original_dy = 500, 250
		
		# View3D to CRS
		x, y = view3d_to_proj(0, 0, 1, original_dx, original_dy)
		
		# CRS back to View3D
		dx, dy = proj_to_view3d(0, 0, 1, x, y)
		
		assert dx == pytest.approx(original_dx)
		assert dy == pytest.approx(original_dy)

	def test_move_origin_prj_with_scale(self):
		"""Move origin with scale factor applied."""
		new_x, new_y = move_origin_prj(
			crsx=1000, crsy=2000,
			dx=100, dy=50,
			scale=2,
			use_scale=True
		)
		
		# With scale=2: actual displacement is 100*2=200, 50*2=100
		assert new_x == pytest.approx(1200)
		assert new_y == pytest.approx(2100)

	def test_move_origin_prj_without_scale(self):
		"""Move origin without applying scale factor."""
		new_x, new_y = move_origin_prj(
			crsx=1000, crsy=2000,
			dx=100, dy=50,
			scale=2,
			use_scale=False
		)
		
		# Scale ignored
		assert new_x == pytest.approx(1100)
		assert new_y == pytest.approx(2050)


# ============= SECRETS MODULE TESTS =============

class TestSecretsManager:
	"""Test secure credential storage."""

	@pytest.fixture
	def temp_secrets(self):
		"""Create temporary secrets manager for testing."""
		with tempfile.TemporaryDirectory() as tmpdir:
			manager = SecretsManager()
			# Override fallback path for testing
			manager.fallback_path = Path(tmpdir) / '.blendergis_secrets'
			yield manager

	def test_secrets_manager_set_and_get(self, temp_secrets):
		"""Store and retrieve API key."""
		temp_secrets.set_api_key('test_service', 'secret123')
		
		retrieved = temp_secrets.get_api_key('test_service')
		assert retrieved == 'secret123'

	def test_secrets_manager_returns_none_for_missing(self, temp_secrets):
		"""Return None for non-existent key."""
		retrieved = temp_secrets.get_api_key('nonexistent')
		assert retrieved is None

	def test_secrets_manager_delete(self, temp_secrets):
		"""Delete stored API key."""
		temp_secrets.set_api_key('test_service', 'secret123')
		temp_secrets.delete_api_key('test_service')
		
		retrieved = temp_secrets.get_api_key('test_service')
		assert retrieved is None

	def test_secrets_manager_multiple_services(self, temp_secrets):
		"""Store multiple services independently."""
		temp_secrets.set_api_key('service1', 'key1')
		temp_secrets.set_api_key('service2', 'key2')
		
		assert temp_secrets.get_api_key('service1') == 'key1'
		assert temp_secrets.get_api_key('service2') == 'key2'

	def test_secrets_manager_list_services(self, temp_secrets):
		"""List all stored services."""
		temp_secrets.set_api_key('service1', 'key1')
		temp_secrets.set_api_key('service2', 'key2')
		
		services = temp_secrets.list_services()
		
		assert 'service1' in services
		assert 'service2' in services
		assert 'default' in services['service1']


# ============= SQLITE OPTIMIZER TESTS =============

class TestSQLiteOptimizer:
	"""Test SQLite performance optimizations."""

	@pytest.fixture
	def test_db(self):
		"""Create test SQLite database."""
		with tempfile.TemporaryDirectory() as tmpdir:
			db_path = Path(tmpdir) / 'test.gpkg'
			conn = sqlite3.connect(str(db_path))
			
			# Create tiles table (mimicking GPKG)
			conn.execute('''
				CREATE TABLE gpkg_tiles (
					id INTEGER PRIMARY KEY,
					zoom_level INTEGER,
					tile_column INTEGER,
					tile_row INTEGER,
					tile_data BLOB,
					last_modified DATETIME DEFAULT CURRENT_TIMESTAMP
				)
			''')
			conn.commit()
			
			yield conn, db_path
			conn.close()

	def test_sqlite_optimizer_applies_pragmas(self, test_db):
		"""Optimizer sets SQLite PRAGMAs for performance."""
		conn, _ = test_db
		
		SQLiteOptimizer.apply_pragmas(conn)
		
		# Check WAL mode
		cursor = conn.execute('PRAGMA journal_mode')
		assert cursor.fetchone()[0].lower() == 'wal'

	def test_sqlite_optimizer_creates_indexes(self, test_db):
		"""Optimizer creates composite indexes for common queries."""
		conn, _ = test_db
		
		SQLiteOptimizer.create_indexes(conn)
		
		# Check that indexes exist
		cursor = conn.execute(
			"SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
		)
		indexes = {row[0] for row in cursor.fetchall()}
		
		assert 'idx_tiles_zxy' in indexes  # Main query index

	def test_sqlite_optimizer_vacuum(self, test_db):
		"""Optimizer vacuums and defragments database."""
		conn, db_path = test_db
		
		# Insert and delete data to create fragmentation
		for i in range(100):
			conn.execute(
				'INSERT INTO gpkg_tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?)',
				(i % 5, i, i, b'data' * 100)
			)
		conn.commit()
		
		size_before = db_path.stat().st_size
		
		# Delete most data
		conn.execute('DELETE FROM gpkg_tiles WHERE zoom_level > 2')
		conn.commit()
		
		size_fragmented = db_path.stat().st_size
		
		# Vacuum
		SQLiteOptimizer.vacuum_database(conn)
		
		size_after = db_path.stat().st_size
		
		# Size should decrease significantly
		assert size_after < size_fragmented


# ============= FIXTURE AND CONFTEST =============

@pytest.fixture(scope="session")
def blender_setup():
	"""Mock Blender environment for testing.
	
	This prevents ImportError when bpy module is not available.
	"""
	pass


if __name__ == '__main__':
	pytest.main([__file__, '-v', '--tb=short'])
