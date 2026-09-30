"""쇼케이스 기체(`showcase-delta`) — 패키지에 실린 **그 문서**를 검사한다.

200 kg급 EO/IR 정찰 무인기(크롭 델타 무미익·푸셔 프로펠러·공압 레일 발진·스키드 착륙·활주로 복귀)다. 예제와 달리
편집 가능한 저장 기체로 설치되므로(is_example false — 서버 `/profiles/_showcase/install`) 쓰기 기능까지 시연된다.
게인·δe_trim·확정 게인 표는 생성 모듈(claw.profile.showcase)이 툴로 도출해 출처와 함께 실었다 — 여기서는 그 출처가
지금 문서와 맞는지(낡지 않았는지)와 공학 수치의 기본 정합(실속·레일·연료 소모·구조 한계)을 본다. 확정 표는 기본형
설계 결과라 EO/IR형은 규칙 스케줄로 난다(변형 패치가 표를 비운다) — 두 형상 모두 법칙이 조립되는지도 본다.

conftest가 예제 자리를 구 합성 기체로 바꿔 두지만 쇼케이스 로더는 그 환경변수를 보지 않는다(예제 전용).
"""

import copy
import json
import math
from importlib import resources

import numpy as np
import pytest

from claw.common.constants import G0
from claw.common.contracts import TrimCase
from claw.design import DesignSession, design_inputs
from claw.design.points import envelope_ok
from claw.opspace.verdict import VerdictContext
from claw.analysis import broken_loop, nyquist_margins
from claw.design.criteria import MarginCriteria
from claw.design.tune import TuneTargets
from claw.env import isa_atmosphere
from claw.fcl.assemble import assemble_law
from claw.guidance import Guidance, ModeSpec
from claw.params.registry import REGISTRY
from claw.pipeline.openloop import effective_gain
from claw.profile import (
    EXAMPLE_ID, SHOWCASE_ID, build_profile, load_shipped_example, load_showcase, validate_document,
)
from claw.profile.aeroview import MAX_POINTS, aero_slice
from claw.profile.derive import DERIVE_SOURCE
from claw.profile.document import _SHOWCASE_FILE
from claw.profile.errors import ProfileError
from claw.profile.showcase import (
    GAIN_TABLES_PTR, SEED_SOURCES, _config, basis_point, document_text, generate, resolve_design_config, resolve_seed,
    rule_schedule_variants,
)
from claw.sim import Simulator
from claw.trim import linearize, split_axes, trim_batch, trim_ground, trim_level

RAIL_EXIT_MIN_RATIO = 1.15  # 레일 이탈속도 ≥ 이 배수 × 해면 최소 트림 속도(만재) — 이탈 직후 가속·자세 잡기 여유
STALL_TOL = 0.01  # [rad] 실속표 ↔ CL 표 꼭대기 허용 차
STALL_SCAN_STEP = 0.005  # [마하] 실속 일치를 보는 간격 — 공력 DB 마하 범위 전부를 훑는다
BSFC_RANGE = (0.3, 0.5)  # [kg/kWh] 소형 2행정 가솔린 엔진 급
MACH_D_OVER_NO = 1.25  # 설계 다이브 마하 / 최대 운용 마하 하한 (V_D ≥ 1.25 V_C 관례)
LAUNCH_THR_DELAY = 0.5  # [s] 레일 이탈 뒤 이 시간 안에 스로틀이 들어온다(> 0.05)
LAUNCH_SAG_MAX = 0.5  # [m] 이탈 뒤 10 s 안에 고도가 그때까지의 최고보다 이만큼 넘게 내려가지 않는다
LAUNCH_FLY_S = 10.0  # [s] 발진 확인 비행 길이(레일 이탈 뒤 상승 구간)
APPROACH_MIN_RATIO = 1.2  # 접근 속도 ≥ 이 배 × 가장 무거운 형상의 만재 해면 최소 트림 속도
FLARE_MIN_RATIO = 1.15  # 플레어 속도 ≥ 이 배 × 같은 최소 트림 속도
SCHEDULE_BAND = 0.01  # [마하] 확정 게인 표 급변을 보는 띠 폭 (해면 약 3.4 m/s)
SCHEDULE_BAND_RATIO_MAX = 2.5  # 그 띠 안 게인 크기 최대/최소 상한
HANDOVER_TOL = 0.1  # 마지막 웨이포인트 도달 반경 ↔ 헤딩 루프 이월 거리 V²/(g·kp_hdg) 허용 비율
TABLE_ZIGZAG_MAX = 1  # 확정 표 자리마다 방향 반전 상한 — 한 고도 줄의 스케줄은 단조에 가깝다(yaw.k_rate 1회 — 2차 패스 경계)
# 운용 범위 검증 격자의 연료 — × fuel_max (설계 기본 비율 0.1·0.5·1.0 + 미션 연료 40 kg = 0.8)
ENVELOPE_FUEL_FRACS = (0.1, 0.5, 0.8, 1.0)
# [m] 운용 고도 — v2 문서의 operating 절 값(0~3500 m). 스키마 v3에서 절이 폐지됐고(운용 고도 = 요구영역 고도, 이관 11단계)
# 이 기체의 요구영역(200~3000 m)과 다르다. 아래 검증들은 description이 이 범위에서 잰 서술(운용 범위 전부 재판정 실패 0 ·
# 속도 루프 띠)을 붙잡으므로 그 범위를 여기 고정한다 — 요구영역을 넓히면 이 값을 그 고도로 바꾼다
OPERATING_ALTS = (0.0, 3500.0)
ENVELOPE_MIN_JUDGED = 600  # 그 격자에서 판정된 (점, 자리) 수 하한 — 격자가 엔벨로프 밖으로 새면 판정 없이 통과한다
SPD_SCAN_MACH = (0.095, 0.1401, 0.0025)  # 속도 루프 띠를 훑는 마하 (시작, 끝, 간격) — 최소 트림 속도 근처
SPD_BAND_RATIO = 1.05  # 속도 루프 하드 FAIL 띠 — 그 행 최소 트림 마하의 이 배 안 (description과 같은 값)
SPD_BAND_ALT_MIN = {"base": 2000.0, "eoir": 1000.0}  # [m] 그 띠가 나기 시작하는 고도 (description과 같은 값)
LANDING_STOP_MAX_S = 449.8  # [s] 웹 기본 미션 정지 시각 최대(S1 착륙 하네스 실측 449.82 — 기본형 연료 10 kg · 롤 마진 가드 재생성 뒤)
T_END_DWELL_S = (20.0, 30.0)  # [s] 정지 뒤 t_end까지 여유 범위
ROLLOUT_REL = 0.03  # rollout_m ↔ 엔진 직선 착륙 미끄럼 허용 비율
ROLLOUT_T_END = 200.0  # [s] 그 직선 착륙 시뮬 길이 — 정지(약 183 s) 뒤 여유
# 마진 맵(서버 /analysis/margin-map — 웹 마진 탭) 재현 조건: 지연은 웹 툴 기본값(lib/loops.js DELAY_TOOL_DEFAULT 35 ms ·
# Padé 2차 — 문서에 지연 칸이 없다), 작동기는 문서 actuator, 루프는 레이트 댐퍼 3개(법칙 게인 — 칸마다 확정 표@칸)
MAP_DELAY_S, MAP_PADE = 0.035, 2
MAP_RATE_LOOPS = (("pitch", "lon", "q", "de"), ("roll", "lat", "p", "da"), ("yaw", "lat", "r", "dr"))
# 확정 게인 표 띠 검사에서 지금 알려진 결함으로 걸리는 자리 → 사유(strict xfail — 고쳐지면 XPASS로 빨개진다, 그때 이
# 항목을 지운다·재생성·재측정과 함께). 지금은 없다: 요 댐퍼 표가 2차 패스 적용 경계에서 2.9배 뛰던 것(띠 비 3.00)은
# 튜너가 닿은 점에도 2차 패스를 돌게 고쳐(design/tune.py _retune_with_later_closed) 띠 비 1.23, 요 설계 목표를 ζ_dr 0.6으로
# 올린 뒤 1.26이다
BAND_KNOWN_DEFECTS: dict = {}
# 문서가 정한 자동조종 칸(출처 「document」) 중 공학 근거로 레지스트리 기본값을 벗어나는 칸 → 근거. 결함을 피해 가려고 바꾼
# 값은 여기 두지 않는다(결함을 고친다)
LAW_DOCUMENT_OVERRIDES: dict = {}


def _raw() -> dict:
    text = resources.files("claw.profile").joinpath(_SHOWCASE_FILE).read_text(encoding="utf-8")
    return json.loads(text)


@pytest.fixture(scope="module")
def doc():
    return load_showcase()


@pytest.fixture(scope="module")
def base(doc):
    return build_profile(doc, validated=True)


@pytest.fixture(scope="module")
def eoir(doc):
    return build_profile(doc, "eoir", validated=True)


# ── 정체·로더 ─────────────────────────────────────────────────────────────


def test_문서가_검증을_통과하고_편집_가능한_저장_기체다():
    doc = validate_document(_raw())
    assert SHOWCASE_ID == "showcase-delta"
    assert doc["id"] == SHOWCASE_ID
    assert doc["is_example"] is False  # 예제 표시가 있으면 서버 저장 규칙이 설치를 거부한다
    assert [v["id"] for v in doc["variants"]] == ["eoir"]


