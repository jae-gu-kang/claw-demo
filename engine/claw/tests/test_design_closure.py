"""M17 closure 검증 — 레이트 필터 상태 증강 (01 §2.6·§4.2).

법칙에 실제로 있는 레이트 필터(데모 요축 워시아웃 τ=2 s)를 지표 경로가 보게 하는
변경의 회귀 고정. 핵심 불변식 둘:
- 필터 상태는 **뒤에 붙는다** — 물리 상태 인덱스가 밀리면 이름 조회를 쓰는 소비자
  (make_siso·axis_metrics·roll_real_mode)가 조용히 다른 상태를 읽는다.
- 1차 필터 극은 **지표 선별을 안 건드린다** — 워시아웃 극은 floor 아래, 저역통과
  극은 실근이라 ζ 복소쌍에 안 든다. 이 성질이 깨지면 노치처럼 거부해야 한다.
"""

import numpy as np
import pytest

from claw.analysis.modes import damp
from claw.common.contracts import TrimCase
from claw.design.closure import axis_metrics, close_rates, wn_reference
from claw.plant import make_demo_aircraft
from claw.trim import linearize, split_axes, trim_level

RATES = {"yaw.k_rate": 0.8, "roll.k_rate": -0.2}
WASHOUT = {"yaw": {"kind": "washout", "tau": 2.0}}  # 데모 DEMO_YAW 그대로


@pytest.fixture(scope="module")
def lat_axes():
    ac = make_demo_aircraft()
    out = {}
    for mach, alt in ((0.3, 0.0), (0.6, 1000.0)):
        tr = trim_level(ac, TrimCase("t", mach=mach, alt=alt, fuel=200.0))
        assert tr.converged
        out[(mach, alt)] = split_axes(linearize(ac, tr))[1]
    return out


def test_filter_state_is_appended_not_inserted(lat_axes):
    """증강은 뒤에만 붙는다 — 물리 상태 인덱스 불변이 이름 조회의 전제다."""
    lat = lat_axes[(0.6, 1000.0)]
    base = close_rates(lat, RATES)
    aug = close_rates(lat, RATES, WASHOUT)

    assert tuple(base.x_names) == tuple(lat.x_names)
    assert tuple(aug.x_names) == tuple(lat.x_names) + ("yaw_filt",)
    for name in lat.x_names:  # 물리 상태 인덱스가 하나도 안 밀렸다
        assert aug.x_names.index(name) == lat.x_names.index(name), name
    # 행렬 모양이 함께 늘어야 make_siso(A, B, C)가 성립한다
    n = len(lat.x_names)
    assert aug.A.shape == (n + 1, n + 1)
    assert aug.B.shape == (n + 1, lat.B.shape[1])
    assert aug.C.shape == (lat.C.shape[0], n + 1)
    # 필터 상태는 외부 입력이 직접 몰지 않는다 (피드백 경로 안에만 있다)
    assert np.allclose(aug.B[n, :], 0.0)


def test_filter_absent_paths_are_byte_identical(lat_axes):
    """필터 미지정·"none"·댐퍼 꺼짐 — 셋 다 기존 A′ 그대로 (하위호환 핀)."""
    lat = lat_axes[(0.6, 1000.0)]
    base = close_rates(lat, RATES)
    for filters in (None, {}, {"yaw": {"kind": "none"}}):
        assert np.array_equal(close_rates(lat, RATES, filters).A, base.A), filters
    # 댐퍼가 0인 자리는 필터를 줘도 루프에 없다 — 상태를 만들지 않는다
    off = close_rates(lat, {"yaw.k_rate": 0.0, "roll.k_rate": -0.2}, WASHOUT)
    assert "yaw_filt" not in off.x_names
    # 같은 이유로 **노치도 거부하지 않는다** — 종류를 따지기 전에 루프에 없다.
    # (거부 검사를 k==0 위로 되돌리면 여기서 걸린다)
    close_rates(lat, {"yaw.k_rate": 0.0, "roll.k_rate": -0.2},
                {"yaw": {"kind": "notch", "f0": 4.4, "q": 2.0}})


def _added_mode_wn(lat, filters):
    """증강으로 **새로 생긴** 모드의 wn — 기저 고유치에 그리디 매칭해 남는 하나.

    "floor 아래 모드가 있다"만 보면 기저에 이미 있는 나선(wn 0.05)이 늘 걸려
    단정이 공허해진다. 새 극을 지목해야 τ가 틀렸을 때 실패한다.
    """
    base = list(np.linalg.eigvals(close_rates(lat, RATES).A))
    aug = list(np.linalg.eigvals(close_rates(lat, RATES, filters).A))
    assert len(aug) == len(base) + 1
    for b in base:  # 기저 극을 하나씩 소거
        aug.pop(min(range(len(aug)), key=lambda i: abs(aug[i] - b)))
    return abs(aug[0])


