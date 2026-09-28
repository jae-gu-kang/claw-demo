"""마진 맵·보드선도의 마진 정의 — 나이퀴스트에 맞는 여유 (analysis.margins.nyquist_margins, 01 §4.2, e2e D2).

e2e: 쇼케이스 기체 마진 맵이 pitch_q PM을 전 칸 −50~−79°, roll_p GM을 −9.7 dB까지 냈다 — 게인 탭은 하드 게이트
전부 통과·검증 통과·시뮬 착지인데. control.margin은 −1에 가장 가까운 교차를 고르고(그 선택은 나이퀴스트 그대로다)
**부호째** 낸다. 그 부호는 교차가 여럿이면 안정·불안정이 아니라 방향이다(PM: 교차점이 실축 위·아래, GM: 이득을
올려·내려 닿는다). 레이트 루프는 원점 영점(q = θ̇) 때문에 장주기·나선 봉우리에서 0 dB를 여러 번 지나 그 방향이
곧잘 "음수"로 나오고, 화면은 그것을 부족으로 칠했다. 판정의 정본은 이 루프만 닫은 폐루프의 극이다.

픽스처 선형 모델은 **녹화본**이다 — 기체 문서(쇼케이스는 다른 작업이 값을 고친다)·공력 모델이 바뀌어도 이
테스트가 보는 병리는 그대로 남게. 녹화: 쇼케이스 M0.12/h3000/f50 종축·M0.18/h3000/f50 횡축, 예제
M0.16/h100/f25 종축(v1.48 재튜닝 **전** 게인 — 지금 출하 예제의 게인이 아니다, 02 §5.6.1), 게인은 그 칸의 조립 법칙
k_rate(openloop.effective_gain), 작동기 30 rad/s·ζ 0.7·지연 35 ms(마진 탭 기본 조립).
"""

import math

import control
import numpy as np
import pytest

from claw.analysis import (
    bode_data,
    closed_loop_unstable,
    nyquist_margins,
    loop_margins,
    margin_map,
)

ACT = {"actuator_wn": 30.0, "actuator_zeta": 0.7, "delay_s": 0.035, "pade_order": 2}

# 쇼케이스 M0.12/h3000/f50 종축 (u, w, q, θ) · δe 열 · pitch.k_rate
S1_LON_A = [[-0.07715889683969361, 0.15844162203686152, -12.534435454455874, -9.300146542898347],
            [-0.21498062854896277, -0.8482796862476536, 37.06506329654449, -3.1108935210681916],
            [0.036655001826841546, -0.10958167943047994, -0.8666227647850798, 0.0],
            [0.0, 0.0, 1.0, 0.0]]
S1_LON_B = [-0.3256127790507435, -4.021121876007783, -6.378469722937355, 0.0]
S1_PITCH_K = 0.48245173316058304
# 쇼케이스 M0.18/h3000/f50 횡축 (v, p, r, φ) · δa 열 · roll.k_rate
S1_LAT_A = [[-0.18960568291776583, 8.592093315876538, -58.516594845974666, 9.702615684335811],
            [-0.7332153815999967, -3.0245134490999286, 0.4582596134999892, 0.0],
            [0.092117160886294, -0.02558810024619229, -0.15352860147715372, 0.0],
            [0.0, 1.0, 0.146831737876962, 0.0]]
S1_LAT_B = [0.0, 39.028779350115975, -0.48428265409055343, 0.0]
S1_ROLL_K = -0.17087122388798723
# 예제 기체 M0.16/h100/f25 종축 · δe 열 · pitch.k_rate (규칙 스케줄) — v1.48 재튜닝 전 게인의 녹화다(설계 k_rate 0.4 × 상한 2).
# 현행 예제는 이 발산을 게인 탭 게이트가 FAIL로 잡아 게인을 다시 냈다(pitch.k_rate 약 0.09) — 병리 픽스처로는 그대로 유효하다
EX_LON_A = [[-0.04713387263592841, 0.05586856525469323, -5.2336008055214736, -9.761137249865572],
            [-0.16402499645122723, -2.0336049663097113, 54.133189404361204, -0.9437074803437487],
            [0.06492677133875227, -0.6715630540275028, -3.7951555321875885, 0.0],
            [0.0, 0.0, 1.0, 0.0]]
EX_LON_B = [-0.7417271881747313, -12.432984332528056, -45.86706350408802, 0.0]
EX_PITCH_K = 0.8


