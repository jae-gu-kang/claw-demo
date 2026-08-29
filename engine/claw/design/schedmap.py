"""스케줄 인지 마진맵 — 보간(또는 다항 평가) **실효 게인**으로 검증 재계산 (01 §3.4 [확정]).

기존 마진맵(routes/analysis.py)은 요청 상수 kp/ki를 전 케이스에 동일 적용한다 —
게인 스케줄이 있는 형상에서 "보간 구간 검증점" 검증은 그 경로로 성립하지 않는다.
케이스별 실효 게인은 pipeline/openloop.py `_effective_gain`이 이미 뽑지만
(테이블@케이스 보간) 작동기·지연을 포함하지 않고, 평탄 SISO 선언(GROUP_LOOPS)은
절대 판정에 병리가 있다(closure.py 머리말 — 레이트 루프 DC 0 아티팩트, 자세
루프의 레이트 피드백 누락). 여기는 셋을 결합한다: 실효 게인 × successive
closure 조성(closure.py) × pi_loop 전체 조성(작동기 2차계 + Padé 지연).

판정 (criteria.py):
- 레이트 자리: 폐쇄 모드 감쇠 — pitch_rate는 ζ_sp, yaw_rate는 ζ_dr(judge_damping).
  roll_rate는 롤 수렴 모드 대역폭 λ_roll — 안정성 아닌 성능 지표라 정보 보고만
- 자세 자리: PI 개루프 마진(레이트 폐쇄 후) — judge(PM/GM), 방향 자동 결정

스케줄 항목은 Table이든 다항(PolySchedule spec)이든 `axis_names` + `interp(**좌표)`
덕 타이핑으로 소비한다 (blocks/lookup.py의 Table 소비와 같은 원칙).

검증점 생성 기본값(01 §3.4 [TBD] "보간 구간 검증점 밀도"의 확정): breakpoint 이상
역할 점의 축정렬 인접쌍마다 중점 1개. anchor는 breakpoint 역할을 겸하므로
(points.at_least 서열) 트림 앵커 인접 구간의 중점도 함께 나온다.
"""

import numpy as np

from claw.common.contracts import TrimCase
from claw.design.closure import (
    AXIS_SPECS,
    att_margin_loop,
    axis_metrics,
    oriented_margins,
    rate_loop_crossover,
)
from claw.design.points import ROLE_BREAKPOINT, ROLE_VALIDATION, OperatingPoint, case_name
from claw.trim import split_axes
from claw.trim.trim import trim_batch


def scheduled_gains(tables: dict, design: dict, case) -> dict:
    """자리별 케이스 실효 게인 — 스케줄 항목은 @케이스 평가, 아니면 설계 상수.

    tables: {"그룹.게인": Table 또는 다항 spec (axis_names+interp 덕 타이핑)}
    design: schedule.design_gains() 형식 {"그룹.게인": float} — 스케줄 안 덮는 자리의 정본.
    """
    coords = {"mach": case.mach, "alt": case.alt, "fuel": case.fuel}
    out = {}
    for name, value in design.items():
        tab = tables.get(name)
        if tab is None:
            out[name] = float(value)
        else:
            out[name] = float(tab.interp(**{ax: coords[ax] for ax in tab.axis_names}))
    return out


def scheduled_margin_point(
    lm_full, tables, design, case, *, criteria=None,
    actuator_wn=None, actuator_zeta=None, delay_s=0.0, pade_order=2,
) -> dict:
    """한 운영점의 스케줄 인지 검증 — {자리명: 지표+판정}.

    반환 자리: pitch_rate(ζ_sp)·pitch_att(마진)·yaw_rate(ζ_dr)·roll_rate(λ_roll,
    정보)·roll_att(마진). 자세 마진은 실효 게인 전부 0이면 note로 분리 보고한다
    (0 위장 금지 — openloop의 제로 개루프 관례).
    """
    lon, lat = split_axes(lm_full)
    eff = scheduled_gains(tables, design, case)
    act_kw = dict(
        actuator_wn=actuator_wn, actuator_zeta=actuator_zeta,
        delay_s=delay_s, pade_order=pade_order,
    )
    out = {}
    for lm_axis in (lon, lat):
        spec = AXIS_SPECS[lm_axis.axis]
        rate_gains = {
            f"{g}.k_rate": eff.get(f"{g}.k_rate", 0.0) for g, _, _ in spec["rates"]
        }
        metrics = axis_metrics(lm_axis, rate_gains)
        for group, x_rate, u_in in spec["rates"]:
            k = rate_gains[f"{group}.k_rate"]
            wc = rate_loop_crossover(lm_axis, group, x_rate, u_in, k, **act_kw)
            entry = {"gains": {"k_rate": k}, "wc": wc}
            if group == "roll":
                entry["kind"] = "bandwidth"
                entry["roll_lambda"] = metrics["roll_lambda"]
                entry["status"] = "ok"  # 성능 지표 — 안정성 판정은 ζ_dr·자세 마진 소관
            else:
                zeta = metrics["zeta_sp"] if lm_axis.axis == "lon" else metrics["zeta_dr"]
                entry["kind"] = "damping"
                entry["zeta"] = zeta
                if criteria is not None:
                    entry["status"] = criteria.judge_damping(zeta)
            out[f"{group}_rate"] = entry

        group, _x_out, _u_in = spec["att"]
        kp, ki = eff[f"{group}.kp"], eff[f"{group}.ki"]
        if kp == 0.0 and ki == 0.0:
            out[f"{group}_att"] = {
                "kind": "margin", "note": "제로 개루프 — 이 케이스 실효 게인이 전부 0",
                "gains": {"kp": kp, "ki": ki}, "status": "na",
            }
            continue
        loop = att_margin_loop(lm_axis, rate_gains, kp, ki, **act_kw)
        m, orient = oriented_margins(loop)
        entry = {"kind": "margin", **m, "orientation": orient, "gains": {"kp": kp, "ki": ki}}
        if criteria is not None:
            entry["status"] = criteria.judge(m)
        out[f"{group}_att"] = entry
    return out


