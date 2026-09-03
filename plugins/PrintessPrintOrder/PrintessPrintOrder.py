# Copyright (c) 2026 Printess Technologies
# Released under the terms of the LGPLv3 or higher.
#
# Lets the operator say which object on the build plate prints first.
#
# Cura already carries all of this: every CuraSceneNode has a printOrder, the
# object list can number and sort itself by it, "Print Before" / "Print After"
# already sit in the right-click and Edit menus, and the number survives a 3MF
# round trip. None of it is reachable in PrintessFlow, because the gate in
# PrintOrderManager.isUserDefinedPrintOrderEnabled also demands
# print_sequence == 'one_at_a_time', and PrintessFlow deliberately slices all at
# once and sequences the parts afterwards in PrintessOneAtATime.
#
# So this plugin opens the gate rather than building a second ordering UI.
#
# The gate is opened by patching the two static methods at runtime instead of
# overlaying cura/PrintOrderManager.py, so a stock core file stays unforked and
# a future Cura bump cannot silently clobber the change: it would fail loudly
# here instead, in cura.log. It cannot reach Cura's own one-at-a-time slicing.
# The only consumer of the ordering, OneAtATimeIterator, is constructed in one
# place, StartSliceJob, inside the print_sequence == 'one_at_a_time' branch that
# this build never takes.
#
# What the order MEANS in the g-code is PrintessOneAtATime's business: it sorts
# its parts by printOrder, and falls back to its old distance sort for anything
# left unnumbered.

import math
from typing import List, Optional, Tuple

from PyQt6.QtCore import QObject, pyqtSlot
from PyQt6.QtQml import qmlRegisterSingletonType

from UM.Application import Application
from UM.Extension import Extension
from UM.Logger import Logger
from UM.Message import Message
from UM.Scene.Selection import Selection
from UM.i18n import i18nCatalog

catalog = i18nCatalog("cura")

Point = Tuple[float, float]


# ----------------------------------------------------------------------
# Geometry
#
# Positions are read the same way PrintessOneAtATime reads them, because the two
# have to agree about what "nearest" means: scene coordinates, whose origin is
# the middle of the plate, with the front of the bed at +Z. The printer's own
# origin is therefore the FRONT-LEFT corner, at (-width/2, +depth/2).
# ----------------------------------------------------------------------

def _plate_origin():
    """The printer's 0,0 in scene coordinates. Falls back to the plate center."""
    try:
        stack = Application.getInstance().getGlobalContainerStack()
        return (-float(stack.getProperty("machine_width", "value")) / 2.0,
                float(stack.getProperty("machine_depth", "value")) / 2.0)
    except Exception:
        return (0.0, 0.0)


def _center(node) -> Optional[Point]:
    """Where a node sits on the plate, or None if it has no bounding box yet."""
    try:
        box = node.getBoundingBox()
    except Exception:
        return None
    if box is None:
        return None
    return (box.center.x, box.center.z)


def _travel_chain(nodes: List, start: Point) -> List:
    """The nodes in nearest-neighbor order, each hop measured from the last one.

    This is the order for objects nobody has placed by hand: not distance from a
    fixed corner, but distance from wherever the head just finished, which is the
    travel the printer actually makes. Nodes with no bounding box keep their
    given order at the end, since there is nothing to measure them by.
    """
    placeable = [n for n in nodes if _center(n) is not None]
    unplaceable = [n for n in nodes if _center(n) is None]

    chain = []
    current = start
    while placeable:
        nearest = min(placeable,
                      key = lambda n: math.hypot(_center(n)[0] - current[0],
                                                 _center(n)[1] - current[1]))
        placeable.remove(nearest)
        chain.append(nearest)
        current = _center(nearest)
    return chain + unplaceable


def _print_order(node) -> int:
    return int(getattr(node, "printOrder", 0) or 0)


def _extruder(node) -> int:
    """Which extruder a node prints with. Anything unreadable sorts last."""
    try:
        return int(node.callDecoration("getActiveExtruderPosition"))
    except Exception:
        return 99


# ----------------------------------------------------------------------
# The replacement for PrintOrderManager.initializePrintOrders
# ----------------------------------------------------------------------

