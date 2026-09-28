/** 가상환경의 기체 도식 — 표시 모델(GLB)이 없거나 못 읽었을 때 궤적만 두지 않고 **그 자리에 도식을** 세운다.
 *
 * 궤적만 남기면 발사·접지 장면에서 기체가 어디 있는지가 화면에 없다(쇼케이스 e2e 실측 — 모델 폴더를 못 찾은
 * 서버에서 추적 시점으로 바꿔도 빈 하늘이었다). 기체 탭 대표 그림은 같은 경우에 이미 도식으로 물러난다.
 *
 * **형상의 정본은 기체 탭이다** — `web/js/lib/aircrafthero.js heroPlan`이 문서의 익폭·기준면적·스키드 접촉점을
 * `lib/uavmesh.js`에 넘겨 만든다. 여기서 치수 대응을 다시 적지 않고 그 함수를 그대로 부른다(두 화면이 같은
 * 기체를 다른 모양으로 그리지 않게). 문서가 없으면 도식도 없다 — 다른 기체의 형상을 빌려 그리지 않는다.
 */

import { heroPlan as rawHeroPlan } from "../../../js/lib/aircrafthero.js";

/** 절차 도식 메시 — `web/js/lib/uavmesh.js`의 반환 모양(FRD 성분, 면마다 정점). */
export interface SchematicMesh {
  positions: Float32Array;
  normals: Float32Array;
  indices: Uint16Array;
  groups: readonly { start: number; count: number; name: string }[];
}

/** 이 런의 기체 적용 문서 → 도식. 문서가 없으면 둘 다 null(사유는 기체 모델 계획이 말한다),
 *  기준량이 깨졌으면 사유 문장. */
export function vehicleSchematic(doc: unknown): { mesh: SchematicMesh | null; reason: string | null } {
  if (doc == null || typeof doc !== "object") return { mesh: null, reason: null };
  const plan = rawHeroPlan(doc, null) as { schematic: SchematicMesh | null; notes: string[] };
  if (plan.schematic != null) return { mesh: plan.schematic, reason: null };
  // 도식을 못 만들면 heroPlan이 그 사유를 첫 줄에 싣는다
  return { mesh: null, reason: plan.notes[0] ?? "도식을 만들 수 없습니다." };
}

/** 도식이 무엇인지 — 캡션 한 줄. 모양이 설계 자료가 아니라는 것과, 움직이는 노드가 없다는 것. */
export const SCHEMATIC_NOTE =
  "도식은 문서의 익폭·기준면적에서 만든 삼각 평면형(표시용)이라 타면·프로펠러는 움직이지 않습니다.";

const TRACK_ONLY = "궤적만 그립니다";
const INSTEAD = "도식으로 대신 그립니다";

/** 도식으로 물러난 사유 → 캡션. 사유 문장(`vehicleModelPlan`의 「…없어 궤적만 그립니다」·GLB 읽기 실패)은
 *  그대로 두고 **결말만** 도식으로 고친다 — 도식을 그리면서 「궤적만」이라고 말하면 화면과 캡션이 어긋난다. */
export function schematicCaption(why: string | null): string {
  if (why == null || why === "") return `기체 모델 대신 ${INSTEAD}.`;
  if (why.includes(TRACK_ONLY)) return why.replace(TRACK_ONLY, INSTEAD);
  return `${why.replace(/[.\s]+$/, "")} — ${INSTEAD}.`;
}
