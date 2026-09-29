"""미션 초안 프롬프트 — 기체 사실·기본 미션 예시가 **고른 기체 문서에서** 오는가 (기체 고정 금지).

종전 프롬프트는 예제 기체(200 kg급)의 실속·레일·순항·선회 반경을 글로 박아 두었다 — 다른 기체를 고르면
LLM이 남의 기체 수치로 초안을 짰다. 여기서 지키는 것:
  ① 기체 절의 수치가 문서를 따라 움직이고, 다른 기체의 수치가 남지 않는다
  ② 레일·지상장치·템플릿·설계 게인이 없는 기체는 그 사실을 말하고 예시를 세우지 않는다
  ③ 예시는 시뮬 탭 기본 미션(web lib/simrequest.js defaultModeRows·defaultWpRows)과 같은 조립이다
  ④ 무대(고흥 활주로) 사실은 정본(data/geo/goheung-runway.json)과 같다
LLM은 부르지 않는다 — 프롬프트 문자열만 본다.
"""

import copy
import json
import math
import re
from pathlib import Path

import pytest

from claw.profile import build_profile, load_example
from claw_server import llm_draft

_REPO = Path(__file__).resolve().parents[3]


def _built(mutate=None, variant=None):
    d = load_example()
    d.update(id="draft-delta", name="초안 시험 기체", is_example=False)
    if mutate:
        mutate(d)
    return build_profile(d, variant)


def test_aircraft_facts_follow_the_document():
    base = _built()
    facts = llm_draft.aircraft_facts(base)
    doc = base.doc
    sim = doc["mission_template"]["sim"]
    assert facts["mass_max"] == doc["mass"]["m_empty"] + doc["mass"]["fuel_max"]
    assert facts["rail"]["exit_speed"] == doc["ground"]["rail"]["exit_speed"]
    assert facts["cruise_speed"] == sim["cruise"]["speed"]
    phi = doc["law"]["design"]["autopilot"]["phi_max"]
    assert facts["phi_max"] == phi
    assert facts["turn_radius"] == pytest.approx(sim["cruise"]["speed"] ** 2 / (9.80665 * math.tan(phi)))
    assert facts["v_s"] > 0.0 and facts["v_s"] < doc["ground"]["rail"]["exit_speed"]

    def other(d):
        d["mass"]["m_empty"] += 111.0
        d["ground"]["rail"]["exit_speed"] = 97.3
        d["mission_template"]["sim"]["cruise"]["speed"] = 91.7
        d["law"]["design"]["autopilot"]["phi_max"] = 0.55

    heavy = llm_draft.aircraft_facts(_built(other))
    assert heavy["v_s"] > facts["v_s"]  # 무거우면 실속속도가 오른다 — 문서에서 잰 값이다
    assert heavy["turn_radius"] == pytest.approx(91.7 ** 2 / (9.80665 * math.tan(0.55)))
    prompt = llm_draft.draft_system(_built(other))
    for v in ("97.3", "91.7", "0.55", f"{heavy['mass_max']:g}"):
        assert v in prompt, v
    # 다른 기체의 수치가 남지 않는다 — 종전 프롬프트의 예제 사실이 글로 박혀 있던 자리
    assert f"이탈속도 {facts['rail']['exit_speed']:g} m/s" not in prompt
    assert f"순항 {facts['cruise_speed']:g} m/s" not in prompt


def test_the_selected_variant_is_what_the_prompt_describes():
    def with_variant(d):
        d["variants"] = [{"id": "heavy-stores", "name": "무거운 변형",
                          "patch": {"/mass/m_empty": d["mass"]["m_empty"] + 200.0}}]

    plain = llm_draft.aircraft_facts(_built(with_variant))
    fat = llm_draft.aircraft_facts(_built(with_variant, "heavy-stores"))
    assert fat["mass_max"] == plain["mass_max"] + 200.0 and fat["v_s"] > plain["v_s"]
    prompt = llm_draft.draft_system(_built(with_variant, "heavy-stores"))
    assert "형상 변형 heavy-stores" in prompt and f"최대 이륙 {fat['mass_max']:g} kg" in prompt


