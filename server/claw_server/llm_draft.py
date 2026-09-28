"""미션 초안 프롬프트 — 규칙·무대는 고정, **기체 사실·기본 미션 예시는 고른 기체 문서에서** (06 §8).

종전 시스템 프롬프트는 예제 기체(200 kg급)의 실속·발사 이탈·순항·선회 반경과 그 기체의 완주 예시를 글로
박아 두었다 — 다른 기체를 고르면 LLM이 남의 기체 수치로 초안을 짰다(기체 고정 금지 원칙 위반). 이제
라우트가 요청의 기체 선택(`profile`)을 해석해 이 모듈에 넘기고, 여기서 그 기체의 문서로 기체 절과 예시를
세운다. 값은 전부 문서(적용 문서 — 형상 변형 반영)나 엔진 계산(V-n 선도의 1g 실속속도)에서 온다 —
문서에 없는 칸(레일·지상장치·미션 템플릿·설계 게인)은 없다고 말하고, 남의 값으로 채우지 않는다.

도달 반경(규칙 8)은 기체에서 잰다 — 마지막 웨이포인트 **넘김 거리** V_cruise²/(g·kp_hdg)(순항 속도는 미션 템플릿,
kp_hdg는 조립이 순항에서 쓰는 헤딩 게인). 종전 "선회 반경의 1/4 아래로 줄이지 않는다"는 근거 없는 규칙이었고, 쇼케이스
기체는 그 절반(100 m)에서 중심선을 지나 20~24 m 옆에 내렸다(215 m = 넘김 거리에서 1 m 안). 템플릿은 문서 작성자가 적은
값이라 "이 기체에 맞춰 잰"이라고 말하지 않는다 — 문서에 그 기록이 없다.

**예시는 시뮬 탭 기본 미션과 같은 조립이다** — 모드 골격은 web lib/simrequest.js `defaultModeRows`, 속도·
고도·강하율은 기체 문서 `mission_template.sim`, 장주 웨이포인트는 `defaultWpRows`의 활주로 축 좌표.
장주·활주로는 기체가 아니라 무대·시나리오라 여기 사본을 두되, 테스트(test_llm_draft.py)가 웹 원문과
활주로 정본(data/geo/goheung-runway.json)에 대조한다 — 어느 한쪽만 고치면 빨개진다.
"""

import json
import math

from claw.analysis import vn_envelope
from claw.common.constants import G0
from claw.env import isa_atmosphere
from claw.profile import ProfileError

# 도달 반경 ↔ 넘김 거리 허용 비율 — 이 안이면 "같다"고 말한다(엔진 test_profile_showcase HANDOVER_TOL과 같은 자)
HANDOVER_TOL = 0.1

# ── 무대 (기체 무관 — 고흥 시험장 실측, data/geo/goheung-runway.json) ─────────────
# 원점·방위는 도색 중심선 위 (2026-09-27 보정 — 종전 34.601303 / 127.212067 · 0.05964, centerline_correction)
RUNWAY_HEADING_RAD = 0.05682  # 진방위 3.256°
RUNWAY_LENGTH_M = 1205
ORIGIN_LAT_DEG = 34.601301
ORIGIN_LON_DEG = 127.212107
TERRAIN_CORE_M = 12000  # 지형 팩 core 반경

# 시뮬 탭 기본 장주 — 활주로 축 좌표 (along 시단에서 방위 방향, cross 그 오른쪽) [m]. web lib/simrequest.js
# defaultWpRows의 사본(이륙 구간 → 크로스윈드 → 다운윈드 → 베이스 → 파이널 진입)
PATTERN_AXIS_M = ((3500, 0), (3500, 900), (-5800, 900), (-5800, 0), (-4400, 0))


def js_num(x) -> str:
    """수 → 웹 `String(number)`와 같은 글 — 정수값은 소수점 없이(44.0 → "44"). 예시가 폼 칸 글 그대로다."""
    x = float(x)
    return str(int(x)) if x.is_integer() else repr(x)


_HDG = js_num(RUNWAY_HEADING_RAD)  # 웹 RUNWAY_HDG = String(GOHEUNG.runwayHeadingRad)


def _axis_wp(along: float, cross: float) -> dict:
    """활주로 축 좌표 → NED 행 — 웹 axisWp와 같은 식·같은 반올림(Math.round = floor(x + 0.5))."""
    c, s = math.cos(RUNWAY_HEADING_RAD), math.sin(RUNWAY_HEADING_RAD)
    return {"n": str(math.floor(along * c - cross * s + 0.5)),
            "e": str(math.floor(along * s + cross * c + 0.5)), "d": ""}