def test_washout_pole_sits_below_the_metric_floor(lat_axes):
    """워시아웃이 **새로 넣는 극**(1/τ=0.5 rad/s)이 floor 아래다 — 지표 선별에 안 든다.

    이 성질 덕에 lon_metrics/lat_metrics를 안 고치고 증강할 수 있다. τ가 작아지면
    (극이 빨라지면) 그 전제가 깨지고 극이 강체 모드와 섞인다 — 아래 두 번째
    단정이 그 반대 경우를 직접 확인해, 이 테스트가 τ 오류에 반응함을 보인다.
    """
    lat = lat_axes[(0.3, 0.0)]
    floor = 0.4 * wn_reference(lat)
    added = _added_mode_wn(lat, WASHOUT)
    # 1/τ = 0.5가 **정확히** 나오지는 않는다 — 필터 상태가 플랜트와 결합해 극이
    # 옮겨간다(실측 0.671). 중요한 것은 그 극이 floor 아래에 남는다는 성질이다
    assert added == pytest.approx(0.671, abs=5e-3), f"새 극 위치가 움직였다: {added}"
    assert added < floor, f"워시아웃 극 {added:.3f}이 floor {floor:.3f} 위 — 지표를 오염시킨다"
    # τ를 100분의 1로 줄이면 극이 50 rad/s로 올라가 floor 위 — 전제가 깨지는 조건이
    # 실제로 검출되는지 (이 단정이 없으면 위 단정이 τ와 무관하게 통과할 수 있다)
    fast = _added_mode_wn(lat, {"yaw": {"kind": "washout", "tau": 0.02}})
    assert fast > floor, "τ를 줄여도 극이 floor 아래 — 이 테스트는 τ를 안 보고 있다"


def test_lowpass_pole_is_real_so_zeta_pairs_are_untouched(lat_axes):
    """저역통과 극은 실근 — ζ_dr가 모으는 **복소쌍**에 애초에 안 든다."""
    lat = lat_axes[(0.3, 0.0)]
    lp = {"yaw": {"kind": "lowpass", "fc": 5.0}}
    base_pairs = [m for m in damp(close_rates(lat, RATES).A) if m["eig"].imag > 1e-9]
    aug_pairs = [m for m in damp(close_rates(lat, RATES, lp).A) if m["eig"].imag > 1e-9]
    assert len(aug_pairs) == len(base_pairs), "저역통과가 복소쌍을 새로 만들었다"


def test_notch_is_refused_with_a_reason(lat_axes):
    """노치는 f0 복소쌍이 floor 위에 들어와 ζ_dr를 오염시킨다 — 조용히 무시하지 않는다.

    (마진 평가는 pi_loop 경유로 여전히 가능하다 — 거부되는 것은 이 지표 경로뿐.)
    """
    lat = lat_axes[(0.6, 1000.0)]
    with pytest.raises(ValueError, match="노치"):
        close_rates(lat, RATES, {"yaw": {"kind": "notch", "f0": 4.4, "q": 2.0}})


def test_washout_raises_dutch_roll_damping_where_the_pair_survives(lat_axes):
    """요축 워시아웃 반영 전후 실측 — 종전 해석은 이 자리를 **비관적으로** 보고 있었다.

    워시아웃은 더치롤 대역에서 위상 **진상**이 크고(τ=2, ω=1 rad/s에서 +26.6°,
    |H|=0.894) 감쇠 손실은 작아 ζ_dr를 올린다. 실측:

        M0.3/h0    ζ_dr 0.5951 → 0.6612   (+11%)
        M0.6/h1000 ζ_dr 1.0000 → 1.0000   (더치롤이 이미 실근으로 갈라져 변화 없음)

    고주파에서는 워시아웃이 투과라(ω=16 rad/s에서 |H|=1.000) 롤 대역폭은 사실상
    불변이다 — M0.6/h1000 roll_λ 16.5945 → 16.5947.
    """
    lat = lat_axes[(0.3, 0.0)]
    m0 = axis_metrics(lat, RATES)
    m1 = axis_metrics(lat, RATES, WASHOUT)
    assert m0["zeta_dr"] == pytest.approx(0.5951, abs=5e-3)
    assert m1["zeta_dr"] == pytest.approx(0.6612, abs=5e-3)
    assert m1["zeta_dr"] > m0["zeta_dr"], "워시아웃 반영이 감쇠를 낮췄다 — 위상 진상 전제 재검토"

    hi = lat_axes[(0.6, 1000.0)]
    r0, r1 = axis_metrics(hi, RATES), axis_metrics(hi, RATES, WASHOUT)
    assert r1["roll_lambda"] == pytest.approx(r0["roll_lambda"], rel=1e-4), (
        "롤 대역(≫코너)에서 워시아웃은 투과여야 한다"
    )


