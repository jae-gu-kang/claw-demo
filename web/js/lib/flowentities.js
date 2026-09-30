/** 설계 흐름 — 엔티티 막대 목록과 엔티티 저장소 모델 (06 §3 · 06 §10, 사용자 후속 ③.5).
 *
 * **1 엔티티 = 기체(+형상 변형) 하나의 제어법칙 설계 하나**이다 — 게인 자리가 아니다(사용자 논거:
 * 그래야 흐름 탭의 6블록이 그 엔티티의 진행을 뜻한다). 목록의 재료는 흐름 탭이 **이미 부르는 둘**뿐이고
 * (GET /profiles · GET /results) 엔티티당 계산은 0회다 — 새 엔드포인트도, 줄마다 도는 잡도 없다.
 *
 * ## 이 파일의 규율 — 증거가 없는 칸은 실패한 칸과 달라야 하고, 둘 다 「통과」가 아니다
 *
 * 화면이 6칸 막대를 그리면 사용자는 그것을 「여기까지 했다」로 읽는다. 그래서 여기서 가장 많은 줄을
 * 차지하는 것은 판정이 아니라 **판정을 거절하는 규칙**이다:
 *
 * - ①문서 검증·②엔벨로프는 **per-entity 기록이 원리적으로 없다**(둘 다 저장물 없는 동기 조회다).
 *   목록만으로는 그 엔티티가 그 단계를 돌았는지 알 수 없어 `no_record`(「기록 없는 조회 단계」)로 두고,
 *   도달(reach) 계산에서 아예 뺀다. 지금 세션이 직접 돈 엔티티(뷰의 stages = `live`)에서만 판정 칸이 된다.
 * - ④자동 설계의 `judged`·`failures`·`iterations`·`trim_reuse`는 meta에 **있으면** 읽고 없으면
 *   (옛 결과) 그리지 않는다. 판정 0의 실패 0은 통과가 아니다(flowsteps.designVerdict과 같은 규약).
 * - ⑤평가의 합격/불합격은 meta의 `hard_fail`이 있을 때만이다. 없으면 `unknown_verdict` — 점선 테두리로
 *   「돌았으나 목록에서 판정 모름」이라 말하고, 불합격(붉은색)으로 위장하지 않는다.
 * - 형상 변형 줄은 **기본형의 확정 표를 물려받지 않는다** — 확정 표는 기본형 설계 결과라, 변형 패치가
 *   표를 비우면 그 변형은 규칙 스케줄로 난다(quickseed.variantTableSource와 같은 자).
 * - 기체 기록(meta.profile)이 없는 옛 결과는 어느 엔티티 것인지 모르므로 어느 줄에도 싣지 않는다
 *   (flowsteps.latestResultFor의 규약).
 *
 * 색은 새로 만들지 않고 lib/plot.js 한 벌을 재사용한다(FE_TOKENS). **계산 상태는 무늬·테두리, 성능
 * 판정은 색**이다(06 §10 ⑥) — 안 돌림·건너뜀·실패·불합격이 색을 나눠 갖고, 막대 위에는 글자가 없다
 * (수는 캡션·툴팁이 말한다 — 사용자 지적 「그림 위엔 조작만」).
 */

import { FLOW_STAGES, latestResultFor } from "./flowsteps.js";
import { STATUS, TRIM_STATE_CELL } from "./plot.js";

/** 목록 막대의 칸 = 흐름 레일의 단계와 **같은 수·같은 순서**다(6) — 화면이 둘을 같은 그리드로 세운다
 *  (app.css .fe-row와 .fd-rail이 repeat(6,1fr)를 공유한다. 단계를 늘리면 둘을 같이 고친다). */
export const FE_STAGES = FLOW_STAGES;

/** per-entity 기록이 원리적으로 없는 머리 단계 — 도달 계산에서 뺀다(머리말). */
export const FE_HEAD_KEYS = Object.freeze(["doc", "envelope"]);

/** 상태·판정 → 그리기 토큰. **새 색을 만들지 않는다** — lib/plot.js의 STATUS·TRIM_STATE_CELL을 그대로 쓴다.
 *
 *  - `fill: "gradient"`는 레일 채움(.fd-fill)과 같은 그러데이션이다 — 「도달」의 뜻을 한 화면에서 한 가지로.
 *  - `pattern`은 계산 상태를 가른다(민무늬·사선·점) — 색이 아니라 무늬라, 성능 판정색과 섞이지 않는다.
 *  - `border: "dotted"`는 「돌았으나 판정 모름」 하나뿐이다 — 채움은 같아도 테두리가 판정의 부재를 말한다.
 *  - `marker: "stop"`이 붙은 칸에만 막대 끝 정지 사유 마커가 선다.
 */
