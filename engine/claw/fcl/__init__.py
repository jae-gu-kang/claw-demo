"""M7 fcl — SCAS·오토파일럿·게인 스케줄·엘레본 믹싱·α 리미터 (도메인 문서 §3).

법칙은 NavOutput만 소비한다 — plant 참값 직접 참조 금지 (03 §4 핵심 계약).
구성: airdata(NavOutput→V·α·β), SCAS, 오토파일럿(+명령필터·선회 FF),
게인 스케줄(동압 등 테이블+변수 필터), α 리미터, 믹서(엘레본4+차동추력),
FlightControlLaw(최상위 조립: 스케줄→AP→리미터→SCAS→믹서).
데모 프로파일 조립은 claw.fcl.demo.make_demo_fcl.
"""

from claw.fcl.airdata import airdata_from_nav, vel_b_from_nav
from claw.fcl.autopilot import Autopilot, CommandFilter
from claw.fcl.demo import make_demo_fcl
from claw.fcl.law import FlightControlLaw
from claw.fcl.limiter import AlphaLimiter
from claw.fcl.mixer import Mixer
from claw.fcl.scas import Scas, ScasAxis
from claw.fcl.schedule import SCHED_VARS, GainSchedule, max_adjacent_jump
from claw.params.registry import REGISTRY

# 파라미터 보유 법칙 컴포넌트 등록 (02 §2.3) — 웹 블록 파라미터 폼의 스키마 원천.
# α 리미터는 실속 테이블(공력 정본) 의존이라 파라미터 폼 대상 아님 — 미등록.
Autopilot.register(REGISTRY, category="fcl")
ScasAxis.register(REGISTRY, category="fcl")
Mixer.register(REGISTRY, category="fcl")

__all__ = [
    "airdata_from_nav",
    "vel_b_from_nav",
    "Autopilot",
    "CommandFilter",
    "Scas",
    "ScasAxis",
    "GainSchedule",
    "SCHED_VARS",
    "max_adjacent_jump",
    "AlphaLimiter",
    "Mixer",
    "FlightControlLaw",
    "make_demo_fcl",
]