def test_missing_rail_gear_template_and_design_are_said_and_no_example_is_invented():
    def bare(d):
        d["ground"]["rail"] = None
        d["ground"]["skid"] = None
        d["mission_template"] = None
        d["law"]["design"] = None
        d["law"]["alloc"] = None
        d["law"]["schedule"] = None

    b = _built(bare)
    facts = llm_draft.aircraft_facts(b)
    assert facts["rail"] is None and facts["skid"] is False and facts["phi_max"] is None
    assert facts["turn_radius"] is None and facts["cruise_speed"] is None
    example, reason = llm_draft.example_draft(b)
    assert example is None and "레일" in reason
    prompt = llm_draft.draft_system(b)
    assert "발사 레일 없음" in prompt and "지상장치 없음" in prompt and "미션 템플릿 없음" in prompt
    assert "게인 미설계" in prompt
    assert '"modeRows"' not in prompt  # 예시 JSON이 없다 — 남의 기체 예시로 채우지 않는다
    assert reason in prompt


def test_example_is_the_sim_tab_default_mission_built_from_the_template():
    """예시 = 시뮬 탭 기본 미션(lib/simrequest.js)과 같은 조립. 모드 골격은 웹 defaultModeRows, 장주 웨이포인트는
    웹 defaultWpRows의 활주로 축 좌표 — 원문에서 읽어 대조한다(웹이 장주를 고치면 여기가 빨개진다)."""
    b = _built()
    ex, reason = llm_draft.example_draft(b)
    assert reason is None
    sim = b.doc["mission_template"]["sim"]
    js = (_REPO / "web/js/lib/simrequest.js").read_text(encoding="utf-8")

    rows_src = js[js.index("export function defaultModeRows"):js.index("const axisWp")]
    names = re.findall(r'name: "(\w+)"', rows_src)
    assert [r["name"] for r in ex["modeRows"]] == names
    assert [r["exitKind"] for r in ex["modeRows"]] == re.findall(r'exitKind: "(\w+)"', rows_src)
    assert [r["lonAxis"] for r in ex["modeRows"]] == re.findall(r'lonAxis: "(\w+)"', rows_src)
    assert [r["next"] for r in ex["modeRows"]] == re.findall(r'next: "(\w*)"', rows_src)
    by = {r["name"]: r for r in ex["modeRows"]}
    assert (by["climb"]["speed"], by["climb"]["lonValue"], by["climb"]["exitValue"]) == (
        llm_draft.js_num(sim["climb"]["speed"]), llm_draft.js_num(sim["climb"]["pitch"]),
        llm_draft.js_num(sim["climb"]["exit_alt"]))
    assert (by["cruise"]["speed"], by["cruise"]["lonValue"], by["cruise"]["heading"]) == (
        llm_draft.js_num(sim["cruise"]["speed"]), llm_draft.js_num(sim["cruise"]["alt"]), "path")
    assert (by["approach"]["lonValue"], by["flare"]["speed"]) == (
        llm_draft.js_num(sim["approach"]["hdot"]), llm_draft.js_num(sim["flare"]["speed"]))

    cross = float(re.search(r"const PATTERN_CROSS = (\d+);", js).group(1))
    wp_src = js[js.index("export function defaultWpRows"):]
    wp_src = wp_src[:wp_src.index("\n}\n")]
    args = [(float(a), cross if c == "PATTERN_CROSS" else float(c))
            for a, c in re.findall(r"axisWp\((-?\d+), (PATTERN_CROSS|-?\d+)\)", wp_src)]
    assert len(args) == len(ex["wpRows"]) >= 3
    h = llm_draft.RUNWAY_HEADING_RAD

    def js_round(v):
        return math.floor(v + 0.5)

    for (along, c), row in zip(args, ex["wpRows"]):
        assert row == {"n": str(js_round(along * math.cos(h) - c * math.sin(h))),
                       "e": str(js_round(along * math.sin(h) + c * math.cos(h))), "d": ""}

    rc = ex["runConditions"]
    assert rc == {"mach": "0", "alt": "0", "fuel": llm_draft.js_num(sim["fuel"]), "groundOn": True,
                  "launchOn": True, "tEnd": llm_draft.js_num(sim["t_end"]),
                  "accept": llm_draft.js_num(sim["accept_radius"])}
    # 예시는 프롬프트에 그대로 실린다 — 모드 한 줄씩
    prompt = llm_draft.draft_system(b)
    for row in ex["modeRows"]:
        assert json.dumps(row, ensure_ascii=False, separators=(",", ":")) in prompt


