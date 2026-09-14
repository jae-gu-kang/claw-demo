"""제어법칙 조립 정본 — 기체 프로파일 → FlightControlLaw (02 §5.6 · 03 M18).

종전 `fcl/demo.py make_demo_fcl`의 본문이다. 달라진 것은 **값의 출처** 하나다 — 설계 게인·
스케줄·타면 한계·α 마진·할당 표를 모듈 상수가 아니라 기체 프로파일에서 읽는다. 생성기·서버·해석이
전부 이 함수를 지난다 (02 v0.24 「조립 정본은 하나」).

주입 인자(autopilot·scas·mixer·gain_tables·alpha_margin)는 파라미터 스터디용 설계변수이고 None이면
프로파일의 설계값이다. gain_tables 주입은 **전체 교체**다(설계 테이블과 병합하지 않는다 — 일부만
주입하면 나머지 자리는 스케줄 없이 설계점 상수). 설계 게인이 없는 프로파일(`law.design` null)은
주입 없이 조립하면 경로가 붙은 ProfileError가 난다 — 없는 게인을 지어내지 않는다.
"""

from claw.fcl.autopilot import Autopilot
from claw.fcl.law import FlightControlLaw
from claw.fcl.limiter import AlphaLimiter
from claw.fcl.mixer import Mixer
from claw.fcl.scas import Scas, ScasAxis
from claw.fcl.schedule import GainSchedule


def assemble_law(
    profile,
    *,
    with_schedule: bool = True,
    with_limiter: bool = True,
    autopilot: Autopilot | None = None,
    gain_tables: dict | None = None,
    scas: Scas | None = None,
    mixer: Mixer | None = None,
    alpha_margin: float | None = None,
) -> FlightControlLaw:
    """BuiltProfile → FlightControlLaw (init(dt) 전). alpha_margin은 리미터가 있을 때만 뜻이 있다."""
    if gain_tables is not None and not with_schedule:
        raise ValueError("gain_tables 주입은 with_schedule=True에서만 유효")
    if alpha_margin is not None and not with_limiter:
        raise ValueError("alpha_margin 주입은 with_limiter=True에서만 유효")
    scas = scas if scas is not None else Scas(
        *(ScasAxis(**profile.scas_axis_params(axis)) for axis in ("pitch", "roll", "yaw"))
    )
    ap = autopilot if autopilot is not None else Autopilot(**profile.autopilot_params())
    mixer = mixer if mixer is not None else Mixer(**profile.mixer_params())
    law = profile.law
    schedule = (
        GainSchedule(
            gain_tables if gain_tables is not None else profile.gain_tables(),
            filter_tau=law["filter_tau"],
        )
        if with_schedule
        else None
    )
    margin = law["alpha_margin"] if alpha_margin is None else float(alpha_margin)
    limiter = AlphaLimiter(profile.stall_table(), margin=margin) if with_limiter else None
    alloc = {} if profile.alloc_resv_frac is None else {"alloc_resv_frac": profile.alloc_resv_frac}
    return FlightControlLaw(
        scas, ap, mixer, schedule=schedule, alpha_limiter=limiter,
        alloc_trim_table=profile.alloc_trim_table(),
        **alloc,
    )
