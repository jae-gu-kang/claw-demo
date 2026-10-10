"""구간 처방 — 보강 구간의 절점·구간별 게인 조정 (05 §7 `tune_interval` · 05 §11.13 ⑤ 후속 ⑥).

새 최적화기가 아니다. 보강(⑤ — reinforce.py)이 남긴 구간 기록(reinforcement.intervals) 중 처방할 구간을 골라, 이미 있는
한 점 튜닝 경로(편입 → TUNE이 그 점의 자유 게인 최적을 표본으로)와 절점 추가(add_knot — 그 루프 표만, 05 §11.5)를 그
구간에 건다. 절점 값은 매 FIT에서 표본 lstsq로 다시 풀리므로(fit.table_on_knots) 값을 직접 덮어쓰는 층은 두지 않는다(보류).

- **트리거** — 잎 구간(status ≠ split) 중 자리별 d가 허용치를 넘음(exceeds — 양끝·중간이 다 통과여도 보간 형상이 어긋남)
  또는 판정 다름에 fail이 섞임(verdict_change ∧ fail). ok↔warn만 갈린 판정 다름은 보고만 한다(쇼케이스 보호 — 계약 결정)
- **처방** — 구간 중간점(d를 잰 점, 이미 트림·판정된 검증점)이 대상이다. exceeds면 add_knot(검증점이면 편입까지 — 표본이
  그 절점 값이 된다), 판정 다름만이면 편입만(형상은 맞고 표본이 모자람). 같은 점에 점 실패 카드가 있으면 그 카드가
  대신한다(superseded_by) — 같은 점을 두 번 편입할 수 없다
- **비퇴행 가드**(judge_remedy) — 재검증 뒤 (a) 구간 자기 점(양끝·중간)의 어느 자리도 등급이 오르지 않고 대상 자리가
  개선(등급 하락 · severity가 1e-3 넘게 감소 · 구간 d ≤ 허용치)됐으며 (b) 같은 행 좌우 이웃 구간의 대상 자리 등급이 오르지
  않고 (c) 전 요구영역의 앞뒤 모두 판정된 자리에서 ok|warn → fail 0 · 판정 소실 0(schedmap.margin_delta 재사용 — ok →
  warn은 허용하되 caution_regressions로 적는다)이어야 받아들인다. 재계획이 새로 세운 검증점은 비교 모집단이 아니다(다음
  보강의 입력)
- 위반이면 오케스트레이터가 **이터 전체**를 체크포인트로 되돌리고 그 처방을 한 번에 봉인한다(결정론이라 다시 내도 같다)

여기는 순수 함수다 — 체크포인트·되돌림·기록은 오케스트레이터(DesignSession)가 쥔다.
"""

from __future__ import annotations

import math

from claw.design.points import ROLE_VALIDATION
from claw.design.reinforce import _metric, _worst_status
from claw.design.schedmap import _STATUS_RANK, margin_delta
from claw.design.tune import LOOP_SLOTS

# 구간 처방 카드의 verdict — 05 §7 표의 interval_exceeds 행(점 실패 분류기 classify.VERDICTS와 별개다: 점이 아니라 구간의
# 판정이다)
INTERVAL_VERDICT = "interval_exceeds"
REMEDIES = ("add_knot", "promote")
# 구간 처방 기록 상태 — 제안 · 반영(재검증 전) · 수용 · 되돌림 · 봉인(되돌린 처방을 다시 냈으나 봉인) · 미개선(낼 처방이 없다)
REMEDY_STATUS = ("proposed", "applied", "accepted", "rolled_back", "sealed", "unimproved")
REMEDY_STATUS_TEXT = {
    "proposed": "구간 처방 제안",
    "applied": "구간 처방 반영 — 재검증 전",
    "accepted": "구간 처방 수용 — 비퇴행 확인",
    "rolled_back": "구간 처방 되돌림 — 이터 전체를 체크포인트로",
    "sealed": "구간 미개선 — 처방 소진",
    "unimproved": "구간 미개선 — 처방 소진",
}
# 미개선의 두 갈래 — 처방으로 못 고친 것을 구조 한계라 부르지 않는다. 편입한 점의 튜닝 자체가 성립하지 않았을 때만(05 §7.2
# 단일 술어 — tune.SLOT_DESIGN_FAILED) 구조적 한계다
UNIMPROVED_EXHAUSTED = "구간 미개선 — 처방 소진"
UNIMPROVED_STRUCTURAL = "구간 미개선 — 구조적 한계"
# 처방 효과의 문턱 — 오케스트레이터의 _EFFECT_EPS와 같은 값(부족 비율이 이만큼도 안 움직이면 개선이 아니다)
EFFECT_EPS = 1e-3
_EQ = 1e-9


