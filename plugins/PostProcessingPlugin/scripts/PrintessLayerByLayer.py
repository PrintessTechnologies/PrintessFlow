# Copyright (c) 2024 Printess Technologies
# Printess Layer by Layer Post Processing Script for Cura
#
# T0 scope: E -> B
# T1 scope: E -> C, Z -> A
#
# Temperature and fan commands are stripped entirely.
# Tool change sequences: retract, park active extruder, switch, lower new extruder, prime.
# Park height = the absolute Print Level Clearance height (PARK_LIFT); on resume the new
# tool lowers from there to its layer height. The fixed height clears tall obstacles such
# as well-plate walls.

import re
import math
from collections import deque
from ..Script import Script
from UM.Logger import Logger

PARK_LIFT = 30.0  # absolute park height (mm); fallback if the setting is unreadable

# Startup-datum constants (see _startup_datum). Only XY is homed: after the printer's
# custom G28 the plate is centered under the nozzle, and the datum G92 declares the
# zero-offset origin relative to that without moving. Z and A are never homed, so they
# have no machine-defined post-home position; the operator zeroes the axis of the extruder
# they are using with a manual G92 before starting the print.
# This is the head's post-G28 position expressed in Cura's build-plate frame, whose origin
# is the front-left plate corner (machine_center_is_zero = False). It is what couples the
# two coordinate systems: change it and every print shifts on the plate by the difference.
# It is a MEASURED value, dialed in from test prints, so it need not come out at exactly
# (machine_width / 2, machine_depth / 2). Where it deviates, that is the amount by which
# G28 does not leave the head over the true plate center, and Cura's on-screen plate is
# offset from the physical one by the same amount. Keep all three copies of these
# constants in step: PrintessOneAtATime, PrintessLayerByLayer, FlowTestGenerator.
PLATE_CENTER_X = 62.00   # mm from the X endstop: build-plate center after G28
PLATE_CENTER_Y = 43.00   # mm from the Y endstop: build-plate center after G28

# Clearance lift emitted at the very top of the file, before XY homes, so the nozzles
# rise off the bed first. Absolute (G90) against the operator's manual Z/A zero, not a
# relative delta. Only the axis of an extruder that actually prints is commanded
# (Z for extruder 0, A for extruder 1).
STARTUP_CLEARANCE   = 50.0   # mm: absolute height to raise the used carriage(s) to
STARTUP_CLEARANCE_F = 200.0  # feedrate for that lift


# ---------------------------------------------------------------------------
# Print order pre-pass
#
# The operator sets the print order in the object list, and this is where a
# layer-by-layer print obeys it. It runs BEFORE anything else in execute(), on
# CuraEngine's own output, and does one thing: within each layer it puts the
# ;MESH: sections in the numbered order. Everything downstream then walks a
# stream that is already in the right order and needs no knowledge of any of it.
#
# A pre-pass rather than a change to the emitter, and that is the whole design.
# The main loop carries state from line to line: which tool is live, whether it
# is retracted, the last XY, the current layer height, the feedrate CuraEngine
# last wrote. Reordering the OUTPUT would strand every one of those against the
# lines they were computed from. Reordering the INPUT invalidates none of them,
# because they are all derived by walking whatever it is handed.
#
# Two properties of the g-code are what make the move safe: XY and Z/A are
# absolute, so a part prints where it belongs no matter what came before it, and
# extrusion is relative (M83), so no B/C total is thrown off by the shuffle.
# ---------------------------------------------------------------------------

_PP_MESH_RE  = re.compile(r'^;MESH:(.+)')
_PP_LAYER_RE = re.compile(r'^;LAYER:\d')
_PP_TOOL_RE  = re.compile(r'^T([01])\b')


def _pp_last_tool(lines, tool):
    """The tool left active by these lines."""
    for line in lines:
        match = _PP_TOOL_RE.match(line.strip())
        if match:
            tool = int(match.group(1))
    return tool


def _pp_build_print_order_maps(app):
    """{gcode_name: print order} and {gcode_name: extruder} from the scene.

    A trimmed copy of PrintessOneAtATime._build_mesh_maps, and duplicated on
    purpose: the post-processing scripts are loaded one file at a time and do not
    import each other, the same way the plate-center constants are kept in step
    by hand across all three of them.

    It reconstructs the ;MESH: names by replaying StartSliceJob's per-name "#N"
    counter over DepthFirstIterator, which is the only way to tie a name in the
    g-code back to the node in the object list that carries the number. Meshes in
    a group take the GROUP's number, so a group stays together and lands where
    the object list says it does.
    """
    from UM.Scene.Iterator.DepthFirstIterator import DepthFirstIterator
    scene = app.getController().getScene()

    name_counts      = {}
    order_by_mesh    = {}
    extruder_by_mesh = {}

    for node in DepthFirstIterator(scene.getRoot()):
        mesh_data = node.getMeshData()
        if not node.callDecoration("isSliceable") \
                or mesh_data is None \
                or mesh_data.getVertices() is None:
            continue

        base_name = node.getName()
        if not base_name:
            continue

        count      = name_counts.get(base_name, 0)
        gcode_name = base_name if count == 0 else f"{base_name} #{count + 1}"
        name_counts[base_name] = count + 1

        # Non-printing meshes are counted for the suffixes above but appear as
        # ;MESH:NONMESH in the g-code, so they are never a block of their own.
        if bool(node.callDecoration("isNonPrintingMesh")):
            continue

        # Climb to the OUTERMOST group. The object list shows one row for the
        # top-level group and numbers that row, so an inner group of a nested
        # group keeps whatever number it carried before it was grouped, which
        # goes stale as soon as the outer group is renumbered.
        holder = node
        parent = node.getParent()
        while parent is not None and parent.callDecoration("isGroup"):
            holder = parent
            parent = parent.getParent()
        try:
            order_by_mesh[gcode_name] = int(getattr(holder, "printOrder", 0) or 0)
        except (TypeError, ValueError):
            order_by_mesh[gcode_name] = 0

        try:
            extruder_by_mesh[gcode_name] = int(node.callDecoration("getActiveExtruderPosition"))
        except Exception:
            extruder_by_mesh[gcode_name] = 0

    return order_by_mesh, extruder_by_mesh


