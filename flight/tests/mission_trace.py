"""대조용 미션 기록 — 껍데기. 정본은 `claw.verify.trace.record_mission`이다.

검증 탭(서버 /verify/flight → claw.verify.autocode)이 같은 대조 미션을 쓰게 되면서
미션 정의가 엔진으로 이관됐다 — 두 곳에 적히면 "테스트가 검증한 것"과 "화면이
검증한 것"이 조용히 갈라진다 (02 §5.5). 여기 남은 것은 test_parity가 쓰는 형태
(입력 dict 목록, OUTPUT_ORDER 튜플 목록, 웜스타트)로 바꾸는 어댑터뿐이다.
"""

from claw.fcl import make_demo_fcl
from claw.verify.trace import INPUT_ORDER, record_mission  # noqa: F401 — 재수출

# 데모 형상 fcl 그래프의 출력 선언 순서 — 하네스 출력 열과 1:1
OUTPUT_ORDER = (
    "elevon_l", "elevon_r", "rudder", "throttle_l", "throttle_r",
    "limiter_active", "alpha_margin",
)


def run(t_end=180.0):
    """→ (입력 dict 목록, 기준 출력 튜플 목록, 트림 웜스타트 (de0, th0, thr0))."""
    rec = record_mission(make_demo_fcl(), t_end=t_end)
    assert rec["meta"]["aborted"] is None, rec["meta"]["aborted"]
    # 여기 적은 순서가 낡으면 하네스 열이 어긋난 채 대조된다 — 그래프가 정본
    assert rec["output_order"] == OUTPUT_ORDER, rec["output_order"]
    refs = [tuple(row[k] for k in OUTPUT_ORDER) for row in rec["outputs"]]
    return rec["inputs"], refs, rec["warm"]
