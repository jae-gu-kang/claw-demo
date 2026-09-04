"""M9 trim 검증 — 데모 델타윙 수평정상비행 트림: 잔차·해석 근사 대조·판정 플래그·배치 시드."""

import numpy as np
import pytest

from claw.common.contracts import TrimCase
from claw.plant import XE_H, XE_Q, XE_THETA, XE_U, XE_W, make_demo_aircraft
from claw.design.points import envelope_ok
from claw.trim import trim_batch, trim_level


@pytest.fixture(scope="module")
def ac():
    return make_demo_aircraft()


def test_level_trim_converges_and_balances(ac):
    tr = trim_level(ac, TrimCase("cruise", mach=0.4, alt=1000.0, fuel=200.0))
    assert tr.converged
    alpha = tr.state.euler()[1]  # 수평비행 θ = α
    de = tr.control.elevon[0]
    thr = tr.control.throttle[0]
    # 해석 근사 (선형 계수 손계산) — 기준 순항을 M0.7에서 **M0.4로 옮겼다**.
    # 프로펠러 추력 모델(T = δσ·min(T_static, ηP/V))로 가면서 비행 가능 상단이
    # 해면 M0.60으로 내려와 M0.7이 못 나는 조건이 됐기 때문이다 (plant/prop.py).
    #
    #   q̄ = ½ρV² = 10,074 Pa (V = 134.6 m/s, ρ_1000 = 1.112)
    #   CL = W/(q̄S) = 9,807/(10,074·3.0) = 0.3247
    #   Cm = 0 ⇒ δe = 0.02 − 0.8α, CL = 3.5α + 0.4δe ⇒ α = 0.0996, δe = −0.0597
    #   CD = 0.02 + 0.25·CL² = 0.0464 ⇒ D = 1,400 N
    #   T_avail(V, σ=0.908) = 0.908·0.8·500 kW/134.6 = 2,697 N ⇒ thr = 0.519
    # 실측 α 0.0982 · δe −0.0586 · thr 0.5134 (손계산과 1.4% 이내)
    assert alpha == pytest.approx(0.0996, abs=0.005)
    assert de == pytest.approx(-0.0597, abs=0.005)
    assert thr == pytest.approx(0.519, abs=0.05)
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
    # 격자는 **비행 가능 범위** 안이다 — 프로펠러 전환으로 상단이 해면 M0.60,
    # 3000 m M0.55로 내려왔다 (plant/prop.py PropEngine). 저마하 끝을 피한 것은
    # α ∝ 1/V²라 M0.25~0.30 사이에서 해가 급하게 움직여(0.222 → 0.156) 연속성
    # 판정이 걸리기 때문이다 — 격자 간격이 물리보다 성긴 것이지 해가 틀린 게 아니다
    machs = (0.35, 0.4, 0.45, 0.5, 0.55)
    cases = [TrimCase(f"m{m:.2f}_h100", mach=m, alt=100.0, fuel=200.0) for m in machs] + [
        TrimCase(f"m{m:.2f}_h3000", mach=m, alt=3000.0, fuel=200.0) for m in reversed(machs)
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
    ac_weak.engine = TwinEngine(max_thrust=400.0, y_offset=0.5)  # 명백히 부족 — 700은 thr 0.989로 칼날 위
    tr2 = trim_level(ac_weak, TrimCase("weak", mach=0.4, alt=1000.0, fuel=200.0))
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
        TrimCase("cruise", mach=0.4, alt=1000.0, fuel=200.0),
        # 포화는 이제 **고고도**에서 온다 — 프로펠러 축동력이 밀도비로 빠지기
        # 때문이다(P ∝ σ). 종전 상수 추력에서는 저속 저동압이 포화 유도점이었다.
        TrimCase("high_alt", mach=0.5, alt=3500.0, fuel=400.0),  # 스로틀 상한 포화 유도
        TrimCase("high", mach=0.4, alt=3000.0, fuel=400.0),  # 설계 천장(만재 ~3.8 km, CEILING) 아래로
    ]
    for tr in trim_batch(ac, cases):
        det = saturation_detail(tr)
        assert set(det) == {"de", "throttle_high", "throttle_low"}
        assert tr.flags["saturation_ok"] == (not any(det.values())), tr.case.name


# ---- 지상 정지 평형 (01 §3.3.1 이륙·착륙) ----


@pytest.fixture(scope="module")
def ac_ground():
    from claw.plant import make_demo_skid_gear

    return make_demo_aircraft(ground=make_demo_skid_gear())


