"""기체 프로파일 문서 검증·정규화 (02 §5.6).

문서는 JSON이고, 이 검증기를 통과한 문서만 build가 받는다. 오류는 **문서 안 경로**를 싣는다
(`/mass/m_empty: 양수여야 함`) — 웹 편집기가 그 칸을 짚는다.

규칙:
- 모르는 키는 거부한다 — 오타가 조용히 무시되면 "입력했는데 반영 안 된 값"이 된다
- null은 "없음"이다(허용된 자리만). 예제 값이나 레지스트리 기본값으로 채우지 않는다 —
  그래서 추진·작동기·SCAS·자동조종 파라미터는 **전부 명시**해야 한다
- 수치는 float로 정규화한다 — 저장본의 6과 6.0이 지문·응답 바이트를 가르지 않게
"""

import copy
import json
import math
import re

from claw.profile.errors import ProfileError
from claw.profile.patch import apply_patch, get_pointer

# v2 (v1.31): law.gain_tables(확정 게인 표 — 자동 설계 산출의 정본 되쓰기) 추가. 계산에 쓰이는
# 절이라 OPTIONAL_SECTIONS 방식(지문 밖·버전 불변)이 아니라 버전을 올렸다 — 예제 지문이 바뀌어
# 옛 결과·스냅숏 계보가 끊기고, v1 저장 문서는 다음 검증에서 거부된다(공개 데모는 volatile이라
# 영향 미미 — v1.17 마하 0 격자점 거부와 같은 정책)
# v3 (05 §11.13 이관 11·12단계): operating 절 폐지(운용 고도 = 요구영역 고도), trim 절을 해석 설정(solver — 플랜트 지문
# 밖)과 판정선(criteria.trim_margin)으로 가름, mass.loadings(탑재 구성 자리), mission_template.envelope.scan_* 폐지.
# v2 문서는 upgrade_document가 옮긴다(저장·가져오기 경로가 부른다 — validate_document는 v3만 받는다)
SCHEMA_VERSION = 3
MAX_VARIANTS = 64  # 형상 변형 상한 — 읽을 때마다 변형마다 재검증하므로 단일 워커를 물지 않게

SECTIONS = (
    "schema_version", "id", "name", "description", "is_example",
    "geometry", "aero", "stall", "mass", "propulsion", "actuator", "surfaces",
    "structural", "ground", "solver", "law", "mission_template", "display", "criteria", "tuning",
    "operating_region", "variants",
)
# 스키마 v1에 나중에 더한 **선택 절** — 문서에 없으면 null(없음)로 채운다. 버전을 올리는 대신 이렇게 한
# 이유: 이 절들은 계산에 쓰이지 않아 지문 밖인데(fingerprint.py), 버전을 올리면 버전 값이 지문에 들어가 옛
# 결과·설계 세션의 계보(스냅숏 지문)가 통째로 끊긴다. 계산에 쓰이는 절이 생기면 그때 버전을 올린다
OPTIONAL_SECTIONS = ("mission_template", "display", "criteria", "tuning", "operating_region")
# 평가 기준(합격선·권장선)과 튜닝 목표 — 이 설계 작업 단위(프로파일)의 모든 탭이 공유한다(기준 통합 ①, v1.51).
# 없음(null)이면 도구 기본값이고, 부분만 적으면 나머지는 기본값이다. 둘 다 **지문 밖**이다(fingerprint.py) — 기준을
# 바꿨다고 트림·게인 표가 낡지 않는다. 판정·결과가 어느 기준으로 났는지는 기준 지문 둘이 따로 말한다
# (pipeline/criteria.py judgement_fingerprint·targets_fingerprint). 형상 변형은 이 둘을 고칠 수 없다 — 기준은
# 형상 하나가 아니라 작업 단위 전체의 요구조건이다
# 요구 운용영역(operating_region)도 같다 — 성능을 확보해야 할 범위는 작업 단위의 요구조건이지 형상 하나의 값이 아니다
# (형상마다 날 수 있는 범위가 다른 것은 조건 상태 — 물리적 불가·모델 부족 — 가 말한다, 05 §11.2)
VARIANT_FORBIDDEN = ("criteria", "tuning", "operating_region")
# 요구 운용영역 기본 격자의 마하 점 수 상한 — 행마다 이 수 + 끝점 둘이다. 점 총수는 MAX_TEMPLATE_CASES가 막는다
MAX_REGION_MACH_POINTS = 50
# 미션 템플릿 격자의 케이스 상한 — 서버 스캔·영향성 격자 상한(MAX_SCAN_CASES·MAX_CASES)과 같은 자리.
# 간격 오타 하나로 수만 케이스가 되면 그 기체를 고른 모든 화면이 격자를 만들다 멈춘다
MAX_TEMPLATE_CASES = 200
# 엔벨로프 선도 고도(mission_template.envelope.alt)를 목록으로 줄 때의 개수 상한 — V-n 선도를 고도마다 한 장씩
# 겹쳐 그린다. 여섯 장이 넘으면 곡선이 서로를 가려 읽을 수 없다(화면 사정의 상한이지 물리 상한이 아니다)
MAX_ENVELOPE_ALTS = 6
# 표시 모델 형식 — 지금은 GLB 파일 하나다. 모델이 없는 기체는 절을 없음(null)으로 두고, 화면이 기준량에서 만든
# 도식을 그리며 그렇다고 말한다(06 §8)
DISPLAY_KINDS = ("model",)
# GLB 파일 이름 — 서버 `GET /api/world/model/{이름}`이 models/<모델>/<이름>.glb를 **이름으로** 찾는다. 경로 구분자·
# 상위 폴더를 받지 않는다: 이름이 곧 조회 키이고, 경로를 받으면 문서가 자산 폴더 밖을 가리킬 수 있다
DISPLAY_MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.glb")
AERO_FORMS = {
    "lift_drag": ("CL", "CD", "CY", "Cl", "Cm", "Cn"),
    "body": ("CX", "CY", "CZ", "Cl", "Cm", "Cn"),
}
TERM_INPUTS = ("alpha", "beta", "V", "mach", "phat", "qhat", "rhat", "de", "da", "dr")
# 형식·계수별로 더 받는 입력 — 양력·항력형 CD의 유도항력 항만 CL을 곱할 수 있다
TERM_EXTRA_INPUTS = {("lift_drag", "CD"): ("CL",)}
# 항의 k를 **표**로 줄 때 쓸 수 있는 축 — 공력 DB의 조건 축(01 §2.3). 무차원 각속도·V는 표 축이 아니라 곱하는
# 입력이고(동미계수), 고도는 입력이 아니라 표 축으로만 들어온다(계수에 고도를 곱할 일은 없다)
TABLE_AXES = ("alpha", "beta", "mach", "alt", "de", "da", "dr")
TABLE_POLICIES = ("clip", "linear", "error")  # tables/table.py 외삽 정책
MAX_TABLE_CELLS = 100_000  # 표 한 장의 칸 상한
# 문서 한 벌의 표 칸 합 상한 — 기본 문서 칸 × (1 + 형상 변형 수) + 변형이 넣는 표 칸. 한 장 상한만으로는 못 막는다:
# 저장소가 읽을 때마다 문서를 다시 검증하고 형상 변형마다 **문서 전체**를 다시 검증·지문하므로 칸이 변형 수만큼
# 곱해진다(실측: 10만 칸 표 10장 + 변형 16개 → 검증 7.6 s + 지문 11.6 s, 요청마다)
MAX_DOCUMENT_TABLE_CELLS = 400_000
# 계수 계산 한 번에 도는 표 모서리 합(표마다 2^축 수) 상한 — 시뮬·스캔이 계수를 스텝마다 부르므로 요청 한 번이
# CPU를 물지 않게(7축 표 60개 → 뷰어 401점 1.7 s). 항 수 상한도 같은 이유다
MAX_TABLE_CORNERS = 1024
MAX_TERMS_PER_COEF = 200
# 섭동 태그 → (허용 계수, 항에 반드시 있어야 할 입력). 태그가 없는 축은 흔들 수 없다
DISPERSION_TAGS = {"cmalpha": ("Cm", "alpha"), "cmq": ("Cm", "qhat")}
LAYOUTS = ("elevon4_rudder1",)  # [한계] 법칙 템플릿이 하나라 배치도 하나다
TEMPLATES = ("delta_elevon_v1",)
SCHEDULE_RULES = ("qbar_inverse",)
DE_TRIM_SOURCES = ("explicit", "derived")  # 트림 엘레본 표의 출처 — 손으로 넣음 / 도출 잡이 만듦
TABLE_EXTRAPOLATE = ("clip",)  # 문서 속 마하 표의 외삽 — α 리미터·할당 조회가 clip만 받는다
ACTUATOR_RESERVED = ("pos_lo", "pos_hi", "initial")  # 위치 한계는 surfaces, 초기값은 트림
SCAS_RESERVED = ("out_lo", "out_hi")  # 출력 한계는 surfaces에서 온다 (중복 정의 금지)
ISA_ALT_RANGE = (-5000.0, 20000.0)  # env/constants.py ISA_MIN_ALT·ISA_STRATO1_TOP_ALT
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _registry():
    # 레지스트리 등록은 패키지 import가 한다 — 모듈 로드 시점이 아니라 검증 시점에 끌어와
    # claw.fcl·claw.plant가 이 모듈을 import하게 되더라도 순환이 생기지 않게 한다
    import claw.fcl  # noqa: F401
    import claw.plant  # noqa: F401
    from claw.params.registry import REGISTRY

    return REGISTRY


def _fail(path, msg):
    raise ProfileError(path, msg)


def _keys(obj, path, keys):
    if not isinstance(obj, dict):
        _fail(path, "객체여야 함")
    for k in keys:
        if k not in obj:
            _fail(f"{path}/{k}", "필수 항목 누락")
    for k in obj:
        if k not in keys:
            _fail(f"{path}/{k}", f"모르는 항목 (허용: {', '.join(keys)})")


def _num(v, path, *, lo=None, hi=None, lo_open=False, hi_open=False, nullable=False):
    if v is None:
        if nullable:
            return None
        _fail(path, "수치가 필요함 (null 불가)")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _fail(path, f"수치여야 함: {v!r}")
    try:
        f = float(v)
    except OverflowError:
        _fail(path, f"수치 범위 밖: {v!r}")
    if not math.isfinite(f):
        _fail(path, f"유한값이어야 함: {v!r}")
    if lo is not None and (f <= lo if lo_open else f < lo):
        _fail(path, f"{'>' if lo_open else '≥'} {lo} 이어야 함: {f}")
    if hi is not None and (f >= hi if hi_open else f > hi):
        _fail(path, f"{'<' if hi_open else '≤'} {hi} 이어야 함: {f}")
    return f


def _text(v, path, *, min_len=0):
    if not isinstance(v, str) or len(v.strip()) < min_len:
        _fail(path, "문자열이어야 함" if min_len == 0 else "비어 있지 않은 문자열이어야 함")
    return v


