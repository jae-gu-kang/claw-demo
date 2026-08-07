"""M2 blocks 검증 — 프로토콜 계약 + 기본 연산·신호 저장 블록 해석해 대조 (Phase 1)."""

import inspect

import pytest

from claw.blocks import (
    REGISTRABLE,
    Block,
    Delay,
    Divide,
    Gain,
    Memory,
    Product,
    Saturation,
    Sum,
    Switch,
    UnitDelay,
    register_all,
)
from claw.params.registry import REGISTRY, ComponentRegistry, RegistryError

DT = 0.01


def make_instances():
    """대표 파라미터로 만든 전 블록 인스턴스 (프로토콜 공통 테스트용)."""
    return [
        Gain(2.0),
        Sum((1.0, -1.0)),
        Product(),
        Divide(),
        Switch(0.5),
        Saturation(-1.0, 1.0),
        Delay(3, initial=9.0),
        UnitDelay(),
        Memory(),
    ]


# ---- 프로토콜 계약 ----


@pytest.mark.parametrize("blk", make_instances(), ids=lambda b: type(b).__name__)
def test_init_returns_self(blk):
    assert blk.init(DT) is blk
    assert blk.dt == DT


def test_init_rejects_nonpositive_dt():
    with pytest.raises(ValueError):
        Gain().init(0.0)
    with pytest.raises(ValueError):
        Gain().init(-0.01)


@pytest.mark.parametrize("cls", REGISTRABLE, ids=lambda c: c.NAME)
def test_schema_matches_constructor(cls):
    """스키마 키 == 생성자 kwargs — 레지스트리 create()가 cls(**values)로 직결되는 근거."""
    props = set(cls.schema()["properties"])
    kwargs = set(inspect.signature(cls.__init__).parameters) - {"self"}
    assert props == kwargs


def test_registry_roundtrip():
    reg = ComponentRegistry()
    register_all(reg)
    assert set(reg.names("blocks")) == {cls.NAME for cls in REGISTRABLE}
    g = reg.create("blocks", "Gain", {"k": 3.0}).init(DT)
    assert g.step(2.0) == pytest.approx(6.0)
    with pytest.raises(RegistryError):
        register_all(reg)  # 중복 등록 거부


def test_global_registry_autoregistered():
    """claw.blocks import 시 전역 REGISTRY에 1회 자동 등록된다."""
    assert "Gain" in REGISTRY.names("blocks")
    assert "Integrator" in REGISTRY.names("blocks")


# ---- 기본 연산 블록: 대수 항등 ----


def test_gain():
    assert Gain(2.5).init(DT).step(4.0) == pytest.approx(10.0)


def test_sum_signs():
    assert Sum((1.0, -1.0)).init(DT).step((5.0, 2.0)) == pytest.approx(3.0)
    assert Sum().init(DT).step((1.5, 2.5)) == pytest.approx(4.0)


def test_product_divide():
    assert Product().init(DT).step((2.0, 3.0, 4.0)) == pytest.approx(24.0)
    assert Divide().init(DT).step((6.0, 3.0)) == pytest.approx(2.0)


def test_switch_threshold():
    sw = Switch(threshold=0.5).init(DT)
    assert sw.step((10.0, 0.5, 20.0)) == 10.0  # ctrl == threshold → in1 (Simulink 관례)
    assert sw.step((10.0, 0.49, 20.0)) == 20.0


def test_saturation():
    sat = Saturation(-1.0, 2.0).init(DT)
    assert sat.step(-3.0) == -1.0
    assert sat.step(0.7) == 0.7
    assert sat.step(5.0) == 2.0
    with pytest.raises(ValueError):
        Saturation(1.0, -1.0)


# ---- 신호 저장 블록 ----


def test_delay_shifts_by_n():
    d = Delay(3, initial=9.0).init(DT)
    outs = [d.step(u) for u in [1.0, 2.0, 3.0, 4.0, 5.0]]
    assert outs == [9.0, 9.0, 9.0, 1.0, 2.0]


def test_unit_delay_and_memory():
    for blk in (UnitDelay(), Memory()):
        blk.init(DT)
        outs = [blk.step(u) for u in [1.0, 2.0, 3.0]]
        assert outs == [0.0, 1.0, 2.0]


def test_delay_warm_start_and_bad_state():
    d = Delay(2, initial=0.0).init(DT)
    d.reset([7.0, 8.0])
    assert d.step(1.0) == 7.0
    with pytest.raises(ValueError):
        d.reset([1.0])  # 짧은 버퍼
    with pytest.raises(ValueError):
        d.reset([1.0, 2.0, 3.0])  # 긴 버퍼 — 조용한 절단 금지


def test_delay_invalid_n():
    with pytest.raises(ValueError):
        Delay(0)
    with pytest.raises(ValueError):
        Delay(1.7)  # 소수 절단 금지


def test_sum_rejects_length_mismatch():
    with pytest.raises(ValueError):
        Sum((1.0, -1.0)).init(DT).step((5.0, 2.0, 100.0))  # 배선 실수의 조용한 절단 금지


@pytest.mark.parametrize(
    "blk",
    [Delay(2, initial=0.5), UnitDelay(), Memory()],
    ids=lambda b: type(b).__name__,
)
def test_reset_determinism(blk):
    """reset() 후 같은 입력열에 같은 출력열 — 상태 완전 초기화 계약."""
    seq = [0.3, -1.2, 2.5, 0.0, 1.1]
    blk.init(DT)
    outs1 = [blk.step(u) for u in seq]
    blk.reset()
    outs2 = [blk.step(u) for u in seq]
    assert outs1 == outs2
