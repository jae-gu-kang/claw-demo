"""M2 필터·PID 검증 — 1차 필터는 ZOH-정확 해석해 대조(abs 1e-12), 노치는 주파수영역 검증."""

import cmath
import math

import pytest

from claw.blocks import PID, Lag, LeadLag, LowPass, Notch, Washout

DT = 0.01


# ---- Lag / LowPass: ZOH-정확 이산화 → 스텝응답이 표본점에서 해석해와 기계정밀도 일치 ----


@pytest.mark.parametrize("dt", [0.01, 0.02])  # 100 vs 50 Hz — 둘 다 해석해와 정확 일치
def test_lag_step_exact(dt):
    tau = 0.1
    lag = Lag(tau).init(dt)
    outs = [lag.step(1.0) for _ in range(30)]
    for k, y in enumerate(outs):
        assert y == pytest.approx(1.0 - math.exp(-k * dt / tau), abs=1e-12)


def test_lowpass_equals_lag():
    fc = 3.0
    lp = LowPass(fc).init(DT)
    lag = Lag(1.0 / (2.0 * math.pi * fc)).init(DT)
    seq = [0.5, 1.0, -0.2, 0.0, 2.0, 1.0]
    assert [lp.step(u) for u in seq] == pytest.approx([lag.step(u) for u in seq], abs=1e-15)


def test_lag_invalid_tau():
    with pytest.raises(ValueError):
        Lag(0.0)


# ---- Washout ----


def test_washout_step_exact():
    tau = 0.2
    wo = Washout(tau).init(DT)
    outs = [wo.step(1.0) for _ in range(50)]
    assert outs[0] == pytest.approx(1.0, abs=1e-15)  # 초기값 정확히 1
    for k, y in enumerate(outs):
        assert y == pytest.approx(math.exp(-k * DT / tau), abs=1e-12)


def test_washout_ramp_steady_state():
    """램프 a·t 입력의 이산 정상상태 = a·dt/(1-p) → dt→0 극한에서 a·tau."""
    tau, a = 0.5, 2.0
    wo = Washout(tau).init(DT)
    for k in range(3000):
        y = wo.step(a * k * DT)
    p = math.exp(-DT / tau)
    assert y == pytest.approx(a * DT / (1.0 - p), abs=1e-9)


# ---- LeadLag ----


@pytest.mark.parametrize("t1, t2", [(0.2, 0.05), (0.05, 0.2)])  # 리드 / 래그 양쪽
def test_leadlag_step_exact(t1, t2):
    c = t1 / t2
    ll = LeadLag(t1, t2).init(DT)
    outs = [ll.step(1.0) for _ in range(60)]
    assert outs[0] == pytest.approx(c, abs=1e-12)  # 초기값 t1/t2
    for k, y in enumerate(outs):
        assert y == pytest.approx(1.0 + (c - 1.0) * math.exp(-k * DT / t2), abs=1e-11)


# ---- Notch: 주파수영역 정본 검증 (다항식 평가 — 시뮬 불요) ----


def _freq_response(nt, f_hz):
    z = cmath.exp(1j * 2.0 * math.pi * f_hz * nt.dt)
    b0, b1, b2 = nt.b
    a1, a2 = nt.a
    return (b0 + b1 / z + b2 / z**2) / (1.0 + a1 / z + a2 / z**2)


def test_notch_frequency_response():
    f0 = 5.0
    nt = Notch(f0=f0, q=2.0).init(DT)
    assert abs(_freq_response(nt, f0)) < 1e-12  # 중심주파수 완전 차단 (프리워핑 정확)
    assert abs(_freq_response(nt, 1e-9)) == pytest.approx(1.0, abs=1e-6)  # DC 이득 1
    assert abs(_freq_response(nt, 45.0)) == pytest.approx(1.0, abs=0.1)  # 고주파 통과


