import os

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSignal, pyqtSlot

from cura.CuraApplication import CuraApplication
from UM.Extension import Extension
from UM.Logger import Logger
from UM.Math.Vector import Vector
from UM.Operations.GroupedOperation import GroupedOperation
from UM.Operations.TranslateOperation import TranslateOperation


# origin_x / origin_y are the measured centre of the BOTTOM-LEFT well, expressed
# in PRINTER (build-plate corner) coordinates where 0,0 is the front-left corner
# of the bed. They are referenced to extruder 0; arrangeWellPlate() applies an
# additional half-extruder X shift so the plate sits between the two nozzles.
# Custom configs have no measured origin and fall back to the legacy bed-centred layout.
_PRESETS = {
    "6-Well":  {"rows": 2,  "cols": 3,  "spacing_x": 39.12, "spacing_y": 39.12, "origin_x": 40.0, "origin_y": 23.0},
    "12-Well": {"rows": 3,  "cols": 4,  "spacing_x": 26.01, "spacing_y": 26.01, "origin_x": 40.0, "origin_y": 16.0},
    "24-Well": {"rows": 4,  "cols": 6,  "spacing_x": 19.30, "spacing_y": 19.30, "origin_x": 33.0, "origin_y": 14.0},
    "48-Well": {"rows": 6,  "cols": 8,  "spacing_x": 13.08, "spacing_y": 13.08, "origin_x": 34.0, "origin_y": 10.0},
}

_PREF_ROWS       = "WellPlate/rows"
_PREF_COLS       = "WellPlate/cols"
_PREF_SPACING_X  = "WellPlate/spacing_x"
_PREF_SPACING_Y  = "WellPlate/spacing_y"
_PREF_ORIGIN_X   = "WellPlate/origin_x"
_PREF_ORIGIN_Y   = "WellPlate/origin_y"
_PREF_HAS_ORIGIN = "WellPlate/has_origin"
_PREF_DEFAULTS_VERSION = "WellPlate/defaults_version"

# Active selection ("6-Well" .. "48-Well" or "Custom") and the dedicated Custom
# grid. Custom is stored independently of the presets so that editing a value
# (which switches the selection to Custom) never appears to mutate a preset, and
# so switching between a preset and Custom is non-destructive.
_PREF_ACTIVE_PRESET   = "WellPlate/active_preset"
_PREF_CUSTOM_ROWS     = "WellPlate/custom_rows"
_PREF_CUSTOM_COLS     = "WellPlate/custom_cols"
_PREF_CUSTOM_SPACING_X = "WellPlate/custom_spacing_x"
_PREF_CUSTOM_SPACING_Y = "WellPlate/custom_spacing_y"

_CUSTOM = "Custom"

# Bump this whenever the in-code default grid changes and you want existing
# installs (which have an older grid saved in preferences) to pick up the new
# default once. Version 1 = default switched to the 6-Well preset.
_DEFAULTS_VERSION = 1


