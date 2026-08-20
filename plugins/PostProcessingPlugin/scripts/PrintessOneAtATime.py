# Copyright (c) 2024 Printess Technologies
# Printess One at a Time Post Processing Script
#
# Prints each object on the build plate fully before moving to the next.
# Both extruders can contribute to a single object; they alternate sequentially.
# Within each layer: T0 block first, then T1 block.
# Idle extruder parks at the absolute Print Level Clearance height while the other prints.
# Axis renaming: T0 E->B, T1 E->C and Z->A.
# Temperature and fan commands are stripped.
# Assumes relative extrusion (M83) is set by the machine definition.
#
# Objects are identified using ;MESH:name comments written by CuraEngine.
# Grouped objects share a part key derived from the scene graph so all meshes
# in the same Cura group are printed together (layer-by-layer) before moving
# to the next part.

import re
import math
from ..Script import Script
from UM.Message import Message
from UM.i18n import i18nCatalog

catalog = i18nCatalog("cura")

PARK_LIFT = 30.0  # absolute park height (mm) for the idle extruder; fallback if the setting is unreadable

# Startup-datum constants (see _startup_datum). Only XY is homed: after the printer's
# custom G28 the plate is centered under the nozzle, and the datum G92 declares the
# zero-offset origin relative to that without moving. Z and A are never homed, so they
# have no machine-defined post-home position; the operator zeroes the axis of the extruder
# they are using with a manual G92 before starting the print.
PLATE_CENTER_X = 63.0   # mm from the X endstop: build-plate centre after G28
PLATE_CENTER_Y = 42.0   # mm from the Y endstop: build-plate centre after G28

# Clearance lift emitted at the very top of the file, before XY homes, so the nozzles
# rise off the bed first. Absolute (G90) against the operator's manual Z/A zero, not a
# relative delta. Only the axis of an extruder that actually prints is commanded
# (Z for extruder 0, A for extruder 1).
STARTUP_CLEARANCE   = 50.0   # mm: absolute height to raise the used carriage(s) to
STARTUP_CLEARANCE_F = 200.0  # feedrate for that lift


