"""기체 문서 편집 폼 서술 — 칸마다 이름·단위·형식 (02 §5.6 · 06 §8).

웹 기체 탭의 절별 폼이 이것을 받아 그린다(`GET /api/profiles/_form`). 검증기(schema.py) 옆에 두는
이유: 칸의 뜻·단위·고를 수 있는 값은 검증기가 이미 아는 지식이다. 웹에 다시 적으면 두 곳이 갈리고,
갈린 쪽이 화면이라 사용자는 엔진이 받지 않는 값을 고르게 된다. 선택지는 검증기 상수에서 **그대로**
읽는다. 판정(범위·서열·대칭)은 여기 적지 않는다 — 저장·검증 때 검증기가 경로와 함께 말한다.

단위는 문서 규약대로 SI·rad다. `test_profile_form.py`가 예제 문서의 모든 값이 어느 칸에 속하는지,
모든 칸이 예제 문서에 실재하는지 대조한다 — 검증기에 키가 늘면 폼에 칸이 없다고 빨개진다.

칸 형식(kind):
  number · range([lo,hi]) · vec3 · mat3(3×3, symmetric이면 대칭 칸을 함께 고친다) · rows3(N×3 행)
  · table_mach(마하 1축 표) · choice · multichoice · numlist · text_json(자유 객체 — 출처 등)
  · terms(공력 계수 항 목록) · registry(레지스트리 파라미터 객체, 형식 고정)
  · component({type, params} — 형식을 고르면 파라미터 칸이 바뀐다) · group(하위 칸 묶음, nullable 가능)
"""

from claw.profile.schema import (
    ACTUATOR_RESERVED, AERO_FORMS, DE_TRIM_SOURCES, DISPERSION_TAGS, LAYOUTS, SCAS_RESERVED,
    SCHEDULE_RULES, SCHEMA_VERSION, TABLE_AXES, TABLE_EXTRAPOLATE, TABLE_POLICIES, TEMPLATES,
    TERM_EXTRA_INPUTS, TERM_INPUTS,
)

# 문서 머리 — 폼 절이 아니라 탭의 이름표·형상 변형 편집이 다룬다
META_KEYS = ("schema_version", "id", "name", "description", "is_example", "variants")


def _f(kind, path, label, unit="", **extra):
    return {"kind": kind, "path": path, "label": label, "unit": unit, **extra}


def _group(path, label, fields, *, nullable=False, help=""):
    return {"kind": "group", "path": path, "label": label, "nullable": nullable, "help": help,
            "fields": fields}


def _section(key, title, help, fields):
    return {"key": key, "title": title, "help": help, "fields": fields}


def _scas(axis, label):
    return _f("registry", f"/law/design/scas/{axis}", label, category="fcl", name="ScasAxis",
              reserved=list(SCAS_RESERVED))


