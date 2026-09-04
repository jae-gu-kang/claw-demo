"""M7 SCAS 검증 — 축 해석해(PI 수열·워시아웃 감쇠), 선형모델 폐루프 성능, NavOutput 소비.

폐루프 게인은 설계점 M0.6 h1000 fuel200의 선형모델(트림→선형화, Phase 3 산출물)로
연속 고유치 스캔 + 이산 100 Hz 응답 확인을 거쳐 선정한 데모 기체 설계값.
게인 부호는 설계값이 보유 — 코드는 공력 부호를 가정하지 않음 (conventions.md).
"""

import math

import numpy as np
import pytest

from claw.common.attitude import euler_to_quat
from claw.common.contracts import NavOutput, TrimCase
from claw.fcl import Scas, ScasAxis, airdata_from_nav
from claw.plant import make_demo_aircraft, rk4_step
from claw.trim import linearize, split_axes, trim_level

DT = 0.01  # 제어주기 100 Hz [확정 시작값]

# 데모 기체 SCAS 설계값 (설계점 M0.6 h1000 fuel200)
PITCH = dict(kp=-2.0, ki=-0.5, k_rate=0.4, out_lo=-0.35, out_hi=0.35)
ROLL = dict(kp=1.0, ki=0.1, k_rate=-0.2, out_lo=-0.35, out_hi=0.35)
YAW = dict(kp=0.5, ki=0.0, k_rate=0.8, washout_tau=2.0, out_lo=-0.35, out_hi=0.35)


@pytest.fixture(scope="module")
def design_point():
    ac = make_demo_aircraft()
    tr = trim_level(ac, TrimCase("design", mach=0.6, alt=1000.0, fuel=200.0))
    assert tr.converged
    lon, lat = split_axes(linearize(ac, tr))
    return tr, lon, lat


# ---------- 축 단위 해석해 ----------


def test_axis_pi_sequence_analytic():
    """상수 오차 e에서 y_k = kp·e + ki·e·k·dt — PID forward Euler 정확 수열."""
    ax = ScasAxis(kp=2.0, ki=1.0).init(DT)
    e = 0.1
    for k in range(50):
        y = ax.step(e, 0.0)
        assert y == pytest.approx(2.0 * e + 1.0 * e * k * DT, rel=1e-12)


def test_axis_washout_rate_decays():
    """상수 각속도 입력 → 워시아웃 기여 y_k = r·p^k (ZOH-정확), 지속 선회 미대항."""
    ax = ScasAxis(k_rate=1.0, washout_tau=1.0).init(DT)
    p = math.exp(-DT / 1.0)
    r = 0.2
    for k in range(200):
        assert ax.step(0.0, r) == pytest.approx(r * p**k, rel=1e-9)


def test_axis_output_clamp_and_validation():
    ax = ScasAxis(kp=1.0, out_lo=-0.1, out_hi=0.1).init(DT)
    assert ax.step(5.0, 0.0) == 0.1
    assert ax.step(-5.0, 0.0) == -0.1
    with pytest.raises(ValueError):
        ScasAxis(out_lo=1.0, out_hi=-1.0)


def test_axis_gain_override_schedule():
    """스텝 인자 게인 덮어쓰기 — M7 게인 스케줄 주입 경로."""
    ax = ScasAxis(kp=1.0, ki=0.0, k_rate=0.0).init(DT)
    assert ax.step(0.1, 0.3) == pytest.approx(0.1)
    assert ax.step(0.1, 0.3, kp=2.0, k_rate=0.5) == pytest.approx(0.2 + 0.15)


def test_axis_reset_warm_start_bumpless():
    """reset(state)=적분기 웜스타트 — 범프리스 전환 계약."""
    ax = ScasAxis(kp=1.0, ki=1.0).init(DT)
    ax.reset(state=0.05)
    assert ax.step(0.0, 0.0) == pytest.approx(0.05)


