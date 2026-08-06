# Copyright (c) 2026 Printess Technologies
# Released under the terms of the LGPLv3 or higher.
#
# Puts generated path g-code into the sliced g-code, in place of the parts the
# slicer produced for the same drawn shapes.
#
# Drawn outlines are still put on the build plate as meshes, so the plate looks
# the same, the shapes stay selectable, and pressing Slice always produces a
# gcode_dict to work on. What the slicer makes of those meshes is then thrown
# away and replaced with the drawn trajectory itself, which is the whole point:
# a stroke reconstructed from a solid loses the order it was drawn in, and no
# slicer setting brings it back.
#
# Filled shapes are left completely alone. They slice like any imported model.
#
# The merge is per LAYER, chunk by chunk, so layer-by-layer printing keeps
# interleaving the drawn paths with the sliced shapes. Appending at the end
# would print every mesh and then every path.

import re
from typing import Dict, List

from .GcodeGenerator import DRAWING_TAG, DRAWING_KIND_PATH

_MESH_RE = re.compile(r'^;MESH:(.*)$')
_LAYER_RE = re.compile(r'^;LAYER:(\d+)', re.MULTILINE)
_TOOL_RE = re.compile(r'^T(\d+)\b')
_PATH_PREFIX = "{0}-{1}".format(DRAWING_TAG, DRAWING_KIND_PATH)

# Machine state that a stripped part must not take with it. These lines say what
# the printer is doing, not what the part is, and the parts that follow depend on
# them still having been said.
_MACHINE_STATE_RE = re.compile(r'^(?:T\d+\b|M(?:104|105|106|107|109|140|190)\b)')


def is_generated_part(mesh_name: str) -> bool:
    """Whether this ;MESH: names a drawn outline, whose slicing we discard."""
    return mesh_name.strip().startswith(_PATH_PREFIX)


def replaced_names(generated: List[str]) -> set:
    """The part names the generated g-code provides.

    Strip and replace MUST be keyed on the same thing. Removing anything merely
    named like a drawn outline deleted the shapes that are legitimately sliced:
    a serpentine whose lines touch is rastered rather than generated, but it is
    still called PrintessDrawing-path-N, so it was stripped with nothing to put
    back and vanished from the print.

    NONMESH is excluded, and that exclusion is the whole correctness of this.
    Generated layers END with ;MESH:NONMESH, exactly as CuraEngine closes a mesh
    before travelling away from it. Collecting it here put "NONMESH" in the strip
    set, so strip_path_parts never turned skipping back off: everything from the
    drawn part's marker to the END OF THE LAYER went out, including the travel
    that positions the nozzle for the next layer. Every layer then began
    extruding from wherever the drawn path finished, and the chunk lost its
    trailing newline too, which glued the next ;LAYER: marker onto the previous
    line in the saved file.
    """
    names = set()
    for chunk in generated:
        for line in chunk.split("\n"):
            match = _MESH_RE.match(line.strip())
            if match:
                name = match.group(1).strip()
                if name and name != "NONMESH":
                    names.add(name)
    return names


def strip_path_parts(chunk: str, names: set) -> str:
    """Drop everything the slicer emitted for drawn outlines.

    Lines belong to a part until the next ;MESH: marker, so the skip is turned
    off again by whatever mesh comes next: a filled shape or an imported model
    following a drawn one keeps all of its own output.
    """
    kept = []
    skipping = False
    for line in chunk.split("\n"):
        stripped = line.strip()
        match = _MESH_RE.match(stripped)
        if match:
            # Only what the generated g-code actually replaces. Matching on the
            # name pattern instead deleted shapes that are legitimately sliced.
            skipping = match.group(1).strip() in names
            if skipping:
                continue
        if skipping and not _MACHINE_STATE_RE.match(stripped):
            continue
        # The slicer groups meshes by extruder, so the switch to the next
        # extruder is written directly after the last mesh of the current one.
        # When that last mesh is a drawn outline the switch falls inside the
        # skipped run, and taking it out left the part that followed printing on
        # the tool the drawn outline had been using. It was the first switch of
        # this print that went, and only that one, which is why nothing looked
        # wrong until an extruder's first two layers came out in the other
        # extruder's material a nozzle separation away from the model.
        kept.append(line)
    return "\n".join(kept)


