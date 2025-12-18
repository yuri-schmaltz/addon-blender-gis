# -*- coding:utf-8 -*-
"""
BaseImportOperator: classe base para operadores de importação com utilitários comuns.

Padroniza:
- Seleção de arquivo + diálogo
- Gerenciamento de CRS (predefinidos e customizados)
- Feedback de progresso ao usuário
- Tratamento de erros com relatórios descritivos
- Georeferenciamento de cena
"""

import os
import logging
import bpy
from bpy.props import StringProperty, BoolProperty, EnumProperty
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper

log = logging.getLogger(__name__)

from ..geoscene import GeoScene, georefManagerLayout
from ..prefs import PredefCRS
from ..core.proj import SRS


class BaseImportOperator(Operator, ImportHelper):
	"""Base class for import operators with common functionality."""

	# ImportHelper provides filename, invoke(), file browser UI
	bl_options = {"UNDO"}

	# CRS selection (common to all import operators)
	def list_predef_crs(self, context):
		"""List predefined CRS from addon preferences."""
		return PredefCRS.getEnumItems()

	import_crs: EnumProperty(
		name="CRS",
		description="Coordinate Reference System for imported data",
		items="list_predef_crs",
	)

	def draw(self, context):
		"""Draw operator panel with standard CRS selector."""
		layout = self.layout

		# CRS selection row
		row = layout.row(align=True)
		split = row.split(factor=0.35, align=True)
		split.label(text='CRS:')
		split.prop(self, "import_crs", text='')
		row.operator("bgis.add_predef_crs", text='', icon='ADD')

		# Georeferencing info if scene is already georeferenced
		scn = bpy.context.scene
		geoscn = GeoScene(scn)
		if geoscn.isPartiallyGeoref:
			georefManagerLayout(self, context)

		# Subclasses can override and call super().draw() then add more UI
		self.draw_operator_props(layout, context)

	def draw_operator_props(self, layout, context):
		"""Override this in subclasses to add operator-specific UI."""
		pass

	def get_crs(self):
		"""Get CRS string from enum selection."""
		return self.import_crs

	def validate_crs(self):
		"""Validate selected CRS."""
		try:
			crs_str = self.get_crs()
			srs = SRS(crs_str)
			if not srs.is_valid:
				raise ValueError(f"Invalid CRS: {crs_str}")
			return True
		except Exception as e:
			log.error(f"CRS validation failed: {e}")
			return False

	def validate_file(self, filepath):
		"""Validate that file exists and is readable."""
		if not filepath:
			raise ValueError("No file selected")
		if not os.path.exists(filepath):
			raise ValueError(f"File not found: {filepath}")
		if not os.path.isfile(filepath):
			raise ValueError(f"Path is not a file: {filepath}")
		return True

	def report_error(self, operator_report, message):
		"""Report error to user and log it."""
		log.error(message)
		operator_report({'ERROR'}, message)

	def report_warning(self, operator_report, message):
		"""Report warning to user and log it."""
		log.warning(message)
		operator_report({'WARNING'}, message)

	def report_info(self, operator_report, message):
		"""Report info to user and log it."""
		log.info(message)
		operator_report({'INFO'}, message)

	def get_geoscene(self, context):
		"""Get GeoScene for active scene."""
		return GeoScene(context.scene)

	def sync_scene_crs(self, context):
		"""Sync imported CRS with scene georeferencing if possible."""
		try:
			geoscn = self.get_geoscene(context)
			crs_str = self.get_crs()

			# Only set CRS if scene doesn't already have one
			if not geoscn.hasCRS:
				geoscn.crs = crs_str
				log.info(f"Scene CRS set to: {crs_str}")
				return True
			elif geoscn.crs != crs_str:
				log.warning(f"Scene CRS mismatch: scene={geoscn.crs}, import={crs_str}")
				return False

			return True
		except Exception as e:
			log.warning(f"Could not sync scene CRS: {e}")
			return False