def _choice(v, path, choices):
    if v not in choices:
        _fail(path, f"허용값 {list(choices)} 중 하나여야 함: {v!r}")
    return v


def _vec(v, path, n):
    if not isinstance(v, list) or len(v) != n:
        _fail(path, f"길이 {n} 수치 목록이어야 함")
    return [_num(x, f"{path}/{i}") for i, x in enumerate(v)]


def _range(v, path, *, nullable=False):
    if v is None and nullable:
        return None
    lo, hi = _vec(v, path, 2)
    if not lo < hi:
        _fail(path, f"하한 < 상한이어야 함: [{lo}, {hi}]")
    return [lo, hi]


def _increasing(v, path, *, min_len=2, lo=None, lo_open=False):
    if not isinstance(v, list) or len(v) < min_len:
        _fail(path, f"수치 {min_len}개 이상 목록이어야 함")
    out = [_num(x, f"{path}/{i}", lo=lo, lo_open=lo_open) for i, x in enumerate(v)]
    for i in range(1, len(out)):
        if not out[i] > out[i - 1]:
            _fail(f"{path}/{i}", "순증가(오름차순)여야 함")
    return out


def _table_mach(t, path, *, extrapolate):
    _keys(t, path, ("axes", "data", "extrapolate"))
    _keys(t["axes"], f"{path}/axes", ("mach",))
    # 마하 0·음수는 격자점으로 물리에 없다 — 오름차순이라 첫 점만 걸려도 전부 양수다
    axis = _increasing(t["axes"]["mach"], f"{path}/axes/mach", lo=0.0, lo_open=True)
    data = t["data"]
    if not isinstance(data, list) or len(data) != len(axis):
        _fail(f"{path}/data", f"축 길이 {len(axis)}와 같은 수치 목록이어야 함")
    return {
        "axes": {"mach": axis},
        "data": [_num(x, f"{path}/data/{i}") for i, x in enumerate(data)],
        "extrapolate": _choice(t["extrapolate"], f"{path}/extrapolate", extrapolate),
    }


def _registry_params(category, name, params, path, *, reserved=(), type_path=None):
    """레지스트리 컴포넌트 파라미터 — **전부 명시**(기본값 보충 없음), ParamDef가 판정.

    path는 파라미터 객체 자체의 경로다. type_path는 형식 이름이 틀렸을 때 짚을 자리.
    """
    from claw.params.param import ParamError
    from claw.params.registry import RegistryError

    reg = _registry()
    try:
        defs = [d for d in reg.param_defs(category, name) if d.name not in reserved]
    except (RegistryError, KeyError):
        _fail(type_path or path,
              f"등록되지 않은 {category} 형식: {name!r} (허용: {reg.names(category)})")
    _keys(params, path, tuple(d.name for d in defs))
    out = {}
    for d in defs:
        p = f"{path}/{d.name}"
        v = params[d.name]
        if isinstance(d.default, float) and isinstance(v, int) and not isinstance(v, bool):
            try:
                v = float(v)
            except OverflowError:
                _fail(p, f"수치 범위 밖: {v!r}")
        # ParamDef.validate는 범위만 보고 유한성은 안 본다 — NaN은 두 경계 비교를 모두 통과하고
        # inf는 상한 없는 자리를 통과한다. 그 값이 저장·지문까지 가면 시뮬이 NaN을 낸다
        if isinstance(v, float) and not math.isfinite(v):
            _fail(p, f"유한값이어야 함: {v!r}")
        if isinstance(v, list) and any(isinstance(x, float) and not math.isfinite(x) for x in v):
            _fail(p, "배열 원소는 유한값이어야 함")
        try:
            out[d.name] = d.validate(v)
        except ParamError as e:
            _fail(p, str(e))
    return out


def _component(v, path, category, *, reserved=()):
    _keys(v, path, ("type", "params"))
    t = v["type"]
    if not isinstance(t, str):
        _fail(f"{path}/type", "문자열이어야 함")
    return {"type": t, "params": _registry_params(category, t, v["params"], f"{path}/params",
                                                  reserved=reserved, type_path=f"{path}/type")}


def _nested(v, shape, path):
    if not shape:
        return _num(v, path)
    if not isinstance(v, list) or len(v) != shape[0]:
        _fail(path, f"길이 {shape[0]} 목록이어야 함 (축을 적은 순서대로 중첩)")
    return [_nested(x, shape[1:], f"{path}/{i}") for i, x in enumerate(v)]


def _aero_table(t, path):
    """공력 표 — {axes: {축: 순증가 격자}, data: 축을 적은 순서대로 중첩한 수치, extrapolate}.

    축 순서가 data 중첩 순서다 — JSON 객체의 키 순서를 그대로 쓴다(내보내기·가져오기가 순서를 지킨다)."""
    _keys(t, path, ("axes", "data", "extrapolate"))
    axes = t["axes"]
    if not isinstance(axes, dict) or not axes:
        _fail(f"{path}/axes", "축 이름 → 격자 목록 객체여야 함 (1축 이상)")
    out_axes = {}
    for name, grid in axes.items():
        if name not in TABLE_AXES:
            _fail(f"{path}/axes/{name}", f"허용 축 {list(TABLE_AXES)} 중 하나여야 함")
        out_axes[name] = _increasing(grid, f"{path}/axes/{name}")
    shape = tuple(len(g) for g in out_axes.values())
    cells = math.prod(shape)
    if cells > MAX_TABLE_CELLS:
        _fail(f"{path}/data", f"표 칸 {cells}개 — {MAX_TABLE_CELLS}개까지")
    return {
        "axes": out_axes,
        "data": _nested(t["data"], shape, f"{path}/data"),
        "extrapolate": _choice(t["extrapolate"], f"{path}/extrapolate", TABLE_POLICIES),
    }


def _term_k(v, path):
    """항의 k — 수치, 또는 {"table": 공력 표}."""
    if isinstance(v, dict):
        _keys(v, path, ("table",))
        return {"table": _aero_table(v["table"], f"{path}/table")}
    return _num(v, path)


def _terms(v, path, *, coef, form):
    if not isinstance(v, list):
        _fail(path, "항 목록이어야 함")
    if len(v) > MAX_TERMS_PER_COEF:
        _fail(path, f"항 {len(v)}개 — 계수마다 {MAX_TERMS_PER_COEF}개까지")
    allowed = TERM_INPUTS + TERM_EXTRA_INPUTS.get((form, coef), ())
    out = []
    for i, t in enumerate(v):
        p = f"{path}/{i}"
        _keys(t, p, ("k", "inputs", "dispersion"))
        k = _term_k(t["k"], f"{p}/k")
        inputs = t["inputs"]
        if not isinstance(inputs, list):
            _fail(f"{p}/inputs", "입력 이름 목록이어야 함")
        for j, name in enumerate(inputs):
            if not isinstance(name, str) or name not in allowed:
                _fail(f"{p}/inputs/{j}", f"허용 입력 {list(allowed)} 중 하나여야 함: {name!r}")
        tag = t["dispersion"]
        if tag is not None:
            if not isinstance(tag, str) or tag not in DISPERSION_TAGS:
                _fail(f"{p}/dispersion", f"허용 섭동 태그 {list(DISPERSION_TAGS)} 또는 null: {tag!r}")
            coef_ok, needed = DISPERSION_TAGS[tag]
            if coef != coef_ok or needed not in inputs:
                _fail(f"{p}/dispersion",
                      f"{tag} 태그는 {coef_ok} 계수의 {needed} 입력 항에만 붙는다")
        out.append({"k": k, "inputs": list(inputs), "dispersion": tag})
    return out


def _geometry(g, p):
    _keys(g, p, ("S", "cbar", "b"))
    return {k: _num(g[k], f"{p}/{k}", lo=0.0, lo_open=True) for k in ("S", "cbar", "b")}


def _aero(a, p):
    _keys(a, p, ("form", "coefficients", "db_ranges"))
    form = _choice(a["form"], f"{p}/form", tuple(AERO_FORMS))
    names = AERO_FORMS[form]
    _keys(a["coefficients"], f"{p}/coefficients", names)
    coefs = {n: _terms(a["coefficients"][n], f"{p}/coefficients/{n}", coef=n, form=form)
             for n in names}
    corners = sum(2 ** len(t["k"]["table"]["axes"]) for terms in coefs.values() for t in terms
                  if isinstance(t["k"], dict))
    if corners > MAX_TABLE_CORNERS:
        _fail(f"{p}/coefficients", f"표 항 모서리 합 {corners}개(표마다 2^축 수) — {MAX_TABLE_CORNERS}개까지."
                                   " 계수를 부를 때마다 이만큼 보간한다")
    _keys(a["db_ranges"], f"{p}/db_ranges", ("alpha", "beta", "mach"))
    ranges = {k: _range(a["db_ranges"][k], f"{p}/db_ranges/{k}", nullable=True)
              for k in ("alpha", "beta", "mach")}
    return {"form": form, "coefficients": coefs, "db_ranges": ranges}


def _stall(s, p):
    _keys(s, p, ("table", "neg_alpha_ratio"))
    return {
        # α 리미터가 1축(mach)·clip만 받는다 (fcl/limiter.py) — 문서도 같은 제약
        "table": _table_mach(s["table"], f"{p}/table", extrapolate=TABLE_EXTRAPOLATE),
        "neg_alpha_ratio": _num(s["neg_alpha_ratio"], f"{p}/neg_alpha_ratio",
                                lo=0.0, lo_open=True, hi=1.0),
    }


def _mat3(v, path):
    if not isinstance(v, list) or len(v) != 3:
        _fail(path, "3×3 행렬이어야 함")
    rows = [_vec(r, f"{path}/{i}", 3) for i, r in enumerate(v)]
    for i in range(3):
        if not rows[i][i] > 0.0:
            _fail(f"{path}/{i}/{i}", "관성 대각은 양수여야 함")
        for j in range(i + 1, 3):
            if rows[i][j] != rows[j][i]:
                _fail(f"{path}/{i}/{j}", "관성 행렬은 대칭이어야 함")
    return rows


def _loadings(v, p):
    """탑재 구성(이산) — null 또는 [{id, name, payload_kg ≥ 0, cg: [x,y,z] | null}] (v3, 05 §11.3 · 05 §11.13 11단계).

    **자리만 있다** — 계산은 기본 질량 모델(탑재 없음 = 대표 구성)로 한다. 플랜트는 연료로 질량·관성만 바꾸고 CG를
    동역학에 넣지 않으므로(02 §5.6 [한계]) 구성을 적어도 결과가 달라지지 않는다. 그래서 적힌 구성이 있으면 조건 판정이
    `mass_condition`으로 그렇다고 말하고(opspace/verdict.py) CG 영향 검증은 통과로 세지 않는다. 트림이 보지 않으므로 플랜트
    지문 밖이고(fingerprint.plant_fingerprint가 뺀다 — 구성을 적었다고 δe_trim 표가 낡지 않는다) 계보 지문 안이다."""
    if v is None:
        return None
    if not isinstance(v, list):
        _fail(p, "탑재 구성 목록이어야 함 (없으면 null)")
    out, seen = [], set()
    for i, item in enumerate(v):
        ip = f"{p}/{i}"
        _keys(item, ip, ("id", "name", "payload_kg", "cg"))
        lid = item["id"]
        if not isinstance(lid, str) or not _ID.fullmatch(lid):
            _fail(f"{ip}/id", "영문·숫자·_·- 1~64자여야 함")
        if lid in seen:
            _fail(f"{ip}/id", f"탑재 구성 id 중복: {lid!r}")
        seen.add(lid)
        out.append({"id": lid, "name": _text(item["name"], f"{ip}/name", min_len=1),
                    "payload_kg": _num(item["payload_kg"], f"{ip}/payload_kg", lo=0.0),
                    "cg": None if item["cg"] is None else _vec(item["cg"], f"{ip}/cg", 3)})
    return out


