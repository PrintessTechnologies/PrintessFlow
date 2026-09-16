# Copyright (c) 2026 Printess Technologies
# Released under the terms of the LGPLv3 or higher.

from . import PrintessLicense


def getMetaData():
    return {}


def register(app):
    return {"extension": PrintessLicense.PrintessLicense()}
