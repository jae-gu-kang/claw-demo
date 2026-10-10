"""build_terrain.py — 첨탑 정리(`despike`) 시험. 내려받기 없음(합성 격자만 쓴다).

정리는 **지우는 쪽**이라 틀리면 실제 지형이 깎인다. 그래서 두 방향을 같이 못박는다:
있을 수 없는 것(바늘·1픽셀 벽·덩어리·구멍)은 지우고, 있을 법한 것(가파른 봉우리·평면
경사·절벽)은 한 픽셀도 건드리지 않는다. 그리고 후보만 판정하는 지름길이 전면 탐색과
같은 답을 낸다는 독스트링의 주장을 무작위 격자로 대조한다.
"""

import importlib.util
import pathlib
from array import array

_spec = importlib.util.spec_from_file_location(
    "build_terrain", pathlib.Path(__file__).with_name("build_terrain.py"))
bt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bt)

PX = 31.5  # 원본 픽셀 한 변 [m] — 고흥 위도의 z12


def grid_of(rows):
    h, w = len(rows), len(rows[0])
    return array("d", [float(v) for row in rows for v in row]), w, h


def flat(w, h, z):
    return [[z] * w for _ in range(h)]


def run(rows):
    g, w, h = grid_of(rows)
    changed, per_stage = bt.despike(g, w, h)
    return g, w, h, changed, per_stage


def at(g, w, r, c):
    return g[r * w + c]


def test_needle_on_flat_ground_is_replaced_by_its_surroundings():
    rows = flat(15, 15, 5.0)
    rows[7][7] = 400.0
    g, w, _, changed, _ = run(rows)
    assert at(g, w, 7, 7) == 5.0
    assert changed == {7 * w + 7}


def test_one_pixel_wall_in_the_sea_is_removed_with_its_low_tail():
    # 만 한가운데의 벽 — 실측 모양(폭 1픽셀, 314 m 꼭대기에서 12 m 꼬리까지). 꼬리 12 m는
    # 바닥 문턱 20 m 아래라 강한 단계만으로는 바다 위 작은 섬으로 남았다.
    rows = flat(21, 21, 0.0)
    for r, z in zip(range(5, 16), (12, 59, 193, 278, 219, 108, 65, 120, 90, 60, 12)):
        rows[r][10] = float(z)
    g, w, h, _, per_stage = run(rows)
    assert max(g) == 0.0
    assert per_stage[-1] > 0, "꼬리 단계가 한 일이 없다 — 강한 단계가 꼬리까지 지웠다면 시험 모양을 다시 볼 것"


def test_isolated_low_rock_in_the_sea_is_kept():
    # 홀로 선 12 m 암초 — 지운 것과 닿지 않으므로 꼬리 단계도 보지 않는다(실제일 수 있다)
    rows = flat(21, 21, 0.0)
    rows[10][10] = 12.0
    g, w, _, changed, _ = run(rows)
    assert not changed and at(g, w, 10, 10) == 12.0


def test_two_by_two_cluster_on_flat_ground_is_removed():
    rows = flat(17, 17, 6.5)
    for r, c, z in ((8, 8, 428.0), (8, 9, 358.0), (9, 8, 389.0), (9, 9, 475.0)):
        rows[r][c] = z
    g, _, _, _, _ = run(rows)
    assert max(g) == 6.5


def test_pit_on_a_lake_plateau_is_filled():
    rows = flat(15, 15, 125.0)
    rows[7][7] = 0.0
    rows[7][8] = 13.0
    g, w, _, _, _ = run(rows)
    assert at(g, w, 7, 7) == 125.0 and at(g, w, 7, 8) == 125.0


def cone(n, slope_per_px, top):
    c = n // 2
    return [[max(0.0, top - slope_per_px * PX * ((r - c) ** 2 + (q - c) ** 2) ** 0.5)
             for q in range(n)] for r in range(n)]


def test_steep_real_summits_are_untouched():
    # 45°(1.0)와 56°(1.5) 원뿔 — 원자료의 실제 봉우리는 이보다 무디다(5×5 중앙값 이탈 최대 28 m)
    for slope in (1.0, 1.5):
        rows = cone(31, slope, 600.0)
        g, _, _, changed, _ = run(rows)
        assert not changed, f"기울기 {slope}의 봉우리가 깎였다"


def test_planar_slope_and_cliff_are_untouched():
    slope = [[3.0 * c + 1.5 * r for c in range(25)] for r in range(25)]
    assert not run(slope)[3]
    cliff = [[0.0 if c < 12 else 100.0 for c in range(25)] for r in range(25)]
    assert not run(cliff)[3]


def test_second_run_changes_nothing():
    rows = flat(21, 21, 0.0)
    rows[5][5] = 300.0
    rows[12][14], rows[13][14] = 250.0, 190.0
    g, w, h, changed, _ = run(rows)
    assert changed
    again, _ = bt.despike(g, w, h)
    assert not again


def brute_force(g, w, h, stages):
    """독스트링이 말하는 기준 — 매 회차 **전 픽셀**을 판정한다."""
    for k, floor, k_mad in stages:
        half = k // 2
        for _ in range(bt.DESPIKE_MAX_PASSES):
            repl = {}
            for i in range(w * h):
                r, c = divmod(i, w)
                vals = sorted(bt._window_values(g, w, h, r, c, half))
                mid = len(vals) // 2
                med = vals[mid]
                mad = sorted(abs(v - med) for v in vals)[mid]
                if abs(g[i] - med) > max(floor, k_mad * bt.MAD_SIGMA * mad):
                    repl[i] = med
            if not repl:
                break
            for i, m in repl.items():
                g[i] = m


def test_candidate_shortcut_matches_full_scan():
    seed = 12345

    def rnd():
        nonlocal seed
        seed = (1103515245 * seed + 12345) % 2 ** 31
        return seed / 2 ** 31

    for _trial in range(4):
        w, h = 48, 44
        # 완만한 언덕 + 잡음 + 첨탑·덩어리·구멍을 무작위로
        rows = [[max(0.0, 40.0 * (1 + ((c - 20) * (r - 18)) / 900.0) + 6.0 * rnd() - 3.0)
                 for c in range(w)] for r in range(h)]
        for _ in range(14):
            r, c = int(rnd() * (h - 2)), int(rnd() * (w - 2))
            z = 30.0 + 400.0 * rnd()
            rows[r][c] = z
            if rnd() < 0.4:
                rows[r + 1][c] = z * 0.8
            if rnd() < 0.3:
                rows[r][c + 1] = 0.0
        g1, w1, h1 = grid_of(rows)
        g2 = array("d", g1)
        # 대조는 강한 단계에만 — 꼬리 단계는 정의부터 「지운 것의 이웃」이라 전면 탐색이 없다
        bt.despike(g1, w1, h1, tail=(5, float("inf"), 5.0))
        brute_force(g2, w1, h1, bt.DESPIKE_STAGES)
        assert g1 == g2
