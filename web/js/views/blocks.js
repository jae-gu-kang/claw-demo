/** 구조도 뷰 — 시뮬링크 스타일 블록 다이어그램 허브 (02 §4).

최상위 블록도(설계 순서 점선 프레임 포함)에서 블록 클릭 → 서브시스템 하위
페이지(#blocks/<id>)로 진입 — 브레드크럼·내부 블록도·설계 노트·파라미터 패널.
해시가 페이지 상태를 들고 있어 브라우저 뒤로가기로 상위 복귀 가능.

드릴다운은 깊이 무제한(시뮬링크 더블클릭 대응): 하위 페이지 SVG 안의
data-child 블록 클릭 → 해시 세그먼트 추가(#blocks/scas/pitch/pi) — 트리는
SUBSYSTEMS[id].children 재귀 (subsystems.js 규약). 브레드크럼 중간 클릭으로
임의 조상 이동, "↑ 상위로"는 한 단계.

- 파라미터 스키마는 서버 /registry/{cat}/{name}/schema (엔진 ParamSet이 정본)
- 편집 가능 블록(AP·작동기·항법 — 시뮬 주입 경로 보유)은 폼 편집 → store 주입
- 그 외 블록은 스키마 열람 + 편집처로 이동 — 진실 이원화 방지 (lib/blocks.js 계약)
- SVG 내 <tspan data-p="이름">은 파라미터 연동 표시값 — 스키마 기본값(+적용 편집값)
  으로 채우고, 폼 입력마다 실시간 재동기화 (subsystems.js 규약)
*/

import { api, errorText } from "../api.js";
import { clear, el } from "../dom.js";
import { BLOCKS, resolvePath } from "../lib/blocks.js";
import { groupFields, parseFieldValue, schemaFields } from "../lib/schemaform.js";
import { store } from "../store.js";
import { renderCodePanel } from "./codegen.js";
import { DESIGN_ORDER, fromMarkup, topDiagramSvg } from "./diagram.js";
import { createTopReplay } from "./replayoverlay.js";
import { CHIP_LABEL, SUBSYSTEMS } from "./subsystems.js";

const schemaCache = {}; // "cat/name" → schema
const blockById = Object.fromEntries(BLOCKS.map((b) => [b.id, b]));

/** 이동 — 문자열(층2 진입)·경로 배열(하위 층)·null(홈) 모두 수용. */
const navigate = (p) => {
  const segs = p == null ? [] : Array.isArray(p) ? p : [p];
  location.hash = segs.length ? `blocks/${segs.join("/")}` : "blocks";
};

/** #blocks/<a>/<b>/… → 트리 경로 배열 (해시가 페이지 상태의 정본).
하강·절단 규칙은 lib/blocks.js resolvePath — 미실존 세그먼트에서 절단, 빈 배열 = 홈. */
function currentPath() {
  return resolvePath(location.hash.slice(1).split("/").slice(1), SUBSYSTEMS);
}

/** 경로 → 트리 노드 (경로는 currentPath가 검증한 실존 경로 전제). */
function nodeAt(path) {
  let node = null;
  let nodes = SUBSYSTEMS;
  for (const seg of path) {
    node = nodes[seg];
    nodes = node.children ?? {};
  }
  return node;
}

// 재생 오버레이 핸들 — 재렌더·탭 전환 시 이전 타이머를 확실히 끈다 (버려진 SVG를
// 계속 갱신하는 타이머가 남지 않게)
let topReplay = null;

export function render() {
  if (topReplay) { topReplay.dispose(); topReplay = null; }
  const path = currentPath();
  // 절단 폴백 가시화 — 무효 해시(#blocks/scas/PITCH 등)를 실제 렌더 경로로
  // 정규화 (replace: 히스토리 오염 없음, 정규화 후엔 동일 해시라 재발화 안정).
  // blocks 계열 해시만 — 미등록 뷰 해시의 blocks 폴백 표시(#foo)는 기존대로 둔다.
  const canonical = path.length ? `#blocks/${path.join("/")}` : "#blocks";
  if (location.hash !== canonical && location.hash.slice(1).split("/")[0] === "blocks") {
    location.replace(canonical);
  }
  const root = el("div", { class: "bd" });
  if (path.length) renderSubPage(root, path);
  else renderHome(root);
  return root;
}

// ── 최상위 (홈) ────────────────────────────────────────────────────────

