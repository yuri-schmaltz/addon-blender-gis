# -*- coding:utf-8 -*-
"""
Performance monitoring and telemetry for BlenderGIS.

Collects metrics:
- Download speeds (bytes/sec)
- Cache hit/miss rates
- Error rates and types
- Operation latencies
- Memory usage peaks

Provides visualization dashboard and regression alerts.
"""

import time
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from collections import deque, defaultdict
from dataclasses import dataclass, asdict
import json
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class MetricEvent:
	"""Single metric measurement."""
	timestamp: float
	operation: str
	metric_name: str
	value: float
	metadata: Dict = None

	def to_dict(self):
		"""Convert to dictionary."""
		return {
			'timestamp': self.timestamp,
			'operation': self.operation,
			'metric_name': self.metric_name,
			'value': self.value,
			'metadata': self.metadata or {}
		}


class PerformanceMonitor:
	"""Monitors and aggregates performance metrics."""

	def __init__(self, max_events: int = 10000):
		"""Initialize performance monitor.
		
		Args:
			max_events: Maximum events to keep in memory
		"""
		self.max_events = max_events
		self.events = deque(maxlen=max_events)
		self.thresholds = self._init_thresholds()

	def _init_thresholds(self) -> Dict:
		"""Initialize performance thresholds for alerts."""
		return {
			'download_speed': {'min': 100000, 'unit': 'bytes/sec'},  # Min 100KB/s
			'cache_hit_rate': {'min': 0.7, 'unit': '%'},  # Min 70% hit rate
			'tile_download_latency': {'max': 5.0, 'unit': 'sec'},  # Max 5s per tile
			'raster_import_latency': {'max': 30.0, 'unit': 'sec'},  # Max 30s
			'error_rate': {'max': 0.05, 'unit': 'ratio'},  # Max 5% errors
		}

	def record_metric(
		self,
		operation: str,
		metric_name: str,
		value: float,
		metadata: Optional[Dict] = None
	):
		"""Record single metric event.
		
		Args:
			operation: Operation name (e.g., 'tile_download', 'raster_import')
			metric_name: Metric name (e.g., 'latency', 'download_speed')
			value: Metric value
			metadata: Optional metadata (file size, count, etc.)
		"""
		event = MetricEvent(
			timestamp=time.time(),
			operation=operation,
			metric_name=metric_name,
			value=value,
			metadata=metadata
		)
		self.events.append(event)
		
		# Check thresholds
		self._check_thresholds(event)

	def _check_thresholds(self, event: MetricEvent):
		"""Check if metric exceeds thresholds and alert if needed."""
		threshold_key = f"{event.operation}_{event.metric_name}"
		
		if threshold_key not in self.thresholds:
			return

		threshold = self.thresholds[threshold_key]

		# Check minimum threshold
		if 'min' in threshold and event.value < threshold['min']:
			log.warning(
				f"Performance regression: {event.operation}.{event.metric_name} = {event.value} "
				f"(expected >= {threshold['min']})"
			)

		# Check maximum threshold
		if 'max' in threshold and event.value > threshold['max']:
			log.warning(
				f"Performance regression: {event.operation}.{event.metric_name} = {event.value} "
				f"(expected <= {threshold['max']})"
			)

	def get_metric_summary(
		self,
		operation: Optional[str] = None,
		metric_name: Optional[str] = None,
		minutes: int = 60
	) -> Dict:
		"""Get aggregated metric summary.
		
		Args:
			operation: Filter by operation (None = all)
			metric_name: Filter by metric name (None = all)
			minutes: Time window in minutes (0 = all time)

		Returns:
			Dict with min, max, mean, count, etc.
		"""
		cutoff_time = time.time() - (minutes * 60) if minutes > 0 else 0

		# Filter events
		filtered = [
			e for e in self.events
			if e.timestamp >= cutoff_time
			and (operation is None or e.operation == operation)
			and (metric_name is None or e.metric_name == metric_name)
		]

		if not filtered:
			return {}

		values = [e.value for e in filtered]

		return {
			'count': len(filtered),
			'min': min(values),
			'max': max(values),
			'mean': sum(values) / len(values),
			'median': sorted(values)[len(values) // 2],
			'p95': sorted(values)[int(len(values) * 0.95)],
			'p99': sorted(values)[int(len(values) * 0.99)],
			'sum': sum(values),
		}

	def get_operation_stats(self, minutes: int = 60) -> Dict:
		"""Get statistics by operation type.
		
		Args:
			minutes: Time window in minutes

		Returns:
			Dict mapping operation -> {metric -> stats}
		"""
		cutoff_time = time.time() - (minutes * 60) if minutes > 0 else 0
		
		# Group by operation and metric
		grouped = defaultdict(lambda: defaultdict(list))
		
		for event in self.events:
			if event.timestamp >= cutoff_time:
				grouped[event.operation][event.metric_name].append(event.value)

		# Calculate stats
		stats = {}
		for op_name, metrics in grouped.items():
			stats[op_name] = {}
			for metric_name, values in metrics.items():
				if values:
					stats[op_name][metric_name] = {
						'count': len(values),
						'mean': sum(values) / len(values),
						'min': min(values),
						'max': max(values),
					}

		return stats

	def get_cache_statistics(self, minutes: int = 60) -> Dict:
		"""Get cache hit/miss statistics.
		
		Args:
			minutes: Time window in minutes

		Returns:
			Dict with hit_count, miss_count, hit_rate
		"""
		cutoff_time = time.time() - (minutes * 60) if minutes > 0 else 0

		cache_events = [
			e for e in self.events
			if e.timestamp >= cutoff_time
			and e.operation == 'cache_lookup'
		]

		if not cache_events:
			return {'hit_count': 0, 'miss_count': 0, 'hit_rate': 0}

		hit_count = sum(1 for e in cache_events if e.metric_name == 'cache_hit')
		miss_count = sum(1 for e in cache_events if e.metric_name == 'cache_miss')
		total = hit_count + miss_count

		return {
			'hit_count': hit_count,
			'miss_count': miss_count,
			'hit_rate': hit_count / total if total > 0 else 0,
		}

	def get_error_statistics(self, minutes: int = 60) -> Dict:
		"""Get error statistics.
		
		Args:
			minutes: Time window in minutes

		Returns:
			Dict with error counts by type
		"""
		cutoff_time = time.time() - (minutes * 60) if minutes > 0 else 0

		error_events = [
			e for e in self.events
			if e.timestamp >= cutoff_time
			and 'error' in e.metric_name.lower()
		]

		if not error_events:
			return {}

		# Group by error type
		errors_by_type = defaultdict(int)
		for event in error_events:
			error_type = event.metadata.get('error_type', 'unknown') if event.metadata else 'unknown'
			errors_by_type[error_type] += 1

		return dict(errors_by_type)

	def export_metrics(self, filepath: Path):
		"""Export collected metrics to JSON file.
		
		Args:
			filepath: Path to export to
		"""
		try:
			with open(filepath, 'w') as f:
				json.dump(
					[e.to_dict() for e in self.events],
					f,
					indent=2,
					default=str
				)
			log.info(f"Exported {len(self.events)} metrics to {filepath}")
		except Exception as e:
			log.error(f"Failed to export metrics: {e}")

	def import_metrics(self, filepath: Path):
		"""Import metrics from JSON file.
		
		Args:
			filepath: Path to import from
		"""
		try:
			with open(filepath, 'r') as f:
				data = json.load(f)
			
			for item in data:
				event = MetricEvent(
					timestamp=item['timestamp'],
					operation=item['operation'],
					metric_name=item['metric_name'],
					value=item['value'],
					metadata=item.get('metadata')
				)
				self.events.append(event)
			
			log.info(f"Imported {len(data)} metrics from {filepath}")
		except Exception as e:
			log.error(f"Failed to import metrics: {e}")

	def clear_metrics(self):
		"""Clear all collected metrics."""
		self.events.clear()
		log.info("Cleared all metrics")


class DownloadSpeedMonitor:
	"""Monitor download speeds for tile/DEM downloads."""

	def __init__(self, monitor: PerformanceMonitor):
		self.monitor = monitor
		self.start_time = None
		self.bytes_transferred = 0

	def start(self):
		"""Start measuring download speed."""
		self.start_time = time.time()
		self.bytes_transferred = 0

	def add_bytes(self, byte_count: int):
		"""Record bytes transferred."""
		self.bytes_transferred += byte_count

	def finish(self, operation: str):
		"""Finish download and record speed metric.
		
		Args:
			operation: Operation name (e.g., 'tile_download', 'dem_download')
		"""
		if self.start_time is None:
			return

		elapsed = time.time() - self.start_time
		if elapsed <= 0:
			return

		speed = self.bytes_transferred / elapsed  # bytes/sec

		self.monitor.record_metric(
			operation=operation,
			metric_name='download_speed',
			value=speed,
			metadata={
				'bytes': self.bytes_transferred,
				'elapsed_sec': elapsed
			}
		)

		# Reset for next measurement
		self.start_time = None
		self.bytes_transferred = 0


class LatencyMonitor:
	"""Monitor operation latencies."""

	def __init__(self, monitor: PerformanceMonitor):
		self.monitor = monitor
		self.start_time = None
		self.operation_name = None

	def start(self, operation: str):
		"""Start measuring operation latency.
		
		Args:
			operation: Operation name
		"""
		self.operation_name = operation
		self.start_time = time.time()

	def finish(self, metadata: Optional[Dict] = None):
		"""Finish measurement and record latency.
		
		Args:
			metadata: Optional metadata about the operation
		"""
		if self.start_time is None or self.operation_name is None:
			return

		latency = time.time() - self.start_time

		self.monitor.record_metric(
			operation=self.operation_name,
			metric_name='latency',
			value=latency,
			metadata=metadata
		)

		self.start_time = None
		self.operation_name = None


# Global performance monitor instance
_performance_monitor = None


def get_performance_monitor() -> PerformanceMonitor:
	"""Get or create global performance monitor."""
	global _performance_monitor
	if _performance_monitor is None:
		_performance_monitor = PerformanceMonitor()
	return _performance_monitor


def record_metric(
	operation: str,
	metric_name: str,
	value: float,
	metadata: Optional[Dict] = None
):
	"""Convenience function to record metric."""
	get_performance_monitor().record_metric(operation, metric_name, value, metadata)


def get_download_speed_monitor() -> DownloadSpeedMonitor:
	"""Get download speed monitor."""
	return DownloadSpeedMonitor(get_performance_monitor())


def get_latency_monitor() -> LatencyMonitor:
	"""Get latency monitor."""
	return LatencyMonitor(get_performance_monitor())