def _ground_case(alt=0.0, fuel=300.0):
    return TrimCase("ground", mach=0.0, alt=alt, fuel=fuel, condition="ground")


def test_ground_trim_stands_on_its_gear(ac_ground):
    """정지 평형 = 기어 반력이 무게를 정확히 받는 높이·자세."""
    from claw.common.constants import G0
    from claw.trim import trim_ground

    tr = trim_ground(ac_ground, _ground_case())
    assert tr.converged
    m, _cg, _J = ac_ground.fuel_mass.at(300.0)
    weight = m * G0
    # 대칭 기하라 평형 자세는 수평이고 침투는 해석값과 같다
    phi, theta, _psi = tr.state.euler()
    assert theta == pytest.approx(0.0, abs=1e-6)
    assert phi == pytest.approx(0.0, abs=1e-6)
    st = ac_ground.ground.contact_state(
        tr.state.pos_n, np.zeros(3), tr.state.q_nb, np.zeros(3), 0.0
    )
    assert st["n_total"] == pytest.approx(weight, rel=1e-6)
    assert st["max_pen"] == pytest.approx(ac_ground.ground.rest_penetration(weight), abs=1e-5)
    assert np.allclose(tr.state.vel_b, 0.0), "정지 상태"


def test_ground_trim_follows_runway_elevation_and_fuel(ac_ground):
    """표고는 그대로 얹히고, 가벼우면 덜 파고든다 — 두 입력이 실제로 먹는지."""
    from claw.trim import trim_ground

    low = trim_ground(ac_ground, _ground_case(alt=0.0))
    high = trim_ground(ac_ground, _ground_case(alt=1500.0))
    assert -high.state.pos_n[2] - (-low.state.pos_n[2]) == pytest.approx(1500.0, abs=1e-4)
    light = trim_ground(ac_ground, _ground_case(fuel=0.0))
    assert -light.state.pos_n[2] > -low.state.pos_n[2], "가벼우면 덜 파고들어 더 높이 선다"


def test_ground_trim_does_not_fake_the_flight_judgements(ac_ground):
    """V=0에서 의미 없는 판정은 미판정(None) — True로 두면 없는 여유를 보고하게 된다."""
    from claw.trim import trim_ground

    tr = trim_ground(ac_ground, _ground_case())
    assert tr.flags["residual_ok"] is True
    assert tr.flags["supported_ok"] is True
    assert tr.flags["saturation_ok"] is None
    assert tr.flags["alpha_margin_ok"] is None
    assert tr.flags["continuity_ok"] is None
    assert np.allclose(tr.control.throttle, 0.0), "정칙화 마찰은 v=0에서 0 — 추력이 있으면 가속"


def test_ground_trim_refuses_what_it_cannot_mean(ac_ground):
    from claw.trim import trim_ground

    with pytest.raises(ValueError, match="mach"):
        trim_ground(ac_ground, TrimCase("x", mach=0.5, alt=0.0, fuel=300.0, condition="ground"))
    with pytest.raises(ValueError, match="착륙장치"):
        trim_ground(make_demo_aircraft(), _ground_case())


def test_trim_dispatcher_reads_the_condition_field(ac, ac_ground):
    """condition이 실제로 갈린다 — 그 전까지 계약에만 있고 아무도 안 읽던 필드."""
    from claw.trim import trim

    lvl = trim(ac, TrimCase("cruise", mach=0.4, alt=1000.0, fuel=200.0))
    assert lvl.converged and np.linalg.norm(lvl.state.vel_b) > 100.0
    gnd = trim(ac_ground, _ground_case())
    assert gnd.converged and np.allclose(gnd.state.vel_b, 0.0)
    # 모르는 조건을 조용히 level로 떨어뜨리면 지상 케이스가 비행 트림으로 풀린다
    with pytest.raises(ValueError, match="모르는 트림 조건"):
        trim(ac, TrimCase("x", mach=0.5, alt=0.0, fuel=200.0, condition="hover"))


# 코드·주석·웹 매뉴얼 세 군데가 이 숫자를 문장으로 인용한다(fcl/demo.py,
# web/js/lib/manualdoc.js, web/js/views/subsystems.js). 인용은 스윕에서 빠지기
# 마련이라 **한 자리에서 못박는다** — 여기가 그 자리다.
#
# 반올림은 **안쪽으로** 한다. 실측 하한 0.205를 "M0.20"으로 적으면 화면이 못 나는
# 점을 난다고 말하게 된다 — 이 저장소가 계속 걸러 온 방향의 오류다. 상한도 같은
# 이유로 내림이다(0.602 → 0.60).
SEA_LEVEL_BAND = {  # 연료(kg): (하한, 상한) — 0.001 격자 실측을 안쪽으로 반올림
    0.0: (0.19, 0.61),    # 실측 0.184 ~ 0.617
    200.0: (0.21, 0.60),  # 실측 0.205 ~ 0.602  ← 앱 기본값
    300.0: (0.22, 0.59),  # 실측 0.215 ~ 0.593
    400.0: (0.23, 0.58),  # 실측 0.225 ~ 0.582
}