function renderHome(root) {
  const snapshotBox = el("div");
  const svg = topDiagramSvg(navigate);
  topReplay = createTopReplay({ svgRoot: svg }); // 블록 값 표시·리미터 점멸
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
      el("button", {
        title: "적용된 파라미터·게인 스케줄을 한 파일의 코드로 — 검토·추적성 표 포함",
        onclick: () => showSnapshotCode(snapshotBox),
      }, "🧾 전체 형상 코드"),
      el("span", { class: "note-line" },
        "명령은 바깥(유도)에서 안(SCAS)으로 내려가지만, 설계는 플랜트 해석 후 ",
        el("b", {}, "가장 안쪽 루프부터"), " 닫아 나갑니다. 프레임 라벨을 클릭해도 이동합니다."),
    ),
    topReplay.root,
    el("div", { class: "canvas-wrap top" }, svg),
    el("p", { class: "hint-row" },
      "💡 블록(게인 스케줄링·항법 포함)이나 우상단 범례(①~⑤ 프레임 설명)를 클릭하면 서브시스템 ",
      "내부 블록도가 열립니다 — 시뮬링크의 서브시스템 더블클릭 대응. 브라우저 뒤로가기로 복귀. ",
      "구조는 코드(M7 조립)와 1:1 고정 — 자유 배선 없음 [확정 02 §4]."),
    snapshotBox, // 비어 있다가 [전체 형상 코드]에서 채워짐
  );
}

// ── 서브시스템 하위 페이지 ─────────────────────────────────────────────

function renderSubPage(root, path) {
  const rootSub = SUBSYSTEMS[path[0]];
  const sub = nodeAt(path); // 리프 노드 (children 재귀)
  const block = blockById[path[0]] ?? null; // verify는 블록 아님 (설계 단계 페이지)
  const paramBox = el("div");
  const svgWrap = el("div", { class: "canvas-wrap sub" }, fromMarkup(sub.svg));
  // 하위 진입 배선 — data-child (최상위 data-block과 동일 패턴, 깊이 무제한)
  for (const node of svgWrap.querySelectorAll("[data-child]")) {
    const go = () => navigate([...path, node.dataset.child]);
    node.addEventListener("click", go);
    node.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); }
    });
  }

  const crumbLabel = (seg, i, n) =>
    i === 0 ? (blockById[seg]?.title ?? n.title) : (n.crumb ?? n.title);
  root.append(
    el("div", { class: "pagehead" },
      // 단계 태그는 루트 상속 (하위 층은 같은 설계 단계 소속)
      el("span", { class: "step-tag", style: `background:${sub.tagBg ?? rootSub.tagBg}` },
        sub.tag ?? rootSub.tag),
      el("h2", {}, sub.title),
      el("span", { class: "eng" }, sub.eng),
      el("span", { class: "chips" },
        sub.chips.map((k) => el("span", { class: `chip ${k}` }, CHIP_LABEL[k]))),
    ),
    el("div", { class: "crumbbar" },
      el("button", { class: "home-btn", onclick: () => navigate(null) }, "⌂ 제어법칙 (Top)"),
      path.map((seg, i) => {
        const n = nodeAt(path.slice(0, i + 1));
        return [
          el("span", { class: "sep" }, "▸"),
          i === path.length - 1
            ? el("span", { class: "cur" }, crumbLabel(seg, i, n))
            : el("button", {
                class: "home-btn", onclick: () => navigate(path.slice(0, i + 1)),
              }, crumbLabel(seg, i, n)),
        ];
      }),
      el("button", {
        class: "up-btn",
        onclick: () => navigate(path.length > 1 ? path.slice(0, -1) : null),
      }, "↑ 상위로"),
    ),
    svgWrap,
    fromMarkup(`<div class="notes">${sub.notes}</div>`),
    el("div", { class: "notes" }, paramBox),
  );
  renderParams(paramBox, sub, block, svgWrap);
}

/** SVG 내 data-p 표시값 갱신 — 블록도 수치를 파라미터 값과 동기화.
values에 없는 이름은 초기(폴백) 텍스트 유지. textContent만 교체 (마크업 삽입 없음). */
function bindSvgParams(svgWrap, values) {
  for (const node of svgWrap.querySelectorAll("[data-p]")) {
    const v = values[node.dataset.p];
    if (v !== undefined) node.textContent = displayVal(v);
  }
}

/** 표시용 값 포맷 — UNBOUNDED(±1e30)는 ±∞, 수치는 유효 6자리로 정리. */
function displayVal(v) {
  if (typeof v === "number") {
    if (Math.abs(v) >= 1e30) return v > 0 ? "∞" : "−∞";
    return String(Number(v.toPrecision(6)));
  }
  return String(v);
}

