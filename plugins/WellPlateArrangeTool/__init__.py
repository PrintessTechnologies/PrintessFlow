from . import WellPlateArrangeTool


def getMetaData():
    return {}


def register(app):
    return {"extension": WellPlateArrangeTool.WellPlateArrange()}
