"""제품 예제(200 kg급 델타윙 · EO/IR형 220 kg) — 패키지에 실린 **그 문서**를 검사한다 (02 §5.6.1).

엔진·서버 테스트는 conftest가 예제 자리에 구 합성 기체(1200 kg 회귀 픽스처)를 두므로, 여기서는
`load_shipped_example()`로 제품(서버·웹·flight/generate.py)이 실제로 쓰는 문서를 읽는다. 웹 매뉴얼·블록도가
인용하는 해면 수평비행 범위와 설계 천장은 이 파일의 표가 정본이다(web/js/lib/blocks.test.js가 원문으로 대조한다).
"""

import json
import math
from pathlib import Path

import pytest

from claw.common.contracts import TrimCase
from claw.design.basis import apply_seed_basis
from claw.design.points import envelope_ok
from claw.opspace.verdict import VerdictContext, condition_verdict
from claw.design.tune import TuneTargets
from claw.env import isa_atmosphere
from claw.pipeline.criteria import GainEvalCriteria
from claw.pipeline.evaluate import evaluate
from claw.pipeline.influence import Shape
from claw.profile import build_profile, effective_document, load_shipped_example, validate_document
from claw.trim.trim import trim_batch, trim_level

LEGACY = Path(__file__).resolve().parent / "fixtures" / "delta_legacy.json"
R = 200.0 / 1200.0  # 무게비 (연료 만재 기준)
THRUST_UP = 1.45  # 추진 상향 배율 — 정지추력·축동력만 상사값의 이 배수(사용자 결정: EO/IR형 만재 3000 m·격자 추력 여유)
S = math.sqrt(R)  # 속도비 — 같은 받음각에서 같은 CL


@pytest.fixture(scope="module")
def doc():
    return load_shipped_example()


@pytest.fixture(scope="module")
def ac(doc):
    return build_profile(doc, validated=True).aircraft()


@pytest.fixture(scope="module")
def ctx(doc):
    return VerdictContext.from_profile(build_profile(doc, validated=True))


def test_만재_200_kg_EO_IR형은_220_kg이고_계산이_달라지는_변형이다(doc):
    m = doc["mass"]
    assert (m["m_empty"], m["fuel_max"]) == (150.0, 50.0)
    eo = effective_document(doc, "eoir")
    assert eo["mass"]["m_empty"] + eo["mass"]["fuel_max"] == 220.0
    assert eo["display"]["model"] == "shahed136_eoir.glb"
    # 짐벌 20 kg가 질량·관성에 실린다 — 표시 모델만 바꾼 변형이 아니므로 플랜트 지문이 갈린다
    assert build_profile(doc, validated=True).plant_fingerprint != build_profile(doc, "eoir", validated=True).plant_fingerprint


def test_구_합성_기체를_무게비_상사로_줄였다(doc):
    """공력·형상·실속은 그대로(같은 받음각·마하 비에서 회전 동역학이 같다), 질량·관성·추진·지상장치는 무게비,
    속도류는 √무게비다. 법칙 설계 게인(SCAS·자동조종)은 상사가 아니다 — 2026-09 재튜닝에서 툴이 이 기체로 다시 도출했다
    (아래 test_법칙_설계는_툴_산출_근거_직행의_출력_그대로다)."""
    old = validate_document(json.loads(LEGACY.read_text(encoding="utf-8")))
    for sec in ("geometry", "aero", "stall", "surfaces", "trim", "actuator"):
        assert doc[sec] == old[sec], sec
    flat = lambda J: [v for row in J for v in row]  # noqa: E731 — approx는 중첩 목록을 못 받는다
    assert flat(doc["mass"]["J_full"]) == pytest.approx([v * R for v in flat(old["mass"]["J_full"])], abs=0.006)
    p, q = doc["propulsion"]["params"], old["propulsion"]["params"]
    assert p["static_thrust"] == pytest.approx(q["static_thrust"] * R * THRUST_UP)
    assert p["power_max"] == pytest.approx(q["power_max"] * R * S * THRUST_UP, rel=2e-3)
    assert doc["ground"]["rail"]["exit_speed"] == pytest.approx(old["ground"]["rail"]["exit_speed"] * S, abs=0.05)
    assert doc["ground"]["skid"]["k"] == pytest.approx(old["ground"]["skid"]["k"] * R, abs=0.05)
    assert doc["law"]["schedule"]["m_design"] == pytest.approx(old["law"]["schedule"]["m_design"] * S, abs=5e-5)
    sim, osim = doc["mission_template"]["sim"], old["mission_template"]["sim"]
    # 순항만 상사값(35.9 m/s)이 아니다 — 트림 실속속도의 1.24배로는 장주 선회에서 받음각이 α 리미터 한계에 붙어 고도를
    # 잃었다(흔들린 선회가 겹치면 나선 강하, v1.10 실측). 44 m/s(1.52배)에서 선회 중 최소 α 여유 0.09 rad
    for phase in ("climb", "approach", "flare"):
        assert sim[phase]["speed"] == pytest.approx(osim[phase]["speed"] * S, abs=0.05), phase
    assert sim["cruise"]["speed"] == 44.0


