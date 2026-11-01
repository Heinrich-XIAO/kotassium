"""Measure the ink box of an SVG path, without a browser.

The page draws every icon from hand-written path data in ``web/app.jsx``, and
the question "is this glyph centred?" has to be answerable in a build that has
no browser (the agent sandbox has none, and neither does CI). This module
reports the same box ``getBoundingClientRect()`` would, including the bulge of
a rounded corner, so a glyph can be placed by arithmetic instead of by eye.

That distinction is exactly what went wrong before: a rounded triangle's apex
arc reaches further out than its vertex, and ``getBoundingClientRect`` was used
to claim a 16-unit play glyph measured ``dx=0`` while it still read left of
centre. Measure the box here, decide the offset deliberately, store the result
in the coordinates - never as a ``transform``, which is in user units and so
misplaces the glyph at every render size but the one it was tuned at.

Only the commands the glyphs actually use are implemented (M L H V C A Z,
absolute and relative). Anything else raises instead of silently returning a
wrong box.
"""

import math
import re

_ARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "A": 7, "Z": 0}
_NUMBER = re.compile(r"[+-]?(?:\d*\.\d+|\d+\.?)(?:[eE][+-]?\d+)?")


def _tokens(data):
    index, length = 0, len(data)
    while index < length:
        char = data[index]
        if char in " \t\r\n,":
            index += 1
        elif char.isalpha():
            yield ("cmd", char)
            index += 1
        else:
            match = _NUMBER.match(data, index)
            if not match:
                raise ValueError("unsupported path data at %r" % data[index:index + 12])
            yield ("num", float(match.group()))
            index = match.end()


def segments(data):
    """Return the path as absolute segments: ('M'|'L'|'C'|'A'|'Z', points)."""
    tokens = list(_tokens(data))
    position = 0
    out = []
    current = (0.0, 0.0)
    start = (0.0, 0.0)
    previous = None

    def take(count):
        nonlocal position
        values = []
        for _ in range(count):
            if position >= len(tokens) or tokens[position][0] != "num":
                raise ValueError("path data ended early")
            values.append(tokens[position][1])
            position += 1
        return values

    while position < len(tokens):
        if tokens[position][0] == "cmd":
            command = tokens[position][1]
            position += 1
        elif previous:
            # An implicit lineto after moveto keeps the moveto's case: `m`
            # continues as a relative `l`, `M` as an absolute `L`.
            command = {"M": "L", "m": "l"}.get(previous, previous)
        else:
            raise ValueError("path data does not start with a command")
        upper = command.upper()
        if upper not in _ARGS:
            raise ValueError("unsupported path command %r" % command)
        relative = command.islower()
        if upper == "Z":
            out.append(("Z", [current, start]))
            current = start
            previous = None
            continue
        args = take(_ARGS[upper])
        if upper == "M":
            point = (args[0] + current[0], args[1] + current[1]) if relative else (args[0], args[1])
            out.append(("M", [point]))
            current = start = point
        elif upper == "L":
            point = (args[0] + current[0], args[1] + current[1]) if relative else (args[0], args[1])
            out.append(("L", [current, point]))
            current = point
        elif upper == "H":
            x = args[0] + current[0] if relative else args[0]
            out.append(("L", [current, (x, current[1])]))
            current = (x, current[1])
        elif upper == "V":
            y = args[0] + current[1] if relative else args[0]
            out.append(("L", [current, (current[0], y)]))
            current = (current[0], y)
        elif upper == "C":
            offsets = [(args[index] + current[0], args[index + 1] + current[1]) for index in (0, 2, 4)] if relative else [
                (args[0], args[1]), (args[2], args[3]), (args[4], args[5])]
            out.append(("C", [current] + offsets))
            current = offsets[2]
        elif upper == "A":
            end = (args[5] + current[0], args[6] + current[1]) if relative else (args[5], args[6])
            out.append(("A", [current, (args[0], args[1], args[2], args[3], args[4]), end]))
            current = end
        previous = command
    return out


