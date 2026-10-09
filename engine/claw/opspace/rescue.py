"""한계 안쪽 트림 재풀이 (05 §11.3 · 이관 7b) — trim_inside_limit를 그 근거 해 시드로 다시 푼다.

풀이기가 물리 한계 하나(스로틀 0·1, 엘레본 끝)에 멈춘 미수렴인데, 그 채널을 한계에 고정하고 나머지 평형을 다시 푼
근거(states._limit_evidence)가 한계 **안쪽**에 트림이 있다고 가리키면 조건 상태는 계산 실패 [채널, not_converged,
trim_inside_limit]다. 배치 재시도(trim.retry_level)는 어느 한계에도 안 붙은 미수렴만 다시 풀므로 이 점은 그대로 남았다.
여기서 근거 해를 시드로 전체 트림을 다시 푼다 — 고정 채널을 need(남은 식을 없애는 1차 변화량)만큼 안쪽으로 옮긴 점을
**모두** 먼저, 그다음 원 근거 해를 모두(정책 max_attempts 상한, 첫 수렴·첫 한계 하나에서 멈춤 — retry_level 규칙 그대로).

- 엔진 trim_batch는 바꾸지 않는다(엔진 골든 · 자동 설계). 서버 저장소 경로가 trim_batch 뒤·판정 앞에 부른다.
- 근거는 trim_assessment의 메모(cache[("limit_evidence", 조건 키, 채널)])로 한 번만 푼다 — 같은 cache를 이 패스와 뒤의
  판정(행 판정·retried_states)에 넘겨야 한다.
- 수렴하면 저장소에 그 해를 넣는다(먼저 쓴 수렴 기록이 이긴다 — 배치가 쓴 미수렴 기록은 대체된다). 뒤 점들의 시드는
  다시 돌리지 않는다(풀이 수와 맞바꾼 비용 — 뒤 점은 이미 다른 인접 해에서 풀렸다).
- 그래도 안 되면 처음 해(또는 retry_level 순서의 최선)를 두고 기록만 붙인다. 판정은 같은 근거를 메모에서 다시 싣고
  사유에 retry_exhausted를 더한다 — 실패 상태와 근거를 보존한다.
- 기록은 TrimResult.retry에 실린다(배치 재시도 기록이 이미 있으면 합친다): 시드·결과를 잇고, chosen을 합친 번호로
  다시 매기고, evidence_pass = {"channel", "attempts"}를 더한다.
"""

from __future__ import annotations

import numpy as np

from claw.opspace.states import _LIMIT_CHANNEL, _UNKNOWNS, trim_assessment
from claw.trim.store import TrimRecord
from claw.trim.trim import (
    CONTINUITY_STEP, DEFAULT_RETRY, THR_BOUNDS, _retry_level, _z_of, _zkey, physical_limits,
)

EVIDENCE_KIND = "limit_evidence"  # 시드 종류 — TrimRecord.seed["kind"]·재시도 기록 seeds[].kind


def evidence_seeds(evidence, trim_bounds, *, skip=None) -> list:
    """한계 근거(_limit_evidence) → 시드 후보 [{"kind": "limit_evidence", "from": 채널, "z0": [α, δe, thr]}].

    대상은 한계 안쪽을 가리킨 해(short False)뿐이다. 순서: 고정 채널을 need만큼 옮긴 점(그 채널의 물리 한계로 자름)
    전부 → 원 근거 해 전부. 1e-6 반올림 중복과 skip(멈춘 해 그 자체)은 뺀다."""
    channel = evidence["channel"]
    fixed_i = _LIMIT_CHANNEL[channel][0]
    lo, hi = THR_BOUNDS if fixed_i == 2 else tuple(trim_bounds["de"])
    inside = [s for s in evidence.get("solutions") or [] if s.get("short") is False]
    seen = set() if skip is None else {_zkey(skip)}
    out = []

    def add(z):
        k = _zkey(z)
        if k not in seen:
            seen.add(k)
            out.append({"kind": EVIDENCE_KIND, "from": channel, "z0": [float(v) for v in z]})

    for s in inside:
        z = [float(s[k]) for k in _UNKNOWNS]
        z[fixed_i] = min(max(z[fixed_i] + float(s["need"]), float(lo)), float(hi))
        add(z)
    for s in inside:
        add([float(s[k]) for k in _UNKNOWNS])
    return out


