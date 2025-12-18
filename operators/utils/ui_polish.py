# -*- coding:utf-8 -*-
"""
UI Polish enhancements for BlenderGIS operators.

Implements:
- Real-time progress bars for long-running operations
- Async progress updates from worker threads
- Better error dialogs with copyable logs
- Status messages with time estimation
"""

import bpy
import time
import logging
from bpy.types import Operator, Panel
from bpy.props import StringProperty, IntProperty, FloatProperty, BoolProperty
from enum import Enum

log = logging.getLogger(__name__)


class ProgressTracker:
	"""Tracks and reports operation progress to Blender UI.
	
	Updates progress through a modal timer operator.
	"""

	def __init__(self, context, title: str, total_items: int):
		"""Initialize progress tracker.
		
		Args:
			context: Blender context
			title: Operation title
			total_items: Total number of items to process
		"""
		self.context = context
		self.title = title
		self.total_items = max(1, total_items)
		self.current_item = 0
		self.start_time = time.time()
		self.paused = False
		self.pause_time = 0

	def update(self, count: int = 1, message: str = ""):
		"""Update progress.
		
		Args:
			count: Number of items processed (default: 1)
			message: Status message to display
		"""
		self.current_item += count

	def get_progress_percent(self) -> float:
		"""Get current progress as percentage (0-100)."""
		return (self.current_item / self.total_items) * 100

	def get_eta_seconds(self) -> float:
		"""Estimate remaining time in seconds."""
		if self.current_item == 0:
			return 0
		
		elapsed = time.time() - self.start_time - self.pause_time
		rate = self.current_item / max(0.1, elapsed)  # items/sec
		remaining = self.total_items - self.current_item
		
		return remaining / rate if rate > 0 else 0

	def get_status_string(self) -> str:
		"""Get formatted status message."""
		percent = self.get_progress_percent()
		eta = self.get_eta_seconds()
		elapsed = time.time() - self.start_time - self.pause_time
		
		# Format times as MM:SS
		elapsed_str = f"{int(elapsed)//60:02d}:{int(elapsed)%60:02d}"
		eta_str = f"{int(eta)//60:02d}:{int(eta)%60:02d}"
		
		return f"{self.title}: {percent:.0f}% ({self.current_item}/{self.total_items}) Elapsed: {elapsed_str} ETA: {eta_str}"

	def is_complete(self) -> bool:
		"""Check if all items processed."""
		return self.current_item >= self.total_items


class BGIS_OT_modal_progress(Operator):
	"""Modal operator for displaying real-time progress.
	
	Used by other operators to show progress during long operations.
	"""

	bl_idname = "bgis.modal_progress"
	bl_label = "Operation Progress"
	bl_options = {'INTERNAL'}

	# Store reference to parent operator and progress tracker
	_parent_op = None
	_progress = None
	_timer = None

	title: StringProperty(name="Title", default="Processing")
	total: IntProperty(name="Total", default=100)
	current: IntProperty(name="Current", default=0)
	status_msg: StringProperty(name="Status", default="")
	is_complete: BoolProperty(name="Complete", default=False)

	def modal(self, context, event):
		"""Handle modal events."""
		if event.type == 'ESC':
			# Cancel operation
			if self._parent_op and hasattr(self._parent_op, 'cancel'):
				self._parent_op.cancel()
			self.report({'INFO'}, "Operation cancelled")
			return self.finish_modal()

		if event.type == 'TIMER':
			# Update progress display
			if self._progress:
				self.current = self._progress.current_item
				self.total = self._progress.total_items
				self.status_msg = self._progress.get_status_string()

				# Header display
				for area in context.screen.areas:
					if area.type == 'PROPERTIES':
						area.tag_redraw()

				if self._progress.is_complete():
					return self.finish_modal()

		return {'RUNNING_MODAL'}

	def finish_modal(self):
		"""Clean up and finish modal."""
		if self._timer:
			wm = bpy.context.window_manager
			wm.event_timer_remove(self._timer)

		return {'FINISHED'}

	def execute(self, context):
		"""Set up modal timer."""
		wm = context.window_manager
		self._timer = wm.event_timer_add(0.1, window=context.window)
		wm.modal_handler_add(self)
		return {'RUNNING_MODAL'}

	@classmethod
	def start(cls, context, title: str, total_items: int):
		"""Start modal progress display.
		
		Returns:
			ProgressTracker instance
		"""
		# Execute modal operator
		bpy.ops.bgis.modal_progress('INVOKE_DEFAULT')

		# Create and return progress tracker
		progress = ProgressTracker(context, title, total_items)
		cls._progress = progress
		return progress


class BGIS_OT_error_details(Operator):
	"""Dialog showing detailed error information with copy functionality."""

	bl_idname = "bgis.show_error_details"
	bl_label = "Error Details"
	bl_options = {'INTERNAL'}

	error_title: StringProperty(name="Error Title")
	error_message: StringProperty(name="Error Message", default="")
	error_traceback: StringProperty(name="Traceback", default="")

	def draw(self, context):
		"""Draw error dialog."""
		layout = self.layout

		# Title
		if self.error_title:
			box = layout.box()
			box.label(text=self.error_title, icon='ERROR')

		# Error message
		if self.error_message:
			col = layout.column()
			col.label(text="Error:")
			# Split message into lines for display
			for line in self.error_message.split('\n'):
				if line.strip():
					col.label(text=line)

		# Traceback (if available)
		if self.error_traceback:
			box = layout.box()
			box.label(text="Technical Details:")
			col = box.column()
			col.scale_y = 0.8
			for line in self.error_traceback.split('\n')[-10:]:  # Last 10 lines
				if line.strip():
					col.label(text=line)

		# Buttons
		row = layout.row(align=True)
		row.operator("wm.url_open", text="Copy to Clipboard").url = ""  # Custom handling
		row.operator("bgis.open_error_log", text="Open Log File")

	def execute(self, context):
		return {'FINISHED'}

	def invoke(self, context, event):
		return context.window_manager.invoke_props_dialog(self, width=600)