def test_δe_trim_표는_이_플랜트에서_기본과_EO_IR형을_함께_재어_도출했다(doc):
    de = doc["law"]["alloc"]["de_trim"]
    assert de["source"] == "derived"
    assert de["provenance"]["configurations"] == ["base", "eoir"] and de["provenance"]["shortfall"] == 0
    assert not build_profile(doc, validated=True).de_trim_stale
    assert not build_profile(doc, "eoir", validated=True).de_trim_stale


# 해면 자동 설계 채택 대역(v1.65 — 조건 판정의 채택, 트림 탭과 같은 판정). 채택이 여유 미달을 막지 않게 되어 상한이
# 트림이 풀리는 끝(0.001 탐색 격자에서 확인한 끝 — 기체의 절대 최고 속도가 아니다)으로 올라갔다: 기체 성능이 아니라
# 채택 조건이 바뀐 것이다. 이 기체는 해면에서 α 리미터가 트림을 자르는 점이 없어 하한은 그대로다.
# 옛 상한(스로틀 95 % 등고선)은 추진 여유 충족 끝으로 따로 못박는다(SHIPPED_SEA_LEVEL_THRUST_EDGE) — 두 상한 사이가
# 「설계 채택 가능 · 추진 여유 미달」 구간이다.
SHIPPED_SEA_LEVEL_BAND = {  # 연료(kg): (하한, 상한) — 0.001 격자 실측을 안쪽으로 반올림 (v1.65 전 상한은 95 % 끝)
    0.0: (0.08, 0.29),    # 실측 0.075 ~ 0.293 (M0.282 한 점은 트림이 안 풀린다 — 두 끝 판정과 웹 인용에는 무관)
    25.0: (0.09, 0.29),    # 실측 0.081 ~ 0.290  ← 앱 기본값
    50.0: (0.09, 0.28),    # 실측 0.087 ~ 0.286
}
SHIPPED_SEA_LEVEL_THRUST_EDGE = {  # 연료(kg): (추진 여유 충족 끝 — 안쪽 내림, 그 위 여유 미달 구간 안 한 점)
    0.0: (0.28, 0.29),     # 실측 0.287
    25.0: (0.28, 0.29),    # 실측 0.284
    50.0: (0.28, 0.285),   # 실측 0.280 — 채택 상한이 0.286이라 한 칸(0.01) 위는 대역 밖이다
}


def _design_ok(tr, ctx) -> bool:
    """채택 ∧ 여유 충족 — 95 % 등고선 안. 채택(envelope_ok)은 여유 미달을 막지 않는다(v1.65)."""
    v = condition_verdict(tr, ctx)
    return v["adopted"] and v["margin"]["status"] == "met"


@pytest.mark.parametrize("fuel", sorted(SHIPPED_SEA_LEVEL_BAND))
def test_해면_자동_설계_채택_대역이_적어_둔_수치와_같다(ac, ctx, fuel):
    """적어 둔 두 끝은 안에, 한 칸(0.01) 밖은 밖에 — 안쪽만 보면 범위를 넓게 적어도 통과한다."""
    lo, hi = SHIPPED_SEA_LEVEL_BAND[fuel]

    def ok(m):
        return envelope_ok(trim_level(ac, TrimCase(f"m{m}", mach=m, alt=0.0, fuel=fuel)), ctx)
    assert ok(lo) and ok(hi)
    assert not ok(round(lo - 0.01, 2)) and not ok(round(hi + 0.01, 2))


