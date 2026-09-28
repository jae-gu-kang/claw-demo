"""영향성 지표 `launch_gx`의 이름·설명이 재는 것과 같은가, 그리고 실효 게인 조회의 공개 이름.

`launch_gx`는 레일 축 **순가속도**(중력 성분 제외 — plant/ground.py LaunchRail.launch_gx)다. 예전 이름 「사출 하중」은
하중배수로 읽혔고, 설명은 「판정 기준은 아직 없다 [TBD]」였다 — 웹 시뮬 탭 착륙 요약은 이미 n_x = gx + sin γ를
structural.n_x_launch와 견준다(lib/replay.js launchLoad). 앙각이 위면 n_x가 이 값보다 커서, 이 값을 한계와 바로 견주면
낙관한다 — 이름이 그 오독을 부르지 않아야 한다.
"""

from claw.common.contracts import TrimCase
from claw.fcl.assemble import assemble_law
from claw.pipeline import openloop
from claw.pipeline.influence import METRICS
from claw.profile import example_profile


def _metric(key):
    return next(m for m in METRICS if m.key == key)


def test_레일_가속_지표는_하중이라_부르지_않고_판정_자리를_말한다():
    m = _metric("launch_gx")
    assert m.label == "레일 가속"
    assert "하중" not in m.label
    assert "[TBD]" not in m.desc and "아직 없다" not in m.desc
    for word in ("중력 성분", "하중배수가 아니다", "sin 앙각", "structural.n_x_launch", "착륙 요약"):
        assert word in m.desc, word
    # 신호·단위·방향은 그대로다 — 이름만 정직해진다
    assert (m.unit, m.signals, m.better) == ("g", ("launch_gx", "on_rail"), "lower")


def test_실효_게인_조회는_공개_이름으로도_같은_함수다():
    """서버 분석 라우트가 밑줄 이름을 import하던 자리 — 공개 이름으로 옮길 수 있게 둘이 같은 객체여야 한다."""
    assert openloop.effective_gain is openloop._effective_gain
    fcl = assemble_law(example_profile())
    case = TrimCase("c", mach=0.45, alt=1000.0, fuel=200.0)
    for group, key in (("pitch", "kp"), ("roll", "k_rate"), ("speed", "kp"), ("alt", "k_rate")):
        assert openloop.effective_gain(fcl, group, key, case) == openloop._effective_gain(fcl, group, key, case)
