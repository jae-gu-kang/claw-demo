/** 구조도 뷰 — 시뮬링크 스타일 블록 다이어그램 허브 (02 §4).

최상위 블록도(설계 순서 점선 프레임 포함)에서 블록 클릭 → 서브시스템 하위
페이지(#blocks/<id>)로 진입 — 브레드크럼·내부 블록도·설계 노트·파라미터 패널.
해시가 페이지 상태를 들고 있어 브라우저 뒤로가기로 상위 복귀 가능.

- 파라미터 스키마는 서버 /registry/{cat}/{name}/schema (엔진 ParamSet이 정본)
- 편집 가능 블록(오토파일럿)만 폼 편집 → store 주입 (시뮬 탭 '편집 AP'로 사용)
- 그 외 블록은 스키마 열람 + 편집처로 이동 — 진실 이원화 방지 (lib/blocks.js 계약)
*/

import { api, errorText } from "../api.js";
import { clear, el } from "../dom.js";
import { BLOCKS } from "../lib/blocks.js";
import { groupFields, parseFieldValue, schemaFields } from "../lib/schemaform.js";
import { store } from "../store.js";
import { DESIGN_ORDER, fromMarkup, topDiagramSvg } from "./diagram.js";
import { CHIP_LABEL, SUBSYSTEMS } from "./subsystems.js";

const schemaCache = {}; // "cat/name" → schema
const blockById = Object.fromEntries(BLOCKS.map((b) => [b.id, b]));

const navigate = (id) => { location.hash = id ? `blocks/${id}` : "blocks"; };

/** #blocks/<id> → 페이지 id (미실존이면 홈). 해시가 페이지 상태의 정본. */
function currentPage() {
  const seg = location.hash.slice(1).split("/")[1];
  return seg && SUBSYSTEMS[seg] ? seg : null;
}

export function render() {
  const page = currentPage();
  const root = el("div", { class: "bd" });
  if (page) renderSubPage(root, page);
  else renderHome(root);
  return root;
}

// ── 최상위 (홈) ────────────────────────────────────────────────────────

function renderHome(root) {
  root.append(
    el("div", { class: "order" },
      el("span", { class: "cap" }, "설계 순서"),
      DESIGN_ORDER.flatMap((s, i) => [
        el("button", {
          class: "pill", style: `background:${s.color}`,
          onclick: () => navigate(s.page),
        }, s.label),
        i < DESIGN_ORDER.length - 1 && el("span", { class: "arr" }, "→"),
      ]),
      el("span", { class: "note-line" },
        "명령은 바깥(유도)에서 안(SCAS)으로 내려가지만, 설계는 플랜트 해석 후 ",
        el("b", {}, "가장 안쪽 루프부터"), " 닫아 나갑니다. 프레임 라벨을 클릭해도 이동합니다."),
    ),
    el("div", { class: "canvas-wrap top" }, topDiagramSvg(navigate)),
    el("p", { class: "hint-row" },
      "💡 블록(게인 스케줄링·항법 포함)이나 점선 프레임 라벨(①~⑤)을 클릭하면 서브시스템 ",
      "내부 블록도가 열립니다 — 시뮬링크의 서브시스템 더블클릭 대응. 브라우저 뒤로가기로 복귀. ",
      "구조는 코드(M7 조립)와 1:1 고정 — 자유 배선 없음 [확정 02 §4]."),
  );
}

// ── 서브시스템 하위 페이지 ─────────────────────────────────────────────

function renderSubPage(root, page) {
  const sub = SUBSYSTEMS[page];
  const block = blockById[page] ?? null; // verify는 블록 아님 (설계 단계 페이지)
  const paramBox = el("div");

  root.append(
    el("div", { class: "pagehead" },
      el("span", { class: "step-tag", style: `background:${sub.tagBg}` }, sub.tag),
      el("h2", {}, sub.title),
      el("span", { class: "eng" }, sub.eng),
      el("span", { class: "chips" },
        sub.chips.map((k) => el("span", { class: `chip ${k}` }, CHIP_LABEL[k]))),
    ),
    el("div", { class: "crumbbar" },
      el("button", { class: "home-btn", onclick: () => navigate(null) }, "⌂ 제어법칙 (Top)"),
      el("span", { class: "sep" }, "▸"),
      el("span", { class: "cur" }, block?.title ?? sub.title),
      el("button", { class: "up-btn", onclick: () => navigate(null) }, "↑ 상위로"),
    ),
    el("div", { class: "canvas-wrap sub" }, fromMarkup(sub.svg)),
    fromMarkup(`<div class="notes">${sub.notes}</div>`),
    el("div", { class: "notes" }, paramBox),
  );
  renderParams(paramBox, sub, block);
}

/** 파라미터 패널 — 스키마 열람/편집 + 정본 편집처 이동 (lib/blocks.js 계약). */
function renderParams(box, sub, block) {
  const edits = block?.detail.edit ? [block.detail.edit] : (sub.edits ?? []);
  box.append(
    el("h4", {}, "파라미터 · 편집 경로"),
    block && el("p", { class: "hint" }, block.detail.desc),
    edits.length > 0 && el("div", { class: "row", style: "margin: 6px 0 10px" },
      edits.map((e) => el("button", {
        onclick: () => { location.hash = e.hash; },
      }, `→ ${e.label}`))),
  );
  if (!block?.detail.schema) {
    if (!block) return; // verify — 이동 버튼만
    box.append(el("p", { class: "hint" },
      "레지스트리 파라미터 폼 없음 — 정본은 위 편집처 참조."));
    return;
  }
  const schemaBox = el("div");
  box.append(schemaBox);
  loadSchema(schemaBox, block);
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