def test_example_fits_the_draft_schema():
    from claw_server.routes.llm import _DRAFT_SCHEMA

    ex, _ = llm_draft.example_draft(_built())

    def check(value, schema, path="$"):
        t = schema["type"]
        if t == "object":
            assert isinstance(value, dict), path
            assert set(value) == set(schema["properties"]), path  # required 전부·추가 키 없음
            for k, sub in schema["properties"].items():
                check(value[k], sub, f"{path}.{k}")
        elif t == "array":
            assert isinstance(value, list), path
            for i, v in enumerate(value):
                check(v, schema["items"], f"{path}[{i}]")
        elif t == "string":
            assert isinstance(value, str), path
            if "enum" in schema:
                assert value in schema["enum"], path
        elif t == "boolean":
            assert isinstance(value, bool), path

    check(ex, _DRAFT_SCHEMA)


def test_js_num_formats_like_the_web_string_of_a_number():
    assert [llm_draft.js_num(v) for v in (44.0, 44.9, 0.3665, -1.96, 0.05964, 0, 180.0)] == [
        "44", "44.9", "0.3665", "-1.96", "0.05964", "0", "180"]


def test_site_facts_match_the_measured_runway():
    """활주로 수치의 정본은 data/geo/goheung-runway.json — 프롬프트는 그 사본이라 여기서 대조한다."""
    geo = json.loads((_REPO / "data/geo/goheung-runway.json").read_text(encoding="utf-8"))
    prompt = llm_draft.draft_system(_built())
    assert llm_draft.RUNWAY_HEADING_RAD == geo["heading_rad"]
    for v in (geo["heading_rad"], geo["threshold_south"]["lat_deg"], geo["threshold_south"]["lon_deg"],
              int(geo["length_m"])):
        assert str(v) in prompt, v


def test_prompt_does_not_mutate_the_built_document():
    b = _built()
    before = copy.deepcopy(b.doc)
    llm_draft.draft_system(b)
    assert b.doc == before


def test_도달_반경_규칙은_헤딩_루프_넘김_거리다():
    """규칙 8은 근거 없는 "선회 반경의 1/4" 대신 마지막 웨이포인트 넘김 거리 V²/(g·kp_hdg)다 — 경로 추종(순수추적)이
    마지막 점을 겨눈 채 접근에 넘기고, 접근의 헤딩 루프가 시정수 V/(g·kp_hdg)로 가라앉는 동안 나는 거리. 수치는 고른
    기체의 순항 속도(미션 템플릿)와 설계 헤딩 게인에서 온다(쇼케이스 기체 실측: 100 m에서 중심선 20~24 m 옆, 215 m에서
    1 m 안)."""
    b = _built()
    f = llm_draft.aircraft_facts(b)
    doc = b.doc
    v = doc["mission_template"]["sim"]["cruise"]["speed"]
    kp = doc["law"]["design"]["autopilot"]["kp_hdg"]
    assert f["handover"] == pytest.approx(v ** 2 / (9.80665 * kp))
    prompt = llm_draft.draft_system(b)
    assert "1/4" not in prompt and "영영 끝나지 않는다" not in prompt  # 종전 규칙의 근거 없는 문장
    assert "V²/(g·kp_hdg)" in prompt and f"넘김 거리 약 {f['handover']:.0f} m" in prompt

    def other(d):
        d["mission_template"]["sim"]["cruise"]["speed"] = 61.0
        d["law"]["design"]["autopilot"]["kp_hdg"] = 0.9

    g = llm_draft.aircraft_facts(_built(other))
    assert g["handover"] == pytest.approx(61.0 ** 2 / (9.80665 * 0.9))
    assert f"넘김 거리 약 {g['handover']:.0f} m" in llm_draft.draft_system(_built(other))


