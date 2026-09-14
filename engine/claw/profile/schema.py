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
import math
import re

from claw.profile.errors import ProfileError
from claw.profile.patch import apply_patch, get_pointer

SCHEMA_VERSION = 1
MAX_VARIANTS = 64  # 형상 변형 상한 — 읽을 때마다 변형마다 재검증하므로 단일 워커를 물지 않게

SECTIONS = (
    "schema_version", "id", "name", "description", "is_example",
    "geometry", "aero", "stall", "mass", "propulsion", "actuator", "surfaces",
    "structural", "operating", "ground", "trim", "law", "mission_template", "variants",
)
# 스키마 v1에 나중에 더한 **선택 절** — 문서에 없으면 null(없음)로 채운다. 버전을 올리는 대신 이렇게 한
# 이유: 이 절은 계산에 쓰이지 않아 지문 밖인데(fingerprint.py), 버전을 올리면 버전 값이 지문에 들어가 옛
# 결과·설계 세션의 계보(스냅숏 지문)가 통째로 끊긴다. 계산에 쓰이는 절이 생기면 그때 버전을 올린다
OPTIONAL_SECTIONS = ("mission_template",)
# 미션 템플릿 격자의 케이스 상한 — 서버 스캔·영향성 격자 상한(MAX_SCAN_CASES·MAX_CASES)과 같은 자리.
# 간격 오타 하나로 수만 케이스가 되면 그 기체를 고른 모든 화면이 격자를 만들다 멈춘다
MAX_TEMPLATE_CASES = 200
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


def _increasing(v, path, *, min_len=2):
    if not isinstance(v, list) or len(v) < min_len:
        _fail(path, f"수치 {min_len}개 이상 목록이어야 함")
    out = [_num(x, f"{path}/{i}") for i, x in enumerate(v)]
    for i in range(1, len(out)):
        if not out[i] > out[i - 1]:
            _fail(f"{path}/{i}", "순증가(오름차순)여야 함")
    return out


def _table_mach(t, path, *, extrapolate):
    _keys(t, path, ("axes", "data", "extrapolate"))
    _keys(t["axes"], f"{path}/axes", ("mach",))
    axis = _increasing(t["axes"]["mach"], f"{path}/axes/mach")
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


def _mass(m, p):
    _keys(m, p, ("m_empty", "fuel_max", "J_empty", "J_full", "cg_empty", "cg_full"))
    return {
        "m_empty": _num(m["m_empty"], f"{p}/m_empty", lo=0.0, lo_open=True),
        "fuel_max": _num(m["fuel_max"], f"{p}/fuel_max", lo=0.0),
        "J_empty": _mat3(m["J_empty"], f"{p}/J_empty"),
        "J_full": _mat3(m["J_full"], f"{p}/J_full"),
        "cg_empty": _vec(m["cg_empty"], f"{p}/cg_empty", 3),
        "cg_full": _vec(m["cg_full"], f"{p}/cg_full", 3),
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


def _operating(o, p):
    _keys(o, p, ("alt_min", "alt_max"))
    lo, hi = ISA_ALT_RANGE
    out = {k: _num(o[k], f"{p}/{k}", lo=lo, hi=hi, nullable=True) for k in ("alt_min", "alt_max")}
    if out["alt_min"] is not None and out["alt_max"] is not None \
            and not out["alt_min"] < out["alt_max"]:
        _fail(f"{p}/alt_max", "운용 고도 하한 < 상한이어야 함")
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


def _trim(t, p):
    _keys(t, p, ("alpha_bounds", "alpha_margin"))
    return {
        "alpha_bounds": _range(t["alpha_bounds"], f"{p}/alpha_bounds"),
        "alpha_margin": _num(t["alpha_margin"], f"{p}/alpha_margin", lo=0.0),
    }


def _schedulable_slots():
    from claw.fcl.graphs import SCHEDULABLE

    return SCHEDULABLE


def _law(law, p):
    _keys(law, p, ("template", "alpha_margin", "filter_tau", "design", "schedule", "alloc"))
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
            "mach_grid": _increasing(sched["mach_grid"], f"{sp}/mach_grid"),
            "caps": {
                "default": _num(sched["caps"]["default"], f"{sp}/caps/default",
                                lo=0.0, lo_open=True),
                "by_group": {g: _num(v, f"{sp}/caps/by_group/{g}", lo=0.0, lo_open=True)
                             for g, v in by_group.items()},
            },
            "scheduled": list(scheduled),
        }
    out["schedule"] = sched
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
    _keys(e, ep, ("alt", "fuel", "scan_mach", "scan_alt"))
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
        "alt": _num(e["alt"], f"{ep}/alt", lo=lo, hi=hi),
        "fuel": _num(e["fuel"], f"{ep}/fuel", lo=0.0),
        "scan_mach": _span(e["scan_mach"], f"{ep}/scan_mach", lo=0.0),
        "scan_alt": _numlist(e["scan_alt"], f"{ep}/scan_alt", lo=lo, hi=hi),
    }
    n = points(envelope["scan_mach"], f"{ep}/scan_mach") * len(envelope["scan_alt"])
    if n > MAX_TEMPLATE_CASES:
        _fail(f"{ep}/scan_mach", f"스캔 케이스 {n}개 — {MAX_TEMPLATE_CASES}개까지 (간격·목록 확인)")

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


