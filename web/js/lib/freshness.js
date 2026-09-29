/** 결과 신선도 — 결과 meta의 기체 echo를 지금 기체 목록과 지문 대조 (06 §4, v1.32).

인계물은 결과가 아니라 정본(문서)이다 — 그래서 결과는 낡을 수 있고, 낡음을 화면이 말해야 사용자가
사슬을 눈으로 관리한다(파이프라인 유기화 2단계). 판정 재료는 전부 서버가 준 것이다: echo의
리비전·지문(계산 시점)과 목록의 지문(지금 — 변형 지문 포함). 여기는 대조와 문구뿐이다.

상태 여섯 — fresh(같음: 조용, 배지 남발 금지) · stale(다름: 계산 시점과 지금을 함께 말한다) ·
applied(다르지만 달라진 것이 **이 결과 자신의 산출물뿐** — 자동 설계 결과의 확정 게인 표를 문서에
반영한 직후. 반영이 표를 써서 지문이 바뀌므로 지문만 보면 그 결과가 곧바로 낡음으로 보였다. 신선과
같은 무게다) · gone(기체·변형이 목록에 없음) · unreadable(기체가 id를 점유한 채 손상 — "지워졌다"고
하면 같은 id로 다시 만들 수 있는 것처럼 읽힌다) · unknown(기체 기록 없는 옛 결과·목록 미수신 — 낡음으로
위장하지 않는다).

applied의 재료도 서버 것이다 — 목록 행의 applied_design({result_id, revision})은 "표 절이 반영한 그대로이고
표 밖은 반영 뒤 그대로"일 때만 서고(server profiles._applied_design), 반영 자체는 결과의 지문과 문서가 같을
때만 받는다(apply-gains 409). 여기는 결과 id 대조뿐이다 — 이름이 불린 그 결과만 applied이고, 같은
문서로 계산한 다른 결과(트림·마진·시뮬, 다른 자동 설계)는 표가 그 계산을 실제로 바꾸므로 낡음 그대로다.
*/

/** resultId — 그 결과의 id(applied 대조 재료). 안 넘기면 applied를 판정하지 않는다(종전 판정). */
export function resultFreshness(echo, rows, resultId = null) {
  if (!echo?.fingerprint) return { state: "unknown", label: null };
  if (!Array.isArray(rows)) return { state: "unknown", label: null };
  const row = rows.find((p) => p.id === echo.id);
  if (!row) {
    return { state: "gone",
      label: `계산한 기체(${echo.id})가 지금 목록에 없습니다 — 지워졌거나 저장소가 비워졌습니다`
        + "(결과·스냅숏은 남습니다)" };
  }
  if (row.unreadable) {
    return { state: "unreadable",
      label: `계산한 기체(${echo.id})를 지금 읽을 수 없습니다 — ${row.reason ?? "손상"}. `
        + "id는 남아 있습니다(기체 탭에서 지운 뒤 다시 만드는 것이 복구 경로)" };
  }
  const fp = echo.variant
    ? (row.variants?.find((v) => v.id === echo.variant)?.fingerprint ?? null)
    : row.fingerprint;
  if (fp == null) {
    return { state: "gone",
      label: `계산한 형상 변형(${echo.id} / ${echo.variant})이 지금 문서에 없습니다` };
  }
  if (fp === echo.fingerprint) return { state: "fresh", label: null };
  // 변형 위에서 돈 설계는 기본 문서에 반영될 수 없다(서버 422) — 기본 형상 결과만 대조한다
  const applied = row.applied_design;
  if (resultId != null && !echo.variant && applied?.result_id === resultId) {
    return { state: "applied",
      label: `이 결과의 확정 게인 표가 문서 리비전 ${applied.revision}에 반영돼 있습니다 — 계산 시점`
        + `(리비전 ${echo.revision ?? "—"}) 이후 문서가 달라진 것은 이 결과 자신의 산출물(law.gain_tables)뿐이라 `
        + "낡음이 아닙니다" };
  }
  return { state: "stale",
    label: `이 결과는 리비전 ${echo.revision ?? "—"}·지문 ${echo.fingerprint}로 계산했습니다 — `
      + `지금 문서(리비전 ${row.revision}·지문 ${fp})와 다릅니다. 다시 계산해야 지금 기체를 말합니다` };
}

/** 판정 기준 신선도 (기준 통합 ① S4c) — 결과의 criteria_echo를 **그 결과를 계산한 기체의 지금 기준**
(GET /profiles/{id}/criteria의 echo)과 대조한다. 재료는 전부 서버 것이다: 판정 기준 지문·목표 지문·판정 함수
버전(scheme). 여기는 대조와 문구뿐이다.

상태 다섯 — fresh(같음: 조용) · reeval(판정 기준 지문 또는 판정 함수 버전이 다름: 합격·불합격이 지금 기준과
다를 수 있다) · rescore(목표 지문만 다르고 결과가 목표로 J를 매긴 종류 — 영향성 평가·처방) ·
target_changed(목표 지문만 다르고 자동 설계 — 게인은 여전히 유효하되 다른 목표로 설계했다) ·
unknown(echo·scheme 없는 옛 결과, 지금 기준 미수신 — 낡음으로 위장하지 않는다. 옛 결과의
`criteria_fingerprint`는 정의가 달라 대조하지 않는다). 목표를 안 쓰는 종류(마진 맵·스캔·진단·검증)는 목표만
다르면 fresh다. */