def _bezier(points, steps=24):
    start, control1, control2, end = points
    sampled = []
    for step in range(1, steps + 1):
        t = step / steps
        u = 1 - t
        sampled.append((
            u * u * u * start[0] + 3 * u * u * t * control1[0] + 3 * u * t * t * control2[0] + t * t * t * end[0],
            u * u * u * start[1] + 3 * u * u * t * control1[1] + 3 * u * t * t * control2[1] + t * t * t * end[1],
        ))
    return sampled


def _arc(start, params, end, steps=32):
    """Sample an SVG elliptical arc (endpoint parameterisation) as points."""
    radius_x, radius_y, rotation, large_arc, sweep = params
    if radius_x == 0 or radius_y == 0:
        return [end]
    phi = math.radians(rotation)
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)
    half_x = (start[0] - end[0]) / 2.0
    half_y = (start[1] - end[1]) / 2.0
    x1 = cos_phi * half_x + sin_phi * half_y
    y1 = -sin_phi * half_x + cos_phi * half_y
    radius_x, radius_y = abs(radius_x), abs(radius_y)
    scale = (x1 * x1) / (radius_x * radius_x) + (y1 * y1) / (radius_y * radius_y)
    if scale > 1:
        factor = math.sqrt(scale)
        radius_x *= factor
        radius_y *= factor
    numerator = radius_x ** 2 * radius_y ** 2 - radius_x ** 2 * y1 ** 2 - radius_y ** 2 * x1 ** 2
    denominator = radius_x ** 2 * y1 ** 2 + radius_y ** 2 * x1 ** 2
    coefficient = 0.0 if denominator == 0 else math.sqrt(max(0.0, numerator / denominator))
    if bool(large_arc) == bool(sweep):
        coefficient = -coefficient
    center_x = coefficient * radius_x * y1 / radius_y
    center_y = -coefficient * radius_y * x1 / radius_x
    origin_x = cos_phi * center_x - sin_phi * center_y + (start[0] + end[0]) / 2.0
    origin_y = sin_phi * center_x + cos_phi * center_y + (start[1] + end[1]) / 2.0

    def angle(ux, uy, vx, vy):
        return math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)

    start_angle = angle(1.0, 0.0, (x1 - center_x) / radius_x, (y1 - center_y) / radius_y)
    sweep_angle = angle(
        (x1 - center_x) / radius_x, (y1 - center_y) / radius_y,
        (-x1 - center_x) / radius_x, (-y1 - center_y) / radius_y,
    )
    if not sweep and sweep_angle > 0:
        sweep_angle -= 2 * math.pi
    elif sweep and sweep_angle < 0:
        sweep_angle += 2 * math.pi
    count = max(8, int(abs(sweep_angle) / (math.pi / 12)) + 1)
    sampled = []
    for step in range(1, count + 1):
        theta = start_angle + sweep_angle * step / count
        sampled.append((
            origin_x + radius_x * math.cos(theta) * cos_phi - radius_y * math.sin(theta) * sin_phi,
            origin_y + radius_x * math.cos(theta) * sin_phi + radius_y * math.sin(theta) * cos_phi,
        ))
    return sampled


def points(data):
    """Every point needed to bound the path, start points included."""
    collected = []
    for command, payload in segments(data):
        if command == "Z":
            collected.append(payload[1])
        elif command in ("M", "L"):
            collected.append(payload[-1])
        elif command == "C":
            collected.extend(_bezier(payload))
        else:
            collected.extend(_arc(payload[0], payload[1], payload[2]))
    return collected


def bbox(data):
    """(min_x, min_y, max_x, max_y) of the ink drawn by this path data."""
    drawn = points(data)
    if not drawn:
        raise ValueError("path data draws nothing")
    xs = [point[0] for point in drawn]
    ys = [point[1] for point in drawn]
    return min(xs), min(ys), max(xs), max(ys)


def center(data):
    """Centre of the ink box - what the eye judges, unlike the viewBox centre."""
    left, top, right, bottom = bbox(data)
    return (left + right) / 2.0, (top + bottom) / 2.0


if __name__ == "__main__":
    import sys

    for argument in sys.argv[1:]:
        box = bbox(argument)
        print("bbox=(%.3f, %.3f, %.3f, %.3f) centre=(%.3f, %.3f)" % (box + center(argument)))
