/** 구조도 뷰 — 시뮬링크 스타일 블록 다이어그램 허브 (02 §4).

최상위 블록도(설계 순서 점선 프레임 포함)에서 블록 클릭 → 서브시스템 하위
페이지(#blocks/<id>)로 진입 — 브레드크럼·내부 블록도·설계 노트·파라미터 패널.
해시가 페이지 상태를 들고 있어 브라우저 뒤로가기로 상위 복귀 가능.

드릴다운은 깊이 무제한(시뮬링크 더블클릭 대응): 하위 페이지 SVG 안의
data-child 블록 클릭 → 해시 세그먼트 추가(#blocks/scas/pitch/pi) — 트리는
SUBSYSTEMS[id].children 재귀 (subsystems.js 규약). 브레드크럼 중간 클릭으로
임의 조상 이동, "↑ 상위로"는 한 단계.

- 파라미터 스키마는 서버 /registry/{cat}/{name}/schema (엔진 ParamSet이 정본)
- 편집 가능 블록(AP·SCAS·작동기·항법 — 시뮬 주입 경로 보유)은 폼 편집 → store 주입
- 그 외 블록은 스키마 열람 + 편집처로 이동 — 진실 이원화 방지 (lib/blocks.js 계약)
- SCAS는 축이 셋이라 폼이 **축 페이지**(#blocks/scas/pitch)에 붙는다. 한 축만 고쳐도
  세 축을 함께 저장한다 — 서버 req.scas가 세 축 전부를 요구하고(부분 주입은 나머지
  축이 조용히 달라진다), ScasAxis의 스키마 기본값은 0이라 빈 축을 스키마로 채울 수
  없기 때문이다. 축 설계 kwargs는 /gains/catalog scas_design이 준다
- **스케줄이 덮는 자리는 폼에서 잠긴다**: 그 자리는 테이블이 정본이고 실행 시점에
  룩업이 상수를 이긴다(fcl/graphs.py). 잠긴 입력에는 설계점 값을 보여 주고 저장에도
  그 값을 담는다 — 빼 버리면 서버 ParamDef 기본값(SCAS는 0)이 들어차고, 옛 상수를
  남기면 스케줄을 껐을 때 화면과 다른 값으로 굳는다
- SVG 내 <tspan data-p="이름">은 파라미터 연동 표시값 — 스키마 기본값(+적용 편집값)
  으로 채우고, 폼 입력마다 실시간 재동기화 (subsystems.js 규약)
*/

import { api, errorText } from "../api.js";
import { clear, el } from "../dom.js";
import { BLOCKS, codegenTargets, resolvePath } from "../lib/blocks.js";
import {
  designCoord, designValue, lockedParams, scasKwargs, selectedSlots, slotIndex,
} from "../lib/gainsync.js";
import { groupFields, parseFieldValue, schemaFields } from "../lib/schemaform.js";
import { store } from "../store.js";
import { renderCodePanel } from "./codegen.js";
import { DESIGN_ORDER, fromMarkup, topDiagramSvg } from "./diagram.js";
import { createTopReplay } from "./replayoverlay.js";
import { CHIP_LABEL, SUBSYSTEMS } from "./subsystems.js";

const schemaCache = {}; // "cat/name" → schema
let gainsCatalog = null; // GET /gains/catalog — 스케줄 자리·설계 상수·SCAS 설계 kwargs
const blockById = Object.fromEntries(BLOCKS.map((b) => [b.id, b]));

/** 게인 카탈로그 — 잠금 판정과 SCAS 축 폼 기본값의 원천. 실패해도 폼은 뜬다
 * (잠금 없이 열리는 편이, 화면이 통째로 안 뜨는 것보다 낫다). */
async function loadGainsCatalog() {
  if (gainsCatalog === null) {
    try {
      gainsCatalog = await api.get("/gains/catalog");
      // 설계점 **좌표**를 제안 표 기준으로 굳혀 둔다 — 이후 값 조회는 격자가 아니라
      // 비행조건으로 읽는다 (lib/gainsync designCoord·designValue)
      gainsCatalog.design_coord = designCoord(gainsCatalog);
    } catch {
      // **실패는 캐시하지 않는다.** 캐시하면 첫 요청 한 번이 실패한 뒤로 새로고침
      // 전까지 SCAS 축 폼이 읽기 전용으로 굳는다 — 무료 플랜 콜드 스타트(~1분)에서
      // 그 첫 요청이 실패하는 것은 흔하고, 재시도 비용은 요청 하나다
      return null;
    }
  }
  return gainsCatalog || null;
}

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
// 계속 갱신하는 타이머가 남지 않게). 재렌더는 render() 진입에서, 탭 이탈은 아래
// dispose() export로 — main.js는 떠나는 뷰의 dispose()를 부르는데 이 뷰가 그걸
// 내보내지 않아, 재생 중에 다른 탭으로 나가면 타이머가 떨어져 나간 SVG를 계속 갱신했다
let topReplay = null;