def _mass(m, p):
    _keys(m, p, ("m_empty", "fuel_max", "J_empty", "J_full", "cg_empty", "cg_full", "loadings"))
    return {
        "m_empty": _num(m["m_empty"], f"{p}/m_empty", lo=0.0, lo_open=True),
        "fuel_max": _num(m["fuel_max"], f"{p}/fuel_max", lo=0.0),
        "J_empty": _mat3(m["J_empty"], f"{p}/J_empty"),
        "J_full": _mat3(m["J_full"], f"{p}/J_full"),
        "cg_empty": _vec(m["cg_empty"], f"{p}/cg_empty", 3),
        "cg_full": _vec(m["cg_full"], f"{p}/cg_full", 3),
        "loadings": _loadings(m["loadings"], f"{p}/loadings"),
    }


def _surfaces(s, p):
    _keys(s, p, ("layout", "elevon", "rudder"))
    out = {
        "layout": _choice(s["layout"], f"{p}/layout", LAYOUTS),
        "elevon": _range(s["elevon"], f"{p}/elevon"),
        "rudder": _range(s["rudder"], f"{p}/rudder"),
    }
    for k in ("elevon", "rudder"):
        lo, hi = out[k]
        # 트림은 중립에서 탐색을 시작하고 소모율은 부호 쪽 한계로 나눈다 — 0이 범위 끝이면 0/0이 된다
        if not lo < 0.0 < hi:
            _fail(f"{p}/{k}", f"타면 한계는 중립(0)을 사이에 둬야 함: [{lo}, {hi}]")
    return out


def _structural(s, p):
    keys = ("n_limit_pos", "n_limit_neg", "safety_factor", "mach_no", "mach_d", "q_max",
            "n_x_launch")
    _keys(s, p, keys)
    out = {
        "n_limit_pos": _num(s["n_limit_pos"], f"{p}/n_limit_pos", lo=0.0, lo_open=True),
        "n_limit_neg": _num(s["n_limit_neg"], f"{p}/n_limit_neg", hi=0.0, hi_open=True),
        "safety_factor": _num(s["safety_factor"], f"{p}/safety_factor", lo=1.0),
        "mach_no": _num(s["mach_no"], f"{p}/mach_no", lo=0.0, lo_open=True),
        "mach_d": _num(s["mach_d"], f"{p}/mach_d", lo=0.0, lo_open=True),
        "q_max": _num(s["q_max"], f"{p}/q_max", lo=0.0, lo_open=True, nullable=True),
        "n_x_launch": _num(s["n_x_launch"], f"{p}/n_x_launch", lo=0.0, lo_open=True,
                           nullable=True),
    }
    if not out["mach_no"] <= out["mach_d"]:
        _fail(f"{p}/mach_d", f"M_NO ≤ M_D 서열 위반: {out['mach_no']} > {out['mach_d']}")
    return out


def _ground(g, p):
    _keys(g, p, ("skid", "rail"))
    skid = g["skid"]
    if skid is not None:
        _keys(skid, f"{p}/skid", ("contacts", "k", "c", "mu"))
        contacts = skid["contacts"]
        if not isinstance(contacts, list) or not contacts:
            _fail(f"{p}/skid/contacts", "접촉점 [x,y,z] 1개 이상 목록이어야 함")
        skid = {
            "contacts": [_vec(r, f"{p}/skid/contacts/{i}", 3) for i, r in enumerate(contacts)],
            "k": _num(skid["k"], f"{p}/skid/k", lo=0.0, lo_open=True),
            "c": _num(skid["c"], f"{p}/skid/c", lo=0.0),
            "mu": _num(skid["mu"], f"{p}/skid/mu", lo=0.0),
        }
    rail = g["rail"]
    if rail is not None:
        _keys(rail, f"{p}/rail", ("length", "elev_angle", "exit_speed", "origin_height"))
        rail = {
            "length": _num(rail["length"], f"{p}/rail/length", lo=0.0, lo_open=True),
            "elev_angle": _num(rail["elev_angle"], f"{p}/rail/elev_angle",
                               lo=-0.5 * math.pi, hi=0.5 * math.pi, lo_open=True, hi_open=True),
            "exit_speed": _num(rail["exit_speed"], f"{p}/rail/exit_speed", lo=0.0, lo_open=True),
            "origin_height": _num(rail["origin_height"], f"{p}/rail/origin_height", lo=0.0),
        }
    return {"skid": skid, "rail": rail}


def _solver(t, p):
    """해석 설정(v3) — 트림 풀이의 받음각 탐색 범위와 수렴 잔차 허용치. **기체가 아니라 풀이 방법**이라 플랜트 지문 밖이고
    (fingerprint.PLANT_SECTIONS) 계보 지문 안이다 — 바꾸면 트림 결과가 낡는다(05 §11.8 「트림 설정 → 그 키만 재계산 ·
    결과 낡음」: 트림 저장 키 = BuiltProfile.trim_fingerprint, δe_trim 도출은 solver 기록을 대조한다). 판정선(포화 등고선·
    트림 α 여유)은 여기가 아니라 기준 criteria.trim_margin이다(이관 12단계)."""
    _keys(t, p, ("trim_alpha_bounds", "resid_tol"))
    return {
        "trim_alpha_bounds": _range(t["trim_alpha_bounds"], f"{p}/trim_alpha_bounds"),
        "resid_tol": _num(t["resid_tol"], f"{p}/resid_tol", lo=0.0, lo_open=True),
    }


def _schedulable_slots():
    from claw.fcl.graphs import SCHEDULABLE

    return SCHEDULABLE


def _law(law, p):
    if isinstance(law, dict):
        law = {"gain_tables": None, **law}  # v2에 더한 절 — 없으면 없음(null), 최상위 선택 절과 같은 규약
    _keys(law, p, ("template", "alpha_margin", "filter_tau", "design", "schedule", "alloc", "gain_tables"))
    out = {
        "template": _choice(law["template"], f"{p}/template", TEMPLATES),
        "alpha_margin": _num(law["alpha_margin"], f"{p}/alpha_margin", lo=0.0),
        "filter_tau": _num(law["filter_tau"], f"{p}/filter_tau", lo=0.0),
    }
    design = law["design"]
    if design is not None:
        dp = f"{p}/design"
        _keys(design, dp, ("scas", "autopilot", "k_diff_thr", "provenance"))
        _keys(design["scas"], f"{dp}/scas", ("pitch", "roll", "yaw"))
        design = {
            "scas": {ax: _registry_params("fcl", "ScasAxis", design["scas"][ax],
                                          f"{dp}/scas/{ax}", reserved=SCAS_RESERVED)
                     for ax in ("pitch", "roll", "yaw")},
            "autopilot": _registry_params("fcl", "Autopilot", design["autopilot"],
                                          f"{dp}/autopilot"),
            "k_diff_thr": _num(design["k_diff_thr"], f"{dp}/k_diff_thr"),
            "provenance": copy.deepcopy(design["provenance"]),
        }
    out["design"] = design
    sched = law["schedule"]
    if sched is not None:
        sp = f"{p}/schedule"
        if design is None:
            _fail(sp, "게인 스케줄은 설계 게인(design) 없이 둘 수 없음")
        _keys(sched, sp, ("rule", "m_design", "mach_grid", "caps", "scheduled"))
        slots = _schedulable_slots()
        _keys(sched["caps"], f"{sp}/caps", ("default", "by_group"))
        by_group = sched["caps"]["by_group"]
        if not isinstance(by_group, dict):
            _fail(f"{sp}/caps/by_group", "객체여야 함")
        for g in by_group:
            if g not in slots:
                _fail(f"{sp}/caps/by_group/{g}", f"스케줄 그룹 {list(slots)} 중 하나여야 함")
        scheduled = sched["scheduled"]
        names = [f"{g}.{k}" for g, ks in slots.items() for k in ks]
        if not isinstance(scheduled, list) or not all(isinstance(n, str) for n in scheduled) \
                or len(set(scheduled)) != len(scheduled):
            _fail(f"{sp}/scheduled", "중복 없는 자리 이름(문자열) 목록이어야 함")
        for i, n in enumerate(scheduled):
            if n not in names:
                _fail(f"{sp}/scheduled/{i}", f"스케줄 불가 자리: {n!r}")
        sched = {
            "rule": _choice(sched["rule"], f"{sp}/rule", SCHEDULE_RULES),
            "m_design": _num(sched["m_design"], f"{sp}/m_design", lo=0.0, lo_open=True),
            # 스케줄은 (M_design/M)²을 계산한다 — 격자에 0이 있으면 inf가 조용히 배율 상한으로 잘린다
            "mach_grid": _increasing(sched["mach_grid"], f"{sp}/mach_grid", lo=0.0, lo_open=True),
            "caps": {
                "default": _num(sched["caps"]["default"], f"{sp}/caps/default",
                                lo=0.0, lo_open=True),
                "by_group": {g: _num(v, f"{sp}/caps/by_group/{g}", lo=0.0, lo_open=True)
                             for g, v in by_group.items()},
            },
            "scheduled": list(scheduled),
        }
    out["schedule"] = sched
    # 확정 게인 표(v2) — 자동 설계 산출을 정본에 반영한 마하별 표. 있으면 조립이 규칙 스케줄 대신
    # 이 표를 쓴다(build.confirmed_gain_tables). 낡음 판정(반영 뒤 문서 변경)은 조립이 한다 —
    # 스키마는 모양만 본다
    gt = law["gain_tables"]
    if gt is not None:
        gp = f"{p}/gain_tables"
        if design is None:
            _fail(gp, "확정 게인 표는 설계 게인(design) 없이 둘 수 없음 — 표는 설계의 산출물이다")
        _keys(gt, gp, ("tables", "provenance"))
        tables = gt["tables"]
        if not isinstance(tables, dict) or not tables:
            _fail(f"{gp}/tables", "자리 이름 → 마하 표의 비어 있지 않은 객체여야 함")
        slots = _schedulable_slots()
        names = [f"{g}.{k}" for g, ks in slots.items() for k in ks]
        out_tables = {}
        for n in tables:
            if n not in names:
                _fail(f"{gp}/tables/{n}", f"스케줄 불가 자리: {n!r}")
            # 외삽 금지 원칙 — GainSchedule이 clip만 받는다(fcl/schedule.py)
            out_tables[n] = _table_mach(tables[n], f"{gp}/tables/{n}", extrapolate=("clip",))
        gt = {"tables": out_tables, "provenance": copy.deepcopy(gt["provenance"])}
    out["gain_tables"] = gt
    alloc = law["alloc"]
    if alloc is not None:
        ap = f"{p}/alloc"
        _keys(alloc, ap, ("resv_frac", "de_trim"))
        de_trim = alloc["de_trim"]
        if de_trim is not None:
            _keys(de_trim, f"{ap}/de_trim", ("source", "table", "provenance"))
            de_trim = {
                "source": _choice(de_trim["source"], f"{ap}/de_trim/source", DE_TRIM_SOURCES),
                "table": _table_mach(de_trim["table"], f"{ap}/de_trim/table",
                                     extrapolate=TABLE_EXTRAPOLATE),
                "provenance": copy.deepcopy(de_trim["provenance"]),
            }
        alloc = {
            "resv_frac": _num(alloc["resv_frac"], f"{ap}/resv_frac", lo=0.0, lo_open=True, hi=1.0),
            "de_trim": de_trim,
        }
    out["alloc"] = alloc
    return out