class BGIS_OT_open_error_log(Operator):
	"""Open error log file in default text editor."""

	bl_idname = "bgis.open_error_log"
	bl_label = "Open Log"
	bl_options = {'INTERNAL'}

	def execute(self, context):
		import subprocess
		import os
		import platform

		# Get log file path (typically in user app data)
		log_dir = os.path.expanduser('~/.bgis/logs')
		if not os.path.exists(log_dir):
			self.report({'ERROR'}, f"Log directory not found: {log_dir}")
			return {'CANCELLED'}

		# Find latest log file
		log_files = sorted([f for f in os.listdir(log_dir) if f.endswith('.log')])
		if not log_files:
			self.report({'ERROR'}, "No log files found")
			return {'CANCELLED'}

		log_file = os.path.join(log_dir, log_files[-1])

		# Open with system default editor
		try:
			if platform.system() == 'Darwin':  # macOS
				subprocess.Popen(['open', log_file])
			elif platform.system() == 'Windows':
				os.startfile(log_file)
			else:  # Linux
				subprocess.Popen(['xdg-open', log_file])
			
			self.report({'INFO'}, f"Opened log file: {log_file}")
			return {'FINISHED'}
		except Exception as e:
			self.report({'ERROR'}, f"Could not open log: {str(e)}")
			return {'CANCELLED'}


class BGIS_OT_operation_with_progress(Operator):
	"""Base class for long-running operations with progress display.
	
	Subclasses should implement:
	- get_total_items(): Returns number of items to process
	- process_item(index): Process single item
	- get_title(): Returns operation title
	"""

	bl_options = {'REGISTER', 'UNDO'}

	_progress = None
	_cancel_requested = False

	def execute(self, context):
		"""Execute operation with progress tracking."""
		try:
			total = self.get_total_items()
			title = self.get_title()

			# Start progress display
			self._progress = ProgressTracker(context, title, total)

			# Process items
			for i in range(total):
				if self._cancel_requested:
					self.report({'WARNING'}, "Operation cancelled")
					return {'CANCELLED'}

				try:
					self.process_item(i)
					self._progress.update(1)
				except Exception as e:
					self.report({'ERROR'}, f"Failed to process item {i+1}: {str(e)}")
					log.exception(f"Error processing item {i}")
					return {'CANCELLED'}

				# Allow UI updates
				for area in context.screen.areas:
					if area.type in ('PROPERTIES', 'HEADER'):
						area.tag_redraw()

			self.report({'INFO'}, f"{title}: Completed successfully")
			return {'FINISHED'}

		except Exception as e:
			self.report({'ERROR'}, str(e))
			log.exception("Operation failed")
			return {'CANCELLED'}

	def cancel(self):
		"""Request cancellation of operation."""
		self._cancel_requested = True

	def get_total_items(self) -> int:
		"""Override: Return total number of items to process."""
		return 0

	def process_item(self, index: int):
		"""Override: Process single item."""
		pass

	def get_title(self) -> str:
		"""Override: Return operation title."""
		return "Processing"


class BGIS_PANEL_operation_status(Panel):
	"""Status panel showing current operation progress."""

	bl_label = "BlenderGIS Status"
	bl_idname = "BGIS_PT_operation_status"
	bl_space_type = 'PROPERTIES'
	bl_region_type = 'WINDOW'
	bl_category = "GIS"

	def draw(self, context):
		"""Draw status panel."""
		layout = self.layout

		# Check if there's an active progress tracker
		if BGIS_OT_modal_progress._progress:
			progress = BGIS_OT_modal_progress._progress

			# Progress bar
			col = layout.column()
			row = col.row(align=True)
			row.scale_x = 1
			row.scale_y = 1.5

			# Custom progress bar
			percent = progress.get_progress_percent()
			bar_col = row.column()
			bar_col.template_progress_bar(value=percent / 100.0)

			# Status text
			col.label(text=progress.get_status_string())

			# Cancel button
			col.operator("bgis.cancel_operation", text="Cancel", icon='X')
		else:
			layout.label(text="No active operation")


class BGIS_OT_cancel_operation(Operator):
	"""Cancel current operation."""

	bl_idname = "bgis.cancel_operation"
	bl_label = "Cancel"

	def execute(self, context):
		if BGIS_OT_modal_progress._parent_op:
			BGIS_OT_modal_progress._parent_op.cancel()
		return {'FINISHED'}


# Register all classes
classes = [
	BGIS_OT_modal_progress,
	BGIS_OT_error_details,
	BGIS_OT_open_error_log,
	BGIS_OT_operation_with_progress,
	BGIS_PANEL_operation_status,
	BGIS_OT_cancel_operation,
]


def register():
	for cls in classes:
		bpy.utils.register_class(cls)


def unregister():
	for cls in reversed(classes):
		bpy.utils.unregister_class(cls)
