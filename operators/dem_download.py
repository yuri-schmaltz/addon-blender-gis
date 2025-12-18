# -*- coding:utf-8 -*-
"""
DEM Download Helpers with Resilience
Handles network retries and circuit breaker for elevation data queries
"""

import logging
import os
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

from ..core.utils.resilience import retry_with_backoff, with_circuit_breaker


TIMEOUT = 120


@retry_with_backoff(
	max_retries=3,
	initial_delay=1.0,
	backoff_factor=2.0,
	max_delay=10.0,
	exceptions=(Exception,)
)
@with_circuit_breaker('DEM_Service', failure_threshold=5, recovery_timeout=60)
def download_dem_file(url: str, filepath: str, user_agent: str, timeout: int = TIMEOUT) -> bool:
	"""
	Download DEM file from URL with automatic retry and circuit breaker protection.
	
	The function will:
	1. Retry up to 3 times with exponential backoff (1s, 2s, 4s, max 10s)
	2. Apply circuit breaker to prevent cascading failures
	3. Log all attempts and failures
	
	Args:
		url: URL to download DEM from
		filepath: Local file path to save downloaded file
		user_agent: User agent string for HTTP requests
		timeout: Request timeout in seconds (default: 120s)
	
	Returns:
		True if download successful
	
	Raises:
		URLError, HTTPError: On network errors (retried automatically)
		RuntimeError: If circuit breaker is open (service down)
		IOError: If file write fails
	
	Example:
		try:
			download_dem_file(dem_url, '/tmp/srtm.tif', 'BlenderGIS/2.2.13')
		except RuntimeError as e:
			print("DEM service temporarily unavailable")
	"""
	log.debug(f'Downloading DEM from: {url} → {filepath}')
	
	# Create directory if needed
	os.makedirs(os.path.dirname(filepath), exist_ok=True)
	
	# Download with retry/circuit breaker decorators
	rq = Request(url, headers={'User-Agent': user_agent})
	with urlopen(rq, timeout=timeout) as response:
		with open(filepath, 'wb') as outFile:
			# Stream large files in chunks
			chunk_size = 8192
			while True:
				chunk = response.read(chunk_size)
				if not chunk:
					break
				outFile.write(chunk)
	
	log.info(f'Successfully downloaded DEM to: {filepath}')
	return True