def seal_key(row, interval, slot, remedy) -> str:
    """구간 처방의 봉인 키 — (행, 구간, 자리, 처방). 문자열이라야 세션 왕복(JSON)에서 살아남는다. 점 처방의 봉인 키
    (`점|자리|verdict`)와 같은 사전(ineffective)에 들어가므로 앞에 interval을 붙여 겹치지 않게 한다."""
    alt, fuel = row
    a, b = interval
    return f"interval|{float(alt):.12g}|{float(fuel):.12g}|{float(a):.12g}|{float(b):.12g}|{slot}|{remedy}"


def triggered(iv) -> bool:
    """처방할 구간인가 — 잎 구간(쪼갠 구간은 자식 조각이 잰다) ∧ (d > 허용치 ∨ fail이 섞인 판정 다름)."""
    if iv.get("status") == "split":
        return False
    if iv.get("exceeds"):
        return True
    return bool(iv.get("verdict_change")) and "fail" in (iv.get("verdicts") or {}).values()


def _mid(iv):
    pts = iv.get("points") or []
    return pts[1] if len(pts) == 3 else None


def _target_slot(iv, cases, mid):
    """대상 자리 — d / 허용치가 최대인 자리(⑤ 기록), d를 잰 자리가 없으면 중간점의 가장 나쁜 판정 자리."""
    if iv.get("slot"):
        return iv["slot"]
    loops = ((cases.get(mid) or {}).get("loops") or {})
    for st in ("fail", "warn"):
        for loop, m in loops.items():
            if m.get("status") == st:
                return loop
    return None


def interval_remedies(intervals, cases, actions, *, role_of, mach_of, has_knot, sealed=(), design_failed=None) -> dict:
    """구간 처방 카드 — {"cards": [tune_interval 카드], "unimproved": [{row, interval, slot, point, label, why, key}]}.

    intervals: reinforce_intervals 기록(⑤). cases: 마진 맵 cases. actions: 같은 판의 점 실패 카드(supersede 판단).
    role_of(name) → 역할 | None(점 집합에 없음). mach_of(name) → 마하. has_knot(slots, mach) → 이름 댄 표가 전부 그 마하
    절점을 이미 가졌나. sealed: 봉인 키 집합(seal_key). design_failed(name, loop) → 그 점·자리 튜닝이 성립하지 않았나.

    카드 = {id, case, loop, verdict interval_exceeds, action {type tune_interval, remedy add_knot|promote, point, mach, slots,
    promote, interval {row, interval, slot, d, tol}}, evidence {interval: ⑤ 기록}, severity d/허용치, interval_key}. 낼 처방이
    없는 구간(중간점이 이미 설계점이고 절점도 있음 · 판정 다름만인데 편입할 검증점이 없음 · 봉인)은 unimproved에 사유와
    함께 남는다 — 조용히 빼지 않는다. 봉인된 카드도 카드 목록에 sealed 표식과 함께 남는다(점 처방과 같은 규약) — 그
    구간은 unimproved에도 봉인 키(key)를 달고 들어간다(그 밖의 미개선은 key None)."""
    by_case: dict = {}
    for a in actions:
        by_case.setdefault(a.get("case"), a)
    cards, unimproved = [], []
    for iv in intervals:
        if not triggered(iv):
            continue
        mid = _mid(iv)
        row, interval = list(iv["row"]), list(iv["interval"])
        slot = _target_slot(iv, cases, mid) if mid else None

        def give_up(why, *, structural=False, key=None):
            unimproved.append({"row": row, "interval": interval, "slot": slot, "point": mid, "why": why, "key": key,
                               "label": UNIMPROVED_STRUCTURAL if structural else UNIMPROVED_EXHAUSTED})

        role = role_of(mid) if mid else None
        if mid is None or role is None or not ((cases.get(mid) or {}).get("loops")) or slot is None:
            give_up("중간점이 점 집합에 없거나 판정이 없다 — 처방할 표본 자리가 없다")
            continue
        slots = list(LOOP_SLOTS.get(slot, ()))
        mach = float(mach_of(mid))
        promote = role == ROLE_VALIDATION
        structural = bool(design_failed and design_failed(mid, slot))
        if iv.get("exceeds") and not has_knot(slots, mach):
            remedy = "add_knot"
        elif promote:
            remedy = "promote"  # 판정 다름만(형상은 맞고 표본이 모자람) — 또는 절점은 이미 있고 표본만 없다
        else:
            give_up("중간점이 이미 설계점이고 그 마하 절점도 있다 — 편입·절점 추가 둘 다 남지 않았다", structural=structural)
            continue
        key = seal_key(row, interval, slot, remedy)
        d, tol = iv.get("d"), iv.get("tol")
        card = {
            "id": f"tune_interval:{mid}:{slot}", "case": mid, "loop": slot, "verdict": INTERVAL_VERDICT,
            "action": {"type": "tune_interval", "remedy": remedy, "point": mid, "mach": mach, "slots": slots,
                       "promote": promote,
                       "interval": {"row": row, "interval": interval, "slot": slot, "d": d, "tol": tol}},
            "evidence": {"interval": {k: iv.get(k) for k in ("row", "interval", "depth", "slot", "d", "tol", "exceeds",
                                                              "verdict_change", "verdicts", "points", "status",
                                                              "reasons")}},
            "severity": (d / tol) if (d is not None and tol) else None,
            "interval_key": key,
        }
        other = by_case.get(mid)
        if other is not None:
            card["superseded_by"] = other["id"]  # 점 실패 처방이 같은 점을 이미 다룬다
        elif key in sealed:
            card["sealed"] = "이 구간 처방은 재검증 가드에 한 번 거부돼 되돌렸다 — 결정론이라 다시 내도 같다(봉인)"
            give_up("처방이 거부돼 봉인됐다 — 남은 처방이 없다", structural=structural, key=key)
        cards.append(card)
    return {"cards": cards, "unimproved": unimproved}