def test_load_showcase는_검증된_독립_사본을_준다():
    a, b = load_showcase(), load_showcase()
    assert a == b == validate_document(_raw())
    assert a is not b and a["law"] is not b["law"]
    a["name"] = "고친 이름"
    a["law"]["design"] = None
    fresh = load_showcase()
    assert fresh == b and fresh["name"] != "고친 이름"  # 호출자가 고쳐도 캐시가 오염되지 않는다
    assert load_shipped_example()["id"] == EXAMPLE_ID  # 예제 로더는 그대로다


def test_패키지_파일이_생성_모듈의_정규_형식이다():
    """`python -m claw.profile.showcase --write`가 쓰는 모양 그대로다 — 손으로 고친 흔적(키 순서·들여쓰기)이 없다."""
    text = resources.files("claw.profile").joinpath(_SHOWCASE_FILE).read_text(encoding="utf-8")
    assert text == document_text(validate_document(json.loads(text)))


# ── 툴로 도출한 부분의 출처·신선도 ─────────────────────────────────────────


def test_δe_trim_표는_도출한_것이고_기본과_EO_IR형에서_낡지_않았다(doc, base, eoir):
    de = doc["law"]["alloc"]["de_trim"]
    assert de["source"] == "derived"
    prov = de["provenance"]
    assert prov["source"] == DERIVE_SOURCE and prov["shortfall"] == 0
    assert prov["configurations"] == ["base", "eoir"]
    assert base.de_trim_stale is False
    assert eoir.de_trim_stale is False
    assert base.alloc_trim_table() is not None and eoir.alloc_trim_table() is not None
    # 이관 10단계 — 요구 마하 M0.10~0.24 중 M0.225~0.24는 어느 요구 조건에서도 날 수 있는 트림이 없다(추력·제한). 표는
    # M0.22에서 끝나고 그 위 요구 구간은 런타임이 끝값을 쓴다 — 끝값으로 채워 완료라 하지 않고 두 구간을 따로 적는다
    cov = prov["coverage"]
    assert cov["required_mach"] == [0.1, 0.24] and cov["table_mach"] == [0.1, 0.22]
    assert cov["unsupported"] == [[0.225, 0.24]] and cov["beyond_table"] == [[0.22, 0.24]]


def test_생성기가_자기_출처에서_시드_경로와_설계_설정을_되짚는다(doc):
    """인자 없이 --write를 다시 불러도 같은 길(산출 근거 직행 · 표 출처에 적힌 설계 설정)을 밟는다 — 설계 목표 같은 선택이
    재실행에서 조용히 기본값으로 돌아가지 않는다. 이 생성기 출처가 없는 문서(예제)는 기본(quick · design_overrides)이다."""
    assert resolve_seed(doc, None) == "basis"
    assert resolve_design_config(doc, None) == doc["law"]["gain_tables"]["provenance"]["design"]["config"]
    assert resolve_seed(doc, "quick") == "quick" and resolve_design_config(doc, {"n_mach": 3}) == {"n_mach": 3}
    example = load_shipped_example()
    assert resolve_seed(example, None) == "quick" and resolve_design_config(example, None) is None


def test_생성기의_판정선_튜닝_목표는_문서의_것이다(doc):
    """기준 통합 ① — 설계 설정의 criteria·targets는 떼고 문서의 /criteria·/tuning(eval_criteria)으로 설계한다(서버 자동 설계와
    같은 길). 기록 설정에 목표가 남아 있어도 문서와 같으면 통과, 다르면 조용히 무시하지 않고 거부한다."""
    rec = doc["law"]["gain_tables"]["provenance"]["design"]["config"]
    assert doc["tuning"]["targets"]["zeta_sp"] == rec["targets"]["zeta_sp"] == 0.9
    ev = build_profile(doc, validated=True).eval_criteria
    stripped = {k: v for k, v in rec.items() if k not in ("criteria", "targets")}
    for cfg in (rec, stripped):
        c = _config(cfg, doc)
        assert c.targets.to_dict() == ev.targets.to_dict() and c.targets.zeta_sp == 0.9
        assert c.criteria.to_dict() == ev.margin.to_dict()
        # 기록에 n_mach가 없으면 요구영역 기본 격자 명세(None) — 이관 2단계 재생성은 격자를 요구영역에 맡겼다
        assert c.n_mach == rec.get("n_mach") and c.fit_mode == rec["fit_mode"]
    with pytest.raises(ValueError, match=r"targets\.zeta_sp"):
        _config({**rec, "targets": {"zeta_sp": 0.7}}, doc)
    # 문서가 목표를 안 적었으면 도구 기본값 — 설정의 목표가 그것을 덮지 않는다
    bare = copy.deepcopy(doc)
    bare.pop("tuning", None)
    assert _config(stripped, bare).targets.to_dict() == TuneTargets().to_dict()
    with pytest.raises(ValueError, match="/tuning"):
        _config(rec, bare)


def test_설계_게인은_툴이_잡은_것이다(doc):
    design = doc["law"]["design"]
    assert design is not None and doc["law"]["schedule"] is not None
    prov = design["provenance"]
    assert prov["source"] in SEED_SOURCES
    assert prov.get("ok", True) is True  # 빠른 탐색이면 채택 판정이 참이어야 한다(산출 근거 직행은 ok 칸이 없다)


def test_확정_게인_표가_있으면_출처가_자동_설계이고_낡지_않았다(doc, base):
    gt = doc["law"]["gain_tables"]
    if gt is not None:
        assert gt["provenance"]["source"] == "auto_design"
        assert base.gain_tables_stale is False
        tables = base.confirmed_gain_tables()
        assert set(tables) == set(gt["tables"])
    law = assemble_law(base)  # 설계·스케줄(또는 확정 표)·δe_trim이 함께 조립된다
    assert law.schedule is not None


def test_확정_게인_표는_표_표현_자동_설계가_검증한_그_표다(doc):
    """쇼케이스 기체도 자동 설계 기본 표현(fit_mode "table")으로 설계한다 — 점마다 선형화해 튜닝한 게인을 마하 분할점 표로
    그대로 싣고, 다항 재양자화가 없어 반출 표가 곧 세션이 검증한 표다(재샘플 오차 0 · 재검증에서 움직인 판정 0).
    그 표현은 표 출처의 설계 설정에 적혀 있어야 한다 — 웹 진행기 단계 8(공학 수정 뒤 재설계)이 이 기록을 설정으로 쓰므로
    (lib/showcase.js autodesignConfigFor), 빠지면 시연의 재설계가 출하 표와 다른 표현으로 돈다."""
    prov = doc["law"]["gain_tables"]["provenance"]
    assert prov["design"]["config"]["fit_mode"] == "table"
    # 설계 요약은 서버 apply-gains(routes/design.py _design_summary)와 같은 칸이다 — 표현·적합에서 뺀 표본 수·보류 자리
    assert prov["design"]["fit_mode"] == "table"
    assert prov["design"]["excluded_samples"] == 0 and prov["design"]["exclusion_withheld"] == []
    for name, t in doc["law"]["gain_tables"]["tables"].items():
        err = prov["resample_error"][name]
        assert err["max_abs"] == 0.0 and err["n_points"] == len(t["data"]), (name, err)
    assert prov["reverify"]["changed"] == 0 and prov["reverify"]["worse"] == 0, prov["reverify"]


