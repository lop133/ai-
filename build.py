#!/usr/bin/env python3
"""
鹈鹕骑自行车 — SVG 动画生成器 / Pelican-on-a-bicycle SVG animation generator.

Emits:
  * pelican-bicycle.svg  — standalone SMIL animation, no JS required
  * index.html           — demo page with the same SVG inlined + playback controls

Everything is plain SVG + SMIL (<animate>/<animateTransform>), so the .svg file
plays on its own in any browser, in an <img> tag, or in a design tool.

The bicycle is real geometry: the pedals travel on a circle around the bottom
bracket, and the legs are solved with two-bone inverse kinematics each frame so
the feet stay glued to the pedals for the whole revolution.

Usage:  python3 build.py
"""

from __future__ import annotations

import math
import pathlib

# ----------------------------------------------------------------------------
# geometry
# ----------------------------------------------------------------------------
W, H = 900, 600
GROUND = 463                      # road surface (y of tyre contact)

REAR_HUB = (330.0, 385.0)         # rear wheel centre
FRONT_HUB = (585.0, 385.0)        # front wheel centre
WHEEL_R = 78.0

BB = (450.0, 390.0)               # bottom bracket / crank axle
CRANK_R = 30.0                    # crank arm length (pedal circle radius)
CHAINRING_R = 26.0
COG_R = 12.0

HIP = (400.0, 300.0)              # pelvis pivot of the near leg
THIGH, SHIN = 68.0, 74.0

# ----------------------------------------------------------------------------
# timing
# ----------------------------------------------------------------------------
CRANK_T = 1.95                    # one full pedal revolution
# gearing: chainring 26t driving a 12t cog -> wheel turns 26/12 per crank turn
WHEEL_T = CRANK_T * COG_R / CHAINRING_R          # ~0.90 s
ROLL_T = 0.45                                    # road dash scroll period
BOB_T = CRANK_T / 2                              # pelican bobs twice per rev

KEYFRAMES = 24                    # IK samples per pedal revolution


# ----------------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------------
def f2(x: float) -> str:
    return f"{x:.2f}"


def attrs(**kw) -> str:
    out = []
    for k, v in kw.items():
        if v is None:
            continue
        name = "data-dur" if k == "data_dur" else k
        out.append(f'{name}="{v}"')
    return " ".join(out)


def animate(attr: str, values, dur: float, indent: int = 6, **kw) -> str:
    """<animate> with a `values` list; repeats forever, tagged for the speed UI."""
    kw.setdefault("data_dur", f"{dur:.3f}")
    if isinstance(values, (list, tuple)):
        values = ";".join(values)
    pad = " " * indent
    extra = attrs(**kw)
    tail = f" {extra}" if extra else ""
    return (f'{pad}<animate attributeName="{attr}" values="{values}" '
            f'dur="{dur:.3f}s" repeatCount="indefinite"{tail}/>\n')


def animate_tf(kind: str, values, dur: float, indent: int = 6, **kw) -> str:
    """<animateTransform>; `kind` is rotate/translate/scale."""
    kw.setdefault("data_dur", f"{dur:.3f}")
    if isinstance(values, (list, tuple)):
        values = ";".join(values)
    pad = " " * indent
    extra = attrs(**kw)
    tail = f" {extra}" if extra else ""
    return (f'{pad}<animateTransform attributeName="transform" type="{kind}" '
            f'values="{values}" dur="{dur:.3f}s" repeatCount="indefinite"{tail}/>\n')


# ----------------------------------------------------------------------------
# kinematics
# ----------------------------------------------------------------------------
def pedal_point(theta: float) -> tuple[float, float]:
    """Pedal position for crank angle `theta` (radians, +y is down => clockwise)."""
    return (BB[0] + CRANK_R * math.cos(theta),
            BB[1] + CRANK_R * math.sin(theta))