def _loop_state(cases, name, loop, criteria):
    m = (((cases.get(name) or {}).get("loops") or {}).get(loop))
    if m is None:
        return None
    sev = criteria.severity(m)
    return {"status": m.get("status"), "severity": sev if math.isfinite(sev) else None}


def snapshot(points, t, slot, cases, criteria, scales) -> dict:
    """구간 세 점(양끝·중간 이름)의 판정 — {verdicts{a, mid, b}, d(대상 자리 — 같은 이름·같은 t로 다시 잰다), slot,
    loops{점: {자리: {status, severity}}}}. 재검증 뒤에는 절점이 늘어 그 구간이 계획에서 사라질 수 있다 — 그래서 구간이
    아니라 **같은 세 점**을 다시 잰다."""
    loops: dict = {}
    for name in points:
        entry = (cases.get(name) or {}).get("loops") or {}
        loops[name] = {lp: _loop_state(cases, name, lp, criteria) for lp in entry}
    verdicts = dict(zip(("a", "mid", "b"), (_worst_status(cases.get(n)) for n in points))) if len(points) == 3 else {}
    d = None
    s = scales.get(slot) if slot else None
    if len(points) == 3 and s and t is not None:
        vals = [_metric(cases.get(n), slot) for n in points]
        if all(v is not None for v in vals):
            d = abs(vals[1] - (vals[0] + t * (vals[2] - vals[0]))) / s
    return {"verdicts": verdicts, "d": d, "slot": slot, "loops": loops}


def _rank(state):
    return None if state is None else _STATUS_RANK.get(state.get("status"))


def _worse(before, after, *, only_loop=None) -> list:
    """두 스냅숏 사이 등급이 오른 자리 — [{case, loop, from, to}]. 앞에 판정이 있다가 뒤에 없어진 자리도 오름으로 센다
    (판정 소실 — 0으로 위장하지 않는다)."""
    out = []
    for name, loops in (before.get("loops") or {}).items():
        for loop, st in loops.items():
            if only_loop is not None and loop != only_loop:
                continue
            rb = _rank(st)
            if rb is None:
                continue
            st_a = ((after.get("loops") or {}).get(name) or {}).get(loop)
            ra = _rank(st_a)
            if ra is None or ra > rb:
                out.append({"case": name, "loop": loop, "from": st.get("status"),
                            "to": None if st_a is None else st_a.get("status")})
    return out


def _improved(before, after, slot, tol) -> bool:
    """대상 자리 개선 — 구간 d ≤ 허용치, 또는 세 점 중 한 곳의 대상 자리 등급 하락, 또는 severity가 EFFECT_EPS 넘게 감소."""
    if tol is not None and after.get("d") is not None and after["d"] <= tol:
        return True
    for name, loops in (before.get("loops") or {}).items():
        b = loops.get(slot)
        a = ((after.get("loops") or {}).get(name) or {}).get(slot)
        rb, ra = _rank(b), _rank(a)
        if rb is not None and ra is not None and ra < rb:
            return True
        sb, sa = (b or {}).get("severity"), (a or {}).get("severity")
        if sb is not None and sa is not None and sb - sa > EFFECT_EPS:
            return True
    return False