def heading_gain(built, sim) -> dict | None:
    """순항에서 실제로 도는 헤딩 비례 게인 — {kp, ki, mach, scheduled} 또는 None(게인 미설계).

    조립(assemble_law)이 쓰는 표를 따른다: 확정 표가 있으면 그 표, 없으면 규칙 스케줄의 자리들이다. heading.kp가
    그 안에 있으면 순항 마하(순항 속도 ÷ 순항 고도 음속)의 표 값, 없으면 설계 상수다. 낡은 확정 표는 조립이
    거부하므로(시뮬이 안 돈다) 설계 상수로 말한다."""
    design = built.doc["law"]["design"]
    if design is None:
        return None
    ap = design["autopilot"]
    out = {"kp": float(ap["kp_hdg"]), "ki": float(ap["ki_hdg"]), "mach": None, "scheduled": False}
    gt, sched = built.doc["law"]["gain_tables"], built.doc["law"]["schedule"]
    names = set(gt["tables"]) if gt is not None else set(sched["scheduled"] if sched else ())
    if "heading.kp" not in names or sim is None:
        return out
    mach = sim["cruise"]["speed"] / isa_atmosphere(sim["cruise"]["alt"]).a
    try:
        table = (built.confirmed_gain_tables() if gt is not None else built.gain_tables(["heading.kp"]))["heading.kp"]
    except (ProfileError, ValueError):
        return out
    out.update(kp=float(table.interp(mach=mach)), mach=mach, scheduled=True)
    return out


def aircraft_facts(built) -> dict:
    """초안이 알아야 할 기체 사실 — 전부 적용 문서(형상 변형 반영)와 엔진 계산에서. 없는 칸은 None.

    v_s는 V-n 선도의 1g 실속속도(해면·미션 연료 — 템플릿이 없으면 연료 만재, 타면 0° 공력)다. 엔벨로프 탭이
    그리는 값과 같은 엔진 계산이고, 트림 타면 몫은 빠져 있다."""
    doc = built.doc
    m, s = doc["mass"], doc["structural"]
    tpl = doc["mission_template"]
    sim = tpl["sim"] if tpl else None
    design = doc["law"]["design"]
    phi = design["autopilot"].get("phi_max") if design else None
    rail = doc["ground"]["rail"]
    fuel = sim["fuel"] if sim else m["fuel_max"]
    env = vn_envelope(built.aircraft(), built.stall_table(), built.structural_limits(), alt=0.0, fuel=fuel,
                      alpha_margin=doc["law"]["alpha_margin"], neg_alpha_ratio=built.neg_alpha_ratio)
    a0 = isa_atmosphere(0.0).a
    cruise = sim["cruise"]["speed"] if sim else None
    hdg = heading_gain(built, sim)
    # 마지막 웨이포인트 넘김 거리 V²/(g·kp_hdg) — 경로 추종(순수추적)은 마지막 점을 겨눈 채 다음 모드에 넘기고,
    # 방위만 잡는 모드(접근)의 헤딩 루프 φ = kp_hdg·Δψ가 협조선회 ψ̇ = g·φ/V로 시정수 V/(g·kp_hdg)에 가라앉는 동안
    # 옆으로 흐른다. 도달 반경이 이 거리면 가라앉는 순간 새 방위의 선(활주로 중심선) 위다 — 쇼케이스 기체 실측:
    # 100 m(이 거리의 절반)에서 중심선을 지나 20~24 m 옆, 215 m(= 이 거리)에서 1 m 안에 접지했다
    handover = (cruise ** 2 / (G0 * hdg["kp"])
                if cruise is not None and hdg is not None and hdg["kp"] > 0 else None)
    return {
        "name": built.name, "id": built.id, "variant": built.variant,
        "mass_max": m["m_empty"] + m["fuel_max"], "m_empty": m["m_empty"], "fuel_max": m["fuel_max"],
        "v_s": env["speeds"]["v_s"], "v_s_fuel": fuel,
        "mach_no": s["mach_no"], "v_no": s["mach_no"] * a0, "n_limit_pos": s["n_limit_pos"],
        "a0": a0,
        "rail": None if rail is None else {k: rail[k] for k in ("length", "elev_angle", "exit_speed")},
        "skid": doc["ground"]["skid"] is not None,
        "operating": dict(doc["operating"]),
        "phi_max": phi,
        "cruise_speed": cruise,
        "turn_radius": cruise ** 2 / (G0 * math.tan(phi)) if cruise is not None and phi else None,
        "heading": hdg,
        "handover": handover,
        "sim": sim,
    }