@pytest.mark.parametrize("fuel", sorted(SHIPPED_SEA_LEVEL_THRUST_EDGE))
def test_해면_추진_여유_충족_끝이_적어_둔_수치와_같다(ac, ctx, fuel):
    """끝은 채택 ∧ 여유 충족, 그 위 한 점은 채택 ∧ 여유 미달(「설계 채택 가능 · 추진 여유 미달」)."""
    edge, over = SHIPPED_SEA_LEVEL_THRUST_EDGE[fuel]
    assert edge < over  # over는 채택 대역 실측 상한 안 — 0.001 실측이라 안쪽 반올림한 표 상한보다 클 수 있다
    assert _design_ok(trim_level(ac, TrimCase(f"t{edge}", mach=edge, alt=0.0, fuel=fuel)), ctx)
    v = condition_verdict(trim_level(ac, TrimCase(f"t{over}", mach=over, alt=0.0, fuel=fuel)), ctx)
    assert v["adopted"] and v["margin"] == {"status": "short", "reasons": ["throttle_high"]}, (fuel, v["margin"])


# 설계 천장은 스로틀 95 % 등고선(여유 충족) 기준이다 — v1.65부터 채택이 여유를 보지 않으므로 "난다"를 채택 ∧ 여유
# 충족(_design_ok)으로 잰다. 채택만으로 재면 트림이 풀리는 끝까지 올라간다(이분법 실측: 공허 ~8.89 · 25 kg ~7.58 ·
# 만재 ~6.40 km) — 인용문이 말하는 천장은 이것이 아니다.
SHIPPED_CEILING = {  # 연료(kg): (인용값, 여기서는 난다, 여기서는 못 난다) [m] — 스로틀 95% 등고선 기준
    0.0: (8600.0, 8500.0, 8700.0),     # 실측 8,596 m는 나고 8,602 m는 못 난다
    25.0: (7300.0, 7200.0, 7400.0),     # 실측 7,277 m는 나고 7,283 m는 못 난다  ← 앱 기본값
    50.0: (6100.0, 6000.0, 6200.0),     # 실측 6,094 m는 나고 6,100 m는 못 난다
}


@pytest.mark.parametrize("fuel", sorted(SHIPPED_CEILING))
def test_설계_천장이_적어_둔_수치_근방이다(ac, ctx, fuel):
    cited, below, above = SHIPPED_CEILING[fuel]
    assert below < cited < above

    def flies(alt):
        m = 0.06
        while m <= 0.30001:
            if _design_ok(trim_level(ac, TrimCase(f"c{m:.3f}", mach=m, alt=alt, fuel=fuel)), ctx):
                return True
            m = round(m + 0.005, 4)
        return False
    assert flies(below), f"연료 {fuel:.0f} kg: {below:.0f} m에서 난다고 적어 뒀는데 못 난다"
    assert not flies(above), f"연료 {fuel:.0f} kg: {above:.0f} m는 천장 위여야 하는데 난다"


def _evaluate_cases(bp, cases):
    ac = bp.aircraft()
    trs = trim_batch(ac, [TrimCase(name=f"M{m}_h{int(h)}", mach=m, alt=h, fuel=f) for m, h, f in cases])
    return evaluate(ac, trs, Shape(profile=bp), GainEvalCriteria(), depth="linear")["cases"]


def _spiral_t2(bp, cases):
    return [min((u["t2_s"] for u in c["stages"]["stability"]["unstable"]), default=math.inf)
            for c in _evaluate_cases(bp, cases)]


def test_기본_해석_격자_하한은_나선_배가_시간_20_s_위다(doc):
    """구 기체 격자 하한 M0.30을 상사로 줄이면 M0.12지만, 느린 기체는 경로 시간 규모가 짧아 나선 발산도 빠르다 — M0.12·3000 m의
    배가 시간이 14 s로 판정선(20 s, MIL-8785 Level 1)에 못 미친다. 그래서 기본 격자는 M0.14부터다(EO/IR형 포함 전 고도 20 s 위)."""
    grid = doc["mission_template"]["trim_grid"]
    assert grid["mach"]["from"] == 0.14 and grid["fuel"] == [25.0]
    for variant in (None, "eoir"):
        bp = build_profile(doc, variant, validated=True)
        t2 = _spiral_t2(bp, [(0.14, h, 25.0) for h in grid["alt"]])
        assert min(t2) >= 20.0, (variant, t2)
    below = _spiral_t2(build_profile(doc, validated=True), [(0.12, 3000.0, 25.0)])
    assert below[0] < 20.0, below


