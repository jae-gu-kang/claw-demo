"""M9 trim 검증 — 데모 델타윙 수평정상비행 트림: 잔차·해석 근사 대조·판정 플래그·배치 시드."""

import numpy as np
import pytest

from claw.common.contracts import TrimCase
from claw.plant import XE_H, XE_Q, XE_THETA, XE_U, XE_W, make_demo_aircraft
from claw.trim import trim_batch, trim_level


@pytest.fixture(scope="module")
def ac():
    return make_demo_aircraft()


def test_level_trim_converges_and_balances(ac):
    tr = trim_level(ac, TrimCase("cruise", mach=0.7, alt=1000.0, fuel=200.0))
    assert tr.converged
    alpha = tr.state.euler()[1]  # 수평비행 θ = α
    de = tr.control.elevon[0]
    thr = tr.control.throttle[0]
    # 해석 근사 (선형 계수 손계산): α≈0.0302, δe≈-0.004, thr≈0.27
    assert alpha == pytest.approx(0.0302, abs=0.005)
    assert de == pytest.approx(-0.004, abs=0.005)
    assert thr == pytest.approx(0.27, abs=0.05)
    # 잔차 직접 확인: 트림 상태에서 u̇·ẇ·q̇ ≈ 0, ḣ = 0 (구성상)
    xe = np.zeros(12)
    xe[XE_U], xe[XE_W] = tr.state.vel_b[0], tr.state.vel_b[2]
    xe[XE_THETA], xe[XE_H] = alpha, 1000.0
    xd = ac.deriv_euler(xe, {"de": de, "da": 0.0, "dr": 0.0, "throttle": (thr, thr)}, 200.0)
    assert abs(xd[XE_U]) < 1e-4 and abs(xd[XE_W]) < 1e-4 and abs(xd[XE_Q]) < 1e-4
    assert abs(xd[XE_H]) < 1e-9
    assert tr.flags["residual_ok"] and tr.flags["saturation_ok"] and tr.flags["alpha_margin_ok"]


def test_infeasible_case_flagged(ac):
    """저속 저동압 — 요구 CL이 α 한계 밖 → 수렴 실패 또는 잔차 플래그로 드러나야 함."""
    tr = trim_level(ac, TrimCase("slow", mach=0.12, alt=100.0, fuel=400.0))
    assert not (tr.converged and tr.flags["residual_ok"] and tr.flags["alpha_margin_ok"])


def test_trim_batch_seed_and_continuity(ac):
    # 서펜타인 순서 — 리스트상 인접 케이스가 물리적으로도 인접하도록 (시드·연속성 판정 전제)
    machs = (0.4, 0.5, 0.6, 0.7, 0.8)
    cases = [TrimCase(f"m{m:.1f}_h100", mach=m, alt=100.0, fuel=200.0) for m in machs] + [
        TrimCase(f"m{m:.1f}_h3000", mach=m, alt=3000.0, fuel=200.0) for m in reversed(machs)
    ]
    results = trim_batch(ac, cases, fingerprint="abc123")
    assert all(r.converged for r in results)
    assert results[0].flags["continuity_ok"] is None  # 첫 케이스 = 미판정 (합격 아님)
    assert all(r.flags["continuity_ok"] is True for r in results[1:])
    assert all(r.params_fingerprint == "abc123" for r in results)
    # 물리 경향: 같은 고도에서 마하 증가 → 동압 증가 → 트림 α 감소
    alphas = [r.state.euler()[1] for r in results[:5]]
    assert all(a1 > a2 for a1, a2 in zip(alphas, alphas[1:]))