def _initialize_print_orders(nodes: List) -> None:
    """Number the objects that do not have a number yet.

    Stock Cura hands out the next free number in whatever order the object list
    happened to build, which is the arbitrariness this feature exists to remove.
    A batch that arrives together (a project opened, several models imported at
    once, a drawing applied as a row of wells) is numbered by travel instead, so
    the list starts out saying something sensible and the operator only has to
    move the one or two objects they actually care about.

    New objects still go to the END of the list, as they do in stock Cura.
    Inserting them by position would renumber, and so silently reshuffle, an
    order somebody had already set.

    Objects are grouped by extruder first and chained by travel within each
    group, so the default numbering never interleaves the two syringes. This is
    not tidiness. A layer-by-layer print obeys these numbers in EVERY layer, and
    each crossing between extruders costs a tool change there: a retract, a park
    at the clearance height, a switch, a lower and a prime. Ordering by position
    alone would scatter a two-syringe plate into an order that pays for that
    several times a layer, where CuraEngine paid once. Anyone who does want the
    syringes interleaved can still say so by hand.
    """
    unordered = [n for n in nodes if _print_order(n) == 0]
    if not unordered:
        return

    ordered = [n for n in nodes if _print_order(n) != 0]
    if ordered:
        last = max(ordered, key = _print_order)
        start = _center(last) or _plate_origin()
        next_order = _print_order(last)
    else:
        start = _plate_origin()
        next_order = 0

    for extruder in sorted({_extruder(n) for n in unordered}):
        for node in _travel_chain([n for n in unordered if _extruder(n) == extruder], start):
            next_order += 1
            node.printOrder = next_order
            start = _center(node) or start


def _nodes() -> List:
    """The object list, in the order it is shown, which is print order."""
    try:
        return list(Application.getInstance().getObjectsModel().getNodes())
    except Exception:
        Logger.logException("w", "PrintessPrintOrder: could not read the object list")
        return []


def _applied(text: str = "") -> None:
    """Refresh the object list and drop the slice, exactly as a swap does.

    The same two steps CuraApplication._onPrintOrderChanged takes: the scene
    signal rebuilds the numbered object list, and marking the backend as needing
    a slice is what makes the new order reach the g-code. Without the second one
    the previous slice stays in the buffer and Save writes the old sequence, with
    the object list showing the new one.
    """
    application = Application.getInstance()
    try:
        scene = application.getController().getScene()
        scene.sceneChanged.emit(scene.getRoot())
        application.getBackend().needsSlicing()
        application.getBackend().tickle()
    except Exception:
        Logger.logException("w", "PrintessPrintOrder: could not refresh after the print order changed")
    if text:
        Message(text, title = catalog.i18nc("@info:title", "Print Order"), lifetime = 8).show()


def _renumber(nodes: List) -> None:
    for index, node in enumerate(nodes, 1):
        node.printOrder = index


class PrintOrderController(QObject):
    """What the object list's drag handles call.

    Registered into the Cura QML namespace so the forked ObjectItemButton.qml can
    reach it as Cura.PrintessPrintOrder. PrintOrderManager, which is the natural
    home for this, cannot take it: QML resolves slots through a class's
    meta-object, which is fixed when the class is created, so a slot added to it
    at runtime the way the two static methods are would be invisible to QML.
    """

    @pyqtSlot(int, int)
    def moveObject(self, from_index: int, to_index: int) -> None:
        """Move the row at from_index so that it becomes the row at to_index.

        Indices are object list rows, and the list is sorted by print order, so a
        row index IS a print position. Everything is renumbered afterwards rather
        than only the two rows touched, which keeps the numbering 1..n with no
        gaps or ties for the rows that shuffled up or down to make room.
        """
        nodes = _nodes()
        if not 0 <= from_index < len(nodes) or not 0 <= to_index < len(nodes):
            Logger.log("w", "PrintessPrintOrder: ignoring a move from %s to %s in a list of %s",
                       from_index, to_index, len(nodes))
            return
        if from_index == to_index:
            return

        nodes.insert(to_index, nodes.pop(from_index))
        _renumber(nodes)
        _applied()


_print_order_controller = None  # kept alive for as long as QML can call into it


def _get_print_order_controller(*args) -> PrintOrderController:
    global _print_order_controller
    if _print_order_controller is None:
        _print_order_controller = PrintOrderController()
    return _print_order_controller


def _install_qml_controller() -> None:
    """Expose the controller as Cura.PrintessPrintOrder.

    Registered from here rather than from CuraApplication because this is a
    plugin, and it lands in time: plugins are loaded during
    startSplashWindowPhase, while the QML that uses the type is not loaded until
    initializeEngine, much later in run().
    """
    qmlRegisterSingletonType(PrintOrderController, "Cura", 1, 0,
                             _get_print_order_controller, "PrintessPrintOrder")


def _install_print_order_unlock() -> None:
    """Open Cura's user-defined print order for this build."""
    from cura.PrintOrderManager import PrintOrderManager

    PrintOrderManager.isUserDefinedPrintOrderEnabled = staticmethod(lambda: True)
    PrintOrderManager.initializePrintOrders = staticmethod(_initialize_print_orders)
    # Said out loud because nothing else about this feature is: it turns on menu
    # items and a numbering that are easy to miss, so "is it installed" and "did
    # I find it" are two different questions and the log should answer the first.
    Logger.log("i", "PrintessPrintOrder: print order enabled. The object list is numbered,"
                    " Print Before / Print After are live in the right-click and Edit menus,"
                    " and Extensions -> Print Order holds First / Last / Reorder by travel.")


