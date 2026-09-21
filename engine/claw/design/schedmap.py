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
  roll_rate는 롤 수렴 모드 대역폭 λ_roll — 관례적 절대 합격선이 없어 **그 실행의
  튜닝 목표 대비 비율**로 잰다(judge_bandwidth). 종전에는 상수 "ok"라 보간이 λ를
  얼마나 놓치든 통과였다 — 절대 실패할 수 없는 판정이 자리 하나를 차지했다
- 자세 자리: PI 개루프 마진(레이트 폐쇄 후) — judge(PM/GM), 방향 자동 결정

스케줄 항목은 Table이든 다항(PolySchedule spec)이든 `axis_names` + `interp(**좌표)`
덕 타이핑으로 소비한다 (blocks/lookup.py의 Table 소비와 같은 원칙).

검증점 생성 기본값(05 §3 — 01 §3.4 [TBD] "보간 구간 검증점 밀도"의 확정): breakpoint 이상
역할 점의 축정렬 인접쌍마다 등간 내분점 n_between개(기본 1 = 중점, v1.41 파라미터화 —
라운드 우선 순서라 예산이 끊겨도 구간당 1점이 먼저 찬다). anchor는 breakpoint 역할을
겸하므로(points.at_least 서열) 트림 앵커 인접 구간의 검증점도 함께 나온다.

