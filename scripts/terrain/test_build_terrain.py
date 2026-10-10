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


def test_isolated_low_point_in_the_sea_is_left_by_despike_and_taken_by_the_shape_stage():
    # 홀로 선 12 m 점 — 창 중앙값 판정(despike)은 바닥 문턱 아래라 남기고, 꼬리 단계도 안 본다(지운 것과
    # 안 닿는다). 꼴 단계의 좁은 기둥 판정이 맡는다: 31 m 자료로는 그 크기의 암초와 잡음을 가를 수 없고
    # 그리면 바다 위 바늘이다. 폭 3칸 넘는 섬은 남는다(test_islet_three_pixels_wide_is_kept).
    rows = flat(21, 21, 0.0)
    rows[10][10] = 12.0
    g, w, _, changed, _ = run(rows)
    assert not changed and at(g, w, 10, 10) == 12.0
    g2, w2, _, _, stages = clean(rows)
    assert stages["spires"] == 1 and at(g2, w2, 10, 10) == 0.0


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


# ---- 꼴로 잡는 결함 (clean_elevations) — 1차 판정(despike)이 산포에 눈이 머는 자리


def clean(rows):
    g, w, h = grid_of(rows)
    changed, stages = bt.clean_elevations(g, w, h)
    return g, w, h, changed, stages


def slope_plane(w, h, z0=20.0, dz=1.2):
    return [[z0 + dz * c + 0.6 * r for c in range(w)] for r in range(h)]


# 고흥 원자료(1차 정리 뒤) 해안 잡음 지대 — n=4300·e=−2000 둘레 원본 픽셀, 북쪽이 위. 왼쪽이 바다(0),
# 가운데 열의 89·89·76·43이 폭 1픽셀 벽이고 바로 왼쪽 0이 도랑이다. 화면에서는 해안 끝의 뾰족한 원뿔이었다.
COAST_NOISE = [
    [0, 0, 1, 5, 10, 17, 0, 76, 44, 53, 56, 56, 55],
    [0, 0, 1, 6, 11, 17, 32, 34, 50, 58, 63, 64, 62],
    [0, 0, 2, 6, 0, 89, 37, 28, 51, 60, 68, 74, 72],
    [0, 0, 2, 6, 0, 89, 39, 28, 50, 59, 70, 79, 80],
    [0, 1, 3, 7, 0, 76, 39, 29, 48, 57, 68, 78, 84],
    [0, 1, 4, 8, 0, 43, 32, 31, 43, 53, 63, 72, 81],
    [0, 2, 5, 8, 0, 24, 24, 28, 38, 48, 56, 65, 74],
    [1, 3, 5, 9, 16, 10, 17, 25, 33, 42, 50, 58, 67],
    [1, 3, 6, 24, 14, 9, 15, 22, 29, 37, 45, 54, 62],
    [2, 4, 7, 11, 11, 12, 15, 19, 25, 33, 41, 50, 59],
    [3, 5, 8, 9, 13, 18, 19, 20, 24, 31, 39, 48, 57],
]


def test_real_coastal_wall_is_removed_where_despike_is_blind():
    # 도랑과 바다가 창의 산포를 키워 1차 판정을 빠져나간다 — 먼저 그것을 확인해 이 시험이 새 단계를 본다는 것을 못박는다
    rows = [[float(v) for v in row] for row in reversed(COAST_NOISE)]   # 행 0 = 남
    g0, w, h = grid_of(rows)
    bt.despike(g0, w, h)
    wall = [(len(rows) - 1 - r, 5) for r in (2, 3, 4)]   # 그림의 89·89·76
    assert all(at(g0, w, r, c) >= 76.0 for r, c in wall), "1차 판정이 벽을 잡았다면 시험 모양을 다시 볼 것"
    g, w, h, changed, stages = clean(rows)
    assert stages["walls"] + stages["spires"] > 0
    for r, c in wall:
        assert at(g, w, r, c) < 45.0, f"벽이 남았다: {at(g, w, r, c):.1f} m"
    # 바다 쪽(왼쪽 세 열)은 그대로 낮고, 오른쪽 비탈의 실제 땅은 크게 안 바뀐다
    assert max(at(g, w, r, c) for r in range(h) for c in range(3)) < 10.0
    assert abs(at(g, w, len(rows) - 1 - 4, 12) - 84.0) < 15.0