def test_법칙_설계는_툴_산출_근거_직행의_출력_그대로다(doc):
    """2026-09 재튜닝 — 설계 게인은 손으로 고른 수가 아니라 툴 출력이다(provenance.note에 근거). SCAS는 provenance.case(기본
    격자 최대 동압 모서리), 자동조종은 provenance.autopilot_case(미션 템플릿 접근 속도의 해면 마하)에서 같은 목표(provenance.
    targets — 사람이 정한 덧씀은 targets_override)로 산출 근거 직행을 다시 돌리면 **실린 값이 그대로 나온다**. 사람이 정한
    자동조종 칸(명령필터 tau_*·자세 한계 등)은 툴이 문서 값을 이어 쓰므로 그대로 돌아온다(tau_vs 0.5는 그 사람 몫 — note). 엔진 튜너가
    바뀌어 여기가 깨지면 예제 게인이 더는 툴 출력이 아니라는 뜻이다 — provenance의 두 점·목표로 다시 도출해 게이트·착륙을
    다시 잰다."""
    design = doc["law"]["design"]
    prov = design["provenance"]
    assert prov["source"] == "seed_basis"
    assert prov["targets_override"] == {"zeta_sp": 0.85}
    assert design["autopilot"]["tau_vs"] == 0.5 and prov["autopilot"]["tau_vs"] == "document"
    assert "yaw.k_rate" in doc["law"]["schedule"]["scheduled"]
    grid, sim = doc["mission_template"]["trim_grid"], doc["mission_template"]["sim"]
    # 점 선택 규칙 — 격자 최대 동압 모서리(마하 끝·최저 고도·연료 절반) · 접근 속도의 해면 마하
    assert (prov["case"]["mach"], prov["case"]["alt"], prov["case"]["fuel"]) == (
        grid["mach"]["to"], min(grid["alt"]), doc["mass"]["fuel_max"] * 0.5)
    assert prov["autopilot_case"]["mach"] == round(sim["approach"]["speed"] / isa_atmosphere(0.0).a, 4)
    assert prov["autopilot_case"]["alt"] == 0.0
    targets = TuneTargets.from_dict(prov["targets"])
    bp = build_profile(doc, validated=True)
    c, a = prov["case"], prov["autopilot_case"]
    scas = apply_seed_basis(bp, c["mach"], c["alt"], c["fuel"], targets=targets)
    ap = apply_seed_basis(bp, a["mach"], a["alt"], a["fuel"], targets=targets)
    assert scas["ok"] and ap["ok"]
    for g in ("pitch", "roll", "yaw"):
        for k, v in design["scas"][g].items():
            assert scas["design"]["scas"][g][k] == pytest.approx(v, rel=1e-9, abs=1e-12), (g, k)
    for k, v in design["autopilot"].items():
        assert ap["design"]["autopilot"][k] == pytest.approx(v, rel=1e-9, abs=1e-12), k


