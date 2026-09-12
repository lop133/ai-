#!/usr/bin/env python3
"""
Verification harness for pelican-bicycle.svg.

1. structural checks on the shipped file (well-formed XML, keyTimes/values agree,
   path `d` frames share a command structure, IK actually closes the leg chain)
2. a SMIL-subset evaluator: it *reads the real .svg*, resolves every
   <animate>/<animateTransform> at a given document time, bakes the result into
   the element's attributes and rasterises the frame with resvg.

That way the PNGs come from the file we ship, not from a model of it.

Usage:  python3 verify.py            # checks + frames/*.png
        python3 verify.py --no-png   # checks only
"""

from __future__ import annotations

import math
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SVG = ROOT / "pelican-bicycle.svg"
FRAMES = ROOT / "frames"
SVGNS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVGNS)

TAG = lambda n: f"{{{SVGNS}}}{n}"
NUM = re.compile(r"-?\d*\.?\d+(?:e[-+]?\d+)?", re.I)

FAILURES: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILURES.append(msg)


# --------------------------------------------------------------------------- #
# SMIL subset evaluator
# --------------------------------------------------------------------------- #
def parse_values(raw: str) -> list[str]:
    return [v.strip() for v in raw.split(";") if v.strip() != ""]


def parse_keytimes(raw: str | None, n: int) -> list[float]:
    if not raw:
        return [i / (n - 1) for i in range(n)]
    return [float(v) for v in raw.replace(";", " ").split()]


def lerp_str(a: str, b: str, k: float) -> str:
    """Interpolate every number inside two same-shaped attribute strings."""
    na = [float(x) for x in NUM.findall(a)]
    nb = [float(x) for x in NUM.findall(b)]
    if len(na) != len(nb):
        raise ValueError(f"shape mismatch: {len(na)} vs {len(nb)} numbers")
    it = iter(round(x + (y - x) * k, 3) for x, y in zip(na, nb))
    return NUM.sub(lambda _: str(next(it)), a)


def sample(anim: ET.Element, t: float) -> str | None:
    dur = float(anim.get("dur", "0s").rstrip("s"))
    if dur <= 0:
        return None
    begin = 0.0
    if anim.get("begin"):
        begin = float(anim.get("begin").rstrip("s"))
    if anim.get("repeatCount") != "indefinite":
        return None

    if anim.get("values"):
        vals = parse_values(anim.get("values"))
    elif anim.get("from") and anim.get("to"):
        vals = [anim.get("from"), anim.get("to")]
    else:
        return None

    kt = parse_keytimes(anim.get("keyTimes"), len(vals))
    if len(kt) != len(vals):
        raise ValueError(f"keyTimes ({len(kt)}) != values ({len(vals)})")

    local = (t - begin) % dur
    p = local / dur
    if p <= kt[0]:
        return vals[0]
    for i in range(len(kt) - 1):
        if p <= kt[i + 1]:
            span = kt[i + 1] - kt[i]
            k = 0.0 if span == 0 else (p - kt[i]) / span
            return lerp_str(vals[i], vals[i + 1], k)
    return vals[-1]


def bake(xml_root: ET.Element, t: float) -> int:
    """Apply every animation's value at time `t` and strip the anim elements."""
    n = 0
    for parent in list(xml_root.iter()):
        for anim in [c for c in parent if c.tag in (TAG("animate"), TAG("animateTransform"))]:
            val = sample(anim, t)
            if val is not None:
                attr = anim.get("attributeName")
                if anim.tag == TAG("animateTransform"):
                    kind = anim.get("type")
                    val = f"{kind}({val.replace(';', ' ').replace(',', ' ')})"
                    existing = parent.get("transform")
                    parent.set("transform", f"{val} {existing}" if existing else val)
                else:
                    parent.set(attr, val)
            parent.remove(anim)
            n += 1
    return n


