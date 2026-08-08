"""serialize 검증 — 비유한값 정책(NaN→null, ±inf→문자열), 계약 직렬화, stride 다운샘플."""

import json

import numpy as np
import pytest

from claw_server.serialize import sim_result_dict, to_jsonable, trim_result_dict


def test_to_jsonable_nonfinite_policy():
    a = np.array([1.0, np.nan, np.inf, -np.inf])
    assert to_jsonable(a) == [1.0, None, "inf", "-inf"]
    assert to_jsonable(np.float64(2.5)) == 2.5
    assert to_jsonable(np.bool_(True)) is True
    assert to_jsonable({"x": (np.int64(3), float("nan"))}) == {"x": [3, None]}
    # 저장 정책(allow_nan=False)과 호환 — 예외 없이 직렬화되어야 함
    json.dumps(to_jsonable({"m": np.array([np.nan, np.inf])}), allow_nan=False)


def test_to_jsonable_2d_array():
    assert to_jsonable(np.array([[1.0, np.nan], [2.0, 3.0]])) == [[1.0, None], [2.0, 3.0]]
    assert to_jsonable(np.eye(2)) == [[1.0, 0.0], [0.0, 1.0]]


def test_trim_result_dict_fields():
    from claw.common.contracts import TrimCase
    from claw.plant import make_demo_aircraft
    from claw.trim import trim_level

    tr = trim_level(
        make_demo_aircraft(), TrimCase("d", mach=0.6, alt=1000.0, fuel=200.0),
        fingerprint="fp1",
    )
    d = trim_result_dict(tr)
    assert d["case"] == {
        "name": "d", "mach": 0.6, "alt": 1000.0, "fuel": 200.0, "condition": "level",
    }
    assert d["converged"] is True
    assert d["flags"]["residual_ok"] is True
    assert d["flags"]["continuity_ok"] is None  # 3-상태(미판정) 보존
    assert len(d["euler"]) == 3 and len(d["vel_b"]) == 3
    assert len(d["control"]["elevon"]) == 4 and len(d["control"]["throttle"]) == 2
    assert d["params_fingerprint"] == "fp1"
    json.dumps(d, allow_nan=False)


def test_sim_result_dict_stride():
    from claw.common.contracts import SimResult

    n = 10
    res = SimResult(
        t=np.arange(n) * 0.1,
        signals={"h": np.linspace(0.0, 9.0, n), "mode": ["climb"] * 5 + ["cruise"] * 5},
        envelope={
            "stall_margin": np.full(n, 0.3),
            "flags": {"alpha": np.zeros(n, dtype=bool)},
            "worst_margin": 0.25,
            "first_flag_t": None,
        },
        params_fingerprint="fp",
        meta={"aborted": None},
    )
    d = sim_result_dict(res, stride=3)
    assert d["t"] == pytest.approx([0.0, 0.3, 0.6, 0.9])
    assert len(d["signals"]["h"]) == 4
    assert d["signals"]["mode"] == ["climb", "climb", "cruise", "cruise"]
    assert len(d["envelope"]["stall_margin"]) == 4
    assert len(d["envelope"]["flags"]["alpha"]) == 4
    assert d["envelope"]["worst_margin"] == 0.25  # 요약 스칼라는 원본 해상도 값 유지
    assert d["n_total"] == 10 and d["stride"] == 3
    json.dumps(d, allow_nan=False)
    with pytest.raises(ValueError):
        sim_result_dict(res, stride=0)