export const FE_TOKENS = Object.freeze({
  reached: { fill: "gradient", color: null, pattern: "none", border: "solid", marker: null,
    label: "도달" },
  running: { fill: "gradient", color: null, pattern: "pulse", border: "solid", marker: null,
    label: "실행 중" },
  // 안 돌림 — 회색 민무늬(TRIM_STATE_CELL.unevaluated). 「미평가」와 같은 뜻의 자리다
  not_run: { fill: "flat", color: TRIM_STATE_CELL.unevaluated.color, pattern: "none",
    border: "solid", marker: null, label: "안 돌림" },
  // 건너뜀 — 판정 불가색 + 사선. 안 돌린 것과 같은 회색 민무늬면 「탐색 생략」이 「미실행」으로 읽힌다
  skipped: { fill: "flat", color: STATUS.na, pattern: "diagonal", border: "solid", marker: null,
    label: "건너뜀" },
  failed: { fill: "flat", color: TRIM_STATE_CELL.calc_failed.color, pattern: "none",
    border: "solid", marker: "stop", label: "실패" },
  blocked: { fill: "flat", color: STATUS.warn, pattern: "none", border: "solid", marker: "stop",
    label: "막힘" },
  // 주의 — 지나가긴 했으나 알릴 것이 있다(문서 경고 등). 도달 채움에 주의색 테두리를 얹는다:
  // 막힘(민무늬 주의색 + 끝 마커)과 색은 같고 **지나갔다는 사실**이 채움으로 남는다
  warn: { fill: "gradient", color: STATUS.warn, pattern: "none", border: "solid", marker: null,
    label: "주의(지나감)" },
  // 불합격 — 성능 판정이므로 **색**이다(계산은 끝까지 돌았다)
  fail: { fill: "flat", color: STATUS.bad, pattern: "none", border: "solid", marker: "stop",
    label: "불합격" },
  unknown_verdict: { fill: "gradient", color: null, pattern: "none", border: "dotted",
    marker: "stop", label: "판정 모름" },
  // 기록 없는 조회 단계(①②) — 판정 불가색 + 점무늬. 건너뜀(사선)과 다른 무늬다: 「생략했다」가 아니라
  // 「목록으로는 알 수 없다」다
  no_record: { fill: "flat", color: STATUS.na, pattern: "dots", border: "solid", marker: null,
    label: "기록 없는 조회 단계" },
});

/** 도달로 세는 상태 — 사슬이 이 칸을 **지나갔다**고 말할 수 있는 것만. 건너뜀(탐색 생략)은 지나간 것이다. */
const PASSED = new Set(["reached", "skipped"]);

const numOr = (v, d = null) => (typeof v === "number" && Number.isFinite(v) ? v : d);
const cnt = (v) => numOr(v, 0);

/** 트림 재사용·이터 수 → 막대 안 세그먼트. 키가 없는 옛 meta는 **빈 배열**이다(없는 수를 0으로 그리지 않는다). */
function reuseSegments(counts, iterations = null) {
  const out = [];
  if (counts && typeof counts === "object") {
    const each = [
      ["trim_reused", numOr(counts.reused), (n) => `트림 재사용 ${n}점(저장소에서 꺼냈다)`],
      ["trim_computed", numOr(counts.computed), (n) => `새로 푼 트림 ${n}점`],
      ["trim_resolved_failed", numOr(counts.resolved_failed),
        (n) => `이전에 미수렴이던 ${n}점을 이번에 다시 풀었다`],
    ];
    for (const [kind, n, tip] of each) if (n != null && n > 0) out.push({ kind, n, tip: tip(n) });
  }
  const it = numOr(iterations);
  if (it != null && it > 0) out.push({ kind: "iterations", n: it, tip: `설계 이터 ${it}회` });
  return out;
}

/** 지금 세션이 직접 돈 기록(뷰의 stages[key]) → 칸. 없으면 null — 목록 재료로 되돌아간다. */
function liveCell(stage, st) {
  if (!st?.state) return null;
  if (st.state === "running") {
    return { state: "running", tone: "running", label: st.note ?? "실행 중…",
      tip: `${stage.label} — 지금 이 화면이 돌리는 중`, source: "live" };
  }
  const v = st.verdict;
  if (!v) return null;
  const cell = { label: v.text, tip: v.text, source: "live", resultId: st.resultId ?? null };
  if (v.stop) return { ...cell, state: "blocked", tone: "blocked" };
  if (v.tone === "bad") return { ...cell, state: "failed", tone: "failed" };
  // 초기 게인의 「탐색 생략」은 run:false로 온다(flowsteps.seedStateVerdict) — 건너뜀이지 미실행이 아니다
  if (v.run === false && stage.key === "seed") return { ...cell, state: "skipped", tone: "skipped" };
  if (v.tone === "na") return { ...cell, state: "unknown_verdict", tone: "unknown_verdict" };
  if (v.tone === "warn") return { ...cell, state: "reached", tone: "warn" };
  return { ...cell, state: "reached", tone: "reached" };
}

const HEAD_TIP = {
  doc: "문서 검증은 저장물이 없는 조회다 — 이 목록만으로는 이 기체가 검증을 돌았는지 알 수 없다. "
    + "[열기]로 이 엔티티의 레일에서 돌리면 그 판정이 여기 선다",
  envelope: "설계 엔벨로프는 저장물이 없는 동기 조회다 — 결과 저장소에 기록이 없어 목록은 도달을 그리지 "
    + "않는다. [열기]로 이 엔티티의 레일에서 돌린다",
};

/** ① 문서 검증 칸 — 읽을 수 없는 기체만 실패다. 경고 수는 서버 목록의 `doc_warnings`(순수 문서 판정)가
 *  있을 때만 말한다 — 없는 서버에서는 「기록 없는 조회 단계」로 남는다(0건으로 위조하지 않는다). */