def solve_knee(hip, foot, l1: float, l2: float):
    """Two-bone IK; returns the knee position, picking the knee-forward branch."""
    dx, dy = foot[0] - hip[0], foot[1] - hip[1]
    d = math.hypot(dx, dy)
    d = max(abs(l1 - l2) + 1e-6, min(d, l1 + l2 - 1e-6))
    a = (l1 * l1 - l2 * l2 + d * d) / (2 * d)
    h = math.sqrt(max(l1 * l1 - a * a, 0.0))
    ux, uy = dx / math.hypot(dx, dy), dy / math.hypot(dx, dy)
    mx, my = hip[0] + a * ux, hip[1] + a * uy
    k1 = (mx + h * -uy, my + h * ux)      # one side of the hip->foot line
    k2 = (mx - h * -uy, my - h * ux)      # the other
    return k1 if k1[0] >= k2[0] else k2   # knee points forward (+x)


def unwrap(seq):
    """Keep an angle sequence continuous (no 359->1 jumps)."""
    out = [seq[0]]
    for v in seq[1:]:
        while v - out[-1] > 180:
            v -= 360
        while v - out[-1] < -180:
            v += 360
        out.append(v)
    return out


def leg_frames(phase: float):
    """Pedal track + thigh/shin angles over one full crank revolution."""
    pedals, thigh, shin = [], [], []
    for k in range(KEYFRAMES + 1):                 # +1 => last frame == first
        th = phase + 2 * math.pi * k / KEYFRAMES
        foot = pedal_point(th)
        knee = solve_knee(HIP, foot, THIGH, SHIN)
        pedals.append(foot)
        thigh.append(math.degrees(math.atan2(knee[1] - HIP[1], knee[0] - HIP[0])))
        shin.append(math.degrees(math.atan2(foot[1] - knee[1], foot[0] - knee[0])))

    thigh = unwrap(thigh)
    shin_abs = unwrap(shin)
    shin_rel = unwrap([s - t for s, t in zip(shin_abs, thigh)])

    assert abs(thigh[-1] - thigh[0]) < 1e-6, "thigh angle does not close the loop"
    assert abs(shin_rel[-1] - shin_rel[0]) < 1e-6, "shin angle does not close the loop"
    return pedals, thigh, shin_rel


def leg_svg(hx: float, hy: float, phase: float, dark: str, mid: str, light: str) -> str:
    """A pedalling leg: nested rotate groups driven by the IK solution."""
    pedals, thigh, shin_rel = leg_frames(phase)

    thigh_vals = [f2(a) for a in thigh]
    shin_vals = [f2(a) for a in shin_rel]
    pedal_vals = [f"{f2(x)},{f2(y)}" for x, y in pedals]

    return f"""      <g>
        <!-- pedal + webbed foot ride the crank circle, kept horizontal -->
        <g>
{animate_tf("translate", pedal_vals, CRANK_T, 10)}          <path d="M -15,-5 C -6,-9 8,-10 18,-6 C 23,-4 22,3 15,5 C 5,8 -8,7 -14,3 C -18,0 -19,-3 -15,-5 Z" fill="{light}" stroke="{dark}" stroke-width="2"/>
          <path d="M -4,-6 L -2,5 M 5,-7 L 6,6 M 13,-6 L 13,5" stroke="{dark}" stroke-width="1.6" fill="none" opacity=".55"/>
          <rect x="-14" y="-3" width="28" height="7" rx="3" fill="#2b2d42"/>
        </g>
        <g transform="translate({f2(hx)},{f2(hy)})">
          <g>
{animate_tf("rotate", thigh_vals, CRANK_T, 12)}            <line x1="0" y1="0" x2="{f2(THIGH)}" y2="0" stroke="{dark}" stroke-width="24" stroke-linecap="round"/>
            <line x1="0" y1="0" x2="{f2(THIGH)}" y2="0" stroke="{mid}" stroke-width="19" stroke-linecap="round"/>
            <g transform="translate({f2(THIGH)},0)">
              <g>
{animate_tf("rotate", shin_vals, CRANK_T, 16)}                <line x1="0" y1="0" x2="{f2(SHIN)}" y2="0" stroke="{dark}" stroke-width="17" stroke-linecap="round"/>
                <line x1="0" y1="0" x2="{f2(SHIN)}" y2="0" stroke="{mid}" stroke-width="13" stroke-linecap="round"/>
              </g>
              <circle cx="0" cy="0" r="11" fill="{mid}" stroke="{dark}" stroke-width="3"/>
            </g>
          </g>
        </g>
      </g>
"""


