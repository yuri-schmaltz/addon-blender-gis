# -*- coding:utf-8 -*-
"""
Import Operators Base Utilities
Shared helpers to reduce duplication across import operators.

Designed to be non-invasive: provides simple functions and a mixin
that operators can use without changing their inheritance hierarchies.
"""
import logging
from typing import Tuple, Optional

log = logging.getLogger(__name__)

try:
	import bpy
	from bpy.types import Operator
except Exception:
	# Allow static analysis / tests without Blender
	bpy = None
	Operator = object

from ...geoscene import GeoScene


class ImportOperatorMixin:
	"""Mixin with common error reporting and geoscene helpers"""

	def report_error(self, message: str, exc: Optional[Exception] = None) -> None:
		if exc:
			log.error(message, exc_info=True)
		else:
			log.error(message)
		if hasattr(self, 'report'):
			self.report({'ERROR'}, message)

	def get_geoscene(self, context) -> GeoScene:
		return GeoScene(context.scene)

	def ensure_geoscene_ready(self, context, file_crs: str) -> Tuple[bool, Optional[GeoScene]]:
		"""
		Validate scene georef and set CRS if missing using file_crs.
		Returns (success, geoscene_or_none).
		"""
		geoscn = GeoScene(context.scene)
		if geoscn.isBroken:
			self.report_error('Scene georef is broken, please fix it beforehand')
			return False, None
		# Set CRS from file if scene has no CRS
		if not geoscn.hasCRS:
			try:
				geoscn.crs = file_crs
			except Exception as e:
				self.report_error('Cannot set scene CRS, check logs for more infos', e)
				return False, None
		return True, geoscn


def safe_open(operator, filepath: str, mode: str = 'r'):
	"""Open a file safely, reporting errors via operator.report"""
	try:
		return open(filepath, mode)
	except FileNotFoundError as e:
		operator.report_error(f'File not found: {filepath}', e)
		return None
	except PermissionError as e:
		operator.report_error(f'Permission denied: {filepath}', e)
		return None
	except Exception as e:
		operator.report_error(f'Cannot open file: {filepath}', e)
		return None
