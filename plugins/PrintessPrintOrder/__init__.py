# Copyright (c) 2026 Printess Technologies
# Released under the terms of the LGPLv3 or higher.

from . import PrintessPrintOrder


def getMetaData():
    # The menu items are registered by the Extension itself (addMenuItem), which
    # is what puts them under Extensions -> Print Order. Nothing is needed here.
    return {}


def register(app):
    return {"extension": PrintessPrintOrder.PrintessPrintOrder()}