# ----------------------------------------------------------------------------
# scene pieces
# ----------------------------------------------------------------------------
def wheel(cx: float, cy: float) -> str:
    spokes = ""
    for i in range(14):
        a = 2 * math.pi * i / 14
        spokes += (f'          <line x1="0" y1="0" x2="{f2(62 * math.cos(a))}" '
                   f'y2="{f2(62 * math.sin(a))}" stroke="#93a1b0" stroke-width="2.4"/>\n')
    return f"""      <g transform="translate({f2(cx)},{f2(cy)})">
        <circle r="{f2(WHEEL_R)}" fill="none" stroke="#22242f" stroke-width="11"/>
        <circle r="66" fill="none" stroke="#c7d0da" stroke-width="4"/>
        <g>
          <animateTransform attributeName="transform" type="rotate"
            from="0 0 0" to="360 0 0" dur="{WHEEL_T:.3f}s" repeatCount="indefinite"
            data-dur="{WHEEL_T:.3f}"/>
{spokes}          <circle r="74" fill="none" stroke="#15161d" stroke-width="7"
            stroke-dasharray="5 27" opacity=".85"/>
          <circle cx="0" cy="-60" r="3.4" fill="#e63946"/>
        </g>
        <circle r="9" fill="#7d8794"/>
        <circle r="4" fill="#3a3f4b"/>
      </g>
"""


def cloud(x: float, y: float, s: float, dur: float, begin: float) -> str:
    return f"""      <g>
{animate_tf("translate", [f"{x},{y}", f"{x - 1250},{y}"], dur, 8, begin=f"{begin:.2f}s")}        <g transform="scale({s})" fill="#ffffff" opacity=".92">
          <ellipse cx="0" cy="0" rx="46" ry="26"/>
          <ellipse cx="-34" cy="8" rx="30" ry="18"/>
          <ellipse cx="30" cy="9" rx="34" ry="19"/>
          <ellipse cx="4" cy="-18" rx="26" ry="20"/>
        </g>
      </g>
"""


def bird(x: float, y: float, s: float, dur: float, begin: float) -> str:
    flap = ["M 0,0 q 9,-8 18,0 q 9,-8 18,0",
            "M 0,0 q 9,4 18,0 q 9,4 18,0"]
    return f"""      <g>
{animate_tf("translate", [f"{x},{y}", f"{x - 1100},{y - 40}"], dur, 8, begin=f"{begin:.2f}s")}        <g transform="scale({s})">
          <path d="{flap[0]}" fill="none" stroke="#5c6b7a" stroke-width="3.4" stroke-linecap="round">
{animate("d", flap, 0.52, 12, begin=f"{begin:.2f}s")}          </path>
        </g>
      </g>
"""


def dust(cx: float, cy: float, begin: float) -> str:
    return f"""      <g>
        <circle cx="{f2(cx)}" cy="{f2(cy)}" r="5" fill="#ffffff">
{animate("cx", [f"{cx:.0f}", f"{cx - 95:.0f}"], 0.9, 10, begin=f"{begin:.2f}s")}{animate("cy", [f"{cy:.0f}", f"{cy - 26:.0f}"], 0.9, 10, begin=f"{begin:.2f}s")}{animate("r", ["4", "17"], 0.9, 10, begin=f"{begin:.2f}s")}{animate("opacity", ["0.55", "0"], 0.9, 10, begin=f"{begin:.2f}s")}        </circle>
      </g>
"""


