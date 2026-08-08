/** 구조도 뷰 — 블록 다이어그램 허브 (02 §4). 시뮬링크의 "다이어그램에서 시작"
대응: 블록 클릭 → 파라미터 대화상자(레지스트리 스키마 폼) 또는 정본 편집 화면 이동.

- 파라미터 스키마는 서버 /registry/{cat}/{name}/schema (엔진 ParamSet이 정본)
- 편집 가능 블록(오토파일럿)만 폼 편집 → store 주입 (시뮬 탭 '편집 AP'로 사용)
- 그 외 블록은 스키마 열람 + 편집처로 이동 — 진실 이원화 방지 (lib/blocks.js 계약)
*/

import { api, errorText } from "../api.js";
import { clear, el } from "../dom.js";
import { BLOCKS } from "../lib/blocks.js";
import { groupFields, parseFieldValue, schemaFields } from "../lib/schemaform.js";
import { store } from "../store.js";
import { clawDiagramCanvas } from "./diagram.js";

let selectedId = null; // 탭 재진입에도 선택 유지
const schemaCache = {}; // "cat/name" → schema

export function render() {
  const diagramBox = el("div", { class: "scroll-x" });
  const detailBox = el("div");

  const select = (block) => {
    selectedId = block?.id ?? null;
    clear(diagramBox).append(
      clawDiagramCanvas({ selectedId, onBlockClick: select }));
    renderDetail(detailBox, block);
  };

  const root = el("div", {},
    el("div", { class: "panel" },
      el("h2", {}, "제어법칙 구조도 — 블록을 클릭하세요"),
      diagramBox,
      el("p", { class: "hint" },
        "구조는 코드(M7 FlightControlLaw 조립)와 1:1 고정 — 자유 배선 없음 [확정 02 §4]. ",
        "블록 클릭 = 파라미터 대화상자(스키마 폼) 열람·편집, 캠페인 작업(트림 격자·마진 맵·미션)은 상단 탭."),
    ),
    el("div", { class: "panel" }, detailBox),
  );
  select(BLOCKS.find((b) => b.id === selectedId) ?? null);
  return root;
}

function renderDetail(box, block) {
  if (!block) {
    clear(box).append(el("p", { class: "placeholder" },
      "블록을 클릭하면 해당 블록의 파라미터(단위·범위·기본값)와 편집 경로가 표시됩니다."));
    return;
  }
  const d = block.detail;
  const schemaBox = el("div");
  // el() 래핑 필수 — 네이티브 append(null)은 "null" 텍스트 노드가 됨 (리뷰 M1)
  clear(box).append(el("div", {},
    el("h2", {}, `${block.title} — 파라미터`),
    el("p", { class: "hint" }, d.desc),
    d.edit && el("div", { class: "row", style: "margin-bottom: 10px" },
      el("button", { onclick: () => { location.hash = d.edit.hash; } }, `→ ${d.edit.label}`)),
    schemaBox,
  ));
  if (d.schema) loadSchema(schemaBox, block);
}

async function loadSchema(schemaBox, block) {
  const { category, name } = block.detail.schema;
  const key = `${category}/${name}`;
  try {
    schemaCache[key] ??= await api.get(`/registry/${category}/${name}/schema`);
  } catch (e) {
    clear(schemaBox).append(el("div", { class: "error-box" }, errorText(e)));
    return;
  }
  const fields = schemaFields(schemaCache[key]);
  if (block.detail.editable) renderForm(schemaBox, block, key, fields);
  else renderReadonlyTable(schemaBox, key, fields);
}

function renderReadonlyTable(schemaBox, key, fields) {
  clear(schemaBox).append(
    el("div", { class: "scroll-x" }, el("table", {},
      el("thead", {}, el("tr", {},
        el("th", {}, "파라미터"), el("th", {}, "기본값"), el("th", {}, "단위"),
        el("th", {}, "범위"), el("th", {}, "설명"))),
      el("tbody", {}, groupFields(key, fields).flatMap((g) => [
        g.title && el("tr", {},
          el("th", { colspan: "5", style: "text-align: left; padding-top: 10px" }, g.title)),
        g.fields.map((f) => el("tr", {},
          el("td", { class: "num" }, f.name),
          el("td", { class: "num" }, defaultText(f.default)),
          el("td", {}, f.unit),
          el("td", { class: "num" }, rangeText(f)),
          el("td", { style: "text-align: left" }, f.desc))),
      ])))),
    el("p", { class: "hint" }, `스키마: ${key} (엔진 레지스트리 — 02 §2.3)`),
  );
}