def form_spec() -> dict:
    """JSON으로 내보낼 폼 서술. 선택지는 검증기·레지스트리에서 읽는다(호출 시점 기준)."""
    from claw.fcl.graphs import SCHEDULABLE
    from claw.profile.aeroview import COEFFICIENTS, MAX_POINTS, SLICE_AXES
    from claw.profile.schema import _registry

    reg = _registry()
    slots = [f"{g}.{k}" for g, ks in SCHEDULABLE.items() for k in ks]
    sections = [
        _section("geometry", "기준 형상", "공력 계수를 힘·모멘트로 바꾸는 기준 길이·면적", [
            _f("number", "/geometry/S", "기준 면적", "m²"),
            _f("number", "/geometry/cbar", "평균 공력 시위", "m"),
            _f("number", "/geometry/b", "날개폭", "m"),
        ]),
        _section("aero", "공력", "계수 = 항들의 합(항 = k × 입력들의 곱). DB 유효 범위는 엔벨로프의 공력 경계다", [
            _f("choice", "/aero/form", "계수 형식", choices=list(AERO_FORMS),
               help="lift_drag: CL·CD·CY(풍축) / body: CX·CY·CZ(동체축) — 바꾸면 계수 이름이 바뀐다"),
            _f("terms", "/aero/coefficients", "계수 항"),
            _f("range", "/aero/db_ranges/alpha", "DB 유효 받음각", "rad", nullable=True),
            _f("range", "/aero/db_ranges/beta", "DB 유효 옆미끄럼각", "rad", nullable=True),
            _f("range", "/aero/db_ranges/mach", "DB 유효 마하", "-", nullable=True),
        ]),
        _section("stall", "실속", "α 리미터·엔벨로프의 실속 경계(공력팀 표가 정본)", [
            _f("table_mach", "/stall/table", "실속 받음각", "rad", value_label="α_stall",
               extrapolate=list(TABLE_EXTRAPOLATE)),
            _f("number", "/stall/neg_alpha_ratio", "음의 실속 비율 (|α_stall,neg| / α_stall)", "-"),
        ]),
        _section("mass", "질량·관성", "연료 0과 만재 사이를 연료량으로 보간한다. 무게중심은 아직 동역학에 반영되지 않는다", [
            _f("number", "/mass/m_empty", "공허 질량", "kg"),
            _f("number", "/mass/fuel_max", "최대 연료", "kg"),
            _f("mat3", "/mass/J_empty", "관성 행렬 (연료 0)", "kg·m²", symmetric=True),
            _f("mat3", "/mass/J_full", "관성 행렬 (연료 만재)", "kg·m²", symmetric=True),
            _f("vec3", "/mass/cg_empty", "무게중심 (연료 0) [x,y,z]", "m"),
            _f("vec3", "/mass/cg_full", "무게중심 (연료 만재) [x,y,z]", "m"),
        ]),
        _section("propulsion", "추진", "형식을 고르면 그 형식의 파라미터 칸이 선다 — 파라미터는 전부 명시한다", [
            _f("component", "/propulsion", "추진 형식", category="propulsion", reserved=[]),
        ]),
        _section("actuator", "작동기", "위치 한계는 타면 절, 초기값은 트림이 정한다", [
            _f("component", "/actuator", "작동기 형식", category="actuator", reserved=list(ACTUATOR_RESERVED)),
        ]),
        _section("surfaces", "타면", "타면 한계는 중립(0)을 사이에 둔다 — 믹서·트림 탐색 범위가 이 값을 쓴다", [
            _f("choice", "/surfaces/layout", "타면 배치", choices=list(LAYOUTS)),
            _f("range", "/surfaces/elevon", "엘레본 한계", "rad"),
            _f("range", "/surfaces/rudder", "러더 한계", "rad"),
        ]),
        _section("structural", "구조 한계", "V-n·설계 엔벨로프의 구조 경계(구조팀 값이 정본)", [
            _f("number", "/structural/n_limit_pos", "양의 제한 하중배수", "g"),
            _f("number", "/structural/n_limit_neg", "음의 제한 하중배수", "g"),
            _f("number", "/structural/safety_factor", "안전계수", "-"),
            _f("number", "/structural/mach_no", "M_NO (최대 순항 마하)", "-"),
            _f("number", "/structural/mach_d", "M_D (설계 급강하 마하)", "-"),
            _f("number", "/structural/q_max", "최대 동압", "Pa", nullable=True),
            _f("number", "/structural/n_x_launch", "발사 축방향 하중배수 한계", "g", nullable=True),
        ]),
        _section("operating", "운용", "설계 엔벨로프의 운용 고도 경계 — 없으면 경계를 그리지 않는다", [
            _f("number", "/operating/alt_min", "운용 고도 하한", "m", nullable=True),
            _f("number", "/operating/alt_max", "운용 고도 상한", "m", nullable=True),
        ]),
        _section("ground", "지상·발사", "없음이면 그 지상 모델을 쓰지 않는다", [
            _group("/ground/skid", "스키드 접지", nullable=True, fields=[
                _f("rows3", "/ground/skid/contacts", "접촉점 [x,y,z] (동체축)", "m"),
                _f("number", "/ground/skid/k", "접지 강성", "N/m"),
                _f("number", "/ground/skid/c", "접지 감쇠", "N·s/m"),
                _f("number", "/ground/skid/mu", "마찰계수", "-"),
            ]),
            _group("/ground/rail", "발사 레일", nullable=True, fields=[
                _f("number", "/ground/rail/length", "레일 길이", "m"),
                _f("number", "/ground/rail/elev_angle", "레일 앙각", "rad"),
                _f("number", "/ground/rail/exit_speed", "이탈 속도", "m/s"),
                _f("number", "/ground/rail/origin_height", "레일 원점 높이", "m"),
            ]),
        ]),
        _section("trim", "트림 판정", "트림 여유 — 리미터 여유(제어법칙 절)와 따로 간다", [
            _f("range", "/trim/alpha_bounds", "트림 받음각 탐색 범위", "rad"),
            _f("number", "/trim/alpha_margin", "트림 α 여유", "rad"),
        ]),
        _section("law", "제어법칙", "설계 게인이 없으면(없음) 시뮬·코드 생성이 거부한다 — 없는 게인을 지어내지 않는다", [
            _f("choice", "/law/template", "법칙 템플릿", choices=list(TEMPLATES)),
            _f("number", "/law/alpha_margin", "α 리미터 여유", "rad"),
            _f("number", "/law/filter_tau", "명령 필터 시정수", "s"),
            _group("/law/design", "설계 게인", nullable=True, fields=[
                _scas("pitch", "피치 SCAS"), _scas("roll", "롤 SCAS"), _scas("yaw", "요 SCAS"),
                _f("registry", "/law/design/autopilot", "자동조종", category="fcl", name="Autopilot",
                   reserved=[]),
                _f("number", "/law/design/k_diff_thr", "차동추력 보상 게인", "-"),
                _f("text_json", "/law/design/provenance", "출처 (자유 기록)"),
            ]),
            _group("/law/schedule", "게인 스케줄", nullable=True, help="설계 게인 없이 둘 수 없다", fields=[
                _f("choice", "/law/schedule/rule", "스케줄 규칙", choices=list(SCHEDULE_RULES)),
                _f("number", "/law/schedule/m_design", "설계 마하", "-"),
                _f("numlist", "/law/schedule/mach_grid", "마하 격자 (오름차순)", "-"),
                _f("number", "/law/schedule/caps/default", "게인 배율 상한", "-"),
                _f("text_json", "/law/schedule/caps/by_group", "그룹별 배율 상한 {그룹: 상한}",
                   help=f"그룹: {', '.join(SCHEDULABLE)}"),
                _f("multichoice", "/law/schedule/scheduled", "스케줄 적용 자리", choices=slots),
            ]),
            _group("/law/alloc", "타면 할당", nullable=True, fields=[
                _f("number", "/law/alloc/resv_frac", "롤 권한 예비 비율", "-"),
                _group("/law/alloc/de_trim", "트림 엘레본 표", nullable=True, fields=[
                    _f("choice", "/law/alloc/de_trim/source", "표 출처", choices=list(DE_TRIM_SOURCES)),
                    _f("table_mach", "/law/alloc/de_trim/table", "마하별 트림 엘레본", "rad",
                       value_label="δe_trim", extrapolate=list(TABLE_EXTRAPOLATE)),
                    _f("text_json", "/law/alloc/de_trim/provenance", "출처 (자유 기록)"),
                ]),
            ]),
        ]),
        _section("mission_template", "미션 템플릿",
                 "웹 폼의 초기값(격자·엔벨로프·시뮬 미션) — 계산에 쓰이지 않고 지문 밖이다. 없음이면 화면이 예제 기체에 "
                 "맞춘 값을 쓰고 그렇다고 말한다. 장소 값(경로·활주로)은 여기 없다", [
            _group("/mission_template", "미션 템플릿", nullable=True, fields=[
                _group("/mission_template/trim_grid", "해석 격자 (트림·마진 맵·영향성)", fields=[
                    _f("number", "/mission_template/trim_grid/mach/from", "마하 시작", "-"),
                    _f("number", "/mission_template/trim_grid/mach/to", "마하 끝", "-"),
                    _f("number", "/mission_template/trim_grid/mach/step", "마하 간격", "-"),
                    _f("numlist", "/mission_template/trim_grid/alt", "고도 목록", "m"),
                    _f("numlist", "/mission_template/trim_grid/fuel", "연료 목록", "kg"),
                ]),
                _group("/mission_template/envelope", "엔벨로프 폼", fields=[
                    _f("number", "/mission_template/envelope/alt", "선도 고도", "m"),
                    _f("number", "/mission_template/envelope/fuel", "선도 연료", "kg"),
                    _f("number", "/mission_template/envelope/scan_mach/from", "스캔 마하 시작", "-"),
                    _f("number", "/mission_template/envelope/scan_mach/to", "스캔 마하 끝", "-"),
                    _f("number", "/mission_template/envelope/scan_mach/step", "스캔 마하 간격", "-"),
                    _f("numlist", "/mission_template/envelope/scan_alt", "스캔 고도 목록", "m"),
                ]),
                _group("/mission_template/sim", "시뮬 기본 미션 (발사 → 장주 → 착륙)", fields=[
                    _f("number", "/mission_template/sim/fuel", "시작 연료", "kg"),
                    _f("number", "/mission_template/sim/fuel_flow", "연료 소모율", "kg/s"),
                    _f("number", "/mission_template/sim/t_end", "시뮬 시간", "s"),
                    _f("number", "/mission_template/sim/accept_radius", "웨이포인트 도달 반경", "m"),
                    _group("/mission_template/sim/climb", "발사·상승", fields=[
                        _f("number", "/mission_template/sim/climb/speed", "속도 명령", "m/s"),
                        _f("number", "/mission_template/sim/climb/pitch", "피치 명령", "rad"),
                        _f("number", "/mission_template/sim/climb/exit_alt", "상승 종료 고도", "m"),
                    ]),
                    _group("/mission_template/sim/cruise", "순항 (경로 추종)", fields=[
                        _f("number", "/mission_template/sim/cruise/speed", "속도 명령", "m/s"),
                        _f("number", "/mission_template/sim/cruise/alt", "고도 명령", "m"),
                    ]),
                    _group("/mission_template/sim/approach", "접근", fields=[
                        _f("number", "/mission_template/sim/approach/speed", "속도 명령", "m/s"),
                        _f("number", "/mission_template/sim/approach/hdot", "강하율 명령", "m/s"),
                        _f("number", "/mission_template/sim/approach/exit_alt", "플레어 개시 고도", "m"),
                    ]),
                    _group("/mission_template/sim/flare", "플레어", fields=[
                        _f("number", "/mission_template/sim/flare/speed", "속도 명령", "m/s"),
                        _f("number", "/mission_template/sim/flare/hdot", "강하율 명령", "m/s"),
                    ]),
                    _f("number", "/mission_template/sim/rollout_m", "접지 후 미끄럼 거리 (실측)", "m", nullable=True,
                       help="활주로 안에 서려면 얼마나 앞에 접지해야 하는지를 화면이 재는 값 — 없으면 그 안내를 내지 않는다"),
                ]),
            ]),
        ]),
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "meta_keys": list(META_KEYS),
        "sections": sections,
        "registry": {c: list(reg.names(c)) for c in ("propulsion", "actuator")},
        "aero_forms": {k: list(v) for k, v in AERO_FORMS.items()},
        "term_inputs": list(TERM_INPUTS),
        "term_extra_inputs": [{"form": f, "coef": c, "inputs": list(i)}
                              for (f, c), i in TERM_EXTRA_INPUTS.items()],
        "dispersion_tags": {t: {"coef": c, "input": i} for t, (c, i) in DISPERSION_TAGS.items()},
        # 공력 항 k를 표로 줄 때 — 축 이름·외삽 정책 (CSV 반입이 이 이름을 머리줄로 쓴다)
        "table_axes": list(TABLE_AXES),
        "table_policies": list(TABLE_POLICIES),
        # 공력 DB 뷰어(POST /profiles/aero-slice)가 받는 축·내는 계수·점 수 상한 — 뷰어 칸이 이것으로 선다
        "slice": {"axes": list(SLICE_AXES), "coefficients": list(COEFFICIENTS), "max_points": MAX_POINTS},
    }
