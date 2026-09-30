"""기본 모델 격자 (05 §11.11) — 트림·선형모델을 미리 확보하는 이름 붙은 점 집합.

**공통 마하 좌표**에 둔다 [기본값]: 요구영역 전체 마하를 n_mach 등간격한 좌표를 행(고도·연료)의 요구 범위로
거르고 행 끝점(하한·상한)을 더한다. 행마다 자기 범위를 따로 등분하면 절점·검증점(공통 좌표)과 좌표가 어긋나
기본 격자가 재사용되지 않는다 — 실측 재사용률 0.31~0.33 → 0.85 (05 §11.10).

물리 경계(실속·추력)로 행을 깎지 않는다 — 그것은 조건의 판정 결과다(05 §11.2). 모델 범위 밖의 점도 지우지 않고
「모델 부족」 상태로 싣는다. 요구 미정의 행은 점이 없지만 행 목록에 그 상태로 남는다 — 계산하지 못한 것이
목록에서 사라지지 않게(05 §11.8).
"""

from __future__ import annotations

import numpy as np

from claw.opspace.states import NOT_RUN, UNDEFINED, pre_state

_EPS = 1e-9
MAX_BASE_POINTS = 400  # 한 번에 만드는 기본 격자 상한 — 오타 명세가 단일 워커를 물지 않게


def _r(x: float) -> float:
    return round(float(x), 9)  # 부동소수 오차 제거 — 이름이 값 그대로라 0.30000000000000004가 새지 않게


def base_grid(region, model, *, n_mach: int | None = None, alts=None, fuels=None) -> dict:
    """{"points": [{mach, alt, fuel, name, state}], "rows": [{alt, fuel, bounds, n, state}], "axis": [...]}.

    명세를 안 주면 영역의 기본 격자 명세(region.grid)를 쓴다. 점 순서는 서펜타인(행마다 마하 방향을 뒤집는다)이라
    배치 트림의 인접 시드가 그대로 이어진다(01 §4.1). state는 트림 전 상태(미계산 · 모델 부족)다.
    """
    # 지연 import — claw.design 패키지가 이 모듈을 부르므로 모듈 머리에서 부르면 opspace를 먼저 import할 때 순환이 된다
    from claw.design.points import case_name

    n_mach = int(region.grid["n_mach"] if n_mach is None else n_mach)
    # 정렬·중복 제거 — 같은 고도가 두 번이면 같은 이름의 케이스가 두 번 나가(이름 = 케이스 매핑 키) 결과가 조용히 다른
    # 점에 귀속되고, 섞인 순서는 서펜타인 행을 물리적으로 떨어뜨려 인접 시드 전제를 깬다
    alts = sorted({float(a) for a in (region.grid["alts"] if alts is None else alts)})
    fuels = sorted({float(f) for f in (region.grid["fuels"] if fuels is None else fuels)})
    if n_mach < 2:
        raise ValueError(f"마하 점 수는 2 이상: {n_mach}")
    if not alts or not fuels:
        raise ValueError("고도·연료 목록이 비었다 — 하나 이상 적는다")
    axis = [_r(m) for m in np.linspace(region.mach[0], region.mach[1], n_mach)]
    points, rows, k = [], [], 0
    for fuel in fuels:
        for alt in alts:
            b = region.mach_bounds(alt, fuel)
            if b is None or region.classify(b[0], alt, fuel) is not None:
                # 경계표가 안 덮거나 기본 범위 밖의 행 — 점은 없고 행은 그 상태로 남는다
                # bounds는 싣지 않는다 — 영역 밖 행에 마하 범위를 실으면 화면이 없는 요구 띠를 그린다
                state = UNDEFINED if b is None else region.classify(b[0], alt, fuel)
                rows.append({"alt": alt, "fuel": fuel, "bounds": None, "n": 0, "state": state})
                continue
            lo, hi = _r(b[0]), _r(b[1])
            ms = sorted({lo, hi} | {m for m in axis if lo - _EPS <= m <= hi + _EPS})
            if k % 2:
                ms.reverse()
            k += 1
            for m in ms:
                points.append({"mach": m, "alt": alt, "fuel": fuel, "name": case_name(m, alt, fuel),
                               "state": pre_state(region, model, m, alt, fuel)})
            rows.append({"alt": alt, "fuel": fuel, "bounds": [lo, hi], "n": len(ms), "state": NOT_RUN})
            if len(points) > MAX_BASE_POINTS:
                raise ValueError(f"기본 격자가 {MAX_BASE_POINTS}점을 넘는다 — 마하 점 수·고도·연료 목록을 줄인다")
    return {"points": points, "rows": rows, "axis": axis}