def _pp_reorder_layer(chunk, orders, extruders, tool):
    """One layer, reordered. Returns (chunk, tool left active).

    A block is a named ;MESH: section together with the ;MESH:NONMESH travel that
    approaches it, so a part keeps the move that goes and fetches it. The travel
    ends at an absolute XY, which is why it can be carried to a new position at
    all: wherever the head starts from, it arrives where the part begins.
    """
    lines = chunk.split('\n')
    if not any(_PP_LAYER_RE.match(line.strip()) for line in lines):
        # Header and footer are not layers. They still get read for their tool
        # changes, because the tool a chunk leaves active is the tool the next
        # layer starts with, and that is what decides whether a T has to be
        # written at all.
        return chunk, _pp_last_tool(lines, tool)

    prologue = []
    segments = []   # [name, [lines]] in file order, one per ;MESH: marker
    current  = None
    for line in lines:
        match = _PP_MESH_RE.match(line.strip())
        if match:
            current = [match.group(1).strip(), [line]]
            segments.append(current)
        elif current is None:
            prologue.append(line)
        else:
            current[1].append(line)

    blocks  = []
    pending = []    # NONMESH travel waiting for the part it approaches
    for name, segment_lines in segments:
        if name == 'NONMESH':
            pending.append(segment_lines)
            continue
        blocks.append({"name": name, "lines": [l for seg in pending for l in seg] + segment_lines})
        pending = []
    # Travel with no part after it belongs to the end of the layer, where it is.
    tail = [line for segment in pending for line in segment]

    if not blocks:
        return chunk, _pp_last_tool(lines, tool)

    # Ties keep their file order, so parts that share a number (the meshes of one
    # group) stay in the order CuraEngine chose for them.
    ranked = sorted(enumerate(blocks),
                    key = lambda pair: (orders.get(pair[1]["name"], 0) or float('inf'), pair[0]))

    # Every layer goes through the rebuild below, even one already in the right
    # order and even one holding a single part, and that is not wasted work: it
    # is the only place the tool is put right. CuraEngine writes at most one T
    # per layer and lets the next layer INHERIT the tool the last one left, so a
    # layer can open with T1 parts and no T1 anywhere in it. Reordering an
    # earlier layer changes what it leaves behind, and a later layer passed
    # through untouched would then print from whichever syringe happened to be
    # live. Layers that need no change come back byte-identical anyway, by
    # comparison at the end rather than by being skipped.
    out  = list(prologue)
    tool = _pp_last_tool(prologue, tool)
    for _, block in ranked:
        wanted = extruders.get(block["name"])
        if wanted is None:
            # A part that could not be tied back to a node: its own tool changes
            # are the only thing that knows what it prints with, so they stay.
            out.extend(block["lines"])
            tool = _pp_last_tool(block["lines"], tool)
            continue
        if wanted != tool:
            out.append("T{0}".format(wanted))
            tool = wanted
        # CuraEngine's own T commands are dropped and re-issued above, once per
        # block, so a reordered layer switches tools where it now needs to and
        # never where it used to. A redundant T would cost a park and a prime,
        # since the main loop treats every T as a real change.
        out.extend(line for line in block["lines"] if not _PP_TOOL_RE.match(line.strip()))

    # The trailing travel is the one piece that must not move. CuraEngine puts
    # the NEXT layer's height change and its approach at the end of THIS layer,
    # after the last part, so everything printed above it is at the height this
    # layer established and the tail is what hands the following layer its own.
    out.extend(tail)
    tool = _pp_last_tool(tail, tool)

    rebuilt = '\n'.join(out)
    return (chunk if rebuilt == chunk else rebuilt), tool


def _pp_reorder(data, orders, extruders):
    """Every layer in the file, in the operator's order."""
    if not any(orders.values()):
        return data     # nothing numbered: hand back the file untouched

    # T0 to begin with, matching what the scan below assumes when a file carries
    # no T commands at all. The header is read before the first layer, so a file
    # that does say which tool it starts on overrides this.
    tool = 0
    result = []
    for chunk in data:
        new_chunk, tool = _pp_reorder_layer(chunk, orders, extruders, tool)
        result.append(new_chunk)
    return result


