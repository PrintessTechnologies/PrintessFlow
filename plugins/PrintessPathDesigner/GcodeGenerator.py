# Copyright (c) 2026 Printess Technologies
# Released under the terms of the LGPLv3 or higher.
#
# Generates Cura-style g-code directly from drawn paths, without CuraEngine.
#
# The output deliberately mimics what CuraEngine emits for this machine so the
# Printess post-processing scripts (PrintessLayerByLayer / PrintessOneAtATime)
# can run on it unchanged:
#   - relative E deltas (relative_extrusion = True on this machine; the script
#     converts the renamed B/C axes to absolute itself),
#   - plain X/Y/Z/E axes (the script renames E->B for T0, Z->A and E->C for T1),
#   - ;LAYER:/;MESH: markers and T0/T1 tool changes (the script inserts homing,
#     the G92 datum, parking, retraction and feedrate overrides around them),
#   - coordinates in the printer frame (corner origin) with the per-extruder
#     nozzle offset subtracted, exactly like CuraEngine's getGcodePos().

import math
from typing import Dict, List

from . import PathShapes

# Kept in step with PrintessPathDesigner; imported there rather than duplicated
# would be circular, so the names live here and the tool asserts they match.
DRAWING_TAG = "PrintessDrawing"
DRAWING_KIND_PATH = "path"


