# -*- coding:utf-8 -*-
"""
Operators for managing secure API keys in BlenderGIS preferences.
Integrates with keyring manager for secure credential storage.
"""

import bpy
from bpy.types import Operator
from bpy.props import StringProperty, EnumProperty

from .core.utils.secrets import get_secrets_manager

class BGIS_OT_set_api_key(Operator):
	"""Store API key securely using system keyring"""
	
	bl_idname = "bgis.set_api_key"
	bl_label = "Store API Key"
	bl_description = "Store API key securely in system keyring"
	bl_options = {'INTERNAL'}

	service: StringProperty(
		name="Service",
		description="Service name (e.g., opentopodata, maptiler)"
	)

	api_key: StringProperty(
		name="API Key",
		description="API key to store",
		subtype='PASSWORD'
	)

	def execute(self, context):
		if not self.service or not self.api_key:
			self.report({'ERROR'}, "Service and API key cannot be empty")
			return {'CANCELLED'}

		secrets = get_secrets_manager()
		if secrets.set_api_key(self.service, self.api_key):
			self.report({'INFO'}, f"API key stored successfully for {self.service}")
			return {'FINISHED'}
		else:
			self.report({'ERROR'}, f"Failed to store API key for {self.service}")
			return {'CANCELLED'}

	def invoke(self, context, event):
		return context.window_manager.invoke_props_dialog(self, width=400)


class BGIS_OT_get_api_key(Operator):
	"""Retrieve API key from system keyring"""
	
	bl_idname = "bgis.get_api_key"
	bl_label = "Retrieve API Key"
	bl_description = "Retrieve API key from secure storage"
	bl_options = {'INTERNAL'}

	service: StringProperty(
		name="Service",
		description="Service name (e.g., opentopodata, maptiler)"
	)

	def execute(self, context):
		if not self.service:
			self.report({'ERROR'}, "Service name cannot be empty")
			return {'CANCELLED'}

		secrets = get_secrets_manager()
		api_key = secrets.get_api_key(self.service)
		
		if api_key:
			self.report({'INFO'}, f"API key found for {self.service} (length: {len(api_key)})")
			# Note: We don't print the actual key for security reasons
			return {'FINISHED'}
		else:
			self.report({'WARNING'}, f"No API key found for {self.service}")
			return {'CANCELLED'}


class BGIS_OT_delete_api_key(Operator):
	"""Delete API key from system keyring"""
	
	bl_idname = "bgis.delete_api_key"
	bl_label = "Delete API Key"
	bl_description = "Remove API key from secure storage"
	bl_options = {'INTERNAL'}

	service: StringProperty(
		name="Service",
		description="Service name (e.g., opentopodata, maptiler)"
	)

	def execute(self, context):
		if not self.service:
			self.report({'ERROR'}, "Service name cannot be empty")
			return {'CANCELLED'}

		secrets = get_secrets_manager()
		if secrets.delete_api_key(self.service):
			self.report({'INFO'}, f"API key deleted for {self.service}")
			return {'FINISHED'}
		else:
			self.report({'WARNING'}, f"Could not delete API key for {self.service}")
			return {'CANCELLED'}


class BGIS_OT_list_api_keys(Operator):
	"""List all stored API keys"""
	
	bl_idname = "bgis.list_api_keys"
	bl_label = "List API Keys"
	bl_description = "Show all stored API keys (without revealing values)"
	bl_options = {'INTERNAL'}

	def execute(self, context):
		secrets = get_secrets_manager()
		services = secrets.list_services()
		
		if services:
			msg = "Stored API keys:\n" + "\n".join(
				f"  {service}: {', '.join(users)}" 
				for service, users in services.items()
			)
			self.report({'INFO'}, msg)
		else:
			self.report({'INFO'}, "No API keys stored")
		
		return {'FINISHED'}


# Register all operators
classes = [
	BGIS_OT_set_api_key,
	BGIS_OT_get_api_key,
	BGIS_OT_delete_api_key,
	BGIS_OT_list_api_keys,
]


def register():
	for cls in classes:
		bpy.utils.register_class(cls)


def unregister():
	for cls in reversed(classes):
		bpy.utils.unregister_class(cls)
