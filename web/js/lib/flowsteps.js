/** 설계 흐름 탭의 단계 판정 — 각 단계 응답을 한 줄 판정으로 (06 §3, v1.33 파이프라인 유기화 3단계).

여기는 **줄 세우기만** 한다: 판정 재료(검증 ok·경고 수, 엔벨로프 region·limits_source, 시드
채택(quickseed.seedSummary가 판 것), 자동 설계 report.status, 평가 aggregate.hard_fail)는 전부
서버 응답이고, 문구도 그 수를 옮길 뿐이다. 실행·순서는 뷰(views/flow.js) 소관.

tone 어휘는 평가 카드와 같은 넷(ok·warn·bad·na) — 화면이 flag 배지로 그대로 그린다.
*/

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

/** 자동 설계 결과 → 판정 — gated 승인 대기는 흐름을 멈추는 관문이다. */
export function designVerdict(body) {
  const st = body?.report?.status;
  if (st == null) return { tone: "na", text: "결과에 보고서가 없습니다" };
  if (st === "awaiting_approval") {
    return { tone: "warn", stop: true,
      text: "처방 승인 대기 — 자동 설계 탭에서 카드를 승인해 재개한 뒤 흐름을 이어 갑니다" };
  }
  const failures = body.report.failures ?? 0;
  const tone = st === "converged" ? (failures ? "warn" : "ok") : "warn";
  return { tone,
    text: `${st}${failures ? ` — 미달 ${failures}건(자동 설계 탭 원장)` : " — 전 판정 통과"}` };
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

/** 채택·반영 단계의 상태 — 목록 요약의 확정 표(gain_tables)와 이 흐름의 설계 결과 유무로. */
export function applyStateVerdict(gainTables, hasDesignResult) {
  if (gainTables && !gainTables.stale) {
    return { tone: "ok", text: `문서에 확정 게인 표 반영됨(출처 ${gainTables.source ?? "기록 없음"})` };
  }
  if (gainTables?.stale) {
    return { tone: "warn", text: "확정 게인 표가 낡았습니다 — 자동 설계를 다시 돌려 반영합니다" };
  }
  if (hasDesignResult) {
    return { tone: "na", text: "미반영 — 아래 [문서에 반영]이 정본에 씁니다(수동 관문)" };
  }
  return { tone: "na", text: "미반영 — 자동 설계를 먼저 돌립니다" };
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
