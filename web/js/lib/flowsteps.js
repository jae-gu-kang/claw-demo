/** 설계 흐름 탭의 단계 판정 — 각 단계 응답을 한 줄 판정으로 (06 §3, v1.33 파이프라인 유기화 3단계).

여기는 **줄 세우기만** 한다: 판정 재료(검증 ok·경고 수, 엔벨로프 region·limits_source, 시드
채택(quickseed.seedSummary가 판 것), 자동 설계 report.status, 평가 aggregate.hard_fail)는 전부
서버 응답이고, 문구도 그 수를 옮길 뿐이다. 실행·순서는 뷰(views/flow.js) 소관.

tone 어휘는 평가 카드와 같은 넷(ok·warn·bad·na) — 화면이 flag 배지로 그대로 그린다.
*/

import { failureRoleText } from "./autodesign.js";

/** 단계 정의 — key·이름·드릴다운 탭. 순서가 곧 [끝까지 실행]의 순서다.
 *  apply(채택·문서 반영)는 실행 단계가 아니라 **수동 관문**이다(사용자 결정) — run이 없다.
 *  단계 **수(6)는 화면과 결합돼 있다**: app.css .fd-rail의 repeat(6,1fr)·8.33%(=1/12) 마디
 *  여백이 같은 수를 전제한다 — 단계를 늘리면 CSS를 같이 고친다(리뷰 지적; 번호 숫자는
 *  flow.js가 인덱스+1로 만든다). */
export const FLOW_STAGES = [
  { key: "doc", label: "문서 검증", tab: "#aircraft" },
  { key: "envelope", label: "엔벨로프", tab: "#envelope" },
  { key: "seed", label: "초기 게인", tab: "#aircraft" },
  { key: "design", label: "자동 설계", tab: "#autodesign" },
  { key: "eval", label: "평가", tab: "#influence" },
  { key: "apply", label: "채택·문서 반영", tab: "#autodesign", manual: true },
];

/** 문서 검증 응답({ok, warnings, fingerprint}) → 판정. 경고는 통과이되 수를 말한다. */
export function docVerdict(res) {
  if (!res?.ok) return { tone: "bad", text: "검증 실패" };
  const n = res.warnings?.length ?? 0;
  return { tone: n ? "warn" : "ok",
    text: n ? `통과 — 문서 경고 ${n}건(기체 탭에서 확인)` : "통과" };
}

/** 설계 엔벨로프 응답 → 판정 — 성립 고도 수와 자리표시 한계 여부.
 *  region은 **컬럼형**({alt: [...], empty: [...], …} — 서버 직렬화 형상)이다. */
export function envelopeVerdict(res) {
  const empty = res?.region?.empty;
  if (!Array.isArray(empty) || !empty.length) {
    return { tone: "na", text: "엔벨로프 응답에 고도 줄이 없습니다" };
  }
  const nonEmpty = empty.filter((e) => !e).length;
  const placeholder = res.limits_source !== "profile";
  if (!nonEmpty) {
    return { tone: "bad",
      text: `성립 영역 없음 — 고도 ${empty.length}줄 전부 비었습니다(트림·추력 확인)` };
  }
  return { tone: placeholder ? "warn" : "ok",
    text: `성립 고도 ${nonEmpty}/${empty.length}줄`
      + (placeholder ? " — 구조 한계는 예제 자리표시(실기체 값 아님, 기체 탭에서 입력)" : "") };
}

/** 초기 게인 단계 — 실행 전 상태 판정: 설계 게인이 있으면 생략, 없으면 탐색 대상. */
export function seedStateVerdict(designSource) {
  if (designSource == null) {
    return { tone: "na", text: "게인 미설계 — 빠른 탐색을 실행합니다", run: true };
  }
  return { tone: "ok", run: false,
    text: `게인 있음(출처 ${designSource}) — 탐색 생략(다시 탐색은 기체 탭)` };
}

/** 자동 설계 결과 → 판정 — gated 승인 대기는 흐름을 멈추는 관문이다.
 *
 * 실패 0이 곧 통과가 아니다(자동 설계 탭 adoptBlockedText와 같은 규약). 「전 판정 통과」는 **수렴했을
 * 때만**이다: 판정이 0이면(nothing_verified) 실패 0은 아무것도 검증하지 않았다는 뜻이고, 취소처럼
 * 수렴 전에 멈춘 실행의 실패 0은 끝까지 보지 않았다는 뜻이다 — 종전에는 셋 다 「전 판정 통과」라 적었다.
 * 미달이 있으면 위치(앵커·검증점)를 붙인다 — 탭 상태 줄과 같은 함수(lib/autodesign failureRoleText). */
