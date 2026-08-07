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
    assert de == pytest.approx(-0.004, abs=0.01)
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
    assert all(r.flags["continuity_ok"] for r in results)
    assert all(r.params_fingerprint == "abc123" for r in results)
    # 물리 경향: 같은 고도에서 마하 증가 → 동압 증가 → 트림 α 감소
    alphas = [r.state.euler()[1] for r in results[:5]]
    assert all(a1 > a2 for a1, a2 in zip(alphas, alphas[1:]))


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