def generate(paths: List[dict], settings: dict) -> List[str]:
    """Build the g-code chunk list for the drawn paths.

    :param paths: list of path dicts with keys: points (scene (x, z) tuples,
                  closed polygons do not repeat the first point), closed,
                  fill_segments, extruder, layers (how many passes to stack),
                  line_width, speed (mm/s, 0 = profile). path["flow"] is
                  present in the dict and stored in projects, but is NOT read;
                  see e_per_mm.
    :param settings: dict with machine_width, machine_depth, layer_height,
                     layer_height_0 and per-extruder dicts under "extruders":
                     {index: {print_speed, speed_travel, material_flow,
                              initial_flow, initial_line_width_factor,
                              initial_speed, slowdown_layers, material_diameter,
                              nozzle_offset_x, nozzle_offset_y}}.
                     initial_flow and initial_line_width_factor are percentages
                     that apply to LAYER 0 ONLY, matching CuraEngine.
                     initial_speed (speed_print_layer_0, mm/s) and
                     slowdown_layers (speed_slowdown_layers) drive the ramp back
                     up to full speed over the first layers; see
                     print_speed_for.
                     print_speed and material_flow are both read off the GENERAL
                     settings (speed_print, material_flow), and deliberately as a
                     PAIR: reading one from the outer wall and the other from the
                     general level would describe the same line as two different
                     features, which is the mistake this pairing exists to
                     prevent whichever level it is anchored at.
                     They were on the OUTER WALL (speed_wall_0,
                     wall_0_material_flow) until 2026-08-17, on the reasoning
                     that a drawn line is the equivalent of an outer wall. Moved
                     at the user's request to match the Flow Rate Tester: an
                     unfilled drawn path never reaches CuraEngine, so "it is a
                     wall" was a convention rather than a fact, and Flow is the
                     knob a user actually tunes. Behavior-neutral on every
                     current profile, since none sets a wall-specific value.
                     Note that a FILLED drawn shape is unaffected - it is a mesh,
                     CuraEngine slices it, and its perimeter genuinely is an
                     outer wall printed with the wall settings.
                     Read fresh at slice time so changing a setting and
                     re-slicing is enough.
    :return: list of g-code chunks (each ends with a newline), in the same
             shape Cura hands to post-processing scripts.
    """
    half_w = settings["machine_width"] / 2.0
    half_d = settings["machine_depth"] / 2.0
    lh = max(settings["layer_height"], 0.01)
    lh0 = max(settings["layer_height_0"], 0.01)
    extruders: Dict[int, dict] = settings["extruders"]

    def to_printer(point, extruder):
        # Scene (center origin, +z toward the front) -> printer (corner origin),
        # then subtract the nozzle offset like CuraEngine's getGcodePos().
        ex = extruders[extruder]
        gx = (point[0] + half_w) - ex["nozzle_offset_x"]
        gy = (half_d - point[1]) - ex["nozzle_offset_y"]
        return gx, gy

    def passes_for(path):
        # The tool counts layers directly; it used to carry a height in mm and
        # divide it out here, which no longer matches what a path holds.
        return max(1, int(path.get("layers", 1)))

    def filament_area(extruder):
        d = extruders[extruder]["material_diameter"]
        return math.pi * (d / 2.0) ** 2

    def e_per_mm(path, layer, layer_thickness):
        ex = extruders[path["extruder"]]
        # The profile's outer-wall flow, and nothing else.
        #
        # This used to be `wall_flow * path["flow"]`, a per-path MULTIPLIER.
        # Nothing has ever set path["flow"] to anything but 100 (FlowPercent is
        # not in setExposedProperties, so QML cannot reach the setter and the
        # panel offers no field), so the product has always equalled wall_flow
        # and no print is affected by dropping it. It is dropped because the
        # multiplier convention is a trap:
        #
        #   - Cura's own per-object settings REPLACE, they do not scale. A mesh
        #     carrying wall_0_material_flow = 110 prints at 110, not at 110% of
        #     the global.
        #   - `speed` in this very dict already replaces (0 means "use the
        #     profile"), so the two overrides read the same and behaved
        #     differently.
        #   - The Flow Rate Tester shipped with exactly this multiply and it was
        #     wrong there for a concrete reason: a user on Flow 90 who picks the
        #     line labeled 110 has actually printed 99, and typing 110 back
        #     into Flow gives them something they never saw.
        #
        # IF A PER-PATH FLOW FIELD IS EVER ADDED, IT MUST REPLACE, NOT MULTIPLY:
        # `flow = path["flow"] if path["flow"] > 0 else ex["material_flow"]`,
        # with 0 as the "use the profile" sentinel, mirroring speed exactly.
        #
        # Note for whoever does that: "flow" is in _SNAPSHOT_KEYS, so projects
        # already on disk carry "flow": 100.0. Under replace semantics that
        # stored 100 would read as a deliberate absolute 100% and would override
        # a profile set to anything else. Those records mean "unset" and have to
        # be migrated to the sentinel on restore, not taken at face value.
        flow = ex["material_flow"] / 100.0
        line_width = path["line_width"]
        if layer == 0:
            # Initial Layer Flow and Initial Layer Line Width, both of which
            # CuraEngine applies to the first layer and nothing else. A drawn
            # line has to pick up bed-adhesion tuning the same way a sliced wall
            # does, or the first layer is the one layer where the two disagree —
            # and the first layer is the one that has to stick.
            #
            # The line width is scaled BEFORE the extrusion is computed from it,
            # as CuraEngine does it, so the two multipliers compound rather than
            # either one winning. Only the extrusion changes: the trajectory is
            # what was drawn, and a wider bead is laid along the same line.
            flow *= ex["initial_flow"] / 100.0
            line_width *= ex["initial_line_width_factor"] / 100.0
        return line_width * layer_thickness * flow / filament_area(path["extruder"])

    def print_speed_for(path, layer, ex):
        """The path's speed on this layer, including the initial-layer ramp.

        CuraEngine prints the first layers slower for adhesion and interpolates
        linearly back up to full speed over speed_slowdown_layers, which is its
        smoothSpeed(): layer 0 runs at speed_print_layer_0, and each layer after
        it moves one step toward the normal speed. speed_slowdown_layers = 0
        turns the ramp off entirely, for a drawn line exactly as for a sliced
        wall, which is how the Nordson profiles have it.

        The ramp applies to a per-path speed override as well, because in
        CuraEngine it applies to whatever a feature's own speed is: it is about
        sticking to the plate, not about this path. A path told to print at
        1 mm/s therefore still has its first layers pulled toward the initial
        layer speed, and the way to opt out is to set speed_slowdown_layers to 0.
        """
        speed = path["speed"] if path["speed"] > 0 else ex["print_speed"]
        slowdown = int(ex["slowdown_layers"])
        if layer < slowdown:
            speed = (speed * layer + ex["initial_speed"] * (slowdown - layer)) / slowdown
        return speed

    total_layers = max(passes_for(p) for p in paths)
    used_extruders = sorted({p["extruder"] for p in paths})
    first_extruder = used_extruders[0]

    # Bounding box over all printed coordinates (header info only).
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    for p in paths:
        for pt in p["points"]:
            gx, gy = to_printer(pt, p["extruder"])
            min_x, max_x = min(min_x, gx), max(max_x, gx)
            min_y, max_y = min(min_y, gy), max(max_y, gy)

    chunks: List[str] = []

    header = [
        ";FLAVOR:Marlin",
        ";TIME:0",
        ";Filament used: 0m",
        ";Layer height: {0:.2f}".format(lh),
        ";MINX:{0:.3f}".format(min_x),
        ";MINY:{0:.3f}".format(min_y),
        ";MINZ:{0:.3f}".format(lh0),
        ";MAXX:{0:.3f}".format(max_x),
        ";MAXY:{0:.3f}".format(max_y),
        ";MAXZ:{0:.3f}".format(lh0 + (total_layers - 1) * lh),
    ]
    chunks.append("\n".join(header) + "\n")

    startup = [
        ";Generated with PrintessFlow Path Designer",
        "T{0}".format(first_extruder),
        ";LAYER_COUNT:{0}".format(total_layers),
    ]
    chunks.append("\n".join(startup) + "\n")

    for layer in range(total_layers):
        z = lh0 + layer * lh
        layer_thickness = lh0 if layer == 0 else lh
        lines = [";LAYER:{0}".format(layer), ";Z:{0:.3f}".format(z)]

        for extruder in used_extruders:
            layer_paths = [(k, p) for k, p in enumerate(paths)
                           if p["extruder"] == extruder and passes_for(p) > layer]
            if not layer_paths:
                continue
            # Stated for every group in every layer, not only where this loop
            # believes it changed. A layer body is spliced into sliced g-code on
            # its own, after whatever mesh the slicer printed last, so a body
            # that says nothing about its tool leaves the choice to the stream
            # around it — and the two post-processing scripts then answer
            # differently. PrintessLayerByLayer follows the tool that happens to
            # be selected, which is the slicer's business and changes with the
            # mesh order; PrintessOneAtATime follows the scene node. A drawn path
            # printed on B and Z through the first layers and on C and A from the
            # layer a second extruder happened to run last. GcodeMerge drops the
            # ones that are redundant where the body actually lands, so the extra
            # T costs nothing.
            lines.append("T{0}".format(extruder))

            ex = extruders[extruder]
            # Travel is deliberately NOT ramped with speed_travel_layer_0. Every
            # travel feedrate emitted here is replaced by the post-processing
            # script, which sets pure XY moves to the profile's travel speed, so
            # a ramp applied to this number would be discarded before it printed.
            # The print feedrate is the one the script leaves alone.
            travel_f = int(ex["speed_travel"] * 60)
            for k, path in layer_paths:
                print_f = int(print_speed_for(path, layer, ex) * 60)
                epmm = e_per_mm(path, layer, layer_thickness)

                # The same mark the meshed shapes carry, so a drawn path and a
                # sliced one are named by one convention and the post-processing
                # script's part handling cannot tell them apart.
                lines.append(";MESH:" + (path.get("name") or
                             "{0}-{1}-{2} (Extruder {3})".format(
                                 DRAWING_TAG, DRAWING_KIND_PATH, k + 1, extruder + 1)))

                points = list(path["points"])
                if path["closed"]:
                    points = points + [points[0]]
                elif layer % 2 == 1:
                    # Alternate direction on open paths so stacked passes do
                    # not need a travel back to the start every layer.
                    points = list(reversed(points))

                gx, gy = to_printer(points[0], extruder)
                lines.append("G0 F{0} X{1:.3f} Y{2:.3f} Z{3:.3f}".format(travel_f, gx, gy, z))

                first_move = True
                for i in range(1, len(points)):
                    seg_len = PathShapes.dist(points[i - 1], points[i])
                    if seg_len < 1e-6:
                        continue
                    gx, gy = to_printer(points[i], extruder)
                    de = seg_len * epmm
                    if first_move:
                        lines.append("G1 F{0} X{1:.3f} Y{2:.3f} E{3:.5f}".format(print_f, gx, gy, de))
                        first_move = False
                    else:
                        lines.append("G1 X{0:.3f} Y{1:.3f} E{2:.5f}".format(gx, gy, de))

                for seg in path["fill_segments"]:
                    (a, b) = seg
                    seg_len = PathShapes.dist(a, b)
                    if seg_len < 1e-6:
                        continue
                    gax, gay = to_printer(a, extruder)
                    gbx, gby = to_printer(b, extruder)
                    lines.append("G0 F{0} X{1:.3f} Y{2:.3f}".format(travel_f, gax, gay))
                    lines.append("G1 F{0} X{1:.3f} Y{2:.3f} E{3:.5f}".format(
                        print_f, gbx, gby, seg_len * epmm))

        # Close the mesh context, exactly as CuraEngine does before traveling
        # away from a mesh. Without it the NEXT layer's leading comments, which
        # come before its own ;MESH: marker, are still attributed to this part:
        # a one-layer drawing picked up a ;TYPE:FILL from the layer above it and
        # the post-processing script gave the drawing a phantom empty layer,
        # complete with a pointless descent to that layer's height.
        if len(lines) > 2:
            lines.append(";MESH:NONMESH")
        chunks.append("\n".join(lines) + "\n")

    chunks.append(";TIME_ELAPSED:0\n;End of Gcode\n")
    return chunks