export function designVerdict(body) {
  const st = body?.report?.status;
  if (st == null) return { tone: "na", text: "결과에 보고서가 없습니다" };
  if (st === "awaiting_approval") {
    return { tone: "warn", stop: true,
      text: "처방 승인 대기 — 자동 설계 탭에서 카드를 승인해 재개한 뒤 흐름을 이어 갑니다" };
  }
  const r = body.report;
  const failures = Number(r.failures) || 0;
  const tone = st === "converged" ? (failures ? "warn" : "ok") : "warn";
  if (failures) {
    const where = failureRoleText(r.failures_by_role);
    return { tone, text: `${st} — 미달 ${failures}건${where ? `(${where})` : ""} — 자동 설계 탭 원장` };
  }
  // judged가 없는 옛 결과는 이 판정을 못 한다 — 없는 수를 0으로 읽지 않는다
  if (r.judged != null && !(Number(r.judged) > 0)) {
    return { tone, text: `${st} — 판정 0: 실패 0은 통과가 아니다(아무것도 검증하지 않았다)` };
  }
  if (st !== "converged") return { tone, text: `${st} — 실패 0이나 수렴 전에 멈췄다` };
  return { tone, text: `${st} — 전 판정 통과` };
}

/** 평가(엔진 평가 전체) 결과(normalizeEvalReport) → 판정 — 하드 게이트가 최종선이다. */
export function evalVerdict(m) {
  const agg = m?.aggregate;
  if (agg?.hard_fail == null) return { tone: "na", text: "하드 게이트 판정 보류(케이스 0건)" };
  if (agg.hard_fail) {
    return { tone: "bad",
      text: `하드 게이트 위반 ${(agg.hard_fails ?? []).length}건 — Fail(영향성 탭 상세)` };
  }
  return { tone: "ok", text: `하드 게이트 전부 통과 · depth=${m.depth}` };
}

/** 채택·반영 단계의 상태 — 목록 요약의 확정 표(gain_tables)와 이 흐름의 설계 결과 유무로.
 *
 * hasDesignResult는 **설계 결과가 있는가**다(반영 가능한가가 아니다). 결과는 있는데 반영이 막힌
 * 경우(승인 대기·예제·변형·낡음)는 blockReason이 그 사유를 말한다 — 종전에는 뷰가 "막히지 않음"을
 * 이 자리에 넘겨, 승인 대기 결과가 있어도 "자동 설계를 먼저 돌립니다"가 떴다. */
export function applyStateVerdict(gainTables, hasDesignResult, blockReason = null) {
  if (gainTables && !gainTables.stale) {
    return { tone: "ok", text: `문서에 확정 게인 표 반영됨(출처 ${gainTables.source ?? "기록 없음"})` };
  }
  if (gainTables?.stale) {
    return { tone: "warn", text: "확정 게인 표가 낡았습니다 — 자동 설계를 다시 돌려 반영합니다" };
  }
  if (hasDesignResult && blockReason) {
    return { tone: "na", text: `미반영 — ${blockReason}` };
  }
  if (hasDesignResult) {
    return { tone: "na", text: "미반영 — 아래 [문서에 반영]이 정본에 씁니다(수동 관문)" };
  }
  return { tone: "na", text: "미반영 — 자동 설계를 먼저 돌립니다" };
}

/** [문서에 반영] 관문의 신선도 사유 — null이면 이 관문은 막지 않는다. 설계가 잰 문서와 지금 문서가
 *  다르면 서버가 409로 거절한다(지문 가드) — 버튼 앞에서 같은 판정을 한다. applied(이 결과를 이미
 *  반영 — 달라진 것이 제 표뿐)도 막는다: 반영이 지문을 바꿨으니 재반영은 서버가 거절하고, 다시 쓸
 *  것도 없다. 문구는 둘을 가른다 — 반영된 결과에 "문서가 다르다"고 하면 고친 적 없는 사용자를 속인다. */
export function applyFreshnessBlock(freshState) {
  if (freshState === "applied") {
    return "이 결과는 이미 문서에 반영했다 — 다시 반영할 것이 없다(새로 설계하면 그 결과를 반영한다)";
  }
  if (freshState === "stale") {
    return "설계가 잰 문서와 지금 문서가 다르다(이미 반영했거나 문서를 고쳤다) — 자동 설계를 다시 돌린 뒤 반영한다";
  }
  return null;
}

/** 결과 목록(최근순 meta)에서 이 기체·형상 변형의 가장 최근 kind 결과 — 없으면 null.
 *  기체 기록(meta.profile)이 없는 옛 결과는 어느 기체 것인지 모르므로 고르지 않는다. */