def test_flag_false_paths(ac):
    """판정 플래그의 탐지 방향 고정 — 각 플래그가 실제로 False를 낼 수 있는지."""
    # 연속성: 물리적으로 인접하지 않은 케이스 점프 → False
    jump = trim_batch(
        ac,
        [TrimCase("a", 0.4, 100.0, 200.0), TrimCase("b", 0.8, 100.0, 200.0)],
    )
    assert jump[1].flags["continuity_ok"] is False
    # α 여유: 저속·최대중량 — 해가 α 상한으로 몰려 여유 침범 (수렴 여부와 무관한 판정)
    tr = trim_level(ac, TrimCase("higha", mach=0.15, alt=100.0, fuel=400.0))
    assert tr.flags["alpha_margin_ok"] is False
    # 포화: 약한 엔진 → 스로틀 한계 도달
    from claw.plant import TwinEngine

    ac_weak = make_demo_aircraft()
    ac_weak.engine = TwinEngine(max_thrust=800.0, y_offset=0.5)
    tr2 = trim_level(ac_weak, TrimCase("weak", mach=0.7, alt=1000.0, fuel=200.0))
    assert tr2.flags["saturation_ok"] is False


def test_trim_batch_progress_callback(ac):
    """진행 콜백 (M13 서버 진행률 경로) — 케이스마다 (done, total, 결과) 호출."""
    cases = [TrimCase(f"m{m:.1f}", mach=m, alt=1000.0, fuel=200.0) for m in (0.5, 0.6, 0.7)]
    calls = []

    def on_progress(done, total, tr):
        calls.append((done, total, tr.case.name))
        return False

    results = trim_batch(ac, cases, on_progress=on_progress)
    assert len(results) == 3
    assert [(d, t) for d, t, _ in calls] == [(1, 3), (2, 3), (3, 3)]
    assert [name for _, _, name in calls] == [c.name for c in cases]


def test_trim_batch_progress_cancel(ac):
    """콜백 truthy 반환 = 협조적 취소 — 부분 결과 반환 (M13 작업 취소 경로)."""
    cases = [TrimCase(f"m{m:.1f}", mach=m, alt=1000.0, fuel=200.0) for m in (0.5, 0.6, 0.7)]
    results = trim_batch(ac, cases, on_progress=lambda done, total, tr: done >= 2)
    assert len(results) == 2
    assert all(r.converged for r in results)


def test_euler_deriv_consistency_with_quaternion_path(ac):
    """euler 표현 deriv와 쿼터니언 경로(RigidBody용 fm)의 힘 일관성 — u̇ 성분 대조."""
    xe = np.zeros(12)
    xe[XE_U], xe[XE_W], xe[XE_THETA], xe[XE_H] = 200.0, 8.0, 0.06, 1500.0
    controls = {"de": -0.01, "da": 0.0, "dr": 0.0, "throttle": (0.4, 0.4)}
    xd = ac.deriv_euler(xe, controls, 150.0)
    from claw.common.attitude import euler_to_quat

    F, M, m, _ = ac.fm(
        vel_b=np.array([200.0, 0.0, 8.0]),
        omega_b=np.zeros(3),
        q_nb=euler_to_quat(0.0, 0.06, 0.0),
        h=1500.0,
        controls=controls,
        fuel=150.0,
    )
    assert xd[XE_U] == pytest.approx(F[0] / m, rel=1e-12)


def test_saturation_detail_matches_saturation_ok(ac):
    """saturation_detail이 트림이 판정한 것과 같은 채널(elevon[0]·throttle[0])을 읽는다.

    두 쪽 다 _saturation_channels를 부르므로 식 자체의 회귀는 여기서 안 잡힌다
    (식은 test_level_trim_* 의 ok/포화 핀이 지킨다) — 이 테스트가 지키는 것은
    TrimResult 필드 추출 경로의 일치다 (detail이 다른 타면·엔진 값을 읽으면 실패)."""
    from claw.trim import saturation_detail

    cases = [
        TrimCase("cruise", mach=0.7, alt=1000.0, fuel=200.0),
        TrimCase("slow", mach=0.12, alt=100.0, fuel=400.0),  # 저속 저동압 — 포화 유도
        TrimCase("high", mach=0.4, alt=5000.0, fuel=400.0),
    ]
    for tr in trim_batch(ac, cases):
        det = saturation_detail(tr)
        assert set(det) == {"de", "throttle_high", "throttle_low"}
        assert tr.flags["saturation_ok"] == (not any(det.values())), tr.case.name