function docCell(row) {
  if (row.unreadable) {
    return { state: "failed", tone: "failed", label: "읽을 수 없음",
      tip: `기체 문서를 읽을 수 없다 — ${row.reason ?? "사유 없음"}`, source: "profiles" };
  }
  const n = numOr(row.doc_warnings);
  const notes = row.upgrade_notes && Object.keys(row.upgrade_notes).length
    ? " · 옛 스키마 저장본(저장하면 올린 문서가 새 리비전이 된다)" : "";
  if (n == null) {
    return { state: "no_record", tone: "no_record", label: `문서 경고 수 모름${notes}`,
      tip: HEAD_TIP.doc + notes, source: "none" };
  }
  const tail = `서버 목록의 순수 문서 판정이다 — 저장 규칙 검증은 [열기]의 ①이 돈다${notes}`;
  return { state: "reached", tone: n ? "warn" : "reached",
    label: n ? `문서 경고 ${n}건` : "문서 경고 없음",
    tip: n ? `문서 경고 ${n}건(기체 탭에서 확인) — ${tail}` : `문서 경고 없음 — ${tail}`,
    source: "profiles" };
}

/** ③ 초기 게인 칸 — 문서의 design_source가 있으면 탐색 생략(건너뜀)이다. 없으면 최근 quick_seed 결과. */
function seedCell(row, meta) {
  const src = row.design_source ?? null;
  if (src) {
    return { state: "skipped", tone: "skipped", label: `게인 있음(출처 ${src}) — 탐색 생략`,
      tip: `문서에 설계 게인이 있어 빠른 탐색을 돌리지 않는다(출처 ${src}) — 다시 탐색은 기체 탭`,
      source: "profiles" };
  }
  if (!meta) {
    return { state: "not_run", tone: "not_run", label: "게인 미설계 — 빠른 탐색 필요",
      tip: "문서에 설계 게인이 없고 이 엔티티의 빠른 탐색 결과도 없다", source: "none" };
  }
  const st = meta.status ?? null;
  const base = { source: "meta", resultId: meta.id ?? null,
    link: meta.id ? { tab: "#results", cue: "resultBrief" } : null };
  if (st === "failed" || st === "write_error") {
    return { ...base, state: "failed", tone: "failed", label: `빠른 탐색 ${st}`,
      tip: `가장 최근 빠른 탐색 결과가 ${st}다 — 문서에 게인이 남지 않았다` };
  }
  if (st == null) {
    return { ...base, state: "unknown_verdict", tone: "unknown_verdict",
      label: "빠른 탐색 결과 있음 — 채택 판정 기록 없음",
      tip: "이 결과 meta에 채택·저장 판정이 없다(옛 결과) — 결과 탭에서 본문을 연다" };
  }
  return { ...base, state: "reached", tone: st === "written" || st === "ok" ? "reached" : "warn",
    label: `빠른 탐색 ${st}`, tip: `가장 최근 빠른 탐색 결과 판정 ${st}` };
}

/** ④ 자동 설계 칸 — 승인 대기는 막힘이고, 판정 수(judged)가 없거나 0이면 통과로 쓰지 않는다. */
function designCell(meta) {
  if (!meta) {
    return { state: "not_run", tone: "not_run", label: "자동 설계 기록 없음",
      tip: "이 엔티티로 돈 자동 설계 결과가 결과 저장소에 없다", source: "none" };
  }
  const rid = meta.id ?? null;
  const st = meta.status ?? null;
  const stage = meta.stage ?? null;
  // trim_reuse·iterations는 meta에 **있으면** 세그먼트, 없으면(옛 결과) 그리지 않는다
  const segments = reuseSegments(meta.trim_reuse ?? meta.trim_reuse_counts ?? null, meta.iterations);
  const base = { source: "meta", resultId: rid, segments,
    link: rid ? { tab: "#autodesign", cue: "designOpen" } : null };
  if (st === "awaiting_approval") {
    return { ...base, state: "blocked", tone: "blocked", label: "처방 승인 대기",
      tip: "처방 승인 대기(gated) — 자동 설계 탭에서 승인·재개한 뒤 흐름을 이어 간다" };
  }
  const judged = numOr(meta.judged);
  const failures = numOr(meta.failures);
  if (st !== "converged") {
    return { ...base, state: "failed", tone: "failed",
      label: `${st ?? "상태 기록 없음"} — 수렴 전에 멈췄다`,
      tip: `자동 설계가 수렴하지 않았다(status ${st ?? "없음"}${stage ? ` · stage ${stage}` : ""}) — `
        + "끝까지 보지 않은 실행의 실패 0은 통과가 아니다" };
  }
  if (judged == null || failures == null) {
    return { ...base, state: "unknown_verdict", tone: "unknown_verdict",
      label: `${st} — 판정 수 기록 없음`,
      tip: "이 결과 meta에 판정 수(judged)·미달 수(failures)가 없다(옛 결과) — 수렴했다는 것만 알고 "
        + "무엇을 얼마나 검증했는지는 모른다. 자동 설계 탭 원장에서 본다" };
  }
  if (judged <= 0) {
    return { ...base, state: "unknown_verdict", tone: "unknown_verdict", label: `${st} — 판정 0`,
      tip: "판정 0: 실패 0은 통과가 아니다(아무것도 검증하지 않았다)" };
  }
  if (failures > 0) {
    return { ...base, state: "reached", tone: "fail", label: `미달 ${failures}건 / 판정 ${judged}건`,
      tip: `수렴했으나 미달 ${failures}건(판정 ${judged}건) — 자동 설계 탭 원장` };
  }
  return { ...base, state: "reached", tone: "reached", label: `전 판정 통과(판정 ${judged}건)`,
    tip: `수렴 · 판정 ${judged}건 전부 통과` };
}

