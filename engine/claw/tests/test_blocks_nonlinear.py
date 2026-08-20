"""M2 blocks 검증 — 비선형(DeadZone·Backlash·Hysteresis)·Fader (Phase 1 백로그 소진)."""

import pytest

from claw.blocks import Backlash, DeadZone, Fader, Hysteresis

DT = 0.01


# ---- DeadZone ----


def test_dead_zone_zero_inside_band():
    dz = DeadZone(lo=-0.5, hi=0.5).init(DT)
    assert dz.step(0.0) == 0.0
    assert dz.step(0.5) == 0.0  # 경계 포함
    assert dz.step(-0.5) == 0.0


def test_dead_zone_offset_outside_band():
    dz = DeadZone(lo=-0.5, hi=0.5).init(DT)
    assert dz.step(1.2) == pytest.approx(0.7)  # 초과분만 출력 (Simulink 관례)
    assert dz.step(-2.0) == pytest.approx(-1.5)


def test_dead_zone_invalid_range():
    with pytest.raises(ValueError):
        DeadZone(lo=1.0, hi=-1.0)


# ---- Backlash ----


def test_backlash_holds_inside_gap():
    b = Backlash(width=0.4, initial=0.0).init(DT)
    assert b.step(0.1) == pytest.approx(0.0)  # 갭 내부 — 이동 없음
    assert b.step(-0.1) == pytest.approx(0.0)


def test_backlash_tracks_with_half_width_lag():
    b = Backlash(width=0.4, initial=0.0).init(DT)
    assert b.step(1.0) == pytest.approx(0.8)  # 갭 상단이 입력을 half=0.2 뒤에서 추종
    assert b.step(0.9) == pytest.approx(0.8)  # 방향 반전 직후 갭 내부 — 유지
    assert b.step(0.3) == pytest.approx(0.5)  # 갭 하단에 닿아 하강 추종


def test_backlash_zero_width_is_passthrough():
    b = Backlash(width=0.0).init(DT)
    for u in (0.3, -1.2, 2.5):
        assert b.step(u) == pytest.approx(u)


def test_backlash_warm_start_and_validation():
    b = Backlash(width=0.4).init(DT)
    b.reset(5.0)
    assert b.step(5.1) == pytest.approx(5.0)  # 웜스타트 출력 기준 갭 내부
    with pytest.raises(ValueError):
        Backlash(width=-0.1)


# ---- Hysteresis ----


def test_hysteresis_switching_and_deadband_memory():
    h = Hysteresis(low_threshold=-1.0, high_threshold=1.0, low_value=0.0, high_value=10.0).init(DT)
    assert h.step(0.0) == 0.0  # 초기 저상태
    assert h.step(1.0) == 10.0  # 상승 임계 도달(경계 포함) → 고상태
    assert h.step(0.0) == 10.0  # 데드밴드 내부 — 상태 유지
    assert h.step(-1.0) == 0.0  # 하강 임계 도달 → 저상태
    assert h.step(0.999) == 0.0  # 임계 미만 — 유지


def test_hysteresis_warm_start_high():
    h = Hysteresis().init(DT)
    h.reset(True)
    assert h.step(0.0) == 1.0  # 고상태에서 시작


def test_hysteresis_invalid_thresholds():
    with pytest.raises(ValueError):
        Hysteresis(low_threshold=1.0, high_threshold=-1.0)


# ---- Fader ----


def test_fader_passes_a_before_trigger():
    f = Fader(duration=1.0).init(0.1)
    for _ in range(5):
        assert f.step((3.0, 100.0)) == pytest.approx(3.0)


def test_fader_completes_in_duration():
    f = Fader(duration=1.0).init(0.1)
    f.trigger()
    outs = [f.step((0.0, 10.0)) for _ in range(10)]  # 10스텝 = duration
    assert outs[0] == pytest.approx(1.0)  # w = dt/duration = 0.1
    assert all(outs[i] < outs[i + 1] for i in range(8))  # 단조 증가 램프
    assert outs[-1] == pytest.approx(10.0)
    assert f.step((0.0, 10.0)) == pytest.approx(10.0)  # 완료 후 b 고정


def test_fader_warm_start_weight_and_validation():
    f = Fader(duration=1.0).init(0.1)
    f.reset(0.5)
    assert f.step((0.0, 10.0)) == pytest.approx(6.0)  # w: 0.5 → 0.6
    with pytest.raises(ValueError):
        f.reset(1.5)
    with pytest.raises(ValueError):
        Fader(duration=0.0)


def test_fader_reset_determinism():
    f = Fader(duration=0.5).init(0.1)
    f.trigger()
    outs1 = [f.step((0.0, 1.0)) for _ in range(8)]
    f.reset()
    f.trigger()
    outs2 = [f.step((0.0, 1.0)) for _ in range(8)]
    assert outs1 == outs2