def layer_bodies(generated: List[str]) -> Dict[int, str]:
    """The generated chunks keyed by layer, with their own ;LAYER:/;Z: header
    removed: the sliced chunk being merged into already carries one."""
    bodies = {}
    for chunk in generated:
        match = _LAYER_RE.search(chunk)
        if match is None:
            continue
        body = [line for line in chunk.split("\n")
                if not line.startswith(";LAYER:") and not line.startswith(";Z:")]
        bodies[int(match.group(1))] = "\n".join(body).strip("\n")
    return bodies


def last_tool(lines: List[str], current):
    """The tool selected after these lines, given the one selected before them."""
    for line in lines:
        match = _TOOL_RE.match(line.strip())
        if match:
            current = int(match.group(1))
    return current


def retooled(body: str, active_tool) -> List[str]:
    """The body's tool changes reduced to the ones that change anything here,
    with the caller's tool put back afterwards.

    The generator names a tool before every drawn part, because on its own it
    cannot know what the slicer left selected. Here that IS known, so a T
    selecting the tool already in use is dropped rather than made real: both
    post-processing scripts treat every T as a switch and would retract, park the
    carriage at clearance height and bring it back down for a tool the printer is
    already holding.

    Restoring the tool afterwards is what keeps the splice invisible. The layers
    around it were written by the slicer on the assumption that nothing came
    between them, so the drawn paths have to hand the stream back exactly as they
    found it.
    """
    tool = active_tool
    lines = []
    for line in body.split("\n"):
        match = _TOOL_RE.match(line.strip())
        if match:
            new_tool = int(match.group(1))
            if new_tool == tool:
                continue
            tool = new_tool
        lines.append(line)
    if active_tool is not None and tool != active_tool:
        lines.append("T{0}".format(active_tool))
    return lines


def split_closing_travel(chunk: str):
    """The chunk in two: everything up to the travel that closes the layer, and
    that travel.

    CuraEngine ends a layer by closing the mesh context with ;MESH:NONMESH and
    travelling to where the next layer begins. Putting the drawn paths after that
    travel undid it, because they move away again: the layer ended wherever the
    drawing ended, and the next layer's first move was dragged across the part
    from there. That move is an extrusion whenever the part reopens on infill, so
    it laid one segment's worth of material over the whole width of the part.

    The paths go in before the travel instead, so the travel still does the job
    it was written to do and both scripts see the layout they were built for.
    """
    lines = chunk.split("\n")
    for index in range(len(lines) - 1, -1, -1):
        match = _MESH_RE.match(lines[index].strip())
        if match:
            if match.group(1).strip() == "NONMESH":
                return lines[:index], lines[index:]
            break
    return lines, []


def merge(sliced: List[str], generated: List[str]) -> List[str]:
    """Sliced g-code with drawn outlines replaced by their generated paths."""
    bodies = layer_bodies(generated)
    names = replaced_names(generated)
    merged = []
    seen = set()
    active_tool = None

    for chunk in sliced:
        cleaned = strip_path_parts(chunk, names)
        match = _LAYER_RE.search(chunk)
        body = bodies.get(int(match.group(1))) if match is not None else None

        if not body:
            active_tool = last_tool(cleaned.split("\n"), active_tool)
            merged.append(cleaned)
            continue

        head, tail = split_closing_travel(cleaned)
        while head and not head[-1].strip():
            head.pop()
        active_tool = last_tool(head, active_tool)

        lines = head + retooled(body, active_tool) + tail
        active_tool = last_tool(lines, active_tool)
        text = "\n".join(lines)
        merged.append(text if text.endswith("\n") else text + "\n")
        seen.add(int(match.group(1)))

    # A drawing stacked taller than anything sliced has layers with no chunk to
    # go in. They are added before the footer, in order, so they still print.
    extra = sorted(layer for layer in bodies if layer not in seen)
    if extra:
        tail = []
        for layer in extra:
            lines = retooled(bodies[layer], active_tool)
            active_tool = last_tool(lines, active_tool)
            tail.append(";LAYER:{0}\n".format(layer) + "\n".join(lines) + "\n")
        merged = merged[:-1] + tail + merged[-1:] if len(merged) > 1 else merged + tail
    return merged