/** 탭 이탈 시 자원 반납 (main.js 라우터 규약 — 선택 export). */
export function dispose() {
  if (topReplay) { topReplay.dispose(); topReplay = null; }
}

export function render() {
  dispose();
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
    // 제목 줄 + 층 칩. 칩은 보드의 판에서 색·이름을 그대로 받아 오므로(diagram.js
    // LAYERS가 정본) 칩과 판이 어긋날 수 없다 — 색으로 층을 되짚는 독법의 전제
    el("div", { class: "pagetop" },
      el("h1", {}, "구조도"),
      // 설명과 층 칩은 **같은 줄**이다 — 설명이 길어 두 줄이 되면 칩이 어긋나므로
      // 여기는 한 줄로 짧게 두고, 자세한 안내는 보드 아래 hint-row가 맡는다
      el("div", { class: "subline" },
        el("p", {}, el("b", {}, "안쪽 루프부터"), " 닫는 설계 순서가 곧 판의 높이입니다."),
        el("div", { class: "layerchips" },
          DESIGN_ORDER.map((s) => el("button", {
            class: "lchip",
            style: `background:${s.tint};border-bottom-color:${s.edge}`,
            title: `${s.n}단계 — ${s.name} 설계 화면으로`,
            onclick: () => navigate(s.page),
          }, el("span", { class: "n", style: `background:${s.color}` }, String(s.n)), s.name)),
        ),
      ),
    ),
    el("div", { class: "canvas-wrap top" }, svg),
    // 재생 컨트롤은 보드 바로 밑 — 값이 뜨는 자리(블록 앞 판 위)와 눈이 오가는 거리가 짧다
    el("div", { class: "boardbar" },
      topReplay.root,
      el("button", {
        title: "적용된 파라미터·게인 스케줄을 한 파일의 코드로 — 검토·추적성 표 포함",
        onclick: () => showSnapshotCode(snapshotBox),
      }, "🧾 전체 형상 코드"),
    ),
    el("p", { class: "hint-row" },
      "💡 블록이나 판 앞면의 층 이름을 클릭하면 서브시스템 내부 블록도가 열립니다 ",
      "(시뮬링크의 서브시스템 더블클릭 대응 · 브라우저 뒤로가기로 복귀). 신호는 오른쪽에서 ",
      "왼쪽으로 흐르고, 구조는 코드(M7 조립)와 1:1 고정 — 자유 배선 없음 [확정 02 §4]."),
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
  renderParams(paramBox, sub, block, svgWrap, path);
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

/** 파라미터 패널 — 스키마 열람/편집 + 정본 편집처 이동 (lib/blocks.js 계약).
 *
 * 축이 여럿인 블록(SCAS)은 축 페이지에서만 폼을 연다 — 블록 루트에서는 어느 축의
 * 값인지 정해지지 않아 편집이 성립하지 않는다. */
function renderParams(box, sub, block, svgWrap, path = []) {
  const axes = block?.detail.axes ?? null;
  // 축 폼은 **축 페이지(층3)에만** 붙는다. 층4(#blocks/scas/pitch/pi)는 축들이
  // 공유하는 PI 페이지라, 거기에 또 폼을 그리면 같은 값의 편집처가 두 곳이 된다
  const axis = axes && path.length === 2 ? (axes[path[1]] ?? null) : null;
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
  if (axes && !axis) {
    box.append(el("p", { class: "hint" },
      `축 파라미터는 축 페이지에서 편집합니다 — ${Object.keys(axes).join(" · ")} `
      + "블록을 클릭해 들어가세요 (한 축을 고쳐도 세 축이 함께 주입됩니다)."));
  }
  const schemaBox = el("div");
  box.append(schemaBox);
  loadSchema(schemaBox, block, svgWrap, axis);
}

async function loadSchema(schemaBox, block, svgWrap, axis = null) {
  // omit(주입 경로 예약 키)까지 적용된 필드 목록 — 폼·코드 생성이 같은 원천을 쓴다
  let key, fields, catalog;
  try {
    [{ key, fields }, catalog] = await Promise.all([
      fetchFields(block), loadGainsCatalog(),
    ]);
  } catch (e) {
    clear(schemaBox).append(el("div", { class: "error-box" }, errorText(e)));
    return;
  }
  const access = paramAccess(block, axis, catalog);
  const locks = scheduleLocks(catalog, access);
  // 폼 기본값 = 스키마 기본값 + 그 축의 설계 kwargs. ScasAxis는 범용 축 컴포넌트라
  // 스키마 기본값이 전부 0이다 — 그걸 "기본값으로 되돌리기"에 쓰면 게인이 0이 된다
  const defaults = {
    ...Object.fromEntries(fields.map((f) => [f.name, f.default])),
    ...(access.defaults ?? {}),
  };
  // 블록도 수치 ← 기본값 + 적용된 편집값 + **잠긴 자리는 표의 설계점 값**.
  // 잠긴 자리에 스토어 상수를 그리면 블록도가 런타임이 무시하는 숫자를 보여 준다
  const lockedVals = Object.fromEntries(
    [...locks].filter(([, lk]) => typeof lk.value === "number").map(([k, lk]) => [k, lk.value]),
  );
  bindSvgParams(svgWrap, { ...defaults, ...(access.read() ?? {}), ...lockedVals });
  // 축 폼은 카탈로그 없이 열지 않는다 — ScasAxis의 스키마 기본값은 전부 0이라,
  // 설계 kwargs를 못 받은 채 열면 0을 설계값인 양 보여 주고 그대로 적용하면 게인이
  // 사라진다. 값을 모를 때는 안 고치는 편이 낫다
  if (axis && !catalog) {
    renderReadonlyTable(schemaBox, key, fields);
    schemaBox.append(el("p", { class: "hint" },
      "게인 카탈로그(/gains/catalog)를 못 받아 축 설계값을 모릅니다 — 편집을 열지 "
      + "않습니다. 위 표의 기본값은 레지스트리 기본값이지 이 기체의 설계값이 아닙니다."));
    return;
  }
  if (block.detail.editable && (!block.detail.axes || axis)) {
    renderForm(schemaBox, block, key, fields, svgWrap, defaults, access, locks);
  } else {
    renderReadonlyTable(schemaBox, key, fields);
  }
}

/** 값 접근 계약 — 블록 한 벌(AP·작동기·항법)과 축 한 벌(SCAS)의 차이를 여기서 흡수.
 *
 * 축 쓰기가 세 축을 함께 담는 이유는 서버 계약이다(req.scas는 부분 주입 거부). 안
 * 고친 축은 카탈로그의 설계 kwargs로 채운다 — 스키마 기본값(0)으로 채우면 손대지도
 * 않은 축의 게인이 0이 되어 "형상이 조용히 달라진다". */
function paramAccess(block, axis, catalog) {
  const injectKey = block.detail.injectKey;
  if (!axis) {
    return {
      read: () => store.get(injectKey) ?? null,
      write: (v) => store.set(injectKey, v),
      reset: () => store.set(injectKey, null),
      defaults: null,
      lockBlock: block.id === "autopilot" ? "autopilot" : null,
      lockGroup: null,
      codegen: block.detail.codegen,
    };
  }
  const design = catalog?.scas_design ?? {};
  return {
    read: () => store.get(injectKey)?.[axis.group] ?? null,
    write: (v) => store.set(injectKey, {
      ...scasKwargs(catalog, store.get(injectKey)), [axis.group]: v,
    }),
    reset: () => {
      const rest = { ...(store.get(injectKey) ?? {}) };
      delete rest[axis.group];
      store.set(injectKey, Object.keys(rest).length ? scasKwargs(catalog, rest) : null);
    },
    defaults: design[axis.group] ?? null,
    lockBlock: "scas",
    lockGroup: axis.group,
    codegen: { ...block.detail.codegen, varName: axis.varName, cPrefix: axis.cPrefix },
  };
}

/** 스케줄이 덮고 있는 파라미터 → {slot, value, label} — 폼 잠금 표시의 근거.
 *
 * value는 **지금 걸린 표의 설계점 값**이다. 편집한 표가 있으면 그 표에서, 없으면
 * 서버 제안 표의 설계점(= 설계 상수)에서 읽는다 — 잠긴 칸에 옛 상수를 남기면
 * 스케줄을 껐을 때 화면과 다른 값으로 굳는다. */
function scheduleLocks(catalog, access) {
  if (!catalog || !access.lockBlock) return new Map();
  const tables = store.get("gainTables");
  const selected = selectedSlots(catalog, tables, store.get("gainScheduleOff"));
  const slots = slotIndex(catalog);
  const out = new Map();
  for (const [param, name] of lockedParams(catalog, selected, access.lockBlock, access.lockGroup)) {
    const slot = slots.get(name);
    const table = tables?.[name] ?? slot?.table;
    out.set(param, {
      // 좌표로 읽는다 — 자동 설계 확정본은 격자가 서버 제안과 달라(자리마다 다르기도
      // 하다) 인덱스로 읽으면 엉뚱한 비행조건의 값이 설계점 배지에 뜬다
      slot: name,
      value: designValue(catalog, table),
      label: designPointLabel(catalog, slot),
    });
  }
  return out;
}

/** "M0.6" — 잠금 배지에 붙일 설계점 표기 (축 이름·격자는 서버가 정본). */
function designPointLabel(catalog, slot) {
  const axisName = catalog?.axis;
  const grid = slot?.table?.axes?.[axisName];
  const at = grid?.[catalog?.design_index];
  return at == null ? "설계점" : `${String(axisName).toUpperCase()[0]}${at}`;
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

function renderForm(schemaBox, block, key, fields, svgWrap, defaults, access, locks) {
  const applied = access.read(); // 이전 적용값 (전체 kwargs) 또는 null
  const statusLine = el("p", { class: "hint" },
    applied ? "적용된 편집값이 있습니다 — 시뮬 실행이 이 값을 주입합니다." : "");
  const errBox = el("div");
  const codeBox = el("div"); // 코드 생성 결과 (버튼을 누르기 전엔 비어 있음)
  const inputs = {}; // name → input 요소 (잠긴 자리는 없다)

  /** 잠긴 자리의 값 = 걸린 표의 설계점 값. 입력이 없으므로 여기서만 나온다. */
  const lockedValue = (f) => {
    const v = locks.get(f.name)?.value;
    return typeof v === "number" ? v : (applied?.[f.name] ?? defaults[f.name] ?? f.default);
  };

  // 폼 입력 → 블록도 수치 실시간 동기화 (파싱 실패 필드는 마지막 유효값 유지)
  const liveSync = () => {
    const vals = { ...defaults };
    for (const f of fields) {
      if (locks.has(f.name)) { vals[f.name] = lockedValue(f); continue; }
      if (f.type === "boolean") { vals[f.name] = inputs[f.name].checked; continue; }
      const r = parseFieldValue(f, inputs[f.name].value);
      if (!r.error) vals[f.name] = r.value;
    }
    bindSvgParams(svgWrap, vals);
  };

  const lockedFieldEl = (f) => {
    const lk = locks.get(f.name);
    const unit = f.unit && f.unit !== "-" ? ` [${f.unit}]` : "";
    return el("label", {
      class: "field locked",
      title: `${f.desc} — 게인 탭에서 '${lk.slot}' 자리가 스케줄로 켜져 있습니다. `
        + "값의 정본은 그 표이고, 실행 시점에는 룩업이 이 상수를 덮습니다.",
    },
      `${f.name}${unit}`,
      el("input", { class: "num", value: String(lockedValue(f)), disabled: true }),
      el("span", { class: "lock-note" }, `🔒 스케줄 중 · ${lk.label} 값`),
    );
  };

  const fieldEl = (f) => {
    if (locks.has(f.name)) return lockedFieldEl(f);
    // 기본값은 스키마가 아니라 `defaults`다 — ScasAxis는 범용 축이라 스키마 기본값이
    // 전부 0이고, 그걸 폼에 띄우면 게인 없는 축을 설계값인 양 보여 준다
    const cur = applied?.[f.name] ?? defaults[f.name] ?? f.default;
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

  // 주입 계약: autopilot·scas는 서버가 레지스트리 ParamDef로 판정(타입·범위·choices —
  // bool/enum 컴포넌트도 수용). nav·actuators는 여전히 수치 한정 validator —
  // 그쪽을 승격하려면 서버의 레지스트리 판정 확장이 선행 (리뷰 S2 갱신).
  // 잠긴 자리도 값을 담는다 — 빼면 서버 ParamDef 기본값(SCAS는 0)이 들어찬다.
  const collect = () => {
    const values = {};
    const errors = [];
    for (const f of fields) {
      if (locks.has(f.name)) {
        values[f.name] = lockedValue(f);
        continue;
      }
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
          access.write(values);
          liveSync();
          statusLine.textContent = access.lockGroup
            ? "적용됨 — 세 축 전부가 한 벌로 주입됩니다 (안 고친 축은 설계값)."
            : "적용됨 (전체 kwargs 교체) — 시뮬레이션 탭 실행이 이 값을 주입합니다.";
        },
      }, "시뮬에 적용"),
      el("button", {
        onclick: () => {
          access.reset();
          clear(errBox);
          for (const f of fields) {
            if (locks.has(f.name)) continue; // 입력이 없다 (스케줄 정본)
            const d = defaults[f.name];
            if (f.type === "boolean") inputs[f.name].checked = d === true;
            else inputs[f.name].value = String(d);
          }
          liveSync();
          statusLine.textContent = "적용 해제 — 시뮬은 설계 기본값으로 돌아갑니다.";
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
          showBlockCode(codeBox, block, values, access.codegen);
        },
      }, "코드 생성"),
    ),
    statusLine, errBox, codeBox,
    locks.size
      ? el("p", { class: "hint" },
          `🔒 ${[...locks.keys()].join(" · ")} — 게인 탭에서 스케줄로 켜 둔 자리입니다. `
          + "값의 정본은 그 표이고 여기 상수는 설계점 값입니다. 상수로 되돌리려면 "
          + "게인 탭에서 그 자리의 체크를 끄세요 (탑재 코드에서 룩업이 사라집니다).")
      : null,
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

/** 블록 + 값 → {spec, validation}. values=null이면 엔진 기본값 형상.
 * cgOverride는 축이 여럿인 블록의 축별 varName·cPrefix (lib/blocks codegenTargets). */
async function buildSpec(block, values, cgOverride = null, appliedOverride = null) {
  const { key, fields } = await fetchFields(block);
  // 설계값으로 채운 줄은 값이 있어도 "편집값"이 아니다 (lib/blocks codegenTargets)
  const applied = appliedOverride ?? values != null;
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
  const cg = cgOverride ?? block.detail.codegen;
  return {
    validation,
    spec: {
      key, fields, values: vals, applied,
      pyImport: sym.py_import ?? "claw", pyClass: sym.py_class ?? block.detail.schema.name,
      varName: cg.varName, cPrefix: cg.cPrefix, kind: cg.kind, hint: cg.hint ?? "",
      group: cg.group ?? null, // 축이 여럿인 블록의 축 이름 (탑재 C 요청 조립용)
      desc: block.detail.desc, notes: SUBSYSTEMS[block.id]?.notes ?? "",
    },
  };
}

const busy = (box, text) => clear(box).append(el("p", { class: "hint" }, text));

/** 블록 1개 — 폼의 현재 값으로 생성 (적용 여부와 무관하게 지금 보이는 형상). */
async function showBlockCode(box, block, values, cgOverride = null) {
  busy(box, "코드 생성 중…");
  try {
    const [{ spec, validation }, meta] = await Promise.all([
      buildSpec(block, values, cgOverride), codegenMeta(),
    ]);
    renderCodePanel(box, { specs: [spec], meta, validation: [validation] });
  } catch (e) {
    clear(box).append(el("div", { class: "error-box" }, errorText(e)));
  }
}

/** 전체 형상 — 편집 블록의 적용값(없으면 설계 기본값) + 게인 스케줄 테이블.
 *
 * SCAS는 축마다 한 줄로 펴고, 편집이 없어도 **카탈로그 설계 kwargs**로 채운다 —
 * ScasAxis의 스키마 기본값은 0이라 그대로 내면 게인 없는 형상 코드가 나온다. */
async function showSnapshotCode(box) {
  busy(box, "전체 형상 코드 생성 중…");
  try {
    const catalog = await loadGainsCatalog();
    const blocks = BLOCKS.filter((b) => b.detail.editable && b.detail.codegen);
    const targets = blocks.flatMap((b) =>
      codegenTargets(b, store.get(b.detail.injectKey), catalog?.scas_design)
        .map((t) => ({ block: b, ...t })));
    const [built, meta] = await Promise.all([
      Promise.all(targets.map((t) => buildSpec(t.block, t.values, t.cg, t.applied))),
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
