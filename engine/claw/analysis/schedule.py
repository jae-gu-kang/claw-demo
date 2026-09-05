"""게인 스케줄 매끄러움 — 인접 격자점 사이의 상대 점프 (평가 항목 11, 02 §2.4).

각 operating point가 좋은 것만으로는 부족하다 — 게인이 보간되는 격자점 **사이**에서
급변·불연속이 있으면 전이 중 특성이 흔들린다. 이 모듈은 저장된 게인 테이블만 보고
(시뮬 0회) 인접 격자점 간 점프를 잰다.

판정량은 **상대 점프** |ΔK| / max(|K₁|, |K₂|)다. 테이블마다 단위가 다르므로
(kp[-]·tau[s]·클램프[rad]) 절대 기울기로는 한 문턱에 못 세운다. 축 단위 기울기
|ΔK|/Δx는 정보로만 동봉한다 — mach(무차원)와 alt[m]의 기울기는 서로 비교가 안 된다.

격자점이 1개뿐인 축은 점프가 정의되지 않는다 — 그 축 항목을 **내지 않는다**
(0으로 채우면 "잴 것이 없다"가 "완벽히 매끄럽다"로 위장된다, 01 §4.2 규약).

중간점(mach_midpoints)은 여기서 **좌표만** 만든다 — 케이스 구성·트림·평가는
호출자가 기존 격자 경로로 돌린다. 보간 지점의 안정성·마진은 테이블만 봐서는
알 수 없으므로(같은 mach에서 플랜트도 변한다) 실측이 답이다.
"""

import numpy as np

# 0 근방 게인의 상대 점프 발산을 막는 바닥. 두 값이 전부 이 아래면 "꺼진 자리"로
# 보고 점프 0으로 센다 — 0 → 1e-12는 급변이 아니라 잡음이다.
_SCALE_FLOOR = 1e-9


def _axis_jump(data, axes, i):
    """축 i를 따라 인접 격자점 상대 점프의 최대 — (max_rel, at, gap, max_grad).

    at은 최대가 난 인접 쌍의 축 좌표 (x_j, x_{j+1})다. 다차원 테이블은 다른 축의
    전 조합에서 최댓값을 취한다 — "어느 조합에서든 급변이 있으면 급변이 있다".
    """
    a = np.moveaxis(np.asarray(data, dtype=float), i, 0)
    d = np.abs(np.diff(a, axis=0))
    scale = np.maximum(np.abs(a[:-1]), np.abs(a[1:]))
    off = scale < _SCALE_FLOOR  # 양끝 다 사실상 0 — 꺼진 자리
    rel = np.where(off, 0.0, d / np.maximum(scale, _SCALE_FLOOR))
    j_flat = int(np.argmax(rel))
    j = int(np.unravel_index(j_flat, rel.shape)[0])
    ax = np.asarray(axes[i], dtype=float)
    gaps = np.diff(ax).reshape((-1,) + (1,) * (rel.ndim - 1))
    with np.errstate(divide="ignore", invalid="ignore"):
        grad = np.where(gaps > 0.0, d / gaps, np.inf)
    return (
        float(rel.flat[j_flat]),
        (float(ax[j]), float(ax[j + 1])),
        float(ax[j + 1] - ax[j]),
        float(np.max(grad)),
    )


def table_smoothness(tables: dict) -> dict:
    """{이름: Table} → 테이블·축별 최대 상대 점프.

    반환: {이름: {"per_axis": {축이름: {max_rel_step, at, gap, max_grad}},
                "max_rel_step": 전 축 최대(잴 축이 없으면 None)}}
    """
    out = {}
    for name, t in tables.items():
        per_axis = {}
        for i, ax_name in enumerate(t.axis_names):
            if np.asarray(t.axes[i]).size < 2:
                continue  # 점프가 정의되지 않는 축 — 항목을 내지 않는다
            rel, at, gap, grad = _axis_jump(t.data, t.axes, i)
            per_axis[ax_name] = {
                "max_rel_step": rel, "at": list(at), "gap": gap, "max_grad": grad,
            }
        out[name] = {
            "per_axis": per_axis,
            "max_rel_step": (max(v["max_rel_step"] for v in per_axis.values())
                             if per_axis else None),
        }
    return out


def mach_midpoints(tables: dict, lo=None, hi=None) -> list:
    """전 테이블 mach 격자점 합집합의 인접 쌍 중간값 — 스케줄 전이 케이스의 mach 좌표.

    lo/hi 창 밖은 버린다(요청 케이스 격자의 창과 맞춘다). mach 축이 없는 테이블은
    기여하지 않는다. 반환은 오름차순·중복 제거 — 케이스 이름이 이 값으로 만들어지므로
    순서가 결정적이어야 한다.
    """
    pts: set = set()
    for t in tables.values():
        for ax_name, ax in zip(t.axis_names, t.axes):
            if ax_name == "mach":
                pts.update(float(v) for v in np.asarray(ax, dtype=float))
    bps = sorted(pts)
    mids = [(a + b) / 2.0 for a, b in zip(bps[:-1], bps[1:])]
    if lo is not None:
        mids = [m for m in mids if m >= float(lo)]
    if hi is not None:
        mids = [m for m in mids if m <= float(hi)]
    return mids
