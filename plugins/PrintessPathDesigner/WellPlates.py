# Copyright (c) 2026 Printess Technologies
# Released under the terms of the LGPLv3 or higher.
#
# Well-plate presets and layout math for the Path Designer.
#
# rows/cols/spacing/origin are the SAME calibrated values used by the
# WellPlateArrangeTool (keep the two in sync): origin_x/origin_y are the
# measured centre of the BOTTOM-LEFT well in PRINTER (build-plate corner)
# coordinates referenced to extruder 0, and the plate sits half the nozzle
# X separation toward the midpoint between the two nozzles (extruder_shift).
# well_d is the standard nominal well diameter for each plate format.

from typing import List, Tuple

Point = Tuple[float, float]

PRESETS = {
    "6-Well":  {"rows": 2, "cols": 3, "spacing_x": 39.12, "spacing_y": 39.12,
                "origin_x": 40.0, "origin_y": 23.0, "well_d": 34.8},
    "12-Well": {"rows": 3, "cols": 4, "spacing_x": 26.01, "spacing_y": 26.01,
                "origin_x": 40.0, "origin_y": 16.0, "well_d": 22.1},
    "24-Well": {"rows": 4, "cols": 6, "spacing_x": 19.30, "spacing_y": 19.30,
                "origin_x": 33.0, "origin_y": 14.0, "well_d": 15.6},
    "48-Well": {"rows": 6, "cols": 8, "spacing_x": 13.08, "spacing_y": 13.08,
                "origin_x": 34.0, "origin_y": 10.0, "well_d": 11.1},
}

PRESET_ORDER = ["6-Well", "12-Well", "24-Well", "48-Well"]


def well_centers(preset_name: str, half_w: float, half_d: float,
                 extruder_shift: float) -> List[Point]:
    """Scene-coordinate centres of all wells, indexed by row * cols + col.

    Row 0 is the front row (small printer y). Scene coords are centre-origin
    with +z toward the front of the plate: scene_x = x_printer - half_w,
    scene_z = half_d - y_printer.
    """
    preset = PRESETS.get(preset_name)
    if preset is None:
        return []
    centers = []
    for row in range(preset["rows"]):
        for col in range(preset["cols"]):
            x_printer = preset["origin_x"] + extruder_shift + col * preset["spacing_x"]
            y_printer = preset["origin_y"] + row * preset["spacing_y"]
            centers.append((x_printer - half_w, half_d - y_printer))
    return centers


def nearest_well(point: Point, centers: List[Point]) -> int:
    """Index of the well centre closest to a point, or -1 when there are none."""
    best = -1
    best_dist = float("inf")
    for i, (cx, cz) in enumerate(centers):
        d = (point[0] - cx) ** 2 + (point[1] - cz) ** 2
        if d < best_dist:
            best_dist = d
            best = i
    return best
