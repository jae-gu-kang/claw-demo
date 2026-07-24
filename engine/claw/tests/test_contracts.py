import numpy as np
import pytest

from claw.common.attitude import euler_to_quat
from claw.common.contracts import (
    GuidanceCommand,
    LinearModel,
    SurfaceCommand,
    TrimCase,
    TrimResult,
    VehicleState,
)


def test_vehicle_state_defaults():
    s = VehicleState()
    assert s.pos_n.shape == (3,) and s.vel_b.shape == (3,) and s.omega_b.shape == (3,)
    assert np.allclose(s.q_nb, [1, 0, 0, 0])
    assert s.euler() == pytest.approx((0.0, 0.0, 0.0))


def test_vehicle_state_vel_n():
    s = VehicleState(q_nb=euler_to_quat(0.0, 0.0, np.pi / 2), vel_b=np.array([10.0, 0.0, 0.0]))
    assert np.allclose(s.vel_n(), [0.0, 10.0, 0.0], atol=1e-12)


def test_surface_command_shapes():
    c = SurfaceCommand()
    assert c.elevon.shape == (4,) and c.throttle.shape == (2,)


def test_guidance_command_flags_default_off():
    g = GuidanceCommand(speed=250.0, speed_on=True, mode="cruise")
    assert g.speed_on and not g.alt_on and not g.heading_on


def test_lineage_on_results():
    case = TrimCase(name="c1", mach=0.7, alt=1000.0, fuel=300.0)
    r = TrimResult(
        case=case,
        state=VehicleState(),
        control=SurfaceCommand(),
        converged=True,
        cost=1e-9,
        params_fingerprint="abc123",
    )
    m = LinearModel(
        A=np.zeros((4, 4)),
        B=np.zeros((4, 2)),
        C=np.eye(4),
        D=np.zeros((4, 2)),
        axis="lon",
        case=case,
        params_fingerprint="abc123",
    )
    # 계보 지문 — 트림 해와 그로부터 나온 선형모델이 같은 파라미터 스냅샷을 가리킴
    assert r.params_fingerprint == m.params_fingerprint == "abc123"
    assert m.dt == 0.0  # 연속시간 기본