def test_notch_time_domain():
    f0 = 5.0
    nt = Notch(f0=f0, q=2.0).init(DT)
    outs = [nt.step(math.sin(2.0 * math.pi * f0 * k * DT)) for k in range(600)]
    assert max(abs(y) for y in outs[-100:]) < 0.05  # f0 정현파 감쇠
    nt.reset()
    outs = [nt.step(math.sin(2.0 * math.pi * (f0 / 4) * k * DT)) for k in range(600)]
    assert max(abs(y) for y in outs[-100:]) > 0.9  # f0/4 통과
    nt.reset()
    outs = [nt.step(1.0) for _ in range(800)]
    assert outs[-1] == pytest.approx(1.0, abs=1e-6)  # DC 스텝 정착


def test_notch_nyquist_guard():
    with pytest.raises(ValueError):
        Notch(f0=60.0, q=2.0).init(DT)  # 60 Hz >= 나이퀴스트(50 Hz)


# ---- PID ----


def test_pid_p_only_and_override():
    pid = PID(kp=1.5).init(DT)
    assert pid.step(2.0) == pytest.approx(3.0)
    assert pid.step(2.0, kp=3.0) == pytest.approx(6.0)  # 게인 스케줄 덮어쓰기


def test_pid_pi_exact_sequence():
    kp, ki, e = 2.0, 3.0, 0.5
    pid = PID(kp=kp, ki=ki).init(DT)
    for k in range(10):
        y = pid.step(e)
        assert y == pytest.approx(kp * e + ki * e * k * DT, abs=1e-12)


def test_pid_derivative_kick():
    pid = PID(kp=0.0, ki=0.0, kd=1.0).init(DT)
    assert pid.step(1.0) == pytest.approx(1.0 / DT)
    assert pid.step(1.0) == pytest.approx(0.0)


def test_pid_antiwindup():
    """안티와인드업 계약 — **조건부 적분**이다 (종전 클램프-온리에서 바뀌었다).

    클램프-온리에서는 30스텝 뒤 I가 상한 1.0까지 차서 e=−1 한 번에 출력이 정확히
    0.0으로 떨어졌다. 조건부 적분은 raw가 상한을 넘는 순간 적분을 멈추므로 I는
    첫 스텝의 0.1에서 얼어붙고, 그래서 반전 시 출력이 −0.9다.

    **이 차이가 곧 이 변경의 요점이다**: 클램프는 적분기가 쌓이는 *크기*만 제한하고
    쌓이는 것 자체를 막지 않아, 출력범위가 넓은 축에서 "출력 한 벌 분량"이 차고
    그것을 푸는 데 오래 걸린다 (fcl/autopilot.py tau_spd 주석의 실측 참조).
    """
    pid = PID(kp=1.0, ki=1.0, out_lo=-1.0, out_hi=1.0).init(0.1)
    for _ in range(30):
        y = pid.step(1.0)
    assert y == pytest.approx(1.0)  # 출력 포화
    # 적분기는 **첫 스텝 분량에서 멈춰 있다** — 포화 방향 증분을 버렸다
    assert pid._i == pytest.approx(0.1)
    # 반전 시 출력 = kp·e + I = −1.0 + 0.1 (클램프-온리였다면 −1.0 + 1.0 = 0.0)
    assert pid.step(-1.0) == pytest.approx(-0.9)


def test_pid_reset_warm_start():
    pid = PID(kp=0.0, ki=1.0).init(DT)
    pid.reset(0.7)  # 적분기 웜스타트 (범프리스 전환 계약)
    assert pid.step(0.0) == pytest.approx(0.7)