/** ⑤ 평가 칸 — 합격/불합격은 meta의 hard_fail이 있을 때만이다(없으면 판정 모름). */
function evalCell(meta) {
  if (!meta) {
    return { state: "not_run", tone: "not_run", label: "평가 기록 없음",
      tip: "이 엔티티로 돈 엔진 평가 결과가 결과 저장소에 없다", source: "none" };
  }
  const rid = meta.id ?? null;
  const n = numOr(meta.n);
  const segments = reuseSegments(meta.trim_reuse_counts ?? null);
  const base = { source: "meta", resultId: rid, segments,
    link: rid ? { tab: "#results", cue: "resultBrief" } : null };
  const where = n == null ? "" : ` · ${n}건`;
  const hf = meta.hard_fail;
  if (hf === true) {
    const k = numOr(meta.hard_fails);
    const many = k == null ? "" : ` ${k}건`;
    return { ...base, state: "reached", tone: "fail", label: `하드 게이트 위반${many}`,
      tip: `하드 게이트 위반${many}${where} — 영향성 탭 상세` };
  }
  if (hf === false) {
    return { ...base, state: "reached", tone: "reached", label: `하드 게이트 전부 통과${where}`,
      tip: `하드 게이트 전부 통과${where}` };
  }
  return { ...base, state: "unknown_verdict", tone: "unknown_verdict",
    label: n === 0 ? "케이스 0건 — 판정 보류" : `평가 기록 있음${where} — 합격 판정 기록 없음`,
    tip: n === 0
      ? "판정할 케이스가 0건이었다 — 합격도 불합격도 아니다"
      : "이 결과 meta에 하드 게이트 판정(hard_fail)이 없다(옛 결과) — 돌긴 돌았으나 합격 여부는 목록으로 "
        + "알 수 없다. 영향성 탭·결과 탭에서 본문을 연다" };
}

/** ⑥ 채택·반영 칸 — 기본 줄은 문서의 확정 표, 변형 줄은 **그 변형의** 출처다(기본형 표를 물려받지 않는다). */
function applyCell(row, variant) {
  const gt = row.gain_tables ?? null;
  if (variant) {
    const src = gt?.variants?.[variant]?.source ?? null;
    if (src === "confirmed") {
      return { state: "reached", tone: "reached", label: "이 변형도 확정 표로 난다",
        tip: "이 형상 변형은 기본형에서 확정된 표를 그대로 쓴다(변형 패치가 표 기준을 바꾸지 않았다)",
        source: "profiles" };
    }
    if (src === "stale") {
      return { state: "blocked", tone: "blocked", label: "이 변형에서 확정 표가 낡음",
        tip: "이 형상 변형은 확정 표의 기준 문서를 바꿔 표가 낡았다 — 계산이 거부한다(자동 설계를 다시 돌린다)",
        source: "profiles" };
    }
    if (src === "rule_schedule") {
      return { state: "not_run", tone: "not_run", label: "이 변형은 규칙 스케줄로 난다",
        tip: "변형 패치가 확정 표를 비웠다 — 이 형상의 게인은 규칙 스케줄이다(기본형 확정 표는 이 줄의 것이 아니다)",
        source: "profiles" };
    }
    if (src === "none" || gt == null) {
      return { state: "not_run", tone: "not_run", label: "확정 표 없음",
        tip: "이 형상 변형에 확정 게인 표가 없다", source: "profiles" };
    }
    return { state: "unknown_verdict", tone: "unknown_verdict", label: "이 변형의 표 출처 모름",
      tip: "서버 목록에 이 형상 변형의 게인 출처가 없다 — 기본형 문구를 변형에 물려주지 않는다",
      source: "none" };
  }
  if (gt == null) {
    return { state: "not_run", tone: "not_run", label: "확정 표 없음",
      tip: "문서(law.gain_tables)에 확정 게인 표가 없다 — 자동 설계 결과를 반영하면 여기 닿는다",
      source: "profiles" };
  }
  if (gt.stale) {
    return { state: "blocked", tone: "blocked", label: "확정 표 낡음",
      tip: "확정 게인 표가 낡았다(표 밖 문서가 바뀌었다) — 자동 설계를 다시 돌려 반영한다",
      source: "profiles" };
  }
  const ap = row.applied_design ?? null;
  return { state: "reached", tone: "reached", label: `확정 표 유효(출처 ${gt.source ?? "기록 없음"})`,
    tip: `문서에 확정 게인 표가 반영돼 있다(출처 ${gt.source ?? "기록 없음"})`
      + (ap?.result_id ? ` · 결과 ${ap.result_id} → 리비전 ${ap.revision}` : ""),
    source: "profiles", resultId: ap?.result_id ?? null,
    link: ap?.result_id ? { tab: "#autodesign", cue: "designOpen" } : { tab: "#gains", cue: null } };
}

const CELL_DEFAULTS = Object.freeze({ resultId: null, link: null, segments: [] });

/** 한 엔티티의 6칸 — 목록 재료(row·metas)에, 이 엔티티가 지금 선택된 것이면 live 기록을 덮어 쓴다. */
function cellsFor(row, variant, metas, live) {
  const sel = { id: row.id, variant };
  const byKey = {
    doc: () => docCell(row),
    envelope: () => ({ state: "no_record", tone: "no_record", label: "저장물 없는 조회 단계",
      tip: HEAD_TIP.envelope, source: "none" }),
    seed: () => seedCell(row, latestResultFor(metas, "quick_seed", sel)),
    design: () => designCell(latestResultFor(metas, "auto_design", sel)),
    eval: () => evalCell(latestResultFor(metas, "influence_evaluate", sel)),
    apply: () => applyCell(row, variant),
  };
  return FE_STAGES.map((s) => {
    const fromList = { ...CELL_DEFAULTS, stage: s.key, ...byKey[s.key]() };
    const fromLive = live ? liveCell(s, live[s.key]) : null;
    return fromLive ? { ...fromList, ...fromLive, stage: s.key } : fromList;
  });
}

