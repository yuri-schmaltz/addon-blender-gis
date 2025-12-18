# -*- coding:utf-8 -*-
"""
Improved Threading Utilities for BlenderGIS
Provides thread pool management with proper resource cleanup and cancellation
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from typing import Callable, Any, List, Optional, Tuple

log = logging.getLogger(__name__)


class CancellableThreadPool:
	"""
	Thread pool with graceful shutdown, timeout support, and progress tracking.
	
	Replaces manual thread management in MapService.seedTiles() and similar.
	Prevents thread leaks and provides clean cancellation.
	"""
	
	def __init__(self, max_workers: int = 5, timeout: int = 30):
		"""
		Args:
			max_workers: Maximum concurrent threads (default: 5, was 10 - reduced for stability)
			timeout: Timeout per task in seconds
		"""
		self.max_workers = max_workers
		self.timeout = timeout
		self.executor = ThreadPoolExecutor(max_workers=max_workers)
		self.futures = []
		self.cancel_event = threading.Event()
		self.results = []
		self.errors = []
	
	def submit_task(self, fn: Callable, *args, **kwargs) -> None:
		"""Submit a task to the thread pool"""
		if self.cancel_event.is_set():
			log.warning('Cannot submit task: cancellation in progress')
			return
		
		future = self.executor.submit(fn, *args, **kwargs)
		self.futures.append(future)
	
	def wait_completion(self, callback_progress: Optional[Callable] = None) -> Tuple[List, List]:
		"""
		Wait for all tasks to complete with optional progress callback.
		
		Args:
			callback_progress: Optional function(completed_count, total_count) called periodically
		
		Returns:
			Tuple of (results, errors)
		
		Raises:
			RuntimeError: If cancellation was requested
		"""
		total = len(self.futures)
		completed = 0
		
		try:
			for future in as_completed(self.futures, timeout=self.timeout):
				if self.cancel_event.is_set():
					log.warning('Cancellation requested during wait_completion')
					raise RuntimeError('Task cancelled by user')
				
				try:
					result = future.result(timeout=1)
					self.results.append(result)
				except TimeoutError:
					log.warning('Task timeout after %ds', self.timeout)
					self.errors.append('Task timeout')
				except Exception as e:
					log.warning('Task error: %s', str(e))
					self.errors.append(str(e))
				
				completed += 1
				if callback_progress:
					callback_progress(completed, total)
		
		finally:
			self.shutdown(wait=True)
		
		return self.results, self.errors
	
	def cancel(self) -> None:
		"""Request cancellation of all pending tasks"""
		log.info('Cancelling thread pool (max_workers=%d)', self.max_workers)
		self.cancel_event.set()
		
		# Cancel pending futures
		for future in self.futures:
			future.cancel()
		
		# Shutdown executor
		self.shutdown(wait=False)
	
	def shutdown(self, wait: bool = True) -> None:
		"""Shutdown executor cleanly"""
		try:
			self.executor.shutdown(wait=wait)
			log.debug('Thread pool shutdown complete')
		except Exception as e:
			log.warning('Error during thread pool shutdown: %s', str(e))
	
	@property
	def is_cancelled(self) -> bool:
		"""Check if cancellation was requested"""
		return self.cancel_event.is_set()
	
	@property
	def error_count(self) -> int:
		"""Number of failed tasks"""
		return len(self.errors)
	
	@property
	def success_count(self) -> int:
		"""Number of successful tasks"""
		return len(self.results)


class BoundedQueue:
	"""
	Thread-safe queue with bounded size to prevent memory issues.
	Blocks producer when full, allowing consumer to catch up.
	"""
	
	def __init__(self, maxsize: int = 100):
		"""
		Args:
			maxsize: Maximum queue size (blocks put() when reached)
		"""
		self.queue = []
		self.maxsize = maxsize
		self.lock = threading.Lock()
		self.not_full = threading.Condition(self.lock)
		self.not_empty = threading.Condition(self.lock)
	
	def put(self, item: Any, timeout: Optional[int] = None) -> None:
		"""
		Put item in queue, blocking if full.
		
		Args:
			item: Item to add
			timeout: Max seconds to wait (None = infinite)
		
		Raises:
			TimeoutError: If timeout exceeded
		"""
		with self.not_full:
			start_time = time.time()
			while len(self.queue) >= self.maxsize:
				if timeout is not None:
					elapsed = time.time() - start_time
					if elapsed >= timeout:
						raise TimeoutError(f'Queue full after {timeout}s')
					wait_time = timeout - elapsed
				else:
					wait_time = None
				
				self.not_full.wait(timeout=wait_time)
			
			self.queue.append(item)
			self.not_empty.notify()
	
	def get(self, timeout: Optional[int] = None) -> Any:
		"""
		Get item from queue, blocking if empty.
		
		Args:
			timeout: Max seconds to wait
		
		Raises:
			TimeoutError: If timeout exceeded
		"""
		with self.not_empty:
			start_time = time.time()
			while len(self.queue) == 0:
				if timeout is not None:
					elapsed = time.time() - start_time
					if elapsed >= timeout:
						raise TimeoutError(f'Queue empty after {timeout}s')
					wait_time = timeout - elapsed
				else:
					wait_time = None
				
				self.not_empty.wait(timeout=wait_time)
			
			item = self.queue.pop(0)
			self.not_full.notify()
			return item
	
	def qsize(self) -> int:
		"""Get current queue size"""
		with self.lock:
			return len(self.queue)
	
	def empty(self) -> bool:
		"""Check if queue is empty"""
		with self.lock:
			return len(self.queue) == 0
	
	def full(self) -> bool:
		"""Check if queue is full"""
		with self.lock:
			return len(self.queue) >= self.maxsize


def run_with_timeout(fn: Callable, timeout: int, *args, **kwargs) -> Tuple[bool, Any, Optional[str]]:
	"""
	Run function in thread with timeout, returning (success, result, error).
	
	Args:
		fn: Function to run
		timeout: Timeout in seconds
		*args, **kwargs: Arguments to fn
	
	Returns:
		Tuple of (success, result, error_msg)
	"""
	result_box = [None, None, None]  # [success, result, error]
	
	def worker():
		try:
			result = fn(*args, **kwargs)
			result_box[0] = True
			result_box[1] = result
		except Exception as e:
			result_box[0] = False
			result_box[2] = str(e)
			log.warning('Worker error: %s', str(e))
	
	thread = threading.Thread(target=worker, daemon=False)
	thread.start()
	thread.join(timeout=timeout)
	
	if thread.is_alive():
		log.warning('Thread timeout after %ds', timeout)
		return False, None, f'Timeout after {timeout}s'
	
	return tuple(result_box)