def test_기록된_설계_설정으로_다시_설계하면_출하한_문서_그대로다(doc):
    """생성기 설계 단계를 표 출처의 설정으로 다시 돌리면 확정 표와 그 출처(판정·실패 수)가 출하한 문서와 같다 — 시연 단계 8이
    같은 설정으로 다시 설계해 같은 표를 내는 근거다. 엔진의 설계 동작이 바뀌면 여기서 걸린다: 그때는 `python -m
    claw.profile.showcase --write`로 다시 생성하고 착륙·검증·결함 창(web lib/showcase.js SHOWCASE_FAULT)을 다시 잰다
    (엔진이 바뀐 뒤 생성기 출력이 출하본과 갈라진 채로 남았던 적이 있다)."""
    new, summary = generate(doc, stages=("design",))
    assert summary["design_config"] == doc["law"]["gain_tables"]["provenance"]["design"]["config"]
    # 모든 점에서 튜닝이 성립했다 — 적합에서 뺀 표본(분할점 값이 이웃 보간인 자리)이 없다. 생성기 요약이 그것을 낸다
    rep = summary["stages"]["design"]["report"]
    assert rep["fit_mode"] == "table" and rep["excluded_samples"] == [] and rep["exclusion_withheld"] == []
    # 기록된 점 예산 안에서 트림 격자 세분화가 허용치까지 끝나고 절점 구간마다 검증이 섰다 — 예산은 닿지 않는 상한이다
    # (200 m 한 줄 43점 < 90 — 이관 3단계: 설계점 37 · 검증점 6. 절점 구간 6곳 중 5곳은 중점에 세분화가 둔 설계점이 있어
    # 검증점을 ¼ 자리로 옮겼다 — 설계점은 적합 표본이라 그 판정은 보간 검증이 아니다(리뷰 정정 전 초안은 그 5곳을 검증으로
    # 세어 38점 · 검증점 1이었다). 종전 표본 마하마다 분할점일 때 81점. 두 설계 고도 0·3000 m일 때는 예산 90이면 세분화가
    # 허용치 전에 끊기고 43구간이 검증점 없이 남아 150을 적었었다). 트림 미수렴 점은 최대 수평 속도(전 스로틀) 위라 남는다(문서
    # description). 이관 4단계(검증점 생성 절차 — v1.71): 내분점이 요구영역 행 범위 전부에 서서 M0.22~0.24 구간 중점 M0.23(전
    # 스로틀 위 — 물리적 불가)이 더해지고, 요구영역 경계표 모서리 8점(200·3000 m × 10·50 kg 마하 하한·상한)이 들어와 검증점
    # 15 — 상한 M0.24 넷은 물리적 불가, 하한 넷은 판정(3000 m 둘 합격·주의). 실패 0이라 표는 그대로다(판정 210 → 230).
    # 절점 점은 전부 설계점이 겸해 새 점이 없다. 요청 23(절점 7 · 내분점 7 · 경계 9 — 행 하한 설계점 포함) · 완료 17
    cov = rep["coverage"]
    assert cov["validation_missing"] == 0 and cov["validation_unplaceable"] == 0, cov
    assert rep["points"] == {"design": 37, "validation": 15}, rep["points"]
    assert cov["validation_points"] == 7 and cov["midpoints_at_design_points"] == 5, cov
    v = rep["validation"]
    assert (v["rule"], v["conditions"], v["requested"], v["done"], v["not_run"]) == ("plan", [[200.0, 25.0]], 23, 17, 0), v
    assert {k: b["requested"] for k, b in v["by_kind"].items()} == {"midpoint": 7, "knot": 7, "boundary": 9}, v
    # 요청 23 = 새 검증점 15 + 판정을 겸한 기존 설계점 8(절점 7 · 행 하한 M0.10375 경계)
    assert (v["added"], v["existing"]) == (15, 8), v
    assert rep["reinforcement"]["status"] == "tol_unset" and cov["d_unmeasured"] == 2, cov
    # 표는 공통 마하 절점을 공유한다 — 설계점 수와 무관하게 자리마다 절점 7점(M0.24 절점은 설계점 표본이 없어 뺐다)
    assert rep["knots"]["shared"] is True and set(rep["knots"]["tables"].values()) == {7}, rep["knots"]
    assert cov["refine_remaining"] is not None and cov["refine_remaining"] <= cov["refine_tol"], cov
    assert cov["refine_aborted"] is None and rep["n_points"] < summary["design_config"]["budget_points"], (cov, rep["n_points"])
    assert rep["iterations"] < summary["design_config"]["budget_iters"], rep["iterations"]  # 이터 예산도 닿지 않는 상한
    got, want = new["law"]["gain_tables"], doc["law"]["gain_tables"]
    assert got["provenance"] == want["provenance"]
    assert set(got["tables"]) == set(want["tables"])
    for name, t in want["tables"].items():
        g = got["tables"][name]
        np.testing.assert_allclose(g["axes"]["mach"], t["axes"]["mach"], rtol=1e-9, atol=1e-12, err_msg=name)
        np.testing.assert_allclose(g["data"], t["data"], rtol=1e-9, atol=1e-12, err_msg=name)


def test_처음부터_다시_생성하면_출하한_파일_그대로다(doc):
    """δe_trim 도출 → 산출 근거 직행(초기 게인) → 자동 설계 → 반영, 생성기 전 단계를 다시 돌린 문서가 패키지 파일과 바이트
    단위로 같다. 위 설계 단계 검사는 출하한 δe_trim·설계 게인 위에서만 돌아 앞 두 단계를 다시 재지 않는다 — δe_trim 도출이나
    산출 근거 직행의 동작이 바뀌어도(검사 간격·지연 기본값 등) 낡음 판정은 지문만 봐서 조용했고 출하 값이 생성기 출력과 갈라진
    채 남았다(EO/IR형은 설계 게인 × q̄ 역비 스케줄로 나므로 SCAS 전체가 시드 단계에서 온다). 생성기가 자기 출처를 보고 δe_trim·
    설계를 빈 자리에서 다시 잰다(grid_input·seed_input "none"). 약 14 s(δe_trim 도출이 대부분) — 전체 재생성이 곧 검사라
    따로 떼지 않는다."""
    new, summary = generate(doc)
    assert summary["stale"] == []
    assert summary["stages"]["de_trim"]["shortfall"] == 0
    assert new["law"]["alloc"] == doc["law"]["alloc"]
    assert new["law"]["design"] == doc["law"]["design"]
    text = resources.files("claw.profile").joinpath(_SHOWCASE_FILE).read_text(encoding="utf-8")
    assert document_text(new) == text


def test_확정_게인_표는_한_설계_고도_줄의_스케줄이다(doc):
    """확정 표는 마하 1축이라 한 고도의 스케줄만 담는다 — 기록된 설계 격자가 고도 하나·연료 하나(산출 근거 직행과 같은
    해면·연료 절반)이고 표에 톱니가 없다. 두 설계 고도(0·3000 m)를 주면 고도마다 최소 마하(행 하한)가 달라 두 줄의 점이
    한 마하 축에 번갈아 놓이고 값이 두 고도 사이를 오갔다(자리마다 방향 반전 40회 · 분할점 66 — 웹 자동 설계 적합 보고
    「톱니 최대 40회/분할점 66」, roll.ki 띠 비 2.63). 톱니 수는 fit.table_surface와 같은 자로 잰다(스케일 0.5 % 미만 변화 무시)."""
    from claw.design.fit import table_surface

    # 설계 고도 줄은 요구영역의 가장 낮은 행(200 m)이다 — 이관 2단계부터 COARSE는 요구영역 기본 격자에서 나와 요구영역
    # 밖 해면(산출 근거 직행의 점)에는 설계점이 서지 않는다. 연료는 산출 근거 직행과 같은 절반
    from claw.opspace import region_of

    cfg = doc["law"]["gain_tables"]["provenance"]["design"]["config"]
    _, _alt, fuel = basis_point(doc)
    assert cfg["alts"] == [min(region_of(doc).grid["alts"])] and cfg["fuels"] == [fuel], cfg
    for name, t in doc["law"]["gain_tables"]["tables"].items():
        zig = table_surface(t["axes"]["mach"], t["data"])["zigzag"]
        assert zig <= TABLE_ZIGZAG_MAX, (name, zig)


def test_확정_게인_표가_운용_범위_전부에서_자동_설계_검증을_넘는다(doc, base, eoir):
    """설계 격자는 200 m 한 줄이지만 기체는 운용 고도 전부(0~alt_max)와 연료 전부를 난다 — 같은 판정기(자동 설계 검증:
    DesignSession의 점·트림·선형 모델 위에서 reverify_resampled)로 **출하 표 그대로** 운용 범위 격자를 다시 판정해 실패가
    없다. 격자: 운용 고도를 1000 m 간격 + 천장, 연료 fuel_max × ENVELOPE_FUEL_FRACS(미션 연료 40 kg 포함), 마하 7 + 세분화 +
    검증점(점 상한 200 — 서버 MAX_POINTS). EO/IR형은 규칙 스케줄(설계 게인 × q̄ 역비)을 같은 격자로 본다. 실측: 기본형 판정
    880 · EO/IR형 830, 실패 0 (각 약 25 s — v1.70 절점 위 표. 이 세션의 검증점이 절점 구간 중점으로 바뀌어 판정 수도 옮았다.
    v1.66 요구영역 재설계 표에서 865 · 805).

    이 세션은 점·트림·선형 모델을 얻는 수레다 — 세션 **자신의** 설계(여러 고도를 마하 1축 표 하나로 적합)는 롤 속도 루프
    마진 가드(AS94900 끊는 자리 · 목표 GM 8 dB·PM 50° — tune._cap_by_margins) 뒤로 한 마하에서 해면과 고도를 함께 못 맞춰 budget_exhausted로
    끝난다(자기 표 실패 기본형 4 · EO/IR형 7). 판정 대상은 출하 표의 재판정(rv)뿐이라 전제는 "검증이 돌았다"(converged
    또는 budget_exhausted + 판정 케이스 있음)로 둔다. rv가 세션 검증 인용(identical)이면 출하 표를 안 본 것이라 막는다."""
    lo, hi = OPERATING_ALTS
    alts = sorted({*np.arange(lo, hi, 1000.0).tolist(), hi})
    fuels = [round(doc["mass"]["fuel_max"] * f, 6) for f in ENVELOPE_FUEL_FRACS]
    assert doc["mission_template"]["sim"]["fuel"] in fuels
    cfg = {**doc["law"]["gain_tables"]["provenance"]["design"]["config"], "alts": alts, "fuels": fuels,
           "budget_points": 200, "budget_iters": 1}
    import dataclasses

    for b, tables in ((base, base.confirmed_gain_tables()), (eoir, eoir.gain_tables())):
        inp = design_inputs(b)
        # 운용 범위(0~3500 m)는 요구영역(200~3000 m)보다 넓다 — 이 세션은 운용 범위 전부의 점을 얻는 검사 수레라 요구영역
        # 기본 격자(요구영역 밖 행에 점을 두지 않는다 — 이관 2단계)가 아니라 요구영역 없는 옛 격자로 돈다
        inp["verdict_ctx"] = dataclasses.replace(inp["verdict_ctx"], region=None, cache={})
        session = DesignSession(_config(cfg, doc))
        session.run(inp["aircraft"], inp["stall_table"], inp["limits"], inp["db_ranges"], inp["design"],
                    verdict_ctx=inp["verdict_ctx"], rate_filters=inp["rate_filters"], actuator=inp["actuator"],
                    fingerprint="")
        assert session.status in ("converged", "budget_exhausted"), (b.variant, session.report()["status"])
        assert session.margin_out.get("cases"), b.variant  # 검증이 실제로 돌았다(재판정 재료)
        assert {p.case.alt for p in session.points} >= set(alts)
        rv = session.reverify_resampled(inp["aircraft"], tables)
        assert not rv.get("identical"), b.variant  # 세션 표 인용이 아니라 출하 표를 다시 판정했다
        assert rv["failures"] == [] and rv["n_judged"] >= ENVELOPE_MIN_JUDGED, (b.variant, rv["n_judged"], rv["failures"][:3])