def test_기본_격자_게인_평가_게이트에_hard_fail이_없다(doc):
    """게인 탭 [지표 재계산 (선형)]과 같은 판정 — 기본 격자(trim_grid 15칸) × 기본형·EO/IR형. 레이트 루프 GM/PM을 작동기·지연을
    넣어 재는 게이트(2026-09)에서 구 상사 게인은 피치 레이트 발산·롤 레이트 여유 미달로 hard fail 66이었다. 카드 ②GM·④λ의 warn은
    마하 1축 스케줄의 몫이다(provenance.note) — 해면 롤 GM 8 dB와 3000 m 롤 λ 12를 한 게인으로 함께 얻지 못한다."""
    grid = doc["mission_template"]["trim_grid"]
    m0, m1, dm = grid["mach"]["from"], grid["mach"]["to"], grid["mach"]["step"]
    machs = [round(m0 + i * dm, 4) for i in range(int(round((m1 - m0) / dm)) + 1)]
    cases = [(m, h, f) for m in machs for h in grid["alt"] for f in grid["fuel"]]
    for variant in (None, "eoir"):
        bp = build_profile(doc, variant, validated=True)
        ac = bp.aircraft()
        trs = trim_batch(ac, [TrimCase(name=f"M{m}_h{int(h)}_f{int(f)}", mach=m, alt=h, fuel=f) for m, h, f in cases])
        assert all(tr.converged for tr in trs), variant
        res = evaluate(ac, trs, Shape(profile=bp), GainEvalCriteria(), depth="linear")
        assert res["aggregate"]["hard_fail"] is False, (variant, res["aggregate"]["hard_fails"][:3])
        cards = {c["key"]: c for c in res["cards"]}
        assert {k: cards[k]["status"] for k in ("mode_stability", "gm", "pm", "response_speed")} == {
            "mode_stability": "ok", "gm": "warn", "pm": "ok", "response_speed": "warn"}, variant
        assert cards["gm"]["value"]["loop"] == "roll_rate" and cards["gm"]["value"]["gm_db"] > 6.0, variant


def test_EO_IR형은_3000_m_만재에서도_수평비행점이_있다(doc):
    """추력·동력 상향(사용자 결정)의 기준 하나 — 짐벌 20 kg를 싣고 연료를 가득 채워도 3000 m에서 수평비행점이 있다.
    상사 축소 그대로(정지추력 1 kN · 축동력 34 kW)였을 때는 한 점도 없었다."""
    built = build_profile(doc, "eoir", validated=True)
    ac, ctx = built.aircraft(), VerdictContext.from_profile(built)
    ok = [m / 1000 for m in range(100, 300, 5)
          if envelope_ok(trim_level(ac, TrimCase(f"e{m}", mach=m / 1000, alt=3000.0, fuel=50.0)), ctx)]
    assert ok, "EO/IR형 3000 m 만재 수평비행점이 없다"


def test_기본_격자_3000_m_줄은_추력_여유_판정을_통과한다(doc):
    """추진 상향의 다른 기준 — 표준 기동(속도 +3 m/s·고도 +30 m) 직후 스로틀이 1에 붙는 순간 킥이었다(상사값 그대로일 때 3000 m 트림 스로틀 0.72~0.96 — 1.45배에서는 0.47~0.66이고 1에 닿지 않는다).
    배율을 훑는 동안 최악 케이스는 늘 3000 m 줄이었다. 격자 전 칸 통과는 기본형 1.30배, EO/IR형 1.45배부터였다(1.40배는 EO/IR형
    M0.22·3000 m 여유 0.045) — 그래서 THRUST_UP이 1.45다. 전 격자(15칸 × 2형)는 5분 가까이 걸려 최악이 난 줄만 돌린다.
    여유는 자동조종 속도 루프에도 달렸다 — 2026-09 재튜닝에서 휴리스틱을 순항 속도 점에서 잡으면 EO/IR형 M0.22·3000 m 여유가
    0.016이었고, 접근 속도 점(실린 값)에서 0.080이다(provenance.note)."""
    grid = doc["mission_template"]["trim_grid"]
    m0, m1, dm = grid["mach"]["from"], grid["mach"]["to"], grid["mach"]["step"]
    machs = [round(m0 + i * dm, 4) for i in range(int(round((m1 - m0) / dm)) + 1)]
    for variant in (None, "eoir"):
        bp = build_profile(doc, variant, validated=True)
        ac = bp.aircraft()
        trs = trim_batch(ac, [TrimCase(name=f"M{m}_h3000", mach=m, alt=3000.0, fuel=25.0) for m in machs])
        # evaluate는 안 풀린 트림을 조용히 뺀다 — 최악 칸이 빠진 채 "ok"가 나오지 않게 먼저 못박는다
        assert all(tr.converged for tr in trs), (variant, [tr.case.name for tr in trs if not tr.converged])
        checks = evaluate(ac, trs, Shape(profile=bp), GainEvalCriteria(), depth="full")["checks"]["list"]
        thr = next(c for c in checks if c["key"] == "thr_margin")
        assert thr["status"] == "ok", (variant, thr)
