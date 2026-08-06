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

PARK_LIFT = 30.0  # absolute park height (mm); fallback if the setting is unreadable

# Startup-datum constants (see _startup_datum). After the printer's custom G28, XY is
# centred on the build plate and Z/A are hopped clear; these are the resulting positions in
# the homed frame. The datum G92 declares the zero-offset origin relative to them without
# moving, so the old datum feedrate / raise constants are no longer needed.
PLATE_CENTER_X = 63.0   # mm from the X endstop: build-plate centre after G28
PLATE_CENTER_Y = 42.0   # mm from the Y endstop: build-plate centre after G28
G28_HOP        = 30.0   # mm: height G28 hops Z and A to after homing

# Relative clearance lift emitted at the very top of the file, before homing, so the
# nozzles rise off the bed first. Only the axis of an extruder that actually prints is
# commanded (Z for extruder 0, A for extruder 1).
STARTUP_CLEARANCE   = 35.0   # mm to raise
STARTUP_CLEARANCE_F = 200.0  # feedrate for that lift


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
        e0_travel_f  = 240;   e1_travel_f  = 240
        e0_z_hop_f   = 240;   e1_z_hop_f   = 240
        e0_print_f   = 240;   e1_print_f   = 240
        e0_retract   = 0.1;   e1_retract   = 0.1
        e0_retract_f = 240;   e1_retract_f = 240
        e0_prime_f   = 240;   e1_prime_f   = 240
        park_lift                      = PARK_LIFT
        retraction_enabled             = {0: True,  1: True}
        retract_before_travel          = {0: False, 1: False}
        retract_before_travel_min_dist = {0: 3.0,   1: 3.0}

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

        result = []

        # The feedrate CuraEngine has in effect. It writes F only when the value
        # CHANGES, so an extrusion move carrying no F of its own means "same as
        # the line before" — and the line that set it is often one dropped below,
        # typically the prime before a wall. Tracked above every continue so the
        # value survives the drop.
        self._src_f = None

        for chunk in data:
            out_lines = []
            for line in chunk.split('\n'):
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
                    out_lines.append(line)
                    continue

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
                            # XY+height move: XY first at park height, then lower, then prime
                            height_val = float(h_match.group(1))
                            current_layer_z = height_val
                            xy_line = re.sub(rf'\s{height_axis}[-+]?\d+\.?\d*', '', renamed).rstrip()
                            out_lines.extend(self._set_f(xy_line, spd))
                            out_lines.extend(self._set_f(f'G1 {height_axis}{height_val:.3f} F{spd["z_hop"]}', spd))
                        else:
                            # Pure XY: emit then lower, then prime
                            out_lines.extend(self._set_f(renamed, spd))
                            out_lines.extend(self._set_f(f'G1 {height_axis}{current_layer_z:.3f} F{spd["z_hop"]}', spd))

                        if retraction_enabled[scope]:
                            out_lines.extend(self._set_f(f'G1 {e_char}{ra:.5f} F{spd["prime"]}', spd))
                            is_retracted[scope] = False
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
                    # First XY move of the print: lower only the ACTIVE extruder to the
                    # current layer height. The idle extruder is no longer parked here —
                    # G28 homing at the top of the file positions every axis. We still
                    # consume the idle extruder's first activation entry so the park
                    # heights computed at later tool changes stay correctly aligned.
                    inactive = 1 if scope == 0 else 0
                    if activation_z[inactive]:
                        activation_z[inactive].popleft()
                    out_lines.extend(self._set_f(f'G1 {height_axis}{current_layer_z:.3f} F{spd["z_hop"]}', spd))
                    if h_match_n:
                        xy_line = re.sub(rf'\s{height_axis}[-+]?\d+\.?\d*', '', renamed).rstrip()
                        out_lines.extend(self._set_f(xy_line, spd))
                    else:
                        out_lines.extend(self._set_f(renamed, spd))
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

                    if startup_prime_needed and is_g01_n and has_pos_bc:
                        if retraction_enabled[scope]:
                            out_lines.extend(self._set_f(f'G1 {e_char_sp}{ra_sp:.5f} F{spd["prime"]}', spd))
                        startup_prime_needed = False
                        is_retracted[scope] = False
                    elif retract_before_travel[scope] and retraction_enabled[scope] and layer_initialized and is_g01_n:
                        if h_match_n and not has_xy_n and not has_any_bc and not is_retracted[scope]:
                            out_lines.extend(self._set_f(f'G1 {e_char_sp}{-ra_sp:.5f} F{spd["retract"]}', spd))
                            is_retracted[scope] = True
                        elif has_xy_n:
                            if not has_any_bc and not is_retracted[scope]:
                                xm = re.search(r'(?<=\s)X([-+]?\d+\.?\d*)', rgp_n)
                                ym = re.search(r'(?<=\s)Y([-+]?\d+\.?\d*)', rgp_n)
                                dest_x = float(xm.group(1)) if xm else cur_x
                                dest_y = float(ym.group(1)) if ym else cur_y
                                if retract_before_travel_min_dist[scope] <= 0.0 or cur_x is None or cur_y is None:
                                    do_retract = True
                                else:
                                    dx = (dest_x - cur_x) if dest_x is not None else 0.0
                                    dy = (dest_y - cur_y) if dest_y is not None else 0.0
                                    do_retract = math.sqrt(dx * dx + dy * dy) >= retract_before_travel_min_dist[scope]
                                if do_retract:
                                    out_lines.extend(self._set_f(f'G1 {e_char_sp}{-ra_sp:.5f} F1', spd))
                                    is_retracted[scope] = True
                            elif has_pos_bc and is_retracted[scope]:
                                out_lines.extend(self._set_f(f'G1 {e_char_sp}{ra_sp:.5f} F{spd["prime"]}', spd))
                                is_retracted[scope] = False
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
            # Homing (G28) + the zero-offset datum routine (see _startup_datum) establish the
            # datum, replacing the old full software zero (G92 X0 Y0 Z0 A0 B0 C0). These lines
            # are added after the header comments (result[0]) and are exempt from axis renaming
            # because they are inserted after the main rename pass.
            result[1] = self._startup_datum(has_t0, has_t1) + '\n' + result[1]
        return self._to_absolute_extrusion(result)

    # -------------------------------------------------------------------------

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
        """Build the clearance lift + homing + zero-offset datum block.

        Order:
            G91                              relative mode, for the lift only
            G1 Z.. A.. F..                   raise the used carriage(s) clear of the bed
                                             before homing. Only the axis of a tool that
                                             actually prints is commanded: Z for extruder 0,
                                             A for extruder 1 (T1's Z is renamed to A).
            G90                              absolute mode
            G28 <homed axes>                 combined home; only the checkbox-enabled axes
                                             (Z needs extruder 0, A needs extruder 1). The
                                             printer's G28 then centres XY on the plate
                                             (PLATE_CENTER_*) and hops Z/A clear (G28_HOP).
            G92 X.. Y.. Z.. A.. B0 C0        declare the zero-offset origin at that post-home
                                             position WITHOUT moving

        G92 sets the current position rather than driving to it, so nothing has to move: the
        machine is already at a known spot after G28 (XY at PLATE_CENTER_*, Z/A at G28_HOP),
        and each axis value is that known position minus its offset. Subtracting the offset
        shifts the print origin away from the endstop by that many mm; an offset of 0 simply
        keeps the post-home position as the origin. The first print move provides Z clearance,
        so no separate raise/lower travel is emitted.

        X/Y are gated on printess/home_xy; Z on (printess/home_za and extruder 0 prints);
        A on (printess/home_za and extruder 1 prints) — T0 uses the real Z axis, T1's Z is
        renamed to A. Offsets come from printess/zero_offset_{x,y,z,a} (mm from the endstop).
        Only axes that were homed are placed in the G92; B (T0) and C (T1) are always zeroed.
        Returned as a '\\n'-joined string with no trailing newline.
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
        home_za = _flag("printess/home_za")
        z_active = home_za and has_t0
        a_active = home_za and has_t1

        # Relative clearance lift before anything else, so the nozzles come up off
        # the bed before homing. Gated on tool usage only (not on the homing
        # checkboxes): an axis whose extruder never prints is never commanded.
        lines = []
        lift_axes = []
        if has_t0:
            lift_axes.append('Z{0:g}'.format(STARTUP_CLEARANCE))
        if has_t1:
            lift_axes.append('A{0:g}'.format(STARTUP_CLEARANCE))
        if lift_axes:
            lines.append('G91')
            lines.append('G1 ' + ' '.join(lift_axes) + ' F{0:g}'.format(STARTUP_CLEARANCE_F))

        lines.append('G90')

        home_axes = []
        if home_xy:
            home_axes += ['X', 'Y']
        if z_active:
            home_axes.append('Z')
        if a_active:
            home_axes.append('A')
        if home_axes:
            lines.append('G28 ' + ' '.join(home_axes))

        # Declare the zero-offset origin at the known post-home position without moving:
        # each value is (post-home position - offset). Only homed axes are included; the
        # extruder axes B (T0) and C (T1) are always zeroed.
        g92 = []
        if home_xy:
            g92.append(f'X{PLATE_CENTER_X - _num("printess/zero_offset_x"):.3f}')
            g92.append(f'Y{PLATE_CENTER_Y - _num("printess/zero_offset_y"):.3f}')
        if z_active:
            g92.append(f'Z{G28_HOP - _num("printess/zero_offset_z"):.3f}')
        if a_active:
            g92.append(f'A{G28_HOP - _num("printess/zero_offset_a"):.3f}')
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
