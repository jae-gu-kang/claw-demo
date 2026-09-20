/** 결과 신선도 — 결과 meta의 기체 echo를 지금 기체 목록과 지문 대조 (06 §4, v1.32).

인계물은 결과가 아니라 정본(문서)이다 — 그래서 결과는 낡을 수 있고, 낡음을 화면이 말해야 사용자가
사슬을 눈으로 관리한다(파이프라인 유기화 2단계). 판정 재료는 전부 서버가 준 것이다: echo의
리비전·지문(계산 시점)과 목록의 지문(지금 — 변형 지문 포함). 여기는 대조와 문구뿐이다.

상태 다섯 — fresh(같음: 조용, 배지 남발 금지) · stale(다름: 계산 시점과 지금을 함께 말한다) ·
gone(기체·변형이 목록에 없음) · unreadable(기체가 id를 점유한 채 손상 — "지워졌다"고 하면 같은
id로 다시 만들 수 있는 것처럼 읽힌다) · unknown(기체 기록 없는 옛 결과·목록 미수신 — 낡음으로
위장하지 않는다).
*/

export function resultFreshness(echo, rows) {
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
  return { state: "stale",
    label: `이 결과는 리비전 ${echo.revision ?? "—"}·지문 ${echo.fingerprint}로 계산했습니다 — `
      + `지금 문서(리비전 ${row.revision}·지문 ${fp})와 다릅니다. 다시 계산해야 지금 기체를 말합니다` };
}