# --------------------------------------------------------------------------- #
def structural_checks(tree: ET.Element) -> None:
    print("\n[1] structure")
    anims = [e for e in tree.iter() if e.tag in (TAG("animate"), TAG("animateTransform"))]
    check(len(anims) > 0, f"{len(anims)} animation elements present")
    check(all(a.get("repeatCount") == "indefinite" for a in anims),
          "every animation loops forever (repeatCount=indefinite)")
    check(all(a.get("dur", "").endswith("s") and float(a.get("dur", "0s")[:-1]) > 0
              for a in anims), "every animation has a positive dur")
    check(all(a.get("data-dur") and
              abs(float(a.get("data-dur")) - float(a.get("dur", "0s")[:-1])) < 1e-9
              for a in anims), "data-dur matches dur on every animation (speed control)")

    # keyTimes must line up with values
    bad = [a for a in anims if a.get("keyTimes")
           and len(parse_keytimes(a.get("keyTimes"), 0))
           != len(parse_values(a.get("values")))]
    check(not bad, "keyTimes count matches values count")

    # path morph frames must share a command structure
    morphs = [a for a in anims if a.get("attributeName") == "d"]
    for a in morphs:
        vals = parse_values(a.get("values"))
        sig = {re.sub(NUM, "#", v).replace(" ", "") for v in vals}
        check(len(sig) == 1, f"path morph: {len(vals)} frames share one command structure")
        counts = {len(NUM.findall(v)) for v in vals}
        check(len(counts) == 1, f"path morph: all frames carry {counts.pop()} numbers")


def kinematics_checks() -> None:
    print("\n[2] kinematics (imported from build.py, the code that wrote the file)")
    sys.path.insert(0, str(ROOT))
    import build

    pedals, thigh, shin_rel = build.leg_frames(0.0)
    worst_thigh = worst_shin = worst_pedal = 0.0
    for foot, ta, sr in zip(pedals, thigh, shin_rel):
        a = math.radians(ta)
        knee = (build.HIP[0] + build.THIGH * math.cos(a), build.HIP[1] + build.THIGH * math.sin(a))
        b = math.radians(ta + sr)
        end = (knee[0] + build.SHIN * math.cos(b), knee[1] + build.SHIN * math.sin(b))
        worst_thigh = max(worst_thigh, math.dist(knee, build.HIP) - build.THIGH)
        worst_shin = max(worst_shin, math.dist(end, knee) - build.SHIN)
        worst_pedal = max(worst_pedal, math.dist(end, foot))
    check(worst_thigh < 1e-6, f"thigh length constant (max error {worst_thigh:.2e})")
    check(worst_shin < 1e-6, f"shin length constant (max error {worst_shin:.2e})")
    check(worst_pedal < 1e-6, f"foot lands exactly on the pedal (max error {worst_pedal:.2e})")

    on_circle = max(abs(math.dist(p, build.BB) - build.CRANK_R) for p in pedals)
    check(on_circle < 1e-9, f"pedal track is a circle of r={build.CRANK_R} "
                            f"(max error {on_circle:.2e})")
    check(len(pedals) == build.KEYFRAMES + 1 and pedals[0] == pedals[-1],
          f"{len(pedals)} keyframes, first == last so the loop is seamless")

    reach = max(math.dist(build.HIP, p) for p in pedals)
    check(reach < build.THIGH + build.SHIN,
          f"furthest pedal {reach:.1f}px < leg reach {build.THIGH + build.SHIN:.0f}px")

    # the tyre must sit on the road
    check(abs(build.REAR_HUB[1] + build.WHEEL_R - build.GROUND) < 1e-6 and
          abs(build.FRONT_HUB[1] + build.WHEEL_R - build.GROUND) < 1e-6,
          f"both tyres touch the road at y={build.GROUND}")


def render(times: list[float]) -> None:
    print("\n[3] rasterising frames from the shipped .svg")
    script = ROOT / "render-frame.js"
    FRAMES.mkdir(exist_ok=True)
    for t in times:
        tree = ET.parse(SVG)
        n = bake(tree.getroot(), t)
        out = FRAMES / f"t{t:04.2f}.svg"
        out.write_bytes(ET.tostring(tree.getroot(), encoding="utf-8", xml_declaration=True))
        png = FRAMES / f"t{t:04.2f}.png"
        r = subprocess.run(["node", str(script), str(out), str(png)],
                           capture_output=True, text=True)
        ok = r.returncode == 0 and png.exists()
        check(ok, f"t={t:5.2f}s -> {png.name} ({n} animations baked)"
                  + ("" if ok else f"\n         {r.stderr.strip()[:300]}"))


def main() -> None:
    tree = ET.parse(SVG)                       # raises if not well-formed
    check(True, f"{SVG.name} parses as well-formed XML")
    structural_checks(tree.getroot())
    kinematics_checks()
    if "--no-png" not in sys.argv:
        # a few points spread over one pedal revolution + a blink + a bell ring
        render([0.0, 0.24, 0.48, 0.72, 0.97, 1.45, 3.85])
    print("\n" + ("ALL CHECKS PASSED" if not FAILURES else
                  f"{len(FAILURES)} FAILURE(S):\n - " + "\n - ".join(FAILURES)))
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