def test_템플릿_도달_반경이_넘김_거리와_다르면_그렇게_말한다():
    """예시는 시뮬 탭 기본 미션 그대로라 accept가 템플릿 값이다 — 넘김 거리와 다르면 기체 절과 예시가 그 사실을 말해
    규칙 8과 예시가 서로 다른 말을 하지 않는다. 같으면(허용 비율 안) "= 넘김 거리"다."""
    b = _built()
    f = llm_draft.aircraft_facts(b)

    def matched(d):
        d["mission_template"]["sim"]["accept_radius"] = round(f["handover"], 1)

    def off(d):
        d["mission_template"]["sim"]["accept_radius"] = round(f["handover"] * 0.5, 1)

    same = llm_draft.draft_system(_built(matched))
    assert "(= 넘김 거리)" in same and "와 다르다" not in same and "템플릿 값 그대로다" not in same
    diff = llm_draft.draft_system(_built(off))
    assert f"(넘김 거리 약 {f['handover']:.0f} m와 다르다 — 규칙 8)" in diff
    assert "템플릿 값 그대로다" in diff
    # 템플릿은 문서 작성자가 적은 값이다 — 이 기체로 잰 것처럼 말하지 않는다(사용자 문서에서 거짓이었다)
    assert "맞춰 잰" not in same and "문서 작성자가 적은 값" in same


def test_넘김_거리는_조립이_쓰는_헤딩_게인으로_잰다():
    """헤딩 게인이 스케줄되면(규칙 스케줄 자리에 heading.kp) 순항 마하의 표 값이 실제로 도는 게인이다 — 설계 상수로
    재면 스케줄 상한만큼 틀린다. 적분이 있으면 1차 근사라고 말한다. 게인 미설계면 정할 수 없다고 말한다."""
    from claw.env import isa_atmosphere

    def scheduled(d):
        d["law"]["schedule"]["scheduled"] = sorted(set(d["law"]["schedule"]["scheduled"]) | {"heading.kp"})
        d["law"]["gain_tables"] = None

    b = _built(scheduled)
    sim = b.doc["mission_template"]["sim"]
    mach = sim["cruise"]["speed"] / isa_atmosphere(sim["cruise"]["alt"]).a
    sched = b.doc["law"]["schedule"]
    kp0 = b.doc["law"]["design"]["autopilot"]["kp_hdg"]
    want = kp0 * min((sched["m_design"] / mach) ** 2, b.cap_for("heading.kp"))
    h = llm_draft.heading_gain(b, sim)
    assert h["scheduled"] and h["mach"] == pytest.approx(mach)
    # 표는 마하 격자 사이 선형 보간이라 산식 값과는 격자 간격만큼 다를 수 있다 — 엔진 표 자체와 대조한다
    assert h["kp"] == pytest.approx(b.gain_tables(["heading.kp"])["heading.kp"].interp(mach=mach))
    assert h["kp"] == pytest.approx(want, rel=0.05)
    f = llm_draft.aircraft_facts(b)
    assert f["handover"] == pytest.approx(sim["cruise"]["speed"] ** 2 / (9.80665 * h["kp"]))
    assert f"순항 마하 {mach:.3f}의 스케줄 값" in llm_draft.draft_system(b)

    def integral(d):
        d["law"]["design"]["autopilot"]["ki_hdg"] = 0.05

    assert "1차 근사" in llm_draft.draft_system(_built(integral))
    assert "1차 근사" not in llm_draft.draft_system(_built())

    def bare(d):
        d["law"]["design"] = None
        d["law"]["alloc"] = None
        d["law"]["schedule"] = None
        d["law"]["gain_tables"] = None

    nb = _built(bare)
    assert llm_draft.aircraft_facts(nb)["handover"] is None
    p = llm_draft.draft_system(nb)
    assert "넘김 거리(규칙 8)는 정할 수 없다" in p and "넘김 거리 약" not in p


def test_운용_고도는_요구영역_고도에서_온다():
    """스키마 v3(05 §11.13 이관 11단계) — 문서의 운용 고도 절(operating)이 없어지고 요구영역 고도(operating_region.alt)가
    그 자리다. 요구영역이 없으면 운용 고도 줄을 쓰지 않는다(없는 경계를 지어내지 않는다)."""
    def region(d):
        d["operating_region"] = {
            "mach": [0.3, 0.6], "alt": [400.0, 2600.0], "fuel": [100.0, 300.0], "boundary": None,
            "base_grid": {"n_mach": 3, "alts": [400.0], "fuels": [200.0]}}

    b = _built(region)
    assert llm_draft.aircraft_facts(b)["operating"] == {"alt_min": 400.0, "alt_max": 2600.0}
    assert "운용 고도(요구영역) 400 ~ 2600 m" in llm_draft.draft_system(b)

    def no_region(d):
        d["operating_region"] = None

    n = _built(no_region)
    assert llm_draft.aircraft_facts(n)["operating"] is None
    assert "운용 고도" not in llm_draft.draft_system(n)
