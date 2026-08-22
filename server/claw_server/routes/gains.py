"""게인 스케줄 라우트 (02 §8 워크플로우 4단계) — 설계 게인 테이블·스케줄 자리 조회.

편집 흐름: GET으로 설계 테이블을 받아 웹에서 편집 → 시뮬 요청(gain_tables)에
주입. 저장·버전관리는 파라미터 관리 계층(02 §5.5)과 함께 확장 [TBD].

`/gains/catalog`은 **어떤 게인에 테이블을 붙일 수 있나**를 준다. 스케줄 대상은
값 편집과 달리 형상 자체를 바꾸므로(룩업이 생기거나 상수로 접힌다) 자리 목록과
"끄면 무엇이 되는가"(설계점 상수)를 함께 내려 준다. 자리 정본은 엔진의
`fcl/graphs.py` SCHEDULABLE이다 — 서버가 목록을 다시 적으면 웹이 "켤 수 있다"고
보여 준 자리가 실행 시점에 터진다.
"""

from fastapi import APIRouter

from claw.fcl.autopilot import Autopilot
from claw.fcl.demo import (
    DEFAULT_SCHEDULED,
    demo_design_gains,
    make_demo_fcl,
    make_demo_gain_tables,
)
from claw.fcl.graphs import SCHEDULABLE
from claw.fcl.scas import ScasAxis
from claw.fcl.schedule import AP_GAIN_FIELD
from claw_server.serialize import table_dict

router = APIRouter(tags=["gains"])

# 모든 게인 키 — 자리표에 없는 조합은 "불가"로 함께 내려 준다. 격자에서 빈칸으로
# 두면 왜 없는지 알 수 없고, 아예 빼면 축마다 열이 어긋난다.
_ALL_KEYS = ("kp", "ki", "k_rate")
_NO_RATE = "이 축은 rate 입력이 없어 k_rate 경로 자체가 생기지 않는다"

_SCAS_DEF = {p.name: p for p in ScasAxis.PARAM_DEFS}
_AP_DEF = {p.name: p for p in Autopilot.PARAM_DEFS}


def _meta(group: str, key: str) -> dict:
    """자리의 단위·설명·설계 파라미터 이름 — AP 축은 이름이 다르다(alt.k_rate=k_hdot)."""
    field = AP_GAIN_FIELD.get((group, key))
    if field is None:
        d = _SCAS_DEF[key]
        return {"unit": d.unit, "desc": d.desc, "param": key}
    d = _AP_DEF[field]
    return {"unit": d.unit, "desc": d.desc, "param": field}


@router.get("/gains/demo")
def demo_gain_tables() -> dict:
    """데모 기체 설계 게인 테이블 — "그룹.게인" 이름 → 테이블 JSON."""
    return {name: table_dict(t) for name, t in make_demo_gain_tables().items()}


@router.get("/gains/catalog")
def gain_slot_catalog() -> dict:
    """스케줄 **자리** 목록 — 켤 수 있는 곳, 지금 켜진 곳, 끄면 굳는 값.

    켜져 있지 않은 자리에도 제안 테이블(설계 상수 × 같은 동압 스케일)을 함께 준다.
    체크하는 순간 곡선이 뜨고, 설계점에서는 원래 상수와 같은 값에서 출발한다.
    """
    design = demo_design_gains()
    tables = {name: table_dict(t) for name, t in make_demo_gain_tables(design).items()}
    slots = []
    for group in SCHEDULABLE:
        for key in _ALL_KEYS:
            name = f"{group}.{key}"
            if key not in SCHEDULABLE[group]:
                slots.append({
                    "name": name, "group": group, "key": key,
                    "available": False, "reason": _NO_RATE,
                })
                continue
            slots.append({
                "name": name, "group": group, "key": key, "available": True,
                "scheduled": name in DEFAULT_SCHEDULED,
                "design": design[name], "table": tables[name], **_meta(group, key),
            })
    # 축·필터 시정수는 엔진 조립에서 읽는다 — 여기에 0.5를 또 적으면 데모 형상이
    # 바뀌었을 때 웹만 옛 값을 보여 준다 (init(dt) 없이 파라미터만 보유한 상태)
    return {
        "axis": next(iter(tables[DEFAULT_SCHEDULED[0]]["axes"])),
        "filter_tau": make_demo_fcl().schedule.filter_tau,
        "default": list(DEFAULT_SCHEDULED),
        "slots": slots,
    }
