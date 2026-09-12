#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate `pelican-bicycle.svg` — a self-contained animated SVG of a pelican
riding a bicycle (pure SMIL animation, no CSS/JS required).

The pedalling legs are generated with 2-bone inverse kinematics: for 16 crank
angles we solve for the knee position between the (bobbing) hip and the pedal
position on the crank circle, then bake the results into <animate> `d`
keyframes for the thigh+shin paths.

Run:  python3 generate_pelican.py
"""
import math

# ---------------------------------------------------------------- timing ----
CADENCE = 1.2        # s per crank revolution
WHEEL_T = 1.536      # s per wheel revolution (matches 360 px/s road scroll)
N = 16               # leg keyframes per crank revolution
BOB = -3.0           # body bob amplitude (px); 2 bobs per crank revolution

# ---------------------------------------------------------------- geometry ---
CX, CY = 398.0, 490.0     # crank centre
R_PED = 34.0              # crank length (pedal circle radius)
NEAR = dict(hip=(398.0, 302.0), l1=120.0, l2=112.0)
FAR = dict(hip=(392.0, 310.0), l1=116.0, l2=104.0)
RW, FW = (250.0, 470.0), (612.0, 470.0)   # wheel centres


def ikin(H, F, l1, l2):
    """2-bone IK: knee between hip H and foot F, bending forward (+x)."""
    dx, dy = F[0] - H[0], F[1] - H[1]
    d = math.hypot(dx, dy)
    d = max(d, abs(l1 - l2) + 1e-6)
    d = min(d, l1 + l2 - 1e-6)
    a = (l1 * l1 - l2 * l2 + d * d) / (2.0 * d)
    h = math.sqrt(max(l1 * l1 - a * a, 0.0))
    ux, uy = dx / d, dy / d
    bx, by = H[0] + a * ux, H[1] + a * uy
    k1 = (bx - h * uy, by + h * ux)
    k2 = (bx + h * uy, by - h * ux)
    return k1 if k1[0] > k2[0] else k2     # knee points forward


def bob(t):
    """Triangle wave, 2 periods per crank revolution (matches body bob)."""
    p = (t % 0.6) / 0.6
    return BOB * (1.0 - abs(2.0 * p - 1.0))


def leg_anim(leg, phase_deg):
    """Bake `d` keyframes for one leg; phase_deg offsets the crank angle."""
    vals, prev = [], None
    for k in range(N + 1):
        t = CADENCE * k / N
        th = math.radians(phase_deg + 360.0 * k / N)
        F = (CX + R_PED * math.cos(th), CY + R_PED * math.sin(th))
        H = (leg["hip"][0], leg["hip"][1] + bob(t))
        K = ikin(H, F, leg["l1"], leg["l2"])
        if prev and math.dist(K, prev) > 45:
            print("WARN: knee jump at frame", k)
        prev = K
        vals.append("M %.1f %.1f L %.1f %.1f L %.1f %.1f"
                    % (H[0], H[1], K[0], K[1], F[0], F[1]))
    keytimes = ";".join("%.4f" % (k / N) for k in range(N + 1))
    return vals[0], ";\n        ".join(vals), keytimes


def leg_block(leg, phase_deg, stroke_fill, w_out, w_in):
    d0, values, kt = leg_anim(leg, phase_deg)
    return f'''
    <!-- {"near" if phase_deg == 0 else "far"} leg: outline + fill, IK keyframes -->
    <path d="{d0}" fill="none" stroke="#3a382f" stroke-width="{w_out}"
          stroke-linecap="round" stroke-linejoin="round">
      <animate attributeName="d" values="{values}" keyTimes="{kt}"
               dur="{CADENCE}s" repeatCount="indefinite"/>
    </path>
    <path d="{d0}" fill="none" stroke="{stroke_fill}" stroke-width="{w_in}"
          stroke-linecap="round" stroke-linejoin="round">
      <animate attributeName="d" values="{values}" keyTimes="{kt}"
               dur="{CADENCE}s" repeatCount="indefinite"/>
    </path>'''


def wheel(cx, cy, sprocket=False):
    spokes = []
    for a in (0, 45, 90, 135):
        r = math.radians(a)
        x1, y1 = cx + 66 * math.cos(r), cy + 66 * math.sin(r)
        x2, y2 = cx - 66 * math.cos(r), cy - 66 * math.sin(r)
        spokes.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>')
    gear = ""
    if sprocket:
        teeth = []
        for i in range(8):
            r = math.radians(i * 45)
            teeth.append(f'<line x1="{cx+13*math.cos(r):.1f}" y1="{cy+13*math.sin(r):.1f}" '
                         f'x2="{cx+17*math.cos(r):.1f}" y2="{cy+17*math.sin(r):.1f}"/>')
        gear = (f'<g stroke="#33363c" stroke-width="3">'
                f'<circle cx="{cx}" cy="{cy}" r="13" fill="#565b63" stroke-width="2.5"/>'
                + "".join(teeth) + '</g>')
    return f'''
    <!-- wheel -->
    <circle cx="{cx}" cy="{cy}" r="82" fill="none" stroke="#33333a" stroke-width="13"/>
    <circle cx="{cx}" cy="{cy}" r="70" fill="none" stroke="#cfd3da" stroke-width="5"/>
    <g>
      <animateTransform attributeName="transform" type="rotate"
                        from="0 {cx} {cy}" to="360 {cx} {cy}"
                        dur="{WHEEL_T}s" repeatCount="indefinite"/>
      <g stroke="#b9bec7" stroke-width="4">{''.join(spokes)}</g>
      <circle cx="{cx}" cy="{cy}" r="9" fill="#565b63" stroke="#3a3d44" stroke-width="3"/>
      {gear}
    </g>'''


def speed_line(x1, x2, y, begin):
    return f'''
    <g opacity="0">
      <line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}"/>
      <animateTransform attributeName="transform" type="translate"
                        values="70 0;-160 0" dur="0.7s" begin="{begin}s"
                        repeatCount="indefinite"/>
      <animate attributeName="opacity" values="0;0.75;0" keyTimes="0;0.25;1"
               dur="0.7s" begin="{begin}s" repeatCount="indefinite"/>
    </g>'''


def dust(cx, cy, begin):
    return f'''
    <g>
      <circle cx="{cx}" cy="{cy}" r="5" fill="#cfc8ba" opacity="0.55">
        <animate attributeName="r" values="4;16" dur="0.8s" begin="{begin}s"
                 repeatCount="indefinite"/>
        <animate attributeName="opacity" values="0.55;0" dur="0.8s" begin="{begin}s"
                 repeatCount="indefinite"/>
      </circle>
      <animateTransform attributeName="transform" type="translate"
                        values="0 0;-64 -14" dur="0.8s" begin="{begin}s"
                        repeatCount="indefinite"/>
    </g>'''


def bush(x, y, s):
    return (f'<g transform="translate({x},{y}) scale({s})" fill="#5da84e">'
            f'<circle cx="-14" cy="4" r="11"/><circle cx="14" cy="4" r="11"/>'
            f'<circle cx="0" cy="-4" r="15"/></g>')


def flower(x, y, c):
    return f'<circle cx="{x}" cy="{y}" r="3.5" fill="{c}"/>'


def tuft(x, y):
    return (f'<path d="M {x} {y} q 3 -10 6 0 q 3 -10 6 0" fill="none" '
            f'stroke="#6db057" stroke-width="3" stroke-linecap="round"/>')


def cloud(x, y, s):
    return (f'<g transform="translate({x},{y}) scale({s})" fill="#ffffff" opacity="0.92">'
            f'<ellipse cx="0" cy="0" rx="36" ry="20"/><ellipse cx="30" cy="6" rx="28" ry="15"/>'
            f'<ellipse cx="-30" cy="8" rx="26" ry="14"/><ellipse cx="2" cy="-11" rx="24" ry="13"/></g>')


FOOT = ("M -12 -11 Q -16 -2 -8 1 L 12 1 Q 24 -2 22 -6 "
        "Q 8 -14 -12 -11 Z")
# Local crank circles: the near foot starts at the 3-o'clock pedal (global
# 432,490), the far foot at 9-o'clock (364,490); each traces the circle whose
# centre is the crank axis in its own local coordinates.
PEDAL_CIRCLE_NEAR = "M 0 0 A 34 34 0 1 1 -68 0 A 34 34 0 1 1 0 0"
PEDAL_CIRCLE_FAR = "M 0 0 A 34 34 0 1 1 68 0 A 34 34 0 1 1 0 0"


def foot(group_translate, circle, foot_fill, toe_stroke, pedal_fill, pedal_stroke):
    return f'''
    <!-- foot + pedal ride the crank circle (phase via base transform) -->
    <g transform="{group_translate}">
      <animateMotion dur="{CADENCE}s" repeatCount="indefinite"
                     path="{circle}"/>
      <rect x="-15" y="1" width="30" height="7" rx="3.5"
            fill="{pedal_fill}" stroke="{pedal_stroke}" stroke-width="2"/>
      <path d="{FOOT}" fill="{foot_fill}" stroke="#3a382f" stroke-width="4"
            stroke-linejoin="round"/>
      <path d="M 6 -8 L 9 1 M 13 -7 L 15 1" fill="none"
            stroke="{toe_stroke}" stroke-width="2.5" stroke-linecap="round"/>
    </g>'''


# --------------------------------------------------------------- assemble ---
def main():
    S = []
    S.append('''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 600"
     width="960" height="600" role="img" aria-label="鹈鹕骑自行车">
  <title>鹈鹕骑自行车 · Pelican Riding a Bicycle</title>
  <desc>一只戴帽子和围巾的卡通鹈鹕骑着红色自行车，车轮转动、双腿蹬踏板，
  道路与风景向后滚动。</desc>
  <defs>
    <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#b9e6fb"/>
      <stop offset="1" stop-color="#eef9ff"/>
    </linearGradient>
  </defs>

  <!-- ======================= backdrop ======================= -->
  <rect x="0" y="0" width="960" height="600" fill="url(#sky)"/>

  <!-- sun -->
  <g transform="translate(818,100)">
    <g stroke="#ffd75e" stroke-width="6" stroke-linecap="round">
      <animateTransform attributeName="transform" type="rotate"
                        from="0" to="360" dur="60s" repeatCount="indefinite"/>
''' + "".join(f'      <line x1="48" y1="0" x2="62" y2="0" transform="rotate({a})"/>\n'
              for a in range(0, 360, 30)) + '''    </g>
    <circle r="38" fill="#ffd75e" stroke="#f2b13c" stroke-width="5"/>
  </g>

  <!-- clouds (looping parallax band) -->
  <g>
    <animateTransform attributeName="transform" type="translate"
                      values="0 0;-960 0" dur="70s" repeatCount="indefinite"/>''' +
 "".join(cloud(x, y, s) for x, y, s in
         [(170, 105, 1.0), (540, 62, 0.78), (880, 150, 0.55)]) +
 "".join(cloud(x + 960, y, s) for x, y, s in
         [(170, 105, 1.0), (540, 62, 0.78), (880, 150, 0.55)]) + '''
  </g>

  <!-- hills (looping parallax band) -->
  <g>
    <animateTransform attributeName="transform" type="translate"
                      values="0 0;-960 0" dur="55s" repeatCount="indefinite"/>
    <path d="M 0 445 Q 120 383 240 445 Q 360 393 480 445 Q 600 381 720 445
             Q 840 397 960 445 L 960 470 L 0 470 Z" fill="#bfe3a0"/>
    <path d="M 0 445 Q 160 413 320 445 Q 480 405 640 445 Q 800 415 960 445
             L 960 470 L 0 470 Z" fill="#a5d788"/>
    <g transform="translate(960,0)">
      <path d="M 0 445 Q 120 383 240 445 Q 360 393 480 445 Q 600 381 720 445
               Q 840 397 960 445 L 960 470 L 0 470 Z" fill="#bfe3a0"/>
      <path d="M 0 445 Q 160 413 320 445 Q 480 405 640 445 Q 800 415 960 445
               L 960 470 L 0 470 Z" fill="#a5d788"/>
    </g>
  </g>

  <!-- grass + roadside greenery (faster parallax) -->
  <rect x="0" y="445" width="960" height="107" fill="#8ecf6a"/>
  <g>
    <animateTransform attributeName="transform" type="translate"
                      values="0 0;-960 0" dur="6s" repeatCount="indefinite"/>''' +
 "".join([bush(110, 536, 1.1), bush(430, 530, 0.8), bush(760, 538, 1.25),
          flower(230, 548, "#f2789f"), flower(330, 542, "#f7d154"),
          flower(600, 547, "#f2789f"), flower(860, 543, "#f7d154"),
          tuft(180, 550), tuft(520, 545), tuft(680, 551), tuft(90, 549)]) +
 "".join([bush(1070, 536, 1.1), bush(1390, 530, 0.8), bush(1720, 538, 1.25),
          flower(1190, 548, "#f2789f"), flower(1290, 542, "#f7d154"),
          flower(1560, 547, "#f2789f"), flower(1820, 543, "#f7d154"),
          tuft(1140, 550), tuft(1480, 545), tuft(1640, 551), tuft(1050, 549)]) + '''
  </g>

  <!-- road with scrolling dashes -->
  <rect x="0" y="552" width="960" height="48" fill="#454b57"/>
  <rect x="0" y="552" width="960" height="4" fill="#565d6b"/>
  <line x1="-100" y1="578" x2="1060" y2="578" stroke="#f4f0e6" stroke-width="6"
        stroke-dasharray="46 34">
    <animate attributeName="stroke-dashoffset" from="0" to="2880"
             dur="8s" repeatCount="indefinite"/>
  </line>

  <!-- contact shadows -->
  <ellipse cx="250" cy="559" rx="62" ry="7" fill="#2c3038" opacity="0.35"/>
  <ellipse cx="612" cy="559" rx="62" ry="7" fill="#2c3038" opacity="0.35"/>
''')

    # ---------------- speed lines + dust ----------------
    S.append('''  <!-- motion streaks + dust -->
  <g stroke="#ffffff" stroke-width="6" stroke-linecap="round" fill="none">''' +
 speed_line(150, 252, 252, 0) +
 speed_line(120, 210, 310, -0.23) +
 speed_line(160, 258, 364, -0.46) + '''
  </g>''' + dust(196, 549, 0) + dust(206, 552, -0.4))

    # ---------------- far side of the bike ----------------
    S.append(leg_block(FAR, 180, "#e9e2d0", 27, 18))
    S.append(foot("translate(364,490)", PEDAL_CIRCLE_FAR, "#d68f1a", "#b07612", "#3a3a3e", "#26272b"))

    # ---------------- wheels ----------------
    S.append(wheel(*RW, sprocket=True))
    S.append(wheel(*FW))

    # ---------------- frame ----------------
    S.append('''
  <!-- frame -->
  <g stroke="#e0523d" stroke-linecap="round" fill="none">
    <line x1="330" y1="336" x2="398" y2="490" stroke-width="11"/>   <!-- seat tube -->
    <line x1="334" y1="352" x2="590" y2="334" stroke-width="10"/>   <!-- top tube -->
    <line x1="398" y1="490" x2="596" y2="368" stroke-width="11"/>   <!-- down tube -->
    <line x1="334" y1="346" x2="252" y2="468" stroke-width="8"/>    <!-- seat stay -->
    <line x1="398" y1="490" x2="252" y2="468" stroke-width="8"/>    <!-- chain stay -->
    <path d="M 597 372 Q 602 425 612 470" stroke="#cf4534" stroke-width="9"/> <!-- fork -->
    <line x1="585" y1="324" x2="597" y2="372" stroke="#cf4534" stroke-width="12"/> <!-- head tube -->
    <circle cx="333" cy="349" r="6.5" fill="#cf4534" stroke="none"/>
    <circle cx="596" cy="370" r="6.5" fill="#cf4534" stroke="none"/>
    <circle cx="252" cy="468" r="6" fill="#cf4534" stroke="none"/>
  </g>
  <!-- stem, handlebar, grip -->
  <line x1="585" y1="324" x2="575" y2="306" stroke="#46464a" stroke-width="7" stroke-linecap="round"/>
  <path d="M 575 306 C 567 295 551 296 544 310" fill="none" stroke="#46464a"
        stroke-width="7" stroke-linecap="round"/>
  <circle cx="543" cy="311" r="6" fill="#33312c"/>
  <!-- saddle -->
  <path d="M 294 329 Q 322 312 360 322 Q 347 345 312 343 Q 298 338 294 329 Z"
        fill="#7a4a2f" stroke="#3a382f" stroke-width="4"/>

  <!-- chain (dashes crawl in opposite directions) -->
  <path d="M 250 457 L 398 464" stroke="#4c4f56" stroke-width="5" fill="none"
        stroke-dasharray="6 4">
    <animate attributeName="stroke-dashoffset" from="1360" to="0"
             dur="10s" repeatCount="indefinite"/>
  </path>
  <path d="M 250 483 L 398 516" stroke="#4c4f56" stroke-width="5" fill="none"
        stroke-dasharray="6 4">
    <animate attributeName="stroke-dashoffset" from="0" to="1360"
             dur="10s" repeatCount="indefinite"/>
  </path>

  <!-- crank + chainring -->
  <g>
    <animateTransform attributeName="transform" type="rotate"
                      from="0 398 490" to="360 398 490"
                      dur="''' + str(CADENCE) + '''s" repeatCount="indefinite"/>
    <circle cx="398" cy="490" r="26" fill="#565b63" stroke="#33363c" stroke-width="3"/>''' +
 "".join(f'<circle cx="{398+14.5*math.cos(math.radians(a)):.1f}" '
         f'cy="{490+14.5*math.sin(math.radians(a)):.1f}" r="5.5" fill="#3d4046"/>'
         for a in (0, 120, 240)) + '''
    <line x1="398" y1="490" x2="432" y2="490" stroke="#3f4147" stroke-width="11" stroke-linecap="round"/>
    <line x1="398" y1="490" x2="364" y2="490" stroke="#3f4147" stroke-width="11" stroke-linecap="round"/>
    <circle cx="398" cy="490" r="7" fill="#2f3033"/>
  </g>
''')

    # ---------------- pelican (bobbing body group) ----------------
    S.append('''
  <!-- ======================= pelican ======================= -->
  <g>
    <animateTransform attributeName="transform" type="translate"
                      values="0 0;0 -3;0 0;0 -3;0 0" keyTimes="0;0.25;0.5;0.75;1"
                      dur="''' + str(CADENCE) + '''s" repeatCount="indefinite"/>
    <!-- tail feathers -->
    <path d="M 296 214 L 250 196 L 272 226 L 236 232 L 270 248 L 248 274 L 298 258 Z"
          fill="#f3edde" stroke="#3a382f" stroke-width="5" stroke-linejoin="round"/>
    <!-- body -->
    <ellipse cx="372" cy="246" rx="104" ry="80" fill="#fdfaf1"
             stroke="#3a382f" stroke-width="5.5"/>
    <!-- folded wing reaching the handlebar -->
    <g>
      <animateTransform attributeName="transform" type="rotate"
                        values="0 404 214;2 404 214;0 404 214;-1.2 404 214;0 404 214"
                        keyTimes="0;0.25;0.5;0.75;1" dur="''' + str(CADENCE) + '''s"
                        repeatCount="indefinite"/>
      <path d="M 398 202 C 452 204 512 240 552 308 C 557 318 552 326 541 322
               C 498 306 448 288 414 258 C 396 240 390 218 398 202 Z"
            fill="#f3edde" stroke="#3a382f" stroke-width="5" stroke-linejoin="round"/>
      <path d="M 552 317 L 505 297 M 544 309 L 500 289 M 535 300 L 497 282"
            fill="none" stroke="#d9d1bd" stroke-width="3.5" stroke-linecap="round"/>
    </g>
    <!-- neck (outline pass + fill pass) -->
    <path d="M 420 205 C 468 196 494 168 502 132" fill="none"
          stroke="#3a382f" stroke-width="58" stroke-linecap="round"/>
    <path d="M 420 205 C 468 196 494 168 502 132" fill="none"
          stroke="#fdfaf1" stroke-width="47" stroke-linecap="round"/>
    <!-- scarf tails fluttering -->
    <path fill="#e04f3f" stroke="#3a382f" stroke-width="4" stroke-linejoin="round"
          d="M 436 186 C 410 174 384 180 356 164 C 370 184 402 196 434 200 Z">
      <animate attributeName="d" dur="0.9s" repeatCount="indefinite" values="
        M 436 186 C 410 174 384 180 356 164 C 370 184 402 196 434 200 Z;
        M 436 186 C 408 180 384 168 354 176 C 376 190 404 198 434 200 Z;
        M 436 186 C 412 170 388 190 362 184 C 382 192 406 198 434 200 Z;
        M 436 186 C 410 174 384 180 356 164 C 370 184 402 196 434 200 Z"/>
    </path>
    <path fill="#c73f31" stroke="#3a382f" stroke-width="4" stroke-linejoin="round"
          d="M 440 197 C 418 193 398 202 376 193 C 394 208 416 209 438 208 Z">
      <animate attributeName="d" dur="0.9s" begin="-0.3s" repeatCount="indefinite" values="
        M 440 197 C 418 193 398 202 376 193 C 394 208 416 209 438 208 Z;
        M 440 197 C 416 201 394 190 374 199 C 396 209 418 206 438 208 Z;
        M 440 197 C 420 189 396 207 378 201 C 398 211 418 206 438 208 Z;
        M 440 197 C 418 193 398 202 376 193 C 394 208 416 209 438 208 Z"/>
    </path>
    <path d="M 428 190 L 466 176 L 472 194 L 434 208 Z"
          fill="#e04f3f" stroke="#3a382f" stroke-width="4" stroke-linejoin="round"/>
    <!-- head (gentle nod) -->
    <g>
      <animateTransform attributeName="transform" type="rotate"
                        values="0 500 140;2.5 500 140;-1.5 500 140;0 500 140"
                        keyTimes="0;0.35;0.7;1" dur="''' + str(CADENCE) + '''s"
                        repeatCount="indefinite"/>
      <path d="M 486 94 Q 464 76 455 86 Q 471 99 483 108 Z"
            fill="#f3edde" stroke="#3a382f" stroke-width="4.5" stroke-linejoin="round"/>
      <circle cx="508" cy="116" r="31" fill="#fdfaf1" stroke="#3a382f" stroke-width="5.5"/>
      <ellipse cx="498" cy="131" rx="7" ry="4.5" fill="#f4a7a0" opacity="0.55"/>
      <path d="M 528 133 C 536 176 570 199 616 192 C 655 186 685 170 700 159
               C 660 143 592 130 528 131 Z"
            fill="#f8bc45" stroke="#3a382f" stroke-width="5" stroke-linejoin="round"/>
      <path d="M 527 111 C 585 103 655 122 701 149 L 699 159
               C 652 137 590 125 528 133 Z"
            fill="#f5a623" stroke="#3a382f" stroke-width="5" stroke-linejoin="round"/>
      <path d="M 558 116 L 578 121" stroke="#c8860f" stroke-width="3" stroke-linecap="round"/>
      <circle cx="525" cy="110" r="5.2" fill="#2b2a26"/>
      <circle cx="526.8" cy="108" r="1.8" fill="#ffffff"/>
      <!-- cycling cap -->
      <path d="M 479 103 C 482 76 507 67 523 74 C 537 80 543 95 541 105 Q 510 92 479 103 Z"
            fill="#e04f3f" stroke="#3a382f" stroke-width="4.5" stroke-linejoin="round"/>
      <path d="M 539 99 L 563 106 L 558 115 L 536 108 Z"
            fill="#c73f31" stroke="#3a382f" stroke-width="4" stroke-linejoin="round"/>
      <path d="M 487 90 C 498 77 519 73 533 83" fill="none"
            stroke="#f6d7b0" stroke-width="3.5" stroke-linecap="round"/>
      <path d="M 514 101 Q 523 97 532 102" fill="none" stroke="#3a382f"
            stroke-width="3.5" stroke-linecap="round"/>
    </g>
  </g>
''')

    # ---------------- near leg + near foot on top ----------------
    S.append(leg_block(NEAR, 0, "#fdfaf1", 32, 22))
    S.append(foot("translate(432,490)", PEDAL_CIRCLE_NEAR, "#f5a623", "#c8860f", "#46464a", "#2f3033"))

    S.append("\n</svg>\n")

    svg = "".join(S)
    with open("pelican-bicycle.svg", "w", encoding="utf-8") as f:
        f.write(svg)
    print("wrote pelican-bicycle.svg (%d bytes)" % len(svg.encode("utf-8")))


if __name__ == "__main__":
    main()
