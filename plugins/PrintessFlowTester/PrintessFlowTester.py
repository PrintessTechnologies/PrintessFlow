# Copyright (c) 2026 Printess Technologies
# Released under the terms of the LGPLv3 or higher.
#
# Flow Rate Tester: prints a strip of identical 30 mm lines, one per flow value,
# so a user can pick a flow off a real print instead of guessing and re-slicing.
#
# Deliberately NOT a post-processing script. A post-processing script only ever
# edits g-code CuraEngine has already produced, so it would need an object on
# the plate and a Slice press to make a test strip that has nothing to do with
# either. Instead this follows the Path Designer's shape: a button in the action
# bar, a dialog, and g-code written straight to a file. Nothing about slicing or
# about the scripts that run on every real print is touched.

import os
from typing import Dict, List

from PyQt6.QtCore import QObject, pyqtSlot, pyqtProperty, pyqtSignal, QUrl

from UM.Application import Application
from UM.Extension import Extension
from UM.Logger import Logger
from UM.Message import Message

from . import FlowTestGenerator


class PrintessFlowTester(Extension, QObject):

    settingsChanged = pyqtSignal()

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        Extension.__init__(self)

        self._button_view = None
        self._dialog = None

        self._addActionBarButtonWhenReady()

    # ------------------------------------------------------------------
    # Action bar button
    # ------------------------------------------------------------------

    def _addActionBarButtonWhenReady(self):
        """Put a Flow Test button in the action bar, beside Draw Paths.

        Registered against "saveButton", the slot the Well Plate Arranger and
        the Path Designer both use, so all three land in one row. Waits for
        mainWindowChanged because createQmlComponent needs the QML engine, which
        does not exist while plugins are still being constructed.
        """
        try:
            from cura.CuraApplication import CuraApplication
            CuraApplication.getInstance().mainWindowChanged.connect(self._createActionBarButton)
        except Exception:
            Logger.logException("w", "FlowTester: could not hook the action bar button")

    def _createActionBarButton(self):
        if self._button_view is not None:
            return          # mainWindowChanged can fire more than once
        try:
            from cura.CuraApplication import CuraApplication
            application = CuraApplication.getInstance()
            qml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "FlowTesterButton.qml")
            self._button_view = application.createQmlComponent(qml_path, {"manager": self})
            if self._button_view is not None:
                application.addAdditionalComponent("saveButton", self._button_view)
        except Exception:
            Logger.logException("w", "FlowTester: could not create the action bar button")

    @pyqtSlot()
    def showDialog(self):
        """Open the table. Built on first use and kept, so typed rows survive.

        The dialog is created against the plugin's own QML file rather than
        declared inside the button, because the button is a small Item living in
        a Row in the action bar: a Dialog parented there inherits its clipping
        and its size constraints.
        """
        try:
            from cura.CuraApplication import CuraApplication
            application = CuraApplication.getInstance()
            if self._dialog is None:
                qml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "FlowTesterDialog.qml")
                self._dialog = application.createQmlComponent(qml_path, {"manager": self})
            if self._dialog is not None:
                # Settings may have moved since it was last opened (a different
                # dispense tip, a changed flow), and every number the dialog
                # shows is derived from them.
                self.settingsChanged.emit()
                self._dialog.show()
        except Exception:
            Logger.logException("w", "FlowTester: could not open the dialog")

    # ------------------------------------------------------------------
    # Live settings
    # ------------------------------------------------------------------

    def _globalStack(self):
        return Application.getInstance().getGlobalContainerStack()

    def _extruderStack(self, index: int):
        stack = self._globalStack()
        if stack is None:
            return None
        try:
            extruders = stack.extruderList
            return extruders[index] if 0 <= index < len(extruders) else None
        except Exception:
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

    def _globalProperty(self, key: str, fallback: float) -> float:
        stack = self._globalStack()
        if stack is None:
            return fallback
        try:
            value = stack.getProperty(key, "value")
            return float(value) if value is not None else fallback
        except Exception:
            return fallback

    def _extruderFlag(self, index: int, key: str, fallback: bool) -> bool:
        extruder = self._extruderStack(index)
        if extruder is None:
            return fallback
        try:
            value = extruder.getProperty(key, "value")
            return bool(value) if value is not None else fallback
        except Exception:
            return fallback

    def _homingPreference(self, key: str) -> bool:
        """Read a printess/home_* preference the way PrintessOneAtATime does.

        Missing means True there, and it has to mean True here too: a user who
        has never touched the homing checkbox gets XY homing on a real print, so
        a test strip that quietly skipped it would run against a different datum.
        """
        try:
            value = Application.getInstance().getPreferences().getValue(key)
        except Exception:
            return True
        if value is None:
            return True
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes")

    def _offsetPreference(self, key: str) -> float:
        try:
            return float(Application.getInstance().getPreferences().getValue(key))
        except (TypeError, ValueError, AttributeError):
            return 0.0

    def _collectSettings(self, extruder: int) -> Dict:
        """Everything the generator needs, read LIVE off the active profile.

        Read at press time rather than when the dialog was opened: changing the
        dispense tip or the flow and pressing Save G-Code again should be enough
        to get new g-code, the same rule the Path Designer follows.
        """
        return {
            "extruder": extruder,
            "machine_width": self._globalProperty("machine_width", 124.0),
            "machine_depth": self._globalProperty("machine_depth", 86.1),
            "layer_height_0": self._globalProperty("layer_height_0", 0.2),

            "line_width": self._extruderProperty(extruder, "line_width", 0.4),
            # GENERAL speed and GENERAL flow, as a pair.
            #
            # speed_print and material_flow, deliberately NOT speed_wall_0 /
            # wall_0_material_flow and NOT the speed_print_layer_0 /
            # material_flow_layer_0 / initial_layer_line_width_factor first-layer
            # set. The tester exists to isolate the one knob the user will type a
            # number into, so the only flow in the extrusion is the table value
            # and the speed comes from the same general level.
            #
            # material_flow is read for DISPLAY ONLY - see
            # FlowTestGenerator.e_per_mm, which never multiplies by it.
            "speed": self._extruderProperty(extruder, "speed_print", 4.0),
            "material_flow": self._extruderProperty(extruder, "material_flow", 100.0),
            "travel_speed": self._extruderProperty(extruder, "speed_travel", 4.0),
            "z_hop_speed": self._extruderProperty(extruder, "speed_z_hop", 4.0),

            "material_diameter": self._extruderProperty(extruder, "material_diameter", 4.76),
            "nozzle_offset_x": self._extruderProperty(extruder, "machine_nozzle_offset_x", 0.0),
            "nozzle_offset_y": self._extruderProperty(extruder, "machine_nozzle_offset_y", 0.0),

            "retraction_enabled": self._extruderFlag(extruder, "retraction_enable", True),
            "retraction_amount": self._extruderProperty(extruder, "retraction_amount", 0.1),
            "retract_speed": self._extruderProperty(extruder, "retraction_retract_speed", 4.0),
            "prime_speed": self._extruderProperty(extruder, "retraction_prime_speed", 4.0),
            "park_lift": self._globalProperty("printess_park_lift", FlowTestGenerator.PARK_LIFT),

            "home_xy": self._homingPreference("printess/home_xy"),
            "zero_offset_x": self._offsetPreference("printess/zero_offset_x"),
            "zero_offset_y": self._offsetPreference("printess/zero_offset_y"),

            "tip_name": self._activeTipName(),
        }

    def _activeTipName(self) -> str:
        stack = self._globalStack()
        if stack is None:
            return ""
        try:
            return str(stack.qualityChanges.getName())
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Properties the dialog reads
    # ------------------------------------------------------------------

    @pyqtProperty(int, notify = settingsChanged)
    def extruderCount(self) -> int:
        stack = self._globalStack()
        if stack is None:
            return 1
        try:
            return max(1, len(stack.extruderList))
        except Exception:
            return 1

    @pyqtProperty(int, constant = True)
    def maxLines(self) -> int:
        return FlowTestGenerator.MAX_LINES

    @pyqtProperty(float, constant = True)
    def lineLength(self) -> float:
        return FlowTestGenerator.LINE_LENGTH

    @pyqtProperty(float, constant = True)
    def lineGap(self) -> float:
        return FlowTestGenerator.LINE_GAP

    @pyqtSlot(int, result = "QVariantMap")
    def summaryFor(self, extruder: int) -> Dict:
        """The settings line shown above the table, so nothing is hidden.

        profileFlow is the GENERAL flow (material_flow), which is the field the
        user will type their answer into. It is shown for orientation and is not
        applied to the extrusion; no initialFlow is reported any more because
        none is applied either.
        """
        cfg = self._collectSettings(extruder)
        return {
            "tipName": cfg["tip_name"],
            "lineWidth": cfg["line_width"],
            "layerHeight": cfg["layer_height_0"],
            "speed": FlowTestGenerator.print_speed(cfg),
            "profileFlow": cfg["material_flow"],
            "materialDiameter": cfg["material_diameter"],
        }

    @pyqtSlot(int, float, result = float)
    def plungerForFlow(self, extruder: int, flow: float) -> float:
        """Plunger travel in mm over one 30 mm line at this flow.

        Shown per row so the table says what each line will actually deposit,
        not only what was typed.
        """
        cfg = self._collectSettings(extruder)
        return FlowTestGenerator.LINE_LENGTH * FlowTestGenerator.e_per_mm(cfg, flow)

    @pyqtSlot(int, int, result = "QVariantMap")
    def checkFit(self, extruder: int, count: int) -> Dict:
        ok, message = FlowTestGenerator.fits_on_plate(count, self._collectSettings(extruder))
        return {"ok": ok, "message": message}

    # ------------------------------------------------------------------
    # Writing the file
    # ------------------------------------------------------------------

    @pyqtSlot(QUrl, int, "QVariantList", result = bool)
    def saveGcode(self, file_url: QUrl, extruder: int, flows: "List") -> bool:
        """Generate the strip and write it. Returns whether it was written.

        Failures are reported as a Message rather than only logged: this is
        reached from a Save button, and a button that appears to do nothing is
        the worst outcome available.
        """
        try:
            values = [float(f) for f in flows]
        except (TypeError, ValueError):
            self._error("Every line needs a flow value.")
            return False

        if not values:
            self._error("Add at least one line to the table.")
            return False

        cfg = self._collectSettings(extruder)

        ok, message = FlowTestGenerator.fits_on_plate(len(values), cfg)
        if not ok:
            self._error(message)
            return False

        path = file_url.toLocalFile() if file_url.isLocalFile() else file_url.toString()
        if not path:
            self._error("No file name was given.")
            return False

        try:
            gcode = FlowTestGenerator.generate(values, cfg)
        except Exception:
            Logger.logException("e", "FlowTester: could not generate the g-code")
            self._error("The g-code could not be generated. See cura.log for details.")
            return False

        try:
            with open(path, "w", encoding = "utf-8", newline = "\n") as handle:
                handle.write(gcode)
        except OSError as exc:
            Logger.log("e", "FlowTester: could not write %s: %s", path, exc)
            self._error("Could not write {0}: {1}".format(os.path.basename(path), exc))
            return False

        Message(
            text = "Flow test saved: {0} lines at {1:.0f} mm on extruder {2}.".format(
                len(values), FlowTestGenerator.LINE_LENGTH, extruder + 1),
            title = "Flow Rate Tester",
            lifetime = 12,
        ).show()
        return True

    def _error(self, text: str):
        Message(text = text, title = "Flow Rate Tester",
                message_type = Message.MessageType.ERROR, lifetime = 0).show()
