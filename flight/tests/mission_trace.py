"""대조용 미션 기록 — 껍데기. 정본은 `claw.verify.trace.record_mission`이다.

검증 탭(서버 /verify/flight → claw.verify.autocode)이 같은 대조 미션을 쓰게 되면서
미션 정의가 엔진으로 이관됐다 — 두 곳에 적히면 "테스트가 검증한 것"과 "화면이
검증한 것"이 조용히 갈라진다 (02 §5.5). 여기 남은 것은 test_parity가 쓰는 형태
(입력 dict 목록, OUTPUT_ORDER 튜플 목록, 웜스타트)로 바꾸는 어댑터뿐이다.
"""

from claw.fcl import make_demo_fcl
from claw.profile import example_profile
from claw.verify import vectors
from claw.verify.trace import INPUT_ORDER, record_mission  # noqa: F401 — 재수출

# 데모 형상 fcl 그래프의 출력 선언 순서 — 하네스 출력 열과 1:1
OUTPUT_ORDER = (
    "elevon_l", "elevon_r", "rudder", "throttle_l", "throttle_r",
    "limiter_active", "alpha_margin",
)


def run(t_end=180.0):
    """→ (입력 dict 목록, 기준 출력 튜플 목록, 트림 웜스타트 (de0, th0, thr0), 미션 스텝 수).

    미션 뒤에 **검증 탭과 같은 통합 보강 벡터**(verify/vectors.py, verify/autocode.py verify_flight와 같은 순서·같은
    러너)를 잇는다(v1.11). 미션만으로는 롤 동적 배분 한계에 걸리는 경로가 기체 동역학에 매여 있었다 — 제품 예제는
    18,000스텝 중 2스텝만 걸렸고, 적분기 판정 보강으로 롤이 한계의 94%에서 멈추자 0이 됐다. 벡터의 SCAS 포화 왕복은
    한계를 확실히 친다. 그래서 C 대조가 그 구간까지 넓어지고 "테스트가 대조한 것"과 "검증 탭이 대조한 것"이 같아진다.

    미션 스텝 수를 함께 돌려주는 이유: 벡터가 모드 토글·항법 무효·마하 스윕·포화를 전부 확실히 밟으므로 전체 입력으로
    경로를 단정하면 **미션이 그 경로를 잃어도** 아무것도 안 깨진다. 미션 내용 단정은 앞 구간에서 한다(test_parity).
    """
    law = make_demo_fcl()
    rec = record_mission(law, profile=example_profile(), t_end=t_end)
    assert rec["meta"]["aborted"] is None, rec["meta"]["aborted"]
    mission_steps = len(rec["inputs"])
    ap_cfg = getattr(getattr(law, "autopilot", None), "cfg", None)
    theta_hi = getattr(law, "theta_hi_table", None) is not None
    for case in vectors.integration_cases(ap_cfg, law.runner.dt, theta_hi=theta_hi):
        for row in case["rows"]:
            out = law.runner.step_all(**row)
            rec["inputs"].append(row)
            rec["outputs"].append({k: float(v) for k, v in out.items()})
    # 여기 적은 순서가 낡으면 하네스 열이 어긋난 채 대조된다 — 그래프가 정본
    assert rec["output_order"] == OUTPUT_ORDER, rec["output_order"]
    refs = [tuple(row[k] for k in OUTPUT_ORDER) for row in rec["outputs"]]
    return rec["inputs"], refs, rec["warm"], mission_steps
