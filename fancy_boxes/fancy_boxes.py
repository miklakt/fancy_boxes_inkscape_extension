#!/usr/bin/env python3
# coding=utf-8
"""
Fancy Boxes for Inkscape
Generates deterministic G2 and custom smooth-corner boxes.

Install this file together with fancy_boxes.inx in your Inkscape user extensions folder.
"""

import math
from bisect import bisect_left
from lxml import etree
import inkex


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def fmt(x):
    # Stable compact formatting. Avoids noisy coordinates while keeping precision.
    if abs(x) < 1e-10:
        x = 0.0
    return ("%.6f" % x).rstrip("0").rstrip(".")


def bounded_handles(x0, y0, x1, y1, a0, a1, ds):
    eps = 1e-12
    dx = max(0.0, x1 - x0)
    dy = max(0.0, y1 - y0)
    t0x, t0y = math.cos(a0), math.sin(a0)
    t1x, t1y = math.cos(a1), math.sin(a1)
    alpha = ds / 3.0
    beta = ds / 3.0

    if t0x > eps:
        alpha = min(alpha, dx / t0x)
    if t0y > eps:
        alpha = min(alpha, dy / t0y)
    if t1x > eps:
        beta = min(beta, dx / t1x)
    if t1y > eps:
        beta = min(beta, dy / t1y)

    span_x = alpha * t0x + beta * t1x
    if span_x > dx and span_x > eps:
        scale = dx / span_x
        alpha *= scale
        beta *= scale
    span_y = alpha * t0y + beta * t1y
    if span_y > dy and span_y > eps:
        scale = dy / span_y
        alpha *= scale
        beta *= scale

    c1 = (x0 + t0x * alpha, y0 + t0y * alpha)
    c2 = (x1 - t1x * beta, y1 - t1y * beta)
    return c1, c2


def zero_curvature_handles(x0, y0, x1, y1, a0, a1, ds, zero_start=False, zero_end=False):
    if zero_start and zero_end:
        return (x1, y0), (x1, y0)

    eps = 1e-12
    if zero_start and math.sin(a1) > eps:
        beta = y1 / math.sin(a1)
        c2 = (x1 - math.cos(a1) * beta, y0)
        if c2[0] >= x0 - eps:
            alpha = min(ds / 3.0, max(0.0, c2[0] - x0))
            return (x0 + alpha, y0), c2

    if zero_end and math.cos(a0) > eps:
        alpha = (x1 - x0) / math.cos(a0)
        c1 = (x1, y0 + math.sin(a0) * alpha)
        if c1[1] <= y1 + eps:
            beta = min(ds / 3.0, max(0.0, y1 - c1[1]))
            return c1, (x1, y1 - beta)

    return bounded_handles(x0, y0, x1, y1, a0, a1, ds)


def refine_segments(base, length_between, max_node_distance):
    if max_node_distance <= 0.0:
        return base
    refined = [base[0]]
    for p0, p1 in zip(base, base[1:]):
        pieces = max(1, int(math.ceil(length_between(p0, p1) / max_node_distance)))
        for j in range(1, pieces + 1):
            refined.append(p0 + (p1 - p0) * j / pieces)
    return refined


def corner_commands(params, segment_data, extent):
    cmds = []
    last = len(params) - 2
    for i, (p0, p1) in enumerate(zip(params, params[1:])):
        x0, y0, x1, y1, a0, a1, ds = segment_data(p0, p1)
        c1, c2 = zero_curvature_handles(
            x0,
            y0,
            x1,
            y1,
            a0,
            a1,
            ds,
            zero_start=(i == 0),
            zero_end=(i == last),
        )
        cmds.append((c1, c2, (x1, y1)))
    c1, c2, _ = cmds[-1]
    cmds[-1] = (c1, c2, (extent, extent))
    return cmds