# The object list is where the print order is shown and where it is changed, and
# stock Cura keeps it collapsed behind a chevron nobody has a reason to open. A
# numbered list that is never seen is the same as no feature at all, which is
# exactly how this landed the first time it was installed.
_OBJECT_LIST_PREFERENCE = "cura/show_list_of_objects"
_OPENED_ONCE_PREFERENCE = "printess/object_list_opened_once"


def _open_object_list_once() -> None:
    """Open the object list the first time this build runs, and never again.

    Once, not every launch: closing the panel has to stick. The guard preference
    is what remembers, and it is written to cura.cfg because its value then
    differs from its default, which is the only thing Preferences persists.

    Both preferences are registered here first. Plugins are loaded from
    QtApplication.startSplashWindowPhase, which runs BEFORE CuraApplication
    registers cura/show_list_of_objects further down its own
    startSplashWindowPhase, so at this moment the key does not exist yet and
    setValue on it would be dropped with a warning. Registering it early is
    harmless: Cura's later addPreference on an existing key only sets the
    default, and it leaves the value alone unless the value still equals the old
    default, which after the setValue below it does not.
    """
    preferences = Application.getInstance().getPreferences()

    preferences.addPreference(_OPENED_ONCE_PREFERENCE, False)
    if preferences.getValue(_OPENED_ONCE_PREFERENCE):
        return

    preferences.addPreference(_OBJECT_LIST_PREFERENCE, False)
    preferences.setValue(_OBJECT_LIST_PREFERENCE, True)
    preferences.setValue(_OPENED_ONCE_PREFERENCE, True)
    Logger.log("i", "PrintessPrintOrder: opened the object list for this first run,"
                    " so the print order numbering is visible. Closing it will stick.")


class PrintessPrintOrder(Extension):
    def __init__(self) -> None:
        super().__init__()
        self.setMenuName(catalog.i18nc("@item:inmenu", "Print Order"))
        # Bubbling an object up with "Print Before" swaps it one place at a time,
        # which is several trips through the right-click menu for the job this
        # was asked for: a drawn purge line, added last and wanted first.
        self.addMenuItem(catalog.i18nc("@item:inmenu", "Print Selected First"),
                         self.printSelectedFirst)
        self.addMenuItem(catalog.i18nc("@item:inmenu", "Print Selected Last"),
                         self.printSelectedLast)
        self.addMenuItem(catalog.i18nc("@item:inmenu", "Reorder by Travel Distance"),
                         self.reorderByTravel)

        try:
            _install_print_order_unlock()
        except Exception:
            # Loudly in the log, silently in the UI: without this the object list
            # simply keeps its stock behavior, which is worth knowing about but
            # not worth a dialog on startup.
            Logger.logException("e", "PrintessPrintOrder: could not enable the print order UI")

        try:
            _install_qml_controller()
        except Exception:
            # The menu items and Print Before / Print After still work without it.
            # Only the object list's drag handles go dead, and they say so in the
            # log rather than silently doing nothing when dropped.
            Logger.logException("e", "PrintessPrintOrder: could not register the QML controller,"
                                     " so dragging rows in the object list will not work")

        try:
            _open_object_list_once()
        except Exception:
            # Kept apart from the unlock: failing to open a panel must never cost
            # the feature itself, which works whether or not the list is showing.
            Logger.logException("w", "PrintessPrintOrder: could not open the object list")

    # ------------------------------------------------------------------
    # Menu items
    # ------------------------------------------------------------------

    def printSelectedFirst(self) -> None:
        self._moveSelected(to_front = True)

    def printSelectedLast(self) -> None:
        self._moveSelected(to_front = False)

    def reorderByTravel(self) -> None:
        """Throw away the numbering and lay it out by travel again.

        The escape hatch from a hand-set order, and the way to ask for the
        shortest route when the order does not matter. It renumbers everything,
        so it is the thing to do BEFORE pinning an object to the front.
        """
        nodes = _nodes()
        if not nodes:
            return
        for node in nodes:
            node.printOrder = 0
        _initialize_print_orders(nodes)
        _applied(catalog.i18nc("@info:status", "Print order set by travel distance."))

    # ------------------------------------------------------------------

    def _moveSelected(self, to_front: bool) -> None:
        nodes = _nodes()
        selected = [n for n in nodes if Selection.isSelected(n)]
        if not selected:
            Message(catalog.i18nc("@info:status",
                                  "Select an object on the build plate first."),
                    title = catalog.i18nc("@info:title", "Print Order"),
                    lifetime = 8).show()
            return

        rest = [n for n in nodes if n not in selected]
        # Relative order is kept on both sides, so moving two objects to the
        # front does not also shuffle them against each other.
        selected.sort(key = _print_order)
        rest.sort(key = _print_order)

        _renumber(selected + rest if to_front else rest + selected)
        _applied()
