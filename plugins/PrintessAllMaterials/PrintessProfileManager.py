import json
from PyQt6.QtCore import QObject, pyqtSlot, QTimer
from PyQt6.QtQml import QQmlEngine
from UM.Logger import Logger
import cura.CuraApplication
from cura.Machines.ContainerTree import ContainerTree


class PrintessProfileManager(QObject):
    """QML-accessible singleton that creates custom dispense tip profiles.

    Bypasses the QML→Python QVariantMap round-trip that makes
    QualityManagementModel.duplicateQualityChanges unreliable from inside a
    Popup that is not the Preferences page.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        QQmlEngine.setObjectOwnership(self, QQmlEngine.ObjectOwnership.CppOwnership)

    @pyqtSlot(str, str, str, float)
    def createTipProfile(self, name: str, source_name: str, color: str, line_width: float) -> None:
        """Duplicate source_name profile with new name and colour, then activate it.

        If line_width > 0 the new profile's line_width (extruder containers) and
        layer_height / layer_height_0 (global container, = round(7/8 * lw, 2)) are
        overridden before the containers are added to the registry.
        """
        app = cura.CuraApplication.CuraApplication.getInstance()
        container_registry = app.getContainerRegistry()

        unique_name = container_registry.uniqueName(name)

        # Save colour to the UM.Preferences key that all QML getCustomTipColor
        # functions read from ("printess/tip_colors").
        prefs = app.getPreferences()
        prefs.addPreference("printess/tip_colors", "{}")
        try:
            raw = prefs.getValue("printess/tip_colors") or "{}"
            colors = json.loads(raw)
            colors[unique_name] = color
            prefs.setValue("printess/tip_colors", json.dumps(colors))
        except Exception as exc:
            Logger.log("w", "PrintessProfileManager: saveColor failed: %s", exc)

        # Locate source group; fall back to the first available group.
        groups = ContainerTree.getInstance().getCurrentQualityChangesGroups()
        source_group = next((g for g in groups if g.name == source_name), None)
        if source_group is None and groups:
            source_group = groups[0]
        if source_group is None:
            Logger.log("w", "PrintessProfileManager: no quality changes groups available")
            return

        # Duplicate global container + all extruder containers.
        global_metadata = source_group.metadata_for_global
        all_metadata = [global_metadata] + list(source_group.metadata_per_extruder.values())
        layer_height = line_width if line_width > 0 else None

        for metadata in all_metadata:
            containers = container_registry.findContainers(id=metadata["id"])
            if not containers:
                continue
            container = containers[0]
            new_id = container_registry.uniqueName(container.getId())
            new_container = container.duplicate(new_id, unique_name)

            if line_width > 0:
                if metadata is global_metadata:
                    new_container.setProperty("layer_height",   "value", layer_height)
                    new_container.setProperty("layer_height_0", "value", layer_height)
                else:
                    new_container.setProperty("line_width", "value", line_width)

            container_registry.addContainer(new_container)

        Logger.log("d", "PrintessProfileManager: created '%s', activating in 300ms", unique_name)
        QTimer.singleShot(300, lambda f=unique_name: self._activate(f))

    # Nordson tip line widths — mirrors tipDataMap in CustomPrintSetup.qml
    _NORDSON_LINE_WIDTHS = {
        "Nordson Olive 1.54mm ID":    1.54,
        "Nordson Amber 1.36mm ID":    1.36,
        "Nordson Green 0.84mm ID":    0.84,
        "Nordson Pink 0.61mm ID":     0.61,
        "Nordson Purple 0.51mm ID":   0.51,
        "Nordson Blue 0.41mm ID":     0.41,
        "Nordson Orange 0.33mm ID":   0.33,
        "Nordson Red 0.25mm ID":      0.25,
        "Nordson Clear 0.20mm ID":    0.20,
        "Nordson Lavender 0.15mm ID": 0.15,
        "Nordson Yellow 0.10mm ID":   0.10,
    }

    _PER_EXTRUDER_DEFAULTS = {
        "cool_fan_speed":                          0,
        "infill_sparse_density":                   100.0,
        "infill_pattern":                          "grid",
        "zig_zaggify_infill":                      True,
        "infill_angles":                           "[45, 90]",
        "infill_before_walls":                     True,
        "min_infill_area":                         0,
        "material_flow":                           100,
        "material_flow_layer_0":                   100,
        "speed_print":                             4.0,
        "speed_travel":                            4.0,
        "speed_z_hop":                             4.0,
        "skin_support_speed":                      4.0,
        "speed_equalize_flow_width_factor":        100.0,
        "retraction_enable":                       True,
        "retract_at_layer_change":                 False,
        "retraction_amount":                       0.1,
        "retraction_speed":                        4.0,
        "retraction_extra_prime_amount":           0,
        "retraction_hop":                          0,
        "retraction_hop_enabled":                  False,
        "retraction_hop_after_extruder_switch":    False,
        "retraction_hop_after_extruder_switch_height": 0,
        "switch_extruder_retraction_speeds":       4.0,
        "switch_extruder_retraction_amount":       0,
    }

    @pyqtSlot(int, str)
    def resetTipToDefaults(self, extruder_index: int, tip_name: str) -> None:
        """Reset one extruder's settings to the Nordson tip install defaults.

        For each key:
          1. removeInstance from userChanges  → strips user override, fires
             propertyChanged up the stack so the UI updates immediately.
          2. setProperty on qualityChanges    → ensures the correct value sits
             at that level regardless of prior profile state.

        layer_height / layer_height_0 live on the global machine stack and are
        handled separately.  No updateQualityChanges() call is needed or wanted —
        that would persist any other pending user changes into the profile.
        """
        app = cura.CuraApplication.CuraApplication.getInstance()
        active_machine = app.getMachineManager().activeMachine
        if active_machine is None:
            Logger.log("w", "PrintessProfileManager.resetTipToDefaults: no active machine")
            return
        if extruder_index >= len(active_machine.extruderList):
            Logger.log("w", "PrintessProfileManager.resetTipToDefaults: bad extruder index %d", extruder_index)
            return

        extruder = active_machine.extruderList[extruder_index]
        uc = extruder.userChanges
        qc = extruder.qualityChanges

        if qc is None or qc.getId() in ("empty_quality_changes", "empty"):
            Logger.log("w", "PrintessProfileManager.resetTipToDefaults: no quality_changes for extruder %d", extruder_index)
            return

        # Step 1: clear ALL extruder user overrides so nothing in userChanges
        # shadows what we are about to write into quality_changes.
        uc.clear()

        # Step 2: remove every key from quality_changes that is NOT in our
        # explicit defaults set.  Auto-save (updateQualityChanges) writes child
        # overrides — retraction_retract_speed, wall_0_material_flow, etc. —
        # directly into quality_changes, bypassing userChanges entirely.  Removing
        # those keys lets Cura fall back to the formula value ("= retraction_speed",
        # "= material_flow", …), which is the correct "recalculate" behaviour.
        keep_keys = set(self._PER_EXTRUDER_DEFAULTS.keys()) | {"line_width"}
        for key in list(qc.getAllKeys()):
            if key not in keep_keys:
                qc.removeInstance(key)

        # Step 3: write correct install defaults for the parent keys.
        for key, value in self._PER_EXTRUDER_DEFAULTS.items():
            qc.setProperty(key, "value", value)

        if tip_name in self._NORDSON_LINE_WIDTHS:
            lw = self._NORDSON_LINE_WIDTHS[tip_name]
            qc.setProperty("line_width", "value", lw)

            # layer_height / layer_height_0 live on the global machine stack.
            lh = lw
            global_uc = active_machine.userChanges
            global_qc = active_machine.qualityChanges
            global_uc.removeInstance("layer_height")
            global_uc.removeInstance("layer_height_0")
            if global_qc is not None and global_qc.getId() not in ("empty_quality_changes", "empty"):
                global_qc.setProperty("layer_height",   "value", lh)
                global_qc.setProperty("layer_height_0", "value", lh)

        Logger.log("d", "PrintessProfileManager.resetTipToDefaults: reset extruder %d for '%s'", extruder_index, tip_name)

    @pyqtSlot(int)
    def saveExtruderAsDefault(self, extruder_index: int) -> None:
        """Move this extruder's unsaved userChanges into quality_changes, leaving
        the other extruder's quality_changes untouched."""
        app = cura.CuraApplication.CuraApplication.getInstance()
        active_machine = app.getMachineManager().activeMachine
        if active_machine is None:
            return
        if extruder_index >= len(active_machine.extruderList):
            return

        extruder = active_machine.extruderList[extruder_index]
        qc = extruder.qualityChanges
        if qc is None or qc.getId() in ("empty_quality_changes", "empty"):
            return

        for key in list(extruder.userChanges.getAllKeys()):
            value = extruder.userChanges.getProperty(key, "value")
            qc.setProperty(key, "value", value)
        extruder.userChanges.clear()
        Logger.log("d", "PrintessProfileManager.saveExtruderAsDefault: saved extruder %d", extruder_index)

    @pyqtSlot(int, int)
    def mirrorExtruder(self, source_index: int, target_index: int) -> None:
        """Copy all settings from source extruder's qualityChanges + userChanges onto target's qualityChanges."""
        app = cura.CuraApplication.CuraApplication.getInstance()
        active_machine = app.getMachineManager().activeMachine
        if active_machine is None or len(active_machine.extruderList) <= max(source_index, target_index):
            Logger.log("w", "PrintessProfileManager.mirrorExtruder: invalid extruder indices %d→%d", source_index, target_index)
            return

        src = active_machine.extruderList[source_index]
        dst = active_machine.extruderList[target_index]
        qc_dst = dst.qualityChanges

        if qc_dst is None or qc_dst.getId() in ("empty_quality_changes", "empty"):
            Logger.log("w", "PrintessProfileManager.mirrorExtruder: target extruder %d has no quality_changes", target_index)
            return

        # Collect source settings — qualityChanges first, userChanges on top
        to_copy = {}
        for key in src.qualityChanges.getAllKeys():
            to_copy[key] = src.qualityChanges.getProperty(key, "value")
        for key in src.userChanges.getAllKeys():
            to_copy[key] = src.userChanges.getProperty(key, "value")

        # Clear target's unsaved overrides
        dst.userChanges.clear()

        # Remove keys from target's qualityChanges that source doesn't have
        for key in list(qc_dst.getAllKeys()):
            if key not in to_copy:
                qc_dst.removeInstance(key)

        # Write source's settings into target's qualityChanges
        for key, value in to_copy.items():
            qc_dst.setProperty(key, "value", value)

        Logger.log("d", "PrintessProfileManager.mirrorExtruder: copied %d settings from E%d to E%d",
                   len(to_copy), source_index + 1, target_index + 1)

    def _activate(self, name: str) -> None:
        machine_manager = cura.CuraApplication.CuraApplication.getInstance().getMachineManager()
        for group in ContainerTree.getInstance().getCurrentQualityChangesGroups():
            if group.name == name:
                machine_manager.setQualityChangesGroup(group)
                Logger.log("d", "PrintessProfileManager: activated '%s'", name)
                return
        Logger.log("w", "PrintessProfileManager: '%s' not found after 300ms", name)
