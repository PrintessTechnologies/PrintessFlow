# Copyright (c) 2026 Printess Technologies
# Released under the terms of the LGPLv3 or higher.
#
# Builds the Flow Rate Tester strip as PRINTER-READY g-code.
#
# Unlike the Path Designer's GcodeGenerator, which emits CuraEngine-shaped
# g-code and leaves the axis renaming, homing, datum, priming and parking to
# whichever post-processing script is selected, this module writes the final
# file itself. That was a deliberate choice: the tester is a calibration aid
# that has to produce a runnable file whatever the script dropdown happens to
# say, including "None".
#
# The cost of that choice is duplication, so it is contained as tightly as
# possible:
#   - the startup block reproduces PrintessOneAtATime._startup_datum exactly,
#     including reading the same printess/home_* and printess/zero_offset_*
#     preferences, so a user who has changed their homing setup gets the same
#     behavior here as on a real print;
#   - the constants it depends on are declared once, below, and the test
#     harness asserts they still equal the values in PrintessOneAtATime.py.
#     If that script's homing changes, the harness fails rather than the
#     printer.
#
# No Cura imports: everything comes in through the config dict, so the whole
# generator runs (and is tested) standalone.

import math
from typing import Dict, List

# ---------------------------------------------------------------------------
# Machine constants mirrored from PrintessOneAtATime.py.
# scratchpad/test_flow_tester.py parses that script and asserts these match.
# ---------------------------------------------------------------------------
PLATE_CENTER_X = 63.0        # mm from the X endstop: build-plate center after G28
PLATE_CENTER_Y = 42.0        # mm from the Y endstop: build-plate center after G28
STARTUP_CLEARANCE = 50.0     # mm: absolute height to raise the carriage to before XY homes
STARTUP_CLEARANCE_F = 200.0  # feedrate for that lift
PARK_LIFT = 30.0             # absolute park height, fallback if the setting is unreadable

# Strip geometry. Fixed rather than exposed: the point of the test is that every
# line is identical apart from its flow, and a 30 mm line is long enough to read
# a bead width off without spending the plate on one test.
LINE_LENGTH = 30.0
LINE_GAP = 5.0

MAX_LINES = 40   # a guard on the table, not a plate limit; the plate check is separate


def axes_for(extruder: int):
    """Return (vertical axis, extrusion axis) for an extruder.

    Extruder 0 prints on the real Z with its plunger on B; extruder 1's Z is the
    A axis and its plunger is C. This is the same mapping PrintessOneAtATime's
    _rename_t0/_rename_t1 apply, expressed as a choice up front rather than as a
    rename afterwards, because the tester only ever drives one extruder and so
    knows which axes it is allowed to touch before it emits a single line.
    """
    return ("Z", "B") if extruder == 0 else ("A", "C")


def line_positions(count: int, machine_width: float, machine_depth: float):
    """Center the strip on the plate and return [(x_start, x_end, y), ...].

    Row 0 is at the FRONT of the plate (lowest Y) and rows run toward the back,
    so the physical print is read in the same order as the table: the row the
    user typed first is the one nearest them when they face the machine.

    Coordinates are in Cura's build-plate frame (origin at the front-left
    corner). The per-extruder nozzle offset is applied later, in generate(),
    exactly as CuraEngine's getGcodePos() does it.
    """
    span = (count - 1) * LINE_GAP
    x0 = machine_width / 2.0 - LINE_LENGTH / 2.0
    x1 = x0 + LINE_LENGTH
    y0 = machine_depth / 2.0 - span / 2.0
    return [(x0, x1, y0 + i * LINE_GAP) for i in range(count)]


def e_per_mm(cfg: Dict, flow_percent: float) -> float:
    """Plunger travel per mm of bead, for one line's flow setting.

    Cura's own extrusion equation:

        E/mm = line_width x layer_height x flow / (pi (d/2)^2)

    **The table value is the GENERAL flow (material_flow), and it is the ONLY
    flow applied.** Nothing else multiplies it:

      - NOT wall_0_material_flow. A test line is a bare bead, not an outer wall.
      - NOT material_flow_layer_0. The strip is physically a first layer, and
        CuraEngine would apply this to a real one, but applying it here would
        mean a line labeled 110 printing at 110 x that factor, and the number
        read off the strip would not be the number to type into Flow.
      - NOT initial_layer_line_width_factor, for the same reason: it scales the
        width and therefore the deposition, so it would shift every label.

    The point of the tool is to isolate ONE variable. The user prints the strip,
    picks the line that looks right, and types that number into Flow. Anything
    else silently multiplying the labels breaks that, which is the whole value
    of the feature.

    CONSEQUENCE, stated because it is a real trade-off: if a profile sets
    material_flow_layer_0 or initial_layer_line_width_factor away from 100, this
    strip will NOT deposit what a real first layer at the chosen flow would.
    That is deliberate. The strip answers "what should Flow be", not "what will
    my first layer look like".

    The profile's current flow is read and shown for reference only.
    """
    flow = flow_percent / 100.0
    area = math.pi * (cfg["material_diameter"] / 2.0) ** 2
    return cfg["line_width"] * cfg["layer_height_0"] * flow / area


