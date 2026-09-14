/** 결과 목록의 계보 칸 — 지문 표기 (02 §2.4).

탑재 C 검증 결과(v1.12~)는 엔진이 발급한 지문 둘을 meta에 싣는다: 구조 지문(생성 C가 바이트 동일한가)과
파라미터 지문(장입 이미지의 값). 그 전의 검증 결과는 값·구조를 한데 해시한 단일 지문이라 같은 칸에 두면 둘이
같은 종류로 읽힌다 — 「구 형상 지문」으로 구분한다. 다른 종류의 결과는 클라이언트가 보낸 지문 그대로다.
*/

export function lineageText(meta) {
  if (meta?.structure_fingerprint) {
    return `구조 ${meta.structure_fingerprint} · 값 ${meta.param_fingerprint ?? "—"}`;
  }
  if (!meta?.fingerprint) return "—";
  return meta.kind === "verify_flight" ? `구 형상 지문 ${meta.fingerprint}` : meta.fingerprint;
}
