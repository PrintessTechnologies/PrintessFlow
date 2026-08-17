# Copyright (c) 2026 Printess Technologies
# Released under the terms of the LGPLv3 or higher.

from . import PrintessFlowTester


def getMetaData():
    # No "menu_item": the plugin registers purely so it can put its own button in
    # the action bar, beside Draw Paths. An Extension entry would land in the
    # Extensions menu, which this build deliberately keeps trimmed.
    return {}


def register(app):
    return {"extension": PrintessFlowTester.PrintessFlowTester()}