def _template_margin_map(doc, profile) -> dict:
    """마진 탭이 서버에 거는 그 계산 — 템플릿 트림 격자 전 칸 × 레이트 루프 3개, AS94900 끊는 자리(이 루프를 끊고 같은 축의
    나머지 루프는 닫는다 — 서버 close_others 기본). 서버 라우트(routes/analysis.py submit_margin_map: _LawGains.at →
    _closed_others → _compose_loop → nyquist_margins)와 같은 엔진 함수를 같은 순서로 부른다 — 엔진 테스트는 서버를 못
    가져온다(공유 체크아웃의 편집 설치). 반환 {칸 이름: {루프: 마진 | None(트림 미수렴)}}."""
    g = doc["mission_template"]["trim_grid"]
    n = round((g["mach"]["to"] - g["mach"]["from"]) / g["mach"]["step"]) + 1
    machs = [round(g["mach"]["from"] + i * g["mach"]["step"], 6) for i in range(n)]
    cases = [TrimCase(f"M{m:g}_h{a:g}_f{f:g}", mach=m, alt=a, fuel=f) for a in g["alt"] for f in g["fuel"] for m in machs]
    act = doc["actuator"]["params"]
    law, ac = assemble_law(profile), profile.aircraft()
    out = {}
    for tr in trim_batch(ac, cases, fingerprint=""):
        if not tr.converged:
            out[tr.case.name] = None
            continue
        models = dict(zip(("lon", "lat"), split_axes(linearize(ac, tr))))
        kp = {grp: effective_gain(law, grp, "k_rate", tr.case) for grp, *_ in MAP_RATE_LOOPS}
        cell = {}
        for grp, axis, x, u in MAP_RATE_LOOPS:
            others = [{"x_out": ox, "u_in": ou, "kp": kp[og], "ki": 0.0, "sign": -1.0}
                      for og, oa, ox, ou in MAP_RATE_LOOPS if og != grp and oa == axis and kp[og] != 0.0]
            loop = broken_loop(models[axis], x_out=x, u_in=u, kp=kp[grp], ki=0.0, sign=-1.0, others=others,
                               actuator_wn=act["wn"], actuator_zeta=act["zeta"], delay_s=MAP_DELAY_S, pade_order=MAP_PADE)
            cell[grp] = nyquist_margins(loop)
        out[tr.case.name] = cell
    return out


def test_마진_맵_템플릿_격자_전_칸이_레이트_루프_합격선_안이다(doc, base, eoir):
    """웹 마진 탭(템플릿 격자 20칸 · 레이트 루프 3개 · 문서 작동기 · 지연 35 ms)이 칠하는 칸이 전부 안정이고 PM ≥ 45° ·
    GM ≥ 6 dB(MarginCriteria 합격선 — VERIFY가 레이트 루프에 쓰는 선)다. 기본형 롤 댐퍼는 튜너 목표(TuneTargets
    GM 8 dB · PM 50°)까지 든다 — 자동 설계가 롤 댐퍼를 AS94900 끊는 자리의 마진으로 캡하고(tune._cap_by_margins) 그
    표를 실었으니, 설계 격자(해면·연료 25 kg) 밖 템플릿 칸(3000 m · 10·50 kg)에서도 그 목표가 선다.
    실측(서버 라우트와 같은 수): 기본형 pitch_q PM 53.3° · GM 10.9 dB, roll_p PM 70.1° · GM 8.31 dB(M0.15_h200_f10),
    yaw_r PM 80.2° · GM 16.0 dB — 가드 전 출하본은 roll_p GM 7.07 dB · PM 61.3°(M0.12_h200_f10)라 목표에 못 들었다
    (P6 e2e의 4.1~5.1 dB는 그보다 앞선 게인). EO/IR형(규칙 스케줄)은 roll_p GM 8.02 dB · PM 67.7°, M0.18_h3000_f50은
    엔벨로프 밖이라 트림이 서지 않는다(평가 탭 설명과 같은 칸)."""
    crit, tgt = MarginCriteria(), TuneTargets()
    for b, allow_untrimmed in ((base, set()), (eoir, {"M0.18_h3000_f50"})):
        cells = _template_margin_map(doc, b)
        assert len(cells) == 20, (b.variant, len(cells))
        assert {k for k, v in cells.items() if v is None} == allow_untrimmed, b.variant
        for name, cell in cells.items():
            for grp, m in (cell or {}).items():
                where = (b.variant, name, grp, m.get("pm_deg"), m.get("gm_db"))
                assert "closed_loop" not in m, where  # 발산 칸 없음(폐루프 안정)
                assert m["pm_deg"] >= crit.pm_min_deg and m["gm_db"] >= crit.gm_min_db, where
                if b is base and grp == "roll":
                    assert m["pm_deg"] >= tgt.pm_deg and m["gm_db"] >= tgt.gm_db, where

def _same_tables(got: dict, want: dict):
    assert set(got) == set(want)
    for name, t in want.items():
        assert got[name].axis_names == t.axis_names == ("mach",), name
        np.testing.assert_array_equal(got[name].axes[0], t.axes[0], err_msg=name)
        np.testing.assert_array_equal(got[name].data, t.data, err_msg=name)


def test_EO_IR형은_규칙_스케줄로_법칙이_조립된다(doc, base, eoir):
    """확정 표는 기본형 설계 결과다 — 기본 문서에서 확정한 표는 문서를 바꾸는 EO/IR형에서 기준 지문이 어긋나 낡음이라
    조립이 거부한다(서버 시뮬·조립·영향성 422 — 피커에서 EO/IR형을 고르면 못 날았다). 그래서 EO/IR형 패치가 표를 비워
    규칙 스케줄(도구가 도출한 설계 게인 × q̄ 역비)로 난다. 기본형은 확정 표를 그대로 쓴다(낡지 않음)."""
    patch = next(v for v in doc["variants"] if v["id"] == "eoir")["patch"]
    assert GAIN_TABLES_PTR in patch and patch[GAIN_TABLES_PTR] is None
    assert eoir.doc["law"]["gain_tables"] is None and eoir.gain_tables_stale is False
    assert eoir.confirmed_gain_tables() is None and eoir.de_trim_stale is False
    law = assemble_law(eoir)  # 낡은 표 거부(ProfileError /law/gain_tables) 없이 조립된다
    _same_tables(law.schedule.tables, eoir.gain_tables())
    # 기본형은 확정 표로 난다 — 변형의 치환이 기본 문서의 표를 건드리지 않는다
    assert doc["law"]["gain_tables"] is not None and base.gain_tables_stale is False
    _same_tables(assemble_law(base).schedule.tables, base.confirmed_gain_tables())
    # 그 사실이 표 출처에 있다(생성기 rule_schedule_variants)
    prov = doc["law"]["gain_tables"]["provenance"]
    assert prov["rule_schedule_variants"] == ["eoir"] and "EO/IR형" in prov["variant_note"]


def test_생성기는_확정_표를_못_쓰는_형상_변형만_규칙_스케줄로_돌린다(doc):
    """생성기의 설계 단계가 표를 반영한 뒤 쓰는 규칙(rule_schedule_variants) — 치환을 뺀 문서에서 다시 돌리면 패키지
    문서의 치환이 그대로 되살아나고(자기 출력에 다시 돌려도 같다), 지문 밖만 바꾸는 변형(표시 모델)은 표를 그대로 쓴다."""
    stripped = copy.deepcopy(doc)
    eoir_patch = next(v for v in stripped["variants"] if v["id"] == "eoir")["patch"]
    del eoir_patch[GAIN_TABLES_PTR]
    with pytest.raises(ProfileError) as e:  # 치환이 없으면 EO/IR형 조립은 낡은 표를 거부한다
        assemble_law(build_profile(stripped, "eoir", validated=True))
    assert e.value.path == GAIN_TABLES_PTR
    again, moved = rule_schedule_variants(stripped)
    assert moved == ["eoir"] and validate_document(again) == doc
    assert rule_schedule_variants(doc) == (doc, ["eoir"])  # 이미 치환이 있어도 같은 결론

    # 표시 모델만 바꾸는 변형 — 지문 밖이라 기본형 표가 그대로 맞는다. 치환하지 않는다
    looks = copy.deepcopy(doc)
    looks["variants"].append({"id": "paint", "name": "표시만", "patch": {"/display": eoir_patch["/display"]}})
    looks = validate_document(looks)
    out, moved = rule_schedule_variants(looks)
    assert moved == ["eoir"] and GAIN_TABLES_PTR not in out["variants"][1]["patch"]
    assert build_profile(out, "paint", validated=True).gain_tables_stale is False

    # 기본 문서에 표가 없으면 할 일이 없다
    bare = copy.deepcopy(stripped)
    bare["law"]["gain_tables"] = None
    assert rule_schedule_variants(bare) == (bare, [])


