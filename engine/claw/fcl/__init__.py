"""M7 fcl — SCAS·오토파일럿·게인 스케줄·엘레본 믹싱·α 리미터 (도메인 문서 §3).

법칙은 NavOutput만 소비한다 — plant 참값 직접 참조 금지 (03 §4 핵심 계약).
구성: airdata(NavOutput→V·α·β), SCAS, 오토파일럿(+명령필터·선회 FF),
게인 스케줄(동압 등 테이블+변수 필터), α 리미터, 믹서(엘레본4+차동추력),
FlightControlLaw(최상위 조립: 스케줄→AP→리미터→SCAS→믹서).
데모 프로파일 조립은 claw.fcl.demo.make_demo_fcl.

**구조의 정본은 `graphs.py`의 IR 선언 하나다** (02 §2.2, M16). 여기 클래스들은
파라미터를 보유하고, 그 그래프를 태우고, 원시 항법 상태를 그래프가 받는 공학량으로
바꿔 주는 **어댑터**다 — 구조를 따로 갖지 않는다. 탑재 C도 같은 그래프에서 나오므로
설계 실행과 탑재 코드가 어긋날 수 없다.

조립된 뒤에는 **상태가 조립의 러너 한 곳에만** 있다. 자식 인스턴스(예: `scas.pitch`)는
파라미터 보유자일 뿐이라 거기에 웜스타트를 넣으면 법칙 실행에 반영되지 않는다 —
`Scas.reset(states={"pitch": …})`처럼 조립에 넣는다.
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