def example_draft(built) -> tuple:
    """기본 미션 예시 — (초안 dict, None) 또는 (None, 세우지 못한 사유).

    발사 레일에서 떠서 장주를 돌아 활주로에 서는 미션이라 레일·지상장치·미션 템플릿이 다 있어야 한다."""
    doc = built.doc
    missing = [what for what, ok in (("발사 레일", doc["ground"]["rail"] is not None),
                                     ("지상장치", doc["ground"]["skid"] is not None),
                                     ("미션 템플릿", doc["mission_template"] is not None)) if not ok]
    if missing:
        return None, (f"이 기체 문서에 {'·'.join(missing)}이(가) 없어 기본 미션(레일 발사 → 장주 → 착륙 정지) "
                      "예시를 세우지 않는다")
    s = doc["mission_template"]["sim"]
    v = {k: js_num(x) for k, x in (
        ("climbSpeed", s["climb"]["speed"]), ("climbPitch", s["climb"]["pitch"]),
        ("climbExitAlt", s["climb"]["exit_alt"]), ("cruiseSpeed", s["cruise"]["speed"]),
        ("cruiseAlt", s["cruise"]["alt"]), ("approachSpeed", s["approach"]["speed"]),
        ("approachHdot", s["approach"]["hdot"]), ("approachExitAlt", s["approach"]["exit_alt"]),
        ("flareSpeed", s["flare"]["speed"]), ("flareHdot", s["flare"]["hdot"]))}
    row = lambda name, speed, axis, value, heading, kind, arg, nxt: {  # noqa: E731
        "name": name, "speed": speed, "lonAxis": axis, "lonValue": value, "heading": heading,
        "exitKind": kind, "exitValue": arg, "next": nxt}
    modes = [  # web defaultModeRows와 같은 골격
        row("launch", v["climbSpeed"], "pitch", v["climbPitch"], _HDG, "off_rail", "", "climb"),
        row("climb", v["climbSpeed"], "pitch", v["climbPitch"], _HDG, "alt_ge", v["climbExitAlt"], "cruise"),
        row("cruise", v["cruiseSpeed"], "alt", v["cruiseAlt"], "path", "path_done", "", "approach"),
        row("approach", v["approachSpeed"], "hdot", v["approachHdot"], _HDG, "alt_le", v["approachExitAlt"], "flare"),
        row("flare", v["flareSpeed"], "hdot", v["flareHdot"], _HDG, "on_ground", "", "rollout"),
        row("rollout", "0", "pitch", "0", _HDG, "speed_le", "0.5", "stopped"),
        row("stopped", "0", "pitch", "0", "", "time_ge", "1e9", ""),
    ]
    return {
        "summary": "발사대에서 떠서 우선회 장주를 돌아 활주로 축에 정대하고 착륙해 정지",
        "assumptions": [f"순항 고도 {v['cruiseAlt']} m", f"순항 속도 {v['cruiseSpeed']} m/s"],
        "modeRows": modes,
        "wpRows": [_axis_wp(a, c) for a, c in PATTERN_AXIS_M],
        "runConditions": {"mach": "0", "alt": "0", "fuel": js_num(s["fuel"]), "groundOn": True, "launchOn": True,
                          "tEnd": js_num(s["t_end"]), "accept": js_num(s["accept_radius"])},
        "warnings": [],
    }, None