export function latestResultFor(metas, kind, sel) {
  const id = sel?.id;
  if (!id) return null;
  const variant = sel.variant ?? null;
  return (metas ?? []).find((m) => m?.kind === kind && m.profile?.id === id
    && (m.profile.variant ?? null) === variant) ?? null;
}

/** 레일 단계 상태 목록 — [{key, label, state, text, fresh, resultId}] (신호 보고 data.steps).
 *  state: 실행 중이면 "running", 판정이 있으면 그 tone(ok·warn·bad·na), 안 돌렸으면 "none".
 *  apply는 기록이 아니라 문서 상태로 판정하므로 applyVerdict를 따로 받는다(화면과 같은 판정).
 *  fresh는 freshOf(echo, resultId) — 화면의 「낡음」·「문서에 반영됨」 배지와 같은 대조(lib/freshness.js)다.
 *  결과 id를 함께 넘긴다: 반영 직후의 자동 설계 결과는 그 id로만 applied가 된다. */
export function flowStepStates(stages, applyVerdict, freshOf = () => "unknown") {
  return FLOW_STAGES.map((s) => {
    const st = stages?.[s.key];
    const v = s.key === "apply" ? applyVerdict : st?.verdict;
    return {
      key: s.key,
      label: s.label,
      state: st?.state === "running" ? "running" : (v?.tone ?? "none"),
      text: v?.text ?? null,
      fresh: st?.echo ? freshOf(st.echo, st.resultId ?? null) : "unknown",
      resultId: st?.resultId ?? null,
    };
  });
}

const STEP_WORD = { ok: "통과", warn: "주의", bad: "실패", na: "—", none: "안 돌림", running: "실행 중" };
// 신선도 꼬리 — 레일 배지와 같은 글자. 신선·판정 불가는 조용하다
const FRESH_TAIL = { stale: "(낡음)", applied: "(문서에 반영됨)" };

/** 단계 상태 → 한 줄 — 「문서 검증 주의 · 엔벨로프 통과 · … · 자동 설계 주의(낡음)」. 판정어는
 *  레일 칩과 같은 어휘다(새 판정 없음). */
export function flowSummaryLine(steps) {
  return (steps ?? []).map((s) =>
    `${s.label} ${STEP_WORD[s.state] ?? s.state}${FRESH_TAIL[s.fresh] ?? ""}`).join(" · ");
}

/** 단계 산출물 서술 — 이 단계의 저장물이 **어디에** 남았나 (v1.35 다이어그램 발치줄).
 *
 * 사용자 요구 "진행 상황과 저장 파일들이 어디에 있는지 확실히"의 절반이 이 줄이다:
 * 조회 단계(검증·엔벨로프)는 저장이 없다고 말하고, 잡 단계는 결과 저장소의 그 결과를,
 * 문서에 쓴 단계(시드 채택·확정 표 반영)는 문서 리비전을 가리킨다. 없는 결과·안 쓴
 * 문서를 위조하지 않는다. `to`는 뷰가 링크로 배선하는 목적지 표지(brief=결과 탭 브리핑,
 * design=자동 설계 탭 보고서, aircraft=기체 탭, gains=게인 탭)다.
 */
export function stageArtifact(key, st) {
  if (key === "doc") return [{ label: "저장 없음 — 문서 판정만", to: null }];
  if (key === "envelope") return [{ label: "저장 없음 — 조회 계산", to: null }];
  if (key === "apply") {
    // "쓰는 곳" 프레이밍 — 이 줄은 목적지이지 저장됐다는 뜻이 아니다(반영 여부는 위 판정 칩이
    // 말한다). "문서 law.gain_tables"라고만 적으면 확정 표 없는 문서에서도 저장된 것처럼 읽힌다
    return [{ label: "쓰는 곳 — 문서 law.gain_tables(확정 표)", to: "gains" }];
  }
  if (key === "seed") {
    if (!st?.resultId) return [{ label: "저장 없음 — 미실행·탐색 생략", to: null }];
    const out = [{ label: `결과 ${st.resultId}`, to: "brief" }];
    // 채택·저장(ok = seedSummary ok && written)일 때만 문서 항목 — 미채택 결과가 문서에
    // 저장된 것처럼 읽히면 안 된다
    if (st.verdict?.tone === "ok" && st.echo?.revision != null) {
      out.push({ label: `문서 리비전 ${st.echo.revision}에 저장`, to: "aircraft" });
    }
    return out;
  }
  if (!st?.resultId) return [{ label: "결과 저장소(잡 산출물)", to: null }];
  return [{ label: `결과 ${st.resultId}`, to: key === "design" ? "design" : "brief" }];
}
