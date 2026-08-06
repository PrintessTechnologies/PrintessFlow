# Copyright (c) 2026 Printess Technologies
# Released under the terms of the LGPLv3 or higher.
#
# Pure-geometry helpers for the Path Designer tool. All points are 2D tuples
# (x, z) in Cura scene coordinates (millimetres, plate centre at origin,
# +x right, +z toward the front). The vertical scene axis is y.

import math
from typing import List, Optional, Tuple

Point = Tuple[float, float]
Segment = Tuple[Point, Point]


def dist(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def polyline_length(points: List[Point]) -> float:
    return sum(dist(points[i], points[i + 1]) for i in range(len(points) - 1))


def circle_from_3_points(p0: Point, p1: Point, p2: Point) -> Optional[Tuple[Point, float]]:
    """Circumcircle of three points, or None when they are (nearly) collinear."""
    ax, ay = p0
    bx, by = p1
    cx, cy = p2
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    center = (ux, uy)
    return center, dist(center, p0)


def tessellate_arc(start: Point, bulge: Point, end: Point, segment_length: float) -> List[Point]:
    """Arc from start to end passing through bulge, as a polyline.

    Falls back to a straight line when the three points are collinear.
    """
    result = circle_from_3_points(start, bulge, end)
    if result is None:
        return [start, end]
    center, radius = result

    a_start = math.atan2(start[1] - center[1], start[0] - center[0])
    a_bulge = math.atan2(bulge[1] - center[1], bulge[0] - center[0])
    a_end = math.atan2(end[1] - center[1], end[0] - center[0])

    # Choose the sweep direction that passes through the bulge point.
    def sweep_ccw(a_from, a_to):
        s = a_to - a_from
        while s < 0:
            s += 2.0 * math.pi
        return s

    ccw_total = sweep_ccw(a_start, a_end)
    ccw_to_bulge = sweep_ccw(a_start, a_bulge)
    if ccw_to_bulge <= ccw_total:
        sweep = ccw_total  # counter-clockwise
    else:
        sweep = ccw_total - 2.0 * math.pi  # clockwise (negative sweep)

    arc_len = abs(sweep) * radius
    steps = max(4, int(math.ceil(arc_len / max(segment_length, 0.05))))
    points = []
    for i in range(steps + 1):
        a = a_start + sweep * (i / steps)
        points.append((center[0] + radius * math.cos(a), center[1] + radius * math.sin(a)))
    return points


def arc_tangent_and_sweep(start: Point, bulge: Point, end: Point):
    """Travel directions and swept angle of the arc through three points.

    Returns (tangent at start, tangent at end, sweep in degrees), each tangent a
    unit vector pointing the way the arc travels, or None when the three points
    are collinear. The sweep direction is chosen exactly as tessellate_arc
    chooses it, so the tangents match the arc that actually gets drawn.
    """
    result = circle_from_3_points(start, bulge, end)
    if result is None:
        return None
    center, radius = result
    if radius < 1e-9:
        return None

    a_start = math.atan2(start[1] - center[1], start[0] - center[0])
    a_bulge = math.atan2(bulge[1] - center[1], bulge[0] - center[0])
    a_end = math.atan2(end[1] - center[1], end[0] - center[0])

    def sweep_ccw(a_from, a_to):
        s = a_to - a_from
        while s < 0:
            s += 2.0 * math.pi
        return s

    ccw_total = sweep_ccw(a_start, a_end)
    sweep = ccw_total if sweep_ccw(a_start, a_bulge) <= ccw_total else ccw_total - 2.0 * math.pi
    # Travelling counter-clockwise, the direction is the radius turned +90°.
    turn = 1.0 if sweep > 0 else -1.0

    def tangent(angle):
        return (-math.sin(angle) * turn, math.cos(angle) * turn)

    return tangent(a_start), tangent(a_end), math.degrees(abs(sweep))


def turn_angle(a: Point, b: Point, c: Point) -> float:
    """How sharply a polyline turns at b, in degrees. 0 is dead straight."""
    first = (b[0] - a[0], b[1] - a[1])
    second = (c[0] - b[0], c[1] - b[1])
    len_first = math.hypot(first[0], first[1])
    len_second = math.hypot(second[0], second[1])
    if len_first < 1e-9 or len_second < 1e-9:
        return 0.0
    cosine = (first[0] * second[0] + first[1] * second[1]) / (len_first * len_second)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def angle_between_lines(a: Point, b: Point) -> float:
    """Smallest angle in degrees between two directions, ignoring their sign."""
    dot = min(1.0, abs(a[0] * b[0] + a[1] * b[1]))
    return math.degrees(math.acos(dot))


def tessellate_circle(center: Point, radius: float, segment_length: float) -> List[Point]:
    """Full circle as a closed polyline (first point NOT repeated at the end)."""
    circumference = 2.0 * math.pi * radius
    steps = max(12, int(math.ceil(circumference / max(segment_length, 0.05))))
    points = []
    for i in range(steps):
        a = 2.0 * math.pi * i / steps
        points.append((center[0] + radius * math.cos(a), center[1] + radius * math.sin(a)))
    return points


def tessellate_catmull_rom(control_points: List[Point], segment_length: float, closed: bool) -> List[Point]:
    """Catmull-Rom spline through the control points.

    Open splines duplicate the end points as phantom controls; closed splines
    wrap around. Closed result does NOT repeat the first point.
    """
    n = len(control_points)
    if n < 2:
        return list(control_points)
    if n == 2 and not closed:
        return list(control_points)

    pts = list(control_points)
    if closed:
        spans = n
        def cp(i):
            return pts[i % n]
    else:
        spans = n - 1
        def cp(i):
            return pts[max(0, min(n - 1, i))]

    result: List[Point] = []
    for span in range(spans):
        p0 = cp(span - 1)
        p1 = cp(span)
        p2 = cp(span + 1)
        p3 = cp(span + 2)
        chord = dist(p1, p2)
        steps = max(2, int(math.ceil(chord / max(segment_length, 0.05))))
        for i in range(steps):
            t = i / steps
            t2 = t * t
            t3 = t2 * t
            x = 0.5 * ((2.0 * p1[0]) + (-p0[0] + p2[0]) * t
                       + (2.0 * p0[0] - 5.0 * p1[0] + 4.0 * p2[0] - p3[0]) * t2
                       + (-p0[0] + 3.0 * p1[0] - 3.0 * p2[0] + p3[0]) * t3)
            y = 0.5 * ((2.0 * p1[1]) + (-p0[1] + p2[1]) * t
                       + (2.0 * p0[1] - 5.0 * p1[1] + 4.0 * p2[1] - p3[1]) * t2
                       + (-p0[1] + 3.0 * p1[1] - 3.0 * p2[1] + p3[1]) * t3)
            result.append((x, y))
    if not closed:
        result.append(pts[-1])
    return result


def segment_intersection(a1: Point, a2: Point, b1: Point, b2: Point) -> Optional[Point]:
    """Intersection point of two segments, or None when they do not cross."""
    d1x, d1y = a2[0] - a1[0], a2[1] - a1[1]
    d2x, d2y = b2[0] - b1[0], b2[1] - b1[1]
    denom = d1x * d2y - d1y * d2x
    if abs(denom) < 1e-12:
        return None
    t = ((b1[0] - a1[0]) * d2y - (b1[1] - a1[1]) * d2x) / denom
    u = ((b1[0] - a1[0]) * d1y - (b1[1] - a1[1]) * d1x) / denom
    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return (a1[0] + t * d1x, a1[1] + t * d1y)
    return None


def _segments_of(points: List[Point], closed: bool) -> List[Segment]:
    segs = [(points[i], points[i + 1]) for i in range(len(points) - 1)]
    if closed and len(points) > 2:
        segs.append((points[-1], points[0]))
    return segs


def polyline_intersections(points_a: List[Point], closed_a: bool,
                           points_b: List[Point], closed_b: bool) -> List[Point]:
    """All crossing points between two polylines (with coarse bbox rejection)."""
    result: List[Point] = []
    segs_b = _segments_of(points_b, closed_b)
    for a1, a2 in _segments_of(points_a, closed_a):
        a_min_x, a_max_x = min(a1[0], a2[0]), max(a1[0], a2[0])
        a_min_y, a_max_y = min(a1[1], a2[1]), max(a1[1], a2[1])
        for b1, b2 in segs_b:
            if (max(b1[0], b2[0]) < a_min_x or min(b1[0], b2[0]) > a_max_x
                    or max(b1[1], b2[1]) < a_min_y or min(b1[1], b2[1]) > a_max_y):
                continue
            hit = segment_intersection(a1, a2, b1, b2)
            if hit is not None:
                result.append(hit)
    return result


def point_segment_distance(point: Point, a: Point, b: Point) -> float:
    """Shortest distance from a point to a line segment."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-12:
        return dist(point, a)
    t = ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    return dist(point, (a[0] + t * dx, a[1] + t * dy))


def polyline_distance(point: Point, points: List[Point], closed: bool) -> float:
    """Shortest distance from a point to a polyline (or closed polygon outline)."""
    if len(points) == 1:
        return dist(point, points[0])
    best = float("inf")
    loop = points + [points[0]] if closed and len(points) > 2 else points
    for i in range(len(loop) - 1):
        best = min(best, point_segment_distance(point, loop[i], loop[i + 1]))
    return best


def dashed_segments(a: Point, b: Point, dash: float = 1.4, gap: float = 1.0) -> List[List[Point]]:
    """Split segment a-b into short dashes (each a 2-point polyline)."""
    length = dist(a, b)
    if length < 1e-9:
        return []
    ux = (b[0] - a[0]) / length
    uy = (b[1] - a[1]) / length
    result = []
    pos = 0.0
    while pos < length:
        end = min(pos + dash, length)
        result.append([(a[0] + ux * pos, a[1] + uy * pos),
                       (a[0] + ux * end, a[1] + uy * end)])
        pos = end + gap
    return result


def point_in_polygon(point: Point, polygon: List[Point]) -> bool:
    """Ray-casting containment test for a closed polygon."""
    x, y = point
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            x_cross = x1 + (y - y1) / (y2 - y1) * (x2 - x1)
            if x < x_cross:
                inside = not inside
    return inside


def triangulate_polygon(polygon: List[Point]) -> List[Tuple[Point, Point, Point]]:
    """Triangulate a simple polygon by ear clipping (no holes).

    Falls back to a centroid fan if clipping stalls (e.g. self-intersecting
    input), which is fine for a translucent shading overlay.
    """
    n = len(polygon)
    if n < 3:
        return []

    def signed_area(pts):
        return sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                   for i in range(len(pts))) / 2.0

    pts = list(polygon)
    if signed_area(pts) < 0:
        pts.reverse()  # ensure counter-clockwise

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def in_triangle(p, a, b, c):
        d1 = cross(a, b, p)
        d2 = cross(b, c, p)
        d3 = cross(c, a, p)
        return d1 >= -1e-12 and d2 >= -1e-12 and d3 >= -1e-12

    triangles = []
    indices = list(range(len(pts)))
    guard = 0
    while len(indices) > 3 and guard < 10000:
        guard += 1
        ear_found = False
        for k in range(len(indices)):
            i_prev = indices[k - 1]
            i_cur = indices[k]
            i_next = indices[(k + 1) % len(indices)]
            a, b, c = pts[i_prev], pts[i_cur], pts[i_next]
            if cross(a, b, c) <= 1e-12:
                continue  # reflex or degenerate corner
            if any(in_triangle(pts[j], a, b, c)
                   for j in indices if j not in (i_prev, i_cur, i_next)):
                continue
            triangles.append((a, b, c))
            indices.pop(k)
            ear_found = True
            break
        if not ear_found:
            break

    if len(indices) == 3:
        triangles.append((pts[indices[0]], pts[indices[1]], pts[indices[2]]))
    elif len(indices) > 3:
        # Fallback: centroid fan over the remaining vertices.
        cx = sum(pts[i][0] for i in indices) / len(indices)
        cy = sum(pts[i][1] for i in indices) / len(indices)
        for k in range(len(indices)):
            triangles.append(((cx, cy), pts[indices[k]], pts[indices[(k + 1) % len(indices)]]))
    return triangles


def dominant_angle(points: List[Point], closed: bool) -> float:
    """Direction of the longest straight run, in PRINTER degrees, 0 to 180.

    On a serpentine the longest runs are the legs, so this recovers the
    direction the pattern was drawn in. Scene (x, z) maps to printer (x, y) with
    y running the other way, so the sign of the z component flips.
    """
    best = None
    best_length = 0.0
    for a, b in _segments_of(points, closed):
        length = dist(a, b)
        if length > best_length:
            best_length = length
            best = (b[0] - a[0], b[1] - a[1])
    if best is None or best_length < 1e-9:
        return 0.0
    angle = math.degrees(math.atan2(-best[1], best[0]))
    return angle % 180.0


def segment_distance(a1: Point, a2: Point, b1: Point, b2: Point) -> float:
    """Shortest distance between two line segments."""
    if segment_intersection(a1, a2, b1, b2) is not None:
        return 0.0
    return min(point_segment_distance(a1, b1, b2),
               point_segment_distance(a2, b1, b2),
               point_segment_distance(b1, a1, a2),
               point_segment_distance(b2, a1, a2))


def min_self_distance(points: List[Point], closed: bool, limit: float) -> float:
    """Closest approach between two parts of the path that are far apart along it.

    This is the spacing between neighbouring passes of a serpentine. Returns
    `limit` when nothing comes closer, so the caller can treat that as "the
    stroke never runs into itself". See self_overlaps for why the separation is
    measured along the path and not just in space.
    """
    segments = _segments_of(points, closed)
    count = len(segments)
    if count < 3:
        return limit

    starts = []
    running = 0.0
    for a, b in segments:
        starts.append(running)
        running += dist(a, b)
    total = running
    apart = limit * 2.0
    best = limit

    for i in range(count):
        end_i = starts[i] + dist(*segments[i])
        for j in range(i + 1, count):
            along = starts[j] - end_i
            if closed:
                along = min(along, total - (starts[j] + dist(*segments[j])) + starts[i])
            if along <= apart:
                continue
            gap = segment_distance(segments[i][0], segments[i][1],
                                   segments[j][0], segments[j][1])
            if gap < best:
                best = gap
    return best


def self_overlaps(points: List[Point], closed: bool, width: float) -> bool:
    """Whether the stroke of this polyline runs into itself.

    True when two parts of the path that are far apart ALONG the path come
    within a line width of each other in space, which is exactly when their
    beads merge into one solid area instead of staying separate lines.

    Measuring along the path is the whole point. Nearby stretches of any curve
    are close together in space by definition, so a finely tessellated arc
    would look self-overlapping under a plain distance test: on a 0.5 mm
    tessellation, segments two apart are only a millimetre from each other,
    inside a 1.54 mm line width. Only stretches separated by more than a couple
    of line widths of travel can actually be two different passes of the nozzle.
    """
    segments = _segments_of(points, closed)
    count = len(segments)
    if count < 3:
        return False

    starts = []
    running = 0.0
    for a, b in segments:
        starts.append(running)
        running += dist(a, b)
    total = running
    apart = width * 2.0

    for i in range(count):
        end_i = starts[i] + dist(*segments[i])
        for j in range(i + 1, count):
            along = starts[j] - end_i
            if closed:
                along = min(along, total - (starts[j] + dist(*segments[j])) + starts[i])
            if along <= apart:
                continue  # neighbouring stretch of the same line, not a second pass
            a1, a2 = segments[i]
            b1, b2 = segments[j]
            # Touching counts: passes exactly one line width apart have beads
            # that meet, which is already enough to fuse them into one area.
            if segment_distance(a1, a2, b1, b2) <= width:
                return True
    return False


def fillet_polyline(points: List[Point], closed: bool, radius: float,
                    segment_length: float) -> List[Point]:
    """Round off the corners of a polyline with arcs of the given radius.

    A stroke of width w around a SHARP corner is unavoidably thicker across the
    corner than it is wide: (w/2)(1 + sqrt 2) = 1.207 w along the diagonal of a
    right angle. That surplus is real area, so no slicer setting can make it go
    away, and the slicer covers it with an extra little contour beside the main
    bead. Rounding the centreline to a radius of at least w/2 makes the stroke
    exactly w wide the whole way round, and one bead covers it.

    Gentle bends are left alone: the tangent length falls to nothing as the turn
    straightens, so a tessellated arc passes through unchanged.
    """
    count = len(points)
    if count < 3 or radius <= 0:
        return list(points)

    corners = range(count) if closed else range(1, count - 1)
    corner_set = set(corners)
    result: List[Point] = []

    for i in range(count):
        vertex = points[i]
        if i not in corner_set:
            result.append(vertex)
            continue

        previous = points[(i - 1) % count]
        following = points[(i + 1) % count]
        in_len = dist(previous, vertex)
        out_len = dist(vertex, following)
        if in_len < 1e-9 or out_len < 1e-9:
            result.append(vertex)
            continue

        u_in = ((vertex[0] - previous[0]) / in_len, (vertex[1] - previous[1]) / in_len)
        u_out = ((following[0] - vertex[0]) / out_len, (following[1] - vertex[1]) / out_len)
        deviation = math.radians(angle_between_directions(u_in, u_out))
        if deviation > math.radians(179.0):
            result.append(vertex)  # doubled back on itself
            continue

        # Tangent length for this radius, never eating more than a share of
        # either neighbouring segment, so short segments cannot be swallowed.
        tangent = radius * math.tan(deviation / 2.0)
        tangent = min(tangent, in_len * 0.45, out_len * 0.45)
        effective = tangent / math.tan(deviation / 2.0) if deviation > 1e-12 else radius

        # How far the rounding actually pulls the path off the corner. On a
        # tessellated curve each step turns a degree or two and this is a
        # fraction of a micron, so the vertex is left exactly as drawn rather
        # than replaced by an arc that would multiply the point count for
        # nothing.
        offset = effective * (1.0 / math.cos(deviation / 2.0) - 1.0)
        if offset < 0.01:
            result.append(vertex)
            continue

        start = (vertex[0] - u_in[0] * tangent, vertex[1] - u_in[1] * tangent)
        end = (vertex[0] + u_out[0] * tangent, vertex[1] + u_out[1] * tangent)

        # Centre lies along the inward bisector; the arc's near point is the
        # bulge that tessellate_arc wants.
        bisector = (u_out[0] - u_in[0], u_out[1] - u_in[1])
        bis_len = math.hypot(bisector[0], bisector[1])
        if bis_len < 1e-9:
            result.append(vertex)
            continue
        bisector = (bisector[0] / bis_len, bisector[1] / bis_len)
        # The centre sits perpendicular-distance `effective` from BOTH segments,
        # and the bisector meets each at 90 - deviation/2, so the vertex-to-
        # centre distance is effective / cos(deviation / 2). Using sin here
        # instead sends the centre off to infinity as the joint straightens.
        centre_distance = effective / math.cos(deviation / 2.0)
        bulge = (vertex[0] + bisector[0] * (centre_distance - effective),
                 vertex[1] + bisector[1] * (centre_distance - effective))

        arc = tessellate_arc(start, bulge, end, segment_length)
        result.extend(arc)

    # Drop any duplicate points the arcs may have left back to back.
    cleaned: List[Point] = []
    for point in result:
        if not cleaned or dist(cleaned[-1], point) > 1e-9:
            cleaned.append(point)
    if closed and len(cleaned) > 1 and dist(cleaned[0], cleaned[-1]) <= 1e-9:
        cleaned.pop()
    return cleaned


def angle_between_directions(a: Point, b: Point) -> float:
    """Angle in degrees between two unit directions, 0 when they agree."""
    dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1]))
    return math.degrees(math.acos(dot))


def prism_faces(polygon: List[Point], y0: float, y1: float):
    """One watertight solid from a simple polygon: capped top and bottom, with
    a wall around the boundary. Returns 3D triangles as ((x,y,z), ...).

    Every triangle faces OUTWARD, which is what Cura's model check is looking
    for. Winding in this coordinate system is easy to get backwards, so the
    rule is worth stating: for a triangle wound counter-clockwise in (x, z),
    the right-hand normal points DOWN (-y), because y is up and (x, z) is
    left-handed when read as a plane. Hence the bottom cap takes
    triangulate_polygon's output as it comes, and the top cap is reversed.

    The walls are wound to match, which is NOT what
    MeshBuilder.addConvexPolygonExtrusion does with the same counter-clockwise
    input: its side quads come out facing inward. Mixing cap and wall
    directions in one mesh is exactly what shows up as "missing or extraneous
    surfaces", so this builds the walls itself.
    """
    triangles = triangulate_polygon(polygon)
    if not triangles:
        return []

    faces = []
    for a, b, c in triangles:
        # Bottom, as triangulated: counter-clockwise in (x, z) faces down.
        faces.append(((a[0], y0, a[1]), (b[0], y0, b[1]), (c[0], y0, c[1])))
        # Top, reversed, so it faces up.
        faces.append(((a[0], y1, a[1]), (c[0], y1, c[1]), (b[0], y1, b[1])))

    # The wall follows the polygon as given. triangulate_polygon reverses a
    # clockwise polygon before it works, so take the winding from there rather
    # than from the caller.
    outline = list(polygon)
    if signed_area(outline) < 0:
        outline.reverse()
    count = len(outline)
    for i in range(count):
        p0 = outline[i]
        p1 = outline[(i + 1) % count]
        bottom0 = (p0[0], y0, p0[1])
        bottom1 = (p1[0], y0, p1[1])
        top0 = (p0[0], y1, p0[1])
        top1 = (p1[0], y1, p1[1])
        faces.append((bottom0, top0, top1))
        faces.append((bottom0, top1, bottom1))
    return faces


def signed_area(polygon: List[Point]) -> float:
    """Shoelace area of a polygon in (x, z). Positive is counter-clockwise."""
    total = 0.0
    count = len(polygon)
    for i in range(count):
        x0, z0 = polygon[i]
        x1, z1 = polygon[(i + 1) % count]
        total += x0 * z1 - x1 * z0
    return total / 2.0


def mesh_volume(faces) -> float:
    """Signed volume of a closed triangle soup, by the divergence theorem.

    A watertight mesh whose triangles all face outward encloses a positive
    volume, so this is the cheap way to prove a built solid is both closed and
    wound the right way round.
    """
    total = 0.0
    for v0, v1, v2 in faces:
        cross = (v1[1] * v2[2] - v1[2] * v2[1],
                 v1[2] * v2[0] - v1[0] * v2[2],
                 v1[0] * v2[1] - v1[1] * v2[0])
        total += (v0[0] * cross[0] + v0[1] * cross[1] + v0[2] * cross[2])
    return total / 6.0


def zigzag_fill(polygon: List[Point], spacing: float, inset: float) -> List[Segment]:
    """Back-and-forth fill segments for a closed polygon.

    Scanlines run along x at constant z, spaced `spacing` apart. Each segment is
    shortened by `inset` on both ends to stay clear of the outline. Segments are
    returned in boustrophedon (serpentine) order.
    """
    if len(polygon) < 3 or spacing <= 0:
        return []

    zs = [p[1] for p in polygon]
    z_min, z_max = min(zs), max(zs)
    height = z_max - z_min
    if height <= spacing * 0.5:
        return []

    n_lines = int(height / spacing)
    # Centre the scanline pattern vertically inside the polygon.
    z_start = z_min + (height - (n_lines - 1) * spacing) / 2.0 if n_lines > 1 else (z_min + z_max) / 2.0

    edges = []
    n = len(polygon)
    for i in range(n):
        a = polygon[i]
        b = polygon[(i + 1) % n]
        if abs(a[1] - b[1]) > 1e-9:
            edges.append((a, b))

    segments: List[Segment] = []
    left_to_right = True
    for li in range(max(1, n_lines)):
        z = z_start + li * spacing
        # Nudge scanlines that pass exactly through a vertex.
        for p in polygon:
            if abs(p[1] - z) < 1e-7:
                z += 1e-5
                break

        xs = []
        for a, b in edges:
            z0, z1 = a[1], b[1]
            if (z0 < z <= z1) or (z1 < z <= z0):
                t = (z - z0) / (z1 - z0)
                xs.append(a[0] + t * (b[0] - a[0]))
        xs.sort()

        row: List[Segment] = []
        for i in range(0, len(xs) - 1, 2):
            x0, x1 = xs[i] + inset, xs[i + 1] - inset
            if x1 - x0 > max(inset, 0.05):
                row.append(((x0, z), (x1, z)))
        if not left_to_right:
            row = [(seg[1], seg[0]) for seg in reversed(row)]
        segments.extend(row)
        left_to_right = not left_to_right

    return segments