# ----------------------------------------------------------------------------
# assemble
# ----------------------------------------------------------------------------
def build_svg() -> str:
    near_leg = leg_svg(HIP[0], HIP[1], 0.0, "#c9702f", "#f0a35e", "#f7bd85")
    far_leg = leg_svg(HIP[0] - 4, HIP[1] - 2, math.pi, "#a9561f", "#d1813f", "#e09a5c")

    # crank arms (both, one rotating group)
    crank = f"""      <g>
{animate_tf("rotate", ["0 450 390", "360 450 390"], CRANK_T, 8)}        <line x1="450" y1="390" x2="480" y2="390" stroke="#3a3f4b" stroke-width="9" stroke-linecap="round"/>
        <line x1="450" y1="390" x2="420" y2="390" stroke="#2b2f39" stroke-width="9" stroke-linecap="round"/>
      </g>
"""

    # chain: top run goes rearward, so the dashes travel backwards along the path
    chain_speed = 2 * math.pi * CHAINRING_R / CRANK_T      # px / s of chain
    chain_dash = 12.0
    chain_t = chain_dash / chain_speed
    chain = f"""      <path d="M 450,364 L 330,373 A {COG_R} {COG_R} 0 0 0 330,397 L 450,416
               A {CHAINRING_R} {CHAINRING_R} 0 0 0 450,364 Z"
        fill="none" stroke="#3a3f4b" stroke-width="5" stroke-dasharray="7 5">
{animate("stroke-dashoffset", ["0", f"{-chain_dash:.1f}"], chain_t, 8)}      </path>
      <circle cx="450" cy="390" r="{CHAINRING_R}" fill="none" stroke="#4a5060" stroke-width="7"/>
      <g>
{animate_tf("rotate", ["0 450 390", "360 450 390"], CRANK_T, 8)}        <circle cx="450" cy="390" r="{CHAINRING_R - 5}" fill="none" stroke="#6b7383" stroke-width="4"
          stroke-dasharray="4 8"/>
        <line x1="450" y1="390" x2="468" y2="390" stroke="#8d97a6" stroke-width="4"/>
      </g>
      <circle cx="330" cy="385" r="{COG_R}" fill="#4a5060" stroke="#2b2f39" stroke-width="2"/>
"""

    frame = """      <g stroke="#e63946" stroke-width="9" stroke-linecap="round" fill="none">
        <line x1="450" y1="390" x2="330" y2="385"/>
        <line x1="398" y1="306" x2="330" y2="385"/>
        <line x1="450" y1="390" x2="398" y2="298"/>
        <line x1="398" y1="304" x2="546" y2="288"/>
        <line x1="450" y1="390" x2="541" y2="326"/>
      </g>
      <g stroke="#2b2d42" stroke-width="9" stroke-linecap="round" fill="none">
        <line x1="549" y1="300" x2="585" y2="385"/>
        <line x1="541" y1="326" x2="553" y2="284"/>
        <line x1="553" y1="284" x2="561" y2="268"/>
      </g>
      <path d="M 362,290 C 370,279 404,275 417,281 C 422,284 412,292 400,293 L 372,294
               C 366,294 360,292 362,290 Z" fill="#22242f"/>
      <path d="M 534,268 C 543,255 561,251 572,258" fill="none" stroke="#22242f"
        stroke-width="8" stroke-linecap="round"/>
      <rect x="566" y="252" width="14" height="11" rx="5" fill="#15161d"/>
"""

    bell = f"""      <g>
{animate_tf("rotate", ["0 546 258", "-8 546 258", "8 546 258", "-5 546 258",
                        "5 546 258", "0 546 258", "0 546 258"], 3.9, 8,
             keyTimes="0;0.02;0.05;0.08;0.11;0.14;1")}        <path d="M 538,258 a 8,8 0 0 1 16,0 Z" fill="#ffd166" stroke="#e0a800" stroke-width="2"/>
        <circle cx="546" cy="259" r="2.4" fill="#e0a800"/>
      </g>
      <path d="M 562,246 q 8,-6 10,-14" fill="none" stroke="#ffffff" stroke-width="3"
        stroke-linecap="round" opacity="0">
{animate("opacity", ["0", "0", "0.9", "0", "0"], 3.9, 8,
         keyTimes="0;0.03;0.08;0.18;1")}      </path>
"""

    # ---- pelican -----------------------------------------------------------
    scarf = ["M 452,214 C 414,196 372,200 330,188 C 306,182 282,186 258,178 C 276,196 300,206 330,206 C 372,214 414,222 452,224 Z",
             "M 452,214 C 414,210 372,190 330,196 C 306,200 282,182 256,190 C 276,200 300,214 330,212 C 372,218 414,224 452,224 Z",
             "M 452,214 C 414,192 372,208 330,194 C 306,186 282,194 254,186 C 274,204 300,210 330,210 C 372,216 414,222 452,224 Z"]

    pelican = f"""    <g id="pelican">
{animate_tf("translate", ["0,0", "0,-3", "0,0"], BOB_T, 6)}
      <!-- far wing, tucked behind the body -->
      <path d="M 432,244 C 474,238 516,252 546,270 C 522,278 470,272 436,264 Z"
        fill="#d3dde7" stroke="#b6c3d0" stroke-width="2"/>

      <!-- body -->
      <path d="M 320,224 C 322,196 356,182 398,188 C 442,194 470,222 470,254
               C 470,288 434,308 390,306 C 348,304 318,282 318,250 C 318,240 318,232 320,224 Z"
        fill="#fdfefe" stroke="#c9d5e0" stroke-width="3"/>
      <path d="M 356,290 C 392,304 434,298 458,276 C 452,300 424,310 390,308
               C 372,307 360,300 356,290 Z" fill="#e9eff5"/>
      <!-- tail feathers -->
      <path d="M 326,226 L 262,194 L 290,220 L 244,206 L 284,234 L 248,232 L 294,254 L 322,256 Z"
        fill="#f2f6fa" stroke="#c9d5e0" stroke-width="2.5"/>

      <!-- neck -->
      <path d="M 450,216 C 468,182 494,160 524,152" fill="none" stroke="#c9d5e0"
        stroke-width="38" stroke-linecap="round"/>
      <path d="M 450,216 C 468,182 494,160 524,152" fill="none" stroke="#fdfefe"
        stroke-width="33" stroke-linecap="round"/>

      <!-- head -->
      <g>
{animate_tf("translate", ["0,0", "0,2.5", "0,0"], BOB_T, 8)}        <circle cx="532" cy="146" r="27" fill="#fdfefe" stroke="#c9d5e0" stroke-width="3"/>
        <path d="M 514,126 C 504,113 493,111 485,116 C 496,120 503,128 509,137 Z" fill="#f2f6fa" stroke="#c9d5e0" stroke-width="2"/>
        <path d="M 524,120 C 518,105 509,99 500,101 C 509,109 513,120 517,131 Z" fill="#f2f6fa" stroke="#c9d5e0" stroke-width="2"/>

        <!-- upper mandible -->
        <path d="M 550,133 L 664,145 C 673,147 674,153 665,156 L 550,163 Z"
          fill="#ffb703" stroke="#e08a00" stroke-width="2.5"/>
        <path d="M 556,140 L 650,150" stroke="#e08a00" stroke-width="1.6" opacity=".5"/>
        <!-- gular pouch, with today's catch -->
        <g>
{animate_tf("rotate", ["0 552 160", "2.4 552 160", "0 552 160", "-1.6 552 160", "0 552 160"], BOB_T, 10)}          <path d="M 552,161 L 664,154 C 656,188 626,210 596,210 C 566,210 554,187 552,161 Z"
            fill="#ffd07a" stroke="#e08a00" stroke-width="2.5"/>
          <g opacity=".38">
{animate_tf("rotate", ["0 596 190", "5 596 190", "0 596 190", "-5 596 190", "0 596 190"], 1.4, 12)}            <path d="M 576,190 C 586,177 610,177 620,190 C 610,203 586,203 576,190 Z" fill="#7a4a12"/>
            <path d="M 620,190 L 636,179 L 633,190 L 636,201 Z" fill="#7a4a12"/>
            <circle cx="586" cy="186" r="2.6" fill="#ffd07a"/>
          </g>
        </g>

        <!-- eye + blink -->
        <ellipse cx="540" cy="138" rx="9" ry="10" fill="#ffffff" stroke="#c9d5e0" stroke-width="1.5"/>
        <circle cx="543" cy="139" r="5" fill="#1d3557"/>
        <circle cx="541" cy="136" r="1.9" fill="#ffffff"/>
        <g transform="translate(540,127)">
          <g>
{animate_tf("scale", ["1 0", "1 0", "1 1", "1 0", "1 0"], 4.2, 12,
             keyTimes="0;0.90;0.945;0.99;1")}            <ellipse cx="0" cy="11" rx="10.5" ry="11.5" fill="#eef3f8"/>
          </g>
        </g>
      </g>

      <!-- scarf -->
      <path d="{scarf[0]}" fill="#ef476f" stroke="#c9304f" stroke-width="2">
{animate("d", scarf, 1.3, 8)}      </path>
      <path d="M 446,204 C 456,198 468,203 470,212 C 472,221 462,228 451,226 C 444,224 441,209 446,204 Z"
        fill="#ef476f" stroke="#c9304f" stroke-width="2"/>

      <!-- near wing, gripping the handlebar -->
      <g>
{animate_tf("rotate", ["0 436 238", "1.8 436 238", "0 436 238", "-1.2 436 238", "0 436 238"],
             BOB_T, 8)}        <path d="M 428,224 C 470,207 522,224 554,252 C 562,260 558,273 547,271
                 C 520,265 476,253 440,258 C 428,258 420,232 428,224 Z"
          fill="#f7fafc" stroke="#c9d5e0" stroke-width="3"/>
        <path d="M 468,222 C 478,234 486,246 489,255 M 496,231 C 504,242 512,252 516,260
                 M 522,242 C 528,250 534,257 539,263" fill="none" stroke="#c9d5e0" stroke-width="2.4"/>
        <path d="M 549,252 C 561,250 570,256 570,262 C 570,269 558,272 550,268 Z"
          fill="#ffb703" stroke="#e08a00" stroke-width="2"/>
      </g>
    </g>
"""

    # ---- static + background ----------------------------------------------
    head = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}"
     width="{W}" height="{H}" role="img" aria-labelledby="ttl dsc">
  <title id="ttl">鹈鹕骑自行车 · A pelican riding a bicycle</title>
  <desc id="dsc">A white pelican with a big orange beak pedals a red bicycle along a
  road; the wheels spin, the chain runs, clouds drift and its scarf flaps.</desc>

  <defs>
    <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#7ecbf0"/>
      <stop offset=".55" stop-color="#c6eafb"/>
      <stop offset="1" stop-color="#f3fcff"/>
    </linearGradient>
    <linearGradient id="road" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#666c7d"/>
      <stop offset="1" stop-color="#4c5162"/>
    </linearGradient>
    <radialGradient id="sunglow">
      <stop offset="0" stop-color="#ffe9a8" stop-opacity=".95"/>
      <stop offset="1" stop-color="#ffe9a8" stop-opacity="0"/>
    </radialGradient>
  </defs>

  <rect width="{W}" height="{H}" fill="url(#sky)"/>

  <!-- sun -->
  <g id="background">
    <circle cx="770" cy="104" r="78" fill="url(#sunglow)"/>
    <g>
      <animateTransform attributeName="transform" type="rotate"
        from="0 770 104" to="360 770 104" dur="60s" repeatCount="indefinite" data-dur="60.000"/>
      <g stroke="#ffd166" stroke-width="7" stroke-linecap="round" opacity=".85">
        <line x1="770" y1="24" x2="770" y2="6"/>
        <line x1="770" y1="184" x2="770" y2="202"/>
        <line x1="690" y1="104" x2="672" y2="104"/>
        <line x1="850" y1="104" x2="868" y2="104"/>
        <line x1="713" y1="47" x2="700" y2="34"/>
        <line x1="827" y1="161" x2="840" y2="174"/>
        <line x1="827" y1="47" x2="840" y2="34"/>
        <line x1="713" y1="161" x2="700" y2="174"/>
      </g>
    </g>
    <circle cx="770" cy="104" r="44" fill="#ffd166"/>
    <circle cx="758" cy="94" r="14" fill="#ffe08a" opacity=".8"/>