def test_axis_rate_term_pushes_past_clamp():
    """PI가 한계 내여도 rate 항이 더해지면 축 외곽 클램프가 최종 제한 — 리뷰 지적 반영."""
    ax = ScasAxis(kp=1.0, k_rate=1.0, out_lo=-0.1, out_hi=0.1).init(DT)
    assert ax.step(0.05, 0.5) == 0.1  # PI=0.05(한계 내) + rate=0.5 → 클램프
    assert ax.step(-0.05, -0.5) == -0.1


def test_axis_reset_rate_seed_no_washout_kick():
    """정상 선회 중 재관여: reset(rate=r)이면 워시아웃 기여 0에서 시작 (킥 없음)."""
    ax = ScasAxis(k_rate=0.8, washout_tau=2.0).init(DT)
    ax.reset(rate=0.1)
    assert ax.step(0.0, 0.1) == pytest.approx(0.0, abs=1e-15)


def test_axis_gain_override_not_persistent():
    """스텝 인자 게인 덮어쓰기는 그 스텝에만 적용 — 저장 게인 오염 금지."""
    ax = ScasAxis(kp=1.0).init(DT)
    ax.step(0.1, 0.0, kp=5.0)
    assert ax.step(0.1, 0.0) == pytest.approx(0.1)  # 원래 kp=1.0 복원


# ---------- 선형모델 폐루프 (설계점, 이산 100 Hz) ----------


def test_pitch_closed_loop_tracks_theta_cmd(design_point):
    """θ 스텝 0.05 rad: 오버슈트<10%, 10 s 오차<2 mrad, 40 s 오차<1 mrad."""
    _, lon, _ = design_point
    ax = ScasAxis(**PITCH).init(DT)
    cmd, x, hist = 0.05, np.zeros(4), []
    for _ in range(int(40.0 / DT)):
        de = ax.step(cmd - x[3], x[2])
        x = rk4_step(lambda s: lon.A @ s + lon.B @ np.array([de, 0.0]), x, DT)
        hist.append(x[3])
    th = np.array(hist)
    assert (th.max() - cmd) / cmd < 0.10
    assert abs(th[int(10.0 / DT) - 1] - cmd) < 2e-3
    assert abs(th[-1] - cmd) < 1e-3


def test_roll_closed_loop_with_yaw_damper(design_point):
    """φ 스텝 0.3 rad (요 댐퍼 동시 작동): 오버슈트<8%, 5 s 오차<10 mrad, |β|<0.02."""
    tr, _, lat = design_point
    V0 = float(np.linalg.norm(tr.state.vel_b))
    roll = ScasAxis(**ROLL).init(DT)
    yaw = ScasAxis(**YAW).init(DT)
    cmd, x = 0.3, np.zeros(4)
    phis, betas = [], []
    for _ in range(int(20.0 / DT)):
        v, p, r, phi = x
        da = roll.step(cmd - phi, p)
        dr = yaw.step(-(v / V0), r)
        u = lat.B @ np.array([da, dr])
        x = rk4_step(lambda s: lat.A @ s + u, x, DT)
        phis.append(x[3])
        betas.append(x[0] / V0)
    phis = np.array(phis)
    assert (phis.max() - cmd) / cmd < 0.08
    assert abs(phis[int(5.0 / DT) - 1] - cmd) < 1e-2
    assert abs(phis[-1] - cmd) < 5e-3
    assert np.max(np.abs(betas)) < 0.02


def test_yaw_damper_dutch_roll_suppression(design_point):
    """v 초기교란 자유응답: 워시아웃 요 댐퍼가 ∫β²dt를 1/3 미만으로 감쇠 (개루프 ζ≈0.05)."""
    tr, _, lat = design_point
    V0 = float(np.linalg.norm(tr.state.vel_b))

    def beta_energy(with_damper):
        yaw = ScasAxis(**YAW).init(DT) if with_damper else None
        x = np.zeros(4)
        x[0] = 5.0
        acc = 0.0
        for _ in range(int(15.0 / DT)):
            dr = yaw.step(-(x[0] / V0), x[2]) if yaw else 0.0
            u = lat.B @ np.array([0.0, dr])
            x = rk4_step(lambda s: lat.A @ s + u, x, DT)
            acc += (x[0] / V0) ** 2 * DT
        return acc, abs(x[0])

    e_off, _ = beta_energy(False)
    e_on, v_end = beta_energy(True)
    assert e_on / e_off < 0.35
    assert v_end < 0.5  # 감쇠 후 잔여 사이드슬립 미미