/** 이 엔티티 결과들의 가장 최근 created — 정렬 2순위(도달이 같으면 최근 것이 위). 없으면 -Infinity. */
function lastCreated(metas, sel) {
  let out = -Infinity;
  for (const m of metas ?? []) {
    if (m?.profile?.id !== sel.id || (m.profile.variant ?? null) !== sel.variant) continue;
    const c = numOr(m.created);
    if (c != null && c > out) out = c;
  }
  return out;
}

/** 도달 — **①②를 세지 않고** ③부터 이어서 지나간 마지막 칸. 없으면 index -1.
 *  칸을 지나갔다고 말할 수 있는 것은 도달·건너뜀뿐이다(막힘·실패·판정 모름·안 돌림·실행 중에서 끊는다). */
function reachOf(cells) {
  let out = { index: -1, key: null, label: null };
  for (let i = 0; i < cells.length; i++) {
    if (FE_HEAD_KEYS.includes(cells[i].stage)) continue;
    if (!PASSED.has(cells[i].state)) break;
    out = { index: i, key: cells[i].stage, label: FE_STAGES[i].label };
  }
  return out;
}

/** 막대가 멈춘 곳 — ③부터 처음 지나가지 못한 칸과 그 사유. 전부 지나갔으면 null. */
function stopOf(cells) {
  for (let i = 0; i < cells.length; i++) {
    const c = cells[i];
    if (FE_HEAD_KEYS.includes(c.stage) || PASSED.has(c.state)) continue;
    return { stageKey: c.stage, reason: `「${FE_STAGES[i].label}」 — ${c.label}` };
  }
  return null;
}

const sameSel = (a, b) => a != null && b != null && a.id === b.id
  && (a.variant ?? null) === (b.variant ?? null);

/** 이 형상 변형이 **자기 줄**을 가질 근거가 있나 — 그 변형으로 돈 결과가 있거나, 그 변형이 확정 표로 나는 것.
 *  없으면 기본 줄로 접는다(줄만 늘고 칸은 전부 「기록 없음」인 목록을 만들지 않는다). */
function variantHasRecord(row, vid, metas) {
  if (row.gain_tables?.variants?.[vid]?.source === "confirmed") return true;
  return (metas ?? []).some((m) => m?.profile?.id === row.id && (m.profile.variant ?? null) === vid);
}

/**
 * 엔티티 막대 목록 — GET /profiles 행과 GET /results meta만으로 세운다(엔티티당 계산 0회).
 *
 * @param {Array} profiles GET /profiles 응답(읽을 수 없는 행 포함)
 * @param {Array} metas GET /results 응답(최근순 meta)
 * @param {{sel?: object|null, live?: object|null}} opt
 *   sel = 헤더에서 고른 엔티티({id, variant}) — **그 줄만** live 기록을 쓴다(모듈 stages에는 엔티티 키가
 *   없어, 안 가리면 A 기체 판정이 B 줄에 선다). live = 뷰의 stages(지금 세션이 직접 돈 기록).
 * @returns {{rows: Array, caption: string, notes: string[]}}
 */
export function entityRows(profiles, metas, { sel = null, live = null } = {}) {
  const rows = [];
  let variantTotal = 0;
  let variantWithRecord = 0;
  for (const p of profiles ?? []) {
    if (!p?.id) continue;
    const entities = [{ variant: null }];
    for (const v of p.variants ?? []) {
      if (!v?.id) continue;
      variantTotal += 1;
      if (variantHasRecord(p, v.id, metas)) {
        variantWithRecord += 1;
        entities.push({ variant: v.id, name: v.name ?? v.id });
      }
    }
    for (const e of entities) {
      const key = e.variant ? `${p.id}::${e.variant}` : p.id;
      const mySel = { id: p.id, variant: e.variant };
      const selected = sameSel(mySel, sel);
      const cells = cellsFor(p, e.variant, metas, selected ? live : null);
      const reach = reachOf(cells);
      const stop = stopOf(cells);
      const label = e.variant
        ? `${p.name ?? p.id} — ${e.name}`
        : (p.name ?? p.id) + (p.unreadable ? " (읽을 수 없음)" : "");
      rows.push({
        key, id: p.id, variant: e.variant, label,
        unreadable: !!p.unreadable, reason: p.reason ?? null,
        reach, cells, stop, selected, created: lastCreated(metas, mySel),
        tip: stop
          ? `${label} — ${reach.index < 0 ? "③ 초기 게인부터 아직 이어지지 않았다" : `「${reach.label}」까지`}`
            + ` · 멈춘 곳 ${stop.reason}`
          : `${label} — 채택·반영까지 이어졌다`,
      });
    }
  }
  rows.sort((a, b) => (b.reach.index - a.reach.index) || (b.created - a.created)
    || a.key.localeCompare(b.key));
  const reached = rows.filter((r) => r.reach.index >= 0).length;
  const blocked = rows.filter((r) => r.cells.some((c) => c.state === "blocked")).length;
  const unknown = rows.filter((r) => r.cells.some((c) => c.state === "unknown_verdict")).length;
  const caption = [
    `엔티티 ${rows.length}개(기체·형상 변형 하나의 제어법칙 설계 하나)`,
    `③ 초기 게인부터 이어진 줄 ${reached}개`,
    `막힌 줄 ${blocked}개`,
    `판정을 목록으로 알 수 없는 칸이 있는 줄 ${unknown}개`,
    variantTotal
      ? `형상 변형 ${variantTotal}개 중 ${variantWithRecord}개에 설계 기록(나머지는 기본 줄로 접었다)`
      : null,
  ].filter(Boolean).join(" · ");
  const notes = [
    "① 문서 검증·② 엔벨로프는 저장물이 없는 조회 단계다 — 목록은 도달을 그리지 않고 도달 계산에서도 뺀다. "
      + "[열기]로 그 엔티티의 레일에서 돌리면 판정이 그 칸에 선다.",
    "막대 위에는 글자가 없다 — 칸의 뜻은 색·무늬·테두리이고, 수는 이 캡션과 칸 툴팁이 말한다. 계산 상태는 "
      + "무늬·테두리(안 돌림 민무늬 · 건너뜀 사선 · 기록 없음 점 · 판정 모름 점선 테두리), 성능 판정은 "
      + "색(불합격 붉은색)이다.",
    "점선 테두리 칸은 「돌았으나 목록으로 판정을 알 수 없다」다 — 통과도 불합격도 아니다(옛 결과의 meta에 "
      + "판정 수·하드 게이트 기록이 없다).",
  ];
  return { rows, caption, notes };
}