def _merge(old, new):
    """배치 재시도 기록(old) 뒤에 근거 패스 기록(new)을 잇는다. chosen은 합친 시도 번호, 결과·멈춤은 이 패스의 것."""
    if old is None:
        return new
    chosen = old.get("chosen") if new["chosen"] is None else len(old["seeds"]) + new["chosen"]
    return {"attempts": int(old.get("attempts", 0)) + new["attempts"], "seeds": [*old["seeds"], *new["seeds"]],
            "outcomes": [*old["outcomes"], *new["outcomes"]], "chosen": chosen, "result": new["result"],
            "stop": new["stop"], "evidence_pass": new["evidence_pass"]}


def _eligible(tr, tb) -> bool:
    # 새로 푼 수평비행 해 중 물리 한계 하나에 멈춘 미수렴 — 이미 근거 패스를 거친 해는 다시 하지 않는다
    if tr.case.condition != "level" or getattr(tr, "origin", "computed") != "computed" or tr.converged:
        return False
    if "evidence_pass" in (getattr(tr, "retry", None) or {}):
        return False
    return len(physical_limits(tr, tb)) == 1


def rescue_inside_limit(results, built, model, *, cache, store=None, policy=DEFAULT_RETRY, fingerprint="") -> list:
    """trim_batch 결과 → 같은 순서의 결과(근거 해 재풀이를 거친). 대상 아닌 해는 그 객체 그대로다.

    cache: trim_assessment에 넘기는 근거 캐시 — 뒤의 판정과 **같은 dict**여야 근거를 두 번 풀지 않는다. 기체도
    cache["aircraft"]를 쓴다(없으면 만들어 넣는다). store: 트림 저장소 창(TrimStoreScope | None). 다시 푼 해는 retry 기록을
    인스턴스에 싣는다(처음 해를 그대로 두면 그 객체에)."""
    cache = {} if cache is None else cache
    tb = built.trim_bounds
    out = []
    z_prev = None  # 직전 수렴 해 — 연속성은 trim_batch와 같은 기준으로 다시 잰다
    for tr in results:
        if _eligible(tr, tb):
            a = trim_assessment(tr, built, model, cache=cache)
            if "trim_inside_limit" in a["reasons"]:
                tr = _rescue_one(tr, a["evidence"], built, cache, store, policy, fingerprint, z_prev)
        if tr.converged:
            z_prev = _z_of(tr)
        out.append(tr)
    return out


def _rescue_one(tr, evidence, built, cache, store, policy, fingerprint, z_prev):
    seeds = evidence_seeds(evidence, built.trim_bounds, skip=_z_of(tr))
    if not seeds[: max(int(policy.max_attempts), 0)]:
        return tr  # 한 번도 풀 수 없다 — 다시 풀어 본 점이 아니다(기록·retry_exhausted 없음)
    if "aircraft" not in cache:
        cache["aircraft"] = built.aircraft()
    tr2, rec, raw, chosen = _retry_level(cache["aircraft"], tr.case, tr, seeds, policy, fingerprint)
    rec["evidence_pass"] = {"channel": evidence["channel"], "attempts": rec["attempts"]}
    tr2.retry = _merge(getattr(tr, "retry", None), rec)
    if raw is not None:
        if z_prev is not None:
            tr2.flags["continuity_ok"] = bool(np.all(np.abs(_z_of(tr2) - z_prev) < CONTINUITY_STEP))
        if store is not None:
            x, ok, cost = raw
            store.put(tr.case, TrimRecord(z=tuple(float(v) for v in x), success=ok, cost=cost,
                                          converged=tr2.converged, seed={"kind": chosen["kind"], "from": chosen["from"]},
                                          retry=tr2.retry))
    return tr2
