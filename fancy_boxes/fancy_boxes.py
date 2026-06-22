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

SVG_NS = "http://www.w3.org/2000/svg"


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def fmt(x):
    # Stable compact formatting. Avoids noisy coordinates while keeping precision.
    if abs(x) < 1e-10:
        x = 0.0
    return ("%.6f" % x).rstrip("0").rstrip(".")


def simpson_integral_sin_power(power, n=2048):
    # Integral_0^1 sin(pi*t)^power dt. n must be even.
    if n % 2:
        n += 1
    h = 1.0 / n
    acc = math.sin(0.0) ** power + math.sin(math.pi) ** power
    for i in range(1, n):
        coeff = 4 if i % 2 else 2
        acc += coeff * (math.sin(math.pi * i * h) ** power)
    return acc * h / 3.0


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
        if self.max_node_distance <= 0.0:
            return base
        refined = [base[0]]
        for u0, u1 in zip(base, base[1:]):
            arc_len = self.L * (u1 - u0)
            pieces = max(1, int(math.ceil(arc_len / self.max_node_distance)))
            for j in range(1, pieces + 1):
                refined.append(u0 + (u1 - u0) * j / pieces)
        return refined

    @staticmethod
    def _bounded_handles(x0, y0, x1, y1, a0, a1, ds):
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

    def commands(self):
        cmds = []
        us = self._segment_us()
        for u0, u1 in zip(us, us[1:]):
            x0 = self._interp(self.x_table, u0)
            y0 = self._interp(self.y_table, u0)
            x1 = self._interp(self.x_table, u1)
            y1 = self._interp(self.y_table, u1)
            a0 = self._interp(self.phi_table, u0)
            a1 = self._interp(self.phi_table, u1)
            ds = self.L * (u1 - u0)
            c1, c2 = self._bounded_handles(x0, y0, x1, y1, a0, a1, ds)
            cmds.append((c1, c2, (x1, y1)))
        # Snap exact endpoint to avoid accumulated numeric drift.
        c1, c2, _ = cmds[-1]
        cmds[-1] = (c1, c2, (self.extent, self.extent))
        return cmds


