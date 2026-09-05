"""pipeline.evaluate 검증 — A/B/C 채점의 계약.

실행 비용이 케이스×런이므로 6DOF는 초소형 설정(t_settle 1 s·t_step 2 s) 한 벌을
모듈 픽스처로 공유한다 — 이 설정에서 추종 판정은 당연히 나쁘게 나온다(스텝이
정착할 시간이 없다). 그래서 테스트는 **수치가 아니라 구조·규약**을 핀한다:
카드 7·체크 9의 완결성, 원자료(11항목) 보존, J v2의 None 전파(0 위장 금지),
케이스 0건의 판정 보류, depth 게이트의 사유, verify의 코너·중간점.
"""

import dataclasses
import json
import math

import pytest

from claw.common.contracts import TrimCase
from claw.pipeline.criteria import GainEvalCriteria
from claw.pipeline.evaluate import (
    CARD_META,
    CARDS,
    CHECK_META,
    CHECKS,
    HARD_CHECKS,
    ITEMS,
    STAGE_ORDER,
    combined_probe,
    evaluate,
    verify,
)
from claw.pipeline.influence import Shape
from claw.plant.demo import make_demo_aircraft
from claw.trim import trim_batch

_CASE = TrimCase(name="M0.5/h1000", mach=0.5, alt=1000.0, fuel=200.0)


@pytest.fixture(scope="module")
def rig():
    ac = make_demo_aircraft()
    trs = trim_batch(ac, [_CASE])
    assert trs[0].converged
    return ac, trs


@pytest.fixture(scope="module")
def report(rig):
    ac, trs = rig
    return evaluate(ac, trs, Shape(), GainEvalCriteria(),
                    t_settle=1.0, t_step=2.0)


def test_카드는_7장_체크는_9건이고_어휘가_완결이다():
    assert len(CARDS) == 7 and set(CARDS) == set(CARD_META)
    assert len(CHECKS) == 9 and set(CHECKS) == set(CHECK_META)
    assert set(STAGE_ORDER) == set(ITEMS)  # 원자료 11항목은 그대로 산다


def test_카드와_체크가_전부_상태를_낸다(report):
    assert [c["key"] for c in report["cards"]] == list(CARDS)
    for c in report["cards"]:
        assert c["status"] in ("ok", "warn", "fail", "na")
    ch = report["checks"]
    assert [c["key"] for c in ch["list"]] == list(CHECKS)
    # na는 PASS 분모에서 빠지되 반드시 병기된다 — 카운트 합 = 9
    assert ch["n_pass"] + ch["n_warn"] + ch["n_fail"] + ch["n_na"] == len(CHECKS)
    assert ch["n_judged"] == ch["n_pass"] + ch["n_warn"] + ch["n_fail"]


def test_원자료_11항목이_케이스마다_보존된다(report):
    c = report["cases"][0]
    assert set(c["stages"]) == set(STAGE_ORDER)
    for k in STAGE_ORDER:
        assert c["stages"][k]["status"] in ("ok", "warn", "fail", "na")


def test_하드_실패면_J는_None이고_사유가_있다(report):
    c = report["cases"][0]
    if c["hard_fails"]:
        assert c["J"] is None
        assert c["J_reason"]
    for f in c["hard_fails"]:
        assert f["check"] in HARD_CHECKS


def test_직렬화에_nan이_새지_않는다(report):
    from claw_server.serialize import to_jsonable
    json.dumps(to_jsonable(report), allow_nan=False)


def test_카드는_원자료의_집계다(report):
    """카드 ②GM의 값은 어떤 케이스 어떤 루프의 실측 마진과 정확히 같아야 한다 —
    집계가 재계산이 되는 순간 카드와 상세가 다른 수를 말한다."""
    gm_card = next(c for c in report["cards"] if c["key"] == "gm")
    if gm_card["value"] is None:
        return
    loops = report["cases"][0]["stages"]["margins"]["loops"]
    lp = loops[gm_card["value"]["loop"]]
    assert lp["margins"]["gm_db"] == gm_card["value"]["gm_db"]


