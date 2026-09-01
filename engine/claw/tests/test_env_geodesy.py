"""M4 env 검증 — 국지 접평면 측지 변환 (NED ↔ 위경도).

`geodesy.py`가 하는 일은 두 줄짜리 선형화라 틀릴 여지가 좁아 보이지만, 실제로 사고가
나는 자리는 셋이다: ① 북/동 스케일을 뒤바꿔 쓰는 것 ② M(φ)와 N(φ)를 혼동하는 것
③ 웹 구현이 엔진과 조용히 갈라지는 것. 아래 테스트가 각각을 겨눈다.

특히 ③은 `data/geodesy-fixture.json`을 **웹 테스트와 같이 읽어** 막는다.
"""

import json
import math
from pathlib import Path

import pytest

from claw.env.earth import radius_meridian, radius_prime_vertical
from claw.env.geodesy import geodetic_to_ned, local_scales, ned_to_geodetic

LAT0 = math.radians(34.6)
LON0 = math.radians(127.2)

FIXTURE_PATH = Path(__file__).resolve().parents[3] / "data" / "geodesy-fixture.json"


@pytest.fixture(scope="module")
def fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


# ---- 왕복 항등 ----

@pytest.mark.parametrize(
    "n,e",
    [(0.0, 0.0), (1000.0, 0.0), (0.0, 1000.0), (-20000.0, 20000.0), (12345.6, -7890.1)],
)
def test_roundtrip_is_identity(n, e):
    """ned_to_geodetic → geodetic_to_ned는 정확한 역함수다 (같은 스케일을 쓰므로)."""
    lat, lon = ned_to_geodetic(n, e, LAT0, LON0)
    n2, e2 = geodetic_to_ned(lat, lon, LAT0, LON0)
    assert n2 == pytest.approx(n, abs=1e-9)
    assert e2 == pytest.approx(e, abs=1e-9)


# ---- 스케일의 정체 (M과 N을 혼동하지 않는가) ----

def test_north_scale_is_meridian_radius():
    """북쪽 1 km가 만드는 위도 증가는 정확히 1000/M(φ0)여야 한다 — N(φ0)가 아니다."""
    lat, lon = ned_to_geodetic(1000.0, 0.0, LAT0, LON0)
    assert lat - LAT0 == pytest.approx(1000.0 / radius_meridian(LAT0), rel=1e-12)
    assert lon == LON0, "북쪽 이동은 경도를 바꾸지 않는다"


def test_east_scale_is_prime_vertical_times_cos():
    """동쪽 1 km가 만드는 경도 증가는 1000/(N(φ0)·cos φ0)여야 한다."""
    lat, lon = ned_to_geodetic(0.0, 1000.0, LAT0, LON0)
    expected = 1000.0 / (radius_prime_vertical(LAT0) * math.cos(LAT0))
    assert lon - LON0 == pytest.approx(expected, rel=1e-12)
    assert lat == LAT0, "동쪽 이동은 위도를 바꾸지 않는다"


def test_east_scale_is_smaller_than_north_at_midlatitude():
    """중위도에서 동서 스케일이 남북보다 작다 — 자오선이 극으로 모이기 때문.

    이 부등호가 뒤집히면 배경지도가 위도 방향으로 늘어난 채 깔린다(원인이 안 보이는
    부류의 버그라 부호 하나로 못박아 둔다).
    """
    m_north, m_east = local_scales(LAT0)
    assert m_east < m_north
    assert m_east / m_north == pytest.approx(0.8269, abs=1e-4)


def test_scales_match_known_degree_lengths():
    """독립 대조 — 위도 34.6°의 1도 길이는 위도 약 110,930 m, 경도 약 91,730 m다.

    구현식을 그대로 되풀이하지 않는 외부 기준이라, 공식을 통째로 잘못 옮긴 경우를 잡는다.
    """
    m_north, m_east = local_scales(LAT0)
    assert m_north * math.pi / 180.0 == pytest.approx(110930.0, abs=20.0)
    assert m_east * math.pi / 180.0 == pytest.approx(91730.0, abs=20.0)