def print_speed(cfg: Dict) -> float:
    """The strip's print speed: the profile's GENERAL print speed.

    speed_print, not speed_wall_0 and not speed_print_layer_0, to match the flow
    it is testing. Reading the flow from the general setting and the speed from
    the outer wall would describe one line as two different features, and the
    initial-layer speed ramp is excluded for the same reason its flow is: the
    strip is a measurement of a general setting, not a simulation of a first
    layer.

    On the Nordson profiles this changes nothing either way - they set
    speed_wall_0 = =speed_print and speed_slowdown_layers = 0 - but it stays
    correct for a profile that gives the walls a speed of their own.
    """
    return cfg["speed"]


def fits_on_plate(count: int, cfg: Dict):
    """Return (ok, message). Checks the strip against the real travel limits.

    The nozzle offset is part of this: on a two-extruder machine the commanded
    coordinate is the drawn position minus that extruder's offset, which on this
    machine is +-15.27 mm, so a strip that fits the plate geometrically can
    still ask the carriage for a position it does not have.
    """
    if count < 1:
        return False, "Add at least one line to the table."
    if count > MAX_LINES:
        return False, "The tester is limited to {0} lines.".format(MAX_LINES)

    w, d = cfg["machine_width"], cfg["machine_depth"]
    ox, oy = cfg["nozzle_offset_x"], cfg["nozzle_offset_y"]
    for (x0, x1, y) in line_positions(count, w, d):
        for (px, py) in ((x0 - ox, y - oy), (x1 - ox, y - oy)):
            if px < 0.0 or px > w or py < 0.0 or py > d:
                span = (count - 1) * LINE_GAP
                return False, (
                    "{0} lines need {1:.0f} mm of depth at {2:.0f} mm spacing, which does not "
                    "fit this printer's {3:.0f} x {4:.0f} mm plate for this extruder. "
                    "Use fewer lines.".format(count, span, LINE_GAP, w, d))
    return True, ""


def _startup(cfg: Dict, extruder: int) -> List[str]:
    """Clearance lift, XY homing and the zero-offset datum.

    Reproduces PrintessOneAtATime._startup_datum. Order and reasoning are that
    script's, kept verbatim so the printer sees the same opening on a test strip
    as on a real print:

        G90                       absolute
        G1 Z.. F..                raise the carriage to STARTUP_CLEARANCE above the
                                  operator's zero, clear of the bed before XY homes
        G28 X Y                   only when the checkbox is on
        G92 X.. Y.. B0 C0         declare the origin at the post-home position, no motion

    Z and A are never homed and never appear in the G92: the operator zeroes the
    axis of the extruder they are using with a manual G92 before printing, and
    every Z/A coordinate here is absolute against that datum. The axis of the
    extruder that is NOT printing is never commanded, which is the axis-homing
    invariant: this is where the tester gets it for free, since it only ever
    drives one extruder. B and C are both zeroed in the G92 because that declares
    a position without moving anything, exactly as the script does.
    """
    z_axis, _ = axes_for(extruder)
    lines = []

    lines.append("G90")
    lines.append("G1 {0}{1:g} F{2:g}".format(z_axis, STARTUP_CLEARANCE, STARTUP_CLEARANCE_F))

    if cfg["home_xy"]:
        lines.append("G28 X Y")

    g92 = []
    if cfg["home_xy"]:
        g92.append("X{0:.3f}".format(PLATE_CENTER_X - cfg["zero_offset_x"]))
        g92.append("Y{0:.3f}".format(PLATE_CENTER_Y - cfg["zero_offset_y"]))
    g92 += ["B0", "C0"]
    lines.append("G92 " + " ".join(g92))

    return lines


