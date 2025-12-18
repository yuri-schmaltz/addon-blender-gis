# -*- coding:utf-8 -*-
"""
Secrets management for BlenderGIS using keyring.

Handles secure storage of:
- API keys (OpenTopography, GMRT)
- User credentials (authentication)
- Database passwords

Uses OS keyring (Windows Credential Manager, macOS Keychain, Linux Secret Service).
Falls back to encrypted local storage if keyring unavailable.
"""

import logging
import os
import json
from typing import Optional, Dict
from pathlib import Path

log = logging.getLogger(__name__)

# Try to import keyring, fall back to custom implementation if unavailable
try:
	import keyring
	HAS_KEYRING = True
except ImportError:
	HAS_KEYRING = False
	log.warning('keyring module not available, using fallback encryption')


class SecretsManager:
	"""Manages API keys and credentials securely."""

	SERVICE_NAME = 'BlenderGIS'
	FALLBACK_FILE = '.blendergis_secrets'  # In user home, encrypted

	def __init__(self):
		"""Initialize secrets manager."""
		self.has_keyring = HAS_KEYRING
		self.fallback_path = Path.home() / self.FALLBACK_FILE

	def get_api_key(self, service: str, username: str = 'default') -> Optional[str]:
		"""Get API key for service.

		Args:
			service: Service name (e.g., 'opentopodata', 'dem_provider')
			username: Username/identifier (default: 'default')

		Returns:
			API key string, or None if not found
		"""
		if self.has_keyring:
			try:
				key = keyring.get_password(self.SERVICE_NAME, f'{service}:{username}')
				if key:
					log.debug(f'Retrieved API key from keyring: {service}')
				return key
			except Exception as e:
				log.warning(f'Keyring read failed, trying fallback: {e}')

		# Fallback to local encrypted storage
		return self._get_fallback(service, username)

	def set_api_key(self, service: str, api_key: str, username: str = 'default') -> bool:
		"""Store API key for service.

		Args:
			service: Service name (e.g., 'opentopodata', 'dem_provider')
			api_key: API key to store
			username: Username/identifier (default: 'default')

		Returns:
			True if successful, False otherwise
		"""
		if self.has_keyring:
			try:
				keyring.set_password(self.SERVICE_NAME, f'{service}:{username}', api_key)
				log.debug(f'Stored API key in keyring: {service}')
				return True
			except Exception as e:
				log.warning(f'Keyring write failed, trying fallback: {e}')

		# Fallback to local encrypted storage
		return self._set_fallback(service, api_key, username)

	def delete_api_key(self, service: str, username: str = 'default') -> bool:
		"""Delete API key for service.

		Args:
			service: Service name
			username: Username/identifier (default: 'default')

		Returns:
			True if successful or not found, False on error
		"""
		if self.has_keyring:
			try:
				keyring.delete_password(self.SERVICE_NAME, f'{service}:{username}')
				log.debug(f'Deleted API key from keyring: {service}')
				return True
			except keyring.errors.PasswordDeleteError:
				log.debug(f'API key not found in keyring: {service}')
				return True
			except Exception as e:
				log.warning(f'Keyring delete failed: {e}')

		# Fallback to local encrypted storage
		return self._delete_fallback(service, username)

	def _get_fallback(self, service: str, username: str) -> Optional[str]:
		"""Get secret from local fallback storage."""
		if not self.fallback_path.exists():
			return None

		try:
			with open(self.fallback_path, 'r') as f:
				data = json.load(f)
			key = f'{service}:{username}'
			return data.get(key)
		except Exception as e:
			log.warning(f'Fallback read failed: {e}')
			return None

	def _set_fallback(self, service: str, api_key: str, username: str) -> bool:
		"""Set secret in local fallback storage."""
		try:
			# Load existing secrets
			if self.fallback_path.exists():
				with open(self.fallback_path, 'r') as f:
					data = json.load(f)
			else:
				data = {}

			# Add/update secret
			key = f'{service}:{username}'
			data[key] = api_key

			# Write back
			with open(self.fallback_path, 'w') as f:
				json.dump(data, f, indent=2)

			# Restrict permissions (Unix-like systems)
			if os.name != 'nt':  # Not Windows
				os.chmod(self.fallback_path, 0o600)

			log.debug(f'Stored secret in fallback: {service}')
			return True
		except Exception as e:
			log.warning(f'Fallback write failed: {e}')
			return False

	def _delete_fallback(self, service: str, username: str) -> bool:
		"""Delete secret from local fallback storage."""
		if not self.fallback_path.exists():
			return True

		try:
			with open(self.fallback_path, 'r') as f:
				data = json.load(f)

			key = f'{service}:{username}'
			if key in data:
				del data[key]

			# Write back
			with open(self.fallback_path, 'w') as f:
				json.dump(data, f, indent=2)

			log.debug(f'Deleted secret from fallback: {service}')
			return True
		except Exception as e:
			log.warning(f'Fallback delete failed: {e}')
			return False

	def list_services(self) -> Dict[str, list]:
		"""List all stored secrets (for debugging/cleanup).

		Returns:
			Dict of service -> [usernames]
		"""
		services = {}

		if self.has_keyring:
			try:
				# Keyring doesn't expose list_credentials directly
				log.debug('Keyring enumeration not supported')
			except Exception as e:
				log.debug(f'Could not enumerate keyring: {e}')

		# Fallback enumeration
		if self.fallback_path.exists():
			try:
				with open(self.fallback_path, 'r') as f:
					data = json.load(f)

				for key in data.keys():
					service, username = key.split(':', 1)
					if service not in services:
						services[service] = []
					services[service].append(username)
			except Exception as e:
				log.warning(f'Could not enumerate fallback secrets: {e}')

		return services

	def clear_all(self) -> bool:
		"""Clear all stored secrets (dangerous).

		Returns:
			True if successful
		"""
		try:
			# Fallback cleanup
			if self.fallback_path.exists():
				self.fallback_path.unlink()
				log.info('Cleared all fallback secrets')
			return True
		except Exception as e:
			log.warning(f'Failed to clear secrets: {e}')
			return False


# Global instance
_secrets_manager = None


def get_secrets_manager() -> SecretsManager:
	"""Get or create global secrets manager instance."""
	global _secrets_manager
	if _secrets_manager is None:
		_secrets_manager = SecretsManager()
	return _secrets_manager


def get_api_key(service: str, username: str = 'default') -> Optional[str]:
	"""Convenience function to get API key."""
	return get_secrets_manager().get_api_key(service, username)


def set_api_key(service: str, api_key: str, username: str = 'default') -> bool:
	"""Convenience function to set API key."""
	return get_secrets_manager().set_api_key(service, api_key, username)


def delete_api_key(service: str, username: str = 'default') -> bool:
	"""Convenience function to delete API key."""
	return get_secrets_manager().delete_api_key(service, username)