# ---------- 3축 조립 (NavOutput 소비) ----------


def _nav(phi=0.0, theta=0.0, psi=0.0, vel_b=(200.0, 0.0, 0.0), omega=(0.0, 0.0, 0.0)):
    q = euler_to_quat(phi, theta, psi)
    from claw.common.frames import body_to_ned

    return NavOutput(q_nb=q, vel_n=body_to_ned(q, np.array(vel_b)), omega_b=np.array(omega))


def make_scas():
    return Scas(ScasAxis(**PITCH), ScasAxis(**ROLL), ScasAxis(**YAW)).init(DT)


def test_scas_assembly_signs_demo_profile():
    """데모 기체 부호: 기수올림 명령→de<0(TE up), 우롤 명령→da>0, β>0→dr<0."""
    scas = make_scas()
    de, da, dr = scas.step(0.05, 0.3, _nav())
    assert de < 0 and da > 0 and dr == 0.0
    scas.reset()
    de, da, dr = scas.step(0.0, 0.0, _nav(vel_b=(200.0, 5.0, 0.0)))
    assert dr < 0
    assert de == pytest.approx(0.0, abs=1e-12) and da == pytest.approx(0.0, abs=1e-12)


def test_scas_uses_nav_attitude_and_rates():
    """자세·각속도 피드백 반영: 명령=자세이면 P항 0, 레이트만 남음."""
    scas = make_scas()
    de, da, _ = scas.step(0.1, 0.2, _nav(phi=0.2, theta=0.1, omega=(0.05, 0.03, 0.0)))
    assert de == pytest.approx(PITCH["k_rate"] * 0.03)  # kq·q만
    assert da == pytest.approx(ROLL["k_rate"] * 0.05)  # kpp·p만


def test_scas_gain_override_dict():
    scas = make_scas()
    base = scas.step(0.05, 0.0, _nav())[0]
    scas.reset()
    doubled = scas.step(0.05, 0.0, _nav(), gains={"pitch": {"kp": -4.0}})[0]
    assert doubled == pytest.approx(2.0 * base)


def test_scas_roll_error_wraps_at_pi():
    """±π 경계(배면 부근) 롤 오차 — 2π 점프 없이 최단 경로 방향."""
    scas = make_scas()
    de, da, dr = scas.step(0.0, -3.1, _nav(phi=3.1))
    # wrap(−3.1 − 3.1) = +0.083 → 우롤(da>0), 크기는 kp·0.083 수준 (2π 점프 아님)
    assert 0.0 < da < 0.2


def test_airdata_from_nav_roundtrip():
    """NavOutput → (V, α, β): 동체속도 재구성 일치 (바람 0 가정)."""
    nav = _nav(phi=0.1, theta=0.06, psi=1.0, vel_b=(200.0, 4.0, 12.0))
    V, alpha, beta = airdata_from_nav(nav)
    assert V == pytest.approx(math.sqrt(200.0**2 + 4.0**2 + 12.0**2), rel=1e-12)
    assert alpha == pytest.approx(math.atan2(12.0, 200.0), rel=1e-12)
    assert beta == pytest.approx(math.asin(4.0 / V), rel=1e-12)