def generate(flows: List[float], cfg: Dict) -> str:
    """Build the whole file. Returns the g-code as one string.

    :param flows: one flow percentage per line, front of the plate first.
    :param cfg: every number read off the live machine and profile. See
                PrintessFlowTester._collectSettings for where each one comes
                from; nothing here is defaulted or assumed.
    """
    extruder = int(cfg["extruder"])
    z_axis, e_axis = axes_for(extruder)
    count = len(flows)

    z = cfg["layer_height_0"]
    speed = print_speed(cfg)
    print_f = int(round(speed * 60))
    travel_f = int(round(cfg["travel_speed"] * 60))
    retract_f = int(round(cfg["retract_speed"] * 60))
    prime_f = int(round(cfg["prime_speed"] * 60))
    hop_f = int(round(cfg["z_hop_speed"] * 60))
    retract = cfg["retraction_amount"] if cfg["retraction_enabled"] else 0.0

    positions = line_positions(count, cfg["machine_width"], cfg["machine_depth"])
    ox, oy = cfg["nozzle_offset_x"], cfg["nozzle_offset_y"]

    out: List[str] = []

    # ---- Header -----------------------------------------------------------
    # The user chose not to print index marks beside the lines, so the file is
    # the record of which line is which. Written front-of-plate first, the same
    # order the table shows and the same order they come off the machine.
    out.append(";FLAVOR:Marlin")
    out.append(";Printess Flow Rate Tester")
    out.append(";Extruder: {0}".format(extruder + 1))
    if cfg.get("tip_name"):
        out.append(";Dispense tip: {0}".format(cfg["tip_name"]))
    out.append(";Line width: {0:.3f} mm   Layer height: {1:.3f} mm   Speed: {2:.2f} mm/s"
               .format(cfg["line_width"], z, speed))
    # Recorded, not applied. The table value is the only flow in the extrusion,
    # so anyone reading this file later can see what the profile said at the
    # time without wondering whether it was folded in.
    out.append(";Testing the general Flow (material_flow). Nothing else is applied:")
    out.append(";  profile Flow at the time (reference only): {0:.1f}%".format(cfg["material_flow"]))
    out.append(";  wall flow NOT applied, initial layer flow NOT applied")
    out.append(";{0} lines, {1:.0f} mm long, {2:.0f} mm apart, front of the plate first"
               .format(count, LINE_LENGTH, LINE_GAP))
    for i, flow in enumerate(flows):
        out.append(";  Line {0}: flow {1:.1f}%   plunger {2:.5f} mm over the line"
                   .format(i + 1, flow, LINE_LENGTH * e_per_mm(cfg, flow)))

    out += _startup(cfg, extruder)
    out.append("T{0}".format(extruder))

    # ---- The strip --------------------------------------------------------
    # B/C are emitted ABSOLUTE. The machine definition sets relative_extrusion,
    # but the plunger axes are not E as far as the printer is concerned and it
    # ignores M83 for them, which is why PrintessOneAtATime converts its output
    # to absolute at the end. Accumulating here reaches the same place without a
    # second pass over the text.
    e_pos = 0.0
    descended = False

    for i, (x0, x1, y) in enumerate(positions):
        flow = flows[i]
        epmm = e_per_mm(cfg, flow)

        out.append(";Line {0} - flow {1:.1f}%".format(i + 1, flow))

        # XY before Z on the first line: the carriage is parked at the post-home
        # hop height, so traveling horizontally first is what keeps it clear of
        # the bed. Same order _emit_part_start uses.
        out.append("G0 F{0} X{1:.3f} Y{2:.3f}".format(travel_f, x0 - ox, y - oy))
        if not descended:
            out.append("G0 F{0} {1}{2:.3f}".format(travel_f, z_axis, z))
            descended = True

        if retract > 0.0:
            e_pos += retract
            out.append("G1 {0}{1:.5f} F{2}".format(e_axis, e_pos, prime_f))

        e_pos += LINE_LENGTH * epmm
        out.append("G1 F{0} X{1:.3f} Y{2:.3f} {3}{4:.5f}"
                   .format(print_f, x1 - ox, y - oy, e_axis, e_pos))

        if retract > 0.0:
            e_pos -= retract
            out.append("G1 {0}{1:.5f} F{2}".format(e_axis, e_pos, retract_f))

    # ---- End --------------------------------------------------------------
    # Lift to the absolute Print Level Clearance height, the same park the
    # scripts use, so the finished strip is reachable without the tip over it.
    out.append(";End of print")
    out.append("G1 {0}{1:.3f} F{2}".format(z_axis, cfg["park_lift"], hop_f))
    out.append(";End of Gcode")

    return "\n".join(out) + "\n"