점의 세 상태를 구분해 낸다 (종전에는 뒤 둘이 한 덩어리였다):
- 트림 수렴 + 엔벨로프 안 → 정상 판정, 실패는 처방으로
- 트림 수렴 + 포화·α 여유 미달 → `outside_envelope` — 마진은 내되 실패 목록에서 제외
- 트림 미수렴 → loops 비움 (판정 불가)
"""

import math

from claw.common.contracts import TrimCase
from claw.design.closure import (
    AXIS_SPECS,
    att_margin_loop,
    axis_metrics,
    close_rates,
    oriented_margins,
    rate_loop_crossover,
)
from claw.design.points import (
    ROLE_BREAKPOINT,
    ROLE_VALIDATION,
    OperatingPoint,
    case_name,
    envelope_ok,
)
from claw.design.tune import TuneTargets
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
    lm_full, tables, design, case, *, criteria=None, targets=None,
    actuator_wn=None, actuator_zeta=None, delay_s=0.0, pade_order=2,
    rate_filters=None,
) -> dict:
    """한 운영점의 스케줄 인지 검증 — {자리명: 지표+판정}.

    반환 자리: pitch_rate(ζ_sp)·pitch_att(마진)·yaw_rate(ζ_dr)·roll_rate(λ_roll)·
    roll_att(마진). 자세 마진은 실효 게인 전부 0이면 note로 분리 보고한다
    (0 위장 금지 — openloop의 제로 개루프 관례).

    targets는 **λ 판정에만** 쓴다 — 롤 대역폭은 관례적 절대 합격선이 없어 요구가
    그 실행의 튜닝 목표에서 온다 (criteria.judge_bandwidth). 생략하면 기본값이라
    tune_point과 같은 목표를 쓴다.
    """
    targets = targets if targets is not None else TuneTargets()
    lon, lat = split_axes(lm_full)
    eff = scheduled_gains(tables, design, case)
    act_kw = dict(
        actuator_wn=actuator_wn, actuator_zeta=actuator_zeta,
        delay_s=delay_s, pade_order=pade_order,
        # 법칙에 있는 레이트 필터 — 검증이 튜닝과 같은 플랜트를 봐야 한다 (05 §6)
        rate_filters=dict(rate_filters or {}),
    )
    out = {}
    for lm_axis in (lon, lat):
        spec = AXIS_SPECS[lm_axis.axis]
        rate_gains = {
            f"{g}.k_rate": eff.get(f"{g}.k_rate", 0.0) for g, _, _ in spec["rates"]
        }
        metrics = axis_metrics(lm_axis, rate_gains, act_kw.get("rate_filters"))
        for idx, (group, x_rate, u_in) in enumerate(spec["rates"]):
            k = rate_gains[f"{group}.k_rate"]
            # 튜닝(tune._tune_rates)과 같은 플랜트에서 잰다 — 앞서 닫은 레이트까지
            # 접은 A′. 여기만 생 모델로 재면 같은 형상의 ωc가 설계·검증에서 갈린다
            prior = {f"{g}.k_rate": rate_gains[f"{g}.k_rate"]
                     for g, _, _ in spec["rates"][:idx]}
            wc = rate_loop_crossover(
                close_rates(lm_axis, prior, act_kw.get("rate_filters")),
                group, x_rate, u_in, k, **act_kw
            )
            entry = {"gains": {"k_rate": k}, "wc": wc}
            if group == "roll":
                # 종전에는 여기가 **상수 "ok"**였다 — λ를 목표와 비교조차 하지 않아
                # (entry에 target도 없었다) 스케줄 보간이 롤 대역폭을 얼마나 놓치든
                # 통과였고, 그래서 이 자리는 **절대 실패할 수 없는 판정**을 하나씩
                # 보태 judged 수를 부풀렸다. 데모 손설계 스케줄에서 M0.2/h0 두 점이
                # 목표의 0.68~0.72배인데 종전에는 ok로 찍혔다
                entry["kind"] = "bandwidth"
                entry["roll_lambda"] = metrics["roll_lambda"]
                entry["roll_unstable"] = bool(metrics.get("roll_unstable", False))
                entry["participation"] = metrics.get("roll_participation")
                entry["target"] = targets.roll_lambda
                if criteria is not None:
                    entry["status"] = criteria.judge_bandwidth(
                        metrics["roll_lambda"], targets.roll_lambda,
                        unstable=entry["roll_unstable"],
                        participation=entry["participation"],
                    )
            else:
                zeta = metrics["zeta_sp"] if lm_axis.axis == "lon" else metrics["zeta_dr"]
                entry["kind"] = "damping"
                entry["zeta"] = zeta
                if criteria is not None:
                    entry["status"] = criteria.judge_damping(zeta)
            _apply_sign_check(entry, eff, design, [f"{group}.k_rate"])
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
        if orient != 1:
            # 루프를 뒤집어야만 PM>0 — 실효 게인 부호가 플랜트와 반대(양의 되먹임)다. 설계 부호와의 대조
            # (_apply_sign_check)는 설계 부호가 맞다는 전제라, 설계부터 틀렸거나 0이면 못 잡는 자리다
            entry["sign_mismatch"] = True
            entry["status"] = "fail"
            entry["note"] = ("루프를 뒤집어야만 위상여유가 난다 — 실효 게인 부호가 플랜트와 반대다(양의 되먹임)."
                             " 마진 수치는 뒤집은 루프의 값이라 건강해 보인다")
        _apply_sign_check(entry, eff, design, [f"{group}.kp", f"{group}.ki"])
        out[f"{group}_att"] = entry
    return out


def _apply_sign_check(entry: dict, eff: dict, design: dict, slots) -> None:
    """실효 게인이 **설계 부호와 반대**면 판정을 fail로 내린다.

    `oriented_margins`는 PM>0이 되는 방향을 골라 준다 — 자리마다 설계 부호가 달라
    (피치 kp<0·롤 kp>0) 고정 sign으로는 절반이 음의 DC 루프가 되기 때문이다.
    그런데 그 되뒤집기가 **부호가 뒤집힌 게인까지 건강해 보이게 만든다**: 적합이
    링잉을 내 breakpoint 사이에서 kp가 설계와 반대로 나오면, 실제 기체에서는 양의
    되먹임인데 화면에는 멀쩡한 PM이 뜬다. 부호는 설계값이 보유한다는 전제
    (conventions·fcl/demo)가 깨진 것이므로 마진 수치와 무관하게 결함이다.
    """
    flips = [
        slot for slot in slots
        if design.get(slot, 0.0) and eff.get(slot, 0.0)
        and math.copysign(1.0, design[slot]) != math.copysign(1.0, eff[slot])
    ]
    if flips:
        entry["sign_flip"] = flips
        entry["status"] = "fail"
        entry["note"] = (
            f"실효 게인 부호가 설계와 반대: {', '.join(flips)} — 양의 되먹임이다"
            " (마진 수치는 방향 보정 후 값이라 건강해 보일 수 있다)"
        )


def midpoint_validation_points(points, *, n_between: int = 1) -> list:
    """breakpoint 이상 역할 인접쌍의 검증점 — 구간당 n_between개 등간 내분점 (05 §3).

    기본 1 = 종전 중점과 동일. 반환은 **라운드 우선**(전 구간의 1번째 점 → 2번째 …)
    이다 — VERIFY가 예산 소진 시 목록 앞에서 끊으므로, 밀도를 올려도 "구간당 최소
    1점" 커버리지가 한 구간의 2·3번째 점보다 먼저 찬다. 각 라운드 안에서 내분점은
    중점에서 가까운 순(k = ⌈n/2⌉, … 바깥쪽)으로 — **홀수 n**에서는 첫 라운드가 곧
    종전 중점이라 기존 검증점 좌표가 이름째 재사용된다(트림 캐시 적중). 짝수 n은
    등간 내분점에 중점(t=½)이 없어 좌표가 전부 새로 잡힌다 (리뷰 정정).
    이미 있는 좌표는 만들지 않는다. origin은 `midpoint:` 접두 유지(coverage 집계 키).
    """
    if n_between < 1:
        raise ValueError(f"n_between은 1 이상: {n_between}")
    # 중점 우선 라운드 순서 — n=3이면 [2, 1, 3]/(3+1): 중점, 안쪽, 바깥쪽
    ks = sorted(range(1, n_between + 1), key=lambda k: abs(2 * k - (n_between + 1)))
    out = []
    seen = set(points.names())
    pairs = [(points.get(a).case, points.get(b).case, a, b)
             for a, b, _axis in points.adjacent_pairs(ROLE_BREAKPOINT)]
    for k in ks:
        t = k / (n_between + 1.0)
        for ca, cb, a, b in pairs:
            pt = {
                "mach": ca.mach + (cb.mach - ca.mach) * t,
                "alt": ca.alt + (cb.alt - ca.alt) * t,
                "fuel": ca.fuel + (cb.fuel - ca.fuel) * t,
            }
            name = case_name(pt["mach"], pt["alt"], pt["fuel"])
            if name in seen:
                continue
            seen.add(name)
            out.append(OperatingPoint(
                case=TrimCase(name=name, mach=pt["mach"], alt=pt["alt"], fuel=pt["fuel"]),
                role=ROLE_VALIDATION,
                origin=f"midpoint:{a}|{b}",
            ))
    return out


def scheduled_margin_map(
    aircraft, points, lms, tables, design, *,
    criteria, targets=None, trims=None, fingerprint="",
    actuator_wn=None, actuator_zeta=None, delay_s=0.0, pade_order=2,
    rate_filters=None, on_progress=None,
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
            # 종전에는 `converged`만 보고 True를 박았다 — 그래서 **트림은 되지만
            # 포화·α 여유가 미달인 중점 검증점**이 엔벨로프 안으로 취급돼 판정·승격·
            # 튜닝까지 흘러갔다. 같은 조건의 coarse 앵커는 TUNE이 건너뛰는데 두 경로가
            # 갈렸다. 판정은 한 헬퍼가 한다 (points.envelope_ok)
            if pt.trimmable is None:
                pt.trimmable = envelope_ok(tr)
            lm = lms.get(aircraft, tr)
            entry = {
                "role": pt.role,
                "loops": scheduled_margin_point(
                    lm, tables, design, pt.case, criteria=criteria, targets=targets,
                    actuator_wn=actuator_wn, actuator_zeta=actuator_zeta,
                    delay_s=delay_s, pade_order=pade_order,
                    rate_filters=rate_filters,
                ),
            }
            # 트림은 수렴했으나 포화·α 여유 미달 = 엔벨로프 실경계. 마진은 참고로 내되
            # **처방 대상에서는 뺀다** — 튜닝(tune_points)이 이미 이 점을 건너뛰므로
            # 스케줄은 애초에 이 조건을 덮으라고 요구받은 적이 없다. 그런데도 채점만
            # 하면 처방이 나오는데, 앵커로 승격해도 TUNE이 다시 건너뛰어 게인 샘플이
            # 하나도 안 늘어난다 — 반영해도 결과가 그대로인 카드를 사용자에게 계속
            # 내미는 셈이다(래칫·예산으로만 겨우 멈춘다). 판정 자체는 남긴다:
            # 엔벨로프 경계의 마진은 "왜 여기가 경계인가"의 자료다
            if pt.trimmable is False:
                entry["outside_envelope"] = True
                entry["note"] = (
                    "포화·α 여유 미달 — 엔벨로프 실경계다. 마진은 참고값이며 처방·수렴"
                    " 판정에서 제외한다 (튜닝도 이 점을 건너뛴다)"
                )
            cases[name] = entry
        if on_progress is not None and on_progress(done, total, f"margin {name}"):
            aborted = "cancelled"
            break

    return {
        "cases": cases,
        "aborted": aborted,
        "criteria": criteria.to_dict(),
        "criteria_fingerprint": criteria.fingerprint(),
        "failures": _worst_failures(cases, criteria),
    }


_STATUS_RANK = {"ok": 0, "warn": 1, "fail": 2}


def margin_delta(cases_before: dict, cases_after: dict, criteria) -> dict:
    """두 마진맵 `cases`의 (점, 자리)별 판정 대조 — 표현을 바꿔 재판정하면 무엇이 움직였나.

    반출 표(재양자화 Table)가 검증받은 다항과 판정이 갈리는 자리를 세는 용도(05 §5.1).
    양쪽 다 판정(ok·warn·fail)이 있는 자리만 센다 — na·미수렴은 "판정 불가"지 변화가
    아니다. 단 **판정이 있다가 없어진 자리**(예: 재양자화 게인에서 교차 소멸)는 조용히
    빼면 fail→na가 델타에서 사라지므로 dropped로 따로 센다 (0 위장 금지 — 리뷰 지적).
    changed에는 등급이 움직인 자리만 수치를 동봉한다(criteria.severity — 비유한은
    None으로: JSON에 inf를 싣지 않는다). 전 자리 수치 덤프는 저장물만 불린다.

    엔벨로프 밖(포화·α 여유 미달) 점은 **판정 우주 자체에서** 뺀다 — `_worst_failures`·
    `judged_count`와 같은 이유다(그 점의 fail에는 반영해도 듣지 않는다). before·after
    어느 쪽에서든 엔벨로프 밖이면 그 점은 세지 않는다: n_judged·changed·worse·better는
    물론 dropped에도 안 잡힌다(dropped는 "판정하다 못하게 된" 것이지 "애초에 판정
    대상이 아니었던" 것이 아니다). 안 빼면 재양자화로 한 점이 엔벨로프 경계를 넘나들
    때마다 행동 불가능한 판정 변화가 "나빠짐/좋아짐"으로 섞여 든다.
    """
    n_judged = 0
    changed = []
    worse = better = dropped = 0
    for name, entry_b in cases_before.items():
        entry_a = cases_after.get(name)
        if entry_a is None:
            # 케이스가 통째로 빠진 경우 — 그 안의 판정 자리도 소실이다. 유일 호출자
            # (reverify_resampled)는 같은 점집합이라 도달 불가지만 공개 API라 다음
            # 소비자가 밟는 자리다 (리뷰 지적 — 자리 단위 소실과 같은 규약).
            # 엔벨로프 밖 점은 여기서도 제외 원칙 그대로다
            if not entry_b.get("outside_envelope"):
                dropped += sum(1 for m in entry_b.get("loops", {}).values()
                               if _STATUS_RANK.get(m.get("status")) is not None)
            continue
        if entry_b.get("outside_envelope") or entry_a.get("outside_envelope"):
            continue
        loops_a = entry_a.get("loops", {})
        for loop_name, m_b in entry_b.get("loops", {}).items():
            m_a = loops_a.get(loop_name)
            rank_b = _STATUS_RANK.get(m_b.get("status"))
            rank_a = None if m_a is None else _STATUS_RANK.get(m_a.get("status"))
            if rank_b is not None and rank_a is None:
                dropped += 1  # 전엔 판정, 후엔 판정 불가 — 변화가 아니라 소실이다
                continue
            if rank_b is None or rank_a is None:
                continue
            n_judged += 1
            if rank_a == rank_b:
                continue
            if rank_a > rank_b:
                worse += 1
            else:
                better += 1
            sev_b = criteria.severity(m_b)
            sev_a = criteria.severity(m_a)
            changed.append({
                "case": name, "loop": loop_name,
                "from": m_b["status"], "to": m_a["status"],
                "severity_from": sev_b if math.isfinite(sev_b) else None,
                "severity_to": sev_a if math.isfinite(sev_a) else None,
            })
    return {"n_judged": n_judged, "changed": changed, "worse": worse,
            "better": better, "dropped": dropped}


def _worst_failures(cases: dict, criteria) -> list:
    """fail 판정 (점, 자리) 목록 — 심각 순. 분류기(classify)의 작업 목록.

    심각도는 `criteria.severity` — 요구선 대비 **부족 비율**이라 자리 종류(PM·GM·
    ζ·λ)가 섞여도 한 축에서 비교된다. 크기가 곧 심각도이므로 내림차순이다.
    부족량 레코드(shortfall)를 함께 실어 분류기·원장이 다시 계산하지 않게 한다.

    엔벨로프 밖(포화·α 여유 미달) 점은 제외한다 — 그 점의 fail에는 반영해도 듣지
    않는 처방밖에 낼 수 없다(위 outside_envelope 주석). 목록이 곧 작업 목록이므로
    여기서 빼는 것이 곧 "처방·수렴 판정에서 제외"다.
    """
    out = []
    for name, entry in cases.items():
        if entry.get("outside_envelope"):
            continue
        for loop_name, m in entry["loops"].items():
            if m.get("status") == "fail":
                out.append({
                    "case": name, "loop": loop_name, "kind": m.get("kind"),
                    "pm_deg": m.get("pm_deg"), "gm_db": m.get("gm_db"),
                    "zeta": m.get("zeta"), "roll_lambda": m.get("roll_lambda"),
                    "shortfall": criteria.shortfall(m),
                    "severity": criteria.severity(m),
                })
    return sorted(out, key=lambda f: f["severity"], reverse=True)
