# -*- coding:utf-8 -*-
"""
GeoTransform: funções puras de transformação entre coordenadas da View3D e o espaço do CRS.

As funções aqui não dependem de Blender (bpy) nem de estado global, tornando
mais simples a testabilidade e reutilização.
"""
from typing import Tuple


def view3d_to_proj(crsx: float, crsy: float, scale: float, dx: float, dy: float) -> Tuple[float, float]:
	"""Converte coordenadas da View3D (dx, dy) para coordenadas no CRS.
	Parâmetros:
	- crsx, crsy: origem da cena no espaço CRS
	- scale: escala (metros por unidade de View3D)
	- dx, dy: deslocamento relativo na View3D
	Retorna:
	- x, y: coordenadas no espaço CRS
	"""
	x = crsx + (dx * scale)
	y = crsy + (dy * scale)
	return x, y


def proj_to_view3d(crsx: float, crsy: float, scale: float, x: float, y: float) -> Tuple[float, float]:
	"""Converte coordenadas no CRS (x, y) para deslocamento relativo na View3D.
	Parâmetros:
	- crsx, crsy: origem da cena no espaço CRS
	- scale: escala (metros por unidade de View3D)
	- x, y: coordenadas no espaço CRS
	Retorna:
	- dx, dy: deslocamento relativo na View3D
	"""
	dx = (x * scale) - crsx
	dy = (y * scale) - crsy
	return dx, dy


def move_origin_prj(crsx: float, crsy: float, dx: float, dy: float, scale: float, use_scale: bool = True) -> Tuple[float, float]:
	"""Move a origem no espaço do CRS usando deltas relativos.
	Se `use_scale` for True, aplica `dx * scale`, `dy * scale`.
	Retorna a nova origem (x, y) no CRS.
	"""
	if use_scale:
		new_x = crsx + dx * scale
		new_y = crsy + dy * scale
	else:
		new_x = crsx + dx
		new_y = crsy + dy
	return new_x, new_y
