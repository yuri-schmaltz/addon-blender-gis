# -*- coding:utf-8 -*-
"""
Network resilience utilities: retry logic and circuit breaker pattern
Provides robust handling of network failures for GIS data fetching
"""

import logging
import time
from functools import wraps
from typing import Callable, Any, Optional, Tuple

log = logging.getLogger(__name__)


class CircuitBreaker:
	"""
	Circuit breaker pattern for failing external services.
	Prevents cascading failures by temporarily stopping requests to a failing service.
	
	States:
	- CLOSED: Normal operation, requests allowed
	- OPEN: Service failing, requests blocked
	- HALF_OPEN: Testing if service recovered
	"""
	
	def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
		"""
		Args:
			failure_threshold: Number of failures before opening circuit (default: 5)
			recovery_timeout: Seconds to wait before attempting recovery (default: 60s)
		"""
		self.failure_threshold = failure_threshold
		self.recovery_timeout = recovery_timeout
		
		self.failure_count = 0
		self.success_count = 0
		self.last_failure_time = None
		self.state = 'CLOSED'  # CLOSED, OPEN, HALF_OPEN
	
	def record_success(self):
		"""Record successful request"""
		self.failure_count = 0
		if self.state == 'HALF_OPEN':
			self.state = 'CLOSED'
			log.info('Circuit breaker CLOSED: Service recovered')
	
	def record_failure(self):
		"""Record failed request"""
		self.failure_count += 1
		self.last_failure_time = time.time()
		
		if self.failure_count >= self.failure_threshold:
			self.state = 'OPEN'
			log.warning(f'Circuit breaker OPEN: {self.failure_threshold} consecutive failures')
	
	def allow_request(self) -> bool:
		"""Check if request is allowed"""
		if self.state == 'CLOSED':
			return True
		
		if self.state == 'OPEN':
			# Check if recovery timeout has elapsed
			if time.time() - self.last_failure_time >= self.recovery_timeout:
				self.state = 'HALF_OPEN'
				log.info('Circuit breaker HALF_OPEN: Testing service recovery')
				return True
			return False
		
		# HALF_OPEN: allow single test request
		return True


def retry_with_backoff(
	max_retries: int = 3,
	initial_delay: float = 1.0,
	backoff_factor: float = 2.0,
	max_delay: float = 30.0,
	jitter: bool = True,
	exceptions: Tuple = (Exception,)
) -> Callable:
	"""
	Decorator for exponential backoff retry logic with jitter.
	
	Args:
		max_retries: Maximum number of retry attempts (default: 3)
		initial_delay: Initial delay in seconds (default: 1.0s)
		backoff_factor: Multiplier for delay on each retry (default: 2.0x)
		max_delay: Maximum delay between retries (default: 30s)
		jitter: Add randomness to prevent thundering herd (default: True)
		exceptions: Tuple of exceptions to catch and retry (default: all)
	
	Returns:
		Decorated function with retry logic
	
	Example:
		@retry_with_backoff(max_retries=3, initial_delay=1.0)
		def fetch_dem(url):
			return urlopen(url).read()
	"""
	def decorator(func: Callable) -> Callable:
		@wraps(func)
		def wrapper(*args, **kwargs) -> Any:
			delay = initial_delay
			last_exception = None
			
			for attempt in range(max_retries + 1):
				try:
					result = func(*args, **kwargs)
					log.debug(f'{func.__name__} succeeded on attempt {attempt + 1}')
					return result
				except exceptions as e:
					last_exception = e
					
					if attempt < max_retries:
						# Calculate delay with exponential backoff
						delay = min(initial_delay * (backoff_factor ** attempt), max_delay)
						
						# Add jitter (random 0-20% variance)
						if jitter:
							import random
							jitter_amount = delay * random.uniform(0, 0.2)
							delay = delay + jitter_amount
						
						log.warning(
							f'{func.__name__} failed (attempt {attempt + 1}/{max_retries + 1}): {str(e)}. '
							f'Retrying in {delay:.1f}s...'
						)
						time.sleep(delay)
					else:
						log.error(
							f'{func.__name__} failed after {max_retries + 1} attempts: {str(e)}'
						)
			
			raise last_exception
		
		return wrapper
	
	return decorator


def with_circuit_breaker(
	service_name: str,
	failure_threshold: int = 5,
	recovery_timeout: int = 60
) -> Callable:
	"""
	Decorator that applies circuit breaker pattern to a function.
	
	Args:
		service_name: Name of service for logging (e.g. 'OpenTopography')
		failure_threshold: Failures before opening circuit
		recovery_timeout: Seconds before attempting recovery
	
	Returns:
		Decorated function with circuit breaker protection
	
	Example:
		@with_circuit_breaker('OpenTopography', failure_threshold=5)
		def fetch_dem(url):
			return urlopen(url).read()
	"""
	# Global circuit breakers by service
	if not hasattr(with_circuit_breaker, 'breakers'):
		with_circuit_breaker.breakers = {}
	
	if service_name not in with_circuit_breaker.breakers:
		with_circuit_breaker.breakers[service_name] = CircuitBreaker(
			failure_threshold=failure_threshold,
			recovery_timeout=recovery_timeout
		)
	
	breaker = with_circuit_breaker.breakers[service_name]
	
	def decorator(func: Callable) -> Callable:
		@wraps(func)
		def wrapper(*args, **kwargs) -> Any:
			if not breaker.allow_request():
				raise RuntimeError(
					f'Circuit breaker OPEN for {service_name}. '
					f'Service unavailable. Will retry in {breaker.recovery_timeout}s.'
				)
			
			try:
				result = func(*args, **kwargs)
				breaker.record_success()
				return result
			except Exception as e:
				breaker.record_failure()
				raise
		
		return wrapper
	
	return decorator