class ProfileCorner:
    """Canonical 90-degree corner in SVG coordinates.

    Starts at (0, 0) with tangent +x.
    Ends at (extent, extent) with tangent +y.
    The internal curve is generated from a normalized curvature profile,
    then converted to cubic Hermite segments. Segment boundaries are placed
    at equal tangent-angle increments,
    which gives visually stable node placement and identical corners.
    """

    def __init__(self, extent, power=2.0, segments=4, samples=4096, profile="sin_p", max_node_distance=0.0):
        self.extent = float(extent)
        self.power = float(power)
        self.profile = profile
        self.segments = max(1, int(segments))
        self.samples = max(512, int(samples))
        self.max_node_distance = max(0.0, float(max_node_distance))
        self.theta_total = math.pi / 2.0
        self._build_tables()

    def _profile_weight(self, u):
        if self.profile == "smooth_step":
            return (u * (1.0 - u)) ** self.power
        if self.profile == "clothoid":
            plateau = clamp(self.power, 0.0, 1.0)
            ramp = 0.5 * (1.0 - plateau)
            if ramp <= 1e-12:
                return 1.0
            return min(1.0, u / ramp, (1.0 - u) / ramp)
        return math.sin(math.pi * u) ** self.power

    def _build_tables(self):
        n = self.samples
        # Cumulative integral of the selected curvature profile over u in [0,1].
        vals = [self._profile_weight(i / n) for i in range(n + 1)]
        cum = [0.0]
        for i in range(n):
            cum.append(cum[-1] + 0.5 * (vals[i] + vals[i + 1]) / n)
        total = cum[-1]
        # phi(u) = accumulated turning angle.
        phi = [self.theta_total * c / total for c in cum]
        # Integrate cos(phi), sin(phi) to get normalized coordinates for L=1.
        x = [0.0]
        y = [0.0]
        for i in range(n):
            x.append(x[-1] + 0.5 * (math.cos(phi[i]) + math.cos(phi[i + 1])) / n)
            y.append(y[-1] + 0.5 * (math.sin(phi[i]) + math.sin(phi[i + 1])) / n)
        # For the symmetric 90-degree profile, x[-1] == y[-1] within integration error.
        end_extent_for_L1 = 0.5 * (x[-1] + y[-1])
        self.L = self.extent / end_extent_for_L1
        self.u_table = [i / n for i in range(n + 1)]
        self.phi_table = phi
        self.x_table = [xx * self.L for xx in x]
        self.y_table = [yy * self.L for yy in y]

    def _interp(self, table, u):
        if u <= 0.0:
            return table[0]
        if u >= 1.0:
            return table[-1]
        pos = u * self.samples
        i = int(pos)
        f = pos - i
        return table[i] * (1.0 - f) + table[i + 1] * f

    def _u_for_angle_fraction(self, frac):
        target = self.theta_total * frac
        tbl = self.phi_table
        j = bisect_left(tbl, target)
        if j <= 0:
            return 0.0
        if j >= len(tbl):
            return 1.0
        a = tbl[j - 1]
        b = tbl[j]
        if abs(b - a) < 1e-15:
            return self.u_table[j]
        f = (target - a) / (b - a)
        return self.u_table[j - 1] * (1.0 - f) + self.u_table[j] * f

    def _segment_us(self):
        base = [self._u_for_angle_fraction(i / self.segments) for i in range(self.segments + 1)]
        return refine_segments(
            base,
            lambda u0, u1: self.L * (u1 - u0),
            self.max_node_distance,
        )

    def commands(self):
        us = self._segment_us()

        def segment_data(u0, u1):
            x0 = self._interp(self.x_table, u0)
            y0 = self._interp(self.y_table, u0)
            x1 = self._interp(self.x_table, u1)
            y1 = self._interp(self.y_table, u1)
            a0 = self._interp(self.phi_table, u0)
            a1 = self._interp(self.phi_table, u1)
            ds = self.L * (u1 - u0)
            return x0, y0, x1, y1, a0, a1, ds

        return corner_commands(us, segment_data, self.extent)