class ElasticaCorner:
    # Free-length Euler elastica for a symmetric clamped 90-degree corner.

    def __init__(self, extent, segments=4, samples=4096, max_node_distance=0.0, target_length=0.0):
        self.extent = float(extent)
        self.segments = max(1, int(segments))
        self.samples = max(512, int(samples))
        self.max_node_distance = max(0.0, float(max_node_distance))
        self.target_length = max(0.0, float(target_length))
        self.theta_total = math.pi / 2.0
        self.sliding_length_ratio = self._sliding_length_ratio()
        if self.target_length <= 0.0 or self.target_length >= self.sliding_length_ratio * self.extent - 1e-9:
            self.mu = None
        else:
            self.mu = self._solve_mu_for_length()
        self._build_tables()

    def _inv_curvature_weight(self, theta):
        q = math.cos(theta) + math.sin(theta)
        if self.mu is None:
            return 1.0 / math.sqrt(q)
        return 1.0 / math.sqrt(max(1e-15, 1.0 + self.mu * q))

    @classmethod
    def _sliding_length_ratio(cls):
        n = 4096
        theta_total = math.pi / 2.0
        h = theta_total / n
        x = 0.0
        s = 0.0
        for i in range(n):
            a0 = i * h
            a1 = (i + 1) * h
            w0 = 1.0 / math.sqrt(math.cos(a0) + math.sin(a0))
            w1 = 1.0 / math.sqrt(math.cos(a1) + math.sin(a1))
            x += 0.5 * (math.cos(a0) * w0 + math.cos(a1) * w1) * h
            s += 0.5 * (w0 + w1) * h
        return s / x

    @classmethod
    def length_bounds(cls, extent):
        return 1.5 * extent, cls._sliding_length_ratio() * extent

    @staticmethod
    def _ratio_for_mu(mu, n=1024):
        theta_total = math.pi / 2.0
        h = theta_total / n
        x = 0.0
        s = 0.0
        for i in range(n):
            a0 = i * h
            a1 = (i + 1) * h
            q0 = math.cos(a0) + math.sin(a0)
            q1 = math.cos(a1) + math.sin(a1)
            w0 = 1.0 / math.sqrt(max(1e-15, 1.0 + mu * q0))
            w1 = 1.0 / math.sqrt(max(1e-15, 1.0 + mu * q1))
            x += 0.5 * (math.cos(a0) * w0 + math.cos(a1) * w1) * h
            s += 0.5 * (w0 + w1) * h
        return s / x

    def _solve_mu_for_length(self):
        min_len, max_len = self.length_bounds(self.extent)
        target = clamp(self.target_length, min_len, max_len) / self.extent
        circle_ratio = math.pi / 2.0
        if target <= circle_ratio:
            lo = -1.0 / math.sqrt(2.0) + 1e-9
            hi = 0.0
        else:
            lo = 0.0
            hi = 1.0
            while self._ratio_for_mu(hi) < target and hi < 1e9:
                hi *= 2.0
        for _ in range(64):
            mid = 0.5 * (lo + hi)
            if self._ratio_for_mu(mid) < target:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    def _build_tables(self):
        n = self.samples
        h = self.theta_total / n
        x = [0.0]
        y = [0.0]
        s = [0.0]
        for i in range(n):
            a0 = i * h
            a1 = (i + 1) * h
            w0 = self._inv_curvature_weight(a0)
            w1 = self._inv_curvature_weight(a1)
            x.append(x[-1] + 0.5 * (math.cos(a0) * w0 + math.cos(a1) * w1) * h)
            y.append(y[-1] + 0.5 * (math.sin(a0) * w0 + math.sin(a1) * w1) * h)
            s.append(s[-1] + 0.5 * (w0 + w1) * h)
        scale = self.extent / (0.5 * (x[-1] + y[-1]))
        self.x_table = [xx * scale for xx in x]
        self.y_table = [yy * scale for yy in y]
        self.s_table = [ss * scale for ss in s]

    def _interp(self, table, theta):
        if theta <= 0.0:
            return table[0]
        if theta >= self.theta_total:
            return table[-1]
        pos = theta / self.theta_total * self.samples
        i = int(pos)
        f = pos - i
        return table[i] * (1.0 - f) + table[i + 1] * f

    def _segment_thetas(self):
        base = [self.theta_total * i / self.segments for i in range(self.segments + 1)]
        if self.max_node_distance <= 0.0:
            return base
        refined = [base[0]]
        for a0, a1 in zip(base, base[1:]):
            s0 = self._interp(self.s_table, a0)
            s1 = self._interp(self.s_table, a1)
            pieces = max(1, int(math.ceil((s1 - s0) / self.max_node_distance)))
            for j in range(1, pieces + 1):
                refined.append(a0 + (a1 - a0) * j / pieces)
        return refined

    def commands(self):
        cmds = []
        thetas = self._segment_thetas()
        for a0, a1 in zip(thetas, thetas[1:]):
            x0 = self._interp(self.x_table, a0)
            y0 = self._interp(self.y_table, a0)
            x1 = self._interp(self.x_table, a1)
            y1 = self._interp(self.y_table, a1)
            s0 = self._interp(self.s_table, a0)
            s1 = self._interp(self.s_table, a1)
            c1, c2 = ProfileCorner._bounded_handles(x0, y0, x1, y1, a0, a1, s1 - s0)
            cmds.append((c1, c2, (x1, y1)))
        c1, c2, _ = cmds[-1]
        cmds[-1] = (c1, c2, (self.extent, self.extent))
        return cmds


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
        # Legacy names are kept so older command-line invocations still work.
        pars.add_argument("--width", type=float, default=200.0)
        pars.add_argument("--height", type=float, default=100.0)
        pars.add_argument("--corner", type=float, default=20.0)
        pars.add_argument("--unit", default="px")
        pars.add_argument("--label", default="Fancy box")

        pars.add_argument("--mode", default="exact_g2")
        pars.add_argument("--profile", default="sin_p")
        pars.add_argument("--power", type=float, default=2.0)
        pars.add_argument("--sin_power", type=float, default=None)
        pars.add_argument("--smooth_power", type=float, default=None)
        pars.add_argument("--elastica_length", type=float, default=0.0)
        pars.add_argument("--elastica_length_factor", type=float, default=None)
        pars.add_argument("--segments", type=int, default=0)
        pars.add_argument("--max_angle", type=float, default=18.0)
        pars.add_argument("--max_node_distance", type=float, default=0.0)

        for prefix in ("exact", "custom"):
            pars.add_argument(f"--{prefix}_width", type=float, default=None)
            pars.add_argument(f"--{prefix}_height", type=float, default=None)
            pars.add_argument(f"--{prefix}_corner", type=float, default=None)
            pars.add_argument(f"--{prefix}_unit", default=None)
            pars.add_argument(f"--{prefix}_label", default=None)

    def mode_option(self, name):
        prefix = "exact" if self.options.mode == "exact_g2" else "custom"
        value = getattr(self.options, f"{prefix}_{name}", None)
        if value is not None:
            return value
        return getattr(self.options, name)

    def unit_value(self, value, unit):
        return self.svg.unittouu(str(value) + unit)

    def auto_segments(self, mode):
        if self.options.segments and self.options.segments > 0:
            return max(1, self.options.segments)
        # Equal tangent-angle segmentation. This keeps node placement comparable
        # across boxes and puts more representational power where visual turn occurs.
        max_ang = clamp(float(self.options.max_angle), 5.0, 90.0)
        base = int(math.ceil(90.0 / max_ang))
        if mode == "exact_g2":
            return 1
        return max(2, base)

    def effect(self):
        unit = self.mode_option("unit")
        label = self.mode_option("label")
        w = max(1e-9, self.unit_value(self.mode_option("width"), unit))
        h = max(1e-9, self.unit_value(self.mode_option("height"), unit))
        e_req = max(0.0, self.unit_value(self.mode_option("corner"), unit))
        e = clamp(e_req, 0.0, min(w, h) / 2.0)
        mode = self.options.mode
        profile = self.options.profile
        profile_power = None
        elastica_length = 0.0
        if mode != "exact_g2":
            max_node_distance = max(0.0, self.unit_value(self.options.max_node_distance, unit))
            if profile == "elastica":
                profile_power = None
                if self.options.elastica_length_factor is not None:
                    elastica_length_req = max(0.0, float(self.options.elastica_length_factor)) * e
                else:
                    elastica_length_req = max(0.0, self.unit_value(self.options.elastica_length, unit))
                min_len, max_len = ElasticaCorner.length_bounds(e)
                elastica_length = clamp(elastica_length_req, min_len, max_len)
            else:
                if profile == "smooth_step":
                    profile_power = self.options.smooth_power
                else:
                    profile = "sin_p"
                    profile_power = self.options.sin_power
                if profile_power is None:
                    profile_power = self.options.power
                profile_power = clamp(float(profile_power), 1.0, 12.0)

        cx, cy = self.svg.namedview.center
        x0, y0 = cx - w / 2.0, cy - h / 2.0
        x1, y1 = cx + w / 2.0, cy + h / 2.0

        if e <= 1e-9:
            d = "M %s,%s L %s,%s L %s,%s L %s,%s Z" % (
                fmt(x0), fmt(y0), fmt(x1), fmt(y0), fmt(x1), fmt(y1), fmt(x0), fmt(y1)
            )
        else:
            if mode == "exact_g2":
                corner_cmds = exact_g2_corner(e)
            else:
                if profile == "elastica":
                    corner_cmds = ElasticaCorner(
                        e,
                        segments=self.auto_segments(mode),
                        max_node_distance=max_node_distance,
                        target_length=elastica_length,
                    ).commands()
                else:
                    corner_cmds = ProfileCorner(
                        e,
                        power=profile_power,
                        segments=self.auto_segments(mode),
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
        node = etree.SubElement(self.svg.get_current_layer(), inkex.addNS("path", "svg"), attrib)
        node.set("data-fancy-box-width", fmt(w))
        node.set("data-fancy-box-height", fmt(h))
        node.set("data-fancy-box-corner-extent", fmt(e))
        node.set("data-fancy-box-mode", self.options.mode)
        if mode != "exact_g2":
            node.set("data-fancy-box-profile", profile)
            if profile_power is not None:
                node.set("data-fancy-box-profile-power", fmt(profile_power))
            if profile == "elastica" and elastica_length > 0.0:
                node.set("data-fancy-box-elastica-length", fmt(elastica_length))
        node.set("data-fancy-box-segments-per-corner", str(self.auto_segments(mode)))
        if e_req > e:
            inkex.errormsg("Corner size was clamped to half of the smaller box dimension: %s %s" % (fmt(e), unit))


if __name__ == "__main__":
    FancyBoxes().run()