def test_elevon_allocation_never_exceeds_the_surface_budget():
    """배분 뒤에는 |δe| + |δa| ≤ elevon_hi가 **항상** 성립한다 — 믹서가 자를 것이 없다.

    델타윙은 피치와 롤이 같은 네 면을 나눠 쓴다. 배분이 없으면 믹서가 δe ± δa를
    자르고 그 사실을 두 축 모두 모른 채 적분한다. 실측(스트레스 트레이스)에서
    클립 12254건이 전부 한쪽 면만 잘렸고, 그때 |δe| 평균 19.93°(한계 20.05°)에
    |δa| 평균 1.39°였다 — 피치가 예산을 다 쓰고 롤이 밀려나는 모양이었다.

    배분 근거는 실속 마진이 아니라 **선회 하중**이다. 마진은 닿고 나서 움직이는
    지표라 늦다 — 마진 기반으로 두었더니 선회 순간 롤이 19°를 가져가 피치에 1°만
    남았고, 마진이 음수가 된 뒤에야 되찾아 순항 중 59 m까지 내려갔다
    (test_landing의 선회 회귀가 잡았다). 뱅크 명령은 하중이 걸리기 전에 알 수 있다.
    """
    from claw.fcl.demo import DEMO_ALLOC_TRIM_TABLE, make_demo_fcl

    assert DEMO_ALLOC_TRIM_TABLE is not None, "데모에 배분이 꺼져 있다"
    fcl = make_demo_fcl().init(0.01)
    r = fcl.runner
    hi = fcl.mixer.elevon_hi
    r.reset()
    worst = 0.0
    rng = np.random.default_rng(0)
    for _ in range(400):
        # 축을 세게 흔든다 — 배분이 없으면 믹서가 자를 조합이 반드시 나온다
        out = r.step(
            nav_valid=1.0, theta=rng.uniform(-0.3, 0.3), phi=rng.uniform(-0.7, 0.7),
            psi=0.0, p=rng.uniform(-1, 1), q=rng.uniform(-1, 1), r=rng.uniform(-1, 1),
            V=170.0, alpha=rng.uniform(0.0, 0.25), beta=rng.uniform(-0.1, 0.1),
            h=1000.0, hdot=0.0, mach=0.5,
            cmd_speed=170.0, cmd_alt=1000.0, cmd_heading=rng.uniform(-1, 1),
            cmd_pitch=0.0, cmd_hdot=0.0,
            speed_on=1.0, alt_on=1.0, heading_on=1.0, pitch_on=0.0, hdot_on=0.0,
        )
        e = r.last_env
        de, da = e["scas_pitch_sat"], e["scas_roll_sat"]
        worst = max(worst, abs(de) + abs(da))
        # 믹서가 실제로 자를 것이 남아 있으면 배분이 제 일을 못 한 것이다
        assert abs(de) + abs(da) <= hi + 1e-12, f"배분 항등 위반: |{de}|+|{da}| > {hi}"
        for side in (out["elevon_l"], out["elevon_r"]):
            assert abs(side) <= hi + 1e-12
    assert worst > 0.5 * hi, f"예산 근처를 한 번도 안 밟았다 (최대 {worst}) — 항진 테스트다"


def test_allocation_budget_shrinks_to_the_narrowest_configured_limit():
    """비대칭 형상에서도 배분이 **권한을 늘리지 않는다** — 예산은 가장 좁은 쪽이다.

    배분은 예산을 크기 하나로 나누고 하한을 Gain(−1)로 만든다. 그 하나를 상한에
    맞추면, 하한이 더 좁은 축(예: [−0.20, 0.35])에서 −0.20으로 설정된 권한이
    −0.30까지 조용히 늘어난다. 실행 중엔 아무 신호도 안 난다 — 믹서 클립으로만
    뒤늦게 드러난다.

    거부하지 않고 좁히는 이유: 영향성 해석은 out_hi 하나만 흔들어 본다
    (pipeline/influence.py). 거부하면 그 정당한 사용이 조립 예외로 죽는다.
    """
    from claw.fcl.demo import make_demo_fcl
    from claw.fcl.mixer import Mixer

    def budget(fcl):
        g = fcl.init(0.01).runner.graph
        # roll_hi = B − R, 그리고 R = 0(뱅크 명령 0)일 때 상수항이 곧 B다
        node = next(n for n in g.nodes if n.id.endswith("alloc_roll_hi"))
        return node.value

    assert budget(make_demo_fcl()) == pytest.approx(0.35)  # 대칭 현행 형상

    # 믹서 하한이 좁으면 예산이 그리로 줄어든다
    assert budget(make_demo_fcl(mixer=Mixer(elevon_lo=-0.30, elevon_hi=0.35))) \
        == pytest.approx(0.30)

    # SCAS 축 하한이 좁아도 마찬가지 — 설정된 권한을 넘겨 주지 않는다
    fcl = make_demo_fcl()
    fcl.scas.cfg["pitch"]["out_lo"] = -0.20
    assert budget(fcl) == pytest.approx(0.20)

    # 예산이 남지 않는 형상은 조립에서 거부한다 (조용히 부호가 뒤집히는 대신)
    bad = make_demo_fcl()
    bad.scas.cfg["roll"]["out_hi"] = 0.0
    with pytest.raises(ValueError, match="배분 예산"):
        bad.init(0.01)