/** 파라미터 패널 — 스키마 열람/편집 + 정본 편집처 이동 (lib/blocks.js 계약). */
function renderParams(box, sub, block, svgWrap) {
  const edits = block?.detail.edit ? [block.detail.edit] : (sub.edits ?? []);
  // el() 래핑 필수 — 네이티브 append(null/false)는 "null" 텍스트 노드가 됨 (리뷰 M1)
  box.append(el("div", {},
    el("h4", {}, "파라미터 · 편집 경로"),
    block && el("p", { class: "hint" }, block.detail.desc),
    edits.length > 0 && el("div", { class: "row", style: "margin: 6px 0 10px" },
      edits.map((e) => el("button", {
        onclick: () => { location.hash = e.hash; },
      }, `→ ${e.label}`))),
  ));
  if (!block?.detail.schema) {
    if (!block) return; // verify — 이동 버튼만
    box.append(el("p", { class: "hint" },
      "레지스트리 파라미터 폼 없음 — 정본은 위 편집처 참조."));
    return;
  }
  const schemaBox = el("div");
  box.append(schemaBox);
  loadSchema(schemaBox, block, svgWrap);
}

async function loadSchema(schemaBox, block, svgWrap) {
  // omit(주입 경로 예약 키)까지 적용된 필드 목록 — 폼·코드 생성이 같은 원천을 쓴다
  let key, fields;
  try {
    ({ key, fields } = await fetchFields(block));
  } catch (e) {
    clear(schemaBox).append(el("div", { class: "error-box" }, errorText(e)));
    return;
  }
  // 블록도 수치 ← 스키마 기본값 + 적용된 편집값 (정본 = 엔진 스키마, SVG 초기 텍스트는 폴백)
  const defaults = Object.fromEntries(fields.map((f) => [f.name, f.default]));
  const applied = block.detail.injectKey ? store.get(block.detail.injectKey) : null;
  bindSvgParams(svgWrap, { ...defaults, ...(applied ?? {}) });
  if (block.detail.editable) renderForm(schemaBox, block, key, fields, svgWrap, defaults);
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

function renderForm(schemaBox, block, key, fields, svgWrap, defaults) {
  const injectKey = block.detail.injectKey;
  const applied = store.get(injectKey); // 이전 적용값 (전체 kwargs) 또는 undefined
  const statusLine = el("p", { class: "hint" },
    applied ? "적용된 편집값이 있습니다 — 시뮬 실행이 이 값을 주입합니다." : "");
  const errBox = el("div");
  const codeBox = el("div"); // 코드 생성 결과 (버튼을 누르기 전엔 비어 있음)
  const inputs = {}; // name → input 요소

  // 폼 입력 → 블록도 수치 실시간 동기화 (파싱 실패 필드는 마지막 유효값 유지)
  const liveSync = () => {
    const vals = { ...defaults };
    for (const f of fields) {
      if (f.type === "boolean") { vals[f.name] = inputs[f.name].checked; continue; }
      const r = parseFieldValue(f, inputs[f.name].value);
      if (!r.error) vals[f.name] = r.value;
    }
    bindSvgParams(svgWrap, vals);
  };

  const fieldEl = (f) => {
    const cur = applied?.[f.name] ?? f.default;
    if (f.type === "boolean") {
      inputs[f.name] = el("input", { type: "checkbox", checked: cur === true, onchange: liveSync });
      return el("label", { class: "field check", title: f.desc }, inputs[f.name], f.name);
    }
    if (f.type === "enum") {
      inputs[f.name] = el("select", { onchange: liveSync },
        f.choices.map((c) => el("option", { value: c, selected: c === cur }, c)));
      return el("label", { class: "field", title: f.desc }, f.name, inputs[f.name]);
    }
    inputs[f.name] = el("input", { class: "num", value: String(cur), oninput: liveSync });
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
          liveSync();
          statusLine.textContent =
            "적용됨 (전체 kwargs 교체) — 시뮬레이션 탭 실행이 이 값을 주입합니다.";
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
          liveSync();
          statusLine.textContent = "적용 해제 — 시뮬은 엔진 기본값으로 돌아갑니다.";
        },
      }, "기본값·적용 해제"),
      el("button", {
        title: "현재 폼 값을 반영한 코드 + 변경 Δ·주의·추적성 표",
        onclick: () => {
          clear(errBox);
          const { values, errors } = collect();
          if (errors.length) {
            errBox.append(el("div", { class: "error-box" }, errors.join("\n")));
            return;
          }
          showBlockCode(codeBox, block, values);
        },
      }, "코드 생성"),
    ),
    statusLine, errBox, codeBox,
    el("p", { class: "hint" },
      "폼 값을 바꾸면 위 블록도 수치가 즉시 연동됩니다 (강조 표시). ",
      "값 검증(범위·유한성)은 여기서 1차, 교차 조건(theta_lo ≤ theta_hi 등)은 제출 시 ",
      "엔진이 최종 판정 (422로 표시). 마우스를 올리면 파라미터 설명이 보입니다."),
  );
}

