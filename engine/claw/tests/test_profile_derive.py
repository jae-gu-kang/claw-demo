"""δe_trim 표 도출 — 검사 격자에서 요구를 밑도는 점이 없다는 성질, 그리고 낡은 표를 쓰지 않는다 (02 §5.6.1)."""

import copy

import pytest

from claw.fcl.assemble import assemble_law
from claw.profile import ProfileError, build_profile, load_example
from claw.profile.derive import DERIVE_SOURCE, REASON_NO_REQUIREMENT, derive_de_trim

FAST = dict(alts=(0.0, 3000.0), fuel_fracs=(0.5, 1.0), check_step=0.02)


@pytest.fixture(scope="module")
def derived():
    built = build_profile(load_example())
    return built, derive_de_trim(built, **FAST)


def test_derived_table_covers_the_requirement_on_the_check_grid(derived):
    """값 일치가 아니라 성질 — 표 보간이 검사 격자의 모든 요구 이상이다. 마하 격자는 요구영역(구 기체는 trim_grid 초안
    M0.3~0.55)의 기본 격자 공통 좌표다 — 이관 9단계 전에는 문서 표의 격자를 이어 썼다."""
    built, out = derived
    assert out["ok"], out["reason"]
    table = out["alloc"]["de_trim"]["table"]
    assert set(table["axes"]["mach"]) <= {0.3, 0.35, 0.4, 0.45, 0.5, 0.55}
    assert out["alloc"]["de_trim"]["provenance"]["grid_source"] == "region"
    req = out["requirement"]
    assert len(req["mach"]) >= 12  # 요구영역 M0.3~0.55를 0.02 간격 — 종전 문서 격자(M0.2~0.6)면 20점 이상이었다
    assert all(h >= n - 1e-12 for h, n in zip(req["have"], req["need"]))
    prov = out["alloc"]["de_trim"]["provenance"]
    assert prov["source"] == DERIVE_SOURCE and prov["shortfall"] == 0 and prov["plant_fingerprint"] == built.plant_fingerprint
    assert out["alloc"]["resv_frac"] == built.doc["law"]["alloc"]["resv_frac"]  # 문서 값을 그대로 둔다
    # 요구는 동압에 반비례한다 — 저속 끝이 고속 끝보다 크다
    assert table["data"][0] > table["data"][-1] > 0.0


def test_derived_table_assembles_until_the_plant_changes(derived):
    _, out = derived
    doc = load_example()
    doc["law"]["alloc"] = out["alloc"]
    built = build_profile(doc)
    assert built.de_trim_stale is False
    assert built.alloc_trim_table().name == "de_trim"
    assemble_law(built)

    heavier = copy.deepcopy(doc)
    heavier["mass"]["m_empty"] *= 1.1
    stale = build_profile(heavier)
    assert stale.de_trim_stale is True
    with pytest.raises(ProfileError) as e:
        assemble_law(stale)
    assert e.value.path == "/law/alloc/de_trim"
    # 게인만 고치면 플랜트 지문이 그대로라 표는 낡지 않는다
    tuned = copy.deepcopy(doc)
    tuned["law"]["design"]["scas"]["pitch"]["kp"] *= 1.2
    assert build_profile(tuned).de_trim_stale is False
    # 손으로 넣은 표(explicit)는 대조할 기록이 없어 낡았다고 하지 않는다
    assert build_profile(dict(load_example(), mass=heavier["mass"])).de_trim_stale is False


def test_derivation_says_why_it_has_no_table():
    doc = load_example()
    doc["mass"]["m_empty"] *= 40.0
    out = derive_de_trim(build_profile(doc), machs=(0.3, 0.5), alts=(0.0,), fuel_fracs=(1.0,), check_step=0.1)
    assert (out["ok"], out["reason"], out["alloc"]) == (False, REASON_NO_REQUIREMENT, None)