def region_delta(cases_before, cases_after, criteria) -> dict:
    """전 요구영역 비퇴행 — {worse, better, dropped, new_fail: [{case, loop}], caution_regressions: [{case, loop}]}.

    schedmap.margin_delta를 그대로 쓴다 — 앞 판정의 점만 모집단이다(재계획이 새로 세운 검증점은 비교하지 않는다).
    하드 위반은 ok|warn → fail(new_fail)과 판정 소실(dropped), ok → warn은 허용하되 caution_regressions로 적는다."""
    md = margin_delta(cases_before, cases_after, criteria)
    new_fail = [{"case": c["case"], "loop": c["loop"], "from": c["from"]} for c in md["changed"]
                if c["to"] == "fail" and c["from"] in ("ok", "warn")]
    caution = [{"case": c["case"], "loop": c["loop"]} for c in md["changed"] if c["from"] == "ok" and c["to"] == "warn"]
    return {"worse": md["worse"], "better": md["better"], "dropped": md["dropped"], "new_fail": new_fail,
            "caution_regressions": caution, "n_judged": md["n_judged"]}


def judge_remedy(rec, after, neighbours_after, region) -> dict:
    """비퇴행 가드 — {accepted, improved, own: 위반 있음, violations: [문장], own_worse, neighbour_worse}.

    rec: 반영 때의 기록(before 스냅숏 · slot · tol · neighbours[{interval, before}]). after: 같은 세 점의 재검증 스냅숏.
    neighbours_after: 이웃 구간마다 재검증 스냅숏(rec["neighbours"] 순서). region: region_delta(이터 단위 — 같은 이터의 모든
    구간 처방이 같은 값을 본다). own은 이 처방 자기 위반((a)·(b))이 있는가 — 영역 위반만이면 원인을 가를 수 없다."""
    slot, tol = rec["slot"], rec.get("tol")
    own_worse = _worse(rec["before"], after)
    improved = _improved(rec["before"], after, slot, tol)
    nb_worse = []
    for nb, nb_after in zip(rec.get("neighbours") or (), neighbours_after):
        for w in _worse(nb["before"], nb_after, only_loop=slot):
            nb_worse.append({**w, "interval": nb["interval"]})
    violations = []
    if own_worse:
        violations.append(f"구간 자기 점 등급 상승 {len(own_worse)}곳 ("
                          + ", ".join(f"{w['case']} {w['loop']} {w['from']}→{w['to'] or '판정 없음'}"
                                      for w in own_worse[:3]) + ")")
    if not improved:
        violations.append(f"대상 자리 {slot} 개선 없음 — 등급·부족 비율·구간 d 어느 것도 나아지지 않았다")
    if nb_worse:
        violations.append(f"이웃 구간 {slot} 등급 상승 {len(nb_worse)}곳")
    own = bool(violations)
    if region["new_fail"]:
        violations.append(f"전체 신규 불합격 {len(region['new_fail'])}")
    if region["dropped"]:
        violations.append(f"판정 소실 {region['dropped']}")
    return {"accepted": not violations, "improved": improved, "own": own, "violations": violations,
            "own_worse": own_worse, "neighbour_worse": nb_worse}


def neighbours_of(rec_row, rec_interval, intervals) -> list:
    """같은 행의 좌우 이웃 잎 구간 — 이 구간의 왼끝에서 끝나거나 오른끝에서 시작하는 구간. [{interval, points}]."""
    a, b = rec_interval
    out = []
    for iv in intervals:
        if iv.get("status") == "split" or list(iv["row"]) != list(rec_row) or len(iv.get("points") or ()) != 3:
            continue
        lo, hi = iv["interval"]
        if abs(hi - a) <= _EQ or abs(lo - b) <= _EQ:
            out.append({"interval": [lo, hi], "points": list(iv["points"])})
    return out


def grid_codes(grid) -> dict:
    """요약 격자 → {"행|열": 칸 머리 코드} — 처방 전후 격자 비교의 단위."""
    out = {}
    for rk, by_col in ((grid or {}).get("cells") or {}).items():
        for ck, cell in by_col.items():
            out[f"{rk}|{ck}"] = cell.get("headline_code")
    return out


def grid_delta(before: dict, after: dict) -> list:
    """두 격자에 다 있는 칸 중 머리 코드가 바뀐 칸 — [{row, column, from, to}]. 절점이 늘면 열이 바뀌어 새 칸이 생긴다 —
    새 칸은 비교하지 않는다(재계획 중점과 같은 이유)."""
    out = []
    for k in sorted(set(before) & set(after)):
        if before[k] != after[k]:
            rk, ck = k.split("|", 1)
            out.append({"row": rk, "column": ck, "from": before[k], "to": after[k]})
    return out


def remedy_counts(log) -> dict:
    """coverage.interval_remedies — {proposed(제안·반영 대기), accepted, rolled_back(되돌린 적 있는 처방), unimproved(낼 처방이
    없는 구간 — 봉인 포함)}."""
    return {"proposed": sum(r["status"] in ("proposed", "applied") for r in log),
            "accepted": sum(r["status"] == "accepted" for r in log),
            "rolled_back": sum(bool(r.get("rolled_back")) for r in log),
            "unimproved": sum(r["status"] in ("unimproved", "sealed") for r in log)}