// ── 엔티티 저장소 ① 트림 저장소 창 ────────────────────────────────────────────

/** 트림 저장소 칸 토큰 — 색은 lib/plot.js TRIM_STATE_CELL 한 벌. 미수렴 기록은 **원인을 가르지 않는다**:
 *  계산 실패·제약 도달·물리적 불가를 가르려면 한계 근거 풀이(SLSQP)가 필요한데 격자 조회는 그것을 돌리지
 *  않는다(서버 grid.py _mark_stored 머리말). 셋을 색으로 구별하면 없는 판정을 그리는 것이다. */
export const FE_TRIM_TOKENS = Object.freeze({
  stored_converged: { color: TRIM_STATE_CELL.computable.color, pattern: "none",
    label: "저장된 수렴 해 — 다음 실행이 재사용한다" },
  stored_unconverged: { color: STATUS.na, pattern: "diagonal",
    label: "저장된 미수렴 기록(원인 미판정) — 다음 실행이 다시 푼다" },
  not_run: { color: TRIM_STATE_CELL.unevaluated.color, pattern: "none", label: "기록 없음 — 보낼 점" },
  model_gap: { color: TRIM_STATE_CELL.model_gap.color, pattern: "none",
    label: TRIM_STATE_CELL.model_gap.label },
});

const trimTokenOf = (state) => (FE_TRIM_TOKENS[state] ? state : "not_run");

/**
 * 엔티티 저장소 창 — POST /grid/base 응답 점에 트림 저장소 기록(stored)을 얹은 표. 트림을 풀지 않는다.
 *
 * @param {object} baseGrid POST /grid/base 응답(동기 — 좌표와 저장소 엿보기만)
 * @param {object|null} lastTrimLike 마지막 trim_batch·influence_evaluate의 **결과 본문 또는 meta** —
 *   재사용 수와 저장소 창 지문의 근거. meta의 trim_reuse_counts에는 지문이 없다(서버 refs.reuse_counts가
 *   세 수만 남긴다) → 지문은 본문의 trim_reuse에서만 온다. 없으면 fingerprint는 null(「모름」)이다.
 */
export function trimStoreModel(baseGrid, lastTrimLike = null) {
  const points = Array.isArray(baseGrid?.points) ? baseGrid.points : [];
  const groups = new Map();
  const counts = { stored_converged: 0, stored_unconverged: 0, not_run: 0, model_gap: 0, other: 0 };
  for (const p of points) {
    const gk = `${p.alt}|${p.fuel}`;
    if (!groups.has(gk)) groups.set(gk, { alt: p.alt, fuel: p.fuel, cells: [] });
    const stored = !!(p.stored && typeof p.stored === "object");
    const state = stored
      ? (p.stored.converged ? "stored_converged" : "stored_unconverged")
      : (p.state ?? "not_run");
    if (counts[state] == null) counts.other += 1; else counts[state] += 1;
    const tone = trimTokenOf(state);
    const text = FE_TRIM_TOKENS[tone].label;
    groups.get(gk).cells.push({ mach: p.mach, name: p.name, state, stored, tone,
      text: stored ? text : `${text}(격자 상태 ${p.state ?? "없음"})` });
  }
  const rows = [...groups.values()].sort((a, b) => a.alt - b.alt || a.fuel - b.fuel);
  for (const r of rows) r.cells.sort((a, b) => a.mach - b.mach);
  const echo = lastTrimLike?.trim_reuse ?? null;
  const c = echo ?? lastTrimLike?.trim_reuse_counts ?? null;
  const reuse = c
    ? { reused: cnt(c.reused), computed: cnt(c.computed), resolved_failed: cnt(c.resolved_failed),
      policy: echo?.policy ?? null }
    : null;
  const notes = [
    "저장소 창의 키는 플랜트 + 풀이 설정 지문입니다 — 기체 1:1이 아닙니다. 플랜트를 바꾸지 않는 형상 변형은 "
      + "기본형과 같은 창을 쓰고(해를 그대로 재사용합니다), 플랜트를 바꾸는 변형만 자기 창을 갖습니다.",
    "미수렴 기록은 「미수렴(원인 미판정)」 하나다 — 계산 실패·제약 도달·물리적 불가를 가르려면 한계 근거 "
      + "풀이가 필요한데 이 조회는 그것을 돌리지 않는다. 셋을 색으로 구별하지 않는다.",
    reuse ? null : "마지막 트림·평가 결과의 재사용 되울림이 없어 재사용 수는 모른다.",
  ].filter(Boolean);
  return { fingerprint: echo?.trim_fingerprint ?? null, rows, counts, reuse, notes };
}