def _span(v, path, *, lo=None):
    _keys(v, path, ("from", "to", "step"))
    start = _num(v["from"], f"{path}/from", lo=lo)
    end = _num(v["to"], f"{path}/to", lo=lo)
    if not start <= end:
        _fail(f"{path}/to", f"시작 ≤ 끝이어야 함: {start} > {end}")
    return {"from": start, "to": end, "step": _num(v["step"], f"{path}/step", lo=0.0, lo_open=True)}


def _numlist(v, path, *, lo=None, hi=None):
    if not isinstance(v, list) or not v:
        _fail(path, "수치 1개 이상 목록이어야 함")
    return [_num(x, f"{path}/{i}", lo=lo, hi=hi) for i, x in enumerate(v)]


def _num_or_list(v, path, *, lo=None, hi=None, max_items):
    """수치 하나 또는 수치 1~max_items개 목록 — 받은 모양 그대로 정규화한다(수치는 float, 목록은 float 목록).
    한 개짜리 목록을 수치로 바꾸지 않는다 — 저장본이 편집 전후로 모양을 바꾸면 안 한 변경이 생긴다."""
    if isinstance(v, list):
        if not 1 <= len(v) <= max_items:
            _fail(path, f"수치 하나 또는 수치 1~{max_items}개 목록이어야 함: {len(v)}개")
        return [_num(x, f"{path}/{i}", lo=lo, hi=hi) for i, x in enumerate(v)]
    return _num(v, path, lo=lo, hi=hi)


def _mission_template(t, p):
    """미션 시나리오 기본값 — **계산에 쓰이지 않는다.** 웹 폼(트림·마진 맵·영향성 격자, 엔벨로프, 시뮬
    미션)의 초기값이고, 결과는 실제로 보낸 요청을 싣는다. 그래서 지문 밖이다. 경로·활주로 같은 장소 값은
    여기 없다(웹 lib/site.js) — 기체의 성능에 맞춘 값(속도·상승각·고도·연료·미끄럼 거리)만 있다."""
    if t is None:
        return None
    lo, hi = ISA_ALT_RANGE
    _keys(t, p, ("trim_grid", "envelope", "sim"))
    g, e, s = t["trim_grid"], t["envelope"], t["sim"]
    gp, ep, sp = f"{p}/trim_grid", f"{p}/envelope", f"{p}/sim"
    _keys(g, gp, ("mach", "alt", "fuel"))
    _keys(e, ep, ("alt", "fuel"))
    _keys(s, sp, ("fuel", "fuel_flow", "t_end", "accept_radius", "climb", "cruise", "approach", "flare",
                  "rollout_m"))
    for k, keys in (("climb", ("speed", "pitch", "exit_alt")), ("cruise", ("speed", "alt")),
                    ("approach", ("speed", "hdot", "exit_alt")), ("flare", ("speed", "hdot"))):
        _keys(s[k], f"{sp}/{k}", keys)

    def speed(k):
        return _num(s[k]["speed"], f"{sp}/{k}/speed", lo=0.0, lo_open=True)

    def points(span, path):
        # 나누기부터 막는다 — 간격 1e-310이면 비율이 inf라 floor가 OverflowError(500)를 낸다
        ratio = (span["to"] - span["from"]) / span["step"]
        if not math.isfinite(ratio) or ratio > MAX_TEMPLATE_CASES:
            _fail(path, f"격자 점이 너무 많다 — 케이스 {MAX_TEMPLATE_CASES}개까지 (간격·범위 확인)")
        return int(math.floor(ratio + 1e-9)) + 1

    trim_grid = {
        "mach": _span(g["mach"], f"{gp}/mach", lo=0.0),
        "alt": _numlist(g["alt"], f"{gp}/alt", lo=lo, hi=hi),
        "fuel": _numlist(g["fuel"], f"{gp}/fuel", lo=0.0),
    }
    n = points(trim_grid["mach"], gp) * len(trim_grid["alt"]) * len(trim_grid["fuel"])
    if n > MAX_TEMPLATE_CASES:
        _fail(gp, f"격자 케이스 {n}개 — {MAX_TEMPLATE_CASES}개까지 (간격·목록 확인)")
    envelope = {
        # 선도 고도 — 하나(종전) 또는 여럿(V-n 다중 고도 선도). 웹 엔벨로프 폼의 초기값이다
        "alt": _num_or_list(e["alt"], f"{ep}/alt", lo=lo, hi=hi, max_items=MAX_ENVELOPE_ALTS),
        "fuel": _num(e["fuel"], f"{ep}/fuel", lo=0.0),
    }

    return {
        "trim_grid": trim_grid,
        "envelope": envelope,
        "sim": {
            "fuel": _num(s["fuel"], f"{sp}/fuel", lo=0.0),
            "fuel_flow": _num(s["fuel_flow"], f"{sp}/fuel_flow", lo=0.0),
            "t_end": _num(s["t_end"], f"{sp}/t_end", lo=0.0, lo_open=True),
            "accept_radius": _num(s["accept_radius"], f"{sp}/accept_radius", lo=0.0, lo_open=True),
            "climb": {"speed": speed("climb"),
                      "pitch": _num(s["climb"]["pitch"], f"{sp}/climb/pitch", lo=-0.5 * math.pi,
                                    hi=0.5 * math.pi, lo_open=True, hi_open=True),
                      "exit_alt": _num(s["climb"]["exit_alt"], f"{sp}/climb/exit_alt", lo=lo, hi=hi)},
            "cruise": {"speed": speed("cruise"),
                       "alt": _num(s["cruise"]["alt"], f"{sp}/cruise/alt", lo=lo, hi=hi)},
            "approach": {"speed": speed("approach"),
                         "hdot": _num(s["approach"]["hdot"], f"{sp}/approach/hdot", hi=0.0, hi_open=True),
                         "exit_alt": _num(s["approach"]["exit_alt"], f"{sp}/approach/exit_alt", lo=0.0)},
            "flare": {"speed": speed("flare"),
                      "hdot": _num(s["flare"]["hdot"], f"{sp}/flare/hdot", hi=0.0, hi_open=True)},
            "rollout_m": _num(s["rollout_m"], f"{sp}/rollout_m", lo=0.0, lo_open=True, nullable=True),
        },
    }


def _operating_region(r, p):
    """요구 운용영역 (05 §11.2) — **성능을 확보해야 할 범위**. 계산할 점 목록(mission_template.trim_grid)이 아니다.

    기본 범위(마하·고도·연료 [최솟값, 최댓값]) + 선택적 경계표(연료 층마다 고도 행 [alt, mach_lo, mach_hi] —
    행 사이·층 사이 선형 보간, 표가 덮지 않는 조건은 「요구 미정의」) + 기본 격자 명세(마하 점 수 · 고도 목록 ·
    연료 목록 — 05 §11.11). 연료는 kg다. 모델 범위(공력 DB · 연료 만재)를 넘어도 거부하지 않는다 — 넘친 부분은
    「모델 부족」 상태로 남는다(요구를 모델에 맞춰 줄이지 않는다). 절이 없으면(null) 화면이 trim_grid에서 만든
    초안을 「미확정」으로 보인다(claw.opspace.region). 계산 입력이 아니라 지문 밖이다(fingerprint.py)."""
    if r is None:
        return None
    lo_alt, hi_alt = ISA_ALT_RANGE
    _keys(r, p, ("mach", "alt", "fuel", "boundary", "base_grid"))

    def pair(v, path, *, lo=None, hi=None, lo_open=False, strict):
        if not isinstance(v, list) or len(v) != 2:
            _fail(path, "[최솟값, 최댓값] 두 수치여야 함")
        a = _num(v[0], f"{path}/0", lo=lo, hi=hi, lo_open=lo_open)
        b = _num(v[1], f"{path}/1", lo=lo, hi=hi, lo_open=lo_open)
        if not (a < b if strict else a <= b):
            _fail(f"{path}/1", f"최솟값 {'<' if strict else '≤'} 최댓값이어야 함: [{a}, {b}]")
        return [a, b]

    mach = pair(r["mach"], f"{p}/mach", lo=0.0, lo_open=True, strict=True)
    alt = pair(r["alt"], f"{p}/alt", lo=lo_alt, hi=hi_alt, strict=False)
    fuel = pair(r["fuel"], f"{p}/fuel", lo=0.0, strict=False)

    def inside(v, span, path, what):
        if not span[0] - 1e-9 <= v <= span[1] + 1e-9:
            _fail(path, f"{what} {v}이 기본 범위 [{span[0]}, {span[1]}] 밖 — 경계표·격자는 기본 범위 안에 둔다")
        return v

    boundary = r["boundary"]
    if boundary is not None:
        bp = f"{p}/boundary"
        if not isinstance(boundary, list) or not boundary:
            _fail(bp, "연료 층 1개 이상 목록이어야 함 (경계표가 없으면 null)")
        layers, seen = [], set()
        for i, layer in enumerate(boundary):
            lp = f"{bp}/{i}"
            _keys(layer, lp, ("fuel", "rows"))
            f = inside(_num(layer["fuel"], f"{lp}/fuel", lo=0.0), fuel, f"{lp}/fuel", "연료 층")
            if f in seen:
                _fail(f"{lp}/fuel", f"연료 층 {f}이 두 번 있다")
            seen.add(f)
            rows = layer["rows"]
            if not isinstance(rows, list) or not rows:
                _fail(f"{lp}/rows", "고도 행 [alt, mach_lo, mach_hi] 1개 이상이어야 함")
            out_rows, alts_seen = [], set()
            for j, row in enumerate(rows):
                rp = f"{lp}/rows/{j}"
                if not isinstance(row, list) or len(row) != 3:
                    _fail(rp, "[고도, 마하 하한, 마하 상한] 세 수치여야 함")
                a = inside(_num(row[0], f"{rp}/0", lo=lo_alt, hi=hi_alt), alt, f"{rp}/0", "고도")
                m_lo = inside(_num(row[1], f"{rp}/1", lo=0.0, lo_open=True), mach, f"{rp}/1", "마하 하한")
                m_hi = inside(_num(row[2], f"{rp}/2", lo=0.0, lo_open=True), mach, f"{rp}/2", "마하 상한")
                if not m_lo < m_hi:
                    _fail(f"{rp}/2", f"마하 하한 < 상한이어야 함: {m_lo} ≥ {m_hi}")
                if a in alts_seen:
                    _fail(f"{rp}/0", f"고도 행 {a}이 두 번 있다")
                alts_seen.add(a)
                out_rows.append([a, m_lo, m_hi])
            layers.append({"fuel": f, "rows": out_rows})
        boundary = layers

    g = r["base_grid"]
    gp = f"{p}/base_grid"
    _keys(g, gp, ("n_mach", "alts", "fuels"))
    n = g["n_mach"]
    if isinstance(n, bool) or not isinstance(n, int) or not 2 <= n <= MAX_REGION_MACH_POINTS:
        _fail(f"{gp}/n_mach", f"2~{MAX_REGION_MACH_POINTS} 정수여야 함: {n!r}")
    alts = [inside(a, alt, f"{gp}/alts/{i}", "고도")
            for i, a in enumerate(_numlist(g["alts"], f"{gp}/alts", lo=lo_alt, hi=hi_alt))]
    fuels = [inside(f, fuel, f"{gp}/fuels/{i}", "연료")
             for i, f in enumerate(_numlist(g["fuels"], f"{gp}/fuels", lo=0.0))]
    for key, vals in (("alts", alts), ("fuels", fuels)):
        # 같은 값이 두 번이면 같은 이름의 케이스가 두 번 생긴다(이름 = 케이스 매핑 키)
        if len(set(vals)) != len(vals):
            _fail(f"{gp}/{key}", f"같은 값이 두 번 있다: {vals}")
    if (n + 2) * len(alts) * len(fuels) > MAX_TEMPLATE_CASES:
        _fail(gp, f"기본 격자가 최대 {(n + 2) * len(alts) * len(fuels)}점 — {MAX_TEMPLATE_CASES}점까지 (마하 점 수·목록 확인)")
    return {"mach": mach, "alt": alt, "fuel": fuel, "boundary": boundary,
            "base_grid": {"n_mach": n, "alts": alts, "fuels": fuels}}