def test_pid_conditional_integration_stops_only_in_the_saturating_direction():
    """조건부 적분 — 포화 방향으로는 멈추고, 반대 방향은 즉시 푼다.

    **두 가지를 다 고정한다.** 정지만 보면 "적분을 아예 안 한다"로 만들어도 통과하고,
    해제만 보면 종전 클램프-온리와 구분이 안 된다.

    클램프-온리와의 차이가 곧 이 블록의 요점이다: 클램프는 적분기가 쌓이는 크기를
    출력범위로 제한할 뿐 쌓이는 것 자체를 막지 않아, 출력범위가 넓은 축(속도축은
    [0, 1])에서 "출력 한 벌 분량"까지 차고 그것을 푸는 데 오래 걸린다.
    """
    # 대칭 범위를 쓴다 — [0, 1] 같은 편측 범위는 음의 오차가 곧바로 하한 포화라
    # "해제" 가지를 만들 수 없다(그때 막는 것은 옳은 동작이다)
    pid = PID(kp=1.0, ki=1.0, out_lo=-1.0, out_hi=1.0).init(0.1)
    pid.reset()
    # 큰 양의 오차 — 첫 스텝에 출력이 상한을 넘어간다(raw = 5.0 > 1.0)
    assert pid.step(5.0) == pytest.approx(1.0)
    assert pid._i == pytest.approx(0.0), "포화 방향 증분이 들어갔다"
    # 계속 밀어도 적분기는 안 자란다 (클램프-온리였다면 out_hi까지 찼다)
    for _ in range(20):
        pid.step(5.0)
    assert pid._i == pytest.approx(0.0), "포화가 계속되는 동안 적분기가 자랐다"
    # 포화에서 빠져나오는 오차(raw가 범위 안)면 **즉시** 적분한다 — 그 길이 막히면
    # 적분기가 영영 안 풀린다
    pid.step(-0.5)
    assert pid._i == pytest.approx(0.1 * 1.0 * -0.5), "포화 해제 방향 증분까지 막았다"


def test_pid_conditional_integration_holds_for_negative_gain_axes():
    """게인이 음수인 축(피치 kp −2.0·ki −0.5)에서도 부호 논리가 성립한다.

    조건은 출력 포화 방향과 **증분 부호**를 비교하므로 게인 부호와 무관해야 한다 —
    음수 ki에서는 양의 오차가 음의 증분을 만들고, 그때 막히는 쪽은 하한이다.
    """
    pid = PID(kp=-2.0, ki=-0.5, out_lo=-0.35, out_hi=0.35).init(0.1)
    pid.reset()
    for _ in range(30):
        pid.step(5.0)  # 양의 오차 → raw 음수로 하한 포화, 증분도 음수 → 정지
    assert pid._i == pytest.approx(0.0), "하한 포화 방향으로 적분기가 자랐다"
    # 해제는 raw가 범위 안으로 돌아올 때다 — |−2e| < 0.35이려면 |e| < 0.175
    pid.step(-0.1)  # raw = +0.2 (범위 안), 증분 = 0.1·(−0.5)·(−0.1) = +0.005
    assert pid._i == pytest.approx(0.005)


def test_pid_unbounded_axis_behaves_as_before():
    """출력 한계가 없는 PID는 조건이 never-true라 종전과 동일하다 — 회귀 방어."""
    pid = PID(kp=1.0, ki=2.0).init(0.1)  # out_lo/hi = ∓UNBOUNDED
    pid.reset()
    for _ in range(10):
        pid.step(3.0)
    assert pid._i == pytest.approx(10 * 0.1 * 2.0 * 3.0)  # 전부 적분됐다


def test_pid_zero_ki_axis_is_untouched_by_conditional_integration():
    """ki = 0인 축(요축)은 종전과 정확히 같다 — inc = ±0.0이라 두 부등호가 다 거짓이다."""
    pid = PID(kp=0.5, ki=0.0, out_lo=-0.35, out_hi=0.35).init(0.01)
    pid.reset(state=0.2)
    for _ in range(20):
        pid.step(-5.0)  # 하한 포화가 계속돼도
    assert pid._i == pytest.approx(0.2)  # 웜스타트 값 그대로