function rangeHint(f) {
  if (f.lo == null && f.hi == null) return "";
  return ` (${f.lo ?? "−∞"} ~ ${f.hi ?? "∞"})`;
}

// ── 코드 생성 (설계 형상 → 코드 표현) ──────────────────────────────────
// 파이썬 클래스·임포트 경로는 서버 validate가 엔진 인스턴스에서 얻어 준 값만 쓴다
// — 이름을 추측하면 엔진 개명 시 조용히 틀린 코드가 나온다 (lib/codegen.js 주석).

let versionCache = null; // {version, engine} — 생성 코드의 추적성 메타

async function codegenMeta() {
  if (!versionCache) {
    try {
      versionCache = await api.get("/health");
    } catch {
      versionCache = {}; // 버전 줄만 빠지고 코드 생성은 계속
    }
  }
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return {
    generatedAt: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} `
      + `${pad(d.getHours())}:${pad(d.getMinutes())}`,
    server: versionCache.version,
    engine: versionCache.engine,
  };
}

/** 스키마 → 폼·코드가 공유하는 필드 목록 (omit 적용). */
async function fetchFields(block) {
  const { category, name } = block.detail.schema;
  const key = `${category}/${name}`;
  schemaCache[key] ??= await api.get(`/registry/${category}/${name}/schema`);
  const omit = new Set(block.detail.omit ?? []);
  return { key, fields: schemaFields(schemaCache[key]).filter((f) => !omit.has(f.name)) };
}

/** 블록 + 값 → {spec, validation}. values=null이면 엔진 기본값 형상. */
async function buildSpec(block, values) {
  const { key, fields } = await fetchFields(block);
  const applied = values != null;
  const vals = values ?? Object.fromEntries(fields.map((f) => [f.name, f.default]));
  const { category, name } = block.detail.schema;
  const url = `/registry/${category}/${name}/validate`;
  let sym = {};
  let validation = { key, ok: true, detail: "" };
  try {
    sym = await api.post(url, { values: vals });
  } catch (e) {
    validation = { key, ok: false, detail: errorText(e) };
    // 값이 거부돼도 심볼은 필요하다 — 기본값으로 재조회 (등록 컴포넌트면 항상 성립)
    try {
      sym = await api.post(url, { values: {} });
    } catch { /* 서버 이탈 — 아래 폴백 표기로 코드는 생성 */ }
  }
  const cg = block.detail.codegen;
  return {
    validation,
    spec: {
      key, fields, values: vals, applied,
      pyImport: sym.py_import ?? "claw", pyClass: sym.py_class ?? block.detail.schema.name,
      varName: cg.varName, cPrefix: cg.cPrefix, kind: cg.kind, hint: cg.hint ?? "",
      desc: block.detail.desc, notes: SUBSYSTEMS[block.id]?.notes ?? "",
    },
  };
}

const busy = (box, text) => clear(box).append(el("p", { class: "hint" }, text));

/** 블록 1개 — 폼의 현재 값으로 생성 (적용 여부와 무관하게 지금 보이는 형상). */
async function showBlockCode(box, block, values) {
  busy(box, "코드 생성 중…");
  try {
    const [{ spec, validation }, meta] = await Promise.all([
      buildSpec(block, values), codegenMeta(),
    ]);
    renderCodePanel(box, { specs: [spec], meta, validation: [validation] });
  } catch (e) {
    clear(box).append(el("div", { class: "error-box" }, errorText(e)));
  }
}

/** 전체 형상 — 편집 3블록의 적용값(없으면 엔진 기본값) + 게인 스케줄 테이블. */
async function showSnapshotCode(box) {
  busy(box, "전체 형상 코드 생성 중…");
  try {
    const blocks = BLOCKS.filter((b) => b.detail.editable && b.detail.codegen);
    const [built, meta] = await Promise.all([
      Promise.all(blocks.map((b) => buildSpec(b, store.get(b.detail.injectKey) ?? null))),
      codegenMeta(),
    ]);
    renderCodePanel(box, {
      specs: built.map((r) => r.spec),
      validation: built.map((r) => r.validation),
      gainTables: store.get("gainTables") ?? null,
      meta,
    });
  } catch (e) {
    clear(box).append(el("div", { class: "error-box" }, errorText(e)));
  }
}
