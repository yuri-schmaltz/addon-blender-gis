import os
import time

import logging
log = logging.getLogger(__name__)

from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import bpy
import bmesh
from bpy.types import Operator, Panel, AddonPreferences
from bpy.props import StringProperty, IntProperty, FloatProperty, BoolProperty, EnumProperty, FloatVectorProperty

from ..geoscene import GeoScene
from .utils import adjust3Dview, getBBOX, isTopView
from ..core.proj import SRS, reprojBbox
from ..core.utils.resilience import retry_with_backoff, with_circuit_breaker

from ..core import settings
USER_AGENT = settings.user_agent

PKG, SUBPKG = __package__.split('.', maxsplit=1)

TIMEOUT = 120

class IMPORTGIS_OT_dem_query(Operator):
	"""Import elevation data from a web service"""

	bl_idname = "importgis.dem_query"
	bl_description = 'Query for elevation data from a web service'
	bl_label = "Get elevation (SRTM)"
	bl_options = {"UNDO"}

	def invoke(self, context, event):

		#check georef
		geoscn = GeoScene(context.scene)
		if not geoscn.isGeoref:
				self.report({'ERROR'}, "Scene is not georeferenced. Please set a valid CRS and origin in GIS properties.")
				log.warning("DEM query aborted: Scene not georeferenced")
				return {'CANCELLED'}
		if geoscn.isBroken:
				self.report({'ERROR'}, "Scene georeferencing is broken (partial data). Please fix CRS or origin in GIS properties.")
				log.warning("DEM query aborted: Broken georeferencing")
				return {'CANCELLED'}

		#return self.execute(context)
		return context.window_manager.invoke_props_dialog(self)

	def draw(self,context):
		prefs = context.preferences.addons[PKG].preferences
		layout = self.layout
		row = layout.row(align=True)
		row.prop(prefs, "demServer", text='Server')
		if 'opentopography' in prefs.demServer:
			row = layout.row(align=True)
			row.prop(prefs, "opentopography_api_key", text='Api Key')

	@classmethod
	def poll(cls, context):
		return context.mode == 'OBJECT'

	def execute(self, context):

		prefs = bpy.context.preferences.addons[PKG].preferences
		scn = context.scene
		geoscn = GeoScene(scn)
		crs = SRS(geoscn.crs)

		#Validate selection
		objs = bpy.context.selected_objects
		aObj = context.active_object
		if len(objs) == 1 and aObj.type == 'MESH':
			onMesh = True
			bbox = getBBOX.fromObj(aObj).toGeo(geoscn)
		elif isTopView(context):
			onMesh = False
			bbox = getBBOX.fromTopView(context).toGeo(geoscn)
		else:
			self.report({'ERROR'}, "Please define the query extent in orthographic top view or by selecting a reference object")
			return {'CANCELLED'}

		if bbox.dimensions.x > 1000000 or bbox.dimensions.y > 1000000:
			self.report({'ERROR'}, "Query extent too large (>1000 km). Please select a smaller area.")
			return {'CANCELLED'}

		bbox = reprojBbox(geoscn.crs, 4326, bbox)

		if 'SRTM' in prefs.demServer:
			if bbox.ymin > 60:
				self.report({'ERROR'}, "SRTM unavailable beyond 60°N. Try OpenTopography SRTM 30m or Marine-geo.org instead.")
				return {'CANCELLED'}
			if bbox.ymax < -56:
				self.report({'ERROR'}, "SRTM unavailable below 56°S. Try OpenTopography SRTM 30m or Marine-geo.org instead.")
				return {'CANCELLED'}

		if 'opentopography' in prefs.demServer:
			if not prefs.opentopography_api_key:
				self.report({'ERROR'}, "OpenTopography API key required. Register at opentopography.org, request key, and add to BlenderGIS preferences.")
				return {'CANCELLED'}

		#Set cursor representation to 'loading' icon
		w = context.window
		w.cursor_set('WAIT')

		#url template
		#http://opentopo.sdsc.edu/otr/getdem?demtype=SRTMGL3&west=-120.168457&south=36.738884&east=-118.465576&north=38.091337&outputFormat=GTiff
		e = 0.002 #opentopo service does not always respect the entire bbox, so request for a little more
		xmin, xmax = bbox.xmin - e, bbox.xmax + e
		ymin, ymax = bbox.ymin - e, bbox.ymax + e

		url = prefs.demServer.format(W=xmin, E=xmax, S=ymin, N=ymax, API_KEY=prefs.opentopography_api_key)
		log.debug(url)

		# Download the file from url and save it locally
		# opentopo return a geotiff object in wgs84
		if bpy.data.is_saved:
			filePath = os.path.join(os.path.dirname(bpy.data.filepath), 'srtm.tif')
		else:
			filePath = os.path.join(bpy.app.tempdir, 'srtm.tif')

		#we can directly init NpImg from blob but if gdal is not used as image engine then georef will not be extracted
		#Alternatively, we can save on disk, open with GeoRaster class (will use tyf if gdal not available)
		rq = Request(url, headers={'User-Agent': USER_AGENT})
		try:
			with urlopen(rq, timeout=TIMEOUT) as response, open(filePath, 'wb') as outFile:
				data = response.read() # a `bytes` object
				outFile.write(data) #
		except (URLError, HTTPError) as err:
			log.error('HTTP request failed. URL: %s, Code: %s, Error: %s', url, getattr(err, 'code', 'unknown'), err.reason, exc_info=True)
			error_code = getattr(err, 'code', None)
			if error_code == 401:
				self.report({'ERROR'}, "Authentication failed: Invalid or expired API key. Check OpenTopography account.")
			elif error_code == 429:
				self.report({'ERROR'}, "Rate limit exceeded: Too many requests. Please retry in a few minutes.")
			else:
				self.report({'ERROR'}, f"Cannot reach DEM service (HTTP {error_code}). Check internet connection or try another server.")
			return {'CANCELLED'}
		except TimeoutError as err:
			log.error('HTTP request timeout after %ds. URL: %s', TIMEOUT, url, exc_info=True)
			self.report({'ERROR'}, f"DEM service timeout ({TIMEOUT}s). Server may be down. Try another provider or retry later.")
			return {'CANCELLED'}
		except Exception as err:
			log.error('Unexpected error downloading DEM', exc_info=True)
			self.report({'ERROR'}, f"Unexpected error: {str(err)}. Check logs for details.")

		if not onMesh:
			bpy.ops.importgis.georaster(
			'EXEC_DEFAULT',
			filepath = filePath,
			reprojection = True,
			rastCRS = 'EPSG:4326',
			importMode = 'DEM',
			subdivision = 'subsurf',
			demInterpolation = True)
		else:
			bpy.ops.importgis.georaster(
			'EXEC_DEFAULT',
			filepath = filePath,
			reprojection = True,
			rastCRS = 'EPSG:4326',
			importMode = 'DEM',
			subdivision = 'subsurf',
			demInterpolation = True,
			demOnMesh = True,
			objectsLst = [str(i) for i, obj in enumerate(scn.collection.all_objects) if obj.name == bpy.context.active_object.name][0],
			clip = False,
			fillNodata = False)

		bbox = getBBOX.fromScn(scn)
		adjust3Dview(context, bbox, zoomToSelect=False)

		return {'FINISHED'}


def register():
	try:
		bpy.utils.register_class(IMPORTGIS_OT_dem_query)
	except ValueError as e:
		log.warning('{} is already registered, now unregister and retry... '.format(IMPORTGIS_OT_srtm_query))
		unregister()
		bpy.utils.register_class(IMPORTGIS_OT_dem_query)

def unregister():
	bpy.utils.unregister_class(IMPORTGIS_OT_dem_query)