def test_pid_out_of_range_warm_start_is_clamped_on_the_first_step():
    """범위 밖 웜스타트는 **첫 스텝에** 잘린다 — 증분을 버려도 클램프는 무조건이다.

    도달 가능한 조합이다: 트림 θ의 상한(0.35, trim.py ALPHA_BOUNDS)이 AP의
    theta_hi(0.3)보다 커서, 범프리스 웜스타트가 범위 밖 값을 그대로 넣는다.
    증분 버림과 클램프를 한 덩어리로 건너뛰면 그 0.05 rad가 영영 안 잘리고,
    음의 오차로만 방전되므로 **와인드업이 되레 길어진다** (리뷰 지적).
    """
    pid = PID(kp=1.0, ki=1.0, out_lo=-0.3, out_hi=0.3).init(0.01)
    pid.reset(state=0.35)  # 범위 밖
    pid.step(5.0)  # 포화 방향 오차 — 증분은 버려지지만 클램프는 걸려야 한다
    assert pid._i == pytest.approx(0.3), "범위 밖 웜스타트가 안 잘렸다"


def test_pid_integrates_while_saturated_when_the_increment_releases():
    """**포화 중이라도 빠져나오는 방향이면 적분한다** — 이 가지가 안 잡히면 축이 래치된다.

    방향 판정(`and inc > 0` / `and inc < 0`)을 지우고 "포화면 무조건 정지"로 바꾸면
    적분기가 영영 안 풀린다. 그 변이를 다른 어떤 테스트도 못 잡는다는 것이
    리뷰에서 드러났다 — 기존 해제 테스트들은 raw가 **범위 안**이라 "포화가 아니면
    적분한다"만 재고 있었다.

    여기서는 kp와 ki의 부호를 갈라 그 조합을 만든다: kp = −2로 raw = +1.0(상한 0.3
    초과 = 포화)인데 ki = +1이라 증분은 −0.05(포화에서 빠져나오는 방향)다.
    현행 데모 형상은 kd = 0이고 kp·ki 부호가 같아 이 가지가 안 열리지만, PID는
    재사용 블록이고 kd·스케줄이 1급 파라미터라 "지금은 안 열린다"가 근거가 못 된다.
    """
    pid = PID(kp=-2.0, ki=1.0, out_lo=-0.35, out_hi=0.3).init(0.1)
    pid.reset()
    assert pid.step(-0.5) == pytest.approx(0.3)  # 출력은 상한에 붙는다
    assert pid._i == pytest.approx(-0.05), "포화 중 해제 방향 증분을 버렸다 — 축이 래치된다"


def test_pid_integrates_while_saturated_low_when_the_increment_releases():
    """위 테스트의 **하한 쪽 짝** — 이 가지도 따로 잡아야 한다.

    상한만 잡아 두면 `or (raw < self.out_lo and inc < 0.0)`에서 방향 판정만 지운
    변이(`or (raw < self.out_lo)`)가 엔진 전 스위트를 통과한다 — 리뷰에서 실제로
    확인됐다(blocks·filters 68건, law·autopilot·mission·diagnose·landing 71건 전부 통과).
    데모 형상에서 안 열리는 것은 kd = 0이고 sign(kp) == sign(ki)라 raw < out_lo가
    inc < 0을 함의하기 때문인데, 그것은 상한 가지를 남긴 근거와 정확히 같은 이유로
    근거가 못 된다. 이 가지가 죽으면 축이 **하한에** 영영 물린다.

    kp = −2로 raw = −1.0(하한 −0.3 아래 = 포화)인데 ki = +1이라 증분은 +0.05
    (포화에서 빠져나오는 방향)다.
    """
    pid = PID(kp=-2.0, ki=1.0, out_lo=-0.3, out_hi=0.35).init(0.1)
    pid.reset()
    assert pid.step(0.5) == pytest.approx(-0.3)  # 출력은 하한에 붙는다
    assert pid._i == pytest.approx(0.05), "포화 중 해제 방향 증분을 버렸다 — 축이 래치된다"