def _body(d, *, with_variants):
    top = SECTIONS if with_variants else tuple(k for k in SECTIONS if k != "variants")
    if isinstance(d, dict):
        d = {**{k: None for k in OPTIONAL_SECTIONS}, **d}  # 선택 절이 없으면 없음(null)
        # 버전부터 본다 — 옛 문서가 「/solver 필수 항목 누락」 같은 절 오류로 보이지 않게(옛 버전은 업그레이더 몫이다)
        sv = d.get("schema_version")
        if isinstance(sv, bool) or sv != SCHEMA_VERSION:
            _fail("/schema_version", f"지원 스키마 버전은 {SCHEMA_VERSION}: {sv!r}"
                  + (" — v2 문서는 upgrade_document로 옮긴다" if sv == 2 and not isinstance(sv, bool) else ""))
    _keys(d, "", top)
    if not isinstance(d["id"], str) or not _ID.fullmatch(d["id"]):
        _fail("/id", "영문·숫자·_·- 1~64자여야 함")
    if not isinstance(d["is_example"], bool):
        _fail("/is_example", "true/false여야 함")
    return {
        "schema_version": SCHEMA_VERSION,
        "id": d["id"],
        "name": _text(d["name"], "/name", min_len=1),
        "description": _text(d["description"], "/description"),
        "is_example": d["is_example"],
        "geometry": _geometry(d["geometry"], "/geometry"),
        "aero": _aero(d["aero"], "/aero"),
        "stall": _stall(d["stall"], "/stall"),
        "mass": _mass(d["mass"], "/mass"),
        "propulsion": _component(d["propulsion"], "/propulsion", "propulsion"),
        "actuator": _component(d["actuator"], "/actuator", "actuator",
                               reserved=ACTUATOR_RESERVED),
        "surfaces": _surfaces(d["surfaces"], "/surfaces"),
        "structural": _structural(d["structural"], "/structural"),
        "ground": _ground(d["ground"], "/ground"),
        "solver": _solver(d["solver"], "/solver"),
        "law": _law(d["law"], "/law"),
        "mission_template": _mission_template(d["mission_template"], "/mission_template"),
        "display": _display(d["display"], "/display"),
        "criteria": _criteria(d["criteria"], "/criteria"),
        "tuning": _tuning(d["tuning"], "/tuning"),
        "operating_region": _operating_region(d["operating_region"], "/operating_region"),
    }


def _criteria_value(v, default, path):
    """기준 칸 하나의 형식 — 기본값의 형식을 따른다. 형식이 틀린 값을 저장하면 저장은 되고 평가 때(한계와의 비교에서)
    TypeError로 터진다(문자열 "10"이 RMS 한계가 되는 식). 수치는 float로(정수 칸은 int로) 정규화한다."""
    def num(x, p_):
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            _fail(p_, "수치여야 함")
        try:
            f = float(x)
        except OverflowError:  # JSON의 임의 정밀도 정수 — 변환에서 500이 나지 않게
            _fail(p_, "double 범위를 넘는 수치")
        if not math.isfinite(f):  # 판정선이 NaN이면 모든 비교가 거짓이라 조용한 허위 합격이 된다
            _fail(p_, "유한한 수치여야 함")
        return f

    if isinstance(default, bool):
        if not isinstance(v, bool):
            _fail(path, "true/false여야 함")
        return v
    if isinstance(default, int):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v):
            _fail(path, "정수여야 함")
        return int(v)
    if isinstance(default, float):
        return num(v, path)
    if isinstance(default, str):
        if not isinstance(v, str):
            _fail(path, "문자열이어야 함")
        return v
    if isinstance(default, dict):  # 축별 한계(rms_max 등) — {축: 수치}
        if not isinstance(v, dict):
            _fail(path, "{이름: 수치} 객체여야 함")
        return {k: num(x, f"{path}/{k}") for k, x in v.items()}
    # 기본이 없음(null)인 칸 — 없음, 수치, 또는 수치 목록(bandwidth_window)
    if v is None:
        return None
    if isinstance(v, list):
        return [num(x, f"{path}/{i}") for i, x in enumerate(v)]
    return num(v, path)


def _criteria_groups(t, p, allowed, what):
    """기준 절 공통 — 칸마다 형식을 보고(_criteria_value), 그룹마다 GainEvalCriteria.from_dict로 값을 검증(오류 경로는
    그룹까지)하고, **적은 칸만** 정규화해 돌려준다(적지 않은 칸은 기본값을 따른다 — 기본값을 문서에 굳히지 않는다)."""
    from claw.pipeline.criteria import GainEvalCriteria

    if t is None:
        return None
    if not isinstance(t, dict):
        _fail(p, "객체여야 함")
    defaults = GainEvalCriteria().to_dict()
    typed = {}
    for g, v in t.items():
        if g not in allowed:
            _fail(f"{p}/{g}", f"모르는 {what} 그룹 — {', '.join(allowed)} 중 하나")
        if not isinstance(v, dict):
            _fail(f"{p}/{g}", "객체여야 함")
        for k in v:
            if k not in defaults[g]:
                _fail(f"{p}/{g}/{k}", f"모르는 칸 — {', '.join(defaults[g])} 중 하나")
        typed[g] = {k: _criteria_value(x, defaults[g][k], f"{p}/{g}/{k}") for k, x in v.items()}
    # 값 검증(범위·서열) — 그룹 하나씩 재 어느 그룹이 틀렸는지 짚는다(from_dict 오류는 칸 경로를 모른다).
    # AttributeError까지 받는다: 형식을 통과해도 __post_init__이 예상 밖 모양에서 던지면 500이 아니라 경로 있는 오류여야 한다
    for g in typed:
        try:
            GainEvalCriteria.from_dict({g: typed[g]})
        except (ValueError, TypeError, AttributeError) as e:
            _fail(f"{p}/{g}", str(e))
    try:
        full = GainEvalCriteria.from_dict(typed).to_dict()
    except (ValueError, TypeError, AttributeError) as e:  # 그룹 사이 규칙(지금은 없다)
        _fail(p, str(e))
    return {g: {k: copy.deepcopy(full[g][k]) for k in typed[g]} for g in typed}


def _criteria(t, p):
    """평가 기준 — 합격선·권장선(목표·가중치 뺀 전 그룹). 없음이면 도구 기본값."""
    from claw.pipeline.criteria import JUDGED_GROUPS

    return _criteria_groups(t, p, JUDGED_GROUPS, "기준")


def _tuning(t, p):
    """튜닝 목표 — 자동 설계가 겨냥하는 값(targets)과 J 가중치(weights). 없음이면 도구 기본값."""
    from claw.pipeline.criteria import TUNING_GROUPS

    return _criteria_groups(t, p, TUNING_GROUPS, "튜닝")


def _display(t, p):
    """표시 모델 — 화면(기체 탭 대표 그림)이 이 기체를 무엇으로 그리나. **계산에 쓰이지 않는다** — 지문 밖이다.
    없음(null)이면 모델이 없는 기체다: 화면은 기준량(익폭·기준면적)에서 만든 도식을 그리고 그렇다고 말한다 — 다른
    기체의 모델을 빌려 그리지 않는다. 파일이 서버에 실제로 있는지는 엔진이 모른다(자산 폴더는 서버 몫) — 화면이
    서버 자산 목록과 대조해 말한다."""
    if t is None:
        return None
    _keys(t, p, ("kind", "model"))
    _choice(t["kind"], f"{p}/kind", DISPLAY_KINDS)
    name = _text(t["model"], f"{p}/model", min_len=1)
    if not DISPLAY_MODEL_NAME.fullmatch(name):
        _fail(f"{p}/model", "GLB 파일 이름이어야 함 — 영문·숫자·._-, 확장자 .glb, 경로 없이 (예: shahed136.glb)")
    return {"kind": t["kind"], "model": name}


def table_cells(aero: dict) -> int:
    """검증된 aero 섹션의 표 칸 합."""
    return sum(math.prod(len(g) for g in t["k"]["table"]["axes"].values())
               for terms in aero["coefficients"].values() for t in terms if isinstance(t["k"], dict))


