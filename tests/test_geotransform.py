# -*- coding:utf-8 -*-
import math
from core.proj.geotransform import view3d_to_proj, proj_to_view3d, move_origin_prj


def test_view3d_to_proj_basic():
	crsx, crsy = 1000.0, 2000.0
	scale = 2.0
	dx, dy = 10.0, -5.0
	x, y = view3d_to_proj(crsx, crsy, scale, dx, dy)
	assert x == 1000.0 + 10.0 * 2.0
	assert y == 2000.0 + (-5.0) * 2.0


def test_proj_to_view3d_basic():
	crsx, crsy = 1000.0, 2000.0
	scale = 2.0
	x, y = 1040.0, 1990.0
	dx, dy = proj_to_view3d(crsx, crsy, scale, x, y)
	assert dx == x * scale - crsx
	assert dy == y * scale - crsy


def test_move_origin_prj_use_scale():
	crsx, crsy = 0.0, 0.0
	scale = 3.0
	dx, dy = 2.0, 4.0
	new_x, new_y = move_origin_prj(crsx, crsy, dx, dy, scale, use_scale=True)
	assert new_x == dx * scale
	assert new_y == dy * scale


def test_move_origin_prj_no_scale():
	crsx, crsy = 10.0, -10.0
	scale = 3.0
	dx, dy = 2.0, 4.0
	new_x, new_y = move_origin_prj(crsx, crsy, dx, dy, scale, use_scale=False)
	assert new_x == crsx + dx
	assert new_y == crsy + dy
