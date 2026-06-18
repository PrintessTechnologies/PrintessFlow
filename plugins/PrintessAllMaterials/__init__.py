from PyQt6.QtQml import qmlRegisterType
from UM.Logger import Logger
from .AllMaterialBrandsModel import AllMaterialBrandsModel
from .PrintessProfileManager import PrintessProfileManager


def getMetaData():
    return {}


def register(app):
    qmlRegisterType(AllMaterialBrandsModel, "Cura", 1, 0, "AllMaterialBrandsModel")
    Logger.log("i", "PrintessAllMaterials: registered AllMaterialBrandsModel")

    qmlRegisterType(PrintessProfileManager, "Cura", 1, 0, "PrintessProfileManager")
    Logger.log("i", "PrintessAllMaterials: registered PrintessProfileManager")

    # Homing options driven by the Slice panel checkboxes and read by the
    # Printess post-processing scripts (PrintessLayerByLayer / PrintessOneAtATime).
    # Both default on (home every axis); the chosen state is remembered across sessions.
    prefs = app.getPreferences()
    prefs.addPreference("printess/home_xy", True)
    prefs.addPreference("printess/home_za", True)

    # Per-axis zero offsets (mm) entered next to the homing checkboxes. After
    # homing, the axis moves to its offset and that point is declared zero (G92),
    # so a positive value lifts the working zero above the homed position. Default
    # 0 reproduces the previous startup exactly.
    prefs.addPreference("printess/zero_offset_x", 0.0)
    prefs.addPreference("printess/zero_offset_y", 0.0)
    prefs.addPreference("printess/zero_offset_z", 0.0)
    prefs.addPreference("printess/zero_offset_a", 0.0)
    Logger.log("i", "PrintessAllMaterials: registered homing + zero-offset preferences")
    return {}