def test_derived_table_covers_plant_changing_variants_and_goes_stale_only_for_new_plants():
    """형상 변형이 플랜트를 바꾸면 도출이 그 변형까지 재어 최악을 취한다 — 변형을 고르면 막히던 결함의 회귀 방지.

    도출 뒤에 새 플랜트 변형을 더하면 그 변형만 낡는다(기본 문서·잰 변형은 그대로 조립된다)."""
    doc = load_example()
    doc.update(id="variants", is_example=False)
    doc["variants"] = [{"id": "heavy", "name": "무거움", "patch": {"/mass/m_empty": doc["mass"]["m_empty"] * 1.05}},
                       {"id": "renamed", "name": "이름만", "patch": {"/description": "플랜트 그대로"}}]
    base = build_profile(doc)
    variants = [build_profile(doc, v["id"]) for v in doc["variants"]]
    out = derive_de_trim(base, variants=variants, **FAST)
    prov = out["alloc"]["de_trim"]["provenance"]
    assert prov["configurations"] == ["base", "heavy"]  # 플랜트가 같은 변형은 다시 재지 않는다
    assert prov["plant_fingerprints"] == [base.plant_fingerprint, variants[0].plant_fingerprint]
    # 요구는 형상마다의 최악이다 — 기본 문서만 잰 요구 이상이고, 표는 그 합친 요구를 검사 격자에서 덮는다.
    # (표 값 자체는 점마다 크다고 할 수 없다: 요구가 커진 끝점이 기본 문서 도출에서 필요했던 구간 보정을 없앨 수 있다)
    alone = derive_de_trim(base, **FAST)["requirement"]
    need = dict(zip(out["requirement"]["mach"], out["requirement"]["need"]))
    assert set(alone["mach"]) <= set(need)
    assert all(need[m] >= n - 1e-12 for m, n in zip(alone["mach"], alone["need"]))
    assert any(need[m] > n + 1e-9 for m, n in zip(alone["mach"], alone["need"]))  # 무거운 변형이 실제로 요구를 올린다
    assert all(h >= n - 1e-12 for h, n in zip(out["requirement"]["have"], out["requirement"]["need"]))

    doc["law"]["alloc"] = out["alloc"]
    for vid in (None, "heavy", "renamed"):
        built = build_profile(doc, vid)
        assert built.de_trim_stale is False, vid
        assemble_law(built)
    doc["variants"].append({"id": "heavier", "name": "더 무거움", "patch": {"/mass/m_empty": doc["mass"]["m_empty"] * 1.2}})
    assert build_profile(doc, "heavier").de_trim_stale is True
    assert build_profile(doc).de_trim_stale is False


def test_derivation_keeps_to_the_operating_altitudes_and_trims_at_the_ceiling():
    """운용 범위 밖 고도는 재지 않고, 격자 사이에 있는 상한은 반드시 잰다 — 1g 요구가 가장 큰 곳이 상한이다.
    요구영역이 없는 기체의 규칙이다(있으면 검사 고도는 요구영역 기본 격자 — 이관 9단계)."""
    doc = load_example()
    doc["mission_template"] = None  # trim_grid 초안도 없는 기체 — 요구영역 미정의
    doc["operating"]["alt_max"] = 1000.0
    out = derive_de_trim(build_profile(doc), machs=(0.3, 0.5), fuel_fracs=(1.0,), check_step=0.1)
    assert out["alloc"]["de_trim"]["provenance"]["alts"] == [0.0, 500.0, 1000.0]

    doc["operating"].update(alt_min=200.0, alt_max=2900.0)
    built = build_profile(doc)
    assert built.alts_within((0.0, 500.0, 1000.0, 1500.0, 2000.0, 2500.0, 3000.0)) == [
        200.0, 500.0, 1000.0, 1500.0, 2000.0, 2500.0, 2900.0]
    assert build_profile(dict(doc, operating={"alt_min": 4000.0, "alt_max": 5000.0})).alts_within((0.0, 3000.0)) == [
        4000.0, 4500.0, 5000.0]
    # 상한에서 요구를 덮는다 — 격자 사이 상한(2900 m)이 빠지면 M0.30에서 표가 요구를 0.53° 밑돌았다
    out = derive_de_trim(built, machs=(0.3, 0.4), fuel_fracs=(1.0,), check_step=0.05)
    from claw.common.contracts import TrimCase
    from claw.trim import trim_level

    ac = built.aircraft()
    for m, have in ((0.3, out["alloc"]["de_trim"]["table"]["data"][0]), (0.4, out["alloc"]["de_trim"]["table"]["data"][1])):
        tr = trim_level(ac, TrimCase(name="ceiling", mach=m, alt=2900.0, fuel=doc["mass"]["fuel_max"]))
        if tr.converged and tr.flags["saturation_ok"]:
            assert have >= abs(float(tr.control.elevon[0])) - 1e-12