def test_allocation_floors_both_axes_so_neither_can_be_starved():
    """배분은 **양쪽에 바닥을 준다** — 어느 축도 0으로 굶지 않는다.

    두 바닥의 근거가 다르다:

    피치 바닥 = δe_trim(mach) — **그 mach의 1g 트림 요구**. 상수가 아닌 이유는
    요구가 0.68°(M0.6)~15.24°(M0.25)로 21배 움직이기 때문이다. 예약을 하중
    **증분**(n−1)에 비례시켰을 때는 이 바닥이 아예 없었고, 증분은 φ_cmd에
    2차라 선회 진입(롤 수요 최대 지점)에서 사실상 0이었다: 데모 미션 최악값이
    피치 0.192° / 롤 19.862°였다. 원칙이 "실속방지 몫을 **먼저**"인데 정반대로
    동작한 것이다.

    롤 바닥 = (1 − resv_frac)·B. 이게 없으면 R이 예산 전체를 먹어 롤 권한이 0이
    되는데, 그러면 뱅크를 되돌릴 수도 없어 하중이 유지되고 R이 계속 포화하는
    자기지속 상태가 된다. Autopilot(phi_max=1.2)은 생성자가 허용하는 값이다.
    """
    import math

    from claw.fcl.autopilot import Autopilot
    from claw.fcl.demo import DEMO_ALLOC_RESV_FRAC, make_demo_fcl
    from claw.plant import make_demo_trim_elevator_table

    # phi_max를 올려 **R을 실제로 포화시킨 상태**에서 본다. 조립 상수(resv_hi)만
    # 보면 phi_max와 무관해 세 번 같은 단정을 하는 항진 테스트가 된다 — 절벽은
    # 런타임에 R이 예산을 다 먹을 때 생긴다.
    capped = []
    for phi_max in (0.7, 1.2, 1.5):  # 1.5 = Autopilot 생성자 상한
        fcl = make_demo_fcl(autopilot=Autopilot(phi_max=phi_max))
        r = fcl.init(0.01).runner
        budget = next(n for n in r.graph.nodes
                      if n.id.endswith("alloc_roll_hi")).value
        # 헤딩 오차를 크게 줘 φ_cmd를 ±phi_max에 붙인다. mach도 같이 흔든다 —
        # R = δe_trim(mach)·n이라 저속일수록 상한에 먼저 닿는다.
        floor = (1.0 - DEMO_ALLOC_RESV_FRAC) * budget
        assert floor > 0.0
        for mach in (0.25, 0.5):
            for hdg in (-3.0, 3.0):
                r.reset()
                for _ in range(50):
                    r.step_all(
                        nav_valid=1.0, theta=0.0, phi=0.0, psi=0.0, p=0.0, q=0.0,
                        r=0.0, V=170.0, alpha=0.05, beta=0.0, h=1000.0, hdot=0.0,
                        mach=mach, cmd_speed=170.0, cmd_alt=1000.0, cmd_heading=hdg,
                        cmd_pitch=0.0, cmd_hdot=0.0, speed_on=1.0, alt_on=1.0,
                        heading_on=1.0, pitch_on=0.0, hdot_on=0.0)
                    e = r.last_env
                    assert abs(e["ap_hdg_sat"]) <= phi_max + 1e-12
                    assert e["scas_alloc_roll_hi"] >= floor - 1e-12, (
                        f"phi_max={phi_max} M{mach}: 롤 권한이 바닥 아래로 갔다 "
                        f"({e['scas_alloc_roll_hi']} < {floor})")
                    if abs(e["scas_alloc_roll_hi"] - floor) < 1e-9:
                        capped.append((phi_max, mach))

    # 상한(frac·B)은 표의 최댓값을 덮어야 한다 — 안 덮으면 예약 상한이 1g 트림
    # 요구 자체를 잘라, "피치 몫을 먼저"라면서 그 몫을 못 주게 된다. 두 상수가
    # 따로 움직이면 조용히 깨지는 관계라 여기서 묶는다.
    budget0 = next(n for n in make_demo_fcl().init(0.01).runner.graph.nodes
                   if n.id.endswith("alloc_roll_hi")).value
    tab = make_demo_trim_elevator_table()
    need_max = max(float(tab(mach=m)) for m in (0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.6))
    assert DEMO_ALLOC_RESV_FRAC * budget0 >= need_max, (
        f"예약 상한 {math.degrees(DEMO_ALLOC_RESV_FRAC * budget0):.2f}° < "
        f"표 최댓값 {math.degrees(need_max):.2f}° — 상한이 1g 요구를 자른다")

    # 상한이 **실제로 물린** 조합이 있어야 한다 — 없으면 위 바닥 단정이 상한을
    # 한 번도 안 본 채 통과한다(절벽은 상한에 닿는 지점에서 생긴다)
    assert capped, "예약 상한에 닿는 조합이 없다 — 절벽 구간을 안 밟는 시험이다"

    # 피치 바닥: pitch_hi ≥ R ≥ δe_trim(mach)이 **모든 mach·φ_cmd에서** 성립한다.
    # 리터럴 상수와 비교하면 표가 바뀌어도 초록으로 남는다 — 표 자체를 읽는다.
    table = make_demo_trim_elevator_table()
    r = make_demo_fcl().init(0.01).runner
    rng = np.random.default_rng(2)
    tight = None
    for mach in (0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60, 0.70):
        need = float(table(mach=mach))
        for _ in range(60):
            r.step_all(
                nav_valid=1.0, theta=rng.uniform(-.3, .3), phi=rng.uniform(-.7, .7),
                psi=0.0, p=rng.uniform(-1, 1), q=rng.uniform(-1, 1), r=rng.uniform(-1, 1),
                V=170.0, alpha=rng.uniform(0, .25), beta=rng.uniform(-.1, .1),
                h=1000.0, hdot=0.0, mach=mach, cmd_speed=170.0, cmd_alt=1000.0,
                cmd_heading=rng.uniform(-1, 1), cmd_pitch=0.0, cmd_hdot=0.0,
                speed_on=1.0, alt_on=1.0, heading_on=1.0, pitch_on=0.0, hdot_on=0.0)
            got = r.last_env["scas_alloc_pitch_hi"]
            assert got >= need - 1e-12, (
                f"M{mach}: 피치 권한 {math.degrees(got):.2f}° < 트림 요구 "
                f"{math.degrees(need):.2f}° — 1g를 못 버틴다")
            slack = got - need
            if tight is None or slack < tight[0]: tight = (slack, mach)
    # 여유가 항상 넉넉하면 위 단정이 아무것도 안 본 것이다 (M0.15·0.70은 clip 구간)
    assert tight[0] < math.radians(1.0), (
        f"어느 mach에서도 바닥에 근접하지 않았다 (최소 여유 "
        f"{math.degrees(tight[0]):.2f}° at M{tight[1]}) — 항진 테스트다")