def _raw_table_cells(v) -> int:
    """검증 전 패치 값 속 표 칸 어림 — 표 모양 객체(axes 객체 + data)의 격자 길이 곱. data 안으로는 내려가지 않는다."""
    if isinstance(v, dict):
        axes = v.get("axes")
        if isinstance(axes, dict) and "data" in v:
            return math.prod(len(g) if isinstance(g, list) else 1 for g in axes.values())
        return sum(_raw_table_cells(x) for x in v.values())
    if isinstance(v, list):
        return sum(_raw_table_cells(x) for x in v)
    return 0


def _variants(v, base):
    if not isinstance(v, list):
        _fail("/variants", "목록이어야 함")
    if len(v) > MAX_VARIANTS:
        _fail("/variants", f"형상 변형은 {MAX_VARIANTS}개까지: {len(v)}개")
    base_cells = table_cells(base["aero"])
    if base_cells > MAX_DOCUMENT_TABLE_CELLS:
        _fail("/aero/coefficients", f"표 칸 합 {base_cells}개 — 문서 한 벌에 {MAX_DOCUMENT_TABLE_CELLS}개까지")
    # 변형마다 문서 전체를 다시 검증하기 **전에** 센다 — 세고 나서 거부해야 비용을 막는다
    extra = sum(_raw_table_cells(item.get("patch")) for item in v if isinstance(item, dict))
    total = base_cells * (1 + len(v)) + extra
    if total > MAX_DOCUMENT_TABLE_CELLS:
        _fail("/variants", f"표 칸 합 {total}개 — 기본 문서 {base_cells}칸 × (1 + 형상 변형 {len(v)}개)"
                           f" + 변형이 넣는 표 {extra}칸. {MAX_DOCUMENT_TABLE_CELLS}개까지"
                           " (형상 변형마다 문서 전체를 다시 검증·지문하므로 변형 수가 곱해진다)")
    seen = set()
    out = []
    for i, item in enumerate(v):
        p = f"/variants/{i}"
        _keys(item, p, ("id", "name", "patch"))
        vid = item["id"]
        if not isinstance(vid, str) or not _ID.fullmatch(vid):
            _fail(f"{p}/id", "영문·숫자·_·- 1~64자여야 함")
        if vid in seen:
            _fail(f"{p}/id", f"형상 변형 id 중복: {vid!r}")
        seen.add(vid)
        patch = item["patch"]
        if not isinstance(patch, dict):
            _fail(f"{p}/patch", "{경로: 값} 객체여야 함")
        for ptr in patch:
            head = ptr.split("/")[1] if isinstance(ptr, str) and ptr.startswith("/") else None
            if head in VARIANT_FORBIDDEN:
                _fail(f"{p}/patch", f"형상 변형은 /{head}를 고칠 수 없다 — 평가 기준·튜닝 목표·요구 운용영역은 형상이 "
                                    f"아니라 작업 단위(프로파일) 전체의 요구조건이다 ({ptr})")
        try:
            effective = _body(apply_patch(base, patch), with_variants=False)
        except ProfileError as e:
            if e.path.startswith("/") and e.path != "/":
                raise ProfileError(f"{p}/patch{e.path}", e.message) from None
            # 경로가 아닌 오류(슬래시 없는 포인터 등)는 경로에 이어 붙이지 않고 문장에 싣는다
            raise ProfileError(f"{p}/patch", f"{e.message} ({e.path})") from None
        out.append({
            "id": vid,
            "name": _text(item["name"], f"{p}/name", min_len=1),
            # 값도 정규화된 문서에서 다시 읽는다 — 패치의 6이 6.0으로 저장되게
            "patch": {ptr: copy.deepcopy(get_pointer(effective, ptr)) for ptr in patch},
        })
    return out


def document_warnings(doc: dict) -> list:
    """검증된 문서에서 알려야 할 것 — [{"path", "message"}]. 오류가 아니다(저장·계산은 된다).

    - 트림 α 탐색 상한(solver.trim_alpha_bounds) < 판정 한계 최대(실속 표 최대 − 트림 α 여유 criteria.trim_margin.alpha_margin
      — 적용값, 없으면 도구 기본값): 트림 α 판정은 실속 표 기준인데 해가 탐색 상한을 넘을 수 없어, 저속에서 트림이 판정
      한계가 아니라 탐색 상한에 막힌다(저속 가림). 실속 표 최대와 비교하면 그 사이(판정 한계 위·실속각 아래)의 상한에도
      경고하게 된다 — 그 상한은 아무것도 가리지 않는다.
    - 트림 잔차 허용치(solver.resid_tol) > RESID_TOL_WARN: 저장은 되지만(탐색용으로 느슨하게 둘 수 있다) 그 해를 트림으로 부르기
      어렵다 — 경계값의 뜻은 RESID_TOL_WARN 주석.
    형상 변형이 solver·stall을 덮어쓰면 달라지므로 변형마다도 본다(variant 키). 기준은 변형이 못 고친다(VARIANT_FORBIDDEN)."""
    from claw.pipeline.criteria import GainEvalCriteria

    margin = float(GainEvalCriteria.from_profile(doc).trim_margin.alpha_margin)

    def check(d, variant):
        hi = float(d["solver"]["trim_alpha_bounds"][1])
        limit_max = max(float(v) for v in d["stall"]["table"]["data"]) - margin
        if hi >= limit_max:
            return []
        return [{"path": "/solver/trim_alpha_bounds/1", "variant": variant,
                 "message": f"트림 α 탐색 상한 {hi:g} rad가 판정 한계 최대 {limit_max:g} rad(실속 표 최대 − 트림 α 여유)보다 "
                            "낮다 — 저속에서 트림이 판정 한계가 아니라 탐색 상한에 막힌다(저속 가림). 탐색 상한은 판정이 아니라 "
                            "풀이 범위다"}]

    def loose(d, variant):
        tol = float(d["solver"]["resid_tol"])
        if tol <= RESID_TOL_WARN:
            return []
        return [{"path": "/solver/resid_tol", "variant": variant,
                 "message": f"트림 잔차 허용치 {tol:g}가 {RESID_TOL_WARN:g}보다 크다 — 잔차는 수평비행 평형의 u̇·ẇ[m/s²]·"
                            "q̇[rad/s²]라, 이만큼 남은 해를 수렴으로 받으면 「트림」이 눈에 띄게 흐른다(q̇ 0.01 rad/s²면 1 s에 "
                            f"약 0.6°/s 피치 각속도). v2까지의 상수는 {DEFAULT_RESID_TOL:g}였다"}]

    out = check(doc, None) + loose(doc, None) + _target_warnings(doc)
    for item in doc.get("variants") or []:
        eff = effective_document(doc, item["id"])
        warns = check(eff, item["id"]) + loose(eff, item["id"])
        if warns and not (out and eff["solver"] == doc["solver"] and eff["stall"] == doc["stall"]):
            out += warns
    return out


def _target_warnings(doc: dict) -> list:
    """튜닝 목표가 판정선보다 느슨한 자리 — 저장은 된다(경고). 판정은 design.criteria.target_conflicts 한 자리다.
    합격선보다 느슨하면 튜닝에 성공한 점이 곧바로 불합격이고, 권장선보다 느슨하면 성공한 점이 전부 주의다."""
    from claw.pipeline.criteria import GainEvalCriteria

    why = {"pass": "합격선보다 느슨하다 — 튜닝에 성공한 점이 곧바로 불합격으로 찍힌다",
           "rec": "권장선보다 느슨하다 — 튜닝에 성공한 점이 전부 합격·주의로 찍힌다"}
    crit = GainEvalCriteria.from_profile(doc)
    return [{"path": f"/tuning/targets/{c['target_key']}", "variant": None,
             "message": f"튜닝 목표 {c['target_key']} {c['target']:g}가 {c['line_key']} {c['line']:g}보다 "
                        + why[c["level"]]}
            for c in crit.target_conflicts()]


def validate_document(doc) -> dict:
    """기체 문서 전체(형상 변형 포함) 검증 → 정규화된 새 문서. 실패 시 ProfileError."""
    base = _body(doc, with_variants=True)
    base["variants"] = _variants(doc["variants"], base)
    return base


def effective_document(doc: dict, variant: str | None = None) -> dict:
    """검증된 문서 + 형상 변형 id → 적용된 문서(variants 제외, 재검증됨)."""
    if variant is None:
        # 사본을 준다 — 조립 뒤 호출자가 문서를 고쳐도 조립 결과·지문이 따라 흔들리지 않게
        return copy.deepcopy({k: v for k, v in doc.items() if k != "variants"})
    for item in doc["variants"]:
        if item["id"] == variant:
            return _body(apply_patch(doc, item["patch"]), with_variants=False)
    raise ProfileError("/variants", f"없는 형상 변형: {variant!r}")


# ── v2 → v3 업그레이더 (05 §11.13 이관 11·12단계) ───────────────────────────────────────────────────────────────────

# 해석 설정 기본값 — v2까지 코드 상수였던 수평비행 트림 잔차 허용치(trim/trim.py RESID_TOL 1e-4). v3부터는 문서 값이 정본이고
# 이 값은 옮길 때 채우는 자리일 뿐이다(v2 문서는 이 값으로 풀렸다 — 옮겨도 트림이 바뀌지 않는다)
DEFAULT_RESID_TOL = 1e-4
# 잔차 허용치 경고 경계 [m/s²·rad/s²] — v2 상수의 100배. 잔차는 평형식의 가속도(u̇·ẇ·q̇)라 1e-2면 q̇가 1 s에 약 0.6°/s의
# 피치 각속도를 쌓는다 — 그 위의 「수렴」은 시뮬에서 곧바로 흐르는 해다. 판정이 아니라 경고다(검증기 경계로 막지 않는다 —
# 거친 탐색을 일부러 느슨하게 돌리는 쓰임을 막을 까닭이 없다)
RESID_TOL_WARN = 1e-2
_V2_SCAN_KEYS = ("scan_mach", "scan_alt")


def _note(path, message):
    return {"path": path, "message": message}


def _alt_text(v):
    return "없음" if v is None else f"{float(v):g} m"


def _upgrade_operating(op, region, notes):
    """operating 절을 버리며 그 값이 요구영역 고도로 덮였는지 말한다 — 값이 없으면(null 둘) 말할 것이 없다."""
    if not isinstance(op, dict):
        return
    lo, hi = op.get("alt_min"), op.get("alt_max")
    if lo is None and hi is None:
        return
    said = f"운용 고도 [{_alt_text(lo)}, {_alt_text(hi)}]"
    alt = region.get("alt") if isinstance(region, dict) else None
    if not isinstance(alt, list) or len(alt) != 2:
        notes.append(_note("/operating", f"{said}를 버렸다 — v3에는 운용 고도 절이 없고 운용 고도는 요구영역 고도"
                                         "(/operating_region/alt)인데 이 문서에는 요구영역이 없어 그 값을 옮길 자리가 없다. "
                                         "요구영역을 정하면 그 고도가 운용 고도다"))
        return
    same = all(v is None or float(v) == float(a) for v, a in zip((lo, hi), alt))
    if same:
        notes.append(_note("/operating", f"{said}를 버렸다 — 요구영역 고도 [{float(alt[0]):g}, {float(alt[1]):g}] m가 "
                                         "같은 값이라 잃은 것이 없다"))
    else:
        notes.append(_note("/operating", f"{said}를 버렸다 — 요구영역 고도 [{float(alt[0]):g}, {float(alt[1]):g}] m와 "
                                         "달라 그 차이는 잃었다. v3부터 운용 고도는 요구영역 고도다(설계 엔벨로프·도출·"
                                         "초기 게인 탐색이 그 값을 쓴다)"))


