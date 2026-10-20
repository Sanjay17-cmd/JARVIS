"""
assets/robot_painter.py — Programmatic robot mascot generator.

Draws a friendly cyan/blue 3D-style robot using Pillow.
Produces a set of transparent RGBA PNGs for each animation frame.
No Blender, no external art files required.

The robot is stylised to look futuristic:
  • Rounded metallic head with visor
  • Glowing cyan eyes
  • Subtle gradients for depth
  • Multiple expression variants (idle, happy, thinking, error…)
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFilter


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


def _draw_rounded_rect(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    radius: int,
    fill: tuple,
    outline: tuple | None = None,
    width: int = 2,
) -> None:
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill,
                           outline=outline, width=width)


def _lerp_color(c1: tuple, c2: tuple, t: float) -> tuple:
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def draw_robot(
    size: int = 200,
    eye_brightness: float = 1.0,   # 0–1
    mouth_open: float = 0.0,        # 0–1
    head_tilt: float = 0.0,         # degrees
    antenna_phase: float = 0.0,     # radians
    blink: float = 0.0,             # 0=open 1=closed
    glow_intensity: float = 0.6,
    state_color: tuple | None = None,  # override eye colour
) -> Image.Image:
    """
    Render one frame of the JARVIS robot at *size* × *size* pixels,
    returning an RGBA PIL Image with a transparent background.
    """
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)

    s = size
    cx = s // 2

    # ── proportional geometry ─────────────────────────────────────
    head_w   = int(s * 0.52)
    head_h   = int(s * 0.38)
    head_x0  = cx - head_w // 2
    head_y0  = int(s * 0.14)
    head_x1  = head_x0 + head_w
    head_y1  = head_y0 + head_h

    neck_w   = int(s * 0.16)
    neck_h   = int(s * 0.06)
    neck_x0  = cx - neck_w // 2
    neck_y0  = head_y1
    neck_x1  = neck_x0 + neck_w
    neck_y1  = neck_y0 + neck_h

    body_w   = int(s * 0.62)
    body_h   = int(s * 0.32)
    body_x0  = cx - body_w // 2
    body_y0  = neck_y1
    body_x1  = body_x0 + body_w
    body_y1  = body_y0 + body_h

    # ── antenna ───────────────────────────────────────────────────
    ant_base_x = cx
    ant_base_y = head_y0 + 4
    ant_len    = int(s * 0.13)
    ant_tip_x  = ant_base_x + int(math.sin(antenna_phase) * s * 0.035)
    ant_tip_y  = ant_base_y - ant_len
    tip_r      = int(s * 0.035)
    tip_col    = state_color or EYE_GLOW
    d.line([(ant_base_x, ant_base_y), (ant_tip_x, ant_tip_y)],
           fill=VISOR_EDGE, width=max(2, s // 60))
    d.ellipse([ant_tip_x - tip_r, ant_tip_y - tip_r,
               ant_tip_x + tip_r, ant_tip_y + tip_r],
              fill=tip_col)

    # ── body ──────────────────────────────────────────────────────
    _draw_rounded_rect(d, (body_x0, body_y0, body_x1, body_y1),
                       radius=s // 14, fill=BODY_MID, outline=VISOR_EDGE, width=max(1, s//80))

    # body highlight
    _draw_rounded_rect(d,
                       (body_x0 + 3, body_y0 + 3,
                        body_x0 + body_w // 2, body_y0 + body_h // 3),
                       radius=s // 20, fill=WHITE_ALPHA)

    # chest panel
    cp_w = int(body_w * 0.55)
    cp_h = int(body_h * 0.48)
    cp_x = cx - cp_w // 2
    cp_y = body_y0 + int(body_h * 0.18)
    _draw_rounded_rect(d, (cp_x, cp_y, cp_x + cp_w, cp_y + cp_h),
                       radius=s // 24, fill=CHEST_PANEL, outline=ACCENT_CYAN, width=max(1, s//80))

    # LEDs on chest
    led_r = max(3, s // 30)
    led_colors = [LED_ACTIVE, LED_ACTIVE, LED_IDLE, LED_ACTIVE]
    led_spacing = cp_w // (len(led_colors) + 1)
    for i, lc in enumerate(led_colors):
        lx = cp_x + led_spacing * (i + 1)
        ly = cp_y + cp_h // 2
        d.ellipse([lx - led_r, ly - led_r, lx + led_r, ly + led_r], fill=lc)

    # arms stubs
    arm_w = int(s * 0.08)
    arm_h = int(s * 0.20)
    arm_r = s // 12
    # left
    d.rounded_rectangle([body_x0 - arm_w - 2, body_y0 + 6,
                          body_x0 - 2,          body_y0 + arm_h],
                         radius=arm_r, fill=BODY_DARK, outline=VISOR_EDGE, width=max(1, s//80))
    # right
    d.rounded_rectangle([body_x1 + 2,           body_y0 + 6,
                          body_x1 + arm_w + 2,  body_y0 + arm_h],
                         radius=arm_r, fill=BODY_DARK, outline=VISOR_EDGE, width=max(1, s//80))

    # ── neck ──────────────────────────────────────────────────────
    d.rounded_rectangle([neck_x0, neck_y0, neck_x1, neck_y1],
                        radius=3, fill=BODY_DARK)

    # ── head ──────────────────────────────────────────────────────
    _draw_rounded_rect(d, (head_x0, head_y0, head_x1, head_y1),
                       radius=s // 10, fill=BODY_LIGHT, outline=VISOR_EDGE, width=max(1, s//70))
    # head highlight strip
    _draw_rounded_rect(d,
                       (head_x0 + 4, head_y0 + 4,
                        head_x1 - 4, head_y0 + head_h // 3),
                       radius=s // 14, fill=WHITE_ALPHA)

    # ── visor ─────────────────────────────────────────────────────
    vis_pad_x = int(head_w * 0.10)
    vis_pad_y = int(head_h * 0.18)
    vis_x0 = head_x0 + vis_pad_x
    vis_y0 = head_y0 + vis_pad_y
    vis_x1 = head_x1 - vis_pad_x
    vis_y1 = head_y1 - int(head_h * 0.14)
    _draw_rounded_rect(d, (vis_x0, vis_y0, vis_x1, vis_y1),
                       radius=s // 16, fill=VISOR_BG, outline=VISOR_EDGE, width=max(1, s//60))

    # ── eyes ──────────────────────────────────────────────────────
    eye_y_center = (vis_y0 + vis_y1) // 2
    eye_r_outer = max(4, int(s * 0.065))
    eye_r_inner = max(2, int(s * 0.038))
    eye_r_pupil = max(1, int(s * 0.018))

    eye_col = state_color if state_color else EYE_GLOW
    eye_col_b = _lerp_color(eye_col, EYE_CORE, 1.0 - eye_brightness)

    for ex in [vis_x0 + (vis_x1 - vis_x0) // 3,
               vis_x0 + 2 * (vis_x1 - vis_x0) // 3]:
        # glow halo
        halo_r = eye_r_outer + int(eye_r_outer * glow_intensity * 0.7)
        halo_col = (*eye_col[:3], int(80 * glow_intensity * eye_brightness))
        d.ellipse([ex - halo_r, eye_y_center - halo_r,
                   ex + halo_r, eye_y_center + halo_r], fill=halo_col)

        # blink: squash eye vertically
        blink_factor = 1.0 - blink * 0.95
        ey0 = eye_y_center - int(eye_r_outer * blink_factor)
        ey1 = eye_y_center + int(eye_r_outer * blink_factor)

        d.ellipse([ex - eye_r_outer, ey0, ex + eye_r_outer, ey1],
                  fill=eye_col_b)
        d.ellipse([ex - eye_r_inner, eye_y_center - int(eye_r_inner * blink_factor),
                   ex + eye_r_inner, eye_y_center + int(eye_r_inner * blink_factor)],
                  fill=EYE_CORE)
        d.ellipse([ex - eye_r_pupil, eye_y_center - int(eye_r_pupil * blink_factor),
                   ex + eye_r_pupil, eye_y_center + int(eye_r_pupil * blink_factor)],
                  fill=EYE_PUPIL)

    # ── mouth ─────────────────────────────────────────────────────
    mouth_y = vis_y1 - int(head_h * 0.18)
    mouth_w = int((vis_x1 - vis_x0) * 0.52)
    mouth_x0 = cx - mouth_w // 2
    mouth_x1 = cx + mouth_w // 2
    mouth_h  = max(2, int(s * 0.018 + mouth_open * s * 0.03))
    mouth_col= (*eye_col[:3], 200)
    d.rounded_rectangle([mouth_x0, mouth_y - mouth_h // 2,
                          mouth_x1, mouth_y + mouth_h // 2],
                         radius=mouth_h, fill=mouth_col)

    return canvas


def generate_animation_frames(
    size: int = 200,
    frames: int = 60,
    state: str = "idle",
    output_dir: Path | None = None,
) -> list[Image.Image]:
    """
    Generate *frames* RGBA images for the given *state*.
    If *output_dir* is given, saves each frame as a PNG.
    Always returns the list of PIL Images.
    """
    STATE_EYE_COLOR = {
        "idle":      EYE_GLOW,
        "listening": (0, 255, 150, 255),
        "thinking":  (255, 200, 0, 255),
        "speaking":  (100, 200, 255, 255),
        "success":   (0, 255, 100, 255),
        "error":     (255, 60, 60, 255),
        "paused":    (100, 100, 130, 255),
    }
    eye_col = STATE_EYE_COLOR.get(state, EYE_GLOW)
    images: list[Image.Image] = []

    for i in range(frames):
        t = i / frames
        phase = t * 2 * math.pi

        # Idle: gentle bob + slow antenna sway + periodic blink
        bob_offset   = math.sin(phase) * 0.02
        ant_phase    = math.sin(phase * 0.7) * 1.2
        blink        = 1.0 if (i % 50 in range(2)) else 0.0
        glow_i       = 0.5 + 0.5 * math.sin(phase * 1.3)
        mouth_open   = 0.0

        if state == "speaking":
            mouth_open = abs(math.sin(phase * 4)) * 0.8
        if state == "thinking":
            glow_i = 0.3 + 0.7 * ((i % 20) / 20)
        if state == "listening":
            glow_i = 0.7 + 0.3 * math.sin(phase * 2)

        img = draw_robot(
            size=size,
            eye_brightness=glow_i,
            mouth_open=mouth_open,
            antenna_phase=ant_phase,
            blink=blink,
            glow_intensity=glow_i,
            state_color=eye_col,
        )

        # Apply a very subtle vertical shift (bob)
        if bob_offset != 0:
            shift = int(bob_offset * size)
            shifted = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            shifted.paste(img, (0, shift))
            img = shifted

        images.append(img)
        if output_dir:
            out_path = output_dir / f"{state}_{i:03d}.png"
            img.save(out_path, "PNG")

    return images


def ensure_assets(asset_dir: Path, size: int = 200) -> dict[str, list[Image.Image]]:
    """
    Check whether pre-rendered frames exist; generate them if not.
    Returns a dict  state → [PIL Image, …].
    """
    asset_dir.mkdir(parents=True, exist_ok=True)
    states = ["idle", "listening", "thinking", "speaking", "success", "error", "paused"]
    frame_counts = {
        "idle": 60, "listening": 40, "thinking": 40,
        "speaking": 40, "success": 30, "error": 30, "paused": 20,
    }
    result: dict[str, list[Image.Image]] = {}
    for state in states:
        frames_needed = frame_counts[state]
        sample_path = asset_dir / f"{state}_000.png"
        if sample_path.exists():
            # Load existing frames
            imgs = []
            for j in range(frames_needed):
                p = asset_dir / f"{state}_{j:03d}.png"
                if p.exists():
                    imgs.append(Image.open(p).convert("RGBA"))
            result[state] = imgs or generate_animation_frames(size, frames_needed, state)
        else:
            result[state] = generate_animation_frames(
                size, frames_needed, state, output_dir=asset_dir
            )
    return result


if __name__ == "__main__":
    # Quick preview test
    out = Path("preview_frames")
    out.mkdir(exist_ok=True)
    ensure_assets(out, size=200)
    print(f"Frames written to {out.resolve()}")