def test_demo_rate_filters_matches_the_assembled_law():
    """프로파일이 내는 필터 스펙 = 법칙이 실제로 조립하는 것 — 정본이 갈리면 안 된다.

    자동 설계는 `demo_rate_filters()`를 보고 튜닝·검증하는데, 그 값이 DEMO_* 프로파일
    (=`make_demo_fcl`이 조립하는 값)과 어긋나면 **출하되지 않는 조성**을 검증하게 된다.
    `washout_tau == 0`은 목록에서 빠져야 한다 — graphs.py가 0이면 노드를 아예 안
    만들므로, 여기 남기면 해석이 법칙에 없는 필터를 만들어 내는 것이 된다.
    """
    from claw.blocks.filters import RATE_FILTERS
    from claw.fcl.demo import DEMO_PITCH, DEMO_ROLL, DEMO_YAW, demo_rate_filters

    got = demo_rate_filters()
    assert got == {"yaw": {"kind": "washout", "tau": DEMO_YAW["washout_tau"]}}
    assert DEMO_PITCH.get("washout_tau", 0.0) == 0.0  # 목록에 없는 이유
    assert DEMO_ROLL.get("washout_tau", 0.0) == 0.0
    for spec in got.values():  # 어휘 정본 밖의 종류를 만들지 않는다
        assert spec["kind"] in RATE_FILTERS


def test_augmented_state_space_matches_an_independent_tf_closure(lat_axes):
    """증강 A′의 고유치 == 전달함수로 닫은 폐루프 극 — 구현 독립 검증.

    상태 증강은 부호·행 배치를 틀리기 쉽고, 틀리면 "지표가 나빠졌다"로 조용히
    보고된다(그게 정상 결과처럼 보인다). 그래서 같은 물리를 **다른 경로**로 짜서
    맞춘다: `pi_loop(rate_filter=...)`의 TF 캐스케이드를 양의 되먹임으로 닫은 극
    (물리 댐퍼 u = +k·rate → 특성식 1 − L, tune._damper_loop_stable과 같은 규약).
    """
    import control

    from claw.analysis import pi_loop

    lat = lat_axes[(0.6, 1000.0)]
    k = 0.8
    for filt in (None, {"kind": "washout", "tau": 2.0}):
        aug = close_rates(lat, {"yaw.k_rate": k}, {"yaw": filt} if filt else None)
        ss = np.sort_complex(np.linalg.eigvals(aug.A))
        tf = np.sort_complex(control.feedback(
            pi_loop(lat, x_out="r", u_in="dr", kp=k, ki=0.0, sign=1.0, rate_filter=filt),
            1, sign=1).poles())
        assert len(ss) == len(tf), f"{filt}: 극 개수 불일치"
        for p in ss:
            assert np.min(np.abs(tf - p)) < 1e-6, f"{filt}: {p}에 대응하는 TF 극이 없다"


def test_washout_returns_the_spiral_the_yaw_damper_was_moving(lat_axes):
    """워시아웃은 나선 주파수에서 요 댐퍼 권한을 사실상 없앤다 — 그게 워시아웃의 목적이다.

    실측(M0.6/h1000, k_rate 0.8): 요 댐퍼만 닫았을 때 느린 실근이
        필터 없음 −2.2447  →  워시아웃 반영 −0.0032
    로, 개루프 나선 자리로 되돌아온다. |H(0.05 rad/s)| ≈ 0.1이라 저주파에서 댐퍼가
    거의 안 먹기 때문이고, 워시아웃은 정상선회에서 댐퍼가 버티지 않게 하려고 바로
    그러라고 넣은 것이다 (01 §3.1).

    이 사실이 롤 댐퍼까지 번진다 — 롤은 **요를 닫은 뒤** 튜닝되는데(AXIS_SPECS 순서),
    그 조성에 느린 나선근이 남아 있으면 안정 캡이 |k|를 깎는다
    (test_design_tune.test_raw_axis_is_the_wrong_stability_plant가 기록한 그 경로다).
    """
    lat = lat_axes[(0.6, 1000.0)]
    slow = lambda A: max(  # noqa: E731 — 0에 가장 가까운 실근
        (p for p in np.linalg.eigvals(A) if abs(p.imag) < 1e-9), key=lambda p: p.real)
    without = slow(close_rates(lat, {"yaw.k_rate": 0.8}).A).real
    with_wo = slow(close_rates(lat, {"yaw.k_rate": 0.8}, WASHOUT).A).real
    assert without == pytest.approx(-2.2447, abs=1e-3)
    assert with_wo == pytest.approx(-0.0032, abs=1e-3)
    assert with_wo > without, "워시아웃을 넣었는데 저주파 댐퍼 권한이 늘었다 — 부호 확인"