function rangeText(f) {
  if (f.choices) return f.choices.join(" | ");
  if (f.lo == null && f.hi == null) return "—";
  return `${f.lo ?? "−∞"} ~ ${f.hi ?? "∞"}`;
}

/** UNBOUNDED(±1e30 — 엔진 blocks.base)는 "무제한"으로 — 폼에 1e+30 노출 방지. */
function defaultText(v) {
  if (typeof v === "number" && Math.abs(v) >= 1e30) return v > 0 ? "무제한" : "−무제한";
  return String(v);
}

function renderForm(schemaBox, block, key, fields) {
  const injectKey = block.detail.injectKey;
  const applied = store.get(injectKey); // 이전 적용값 (전체 kwargs) 또는 undefined
  const statusLine = el("p", { class: "hint" },
    applied ? "적용된 편집값이 있습니다 — 시뮬 탭 '편집 AP'가 이 값을 주입합니다." : "");
  const errBox = el("div");
  const inputs = {}; // name → input 요소

  const fieldEl = (f) => {
    const cur = applied?.[f.name] ?? f.default;
    if (f.type === "boolean") {
      inputs[f.name] = el("input", { type: "checkbox", checked: cur === true });
      return el("label", { class: "field check", title: f.desc }, inputs[f.name], f.name);
    }
    if (f.type === "enum") {
      inputs[f.name] = el("select", {},
        f.choices.map((c) => el("option", { value: c, selected: c === cur }, c)));
      return el("label", { class: "field", title: f.desc }, f.name, inputs[f.name]);
    }
    inputs[f.name] = el("input", { class: "num", value: String(cur) });
    const unit = f.unit && f.unit !== "-" ? ` [${f.unit}]` : "";
    return el("label", { class: "field", title: `${f.desc}${rangeHint(f)}` },
      `${f.name}${unit}`, inputs[f.name]);
  };

  // 주입 계약: autopilot은 서버가 레지스트리 ParamDef로 판정(타입·범위·choices —
  // bool/enum 컴포넌트도 수용). nav·actuators는 여전히 수치 한정 validator —
  // 그쪽을 editable로 확장하려면 서버의 레지스트리 판정 승격이 선행 (리뷰 S2 갱신)
  const collect = () => {
    const values = {};
    const errors = [];
    for (const f of fields) {
      if (f.type === "boolean") {
        values[f.name] = inputs[f.name].checked;
        continue;
      }
      const r = parseFieldValue(f, inputs[f.name].value);
      if (r.error) errors.push(r.error);
      else values[f.name] = r.value;
    }
    return { values, errors };
  };

  clear(schemaBox).append(
    el("div", { class: "field-grid" }, groupFields(key, fields).map((g) =>
      el("div", { class: "opt-group" },
        g.title && el("div", { class: "g-title" }, g.title),
        el("div", { class: "row-inner" }, g.fields.map(fieldEl))))),
    el("div", { class: "row", style: "margin-top: 12px" },
      el("button", {
        class: "primary",
        onclick: () => {
          clear(errBox);
          const { values, errors } = collect();
          if (errors.length) {
            errBox.append(el("div", { class: "error-box" }, errors.join("\n")));
            return;
          }
          store.set(injectKey, values);
          statusLine.textContent =
            "적용됨 (전체 kwargs 교체) — 시뮬레이션 탭에서 '편집 AP'를 켜면 주입됩니다.";
        },
      }, "시뮬에 적용"),
      el("button", {
        onclick: () => {
          store.set(injectKey, null);
          clear(errBox);
          for (const f of fields) {
            if (f.type === "boolean") inputs[f.name].checked = f.default === true;
            else if (f.type === "enum") inputs[f.name].value = String(f.default);
            else inputs[f.name].value = String(f.default);
          }
          statusLine.textContent = "적용 해제 — 시뮬은 엔진 기본 AP로 돌아갑니다.";
        },
      }, "기본값·적용 해제"),
    ),
    statusLine, errBox,
    el("p", { class: "hint" },
      "값 검증(범위·유한성)은 여기서 1차, 교차 조건(theta_lo ≤ theta_hi 등)은 제출 시 ",
      "엔진이 최종 판정 (422로 표시). 마우스를 올리면 파라미터 설명이 보입니다."),
  );
}

function rangeHint(f) {
  if (f.lo == null && f.hi == null) return "";
  return ` (${f.lo ?? "−∞"} ~ ${f.hi ?? "∞"})`;
}
