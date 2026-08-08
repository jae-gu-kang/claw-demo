"""엔진 산출물 계약 → JSON 표현 (M13). 도메인 계산 없음 — 형 변환·비유한값 정책만.

비유한값 [기본값]: NaN → null, ±inf → "inf"/"-inf" 문자열. JSON 표준에
NaN·Infinity가 없어 브라우저 파서와 호환되도록 저장 전에 정리한다 —
ResultStore가 allow_nan=False로 직렬화해 이 정책 위반을 저장 시점에 잡는다.
소비자(M14)는 마진 무한대("inf")를 문자열로 식별한다.
복소수(고유치) → [re, im] 2원소 배열.
"""

import numpy as np


def _clean_float(v: float):
    if v != v:  # NaN
        return None
    if v == float("inf"):
        return "inf"
    if v == float("-inf"):
        return "-inf"
    return v


def _array(a: np.ndarray):
    if a.dtype.kind == "f" and not np.all(np.isfinite(a)):
        if a.ndim == 0:
            return _clean_float(float(a))
        if a.ndim == 1:
            return [_clean_float(float(v)) for v in a]
        return [_array(row) for row in a]
    return a.tolist()  # 유한 배열 고속 경로 (시계열 대형 배열)


def to_jsonable(x):
    """ndarray·numpy 스칼라·중첩 dict/list → JSON 직렬화 가능 값 (비유한값 정책 적용)."""
    if isinstance(x, np.ndarray):
        return _array(x)
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, (np.floating, np.integer, np.complexfloating)):
        return to_jsonable(x.item())
    if isinstance(x, complex):
        return [_clean_float(x.real), _clean_float(x.imag)]
    if isinstance(x, float):
        return _clean_float(x)
    if isinstance(x, dict):
        return {k: to_jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [to_jsonable(v) for v in x]
    return x


def trim_result_dict(tr) -> dict:
    """TrimResult → JSON 표현 — 케이스·수렴·판정 플래그·트림 상태/입력.

    전체를 to_jsonable로 마감 — 발산 해의 NaN/inf도 비유한값 정책을 우회하지
    않는다 (개별 필드의 원시 float 통과 금지).
    """
    phi, theta, psi = (float(v) for v in tr.state.euler())
    return to_jsonable({
        "case": {
            "name": tr.case.name,
            "mach": tr.case.mach,
            "alt": tr.case.alt,
            "fuel": tr.case.fuel,
            "condition": tr.case.condition,
        },
        "converged": bool(tr.converged),
        "cost": float(tr.cost),
        "flags": dict(tr.flags),  # continuity_ok는 3-상태 (None = 미판정)
        "euler": [phi, theta, psi],
        "vel_b": tr.state.vel_b,
        "control": {
            "elevon": tr.control.elevon,
            "rudder": float(tr.control.rudder),
            "throttle": tr.control.throttle,
        },
        "params_fingerprint": tr.params_fingerprint,
    })


def sim_result_dict(res, stride: int = 1) -> dict:
    """SimResult → JSON 표현 — stride 다운샘플 (재생·플롯용, 요약 스칼라는 원본 유지)."""
    if stride < 1:
        raise ValueError(f"stride는 1 이상이어야 함: {stride}")
    sl = slice(None, None, stride)
    signals = {
        k: to_jsonable(v[sl]) if isinstance(v, np.ndarray) else to_jsonable(list(v[sl]))
        for k, v in res.signals.items()
    }
    envelope = {}
    for k, v in res.envelope.items():
        if k == "stall_margin":
            envelope[k] = to_jsonable(np.asarray(v)[sl])
        elif k == "flags":
            envelope[k] = {name: to_jsonable(np.asarray(a)[sl]) for name, a in v.items()}
        else:
            envelope[k] = to_jsonable(v)  # worst_margin 등 — 원본 해상도 요약값
    return {
        "t": to_jsonable(res.t[sl]),
        "signals": signals,
        "envelope": envelope,
        "meta": to_jsonable(res.meta),
        "params_fingerprint": res.params_fingerprint,
        "n_total": int(len(res.t)),
        "stride": int(stride),
    }