def midpoint_validation_points(points) -> list:
    """breakpoint 이상 역할 인접쌍의 중점 검증점 — 이미 있는 좌표는 만들지 않는다."""
    out = []
    seen = set(points.names())
    for a, b, axis in points.adjacent_pairs(ROLE_BREAKPOINT):
        ca, cb = points.get(a).case, points.get(b).case
        mid = {
            "mach": (ca.mach + cb.mach) / 2.0,
            "alt": (ca.alt + cb.alt) / 2.0,
            "fuel": (ca.fuel + cb.fuel) / 2.0,
        }
        name = case_name(mid["mach"], mid["alt"], mid["fuel"])
        if name in seen:
            continue
        seen.add(name)
        out.append(OperatingPoint(
            case=TrimCase(name=name, mach=mid["mach"], alt=mid["alt"], fuel=mid["fuel"]),
            role=ROLE_VALIDATION,
            origin=f"midpoint:{a}|{b}",
        ))
    return out


def scheduled_margin_map(
    aircraft, points, lms, tables, design, *,
    criteria, trims=None, fingerprint="",
    actuator_wn=None, actuator_zeta=None, delay_s=0.0, pade_order=2,
    on_progress=None,
) -> dict:
    """전 역할 점(anchor+breakpoint+validation)의 스케줄 인지 검증 + 판정.

    trims: {이름: TrimResult} — 있는 것은 재사용, 없는 점은 서펜타인 순서로
    trim_batch(인접 시드) 후 병합한다 (호출자 dict를 제자리 갱신).
    on_progress(done, total, message) truthy 반환 = 협조적 취소 — 완료분 보존.
    """
    trims = trims if trims is not None else {}
    todo = [p for p in points if p.case.name not in trims]
    if todo:
        order = {c.name: i for i, c in enumerate(points.serpentine())}
        todo_cases = sorted((p.case for p in todo), key=lambda c: order[c.name])
        aborted = []

        def _trim_progress(done, total, tr):
            trims[tr.case.name] = tr
            if on_progress is not None and on_progress(done, total, f"trim {tr.case.name}"):
                aborted.append(True)
                return True
            return False

        trim_batch(aircraft, todo_cases, fingerprint=fingerprint, on_progress=_trim_progress)
        if aborted:
            return {"cases": {}, "aborted": "cancelled", "criteria": criteria.to_dict()}

    cases = {}
    aborted = None
    pts = points.at_least(ROLE_VALIDATION)
    total = len(pts)
    for done, pt in enumerate(pts, start=1):
        name = pt.case.name
        tr = trims[name]
        if not tr.converged:
            pt.trimmable = False
            cases[name] = {"role": pt.role, "note": "미수렴 트림 — 마진 판정 불가", "loops": {}}
        else:
            if pt.trimmable is None:
                pt.trimmable = True
            lm = lms.get(aircraft, tr)
            cases[name] = {
                "role": pt.role,
                "loops": scheduled_margin_point(
                    lm, tables, design, pt.case, criteria=criteria,
                    actuator_wn=actuator_wn, actuator_zeta=actuator_zeta,
                    delay_s=delay_s, pade_order=pade_order,
                ),
            }
        if on_progress is not None and on_progress(done, total, f"margin {name}"):
            aborted = "cancelled"
            break

    return {
        "cases": cases,
        "aborted": aborted,
        "criteria": criteria.to_dict(),
        "criteria_fingerprint": criteria.fingerprint(),
        "failures": _worst_failures(cases),
    }


def _severity(entry: dict) -> float:
    """fail 항목의 처리 순서 키 — 작을수록 심각. 마진 자리는 PM, 감쇠 자리는 ζ×90
    (0.3 합격선 ≈ 27 '도 상당' — 자리 종류가 섞여도 한 줄로 세우기 위한 근사 축)."""
    if "pm_deg" in entry:
        pm = entry["pm_deg"]
        return pm if np.isfinite(pm) else -np.inf
    return entry.get("zeta", 0.0) * 90.0


def _worst_failures(cases: dict) -> list:
    """fail 판정 (점, 자리) 목록 — 심각 순. 분류기(classify)의 작업 목록."""
    out = []
    for name, entry in cases.items():
        for loop_name, m in entry["loops"].items():
            if m.get("status") == "fail":
                out.append({
                    "case": name, "loop": loop_name, "kind": m.get("kind"),
                    "pm_deg": m.get("pm_deg"), "gm_db": m.get("gm_db"),
                    "zeta": m.get("zeta"), "severity": _severity(m),
                })
    return sorted(out, key=lambda f: f["severity"])