// ── 엔티티 저장소 ② 게인값 3층(시드 · 설계 · 확정) ──────────────────────────────

/** 튜너가 잡는 7자리 — 닫는 순서(레이트: 피치·요·롤) 뒤 자세. quickseed.js의 SLOT_ORDER와 같은 순서다. */
const SLOT_ORDER = ["pitch.k_rate", "yaw.k_rate", "roll.k_rate", "pitch.kp", "pitch.ki",
  "roll.kp", "roll.ki"];

/** 판정 자리(루프) → 그 루프를 성형하는 게인 자리 — 엔진 claw.design.tune.LOOP_SLOTS 그대로. */
export const LOOP_SLOTS = Object.freeze({
  pitch_att: ["pitch.kp", "pitch.ki"],
  pitch_rate: ["pitch.k_rate"],
  roll_att: ["roll.kp", "roll.ki"],
  roll_rate: ["roll.k_rate"],
  yaw_rate: ["yaw.k_rate"],
});

const SLOT_LOOPS = (() => {
  const out = {};
  for (const [loop, slots] of Object.entries(LOOP_SLOTS)) {
    for (const s of slots) (out[s] ??= []).push(loop);
  }
  return out;
})();

// 나쁜 쪽이 이긴다 — 모르는 status는 중간(2)으로 둔다(ok로 낙관하지 않는다)
const STATUS_RANK = { ok: 1, warn: 2, capped: 2, infeasible: 3, failed: 3 };
const rank = (s) => (s == null ? 2 : (STATUS_RANK[s] ?? 2));

/** 한 자리의 설계층 — 연 결과 본문의 tune_meta.slots[점][루프]를 이 자리로 접는다(루프→자리는 LOOP_SLOTS).
 *  점마다 다르므로 **가장 나쁜 판정**과 그 점을 싣는다 — 한 점의 값으로 자리를 대표하지 않는다. */
function designLayer(body, slot) {
  if (!body) return null;
  const loops = SLOT_LOOPS[slot] ?? [];
  let picked = null;
  let points = 0;
  for (const [point, byLoop] of Object.entries(body.tune_meta?.slots ?? {})) {
    for (const loop of loops) {
      const r = byLoop?.[loop];
      if (!r) continue;
      points += 1;
      if (!picked || rank(r.status) >= rank(picked.status)) {
        picked = { status: r.status ?? null, reason: r.reason ?? null, target: numOr(r.target),
          achieved: numOr(r.achieved), point };
      }
    }
  }
  const constants = body.gain_export?.constants ?? {};
  const table = body.gain_export?.tables_resampled?.[slot] ?? body.gain_export?.tables?.[slot] ?? null;
  const value = Object.prototype.hasOwnProperty.call(constants, slot) ? numOr(constants[slot]) : null;
  const fit = body.fits?.[slot] ?? null;
  if (!picked && value == null && !table && !fit) return null;
  return {
    // 상수로 적합된 자리만 한 값이다 — 표인 자리는 null(값은 표에 있다)
    value,
    status: picked?.status ?? null, reason: picked?.reason ?? null,
    target: picked?.target ?? null, achieved: picked?.achieved ?? null,
    point: picked?.point ?? null, points,
    shape: table ? "table" : (value != null ? "constant" : null),
    // null = 적합 보고가 없어 모름(0으로 위조하지 않는다)
    fit_excluded: fit ? Object.keys(fit.excluded_samples ?? {}).length : null,
  };
}

/** 한 자리의 확정층 — 문서 law.gain_tables. 절점 수는 표의 마하 축 길이다(없으면 null). */
function confirmedLayer(doc, gainTablesStale, slot) {
  const gt = doc?.law?.gain_tables ?? null;
  const t = gt?.tables?.[slot] ?? null;
  if (!t) return null;
  const mach = t.axes?.mach;
  return { source: gt.provenance?.source ?? null,
    n_knots: Array.isArray(mach) ? mach.length : null, stale: gainTablesStale, shape: "table" };
}

/** 시드 층 기록 — **출처마다 모양이 다르다**(계약이 한 모양으로 적어 둔 곳). 문서의 law.design.provenance.slots는
 *
 *  - 빠른 탐색(quick_seed, 엔진 design/seed.py): {value, sign_basis, anchors_used, reason, reason_text}
 *  - 산출 근거 직행(seed_basis, 엔진 design/basis.py): 레이트 자리는 {k, stored, schedule_factor, achieved,
 *    stable, budget_ok}이고 **자세는 두 자리를 한 키에 묶는다** — "pitch.kp/ki": {kp, ki, stored_kp, stored_ki,
 *    schedule_factor_kp, schedule_factor_ki, passing, reason}
 *
 *  둘을 한 모양으로 접는다: value는 **문서에 든 값**(stored — 조립이 스케줄 배수를 도로 곱해 그 점의 값이 된다)이고
 *  basis는 그 값이 어디서 왔나의 한 줄이다. 묶인 키는 두 자리로 편다 — 안 펴면 "pitch.kp/ki"가 자리 이름인 줄
 *  화면에 서고(실측: 예제 기체에서 자리 9개가 나왔다) 정작 pitch.kp·pitch.ki 줄은 「기록 없음」이 된다.
 *  모양을 모르는 기록은 value를 짐작하지 않는다(kind "unknown").
 */