def _rate_loop(A, B, out, k):
    """녹화한 축 모델 → 마진 탭 레이트 루프 −k·G(x_out←u)·작동기·Padé (pi_loop와 같은 조립, sign −1)."""
    from claw.analysis import pi_loop

    return pi_loop(_model(A, B), x_out=_NAMES[out], u_in="u", kp=k, sign=-1.0, **ACT)


_NAMES = ("s0", "s1", "s2", "s3")


def _model(A, B):
    from claw.common.contracts import LinearModel

    n = len(A)
    return LinearModel(A=np.array(A), B=np.array(B).reshape(n, 1), C=np.eye(n), D=np.zeros((n, 1)),
                       x_names=_NAMES, u_names=("u",))


def test_stable_rate_loop_reports_the_distance_to_minus_one_not_the_direction_sign():
    """쇼케이스 pitch_q — control.margin은 장주기 봉우리 교차(0.29 rad/s)를 −78.6°로 낸다. 폐루프는 안정이고 그 점은
    −1에서 78.6° 떨어진 **실축 위**다(넘기려면 진상 78.6°가 필요하다 — 지연은 오히려 멀어지게 한다). 여유는 78.6°다."""
    loop = _rate_loop(S1_LON_A, S1_LON_B, 2, S1_PITCH_K)
    old = loop_margins(loop)
    assert old["wcp"] < 1.0 and old["pm_deg"] < -45.0, old  # 병리 전제 — 저주파 교차의 음수 PM

    assert closed_loop_unstable(loop) == []  # 이 루프를 닫은 폐루프는 안정이다
    m = nyquist_margins(loop)
    assert m["pm_deg"] == pytest.approx(-old["pm_deg"]) and m["wcp"] == old["wcp"]  # 같은 교차, 거리로
    assert m["pm_lead"] is True
    assert m["gm_db"] == old["gm_db"] and m["wcg"] == old["wcg"] and "gm_lower" not in m  # 작동기 대역, 올리는 쪽
    assert "closed_loop" not in m
    # 공개 — 교차 전량(control 부호 관례). 루프 교차(가장 높은 0 dB 교차)의 PM은 90° 남짓, 지연 쪽 여유다
    gains = m["crossings"]["gain"]
    assert len(gains) == 4, gains
    top = max(gains, key=lambda g: g["w"])
    assert top["w"] > 1.0 and top["pm_deg"] == pytest.approx(92.8, abs=0.5)


def test_slow_real_divergence_is_disclosed_and_gm_is_not_read_at_dc():
    """쇼케이스 roll_p — control.margin은 ω = 0의 −180° 교차(|L(0)| ≈ 3)를 GM −9.7 dB로 낸다. 그 판독은 이 루프만
    닫으면 나선이 느리게 발산한다(실근 +0.009 rad/s)는 사실의 다른 얼굴이다 — 안정 여유가 아니다. 불안정 폐루프는
    루프 교차(7.1 rad/s)의 고전 판독을 내고 발산극을 closed_loop로 따로 말한다: 루프 대역은 PM 82°·GM 10 dB다."""
    loop = _rate_loop(S1_LAT_A, S1_LAT_B, 1, S1_ROLL_K)
    old = loop_margins(loop)
    assert old["wcg"] == 0.0 and old["gm_db"] < -6.0, old  # 병리 전제 — 직류 판독의 음수 GM

    m = nyquist_margins(loop)
    assert m["pm_deg"] == pytest.approx(81.8, abs=0.5) and m["wcp"] == pytest.approx(7.10, abs=0.05)
    assert m["gm_db"] == pytest.approx(10.14, abs=0.05) and 15.0 < m["wcg"] < 25.0  # 루프 교차에 가장 가까운 −180°
    cl = m["closed_loop"]
    assert cl["stable"] is False and len(cl["unstable"]) == 1
    re, im = cl["unstable"][0]
    assert im == 0.0 and 0.0 < re < 0.05 and math.log(2.0) / re > 60.0  # 느린 실근 — 배가 ≈ 75 s
    assert "pm_lead" not in m and "gm_lower" not in m  # 방향 표시는 안정 여유에만 붙는다
    phase = m["crossings"]["phase"]
    assert phase[0]["w"] == 0.0 and phase[0]["gm_db"] == pytest.approx(old["gm_db"])  # 직류 판독도 공개한다