/** 판정에 목표(J)를 쓰는 결과 종류 — 목표만 달라져도 J를 다시 매겨야 한다. */
export const TARGET_SCORED_KINDS = new Set(["influence_evaluate", "influence_prescribe"]);
/** 목표로 설계한 결과 종류 — 목표만 달라지면 "다른 목표로 설계함"(무효는 아니다). */
export const TARGET_DESIGNED_KINDS = new Set(["auto_design"]);
/** 기준으로 판정하는 저장 결과 종류 — 결과 목록은 이 종류에만 기준 배지를 판단한다(시뮬 등은 기준과 무관이라
 *  「미상」을 달면 거짓이다). 트림 탭(trim_batch)·설계 엔벨로프 스캔(envelope_scan)은 스키마 v3부터 여유 판정(포화·스로틀·
 *  트림 α 여유 — 판정선 criteria.trim_margin, 이관 12단계)을 결과에 굳히므로 든다 — 그 판정선을 바꾸면 다시 판정해야 한다.
 *  그 전에 저장된 트림·스캔 결과는 echo가 없어 「판정 기준 미상」이다(낡음으로 위장하지 않는다). */
export const CRITERIA_JUDGED_KINDS = new Set([
  "influence_scan", "influence_evaluate", "influence_verify", "influence_prescribe", "influence_diagnose",
  "auto_design", "margin_map", "trim_batch", "envelope_scan",
]);

export const CRITERIA_FRESHNESS = {
  fresh: { label: null, tone: null, tip: null },
  unknown: { label: "판정 기준 미상", tone: "na",
    tip: "이 결과에는 어느 판정 기준으로 판정했는지 기록(criteria_echo)이 없거나, 지금 기체의 기준을 받지 못했습니다 "
      + "— 기준 통합(v1.52) 이전 결과일 수 있습니다. 낡았다는 뜻은 아닙니다" },
  reeval: { label: "재평가 필요", tone: "bad",
    tip: "이 결과를 판정한 기준(합격·권장선 또는 판정 함수 버전)이 지금 기체 프로파일의 기준과 다릅니다 — "
      + "합격·불합격이 지금 기준과 다를 수 있으니 다시 실행하십시오" },
  rescore: { label: "J 재계산 필요", tone: "warn",
    tip: "판정선은 같지만 튜닝 목표(목표·가중치)가 지금 기체 프로파일과 다릅니다 — 판정은 유효하나 "
      + "목표로 매긴 J 점수는 다시 계산해야 지금 목표를 말합니다" },
  target_changed: { label: "현재 튜닝 목표와 다름", tone: "na",
    tip: "판정선은 같지만 이 설계는 지금과 다른 튜닝 목표로 만들었습니다 — 게인이 무효인 것은 아니고, "
      + "지금 목표로 설계하면 다른 게인이 나올 수 있습니다" },
};

/** resultEcho — 결과의 criteria_echo · currentEcho — 지금 기준의 echo · kind — 결과 종류(meta.kind). */
export function criteriaFreshness(resultEcho, currentEcho, kind) {
  if (!resultEcho?.scheme || !currentEcho?.scheme) return "unknown";
  if (resultEcho.scheme !== currentEcho.scheme) return "reeval";
  if (!resultEcho.judgement_fingerprint || !currentEcho.judgement_fingerprint) return "unknown";
  if (resultEcho.judgement_fingerprint !== currentEcho.judgement_fingerprint) return "reeval";
  if (resultEcho.targets_fingerprint === currentEcho.targets_fingerprint) return "fresh";
  if (TARGET_SCORED_KINDS.has(kind)) return "rescore";
  if (TARGET_DESIGNED_KINDS.has(kind)) return "target_changed";
  return "fresh";
}

/** 배지 재료 {label, tone, tip} — fresh·모르는 상태는 null(배지 없음). */
export function criteriaBadgeSpec(state) {
  const s = CRITERIA_FRESHNESS[state];
  return s?.label ? s : null;
}

/** 기체 id → 지금 기준 echo 조회기 — 한 화면 그리기(render) 동안 기체당 한 번만 부른다.
 *  get(path) → Promise. 실패는 null(→ unknown)로 조용히 — 판정 불가를 낡음으로 위장하지 않는다. */
export function criteriaEchoCache(get) {
  const memo = new Map();
  return (profileId) => {
    if (!profileId) return Promise.resolve(null);
    if (!memo.has(profileId)) {
      memo.set(profileId, Promise.resolve()
        .then(() => get(`/profiles/${encodeURIComponent(profileId)}/criteria`))
        .then((r) => r?.echo ?? null, () => null));
    }
    return memo.get(profileId);
  };
}