def _aircraft_section(f: dict) -> str:
    who = f"「{f['name']}」(id {f['id']}" + (f", 형상 변형 {f['variant']}" if f["variant"] else "") + ")"
    lines = [f"- {who} — 최대 이륙 {f['mass_max']:g} kg (빈 무게 {f['m_empty']:g} + 연료 {f['fuel_max']:g})."]
    if f["v_s"] is not None:
        lines.append(f"- 1g 실속속도 약 {f['v_s']:.1f} m/s (V-n 선도 — 해면·연료 {f['v_s_fuel']:g} kg, 타면 0° 공력이라 "
                     "트림 타면 몫은 빠져 있다). 명령 속도는 플레어·정지 외에는 이보다 넉넉히 위에 둔다.")
    lines.append(f"- 구조 순항 한계 M_NO {f['mach_no']:g} (해면 약 {f['v_no']:.0f} m/s) — 명령 속도는 이 아래로. "
                 f"제한 하중 +{f['n_limit_pos']:g} g.")
    r = f["rail"]
    if r is None:
        lines.append("- 발사 레일 없음 — launchOn은 false다(레일 발사·off_rail 종료를 쓰지 않는다).")
    else:
        ratio = f" = 실속속도의 {r['exit_speed'] / f['v_s']:.2f}배" if f["v_s"] else ""
        lines.append(f"- 발사 레일: 길이 {r['length']:g} m · 앙각 {math.degrees(r['elev_angle']):.0f}° · "
                     f"이탈속도 {r['exit_speed']:g} m/s{ratio}. launchOn=true면 레일에서 뜬다.")
    lines.append("- 지상장치(스키드) 있음 — 접지·활주 정지(on_ground·rollout)가 성립한다." if f["skid"] else
                 "- 지상장치 없음 — groundOn은 false이고 착륙(접지·정지) 미션은 만들 수 없다. 요청이 착륙이면 "
                 "warnings에 적는다.")
    if f["phi_max"] is None:
        lines.append("- 게인 미설계 — 뱅크 한계도 헤딩 게인도 모른다(시뮬 실행 전에 기체 탭 초기 게인이 필요하다). "
                     "선회는 넓게 잡고, 마지막 웨이포인트 넘김 거리(규칙 8)는 정할 수 없다.")
    elif f["turn_radius"] is not None:
        lines.append(f"- 뱅크 한계 {f['phi_max']:g} rad(설계 게인) — 순항 {f['cruise_speed']:g} m/s에서 선회 반경 "
                     f"약 {f['turn_radius']:.0f} m. 되돌기 한 번에 그 두 배 폭이 든다.")
    else:
        lines.append(f"- 뱅크 한계 {f['phi_max']:g} rad(설계 게인) — 선회 반경 = V²/(g·tan {f['phi_max']:g}).")
    h = f["heading"]
    if h is not None:
        at = (f"순항 마하 {h['mach']:.3f}의 스케줄 값 " if h["scheduled"] else "") + f"kp_hdg {h['kp']:.3g}"
        approx = " 헤딩 적분 게인이 있어(ki_hdg ≠ 0) 1차 근사다." if h["ki"] != 0.0 else ""
        if f["handover"] is not None:
            lines.append(f"- 마지막 웨이포인트 넘김 거리 약 {f['handover']:.0f} m = 순항 {f['cruise_speed']:g} m/s의 "
                         f"V²/(g·{at}) — 헤딩 루프 시정수 V/(g·kp_hdg) 약 {f['cruise_speed'] / (G0 * h['kp']):.1f} s "
                         f"동안 나는 거리다(규칙 8).{approx}")
        elif h["kp"] > 0:
            lines.append(f"- 마지막 웨이포인트 넘김 거리 = V²/(g·{at}) — V는 순항 속도(규칙 8).{approx}")
    lo, hi = f["operating"].get("alt_min"), f["operating"].get("alt_max")
    if lo is not None or hi is not None:
        lines.append(f"- 운용 고도 {'—' if lo is None else f'{lo:g}'} ~ {'—' if hi is None else f'{hi:g}'} m.")
    s = f["sim"]
    if s is None:
        lines.append("- 미션 템플릿 없음 — 속도·고도·강하율은 위 사실에서 보수적으로 정하고 assumptions에 적는다.")
    else:
        roll = f", 접지→정지 {s['rollout_m']:g} m(문서 기재)" if s.get("rollout_m") is not None else ""
        # 템플릿은 문서 작성자가 적은 값이다 — 이 기체로 재 봤다는 기록이 문서에 없으므로 그렇게 말하지 않는다
        # (종전 "이 기체에 맞춰 잰"은 사용자 문서에서 거짓이었다). 도달 반경은 넘김 거리와 대조해 말한다
        lines.append(
            f"- 미션 템플릿(이 기체 문서가 싣는 시뮬 탭 기본값 — 문서 작성자가 적은 값이다): 상승 "
            f"{s['climb']['speed']:g} m/s·피치 "
            f"{s['climb']['pitch']:g} rad → {s['climb']['exit_alt']:g} m, 순항 {s['cruise']['speed']:g} m/s·"
            f"{s['cruise']['alt']:g} m, 접근 {s['approach']['speed']:g} m/s·강하율 {s['approach']['hdot']:g} m/s → "
            f"{s['approach']['exit_alt']:g} m, 플레어 {s['flare']['speed']:g} m/s·{s['flare']['hdot']:g} m/s, "
            f"연료 {s['fuel']:g} kg, 도달 반경 {s['accept_radius']:g} m{_accept_vs_handover(f)}, "
            f"종료 {s['t_end']:g} s{roll}.")
    return "\n".join(lines)