@pytest.mark.parametrize("fuel", sorted(SEA_LEVEL_BAND))
def test_해면_수평비행_범위가_적어_둔_수치와_같다(ac, fuel):
    """적어 둔 두 끝은 **안에** 있고, 한 칸 밖은 **밖에** 있어야 한다.

    양쪽을 다 보는 것이 요점이다: 안쪽만 보면 범위를 넓게 적어도 통과하고,
    바깥쪽만 보면 좁게 적어도 통과한다. 둘을 함께 걸면 M0.01 해상도로 고정된다.
    """
    lo, hi = SEA_LEVEL_BAND[fuel]
    inside = [(lo, True), (hi, True), (round(lo - 0.01, 2), False),
              (round(hi + 0.01, 2), False)]
    for mach, want in inside:
        got = envelope_ok(trim_level(ac, TrimCase(f"m{mach:.2f}", mach=mach, alt=0.0, fuel=fuel)))
        assert got is want, (
            f"연료 {fuel:.0f} kg 해면 M{mach:.2f}: 적어 둔 범위는 M{lo:.2f}~M{hi:.2f}인데 "
            f"실제로는 {'난다' if got else '못 난다'} — 인용한 문장들을 같이 고쳐야 한다")


# 설계 천장도 같은 문제였다 — 문서·웹·테스트가 각자 인용하다 **세 벌**로 갈렸다
# (공허 7 / 7.25 / 7.45 km). 격자 해상도에 따라 답이 달라지는 양이라 더 그렇다.
#
# 이분법 실측(마하 0.005 격자): 공허 7488~7506 · 연료 200 kg 5502~5520 · 만재 3797~3814 m.
# 인용은 **0.1 km 반올림**으로 ~7.5 / ~5.5 / ~3.8 km이고, 가드는 그보다 한 칸 보수적인
# 쌍을 못박는다 — 인용값 자체를 핀하면 연료 200 kg가 천장에서 2 m 떨어진 칼날 위가 된다.
# 인용값도 **데이터로** 둔다 — 주석에 두면 테스트가 안 읽어서, 문서가 ~5.4든 ~5.6이든
# 괄호 안이라 초록이다. 이 상수를 만든 이유가 정확히 그 상황(세 벌로 갈림)이었다.
CEILING = {  # 연료(kg): (인용값, 여기서는 난다, 여기서는 못 난다) [m]
    0.0: (7500.0, 7400.0, 7600.0),
    200.0: (5500.0, 5400.0, 5700.0),  # ← 앱 기본값
    400.0: (3800.0, 3700.0, 3900.0),
}


@pytest.mark.parametrize("fuel", sorted(CEILING))
def test_설계_천장이_적어_둔_수치_근방이다(ac, fuel):
    """천장 아래에서는 나는 마하가 **하나라도** 있고, 위에서는 하나도 없다.

    이 천장은 스로틀 95% 등고선(SAT_FRAC) 기준이라 서비스 실링 정의와 같지 않다 —
    문서·웹이 그 단서를 같이 말한다(01 §2.6).
    """
    cited, below, above = CEILING[fuel]
    # 인용과 가드가 갈리지 않는다 — 괄호는 칼날을 피하려 인용값보다 넓지만 **포함**해야 한다
    assert below < cited < above, (
        f"인용 {cited:.0f} m가 실측 괄호 [{below:.0f}, {above:.0f}] 밖 — 인용과 가드가 갈렸다")
    def flies(alt):
        m = 0.15
        while m <= 0.70001:
            if envelope_ok(trim_level(ac, TrimCase(f"c{m:.3f}", mach=m, alt=alt, fuel=fuel))):
                return True
            m = round(m + 0.005, 4)
        return False
    assert flies(below), f"연료 {fuel:.0f} kg: {below:.0f} m에서 난다고 적어 뒀는데 못 난다"
    assert not flies(above), f"연료 {fuel:.0f} kg: {above:.0f} m는 천장 위여야 하는데 난다"
