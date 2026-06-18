# Copyright (c) 2018 Ultimaker B.V.
# Cura is released under the terms of the LGPLv3 or higher.

from typing import Optional, List

from PyQt6.QtCore import pyqtProperty, pyqtSignal, pyqtSlot, QObject

from UM.Logger import Logger
from UM.Preferences import Preferences
from UM.Resources import Resources

from UM.i18n import i18nCatalog
from cura.Settings.SettingVisibilityPreset import SettingVisibilityPreset

catalog = i18nCatalog("cura")


class SettingVisibilityPresetsModel(QObject):
    onItemsChanged = pyqtSignal()
    activePresetChanged = pyqtSignal()

    Version = 2

    def __init__(self, preferences: Preferences, parent = None) -> None:
        super().__init__(parent)

        self._items = []  # type: List[SettingVisibilityPreset]

        self._populate()

        self._preferences = preferences

        self._preferences.addPreference("cura/active_setting_visibility_preset", "printess_v1.0")

        printess_item = self.getVisibilityPresetById("printess_v1.0")
        printess_visible_settings = ";".join(printess_item.settings) if printess_item is not None else ""
        self._preferences.addPreference("cura/custom_visible_settings", printess_visible_settings)
        self._preferences.preferenceChanged.connect(self._onPreferencesChanged)

        stored_preset_id = self._preferences.getValue("cura/active_setting_visibility_preset")
        self._active_preset_item = self.getVisibilityPresetById(stored_preset_id)
        if self._active_preset_item is None:
            # Stored preset no longer exists (e.g. "basic" or "custom" which were removed) — fall back
            self._active_preset_item = self.getVisibilityPresetById("printess_v1.0")
            if self._active_preset_item is None and self._items:
                self._active_preset_item = self._items[0]
            if self._active_preset_item is not None:
                self._preferences.setValue("cura/active_setting_visibility_preset", self._active_preset_item.presetId)

        # Always apply the stored preset's settings on startup so the stored selection is honored
        # regardless of what general/visible_settings contains (which may match a different preset)
        if self._active_preset_item is not None:
            self._preferences.setValue("general/visible_settings", ";".join(self._active_preset_item.settings))

        self.activePresetChanged.emit()

    def getVisibilityPresetById(self, item_id: str) -> Optional[SettingVisibilityPreset]:
        result = None
        for item in self._items:
            if item.presetId == item_id:
                result = item
                break
        return result

    def _populate(self) -> None:
        from cura.CuraApplication import CuraApplication
        items = []  # type: List[SettingVisibilityPreset]
        for file_path in Resources.getAllResourcesOfType(CuraApplication.ResourceTypes.SettingVisibilityPreset):
            setting_visibility_preset = SettingVisibilityPreset()
            try:
                setting_visibility_preset.loadFromFile(file_path)
            except Exception:
                Logger.logException("e", "Failed to load setting preset %s", file_path)

            items.append(setting_visibility_preset)

        # Add the "all" visibility:
        all_setting_visibility_preset = SettingVisibilityPreset(preset_id = "all", name = "All", weight = 9001)
        all_setting_visibility_preset.setSettings(list(CuraApplication.getInstance().getMachineManager().getAllSettingKeys()))
        items.append(all_setting_visibility_preset)
        # Sort them on weight (and if that fails, use ID)
        items.sort(key = lambda k: (int(k.weight), k.presetId))

        self.setItems(items)

    @pyqtProperty("QVariantList", notify = onItemsChanged)
    def items(self) -> List[SettingVisibilityPreset]:
        return self._items

    def setItems(self, items: List[SettingVisibilityPreset]) -> None:
        if self._items != items:
            self._items = items
            self.onItemsChanged.emit()

    @pyqtSlot(str)
    def setActivePreset(self, preset_id: str) -> None:
        if self._active_preset_item is not None and preset_id == self._active_preset_item.presetId:
            Logger.log("d", "Same setting visibility preset [%s] selected, do nothing.", preset_id)
            return

        preset_item = self.getVisibilityPresetById(preset_id)
        if preset_item is None:
            Logger.log("w", "Tried to set active preset to unknown id [%s]", preset_id)
            return

        need_to_save_to_custom = self._active_preset_item is None or (self._active_preset_item.presetId == "custom" and preset_id != "custom")
        if need_to_save_to_custom:
            # Save the current visibility settings to custom
            current_visibility_string = self._preferences.getValue("general/visible_settings")
            if current_visibility_string:
                self._preferences.setValue("cura/custom_visible_settings", current_visibility_string)

        new_visibility_string = ";".join(preset_item.settings)
        if preset_id == "custom":
            # Get settings from the stored custom data
            new_visibility_string = self._preferences.getValue("cura/custom_visible_settings")
            if new_visibility_string is None:
                new_visibility_string = self._preferences.getValue("general/visible_settings")
        self._preferences.setValue("general/visible_settings", new_visibility_string)

        self._preferences.setValue("cura/active_setting_visibility_preset", preset_id)
        self._active_preset_item = preset_item
        self.activePresetChanged.emit()

    @pyqtProperty(str, notify = activePresetChanged)
    def activePreset(self) -> str:
        if self._active_preset_item is not None:
            return self._active_preset_item.presetId
        return ""

    def _onPreferencesChanged(self, name: str) -> None:
        if name != "general/visible_settings":
            return

        # Find the preset that matches with the current visible settings setup
        visibility_string = self._preferences.getValue("general/visible_settings")
        if not visibility_string:
            return

        visibility_set = set(visibility_string.split(";"))
        matching_preset_item = None
        for item in self._items:
            if item.presetId == "custom":
                continue
            if set(item.settings) == visibility_set:
                matching_preset_item = item
                break

        item_to_set = self._active_preset_item
        if matching_preset_item is not None:
            item_to_set = matching_preset_item

        if self._active_preset_item is None or self._active_preset_item.presetId != item_to_set.presetId:
            self._active_preset_item = item_to_set
            if self._active_preset_item is not None:
                self._preferences.setValue("cura/active_setting_visibility_preset", self._active_preset_item.presetId)
            self.activePresetChanged.emit()
