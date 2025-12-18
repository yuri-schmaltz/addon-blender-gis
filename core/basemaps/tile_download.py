# -*- coding:utf-8 -*-
"""
Tile Downloading with Resilience
Provides robust tile fetching for map services with retry and circuit breaker
"""

import logging
import time
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

log = logging.getLogger(__name__)

from ..utils.resilience import retry_with_backoff, with_circuit_breaker


TIMEOUT = 4  # Tiles are small, 4s should be sufficient


@retry_with_backoff(
	max_retries=3,
	initial_delay=0.5,
	backoff_factor=2.0,
	max_delay=5.0,
	exceptions=(URLError, HTTPError, TimeoutError)
)
@with_circuit_breaker('TileServer', failure_threshold=10, recovery_timeout=30)
def download_tile(url: str, user_agent: str, timeout: int = TIMEOUT) -> bytes:
	"""
	Download a single map tile with automatic retry and circuit breaker.
	
	Retry Strategy:
	- Initial delay: 0.5s
	- Backoff: 2x (0.5s → 1s → 2s → max 5s)
	- Max attempts: 3 retries
	
	Circuit Breaker:
	- Opens after 10 consecutive failures
	- Attempts recovery after 30 seconds
	
	Args:
		url: URL of tile to download
		user_agent: User agent string
		timeout: Request timeout in seconds
	
	Returns:
		Tile data as bytes
	
	Raises:
		URLError, HTTPError: On network errors (retried automatically)
		RuntimeError: If circuit breaker is open
		TimeoutError: If request times out (retried automatically)
	
	Example:
		tile_data = download_tile(
			'https://tile.openstreetmap.org/0/0/0.png',
			'BlenderGIS/2.2.13'
		)
	"""
	rq = Request(url, headers={'User-Agent': user_agent})
	response = urlopen(rq, timeout=timeout)
	return response.read()


def download_tile_safe(
	url: str,
	user_agent: str,
	timeout: int = TIMEOUT,
	callback_on_error = None
) -> tuple[bool, bytes | None, str | None]:
	"""
	Download tile with error handling and logging (non-raising version).
	
	Args:
		url: Tile URL
		user_agent: User agent
		timeout: Request timeout
		callback_on_error: Optional callback(error_msg) on failure
	
	Returns:
		Tuple of (success: bool, data: bytes | None, error: str | None)
	
	Example:
		success, data, error = download_tile_safe(url, user_agent)
		if not success:
			print(f"Tile failed: {error}")
	"""
	try:
		data = download_tile(url, user_agent, timeout)
		return True, data, None
	except RuntimeError as e:
		# Circuit breaker open
		msg = f"Tile service temporarily unavailable: {str(e)}"
		log.warning(msg)
		if callback_on_error:
			callback_on_error(msg)
		return False, None, msg
	except (URLError, HTTPError) as e:
		# Network error (after retries exhausted)
		msg = f"Tile download failed (HTTP {getattr(e, 'code', '?')}): {str(e)}"
		log.warning(msg)
		if callback_on_error:
			callback_on_error(msg)
		return False, None, msg
	except TimeoutError as e:
		# Timeout (after retries exhausted)
		msg = f"Tile download timeout after {timeout}s"
		log.warning(msg)
		if callback_on_error:
			callback_on_error(msg)
		return False, None, msg
	except Exception as e:
		# Unexpected error
		msg = f"Unexpected tile download error: {str(e)}"
		log.error(msg, exc_info=True)
		if callback_on_error:
			callback_on_error(msg)
		return False, None, msg