def test_지연_여유는_PM의_보조라_판정을_따로_만들지_않는다(report):
    dm = next(c for c in report["checks"]["list"] if c["key"] == "delay_margin")
    pm = next(c for c in report["cards"] if c["key"] == "pm")
    if dm["value"] is not None:
        assert dm["status"] == pm["status"]
        assert "PM과 한 몸" in dm["note"]


def test_depth_linear는_시뮬_항목을_사유와_함께_비운다(rig):
    ac, trs = rig
    out = evaluate(ac, trs, Shape(), GainEvalCriteria(), depth="linear")
    st = out["cases"][0]["stages"]
    for k in ("tracking", "envelope", "actuator", "coupling", "recovery"):
        assert st[k]["status"] == "na"
        assert "linear" in st[k]["note"]  # "안 잰 것"과 "잴 수 없는 것"은 다른 문장
    # 선형 항목은 살아 있다 — 단계 1의 정의
    assert st["margins"]["status"] != "na"
    assert out["cases"][0]["J"] is None
    assert out["depth"] == "linear"


def test_모르는_depth는_거부():
    with pytest.raises(ValueError, match="depth"):
        evaluate(None, [], Shape(), GainEvalCriteria(), depth="quick")


def test_미수렴_케이스만_있으면_판정을_보류한다(rig):
    ac, trs = rig
    fake = dataclasses.replace(trs[0], converged=False)
    out = evaluate(ac, [fake], Shape(), GainEvalCriteria(),
                   t_settle=1.0, t_step=2.0)
    assert out["cases"] == []
    # False로 두면 "케이스 0건 = 합격"으로 읽힌다 — 통과도 실패도 아닌 None
    assert out["aggregate"]["hard_fail"] is None
    assert all(c["status"] == "na" for c in out["cards"])
    assert out["checks"]["n_judged"] == 0
    assert any("미수렴" in w for w in out["warnings"])


def test_동시명령_기동은_두_축이_한_모드에_같이_걸린다(rig):
    _ac, trs = rig
    modes, t_end = combined_probe(trs[0], dh=100.0, dpsi=0.5,
                                  t_settle=1.0, t_hold=2.0)
    comb = modes[1]
    assert comb.alt == trs[0].case.alt + 100.0
    assert comb.heading == 0.5  # 순차가 아니라 동시 — 교차축 체크의 정의
    assert t_end == 3.0


def test_마진은_레이트_폐쇄_조성으로_판정된다(report):
    """평탄 SISO 근사로 절대 판정을 하면 설계점조차 PM 12°가 나온다(closure 머리말).

    조성이 조용히 되돌아가면 카드 전체가 그 거짓 fail로 덮인다 — 설계점 피치 자세
    마진이 합격선(45°)을 넘는 것으로 조성 선택을 핀한다.
    """
    lp = report["cases"][0]["stages"]["margins"]["loops"]["pitch_att"]
    assert lp["status"] in ("ok", "warn")
    assert lp["margins"]["pm_deg"] > 45.0


def test_잔여_권한이_실측되고_하드_문턱과_비교된다(report):
    """커밋 0e56bcf의 배분 신호가 계측 사슬을 타고 카드 ⑦까지 온다."""
    inflight = report["cases"][0]["stages"]["authority"]["inflight"]
    assert inflight["status"] in ("ok", "fail")  # 데모 형상은 배분 장착 — na가 아니다
    card = next(c for c in report["cards"] if c["key"] == "control_authority")
    assert card["value"]["remaining_worst"]["value"] == inflight["worst"]["value"]


def test_verify는_코너마다_재트림하고_중간점을_따로_잰다(rig):
    """C급 — 강건성 축이 전부 0이면 코너가 없고(흔드는 시늉 금지), 중간점만 돈다."""
    _ac, _trs = rig
    crit = GainEvalCriteria.from_dict({
        "robustness": {"mass_frac": 0.0, "cmalpha_frac": 0.0, "cmq_frac": 0.0}})
    mid = TrimCase(name="mid/M0.525_h1000_f200", mach=0.525, alt=1000.0, fuel=200.0)
    out = verify(make_demo_aircraft, [_CASE], Shape(), crit,
                 depth="linear", midpoint_cases=[mid])
    assert out["verify"]["mass_cg"]["corners"] == []
    assert out["verify"]["mass_cg"]["status"] == "na"
    gm = out["verify"]["grid_midpoints"]
    assert gm["n_cases"] == 1
    assert gm["cases"][0]["case"] == mid.name
    assert gm["hard_fail"] in (True, False)