class PrintessLayerByLayer(Script):

    def getSettingDataString(self):
        return """{
            "name": "Printess Layer by Layer",
            "key": "PrintessLayerByLayer",
            "metadata": {},
            "version": 2,
            "settings": {}
        }"""

    def execute(self, data):
        from UM.Application import Application
        app = Application.getInstance()

        # Print order first, so everything below walks a stream that is already
        # in the right order: the activation scan, the tool-presence scan and the
        # main pass all read `data` as it now stands. Wrapped because a print
        # that comes out in CuraEngine's order is a disappointment, while a print
        # that does not come out at all is a wasted syringe.
        try:
            order_by_mesh, extruder_by_mesh = _pp_build_print_order_maps(app)
            data = _pp_reorder(data, order_by_mesh, extruder_by_mesh)
        except Exception:
            Logger.logException("w", "PrintessLayerByLayer: could not apply the print order;"
                                     " slicing in CuraEngine's own order instead")

        e0_travel_f  = 240;   e1_travel_f  = 240
        e0_z_hop_f   = 240;   e1_z_hop_f   = 240
        e0_print_f   = 240;   e1_print_f   = 240
        e0_retract   = 0.1;   e1_retract   = 0.1
        e0_retract_f = 240;   e1_retract_f = 240
        e0_prime_f   = 240;   e1_prime_f   = 240
        park_lift                      = PARK_LIFT
        retraction_enabled             = {0: True,  1: True}
        # One switch for both halves of a travel, the lift and the retraction.
        z_hop                          = {0: False, 1: False}
        z_hop_height                   = {0: 0.0,   1: 0.0}
        z_hop_min_dist                 = {0: 0.0,   1: 0.0}
        machine_height                 = 80.0

        def _load(ext0, ext1):
            nonlocal e0_travel_f, e1_travel_f, e0_z_hop_f, e1_z_hop_f
            nonlocal e0_print_f, e1_print_f
            nonlocal e0_retract, e1_retract, e0_retract_f, e1_retract_f
            nonlocal e0_prime_f, e1_prime_f
            e0_travel_f  = int(ext0.getProperty("speed_travel",            "value") * 60)
            e1_travel_f  = int(ext1.getProperty("speed_travel",            "value") * 60)
            e0_z_hop_f   = int(ext0.getProperty("speed_z_hop",             "value") * 60)
            e1_z_hop_f   = int(ext1.getProperty("speed_z_hop",             "value") * 60)
            e0_print_f   = int(ext0.getProperty("speed_print",             "value") * 60)
            e1_print_f   = int(ext1.getProperty("speed_print",             "value") * 60)
            e0_retract   = float(ext0.getProperty("retraction_amount",       "value"))
            e1_retract   = float(ext1.getProperty("retraction_amount",       "value"))
            e0_retract_f = int(ext0.getProperty("retraction_retract_speed", "value") * 60)
            e1_retract_f = int(ext1.getProperty("retraction_retract_speed", "value") * 60)
            e0_prime_f   = int(ext0.getProperty("retraction_prime_speed",   "value") * 60)
            e1_prime_f   = int(ext1.getProperty("retraction_prime_speed",   "value") * 60)

        try:
            gs = app.getGlobalContainerStack()
            park_lift             = float(gs.getProperty("printess_park_lift", "value"))
            retraction_enabled             = {0: bool(gs.extruderList[0].getProperty("retraction_enable",                    "value")),
                                               1: bool(gs.extruderList[1].getProperty("retraction_enable",                    "value"))}
            # One switch for the machine, not one per syringe. The height and
            # the distance stay per-extruder, since each tip has its own line
            # width to measure them against.
            _hop_on        = bool(gs.getProperty("printess_z_hop", "value"))
            z_hop          = {0: _hop_on, 1: _hop_on}
            z_hop_height   = {0: float(gs.extruderList[0].getProperty("printess_z_hop_height",   "value")),
                              1: float(gs.extruderList[1].getProperty("printess_z_hop_height",   "value"))}
            z_hop_min_dist = {0: float(gs.extruderList[0].getProperty("printess_z_hop_min_dist", "value")),
                              1: float(gs.extruderList[1].getProperty("printess_z_hop_min_dist", "value"))}
            # Capped because Z and A are never homed: a lift past the limit loses
            # steps in silence and every layer after it is wrong.
            machine_height = float(gs.getProperty("machine_height", "value"))
            _load(gs.extruderList[0], gs.extruderList[1])
        except Exception:
            try:
                from cura.Settings.ExtruderManager import ExtruderManager
                stacks = ExtruderManager.getInstance().getExtruderStacks()
                if len(stacks) >= 2:
                    _load(stacks[0], stacks[1])
            except Exception:
                pass

        def _spd(s):
            if s == 0:
                return {'travel': e0_travel_f, 'z_hop': e0_z_hop_f,
                        'retract': e0_retract_f, 'prime': e0_prime_f, 'print': e0_print_f}
            return     {'travel': e1_travel_f, 'z_hop': e1_z_hop_f,
                        'retract': e1_retract_f, 'prime': e1_prime_f, 'print': e1_print_f}

        # ------------------------------------------------------------------
        # Pre-scan: for each extruder, collect the layer Z at each activation
        # (only T commands that occur after ;LAYER:0 are counted) and track the
        # tallest layer. The activation queues are consumed in lockstep at tool
        # changes so the two extruders stay aligned (park height itself is now a
        # fixed absolute height, not derived from these).
        # ------------------------------------------------------------------
        activation_z = {0: deque(), 1: deque()}
        _scan_z = 0.0
        _max_z  = 0.0
        _in_print = False
        for chunk in data:
            for line in chunk.split('\n'):
                s = line.strip()
                gp_s = s[:s.index(';')] if ';' in s else s
                zm = re.match(r'^;Z:([\d.]+)', s)
                if zm:
                    _scan_z = float(zm.group(1))
                    _max_z  = max(_max_z, _scan_z)
                    continue
                if re.match(r'^G[01]\b', gp_s, re.IGNORECASE):
                    zo = re.search(r'(?<=\s)Z([-+]?\d+\.?\d*)', gp_s)
                    if zo:
                        _scan_z = float(zo.group(1))
                        _max_z  = max(_max_z, _scan_z)
                if re.match(r'^;LAYER:\d', s):
                    _in_print = True
                if _in_print:
                    tm = re.match(r'^T([01])\b', gp_s)
                    if tm:
                        activation_z[int(tm.group(1))].append(_scan_z)

        # Tool presence: T commands may appear in startup before ;LAYER:,
        # so scan the entire data rather than relying on activation_z.
        # If no T commands appear at all, the implicit scope is T0.
        has_t0 = has_t1 = False
        for _chunk in data:
            for _line in _chunk.split('\n'):
                _s = _line.strip()
                _gp = _s[:_s.index(';')] if ';' in _s else _s
                if re.match(r'^T0\b', _gp):
                    has_t0 = True
                elif re.match(r'^T1\b', _gp):
                    has_t1 = True
        if not has_t0 and not has_t1:
            has_t0 = True  # no T commands → default scope is T0

        # ------------------------------------------------------------------
        # Main processing pass
        # ------------------------------------------------------------------
        scope = 0
        print_started = False
        layer_initialized = False
        awaiting_init = False       # True between ;LAYER:0 and first XY move
        startup_prime_needed = False
        startup_retraction_removed = False
        current_layer_z = 0.0
        post_tc_state = 'normal'    # 'normal' | 'after_xy'
        tc_in_real_mesh = True
        is_retracted = {0: True, 1: True}  # both tools start retracted
        cur_x, cur_y = None, None           # last known XY position for min-distance checks
        # is_hopped[t]: this tool is lifted clear of the print and owes a descent
        # before it extrudes again. Per tool because the two carriages are
        # different axes at different heights, and cleared at every layer and
        # tool change, where the script commands an absolute height of its own
        # and any outstanding lift stops being true.
        is_hopped = {0: False, 1: False}
        # Whether the lines being read belong to a real object. Between-object
        # travel is written under ;MESH:NONMESH, and hopping there would be
        # lifting for a move the script already makes at its own heights.
        in_real_mesh = False

        result = []

        # The feedrate CuraEngine has in effect. It writes F only when the value
        # CHANGES, so an extrusion move carrying no F of its own means "same as
        # the line before" — and the line that set it is often one dropped below,
        # typically the prime before a wall. Tracked above every continue so the
        # value survives the drop.
        self._src_f = None

        for chunk in data:
            out_lines = []
            # Kept as a list, not consumed as a stream, so the hop can look
            # ahead and see whether this tool still prints before it is moved.
            chunk_lines = chunk.split('\n')
            for line_index, line in enumerate(chunk_lines):
                stripped = line.strip()
                gp = stripped[:stripped.index(';')] if ';' in stripped else stripped
                if re.match(r'^G[01]\b', gp, re.IGNORECASE):
                    src_fm = re.search(r'(?<=\s)F([\d.]+)', gp)
                    if src_fm:
                        self._src_f = src_fm.group(1)

                # Track Z from ;Z: markers
                z_m = re.match(r'^;Z:([\d.]+)', stripped)
                if z_m:
                    current_layer_z = float(z_m.group(1))
                    out_lines.append(line)
                    continue

                # Track current_layer_z from original G0/G1 Z values (before rename)
                if re.match(r'^G[01]\b', gp, re.IGNORECASE):
                    z_orig = re.search(r'(?<=\s)Z([-+]?\d+\.?\d*)', gp)
                    if z_orig:
                        current_layer_z = float(z_orig.group(1))

                # Detect layer start
                if re.match(r'^;LAYER:\d', stripped):
                    print_started = True
                    if not layer_initialized:
                        awaiting_init = True
                    # A new layer commands its own height, so nothing is lifted
                    # any more. Carrying the flag over would spend the next
                    # descent putting the tool back down to the PREVIOUS layer.
                    is_hopped = {0: False, 1: False}
                    in_real_mesh = False
                    out_lines.append(line)
                    continue

                # Which object the following lines belong to, for the hop gate.
                mesh_line = re.match(r'^;MESH:(.+)', stripped)
                if mesh_line:
                    in_real_mesh = (mesh_line.group(1).strip() != 'NONMESH')

                # Strip temperature/fan commands and extrusion mode commands
                if re.match(r'^M(82|83|104|105|106|107|109|140|141|190|191)\b', gp, re.IGNORECASE):
                    continue

                # Remove startup retraction: first negative E before layers start
                if not startup_retraction_removed and not print_started:
                    if re.match(r'^G1\b', gp, re.IGNORECASE) and re.search(r'(?<=\s)E-', gp):
                        startup_retraction_removed = True
                        continue

                # Strip all lone extrusion moves — we insert our own retract/prime
                if re.match(r'^G1\b', gp, re.IGNORECASE):
                    has_xy = bool(re.search(r'(?<=\s)[XY][-+]?\d', gp))
                    has_z  = bool(re.search(r'(?<=\s)Z[-+]?\d', gp))
                    has_e  = bool(re.search(r'(?<=\s)E[-+]?\d', gp))
                    if has_e and not has_xy and not has_z:
                        continue

                # Tool change
                tm = re.match(r'^T([01])\b', gp)
                if tm:
                    new_scope = int(tm.group(1))

                    # Retract then park current extruder only during mid-print switches
                    if print_started and layer_initialized:
                        e_char    = 'B' if scope == 0 else 'C'
                        park_axis = 'Z' if scope == 0 else 'A'
                        # Keep this extruder's activation queue aligned with the
                        # start-of-print consume below; the value itself is unused
                        # now that park height is a fixed absolute height.
                        if activation_z[scope]:
                            activation_z[scope].popleft()
                        ra        = e0_retract if scope == 0 else e1_retract
                        spd       = _spd(scope)
                        if retraction_enabled[scope] and not is_retracted[scope]:
                            out_lines.extend(self._set_f(f'G1 {e_char}{-ra:.5f} F{spd["retract"]}', spd))
                            is_retracted[scope] = True
                        # Park at the absolute Print Level Clearance height so the idle
                        # nozzle clears tall obstacles (e.g. well-plate walls).
                        out_lines.extend(self._set_f(f'G1 {park_axis}{park_lift:.3f} F{spd["z_hop"]}', spd))

                    # The outgoing tool has just been parked at the clearance
                    # height, and the incoming one is a different axis. Any lift
                    # either of them owed is void: "down" now means somewhere
                    # else entirely.
                    is_hopped = {0: False, 1: False}

                    scope = new_scope
                    out_lines.append(line)

                    if print_started and layer_initialized:
                        post_tc_state = 'after_xy'
                        tc_in_real_mesh = True  # assume real mesh; False if NONMESH seen first

                    continue

                # Post-tool-change state machine (mid-print switches only)
                if post_tc_state == 'after_xy':
                    # Track mesh context so non-mesh travel moves don't trigger the lower+prime
                    mesh_m = re.match(r'^;MESH:(.+)', stripped)
                    if mesh_m:
                        tc_in_real_mesh = (mesh_m.group(1).strip() != 'NONMESH')
                        out_lines.append(line)
                        continue

                    renamed = self._rename_t0(line) if scope == 0 else self._rename_t1(line)
                    rgp = renamed[:renamed.index(';')] if ';' in renamed else renamed

                    is_g01 = bool(re.match(r'^G[01]\b', rgp.strip(), re.IGNORECASE))
                    has_xy = bool(re.search(r'(?<=\s)[XY][-+]?\d', rgp))

                    if is_g01 and has_xy and tc_in_real_mesh:
                        height_axis = 'Z' if scope == 0 else 'A'
                        e_char      = 'B' if scope == 0 else 'C'
                        ra          = e0_retract if scope == 0 else e1_retract
                        spd         = _spd(scope)
                        h_match     = re.search(rf'(?<=\s){height_axis}([-+]?\d+\.?\d*)', rgp)

                        if h_match:
                            # XY+height move: the height is stated by the move
                            # itself, so take it and strip it from the XY line.
                            height_val = float(h_match.group(1))
                            current_layer_z = height_val
                            xy_line = re.sub(rf'\s{height_axis}[-+]?\d+\.?\d*', '', renamed).rstrip()
                        else:
                            height_val = current_layer_z
                            xy_line = renamed

                        def _lower_and_prime():
                            out_lines.extend(self._set_f(
                                f'G1 {height_axis}{height_val:.3f} F{spd["z_hop"]}', spd))
                            if retraction_enabled[scope]:
                                out_lines.extend(self._set_f(
                                    f'G1 {e_char}{ra:.5f} F{spd["prime"]}', spd))
                                is_retracted[scope] = False

                        if re.search(rf'(?<=\s){e_char}[-+]?\d', rgp):
                            # This first move already EXTRUDES. That happens when
                            # the mesh's approach travel sits in the previous
                            # layer's trailing NONMESH, so the block opens on a
                            # printing move with the tool still parked. Descend
                            # and prime ahead of it: emitting it first would lay
                            # the bead at the clearance height, in mid-air. The
                            # descent happens at the XY the previous travel left
                            # us on, which is where this mesh begins.
                            _lower_and_prime()
                            out_lines.extend(self._set_f(xy_line, spd))
                        else:
                            # A travel. Cross at the parked height first, so the
                            # tip never drags over the print, and only then come
                            # down onto the start of the mesh.
                            out_lines.extend(self._set_f(xy_line, spd))
                            _lower_and_prime()
                        post_tc_state = 'normal'
                    else:
                        # Suppress pure height-axis moves until the real-mesh XY fires.
                        # For combined XY+height travel (first NONMESH move after a tool
                        # change when the new tool hasn't been positioned yet), travel XY
                        # first at the current height, then lower — same order as the
                        # real-mesh branch above, but without the prime.
                        height_axis = 'Z' if scope == 0 else 'A'
                        has_za = bool(re.search(r'(?<=\s)[ZA][-+]?\d', rgp))
                        has_bc = bool(re.search(r'(?<=\s)[BC][-+]?\d', rgp))
                        if is_g01 and has_za and not has_xy and not has_bc:
                            continue
                        if is_g01 and has_za and has_xy:
                            # Combined XY+height in NONMESH: emit XY only, defer the height
                            # lowering to the first real-mesh XY trigger (which lowers + primes).
                            h_match = re.search(rf'(?<=\s){height_axis}([-+]?\d+\.?\d*)', rgp)
                            if h_match:
                                current_layer_z = float(h_match.group(1))
                            xy_line = re.sub(rf'\s{height_axis}[-+]?\d+\.?\d*', '', renamed).rstrip()
                            out_lines.extend(self._set_f(xy_line, _spd(scope)))
                        else:
                            out_lines.extend(self._set_f(renamed, _spd(scope)))
                    continue

                # Normal line processing
                renamed = self._rename_t0(line) if scope == 0 else self._rename_t1(line)
                rgp_n = renamed[:renamed.index(';')] if ';' in renamed else renamed

                height_axis = 'Z' if scope == 0 else 'A'
                is_g01_n = bool(re.match(r'^G[01]\b', rgp_n.strip(), re.IGNORECASE))
                has_xy_n = bool(re.search(r'(?<=\s)[XY][-+]?\d', rgp_n))
                h_match_n = re.search(rf'(?<=\s){height_axis}([-+]?\d+\.?\d*)', rgp_n)

                spd = _spd(scope)

                if awaiting_init and is_g01_n and has_xy_n:
                    # Opening the print, in the order PrintessOneAtATime opens a
                    # part: cross to the start point in XY FIRST, while both
                    # carriages are still up at the startup clearance, and only
                    # then bring the printing one down.
                    #
                    # The reverse, which this did before, descends to the layer
                    # height at the post-home position and drags the tip all the
                    # way across the plate at 1.54mm to reach the first object.
                    # On a bed with anything already on it that is a collision,
                    # and on a clean one it still smears the first bead's
                    # approach.
                    inactive = 1 if scope == 0 else 0
                    if activation_z[inactive]:
                        activation_z[inactive].popleft()

                    if h_match_n:
                        xy_line = re.sub(rf'\s{height_axis}[-+]?\d+\.?\d*', '', renamed).rstrip()
                    else:
                        xy_line = renamed
                    out_lines.extend(self._set_f(xy_line, spd))
                    out_lines.extend(self._set_f(f'G1 {height_axis}{current_layer_z:.3f} F{spd["z_hop"]}', spd))

                    # Park the idle syringe at the clearance height, as a part
                    # start does. Only when that extruder prints somewhere in
                    # this file: its axis is never homed, so commanding one that
                    # is not in use drives it from a position nothing has
                    # defined.
                    idle_axis = 'Z' if inactive == 0 else 'A'
                    if (inactive == 0 and has_t0) or (inactive == 1 and has_t1):
                        out_lines.extend(self._set_f(
                            f'G1 {idle_axis}{park_lift:.3f} F{_spd(inactive)["z_hop"]}', spd))

                    layer_initialized = True
                    awaiting_init = False
                    startup_prime_needed = True

                elif is_g01_n and has_xy_n and h_match_n:
                    # Normal layer-change move: height first, then XY
                    height_val = float(h_match_n.group(1))
                    current_layer_z = height_val
                    out_lines.extend(self._set_f(f'G1 {height_axis}{height_val:.3f} F{spd["z_hop"]}', spd))
                    xy_line = re.sub(rf'\s{height_axis}[-+]?\d+\.?\d*', '', renamed).rstrip()
                    out_lines.extend(self._set_f(xy_line, spd))

                else:
                    e_char_sp  = 'B' if scope == 0 else 'C'
                    ra_sp      = e0_retract if scope == 0 else e1_retract
                    has_pos_bc = bool(re.search(rf'(?<=\s){e_char_sp}[+]?\d', rgp_n))
                    has_any_bc = bool(re.search(rf'(?<=\s){e_char_sp}[-+]?\d', rgp_n))

                    # Travel hop, part one: come back down before extruding.
                    # This sits AHEAD of the retract/prime block below so the
                    # descent lands before the prime, which is the order that
                    # keeps pressure off the tip while it is still moving.
                    if is_hopped[scope] and is_g01_n and has_xy_n and has_pos_bc:
                        out_lines.extend(self._set_f(
                            f'G1 {height_axis}{current_layer_z:.3f} F{spd["z_hop"]}', spd))
                        is_hopped[scope] = False

                    if startup_prime_needed and is_g01_n and has_pos_bc:
                        if retraction_enabled[scope]:
                            out_lines.extend(self._set_f(f'G1 {e_char_sp}{ra_sp:.5f} F{spd["prime"]}', spd))
                        startup_prime_needed = False
                        is_retracted[scope] = False
                    elif z_hop[scope] and retraction_enabled[scope] and layer_initialized and is_g01_n:
                        # The retraction half of Hop & Retract on Travel. It
                        # answers to the same switch and the same distance as the
                        # lift below, so the two always act on the same moves.
                        #
                        # TRAVEL only. The old Retract Before Travel also
                        # retracted ahead of a lone height move, which has no XY
                        # length for a minimum distance to judge and no
                        # counterpart in PrintessOneAtATime. Dropping it is what
                        # makes the two scripts do the same thing from the same
                        # switch, which is the point of there being one switch.
                        if has_xy_n:
                            if not has_any_bc and not is_retracted[scope] and in_real_mesh \
                                    and self._travel_at_least(z_hop_min_dist[scope], rgp_n, cur_x, cur_y):
                                out_lines.extend(self._set_f(f'G1 {e_char_sp}{-ra_sp:.5f} F1', spd))
                                is_retracted[scope] = True
                            elif has_pos_bc and is_retracted[scope]:
                                out_lines.extend(self._set_f(f'G1 {e_char_sp}{ra_sp:.5f} F{spd["prime"]}', spd))
                                is_retracted[scope] = False

                    # Travel hop, part two: lift before a pure XY travel inside
                    # an object. After the retract above, so the pressure is off
                    # before the tip moves up, and only inside a real mesh:
                    # NONMESH travel is the move BETWEEN objects, which the
                    # script already makes at heights of its own.
                    if z_hop[scope] and in_real_mesh and layer_initialized \
                            and is_g01_n and has_xy_n and not has_any_bc \
                            and not is_hopped[scope]:
                        # A lift this tool comes back down from is sized for the
                        # layer it is on. Its LAST travel before a park or a new
                        # layer is sized for whatever height comes next, so the
                        # short move away from the seam still crosses the print
                        # high, and the height already on its way then serves as
                        # the descent. Skipping it left that move dragging.
                        base = current_layer_z
                        if not self._prints_again(chunk_lines, line_index):
                            following = self._next_input_height(chunk_lines, line_index)
                            if following is not None and following > current_layer_z:
                                base = following
                        hop_z = min(base + z_hop_height[scope], machine_height)
                        if hop_z > current_layer_z and self._travel_at_least(
                                z_hop_min_dist[scope], rgp_n, cur_x, cur_y):
                            out_lines.extend(self._set_f(
                                f'G1 {height_axis}{hop_z:.3f} F{spd["z_hop"]}', spd))
                            is_hopped[scope] = True

                    out_lines.extend(self._set_f(renamed, spd))
                    if is_g01_n and has_xy_n:
                        xm = re.search(r'(?<=\s)X([-+]?\d+\.?\d*)', rgp_n)
                        ym = re.search(r'(?<=\s)Y([-+]?\d+\.?\d*)', rgp_n)
                        if xm: cur_x = float(xm.group(1))
                        if ym: cur_y = float(ym.group(1))

            result.append('\n'.join(out_lines))

        # Final park: retract then lift active extruder to the absolute Print Level
        # Clearance height. Inserted before result[-1] (the footer chunk) so it
        # precedes M82/End of Gcode.
        spd       = _spd(scope)
        e_char    = 'B' if scope == 0 else 'C'
        park_axis = 'Z' if scope == 0 else 'A'
        ra        = e0_retract if scope == 0 else e1_retract
        park_lines = []
        if retraction_enabled[scope]:
            park_lines.extend(self._set_f(f'G1 {e_char}{-ra:.5f} F{spd["retract"]}', spd))
        park_lines.extend(self._set_f(f'G1 {park_axis}{park_lift:.3f} F{spd["z_hop"]}', spd))
        result.insert(len(result) - 1, '\n'.join(park_lines))

        # Strip Cura's lone Z/A raise from ending chunk — our final park covers it.
        # (Lone E retracts are already stripped by the main loop above.)
        cleaned = []
        for line in result[-1].split('\n'):
            s  = line.strip()
            gp = s[:s.index(';')] if ';' in s else s
            if re.match(r'^G1\b', gp, re.IGNORECASE):
                has_xy = bool(re.search(r'(?<=\s)[XY][-+]?\d', gp))
                has_za = bool(re.search(r'(?<=\s)[ZA][-+]?\d', gp))
                has_e  = bool(re.search(r'(?<=\s)[BCE][-+]?\d', gp))
                if has_za and not has_xy and not has_e:
                    continue
            cleaned.append(line)
        result[-1] = '\n'.join(cleaned)

        if len(result) > 1:
            # The clearance lift + XY homing (G28) + the zero-offset datum routine (see
            # _startup_datum) establish the datum, replacing the old full software zero
            # (G92 X0 Y0 Z0 A0 B0 C0). Only the syringe of an extruder that actually prints
            # is lifted, and Z/A are neither homed nor declared: the operator zeroes the
            # axis they are using by hand before printing. These lines are added after the
            # header comments (result[0]) and are exempt from axis renaming because they
            # are inserted after the main rename pass.
            result[1] = self._startup_datum(has_t0, has_t1) + '\n' + result[1]
        result = self._collapse_height_moves(result)
        return self._to_absolute_extrusion(result)

    # -------------------------------------------------------------------------

    # A move that only sets a height: one of Z or A, and nothing else.
    _HEIGHT_ONLY_RE = re.compile(r'^G[01]\b(?=[^;]*\s[ZA][-+]?\d)'
                                 r'(?![^;]*\s[XYBCE][-+]?\d)', re.IGNORECASE)

    @classmethod
    def _height_axis_of(cls, line):
        """The single axis a height-only move commands, or None."""
        gp = (line[:line.index(';')] if ';' in line else line).strip()
        if not cls._HEIGHT_ONLY_RE.match(gp):
            return None
        axes = set(re.findall(r'(?<=\s)([ZA])[-+]?\d', gp, re.IGNORECASE))
        return axes.pop().upper() if len(axes) == 1 else None

    @staticmethod
    def _is_retract_only(line):
        """A plunger move that only pulls back, and goes nowhere else.

        Read before extrusion is made absolute, so a retract is still written
        as the negative number it is.
        """
        gp = (line[:line.index(';')] if ';' in line else line).strip()
        if not re.match(r'^G[01]\b', gp, re.IGNORECASE):
            return False
        if re.search(r'(?<=\s)[XYZAE][-+]?\d', gp):
            return False
        return bool(re.search(r'(?<=\s)[BC]-\d', gp))

    @classmethod
    def _collapse_height_moves(cls, chunks):
        """Drop height moves nothing can observe, across the WHOLE file.

        Two kinds. First, a height move the very next one overrides (same axis,
        nothing between but comments and retracts): a layer opens by commanding
        its height and then immediately lifts, so it would descend to a layer it
        never prints at. Second, a height move commanding the height the axis
        already holds, which is where one block lifts for the layer to come and
        the next block lifts again to the same place.

        It spans chunks because that second pair lands in different ones: a
        block per chunk, and the pair straddles the boundary. Absolute
        positioning is what makes both safe. A retract may sit inside a run,
        since pulling the plunger back does not depend on the height; a PRIME
        breaks it, and that distinction is the whole safety of this, because
        priming is the one plunger move whose height matters.
        """
        flat = []          # (chunk index, line)
        for chunk_index, chunk in enumerate(chunks):
            for line in chunk.split('\n'):
                flat.append((chunk_index, line))

        drop = set()
        pending = None     # (index, axis) of a height move nothing has used yet
        for index, (_, line) in enumerate(flat):
            stripped = line.strip()
            if not stripped or stripped.startswith(';'):
                continue
            axis = cls._height_axis_of(stripped)
            if axis is not None:
                if pending is not None and pending[1] == axis:
                    drop.add(pending[0])
                pending = (index, axis)
                continue
            if cls._is_retract_only(stripped):
                continue
            pending = None

        # Walked over the SURVIVORS of the first pass, because a move dropped
        # there never happens and so never moves the axis.
        position = {}
        for index, (_, line) in enumerate(flat):
            if index in drop:
                continue
            stripped = line.strip()
            if not stripped or stripped.startswith(';'):
                continue
            axis = cls._height_axis_of(stripped)
            if axis is not None:
                value = float(re.search(r'(?<=\s)' + axis + r'([-+]?\d+\.?\d*)',
                                        stripped, re.IGNORECASE).group(1))
                if position.get(axis) == value:
                    drop.add(index)
                else:
                    position[axis] = value
                continue
            for other in ('Z', 'A'):
                match = re.search(r'(?<=\s)' + other + r'([-+]?\d+\.?\d*)',
                                  stripped, re.IGNORECASE)
                if match:
                    position[other] = float(match.group(1))

        if not drop:
            return chunks
        rebuilt = [[] for _ in chunks]
        for index, (chunk_index, line) in enumerate(flat):
            if index not in drop:
                rebuilt[chunk_index].append(line)
        return ['\n'.join(lines) for lines in rebuilt]

    @staticmethod
    def _prints_again(lines, index):
        """Whether anything still prints later in the chunk, before the tool moves.

        The lines scanned are the RAW input, ahead of the axis rename, so
        extrusion is still written as E here and not as B or C. Looking for B/C
        finds nothing in the input and silently answers "no" to every question,
        which switches the lift off altogether.

        A lift is only worth making if the tool comes back down to print. The
        last travel before a tool change, a new layer or the end of the chunk is
        followed by an absolute height that overrides the lift, so making it
        rises the full hop height to cross a seam-exit move and is then
        cancelled. The scan stops at a T or a ;LAYER: for exactly that reason:
        past either, the height is restated and this lift is void.
        """
        for later in lines[index + 1:]:
            stripped = later.strip()
            if re.match(r'^T[01]\b', stripped) or re.match(r'^;LAYER:', stripped):
                return False
            gp = stripped[:stripped.index(';')] if ';' in stripped else stripped
            if not re.match(r'^G[01]\b', gp, re.IGNORECASE):
                continue
            if re.search(r'(?<=\s)[XY][-+]?\d', gp) and re.search(r'(?<=\s)E[-+]?\d', gp):
                return True
        return False

    @staticmethod
    def _next_input_height(lines, index):
        """The next height CuraEngine commands after `index`, or None.

        Scanned on the RAW input, where the height is still Z for either tool
        and Cura's own hop is off in every dispense-tip profile, so the first Z
        ahead is the next layer. It is what a lift taken on a tool's last travel
        is sized against, and it doubles as that lift's descent.
        """
        for later in lines[index + 1:]:
            stripped = later.strip()
            gp = stripped[:stripped.index(';')] if ';' in stripped else stripped
            if not re.match(r'^G[01]\b', gp, re.IGNORECASE):
                continue
            match = re.search(r'(?<=\s)Z([-+]?\d+\.?\d*)', gp)
            if match:
                return float(match.group(1))
        return None

    @staticmethod
    def _travel_at_least(threshold, gcode_part, cur_x, cur_y):
        """Whether this move covers at least `threshold` mm of XY distance.

        The distance measured is the length of the move itself, sqrt(dX2 + dY2),
        not the height of any lift. A threshold of 0 means every move qualifies.
        A threshold that cannot be evaluated, because nothing has said where the
        head is yet, counts as NOT met: the move may well be shorter than the
        operator asked to act on. PrintessOneAtATime answers this the same way.
        """
        if cur_x is None or cur_y is None:
            return threshold <= 0.0
        xm = re.search(r'(?<=\s)X([-+]?\d+\.?\d*)', gcode_part)
        ym = re.search(r'(?<=\s)Y([-+]?\d+\.?\d*)', gcode_part)
        dest_x = float(xm.group(1)) if xm else cur_x
        dest_y = float(ym.group(1)) if ym else cur_y
        distance = math.hypot(dest_x - cur_x, dest_y - cur_y)
        # A move that goes nowhere is not a travel, whatever the threshold says.
        return distance > 0.0 and distance >= threshold

    def _set_f(self, line, speeds):
        """Classify a renamed G0/G1 line and inject the correct F value.

        Returns a list of lines (usually 1; 2 when a combined XY+Z/A line is split;
        0 when a standalone F-only line is stripped).
        Pure Z/A        -> z_hop speed
        Pure XY         -> travel speed
        Pure B/C <0     -> retract speed
        Pure B/C >=0    -> prime speed
        XY + Z/A        -> split: Z/A line at z_hop, XY line at travel
        XY + Z/A + B/C  -> split: Z/A line at z_hop, XY+B/C line at print
        XY + B/C        -> left as-is (Cura's per-feature speed)
        """
        if ';' in line:
            idx = line.index(';')
            gp, cp = line[:idx], line[idx:]
        else:
            gp, cp = line, ''

        s = gp.strip()
        if not s:
            return [line]
        if not re.match(r'^G[01]\b', s, re.IGNORECASE):
            return [line]

        has_xy = bool(re.search(r'(?<=\s)[XY][-+]?\d', gp))
        has_za = bool(re.search(r'(?<=\s)[ZA][-+]?\d', gp))
        has_bc = bool(re.search(r'(?<=\s)[BC][-+]?\d', gp))
        has_f  = bool(re.search(r'(?<=\s)F[\d]',       gp))

        # Standalone F-only line (no axis parameters) — strip entirely
        if has_f and not has_xy and not has_za and not has_bc:
            return []

        # Strip existing F before injecting the correct one
        gp_nof = re.sub(r'\s+F[\d.]+', '', gp).rstrip()

        if has_za and has_xy and has_bc:
            # Split: Z/A descends first, then XY+B/C at print speed
            za_m = re.search(r'(?<=\s)([ZA])([-+]?\d+\.?\d*)', gp)
            za_char, za_val = za_m.group(1), za_m.group(2)
            xy_bc = re.sub(r'\s[ZA][-+]?\d+\.?\d*', '', gp_nof).rstrip()
            return [f'G1 {za_char}{za_val} F{speeds["z_hop"]}',
                    xy_bc + f' F{speeds["print"]}' + cp]

        if has_za and has_xy:
            # Split: Z/A descends first, then XY at travel speed
            za_m = re.search(r'(?<=\s)([ZA])([-+]?\d+\.?\d*)', gp)
            za_char, za_val = za_m.group(1), za_m.group(2)
            xy_only = re.sub(r'\s[ZA][-+]?\d+\.?\d*', '', gp_nof).rstrip()
            return [f'G1 {za_char}{za_val} F{speeds["z_hop"]}',
                    xy_only + f' F{speeds["travel"]}' + cp]

        if has_za:
            return [gp_nof + f' F{speeds["z_hop"]}' + cp]

        if has_xy and not has_bc:
            return [gp_nof + f' F{speeds["travel"]}' + cp]

        if has_bc and not has_xy:
            bc_m = re.search(r'(?<=\s)[BC]([-+]?\d+\.?\d*)', gp)
            val  = float(bc_m.group(1)) if bc_m else 0.0
            fval = speeds['retract'] if val < 0 else speeds['prime']
            return [gp_nof + f' F{fval}' + cp]

        # XY + B/C (no Z/A): Cura's per-feature speed. A line with an F of its own
        # keeps it. One without meant "same as before", so the tracked feedrate is
        # written back explicitly rather than left to a predecessor that may no
        # longer be there.
        if has_f or getattr(self, '_src_f', None) is None:
            return [line]
        return [gp.rstrip() + ' F' + self._src_f + cp]

    # -------------------------------------------------------------------------

    def _rename_t0(self, line):
        """E→B on G0, G1, G92; all other lines pass through unchanged."""
        if ';' in line:
            idx = line.index(';')
            gcode_part, comment_part = line[:idx], line[idx:]
        else:
            gcode_part, comment_part = line, ''

        stripped = gcode_part.strip()
        if not stripped:
            return line

        m = re.match(r'^(G\d+)', stripped, re.IGNORECASE)
        if m and m.group(1).upper() in ('G0', 'G1', 'G92'):
            gcode_part = re.sub(r'(?<=\s)E(?=[-+]?\d)', 'B', gcode_part)
            return gcode_part + comment_part

        return line

    def _rename_t1(self, line):
        """Z→A, E→C on G0, G1, G92; all other lines pass through unchanged."""
        if ';' in line:
            idx = line.index(';')
            gcode_part, comment_part = line[:idx], line[idx:]
        else:
            gcode_part, comment_part = line, ''

        stripped = gcode_part.strip()
        if not stripped:
            return line

        m = re.match(r'^(G\d+)', stripped, re.IGNORECASE)
        if m and m.group(1).upper() in ('G0', 'G1', 'G92'):
            gcode_part = re.sub(r'(?<=\s)Z(?=[-+]?\d)', 'A', gcode_part)
            gcode_part = re.sub(r'(?<=\s)E(?=[-+]?\d)', 'C', gcode_part)
            return gcode_part + comment_part

        return line

    def _startup_datum(self, has_t0, has_t1):
        """Build the clearance lift + XY homing + zero-offset datum block.

        Z and A are never homed. The operator jogs the syringe of the extruder they
        are using down to the print surface and zeroes that axis with a manual G92
        before starting, so every Z/A coordinate in the file is absolute against that
        operator datum. That is why the lift below is a plain absolute move rather
        than the relative one it used to be.

        Order:
            G90                              absolute mode
            G1 Z.. A.. F..                   raise the used carriage(s) to
                                             STARTUP_CLEARANCE above the operator's zero,
                                             clear of the bed before XY homes. Only the
                                             axis of a tool that actually prints is
                                             commanded: Z for extruder 0, A for extruder 1
                                             (T1's Z is renamed to A).
            G28 X Y                          home XY, when printess/home_xy is on. The
                                             printer's G28 then centers XY on the plate
                                             (PLATE_CENTER_*).
            G92 X.. Y.. B0 C0                declare the zero-offset origin at that
                                             post-home position WITHOUT moving

        G92 sets the current position rather than driving to it, so nothing has to move:
        the machine is already at a known spot in XY after G28 (PLATE_CENTER_*), and each
        axis value is that known position minus its offset. Subtracting the offset shifts
        the print origin away from the endstop by that many mm; an offset of 0 simply keeps
        the post-home position as the origin. Z and A are deliberately absent from the G92
        so the operator's manual zero survives untouched.

        X/Y are gated on printess/home_xy, with offsets from printess/zero_offset_{x,y}
        (mm from the endstop). B (T0) and C (T1) are always zeroed. Returned as a
        '\n'-joined string with no trailing newline.
        """
        from UM.Application import Application
        prefs = Application.getInstance().getPreferences()

        def _flag(key):
            v = prefs.getValue(key)
            if v is None:
                return True
            if isinstance(v, bool):
                return v
            return str(v).strip().lower() in ("true", "1", "yes")

        def _num(key):
            v = prefs.getValue(key)
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0

        home_xy = _flag("printess/home_xy")

        lines = ['G90']

        # Absolute clearance lift before anything else, so the nozzles come up off the
        # bed before the plate homes in XY. Gated on tool usage: an axis whose extruder
        # never prints is never commanded, and is not one the operator will have zeroed.
        lift_axes = []
        if has_t0:
            lift_axes.append('Z{0:g}'.format(STARTUP_CLEARANCE))
        if has_t1:
            lift_axes.append('A{0:g}'.format(STARTUP_CLEARANCE))
        if lift_axes:
            lines.append('G1 ' + ' '.join(lift_axes) + ' F{0:g}'.format(STARTUP_CLEARANCE_F))

        if home_xy:
            lines.append('G28 X Y')

        # Declare the zero-offset origin at the known post-home position without moving:
        # each value is (post-home position - offset). Z and A are left out so the
        # operator's manual G92 zero is preserved; the extruder axes B (T0) and C (T1)
        # are always zeroed.
        g92 = []
        if home_xy:
            g92.append(f'X{PLATE_CENTER_X - _num("printess/zero_offset_x"):.3f}')
            g92.append(f'Y{PLATE_CENTER_Y - _num("printess/zero_offset_y"):.3f}')
        g92 += ['B0', 'C0']
        lines.append('G92 ' + ' '.join(g92))

        return '\n'.join(lines)

    def _to_absolute_extrusion(self, result):
        # B/C stay in absolute mode (printer ignores M83 for unknown axes).
        # Walk result in order, accumulating per-axis totals so every relative
        # delta emitted by the script becomes a correct absolute position.
        _G01_RE = re.compile(r'^G[01]\b', re.IGNORECASE)
        _B_RE   = re.compile(r'(?<=\s)B([-+]?\d+(?:\.\d*)?)')
        _C_RE   = re.compile(r'(?<=\s)C([-+]?\d+(?:\.\d*)?)')
        state = {'b': 0.0, 'c': 0.0}
        def repl_b(m):
            state['b'] += float(m.group(1))
            return f'B{state["b"]:.5f}'
        def repl_c(m):
            state['c'] += float(m.group(1))
            return f'C{state["c"]:.5f}'
        out = []
        for chunk in result:
            new_lines = []
            for line in chunk.split('\n'):
                s  = line.strip()
                gp = s[:s.index(';')] if ';' in s else s
                if _G01_RE.match(gp) and re.search(r'(?<=\s)[BC][-+]?\d', gp):
                    if ';' in line:
                        idx = line.index(';')
                        gcode_part, comment_part = line[:idx], line[idx:]
                    else:
                        gcode_part, comment_part = line, ''
                    gcode_part = _B_RE.sub(repl_b, gcode_part)
                    gcode_part = _C_RE.sub(repl_c, gcode_part)
                    line = gcode_part + comment_part
                new_lines.append(line)
            out.append('\n'.join(new_lines))
        return out