function seedRecord(source, r, pick = null) {
  const base = { kind: source ?? "unknown", reason: null, reason_text: null, anchors_used: null,
    stable: null };
  const bad = (v) => (v == null || v === "ok" ? null : v);
  if (pick) {
    const f = numOr(r[`schedule_factor_${pick}`], numOr(r.schedule_factor));
    return { ...base, kind: "seed_basis", value: numOr(r[`stored_${pick}`]),
      basis: `한 점 산출 근거 ${pick}=${numOr(r[pick]) ?? "모름"}`
        + (f == null ? "" : ` · 스케줄 배수 ${f}`)
        + (r.passing === false ? " · 이 점 판정 미달" : ""),
      reason: bad(r.reason), reason_text: null, stable: r.passing ?? null };
  }
  if (r.sign_basis != null || r.value != null) {
    return { ...base, kind: source ?? "quick_seed", value: numOr(r.value),
      basis: r.sign_basis ?? null, anchors_used: numOr(r.anchors_used),
      reason: bad(r.reason), reason_text: r.reason_text ?? null };
  }
  if (r.k != null || r.stored != null) {
    const f = numOr(r.schedule_factor);
    return { ...base, kind: "seed_basis", value: numOr(r.stored),
      basis: `한 점 산출 근거 k=${numOr(r.k) ?? "모름"}`
        + (f == null ? "" : ` · 스케줄 배수 ${f}`)
        + (r.achieved == null ? "" : ` · 달성 ${numOr(r.achieved)}`)
        + (r.budget_ok === false ? " · 예산 초과" : ""),
      reason: bad(r.reason), stable: r.stable ?? null };
  }
  // 모르는 모양 — 값을 짐작하지 않는다
  return { ...base, value: null, basis: "기록 모양을 모른다(값을 짐작하지 않는다)" };
}

/** 문서의 시드 기록 → {자리: 기록} — 묶인 키("pitch.kp/ki")를 두 자리로 편다. */
function seedSlotRecords(doc) {
  const prov = doc?.law?.design?.provenance ?? null;
  const source = prov?.source ?? null;
  const out = {};
  for (const [name, r] of Object.entries(prov?.slots ?? {})) {
    if (!r || typeof r !== "object") continue;
    if (!name.includes("/")) { out[name] = seedRecord(source, r); continue; }
    const [head, ...rest] = name.split("/");
    const group = head.split(".")[0];
    const first = head.split(".").slice(1).join(".");
    for (const part of [first, ...rest]) {
      if (part) out[`${group}.${part}`] = seedRecord(source, r, part);
    }
  }
  return out;
}

/**
 * 게인값 3층 — 시드(문서) · 설계(연 결과) · 확정(문서). **자리별 줄은 이 안에만 산다** — 최상위 막대는
 * 엔티티이고 자리가 아니다(사용자 논거).
 *
 * @param {object} doc GET /profiles/{id} 응답의 document(law.design.provenance·law.gain_tables)
 * @param {object|null} designBody 연 자동 설계 결과 본문(tune_meta·fits·gain_export) — 없으면 설계층은 null
 * @param {{gainTablesStale?: boolean|null}} opt 확정 표 낡음은 **서버 목록 판정**(gain_tables.stale)이다 —
 *   브라우저가 다시 판정하지 않는다. 안 주면 null(모름)
 */
export function gainLayersModel(doc, designBody = null, { gainTablesStale = null } = {}) {
  const seedSlots = seedSlotRecords(doc);
  const names = [...SLOT_ORDER];
  for (const extra of [
    ...Object.keys(seedSlots),
    ...Object.keys(doc?.law?.gain_tables?.tables ?? {}),
    ...Object.keys(designBody?.gain_export?.tables_resampled ?? {}),
    ...Object.keys(designBody?.gain_export?.constants ?? {}),
  ]) {
    if (!names.includes(extra)) names.push(extra);
  }
  const slots = names.map((slot) => {
    return {
      slot, group: slot.split(".")[0],
      seed: seedSlots[slot] ?? null,
      design: designLayer(designBody, slot),
      confirmed: confirmedLayer(doc, gainTablesStale, slot),
    };
  }).filter((r) => r.seed || r.design || r.confirmed);
  const notes = [
    "세 층은 서로 다른 것을 말한다 — 시드는 문서의 초기 탐색 게인(자동 설계 전), 설계는 연 결과가 그 자리에서 "
      + "무엇을 달성했나, 확정은 문서에 반영된 표다. 층이 비어 있으면 그 층의 기록이 없는 것이다.",
    designBody ? null : "자동 설계 결과를 열지 않았다 — 설계층은 기록 없음이다(0이 아니다).",
    gainTablesStale == null && doc?.law?.gain_tables
      ? "확정 표의 낡음 판정은 서버 목록이 준다 — 지금 그 값이 없어 낡음을 말하지 않는다."
      : null,
  ].filter(Boolean);
  return { slots, notes };
}