def test_h_ref_enlarges_both_scales():
    """기준 고도를 올리면 두 스케일 다 커진다 — 같은 각도가 더 긴 호를 덮는다."""
    lo_n, lo_e = local_scales(LAT0, 0.0)
    hi_n, hi_e = local_scales(LAT0, 1000.0)
    assert hi_n - lo_n == pytest.approx(1000.0, rel=1e-12)
    assert hi_e - lo_e == pytest.approx(1000.0 * math.cos(LAT0), rel=1e-12)


# ---- 거부 경로 (조용한 발산 금지) ----

@pytest.mark.parametrize("lat0", [math.radians(89.5), math.radians(-89.5)])
def test_rejects_near_polar_origin(lat0):
    """극 근방 원점은 동서 스케일이 발산한다 — 거대한 경도를 조용히 내지 않고 거부한다."""
    with pytest.raises(ValueError, match="접평면"):
        local_scales(lat0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_rejects_nonfinite(bad):
    with pytest.raises(ValueError):
        local_scales(bad)
    with pytest.raises(ValueError):
        local_scales(LAT0, bad)


# ---- 웹 구현과의 공유 고정점 ----

def test_fixture_matches_this_implementation(fixture):
    """`data/geodesy-fixture.json`이 이 구현과 일치한다.

    같은 파일을 `web/js/lib/geo.test.js`가 읽는다 — 이 테스트와 그쪽이 함께 통과해야만
    두 구현이 같은 수를 낸다. 고정점을 고칠 일이 생기면 엔진에서 재생성하고 웹 테스트를
    돌려 볼 것.
    """
    o = fixture["origin"]
    lat0, lon0 = math.radians(o["lat_deg"]), math.radians(o["lon_deg"])
    tol_m = fixture["_tolerance_m"]
    for blk in fixture["blocks"]:
        h_ref = blk["h_ref"]
        m_north, m_east = local_scales(lat0, h_ref)
        assert m_north == pytest.approx(blk["local_scales"]["north_m_per_rad"], rel=1e-12)
        assert m_east == pytest.approx(blk["local_scales"]["east_m_per_rad"], rel=1e-12)
        for case in blk["cases"]:
            lat, lon = ned_to_geodetic(case["n"], case["e"], lat0, lon0, h_ref)
            # 각도 오차를 미터로 환산해 비교한다 — 허용오차가 거리 단위여야 뜻이 있다
            d_north = (lat - math.radians(case["lat_deg"])) * m_north
            d_east = (lon - math.radians(case["lon_deg"])) * m_east
            assert abs(d_north) < tol_m, f"h_ref={h_ref} n={case['n']} 북 오차 {d_north} m"
            assert abs(d_east) < tol_m, f"h_ref={h_ref} e={case['e']} 동 오차 {d_east} m"


def test_fixture_pins_h_ref(fixture):
    """고정점이 **h_ref를 실제로 묶는지** — 0인 블록만 두면 그 인자가 사각지대가 된다.

    서버는 h_ref로 활주로 표고를 실어 보내므로 죽은 인자가 아니다. 블록들이 서로 다른
    수를 내야 h_ref를 빠뜨린 구현이 고정점 대조에서 걸린다(리뷰의 변이시험 지적).
    """
    heights = [blk["h_ref"] for blk in fixture["blocks"]]
    assert any(h != 0 for h in heights), "h_ref가 0인 블록뿐이면 그 인자를 검증하지 못한다"
    norths = {blk["local_scales"]["north_m_per_rad"] for blk in fixture["blocks"]}
    assert len(norths) == len(fixture["blocks"]), "블록마다 스케일이 달라야 대조가 뜻이 있다"


def test_fixture_covers_all_sign_combinations(fixture):
    """고정점이 네 사분면을 다 덮는다 — 부호 실수는 한 사분면만 보면 안 잡힌다."""
    for blk in fixture["blocks"]:
        quadrants = {(case["n"] >= 0, case["e"] >= 0) for case in blk["cases"]}
        assert quadrants == {(True, True), (True, False), (False, True), (False, False)}