def test_derivation_drops_unflyable_ends_but_keeps_requirements_between_grid_points():
    """표가 없던 기체의 격자는 DB 마하 범위에서 잡혀 날 수 없는 마하(예: M0.05~0.15)를 포함한다 — 그 끝은 뺀다.
    다만 끝은 **요구가 있는 검사점**이 정한다: 격자점만 보고 자르면 잘린 격자점과 첫 요구 격자점 사이의 검사점
    요구가 버려진다(격자 0.1·0.3에서 M0.25 요구를 32 % 모자라게 답했다 — 리뷰 재현). 요구영역이 없는 기체의 격자 규칙이다
    (있으면 요구영역 마하 전 구간 — 이관 9단계)."""
    doc = load_example()
    doc["law"]["alloc"] = None
    doc["mission_template"] = None
    out = derive_de_trim(build_profile(doc), alts=(0.0,), fuel_fracs=(1.0,), check_step=0.05)
    assert out["ok"], out["reason"]
    table = out["alloc"]["de_trim"]["table"]
    prov = out["alloc"]["de_trim"]["provenance"]
    assert {0.05, 0.1, 0.75} <= set(prov["trimmed_machs"])
    req = out["requirement"]
    assert table["axes"]["mach"][0] <= req["mach"][0] and table["axes"]["mach"][-1] >= req["mach"][-1]
    assert all(h >= n - 1e-12 for h, n in zip(req["have"], req["need"]))

    coarse = derive_de_trim(build_profile(doc), machs=(0.1, 0.3, 0.45, 0.6, 0.7), alts=(0.0,), fuel_fracs=(1.0,),
                            check_step=0.05)
    assert coarse["ok"], coarse["reason"]
    cp = coarse["alloc"]["de_trim"]
    assert cp["table"]["axes"]["mach"][0] == 0.1 and 0.1 in cp["provenance"]["undefined_machs"]  # 0.25 요구를 덮으려 남긴다
    creq = coarse["requirement"]
    assert 0.25 in creq["mach"]
    assert all(h >= n - 1e-12 for h, n in zip(creq["have"], creq["need"]))



# ── 이관 9·10단계 — 도출 격자는 요구영역에서, 표가 덮는 것과 근거가 있는 것을 따로 적는다 ──────────────────────────
from claw.profile.derive import de_trim_coverage  # noqa: E402


def _confirmed(doc, mach=(0.1, 0.55), alt=(1000.0, 1000.0), fuel=(200.0, 200.0), n_mach=10):
    doc["operating_region"] = {"mach": list(mach), "alt": list(alt), "fuel": list(fuel), "boundary": None,
                               "base_grid": {"n_mach": n_mach, "alts": [alt[0]], "fuels": [fuel[0]]}}
    return doc


def test_without_explicit_args_the_check_grid_is_the_region_base_grid():
    built = build_profile(load_example())  # trim_grid 초안: M0.3~0.55 · 100/1000/3000 m · 200 kg
    out = derive_de_trim(built, check_step=0.05)
    prov = out["alloc"]["de_trim"]["provenance"]
    assert prov["alts"] == [100.0, 1000.0, 3000.0] and prov["fuels"] == [200.0]
    assert {k: prov["region"][k] for k in ("source", "confirmed")} == {"source": "draft:trim_grid", "confirmed": False}
    # 요구영역 전체의 기록 — 저장 표의 근거가 지금 요구영역에서 잰 것인지를 이것으로 가른다(de_trim_coverage)
    assert prov["region"]["alt"] == [100.0, 3000.0] and prov["region"]["grid"]["alts"] == [100.0, 1000.0, 3000.0]
    assert prov["excluded_by"].get("region", 0) == 0  # 초안은 판정에 쓰지 않는다(05 §11.2) — 요구영역 밖 제외 없음