def test_in_band_instability_stays_negative_and_is_named():
    """재튜닝 전 예제 기체 pitch_q(k_rate 0.8 — 녹화) — 작동기·지연을 넣으면 이 루프만 닫은 폐루프가 작동기 대역에서 발산한다
    (01 §7의 4.4 Hz 지속 피치 진동 자리). control.margin은 장주기 교차(0.14 rad/s)의 −34°를 골라 교차 대역을
    가렸다. 진짜 문제는 진짜 문제로 남는다 — 루프 교차(28.5 rad/s)의 음수 PM·음수 GM·교차 대역의 발산 쌍."""
    loop = _rate_loop(EX_LON_A, EX_LON_B, 2, EX_PITCH_K)
    old = loop_margins(loop)
    assert old["wcp"] < 1.0, old  # 병리 전제 — 저주파 교차를 골랐다

    m = nyquist_margins(loop)
    assert m["wcp"] > 20.0 and m["pm_deg"] == pytest.approx(-44.4, abs=0.5)
    assert m["gm_db"] == pytest.approx(-4.80, abs=0.05) and m["wcg"] == pytest.approx(20.58, abs=0.05)
    cl = m["closed_loop"]
    assert cl["stable"] is False
    assert any(im > 10.0 and re > 1.0 for re, im in cl["unstable"]), cl  # 교차 대역의 진동 발산 쌍


def test_conditionally_stable_loop_reports_the_gain_reduction_margin_as_a_margin():
    """개루프 불안정 극을 루프가 안정시키는 경우(L = 2/(s−1)) — 폐루프 극 −1(안정). −180° 교차는 ω = 0의 |L| = 2
    하나뿐이라 control.margin은 GM −6.02 dB(부족처럼 읽힌다)를 낸다. 그 자리는 이득을 **내려야** 닿는다 — 절반으로
    내리면 한계. 여유는 6.02 dB(±6 dB 요구의 내리는 쪽)이고 방향을 gm_lower로 말한다."""
    s = control.tf("s")
    loop = 2.0 / (s - 1.0)
    old = loop_margins(loop)
    assert old["gm_db"] == pytest.approx(-6.0206, abs=1e-3)  # 종전 판독
    m = nyquist_margins(loop)
    assert m["gm_db"] == pytest.approx(6.0206, abs=1e-3) and m["gm_lower"] is True and m["wcg"] == 0.0
    assert m["pm_deg"] == pytest.approx(60.0, abs=1e-6) and m["wcp"] == pytest.approx(math.sqrt(3.0))
    assert "closed_loop" not in m and "crossings" not in m and "pm_lead" not in m


def test_lead_direction_distance_is_the_margin_even_when_it_is_thin():
    """폐루프 안정·교차점이 −1 바로 위(control PM −4.1°) — 여유는 4.1°이고 넘기는 쪽은 진상이다. 부호를 떼도 얇은
    여유는 얇게 남는다(이 방식이 나쁜 루프를 좋게 칠하지 않는다는 확인)."""
    s = control.tf("s")
    loop = -2.1 * (s + 0.5) * (s + 3.0) / ((s + 1.0) * (s + 2.0) ** 2)
    assert closed_loop_unstable(loop) == []  # 픽스처 전제
    old = loop_margins(loop)
    m = nyquist_margins(loop)
    assert old["pm_deg"] == pytest.approx(-4.14, abs=0.01)
    assert m["pm_deg"] == pytest.approx(4.14, abs=0.01) and m["pm_lead"] is True and m["wcp"] == old["wcp"]
    assert len(m["crossings"]["gain"]) == 2