def test_변형의_표_비움은_지금_표만의_함수다(doc):
    """rule_schedule_variants는 이력(전에 넣은 null)과 무관하다 — 같은 사람 몫 내용이면 null이 남았든 없든 같은 문서가 난다.
    예전에는 표가 맞게 된 변형(질량·관성 편집을 되돌려 표시만 남은 EO/IR형)에 전 실행의 null이 남아, 출처 기록 없이 규칙
    스케줄로 날았다(확정 표 None · 낡음 False). 기본 문서에 표가 없을 때 남은 null도 뺀다."""
    looks_only = copy.deepcopy(doc)
    item = next(v for v in looks_only["variants"] if v["id"] == "eoir")
    item["patch"] = {"/display": item["patch"]["/display"], GAIN_TABLES_PTR: None}
    leftover = validate_document(looks_only)
    clean = copy.deepcopy(leftover)
    del next(v for v in clean["variants"] if v["id"] == "eoir")["patch"][GAIN_TABLES_PTR]
    out_a, moved_a = rule_schedule_variants(leftover)
    out_b, moved_b = rule_schedule_variants(clean)
    assert moved_a == moved_b == [] and out_a == out_b == clean
    b = build_profile(out_a, "eoir", validated=True)
    assert b.gain_tables_stale is False and b.confirmed_gain_tables() is not None  # 기본형 표로 난다

    bare = copy.deepcopy(doc)  # 표 없는 기본 문서 + EO/IR형 null
    bare["law"]["gain_tables"] = None
    out, moved = rule_schedule_variants(bare)
    assert moved == [] and GAIN_TABLES_PTR not in next(v for v in out["variants"] if v["id"] == "eoir")["patch"]
    # 표가 낡는 변형은 null이 이미 있어도 그 자리 그대로다(키 순서까지 — 정규 파일이 흔들리지 않는다)
    again, moved = rule_schedule_variants(doc)
    assert moved == ["eoir"] and document_text(again) == document_text(doc)


# ── 공학 정합 ─────────────────────────────────────────────────────────────


def test_실속표가_CL_표의_꼭대기와_맞는다(doc, base):
    """공력 뷰어의 실속 추출(α를 따라 CL이 오르다 떨어지는 첫 꼭대기)이 실속표와 ±0.01 rad 안이다.

    보는 마하: 공력 DB 마하 범위(db_ranges.mach — 공력이 스스로 유효하다고 적은 범위) 전부를 STALL_SCAN_STEP 간격으로 +
    실속표·CL 표의 마하 격자점 + 설계 마하 + M_NO. 운용 범위(M_NO 0.24)만 보던 때는 M0.32~0.41에서 실속표(0.385 쪽으로
    내려가는 램프)가 CL 표 꼭대기(M0.45 열까지 α 0.40)보다 최대 0.024 rad 낮은 것을 못 봤다 — CL 표에 α 0.385 행·M0.35
    열을 두어 꼭대기가 실속표를 따라 내려간다(꼭대기가 α 격자점 사이를 한 칸씩 건너는 마하가 M0.30·0.40 — 두 격자점
    가운데라 최대 차 0.0075)."""
    lo, hi = doc["aero"]["db_ranges"]["alpha"]
    m_lo, m_hi = doc["aero"]["db_ranges"]["mach"]
    st = doc["structural"]
    table = base.stall_table()
    cl = next(t for t in doc["aero"]["coefficients"]["CL"] if not t["inputs"])["k"]["table"]["axes"]["mach"]
    machs = sorted({round(float(m), 6) for m in np.arange(m_lo, m_hi + 1e-9, STALL_SCAN_STEP)}
                   | set(doc["stall"]["table"]["axes"]["mach"]) | set(cl)
                   | {doc["law"]["schedule"]["m_design"], st["mach_no"]})
    assert machs[0] == m_lo and machs[-1] == m_hi
    for m in machs:
        s = aero_slice(base, "alpha", lo, hi, MAX_POINTS, {"mach": m})["stall"]
        assert s["extracted"] is not None, (m, s["reason"])
        assert abs(s["extracted"] - float(table.interp(mach=m))) <= STALL_TOL + 1e-9, (m, s)


def _min_trim_speed(built, fuel, alt=0.0, coarse=0.005, fine=0.0005):
    """해면(기본) 최소 트림 속도 [m/s] — 엔벨로프 안(수렴·포화 여유·α 여유) 첫 마하. 성긴 격자로 첫 점을 찾고 그 앞 한 칸을
    촘촘히 되짚는다. 찾은 격자점(참값의 위쪽 — fine 한 칸 안)을 쓴다: 비율 판정이 보수 쪽으로 기운다."""
    ac, ctx = built.aircraft(), VerdictContext.from_profile(built)

    def ok(m):
        return envelope_ok(trim_level(ac, TrimCase(f"v{m:.4f}", mach=m, alt=alt, fuel=fuel)), ctx)
    m = 0.03
    while m <= built.doc["structural"]["mach_no"]:
        if ok(m):
            lo = max(0.03, round(m - coarse, 4))
            while lo < m and not ok(lo):
                lo = round(lo + fine, 5)
            return lo * isa_atmosphere(alt).a
        m = round(m + coarse, 4)
    raise AssertionError("M_NO까지 수평비행점이 없다")


def test_레일_이탈속도는_만재_최소_트림_속도의_1_15배_이상이다(doc, base):
    v_min = _min_trim_speed(base, doc["mass"]["fuel_max"])
    exit_speed = doc["ground"]["rail"]["exit_speed"]
    assert exit_speed >= RAIL_EXIT_MIN_RATIO * v_min, (exit_speed, v_min, exit_speed / v_min)


def test_레일_사출_축방향_하중배수가_종방향_발사하중_한계_아래다(doc, base, eoir):
    """판정 기준은 웹 착륙 요약(lib/replay.js launchLoad)과 같은 축방향 하중배수 n_x = gx + sin γ다 — launch_gx는
    레일 축 **순**가속도라 중력 성분이 빠져 있다(plant/ground.py LaunchRail.launch_gx). 순가속도만 견주면 앙각만큼
    낙관이다. 형상 변형이 레일·한계를 덮어쓸 수 있으므로 형상마다 본다."""
    for b in (base, eoir):
        limit = b.doc["structural"]["n_x_launch"]
        assert limit is not None
        rail = b.launch_rail()
        assert rail.launch_gx == pytest.approx(rail.exit_speed ** 2 / (2.0 * rail.length) / G0)
        nx = rail.launch_gx + math.sin(rail.elev_angle)
        assert rail.elev_angle > 0.0 and nx > rail.launch_gx  # 앙각이 위면 중력 성분만큼 더 무겁다
        assert nx < limit, (b.variant, rail.launch_gx, math.sin(rail.elev_angle), nx, limit)


def test_문서가_정한_자동조종_칸은_레지스트리_기본값이다(doc):
    """게인 도출(산출 근거 직행)은 문서 설계의 비유도 칸(명령필터 시정수·자세 한계·선회 보상)을 이어 쓰고 출처를
    「document」로 적는다 — 그 칸이 사람 몫이다. 쇼케이스 기체는 그 칸을 레지스트리 기본값으로 둔다: 결함을 피해 가려고 바꿔
    둔 값이 남지 않게. 속도 명령필터 0.5 s는 발진 행의 필터가 V = 0에 붙잡혀 이탈 뒤 스로틀이 꺼지던 결함(fcl/graphs.py 추월
    동기화로 고침)을, 피치 명령 상한 0.35 rad는 상수 θ 상한의 커버리지 거짓 FAIL(verify/autocode.py 상수 포트 정당화로 고침)을
    피하던 값이었다 — 둘 다 기본값 2 s·0.3 rad로 돌아왔다. 공학 근거로 벗어나는 칸은 LAW_DOCUMENT_OVERRIDES에 근거와 함께 둔다."""
    import claw.fcl  # noqa: F401 — 자동조종 블록 등록(레지스트리)

    defaults = {d.name: d.default for d in REGISTRY.param_defs("fcl", "Autopilot")}
    design = doc["law"]["design"]
    source = design["provenance"]["autopilot"]
    human = sorted(k for k, s in source.items() if s == "document")
    assert {"tau_spd", "theta_hi"} <= set(human), human
    off = {k: (design["autopilot"][k], defaults[k]) for k in human
           if design["autopilot"][k] != defaults[k] and k not in LAW_DOCUMENT_OVERRIDES}
    assert not off, off