def test_a_confirmed_region_beyond_the_flyable_range_is_reported_not_filled():
    """요구 M0.1~0.55 · 1000 m · 200 kg — 구 기체(1200 kg)는 저속 끝을 날지 못한다. 표의 축이 요구를 덮는 것과 그 구간의
    도출 근거가 있는 것은 다르다(05 §11.13 10단계): 근거 없는 요구 구간과 표 밖 구간을 따로 적는다."""
    built = build_profile(_confirmed(load_example()))
    out = derive_de_trim(built, alts=(0.0, 1000.0), fuel_fracs=(0.5,), check_step=0.05)
    assert out["ok"], out["reason"]
    prov = out["alloc"]["de_trim"]["provenance"]
    assert prov["excluded_by"]["region"] > 0  # 확정 영역 밖 조건(0 m)은 요구가 아니다 — 재지 않고 센다
    cov = prov["coverage"]
    assert cov["required_mach"] == [0.1, 0.55]
    axis = out["alloc"]["de_trim"]["table"]["axes"]["mach"]
    assert cov["table_mach"] == [axis[0], axis[-1]] and axis[0] > 0.1
    assert cov["unsupported"] and cov["unsupported"][0][0] == pytest.approx(0.1)
    assert cov["beyond_table"][0] == [0.1, axis[0]]
    assert cov["undefined_machs"] == prov["undefined_machs"]
    # 저장된 표의 커버리지 — 다시 도출하지 않고 같은 답
    doc = _confirmed(load_example())
    doc["law"]["alloc"] = out["alloc"]
    assert de_trim_coverage(build_profile(doc)) == {**cov, "basis": "derived", "basis_current": True, "stale": False}


def test_stored_table_coverage_does_not_reuse_a_basis_measured_for_another_region():
    doc = load_example()  # 문서 표(손으로 쓴 도출 기록) vs 초안 요구영역
    cov = de_trim_coverage(build_profile(doc))
    axis = doc["law"]["alloc"]["de_trim"]["table"]["axes"]["mach"]
    assert cov["required_mach"] == [0.3, 0.55] and cov["table_mach"] == [axis[0], axis[-1]]
    assert cov["basis_current"] is False and cov["unsupported"] is None  # 이 요구영역에서 잰 근거가 없다 — 모른다

    none = load_example()
    none["law"]["alloc"] = None
    assert de_trim_coverage(build_profile(none)) is None


def test_stored_basis_is_not_current_when_the_region_changes_with_the_same_mach_span():
    """요구 마하 구간이 같아도 고도·연료·경계표·확정·격자가 바뀌면 저장된 근거 없는 구간은 그 요구영역의 것이 아니다 —
    basis_current False · unsupported None(모른다). 마하 구간만 비교하던 때는 옛 근거를 지금 것으로 보였다."""
    built = build_profile(_confirmed(load_example()))
    out = derive_de_trim(built, alts=(0.0, 1000.0), fuel_fracs=(0.5,), check_step=0.05)
    doc = _confirmed(load_example())
    doc["law"]["alloc"] = out["alloc"]
    assert de_trim_coverage(build_profile(doc))["basis_current"] is True
    moved = _confirmed(load_example(), alt=(3000.0, 3000.0))  # 같은 M0.1~0.55, 다른 고도
    moved["law"]["alloc"] = out["alloc"]
    cov = de_trim_coverage(build_profile(moved))
    assert cov["required_mach"] == [0.1, 0.55]
    assert cov["basis_current"] is False and cov["unsupported"] is None
    # 영역 기록이 없는 옛 도출 기록도 모른다
    old = _confirmed(load_example())
    old["law"]["alloc"] = out["alloc"]
    old["law"]["alloc"]["de_trim"]["provenance"]["region"] = {"source": "profile", "confirmed": True}
    assert de_trim_coverage(build_profile(old))["basis_current"] is False


def test_region_mach_axis_matches_the_base_grid_coordinates_exactly():
    """표 절점이 기본 격자 좌표와 같은 값이어야 한다 — 반올림 자릿수가 다르면(6 대 9) 0.1333333 대 0.133333333으로 갈린다."""
    from claw.opspace import ModelRange, Region, base_grid
    from claw.profile.derive import region_mach_axis

    region = Region(mach=(0.1, 0.3), alt=(1000.0, 1000.0), fuel=(200.0, 200.0), boundary=None,
                    grid={"n_mach": 7, "alts": (1000.0,), "fuels": (200.0,)}, confirmed=True, source="profile")
    axis = region_mach_axis(region)
    assert axis == base_grid(region, ModelRange(mach=(0.0, 0.9), fuel=(0.0, 400.0)))["axis"]
    assert axis[1] == 0.133333333