class WellPlateArrange(QObject, Extension):

    rowsChanged          = pyqtSignal()
    colsChanged          = pyqtSignal()
    spacingXChanged      = pyqtSignal()
    spacingYChanged      = pyqtSignal()
    objectCountChanged   = pyqtSignal()
    activePresetChanged  = pyqtSignal()

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        Extension.__init__(self)

        # Active grid (what Arrange uses). Defaults to the 6-Well preset.
        self._rows      = 2
        self._cols      = 3
        self._spacing_x = 39.12
        self._spacing_y = 39.12
        self._origin_x  = 40.0     # bottom-left well centre, printer (corner) coords
        self._origin_y  = 23.0
        self._has_origin = True    # default matches the 6-Well preset

        # Which entry is selected in the UI ("6-Well" .. "48-Well" or "Custom").
        self._active_preset = "6-Well"

        # Dedicated Custom grid, kept separate from the presets so editing never
        # touches a preset. Seeded with a neutral generic plate.
        self._custom_rows      = 8
        self._custom_cols      = 12
        self._custom_spacing_x = 9.0
        self._custom_spacing_y = 9.0

        self._object_count = 0
        self._prefs_loaded = False
        self._view = None

        CuraApplication.getInstance().mainWindowChanged.connect(self._createView)

    # ── View creation (runs once after main window is ready) ─────────────────

    def _createView(self):
        if self._view is not None:
            return
        self._ensurePrefsLoaded()

        qml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "WellPlateButton.qml")
        self._view = CuraApplication.getInstance().createQmlComponent(
            qml_path, {"wellPlateManager": self}
        )
        if self._view is not None:
            CuraApplication.getInstance().addAdditionalComponent("saveButton", self._view)

        try:
            CuraApplication.getInstance().getController().getScene().sceneChanged.connect(
                self._onSceneChanged
            )
        except Exception as e:
            Logger.logException("w", "WellPlateArrange: could not connect to scene: %s", e)

    # ── Scene change tracking ────────────────────────────────────────────────

    def _onSceneChanged(self, _node=None):
        old = self._object_count
        self._refreshObjectCount()
        if self._object_count != old:
            self.objectCountChanged.emit()

    def _refreshObjectCount(self):
        try:
            from cura.Scene.CuraSceneNode import CuraSceneNode
        except ImportError:
            from UM.Scene.SceneNode import SceneNode as CuraSceneNode
        try:
            scene = CuraApplication.getInstance().getController().getScene()
            self._object_count = sum(
                1 for node in scene.getRoot().getChildren()
                if isinstance(node, CuraSceneNode)
            )
        except Exception:
            self._object_count = 0

    # ── Preferences ──────────────────────────────────────────────────────────

    def _ensurePrefsLoaded(self):
        if self._prefs_loaded:
            return
        self._prefs_loaded = True
        try:
            prefs = CuraApplication.getInstance().getPreferences()
            prefs.addPreference(_PREF_ROWS,       self._rows)
            prefs.addPreference(_PREF_COLS,       self._cols)
            prefs.addPreference(_PREF_SPACING_X,  self._spacing_x)
            prefs.addPreference(_PREF_SPACING_Y,  self._spacing_y)
            prefs.addPreference(_PREF_ORIGIN_X,   self._origin_x)
            prefs.addPreference(_PREF_ORIGIN_Y,   self._origin_y)
            prefs.addPreference(_PREF_HAS_ORIGIN, self._has_origin)
            prefs.addPreference(_PREF_DEFAULTS_VERSION, 0)
            prefs.addPreference(_PREF_ACTIVE_PRESET,    self._active_preset)
            prefs.addPreference(_PREF_CUSTOM_ROWS,      self._custom_rows)
            prefs.addPreference(_PREF_CUSTOM_COLS,      self._custom_cols)
            prefs.addPreference(_PREF_CUSTOM_SPACING_X, self._custom_spacing_x)
            prefs.addPreference(_PREF_CUSTOM_SPACING_Y, self._custom_spacing_y)

            # One-time defaults migration: if this install predates the current
            # default grid, overwrite the saved grid with the in-code defaults
            # (set in __init__) so the new default takes effect once. self._rows
            # etc. still hold those defaults at this point.
            try:
                stored_version = int(float(prefs.getValue(_PREF_DEFAULTS_VERSION)))
            except (TypeError, ValueError):
                stored_version = 0
            if stored_version < _DEFAULTS_VERSION:
                self._savePreferences()
                prefs.setValue(_PREF_DEFAULTS_VERSION, _DEFAULTS_VERSION)
                return

            self._rows       = int(float(prefs.getValue(_PREF_ROWS)))
            self._cols       = int(float(prefs.getValue(_PREF_COLS)))
            self._spacing_x  = float(prefs.getValue(_PREF_SPACING_X))
            self._spacing_y  = float(prefs.getValue(_PREF_SPACING_Y))
            self._origin_x   = float(prefs.getValue(_PREF_ORIGIN_X))
            self._origin_y   = float(prefs.getValue(_PREF_ORIGIN_Y))
            self._has_origin = str(prefs.getValue(_PREF_HAS_ORIGIN)).lower() in ("true", "1")

            self._custom_rows      = int(float(prefs.getValue(_PREF_CUSTOM_ROWS)))
            self._custom_cols      = int(float(prefs.getValue(_PREF_CUSTOM_COLS)))
            self._custom_spacing_x = float(prefs.getValue(_PREF_CUSTOM_SPACING_X))
            self._custom_spacing_y = float(prefs.getValue(_PREF_CUSTOM_SPACING_Y))

            active = str(prefs.getValue(_PREF_ACTIVE_PRESET))
            self._active_preset = active if (active in _PRESETS or active == _CUSTOM) else _CUSTOM
        except Exception as e:
            Logger.logException("w", "WellPlateArrange: could not load preferences: %s", e)

    def _savePreferences(self):
        try:
            prefs = CuraApplication.getInstance().getPreferences()
            prefs.setValue(_PREF_ROWS,       self._rows)
            prefs.setValue(_PREF_COLS,       self._cols)
            prefs.setValue(_PREF_SPACING_X,  self._spacing_x)
            prefs.setValue(_PREF_SPACING_Y,  self._spacing_y)
            prefs.setValue(_PREF_ORIGIN_X,   self._origin_x)
            prefs.setValue(_PREF_ORIGIN_Y,   self._origin_y)
            prefs.setValue(_PREF_HAS_ORIGIN, self._has_origin)
            prefs.setValue(_PREF_ACTIVE_PRESET,    self._active_preset)
            prefs.setValue(_PREF_CUSTOM_ROWS,      self._custom_rows)
            prefs.setValue(_PREF_CUSTOM_COLS,      self._custom_cols)
            prefs.setValue(_PREF_CUSTOM_SPACING_X, self._custom_spacing_x)
            prefs.setValue(_PREF_CUSTOM_SPACING_Y, self._custom_spacing_y)
        except Exception as e:
            Logger.logException("w", "WellPlateArrange: could not save preferences: %s", e)

    # ── Properties (read by QML via wellPlateManager.rows etc.) ─────────────

    @pyqtProperty(int, notify=rowsChanged)
    def rows(self):
        return self._rows

    @pyqtProperty(int, notify=colsChanged)
    def cols(self):
        return self._cols

    @pyqtProperty(float, notify=spacingXChanged)
    def spacingX(self):
        return self._spacing_x

    @pyqtProperty(float, notify=spacingYChanged)
    def spacingY(self):
        return self._spacing_y

    @pyqtProperty(int, notify=objectCountChanged)
    def objectCount(self):
        return self._object_count

    @pyqtProperty(str, notify=activePresetChanged)
    def activePreset(self):
        return self._active_preset

    # ── Custom-mode helper ───────────────────────────────────────────────────

    def _enterCustom(self):
        """Switch the active selection to Custom.

        Editing any grid field puts the user in Custom mode. The first time we
        leave a preset we seed the Custom grid from the values currently on
        screen, so the fields the user did not touch keep sensible values. The
        presets themselves are immutable code constants and are never modified.
        """
        if self._active_preset == _CUSTOM:
            return
        self._custom_rows      = self._rows
        self._custom_cols      = self._cols
        self._custom_spacing_x = self._spacing_x
        self._custom_spacing_y = self._spacing_y
        self._active_preset = _CUSTOM
        self._has_origin = False   # Custom configs use the legacy bed-centred layout
        self.activePresetChanged.emit()

    # ── Slots (called by QML via wellPlateManager.setRows(v) etc.) ──────────

    @pyqtSlot(int)
    def setRows(self, value):
        v = max(1, int(value))
        self._enterCustom()
        self._custom_rows = v
        if v != self._rows:
            self._rows = v
            self.rowsChanged.emit()
        self._savePreferences()

    @pyqtSlot(int)
    def setCols(self, value):
        v = max(1, int(value))
        self._enterCustom()
        self._custom_cols = v
        if v != self._cols:
            self._cols = v
            self.colsChanged.emit()
        self._savePreferences()

    @pyqtSlot(float)
    def setSpacingX(self, value):
        v = max(0.1, float(value))
        self._enterCustom()
        self._custom_spacing_x = v
        if abs(v - self._spacing_x) > 1e-6:
            self._spacing_x = v
            self.spacingXChanged.emit()
        self._savePreferences()

    @pyqtSlot(float)
    def setSpacingY(self, value):
        v = max(0.1, float(value))
        self._enterCustom()
        self._custom_spacing_y = v
        if abs(v - self._spacing_y) > 1e-6:
            self._spacing_y = v
            self.spacingYChanged.emit()
        self._savePreferences()

    @pyqtSlot(str)
    def setPreset(self, name):
        if name == _CUSTOM:
            self._loadCustom()
            return
        if name not in _PRESETS:
            return
        p = _PRESETS[name]
        self._prefs_loaded = True
        self._rows      = p["rows"]
        self._cols      = p["cols"]
        self._spacing_x = p["spacing_x"]
        self._spacing_y = p["spacing_y"]
        if "origin_x" in p and "origin_y" in p:
            self._origin_x   = p["origin_x"]
            self._origin_y   = p["origin_y"]
            self._has_origin = True
        else:
            self._has_origin = False
        self._active_preset = name
        self.rowsChanged.emit()
        self.colsChanged.emit()
        self.spacingXChanged.emit()
        self.spacingYChanged.emit()
        self.activePresetChanged.emit()
        self._savePreferences()

    def _loadCustom(self):
        """Make the stored Custom grid the active grid."""
        self._prefs_loaded = True
        self._rows      = max(1, int(self._custom_rows))
        self._cols      = max(1, int(self._custom_cols))
        self._spacing_x = max(0.1, float(self._custom_spacing_x))
        self._spacing_y = max(0.1, float(self._custom_spacing_y))
        self._has_origin = False
        self._active_preset = _CUSTOM
        self.rowsChanged.emit()
        self.colsChanged.emit()
        self.spacingXChanged.emit()
        self.spacingYChanged.emit()
        self.activePresetChanged.emit()
        self._savePreferences()

    @pyqtSlot()
    def arrangeWellPlate(self):
        self._ensurePrefsLoaded()
        try:
            from cura.Scene.CuraSceneNode import CuraSceneNode
        except ImportError:
            from UM.Scene.SceneNode import SceneNode as CuraSceneNode

        scene = CuraApplication.getInstance().getController().getScene()
        nodes = [node for node in scene.getRoot().getChildren()
                 if isinstance(node, CuraSceneNode)]
        if not nodes:
            return

        def sort_key(node):
            aabb = node.getBoundingBox()
            if aabb is None:
                return 0.0
            cx = (aabb.minimum.x + aabb.maximum.x) / 2
            cz = (aabb.minimum.z + aabb.maximum.z) / 2
            return cx * cx + cz * cz

        nodes.sort(key=sort_key)

        # When the active preset carries a measured bottom-left well origin we lay
        # the grid out in PRINTER (build-plate corner) coordinates and convert to
        # Cura's centre-origin scene coordinates. Otherwise (Custom configs) we
        # keep the legacy behaviour: first object at the bed centre, grid growing
        # in +X / +Z.
        half_w, half_d, extruder_shift = self._machineGeometry()
        origin_x, origin_y, has_origin = self._resolveOrigin()
        use_origin = has_origin and half_w is not None

        op = GroupedOperation()
        for idx, node in enumerate(nodes):
            aabb = node.getBoundingBox()
            if aabb is None:
                continue
            col = idx % self._cols
            row = idx // self._cols
            center_x = (aabb.minimum.x + aabb.maximum.x) / 2
            center_z = (aabb.minimum.z + aabb.maximum.z) / 2

            if use_origin:
                # Printer coords: X grows to the right, Y grows toward the back.
                # extruder_shift recentres the plate between the two nozzles.
                x_printer = origin_x + extruder_shift + col * self._spacing_x
                y_printer = origin_y + row * self._spacing_y
                # Printer (corner origin) -> scene (centre origin). Build-plate
                # back is -Z in the scene, so Y maps to half_d - y_printer.
                target_x = x_printer - half_w
                target_z = half_d - y_printer
            else:
                target_x = col * self._spacing_x
                target_z = row * self._spacing_y

            op.addOperation(TranslateOperation(node, Vector(
                target_x - center_x,
                -aabb.minimum.y,
                target_z - center_z,
            )))

        op.push()

    # ── Machine geometry helpers ───────────────────────────────────────────────

    def _resolveOrigin(self):
        """Return (origin_x, origin_y, has_origin) for the CURRENT selection.

        A measured preset uses its calibrated bottom-left well origin. Custom
        configs have no measured origin and fall back to the legacy bed-centred
        layout, even if their grid numerically coincides with a preset.
        """
        p = _PRESETS.get(self._active_preset)
        if p is not None and "origin_x" in p and "origin_y" in p:
            return p["origin_x"], p["origin_y"], True
        return self._origin_x, self._origin_y, self._has_origin

    def _machineGeometry(self):
        """Return (half_width, half_depth, extruder_x_shift) read from the active
        machine, or (None, None, 0.0) if it cannot be resolved.

        extruder_x_shift moves the plate from extruder-0's reference frame to the
        midpoint between the two nozzles, i.e. half the nozzle X separation toward
        extruder 0. The user-measured origins are referenced to extruder 0, so the
        bottom-left well ends up centred between the two extruders.
        """
        try:
            global_stack = CuraApplication.getInstance().getGlobalContainerStack()
            if global_stack is None:
                return None, None, 0.0
            half_w = float(global_stack.getProperty("machine_width", "value")) / 2.0
            half_d = float(global_stack.getProperty("machine_depth", "value")) / 2.0

            extruder_shift = 0.0
            try:
                extruders = list(global_stack.extruderList)
                if len(extruders) >= 2:
                    off0 = float(extruders[0].getProperty("machine_nozzle_offset_x", "value"))
                    off1 = float(extruders[1].getProperty("machine_nozzle_offset_x", "value"))
                    extruder_shift = -(off1 - off0) / 2.0
            except Exception as e:
                Logger.logException("w", "WellPlateArrange: could not read extruder offsets: %s", e)

            return half_w, half_d, extruder_shift
        except Exception as e:
            Logger.logException("w", "WellPlateArrange: could not read machine geometry: %s", e)
            return None, None, 0.0
