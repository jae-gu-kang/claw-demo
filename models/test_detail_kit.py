"""models/detail_kit.py 의 순수 부분 — 블렌더 없이 돈다(윤곽·간격·채우기 기하).

실행: `pytest models`. 블렌더가 필요한 부분(표면 투영·글자·볼트)은 각 모델의 GLB 테스트가 산출물로 확인한다.
"""

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detail_kit import fill_convex, resample_closed, rounded_rect, spaced  # noqa: E402


def _area(pts):
    return 0.5 * sum(pts[i - 1][0] * pts[i][1] - pts[i][0] * pts[i - 1][1] for i in range(len(pts)))


def test_rounded_rect_is_ccw_and_fits_its_box():
    pts = rounded_rect(0.4, 0.2, 0.03)
    assert _area(pts) > 0                                    # 반시계 — 바깥 법선이 u×v
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    assert max(xs) == pytest.approx(0.2) and min(xs) == pytest.approx(-0.2)
    assert max(ys) == pytest.approx(0.1) and min(ys) == pytest.approx(-0.1)
    # 모서리를 깎은 만큼 직사각형보다 작다: 4r² − πr²
    assert _area(pts) == pytest.approx(0.08 - (4 - math.pi) * 0.03 ** 2, rel=0.01)


def test_rounded_rect_rejects_zero_radius():
    with pytest.raises(ValueError):
        rounded_rect(0.4, 0.2, 0.0)                          # 겹친 점이 생긴다


def test_resample_closed_spaces_points_evenly_by_arc_length():
    square = [(0, 0), (1, 0), (1, 1), (0, 1)]
    pts = resample_closed(square, 8)
    assert len(pts) == 8
    gaps = [math.dist(pts[i], pts[(i + 1) % 8]) for i in range(8)]
    assert max(gaps) == pytest.approx(0.5) and min(gaps) == pytest.approx(0.5)


def test_spaced_keeps_margins_and_pitch():
    pts = spaced((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 0.1, margin=0.05)
    assert pts[0][0] == pytest.approx(0.05) and pts[-1][0] == pytest.approx(0.95)
    assert len(pts) == 10                                    # 0.9 / 0.1 = 9칸 → 10점
    assert all(math.dist(a, b) <= 0.1 + 1e-9 for a, b in zip(pts, pts[1:]))


def test_fill_convex_covers_the_outline_with_consistent_winding():
    outline = rounded_rect(0.3, 0.2, 0.02)
    verts, faces = fill_convex(outline, rings=3)
    assert verts[:len(outline)] == outline                  # 바깥 고리가 윤곽 그대로 — 옆면을 이을 자리
    tri_area = 0.0
    for f in faces:
        pts = [verts[i] for i in f]
        a = _area(pts)
        assert a > 0                                         # 전부 같은 방향(반시계)
        tri_area += a
    assert tri_area == pytest.approx(_area(outline), rel=1e-9)