{cloud(960, 96, 1.15, 26.0, 0.0)}{cloud(1180, 168, 0.8, 34.0, -9.0)}{cloud(1400, 60, 0.62, 44.0, -21.0)}{bird(980, 150, 1.0, 19.0, 0.0)}{bird(1120, 208, 0.7, 25.0, -7.0)}
    <!-- hills -->
    <path d="M 0,432 C 120,382 220,404 330,424 C 420,440 520,394 640,412
             C 740,426 830,402 900,416 L 900,470 L 0,470 Z" fill="#a9d9a3"/>
    <path d="M 0,452 C 140,424 260,450 380,447 C 520,443 640,420 760,440
             C 820,450 870,447 900,445 L 900,470 L 0,470 Z" fill="#8cc98a"/>
    <g stroke="#6fb36d" stroke-width="3" stroke-linecap="round">
      <line x1="120" y1="447" x2="120" y2="431"/><line x1="130" y1="448" x2="130" y2="436"/>
      <line x1="690" y1="444" x2="690" y2="429"/><line x1="700" y1="445" x2="700" y2="434"/>
    </g>
  </g>

  <!-- road -->
  <rect x="0" y="{GROUND}" width="{W}" height="{H - GROUND}" fill="url(#road)"/>
  <rect x="0" y="{GROUND}" width="{W}" height="6" fill="#7d8496"/>
  <line x1="-260" y1="540" x2="1160" y2="540" stroke="#f6f1e0" stroke-width="10"
    stroke-dasharray="105 140" stroke-linecap="round">
{animate("stroke-dashoffset", ["0", "245"], ROLL_T, 4)}  </line>
  <ellipse cx="455" cy="470" rx="215" ry="13" fill="#1b1d26" opacity=".22"/>

  <!-- speed lines -->
  <g stroke="#ffffff" stroke-width="5" stroke-linecap="round" opacity=".5">
    <line x1="60" y1="230" x2="240" y2="230" stroke-dasharray="70 260">
{animate("stroke-dashoffset", ["330", "0"], 1.1, 6)}    </line>
    <line x1="20" y1="286" x2="230" y2="286" stroke-dasharray="90 300">
{animate("stroke-dashoffset", ["390", "0"], 1.1, 6, begin="-0.35s")}    </line>
    <line x1="80" y1="342" x2="250" y2="342" stroke-dasharray="60 240">
{animate("stroke-dashoffset", ["300", "0"], 1.1, 6, begin="-0.7s")}    </line>
  </g>

  <!-- dust kicked up behind the rear wheel -->
{dust(318, 456, 0.0)}{dust(322, 462, -0.3)}{dust(314, 452, -0.6)}
"""

    body = f"""  <!-- ============ the rig ============ -->
  <g id="rig">
    <!-- far leg (behind the frame) -->
{far_leg}
    <!-- wheels -->
{wheel(*REAR_HUB)}{wheel(*FRONT_HUB)}    <!-- frame -->
{frame}{bell}{chain}{crank}
    <!-- near pedal + foot, then the near leg on top -->
{near_leg}
    <!-- the bird -->
{pelican}  </g>
</svg>
"""
    return head + body


PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>鹈鹕骑自行车 · Pelican on a Bicycle</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; padding: 32px 20px 48px;
    font-family: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", system-ui, sans-serif;
    background: radial-gradient(1200px 600px at 50% -10%, #24405c, #0e1621 60%);
    color: #e8eef5; display: flex; flex-direction: column; align-items: center; gap: 20px;
  }
  h1 { font-size: clamp(22px, 4vw, 34px); margin: 0; letter-spacing: .04em; font-weight: 650; }
  h1 span { color: #7fd3ff; }
  p.sub { margin: 0; color: #9db0c4; font-size: 14px; }
  .card {
    width: min(960px, 100%); border-radius: 20px; overflow: hidden;
    background: #0b121b; border: 1px solid #23344a;
    box-shadow: 0 30px 70px rgba(0,0,0,.45);
  }
  .card svg { display: block; width: 100%; height: auto; }
  .bar {
    display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px;
    padding: 14px 18px; background: #101a26; border-top: 1px solid #23344a;
  }
  button, label {
    font: inherit; font-size: 14px; color: #e8eef5; background: #1b2a3b;
    border: 1px solid #2f4763; border-radius: 10px; padding: 8px 14px; cursor: pointer;
  }
  button:hover { background: #24394f; }
  button[aria-pressed="true"] { background: #2b6cb0; border-color: #4a90d9; }
  label { display: inline-flex; align-items: center; gap: 8px; cursor: default; }
  input[type=range] { accent-color: #7fd3ff; }
  .hint { font-size: 13px; color: #8296ab; }
  footer { font-size: 13px; color: #7b8ea3; text-align: center; line-height: 1.7; max-width: 720px; }
  code { background: #16232f; padding: 1px 6px; border-radius: 6px; color: #9fd6ff; }
</style>
</head>
<body>
  <h1>鹈鹕骑自行车 <span>· Pelican on a Bicycle</span></h1>
  <p class="sub">纯 SVG + SMIL 动画，不依赖 JavaScript / 图片 / 外部资源</p>

  <div class="card">
__SVG__
    <div class="bar">
      <button id="toggle" aria-pressed="false">⏸ 暂停</button>
      <button id="restart">↺ 重播</button>
      <button id="bg" aria-pressed="false">隐藏背景</button>
      <label>速度 <input id="speed" type="range" min="0.25" max="3" step="0.25" value="1">
        <span id="speedv" class="hint">1.00×</span></label>
      <a class="hint" href="pelican-bicycle.svg" download>⬇ 下载 .svg</a>
    </div>
  </div>

  <footer>
    踏板沿曲柄圆运动，双腿用两骨反向运动学（IK）逐帧求解，所以脚始终踩在踏板上。<br>
    文件 <code>pelican-bicycle.svg</code> 可以单独打开，也能直接放进
    <code>&lt;img&gt;</code> 或 Figma / Sketch 里使用。
  </footer>

<script>
  const svg = document.querySelector('.card svg');
  const toggle = document.getElementById('toggle');
  let paused = false;

  toggle.onclick = () => {
    paused = !paused;
    paused ? svg.pauseAnimations() : svg.unpauseAnimations();
    toggle.textContent = paused ? '▶ 播放' : '⏸ 暂停';
    toggle.setAttribute('aria-pressed', String(paused));
  };

  document.getElementById('restart').onclick = () => {
    svg.setCurrentTime(0);
    if (paused) toggle.onclick();
  };

  document.getElementById('bg').onclick = (e) => {
    const g = svg.querySelector('#background');
    const off = g.style.display === 'none';
    g.style.display = off ? '' : 'none';
    e.currentTarget.setAttribute('aria-pressed', String(!off));
  };

  // scale every animation's duration; each element carries its base dur in data-dur
  const speed = document.getElementById('speed');
  const speedv = document.getElementById('speedv');
  const anims = [...svg.querySelectorAll('[data-dur]')].map(el => [el, +el.dataset.dur]);
  speed.oninput = () => {
    const k = +speed.value;
    speedv.textContent = k.toFixed(2) + '×';
    for (const [el, base] of anims) el.setAttribute('dur', (base / k).toFixed(4) + 's');
  };
</script>
</body>
</html>
"""


def main() -> None:
    root = pathlib.Path(__file__).resolve().parent
    svg = build_svg()
    (root / "pelican-bicycle.svg").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n' + svg, encoding="utf-8")

    indented = "\n".join("    " + ln if ln else ln for ln in svg.splitlines())
    (root / "index.html").write_text(PAGE.replace("__SVG__", indented), encoding="utf-8")

    print(f"wrote pelican-bicycle.svg ({len(svg)} bytes) and index.html")


if __name__ == "__main__":
    main()