class PrintessOneAtATime(Script):

    def getSettingDataString(self):
        return """{
            "name": "Printess One at a Time",
            "key": "PrintessOneAtATime",
            "metadata": {},
            "version": 2,
            "settings": {}
        }"""

    # ------------------------------------------------------------------
    # Compiled patterns
    # ------------------------------------------------------------------
    _TEMP_FAN_RE = re.compile(r'^M(82|83|104|105|106|107|109|140|141|190|191)\b', re.IGNORECASE)
    _G01_RE      = re.compile(r'^G[01]\b',  re.IGNORECASE)
    _G92_RE      = re.compile(r'^G92\b',    re.IGNORECASE)
    _T_RE        = re.compile(r'^T([01])\b')
    _LAYER_RE    = re.compile(r'^;LAYER:(-?\d+)')
    _MESH_RE     = re.compile(r'^;MESH:(.+)')
    _Z_RE        = re.compile(r'^;Z:([\d.]+)')
    _X_RE        = re.compile(r'(?<=\s)X([-+]?\d+(?:\.\d*)?)')
    _Y_RE        = re.compile(r'(?<=\s)Y([-+]?\d+(?:\.\d*)?)')
    _F_RE        = re.compile(r'(?<=\s)F([\d.]+)')

    # ------------------------------------------------------------------

    def execute(self, data):
        from UM.Application import Application
        app = Application.getInstance()

        # Settings — primary read via global container stack, fallback via ExtruderManager
        e1_travel_f  = 240;   e2_travel_f  = 240
        e1_z_hop_f   = 240;   e2_z_hop_f   = 240
        e1_print_f   = 240;   e2_print_f   = 240
        e1_retract   = 0.1;   e1_retract_f = 240;  e1_prime_f = 240
        e2_retract   = 0.1;   e2_retract_f = 240;  e2_prime_f = 240
        park_lift    = PARK_LIFT
        retraction_enabled             = {0: True,  1: True}
        retract_before_travel          = {0: False, 1: False}
        retract_before_travel_min_dist = {0: 3.0,   1: 3.0}

        def _load(ext0, ext1):
            nonlocal e1_travel_f, e2_travel_f, e1_z_hop_f, e2_z_hop_f
            nonlocal e1_print_f, e2_print_f
            nonlocal e1_retract, e1_retract_f, e1_prime_f
            nonlocal e2_retract, e2_retract_f, e2_prime_f
            e1_travel_f  = int(ext0.getProperty("speed_travel",            "value") * 60)
            e2_travel_f  = int(ext1.getProperty("speed_travel",            "value") * 60)
            e1_z_hop_f   = int(ext0.getProperty("speed_z_hop",             "value") * 60)
            e2_z_hop_f   = int(ext1.getProperty("speed_z_hop",             "value") * 60)
            e1_print_f   = int(ext0.getProperty("speed_print",             "value") * 60)
            e2_print_f   = int(ext1.getProperty("speed_print",             "value") * 60)
            e1_retract   = float(ext0.getProperty("retraction_amount",       "value"))
            e1_retract_f = int(ext0.getProperty("retraction_retract_speed", "value") * 60)
            e1_prime_f   = int(ext0.getProperty("retraction_prime_speed",   "value") * 60)
            e2_retract   = float(ext1.getProperty("retraction_amount",       "value"))
            e2_retract_f = int(ext1.getProperty("retraction_retract_speed", "value") * 60)
            e2_prime_f   = int(ext1.getProperty("retraction_prime_speed",   "value") * 60)

        try:
            gs = app.getGlobalContainerStack()
            park_lift             = float(gs.getProperty("printess_park_lift", "value"))
            retraction_enabled             = {0: bool(gs.extruderList[0].getProperty("retraction_enable",                    "value")),
                                               1: bool(gs.extruderList[1].getProperty("retraction_enable",                    "value"))}
            retract_before_travel          = {0: bool(gs.extruderList[0].getProperty("printess_retract_before_travel",        "value")),
                                               1: bool(gs.extruderList[1].getProperty("printess_retract_before_travel",        "value"))}
            retract_before_travel_min_dist = {0: float(gs.extruderList[0].getProperty("printess_retract_before_travel_min_dist", "value")),
                                               1: float(gs.extruderList[1].getProperty("printess_retract_before_travel_min_dist", "value"))}
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
                return {'travel': e1_travel_f, 'z_hop': e1_z_hop_f,
                        'retract': e1_retract_f, 'prime': e1_prime_f, 'print': e1_print_f}
            return     {'travel': e2_travel_f, 'z_hop': e2_z_hop_f,
                        'retract': e2_retract_f, 'prime': e2_prime_f, 'print': e2_print_f}

        header       = data[0]
        startup      = data[1]
        layer_chunks = data[2:-1]
        ending       = data[-1]

        # Build layer_num → Z map.  Prefer ;Z: markers; fall back to the minimum
        # G0/G1 Z value seen in each layer (actual print height < any z-hop/park).
        # Both T0 and T1 raw gcode use Z before axis renaming, so both axes share
        # this map.
        layer_z = {}
        _layer_z_min = {}   # fallback: minimum Z per layer; actual print height < any z-hop/park
        _cur_z_layer = -1
        for chunk in layer_chunks:
            for line in chunk.split('\n'):
                s    = line.strip()
                gp_s = s[:s.index(';')] if ';' in s else s
                lm = self._LAYER_RE.match(s)
                if lm:
                    _cur_z_layer = int(lm.group(1))
                    continue
                if _cur_z_layer < 0:
                    continue
                zm = self._Z_RE.match(s)
                if zm:
                    layer_z[_cur_z_layer] = float(zm.group(1))
                elif re.match(r'^G[01]\b', gp_s, re.IGNORECASE):
                    zo = re.search(r'(?<=\s)Z([-+]?\d+\.?\d*)', gp_s)
                    if zo:
                        z_val = float(zo.group(1))
                        if z_val < _layer_z_min.get(_cur_z_layer, float('inf')):
                            _layer_z_min[_cur_z_layer] = z_val

        for lnum, zval in _layer_z_min.items():
            if lnum not in layer_z:
                layer_z[lnum] = zval

        # The gcode scan misidentifies Z values when z_hop == layer_height:
        # Cura skips the descent at each layer start (the z-hop lands exactly
        # at the next print height), so the fallback captures z-hop exit
        # heights (one layer too high) and the last layer has no z-hop at all.
        # Recompute from the slicer's layer-height settings instead.
        try:
            _lh0 = float(gs.getProperty("layer_height_0", "value"))
            _lh  = float(gs.getProperty("layer_height",   "value"))
            if _lh0 > 0 and _lh > 0 and _cur_z_layer >= 0:
                for _n in range(_cur_z_layer + 1):
                    layer_z[_n] = round(_lh0 + _n * _lh, 4)
        except Exception:
            pass

        startup = self._clean_startup(startup)
        ending  = self._strip_temp_fan(ending)
        ending  = self._strip_ending(ending)

        # ------------------------------------------------------------------
        # Build mesh maps from the scene graph.
        #
        # _build_mesh_maps simulates StartSliceJob's #N suffix assignment
        # (DepthFirstIterator order, per-name counter) to reconstruct the
        # exact gcode mesh name for every node, then maps each name to its
        # extruder position and its group key.
        #
        # group_key for grouped meshes  : f"__group_{id(parent_node)}"
        # group_key for standalone meshes: the gcode name itself
        #
        # All meshes sharing a group_key are printed together layer-by-layer
        # as one part before moving to the next part.
        # ------------------------------------------------------------------
        mesh_extruder_map, mesh_group_map, group_center_map, group_name_map = \
            self._build_mesh_maps(app)

        scope     = 0    # extruder for current mesh section
        cur_group = None # group_key for current mesh section

        annotated = []
        cur_layer = -1
        cur_mesh  = None

        # Where the moves inside a ;MESH:NONMESH run were heading, and whether
        # the mesh section that follows has had its first motion yet.
        #
        # NONMESH lines are dropped because travels BETWEEN parts are meaningless
        # once the parts are reordered. The last of them is different: at every
        # layer change CuraEngine writes the travel that positions the nozzle for
        # the next layer under NONMESH, so dropping it left the part extruding
        # from wherever the previous one finished. The extrusion is still the
        # amount computed for the intended segment, so it lands over the wrong
        # distance: a blob at the seam when the layer reopens on its wall, a thin
        # dragged line when it reopens on infill.
        orphan_x = None
        orphan_y = None
        awaiting_first_move = False

        # The feedrate CuraEngine has in effect. It writes F only when the value
        # CHANGES, so an extrusion move carrying no F of its own means "same as
        # the line before" — and the line that set it is often one dropped below.
        # The prime before a wall is the usual case: it is a lone B/C move, so it
        # goes, and the wall was left running at whatever else survived, normally
        # a travel. Tracked here, above every continue, for that reason.
        self._src_f = None

        for chunk in layer_chunks:
            for raw_line in chunk.split('\n'):
                stripped = raw_line.strip()
                src_gp = stripped[:stripped.index(';')] if ';' in stripped else stripped
                if self._G01_RE.match(src_gp):
                    src_fm = self._F_RE.search(src_gp)
                    if src_fm:
                        self._src_f = src_fm.group(1)

                lm = self._LAYER_RE.match(stripped)
                if lm:
                    cur_layer = int(lm.group(1))
                    annotated.append({'kind': 'layer_marker', 'tool': scope,
                                      'layer': cur_layer, 'mesh': cur_mesh,
                                      'line': raw_line})
                    continue

                mm = self._MESH_RE.match(stripped)
                if mm:
                    name = mm.group(1).strip()
                    if name == 'NONMESH':
                        cur_mesh  = None
                        cur_group = None
                        orphan_x = orphan_y = None   # only this run's travels count
                    else:
                        cur_mesh = name
                        awaiting_first_move = True
                        # Strip StartSliceJob's dedup suffix (#N) as fallback for lookup.
                        base = re.sub(r'\s+#\d+$', '', name)
                        mapped_ext = mesh_extruder_map.get(name, mesh_extruder_map.get(base))
                        if mapped_ext is not None:
                            scope = mapped_ext
                        mapped_grp = mesh_group_map.get(name, mesh_group_map.get(base))
                        cur_group = mapped_grp if mapped_grp is not None else name
                    continue

                if self._TEMP_FAN_RE.match(stripped):
                    continue

                tm = self._T_RE.match(stripped)
                if tm:
                    # T commands reset mesh context (travel after tool change)
                    # but do NOT set scope — the mesh map is the authoritative source.
                    cur_mesh  = None
                    cur_group = None
                    annotated.append({'kind': 'tool_change', 'tool': scope,
                                      'layer': cur_layer, 'mesh': None,
                                      'line': raw_line})
                    continue

                renamed = self._rename_t0(raw_line) if scope == 0 \
                          else self._rename_t1(raw_line)

                if cur_mesh is None:
                    # Still dropped, but remember where it was going: the last
                    # destination in this run is where the next part expects the
                    # nozzle to be.
                    orphan_gp = (raw_line[:raw_line.index(';')]
                                 if ';' in raw_line else raw_line).strip()
                    if self._G01_RE.match(orphan_gp):
                        xm = self._X_RE.search(orphan_gp)
                        ym = self._Y_RE.search(orphan_gp)
                        if xm:
                            orphan_x = float(xm.group(1))
                        if ym:
                            orphan_y = float(ym.group(1))
                    continue

                gp = (renamed[:renamed.index(';')] if ';' in renamed else renamed).strip()

                if self._is_cura_retraction_or_hop(gp):
                    continue

                # Apply F overrides; split combined XY+Z/A lines (Z/A first).
                # Re-apply the hop/retraction filter to each split result — a combined
                # XY+Z/A line passes the original filter (has_xy=True), but the pure
                # Z/A half produced by _set_f must still be dropped.
                for proc in self._set_f(renamed, _spd(scope)):
                    proc_gp = (proc[:proc.index(';')] if ';' in proc else proc).strip()
                    if self._is_cura_retraction_or_hop(proc_gp):
                        continue

                    # First motion of a mesh section: if it extrudes, the nozzle
                    # has to be put where that extrusion begins, because the move
                    # that would have done it was dropped with the NONMESH run.
                    # A section opening with its own travel needs nothing, and
                    # restoring a between-parts staging move there would drag a
                    # pointless trip across the plate into a one-at-a-time part.
                    if awaiting_first_move and self._G01_RE.match(proc_gp):
                        has_xy = bool(re.search(r'(?<=\s)[XY][-+]?\d', proc_gp))
                        has_bc = bool(re.search(r'(?<=\s)[BC][-+]?\d', proc_gp))
                        if has_xy and has_bc \
                                and orphan_x is not None and orphan_y is not None:
                            annotated.append(
                                {'kind': 'gcode', 'tool': scope,
                                 'layer': cur_layer, 'mesh': cur_mesh,
                                 'group': cur_group,
                                 'line': f'G0 X{orphan_x:.3f} Y{orphan_y:.3f}'
                                         f' F{_spd(scope)["travel"]}'})
                        awaiting_first_move = False
                        orphan_x = orphan_y = None

                    annotated.append({'kind': 'gcode', 'tool': scope,
                                      'layer': cur_layer, 'mesh': cur_mesh,
                                      'group': cur_group, 'line': proc})

        # ------------------------------------------------------------------
        # Group lines into part_layers keyed by group_key.
        # Grouped objects share a key so their T0/T1 content accumulates
        # in the same per-layer buckets and is printed together.
        # Standalone objects use their gcode name as their own key.
        # ------------------------------------------------------------------
        part_layers    = {}   # {group_key: {layer: {'t0': [], 't1': []}}}
        max_layer_seen = 0

        for entry in annotated:
            if entry['kind'] != 'gcode' or entry['mesh'] is None:
                continue

            group_key = entry.get('group')
            if group_key is None:
                continue

            layer = entry['layer']
            tool  = entry['tool']

            if layer > max_layer_seen:
                max_layer_seen = layer

            part_layers.setdefault(group_key, {})
            part_layers[group_key].setdefault(layer, {'t0': [], 't1': []})
            part_layers[group_key][layer]['t0' if tool == 0 else 't1'].append(entry['line'])

        # ------------------------------------------------------------------
        # Global park height — the absolute Print Level Clearance height. The
        # idle extruder parks here regardless of print height so it clears tall
        # obstacles on the bed such as well-plate walls.
        # ------------------------------------------------------------------
        park_z = park_lift

        # ------------------------------------------------------------------
        # Warn for empty parts
        # ------------------------------------------------------------------
        for group_key, ldict in part_layers.items():
            if not any(ldict[ln]['t0'] or ldict[ln]['t1'] for ln in ldict):
                self._warn_empty_part(group_name_map.get(group_key, group_key))

        # ------------------------------------------------------------------
        # Sort parts by distance of centre from the FRONT-LEFT build-plate
        # corner (printer 0,0), nearest first. group_center_map holds scene
        # coordinates (centre origin), so the front-left corner is at
        # (-machine_width/2, +machine_depth/2) — the bed front is +Z. Falls
        # back to the bed centre (0,0) if the machine size can't be read.
        # ------------------------------------------------------------------
        corner_x, corner_z = 0.0, 0.0
        try:
            _gs = app.getGlobalContainerStack()
            corner_x = -float(_gs.getProperty("machine_width", "value")) / 2.0
            corner_z =  float(_gs.getProperty("machine_depth", "value")) / 2.0
        except Exception:
            pass

        def _dist(key):
            if key in group_center_map:
                cx, cy = group_center_map[key]
                return math.hypot(cx - corner_x, cy - corner_z)
            return float('inf')

        sorted_parts = sorted(part_layers.keys(), key=_dist)

        # ------------------------------------------------------------------
        # Emit output
        # ------------------------------------------------------------------
        result = [header]

        # Startup: the clearance lift + XY homing + zero-offset datum routine (see
        # _startup_datum) replaces the old full software zero (G92 X0 Y0 Z0 A0 B0 C0) and
        # the raise-to-park_z hop. It lifts only the syringe of an extruder that actually
        # prints, homes XY, then declares the zero-offset origin with a single non-moving
        # G92 at the known post-home position (XY centered). Z and A are neither homed nor
        # declared: the operator zeroes the axis they are using by hand before printing.
        # The first print move in _emit_part_start provides Z clearance, so no datum
        # travel is emitted.
        _print_has_t0 = any(any(v['t0'] for v in ld.values()) for ld in part_layers.values())
        _print_has_t1 = any(any(v['t1'] for v in ld.values()) for ld in part_layers.values())
        result.append(
            self._startup_datum(_print_has_t0, _print_has_t1) + '\n'
            + startup.rstrip('\n') + '\n')

        # needs_prime[t]: True when tool t was retracted and must prime before printing.
        needs_prime = {0: False, 1: False}
        # tool_retracted[t]: actual retraction state per tool, carried across layer blocks.
        tool_retracted = {0: True, 1: True}
        # travel_pos[t]: last known (x, y) position per tool for min-distance checks.
        travel_pos = {0: (None, None), 1: (None, None)}
        # startup_prime_needed: True until the very first extrusion of the print is primed.
        startup_prime_needed = True

        for part_key in sorted_parts:
            part_name     = group_name_map.get(part_key, part_key)
            layer_dict    = part_layers[part_key]
            sorted_layers = sorted(layer_dict.keys())

            first_layer   = sorted_layers[0]
            t0_starts     = bool(layer_dict[first_layer]['t0'])
            first_x, first_y = self._find_first_xy(layer_dict, sorted_layers, t0_starts)
            part_has_t0   = any(ldata['t0'] for ldata in layer_dict.values())
            part_has_t1   = any(ldata['t1'] for ldata in layer_dict.values())
            first_layer_z = layer_z.get(first_layer, 0.0)

            # The approach travel belongs to the extruder that OPENS the part,
            # which is what t0_starts already decides for the height moves below.
            # Passing extruder 1's speed unconditionally sent every extruder 2
            # part across the plate at extruder 1's travel rate: harmless while
            # the two profiles agreed, and nine times too fast the moment they
            # did not.
            result.append(self._emit_part_start(
                part_name, first_x, first_y,
                e1_travel_f if t0_starts else e2_travel_f,
                park_z, e1_z_hop_f, e2_z_hop_f,
                t0_starts, first_layer_z, part_has_t0, part_has_t1,
                _print_has_t0, _print_has_t1))

            last_tool = None
            # _emit_part_start already moved the active-at-start extruder to
            # first_layer_z, so skip that extruder's height move on its first block.
            first_t0_block_done = False
            first_t1_block_done = False

            for layer_num in sorted_layers:
                ldata    = layer_dict[layer_num]
                t0_lines = ldata['t0']
                t1_lines = ldata['t1']
                has_t0   = bool(t0_lines)
                has_t1   = bool(t1_lines)

                if has_t0:
                    tool_switch = last_tool is not None and last_tool != 0
                    if tool_switch:
                        result.append(self._retract_and_park(
                            tool=1, park_z=park_z, z_hop_f=e2_z_hop_f,
                            retract_amount=e2_retract, retract_f=e2_retract_f,
                            retraction_enabled=retraction_enabled[1]))
                        tool_retracted[1] = True

                    do_prime = tool_switch or needs_prime[0]
                    needs_prime[0] = False

                    z_val = layer_z.get(layer_num, 0.0)
                    if not first_t0_block_done and t0_starts:
                        block = [f';LAYER:{layer_num}']
                        if startup_prime_needed:
                            if retraction_enabled[0]:
                                t0_lines = self._insert_prime_before_first_extrusion(
                                    t0_lines, 'B', e1_retract, e1_prime_f)
                            startup_prime_needed = False
                    else:
                        block = [f';LAYER:{layer_num}']
                        if tool_switch:
                            # This tool is parked high: travel in XY first, then
                            # descend, so it never crosses the print at layer height.
                            xy_line, t0_lines = self._hoist_first_travel_xy(t0_lines)
                            if xy_line is not None:
                                block.append(xy_line)
                                xm = self._X_RE.search(xy_line)
                                ym = self._Y_RE.search(xy_line)
                                travel_pos[0] = (float(xm.group(1)) if xm else travel_pos[0][0],
                                                 float(ym.group(1)) if ym else travel_pos[0][1])
                        block.append(f'G1 Z{z_val:.3f} F{e1_z_hop_f}')
                    first_t0_block_done = True
                    if do_prime and retraction_enabled[0]:
                        t0_lines = self._insert_prime_before_first_extrusion(
                            t0_lines, 'B', e1_retract, e1_prime_f)
                    if retract_before_travel[0] and retraction_enabled[0]:
                        cx, cy = travel_pos[0]
                        t0_lines, tool_retracted[0], cx, cy = self._apply_travel_retract(
                            t0_lines, 'B', e1_retract, e1_retract_f, e1_prime_f,
                            is_retracted=tool_retracted[0],
                            min_dist=retract_before_travel_min_dist[0], cur_x=cx, cur_y=cy)
                        travel_pos[0] = (cx, cy)
                    block.extend(t0_lines)
                    result.append('\n'.join(block) + '\n')
                    last_tool = 0

                if has_t1:
                    tool_switch = last_tool is not None and last_tool != 1
                    if tool_switch:
                        result.append(self._retract_and_park(
                            tool=0, park_z=park_z, z_hop_f=e1_z_hop_f,
                            retract_amount=e1_retract, retract_f=e1_retract_f,
                            retraction_enabled=retraction_enabled[0]))
                        tool_retracted[0] = True

                    do_prime = tool_switch or needs_prime[1]
                    needs_prime[1] = False

                    a_val = layer_z.get(layer_num, 0.0)
                    if not first_t1_block_done and not t0_starts:
                        block = [f';LAYER:{layer_num}']
                        if startup_prime_needed:
                            if retraction_enabled[1]:
                                t1_lines = self._insert_prime_before_first_extrusion(
                                    t1_lines, 'C', e2_retract, e2_prime_f)
                            startup_prime_needed = False
                    else:
                        block = [f';LAYER:{layer_num}']
                        if tool_switch:
                            # This tool is parked high: travel in XY first, then
                            # descend, so it never crosses the print at layer height.
                            xy_line, t1_lines = self._hoist_first_travel_xy(t1_lines)
                            if xy_line is not None:
                                block.append(xy_line)
                                xm = self._X_RE.search(xy_line)
                                ym = self._Y_RE.search(xy_line)
                                travel_pos[1] = (float(xm.group(1)) if xm else travel_pos[1][0],
                                                 float(ym.group(1)) if ym else travel_pos[1][1])
                        block.append(f'G1 A{a_val:.3f} F{e2_z_hop_f}')
                    first_t1_block_done = True
                    if do_prime and retraction_enabled[1]:
                        t1_lines = self._insert_prime_before_first_extrusion(
                            t1_lines, 'C', e2_retract, e2_prime_f)
                    if retract_before_travel[1] and retraction_enabled[1]:
                        cx, cy = travel_pos[1]
                        t1_lines, tool_retracted[1], cx, cy = self._apply_travel_retract(
                            t1_lines, 'C', e2_retract, e2_retract_f, e2_prime_f,
                            is_retracted=tool_retracted[1],
                            min_dist=retract_before_travel_min_dist[1], cur_x=cx, cur_y=cy)
                        travel_pos[1] = (cx, cy)
                    block.extend(t1_lines)
                    result.append('\n'.join(block) + '\n')
                    last_tool = 1

            if last_tool is None:
                continue

            result.append(self._retract_and_park(
                tool=last_tool, park_z=park_z,
                z_hop_f=e1_z_hop_f if last_tool == 0 else e2_z_hop_f,
                retract_amount=e1_retract if last_tool == 0 else e2_retract,
                retract_f=e1_retract_f if last_tool == 0 else e2_retract_f,
                retraction_enabled=retraction_enabled[last_tool]))
            needs_prime[0] = True
            needs_prime[1] = True
            tool_retracted[0] = True
            tool_retracted[1] = True

        result.append(ending)
        return self._to_absolute_extrusion(result)

    # ------------------------------------------------------------------
    # Scene graph helpers
    # ------------------------------------------------------------------

    def _build_mesh_maps(self, app):
        """Build four maps from the scene graph.

        Simulates StartSliceJob's #N suffix assignment by iterating nodes via
        DepthFirstIterator in the same order and applying the same per-name
        counter. Non-printing meshes (anti_overhang, infill, cutting) are
        counted for correct suffix numbering but excluded from the returned
        maps since they appear as ;;MESH:NONMESH in the gcode.

        Returns:
            mesh_extruder_map  {gcode_name: extruder_position}
            mesh_group_map     {gcode_name: group_key}
            group_center_map   {group_key: (cx, cy)}
            group_name_map     {group_key: readable_name}

        group_key for grouped meshes   : f"__group_{id(parent_node)}"
        group_key for standalone meshes: gcode_name
        """
        from UM.Scene.Iterator.DepthFirstIterator import DepthFirstIterator
        scene = app.getController().getScene()

        name_counts       = {}  # simulates StartSliceJob's _mesh_name_counts
        mesh_extruder_map = {}
        mesh_group_map    = {}
        group_center_map  = {}
        group_name_map    = {}

        for node in DepthFirstIterator(scene.getRoot()):
            mesh_data = node.getMeshData()
            if not node.callDecoration("isSliceable") \
                    or mesh_data is None \
                    or mesh_data.getVertices() is None:
                continue

            base_name = node.getName()
            if not base_name:
                continue

            # Replicate StartSliceJob's #N deduplication counter.
            count     = name_counts.get(base_name, 0)
            gcode_name = base_name if count == 0 else f"{base_name} #{count + 1}"
            name_counts[base_name] = count + 1

            # Non-printing meshes (anti_overhang, infill, cutting) appear as
            # ;;MESH:NONMESH in the gcode — counted above for correct #N offsets
            # for subsequent nodes, but not added to the lookup maps.
            if bool(node.callDecoration("isNonPrintingMesh")):
                continue

            # Extruder assignment
            try:
                pos = int(node.callDecoration("getActiveExtruderPosition"))
            except Exception:
                pos = 0
            mesh_extruder_map[gcode_name] = pos

            # Group membership
            parent = node.getParent()
            if parent is not None and parent.callDecoration("isGroup"):
                group_key = f"__group_{id(parent)}"
                if group_key not in group_center_map:
                    bb = parent.getBoundingBox()
                    if bb is not None:
                        group_center_map[group_key] = (bb.center.x, bb.center.z)
                    group_name_map[group_key] = parent.getName() or group_key
            else:
                group_key = gcode_name
                bb = node.getBoundingBox()
                if bb is not None:
                    group_center_map[gcode_name] = (bb.center.x, bb.center.z)
                group_name_map[gcode_name] = gcode_name

            mesh_group_map[gcode_name] = group_key

        return mesh_extruder_map, mesh_group_map, group_center_map, group_name_map

    # ------------------------------------------------------------------
    # Transition helpers
    # ------------------------------------------------------------------

    def _apply_travel_retract(self, lines, e_char, retract_amount, retract_f, prime_f, is_retracted, min_dist=0.0, cur_x=None, cur_y=None):
        """Insert retraction before pure XY travels and prime before XY+extrusion moves.

        Tracks existing pure B/C moves in the line list so it doesn't duplicate
        retractions or primes already embedded by other mechanisms (startup, lc, do_prime).
        """
        result = []
        for line in lines:
            gp = (line[:line.index(';')] if ';' in line else line).strip()
            if not re.match(r'^G[01]\b', gp, re.IGNORECASE):
                result.append(line)
                continue
            has_xy     = bool(re.search(r'(?<=\s)[XY][-+]?\d', gp))
            has_bc     = bool(re.search(rf'(?<=\s){e_char}[-+]?\d', gp))
            has_pos_bc = bool(re.search(rf'(?<=\s){e_char}[+]?\d', gp))
            if has_xy and not has_bc:
                # Pure XY travel
                if not is_retracted:
                    xm = re.search(r'(?<=\s)X([-+]?\d+\.?\d*)', gp)
                    ym = re.search(r'(?<=\s)Y([-+]?\d+\.?\d*)', gp)
                    dest_x = float(xm.group(1)) if xm else cur_x
                    dest_y = float(ym.group(1)) if ym else cur_y
                    if min_dist <= 0.0 or cur_x is None or cur_y is None:
                        do_retract = True
                    else:
                        dx = (dest_x - cur_x) if dest_x is not None else 0.0
                        dy = (dest_y - cur_y) if dest_y is not None else 0.0
                        do_retract = math.sqrt(dx * dx + dy * dy) >= min_dist
                    if do_retract:
                        result.append(f'G1 {e_char}{-retract_amount:.5f} F{retract_f}')
                        is_retracted = True
                xm = re.search(r'(?<=\s)X([-+]?\d+\.?\d*)', gp)
                ym = re.search(r'(?<=\s)Y([-+]?\d+\.?\d*)', gp)
                if xm: cur_x = float(xm.group(1))
                if ym: cur_y = float(ym.group(1))
            elif has_xy and has_pos_bc:
                # XY + extrusion (print move)
                if is_retracted:
                    result.append(f'G1 {e_char}{retract_amount:.5f} F{prime_f}')
                    is_retracted = False
                xm = re.search(r'(?<=\s)X([-+]?\d+\.?\d*)', gp)
                ym = re.search(r'(?<=\s)Y([-+]?\d+\.?\d*)', gp)
                if xm: cur_x = float(xm.group(1))
                if ym: cur_y = float(ym.group(1))
            elif not has_xy and has_bc:
                # Lone retract or prime already in content — track state to avoid doubles
                bc_m = re.search(rf'(?<=\s){e_char}([-+]?\d+\.?\d*)', gp)
                val = float(bc_m.group(1)) if bc_m else 0.0
                if val < 0:
                    is_retracted = True
                elif val > 0:
                    is_retracted = False
            result.append(line)
        return result, is_retracted, cur_x, cur_y

    def _insert_prime_before_first_extrusion(self, lines, e_char, prime_amount, prime_f):
        """Return lines with a prime inserted just before the first extrusion move."""
        prime_line = f'G1 {e_char}{prime_amount:.5f} F{prime_f}'
        for i, line in enumerate(lines):
            gp = (line[:line.index(';')] if ';' in line else line).strip()
            if re.match(r'^G[01]\b', gp, re.IGNORECASE) \
                    and re.search(rf'(?<=\s){e_char}[+]?\d', gp):
                return lines[:i] + [prime_line] + lines[i:]
        return lines

    def _retract_and_park(self, tool, park_z, z_hop_f, retract_amount, retract_f, retraction_enabled=True):
        axis_e = 'B' if tool == 0 else 'C'
        axis_z = 'Z' if tool == 0 else 'A'
        lines = []
        if retraction_enabled:
            lines.append(f'G1 {axis_e}{-retract_amount:.5f} F{retract_f}')
        lines.append(f'G1 {axis_z}{park_z:.3f} F{z_hop_f}')
        return '\n'.join(lines) + '\n'

    def _emit_part_start(self, part_name, first_x, first_y, travel_f, park_z,
                         t0_z_hop_f, t1_z_hop_f, t0_starts, first_layer_z,
                         part_has_t0, part_has_t1, print_has_t0, print_has_t1):
        lines = [f'; --- Part: {part_name} ---']
        # XY first — the axes are already lifted clear (post-home hop, or park_z from a
        # previous part's retract-and-park), so horizontal travel is safe before setting heights.
        #
        # travel_f must be the travel speed of the extruder named by t0_starts:
        # this move carries the tool that is about to print, and the two profiles
        # can hold very different travel speeds.
        if first_x is not None:
            lines.append(f'G1 X{first_x:.3f} Y{first_y:.3f} F{travel_f}')
        # Lower the active extruder to first_layer_z and hold the idle extruder at park_z
        # (the absolute clearance height). Setting the idle axis to park_z only ever raises it
        # — the post-home hop is lower and between parts it is already parked — so the idle
        # nozzle always clears bed obstacles such as well-plate walls.
        #
        # An axis is only commanded when the PRINT as a whole uses its tool: _startup_datum
        # homes and G92-zeroes Z only when extruder 0 prints and A only when extruder 1 does,
        # so touching the other axis here would drive it from an undefined position. The
        # part-level flags decide which axis descends; the print-level flags decide whether
        # the idle axis exists at all.
        terms, feeds = [], []
        if part_has_t0:
            terms.append(f'Z{(first_layer_z if t0_starts else park_z):.3f}')
            feeds.append(t0_z_hop_f)
        elif print_has_t0:
            terms.append(f'Z{park_z:.3f}')
            feeds.append(t0_z_hop_f)
        if part_has_t1:
            terms.append(f'A{(first_layer_z if not t0_starts else park_z):.3f}')
            feeds.append(t1_z_hop_f)
        elif print_has_t1:
            terms.append(f'A{park_z:.3f}')
            feeds.append(t1_z_hop_f)
        if terms:
            lines.append('G1 ' + ' '.join(terms) + f' F{min(feeds)}')
        return '\n'.join(lines) + '\n'

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------

    def _hoist_first_travel_xy(self, lines):
        """Pull a block's opening XY travel out so it can be emitted BEFORE the
        height move.

        Used when a tool takes over mid-part: that tool is sitting at the park
        height, so it must travel across in XY first and only then descend to the
        layer height. Any pure Z/A move that preceded the travel is dropped —
        the caller emits the descend itself.

        Returns (xy_line, remaining_lines); (None, lines) when the block does not
        start with a plain travel, in which case the caller keeps the original
        order rather than risk reordering an extruding move.
        """
        drop = []
        for i, line in enumerate(lines):
            gp = line[:line.index(';')] if ';' in line else line
            if not self._G01_RE.match(gp.strip()):
                continue  # comments, M/T commands: leave untouched
            has_xy = bool(self._X_RE.search(gp) or self._Y_RE.search(gp))
            has_za = bool(re.search(r'(?<=\s)[ZA][-+]?\d', gp))
            has_bc = bool(re.search(r'(?<=\s)[BCE][-+]?\d', gp))
            if not has_xy:
                if has_za and not has_bc:
                    drop.append(i)  # standalone descend: replaced by the caller's
                continue            # pure retract/prime moves stay where they are
            if has_bc:
                return None, lines  # already extruding: never reorder
            cleaned = re.sub(r'\s[ZA][-+]?\d+\.?\d*', '', gp).rstrip()
            comment = line[line.index(';'):] if ';' in line else ''
            remaining = [l for j, l in enumerate(lines) if j != i and j not in drop]
            return cleaned + comment, remaining
        return None, lines

    def _find_first_xy(self, layer_dict, sorted_layers, t0_starts):
        bucket = 't0' if t0_starts else 't1'
        for ln in sorted_layers:
            for line in layer_dict[ln][bucket]:
                gp = (line[:line.index(';')] if ';' in line else line).strip()
                if not self._G01_RE.match(gp):
                    continue
                xm = self._X_RE.search(gp)
                ym = self._Y_RE.search(gp)
                if xm or ym:
                    return (float(xm.group(1)) if xm else None,
                            float(ym.group(1)) if ym else None)
        return None, None

    # ------------------------------------------------------------------
    # F-override helper
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Line filtering helpers
    # ------------------------------------------------------------------

    def _clean_startup(self, chunk):
        """Strip temperature/fan commands and lone E moves from startup."""
        out = []
        for line in chunk.split('\n'):
            s  = line.strip()
            gp = s[:s.index(';')] if ';' in s else s
            if self._TEMP_FAN_RE.match(gp):
                continue
            if self._G01_RE.match(gp):
                has_xy = bool(re.search(r'(?<=\s)[XY][-+]?\d', gp))
                has_z  = bool(re.search(r'(?<=\s)Z[-+]?\d',    gp))
                has_e  = bool(re.search(r'(?<=\s)E[-+]?\d',    gp))
                if has_e and not has_xy and not has_z:
                    continue
            out.append(line)
        return '\n'.join(out)

    def _strip_temp_fan(self, chunk):
        return '\n'.join(
            l for l in chunk.split('\n')
            if not self._TEMP_FAN_RE.match(l.strip()))

    def _strip_ending(self, chunk):
        """Strip lone E retracts and lone Z raises from ending chunk."""
        out = []
        for line in chunk.split('\n'):
            s  = line.strip()
            gp = s[:s.index(';')] if ';' in s else s
            if self._G01_RE.match(gp):
                has_xy = bool(re.search(r'(?<=\s)[XY][-+]?\d', gp))
                has_e  = bool(re.search(r'(?<=\s)E[-+]?\d', gp))
                has_z  = bool(re.search(r'(?<=\s)Z[-+]?\d', gp))
                if not has_xy and (has_e or has_z):
                    continue
            out.append(line)
        return '\n'.join(out)

    def _is_cura_retraction_or_hop(self, gp):
        """True for lone retraction/prime (B/C only) or lone Z-hop (Z/A only)
        or G92 resets — all of which we replace with our own inserts."""
        has_xy = bool(self._X_RE.search(gp) or self._Y_RE.search(gp))
        if has_xy:
            return False
        if self._G92_RE.match(gp):
            return True
        if self._G01_RE.match(gp):
            has_e = bool(re.search(r'(?<=\s)[BC][-+]?\d', gp))
            has_z = bool(re.search(r'(?<=\s)[ZA][-+]?\d', gp))
            return has_e ^ has_z
        return False

    # ------------------------------------------------------------------
    # Rename helpers
    # ------------------------------------------------------------------

    def _rename_t0(self, line):
        """E→B on G0, G1, G92; all other lines pass through unchanged."""
        gp, cp = (line[:line.index(';')], line[line.index(';'):]) \
                 if ';' in line else (line, '')
        s = gp.strip()
        if not s:
            return line
        m = re.match(r'^(G\d+)', s, re.IGNORECASE)
        if m and m.group(1).upper() in ('G0', 'G1', 'G92'):
            gp = re.sub(r'(?<=\s)E(?=[-+]?\d)', 'B', gp)
            return gp + cp
        return line

    def _rename_t1(self, line):
        """Z→A, E→C on G0, G1, G92; all other lines pass through unchanged."""
        gp, cp = (line[:line.index(';')], line[line.index(';'):]) \
                 if ';' in line else (line, '')
        s = gp.strip()
        if not s:
            return line
        m = re.match(r'^(G\d+)', s, re.IGNORECASE)
        if m and m.group(1).upper() in ('G0', 'G1', 'G92'):
            gp = re.sub(r'(?<=\s)Z(?=[-+]?\d)', 'A', gp)
            gp = re.sub(r'(?<=\s)E(?=[-+]?\d)', 'C', gp)
            return gp + cp
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

    # ------------------------------------------------------------------
    # Warning helper
    # ------------------------------------------------------------------

    def _warn_empty_part(self, mesh_name):
        msg = Message(
            text=catalog.i18nc(
                "@message",
                f'Object "{mesh_name}" produced no printable G-code after '
                f'processing. It will be skipped. Check that it is assigned '
                f'to an active extruder.'),
            title=catalog.i18nc("@message:title", "Empty Part Warning"),
            message_type=Message.MessageType.WARNING)
        msg.show()