def _fly_launch(built, fuel):
    """웹 기본 미션의 발진·상승 행(미션 템플릿 climb 속도·피치, 레일 이탈 → 상승 → 순항)을 레일 발진부터 LAUNCH_FLY_S 날린다.

    서버 시뮬 조립(routes/sim.py _build)과 같은 재료다 — 스키드·지상 트림(δe·자세 웜스타트)·문서 레일·문서 작동기·문서 법칙.
    레일이 있으면 속도 적분기와 스로틀은 발사 출력(Simulator launch_throttle 기본 1.0 — 전 출력)에서 출발한다(지상 트림
    스로틀 0이 아니다). 항법 오차는 뺀다(이상 항법)."""
    sim_t = built.doc["mission_template"]["sim"]
    ac = built.aircraft(ground=built.skid_gear())
    tr = trim_ground(ac, TrimCase("pad", mach=0.0, alt=0.0, fuel=fuel, condition="ground"))
    assert tr.converged
    climb, cruise = sim_t["climb"], sim_t["cruise"]
    modes = [
        ModeSpec(name="launch", speed=climb["speed"], pitch=climb["pitch"], heading=0.0,
                 exit_when=("off_rail",), next="climb"),
        ModeSpec(name="climb", speed=climb["speed"], pitch=climb["pitch"], heading=0.0,
                 exit_when=("alt_ge", climb["exit_alt"]), next="cruise"),
        ModeSpec(name="cruise", speed=cruise["speed"], alt=cruise["alt"], heading=0.0, exit_when=("time_ge", 1e9)),
    ]
    sim = Simulator(aircraft=ac, fcl=assemble_law(built), guidance=Guidance(modes),
                    stall_table=built.stall_table(), db_ranges=built.db_ranges(), dt_plant=0.01, control_hz=100.0,
                    actuator_params=built.actuator_params(), fuel_flow=sim_t["fuel_flow"], ground_elev=0.0,
                    launch=built.launch_rail())
    return sim.run(tr, t_end=LAUNCH_FLY_S, fingerprint="showcase-launch")


@pytest.mark.parametrize("shape,fuel", [
    pytest.param("base", "template", id="기본형_템플릿_연료"),
    pytest.param("eoir", "max", id="EO_IR형_만재"),
])
def test_발진_직후_스로틀이_들어오고_고도가_처지지_않는다(doc, base, eoir, shape, fuel):
    """레일 위에서는 사출기가 속도를 올리고 속도 명령필터가 기체를 따라간다(fcl/graphs.py 추월 동기화) — 이탈 순간 기준이
    이탈속도라 스로틀이 곧 들어오고 상승이 이어진다. 고치기 전에는 기준이 V = 0에서 τ_spd로 기어올라 이탈 직후 「명령 <
    속도」로 스로틀이 0에 머물렀다(레지스트리 기본 2 s에서 약 3.4 s — 고도 18.3 → 13.6 m, 그래서 문서가 0.5 s로 피해
    갔었다). 그 뒤에도 속도 적분기가 지상 트림 스로틀 0에서 출발해 0.5를 넘기는 데 약 2.4 s가 걸렸고, 가장 무거운 만재
    EO/IR형은 이탈 뒤 4.3 m 처졌다(웹 기본 미션 4.4 m) — 이제 레일 발진은 적분기·스로틀을 발사 출력에서 웜스타트해
    (sim/simulator.py launch_throttle) 이탈 순간 전 출력이고 처짐이 0이다. 연료는 웹 기본 미션(템플릿 sim.fuel)과 만재."""
    built = base if shape == "base" else eoir
    kg = doc["mission_template"]["sim"]["fuel"] if fuel == "template" else doc["mass"]["fuel_max"]
    res = _fly_launch(built, kg)
    s, t = res.signals, np.asarray(res.t)
    on = np.asarray(s["on_rail"], dtype=bool)
    i = int(np.argmax(~on))  # 이탈 뒤 첫 표본
    assert 0 < i and not on[i:].any()
    rail = built.doc["ground"]["rail"]
    assert s["spd_cmd_filt"][i] >= 0.95 * rail["exit_speed"], (s["spd_cmd_filt"][i], rail["exit_speed"])
    thr = 0.5 * (np.asarray(s["thr_l"]) + np.asarray(s["thr_r"]))
    j = int(np.searchsorted(t, t[i] + LAUNCH_THR_DELAY))
    assert thr[i:j].max() > 0.05, "이탈 뒤 스로틀이 0에 머물렀다"
    h = np.asarray(s["h"])[i:]
    sag = float(np.max(np.maximum.accumulate(h) - h))
    assert sag <= LAUNCH_SAG_MAX, (shape, kg, sag)


def test_접근_플레어_속도는_가장_무거운_형상의_최소_트림_속도_위다(doc, base, eoir):
    """미션 템플릿 하나를 기본형·EO/IR형이 함께 쓰므로 기준 속도는 가장 무거운 착륙 형상(만재)에서 잡는다 — 가벼운 형상은
    여유가 더 크다. 플레어가 α 리미터·θ 명령 상한에 닿지 않게 하는 몫이다(웹 기본 미션 실측: 플레어 36 m/s에서 EO/IR형이
    활주로 앞 374 m에 −1.4 m/s로 닿았다)."""
    v_min = max(_min_trim_speed(b, doc["mass"]["fuel_max"]) for b in (base, eoir))
    sim = doc["mission_template"]["sim"]
    assert sim["approach"]["speed"] >= APPROACH_MIN_RATIO * v_min, (sim["approach"]["speed"], v_min)
    assert sim["flare"]["speed"] >= FLARE_MIN_RATIO * v_min, (sim["flare"]["speed"], v_min)
    assert sim["approach"]["speed"] > sim["flare"]["speed"]


def test_마지막_웨이포인트_도달_반경은_헤딩_루프_이월_거리다(doc):
    """기본 미션의 순항은 웨이포인트를 순수추적(guidance/path.py LOS — 활성 점의 방위를 헤딩 명령으로)으로 날고, 마지막 점
    (파이널 진입)은 다음 구간이 없어 선회 예상 전환 없이 **도달 반경**에서 접근에 넘긴다. 접근은 활주로 방위만 잡는다(방위
    유지이지 중심선 추종이 아니다). 넘기는 순간 기체는 그 점을 겨눈 채 중심선에서 c만큼 옆에 있고 헤딩 오차는 약 −c/R_acc다.
    헤딩 루프는 뱅크 명령 φ = kp_hdg·Δψ(비례만 — fcl/graphs.py)에 협조선회 ψ̇ = g·φ/V라 시정수 V/(g·kp_hdg)로 가라앉고,
    그동안 옆으로 −c·V²/(g·kp_hdg·R_acc)만큼 더 간다 — 도달 반경이 V²/(g·kp_hdg)이면 가라앉는 순간 중심선 위다. 속도는 넘길
    때의 순항 속도다. 100 m(그 거리의 절반)에서는 중심선을 지나 기본형·EO/IR형 × 연료 10/40/50 모두 +20~24 m 옆에 내렸다
    (웹 기본 미션 실측 — 착륙 요약이 그것을 「접지 횡편차」로 판정한다)."""
    ap = doc["law"]["design"]["autopilot"]
    # 헤딩 게인이 스케줄되면 순항 마하의 값을 써야 하고, 적분이 있으면 1차 근사가 아니다 — 지금 문서는 둘 다 아니다
    assert not any(k.startswith("heading.") for k in (doc["law"]["schedule"] or {}).get("scheduled", []))
    assert ap["ki_hdg"] == 0.0
    sim = doc["mission_template"]["sim"]
    lead = sim["cruise"]["speed"] ** 2 / (G0 * ap["kp_hdg"])
    assert sim["accept_radius"] == pytest.approx(lead, rel=HANDOVER_TOL), (sim["accept_radius"], lead)


def _linear_hard_fails(built, cases):
    """평가 탭 선형 판정(pipeline.evaluate depth="linear", 기본 기준)의 하드 FAIL — (트림 목록, {케이스: [(check, loop)]})."""
    from claw.pipeline.criteria import GainEvalCriteria
    from claw.pipeline.evaluate import evaluate
    from claw.pipeline.influence import Shape

    ac = built.aircraft()
    trims = trim_batch(ac, cases)
    out = evaluate(ac, trims, Shape(profile=built), GainEvalCriteria(), depth="linear")
    fails: dict = {}
    for hf in out["aggregate"]["hard_fails"]:
        fails.setdefault(hf["case"], []).append((hf["check"], hf.get("loop")))
    return trims, fails