def accept_matches_handover(f: dict) -> bool | None:
    """템플릿 도달 반경이 넘김 거리와 같은가(HANDOVER_TOL 안) — 둘 중 하나라도 없으면 None."""
    if f["sim"] is None or f["handover"] is None:
        return None
    return abs(f["sim"]["accept_radius"] / f["handover"] - 1.0) <= HANDOVER_TOL


def _accept_vs_handover(f: dict) -> str:
    ok = accept_matches_handover(f)
    if ok is None:
        return ""
    return " (= 넘김 거리)" if ok else f" (넘김 거리 약 {f['handover']:.0f} m와 다르다 — 규칙 8)"


def _air_start_hint(f: dict) -> str:
    """규칙 10의 공중 출발 예 — 이 기체의 순항 속도를 마하로 (없으면 환산식만)."""
    if f["cruise_speed"] is None:
        return f"mach를 양수(속도 ÷ 해면 음속 {f['a0']:.0f} m/s)"
    return f"mach를 양수(예: \"{f['cruise_speed'] / f['a0']:.3f}\"≈{f['cruise_speed']:g} m/s — 이 기체의 순항)"


_HEAD = """너는 CLAW 비행제어 설계툴의 미션 초안 생성기다. 사용자의 자연어
의도를 시뮬레이션 탭의 편집 표에 그대로 앉는 초안으로 바꾼다. 초안은 실행되지
않는다 — 사람이 표에서 다듬고 실행 버튼을 누르며, 틀린 값은 엔진이 거부한다.
그래도 첫 초안이 한 번에 완주 가능해야 이 기능이 뜻이 있다.

## 기체 (사용자가 고른 기체 문서에서 — 이 수치로 초안을 짠다)
"""

_STAGE = f"""
## 무대 (고정 사실)
- 무대는 고흥 시험장. NED 좌표(미터), 원점 = 활주로 남단 임계
  (위도 {ORIGIN_LAT_DEG}, 경도 {ORIGIN_LON_DEG}). 활주로는 원점에서 진방위 {RUNWAY_HEADING_RAD} rad
  ({math.degrees(RUNWAY_HEADING_RAD):.3f}°) 방향으로 {RUNWAY_LENGTH_M} m. 지형 팩 core가 반경 {TERRAIN_CORE_M // 1000} km라 웨이포인트는
  |n|, |e| ≤ {TERRAIN_CORE_M} 안에 두고, 벗어나면 warnings에 적는다.
- 각도는 전부 라디안. hdot(강하율)은 상승이 +라 강하는 음수다.
"""

