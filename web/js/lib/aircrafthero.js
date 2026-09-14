/** 기체 탭 대표 그림 — 무엇을 그리고 무엇이라고 말하나 (06 §8). 판단만 — DOM·three 없음.

그리는 것은 **지금 계산에 쓰는 기체**(헤더 선택, 형상 변형 반영)다. 문서의 표시 모델 절(`display`, 02 §5.6)이
GLB를 가리키고 서버 자산 목록에 그 파일이 있으면 모델을, 아니면 기준량에서 만든 도식(`lib/uavmesh.js`)을 그린다.
도식으로 대신할 때는 **왜 도식인지**를 말한다 — 모델이 없는 기체와 모델 파일을 못 찾은 기체는 사용자가 할 일이
다르다. 다른 기체의 모델(예제의 GLB)을 빌려 그리지 않는다: 화면이 기체를 잘못 말하게 된다.

도식의 평면형은 삼각 델타 가정이다(uavmesh 머리말). 스키마가 받는 타면 배치가 엘레본 4면·러더 1면
하나뿐이라(02 §5.6 [한계]) 지금 받을 수 있는 기체와 모순되지 않는다 — 배치가 늘면 도식도 함께 늘어야 한다.
*/

import { uavMesh } from "./uavmesh.js";

const LAYOUT_LABEL = { elevon4_rudder1: "엘레본 4면 · 러더 1면" };

const finite = (v) => typeof v === "number" && Number.isFinite(v);
const fixed = (v, d) => (finite(v) ? v.toFixed(d) : "—");

/** 적용 문서 + 서버 자산 목록(`/api/world/manifest`, 못 받았으면 null) → {model, schematic, notes}.
 *
 *  model은 뷰어가 읽어 볼 GLB 이름이거나 null(도식만). 자산 목록을 못 받았으면 일단 읽어 보게 둔다 — 못 읽으면
 *  뷰어가 사유와 함께 도식으로 물러난다. */
export function heroPlan(doc, manifest) {
  const notes = [];
  let schematic = null;
  try {
    schematic = uavMesh({
      b: doc?.geometry?.b, s_ref: doc?.geometry?.S, cbar: doc?.geometry?.cbar,
      gear_contacts: doc?.ground?.skid?.contacts ?? [],
    });
  } catch (e) {
    notes.push(`도식을 만들 수 없습니다 — ${e.message}`);
  }
  const wanted = doc?.display?.kind === "model" ? doc.display.model : null;
  if (!wanted) {
    notes.push("표시 모델이 없는 기체라 익폭·기준면적에서 만든 도식입니다(삼각 평면형 가정 — 모양은 표시용).");
    return { model: null, schematic, notes };
  }
  const listed = Array.isArray(manifest?.models) ? manifest.models.map((m) => m?.name) : null;
  if (listed && !listed.includes(wanted)) {
    notes.push(`표시 모델 파일(${wanted})을 서버 자산에서 찾지 못해 도식으로 대신 그립니다`
      + (manifest.models_reason ? ` — ${manifest.models_reason}` : "."));
    return { model: null, schematic, notes };
  }
  notes.push(`표시 모델 ${wanted} — 화면용 형상입니다. 계산은 문서의 수치(형상·공력·질량)를 씁니다.`);
  return { model: wanted, schematic, notes };
}

/** 그림 아래 한 줄 사실 — 문서 값 그대로(단위 SI). 없는 값은 줄에서 뺀다. */
export function heroFacts(doc) {
  const g = doc?.geometry ?? {};
  const m = doc?.mass ?? {};
  const facts = [`익폭 ${fixed(g.b, 2)} m`, `기준면적 ${fixed(g.S, 2)} m²`, `평균공력시위 ${fixed(g.cbar, 2)} m`];
  if (finite(g.b) && finite(g.S) && g.S > 0) facts.push(`종횡비 ${fixed((g.b * g.b) / g.S, 2)}`);
  if (finite(m.m_empty) && finite(m.fuel_max)) facts.push(`질량 ${fixed(m.m_empty, 0)}–${fixed(m.m_empty + m.fuel_max, 0)} kg`);
  const layout = doc?.surfaces?.layout;
  if (layout) facts.push(LAYOUT_LABEL[layout] ?? layout);
  if (doc?.ground?.rail) facts.push(`레일 발사 ${fixed(doc.ground.rail.length, 1)} m`);
  if (doc?.ground?.skid) facts.push("스키드 착륙");
  return facts;
}