def test_속도_루프의_하드_FAIL은_문서가_적어_둔_최소_속도_근처_고고도_띠뿐이다(doc, base, eoir):
    """속도 루프 게인(자동조종 kp_spd·ki_spd)은 산출 근거 직행의 경험식 상수라 스케줄도 자동 설계 판정도 받지 않는다. 평가 탭
    선형 판정(승강타 고정 기체의 스로틀→속도 — 우반면 영점)은 전력 곡선 뒷면(최소 트림 속도 바로 위, 스로틀 약 0.86)의 높은
    고도에서 spd_u PM < 45° · GM < 6 dB 하드 FAIL을 낸다 — 운용 범위 안이라 문서 description이 그 띠를 적는다. 여기서 그 서술을
    붙잡는다: 운용 고도 × 연료 격자의 엔벨로프 안 점에서 하드 FAIL은 ① spd_u의 PM·GM뿐이고 ② 그 행 최소 트림 마하의
    SPD_BAND_RATIO 배 안이며 ③ 기본형 SPD_BAND_ALT_MIN["base"] m · EO/IR형 ["eoir"] m 아래에는 없고 ④ 실제로 있다(고쳐지면
    description을 고치라는 신호). 실측(0.0025 격자): 최대 비 1.043 — 기본형 3500 m · 50 kg M0.1175–0.1225, EO/IR형 2500 m ·
    50 kg · 3500 m · 25 kg. 미션 템플릿 트림 격자에서는 기본형 하드 FAIL 0, EO/IR형은 엔벨로프 밖 점(M0.12 · 3000 m · 50 kg)뿐이다."""
    fuel_max = doc["mass"]["fuel_max"]
    lo, hi = OPERATING_ALTS
    alts = sorted({*np.arange(lo, hi, 1000.0).tolist(), hi})
    fuels = [round(fuel_max * f, 6) for f in ENVELOPE_FUEL_FRACS]
    machs = np.round(np.arange(*SPD_SCAN_MACH), 4)
    found = {}
    for b in (base, eoir):
        cases = [TrimCase(f"M{m:.4f}_h{a:g}_f{f:g}", mach=float(m), alt=a, fuel=f)
                 for a in alts for f in fuels for m in machs]
        trims, fails = _linear_hard_fails(b, cases)
        ctx = VerdictContext.from_profile(b)
        inside = [tr for tr in trims if tr.converged and envelope_ok(tr, ctx)]
        m_min = {}
        for tr in inside:
            key = (tr.case.alt, tr.case.fuel)
            m_min[key] = min(m_min.get(key, 9.0), tr.case.mach)
        for tr in inside:
            got = fails.get(tr.case.name)
            if not got:
                continue
            c = tr.case
            assert {loop for _, loop in got} == {"spd_u"} and {k for k, _ in got} <= {"margins.pm", "margins.gm"}, (c.name, got)
            assert c.mach <= SPD_BAND_RATIO * m_min[(c.alt, c.fuel)] + 1e-9, (c.name, m_min[(c.alt, c.fuel)])
            assert c.alt >= SPD_BAND_ALT_MIN[b.variant or "base"], (b.variant, c.name)
            found.setdefault(b.variant or "base", []).append(c.name)
        # 미션 템플릿 트림 격자 — 평가 탭 기본 격자. 하드 FAIL은 엔벨로프 밖 점에서만
        g = doc["mission_template"]["trim_grid"]
        tm = np.round(np.arange(g["mach"]["from"], g["mach"]["to"] + 1e-9, g["mach"]["step"]), 4)
        grid = [TrimCase(f"M{m:g}_h{a:g}_f{f:g}", mach=float(m), alt=a, fuel=f)
                for a in g["alt"] for f in g["fuel"] for m in tm]
        trims, fails = _linear_hard_fails(b, grid)
        env = {tr.case.name: envelope_ok(tr, ctx) for tr in trims}
        assert not [n for n in fails if env[n]], (b.variant, fails)
        if b.variant is None:
            assert fails == {}
    assert set(found) == {"base", "eoir"}, found
    assert "spd_u" in doc["description"] and "kp_spd" in doc["description"]


def test_미션_템플릿의_고도는_운용_고도_범위_안이다(doc):
    """선도·트림 격자·미션 고도가 운용 고도(OPERATING_ALTS) 안이다. 엔벨로프 스캔 고도 칸(scan_alt)은 v3에서 폐지됐다 —
    스캔 격자는 요구영역 기본 격자다(이관 11단계 · v1.66부터 화면이 그 칸을 읽지 않았다)."""
    mt = doc["mission_template"]
    env = mt["envelope"]
    assert "scan_alt" not in env and "scan_mach" not in env
    vn = env["alt"] if isinstance(env["alt"], list) else [env["alt"]]
    sim = mt["sim"]
    alts = [*vn, *mt["trim_grid"]["alt"], sim["cruise"]["alt"], sim["climb"]["exit_alt"]]
    assert all(OPERATING_ALTS[0] <= a <= OPERATING_ALTS[1] for a in alts), alts


def test_미션_시뮬_길이는_실측_정지_시각_뒤_여유다(doc):
    """t_end는 계산이 정하지 않는 사람 몫 값이라 근거를 문서 description과 여기 둔다 — 웹 기본 미션(장주 착륙, S1 착륙 하네스:
    웹 lib로 지은 요청 → 서버 시뮬 → 웹 착륙 요약) 기본형·EO/IR형 × 연료 10·40·50 kg의 정지 시각 최대 LANDING_STOP_MAX_S
    (기본형 10 kg — 나머지 447.6~449.0 s) 뒤 T_END_DWELL_S 안, 5 s 단위다. 짧으면 느린 조합이 정지 전에 끊기고, 길면 재생·결과
    저장만 는다(t_end 475 · 100 Hz 본문 약 69 MB). 법칙·미션 템플릿이 바뀌면 하네스로 다시 재고 이 값과 description을 고친다."""
    t_end = doc["mission_template"]["sim"]["t_end"]
    assert t_end % 5 == 0
    lo, hi = T_END_DWELL_S
    assert lo <= t_end - LANDING_STOP_MAX_S <= hi, (t_end, LANDING_STOP_MAX_S)
    assert "t_end 475" in doc["description"] and f"{LANDING_STOP_MAX_S:.1f} s" in doc["description"]


def test_미끄럼_거리는_템플릿_연료의_실측이다(doc, base):
    """rollout_m(웹 착륙 요약이 미끄럼 거리 기준으로 쓴다)은 템플릿 연료로 착륙해 잰 값이다 — 엔진 시뮬로 다시 잰다. 경로는 웹
    기본 미션(장주)이 아니라 직선이다: 미끄럼은 플레어 속도·접지 강하율·스키드 마찰이 정하고 수평 경로와는 무관하다(제품 예제
    test_landing_shipped_example과 같은 모양 — 웹 기본 미션 기본형 218 m · EO/IR형 219 m, 여기 기본형 218.0 m · EO/IR형
    219.3 m). 허용대 ROLLOUT_REL은 두 형상 차의 두 배 남짓이다. 순항 체류 20 s짜리 비행 한 번(정지 약 183 s — 시뮬은
    t_end까지 돌므로 ROLLOUT_T_END에서 끊는다) — 약 25 s."""
    from claw.nav import NavErrorModel

    m = doc["mission_template"]["sim"]
    c, cr, ap, fl = m["climb"], m["cruise"], m["approach"], m["flare"]
    modes = [
        ModeSpec(name="launch", speed=c["speed"], pitch=c["pitch"], heading=0.0, exit_when=("off_rail",), next="climb"),
        ModeSpec(name="climb", speed=c["speed"], pitch=c["pitch"], heading=0.0,
                 exit_when=("alt_ge", c["exit_alt"]), next="cruise"),
        ModeSpec(name="cruise", speed=cr["speed"], alt=cr["alt"], heading=0.0, exit_when=("time_ge", 20.0), next="approach"),
        ModeSpec(name="approach", speed=ap["speed"], hdot=ap["hdot"], heading=0.0,
                 exit_when=("alt_le", ap["exit_alt"]), next="flare"),
        ModeSpec(name="flare", speed=fl["speed"], hdot=fl["hdot"], heading=0.0, exit_when=("on_ground",), next="rollout"),
        ModeSpec(name="rollout", speed=0.0, pitch=0.0, heading=0.0, exit_when=("speed_le", 0.5), next="stopped"),
        ModeSpec(name="stopped", speed=0.0, pitch=0.0, exit_when=("time_ge", 1e9)),
    ]
    ac = base.aircraft(ground=base.skid_gear())
    tr = trim_ground(ac, TrimCase("pad", mach=0.0, alt=0.0, fuel=m["fuel"], condition="ground"))
    assert tr.converged
    sim = Simulator(aircraft=ac, fcl=assemble_law(base), guidance=Guidance(modes),
                    nav_model=NavErrorModel.rtk_fixed(seed=11), stall_table=base.stall_table(),
                    db_ranges=base.db_ranges(), dt_plant=0.01, control_hz=100.0, ground_elev=0.0,
                    launch=base.launch_rail(), actuator_params=base.actuator_params(), fuel_flow=m["fuel_flow"])
    res = sim.run(tr, t_end=ROLLOUT_T_END, fingerprint="showcase-rollout")
    s, ph = res.signals, res.meta["phases"]
    assert res.meta["aborted"] is None and ph["stop_t"] is not None
    k_td, k_st = int(round(ph["touchdown_t"] / 0.01)), int(round(ph["stop_t"] / 0.01))
    rollout = s["pn"][k_st] - s["pn"][k_td]
    assert rollout == pytest.approx(m["rollout_m"], rel=ROLLOUT_REL), rollout
    assert "rollout_m" in doc["description"]


def _band_params():
    tables = (_raw()["law"]["gain_tables"] or {}).get("tables") or {}
    return [pytest.param(n, marks=pytest.mark.xfail(strict=True, reason=BAND_KNOWN_DEFECTS[n]))
            if n in BAND_KNOWN_DEFECTS else n for n in sorted(tables)]


