"""골든 부호화 — 부동소수를 `float.hex()`로 굳혀 **비트 단위** 비교가 되게 한다.

기체 프로파일 이관(02 §5.6)의 증거 장치다. 데모 기체를 코드에서 데이터로 옮겨도 예제
기체의 모든 산출이 이관 전과 같아야 하는데, `pytest.approx`류 허용오차 비교는 연산 순서가
바뀌어 생긴 1-ulp 차이를 삼킨다 — 그 차이가 곧 "옮기다 식을 바꿨다"는 증거라 삼키면 안 된다.

규약:
- float → "f:<hex>" (−0.0·nan·inf도 구분된다), int·bool·str·None은 그대로
- tuple과 list, ndarray(shape·dtype 포함)는 서로 다른 것으로 부호화한다 — 컨테이너가
  바뀌면 소비자가 다르게 행동할 수 있으므로 동일성 증명에서 뭉개지 않는다
- dict는 **키 순서까지** 보존한다(JSON echo 순서가 응답 바이트를 바꾼다)
- dataclass·Table·일반 객체는 필드를 재귀 부호화한다. 호출 가능 객체는 거부한다
  (클로저 이름 같은 구현 세부가 골든에 박히면 이관 자체가 불일치가 된다)
"""

import dataclasses
import hashlib
import json

import numpy as np

CHUNK = 100


def encode(x):
    if x is None or isinstance(x, (bool, str)):
        return x
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return "f:" + float(x).hex()
    if isinstance(x, (complex, np.complexfloating)):
        return {"complex": [encode(float(x.real)), encode(float(x.imag))]}
    if isinstance(x, np.ndarray):
        return {"ndarray": list(x.shape), "dtype": str(x.dtype),
                "v": [encode(v) for v in x.ravel().tolist()]}
    if isinstance(x, tuple):
        return {"tuple": [encode(v) for v in x]}
    if isinstance(x, list):
        return [encode(v) for v in x]
    if isinstance(x, dict):
        if all(isinstance(k, str) for k in x):
            return {"dict": {k: encode(v) for k, v in x.items()}}
        return {"dict_pairs": [[encode(k), encode(v)] for k, v in x.items()]}
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return {"dataclass": type(x).__name__,
                "fields": {f.name: encode(getattr(x, f.name)) for f in dataclasses.fields(x)}}
    from claw.tables import Table

    if isinstance(x, Table):
        return {"Table": {"name": getattr(x, "name", None),
                          "axis_names": encode(tuple(x.axis_names)),
                          "axes": [encode(a) for a in x.axes],
                          "data": encode(x.data),
                          "extrapolate": x.extrapolate}}
    if callable(x):
        raise TypeError(f"호출 가능 객체는 골든에 넣지 않는다: {x!r}")
    if hasattr(x, "__dict__"):
        return {"object": type(x).__name__,
                "attrs": {k: encode(v) for k, v in vars(x).items()}}
    raise TypeError(f"골든 부호화 불가 타입: {type(x)!r}")


def dumps(enc) -> str:
    return json.dumps(enc, ensure_ascii=False, separators=(",", ":"))


def digest(seq) -> dict:
    """긴 목록 → 조각별 sha256 + 드문드문 표본. 어긋나면 첫 조각이 위치를 짚는다."""
    enc = [encode(v) for v in seq]
    shas = [hashlib.sha256(dumps(enc[i:i + CHUNK]).encode()).hexdigest()
            for i in range(0, len(enc), CHUNK)]
    step = max(1, len(enc) // 16)
    return {"n": len(enc), "chunk": CHUNK, "sha": shas,
            "samples": {str(i): enc[i] for i in range(0, len(enc), step)}}


def first_diff(a, b, path="$"):
    """두 부호화 값의 첫 차이 경로 — 없으면 None."""
    if type(a) is not type(b):
        return f"{path}: 타입 {type(a).__name__} ≠ {type(b).__name__}"
    if isinstance(a, dict):
        ka, kb = list(a), list(b)
        if ka != kb:
            return f"{path}: 키 {ka} ≠ {kb}"
        for k in ka:
            d = first_diff(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: 길이 {len(a)} ≠ {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_diff(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    return None if a == b else f"{path}: {a!r} ≠ {b!r}"
