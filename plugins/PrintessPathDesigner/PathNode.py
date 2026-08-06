# Copyright (c) 2026 Printess Technologies
# Released under the terms of the LGPLv3 or higher.
#
# Scene node that renders drawn paths as flat ribbons on the build plate.
# It renders itself with a flat-color shader (see render()), so SolidView's
# normal per-object handling is skipped. It has no SliceableObjectDecorator,
# which keeps it invisible to StartSliceJob and the rest of the slicing
# pipeline.

import math
from typing import List, Optional, Tuple

import numpy

from UM.Mesh.MeshBuilder import MeshBuilder
from UM.Resources import Resources
from UM.Scene.SceneNode import SceneNode
from UM.View.GL.OpenGL import OpenGL

Point = Tuple[float, float]


class PathNode(SceneNode):
    _shader = None

    def __init__(self, parent: Optional[SceneNode] = None) -> None:
        super().__init__(parent)
        self.setSelectable(False)
        self.setCalculateBoundingBox(False)
        self._color = [0.3, 0.55, 0.85, 1.0]
        self._transparent = False

    def setColor(self, rgba: List[float]) -> None:
        self._color = list(rgba)

    def setTransparent(self, transparent: bool) -> None:
        self._transparent = transparent

    def render(self, renderer) -> bool:
        if not self.getMeshData() or not self.isVisible():
            return True
        if PathNode._shader is None:
            PathNode._shader = OpenGL.getInstance().createShaderProgram(
                Resources.getPath(Resources.Shaders, "color.shader"))
            # color.shader has no binding for u_color by default; add one so the
            # per-item uniforms dict below can set it.
            PathNode._shader.addBinding("u_color", "path_color")
        renderer.queueNode(self, shader = PathNode._shader,
                           transparent = self._transparent,
                           backface_cull = False,
                           uniforms = {"path_color": self._color})
        return True


def build_disc_mesh(centers: List[Point], radius: float, y: float, segments: int = 16):
    """MeshData of flat filled circles — used for round node handles."""
    if not centers or radius <= 0:
        return None
    triangles = []
    for cx, cz in centers:
        ring = []
        for i in range(segments):
            a = 2.0 * math.pi * i / segments
            ring.append((cx + radius * math.cos(a), cz + radius * math.sin(a)))
        for i in range(segments):
            triangles.append(((cx, cz), ring[i], ring[(i + 1) % segments]))
    return build_triangle_mesh(triangles, y)


def build_ring_mesh(center: Point, radius: float, thickness: float, y: float, segments: int = 24):
    """MeshData of a flat annulus — the hover highlight around a node."""
    inner = max(radius - thickness, 0.01)
    triangles = []
    for i in range(segments):
        a0 = 2.0 * math.pi * i / segments
        a1 = 2.0 * math.pi * (i + 1) / segments
        p0 = (center[0] + radius * math.cos(a0), center[1] + radius * math.sin(a0))
        p1 = (center[0] + radius * math.cos(a1), center[1] + radius * math.sin(a1))
        q0 = (center[0] + inner * math.cos(a0), center[1] + inner * math.sin(a0))
        q1 = (center[0] + inner * math.cos(a1), center[1] + inner * math.sin(a1))
        triangles.append((q0, p0, p1))
        triangles.append((q0, p1, q1))
    return build_triangle_mesh(triangles, y)


def build_triangle_mesh(triangles, y: float):
    """MeshData from a list of ((x,z),(x,z),(x,z)) triangles lying on the plate."""
    if not triangles:
        return None
    vertices = []
    indices = []
    for a, b, c in triangles:
        base = len(vertices)
        vertices.extend([[a[0], y, a[1]], [b[0], y, b[1]], [c[0], y, c[1]]])
        indices.append([base, base + 1, base + 2])
    builder = MeshBuilder()
    builder.setVertices(numpy.asarray(vertices, dtype = numpy.float32))
    builder.setIndices(numpy.asarray(indices, dtype = numpy.int32))
    return builder.build()


def build_ribbon_mesh(polylines: List[List[Point]], width: float, y: float,
                      marker: Optional[Point] = None, marker_size: float = 0.0):
    """Build a MeshData of flat ribbons lying on the plate.

    :param polylines: list of polylines, each a list of (x, z) points.
    :param width: ribbon width in mm.
    :param y: height above the plate (small, to avoid z-fighting).
    :param marker: optional (x, z) to draw a square marker at (used to show the
                   snap-to-close target at a path's first point).
    :param marker_size: edge length of the marker square.
    :return: MeshData, or None when there is nothing to build.
    """
    vertices = []
    indices = []

    half = max(width, 0.1) / 2.0

    def add_quad(p0x, p0z, p1x, p1z, p2x, p2z, p3x, p3z):
        base = len(vertices)
        vertices.extend([[p0x, y, p0z], [p1x, y, p1z], [p2x, y, p2z], [p3x, y, p3z]])
        indices.append([base, base + 1, base + 2])
        indices.append([base, base + 2, base + 3])

    for polyline in polylines:
        for i in range(len(polyline) - 1):
            ax, az = polyline[i]
            bx, bz = polyline[i + 1]
            dx, dz = bx - ax, bz - az
            length = math.hypot(dx, dz)
            if length < 1e-9:
                continue
            ux, uz = dx / length, dz / length
            # Extend both ends by half the width so consecutive segments
            # overlap and sharp corners do not show gaps.
            ax2, az2 = ax - ux * half, az - uz * half
            bx2, bz2 = bx + ux * half, bz + uz * half
            nx, nz = -uz * half, ux * half
            add_quad(ax2 + nx, az2 + nz,
                     bx2 + nx, bz2 + nz,
                     bx2 - nx, bz2 - nz,
                     ax2 - nx, az2 - nz)

    if marker is not None and marker_size > 0:
        mx, mz = marker
        s = marker_size / 2.0
        add_quad(mx - s, mz - s, mx + s, mz - s, mx + s, mz + s, mx - s, mz + s)

    if not vertices:
        return None

    builder = MeshBuilder()
    builder.setVertices(numpy.asarray(vertices, dtype = numpy.float32))
    builder.setIndices(numpy.asarray(indices, dtype = numpy.int32))
    return builder.build()