def band_ratio_max(m, v, width) -> tuple:
    """선형 보간 표(끝 밖은 clip)의 폭 width 띠 안 |값| 최대/최소 비의 **정확한** 최댓값 — (비, 그 띠의 시작).

    구간 선형이라 띠 안의 최대·최소는 띠에 든 분할점이나 띠 양끝에서만 난다. 띠 시작 x0이 분할점을 지나거나 띠 끝 x0+width가
    분할점을 지날 때만 그 집합이 바뀌므로, x0 ∈ {분할점} ∪ {분할점 − width}(표 범위 안)만 보면 된다. 고정 간격 표본(예전
    0.0005)은 분할점이 표본 사이에 떨어지면 꼭대기를 놓친다 — 톱니 표에서 roll.ki 2.63을 2.49로 읽었다."""
    m = np.asarray(m, dtype=float)
    a = np.abs(np.asarray(v, dtype=float))
    best = (0.0, None)
    for x0 in sorted(set(m.tolist()) | {x - width for x in m.tolist() if x - width >= m[0]}):
        x1 = min(x0 + width, m[-1])
        ys = np.interp(np.concatenate(([x0, x1], m[(m >= x0) & (m <= x1)])), m, a)
        r = float(ys.max() / ys.min())
        if r > best[0]:
            best = (r, float(x0))
    return best


def test_띠_비는_분할점_사이에_떨어진_꼭대기도_잡는다():
    """띠 검사 자체의 검사 — 옛 출하 표(두 설계 고도의 톱니) roll.ki의 꼭대기 부근(M0.1974–0.2096 분할점 그대로)에서 고정 간격
    0.0005 표본은 M0.1977의 꼭대기를 건너뛰어 상한 안으로 읽었지만(그 표 전체에서 2.49) 실제 띠 비는 2.63이다."""
    m = [0.1974, 0.1977, 0.20045, 0.2035, 0.20655, 0.2096]
    v = [0.1431, 0.3085, 0.1351, 0.1273, 0.1199, 0.1128]
    r, x0 = band_ratio_max(m, v, SCHEDULE_BAND)
    assert x0 == pytest.approx(0.1977) and r == pytest.approx(0.3085 / float(np.interp(0.2077, m, v)))
    assert r > SCHEDULE_BAND_RATIO_MAX
    xs = np.arange(0.1970, m[-1] + 1e-12, 0.0005)  # 예전 표본 격자(표 머리 0.094에서 0.0005 간격 — 0.1975·0.198)
    assert not np.isclose(xs, 0.1977).any()
    # 단조 표는 양끝 비 그대로, 폭보다 짧은 표는 표 전체가 한 띠다
    assert band_ratio_max([0.1, 0.2], [1.0, 3.0], 0.01)[0] == pytest.approx(float(np.interp(0.11, [0.1, 0.2], [1.0, 3.0])))
    assert band_ratio_max([0.1, 0.105], [1.0, 2.0], 0.01) == (2.0, 0.1)


@pytest.mark.parametrize("name", _band_params())
def test_확정_게인_표에_좁은_마하_띠의_급변이_없다(doc, name):
    """마하 0.01 띠 안에서 게인 크기가 2.5배 넘게 바뀌지 않고, 0이 없고, 부호가 뒤집히지 않는다 — 자리마다, 띠 위치를
    연속으로 옮겨 가며 정확히(band_ratio_max).

    표 표현(점마다 튜닝한 게인이 곧 분할점 값)에서 걸리는 것은 셋이다. ① 튜닝이 성립하지 않은 점의 자리값 0 — 적합이 그
    표본을 빼기 전에는 저속·고받음각 점의 roll.k_rate가 0으로 박혀(꺼진 롤 댐퍼) 띠 비가 무한대였다. ② 1축 표의 톱니 — 설계
    고도를 0·3000 m 둘로 주던 때 두 줄의 점이 한 마하 축에 번갈아 놓여 같은 마하 근처에서 고도별 값이 섞였다(3000 m 값이
    q̄가 낮은 만큼 크다 — roll.ki 띠 비 2.63 @M0.1977로 상한 위였는데 0.0005 간격 표본 검사가 2.49로 읽어 통과했다). 설계
    격자를 한 줄로 두어(test_확정_게인_표는_한_설계_고도_줄의_스케줄이다) 출하 표의 띠 비 최대는 roll.ki 1.24(M0.21 — v1.70
    절점 7점 표. 해면 한 줄 표에서 1.29 @M0.094)다. ③ 튜닝 규칙이 갈리는 경계 — 한 고도 계열 안에서도 값이 뛴다(BAND_KNOWN_DEFECTS). 요 댐퍼 2차 패스가 목표에
    못 닿은 점에만 돌던 때 해면 M0.1263 0.93 → M0.1275 2.67로 뛰었다(띠 비 3.00 — 닿은 점에도 돌게 고친 뒤 1.23, 요 목표
    0.6에서 1.26). 다항 적합(차수 4 · 구간 4)은 가까운 매듭 사이가 출렁여 roll.kp가 M0.113–0.118(발진·플레어 속도)에서
    0.5 ↔ 8.8을 오갔다 — 이 역시 여기서 걸린다."""
    t = doc["law"]["gain_tables"]["tables"][name]
    m = np.asarray(t["axes"]["mach"], dtype=float)
    v = np.asarray(t["data"], dtype=float)
    assert np.all(v != 0.0), (name, "0인 분할점 — 튜닝이 성립하지 않은 점의 자리값이 표에 들어갔다")
    assert np.all(v > 0) or np.all(v < 0), (name, "부호가 바뀐다")
    ratio, x0 = band_ratio_max(m, v, SCHEDULE_BAND)
    assert ratio <= SCHEDULE_BAND_RATIO_MAX, (name, x0, ratio)


def test_띠_검사의_알려진_결함은_지금_표의_자리다(doc):
    """BAND_KNOWN_DEFECTS가 없는 자리를 들고 있으면 그 xfail은 아무것도 지키지 않는다 — 자리 이름이 표에 있어야 한다."""
    assert set(BAND_KNOWN_DEFECTS) <= set(doc["law"]["gain_tables"]["tables"])


def test_미션_연료_소모율이_BSFC_0_3_0_5_kg_kWh다(doc):
    """fuel_flow는 상수 소모율[kg/s] — 최대 축동력에서의 연료 소모로 읽어 BSFC를 되짚는다."""
    flow = doc["mission_template"]["sim"]["fuel_flow"]
    power_kw = doc["propulsion"]["params"]["power_max"] / 1000.0
    bsfc = flow * 3600.0 / power_kw
    assert BSFC_RANGE[0] <= bsfc <= BSFC_RANGE[1], bsfc


def test_설계_다이브_마하는_M_NO의_1_25배_이상이다(doc):
    st = doc["structural"]
    assert st["mach_d"] / st["mach_no"] >= MACH_D_OVER_NO - 1e-12, (st["mach_d"], st["mach_no"])


def test_EO_IR형은_플랜트가_다른_변형이다(base, eoir):
    assert eoir.plant_fingerprint != base.plant_fingerprint


def test_CD에는_수치_상수항이_정확히_하나다(doc):
    """공학 수정 시연(EO/IR 볼 ΔCD0)이 치환할 자리 — 입력 없는 수치 항이 하나여야 그 인덱스가 뜻을 갖는다."""
    const = [t for t in doc["aero"]["coefficients"]["CD"] if not t["inputs"]]
    assert len(const) == 1
    assert isinstance(const[0]["k"], float)


def test_EO_IR형_패치에는_CD_치환이_없다(doc):
    """시연이 CD0를 처음 넣는다 — 미리 들어 있으면 같은 값 저장이라 낡음 배지가 서지 않는다."""
    patch = next(v for v in doc["variants"] if v["id"] == "eoir")["patch"]
    cd = "/aero/coefficients/CD"
    # 그 자리 아래(…/CD/0/k)도, 그 자리를 통째로 덮는 윗자리(/aero 등)도 없어야 한다
    assert not [p for p in patch if p == cd or p.startswith(cd + "/") or cd.startswith(p + "/")]


# 쇼케이스 결함 창(web lib/showcase.js SHOWCASE_EVAL_POINTS)은 이 네 이름을 영향성 탭 평가 신호의 args.points로 보낸다 — 탭은
# 이름이 기본 격자에 없으면 실패하고(다른 점으로 조용히 돌지 않는다) 모델 부족 점은 보내지 않는다. 요구영역·기본 격자 명세·
# 이름 규칙이 바뀌어 이 점이 빠지거나 상태가 바뀌면 쇼케이스가 무대에서 깨진다 — 엔진 쪽에서 먼저 잡는다
SHOWCASE_EVAL_POINTS = ["M0.12_h200_f10", "M0.18_h200_f10", "M0.18_h3000_f10", "M0.12_h3000_f10"]


def test_쇼케이스_평가점_네_개가_기본_격자에_미계산으로_서펜타인_순서대로_있다(doc, base):
    from claw.opspace import NOT_RUN, base_grid, model_range_of, region_of

    grid = base_grid(region_of(doc), model_range_of(base))
    picked = [p for p in grid["points"] if p["name"] in SHOWCASE_EVAL_POINTS]
    # 이름이 유일해야 한다 — 같은 이름이 둘이면 평가 결과가 다른 점에 귀속된다
    assert sorted(p["name"] for p in picked) == sorted(SHOWCASE_EVAL_POINTS), [p["name"] for p in grid["points"]]
    assert [p["name"] for p in picked] == SHOWCASE_EVAL_POINTS, "서펜타인 순서(200 m 행 증가 → 3000 m 행 감소)"
    assert all(p["state"] == NOT_RUN for p in picked), [(p["name"], p["state"]) for p in picked]
