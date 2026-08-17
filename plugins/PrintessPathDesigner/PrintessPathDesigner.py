# Copyright (c) 2026 Printess Technologies
# Released under the terms of the LGPLv3 or higher.
#
# Path Designer: draw lines, arcs, circles, and curves directly on the build
# plate and save them as g-code print paths, without needing an STL.
#
# Interaction (while the tool is active the selection tool is suspended, so
# left clicks always go to this tool; the camera still rotates with the right
# mouse button and zooms with the scroll wheel):
#   - Line/Curve: click to place points; click the first point again to close
#     the shape; Enter (or the Finish button) ends an open path; Esc cancels.
#   - Arc: click start, then end, then a third click to set the bulge.
#   - Circle: click the centre, then a point on the radius.

import copy
import json
import math
import os
import re
import time
from typing import List, Optional, Tuple

import numpy

from PyQt6.QtCore import Qt

from UM.Application import Application
from UM.Event import Event, MouseEvent, KeyEvent
from UM.Logger import Logger
from UM.Math.Matrix import Matrix
from UM.Math.Plane import Plane
from UM.Math.Vector import Vector
from UM.Message import Message
from UM.PluginRegistry import PluginRegistry
from UM.Scene.SceneNode import SceneNode
from UM.Scene.SceneNodeDecorator import SceneNodeDecorator
from UM.Scene.Selection import Selection
from UM.Tool import Tool

from . import GcodeGenerator
from . import GcodeMerge
from . import PathShapes
from . import WellPlates
from .PathNode import (PathNode, build_ribbon_mesh, build_triangle_mesh,
                       build_disc_mesh, build_ring_mesh)

Point = Tuple[float, float]

# Where a trajectory is written so that it survives a Cura project file. The
# decorator below covers everything inside a session, but decorators are not
# something Cura serialises, so a 3MF save and reload would bring the meshes back
# without their paths and the drawn shapes would slice as solids again. Per-node
# metadata IS written out and read back (ThreeMFWriter._convertUMNodeToSavitarNode
# stores um_node.metadata; ThreeMFReader puts anything it does not recognise as a
# setting straight back into it), so the record travels there as JSON as well.
DRAWN_PATH_METADATA_KEY = "printess_drawn_path"
# Written NAMESPACED. 3MF requires a custom metadata name to be qualified by a
# namespace declared in the model, and "cura" is the one Cura always declares, so
# a bare key is liable to be dropped on the way out. Coming back the namespace
# may or may not still be attached, which is why reading matches on the suffix
# and then re-stores under the qualified name, so a project can be saved and
# reloaded any number of times.
DRAWN_PATH_METADATA_QUALIFIED = "cura:" + DRAWN_PATH_METADATA_KEY


class DrawnPathDecorator(SceneNodeDecorator):
    """The trajectory that produced this mesh, carried ON the mesh.

    An unfilled drawn shape reaches the printer as the path it was drawn along,
    not as the slicer's reading of the solid built from it: a solid records an
    area and no direction, so the order, the seam and the start would all become
    the slicer's to choose. That trajectory therefore has to survive as long as
    the mesh does.

    Keeping it in the tool did not. The mesh lives in the scene; anything the
    tool remembers dies when the tool is reset, when the plugin is reloaded after
    a re-install, or when Cura restarts. The plate then sliced the ribbons as
    solids and nothing said so, because from the g-code's point of view the
    result looks perfectly plausible: one bead following the outline.

    Holding it here makes the plate self-describing. Whatever is on it at the
    moment of slicing carries what is needed to trace it, and the two cannot be
    separated. The points are stored in the node's OWN frame, as built, so the
    node's world transform is what places them: a mesh dragged in Cura is traced
    where it now sits rather than where it was when it was saved.
    """

    def __init__(self, record: Optional[dict] = None):
        super().__init__()
        self._record = record if record is not None else {}

    def getDrawnPathRecord(self) -> dict:
        return self._record

    def __deepcopy__(self, memo):
        # Cura deep-copies decorators when an object is duplicated. The copy gets
        # its own record and no reference back to the node it came from; the
        # duplicate's own transform is what places it, so a copied drawn path is
        # traced correctly at wherever the copy ends up.
        return DrawnPathDecorator(copy.deepcopy(self._record, memo))

CLOSE_THRESHOLD = 1.5      # mm: clicking this close to the first point closes the shape
OSNAP_THRESHOLD = 2.0      # mm: clicks snap onto existing endpoints/corners/intersections
PATH_RENDER_HEIGHT = 0.2   # mm above the plate for committed paths
PREVIEW_RENDER_HEIGHT = 0.25
SHADE_RENDER_HEIGHT = 0.12  # translucent fill shading, below the outlines
NODE_RENDER_HEIGHT = 0.22
NODE_RADIUS = 1.0          # mm: drawn radius of the round node handles, and the
                           # radius within which one can be grabbed — the two are
                           # deliberately equal, so what is visible is what reshapes.
HANDLE_MIN_SPACING = NODE_RADIUS * 5.0  # mm: handles never crowd along a path.
                           # Tied to the grab radius on purpose — each handle
                           # claims NODE_RADIUS either side, so this leaves about
                           # three fifths of the path free to grab and drag.
HANDLE_TURN_ANGLE = 20.0   # degrees: a vertex this sharp is a corner worth a
                           # handle even when handles are being thinned out
FALLBACK_COLORS = ["#3f7ef0", "#f09a30"]
SEGMENT_LENGTH = 0.5       # mm: fixed tessellation step for arcs and curves

# Every shape saved to the build plate is named with this mark, which reaches
# the g-code as a ;MESH: comment and is how the post-processing script tells a
# drawing from an imported model. "fill" is an ordinary solid and is sliced and
# printed exactly like an STL; "path" is an outline, a trajectory the nozzle is
# meant to trace.
# Corner rounding for outlines, as a multiple of half the line width. At 1.0 the
# inside of the corner closes to a cusp, which is the degenerate case; a little
# over gives the stroke a real inner radius and keeps it honestly one bead wide.
FILLET_FACTOR = 1.2


DRAWING_TAG = "PrintessDrawing"
DRAWING_KIND_FILL = "fill"
DRAWING_KIND_PATH = "path"

SHAPE_NAMES = {"line": "Line", "arc": "Arc", "circle": "Circle", "spline": "Curve",
               "rect": "Rectangle", "merged": "Path", "composite": "Path"}
# Shapes with no parametric definition left to protect: their vertices ARE the
# shape, so they can be joined end to end freely. Everything else (an arc, a
# curve, a circle, a rectangle) is defined by its control points and keeps them,
# which is why joining a chain that contains one produces a "composite" — a path
# holding each original shape as a piece, each with its own control points.
FREEHAND_SHAPES = ("line", "merged")
ALIGN_THRESHOLD = 1.5      # mm: cursor locks onto horizontal/vertical alignment with a node
MERGE_EPSILON = 1e-6       # coincident-endpoint tolerance (object snap makes them exact)
# Degrees: an arc locks onto these sweeps, the way a line segment locks onto the
# horizontal and the vertical. ARC_BIAS_TOLERANCE is how far off the arc being
# drawn may be and still be pulled in — the lock is judged on the ANGLE of that
# arc, not on the cursor's distance to some point, because the bulge point that
# produces a given sweep is nowhere the eye can predict.
ARC_BIAS_ANGLES = (90.0, 180.0, 270.0)
ARC_BIAS_TOLERANCE = 8.0

# Uranium's QtKeyDevice does not map Key_Escape / Key_Delete to its own key
# constants — unmapped keys pass through as their raw Qt key code, so accept
# both representations.
ESCAPE_KEY_CODES = {KeyEvent.EscapeKey, int(Qt.Key.Key_Escape.value)}
# macOS labels its main delete key "delete" but reports Backspace, so accept both.
DELETE_KEY_CODES = {int(Qt.Key.Key_Delete.value), int(Qt.Key.Key_Backspace.value)}

DRAG_SLOP = 0.012          # normalised viewport units: beyond this a press is a drag, not a click
PASTE_OFFSET = 4.0         # mm: how far a pasted copy lands from the original

DOUBLE_CLICK_SECONDS = 0.4
DOUBLE_CLICK_DISTANCE = 2.0  # mm
UNDO_DEPTH = 40