def test_single_crossing_stable_loops_are_bit_identical_to_loop_margins():
    """고를 것이 없으면 두 정의가 같다 — 교과서 루프에서 dict가 같다(키·순서·값, nan은 nan끼리).
    PI 적분기 × q←δe 원점 영점의 상쇄 모드(Re ≈ −1e−16)를 한계 발산으로 세지 않는다 — 종전 골든 꼴(PI on q)."""
    def same(a, b):
        return list(a) == list(b) and all(
            (isinstance(a[k], float) and math.isnan(a[k]) and math.isnan(b[k])) or a[k] == b[k] for k in a)

    s = control.tf("s")
    for loop in (1.0 / (s * (s + 1.0)), 10.0 / (s * (s + 1.0) * (s + 5.0))):
        assert same(nyquist_margins(loop), loop_margins(loop))
        assert list(nyquist_margins(loop)) == ["gm_db", "pm_deg", "wcg", "wcp"]
    from claw.analysis import pi_loop

    pi = pi_loop(_model(S1_LON_A, S1_LON_B), x_out="s2", u_in="u", kp=0.5, ki=0.8)
    assert np.min(np.abs(control.feedback(pi, 1).poles())) < 1e-9  # 픽스처 전제 — 상쇄 모드가 원점에 앉아 있다
    assert closed_loop_unstable(pi) == []
    m = nyquist_margins(pi)
    assert "closed_loop" not in m
    assert same({k: m[k] for k in ("gm_db", "pm_deg", "wcg", "wcp")},
                {k: abs(v) for k, v in loop_margins(pi).items()})


def test_margin_map_and_bode_data_use_the_same_definition():
    """엔진 margin_map(마진 맵 수치 계층)과 bode_data의 margins는 nyquist_margins 그대로 — 칸과 곡선이 같은 수."""
    loop = _rate_loop(S1_LON_A, S1_LON_B, 2, S1_PITCH_K)
    want = nyquist_margins(loop)
    assert margin_map({"c": loop})["c"] == want
    assert bode_data(loop)["margins"] == want


# ── 끊는 자리 — 같은 축의 나머지 루프를 닫고 끊는다 (broken_loop, AS94900) ──────────────────────────────

# 쇼케이스 M0.15/h200/f10 횡축 (v, p, r, φ) · 입력 (δa, δr) · 그 칸의 roll·yaw k_rate — 저고도 저속이라 롤 댐퍼가 가장 세다
S1_LAT2_A = [[-0.26221343615393783, 6.048737956202459, -50.56834895032114, 9.737238309841048],
             [-0.8595322660813505, -3.5455705975854785, 0.53720766630083, 0.0],
             [0.10635715939204353, -0.029543655386677983, -0.17726193232006787, 0.0],
             [0.0, 1.0, 0.1196150968295366, 0.0]]
S1_LAT2_B = [[0.0, 2.337583279184858], [39.3974709974976, 0.0],
             [-0.48147956316886875, -2.407397815844344], [0.0, 0.0]]
S1_ROLL2_K = -0.3473601684364148
S1_YAW2_K = 1.2081460554760663


def _lat_model():
    from claw.common.contracts import LinearModel

    return LinearModel(A=np.array(S1_LAT2_A), B=np.array(S1_LAT2_B), C=np.eye(4), D=np.zeros((4, 2)),
                       x_names=("v", "p", "r", "phi"), u_names=("da", "dr"), axis="lat")


def _fr(sys, w):
    return np.asarray(control.frequency_response(sys, w).complex).ravel()


def test_broken_loop_without_others_is_pi_loop():
    """닫을 루프가 없으면 pi_loop 그대로 — 루프 하나짜리 요청(서버 골든 margin_map)의 수가 비트까지 같다."""
    from claw.analysis import broken_loop, pi_loop

    m = _model(S1_LON_A, S1_LON_B)
    a = broken_loop(m, "s2", "u", 0.5, ki=0.8, sign=-1.0, others=(), **ACT)
    b = pi_loop(m, "s2", "u", 0.5, ki=0.8, sign=-1.0, **ACT)
    assert np.array_equal(a.num[0][0], b.num[0][0]) and np.array_equal(a.den[0][0], b.den[0][0])
    assert loop_margins(a) == loop_margins(b)


def test_broken_loop_matches_the_textbook_interconnection():
    """독립 대조 — 같은 입력(δa)을 쓰는 두 루프(φ PI를 닫고 p 레이트를 끊는다), 작동기·지연 포함. 한 입력이라 SISO
    대수로 풀린다: T(u_cmd → p) = Act·G_p / (1 + C_φ·D·Act·G_φ), L = sign·k·D·T. 주파수응답이 격자 전 점에서 같다."""
    from claw.analysis import broken_loop, make_siso

    lm = _lat_model()
    s = control.tf("s")
    act = 900.0 / (s * s + 2 * 0.7 * 30.0 * s + 900.0)
    num, den = control.pade(0.035, 2)
    dly = control.tf(num, den)
    c_phi = -1.0 * (1.2 + 0.3 / s)  # sign −1 · PI
    g_p = control.ss2tf(make_siso(lm, "p", "da"))
    g_phi = control.ss2tf(make_siso(lm, "phi", "da"))
    want = (-1.0 * S1_ROLL2_K) * dly * act * g_p / (1 + c_phi * dly * act * g_phi)
    got = broken_loop(lm, "p", "da", S1_ROLL2_K, others=[{"x_out": "phi", "u_in": "da", "kp": 1.2, "ki": 0.3,
                                                             "sign": -1.0}], **ACT)
    w = np.logspace(-2, 2.5, 60)
    assert np.allclose(_fr(got, w), _fr(want, w), rtol=1e-6, atol=1e-9)


