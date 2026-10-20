from jarvis.ui.overlay import _chest_button_hit_rects


def test_chest_hitboxes_are_separate_and_inside_robot_canvas():
    for size in (60, 120, 200, 300):
        rects = _chest_button_hit_rects(size)
        assert len(rects) == 4
        for rect in rects:
            assert 10 <= rect.left()
            assert rect.right() < size + 10
            assert 10 <= rect.top()
            assert rect.bottom() < size + 10
        for index, rect in enumerate(rects):
            assert all(
                not rect.intersects(other)
                for other in rects[index + 1:]
            )