class ElasticaCorner:
    """Euler elastica with zero curvature at the two straight-edge joins."""

    def __init__(self, extent, segments=4, samples=4096, max_node_distance=0.0):
        self.extent = float(extent)
        self.segments = max(1, int(segments))
        self.samples = max(512, int(samples))
        self.max_node_distance = max(0.0, float(max_node_distance))
        self.theta_total = math.pi / 2.0
        self._build_tables()

    @staticmethod
    def _smoothstep(t):
        return t * t * (3.0 - 2.0 * t)

    def _theta_for_t(self, t):
        return self.theta_total * self._smoothstep(t)

    def _density(self, t, component):
        theta = self._theta_for_t(t)
        dtheta_dt = self.theta_total * 6.0 * t * (1.0 - t)
        q = math.cos(theta) + math.sin(theta) - 1.0
        if q <= 1e-14:
            base = 2.0 * math.sqrt(3.0 * self.theta_total)
            if t <= 0.5:
                theta = 0.0
            else:
                theta = self.theta_total
        else:
            base = dtheta_dt / math.sqrt(q)

        if component == "x":
            return math.cos(theta) * base
        if component == "y":
            return math.sin(theta) * base
        return base

    def _build_tables(self):
        n = self.samples
        theta = [self._theta_for_t(i / n) for i in range(n + 1)]
        x = [0.0]
        y = [0.0]
        s = [0.0]
        for i in range(n):
            t0 = i / n
            t1 = (i + 1) / n
            h = t1 - t0
            x.append(x[-1] + 0.5 * (self._density(t0, "x") + self._density(t1, "x")) * h)
            y.append(y[-1] + 0.5 * (self._density(t0, "y") + self._density(t1, "y")) * h)
            s.append(s[-1] + 0.5 * (self._density(t0, "s") + self._density(t1, "s")) * h)
        scale = self.extent / (0.5 * (x[-1] + y[-1]))
        self.theta_table = theta
        self.x_table = [xx * scale for xx in x]
        self.y_table = [yy * scale for yy in y]
        self.s_table = [ss * scale for ss in s]

    def _interp(self, table, theta):
        if theta <= 0.0:
            return table[0]
        if theta >= self.theta_total:
            return table[-1]
        tbl = self.theta_table
        j = bisect_left(tbl, theta)
        if j <= 0:
            return table[0]
        if j >= len(tbl):
            return table[-1]
        a = tbl[j - 1]
        b = tbl[j]
        if abs(b - a) < 1e-15:
            return table[j]
        f = (theta - a) / (b - a)
        return table[j - 1] * (1.0 - f) + table[j] * f

    def _segment_thetas(self):
        base = [self.theta_total * i / self.segments for i in range(self.segments + 1)]
        return refine_segments(
            base,
            lambda a0, a1: self._interp(self.s_table, a1) - self._interp(self.s_table, a0),
            self.max_node_distance,
        )

    def commands(self):
        thetas = self._segment_thetas()

        def segment_data(a0, a1):
            s0 = self._interp(self.s_table, a0)
            s1 = self._interp(self.s_table, a1)
            x0 = self._interp(self.x_table, a0)
            y0 = self._interp(self.y_table, a0)
            x1 = self._interp(self.x_table, a1)
            y1 = self._interp(self.y_table, a1)
            return x0, y0, x1, y1, a0, a1, s1 - s0

        return corner_commands(thetas, segment_data, self.extent)


def exact_g2_corner(extent):
    """One-cubic exact G2 transition for a 90-degree box corner.

    This is the minimum-node smooth corner possible with SVG cubic paths.
    It has zero curvature at the two straight-edge joins.
    """
    e = float(extent)
    return [((e, 0.0), (e, 0.0), (e, e))]


def transform_point(pt, origin, rotation_quarters):
    x, y = pt
    r = rotation_quarters % 4
    if r == 0:
        xx, yy = x, y
    elif r == 1:
        xx, yy = -y, x
    elif r == 2:
        xx, yy = -x, -y
    else:
        xx, yy = y, -x
    return origin[0] + xx, origin[1] + yy


def append_corner(path_tokens, cmds, origin, rotation_quarters):
    for c1, c2, p in cmds:
        q1 = transform_point(c1, origin, rotation_quarters)
        q2 = transform_point(c2, origin, rotation_quarters)
        q = transform_point(p, origin, rotation_quarters)
        path_tokens.append("C %s,%s %s,%s %s,%s" % (fmt(q1[0]), fmt(q1[1]), fmt(q2[0]), fmt(q2[1]), fmt(q[0]), fmt(q[1])))