class PrintessPathDesigner(Tool):
    def __init__(self):
        super().__init__()
        self._controller = self.getController()

        self.setExposedProperties(
            "ShapeType", "Extruder", "PathLayers", "SnapEnabled",
            "PathsInfo", "SelectedIndex", "StatusText", "PointCount",
            "ExtruderColors", "ExtruderCount", "LineWidthText", "CanUndo",
            "WellPreset", "WellInfo", "WellCols", "TotalsText",
            "CanCopy", "CanPaste", "ExitPrompt")

        # Defaults for newly drawn paths.
        self._shape_type = "line"
        self._extruder = 0
        self._path_layers = 1       # number of stacked layers; heights from settings
        self._speed_override = 0.0  # 0 -> profile speed_print
        self._flow_percent = 100.0
        self._fill_enabled = False
        self._snap_enabled = False

        self._paths: List[dict] = []          # committed paths
        self._current_points: List[Point] = []  # control points of the shape in progress
        self._hover: Optional[Point] = None
        self._selected_index = -1        # primary selection (drives the panel fields)
        self._selected_indices = set()   # full selection; shift-click adds to it

        self._group_node: Optional[SceneNode] = None
        self._preview_node: Optional[PathNode] = None

        # Well-plate replication state.
        self._well_preset = ""                 # "" = no plate overlay
        self._selected_wells = set()           # extra wells that get a copy
        self._well_rings_node: Optional[PathNode] = None
        self._well_sel_node: Optional[PathNode] = None
        self._well_src_node: Optional[PathNode] = None
        self._ghost_node: Optional[PathNode] = None

        self._nodes_node: Optional[PathNode] = None   # dots on connectable endpoints
        self._guides_node: Optional[PathNode] = None  # dashed alignment guides
        self._align_guides = []                       # [((x, z), "v"|"h"), ...]
        self._arc_bias_label = ""                     # what the arc is locked onto, "" = free
        self._hover_shade_node: Optional[PathNode] = None  # fill-mode hover preview
        self._fill_hover_index = -1
        self._node_hover_node: Optional[PathNode] = None    # ring under the hovered node
        self._hover_node_point: Optional[Point] = None

        # Select-mode dragging.
        self._drag_mode = "none"    # "none" | "path" | "node"
        self._drag_path = -1
        self._drag_node = -1
        self._drag_last: Optional[Point] = None
        self._drag_pushed = False

        # Press tracking: in drawing modes a point is only placed on release and
        # only when the cursor did not travel, so press-and-drag never draws.
        self._press_screen: Optional[Tuple[float, float]] = None
        self._press_pos: Optional[Point] = None
        self._press_moved = False
        self._last_click_time = 0.0
        self._last_click_pos: Optional[Point] = None

        # Segment editing (double-click a segment, then Delete).
        self._selected_segment: Optional[Tuple[int, int]] = None
        self._segment_node: Optional[PathNode] = None

        # Shapes taken with Copy, waiting for a Paste. Plain geometry only.
        self._clipboard: List[dict] = []

        # What the last "Save to Build Plate" put on the plate. The drawing is
        # kept after a save, so saving again must update those meshes rather
        # than stack a second copy on top of them. Each entry is
        # {"node", "extruder", "absorbed"}, where "absorbed" is the mesh
        # transformation already folded back into the drawing.
        self._added_nodes: List[dict] = []
        # The drawing as it stood when the plate last agreed with it. While the
        # two still agree there is no reason to draw the drawing outside the
        # tool: the meshes already show it.
        self._saved_state: Optional[tuple] = None
        # NOTE: there is deliberately no list of trajectories to trace here.
        # Anything this tool remembers dies with it, while the meshes live on in
        # the scene, and a plate that outlives its trajectories slices the drawn
        # shapes as solids without saying so. Each mesh carries its own path
        # instead (DrawnPathDecorator), and the list is read back off the plate
        # at slice time by _drawnPathsOnPlate.
        self._backend_connected = False
        # Hooked at startup, not when this tool is first opened: a project can be
        # loaded and sliced without anyone ever touching Path Designer.
        self._connectBackendWhenReady()
        # The action-bar button, built once the main window exists.
        self._button_view = None
        self._addActionBarButtonWhenReady()
        # The "your drawing is not what was sliced" warning, kept so that one
        # can be taken down again rather than stacking a new one per re-slice.
        self._stale_message: Optional[Message] = None

        self._undo_stack: List[List[dict]] = []
        # The drawing as it stood when the tool was opened, and a counter the
        # panel watches to know it should ask what to do about the difference.
        self._session_state: Optional[tuple] = None
        self._exit_prompt = 0
        # The same offer as the toolbar icon's dialog, for every other way out.
        self._leaving_message: Optional[Message] = None
        # A save deactivates the tool itself, and removing a node empties the
        # selection, which makes Cura deactivate it part-way through. Neither is
        # the user walking away from unsaved work.
        self._saving = False

        self._plate_plane = Plane(Vector(0, 1, 0), 0)
        self._snap_points: List[Point] = []  # endpoints/corners/intersections of committed paths
        self._panel_seen = False
        self._settings_connected = False

        Logger.log("i", "PathDesigner: tool initialized")

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def event(self, event):
        # Exceptions raised in the event path would otherwise vanish to stderr
        # (the packaged app has no console), so catch and log everything.
        try:
            return self._handleEvent(event)
        except Exception:
            Logger.logException("e", "PathDesigner: unhandled exception in event handling")
            return False

    def _handleEvent(self, event):
        super().event(event)

        if event.type == Event.ToolActivateEvent:
            Logger.log("i", "PathDesigner: tool activated")
            self._onActivate()
            return False

        if event.type == Event.ToolDeactivateEvent:
            Logger.log("i", "PathDesigner: tool deactivated")
            self._onDeactivate()
            return False

        if event.type == Event.MousePressEvent and MouseEvent.LeftButton in event.buttons:
            Logger.log("d", "PathDesigner: press in '%s' mode", self._shape_type)
            if self._shape_type == "select":
                # Hit test on the true cursor position: snapping it onto a node
                # first would make the shape itself impossible to grab.
                raw = self._pickPlatePosition(event.x, event.y, raw = True)
                # Track the press here too, so a drag only starts moving things
                # once the cursor has actually travelled (see MouseMoveEvent).
                self._press_screen = (event.x, event.y)
                self._press_moved = False
                # A double-click narrows the selection to one segment, but it
                # must still arm the drag: the press that starts a drag usually
                # lands within the double-click window of the click that selected
                # the shape, and routing it away from _beginSelectDrag left the
                # shape unmovable.
                if self._isDoubleClick(raw):
                    self._selectSegmentAt(raw)
                self._beginSelectDrag(raw)
                return True
            # Drawing modes: remember the press but place nothing yet. The point
            # is committed on release, and only if the cursor stayed put, so a
            # press-and-drag can never drop a point.
            self._press_screen = (event.x, event.y)
            self._press_pos = self._pickPlatePosition(event.x, event.y)
            self._press_moved = False
            return True

        if event.type == Event.MouseMoveEvent:
            position = self._pickPlatePosition(event.x, event.y)
            if self._press_screen is not None:
                dx = event.x - self._press_screen[0]
                dy = event.y - self._press_screen[1]
                if (dx * dx + dy * dy) > (DRAG_SLOP * DRAG_SLOP):
                    self._press_moved = True
            if self._drag_mode != "none":
                if MouseEvent.LeftButton not in event.buttons:
                    self._endSelectDrag()  # release was missed; do not stick to the cursor
                elif self._press_moved:
                    # Moving a whole shape follows the raw cursor: a snapped
                    # position would make the delta jump by up to the snap
                    # radius, which reads as the shape flying off on its own.
                    # Reshaping a single node still snaps, so endpoints can meet.
                    self._updateSelectDrag(
                        self._pickPlatePosition(event.x, event.y, raw = True)
                        if self._drag_mode == "path" else position)
                return True
            if self._shape_type == "erase":
                self._updateEraseHover(position)
                return False
            if self._shape_type == "fill":
                self._updateFillHover(position)
                return False
            self._updateNodeHover(position)
            if self._current_points and position is not None:
                previous_bias = self._arc_bias_label
                self._hover = self._applyDrawBias(position)
                self._updatePreview()
                if self._arc_bias_label != previous_bias:
                    self._emitChanged()  # refresh the "locked to 90°" hint
            return False

        if event.type == Event.MouseReleaseEvent:
            if self._drag_mode != "none":
                self._endSelectDrag()
                return True
            if self._press_screen is not None:
                was_click = not self._press_moved
                press_pos = self._press_pos
                self._press_screen = None
                self._press_pos = None
                self._press_moved = False
                if was_click and self._shape_type != "select":
                    if press_pos is None:
                        # Clicking off the build plate ends the current path.
                        if self._current_points:
                            self.finishPath()
                            return True
                        return False
                    self._onLeftClick(press_pos)
                    return True
            return False

        if event.type == Event.KeyPressEvent:
            if event.key == KeyEvent.EnterKey:
                self.finishPath()
                return True
            if event.key in DELETE_KEY_CODES:
                if self._selected_segment is not None:
                    self.deleteSelectedSegment()
                    return True
                if self._selected_indices:
                    self.deleteSelected()
                    return True
            if event.key in ESCAPE_KEY_CODES:
                if self._current_points:
                    # Esc ends the current path, keeping it when it has enough points.
                    self.finishPath()
                    return True
                if self._selected_segment is not None:
                    self._clearSegmentSelection()
                    self._emitChanged()
                    return True
                if self._selected_index >= 0:
                    self.setSelectedIndex(-1)
                    return True

        return False

    def _onActivate(self):
        try:
            plugin_path = PluginRegistry.getInstance().getPluginPath(self.getPluginId())
            panel = os.path.join(plugin_path or "", "PathDesignerPanel.qml")
            Logger.log("i", "PathDesigner: metadata=%s panel=%s exists=%s",
                       self.getMetaData(), panel, os.path.isfile(panel))
        except Exception:
            Logger.logException("w", "PathDesigner: could not resolve panel path")
        # Do NOT call Selection.clear() here: CuraApplication.onSelectionChanged
        # deactivates the active tool whenever the selection becomes empty, which
        # would instantly kick this tool off again. An existing selection is
        # harmless while drawing.
        # Suspend the selection tool so left clicks are never consumed by
        # (de)selection while drawing. Restored on deactivate.
        self._controller.setSelectionTool(None)
        # A prompt belongs to the session that raised it. The panel opens its
        # dialog whenever this value CHANGES, and while the tool is shut the QML
        # side reads it as 0, so a count left standing from last time reads as a
        # fresh change the moment the tool is opened again: the dialog appeared
        # immediately on opening, and whatever was clicked closed the tool again.
        self._exit_prompt = 0
        self._hideLeavingOffer()
        self._ensureGroupNode()
        self._group_node.setVisible(True)  # the drawing always shows while editing
        # Opening the tool on a plate whose drawing this session has never seen,
        # which is what a reloaded project looks like. The shapes carry their own
        # paths, so the drawing can be collected back off the plate and edited.
        # Only when there is nothing in hand: a drawing in progress is never
        # replaced by what happens to be lying on the plate.
        if not self._paths:
            try:
                self._restoreDrawingFromPlate()
            except Exception:
                # Opening the tool must never fail because of what is lying on
                # the plate. Losing the recovery costs an edit; an exception here
                # costs the whole application, as it did once.
                self._paths = []
                Logger.logException("e", "PathDesigner: could not recover the drawing from the plate")
        # Catch the drawing up with anything done to the saved meshes out in the
        # scene, before they are hidden and the drawing takes over the view.
        self._absorbMeshMoves()
        self._setSavedMeshesVisible(False)
        self._connectSettingSignals()
        self._connectBackend()
        self._refreshLineWidths()
        self._rebuildWellOverlay()
        self._setTopView()
        # What "revert" means: the drawing exactly as it was when this tool was
        # opened. Taken after any recovery from the plate, so reopening a project
        # and immediately reverting is a no-op rather than a way to lose the
        # shapes that were just recovered.
        self._session_state = self._plateState()
        self._emitChanged()

    def _onDeactivate(self):
        self._exit_prompt = 0
        # Commit (not discard) any path still being drawn, so leaving the tool
        # never loses work.
        if self._current_points:
            self.finishPath()
        self._cancelCurrent()
        self._clearFillHover()
        self._clearSegmentSelection()
        self._updateNodeHover(None)
        self._setSavedMeshesVisible(True)
        self._updateDrawingVisibility()
        self._offerToKeepOrDropOnLeaving()
        try:
            self._controller.setSelectionTool("SelectionTool")
        except Exception:
            Logger.logException("w", "PathDesigner: could not restore selection tool")

    def _onLeftClick(self, position: Point):
        shape = self._shape_type

        if shape == "select":
            return  # Select never draws; picking and dragging is handled on press.

        if shape == "erase":
            # Rub out whatever the hover highlight is showing.
            target = self._eraseTargetAt(position)
            if target is not None:
                self._setSelectedSegment(target)
                self.deleteSelectedSegment()
            return

        if shape == "fill":
            # Fill mode: clicking inside a closed shape toggles its fill.
            for i in range(len(self._paths) - 1, -1, -1):
                path = self._paths[i]
                if path["closed"] and PathShapes.point_in_polygon(position, path["points"]):
                    self._pushUndo()
                    path["fill"] = not path["fill"]
                    self._recomputeFill(path)
                    self._rebuildPathNode(i)
                    self._rebuildWellOverlay()
                    self._emitChanged()
                    return
            return

        if shape in ("line", "spline"):
            if len(self._current_points) >= 3 and PathShapes.dist(position, self._current_points[0]) < CLOSE_THRESHOLD:
                self._finishCurrent(closed = True)
                return
            self._current_points.append(self._applyDrawBias(position))

        elif shape == "circle":
            if not self._current_points:
                self._current_points.append(position)
            else:
                radius = PathShapes.dist(self._current_points[0], position)
                if radius > 0.2:
                    self._current_points.append(position)
                    self._finishCurrent(closed = True)
                    return

        elif shape == "arc":
            # The third click sets the bulge, and is biased onto a clean sweep.
            self._current_points.append(self._applyDrawBias(position))
            if len(self._current_points) >= 3:
                self._finishCurrent(closed = False)
                return

        elif shape == "rect":
            if not self._current_points:
                self._current_points.append(position)
            else:
                first = self._current_points[0]
                if abs(position[0] - first[0]) > 0.2 and abs(position[1] - first[1]) > 0.2:
                    self._current_points.append(position)
                    self._finishCurrent(closed = True)
                    return

        self._hover = position
        self._updatePreview()
        self._emitChanged()

    # ------------------------------------------------------------------
    # Picking
    # ------------------------------------------------------------------

    def _pickPlatePosition(self, x, y, raw: bool = False) -> Optional[Point]:
        camera = self._controller.getScene().getActiveCamera()
        if camera is None:
            return None
        ray = camera.getRay(x, y)
        target = self._plate_plane.intersectsRay(ray)
        if target is False:  # intersectsRay returns False on a miss, not None
            return None
        spot = ray.getPointAlongRay(target)

        half_w, half_d = self._plateHalfSize()
        if abs(spot.x) > half_w + 0.5 or abs(spot.z) > half_d + 0.5:
            return None  # off the build plate
        px = max(-half_w, min(half_w, spot.x))
        pz = max(-half_d, min(half_d, spot.z))

        if raw:
            # Unmodified cursor position — used for hit testing in Select mode,
            # where snapping the press point onto a node would make it
            # impossible to grab the shape itself.
            return (px, pz)

        # Object snap first: endpoints, corners, centres, and intersections of
        # the committed paths.
        self._align_guides = []
        best = None
        best_dist = OSNAP_THRESHOLD
        for candidate in self._snap_points:
            d = PathShapes.dist((px, pz), candidate)
            if d < best_dist:
                best = candidate
                best_dist = d
        if best is not None:
            return best

        # Alignment locks: pull the cursor onto horizontal/vertical alignment
        # with nearby nodes (including the shape being drawn) and remember the
        # aligned nodes so dashed guides can be rendered.
        candidates = self._snap_points + self._current_points
        best_x = None
        best_x_dist = ALIGN_THRESHOLD
        best_z = None
        best_z_dist = ALIGN_THRESHOLD
        for candidate in candidates:
            dx = abs(px - candidate[0])
            dz = abs(pz - candidate[1])
            if dx < best_x_dist:
                best_x_dist = dx
                best_x = candidate
            if dz < best_z_dist:
                best_z_dist = dz
                best_z = candidate
        if best_x is not None:
            px = best_x[0]
            self._align_guides.append((best_x, "v"))
        if best_z is not None:
            pz = best_z[1]
            self._align_guides.append((best_z, "h"))

        if self._snap_enabled:
            # Snap on a line-width grid in printer coordinates (corner origin),
            # so drawn shapes come out as whole multiples of the bead width.
            # Applied per axis: an axis held by an alignment lock keeps the
            # aligned value, the other one still snaps to the grid.
            step = self._snapStep()
            if best_x is None:
                px = round((px + half_w) / step) * step - half_w
                px = max(-half_w, min(half_w, px))
            if best_z is None:
                pz = half_d - round((half_d - pz) / step) * step
                pz = max(-half_d, min(half_d, pz))

        return (px, pz)

    def _snapStep(self) -> float:
        """Grid step for snapping = the active extruder's line width."""
        return max(0.05, self._lineWidth(self._extruder))

    def _applyDrawBias(self, position: Point) -> Point:
        """Shape-specific cursor bias: axis locks for lines, clean sweeps for arcs."""
        if self._shape_type == "arc":
            return self._applyArcBias(position)
        return self._applyAxisBias(position)

    def _tangentsAt(self, point: Point) -> List[Point]:
        """Unit directions in which existing paths leave `point`.

        Used to offer a tangent arc where the new arc starts or ends on an
        existing path, so the two meet without a visible kink.
        """
        directions: List[Point] = []
        for path in self._paths:
            points = path["points"]
            count = len(points)
            if count < 2:
                continue
            span = count if (path["closed"] and count > 2) else count - 1
            for k in range(span):
                # Touching a segment part-way along (an object-snapped crossing,
                # say) is just as much a connection as landing on a vertex.
                a, b = points[k], points[(k + 1) % count]
                if (PathShapes.dist(point, a) > MERGE_EPSILON
                        and PathShapes.dist(point, b) > MERGE_EPSILON
                        and PathShapes.point_segment_distance(point, a, b) <= MERGE_EPSILON):
                    length = PathShapes.dist(a, b)
                    if length > 1e-9:
                        directions.append(((b[0] - a[0]) / length, (b[1] - a[1]) / length))
            for k in range(count):
                if PathShapes.dist(point, points[k]) > MERGE_EPSILON:
                    continue
                neighbours = []
                if k > 0:
                    neighbours.append(points[k - 1])
                elif path["closed"]:
                    neighbours.append(points[-1])
                if k < count - 1:
                    neighbours.append(points[k + 1])
                elif path["closed"]:
                    neighbours.append(points[0])
                for neighbour in neighbours:
                    length = PathShapes.dist(neighbour, point)
                    if length > 1e-9:
                        directions.append(((point[0] - neighbour[0]) / length,
                                           (point[1] - neighbour[1]) / length))
        return directions

    def _tangentBulge(self, anchor: Point, other: Point, tangent: Point) -> Optional[Point]:
        """Bulge point of the arc from `anchor` to `other` that leaves `anchor`
        along `tangent`.

        There is exactly one such circle: its centre lies on the line through
        `anchor` perpendicular to the tangent, at the distance that also puts it
        on the perpendicular bisector of the chord. Returns the arc's midpoint,
        which is what tessellate_arc takes as its bulge.
        """
        nx, nz = -tangent[1], tangent[0]           # unit normal: the centre lies along it
        dx, dz = anchor[0] - other[0], anchor[1] - other[1]
        denominator = nx * dx + nz * dz
        if abs(denominator) < 1e-9:
            return None                             # `other` is on the tangent line: a straight run
        radius_signed = -(dx * dx + dz * dz) / (2.0 * denominator)
        radius = abs(radius_signed)
        if radius < 1e-6 or radius > 1e6:
            return None
        center = (anchor[0] + nx * radius_signed, anchor[1] + nz * radius_signed)

        a_anchor = math.atan2(anchor[1] - center[1], anchor[0] - center[0])
        a_other = math.atan2(other[1] - center[1], other[0] - center[0])
        # Leaving along +tangent turns counter-clockwise when the centre is on
        # the +normal side (radius_signed > 0), clockwise otherwise.
        sweep = a_other - a_anchor
        if radius_signed > 0:
            while sweep <= 0:
                sweep += 2.0 * math.pi
        else:
            while sweep >= 0:
                sweep -= 2.0 * math.pi
        a_mid = a_anchor + sweep / 2.0
        return (center[0] + radius * math.cos(a_mid), center[1] + radius * math.sin(a_mid))

    def _applyArcBias(self, position: Point) -> Point:
        """Bias an arc toward a clean sweep, or toward meeting its neighbour smoothly.

        The first two clicks fix the chord; the third says how far the arc bulges
        away from it. Two locks are offered: a quarter, half, or three-quarter
        circle, and — where an end of the arc sits on an existing path — leaving
        that path tangentially so the two join without a kink. Both are judged on
        the ANGLE of the arc being drawn, within ARC_BIAS_TOLERANCE, the same way
        a line segment locks onto the horizontal once it is nearly horizontal.
        """
        self._arc_bias_label = ""
        if len(self._current_points) != 2:
            return position  # not placing the bulge yet
        start, end = self._current_points[0], self._current_points[1]
        chord = PathShapes.dist(start, end)
        if chord < 1e-6:
            return position
        for candidate in self._snap_points:
            if PathShapes.dist(position, candidate) < 1e-9:
                return position  # object snap wins, as it does over the axis bias

        # Measure the arc the cursor is defining right now; both locks are judged
        # against its angles, so they engage whenever the arc is nearly right
        # rather than only when the cursor finds an invisible point.
        measured = PathShapes.arc_tangent_and_sweep(start, position, end)
        if measured is None:
            return position  # cursor on the chord: a straight run, nothing to bias
        tangent_start, tangent_end, sweep = measured

        # 1. Tangent join, tested first so it wins over a sweep lock: is the arc
        #    already leaving a path it touches at close to that path's direction?
        for anchor, other, arc_tangent in ((start, end, tangent_start),
                                           (end, start, tangent_end)):
            for direction in self._tangentsAt(anchor):
                if PathShapes.angle_between_lines(arc_tangent, direction) > ARC_BIAS_TOLERANCE:
                    continue
                # Both ways round the tangent circle are tangent; keep whichever
                # is nearer the cursor, so the arc does not flip to the far side.
                bulges = [bulge for bulge in
                          (self._tangentBulge(anchor, other, direction),
                           self._tangentBulge(anchor, other, (-direction[0], -direction[1])))
                          if bulge is not None]
                if not bulges:
                    continue
                self._align_guides = []
                self._arc_bias_label = "tangent"
                return min(bulges, key = lambda bulge: PathShapes.dist(position, bulge))

        # 2. Clean sweeps, kept on the side of the chord the cursor is already on.
        mid = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
        nx, nz = -(end[1] - start[1]) / chord, (end[0] - start[0]) / chord
        side = 1.0 if ((position[0] - mid[0]) * nx + (position[1] - mid[1]) * nz) >= 0 else -1.0
        for angle in ARC_BIAS_ANGLES:
            if abs(sweep - angle) > ARC_BIAS_TOLERANCE:
                continue
            half = math.radians(angle) / 2.0
            # Height of the arc's midpoint above the chord: R(1 - cos(θ/2)),
            # with R = chord / (2 sin(θ/2)).
            sagitta = chord * (1.0 - math.cos(half)) / (2.0 * math.sin(half))
            self._align_guides = []
            self._arc_bias_label = "{0:g}°".format(angle)
            return (mid[0] + nx * sagitta * side, mid[1] + nz * sagitta * side)
        return position

    def _applyAxisBias(self, position: Point) -> Point:
        """Bias line segments toward horizontal/vertical.

        While drawing lines, the segment from the previous point locks onto the
        nearest axis whenever the off-axis component is small relative to the
        along-axis component, so the cursor must move deliberately off-axis to
        unlock. Snapped (object-snap) positions are never modified.
        """
        if self._shape_type != "line" or not self._current_points:
            return position
        if self._align_guides:
            return position  # an alignment lock is already in effect
        for candidate in self._snap_points:
            if PathShapes.dist(position, candidate) < 1e-9:
                return position  # object snap wins over the axis bias
        last = self._current_points[-1]
        dx = position[0] - last[0]
        dz = position[1] - last[1]
        adx, adz = abs(dx), abs(dz)
        if adx >= adz:
            if adz <= max(1.0, 0.15 * adx):
                return (position[0], last[1])
        else:
            if adx <= max(1.0, 0.15 * adz):
                return (last[0], position[1])
        return position

    def _plateHalfSize(self):
        stack = Application.getInstance().getGlobalContainerStack()
        if stack is None:
            return 60.0, 40.0
        try:
            return (float(stack.getProperty("machine_width", "value")) / 2.0,
                    float(stack.getProperty("machine_depth", "value")) / 2.0)
        except Exception:
            return 60.0, 40.0

    # ------------------------------------------------------------------
    # Path lifecycle
    # ------------------------------------------------------------------

    def _finishCurrent(self, closed: bool):
        shape = self._shape_type
        control = list(self._current_points)
        self._current_points = []
        self._hover = None
        self._updatePreview()

        seg = SEGMENT_LENGTH
        fill_segments: List = []

        if shape == "line":
            points = list(control)  # a copy: control and points are edited separately
        elif shape == "spline":
            points = PathShapes.tessellate_catmull_rom(control, seg, closed)
        elif shape == "arc":
            points = PathShapes.tessellate_arc(control[0], control[2], control[1], seg)
        elif shape == "circle":
            radius = PathShapes.dist(control[0], control[1])
            points = PathShapes.tessellate_circle(control[0], radius, seg)
        elif shape == "rect":
            (x1, z1), (x2, z2) = control[0], control[1]
            points = [(x1, z1), (x2, z1), (x2, z2), (x1, z2)]
        else:
            return

        if len(points) < 2 or PathShapes.polyline_length(points) < 0.05:
            # Two clicks landing on the same spot (a double-click, or two clicks
            # that both snapped to the same node) would otherwise commit a
            # zero-length path that shows up as a stray mark on the plate.
            self._emitChanged()
            return

        self._pushUndo()

        extruder = self._extruder
        line_width = self._lineWidth(extruder)

        if closed and self._fill_enabled:
            spacing = line_width * 100.0 / self._fillDensityFromSettings(extruder)
            fill_segments = PathShapes.zigzag_fill(points, spacing, line_width * 0.5)

        path = {
            "shape": shape,
            "control": control,
            "points": points,
            "closed": closed,
            "fill": bool(closed and self._fill_enabled),
            "fill_segments": fill_segments,
            "extruder": extruder,
            "layers": max(1, int(self._path_layers)),
            "speed": self._speed_override,
            "flow": self._flow_percent,
            "line_width": line_width,
            "node": None,
        }
        self._paths.append(path)
        self._rebuildPathNode(len(self._paths) - 1)
        self._tryMergePaths()
        self._rebuildSnapPoints()
        self._rebuildWellOverlay()
        self._emitChanged()

    def _cancelCurrent(self):
        self._current_points = []
        self._hover = None
        self._arc_bias_label = ""
        self._updatePreview()

    def _refreshLineWidths(self):
        """Re-read every path's bead width from its extruder and redraw.

        Line width comes from the dispense tip profile, so switching tips has to
        change what is already drawn on the plate, not just what is drawn next:
        a thinner tip must show a thinner line.
        """
        changed = False
        for index, path in enumerate(self._paths):
            width = self._lineWidth(path["extruder"])
            if abs(width - path.get("line_width", 0.0)) < 1e-9:
                continue
            path["line_width"] = width
            self._recomputeFill(path)
            self._rebuildPathNode(index)
            changed = True
        if changed:
            self._rebuildWellOverlay()
            self._emitChanged()

    def _connectSettingSignals(self):
        """Watch the print settings so a dispense tip change redraws the paths."""
        if self._settings_connected:
            return
        try:
            from cura.CuraApplication import CuraApplication
            machine_manager = CuraApplication.getInstance().getMachineManager()
        except Exception:
            Logger.logException("w", "PathDesigner: no machine manager to watch for line width changes")
            return
        for signal_name in ("activeStackValueChanged", "activeQualityChanged",
                            "activeQualityGroupChanged", "activeMaterialChanged"):
            signal = getattr(machine_manager, signal_name, None)
            if signal is None:
                continue
            try:
                signal.connect(self._onSettingsChanged)
            except Exception:
                Logger.logException("w", "PathDesigner: could not connect %s", signal_name)
        self._settings_connected = True

    def _onSettingsChanged(self, *args):
        self._refreshLineWidths()
        self._updatePreview()  # the rubber band is drawn at the live width too
        self._emitChanged()

    def _rebuildPathNode(self, index: int):
        path = self._paths[index]
        # Always draw at the extruder's current bead width, so what is on the
        # plate is the width that will actually be printed.
        path["line_width"] = self._lineWidth(path["extruder"])
        node = path["node"]
        if node is None:
            node = PathNode(self._ensureGroupNode())
            node.setName("PathDesigner_{0}".format(index + 1))
            path["node"] = node

        outline = list(path["points"])
        if path["closed"]:
            outline = outline + [outline[0]]
        polylines = (self._outlineWithoutHighlight(index, outline)
                     + [[a, b] for (a, b) in path["fill_segments"]])
        mesh = build_ribbon_mesh(polylines, path["line_width"], PATH_RENDER_HEIGHT)
        node.setMeshData(mesh)
        node.setColor(self._pathColor(index))
        self._controller.getScene().sceneChanged.emit(node)

        # Translucent shading so filled shapes read as filled at a glance.
        shade = path.get("shade_node")
        if path["fill"] and path["closed"]:
            if shade is None or shade.getParent() is None:
                shade = PathNode(self._ensureGroupNode())
                shade.setName("PathDesignerShade_{0}".format(index + 1))
                shade.setTransparent(True)
                path["shade_node"] = shade
            shade.setMeshData(build_triangle_mesh(
                PathShapes.triangulate_polygon(path["points"]), SHADE_RENDER_HEIGHT))
            color = self._extruderColorRgba(path["extruder"])
            shade.setColor(color[:3] + [0.25])
            self._controller.getScene().sceneChanged.emit(shade)
        elif shade is not None:
            shade.setMeshData(None)
            self._controller.getScene().sceneChanged.emit(shade)

    def _refreshColors(self):
        for i, path in enumerate(self._paths):
            if path["node"] is not None:
                path["node"].setColor(self._pathColor(i))
                self._controller.getScene().sceneChanged.emit(path["node"])

    def _pathColor(self, index: int) -> List[float]:
        color = self._extruderColorRgba(self._paths[index]["extruder"])
        if index in self._selected_indices:
            color = [min(1.0, c * 0.4 + 0.6) for c in color[:3]] + [1.0]
        return color

    # ------------------------------------------------------------------
    # Preview (rubber band while drawing)
    # ------------------------------------------------------------------

    def _updatePreview(self):
        node = self._ensurePreviewNode()
        self._updateGuides()

        if not self._current_points or self._hover is None:
            node.setMeshData(None)
            self._controller.getScene().sceneChanged.emit(node)
            return

        shape = self._shape_type
        pts = self._current_points
        hover = self._hover
        seg = SEGMENT_LENGTH

        if shape == "line":
            preview = pts + [hover]
        elif shape == "spline":
            preview = PathShapes.tessellate_catmull_rom(pts + [hover], seg, False)
        elif shape == "arc":
            if len(pts) == 1:
                preview = [pts[0], hover]
            else:
                preview = PathShapes.tessellate_arc(pts[0], hover, pts[1], seg)
        elif shape == "circle":
            radius = PathShapes.dist(pts[0], hover)
            circle = PathShapes.tessellate_circle(pts[0], max(radius, 0.05), seg)
            preview = circle + [circle[0]]
        elif shape == "rect":
            (x1, z1), (x2, z2) = pts[0], hover
            preview = [(x1, z1), (x2, z1), (x2, z2), (x1, z2), (x1, z1)]
        else:
            preview = []

        marker = None
        marker_size = 0.0
        if shape in ("line", "spline") and len(pts) >= 3:
            marker = pts[0]
            marker_size = CLOSE_THRESHOLD

        width = self._lineWidth(self._extruder)
        mesh = build_ribbon_mesh([preview], width, PREVIEW_RENDER_HEIGHT, marker, marker_size)
        node.setMeshData(mesh)
        color = self._extruderColorRgba(self._extruder)
        node.setColor(color[:3] + [0.55])
        self._controller.getScene().sceneChanged.emit(node)

    def _updateGuides(self):
        """Dashed lines from aligned nodes to the cursor while an alignment
        lock is active."""
        guides = self._ensureOverlayNode("_guides_node", True)
        polylines = []
        if self._current_points and self._hover is not None:
            for point, axis in self._align_guides:
                if axis == "v":
                    end = (point[0], self._hover[1])
                else:
                    end = (self._hover[0], point[1])
                polylines.extend(PathShapes.dashed_segments(point, end))
        guides.setMeshData(build_ribbon_mesh(polylines, 0.3, 0.18) if polylines else None)
        guides.setColor([0.25, 0.55, 0.95, 0.9])
        self._controller.getScene().sceneChanged.emit(guides)

    # ------------------------------------------------------------------
    # Select mode: pick, move, and reshape existing paths
    # ------------------------------------------------------------------

    def _editableNodes(self, path: dict) -> List[Point]:
        """The list a node drag writes into.

        Freehand shapes (lines and merged chains) edit their vertices; the
        parametric shapes edit their defining control points instead, and are
        rebuilt from those when one moves. Returned live, so a drag mutating an
        entry changes the path.
        """
        if path["shape"] == "composite":
            # Derived, not live: a composite handle can drive several pieces at
            # once, so drags go through _moveCompositeHandle instead.
            return self._compositeHandlePoints(path)
        if path["shape"] in FREEHAND_SHAPES:
            return path["points"]
        return path.get("control", [])

    def _handleIndices(self, path: dict) -> List[int]:
        """Which of _editableNodes actually get a handle.

        A merged chain keeps whatever vertices it was built from, and merging in
        an arc or a curve brings one every SEGMENT_LENGTH. A handle on each would
        bury the shape under dots and — since anything within NODE_RADIUS of a
        handle reshapes rather than moves — leave no part of the shape free to
        drag. So handles thin out: the ends always, a corner as long as it does
        not collide with the previous handle, and otherwise only vertices spaced
        at least HANDLE_MIN_SPACING apart. Hand-clicked vertices are normally
        further apart than that, so they all survive.
        """
        nodes = self._editableNodes(path)
        count = len(nodes)
        if count <= 2 or path["shape"] not in FREEHAND_SHAPES:
            return list(range(count))

        closed = path["closed"]
        kept: List[int] = []
        last: Optional[Point] = None
        for i in range(count):
            if not closed and (i == 0 or i == count - 1):
                kept.append(i)
                last = nodes[i]
                continue
            previous = nodes[i - 1] if i > 0 else nodes[-1]
            following = nodes[i + 1] if i < count - 1 else nodes[0]
            corner = PathShapes.turn_angle(previous, nodes[i], following) >= HANDLE_TURN_ANGLE
            spacing = NODE_RADIUS * 2.0 if corner else HANDLE_MIN_SPACING
            if last is not None and PathShapes.dist(nodes[i], last) < spacing:
                continue
            kept.append(i)
            last = nodes[i]
        return kept

    def _handlePoints(self, path: dict) -> List[Point]:
        """The handle positions of a path, in _handleIndices order."""
        nodes = self._editableNodes(path)
        return [nodes[i] for i in self._handleIndices(path)]

    def _pointsFor(self, shape: str, control: List[Point], closed: bool = False) -> List[Point]:
        """The outline a shape's control points describe."""
        if shape == "spline" and len(control) >= 2:
            return PathShapes.tessellate_catmull_rom(control, SEGMENT_LENGTH, closed)
        if shape == "arc" and len(control) >= 3:
            return PathShapes.tessellate_arc(control[0], control[2], control[1], SEGMENT_LENGTH)
        if shape == "circle" and len(control) >= 2:
            radius = max(PathShapes.dist(control[0], control[1]), 0.1)
            return PathShapes.tessellate_circle(control[0], radius, SEGMENT_LENGTH)
        if shape == "rect" and len(control) >= 2:
            (x1, z1), (x2, z2) = control[0], control[1]
            return [(x1, z1), (x2, z1), (x2, z2), (x1, z2)]
        return list(control)

    def _regeneratePath(self, path: dict):
        """Rebuild a shape's outline from its control points."""
        if path["shape"] == "composite":
            self._regenerateComposite(path)
            return
        control = path.get("control", [])
        points = self._pointsFor(path["shape"], control, path["closed"]) if control else []
        if len(points) >= 2:
            # Never overwrite a good outline with a degenerate one: a parametric
            # shape short of control points would otherwise collapse to a
            # straight run between whatever it does have.
            path["points"] = points

    # ------------------------------------------------------------------
    # Composite paths: a chain that keeps each shape it was built from
    # ------------------------------------------------------------------

    def _pathAsPieces(self, path: dict) -> List[dict]:
        """A path expressed as composite pieces, each with its own control points."""
        if path["shape"] == "composite":
            return [{"shape": piece["shape"], "control": list(piece["control"])}
                    for piece in path["pieces"]]
        if path["shape"] in FREEHAND_SHAPES:
            return [{"shape": "line", "control": list(path["points"])}]
        return [{"shape": path["shape"], "control": list(path.get("control", []))}]

    def _reversePiece(self, piece: dict) -> dict:
        """The same piece travelled the other way.

        An arc's control points are (start, end, bulge), so reversing swaps the
        first two and leaves the bulge — it is a point on the arc either way.
        """
        control = list(piece["control"])
        if piece["shape"] == "arc" and len(control) >= 3:
            control = [control[1], control[0]] + control[2:]
        else:
            control = list(reversed(control))
        return {"shape": piece["shape"], "control": control}

    def _reversedPieces(self, pieces: List[dict]) -> List[dict]:
        return [self._reversePiece(piece) for piece in reversed(pieces)]

    def _regenerateComposite(self, path: dict):
        """Rebuild a composite's outline by regenerating and joining its pieces."""
        points: List[Point] = []
        for piece in path["pieces"]:
            piece_points = self._pointsFor(piece["shape"], piece["control"])
            if len(piece_points) < 2:
                continue
            if points and PathShapes.dist(points[-1], piece_points[0]) < MERGE_EPSILON:
                piece_points = piece_points[1:]  # shared junction, counted once
            points.extend(piece_points)
        if (path["closed"] and len(points) > 2
                and PathShapes.dist(points[0], points[-1]) < MERGE_EPSILON):
            points = points[:-1]  # closed outlines do not repeat their first point
        path["points"] = points

    def _compositeHandles(self, path: dict) -> List[List[Tuple[int, int]]]:
        """Handles of a composite, each as the (piece, control) slots it drives.

        Where two pieces meet they share a point, and both slots belong to the
        same handle — otherwise dragging a junction would tear the chain apart.
        """
        groups: List[List[Tuple[int, int]]] = []
        positions: List[Point] = []
        for piece_index, piece in enumerate(path["pieces"]):
            for control_index, point in enumerate(piece["control"]):
                for group_index, existing in enumerate(positions):
                    if PathShapes.dist(point, existing) < MERGE_EPSILON:
                        groups[group_index].append((piece_index, control_index))
                        break
                else:
                    positions.append(point)
                    groups.append([(piece_index, control_index)])
        return groups

    def _compositeHandlePoints(self, path: dict) -> List[Point]:
        return [path["pieces"][slots[0][0]]["control"][slots[0][1]]
                for slots in self._compositeHandles(path)]

    def _moveCompositeHandle(self, path: dict, handle: int, position: Point):
        """Move one handle of a composite, keeping its pieces joined."""
        groups = self._compositeHandles(path)
        if not (0 <= handle < len(groups)):
            return
        for piece_index, control_index in groups[handle]:
            piece = path["pieces"][piece_index]
            if piece["shape"] == "arc":
                self._moveArcControl(piece["control"], control_index, position)
            else:
                piece["control"][control_index] = position
        self._regenerateComposite(path)

    def _applyPieces(self, path: dict, pieces: List[dict]):
        """Store a joined chain on `path`, as plain vertices when every piece is
        freehand and as a composite as soon as one piece is a real shape."""
        if all(piece["shape"] in FREEHAND_SHAPES for piece in pieces):
            points: List[Point] = []
            for piece in pieces:
                piece_points = list(piece["control"])
                if points and PathShapes.dist(points[-1], piece_points[0]) < MERGE_EPSILON:
                    piece_points = piece_points[1:]
                points.extend(piece_points)
            path.pop("pieces", None)
            path["shape"] = "merged"
            path["points"] = points
            path["control"] = list(points)
        else:
            path["shape"] = "composite"
            path["pieces"] = pieces
            path["control"] = []
            self._regenerateComposite(path)

    def _closeChain(self, path: dict) -> bool:
        """Turn a chain whose two ends meet into a closed loop, so it can be
        filled. Returns whether anything changed."""
        if path["shape"] == "composite":
            path["closed"] = True
            self._regenerateComposite(path)
        elif path["shape"] in FREEHAND_SHAPES:
            path["points"] = path["points"][:-1]
            path["closed"] = True
            path["shape"] = "merged"
            path["control"] = list(path["points"])
        else:
            return False  # a single parametric shape keeps its own definition
        self._recomputeFill(path)
        return True

    def _arcSweepAndSide(self, control: List[Point]):
        """(sweep in degrees, which side of the chord) of a 3-point arc."""
        if len(control) < 3:
            return None
        measured = PathShapes.arc_tangent_and_sweep(control[0], control[2], control[1])
        if measured is None:
            return None
        start, end = control[0], control[1]
        chord = PathShapes.dist(start, end)
        if chord < 1e-9:
            return None
        mid = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
        nx, nz = -(end[1] - start[1]) / chord, (end[0] - start[0]) / chord
        offset = (control[2][0] - mid[0]) * nx + (control[2][1] - mid[1]) * nz
        return measured[2], (1.0 if offset >= 0 else -1.0)

    def _apexBulge(self, start: Point, end: Point, sweep: float, side: float) -> Optional[Point]:
        """The point at the very top of an arc of this sweep across this chord."""
        chord = PathShapes.dist(start, end)
        half = math.radians(sweep) / 2.0
        if chord < 1e-9 or abs(math.sin(half)) < 1e-9:
            return None
        sagitta = chord * (1.0 - math.cos(half)) / (2.0 * math.sin(half))
        mid = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
        nx, nz = -(end[1] - start[1]) / chord, (end[0] - start[0]) / chord
        return (mid[0] + nx * sagitta * side, mid[1] + nz * sagitta * side)

    def _moveArcControl(self, control: List[Point], control_index: int, position: Point):
        """Move one control point of an arc, keeping its bulge handle on top.

        The bulge is only a point the arc passes through, so moving an end would
        otherwise pivot the arc around it and leave the handle stranded off to
        one side. Reseating it at the apex, with the arc's sweep unchanged, keeps
        the handle where the eye expects it and keeps the curve's character.
        """
        if control_index == 2 or len(control) < 3:
            control[control_index] = position
            return
        measured = self._arcSweepAndSide(control)
        control[control_index] = position
        if measured is None:
            return
        apex = self._apexBulge(control[0], control[1], measured[0], measured[1])
        if apex is not None:
            control[2] = apex

    def _nodeAt(self, position: Point):
        """(path index, node index) of the handle under the cursor, or (-1, -1).

        Only nodes of already-selected shapes can be grabbed, and only strictly
        within the drawn handle: otherwise pressing anywhere near a shape would
        catch one of its vertices and stretch it out into what looks like a new
        line, instead of moving the whole shape.
        """
        best = NODE_RADIUS
        found = (-1, -1)
        for i in sorted(self._selected_indices):
            if i >= len(self._paths):
                continue
            nodes = self._editableNodes(self._paths[i])
            for j in self._handleIndices(self._paths[i]):
                d = PathShapes.dist(position, nodes[j])
                if d < best:
                    best = d
                    found = (i, j)
        return found

    def _pathAt(self, position: Point) -> int:
        """Index of the topmost path under the cursor, or -1.

        Outlines are tested first so a small shape sitting inside a larger one
        stays clickable; then the interior of every closed shape counts as a hit,
        filled or not, so a circle or rectangle can be grabbed from anywhere
        inside it rather than only on its thin outline.
        """
        for i in range(len(self._paths) - 1, -1, -1):
            path = self._paths[i]
            tolerance = max(path["line_width"], 1.2)
            if PathShapes.polyline_distance(position, path["points"], path["closed"]) <= tolerance:
                return i
        for i in range(len(self._paths) - 1, -1, -1):
            path = self._paths[i]
            if path["closed"] and PathShapes.point_in_polygon(position, path["points"]):
                return i
        return -1

    # ------------------------------------------------------------------
    # Undo history (Ctrl+Z / Cmd+Z, routed here from Cura's Undo action)
    # ------------------------------------------------------------------

    _SNAPSHOT_KEYS = ("shape", "points", "control", "pieces", "closed", "fill",
                      "fill_segments", "extruder", "layers", "speed", "flow",
                      "line_width")

    def _snapshot(self) -> List[dict]:
        """Plain-data copy of every path; scene nodes are left out and rebuilt
        when the snapshot is restored."""
        return [copy.deepcopy({key: path[key] for key in self._SNAPSHOT_KEYS if key in path})
                for path in self._paths]

    def _pushUndo(self):
        self._undo_stack.append(self._snapshot())
        if len(self._undo_stack) > UNDO_DEPTH:
            self._undo_stack.pop(0)

    def undoLast(self):
        """Restore the drawing to the state before the last change."""
        if not self._undo_stack:
            return
        state = self._undo_stack.pop()
        self._cancelCurrent()
        self._clearFillHover()
        self._clearSegmentSelection()
        for path in self._paths:
            for node in (path.get("node"), path.get("shade_node")):
                if node is not None:
                    node.setParent(None)
                    self._controller.getScene().sceneChanged.emit(node)
        self._paths = []
        for entry in state:
            path = dict(entry)
            path["node"] = None
            path["shade_node"] = None
            self._paths.append(path)
        self._selected_index = -1
        self._selected_indices = set()
        for index in range(len(self._paths)):
            self._rebuildPathNode(index)
        self._rebuildSnapPoints()
        self._rebuildWellOverlay()
        self._emitChanged()

    def getCanUndo(self) -> bool:
        return bool(self._undo_stack)

    # ------------------------------------------------------------------

    def _shiftHeld(self) -> bool:
        try:
            from PyQt6.QtWidgets import QApplication
            return bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        except Exception:
            return False

    def _beginSelectDrag(self, position: Optional[Point]):
        if position is None:
            self.setSelectedIndex(-1)
            return

        # A node of an already-selected shape reshapes it; anything else picks.
        path_index, node_index = self._nodeAt(position)
        if path_index >= 0:
            # Reshaping is not a segment operation. It also regenerates the
            # outline — an arc re-tessellates to a different set of vertices —
            # so a held segment index would end up pointing at unrelated
            # geometry: a stray highlighted streak across the shape and a gap
            # cut out of it somewhere else entirely.
            self._clearSegmentSelection()
            self._drag_mode = "node"
            self._drag_path = path_index
            self._drag_node = node_index
            self._drag_last = position
            self._drag_pushed = False
            return

        hit = self._pathAt(position)
        if hit < 0:
            if not self._shiftHeld():
                self._clearSegmentSelection()
                self.setSelectedIndex(-1)
            return

        # A fresh pick replaces any single-segment selection.
        if self._selected_segment is not None and self._selected_segment[0] != hit:
            self._clearSegmentSelection()

        if self._shiftHeld():
            self._toggleSelection(hit)
            if hit not in self._selected_indices:
                return  # shift-clicked out of the selection: nothing to drag
        elif hit not in self._selected_indices:
            self.setSelectedIndex(hit)

        # Drag the whole selection together.
        self._drag_mode = "path"
        self._drag_path = hit
        self._drag_last = position
        self._drag_pushed = False

    def _updateSelectDrag(self, position: Optional[Point]):
        if position is None or self._drag_last is None:
            return
        if not (0 <= self._drag_path < len(self._paths)):
            self._endSelectDrag()
            return
        if not self._drag_pushed:
            # Snapshot once, on the first real movement, so the whole drag is a
            # single undo step.
            self._pushUndo()
            self._drag_pushed = True
        path = self._paths[self._drag_path]

        if self._drag_mode == "node":
            if path["shape"] == "composite":
                self._moveCompositeHandle(path, self._drag_node, position)
                self._recomputeFill(path)
                self._rebuildPathNode(self._drag_path)
            else:
                nodes = self._editableNodes(path)
                if 0 <= self._drag_node < len(nodes):
                    if path["shape"] == "arc":
                        self._moveArcControl(nodes, self._drag_node, position)
                    else:
                        nodes[self._drag_node] = position
                    if path["shape"] == "line":
                        path["control"] = list(path["points"])
                    elif path["shape"] not in FREEHAND_SHAPES:
                        # Parametric: the handle is a control point, so rebuild
                        # the outline from it rather than displacing one vertex.
                        self._regeneratePath(path)
                    self._recomputeFill(path)
                    self._rebuildPathNode(self._drag_path)
        elif self._drag_mode == "path":
            dx = position[0] - self._drag_last[0]
            dz = position[1] - self._drag_last[1]
            if abs(dx) < 1e-9 and abs(dz) < 1e-9:
                return
            # Move every selected shape by the same delta.
            targets = self._selected_indices or {self._drag_path}
            for index in sorted(targets):
                if index >= len(self._paths):
                    continue
                target = self._paths[index]
                target["points"] = [(x + dx, z + dz) for x, z in target["points"]]
                target["control"] = [(x + dx, z + dz) for x, z in target.get("control", [])]
                # A composite is regenerated from its pieces, so they have to
                # travel too or the next rebuild would snap it back.
                for piece in target.get("pieces", []):
                    piece["control"] = [(x + dx, z + dz) for x, z in piece["control"]]
                target["fill_segments"] = [((a[0] + dx, a[1] + dz), (b[0] + dx, b[1] + dz))
                                           for a, b in target["fill_segments"]]
                self._rebuildPathNode(index)

        self._drag_last = position
        self._rebuildNodeMarkers()
        self._rebuildSegmentHighlight()  # the highlight has to travel with the shape
        self._updateNodeHover(position)  # and so does the ring under the cursor

    def _endSelectDrag(self):
        was_node_drag = self._drag_mode == "node"
        self._drag_mode = "none"
        self._drag_path = -1
        self._drag_node = -1
        self._drag_last = None
        self._press_screen = None
        self._press_moved = False
        if was_node_drag:
            # Dropping a node onto another path's endpoint joins the two.
            self._tryMergePaths()
        self._rebuildSnapPoints()
        self._rebuildWellOverlay()
        self._emitChanged()

    # ------------------------------------------------------------------
    # Segment editing: double-click a segment, press Delete to remove it
    # ------------------------------------------------------------------

    def _outlineOf(self, path: dict) -> List[Point]:
        """A path's outline as a run of points, with a closed loop's first point
        repeated at the end so every segment has an index."""
        outline = list(path["points"])
        if path["closed"] and outline:
            outline = outline + [outline[0]]
        return outline

    def _compositePieceSpans(self, path: dict) -> List[Optional[Tuple[int, int]]]:
        """The (first, last) outline indices each composite piece covers.

        Pieces share their junction points, so each one after the first starts
        on the index its predecessor ended on.
        """
        spans: List[Optional[Tuple[int, int]]] = []
        cursor = 0
        for piece in path["pieces"]:
            piece_points = self._pointsFor(piece["shape"], piece["control"])
            if len(piece_points) < 2:
                spans.append(None)
                continue
            spans.append((cursor, cursor + len(piece_points) - 1))
            cursor += len(piece_points) - 1
        return spans

    def _eraseTargetAt(self, position: Optional[Point]):
        """What a click at `position` would rub out, as (path, first, last)
        outline indices.

        The unit is one thing the user drew: a piece of a joined chain, a single
        segment of a hand-drawn polyline, or a whole arc / curve / circle /
        rectangle, since each of those is one stroke with no smaller part that
        would still mean anything.
        """
        found = self._segmentAt(position) if position is not None else None
        if found is None:
            return None
        index, k = found
        path = self._paths[index]
        if path["shape"] == "composite":
            for span in self._compositePieceSpans(path):
                if span is not None and span[0] <= k < span[1]:
                    return (index, span[0], span[1])
            return None
        if path["shape"] in FREEHAND_SHAPES:
            return (index, k, k + 1)
        return (index, 0, max(1, len(self._outlineOf(path)) - 1))

    def _isDoubleClick(self, position: Optional[Point]) -> bool:
        now = time.monotonic()
        quick = (now - self._last_click_time) < DOUBLE_CLICK_SECONDS
        near = (position is not None and self._last_click_pos is not None
                and PathShapes.dist(position, self._last_click_pos) < DOUBLE_CLICK_DISTANCE)
        self._last_click_time = now
        self._last_click_pos = position
        return bool(quick and near)

    def _segmentAt(self, position: Point):
        """(path index, segment index) of the segment under the cursor."""
        found = None
        best = float("inf")
        for i, path in enumerate(self._paths):
            points = path["points"]
            count = len(points)
            if count < 2:
                continue
            span = count if (path["closed"] and count > 2) else count - 1
            tolerance = max(path["line_width"], 1.2)
            for k in range(span):
                d = PathShapes.point_segment_distance(position, points[k], points[(k + 1) % count])
                if d <= tolerance and d < best:
                    best = d
                    found = (i, k)
        return found

    def _setSelectedSegment(self, found) -> bool:
        """Point the highlight at an outline span, or nowhere. Returns whether
        anything changed."""
        if found == self._selected_segment:
            return False
        previous = self._selected_segment
        self._selected_segment = found
        # Both the old and the new host path have to be redrawn: one closes the
        # gap the highlight left, the other opens one.
        for index in {previous[0] if previous else -1, found[0] if found else -1}:
            if 0 <= index < len(self._paths):
                self._rebuildPathNode(index)
        self._rebuildSegmentHighlight()
        return True

    def _selectSegmentAt(self, position: Optional[Point]):
        found = self._eraseTargetAt(position)
        self._setSelectedSegment(found)
        if found is not None:
            self.setSelectedIndex(found[0])
        self._emitChanged()

    def _updateEraseHover(self, position: Optional[Point]):
        """Show what the next click in Erase mode would rub out."""
        if self._setSelectedSegment(self._eraseTargetAt(position)):
            self._emitChanged()

    def _clearSegmentSelection(self):
        self._setSelectedSegment(None)

    def _outlineWithoutHighlight(self, index: int, outline: List[Point]) -> List[List[Point]]:
        """The outline split so the highlighted segment is left out of it.

        The path itself stops either side of the selected segment and
        _rebuildSegmentHighlight draws that stretch in the highlight colour, so
        the line simply changes colour along one segment. Nothing is laid over
        the top, which is what made the old highlight read as a separate block.
        """
        if self._selected_segment is None or self._selected_segment[0] != index:
            return [outline]
        _, first, last = self._selected_segment
        first = max(0, min(first, len(outline) - 1))
        last = max(0, min(last, len(outline) - 1))
        if last <= first:
            return [outline]
        return [piece for piece in (outline[:first + 1], outline[last:]) if len(piece) >= 2]

    def _rebuildSegmentHighlight(self):
        """Draw the selected segment in the highlight colour.

        Same width and same place as the stretch of path it replaces (see
        _outlineWithoutHighlight), so it reads as that part of the line being
        highlighted rather than as something new drawn on top of it.
        """
        node = self._ensureOverlayNode("_segment_node", False)
        mesh = None
        if self._selected_segment is not None:
            i, first, last = self._selected_segment
            if i < len(self._paths):
                outline = self._outlineOf(self._paths[i])
                if 0 <= first < last < len(outline):
                    mesh = build_ribbon_mesh([outline[first:last + 1]],
                                             self._paths[i]["line_width"],
                                             PATH_RENDER_HEIGHT + 0.01)
        node.setMeshData(mesh)
        node.setColor([0.95, 0.35, 0.25, 1.0])
        self._controller.getScene().sceneChanged.emit(node)

    def _compositeRemnants(self, path: dict, span: Tuple[int, int]) -> Optional[List[List[dict]]]:
        """The piece lists left when one piece of a composite is rubbed out.

        Returns None when the span is not exactly one piece, so the caller can
        fall back to cutting the raw outline. Working in pieces matters: it is
        what lets the arcs and curves either side survive as arcs and curves.
        """
        spans = self._compositePieceSpans(path)
        for position, piece_span in enumerate(spans):
            if piece_span != span:
                continue
            pieces = [dict(piece, control = list(piece["control"]))
                      for piece in path["pieces"]]
            if path["closed"]:
                # A loop stays one chain: rotate so the gap falls at the ends.
                return [pieces[position + 1:] + pieces[:position]]
            return [group for group in (pieces[:position], pieces[position + 1:]) if group]
        return None

    def deleteSelectedSegment(self):
        """Rub out the highlighted span: a closed shape opens up, an open path
        splits, and a joined chain loses one of the shapes it was built from."""
        if self._selected_segment is None:
            return
        index, first, last = self._selected_segment
        if index >= len(self._paths):
            self._clearSegmentSelection()
            return
        self._pushUndo()

        path = self._paths[index]
        outline = self._outlineOf(path)
        first = max(0, min(first, len(outline) - 1))
        last = max(0, min(last, len(outline) - 1))

        remnant_pieces = None
        remnant_points: List[List[Point]] = []
        if path["shape"] == "composite":
            remnant_pieces = self._compositeRemnants(path, (first, last))
        if remnant_pieces is None:
            if path["closed"]:
                # Walk the loop from the far end of the gap round to its start.
                count = len(path["points"])
                remaining = outline[last:count] + outline[:first + 1]
                if len(remaining) >= 2:
                    remnant_points.append(remaining)
            else:
                for run in (outline[:first + 1], outline[last:]):
                    if len(run) >= 2:
                        remnant_points.append(run)

        for node in (path.get("node"), path.get("shade_node")):
            if node is not None:
                node.setParent(None)
                self._controller.getScene().sceneChanged.emit(node)
        self._paths.pop(index)

        def blank_copy():
            new_path = dict(path)
            new_path["closed"] = False
            new_path["fill"] = False
            new_path["fill_segments"] = []
            new_path["node"] = None
            new_path["shade_node"] = None
            return new_path

        offset = 0
        for pieces in (remnant_pieces or []):
            new_path = blank_copy()
            new_path.pop("pieces", None)
            self._applyPieces(new_path, pieces)
            if len(new_path["points"]) >= 2:
                self._paths.insert(index + offset, new_path)
                offset += 1
        for piece in remnant_points:
            new_path = blank_copy()
            new_path["shape"] = "merged"   # no longer a parametric shape
            new_path.pop("pieces", None)   # nor a composite of them
            new_path["points"] = piece
            new_path["control"] = list(piece)
            self._paths.insert(index + offset, new_path)
            offset += 1

        self._selected_segment = None
        self._selected_index = -1
        self._selected_indices = set()
        for i in range(len(self._paths)):
            self._rebuildPathNode(i)
        self._rebuildSegmentHighlight()
        self._rebuildSnapPoints()
        self._rebuildWellOverlay()
        self._emitChanged()

    def _updateFillHover(self, position: Optional[Point]):
        """Light shading preview over the closed shape under the cursor (fill mode)."""
        idx = -1
        if position is not None:
            for i in range(len(self._paths) - 1, -1, -1):
                path = self._paths[i]
                if path["closed"] and PathShapes.point_in_polygon(position, path["points"]):
                    idx = i
                    break
        if idx == self._fill_hover_index:
            return
        self._fill_hover_index = idx
        node = self._ensureOverlayNode("_hover_shade_node", True)
        if idx < 0:
            node.setMeshData(None)
        else:
            path = self._paths[idx]
            node.setMeshData(build_triangle_mesh(
                PathShapes.triangulate_polygon(path["points"]), SHADE_RENDER_HEIGHT + 0.03))
            color = self._extruderColorRgba(path["extruder"])
            node.setColor(color[:3] + [0.13])
        self._controller.getScene().sceneChanged.emit(node)

    def _clearFillHover(self):
        self._fill_hover_index = -1
        if self._hover_shade_node is not None:
            self._hover_shade_node.setMeshData(None)
            self._controller.getScene().sceneChanged.emit(self._hover_shade_node)

    def _handleNodes(self) -> List[Point]:
        """Round handles shown on the plate: open-path endpoints while drawing,
        every editable node of every path in Select mode."""
        points: List[Point] = []
        if self._shape_type == "select":
            # Only the selected shapes show grab handles, so what is visible is
            # exactly what can be dragged.
            for index in sorted(self._selected_indices):
                if index < len(self._paths):
                    points.extend(self._handlePoints(self._paths[index]))
        else:
            for path in self._paths:
                if path["closed"]:
                    continue
                points.append(path["points"][0])
                points.append(path["points"][-1])
        return points

    def _rebuildNodeMarkers(self):
        """Round handles on the nodes that can be connected to (drawing) or
        dragged (Select mode)."""
        node = self._ensureOverlayNode("_nodes_node", False)
        points = self._handleNodes()
        node.setMeshData(build_disc_mesh(points, NODE_RADIUS, NODE_RENDER_HEIGHT) if points else None)
        node.setColor([0.16, 0.36, 0.62, 1.0])
        self._controller.getScene().sceneChanged.emit(node)

    def _updateNodeHover(self, position: Optional[Point]):
        """Highlight ring on the node under the cursor, so it is obvious that
        clicking will snap to / grab that node."""
        target = None
        if position is not None:
            # In Select mode the ring means "this will be grabbed", so it must
            # light up over exactly the grab radius; while drawing it means
            # "a click will snap here", which is the object-snap radius.
            best = NODE_RADIUS if self._shape_type == "select" else OSNAP_THRESHOLD
            for candidate in self._handleNodes():
                d = PathShapes.dist(position, candidate)
                if d < best:
                    best = d
                    target = candidate
        if target is not None and self._hover_node_point is not None \
                and PathShapes.dist(target, self._hover_node_point) < 1e-9:
            return
        if target is None and self._hover_node_point is None:
            return
        self._hover_node_point = target
        node = self._ensureOverlayNode("_node_hover_node", True)
        if target is None:
            node.setMeshData(None)
        else:
            # A halo that hugs the handle: a wider ring would imply the node can
            # be grabbed from further out than it actually can.
            node.setMeshData(build_ring_mesh(target, NODE_RADIUS * 1.6, NODE_RADIUS * 0.45,
                                             NODE_RENDER_HEIGHT + 0.02))
            node.setColor([0.99, 0.68, 0.14, 0.95])
        self._controller.getScene().sceneChanged.emit(node)

    def _tryMergePaths(self):
        """Merge open freehand paths that share an endpoint into one path; a
        chain whose two ends meet becomes a closed loop (which can then be
        filled).

        A chain of plain lines stays plain vertices. As soon as it contains a
        real shape — an arc, a curve — the result is a COMPOSITE: one path that
        holds each original shape as a piece with its own control points, so an
        arc in the middle of a chain still shows its three handles and still
        reshapes as an arc. Only the outline is concatenated.
        """
        merged_any = False
        changed = True
        while changed:
            changed = False
            for i, path_a in enumerate(self._paths):
                if path_a["closed"]:
                    continue
                pts_a = path_a["points"]
                # A path whose own ends meet becomes a closed loop.
                if (len(pts_a) > 2 and PathShapes.dist(pts_a[0], pts_a[-1]) < MERGE_EPSILON
                        and self._closeChain(path_a)):
                    changed = True
                    merged_any = True
                    break
                for j, path_b in enumerate(self._paths):
                    if i == j or path_b["closed"] or path_a["extruder"] != path_b["extruder"]:
                        continue
                    pts_b = path_b["points"]
                    pieces_a = self._pathAsPieces(path_a)
                    pieces_b = self._pathAsPieces(path_b)
                    joined = None
                    if PathShapes.dist(pts_a[-1], pts_b[0]) < MERGE_EPSILON:
                        joined = pieces_a + pieces_b
                    elif PathShapes.dist(pts_a[-1], pts_b[-1]) < MERGE_EPSILON:
                        joined = pieces_a + self._reversedPieces(pieces_b)
                    elif PathShapes.dist(pts_a[0], pts_b[-1]) < MERGE_EPSILON:
                        joined = pieces_b + pieces_a
                    elif PathShapes.dist(pts_a[0], pts_b[0]) < MERGE_EPSILON:
                        joined = self._reversedPieces(pieces_b) + pieces_a
                    if joined is None:
                        continue
                    self._applyPieces(path_a, joined)
                    for scene_node in (path_b["node"], path_b.get("shade_node")):
                        if scene_node is not None:
                            scene_node.setParent(None)
                            self._controller.getScene().sceneChanged.emit(scene_node)
                    self._paths.pop(j)
                    changed = True
                    merged_any = True
                    break
                if changed:
                    break
        if merged_any:
            # Indices shift when paths are joined, so drop the selection.
            self._selected_index = -1
            self._selected_indices = set()
            for k in range(len(self._paths)):
                self._rebuildPathNode(k)
            self._refreshColors()

    # ------------------------------------------------------------------
    # Scene nodes
    # ------------------------------------------------------------------

    def _ensureGroupNode(self) -> SceneNode:
        root = self._controller.getScene().getRoot()
        if self._group_node is None or self._group_node.getParent() is None:
            self._group_node = SceneNode(root)
            self._group_node.setName("PathDesignerPaths")
            self._group_node.setSelectable(False)
        return self._group_node

    def _ensurePreviewNode(self) -> PathNode:
        if self._preview_node is None or self._preview_node.getParent() is None:
            self._preview_node = PathNode(self._ensureGroupNode())
            self._preview_node.setName("PathDesignerPreview")
            self._preview_node.setTransparent(True)
        return self._preview_node

    # ------------------------------------------------------------------
    # Settings helpers
    # ------------------------------------------------------------------

    def _extruderStack(self, index: int):
        stack = Application.getInstance().getGlobalContainerStack()
        if stack is None:
            return None
        try:
            return stack.extruderList[index]
        except (IndexError, AttributeError):
            return None

    def _extruderProperty(self, index: int, key: str, fallback: float) -> float:
        extruder = self._extruderStack(index)
        if extruder is None:
            return fallback
        try:
            value = extruder.getProperty(key, "value")
            return float(value) if value is not None else fallback
        except Exception:
            return fallback

    def _lineWidth(self, extruder: int) -> float:
        return self._extruderProperty(extruder, "line_width", 0.4)

    def _layerHeights(self):
        stack = Application.getInstance().getGlobalContainerStack()
        lh = lh0 = 0.2
        if stack is not None:
            try:
                lh = float(stack.getProperty("layer_height", "value"))
                lh0 = float(stack.getProperty("layer_height_0", "value"))
            except Exception:
                pass
        return lh, lh0

    def _extruderColorRgba(self, index: int) -> List[float]:
        color_hex = None
        try:
            from cura.CuraApplication import CuraApplication
            model = CuraApplication.getInstance().getExtrudersModel()
            item = model.getItem(index)
            color_hex = item.get("color") if item else None
        except Exception:
            pass
        if not color_hex or not str(color_hex).startswith("#"):
            color_hex = FALLBACK_COLORS[index % len(FALLBACK_COLORS)]
        color_hex = str(color_hex).lstrip("#")
        try:
            r = int(color_hex[0:2], 16) / 255.0
            g = int(color_hex[2:4], 16) / 255.0
            b = int(color_hex[4:6], 16) / 255.0
        except (ValueError, IndexError):
            r, g, b = 0.3, 0.55, 0.85
        return [r, g, b, 1.0]

    def _rgbaToHex(self, rgba: List[float]) -> str:
        return "#{0:02x}{1:02x}{2:02x}".format(
            int(rgba[0] * 255), int(rgba[1] * 255), int(rgba[2] * 255))

    def _emitChanged(self):
        self.propertyChanged.emit()

    def _selectedPath(self) -> Optional[dict]:
        if 0 <= self._selected_index < len(self._paths):
            return self._paths[self._selected_index]
        return None

    # ------------------------------------------------------------------
    # Exposed properties (read by QML via UM.Controller.properties)
    # ------------------------------------------------------------------

    def getShapeType(self) -> str:
        return self._shape_type

    def setShapeType(self, value):
        value = str(value)
        if (value not in SHAPE_NAMES
                and value not in ("fill", "select", "erase")) \
                or value == self._shape_type:
            return
        self._cancelCurrent()
        self._clearFillHover()
        self._clearSegmentSelection()
        self._shape_type = value
        if value != "select":
            self.setSelectedIndex(-1)
        # Select mode exposes every node as a handle, drawing modes only the
        # connectable endpoints.
        self._rebuildNodeMarkers()
        self._updateNodeHover(None)
        self._emitChanged()

    def getExtruder(self) -> int:
        path = self._selectedPath()
        return path["extruder"] if path else self._extruder

    def setExtruder(self, value):
        value = max(0, min(1, int(value)))
        if self._selected_indices:
            # Applies to the whole selection, so several shapes can be
            # reassigned in one go.
            for index in sorted(self._selected_indices):
                if index >= len(self._paths):
                    continue
                path = self._paths[index]
                path["extruder"] = value
                path["line_width"] = self._lineWidth(value)
                self._recomputeFill(path)
                self._rebuildPathNode(index)
        else:
            self._extruder = value
            self._updatePreview()
        self._emitChanged()

    def getPathLayers(self) -> int:
        path = self._selectedPath()
        return path["layers"] if path else self._path_layers

    def setPathLayers(self, value):
        value = max(1, int(float(value)))
        if self._selected_indices:
            for index in sorted(self._selected_indices):
                if index < len(self._paths):
                    self._paths[index]["layers"] = value
        else:
            self._path_layers = value
        self._emitChanged()

    def getSpeedOverride(self) -> float:
        path = self._selectedPath()
        return path["speed"] if path else self._speed_override

    def setSpeedOverride(self, value):
        value = max(0.0, float(value))
        path = self._selectedPath()
        if path:
            path["speed"] = value
        else:
            self._speed_override = value
        self._emitChanged()

    # NOT WIRED TO ANYTHING. "FlowPercent" is absent from setExposedProperties
    # and no QML references it, so neither of these is reachable and every path
    # carries flow = 100. GcodeGenerator.e_per_mm deliberately ignores the value
    # and prints at the profile's outer-wall flow.
    #
    # Before exposing this, read the contract note in GcodeGenerator.e_per_mm:
    # a per-path flow has to REPLACE the profile flow with 0 as the "use the
    # profile" sentinel, the way speed does, and projects already on disk store
    # flow = 100 meaning "unset", which needs migrating rather than believing.
    def getFlowPercent(self) -> float:
        path = self._selectedPath()
        return path["flow"] if path else self._flow_percent

    def setFlowPercent(self, value):
        value = max(1.0, float(value))
        path = self._selectedPath()
        if path:
            path["flow"] = value
        else:
            self._flow_percent = value
        self._emitChanged()

    def getFillEnabled(self) -> bool:
        path = self._selectedPath()
        return path["fill"] if path else self._fill_enabled

    def setFillEnabled(self, value):
        value = bool(value)
        path = self._selectedPath()
        if path:
            if path["closed"]:
                path["fill"] = value
                self._recomputeFill(path)
                self._rebuildPathNode(self._selected_index)
        else:
            self._fill_enabled = value
        self._emitChanged()

    def getLineWidthText(self) -> str:
        """Read-only bead width from the active dispense tip profile, shown in
        the panel and used as the snap grid step."""
        path = self._selectedPath()
        extruder = path["extruder"] if path else self._extruder
        return "{0:g} mm".format(round(self._lineWidth(extruder), 3))

    def getSnapEnabled(self) -> bool:
        return self._snap_enabled

    def setSnapEnabled(self, value):
        self._snap_enabled = bool(value)
        self._emitChanged()

    def getSelectedIndex(self) -> int:
        return self._selected_index

    def setSelectedIndex(self, value):
        value = int(value)
        if value < -1 or value >= len(self._paths):
            value = -1
        if value == self._selected_index and self._selected_indices == ({value} if value >= 0 else set()):
            return
        self._selected_index = value
        self._selected_indices = {value} if value >= 0 else set()
        self._refreshColors()
        self._rebuildNodeMarkers()
        self._emitChanged()

    def _toggleSelection(self, index: int):
        """Shift-click: add the shape to the selection, or take it back out."""
        if index in self._selected_indices:
            self._selected_indices.discard(index)
            if self._selected_index == index:
                self._selected_index = max(self._selected_indices) if self._selected_indices else -1
        else:
            self._selected_indices.add(index)
            self._selected_index = index
        self._refreshColors()
        self._rebuildNodeMarkers()
        self._emitChanged()

    def getPointCount(self) -> int:
        return len(self._current_points)

    def getExtruderCount(self) -> int:
        stack = Application.getInstance().getGlobalContainerStack()
        if stack is None:
            return 1
        try:
            return len(stack.extruderList)
        except Exception:
            return 1

    def getExtruderColors(self) -> List[str]:
        return [self._rgbaToHex(self._extruderColorRgba(i)) for i in range(2)]

    def getPathsInfo(self) -> List[dict]:
        info = []
        for i, path in enumerate(self._paths):
            label = "{0} · E{1} · {2} layer{3}".format(
                SHAPE_NAMES.get(path.get("shape"), "Path"), path.get("extruder", 0) + 1,
                path.get("layers", 1), "" if path.get("layers", 1) == 1 else "s")
            if path.get("fill"):
                label += " · fill"
            info.append({
                "index": i,
                "label": label,
                "color": self._rgbaToHex(self._extruderColorRgba(path["extruder"])),
                "selected": i in self._selected_indices,
            })
        return info

    def getStatusText(self) -> str:
        if not self._panel_seen:
            self._panel_seen = True
            Logger.log("i", "PathDesigner: tool panel is reading properties (panel loaded)")
        n = len(self._current_points)
        shape = self._shape_type
        if shape in ("line", "spline"):
            if n == 0:
                return "Click on the build plate to start a path."
            if n < 3:
                return "Click to add points. Enter, Esc, or a click off the plate finishes."
            return "Click to add points; click the first point to close. Enter/Esc finishes."
        if shape == "arc":
            if n < 2:
                return ["Click the arc start point.", "Click the arc end point."][n]
            if self._arc_bias_label == "tangent":
                return "Click to set the arc bulge. Locked tangent to the path it meets."
            if self._arc_bias_label:
                return "Click to set the arc bulge. Locked to a {0} arc.".format(self._arc_bias_label)
            return "Click to set the arc bulge; it locks onto 90°/180°/270° arcs and onto a tangent join."
        if shape == "circle":
            return "Click the circle centre." if n == 0 else "Click to set the radius."
        if shape == "rect":
            return "Click the first corner." if n == 0 else "Click the opposite corner."
        if shape == "erase":
            if self._selected_segment is not None:
                return "Click to rub out the highlighted part."
            return "Click a shape to rub it out. Hover first: what will go is highlighted."
        if shape == "fill":
            return "Click inside a closed shape to fill it; click again to unfill."
        if shape == "select":
            if self._selected_segment is not None:
                return "Segment selected. Press Delete to remove just this segment."
            count = len(self._selected_indices)
            if count > 1:
                return "{0} shapes selected. Drag to move them together, or press Delete to remove them.".format(count)
            if count == 1:
                return "Drag to move, drag a round node to reshape, double-click a segment to select just it, Delete to remove."
            return "Click a shape to select it. Shift+click to select several, double-click a segment to select just it."
        return ""

    # ------------------------------------------------------------------
    # Actions (invoked from QML via UM.Controller.triggerAction)
    # ------------------------------------------------------------------

    def finishPath(self):
        shape = self._shape_type
        n = len(self._current_points)
        if shape in ("line", "spline") and n >= 2:
            self._finishCurrent(closed = False)
        elif n > 0:
            self._cancelCurrent()
        self._emitChanged()

    def cancelPath(self):
        self._cancelCurrent()
        self._emitChanged()

    def undoPoint(self):
        if self._current_points:
            self._current_points.pop()
            self._updatePreview()
            self._emitChanged()

    def toggleSelection(self, data):
        """Shift-click from the path list: add/remove one shape."""
        index = int(data)
        if 0 <= index < len(self._paths):
            self._toggleSelection(index)

    def selectAllPaths(self):
        """Select every drawn shape. Wired to Cura's own Ctrl+A."""
        if not self._paths:
            return
        if self._shape_type != "select":
            # Selecting is only meaningful in Select mode, so switch to it
            # rather than selecting invisibly behind a drawing tool.
            self.setShapeType("select")
        self._selected_indices = set(range(len(self._paths)))
        self._selected_index = len(self._paths) - 1
        self._refreshColors()
        self._rebuildNodeMarkers()
        self._emitChanged()

    # ------------------------------------------------------------------
    # Clipboard, on Cura's own Ctrl+C / Ctrl+V
    # ------------------------------------------------------------------

    def getCanCopy(self) -> bool:
        return bool(self._selected_indices)

    def getCanPaste(self) -> bool:
        return bool(self._clipboard)

    def copySelection(self):
        """Take a copy of every selected shape."""
        if not self._selected_indices:
            return
        self._clipboard = [
            copy.deepcopy({key: self._paths[index][key]
                           for key in self._SNAPSHOT_KEYS if key in self._paths[index]})
            for index in sorted(self._selected_indices) if index < len(self._paths)]
        self._emitChanged()

    def cutSelection(self):
        """Take the selection and remove it, on Cura's Ctrl+X.

        deleteSelected pushes the undo step, so a cut is one Ctrl+Z away from
        being put back.
        """
        if not self._selected_indices:
            return
        self.copySelection()
        self.deleteSelected()

    def pasteClipboard(self):
        """Drop the copied shapes back on the plate, offset so they are visible
        as separate shapes, and leave them selected so they can be dragged into
        place straight away."""
        if not self._clipboard:
            return
        self._pushUndo()
        self._clearSegmentSelection()
        offset = self._pasteOffset()

        def shifted(point: Point) -> Point:
            return (point[0] + offset[0], point[1] + offset[1])

        first = len(self._paths)
        for entry in self._clipboard:
            path = copy.deepcopy(entry)
            path["points"] = [shifted(point) for point in path["points"]]
            path["control"] = [shifted(point) for point in path.get("control", [])]
            for piece in path.get("pieces", []):
                piece["control"] = [shifted(point) for point in piece["control"]]
            path["fill_segments"] = [(shifted(a), shifted(b))
                                     for a, b in path.get("fill_segments", [])]
            path["node"] = None
            path["shade_node"] = None
            self._paths.append(path)
            self._rebuildPathNode(len(self._paths) - 1)

        # A paste never joins itself onto what it was copied from, so the offset
        # is deliberately larger than the merge tolerance.
        self._selected_indices = set(range(first, len(self._paths)))
        self._selected_index = len(self._paths) - 1
        if self._shape_type != "select":
            self.setShapeType("select")
        self._refreshColors()
        self._rebuildNodeMarkers()
        self._rebuildSnapPoints()
        self._rebuildWellOverlay()
        self._emitChanged()

    def _pasteOffset(self) -> Point:
        """Where a paste lands: one step down-right, stepped again each time the
        same clipboard is pasted, so repeats stack instead of hiding."""
        step = max(PASTE_OFFSET, self._lineWidth(self._extruder) * 2.0)
        existing = 0
        for path in self._paths:
            if any(self._sameShape(path, entry) for entry in self._clipboard):
                existing += 1
        return (step * (existing + 1), step * (existing + 1))

    def _sameShape(self, path: dict, entry: dict) -> bool:
        """Whether a path looks like a copy of this clipboard entry, judged on
        shape and size rather than position."""
        if path["shape"] != entry["shape"] or len(path["points"]) != len(entry["points"]):
            return False
        return abs(PathShapes.polyline_length(path["points"])
                   - PathShapes.polyline_length(entry["points"])) < 1e-6

    def deleteSelected(self):
        """Delete every selected shape (shift-click builds the selection)."""
        if not self._selected_indices:
            return
        self._pushUndo()
        self._clearSegmentSelection()
        for index in sorted(self._selected_indices, reverse = True):
            if index >= len(self._paths):
                continue
            path = self._paths[index]
            for node in (path["node"], path.get("shade_node")):
                if node is not None:
                    node.setParent(None)
                    self._controller.getScene().sceneChanged.emit(node)
            self._paths.pop(index)
        self._selected_index = -1
        self._selected_indices = set()
        self._clearFillHover()
        self._refreshColors()
        self._rebuildSnapPoints()
        self._rebuildWellOverlay()
        self._emitChanged()

    def clearAll(self):
        if self._paths:
            self._pushUndo()
        self._clearSegmentSelection()
        self._cancelCurrent()
        for path in self._paths:
            for node in (path["node"], path.get("shade_node")):
                if node is not None:
                    node.setParent(None)
                    self._controller.getScene().sceneChanged.emit(node)
        self._paths = []
        self._selected_index = -1
        self._selected_indices = set()
        # Anything already saved to the plate stays there as an ordinary model,
        # but it is no longer this drawing's to replace: the next save adds
        # rather than updates. Show it first, or forgetting the nodes while the
        # tool is open would strand them invisible with nothing left to restore
        # them.
        self._setSavedMeshesVisible(True)
        # "No longer this drawing's" has to be true in the SCENE, not only in
        # this tool's memory: a save now replaces every mesh carrying a name it
        # is producing, so a mesh still called PrintessDrawing-fill-1 would be
        # claimed and removed by the next save of a new shape #1. Renaming
        # leaves it on the plate as the ordinary model it has become.
        for entry in self._added_nodes:
            node = entry["node"]
            if node.getParent() is None:
                continue
            name = node.getName()
            if name.startswith(DRAWING_TAG):
                node.setName("Drawing" + name[len(DRAWING_TAG):])
                self._controller.getScene().sceneChanged.emit(node)
        self._added_nodes = []
        self._saved_state = None
        # There is no drawing left to be out of step with anything.
        self._hideStaleWarning()
        self._clearFillHover()
        self._rebuildSnapPoints()
        self._rebuildWellOverlay()
        self._emitChanged()

    def topView(self):
        self._setTopView()

    def _setTopView(self):
        """Exact top-down view of the build plate.

        Cura's own top view; rotating away from it is smooth thanks to the
        patched pole guard in CameraTool._rotateCamera (the stock guard also
        rejected drags that move AWAY from the pole, which made the top view
        feel stuck).
        """
        try:
            self._controller.setCameraRotation("y", 90)
        except Exception:
            Logger.logException("w", "PathDesigner: could not set top view")

    def _offerToKeepOrDropOnLeaving(self):
        """Make the same offer as the icon's dialog, by every other way out.

        Esc, switching to another tool, or Cura deactivating this one all leave
        without asking, and leaving with unsaved changes is exactly what looks
        like the drawing has been duplicated: the ribbons stay on screen beside
        the meshes from the last save, because an edited drawing must never
        vanish on exit, and a ribbon is not a Cura object so it cannot be
        selected or deleted.

        A Message rather than the panel's dialog, and not by choice: the dialog
        lives in the tool panel, which Cura destroys the moment the tool
        deactivates, so by the time this runs there is nothing left to host it.
        A Message outlives the tool, which is what this needs.
        """
        if self._saving or not self._sessionHasChanges():
            self._hideLeavingOffer()
            return
        if self._leaving_message is not None:
            return
        message = Message(
            "You left Path Designer with changes that are not on the build "
            "plate yet, so they will not print. Save them, or revert the "
            "drawing to how it was when you opened the tool.",
            title = "Path Designer",
            lifetime = 0,
            message_type = Message.MessageType.WARNING)
        message.addAction("save_plate", "Save to build plate", "",
                          "Put the drawing on the build plate so it prints")
        message.addAction("revert", "Revert changes", "",
                          "Put the drawing back as it was when the tool was opened")
        message.actionTriggered.connect(self._onLeavingOfferAction)
        self._leaving_message = message
        message.show()

    def _hideLeavingOffer(self):
        if self._leaving_message is None:
            return
        message, self._leaving_message = self._leaving_message, None
        try:
            message.hide()
        except Exception:
            Logger.logException("w", "PathDesigner: could not take down the leaving offer")

    def _onLeavingOfferAction(self, message, action_id):
        self._hideLeavingOffer()
        try:
            if action_id == "save_plate":
                self.addToBuildPlate()
            elif action_id == "revert":
                self.discardSession()
                # Settle what is on screen: the tool is not open to do it.
                self._updateDrawingVisibility()
        except Exception:
            Logger.logException("e", "PathDesigner: could not act on the leaving offer")

    def getExitPrompt(self) -> int:
        """Bumped when the panel should ask what to do with unsaved changes."""
        return self._exit_prompt

    def _sessionHasChanges(self) -> bool:
        if self._session_state is None:
            return bool(self._paths)
        return self._plateState() != self._session_state

    def requestExit(self):
        """Leaving by the toolbar icon.

        Closing the tool has never lost work, since the drawing is kept and comes
        back on reopening, but nothing on the plate changes either: what has been
        drawn since the tool was opened is not printed until it is saved. So
        rather than simply closing, offer the two things worth doing, and only
        when there is a difference to do them about. Clicking away from an
        unchanged drawing should just close, not interrogate.
        """
        if self._current_points:
            self.finishPath()
        if not self._sessionHasChanges():
            self.exitTool()
            return
        self._exit_prompt += 1
        self._emitChanged()

    def discardSession(self):
        """Put the drawing back as it was when the tool was opened.

        Undoable in one step like any other change, so a mis-click on Discard is
        recoverable while the tool is still open.
        """
        if self._session_state is None:
            return
        self._pushUndo()
        paths, preset, wells = self._session_state
        self._cancelCurrent()
        self._clearFillHover()
        self._clearSegmentSelection()
        for path in self._paths:
            for node in (path.get("node"), path.get("shade_node")):
                if node is not None:
                    node.setParent(None)
                    self._controller.getScene().sceneChanged.emit(node)
        self._paths = []
        for entry in paths:
            restored = dict(entry)
            restored["node"] = None
            restored["shade_node"] = None
            self._paths.append(restored)
        self._well_preset = preset
        self._selected_wells = set(wells)
        self._selected_index = -1
        self._selected_indices = set()
        for index in range(len(self._paths)):
            self._rebuildPathNode(index)
        self._rebuildSnapPoints()
        self._rebuildWellOverlay()
        # The drawing IS the session start again, so re-anchor rather than trust
        # the two to compare equal: rebuilding a parametric shape re-tessellates
        # it, and points that differ in the last decimal would leave the tool
        # convinced there were still changes to ask about.
        self._session_state = self._plateState()
        self._emitChanged()

    def exitTool(self):
        """Deactivate this tool (invoked by the panel's Exit button)."""
        self._controller.setActiveTool(None)

    def selectAllWells(self):
        preset = WellPlates.PRESETS.get(self._well_preset)
        if preset is None:
            return
        self._selected_wells = set(range(preset["rows"] * preset["cols"]))
        self._rebuildWellOverlay()
        self._emitChanged()

    def clearWellSelection(self):
        self._selected_wells = set()
        self._rebuildWellOverlay()
        self._emitChanged()

    # ------------------------------------------------------------------
    # Save to build plate: the drawing becomes a real sliceable object
    # ------------------------------------------------------------------

    def _addActionBarButtonWhenReady(self):
        """Put a Draw Paths button in the action bar, beside Well Plate Arranger.

        Registered against "saveButton", which is the same slot the Well Plate
        Arranger uses, so the two land side by side. Waits for mainWindowChanged
        because createQmlComponent needs the QML engine, which does not exist
        while plugins are still being constructed.
        """
        try:
            from cura.CuraApplication import CuraApplication
            CuraApplication.getInstance().mainWindowChanged.connect(self._createActionBarButton)
        except Exception:
            Logger.logException("w", "PathDesigner: could not hook the action bar button")

    def _createActionBarButton(self):
        if self._button_view is not None:
            return          # mainWindowChanged can fire more than once
        try:
            from cura.CuraApplication import CuraApplication
            application = CuraApplication.getInstance()
            qml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "PathDesignerButton.qml")
            self._button_view = application.createQmlComponent(qml_path, {})
            if self._button_view is not None:
                application.addAdditionalComponent("saveButton", self._button_view)
        except Exception:
            Logger.logException("w", "PathDesigner: could not create the action bar button")

    def _connectBackendWhenReady(self):
        """Arrange to hear the end of every slice from the moment Cura is up.

        This used to be done only from _onActivate, which was enough while a
        drawing was being made in the same session and wrong for everything
        else. Load a project and press Slice without ever opening Path Designer
        and the hook was never connected at all: the drawn paths were never put
        into the g-code, every shape sliced as the solid built from it, and
        nothing said so, because from the plugin's point of view nothing had
        happened. Carrying the trajectory on the mesh fixed WHERE the path lives;
        this fixes whether anyone ever asks for it.

        Tried immediately, in case the backend is already up, and again when the
        application says it has finished starting, in case it is not. Connecting
        is idempotent, so doing both is free.
        """
        self._connectBackend()
        if self._backend_connected:
            return
        try:
            from cura.CuraApplication import CuraApplication
            application = CuraApplication.getInstance()
            if application is not None:
                application.initializationFinished.connect(self._connectBackend)
        except Exception:
            Logger.logException("w", "PathDesigner: could not arrange to listen for slicing")

    def _connectBackend(self, *_args):
        """Listen for the end of a slice, once."""
        if self._backend_connected:
            return
        try:
            from cura.CuraApplication import CuraApplication
            CuraApplication.getInstance().getBackend().backendStateChange.connect(
                self._onBackendStateChanged)
            self._backend_connected = True
        except Exception:
            Logger.logException("w", "PathDesigner: could not listen for slicing to finish")

    def _onBackendStateChanged(self, state):
        """Swap the slicer's version of every drawn outline for the drawn path.

        Done when the slice FINISHES, which is comfortably before
        PostProcessingPlugin runs: that hangs off writeStarted and reads
        scene.gcode_dict there. So the selected script still runs exactly once,
        over one stream holding both the sliced shapes and the drawn paths, and
        nothing about the scripts has to change.
        """
        try:
            from UM.Backend.Backend import BackendState
            if state != BackendState.Done:
                return
            # Checked on every finished slice, not only when there is something
            # to inject: a drawing made entirely of filled shapes produces no
            # trajectories and can still be out of step with the plate. Caught
            # separately so that a failure to WARN can never cost the merge,
            # which is the part the print depends on.
            try:
                self._warnIfPlateIsStale()
            except Exception:
                Logger.logException("w", "PathDesigner: could not check the build plate against the drawing")

            # Read off the plate, never remembered. This is what makes a drawn
            # path impossible to lose: it is carried by the mesh, so it survives
            # the tool being reset, the plugin being reloaded, and Cura being
            # restarted, and it is placed by the mesh's own transform, so a shape
            # dragged since the last save is traced where it now sits.
            drawn = self._drawnPathsOnPlate()
            if not drawn:
                return
            from cura.CuraApplication import CuraApplication
            application = CuraApplication.getInstance()
            scene = application.getController().getScene()
            gcode_dict = getattr(scene, "gcode_dict", None)
            if not gcode_dict:
                return
            plate = application.getMultiBuildPlateModel().activeBuildPlate
            sliced = gcode_dict.get(plate)
            if not sliced:
                return

            generated = GcodeGenerator.generate(drawn, self._gcodeSettings())
            gcode_dict[plate] = GcodeMerge.merge(sliced, generated)
            setattr(scene, "gcode_dict", gcode_dict)
            Logger.log("i", "PathDesigner: replaced the sliced output of %d drawn path(s)",
                       len(drawn))
        except Exception:
            Logger.logException("e", "PathDesigner: could not put the drawn paths into the g-code")

    def _warnIfPlateIsStale(self):
        """Say so when the slice was made from an out-of-date build plate.

        Everything that reaches the printer is captured at Save to Build Plate:
        the meshes carry the shapes, and each one carries its own trajectory and
        layer count. Drawing another shape, or just
        changing Layers, and then pressing Slice therefore prints the PREVIOUS
        state, silently, with nothing on screen to say the plate and the drawing
        have parted company. A four-layer circle and a three-layer curve came
        out as one layer of the same shape twice this way.

        The comparison is the one that already decides whether the drawing shows
        outside the tool, so the two can never disagree about what "in step"
        means.
        """
        if not self._paths or self._drawingIsOnThePlate():
            self._hideStaleWarning()
            return
        if self._stale_message is not None:
            return  # already up: a re-slice must not stack a second copy

        saved = self._saved_state is not None and any(
            entry["node"].getParent() is not None for entry in self._added_nodes)
        text = ("Your drawing has changed since it was last saved to the build "
                "plate, so this slice is of the older version."
                if saved else
                "Your drawing has not been saved to the build plate, so it is "
                "not part of this slice.")
        message = Message(text,
                          title = "Path Designer",
                          lifetime = 0,  # it must outlive the slice that caused it
                          message_type = Message.MessageType.WARNING)
        message.addAction("update_plate", "Update build plate", "",
                          "Save the current drawing to the build plate and slice it again")
        message.actionTriggered.connect(self._onStaleWarningAction)
        self._stale_message = message
        message.show()

    def _suppressHullShadow(self, node):
        """Keep the hull maths, drop the grey footprint the drawing must not have.

        Cura gives every sliceable node a ConvexHullDecorator, and the hull is
        CONVEX, so on a drawing it bridges the gaps between separate shapes and
        renders as a grey slab. The hull node is parented to the scene ROOT, not
        to the mesh, which is why hiding a saved drawing does not take its shadow
        with it, and why the shadow sits still while the drawing is dragged
        around: it belongs to the mesh, not to what is on screen.

        It has to be an EXACT ConvexHullDecorator, not a subclass, and that is
        the whole trick: SceneNode.getDecorator matches on
        `type(decorator) == dec_type`, so PlatformPhysics' "does this node have a
        hull decorator yet?" test (PlatformPhysics.py ~line 93) does not
        recognise a subclass and quietly adds a stock one alongside, which draws
        the shadow anyway. Overriding the method on the instance leaves the type
        alone. Nothing calls it through the class: the recompute timer is created
        from a callLater scheduled in __init__, so it binds this instance
        attribute rather than the class one.

        Applied to meshes this tool ADOPTS as well as ones it builds. A mesh out
        of a project file arrives with no decorators at all, since Cura does not
        serialise them, so PlatformPhysics has already given it a stock one by
        the time we see it, and that one has to be neutered in place and its
        hull torn down rather than merely not created.
        """
        try:
            from cura.Scene.ConvexHullDecorator import ConvexHullDecorator
        except Exception:
            return
        decorator = node.getDecorator(ConvexHullDecorator)
        if decorator is None:
            decorator = ConvexHullDecorator()
            node.addDecorator(decorator)

        def recompute_without_shadow():
            if getattr(decorator, "_convex_hull_node", None):
                decorator._convex_hull_node.setParent(None)
                decorator._convex_hull_node = None

        decorator.recomputeConvexHull = recompute_without_shadow
        recompute_without_shadow()   # take down one that has already been drawn

    # The extruder as it appears IN a mesh's name. Only ever rewritten in place:
    # the name is the key the merge joins the generated part to the sliced one on,
    # so a name that loses or gains a component stops matching the ;MESH: the
    # slicer already wrote.
    _EXTRUDER_SUFFIX_RE = re.compile(r'\(Extruder \d+\)')

    def _watchNodeExtruder(self, node):
        """Follow this mesh's extruder, so its name keeps telling the truth.

        The name is written once, at Save to Build Plate, and has the extruder
        baked into it. Cura can reassign the mesh afterwards through per-object
        settings, and nothing rewrote the name, so a mesh printed by extruder 2
        went on calling itself "(Extruder 1)" in the object list and in every
        ;MESH: comment in the g-code. Which extruder actually prints it is read
        off the node, so this is a label rather than a decision, but it was a
        label that disagreed with the print.

        Connected exactly once per node, at the two points where this tool takes
        one on: UM signals do not de-duplicate listeners. A mesh that came back
        in a project file is picked up on the first slice after loading, which is
        where its record is re-attached.
        """
        try:
            signal = node.callDecoration("getActiveExtruderChangedSignal")
            if signal is not None:
                signal.connect(self._onNodeExtruderChanged)
        except Exception:
            Logger.logException("w", "PathDesigner: could not watch a drawing's extruder")

    def _onNodeExtruderChanged(self, *args):
        # The signal says an extruder changed, not whose: it is emitted by the
        # decorator, with nothing to identify the node. Binding one into the
        # handler would keep a deleted mesh alive, so every drawing is checked
        # instead. There are a handful, and only a per-object extruder change
        # gets here.
        self._relabelDrawnMeshes()

    def _relabelDrawnMeshes(self):
        """Put the right extruder in the name of every drawn mesh on the plate.

        Safe to do here because Cura defers re-slicing behind a timer, so this
        runs well before StartSliceJob reads the names. Renaming a mesh once
        slicing has begun would be the dangerous version: the sliced g-code would
        hold the old name, the generated part the new one, and the drawn shape
        would print twice, once as the slicer's reading of the solid.
        """
        for node in self._controller.getScene().getRoot().getAllChildren():
            if node.getParent() is None:
                continue
            decorator = node.getDecorator(DrawnPathDecorator)
            if decorator is None:
                continue
            position = node.callDecoration("getActiveExtruderPosition")
            try:
                position = int(position)
            except (TypeError, ValueError):
                continue
            name = node.getName()
            renamed = self._EXTRUDER_SUFFIX_RE.sub(
                "(Extruder {0})".format(position + 1), name, count = 1)
            if renamed == name:
                continue
            node.setName(renamed)
            # The record follows, or restoring the drawing would bring the old
            # extruder back into the panel and a re-save would undo the rename.
            record = decorator.getDrawnPathRecord()
            record["name"] = renamed
            record["extruder"] = position
            self._storeRecordOnNode(node, record)
            Logger.log("i", "PathDesigner: renamed '%s' to '%s' after its extruder changed",
                       name, renamed)

    def _drawnPathsOnPlate(self) -> List[dict]:
        """Every trajectory to trace, read off the plate at slice time.

        Deliberately derived, never remembered. The record travels on the mesh
        (DrawnPathDecorator), so the answer is whatever is on the plate NOW, and
        the tool can be reset, reloaded or restarted without the drawn paths
        quietly becoming ordinary solids.

        Three things are taken from the node rather than from the record. Its NAME,
        because Cura renames duplicates to "name(1)" and the generated part has
        to replace exactly the part it came from. Its world TRANSFORM, because
        the points are stored in the node's own frame, so a mesh dragged in Cura
        since the last save is traced where it now sits instead of where it was
        saved. And its EXTRUDER, for the same reason as the name: the mesh is
        what the print is made from, and Cura can reassign it through per-object
        settings long after Save to Build Plate wrote the record.

        The extruder used to come from the record alone, and PrintessOneAtATime
        reads it off the node, so the two could disagree with nothing on screen
        to say so. That is not a cosmetic disagreement: these coordinates already
        have the nozzle offset of the extruder named here subtracted from them,
        and the nozzles are 30 mm apart, so a path generated for one extruder and
        printed by the other came out in the wrong material a nozzle separation
        away from where it was drawn.
        """
        drawn = []
        for node in self._controller.getScene().getRoot().getAllChildren():
            if node.getParent() is None:
                continue
            decorator = node.getDecorator(DrawnPathDecorator)
            if decorator is None:
                # No decorator means this mesh came back from a project file,
                # which does not carry them. The same record is in the node's
                # metadata, which a 3MF round-trip does preserve. Re-attach it so
                # the parsing happens once rather than on every slice.
                restored = self._recordFromMetadata(node)
                if restored is None:
                    continue
                decorator = DrawnPathDecorator(restored)
                node.addDecorator(decorator)
                self._watchNodeExtruder(node)
                # Put it back under the qualified name. The key may have come
                # back bare, and saving the project again would then drop it.
                self._storeRecordOnNode(node, restored)
                self._suppressHullShadow(node)
            record = copy.deepcopy(decorator.getDrawnPathRecord())
            if not record.get("points"):
                continue
            # A filled shape carries a record too, so the drawing can be brought
            # back, but it is meant to slice like any model and has no trajectory
            # to trace.
            if record.get("kind", DRAWING_KIND_PATH) != DRAWING_KIND_PATH:
                continue
            record["name"] = node.getName()
            # Only when the node can actually answer, and only for an extruder
            # this machine has: an unreadable or out-of-range answer leaves the
            # record's own value, which is at least a value the generator can
            # look settings up for. A KeyError there would lose the whole merge.
            position = node.callDecoration("getActiveExtruderPosition")
            try:
                if position is not None and self._extruderStack(int(position)) is not None:
                    record["extruder"] = int(position)
            except (TypeError, ValueError):
                pass
            offset = record.get("offset") or (0.0, 0.0)
            matrix = node.getWorldTransformation()

            def placed(point: Point) -> Point:
                # The well offset is recorded beside the path rather than baked
                # into it, so that the drawing restores where it was drawn. It
                # has to go back on here, because this copy prints where it sits.
                moved = Vector(point[0] + offset[0], 0.0,
                               point[1] + offset[1]).preMultiply(matrix)
                return (moved.x, moved.z)

            record["points"] = [placed(point) for point in record["points"]]
            drawn.append(record)
        return drawn

    def _restoreDrawingFromPlate(self) -> bool:
        """Rebuild the drawing from the meshes on the plate. True if anything came back.

        The drawing lives only in this tool, so a reloaded project brought back
        shapes that could be moved and deleted but never opened or edited. Each
        mesh carries its own path, so the drawing can simply be collected from
        the plate, and the link between the two is intrinsic rather than an index
        that could fall out of step: delete a mesh and its path goes with it.

        Only the SOURCE copy of a replicated shape is taken. Every well copy
        carries the same drawing, and taking them all would multiply the drawing
        by the number of wells each time a project was opened.

        Order comes from the recorded index rather than from scene order, because
        the mesh names carry that index and a re-save has to reproduce them.
        """
        found = {}
        wells = None
        for node in self._controller.getScene().getRoot().getAllChildren():
            if node.getParent() is None:
                continue
            decorator = node.getDecorator(DrawnPathDecorator)
            if decorator is None:
                restored = self._recordFromMetadata(node)
                if restored is None:
                    continue
                decorator = DrawnPathDecorator(restored)
                node.addDecorator(decorator)
                self._watchNodeExtruder(node)
                self._storeRecordOnNode(node, restored)
            # Ours again, so it must not wear Cura's grey footprint.
            self._suppressHullShadow(node)
            record = decorator.getDrawnPathRecord()
            if not record.get("points") or record.get("well", 0) != 0:
                continue
            found[record.get("index", len(found) + 1)] = (node, record)
            if wells is None:
                wells = (record.get("well_preset", ""), record.get("wells") or [])
        if not found:
            return False

        self._paths = []
        self._added_nodes = []
        for index in sorted(found):
            node, record = found[index]
            # Start from a complete path and let the record fill in what it has.
            #
            # A record is not necessarily a whole drawing. Earlier builds stored
            # only what was needed to TRACE a shape, with no "shape", "control" or
            # "fill" in it, and a project saved by one of those is still on
            # somebody's disk. Building a path straight out of the record left
            # those keys missing and the panel took Cura down with a KeyError the
            # moment the tool opened. Such a shape comes back as the freehand
            # polyline it can honestly be described as, rather than not at all.
            path = {"shape": "line", "points": [], "control": [], "closed": False,
                    "fill": False, "fill_segments": [], "extruder": 0, "layers": 1,
                    "speed": 0.0, "flow": 100.0}
            path.update({key: copy.deepcopy(record[key])
                         for key in self._SNAPSHOT_KEYS if key in record})
            if "line_width" not in path:
                # Only reached by a record that predates it being stored.
                # _rebuildPathNode re-reads the width live on every rebuild, so
                # this has to be plausible rather than right.
                try:
                    path["line_width"] = self._lineWidth(path["extruder"])
                except Exception:
                    path["line_width"] = 0.4
            path["points"] = [(float(x), float(z)) for x, z in path.get("points", [])]
            path["control"] = [(float(x), float(z)) for x, z in path.get("control", [])]
            path["node"] = None
            path["shade_node"] = None
            self._paths.append(path)
            # absorbed is left at identity on purpose. The record holds the path
            # in the node's own frame, so whatever transform the mesh is carrying
            # is a move that has NOT been folded into the drawing yet, and
            # _absorbMeshMoves will apply it exactly once.
            self._added_nodes.append({"node": node, "extruder": path.get("extruder", 0),
                                      "path": path, "absorbed": Matrix()})
        if wells is not None:
            self._well_preset, selected = wells
            self._selected_wells = set(selected)

        for index in range(len(self._paths)):
            self._rebuildPathNode(index)
        self._rebuildSnapPoints()
        Logger.log("i", "PathDesigner: recovered %d drawn shape(s) from the build plate",
                   len(self._paths))
        return True

    @staticmethod
    def _storeRecordOnNode(node, record: dict):
        """Put the trajectory somewhere a Cura project file will keep it.

        Written as a plain JSON string, deliberately: the metadata dict is
        serialised verbatim, so anything else would come back as whatever str()
        made of it. Coordinates are rounded to 4 decimals, a tenth of a micron,
        which is far below anything the machine can resolve and keeps a
        finely tessellated curve from bloating the project file.
        """
        compact = dict(record)
        compact["points"] = [[round(x, 4), round(z, 4)] for x, z in record["points"]]
        try:
            # Any other spelling left by an earlier round-trip goes, so the node
            # never carries two copies that could drift apart.
            for key in [k for k in node.metadata
                        if str(k).split(":")[-1] == DRAWN_PATH_METADATA_KEY
                        and k != DRAWN_PATH_METADATA_QUALIFIED]:
                del node.metadata[key]
            node.metadata[DRAWN_PATH_METADATA_QUALIFIED] = json.dumps(compact, separators = (",", ":"))
        except Exception:
            # Losing this costs the project file, not the current session: the
            # decorator still carries the path until Cura is closed.
            Logger.logException("w", "PathDesigner: could not store the drawn path on the mesh")

    @staticmethod
    def _recordFromMetadata(node) -> Optional[dict]:
        """Rebuild a trajectory from what a project file preserved, or None."""
        metadata = getattr(node, "metadata", None) or {}
        for key, value in metadata.items():
            # 3MF may or may not put a namespace back on the key, so the suffix
            # is what identifies it rather than the whole thing.
            if str(key).split(":")[-1] != DRAWN_PATH_METADATA_KEY:
                continue
            # ThreeMFReader stores the Savitar setting OBJECT in metadata rather
            # than its string, unlike every other branch it takes, so unwrap it.
            text = getattr(value, "value", value)
            try:
                record = json.loads(text)
                record["points"] = [(float(x), float(z)) for x, z in record.get("points", [])]
            except Exception:
                Logger.logException("w", "PathDesigner: could not read the drawn path stored on a mesh")
                return None
            return record if record["points"] else None
        return None

    def _hideStaleWarning(self):
        if self._stale_message is None:
            return
        message, self._stale_message = self._stale_message, None
        try:
            message.hide()
        except Exception:
            Logger.logException("w", "PathDesigner: could not take down the stale plate warning")

    def _onStaleWarningAction(self, message, action_id):
        """Put the plate back in step, then slice it again.

        The re-save alone is not enough to trust: auto-slicing is off by default
        in Cura, so without forcing one the user would be looking at a message
        that has apparently done nothing.
        """
        if action_id != "update_plate":
            return
        self._hideStaleWarning()
        try:
            self.addToBuildPlate()
            from cura.CuraApplication import CuraApplication
            CuraApplication.getInstance().getBackend().forceSlice()
        except Exception:
            Logger.logException("e", "PathDesigner: could not update the build plate from the warning")

    def _gcodeSettings(self) -> dict:
        """Machine and material values for the generator, read LIVE.

        Deliberately gathered here rather than kept from when the shape was
        drawn or saved: changing flow, speed or a dispense tip and pressing
        Slice again should be enough to get new g-code, exactly as it is for
        anything else on the plate.
        """
        application = Application.getInstance()
        stack = application.getGlobalContainerStack()
        lh, lh0 = self._layerHeights()
        settings = {
            "machine_width": float(stack.getProperty("machine_width", "value")),
            "machine_depth": float(stack.getProperty("machine_depth", "value")),
            "layer_height": lh,
            "layer_height_0": lh0,
            "extruders": {},
        }
        for index in range(len(stack.extruderList)):
            settings["extruders"][index] = {
                # Speed and flow both GENERAL, as a pair: speed_print and
                # material_flow, not speed_wall_0 and wall_0_material_flow.
                #
                # Changed 2026-08-17 at the user's request, to match the Flow
                # Rate Tester. An UNFILLED drawn path bypasses CuraEngine
                # entirely, so calling it an outer wall was a convention rather
                # than a fact, and the number a user tunes with the tester is
                # material_flow. Reading them as a pair still matters: one from
                # the wall and one from the general setting would describe the
                # same line as two different features.
                #
                # Behaviour-neutral on every current profile - nothing sets
                # wall_0_material_flow or speed_wall_0 except as `=speed_print` -
                # and it also brings the g-code into line with getTotalsText,
                # which was already estimating volume from material_flow.
                #
                # NOTE the asymmetry this leaves, and it is deliberate: a FILLED
                # drawn shape is a mesh sliced by CuraEngine, so its perimeter
                # really is an outer wall and really does use the wall settings.
                # Only unfilled paths are generated here.
                "print_speed": self._extruderProperty(index, "speed_print", 4.0),
                "speed_travel": self._extruderProperty(index, "speed_travel", 4.0),
                "material_flow": self._extruderProperty(index, "material_flow", 100.0),
                # First layer only, exactly as CuraEngine applies them. Read
                # through the extruder stack even though Initial Layer Flow is a
                # per-mesh setting rather than a per-extruder one: an extruder
                # stack resolves anything it does not hold itself up to the
                # global stack, so this follows whichever level the user set it
                # at without having to know which that was.
                "initial_flow": self._extruderProperty(index, "material_flow_layer_0", 100.0),
                "initial_line_width_factor": self._extruderProperty(
                    index, "initial_layer_line_width_factor", 100.0),
                "initial_speed": self._extruderProperty(index, "speed_print_layer_0", 4.0),
                # Falls back to 0, meaning no ramp: an unreadable setting must
                # not invent a slowdown the profile never asked for.
                "slowdown_layers": self._extruderProperty(index, "speed_slowdown_layers", 0.0),
                "material_diameter": self._extruderProperty(index, "material_diameter", 2.85),
                "nozzle_offset_x": self._extruderProperty(index, "machine_nozzle_offset_x", 0.0),
                "nozzle_offset_y": self._extruderProperty(index, "machine_nozzle_offset_y", 0.0),
            }
        return settings

    def _setSavedMeshesVisible(self, visible: bool):
        """Show or hide the meshes the last save put on the build plate.

        They are hidden while this tool is open, because a saved shape would
        otherwise bury its own drawing: the ribbons sit at PATH_RENDER_HEIGHT
        (0.2 mm), below the top of even a one-layer mesh, so the mesh is all
        that can be seen. The shape then looks unselectable and unerasable, and
        dragging it reads as spawning a duplicate rather than moving the one
        thing that was there. Hiding the meshes while editing leaves exactly one
        representation of each shape on screen; leaving the tool brings them
        back. This is purely visual: StartSliceJob goes by isSliceable, not by
        visibility, so a hidden mesh still slices and prints.
        """
        scene = self._controller.getScene()
        for entry in self._added_nodes:
            node = entry["node"]
            if node.getParent() is None:
                continue  # already removed from the scene
            node.setVisible(visible)
            scene.sceneChanged.emit(node)

    def _plateState(self) -> tuple:
        """Everything that decides what Save to Build Plate would produce."""
        return (self._snapshot(), self._well_preset, sorted(self._selected_wells))

    def _drawingIsOnThePlate(self) -> bool:
        """Whether the meshes on the plate still stand for the whole drawing."""
        if self._saved_state is None:
            return False
        if not any(entry["node"].getParent() is not None for entry in self._added_nodes):
            return False  # the user removed them, so only the drawing is left
        return self._plateState() == self._saved_state

    def _updateDrawingVisibility(self):
        """Show the drawing outside the tool only when the plate does not
        already show it.

        A saved drawing is drawn twice, once as flat ribbons and once as the
        solid meshes built from them. That went unnoticed while the two sat on
        top of each other, but dragging a mesh aside revealed the ribbons
        stranded at the old position. So once the plate agrees with the drawing,
        the meshes speak for it and the ribbons stand down. A drawing that has
        never been saved, or that has been edited since, stays visible: leaving
        the tool must never look like the work was lost.
        """
        group = self._group_node
        if group is None:
            return
        group.setVisible(not self._drawingIsOnThePlate())
        self._controller.getScene().sceneChanged.emit(group)

    def _transformPath(self, path: dict, matrix: Matrix):
        """Apply a scene transformation to one shape's geometry."""
        def moved(point: Point) -> Point:
            placed = Vector(point[0], 0.0, point[1]).preMultiply(matrix)
            return (placed.x, placed.z)

        path["points"] = [moved(point) for point in path["points"]]
        path["control"] = [moved(point) for point in path.get("control", [])]
        # A composite is regenerated from its pieces, so they have to travel too
        # or the next rebuild would snap it back.
        for piece in path.get("pieces", []):
            piece["control"] = [moved(point) for point in piece["control"]]
        # The zigzag fill is cut along the scene axes, so it is re-cut rather
        # than carried: a rotated shape needs new scanlines, not turned ones.
        self._recomputeFill(path)

    @staticmethod
    def _keepsThePlate(matrix: Matrix) -> bool:
        """Whether a transformation keeps the plate plane flat.

        A point on the plate is (x, 0, z), so its height afterwards is
        m[1][0]*x + m[1][2]*z + m[1][3]. That is the same for every point on the
        plate, which is what "still flat" means, exactly when the two axis terms
        vanish; the constant is only a lift and is dropped along with y. So a
        move, a flat turn about the vertical, and a scale all pass, while
        tipping the model onto its side does not.
        """
        data = matrix.getData()
        return abs(data[1][0]) < 1e-6 and abs(data[1][2]) < 1e-6

    def _absorbMeshMoves(self):
        """Fold any move made to a saved mesh back into the drawing.

        Outside this tool the meshes are ordinary Cura models, so the Move tool
        works on them, but the drawing they came from does not follow. Left
        alone, the next save would rebuild them where the drawing still is,
        which reads as the move being thrown away. Reopening the tool is where
        the two are reconciled: whatever was done to a mesh out there is applied
        to the shapes in here, so the move sticks and the next save agrees.

        Only the change SINCE the last absorb is applied, which is what lets the
        node keep its own transformation: nothing here rebuilds the mesh or
        rewrites the node, so Cura's undo history for that move stays valid.
        """
        moved_any = False
        tumbled = False
        for entry in self._added_nodes:
            node = entry["node"]
            if node.getParent() is None:
                continue
            current = node.getWorldTransformation()
            # current * inverse(absorbed): the part of the transformation the
            # drawing has not caught up with yet.
            delta = current.multiply(entry["absorbed"].getInverse(), copy = True)
            if numpy.allclose(delta.getData(), numpy.identity(4), atol = 1e-6):
                continue
            if not self._keepsThePlate(delta):
                # Tipped out of the plate. A drawing is flat by definition, so
                # there is nothing sensible to fold back in: stand the mesh up
                # again where the drawing still is and say why.
                node.setTransformation(Matrix(entry["absorbed"].getData()))
                self._controller.getScene().sceneChanged.emit(node)
                tumbled = True
                continue
            target = entry.get("path")
            if target is None or not any(path is target for path in self._paths):
                continue  # a well copy, or the shape it came from is gone
            entry["absorbed"] = current
            for path in (target,):
                if not moved_any:
                    # Snapshot the pre-move drawing before the first change, or
                    # the next Undo in here would restore a state from before
                    # the move and teleport the shapes back on their own.
                    self._pushUndo()
                    moved_any = True
                self._transformPath(path, delta)

        if tumbled:
            Message("A drawing lies flat on the build plate, so it cannot be tipped out of it.\n"
                    "The drawing has been stood back up. Move, turn it flat, or scale it instead.",
                    title = "Path Designer").show()

        if not moved_any:
            return
        # The drawing has caught up with the meshes, so the plate stands for it
        # again and it can go on hiding outside the tool.
        self._saved_state = self._plateState()
        for index in range(len(self._paths)):
            self._rebuildPathNode(index)
        self._rebuildSnapPoints()
        self._rebuildWellOverlay()
        self._emitChanged()

    def addToBuildPlate(self):
        """Convert the drawing (with well replication) into solid meshes on the
        build plate, one per extruder, then leave the tool. The user slices
        them like any model: outlines become one-line-wide ridges, filled
        shapes become solid pads (walls + infill from the print settings),
        and Preview shows the real toolpaths.
        """
        if self._current_points:
            self.finishPath()
        if not self._paths:
            Message("Draw at least one path first.", title = "Path Designer").show()
            return
        # Removing a node empties the selection, and an empty selection makes
        # Cura deactivate the active tool, so _onDeactivate runs part-way
        # through the push below. That is not the user walking away from
        # unsaved work, and it must not raise the offer to keep or drop it.
        self._saving = True

        from UM.Mesh.MeshBuilder import MeshBuilder
        from UM.Settings.SettingInstance import SettingInstance
        from UM.Operations.AddSceneNodeOperation import AddSceneNodeOperation
        from UM.Operations.GroupedOperation import GroupedOperation
        from UM.Operations.RemoveSceneNodeOperation import RemoveSceneNodeOperation
        from cura.CuraApplication import CuraApplication
        from cura.Scene.CuraSceneNode import CuraSceneNode
        from cura.Scene.SliceableObjectDecorator import SliceableObjectDecorator
        from cura.Scene.BuildPlateDecorator import BuildPlateDecorator
        from cura.Scene.ConvexHullDecorator import ConvexHullDecorator

        lh, lh0 = self._layerHeights()
        offsets = self._replicationOffsets()

        def segment_quad(a, b, width):
            """The rectangle one segment of a drawn line covers.

            Deliberately NOT extended past its endpoints. The on-screen ribbon
            does extend, so that consecutive segments overlap and corners look
            filled, but a SOLID built that way overshoots every corner by half
            a line width. The slicer reads that square of extra material as
            wider than one bead: it chamfers the corner of the main path and
            fills what is left with a separate little loop. That is exactly the
            blob seen at each corner of a drawn rectangle. Corners are covered
            by a disc at the vertex instead, which keeps the ribbon exactly one
            bead wide the whole way round.
            """
            dx, dz = b[0] - a[0], b[1] - a[1]
            length = math.hypot(dx, dz)
            if length < 1e-9:
                return None
            half = max(width, 0.1) / 2.0
            ux, uz = dx / length, dz / length
            nx, nz = -uz * half, ux * half
            return [(a[0] + nx, a[1] + nz), (a[0] - nx, a[1] - nz),
                    (b[0] - nx, b[1] - nz), (b[0] + nx, b[1] + nz)]

        def join_discs(loop, width):
            """A disc at EVERY vertex of the ribbon, as polygons.

            The discs are what hold the ribbon together, which is why there is
            one at every vertex rather than only at sharp corners. Two
            un-extended segment quads meeting at a vertex overlap in a wedge
            whose area vanishes as the turn straightens: about 0.005 mm2 at one
            degree. That is degenerate contact, and the slicer could not union
            it reliably, so a drawn curve came out shattered into disconnected
            fragments with the odd stray island. A disc of radius half the line
            width covers the whole joint and overlaps both neighbours with real
            area, while still lying within half a width of the drawn line, so
            it buys that robustness without overshooting anything.

            The discs at the two ends of an open path are its round caps, so the
            bead runs the full length instead of stopping half a width short.
            """
            half = max(width, 0.1) / 2.0
            # segment_length = half gives tessellate_circle its 12-sided floor.
            return [PathShapes.tessellate_circle(vertex, half, half) for vertex in loop]

        def build_shape(path, offset, ribbon):
            """One MeshBuilder holding a single drawn shape, or None if empty.

            Every solid goes through PathShapes.prism_faces, which caps and
            walls a polygon with one consistent outward winding.
            MeshBuilder.addConvexPolygonExtrusion cannot be used here: it winds
            its side walls opposite to its caps, and a filled shape built as one
            prism per ear-clipped triangle also buries a wall between every pair
            of triangles. Either one is reported by Cura as "missing or
            extraneous surfaces".
            """
            builder = MeshBuilder()
            height = lh0 + (path["layers"] - 1) * lh
            points = [(x + offset[0], z + offset[1]) for x, z in path["points"]]
            polygons = []
            if path["fill"] and path["closed"]:
                # Solid pad: one polygon, sliced into walls and infill as any
                # imported model would be.
                polygons.append(points)
            else:
                # An outline is a ribbon one bead wide. Each segment is its own
                # closed solid; they overlap at the joints, which the slicer
                # unions, and each one is watertight on its own.
                # Round the corners first. A sharp corner in a constant-width
                # stroke carries surplus area that the slicer covers with an
                # extra contour beside the main bead, and no slicer setting
                # removes area that is genuinely there. At this radius the
                # stroke is exactly one bead wide the whole way round. Gentle
                # bends pass through untouched.
                points = PathShapes.fillet_polyline(
                    points, path["closed"],
                    max(ribbon, 0.1) / 2.0 * FILLET_FACTOR,
                    SEGMENT_LENGTH)
                loop = points + [points[0]] if path["closed"] else points
                for i in range(len(loop) - 1):
                    quad = segment_quad(loop[i], loop[i + 1], ribbon)
                    if quad is not None:
                        polygons.append(quad)
                # The vertices themselves, NOT `loop`: a closed loop repeats its
                # first point, and two discs stacked in the same spot duplicate
                # every face between them, which is precisely the coincident
                # surface Cura complains about.
                polygons.extend(join_discs(points, ribbon))

            faces = 0
            for polygon in polygons:
                for v0, v1, v2 in PathShapes.prism_faces(polygon, 0.0, height):
                    builder.addFaceByPoints(v0[0], v0[1], v0[2],
                                            v1[0], v1[1], v1[2],
                                            v2[0], v2[1], v2[2])
                    faces += 1
            return builder if faces else None

        application = CuraApplication.getInstance()
        root = self._controller.getScene().getRoot()
        active_build_plate = application.getMultiBuildPlateModel().activeBuildPlate
        global_stack = application.getGlobalContainerStack()

        op = GroupedOperation()

        # Un-hide before replacing: these nodes are about to be removed, and a
        # Cura Undo would otherwise hang them back in the scene still invisible.
        self._setSavedMeshesVisible(True)

        # Saving again replaces what the last save put on the plate instead of
        # laying a second copy over it: the drawing is the source, the meshes
        # are only its current rendering, so changing the layer count (or
        # anything else) and saving updates them in place. Meshes the user has
        # already deleted by hand are skipped. Removal and creation go in one
        # GroupedOperation, so a single Undo puts the plate back as it was.
        replaced = [entry["node"] for entry in self._added_nodes
                    if entry["node"].getParent() is not None]
        for node in replaced:
            op.addOperation(RemoveSceneNodeOperation(node))

        # One scene node per drawn shape, per well it is copied into. Each is a
        # separate object, so the slicer and the post-processing script can
        # order them and finish them one at a time. The name carries the mark
        # the script keys on: it reaches the g-code as a ;MESH: comment.
        new_nodes = []
        for number, path in enumerate(self._paths, start = 1):
            kind = DRAWING_KIND_FILL if (path["fill"] and path["closed"]) else DRAWING_KIND_PATH
            # An outline whose own lines run within a line width of each other
            # does not stay a line: the beads merge into a solid area. The
            # drawn trajectory is then gone, because the shape on the plate no
            # longer records which way round it was drawn, and the slicer fills
            # the area however it sees fit.
            width = path["line_width"]
            # Whether the drawn lines touch no longer matters. That distinction
            # existed only because a stroke reconstructed from a solid loses the
            # order it was drawn in, so a touching serpentine had to be filled as
            # an area instead. The generator emits the drawn path itself, so
            # every outline goes through it and the raster is gone, along with
            # the grid it landed on rather than on the drawn legs.
            for well, offset in enumerate(offsets):
                builder = build_shape(path, offset, width)
                if builder is None:
                    continue
                name = "{0}-{1}-{2}".format(DRAWING_TAG, kind, number)
                if len(offsets) > 1:
                    name += "w{0}".format(well + 1)
                name += " (Extruder {0})".format(path["extruder"] + 1)

                node = CuraSceneNode()
                node.setName(name)
                node.setSelectable(True)
                node.setCalculateBoundingBox(True)
                node.setMeshData(builder.build())
                node.calculateBoundingBoxMesh()
                node.addDecorator(BuildPlateDecorator(active_build_plate))
                node.addDecorator(SliceableObjectDecorator())
                self._suppressHullShadow(node)
                # EVERY drawn shape carries its own record, filled ones too.
                # The unfilled ones need it to be traced; all of them need it for
                # the drawing to come back at all, since the drawing itself lives
                # only in this tool's memory and the meshes are what survive.
                #
                # The path goes in AS DRAWN, with the well offset recorded beside
                # it rather than baked in, so the drawing restores to where it was
                # drawn while the trajectory can still be placed in the copy's own
                # position. Coordinates are the node's own frame, so its transform
                # is what moves either of them.
                record = {key: copy.deepcopy(path[key])
                          for key in self._SNAPSHOT_KEYS if key in path}
                record.update({
                    # The mesh's own name, so a generated part replaces exactly
                    # the part it came from. Re-read from the node at slice time,
                    # since Cura renames duplicates.
                    "name": name,
                    "kind": kind,
                    "index": number,
                    "well": well,
                    "offset": [offset[0], offset[1]],
                    # Enough to put the well plate back as it was, so re-saving a
                    # restored drawing produces the same copies.
                    "well_preset": self._well_preset,
                    "wells": sorted(self._selected_wells),
                })
                node.addDecorator(DrawnPathDecorator(record))
                # Twice over on purpose: the decorator covers this session, the
                # metadata is what a saved project file brings back.
                self._storeRecordOnNode(node, record)
                op.addOperation(AddSceneNodeOperation(node, root))
                # Only the shape where it was drawn feeds a move back into the
                # drawing; dragging a well copy would otherwise shift the
                # original and every other copy with it.
                new_nodes.append((node, path["extruder"], path if well == 0 else None))

        # Meshes left over from an earlier save that this tool no longer holds a
        # reference to. They must go too, or they stay on the plate directly
        # underneath the ones just built, in exactly the same place, where
        # nothing on screen can reveal them: two coincident solids do not look
        # like an intersection, they look like one object. The only sign is
        # Cura's object list, which renames the duplicates to "name(1)",
        # "name(2)", and the g-code, where they slice twice.
        #
        # A save is meant to leave exactly one mesh per drawn shape however the
        # tracking got lost, so anything already on the plate carrying a name
        # this save is producing is replaced as well, not just what
        # _added_nodes happens to remember.
        created_names = {node.getName() for node, _extruder, _path in new_nodes}
        tracked = {id(node) for node in replaced}
        reclaimed = [existing for existing in root.getAllChildren()
                     if existing.getName() in created_names
                     and existing.getParent() is not None
                     and id(existing) not in tracked]
        for node in reclaimed:
            op.addOperation(RemoveSceneNodeOperation(node))
        if reclaimed:
            Logger.log("i", "PathDesigner: reclaimed %d untracked mesh(es) of this drawing",
                       len(reclaimed))

        # Recorded before the push: removing a node clears the selection, and an
        # empty selection makes CuraApplication deactivate the active tool, so
        # _onDeactivate can run part-way through op.push().
        # A freshly built mesh sits at the drawing's own coordinates with an
        # identity transformation, so there is nothing absorbed yet.
        self._added_nodes = [{"node": node, "extruder": extruder, "path": path,
                              "absorbed": Matrix()}
                             for node, extruder, path in new_nodes]
        self._saved_state = self._plateState()
        op.push()

        for node, extruder_index, _source_path in new_nodes:
            try:
                if global_stack is not None:
                    node.callDecoration("setActiveExtruder", global_stack.extruderList[extruder_index].getId())
            except Exception:
                Logger.logException("w", "PathDesigner: could not assign extruder to drawing mesh")
            # After the assignment, so the watch does not fire on the tool's own
            # setting of an extruder the name already agrees with.
            self._watchNodeExtruder(node)
            self._controller.getScene().sceneChanged.emit(node)

        # The drawing is deliberately NOT cleared: it stays as the editable
        # source, so reopening the tool finds the shapes again, ready to be
        # moved, reshaped, or given a different layer count and saved anew.
        path_count = len(self._paths)
        well_note = " across {0} wells".format(len(offsets)) if len(offsets) > 1 else ""
        if replaced or reclaimed:
            note = "Updated {0} path(s){1} on the build plate.\nClick Slice to see the print preview.".format(
                path_count, well_note)
            if reclaimed:
                note += "\n{0} earlier cop{1} of this drawing had been left on the plate; " \
                        "they have been replaced too.".format(
                            len(reclaimed), "y" if len(reclaimed) == 1 else "ies")
        else:
            note = ("Added {0} path(s){1} to the build plate.\nClick Slice to see the print preview. "
                    "The drawing is kept, so you can reopen Path Designer, change it, "
                    "and save again to update.").format(path_count, well_note)
        Message(note, title = "Path Designer").show()

        # The plate now stands for the drawing, so any warning that it did not
        # is answered and comes down, and there is nothing unsaved to offer to
        # keep or drop. Re-anchoring the session here means "revert" goes back to
        # what is on the plate rather than to an older state the plate no longer
        # matches.
        self._hideStaleWarning()
        self._hideLeavingOffer()
        self._session_state = self._plateState()
        self._saving = False

        self._controller.setActiveTool(None)
        # Normally the deactivation above settles this. Saving from the warning
        # can happen with the tool already closed, though, and then nothing else
        # would hide the ribbons: the drawing would be on screen twice, once
        # flat and once solid, which is the one thing this must never look like.
        self._updateDrawingVisibility()

    def _rebuildSnapPoints(self):
        """Collect snap targets: control points, open-path endpoints, and all
        crossings between committed paths."""
        points: List[Point] = []
        polylines = []
        for path in self._paths:
            # Handles, not raw control: a composite keeps its control points on
            # its pieces, and its junctions should still be snap targets.
            points.extend(self._editableNodes(path))
            pts = path["points"]
            if not path["closed"]:
                points.append(pts[0])
                points.append(pts[-1])
            polylines.append((pts, path["closed"]))
        for i in range(len(polylines)):
            for j in range(i + 1, len(polylines)):
                points.extend(PathShapes.polyline_intersections(
                    polylines[i][0], polylines[i][1], polylines[j][0], polylines[j][1]))
        self._snap_points = points
        self._rebuildNodeMarkers()

    # ------------------------------------------------------------------
    # Well-plate replication
    # ------------------------------------------------------------------

    def _extruderShift(self) -> float:
        """Half the nozzle X separation toward extruder 0 — same shift the
        WellPlateArrangeTool applies, so wells line up between the two tools."""
        try:
            stack = Application.getInstance().getGlobalContainerStack()
            extruders = list(stack.extruderList)
            if len(extruders) >= 2:
                off0 = float(extruders[0].getProperty("machine_nozzle_offset_x", "value"))
                off1 = float(extruders[1].getProperty("machine_nozzle_offset_x", "value"))
                return -(off1 - off0) / 2.0
        except Exception:
            pass
        return 0.0

    def _wellCenters(self) -> List[Point]:
        half_w, half_d = self._plateHalfSize()
        return WellPlates.well_centers(self._well_preset, half_w, half_d, self._extruderShift())

    def _sourceWellIndex(self) -> int:
        """The well the drawing lives in (nearest to the first drawn point)."""
        if not self._paths or not self._well_preset:
            return -1
        centers = self._wellCenters()
        if not centers:
            return -1
        return WellPlates.nearest_well(self._paths[0]["points"][0], centers)

    def _replicationOffsets(self) -> List[Point]:
        """Scene-coordinate offsets for every printed copy; (0,0) is the source."""
        offsets: List[Point] = [(0.0, 0.0)]
        source = self._sourceWellIndex()
        if source < 0:
            return offsets
        centers = self._wellCenters()
        for idx in sorted(self._selected_wells):
            if idx == source or idx >= len(centers):
                continue
            offsets.append((centers[idx][0] - centers[source][0],
                            centers[idx][1] - centers[source][1]))
        return offsets

    def _ensureOverlayNode(self, attr: str, transparent: bool) -> PathNode:
        node = getattr(self, attr)
        if node is None or node.getParent() is None:
            node = PathNode(self._ensureGroupNode())
            node.setName("PathDesigner" + attr)
            node.setTransparent(transparent)
            setattr(self, attr, node)
        return node

    def _rebuildWellOverlay(self):
        rings = self._ensureOverlayNode("_well_rings_node", False)
        selected_node = self._ensureOverlayNode("_well_sel_node", False)
        source_node = self._ensureOverlayNode("_well_src_node", False)
        ghost = self._ensureOverlayNode("_ghost_node", True)
        scene = self._controller.getScene()

        preset = WellPlates.PRESETS.get(self._well_preset)
        centers = self._wellCenters()
        if not preset or not centers:
            for node in (rings, selected_node, source_node, ghost):
                node.setMeshData(None)
                scene.sceneChanged.emit(node)
            return

        radius = preset["well_d"] / 2.0

        ring_polys = []
        for center in centers:
            circle = PathShapes.tessellate_circle(center, radius, 2.0)
            ring_polys.append(circle + [circle[0]])
        rings.setMeshData(build_ribbon_mesh(ring_polys, 0.5, 0.08))
        rings.setColor([0.55, 0.55, 0.55, 1.0])

        def marker_ring(idx):
            circle = PathShapes.tessellate_circle(centers[idx], radius + 0.8, 2.0)
            return circle + [circle[0]]

        source = self._sourceWellIndex()

        # Copies in blue; the source well in green, matching the panel's "S".
        selected_polys = [marker_ring(idx) for idx in sorted(self._selected_wells)
                          if idx < len(centers) and idx != source]
        selected_node.setMeshData(build_ribbon_mesh(selected_polys, 1.0, 0.1) if selected_polys else None)
        selected_node.setColor([0.25, 0.55, 0.95, 1.0])

        source_node.setMeshData(build_ribbon_mesh([marker_ring(source)], 1.0, 0.1)
                                if 0 <= source < len(centers) else None)
        source_node.setColor([0.30, 0.69, 0.31, 1.0])

        ghost_polys = []
        for off in self._replicationOffsets():
            if off == (0.0, 0.0):
                continue
            for path in self._paths:
                pts = [(x + off[0], z + off[1]) for x, z in path["points"]]
                if path["closed"]:
                    pts = pts + [pts[0]]
                ghost_polys.append(pts)
                for a, b in path["fill_segments"]:
                    ghost_polys.append([(a[0] + off[0], a[1] + off[1]),
                                        (b[0] + off[0], b[1] + off[1])])
        ghost.setMeshData(build_ribbon_mesh(ghost_polys, 0.8, 0.14) if ghost_polys else None)
        ghost.setColor([0.5, 0.65, 0.9, 0.4])

        for node in (rings, selected_node, source_node, ghost):
            scene.sceneChanged.emit(node)

    def getWellPreset(self) -> str:
        return self._well_preset

    def setWellPreset(self, value):
        value = str(value)
        if value == "None":
            value = ""
        if value != "" and value not in WellPlates.PRESETS:
            return
        if value == self._well_preset:
            return
        self._well_preset = value
        self._selected_wells = set()
        self._rebuildWellOverlay()
        self._emitChanged()

    def getWellCols(self) -> int:
        preset = WellPlates.PRESETS.get(self._well_preset)
        return preset["cols"] if preset else 0

    def getWellInfo(self) -> List[dict]:
        """Wells in panel display order: back row of the plate first."""
        preset = WellPlates.PRESETS.get(self._well_preset)
        if not preset:
            return []
        source = self._sourceWellIndex()
        info = []
        for row in range(preset["rows"] - 1, -1, -1):
            for col in range(preset["cols"]):
                idx = row * preset["cols"] + col
                info.append({"index": idx,
                             "selected": idx in self._selected_wells,
                             "source": idx == source})
        return info

    def toggleWell(self, data):
        idx = int(data)
        if idx == self._sourceWellIndex():
            return
        if idx in self._selected_wells:
            self._selected_wells.discard(idx)
        else:
            self._selected_wells.add(idx)
        self._rebuildWellOverlay()
        self._emitChanged()

    def getTotalsText(self) -> str:
        if not self._paths:
            return ""
        lh, lh0 = self._layerHeights()
        total_len = 0.0
        total_vol = 0.0
        for path in self._paths:
            length = PathShapes.polyline_length(path["points"])
            if path["closed"] and len(path["points"]) > 2:
                length += PathShapes.dist(path["points"][-1], path["points"][0])
            for a, b in path["fill_segments"]:
                length += PathShapes.dist(a, b)
            passes = path["layers"]
            thickness_total = lh0 + (passes - 1) * lh
            flow = (path["flow"] / 100.0) * (self._extruderProperty(path["extruder"], "material_flow", 100.0) / 100.0)
            total_len += length * passes
            total_vol += length * path["line_width"] * thickness_total * flow
        wells = len(self._replicationOffsets())
        text = "Total: {0:.0f} mm · {1:.1f} µL".format(total_len, total_vol)
        if wells > 1:
            text += "   ×{0} wells: {1:.0f} mm · {2:.1f} µL".format(
                wells, total_len * wells, total_vol * wells)
        return text

    def _fillDensityFromSettings(self, extruder: int) -> float:
        """Fill density comes from the print settings (infill_sparse_density)."""
        return max(5.0, min(100.0, self._extruderProperty(extruder, "infill_sparse_density", 100.0)))

    def _recomputeFill(self, path: dict):
        if path["closed"] and path["fill"]:
            spacing = path["line_width"] * 100.0 / self._fillDensityFromSettings(path["extruder"])
            path["fill_segments"] = PathShapes.zigzag_fill(path["points"], spacing, path["line_width"] * 0.5)
        else:
            path["fill_segments"] = []

