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

    # XY homing option driven by the Slice panel checkbox and read by the Printess
    # post-processing scripts (PrintessLayerByLayer / PrintessOneAtATime). Defaults on;
    # the chosen state is remembered across sessions. There is deliberately no Z/A
    # equivalent: those axes are never homed, because the operator jogs the extruder
    # they are using down to the print surface and zeroes it with a manual G92.
    prefs = app.getPreferences()
    prefs.addPreference("printess/home_xy", True)

    # Per-axis zero offsets (mm) entered next to the homing checkbox. After homing, the
    # axis moves to its offset and that point is declared zero (G92), so a positive value
    # shifts the working zero away from the homed position. Default 0 keeps the post-home
    # position as the origin. X/Y only, for the same reason as above.
    prefs.addPreference("printess/zero_offset_x", 0.0)
    prefs.addPreference("printess/zero_offset_y", 0.0)
    Logger.log("i", "PrintessAllMaterials: registered homing + zero-offset preferences")
    return {}
