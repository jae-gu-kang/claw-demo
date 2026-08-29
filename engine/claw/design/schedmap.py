"""스케줄 인지 마진맵 — 보간(또는 다항 평가) **실효 게인**으로 마진 재계산 (01 §3.4 [확정]).

기존 마진맵(routes/analysis.py)은 요청 상수 kp/ki를 전 케이스에 동일 적용한다 —
게인 스케줄이 있는 형상에서 "보간 구간 검증점" 마진은 그 경로로 성립하지 않는다.
케이스별 실효 게인은 pipeline/openloop.py `_effective_gain`이 이미 뽑지만
(테이블@케이스 보간) 작동기·지연을 포함하지 않는다. 여기는 그 둘을 결합한다:
실효 게인 × pi_loop 전체 조성(actuator 2차계 + Padé 지연).

루프 선언은 openloop.GROUP_LOOPS **재사용** (재선언 금지 — 웹 DEFAULT_LOOPS와의
정합을 test_openloop이 핀한다). 스케줄 항목은 Table이든 다항(PolySchedule의
구간별 다항 spec)이든 `axis_names` + `interp(**좌표)` 덕 타이핑으로 소비한다 —
LookupBlock이 Table을 소비하는 방식과 같은 원칙(blocks/lookup.py)이다.

검증점 생성 기본값(01 §3.4 [TBD] "보간 구간 검증점 밀도"의 확정): breakpoint 이상
역할 점의 축정렬 인접쌍마다 중점 1개. anchor는 breakpoint 역할을 겸하므로
(points.at_least 서열) 트림 앵커 인접 구간의 중점도 함께 나온다.
"""

import numpy as np

from claw.analysis import loop_margins, pi_loop
from claw.common.contracts import TrimCase
from claw.design.points import ROLE_BREAKPOINT, ROLE_VALIDATION, OperatingPoint, case_name
from claw.pipeline.openloop import GROUP_LOOPS
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
    lm_full, tables, design, case, *,
    loops=GROUP_LOOPS, criteria=None,
    actuator_wn=None, actuator_zeta=None, delay_s=0.0, pade_order=2,
) -> dict:
    """한 운영점의 스케줄 인지 마진 — {루프명: {gm_db, pm_deg, wcg, wcp, gains, status}}.

    openloop._effective_gain과 달리 actuator/delay를 pi_loop 전체 인자로 통과시킨다.
    실효 게인이 전부 0인 루프는 계산하지 않고 note로 분리 보고한다 (0 위장 금지).
    """
    lon, lat = split_axes(lm_full)
    models = {"lon": lon, "lat": lat}
    eff = scheduled_gains(tables, design, case)
    out = {}
    for group, specs in loops.items():
        for sp in specs:
            gains = {port: eff[f"{group}.{key}"] for port, key in sp["gains"].items()}
            if all(v == 0.0 for v in gains.values()):
                out[sp["name"]] = {
                    "note": "제로 개루프 — 이 케이스 실효 게인이 전부 0",
                    "gains": gains, "status": "na",
                }
                continue
            loop = pi_loop(
                models[sp["axis"]], x_out=sp["x_out"], u_in=sp["u_in"],
                kp=gains.get("kp", 0.0), ki=gains.get("ki", 0.0), sign=sp["sign"],
                actuator_wn=actuator_wn, actuator_zeta=actuator_zeta,
                delay_s=delay_s, pade_order=pade_order,
            )
            entry = loop_margins(loop)
            entry["gains"] = gains
            if criteria is not None:
                entry["status"] = criteria.judge(entry)
            out[sp["name"]] = entry
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
    """전 역할 점(anchor+breakpoint+validation)의 스케줄 인지 마진 + 판정.

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

    worst = _worst_failures(cases)
    return {
        "cases": cases,
        "aborted": aborted,
        "criteria": criteria.to_dict(),
        "criteria_fingerprint": criteria.fingerprint(),
        "failures": worst,
    }


def _worst_failures(cases: dict) -> list:
    """fail 판정 (점, 루프) 목록 — PM 부족량 큰 순. 분류기(classify)의 작업 목록."""
    out = []
    for name, entry in cases.items():
        for loop_name, m in entry["loops"].items():
            if m.get("status") == "fail":
                pm = m.get("pm_deg")
                out.append({
                    "case": name, "loop": loop_name,
                    "pm_deg": pm, "gm_db": m.get("gm_db"),
                })
    return sorted(
        out, key=lambda f: f["pm_deg"] if np.isfinite(f["pm_deg"]) else -np.inf
    )