def test_verify_코너는_섭동_기체로_돈다(rig):
    _ac, _trs = rig
    crit = GainEvalCriteria.from_dict({
        "robustness": {"mass_frac": 0.2, "cmalpha_frac": 0.0, "cmq_frac": 0.0}})
    out = verify(make_demo_aircraft, [_CASE], Shape(), crit, depth="linear")
    labels = [c["label"] for c in out["verify"]["mass_cg"]["corners"]]
    assert labels == ["mass+20%", "mass-20%"]
    for c in out["verify"]["mass_cg"]["corners"]:
        assert c["hard_fail"] in (True, False, None)
    # CG는 [TBD]가 문장으로 남는다 — 흔드는 시늉을 하지 않는다
    assert "[TBD]" in out["verify"]["mass_cg"]["note"]


def test_J_v2_산술은_가중치_교환_변이를_잡는다():
    """J = w_ζJ_ζ + w_BW J_BW + w_RMS J_RMS + w_Mp J_Mp + w_δ J_δ — 합성 입력으로
    기대값을 손으로 접어 핀한다(리뷰 지적: 사장 산술은 변이가 통과한다).
    가중치 둘을 맞바꾸거나 제곱 자리를 틀리면 이 수가 달라진다."""
    from claw.pipeline.evaluate import _j_for

    crit = GainEvalCriteria()
    damping = {
        "zeta_sp": {"value": 0.35, "judged": "warn"},   # 부족 0.5 → 0.25
        "zeta_dr": {"value": 0.45, "judged": "warn"},   # 부족 0.1 → 0.01
        "roll_lambda": {"value": 6.0, "unstable": False},  # 부족 0.5 → 0.25
    }
    metrics = {
        "alt_rms": 5.0, "spd_rms": 1.0, "hdg_rms": 0.05,  # (0.5²+0.5²+0.5²)=0.75
        "alt_mp": 0.10, "spd_mp": 0.20, "hdg_mp": 0.05,   # max 0.2 → 0.04
    }
    act = {"channels": {
        "elevon_l": {"pos": {"rms_frac": 0.2}, "rate": {"rms_frac": 0.1}},
        "elevon_r": {"pos": {"rms_frac": 0.4}, "rate": {"rms_frac": 0.3}},
    }}
    j, terms, reason = _j_for(metrics, act, damping, crit)
    assert reason is None
    assert abs(terms["zeta"] - 0.25) < 1e-12  # max(0.25, 0.01) — 최악 축
    assert abs(terms["bw"] - 0.25) < 1e-12
    assert abs(terms["rms"] - 0.75) < 1e-12
    assert abs(terms["mp"] - 0.04) < 1e-12
    # delta = mean(mean(0.04, 0.16), mean(0.01, 0.09)) = mean(0.10, 0.05) = 0.075
    assert abs(terms["delta"] - 0.075) < 1e-12
    w = crit.weights
    expect = (w.w_zeta * 0.25 + w.w_bw * 0.25 + w.w_rms * 0.75
              + w.w_mp * 0.04 + w.w_delta * 0.075)
    assert abs(j - expect) < 1e-12


def test_J_v2_발산근_대역폭은_inf고_스텝_없는_축은_항_불성립():
    from claw.pipeline.evaluate import _j_for

    crit = GainEvalCriteria()
    damping = {"zeta_sp": {"value": 0.7}, "zeta_dr": {"value": 0.5},
               "roll_lambda": {"value": 12.0, "unstable": True}}
    metrics = {"alt_rms": 1.0, "spd_rms": 0.1, "hdg_rms": 0.01,
               "alt_mp": None, "spd_mp": 0.0, "hdg_mp": 0.0}
    act = {"channels": {"elevon_l": {"pos": {"rms_frac": 0.1}, "rate": {}}}}
    j, terms, reason = _j_for(metrics, act, damping, crit)
    assert terms["bw"] == math.inf  # 발산근의 |Re|를 달성으로 위장하지 않는다
    assert terms["mp"] is None and j is None
    assert "스텝" in reason
