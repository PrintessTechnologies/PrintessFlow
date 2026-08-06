# Copyright (c) 2026 Printess Technologies
# Released under the terms of the LGPLv3 or higher.

from . import PrintessPathDesigner

from UM.i18n import i18nCatalog
i18n_catalog = i18nCatalog("cura")


def getMetaData():
    return {
        "tool": {
            "name": i18n_catalog.i18nc("@label", "Path Designer"),
            "description": i18n_catalog.i18nc("@info:tooltip", "Draw lines, arcs, circles, and curves on the build plate and save them directly as G-code print paths."),
            "icon": "PathDesigner.svg",
            "tool_panel": "PathDesignerPanel.qml",
            "weight": 10,
            # Kept out of the tool column down the left edge: it is opened from
            # the Draw Paths button in the action bar instead, beside Well Plate
            # Arranger. Still a real tool, because drawing needs the mouse events
            # on the 3D view that only an active tool receives — this hides the
            # button, nothing else. UM.ToolModel skips any tool marked this way.
            "visible": False
        }
    }


def register(app):
    return {"tool": PrintessPathDesigner.PrintessPathDesigner()}
