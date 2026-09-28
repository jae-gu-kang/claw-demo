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