def test_narrow_low_spire_on_flat_lowland_is_removed():
    # 바닥 문턱(20 m) 아래라 1차 판정이 남기는 높이 — 평지 위에 혼자 선 폭 1~2칸 기둥
    rows = flat(21, 21, 8.0)
    rows[10][10], rows[10][11] = 24.0, 19.0
    g, w, _, _, stages = clean(rows)
    assert stages["spires"] > 0
    assert max(g) < 9.0


def test_islet_three_pixels_wide_is_kept():
    # 폭 3칸(약 95 m) 이상은 3×3 중앙값이 그 높이를 따라가 기둥으로 안 본다 — 실제 작은 섬
    rows = flat(21, 21, 0.0)
    for r in range(9, 12):
        for c in range(9, 12):
            rows[r][c] = 14.0
    rows[10][10] = 18.0
    g, w, _, _, _ = clean(rows)
    assert at(g, w, 10, 10) >= 14.0 and at(g, w, 9, 9) == 14.0


def test_real_knoll_in_highland_is_untouched_beside_a_fixed_artifact():
    # 고흥 외곽 실측 — 125 m 평탄지의 66 m 구멍·167 m 바늘 짝 옆 223 m 언덕 꼭대기가 잡음 지대 다듬기에
    # 10 m 깎였었다. 새 단계는 저지대(둘레 60 m 아래)에서만 돈다.
    rows = [[125.0] * 31 for _ in range(31)]
    knoll = cone(31, 0.25, 225.0)
    for r in range(31):
        for c in range(31):
            rows[r][c] = max(rows[r][c], knoll[r][c])
    rows[3][27], rows[4][28] = 66.0, 167.0   # 평탄지 쪽 — 언덕 비탈 밖
    assert knoll[3][27] < 125.0 and knoll[4][28] < 125.0
    top_before = [rows[r][c] for r in range(12, 19) for c in range(12, 19)]
    g, w, _, _, _ = clean(rows)
    top_after = [at(g, w, r, c) for r in range(12, 19) for c in range(12, 19)]
    assert top_after == top_before, "언덕 꼭대기가 다듬어졌다"
    assert 120.0 < at(g, w, 3, 27) < 130.0 and 120.0 < at(g, w, 4, 28) < 130.0, "결함 짝은 고쳐진다"


def test_noisy_coastal_zone_is_smoothed_only_near_the_defects():
    # 결함 둘레 3칸만 다듬고, 멀리 떨어진 저지대의 고른 잡음(±2 m 밭두렁)은 원본 그대로다
    rows = flat(41, 41, 5.0)
    for r in range(41):
        for c in range(41):
            rows[r][c] += 1.5 if (r * 7 + c * 3) % 5 == 0 else 0.0
    rows[8][8], rows[8][9], rows[9][8] = 31.0, 0.0, 22.0   # 해안 잡음 덩어리
    far = (33, 33)
    before_far = rows[far[0]][far[1]]
    g, w, _, _, stages = clean(rows)
    assert stages["zone_px"] > 0
    assert at(g, w, *far) == before_far
    assert max(at(g, w, r, c) for r in range(5, 12) for c in range(5, 12)) < 9.0


def test_clean_is_idempotent_enough_and_deterministic():
    rows = slope_plane(30, 30)
    rows[10][10], rows[10][9], rows[20][5] = 95.0, 0.0, 40.0
    g1, w, h, _, s1 = clean(rows)
    g2, _, _, _, s2 = clean(rows)
    assert g1 == g2 and s1 == s2   # 같은 입력이면 같은 팩(data/README의 약속)