def test_broken_loop_closes_other_inputs_like_the_rate_closure():
    """다른 입력(δr)의 정적 요 댐퍼를 닫는 것은 A′ = A + B_δr·k·e_rᵀ (design.closure.close_rates — 법칙의 u += k·rate)와
    같다 — 작동기·지연이 없으면 두 조립의 roll_p 개루프가 같은 전달함수다."""
    from claw.analysis import broken_loop, pi_loop
    from claw.design.closure import close_rates

    lm = _lat_model()
    ref = pi_loop(close_rates(lm, {"yaw.k_rate": S1_YAW2_K}), "p", "da", S1_ROLL2_K, sign=-1.0)
    got = broken_loop(lm, "p", "da", S1_ROLL2_K, sign=-1.0,
                      others=[{"x_out": "r", "u_in": "dr", "kp": S1_YAW2_K, "ki": 0.0, "sign": -1.0}])
    w = np.logspace(-3, 2, 80)
    assert np.allclose(_fr(got, w), _fr(ref, w), rtol=1e-7, atol=1e-10)


def test_showcase_roll_rate_margins_with_the_yaw_damper_closed():
    """쇼케이스 roll_p(M0.15/h200/f10) — 요 댐퍼를 연 채로 재면 이 루프만 닫은 폐루프의 나선이 발산해 교차 판독이
    뜻을 잃는다. 요 댐퍼를 닫고(기체가 실제로 나는 폐루프) 끊으면 폐루프는 안정이고 여유는 루프 교차(13.5 rad/s)·
    작동기 대역(20 rad/s)의 것이다: PM 39.9° · GM 4.10 dB — 작동기 30 rad/s·지연 35 ms 조성에서 AS94900 6 dB/45°에
    **실제로 못 미친다**(게인 탭 판정은 레이트 루프를 ζ로 재고 이 여유는 재지 않는다 — 04 §2). 진짜 수로 남는다."""
    from claw.analysis import broken_loop

    lm = _lat_model()
    alone = nyquist_margins(broken_loop(lm, "p", "da", S1_ROLL2_K, **ACT))
    assert alone.get("closed_loop", {}).get("stable") is False  # 병리 전제 — 요 댐퍼 없이 닫으면 나선 발산
    yaw = {"x_out": "r", "u_in": "dr", "kp": S1_YAW2_K, "ki": 0.0, "sign": -1.0}
    m = nyquist_margins(broken_loop(lm, "p", "da", S1_ROLL2_K, others=[yaw], **ACT))
    assert "closed_loop" not in m
    assert m["pm_deg"] == pytest.approx(39.93, abs=0.05) and m["wcp"] == pytest.approx(13.46, abs=0.05)
    assert m["gm_db"] == pytest.approx(4.10, abs=0.02) and m["wcg"] == pytest.approx(20.14, abs=0.05)
    # 거꾸로 — yaw_r을 끊고 roll_p를 닫아도 안정, 요 여유는 넉넉하다
    roll = {"x_out": "p", "u_in": "da", "kp": S1_ROLL2_K, "ki": 0.0, "sign": -1.0}
    y = nyquist_margins(broken_loop(lm, "r", "dr", S1_YAW2_K, others=[roll], **ACT))
    assert "closed_loop" not in y and y["pm_deg"] > 60.0 and y["gm_db"] > 12.0


def test_broken_loop_rejects_half_actuator():
    from claw.analysis import broken_loop

    with pytest.raises(ValueError, match="함께"):
        broken_loop(_lat_model(), "p", "da", 0.3, others=[{"x_out": "r", "u_in": "dr", "kp": 1.0}], actuator_wn=30.0)
