/** 기체 탭 대표 그림 — 무엇을 그리고 무엇이라고 말하나 (06 §8). 판단만 — DOM·three 없음.

그리는 것은 **지금 계산에 쓰는 기체**(헤더 선택, 형상 변형 반영)다. 문서의 표시 모델 절(`display`, 02 §5.6)이
GLB를 가리키고 서버 자산 목록에 그 파일이 있으면 모델을, 아니면 기준량에서 만든 도식(`lib/uavmesh.js`)을 그린다.
도식으로 대신할 때는 **왜 도식인지**를 말한다 — 모델이 없는 기체와 모델 파일을 못 찾은 기체는 사용자가 할 일이
다르다. 다른 기체의 모델(예제의 GLB)을 빌려 그리지 않는다: 화면이 기체를 잘못 말하게 된다.

도식의 평면형은 삼각 델타 가정이다(uavmesh 머리말). 스키마가 받는 타면 배치가 엘레본 4면·러더 1면
하나뿐이라(02 §5.6 [한계]) 지금 받을 수 있는 기체와 모순되지 않는다 — 배치가 늘면 도식도 함께 늘어야 한다.
*/

import { uavMesh } from "./uavmesh.js";

const LAYOUT_LABEL = { elevon4_rudder1: "엘레본 4면·러더 1면" };

const finite = (v) => typeof v === "number" && Number.isFinite(v);
const fixed = (v, d) => (finite(v) ? v.toFixed(d) : "—");

/** 적용 문서 + 서버 자산 목록(`/api/world/manifest`, 못 받았으면 null) → {model, schematic, notes, title}.
 *
 *  model은 뷰어가 읽어 볼 GLB 이름이거나 null(도식만). 자산 목록을 못 받았으면 일단 읽어 보게 둔다 — 못 읽으면
 *  뷰어가 사유와 함께 도식으로 물러난다. notes는 **그림 아래에 보일 말**이라 도식으로 대신한 까닭만 싣는다(그림 위·아래
 *  글을 줄여 달라는 요청 — 모델을 그대로 그릴 때는 할 말이 없다). 모양이 설계 자료가 아니라는 안내는 title(툴팁)이다. */
const SCHEMATIC_TITLE = "익폭·기준면적에서 만든 도식 — 삼각 평면형 가정, 모양은 표시용입니다.";

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
    notes.push("표시 모델이 없는 기체라 익폭·기준면적에서 만든 도식입니다.");
    return { model: null, schematic, notes, title: SCHEMATIC_TITLE };
  }
  const listed = Array.isArray(manifest?.models) ? manifest.models.map((m) => m?.name) : null;
  if (listed && !listed.includes(wanted)) {
    notes.push(`표시 모델 파일(${wanted})을 서버 자산에서 찾지 못해 도식으로 대신 그립니다`
      + (manifest.models_reason ? ` — ${manifest.models_reason}` : "."));
    return { model: null, schematic, notes, title: SCHEMATIC_TITLE };
  }
  return { model: wanted, schematic, notes, title: `표시 모델 ${wanted} — 화면용 형상입니다. 계산은 문서의 수치(형상·공력·질량)를 씁니다.` };
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

/** ‹ › 로 오갈 순서 — 목록의 기체마다 기본 형상, 이어서 그 형상 변형들. 읽을 수 없는 기체는 뺀다.
 *
 *  예제의 EO/IR형처럼 표시 모델만 바꾼 변형도 한 칸이다 — 화면에서 고르는 단위가 계산에서 고르는 단위(기체·형상
 *  변형)와 같아야 [이 기체로 계산]이 무엇을 고르는지 헷갈리지 않는다. */
export function heroEntries(list) {
  const out = [];
  for (const p of Array.isArray(list) ? list : []) {
    if (!p || p.unreadable || typeof p.id !== "string") continue;
    out.push({ id: p.id, variant: null, label: p.name ?? p.id });
    for (const v of Array.isArray(p.variants) ? p.variants : []) {
      if (typeof v?.id === "string") out.push({ id: p.id, variant: v.id, label: `${p.name ?? p.id} · ${v.name ?? v.id}` });
    }
  }
  return out;
}

/** n칸 고리에서 at부터 dir(±1)만큼 — 끝에서 처음으로 돈다. 지금 칸이 목록에 없으면(at < 0) 앞으로는 첫 칸, 뒤로는 끝 칸. */
export function stepIndex(n, at, dir) {
  if (!(n > 0)) return -1;
  if (at < 0) return dir > 0 ? 0 : n - 1;
  return (((at + dir) % n) + n) % n;
}

/** 형상 변형이 무엇을 바꿨나 — 표시 모델만 바꿨으면 **계산은 기본 형상과 같다**고 말한다(짐벌을 달았다고 계산이 달라진
 *  척하지 않는다). 기본 형상이면 null. */
export function variantNote(doc, variantId) {
  if (variantId == null) return null;
  const v = (Array.isArray(doc?.variants) ? doc.variants : []).find((x) => x?.id === variantId);
  if (!v) return null;
  const paths = Object.keys(v.patch ?? {});
  if (paths.length === 0) return `「${v.name}」 — 아직 덮어쓴 항목이 없어 기본 형상과 같습니다.`;
  if (paths.every((k) => k === "/display" || k.startsWith("/display/"))) {
    return `「${v.name}」 — 표시 모델만 다르고 계산 입력은 기본 형상과 같습니다.`;
  }
  const shown = paths.slice(0, 4).join(", ");
  return `「${v.name}」 — 덮어쓴 항목 ${paths.length}개: ${shown}${paths.length > 4 ? " …" : ""}`;
}