_RULES = """
## 표의 의미 규칙 (위반하면 화면·엔진이 거부한다)
1. 모든 칸 값은 문자열이다. 빈 문자열 ""는 "그 축 끔"이다.
2. lonAxis(종방향 축)는 ""·alt·pitch·hdot 중 하나 — 모드마다 종방향 명령은
   딱 하나다. lonValue가 그 축의 값이다.
3. "path"는 두 곳에서만: heading 칸(수평 경로 추종), lonAxis가 alt일 때의
   lonValue(세로 프로파일 추종). pitch·hdot 칸의 "path"는 거부된다.
4. exitKind와 인자: time_ge·alt_ge·alt_le·speed_ge·speed_le·hdot_ge·hdot_le는
   exitValue에 수치가 필수다(빈 문자열이면 거부). always·path_done·on_ground·
   airborne·off_rail은 exitValue를 ""로 둔다.
5. next 사슬: 실행은 첫 행에서 시작해 next로만 넘어간다. 모든 행이 첫 행에서
   닿아야 한다 — 아무도 가리키지 않는 행은 절대 실행되지 않는다. 마지막 행은
   next를 ""로 둔다.
6. 웨이포인트 d(고도)는 전부 채우거나 전부 비운다. 비울 때는 ""로 둔다(화면이
   키를 지운다). 수평 경로만 따를 미션이면 d를 전부 비우는 쪽이 단순하다.
7. heading에 "path"를 쓴 모드가 있으면 wpRows가 비면 안 된다(엔진 거부).
   반대로 wpRows를 채웠는데 어느 모드도 "path"를 안 쓰면 기체는 웨이포인트를
   무시하고 직진한다 — 경로를 날라는 의도면 반드시 한 모드의 heading을
   "path"로 둔다. 세로 프로파일(d)까지 따르려면 그 모드의 lonAxis를 alt,
   lonValue를 "path"로 둔다.
8. accept(도달 반경)는 **마지막 웨이포인트에서 경로 추종이 다음 모드로 넘기는
   거리**다(중간 점은 선회 예상 거리가 더 크면 그만큼 앞에서 넘기고, accept는
   그 바닥이다). 경로 추종은 점을 겨누는 순수추적이라 마지막 점을 겨눈 채 넘기고,
   다음 모드가 방위만 잡으면(접근) 헤딩 루프가 시정수 V/(g·kp_hdg)로 새 방위에
   가라앉는 동안 옆으로 흐른다. 도달 반경이 기체 절의 넘김 거리 V²/(g·kp_hdg)와
   같아야 가라앉는 순간 그 점과 새 방위가 만드는 선(착륙이면 활주로 중심선) 위에
   선다 — 작으면 선을 지나쳐 반대편에, 크면 못 미친 쪽에 선다. 착륙 장주처럼
   마지막 점 뒤에 방위만 잡는 모드가 오면 accept를 넘김 거리로 둔다.
9. tEnd는 미션이 끝나는(착륙이면 정지) 시각을 여유 있게 덮어야 한다. 상한 3600.
10. 지상 출발(groundOn=true)이면 mach는 반드시 "0"이고 alt는 비행 고도가
    아니라 활주로 표고(기본 "0")다. launchOn=true면 발사대에서 뜬다.
    공중 수평비행에서 시작하려면 groundOn=false·launchOn=false로 두고
    {air_start}, alt를 시작 고도로 둔다.
11. 착륙(on_ground·접지·활주 정지)이 있는 미션은 groundOn=true여야 한다 —
    지면이 없으면 접지 판정 자체가 성립하지 않는다.
12. runConditions의 문자열 칸을 ""로 두면 화면의 현재 값이 유지된다. 확신이
    없는 칸은 ""로 두는 쪽이 낫다.

## 답하는 법
- summary는 초안이 무엇을 하는지 한 문장.
- assumptions에는 사용자가 말하지 않아 네가 정한 것을 전부 적는다(고도·속도·
  방향 등). warnings에는 요청을 그대로 못 지킨 것·위험한 값을 적는다.
- 모드 이름은 소문자 영문(launch·climb·cruise 등 관례)을 따른다.
"""


def _example_section(example, reason, f=None) -> str:
    if example is None:
        return f"\n## 기본 미션 예시\n없음 — {reason}. 위 기체 사실과 규칙만으로 짠다.\n"
    one = lambda x: json.dumps(x, ensure_ascii=False, separators=(",", ":"))  # noqa: E731
    head = {k: example[k] for k in ("summary", "assumptions")}
    body = [one(head)[:-1] + ",", '"modeRows":[',
            ",\n".join(one(r) for r in example["modeRows"]) + "],",
            f'"wpRows":{one(example["wpRows"])},',
            f'"runConditions":{one(example["runConditions"])},',
            f'"warnings":{one(example["warnings"])}' + "}"]
    # 예시는 시뮬 탭 기본 미션 그대로라 accept도 템플릿 값이다 — 넘김 거리와 다르면 그 사실을 붙여 규칙 8과
    # 예시가 서로 다른 말을 하지 않게 한다
    note = ("" if f is None or accept_matches_handover(f) is not False else
            f"예시의 accept {example['runConditions']['accept']}는 템플릿 값 그대로다 — 이 기체의 넘김 거리는 약 "
            f"{f['handover']:.0f} m라 착륙 장주 초안은 규칙 8대로 그 값을 쓴다.\n")
    return ("\n## 기본 미션 예시 (발사 → 상승 → 우선회 장주 순항(경로 추종) → 접근 → 플레어 → 착륙 정지)\n"
            "시뮬 탭 기본 미션과 같은 조립이다 — 속도·고도·강하율·연료는 이 기체의 미션 템플릿, 장주는 활주로 축.\n"
            + note + "\n".join(body) + "\n")


def draft_system(built) -> str:
    """고른 기체(BuiltProfile — 형상 변형 반영)의 미션 초안 시스템 프롬프트."""
    f = aircraft_facts(built)
    example, reason = example_draft(built)
    return (_HEAD + _aircraft_section(f) + "\n" + _STAGE + _RULES.replace("{air_start}", _air_start_hint(f))
            + _example_section(example, reason, f))

