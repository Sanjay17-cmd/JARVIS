"""
assets/robot_painter.py — Programmatic robot mascot generator — v2.1

Fixes in v2.1:
  • get_led_positions(size) — returns exact pixel (lx, ly, led_r) for each LED
    so overlay.py can align hit-rects to actual painted pixels.
  • ensure_assets() now checks frame SIZE embedded in filenames; if size
    changes it deletes old frames and regenerates (fixes live-resize cache issue).
  • Animation variety massively improved:
    - idle:      gentle bob, slow antenna sway, random blink every ~50 frames
    - listening: rapid eye-glow pulse, slight head lean, antenna up
    - thinking:  head tilt left/right oscillation, amber eyes, eyebrow furrow
    - speaking:  wide mouth open/close synced to fast cycles, blue glow
    - success:   green eyes, happy wide mouth, fast antenna wag, bounce
    - error:     red eyes, flat/sad mouth, antenna droop, vigorous shake
    - paused:    dim grey eyes, slow heartbeat glow, still antenna
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

# ── colour palette ─────────────────────────────────────────────────────────
BODY_DARK   = (20,  40,  70,  255)
BODY_MID    = (30,  60, 100,  255)
BODY_LIGHT  = (50,  90, 140,  255)
VISOR_BG    = (5,   15,  35,  220)
VISOR_EDGE  = (0,  200, 255,  255)
EYE_GLOW    = (0,  230, 255,  255)
EYE_CORE    = (255, 255, 255, 255)
EYE_PUPIL   = (0,  180, 220,  255)
ACCENT_CYAN = (0,  220, 255,  180)
CHEST_PANEL = (10,  25,  55,  200)
LED_ACTIVE  = (0,  255, 200,  255)
LED_IDLE    = (0,  120, 160,  180)
WHITE_ALPHA = (255, 255, 255,  80)

STATE_EYE_COLOR = {
    "idle":      EYE_GLOW,
    "listening": (0,  255, 150, 255),
    "thinking":  (255, 200,   0, 255),
    "speaking":  (100, 200, 255, 255),
    "success":   (0,  255, 100, 255),
    "error":     (255,  60,  60, 255),
    "paused":    (100, 100, 130, 255),
}


# ── helpers ────────────────────────────────────────────────────────────────

def _draw_rounded_rect(draw, xy, radius, fill, outline=None, width=2):
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius,
                           fill=fill, outline=outline, width=width)


def _lerp_color(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


# ── LED position export (THE KEY FIX) ─────────────────────────────────────

def get_led_positions(size: int) -> list[tuple[int, int, int]]:
    """
    Returns [(lx, ly, led_r), ...] for each chest LED at the EXACT pixel
    coordinates used by draw_robot(). Overlay uses this for hit-testing.
    No padding offset is included — that must be added by the caller.
    """
    s  = size
    cx = s // 2

    head_h  = int(s * 0.38)
    head_y0 = int(s * 0.14)
    neck_h  = int(s * 0.06)
    body_w  = int(s * 0.62)
    body_h  = int(s * 0.32)
    body_y0 = head_y0 + head_h + neck_h

    cp_w = int(body_w * 0.55)
    cp_h = int(body_h * 0.48)
    cp_x = cx - cp_w // 2
    cp_y = body_y0 + int(body_h * 0.18)

    led_r      = max(3, s // 30)           # SAME formula as draw_robot
    led_spacing= cp_w // 5                 # 4 LEDs → spacing = cp_w // (4+1)
    ly         = cp_y + cp_h // 2

    positions = []
    for i in range(4):
        lx = cp_x + led_spacing * (i + 1)
        positions.append((lx, ly, led_r))
    return positions


# ── core draw ──────────────────────────────────────────────────────────────

def draw_robot(
    size: int = 200,
    eye_brightness: float = 1.0,
    mouth_open: float = 0.0,
    head_tilt: float = 0.0,        # degrees, ±15
    antenna_phase: float = 0.0,
    blink: float = 0.0,
    glow_intensity: float = 0.6,
    state_color: tuple | None = None,
    mouth_curve: float = 1.0,      # 1=smile, -1=frown, 0=flat
    led_override: list[tuple] | None = None,  # per-LED colour overrides
) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)

    s  = size
    cx = s // 2

    # ── geometry (identical to get_led_positions so they always match) ─────
    head_w  = int(s * 0.52)
    head_h  = int(s * 0.38)
    head_x0 = cx - head_w // 2
    head_y0 = int(s * 0.14)
    head_x1 = head_x0 + head_w
    head_y1 = head_y0 + head_h

    neck_w  = int(s * 0.16)
    neck_h  = int(s * 0.06)
    neck_x0 = cx - neck_w // 2
    neck_y0 = head_y1
    neck_x1 = neck_x0 + neck_w
    neck_y1 = neck_y0 + neck_h

    body_w  = int(s * 0.62)
    body_h  = int(s * 0.32)
    body_x0 = cx - body_w // 2
    body_y0 = neck_y1
    body_x1 = body_x0 + body_w
    body_y1 = body_y0 + body_h

    # ── antenna ────────────────────────────────────────────────────────────
    ant_base_x = cx
    ant_base_y = head_y0 + 4
    ant_len    = int(s * 0.13)
    ant_tip_x  = ant_base_x + int(math.sin(antenna_phase) * s * 0.05)
    ant_tip_y  = ant_base_y - ant_len
    tip_r      = int(s * 0.035)
    tip_col    = state_color or EYE_GLOW
    d.line([(ant_base_x, ant_base_y), (ant_tip_x, ant_tip_y)],
           fill=VISOR_EDGE, width=max(2, s // 60))
    d.ellipse([ant_tip_x - tip_r, ant_tip_y - tip_r,
               ant_tip_x + tip_r, ant_tip_y + tip_r], fill=tip_col)

    # ── body ───────────────────────────────────────────────────────────────
    _draw_rounded_rect(d, (body_x0, body_y0, body_x1, body_y1),
                       radius=s // 14, fill=BODY_MID,
                       outline=VISOR_EDGE, width=max(1, s // 80))
    _draw_rounded_rect(d,
                       (body_x0 + 3, body_y0 + 3,
                        body_x0 + body_w // 2, body_y0 + body_h // 3),
                       radius=s // 20, fill=WHITE_ALPHA)

    # ── chest panel ────────────────────────────────────────────────────────
    cp_w = int(body_w * 0.55)
    cp_h = int(body_h * 0.48)
    cp_x = cx - cp_w // 2
    cp_y = body_y0 + int(body_h * 0.18)
    _draw_rounded_rect(d, (cp_x, cp_y, cp_x + cp_w, cp_y + cp_h),
                       radius=s // 24, fill=CHEST_PANEL,
                       outline=ACCENT_CYAN, width=max(1, s // 80))

    # ── LEDs ───────────────────────────────────────────────────────────────
    led_r       = max(3, s // 30)
    led_spacing = cp_w // 5
    ly          = cp_y + cp_h // 2
    default_leds= [LED_ACTIVE, LED_ACTIVE, LED_IDLE, LED_ACTIVE]
    for i in range(4):
        lx  = cp_x + led_spacing * (i + 1)
        col = (led_override[i] if led_override and i < len(led_override)
               else default_leds[i])
        # glow halo
        halo = (*col[:3], 80)
        hr   = led_r + 2
        d.ellipse([lx - hr, ly - hr, lx + hr, ly + hr], fill=halo)
        d.ellipse([lx - led_r, ly - led_r, lx + led_r, ly + led_r], fill=col)

    # ── arms ───────────────────────────────────────────────────────────────
    arm_w = int(s * 0.08)
    arm_h = int(s * 0.20)
    arm_r = s // 12
    d.rounded_rectangle([body_x0 - arm_w - 2, body_y0 + 6,
                          body_x0 - 2, body_y0 + arm_h],
                         radius=arm_r, fill=BODY_DARK,
                         outline=VISOR_EDGE, width=max(1, s // 80))
    d.rounded_rectangle([body_x1 + 2, body_y0 + 6,
                          body_x1 + arm_w + 2, body_y0 + arm_h],
                         radius=arm_r, fill=BODY_DARK,
                         outline=VISOR_EDGE, width=max(1, s // 80))

    # ── neck ───────────────────────────────────────────────────────────────
    d.rounded_rectangle([neck_x0, neck_y0, neck_x1, neck_y1],
                        radius=3, fill=BODY_DARK)

    # ── head (with tilt applied via affine) ────────────────────────────────
    head_canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    hd = ImageDraw.Draw(head_canvas)

    _draw_rounded_rect(hd, (head_x0, head_y0, head_x1, head_y1),
                       radius=s // 10, fill=BODY_LIGHT,
                       outline=VISOR_EDGE, width=max(1, s // 70))
    _draw_rounded_rect(hd,
                       (head_x0 + 4, head_y0 + 4,
                        head_x1 - 4, head_y0 + head_h // 3),
                       radius=s // 14, fill=WHITE_ALPHA)

    # visor
    vis_pad_x = int(head_w * 0.10)
    vis_pad_y = int(head_h * 0.18)
    vis_x0 = head_x0 + vis_pad_x;  vis_y0 = head_y0 + vis_pad_y
    vis_x1 = head_x1 - vis_pad_x;  vis_y1 = head_y1 - int(head_h * 0.14)
    _draw_rounded_rect(hd, (vis_x0, vis_y0, vis_x1, vis_y1),
                       radius=s // 16, fill=VISOR_BG,
                       outline=VISOR_EDGE, width=max(1, s // 60))

    # eyes
    eye_y_center = (vis_y0 + vis_y1) // 2
    eye_r_outer  = max(4, int(s * 0.065))
    eye_r_inner  = max(2, int(s * 0.038))
    eye_r_pupil  = max(1, int(s * 0.018))
    eye_col      = state_color if state_color else EYE_GLOW
    eye_col_b    = _lerp_color(eye_col, EYE_CORE, 1.0 - eye_brightness)

    for ex in [vis_x0 + (vis_x1 - vis_x0) // 3,
               vis_x0 + 2 * (vis_x1 - vis_x0) // 3]:
        halo_r   = eye_r_outer + int(eye_r_outer * glow_intensity * 0.8)
        halo_col = (*eye_col[:3], int(100 * glow_intensity * eye_brightness))
        hd.ellipse([ex - halo_r, eye_y_center - halo_r,
                    ex + halo_r, eye_y_center + halo_r], fill=halo_col)

        blink_factor = 1.0 - blink * 0.97
        ey0 = eye_y_center - int(eye_r_outer * blink_factor)
        ey1 = eye_y_center + int(eye_r_outer * blink_factor)
        hd.ellipse([ex - eye_r_outer, ey0, ex + eye_r_outer, ey1], fill=eye_col_b)
        hd.ellipse([ex - eye_r_inner,
                    eye_y_center - int(eye_r_inner * blink_factor),
                    ex + eye_r_inner,
                    eye_y_center + int(eye_r_inner * blink_factor)],
                   fill=EYE_CORE)
        hd.ellipse([ex - eye_r_pupil,
                    eye_y_center - int(eye_r_pupil * blink_factor),
                    ex + eye_r_pupil,
                    eye_y_center + int(eye_r_pupil * blink_factor)],
                   fill=EYE_PUPIL)

    # mouth — curve > 0 = smile, < 0 = frown, 0 = flat
    mouth_y = vis_y1 - int(head_h * 0.18)
    mouth_w = int((vis_x1 - vis_x0) * 0.55)
    mouth_x0_m = cx - mouth_w // 2
    mouth_x1_m = cx + mouth_w // 2
    mouth_h  = max(2, int(s * 0.016 + mouth_open * s * 0.04))
    mouth_col= (*eye_col[:3], 210)
    curve_offset = int(mouth_curve * s * 0.012)
    hd.rounded_rectangle([mouth_x0_m, mouth_y - mouth_h // 2 + curve_offset,
                           mouth_x1_m, mouth_y + mouth_h // 2 + curve_offset],
                          radius=mouth_h, fill=mouth_col)

    # apply tilt to head layer
    if abs(head_tilt) > 0.5:
        head_canvas = head_canvas.rotate(
            head_tilt, center=(cx, (head_y0 + head_y1) // 2),
            resample=Image.BILINEAR, expand=False,
        )

    canvas.alpha_composite(head_canvas)
    return canvas


# ── animation state definitions ────────────────────────────────────────────

def generate_animation_frames(
    size: int = 200,
    frames: int = 60,
    state: str = "idle",
    output_dir: Path | None = None,
) -> list[Image.Image]:
    eye_col = STATE_EYE_COLOR.get(state, EYE_GLOW)
    images: list[Image.Image] = []

    for i in range(frames):
        t     = i / max(frames - 1, 1)
        phase = t * 2 * math.pi

        # ── defaults ──────────────────────────────────────────────────────
        bob_offset    = 0.0
        ant_phase     = 0.0
        blink         = 0.0
        glow_i        = 0.7
        mouth_open    = 0.0
        mouth_curve   = 1.0   # smile
        head_tilt     = 0.0
        led_override  = None

        if state == "idle":
            bob_offset  = math.sin(phase) * 0.018
            ant_phase   = math.sin(phase * 0.6) * 0.8
            blink       = 1.0 if (i % 55 in (0, 1)) else 0.0
            glow_i      = 0.55 + 0.35 * math.sin(phase * 1.1)
            mouth_curve = 0.8

        elif state == "listening":
            bob_offset  = math.sin(phase * 2) * 0.008
            ant_phase   = -0.6 + math.sin(phase * 3) * 0.3   # alert/up
            glow_i      = 0.6 + 0.4 * abs(math.sin(phase * 3))  # rapid pulse
            head_tilt   = math.sin(phase * 0.8) * 4           # slight lean
            blink       = 1.0 if (i % 45 in (0,)) else 0.0
            led_override= [LED_ACTIVE, (0,255,150,255), LED_ACTIVE, LED_ACTIVE]

        elif state == "thinking":
            head_tilt   = math.sin(phase * 1.2) * 10           # distinct head rock
            ant_phase   = math.sin(phase * 0.4) * 0.4
            glow_i      = 0.3 + 0.7 * abs(math.sin(phase * 2))  # pulsing
            blink       = 1.0 if (i % 35 in (0, 1)) else 0.0
            mouth_curve = 0.0   # neutral/flat
            led_override= [(255,200,0,200), (255,200,0,200),
                           (255,200,0,100), (255,200,0,50)]

        elif state == "speaking":
            mouth_open  = abs(math.sin(phase * 5)) * 1.0       # fast mouth
            glow_i      = 0.8 + 0.2 * math.sin(phase * 5)
            ant_phase   = math.sin(phase * 2) * 0.5
            bob_offset  = math.sin(phase * 4) * 0.012
            led_override= [(100,200,255,200),(100,200,255,200),
                           (100,200,255,100),(100,200,255,200)]

        elif state == "success":
            bob_offset  = abs(math.sin(phase * 2)) * 0.03      # bounce
            ant_phase   = math.sin(phase * 4) * 1.5            # fast wag
            glow_i      = 0.7 + 0.3 * math.sin(phase * 3)
            mouth_open  = 0.5
            mouth_curve = 1.5   # big smile
            led_override= [(0,255,100,255),(0,255,100,255),
                           (0,255,100,200),(0,255,100,255)]

        elif state == "error":
            # vigorous shake
            shake       = math.sin(phase * 8) * 8 if i < frames * 0.6 else 0.0
            head_tilt   = shake
            ant_phase   = math.sin(phase * 6) * 0.8
            glow_i      = 0.9
            mouth_curve = -1.0   # frown / sad
            blink       = 1.0 if (i % 15 in (0,)) else 0.0
            bob_offset  = math.sin(phase * 8) * 0.01
            led_override= [(255,60,60,255),(255,60,60,200),
                           (255,60,60,100),(255,60,60,255)]

        elif state == "paused":
            ant_phase   = 0.0   # still
            glow_i      = 0.2 + 0.15 * math.sin(phase * 0.5)  # faint heartbeat
            blink       = 1.0 if (i % 30 in range(3)) else 0.0
            mouth_curve = 0.3
            led_override= [(100,100,130,120),(100,100,130,60),
                           (100,100,130,40),(100,100,130,100)]

        img = draw_robot(
            size=size,
            eye_brightness=glow_i,
            mouth_open=mouth_open,
            antenna_phase=ant_phase,
            blink=blink,
            glow_intensity=glow_i,
            state_color=eye_col,
            mouth_curve=mouth_curve,
            head_tilt=head_tilt,
            led_override=led_override,
        )

        # vertical bob
        if bob_offset:
            shift   = int(bob_offset * size)
            shifted = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            shifted.paste(img, (0, shift))
            img = shifted

        images.append(img)
        if output_dir:
            img.save(output_dir / f"{state}_{i:03d}.png", "PNG")

    return images


# ── cache-aware loader (size-stamped) ──────────────────────────────────────

def _size_stamp_path(asset_dir: Path) -> Path:
    return asset_dir / ".size"


def ensure_assets(asset_dir: Path, size: int = 200) -> dict[str, list[Image.Image]]:
    """
    Generates frames if not cached or if size has changed.
    Stores a .size stamp file; if it doesn't match current size,
    all PNG files are deleted and regenerated.
    """
    asset_dir.mkdir(parents=True, exist_ok=True)

    stamp = _size_stamp_path(asset_dir)
    cached_size = int(stamp.read_text()) if stamp.exists() else -1

    if cached_size != size:
        # Clear stale frames
        for f in asset_dir.glob("*.png"):
            try:
                f.unlink()
            except OSError:
                pass
        stamp.write_text(str(size))

    states = ["idle", "listening", "thinking", "speaking", "success", "error", "paused"]
    frame_counts = {
        "idle": 60, "listening": 40, "thinking": 40,
        "speaking": 40, "success": 30, "error": 30, "paused": 20,
    }
    result: dict[str, list[Image.Image]] = {}
    for state in states:
        n     = frame_counts[state]
        first = asset_dir / f"{state}_000.png"
        if first.exists():
            imgs = []
            for j in range(n):
                p = asset_dir / f"{state}_{j:03d}.png"
                if p.exists():
                    imgs.append(Image.open(p).convert("RGBA"))
            result[state] = imgs if len(imgs) == n else \
                generate_animation_frames(size, n, state, asset_dir)
        else:
            result[state] = generate_animation_frames(size, n, state, asset_dir)
    return result


if __name__ == "__main__":
    out = Path("preview_frames")
    out.mkdir(exist_ok=True)
    ensure_assets(out, size=200)
    print(f"Frames written to {out.resolve()}")