def _strip_scan(env, path, notes):
    """엔벨로프 템플릿 값에서 폐지한 스캔 칸을 뺀다 — 뺀 칸마다 적는다."""
    if not isinstance(env, dict):
        return env
    dropped = [k for k in _V2_SCAN_KEYS if k in env]
    if dropped:
        notes.append(_note(path, f"{'·'.join(dropped)}를 버렸다 — v1.66부터 엔벨로프 스캔 격자는 요구영역 기본 격자이고 "
                                 "화면이 이 칸을 읽지 않는다"))
    return {k: v for k, v in env.items() if k not in _V2_SCAN_KEYS}


def _upgrade_patch(vid, patch, base_margin, notes):
    """형상 변형 패치의 v2 경로를 v3 경로로. 옮길 곳이 없는 값(운용 고도·스캔·트림 α 여유)은 버리고 적는다 — 트림 α 여유는
    v3에서 기준(criteria)이라 형상 변형이 고칠 수 없다(VARIANT_FORBIDDEN)."""
    if not isinstance(patch, dict):
        return patch
    vp = f"/variants/{vid}/patch"
    out = {}
    for ptr, val in patch.items():
        if not isinstance(ptr, str):
            out[ptr] = val
            continue
        if ptr == "/trim":
            if isinstance(val, dict):
                out["/solver"] = {"trim_alpha_bounds": copy.deepcopy(val.get("alpha_bounds")),
                                  "resid_tol": DEFAULT_RESID_TOL}
                m = val.get("alpha_margin")
                if m is not None and m != base_margin:
                    notes.append(_note(f"{vp}{ptr}", f"형상 변형의 트림 α 여유 {m!r}를 버렸다 — v3에서 트림 α 여유는 판정선"
                                                     "(criteria.trim_margin)이라 형상 변형이 고칠 수 없다"))
            else:
                out["/solver"] = val
            continue
        if ptr == "/trim/alpha_bounds" or ptr.startswith("/trim/alpha_bounds/"):
            out["/solver/trim_alpha_bounds" + ptr[len("/trim/alpha_bounds"):]] = val
            continue
        if ptr == "/trim/alpha_margin":
            if val != base_margin:
                notes.append(_note(f"{vp}{ptr}", f"형상 변형의 트림 α 여유 {val!r}를 버렸다 — v3에서 트림 α 여유는 판정선"
                                                 "(criteria.trim_margin)이라 형상 변형이 고칠 수 없다"))
            continue
        if ptr == "/operating" or ptr.startswith("/operating/"):
            if val is not None and val != {"alt_min": None, "alt_max": None}:
                notes.append(_note(f"{vp}{ptr}", f"형상 변형의 운용 고도 {val!r}를 버렸다 — v3에는 운용 고도 절이 없고 "
                                                 "요구영역은 형상 변형이 고칠 수 없다"))
            continue
        if any(ptr == f"/mission_template/envelope/{k}" or ptr.startswith(f"/mission_template/envelope/{k}/")
               for k in _V2_SCAN_KEYS):
            notes.append(_note(f"{vp}{ptr}", "형상 변형의 스캔 칸을 버렸다 — v3에서 폐지(스캔 격자는 요구영역 기본 격자)"))
            continue
        if ptr == "/mission_template/envelope":
            val = _strip_scan(val, f"{vp}{ptr}", notes)
        elif ptr == "/mission_template" and isinstance(val, dict) and "envelope" in val:
            val = {**val, "envelope": _strip_scan(val["envelope"], f"{vp}{ptr}/envelope", notes)}
        elif ptr == "/mass" and isinstance(val, dict) and "loadings" not in val:
            val = {**val, "loadings": None}
        out[ptr] = val
    return out


def upgrade_document(doc):
    """저장·가져온 기체 문서 → (v3 문서, 알림 [{"path", "message"}]) — **검증 전** 원문을 받는다(검증은 호출자가 한다).

    v2만 옮긴다: trim.alpha_bounds → solver.trim_alpha_bounds(resid_tol은 v2 코드 상수 DEFAULT_RESID_TOL — 같은 값이라
    트림이 바뀌지 않는다), trim.alpha_margin → criteria.trim_margin.alpha_margin(도구 기본값과 다를 때만 — 기본값을 문서에
    굳히지 않는다), operating 절 폐기(값이 있었으면 요구영역 고도로 덮였는지·잃었는지 적는다), mission_template.envelope의
    scan_mach·scan_alt 폐기, mass.loadings 자리(없음), 형상 변형 패치 경로도 같은 규칙, schema_version 3. 그 밖의 칸은
    건드리지 않는다. 계보 도장(도출 δe_trim plant_fingerprints·확정 게인 표 basis_fingerprint·초기 게인 출처 plant_fingerprint
    — 형상 변형 패치 안의 것도)은 **v2에서 최신이었음을 v2 지문을 옛 정의로 다시 재서 증명할 수 있을 때만** v3 지문으로
    다시 찍는다(_restamp_lineage). 증명이 안 되는 표(요구영역 없이 도출한 δe_trim — 운용 고도 절로 거른 검사 고도 — 이나
    v2에서도 낡았던 표)는 낡음으로 두고 그 까닭을 알림에 적는다(다시 도출·설계해 반영한다).

    v3(이미 옮김)와 v1·그 밖의 버전은 **그대로** 돌려준다(알림 없음) — 멱등이고, v1은 종전 정책대로 검증이 거부한다
    (v1 → v2의 확정 게인 표는 옮길 원본이 없는 새 절이라 업그레이더가 없었다). dict가 아니면 그대로 돌려준다."""
    if not isinstance(doc, dict) or isinstance(doc.get("schema_version"), bool) or doc.get("schema_version") != 2:
        return copy.deepcopy(doc), []
    from claw.pipeline.criteria import TrimMarginCriteria

    default_margin = TrimMarginCriteria().alpha_margin
    d = copy.deepcopy(doc)
    notes = []
    out = {}
    trim = d.get("trim")
    base_margin = trim.get("alpha_margin") if isinstance(trim, dict) else None
    for k, v in d.items():
        if k == "trim":
            if isinstance(v, dict):
                out["solver"] = {"trim_alpha_bounds": v.get("alpha_bounds"), "resid_tol": DEFAULT_RESID_TOL}
                notes.append(_note("/trim/alpha_bounds", "트림 받음각 탐색 범위를 해석 설정 /solver/trim_alpha_bounds로 "
                                                         f"옮겼다 — 잔차 허용치 resid_tol은 v2 코드 상수 {DEFAULT_RESID_TOL:g}"))
            else:
                out["solver"] = v  # 모양이 틀린 원문 — 검증이 경로와 함께 말한다
            continue
        if k == "operating":
            _upgrade_operating(v, d.get("operating_region"), notes)
            continue
        if k == "mission_template" and isinstance(v, dict) and isinstance(v.get("envelope"), dict):
            v = {**v, "envelope": _strip_scan(v["envelope"], "/mission_template/envelope", notes)}
        if k == "mass" and isinstance(v, dict) and "loadings" not in v:
            v = {**v, "loadings": None}
        if k == "variants" and isinstance(v, list):
            v = [{**item, "patch": _upgrade_patch(item.get("id", i), item.get("patch"), base_margin, notes)} if isinstance(item, dict) else item
                 for i, item in enumerate(v)]
        out[k] = v
    if base_margin is not None and base_margin != default_margin:
        crit = out.get("criteria")
        crit = dict(crit) if isinstance(crit, dict) else {}
        crit["trim_margin"] = {**(crit.get("trim_margin") or {}), "alpha_margin": base_margin}
        out["criteria"] = crit
        notes.append(_note("/trim/alpha_margin", f"트림 α 여유 {base_margin!r}를 판정선 /criteria/trim_margin/alpha_margin으로 "
                                                 f"옮겼다(도구 기본값 {default_margin:g}와 달라서)"))
    elif base_margin is not None:
        notes.append(_note("/trim/alpha_margin", f"트림 α 여유 {base_margin!r}는 도구 기본값과 같아 문서에 적지 않았다 — "
                                                 "판정선 criteria.trim_margin.alpha_margin의 기본값이 그 값이다"))
    out["schema_version"] = SCHEMA_VERSION
    _restamp_lineage(d, out, notes)
    return out, notes


# ── v2 계보 도장 다시 찍기 ─────────────────────────────────────────────────────────────────────────────────────────
# 스키마가 바뀌면 지문 정의가 바뀐다(플랜트 지문에서 trim 절이 빠지고 계보 지문에 solver 절이 든다). 그대로 두면 v2에서
# 최신이던 도출 δe_trim 표·확정 게인 표가 올리자마자 낡음으로 보여 시뮬·코드 생성이 막힌다(build.alloc_trim_table 거부).
# 그래서 **v2에서 최신이었음을 증명할 수 있을 때만** v3 지문으로 다시 찍는다 — 증명은 v2 지문을 옛 정의 그대로 다시 재서
# 기록과 대조하는 것이다. 증명이 안 되면 도장을 두고(낡음) 왜 그런지 적는다.

_V2_PLANT_SECTIONS = ("geometry", "aero", "stall", "mass", "propulsion", "ground", "trim", "surfaces")  # v2 정의 그대로
_DE_TRIM_PROV = ("law", "alloc", "de_trim", "provenance")
_GAIN_PROV = ("law", "gain_tables", "provenance")
_DESIGN_PROV = ("law", "design", "provenance")


def _v2_shadow(eff, raw_eff):
    """v3 적용 문서(검증·정규화) → v2 검증기가 냈을 정규화 문서 중 v2 지문 둘(플랜트·계보)이 읽는 부분.

    올림은 trim·operating·mass.loadings·schema_version만 바꾸고 나머지 절의 검증기는 v2와 같다(같은 정규화) — 그래서 v3
    적용 문서에서 그 칸만 v2 모양으로 되돌리면 v2 지문 입력이 된다. mission_template·criteria는 지문 밖이라 되돌리지
    않는다. 트림 α 여유는 형상 변형마다 달 수 있었으므로(v3는 버린다) v2 원문의 적용값(raw_eff)에서 읽는다."""
    d = copy.deepcopy(eff)
    solver = d.pop("solver")
    op = raw_eff.get("operating") or {}
    d["schema_version"] = 2
    d["trim"] = {"alpha_bounds": [float(x) for x in solver["trim_alpha_bounds"]],
                 "alpha_margin": float(raw_eff["trim"]["alpha_margin"])}
    d["operating"] = {k: None if op.get(k) is None else float(op[k]) for k in ("alt_min", "alt_max")}
    d["mass"] = {k: v for k, v in d["mass"].items() if k != "loadings"}
    return d


