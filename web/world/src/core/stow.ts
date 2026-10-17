/** 접는 노드(착륙 스키드) — 모델이 선언하고, 재생 시각이 접고 편다.
 *
 * ## 왜 접나
 *
 * 델타윙 GLB의 스키드는 쉬는 자세가 **펼침**이고, 마모판 밑면이 기체 문서의 시뮬 접촉점에 앉는다(착지·활주에서 기체가
 * 뜨거나 묻히지 않게). 그런데 펼친 스키드는 캐니스터에 안 들어간다 — 발사관 배치가 꼬리를 관 안에 담으려고 관축 위
 * 기준점을 레일 원점과 **수평만** 맞춰(core/launcher.ts), 15° 발사에서 CG가 관축보다 0.41 m 아래이고 라이너 바닥까지
 * 0.38 m뿐이다(스키드는 CG 아래 0.55). 그래서 관에서 발사하는 결과는 관 안·비행 중엔 접고, 접지 전에 편다.
 *
 * ## 기체를 고정하지 않는다
 *
 * 무엇을 어느 축으로 얼마나 접는지는 **모델이 선언한다** — 루트 extras `claw_stow` = `{노드: [x, y, z]}`, 쉬는 자세에
 * 더할 three Euler XYZ [rad]. 선언이 없는 모델(banshee·도식)은 아무것도 안 접는다. 접고 펴는 것은 시뮬에 없는 표시라
 * 캡션이 밝힌다(`STOW_NOTE`) — 시뮬의 접촉점은 처음부터 있다.
 */

/** 접지 몇 초 전부터 펴나 [s, 시뮬 시각] — 최종 접근에서 내린다. */
export const SKID_DEPLOY_LEAD_S = 20;
/** 펴는 데 걸리는 시간 [s, 시뮬 시각] — 접지보다 한참 앞서 다 펴진다. */
export const SKID_DEPLOY_S = 4;

export interface StowEntry { node: string; rot: [number, number, number] }

/** 선언을 읽는다 — 블렌더 사용자 속성은 문자열(JSON)로 실린다. 못 읽는 항목은 빼고, 못 읽는 선언은 빈 목록. */
export function parseStow(declared: unknown): StowEntry[] {
  let obj = declared;
  if (typeof obj === "string") {
    try { obj = JSON.parse(obj); } catch { return []; }
  }
  if (obj == null || typeof obj !== "object" || Array.isArray(obj)) return [];
  const out: StowEntry[] = [];
  for (const [node, v] of Object.entries(obj as Record<string, unknown>)) {
    if (!Array.isArray(v) || v.length !== 3) continue;
    if (!v.every((a) => typeof a === "number" && Number.isFinite(a))) continue;
    out.push({ node, rot: [v[0], v[1], v[2]] });
  }
  return out;
}

/** 접힘 1 … 펼침 0.
 *
 * - 관에서 발사하지 않는 결과(`startsInCanister` 거짓) — 늘 펼침. 접을 까닭이 없다.
 * - 관에서 발사하고 접지가 없으면 — 내내 접힘.
 * - 아니면 접지 `SKID_DEPLOY_LEAD_S` 전부터 `SKID_DEPLOY_S` 동안 매끄럽게(smoothstep) 편다. 활주·정지 중엔 펼침.
 * - 시각이 성하지 않으면 접힘 — 펼침을 지어내지 않는다. */
export function stowFraction(t: number, startsInCanister: boolean, touchdownT: number | null): number {
  if (!startsInCanister) return 0;
  if (touchdownT == null || !Number.isFinite(touchdownT) || !Number.isFinite(t)) return 1;
  const u = Math.min(Math.max((t - (touchdownT - SKID_DEPLOY_LEAD_S)) / SKID_DEPLOY_S, 0), 1);
  return 1 - u * u * (3 - 2 * u);
}

/** 접는 노드가 있는 모델이면 캡션이 붙이는 줄. */
export const STOW_NOTE =
  `착륙 스키드는 표시용으로 접고 폅니다 — 관에서 발사하는 결과면 관 안·비행 중엔 접어 두었다가 접지 ${SKID_DEPLOY_LEAD_S}초 전에 `
  + "폅니다(시뮬의 스키드 접촉점은 처음부터 있습니다).";