class FancyBoxes(inkex.EffectExtension):
    def add_arguments(self, pars):
        pars.add_argument("--mode", default="exact_g2")
        pars.add_argument("--profile", default="sin_p")
        pars.add_argument("--sin_power", type=float, default=2.0)
        pars.add_argument("--smooth_power", type=float, default=2.0)
        pars.add_argument("--clothoid_plateau", type=float, default=0.0)
        pars.add_argument("--segments", type=int, default=0)
        pars.add_argument("--max_angle", type=float, default=18.0)
        pars.add_argument("--max_node_distance", type=float, default=0.0)

        for prefix in ("exact", "custom"):
            pars.add_argument(f"--{prefix}_width", type=float, default=200.0)
            pars.add_argument(f"--{prefix}_height", type=float, default=100.0)
            pars.add_argument(f"--{prefix}_corner", type=float, default=20.0)
            pars.add_argument(f"--{prefix}_unit", default="px")
            pars.add_argument(f"--{prefix}_label", default="Fancy box")

    def mode_option(self, name):
        prefix = "exact" if self.options.mode == "exact_g2" else "custom"
        return getattr(self.options, f"{prefix}_{name}")

    def unit_value(self, value, unit):
        return self.svg.unittouu(str(value) + unit)

    def auto_segments(self):
        if self.options.segments and self.options.segments > 0:
            return max(1, self.options.segments)
        # Equal tangent-angle segmentation. This keeps node placement comparable
        # across boxes and puts more representational power where visual turn occurs.
        max_ang = clamp(float(self.options.max_angle), 5.0, 90.0)
        base = int(math.ceil(90.0 / max_ang))
        if self.options.mode == "exact_g2":
            return 1
        return max(2, base)

    def selected_style_attribs(self):
        selected = getattr(self.svg, "selected", None)
        source = None
        if selected:
            ids = getattr(self.options, "ids", None) or []
            source = selected.get(ids[-1]) if ids else None
        if source is None and selected:
            source = list(selected.values())[-1]
        style = source.get("style") if source is not None else None
        width = fmt(self.svg.unittouu("0.3mm"))
        return {"style": style or "fill:none;stroke:#000000;stroke-width:%s" % width}

    def effect(self):
        unit = self.mode_option("unit")
        label = self.mode_option("label")
        w = max(1e-9, self.unit_value(self.mode_option("width"), unit))
        h = max(1e-9, self.unit_value(self.mode_option("height"), unit))
        e_req = max(0.0, self.unit_value(self.mode_option("corner"), unit))
        e = clamp(e_req, 0.0, min(w, h) / 2.0)
        mode = self.options.mode
        profile = self.options.profile
        segments = self.auto_segments()
        profile_power = None
        if mode != "exact_g2":
            max_node_distance = max(0.0, self.unit_value(self.options.max_node_distance, unit))
            if profile != "elastica":
                if profile == "smooth_step":
                    profile_power = self.options.smooth_power
                elif profile == "clothoid":
                    profile_power = self.options.clothoid_plateau
                else:
                    profile = "sin_p"
                    profile_power = self.options.sin_power
                if profile_power is not None:
                    lo = 0.0 if profile == "clothoid" else 1.0
                    hi = 1.0 if profile == "clothoid" else 12.0
                    profile_power = clamp(float(profile_power), lo, hi)

        cx, cy = self.svg.namedview.center
        x0, y0 = cx - w / 2.0, cy - h / 2.0
        x1, y1 = cx + w / 2.0, cy + h / 2.0

        if e <= 1e-9:
            d = "M %s,%s L %s,%s L %s,%s L %s,%s Z" % (
                fmt(x0), fmt(y0), fmt(x1), fmt(y0), fmt(x1), fmt(y1), fmt(x0), fmt(y1)
            )
        else:
            if self.options.mode == "exact_g2":
                corner_cmds = exact_g2_corner(e)
            else:
                if profile == "elastica":
                    corner_cmds = ElasticaCorner(
                        e,
                        segments=segments,
                        max_node_distance=max_node_distance,
                    ).commands()
                else:
                    corner_cmds = ProfileCorner(
                        e,
                        power=profile_power if profile_power is not None else 1.0,
                        segments=segments,
                        profile=profile,
                        max_node_distance=max_node_distance,
                    ).commands()

            tokens = ["M %s,%s" % (fmt(x0 + e), fmt(y0))]
            tokens.append("L %s,%s" % (fmt(x1 - e), fmt(y0)))
            append_corner(tokens, corner_cmds, (x1 - e, y0), 0)       # top-right
            tokens.append("L %s,%s" % (fmt(x1), fmt(y1 - e)))
            append_corner(tokens, corner_cmds, (x1, y1 - e), 1)       # bottom-right
            tokens.append("L %s,%s" % (fmt(x0 + e), fmt(y1)))
            append_corner(tokens, corner_cmds, (x0 + e, y1), 2)       # bottom-left
            tokens.append("L %s,%s" % (fmt(x0), fmt(y0 + e)))
            append_corner(tokens, corner_cmds, (x0, y0 + e), 3)       # top-left
            tokens.append("Z")
            d = " ".join(tokens)

        attrib = {
            "d": d,
            inkex.addNS("label", "inkscape"): label,
        }
        attrib.update(self.selected_style_attribs())
        node = etree.SubElement(self.svg.get_current_layer(), inkex.addNS("path", "svg"), attrib)
        node.set("data-fancy-box-width", fmt(w))
        node.set("data-fancy-box-height", fmt(h))
        node.set("data-fancy-box-corner-extent", fmt(e))
        node.set("data-fancy-box-mode", self.options.mode)
        if mode != "exact_g2":
            node.set("data-fancy-box-profile", profile)
            if profile_power is not None:
                node.set("data-fancy-box-profile-power", fmt(profile_power))
        node.set("data-fancy-box-segments-per-corner", str(segments))
        if e_req > e:
            inkex.errormsg("Corner size was clamped to half of the smaller box dimension: %s %s" % (fmt(e), unit))


if __name__ == "__main__":
    FancyBoxes().run()