def _v2_plant_fp(shadow):
    from claw.params.paramset import canonical_hash
    from claw.profile.fingerprint import _ordered_axes

    return canonical_hash({k: (_ordered_axes(shadow[k]) if k == "aero" else shadow[k]) for k in _V2_PLANT_SECTIONS})


def _v2_configs(raw, v):
    """[{vid, name, eff(v3 적용), shadow(v2 그림자 | None — 증명 불가), patch(올린 패치 | None)}] — 기본 문서 먼저."""
    raw_patches = {item.get("id"): item.get("patch") for item in raw.get("variants") or [] if isinstance(item, dict)}
    out = []
    for vid in [None] + [item["id"] for item in v["variants"] or []]:
        eff = effective_document(v, vid)
        try:
            raw_eff = raw if vid is None else apply_patch(raw, raw_patches[vid])
            shadow = _v2_shadow(eff, raw_eff)
        except (ProfileError, KeyError, TypeError, ValueError, AttributeError):
            shadow = None  # v2 원문이 v2 검증기도 못 넘었을 모양 — 증명하지 않는다
        patch = None if vid is None else next(i["patch"] for i in v["variants"] if i["id"] == vid)
        out.append({"vid": vid, "name": vid or "base", "eff": eff, "shadow": shadow, "patch": patch})
    return out


def _prov_owner(patch, target):
    """형상 변형의 target(출처 기록) 값이 어디서 오나 — None(기본 문서), (패치 키, 키 아래 남은 토큰), "deep"(출처 기록
    안쪽 칸을 고치는 키가 있다 — 기록이 기본 문서와 패치의 섞임이라 증명하지 않는다). 뒤 키가 앞 키를 덮는다(apply_patch)."""
    from claw.profile.patch import parse_pointer

    owner = None
    for ptr in patch or {}:
        toks = parse_pointer(ptr)
        if len(toks) > len(target) and toks[:len(target)] == list(target):
            return "deep"
        if toks == list(target[:len(toks)]):
            owner = (ptr, list(target[len(toks):]))
    return owner


def _node(root, tokens):
    for t in tokens:
        root = root.get(t) if isinstance(root, dict) else None
    return root


def _prov_groups(out, configs, target):
    """출처 기록 자리별 형상 묶음 — [(알림 경로, 올린 문서 안의 기록 dict | None, 주인 형상, [형상…])]. 주인은 그 기록을
    쓴 문서(기본 문서 또는 기록을 통째로 덮는 변형)다. "deep" 변형은 (경로, None, 그 형상, [그 형상])으로 — 증명 불가."""
    by_variant = {item.get("id"): item for item in out.get("variants") or [] if isinstance(item, dict)}
    base_path = "/" + "/".join(target[:-1])
    groups = {None: (base_path, _node(out, target), configs[0], [])}
    for cfg in configs:
        owner = None if cfg["vid"] is None else _prov_owner(cfg["patch"], target)
        if owner is None:
            groups[None][3].append(cfg)
        elif owner == "deep":
            groups[(cfg["vid"], "deep")] = (f"/variants/{cfg['vid']}/patch", None, cfg, [cfg])
        else:
            ptr, rest = owner
            raw_patch = (by_variant.get(cfg["vid"]) or {}).get("patch") or {}
            groups[(cfg["vid"], ptr)] = (f"/variants/{cfg['vid']}/patch{ptr}", _node(raw_patch.get(ptr), rest),
                                         cfg, [cfg])
    return list(groups.values())


def _restamp_de_trim(out, configs, notes):
    """도출 δe_trim 표 — v2에서 주인 형상이 최신(v2 플랜트 지문이 기록에 있다)이고 도출이 요구영역으로 돌았으면(기록에
    region이 있다 — 검사 고도가 운용 고도 절이 아니라 요구영역에서 났다) v3 플랜트 지문·풀이 설정으로 다시 찍는다.
    풀이 설정은 v2 트림 탐색 범위 + 옛 상수 잔차 허용치 그대로라(올림이 그렇게 채운다) 트림 입력이 같다."""
    from claw.profile.fingerprint import plant_fingerprint

    for path, prov, owner, group in _prov_groups(out, configs, _DE_TRIM_PROV):
        alloc = owner["eff"]["law"]["alloc"]
        de = None if alloc is None else alloc["de_trim"]
        if de is None or de["source"] != "derived":
            continue
        why = None
        if not isinstance(prov, dict):
            why = ("출처 기록 안쪽 칸을 형상 변형이 따로 고쳐 기록이 섞였다" if path.endswith("/patch")
                   else "출처 기록이 없다")
        elif not isinstance(prov.get("region"), dict):
            why = ("도출 기록에 요구영역이 없다 — v2 도출은 요구영역이 없으면 검사 고도를 운용 고도 절(operating)로 걸렀는데 "
                   "v3에는 그 절이 없어 같은 표를 다시 낼 수 없다")
        elif owner["shadow"] is None or owner["eff"]["solver"]["resid_tol"] != DEFAULT_RESID_TOL:
            why = "v2 플랜트 지문을 다시 잴 수 없다"
        else:
            old = prov.get("plant_fingerprints")
            old = old if isinstance(old, list) else [prov.get("plant_fingerprint")]
            if _v2_plant_fp(owner["shadow"]) not in old:
                why = "v2에서 이미 낡은 표였다(도출 뒤 플랜트가 바뀌었다)"
        if why is not None:
            notes.append(_note(path, f"도출 δe_trim 표는 낡음으로 보인다 — {why}. 표를 다시 도출한다"))
            continue
        fresh, seen = [], set()
        for cfg in [owner] + [c for c in group if c is not owner]:
            if cfg["shadow"] is None or _v2_plant_fp(cfg["shadow"]) not in old:
                continue
            fp, sv = plant_fingerprint(cfg["eff"]), cfg["eff"]["solver"]
            key = (fp, json.dumps(sv, sort_keys=True))
            if key not in seen:
                seen.add(key)
                fresh.append((cfg["name"], fp, {"trim_alpha_bounds": list(sv["trim_alpha_bounds"]),
                                                "resid_tol": sv["resid_tol"]}))
        left = [c["name"] for c in group if c["shadow"] is None or _v2_plant_fp(c["shadow"]) not in old]
        prov.update(plant_fingerprint=fresh[0][1], plant_fingerprints=[f for _, f, _ in fresh],
                    solver=fresh[0][2], solvers=[s for *_, s in fresh], configurations=[n for n, *_ in fresh])
        notes.append(_note(path, "도출 δe_trim 표의 플랜트 지문을 v3 정의로 다시 찍었다 — 이 문서의 v2 플랜트 지문이 도출 "
                                 "기록과 같아 v2에서 최신이던 표이고, 도출이 요구영역으로 돌았으며, 풀이 설정은 v2 트림 탐색 "
                                 f"범위와 옛 상수 잔차 허용치 {DEFAULT_RESID_TOL:g} 그대로라 트림 입력이 같다"
                                 + (f". v2에서도 낡았던 형상({'·'.join(left)})은 그대로 낡음이다" if left else "")))


def _restamp_gain_tables(out, configs, notes):
    """확정 게인 표 — 기준 지문(표 절을 뺀 적용 문서의 계보 지문)을 v2 정의로 다시 재서 기록과 같으면(표를 확정한 문서가
    올리기 전 이 문서와 같다) v3 기준 지문으로 다시 찍는다. 기록과 다르면(v2에서도 낡았다) 그대로 둔다."""
    from claw.profile.fingerprint import gain_tables_basis_fingerprint

    for path, prov, owner, group in _prov_groups(out, configs, _GAIN_PROV):
        if owner["eff"]["law"]["gain_tables"] is None:
            continue
        if not isinstance(prov, dict):
            why = "기준 지문 기록이 없거나 형상 변형이 기록 안쪽을 따로 고쳤다"
        elif owner["shadow"] is None:
            why = "v2 기준 지문을 다시 잴 수 없다"
        elif prov.get("basis_fingerprint") != gain_tables_basis_fingerprint(owner["shadow"]):
            why = "v2에서 이미 낡은 표였다(확정 뒤 문서가 바뀌었다)"
        else:
            prov["basis_fingerprint"] = gain_tables_basis_fingerprint(owner["eff"])
            notes.append(_note(path, "확정 게인 표의 기준 지문을 v3 정의로 다시 찍었다 — v2 기준 지문이 기록과 같아(표를 확정한 "
                                     "문서가 올리기 전 이 문서다) 올림이 바꾼 것은 절 모양뿐이다"))
            continue
        notes.append(_note(path, f"확정 게인 표는 낡음으로 보인다 — {why}. 자동 설계를 다시 돌려 반영하거나 표를 지운다"))


def _restamp_design(out, configs, notes):
    """초기 게인 출처의 플랜트 지문(산출 근거가 잰 플랜트 — 기록일 뿐 낡음 판정에 쓰지 않는다)도 같은 증명으로 다시 찍는다."""
    from claw.profile.fingerprint import plant_fingerprint

    for path, prov, owner, _ in _prov_groups(out, configs, _DESIGN_PROV):
        if not isinstance(prov, dict) or "plant_fingerprint" not in prov or owner["shadow"] is None:
            continue
        if prov["plant_fingerprint"] == _v2_plant_fp(owner["shadow"]):
            prov["plant_fingerprint"] = plant_fingerprint(owner["eff"])
            notes.append(_note(path, "초기 게인 출처의 플랜트 지문을 v3 정의로 다시 찍었다 — v2 플랜트 지문이 기록과 같다"))


def _restamp_lineage(raw, out, notes):
    """올린 문서의 계보 도장을 v3 지문으로 — 증명이 되는 것만(머리말). 올린 문서가 검증을 못 넘으면 아무것도 찍지 않는다
    (검증은 호출자가 경로와 함께 말한다) — 그때 표가 있으면 낡음으로 적는다."""
    try:
        v = validate_document(out)
        configs = _v2_configs(raw, v)
    except ProfileError:
        law = out.get("law") if isinstance(out.get("law"), dict) else {}
        alloc = law.get("alloc") if isinstance(law.get("alloc"), dict) else {}
        if isinstance(alloc.get("de_trim"), dict) and alloc["de_trim"].get("source") == "derived":
            notes.append(_note("/law/alloc/de_trim", "도출 δe_trim 표는 낡음으로 보인다 — 올린 문서가 검증을 넘지 못해 v2 "
                                                     "지문을 다시 잴 수 없다. 표를 다시 도출한다"))
        if law.get("gain_tables") is not None:
            notes.append(_note("/law/gain_tables", "확정 게인 표는 낡음으로 보인다 — 올린 문서가 검증을 넘지 못해 v2 지문을 "
                                                   "다시 잴 수 없다"))
        return
    _restamp_de_trim(out, configs, notes)
    _restamp_gain_tables(out, configs, notes)
    _restamp_design(out, configs, notes)