def _body(d, *, with_variants):
    top = SECTIONS if with_variants else tuple(k for k in SECTIONS if k != "variants")
    if isinstance(d, dict):
        d = {**{k: None for k in OPTIONAL_SECTIONS}, **d}  # 선택 절이 없으면 없음(null)
    _keys(d, "", top)
    sv = d["schema_version"]
    if isinstance(sv, bool) or sv != SCHEMA_VERSION:
        _fail("/schema_version", f"지원 스키마 버전은 {SCHEMA_VERSION}: {sv!r}")
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
        "operating": _operating(d["operating"], "/operating"),
        "ground": _ground(d["ground"], "/ground"),
        "trim": _trim(d["trim"], "/trim"),
        "law": _law(d["law"], "/law"),
        "mission_template": _mission_template(d["mission_template"], "/mission_template"),
    }


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

    - 트림 α 탐색 상한 < 판정 한계 최대(실속 표 최대 − trim.alpha_margin): 트림 α 판정은 실속 표 기준인데 해가 탐색
      상한을 넘을 수 없어, 저속에서 트림이 판정 한계가 아니라 탐색 상한에 막힌다(저속 가림). 실속 표 최대와 비교하면
      그 사이(판정 한계 위·실속각 아래)의 상한에도 경고하게 된다 — 그 상한은 아무것도 가리지 않는다.
    형상 변형이 trim·stall을 덮어쓰면 달라지므로 변형마다도 본다(variant 키)."""
    def check(d, variant):
        hi = float(d["trim"]["alpha_bounds"][1])
        limit_max = max(float(v) for v in d["stall"]["table"]["data"]) - float(d["trim"]["alpha_margin"])
        if hi >= limit_max:
            return []
        return [{"path": "/trim/alpha_bounds/1", "variant": variant,
                 "message": f"트림 α 탐색 상한 {hi:g} rad가 판정 한계 최대 {limit_max:g} rad(실속 표 최대 − 트림 α 여유)보다 "
                            "낮다 — 저속에서 트림이 판정 한계가 아니라 탐색 상한에 막힌다(저속 가림). 탐색 상한은 판정이 아니라 "
                            "풀이 범위다"}]

    out = check(doc, None)
    for item in doc.get("variants") or []:
        eff = effective_document(doc, item["id"])
        warns = check(eff, item["id"])
        if warns and not (out and eff["trim"] == doc["trim"] and eff["stall"] == doc["stall"]):
            out += warns
    return out


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
