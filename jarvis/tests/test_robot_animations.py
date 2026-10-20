from PIL import ImageChops

from jarvis.assets.robot_painter import generate_animation_frames


def test_special_animations_are_visually_distinct():
    names = ("wave", "flying", "tools", "scanning", "typing", "thirsty", "alarm")
    frames = {
        name: generate_animation_frames(size=120, frames=3, state=name)[0]
        for name in names
    }

    for left_index, left in enumerate(names):
        for right in names[left_index + 1:]:
            difference = ImageChops.difference(
                frames[left].convert("RGB"), frames[right].convert("RGB")
            )
            assert difference.getbbox() is not None