def test_rate_filters_reach_the_tuner_and_change_the_design():
    """`rate_filters`가 tune_point까지 실제로 흘러 **설계 결과를 바꾼다** — 배선 핀.

    이 배선은 네 손을 거친다: 라우트 → `DesignSession.run` → `_act_kw` →
    `tune_point`/`close_rates`. 어느 하나만 빠져도 자동 설계는 조용히 **출하되지
    않는 플랜트**(요 댐퍼에 워시아웃이 없는 A′)를 상대로 튜닝하는데, 그때도 기존
    테스트는 전부 통과한다 — 그래서 결과 수치로 직접 못박는다.

    실측 (작동기 wn 30·ζ 0.7·지연 0.035 s):
        M0.3/h0     roll.k_rate −0.5225(ok) → 0.0000(no_stable_gain), λ 12.000 → 2.322
        M0.6/h1000  roll.k_rate −0.1416(ok) → −0.0482(capped),        λ 12.000 → 4.740

    원인은 test_washout_returns_the_spiral_the_yaw_damper_was_moving가 고정한 것 —
    워시아웃이 나선 주파수에서 요 댐퍼 권한을 없애고, 롤은 요를 닫은 뒤 튜닝되므로
    남은 나선근이 안정 캡을 문다. 종전 λ 12.0 달성이 **없는 권한에 기대고 있었다.**
    """
    from claw.design.tune import tune_point
    from claw.fcl.demo import demo_design_gains, demo_rate_filters
    from claw.trim import trim_level

    ac = make_demo_aircraft()
    design = demo_design_gains()
    act = dict(actuator_wn=30.0, actuator_zeta=0.7, delay_s=0.035, pade_order=2)
    expected = {  # (mach, alt): (필터 없음 k, 반영 k, 반영 사유, 반영 λ)
        (0.3, 0.0): (-0.5225, 0.0, "no_stable_gain", 2.322),
        (0.6, 1000.0): (-0.1416, -0.0482, "capped", 4.740),
    }
    for (mach, alt), (k0, k1, reason, lam) in expected.items():
        lm = linearize(ac, trim_level(ac, TrimCase("t", mach=mach, alt=alt, fuel=200.0)))
        without = tune_point(lm, design, **act)
        with_f = tune_point(lm, design, **act, rate_filters=demo_rate_filters())
        tag = f"M{mach}/h{alt:.0f}"
        assert without["gains"]["roll.k_rate"] == pytest.approx(k0, abs=5e-3), tag
        assert without["slots"]["roll_rate"]["reason"] == "ok", tag
        assert with_f["gains"]["roll.k_rate"] == pytest.approx(k1, abs=5e-3), tag
        assert with_f["slots"]["roll_rate"]["reason"] == reason, tag
        assert with_f["achieved"]["roll_rate"]["roll_lambda"] == pytest.approx(lam, abs=5e-3), tag


def test_session_round_trips_rate_filters():
    """세션 직렬화가 `rate_filters`를 왕복한다 — 재개가 필터 없는 플랜트로 안 돌아간다.

    이 모듈(orchestrator) 머리말이 `to_dict/from_dict 완전 왕복`을 잡 취소·gated
    재개·서버 저장의 전제로 선언한다. `design`은 왕복하는데 그 짝인 rate_filters가
    빠지면, 재개한 세션만 다른 플랜트를 보게 되고 그 차이는 결과 수치로만 드러난다.

    `run(rate_filters=None)`은 "안 바꾼다"다 — 재개 호출이 인자를 생략해도 저장된
    값을 이어간다 (덮어쓰면 왕복이 있으나 마나다).
    """
    from claw.design.orchestrator import DesignSession
    from claw.fcl.demo import demo_rate_filters

    s = DesignSession()
    assert s.rate_filters == {}, "__init__이 초기화하지 않으면 getattr 방어에 기대게 된다"
    s.rate_filters = demo_rate_filters()

    d = s.to_dict()
    assert d["rate_filters"] == demo_rate_filters()
    restored = DesignSession.from_dict(d)
    assert restored.rate_filters == s.rate_filters
    assert restored._act_kw()["rate_filters"] == s.rate_filters

    # run(rate_filters=None)이 **덮지 않는다** — 이게 왕복의 값어치다. 덮으면
    # 복원해 놓고 첫 재개에서 도로 비운다. awaiting_approval은 대입 직후 조기
    # 반환하므로 모델 없이도 이 규약만 확인할 수 있다
    restored.status = "awaiting_approval"
    restored.run(None, None, None, None, {})
    assert restored.rate_filters == demo_rate_filters(), "재개가 저장된 필터를 지웠다"
    # 비우려면 빈 dict를 **명시**한다 (None과 다른 뜻)
    restored.status = "awaiting_approval"
    restored.run(None, None, None, None, {}, rate_filters={})
    assert restored.rate_filters == {}
