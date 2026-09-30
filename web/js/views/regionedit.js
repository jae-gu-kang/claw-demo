/** 요구영역 편집 화면 (05 §11.13 이관 6단계 · 06 §10 ①) — 엔벨로프 탭 ① 선도 자리에 선다.

숫자 표가 정본이다. 그림은 그 표를 서버 미리 보기(`POST /grid/region/preview` — 엔진이 검증·윤곽·기본 격자·영향을 낸다)로
그린 것이다 — 꼭짓점을 누르면 그 표 칸이 골라지고, **좌우로 끌면 그 칸의 마하가 바뀐다**(고도는 표에서만 — 끌어서 고도를
바꾸면 행 순서가 뒤바뀌어 422 경로 짝짓기가 손 안에서 흔들린다). 끌기는 타자의 대체가 아니라 덧붙임이고, 놓을 때의 값은
타자와 **같은 길**(edit → applyCell)로 간다. 칸 쓰기 규칙(전체 연료 / 현재 연료만 · 경계표 세우기 · 오류 칸)과 끌기의
눈금·창(dragGrab·dragMach)은 lib/regionedit.js, 여기는 배선·그리기만.

화면 규약(사용자 지적): 그림 위엔 조작만([요구영역 편집] · 연료 칩 · 「전체 연료 / 현재 연료만」 · 저장 버튼) — 이름·값·
수는 그림 아래 **캡션 한 줄**에, 설명은 툴팁에. 그림 안에는 글자를 쓰지 않는다(눈금 숫자는 여백).

- 미리 보기는 입력마다 ~250 ms 뒤에 한 번. 차례(seq) 가드: 늦게 온 옛 답이 새 답을 덮지 않는다. 끄는 동안엔 서버를
  부르지 않는다 — 유령 윤곽·캡션 읽음만 그리고, 놓을 때 한 번 쓰면 그 뒤는 평소의 물린 미리 보기다.
- 422 {path, message} → 그 칸 강조 + 캡션에 메시지. 수치가 아닌 칸은 보내지 않고 그 자리에서 말한다.
- 미확정(저장본에 절이 없어 trim_grid 초안이거나, 저장하지 않은 편집) → 점선 윤곽 + 캡션 「미확정」.
- [저장]/[확정] = `PUT /profiles/{id}/operating-region` (base_revision) — 저장이 곧 확정. [요구영역 지우기] = null.
  예제 기체는 편집·미리 보기는 되고 저장만 막힌다(툴팁 「복제한 기체에서」).
- 계보 패널(접힘): 기본 격자 출처·규칙·판(region_key) · 리비전 이력([출처 보기] — 그 리비전 값 읽기 전용) · 소비자 상태.
- 요구영역은 기체 전체(형상 변형 공통)다 — 형상 변형을 골라도 기본 문서의 절을 보고 고친다(미리 보기에 {id}만 싣는다).
- 낡음: 고른 기체가 바뀌면(헤더 선택 → hashchange → 다시 만듦) 다시 받는다. 미리 보기가 되울린 리비전이 앞서 있으면
  편집이 없을 때 조용히 다시 받고, 편집이 있으면 캡션 경고 + [최신 불러오기](저장의 409도 같은 버튼).
- 표는 칸을 떠날 때(change) 한 박자 뒤에 다시 짜고 포커스를 (고도, 칸)으로 되돌린다 — 미리 보기 답은 표를 다시 짜지 않는다.

상태는 모듈에 산다 — 탭을 떠났다 와도 편집 사본·연료·범위 토글이 남는다(condpick.js와 같은 관행).
*/

import { ApiError, api, errorText } from "../api.js";
import { clear, el } from "../dom.js";
import { boundColor, boundarySegments, requirementBands } from "../lib/envelope.js";
import { niceTicks } from "../lib/plot.js";
import { currentSelection, EXAMPLE_ID } from "../lib/profile.js";
import {
  SCOPE_ALL, SCOPE_LABEL, SCOPE_LAYER, addRow, applyCell, boundarySummary, dragGrab, dragMach, errorCell, errorTarget,
  fuelChoices, hitVertex, impactLine, impactTip, isLayerFuel, lineageRows, plotScale, removeRow, sameSection, shownFuels,
  tableRows, vertexCell, workingFromRegion,
} from "../lib/regionedit.js";
// 클릭↔드래그 문턱은 지도 편집기와 같은 정본을 쓴다 — 여기 px을 따로 적으면 한쪽만 고쳐졌을 때 제스처가 갈린다
import { isDrag } from "../lib/wpmap.js";
import { makeCanvas } from "./plots.js";

const W = 780;
const H = 420;
const EXAMPLE_TIP = "예제 기체는 고칠 수 없습니다 — 기체 탭에서 복제한 기체에서 저장합니다(편집·미리 보기는 됩니다)";
const SCOPE_TIP = {
  all: "같은 고도 행의 같은 칸을 모든 연료 층에 같은 값으로 씁니다 — 그 행이 없는 층엔 행을 넣고, 층마다 달랐던 값은 "
    + "캡션이 무엇을 덮었는지 말합니다",
  layer: "보이는 연료 층의 행만 고칩니다 — 다른 층은 그대로이고, 층 사이 연료는 두 층 사이 선형 보간입니다",
};
const C = {
  reqFill: "rgba(0, 64, 221, 0.10)", reqLine: "#0040dd", frame: "#d2d2d7", tick: "#86868b",
  gap: "rgba(142, 142, 147, 0.55)", undef: "#c93400", point: "#1d1d1f", gapPt: "#8e8e93", stored: "#34c759",
  vertex: "#0040dd", sel: "#ff9500",
};
const VARIANT_TIP = "형상 변형을 골랐어도 요구영역은 기체 문서(기본 형상)의 operating_region 하나입니다 — 미리 보기의 모델 "
  + "범위·기본 격자도 기본 형상 기준입니다";
const CONFIRM_TIP = "기체 문서(기본 형상)의 trim_grid에서 만든 초안을 요구 운용영역으로 확정합니다(새 리비전). 값이 같아도 "
  + "δe_trim 표는 낡음이 됩니다 — 도출 기록(provenance.region)이 확정 여부·출처까지 대조하므로 초안에서 도출한 표는 "
  + "다시 도출해야 합니다";
const near = (a, b) => Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) < 1e-9;
const SIDE_NAME = { lo: "마하 하한", hi: "마하 상한" };
const DRAG_TIP = "꼭짓점을 좌우로 끌면 그 표 칸의 마하가 바뀝니다 — 놓을 때 한 번, 표에 친 것과 똑같이 씁니다"
  + "(「전체 연료 / 현재 연료만」도 그대로). Escape나 그림 밖에서 놓으면 쓰지 않습니다. 고도는 표에서 고칩니다";

const clone = (v) => (v == null ? v : JSON.parse(JSON.stringify(v)));
// 캡션·표의 수 — 적은 값 그대로(0.1을 0.1000으로 늘리지 않는다)
const num = (v) => (Number.isFinite(v) ? String(Number(v.toPrecision(6))) : "—");
const fresh = () => ({
  editing: false, loading: false, loadError: null,
  id: null, revision: null, isExample: false, savedExists: false, saved: null,
  work: null, fuel: null, scope: SCOPE_ALL,
  preview: null, err: null, seq: 0, timer: null, pending: false, draftBase: null, headMoved: null,
  outlines: { key: null, byFuel: {} }, cellBase: null, changes: null, selected: null, note: null,
  busy: false, message: null, history: null, historyOmitted: 0, historyError: null, lineageOpen: false, source: null,
  current: null,
});
let st = fresh();

/** 테스트용 — 모듈 상태를 처음으로. */
export function resetRegionEditor() {
  clearTimeout(st.timer);
  st = fresh();
}

const sectionKey = (w) => JSON.stringify(w ?? null);
const dirty = () => !sameSection(st.work, st.saved);
const draft = () => !st.savedExists || dirty();
const outline = () => st.preview?.outline ?? [];
// 손댄 편집이 있나 — 초안은 저장본(null)과 늘 달라 dirty()로는 못 가른다: 받은 초안 그대로면 편집이 없다
const hasEdits = () => st.work != null && !sameSection(st.work, st.savedExists ? st.saved : st.draftBase);

/** 편집기 한 벌 — {root, toggle, isEditing(), repaint()}. 루트는 한 번만 만들고 안만 갈아 끼운다(칸 포커스를 지킨다).
 *  getMh — 엔벨로프 선도 응답(연료가 같으면 실속·q̄ 등 경계선을 옅게 겹친다), onMode — 편집 켜기/끄기(선도 자리를
 *  다시 그린다), onSaved(body) — 새 리비전 저장 뒤(선도를 다시 받는다). */
export function createRegionEditor({ getMh = () => null, onMode = () => {}, onSaved = () => {}, debounceMs = 250 } = {}) {
  const toggle = el("button", {
    type: "button", title: "요구 운용영역을 숫자 표로 고칩니다 — 그림은 서버 미리 보기이고, 저장하면 새 리비전이 됩니다",
  }, "요구영역 편집");
  const bar = el("div", { class: "re-bar" });
  const stage = el("div", { class: "scroll-x" });
  const cap = el("p", { class: "hint re-caption" });
  const tableBox = el("div", { class: "re-table" });
  const lineageBox = el("div");
  const lineage = el("details", { class: "re-lineage" },
    el("summary", { class: "hint", style: "cursor:pointer" }, "계보 — 기본 격자의 출처·판 · 요구영역 이력 · 낡는 결과"),
    lineageBox);
  lineage.addEventListener("toggle", () => {
    st.lineageOpen = lineage.open;
    if (st.lineageOpen && !st.history) loadHistory();
  });
  const root = el("div", { class: "re-editor" }, bar, stage, cap, tableBox, lineage);
  const inputs = new Map(); // 칸 이름 → input (강조·포커스)
  let rowInputs = []; // 보이는 층의 행마다 {alt: 고도 input, cells: [고도, 하한, 상한]} — 값으로 칸을 짚는다
  let tableCtl = []; // 행 추가 칸·삭제·추가 버튼 — 저장 중엔 막는다
  let focusId = null; // 포커스 칸 — {path} 또는 {fuel, alt, col}(재정렬돼도 같은 칸으로 되돌린다)
  let rebuild = null;
  let geom = null;
  let cv = null; // 캔버스 한 장 {canvas, ctx} — 끌기 중 다시 만들지 않는다(setPointerCapture가 요소에 붙는다)
  // 끌기 — {grab(lib dragGrab: 칸·창·눈금), scale(잡을 때의 축 — 얼린다), x0, from(잡은 값), mach, moved, pointerId}
  let drag = null;

  // soft — 미리 보기 답: 표는 다시 짜지 않는다(타자 중인 칸의 글자·포커스를 지킨다). 표가 아직 없으면 짠다
  const view = {
    root, toggle, isEditing: () => st.editing,
    repaint: (soft = false) => {
      // 고른 기체가 바뀌었다 — 앞 기체의 사본으로 이 기체를 보이면(저장하면) 안 된다
      if (st.editing && st.id !== selectedId()) {
        load();
        return;
      }
      if (soft && inputs.size) paintSoft();
      else paintAll();
    },
  };
  st.current = view;
  const paintCurrent = (soft = false) => st.current?.repaint(soft);

  toggle.addEventListener("click", () => {
    st.editing = !st.editing;
    paintToggle();
    if (st.editing && (!st.saved && !st.work || st.id !== selectedId())) load();
    onMode(st.editing);
    if (st.editing) paintAll();
  });

  function paintToggle() {
    toggle.setAttribute("aria-pressed", st.editing ? "true" : "false");
    toggle.className = st.editing ? "primary" : "";
  }

  // ── 서버 ────────────────────────────────────────────────────────────────
  function selectedId() {
    return currentSelection()?.id ?? EXAMPLE_ID;
  }

  async function load() {
    const id = selectedId();
    // 차례(seq)는 이어 센다 — 0으로 되돌리면 앞 기체의 늦은 미리 보기가 새 차례 번호와 맞아 새 답을 덮는다
    clearTimeout(st.timer);
    Object.assign(st, { ...fresh(), editing: true, loading: true, scope: st.scope, lineageOpen: st.lineageOpen,
      current: st.current, seq: st.seq });
    st.id = id;
    paintCurrent();
    try {
      const body = await api.get(`/profiles/${encodeURIComponent(id)}`);
      if (st.id !== id) return;
      const section = body.document?.operating_region ?? null;
      Object.assign(st, { revision: body.revision, isExample: !!body.is_example, savedExists: section != null,
        saved: workingFromRegion(section), work: workingFromRegion(section), loading: false });
      const mh = getMh();
      const choices = fuelChoices(st.work);
      st.fuel = choices.find((f) => Math.abs(f - (mh?.fuel ?? NaN)) < 1e-9) ?? choices[0] ?? null;
      await preview();
      loadHistory();
    } catch (e) {
      if (st.id !== id) return;
      st.loading = false;
      st.loadError = `기체 문서를 받지 못했습니다 — ${errorText(e)}`;
      paintCurrent();
    }
  }

  async function loadHistory() {
    if (!st.id) return;
    const id = st.id;
    try {
      const h = await api.get(`/profiles/${encodeURIComponent(id)}/region-history`);
      if (st.id !== id) return;
      st.history = Array.isArray(h) ? h : h?.rows ?? [];
      st.historyOmitted = h?.omitted ?? 0;
      st.historyError = null;
    } catch (e) {
      if (st.id !== id) return;
      st.historyError = `요구영역 이력을 받지 못했습니다 — ${errorText(e)}`;
    }
    paintCurrent(true);
  }

  function schedulePreview() {
    clearTimeout(st.timer);
    st.timer = setTimeout(() => preview(), debounceMs);
  }

  // 미리 보기 — 저장하지 않는다. 늦게 온 옛 답은 버린다(차례 가드)
  async function preview() {
    clearTimeout(st.timer);
    const seq = ++st.seq;
    const sent = clone(st.work);
    // 기체 id만 싣는다(형상 변형 없이) — 요구영역은 기본 문서의 절이다(형상 변형 공통). 싣지 않으면 withProfile이
    // 헤더의 형상 변형을 붙인다
    const body = { profile: { id: st.id ?? selectedId() }, region: sent };
    if (st.fuel != null) body.fuel = st.fuel;
    st.pending = true;
    let full = !inputs.size;
    try {
      const r = await api.post("/grid/region/preview", body);
      if (seq !== st.seq) return;
      // 되울린 리비전이 앞선다 — 다른 곳에서 저장했다. 편집이 없으면 조용히 최신을, 있으면 덮지 않고 알린다
      const head = r.profile?.id === st.id ? r.profile?.revision : null;
      if (Number.isInteger(head) && Number.isInteger(st.revision) && head > st.revision) {
        if (!hasEdits()) {
          load();
          return;
        }
        st.headMoved = head;
      }
      st.preview = r;
      st.err = null;
      if (!st.work && r.region) {
        // 저장본에 절이 없다 — 서버가 trim_grid에서 만든 초안을 편집 사본으로(미확정)
        st.work = workingFromRegion(r.region);
        st.draftBase = clone(st.work);
        full = true;
        const choices = fuelChoices(st.work);
        if (st.fuel == null || !choices.some((f) => Math.abs(f - st.fuel) < 1e-9)) st.fuel = choices[0] ?? null;
      }
      // 층마다 엔진 윤곽 — 보낸 사본의 것이라 사본 키를 함께 둔다(「전체 연료」가 행을 넣을 때 같은 사본에서만 쓴다)
      st.outlines = { key: sectionKey(sent), byFuel: r.outlines ?? {} };
    } catch (e) {
      if (seq !== st.seq) return;
      const d = e instanceof ApiError ? e.detail : null;
      // 보낸 사본을 같이 둔다 — 경로의 행 색인은 그 사본의 것이다(errorTarget)
      st.err = d && typeof d === "object" && "message" in d
        ? { path: d.path ?? null, message: String(d.message), work: sent }
        : { path: null, message: errorText(e) };
    } finally {
      if (seq === st.seq) {
        st.pending = false;
        paintCurrent(!full);
      }
    }
  }

  async function putRegion(section) {
    if (st.isExample || st.busy) return;
    const id = st.id;
    st.busy = true;
    st.message = null;
    st.note = null; // 앞선 끌기·고르기 안내가 저장 알림 옆에 남지 않게
    clearTimeout(st.timer); // 저장 중 미리 보기가 끼면 저장 전 사본의 답이 저장 뒤 화면을 덮는다
    paintBar();
    paintMarks(); // 칸을 막는다 — 저장 중 타자가 저장 뒤 사본에 덮여 사라지지 않게
    try {
      const r = await api.put(`/profiles/${encodeURIComponent(id)}/operating-region`,
        { base_revision: st.revision, operating_region: section });
      if (st.id !== id) return;
      Object.assign(st, { revision: r.revision, savedExists: section != null, saved: workingFromRegion(section),
        work: workingFromRegion(section), draftBase: null, headMoved: null, changes: null, err: null, history: null,
        source: null, message: `리비전 ${r.revision} 저장 — 판 ${r.region_key ?? "없음"}` });
      st.busy = false;
      paintTable();
      await preview();
      loadHistory();
      onSaved(r);
    } catch (e) {
      if (st.id !== id) return;
      const d = e instanceof ApiError ? e.detail : null;
      if (e instanceof ApiError && e.status === 409 && d?.head != null) {
        st.headMoved = d.head; // 캡션 경고 + [최신 불러오기]
      } else if (d && typeof d === "object" && "message" in d) {
        st.err = { path: d.path ?? null, message: String(d.message), work: section };
      } else {
        st.message = `⚠ 저장하지 못했습니다 — ${errorText(e)}`;
      }
    } finally {
      if (st.id === id) {
        st.busy = false;
        paintCurrent(true);
      }
    }
  }

  // ── 편집 ────────────────────────────────────────────────────────────────
  // 칸마다 포커스 시점의 사본을 기준으로 쓴다 — 타자마다 「전체 연료」가 앞 글자의 값을 옛 값으로 적지 않게
  function edit(path, value) {
    if (st.busy) return;
    const base = st.cellBase?.path === path ? st.cellBase : { work: st.work, outline: outline() };
    // 층 윤곽은 그 사본에서 받은 것만 — 포커스 뒤 늦게 온 답도 같은 사본이면 쓴다, 다른 사본의 윤곽은 안 쓴다
    const outlines = st.outlines.key === sectionKey(base.work) ? st.outlines.byFuel : null;
    const r = applyCell(base.work, { path, value, scope: st.scope, outline: base.outline, outlines });
    if (r.error) {
      st.err = r.error;
      paintCaption();
      paintMarks();
      return;
    }
    commit(r);
  }

  function commit(r) {
    st.work = r.work;
    st.changes = r.changes?.length ? r.changes : null;
    st.err = null;
    st.message = null;
    st.note = null;
    schedulePreview();
    paintBar();
    paintCanvas();
    paintCaption();
    paintMarks();
  }

  const setFuel = (f) => {
    st.fuel = f;
    st.selected = null;
    preview();
    paintAll();
  };

  // ── 그리기 ──────────────────────────────────────────────────────────────
  function paintAll() {
    paintToggle();
    if (!st.editing) return;
    paintBar();
    paintCanvas();
    paintCaption();
    paintTable();
    paintLineage();
  }

  function paintSoft() {
    paintToggle();
    if (!st.editing) return;
    paintBar();
    paintCanvas();
    paintCaption();
    paintMarks();
    paintLineage();
  }

  function segButton(scope) {
    const on = st.scope === scope;
    return el("button", {
      type: "button", class: on ? "primary" : "", "aria-pressed": on ? "true" : "false", title: SCOPE_TIP[scope],
      onclick: () => {
        st.scope = scope;
        st.cellBase = null;
        paintBar();
      },
    }, SCOPE_LABEL[scope]);
  }

  function paintBar() {
    const lockTip = st.isExample ? EXAMPLE_TIP : null;
    const canSave = !st.isExample && !st.busy && !!st.work && (dirty() || !st.savedExists) && !st.err
      && st.headMoved == null;
    const saveLabel = st.savedExists ? "저장" : "확정";
    const latest = st.headMoved == null ? null : el("button", {
      type: "button", disabled: st.busy,
      title: `리비전 ${st.headMoved}이 최신입니다 — 저장하지 않은 편집을 버리고 최신을 불러옵니다`,
      onclick: () => {
        if (hasEdits() && globalThis.confirm && !globalThis.confirm("저장하지 않은 편집을 버리고 최신을 불러올까요?")) return;
        load();
      },
    }, "최신 불러오기");
    clear(bar).append(
      toggle,
      el("span", { class: "re-group", title: "보이는 연료 — 경계표의 연료 층(없으면 기본 연료 범위 양끝)과 기본 격자 연료. "
        + "층이 아닌 연료는 층 사이 보간이라 보기만 합니다" },
        ...shownFuels(st.work).map((f) => el("button", {
          type: "button", class: Math.abs(f - (st.fuel ?? NaN)) < 1e-9 ? "primary" : "",
          "aria-pressed": Math.abs(f - (st.fuel ?? NaN)) < 1e-9 ? "true" : "false",
          onclick: () => setFuel(f),
        }, `${num(f)} kg`))),
      el("span", { class: "re-group", role: "group" }, segButton(SCOPE_ALL), segButton(SCOPE_LAYER)),
      el("button", {
        type: "button", class: "primary", disabled: !canSave,
        title: lockTip ?? (st.headMoved != null ? `리비전 ${st.headMoved}이 최신입니다 — 최신을 불러온 뒤 고칩니다`
          : st.savedExists
            ? `리비전 ${st.revision} 위에 요구영역만 새 리비전으로 저장합니다 — 지문(계산 입력)은 그대로입니다`
            : CONFIRM_TIP),
        onclick: () => putRegion(clone(st.work)),
      }, saveLabel),
      latest,
      el("button", {
        type: "button", disabled: !dirty() || st.busy,
        title: "저장본으로 되돌립니다", onclick: () => {
          st.work = clone(st.saved);
          st.draftBase = null;
          st.changes = null;
          st.err = null;
          if (!st.work) st.preview = null;
          preview();
          paintAll();
        },
      }, "되돌리기"),
      el("button", {
        type: "button", disabled: st.isExample || !st.savedExists || st.busy,
        title: lockTip ?? "기체 문서의 요구 운용영역을 지웁니다(새 리비전) — 그 뒤엔 trim_grid 초안(미확정)이 요구영역입니다",
        onclick: () => {
          if (globalThis.confirm && !globalThis.confirm("요구 운용영역을 지울까요? 새 리비전으로 저장됩니다.")) return;
          putRegion(null);
        },
      }, "요구영역 지우기"),
    );
  }

  // 캔버스는 **한 장을 지킨다** — 다시 만들면 setPointerCapture가 붙은 요소가 사라져 끌기가 손에서 끊긴다
  // (views/wpmap.js·plot3d.js와 같은 규약). 그려진 것은 clearRect로 지운다
  function ensureCanvas() {
    if (cv) return cv;
    cv = makeCanvas(W, H);
    const { canvas } = cv;
    canvas.style.touchAction = "none"; // 터치·펜도 끈다 — 스크롤이 제스처를 삼키지 않게
    canvas.setAttribute("aria-label", "요구영역 선도 — 꼭짓점을 누르면 그 표 칸이 골라지고, 좌우로 끌면 그 칸의 마하가 "
      + "바뀝니다(고도는 표에서 고칩니다)");
    wireCanvas(canvas);
    return cv;
  }

  function paintCanvas() {
    const { canvas, ctx } = ensureCanvas();
    canvas.setAttribute("title", "가로 마하 · 세로 고도 [m] — 파란 면은 보이는 연료의 요구영역(점선이면 미확정), 빗금은 "
      + "모델 부족(공력 DB 마하 밖), 주황 점선 행은 요구 미정의, 점은 기본 격자(초록 고리 = 트림 저장소 수렴 기록, 회색 "
      + "네모 = 모델 부족), 파란 네모는 경계표 꼭짓점 — 누르면 그 표 칸을 고르고, 좌우로 끌면 마하를 고칩니다");
    if (stage.children?.[0] !== canvas) clear(stage).append(canvas);
    ctx.clearRect(0, 0, W, H);
    const p = st.preview;
    const points = (p?.grid?.points ?? []).filter((q) => Math.abs(q.fuel - (st.fuel ?? NaN)) < 1e-9);
    geom = plotScale({ work: st.work, model: p?.model, points, width: W, height: H });
    ctx.strokeStyle = C.frame;
    ctx.lineWidth = 1;
    if (!geom) {
      ctx.strokeRect(0.5, 0.5, W - 1, H - 1);
      return;
    }
    const { x, y, mL, mR, mT, mB } = geom;
    const [m0, m1] = geom.domain.mach;
    const [a0, a1] = geom.domain.alt;
    ctx.strokeRect(mL, mT, W - mL - mR, H - mT - mB);
    // 눈금 — 숫자는 여백에만(그림 위에는 글자가 없다)
    ctx.fillStyle = C.tick;
    ctx.textAlign = "center";
    for (const t of niceTicks(m0, m1, 6)) if (t >= m0 && t <= m1) ctx.fillText(num(t), x(t), H - mB + 16);
    ctx.textAlign = "right";
    for (const t of niceTicks(a0, a1, 5)) if (t >= a0 && t <= a1) ctx.fillText(num(t), mL - 6, y(t) + 4);
    ctx.textAlign = "left";

    ctx.save();
    ctx.beginPath();
    ctx.rect(mL, mT, W - mL - mR, H - mT - mB);
    ctx.clip();
    // 모델 부족 — 공력 DB 마하 밖(연료가 모델 밖이면 전부) 빗금
    const model = p?.model;
    const fuelOut = model?.fuel && st.fuel != null && (st.fuel < model.fuel[0] - 1e-9 || st.fuel > model.fuel[1] + 1e-9);
    const hatch = (xa, xb) => {
      ctx.strokeStyle = C.gap;
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let k = xa - (H - mB - mT); k < xb; k += 8) {
        ctx.moveTo(Math.max(k, xa), mT + (Math.max(k, xa) - k));
        ctx.lineTo(Math.min(k + (H - mB - mT), xb), mT + (Math.min(k + (H - mB - mT), xb) - k));
      }
      ctx.stroke();
    };
    if (fuelOut) hatch(mL, W - mR);
    else if (model?.mach) {
      if (model.mach[0] > m0) hatch(mL, x(model.mach[0]));
      if (model.mach[1] < m1) hatch(x(model.mach[1]), W - mR);
    }
    // 엔벨로프 선도의 경계선(실속·q̄·M_NO…) — 같은 연료일 때만, 옅게
    const mh = getMh();
    if (mh?.region && Math.abs(mh.fuel - (st.fuel ?? NaN)) < 1e-9) {
      ctx.globalAlpha = 0.55;
      for (const seg of boundarySegments(mh.region)) {
        if (seg.pts.length < 2) continue;
        ctx.strokeStyle = boundColor(seg.source);
        ctx.lineWidth = 1.2;
        ctx.beginPath();
        seg.pts.forEach((q, i) => (i ? ctx.lineTo(x(q.mach), y(q.alt)) : ctx.moveTo(x(q.mach), y(q.alt))));
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }
    // 요구영역 — 엔진 윤곽(보이는 연료)
    const ol = outline();
    const req = bandsOf(ol);
    ctx.fillStyle = C.reqFill;
    for (const poly of req.polys) {
      ctx.beginPath();
      poly.forEach((q, i) => (i ? ctx.lineTo(x(q.mach), y(q.alt)) : ctx.moveTo(x(q.mach), y(q.alt))));
      ctx.closePath();
      ctx.fill();
    }
    ctx.strokeStyle = C.reqLine;
    ctx.lineWidth = 2.2;
    ctx.setLineDash(draft() ? [7, 4] : []);
    for (const poly of req.polys) {
      ctx.beginPath();
      poly.forEach((q, i) => (i ? ctx.lineTo(x(q.mach), y(q.alt)) : ctx.moveTo(x(q.mach), y(q.alt))));
      ctx.closePath();
      ctx.stroke();
    }
    for (const ln of req.lines) {
      ctx.beginPath();
      ctx.moveTo(x(ln.mach0), y(ln.alt));
      ctx.lineTo(x(ln.mach1), y(ln.alt));
      ctx.stroke();
    }
    ctx.setLineDash([]);
    // 요구 미정의 행 — 기본 마하 범위를 가로지르는 주황 점선
    ctx.strokeStyle = C.undef;
    ctx.lineWidth = 3;
    ctx.setLineDash([2, 4]);
    for (const a of req.undefinedAlts) {
      ctx.beginPath();
      ctx.moveTo(x(st.work.mach[0]), y(a));
      ctx.lineTo(x(st.work.mach[1]), y(a));
      ctx.stroke();
    }
    ctx.setLineDash([]);
    // 기본 격자 점
    for (const q of points) {
      if (q.state === "model_gap") {
        ctx.strokeStyle = C.gapPt;
        ctx.lineWidth = 1.3;
        ctx.strokeRect(x(q.mach) - 3, y(q.alt) - 3, 6, 6);
        continue;
      }
      ctx.fillStyle = C.point;
      ctx.beginPath();
      ctx.arc(x(q.mach), y(q.alt), 2.6, 0, 2 * Math.PI);
      ctx.fill();
      if (q.stored?.converged) {
        ctx.strokeStyle = C.stored;
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        ctx.arc(x(q.mach), y(q.alt), 5.2, 0, 2 * Math.PI);
        ctx.stroke();
      }
    }
    // 경계표 꼭짓점 — 누르면 그 칸(고른 칸은 주황)
    for (const r of tableRows(st.work, st.fuel, ol)) {
      for (const [col, m] of [[1, r.lo], [2, r.hi]]) {
        if (!Number.isFinite(m)) continue;
        const on = st.selected === r.paths[col];
        ctx.fillStyle = on ? C.sel : C.vertex;
        const s = on ? 5 : 3.5;
        ctx.fillRect(x(m) - s, y(r.alt) - s, 2 * s, 2 * s);
      }
    }
    // 끄는 중 — 놓을 자리의 윤곽(유령 점선)과 그 꼭짓점만 이 자리에서 보인다(서버는 놓을 때 한 번 부른다).
    // 사본(st.work)은 건드리지 않으므로 실선 윤곽이 지금 값으로 남아 무엇이 어디로 가는지 함께 보인다
    if (drag?.moved && drag.mach != null) {
      const ghost = ol.map((r) => (near(r.alt, drag.grab.alt) ? { ...r, [`mach_${drag.grab.side}`]: drag.mach } : r));
      const gb = bandsOf(ghost);
      ctx.strokeStyle = C.sel;
      ctx.lineWidth = 1.6;
      ctx.setLineDash([5, 3]);
      for (const poly of gb.polys) {
        ctx.beginPath();
        poly.forEach((q, i) => (i ? ctx.lineTo(x(q.mach), y(q.alt)) : ctx.moveTo(x(q.mach), y(q.alt))));
        ctx.closePath();
        ctx.stroke();
      }
      for (const ln of gb.lines) {
        ctx.beginPath();
        ctx.moveTo(x(ln.mach0), y(ln.alt));
        ctx.lineTo(x(ln.mach1), y(ln.alt));
        ctx.stroke();
      }
      ctx.setLineDash([]);
      ctx.fillStyle = C.sel;
      ctx.fillRect(x(drag.mach) - 5, y(drag.grab.alt) - 5, 10, 10);
    }
    ctx.restore();
  }

  const bandsOf = (rows) => requirementBands({ band: { alt: rows.map((r) => r.alt), mach_lo: rows.map((r) => r.mach_lo),
    mach_hi: rows.map((r) => r.mach_hi), state: rows.map((r) => r.state) } });

  // ── 꼭짓점 고르기·끌기 ──────────────────────────────────────────────────
  // 누르면 고르고(옛 click과 같다), 좌우로 끌면 **마하만** 바뀐다. 고도를 끌지 않는 이유: 고도를 끌면 행 순서가 뒤바뀌고,
  // 422의 행 색인 → 화면 칸 짝짓기(errorTarget)가 기대는 고도 오름차순이 손 안에서 흔들린다. 고도는 표 칸으로 고친다.
  // 놓을 때 쓰는 값은 **타자와 같은 길**로 간다(edit → applyCell) — 전체 연료/현재 연료만, 경계표 세우기, 층 윤곽 거부,
  // 물린 미리 보기, 422 칸 강조, 낡음 가드, 예제 기체 저장 막힘이 모두 그대로다
  function wireCanvas(canvas) {
    const at = (ev) => {
      const rect = canvas.getBoundingClientRect();
      return { px: (ev.clientX - rect.left) * (W / (rect.width || W)),
        py: (ev.clientY - rect.top) * (H / (rect.height || H)) };
    };
    const inPlot = ({ px, py }) => !!geom && px >= geom.mL && px <= W - geom.mR && py >= geom.mT && py <= H - geom.mB;
    // 히트테스트는 **그려진 꼭짓점과 같은 값**을 본다: 경계표 행은 편집 사본이 정본이고(방금 끈 값이 곧바로 다시
    // 잡힌다 — 미리 보기가 돌아올 때까지 옛 자리에서만 잡히면 연속으로 끌 수 없다), 사본에 없는 고도(행 사이 보간)는
    // 엔진 윤곽에서 온다 — 그 꼭짓점은 고르기만 되고 끌 칸이 없다(dragGrab이 거부한다)
    function hitRows() {
      const ol = outline();
      const rows = tableRows(st.work, st.fuel, ol)
        .filter((r) => Number.isFinite(r.lo) || Number.isFinite(r.hi))
        .map((r) => ({ alt: r.alt, mach_lo: r.lo, mach_hi: r.hi, state: "in" }));
      return [...rows, ...ol.filter((o) => !rows.some((r) => near(r.alt, o.alt)))];
    }
    const hitAt = (px, py) => (geom ? hitVertex(hitRows(), px, py, { x: geom.x, y: geom.y, r: 9 }) : null);

    // 누른 꼭짓점의 표 칸을 고른다(끌지 않아도) — 골라진 칸에 타자할 수 있어야 끌기가 대체가 아닌 덧붙임이 된다
    function select(hit) {
      const c = vertexCell(st.work, st.fuel, hit, outline());
      st.selected = c;
      st.note = c ? null : `고도 ${num(hit.alt)} m는 경계표 행이 아니다(행·층 사이 보간)`;
      paintCanvas();
      paintCaption();
      paintMarks();
      // The input is below the plot; ordinary focus scrolls it into view mid-drag.
      if (c) inputs.get(c)?.focus({ preventScroll: true });
      return c;
    }

    const onKey = (ev) => {
      if (ev.key !== "Escape" || !drag) return;
      ev.preventDefault?.();
      endDrag(null, true);
    };

    function endDrag(ev, cancel) {
      if (!drag) return;
      const d = drag;
      drag = null;
      globalThis.window?.removeEventListener?.("keydown", onKey);
      if (ev && canvas.hasPointerCapture?.(ev.pointerId)) canvas.releasePointerCapture?.(ev.pointerId);
      canvas.style.cursor = "default";
      // 취소(Escape·그림 밖에서 놓기·pointercancel)거나 문턱을 넘지 않았으면 **아무것도 쓰지 않는다**
      if (cancel || !d.moved || d.mach == null) {
        if (cancel && d.moved) st.note = "끌기를 취소했습니다 — 아무것도 쓰지 않았습니다";
        paintCanvas();
        paintCaption();
        return;
      }
      commitDrag(d);
    }

    // 놓을 때 한 번 — 타자와 같은 길(edit)로 쓴다. 표 칸의 글도 같이 바꿔 둔다(끌기와 타자가 같은 칸이다)
    function commitDrag(d) {
      const inp = inputs.get(d.grab.cell);
      const text = String(d.mach);
      if (inp) inp.value = text;
      edit(d.grab.cell, text);
      st.cellBase = null; // 한 번 쓰고 기준 사본을 놓는다 — 다음 끌기·타자는 새 기준(칸을 떠난 것과 같다)
      if (!st.err) {
        st.note = `끌어 고침 — 고도 ${num(d.grab.alt)} m ${SIDE_NAME[d.grab.side]} ${num(d.from)} → ${num(d.mach)}`
          + (d.mach === d.grab.min || d.mach === d.grab.max ? " (한계에 물림)" : "");
      }
      paintTable(true); // 경계표를 막 세웠으면(가상 행 → 실제 행) 표가 달라진다 — 고도 순서는 끌기로 바뀌지 않는다
      paintCaption();
    }

    canvas.addEventListener("pointerdown", (ev) => {
      if (ev.button != null && ev.button !== 0) return;
      if (!geom || st.busy) return;
      const { px, py } = at(ev);
      const hit = hitAt(px, py);
      if (!hit) return;
      ev.preventDefault?.();
      const cell = select(hit);
      const grab = dragGrab(st.work, st.fuel, hit, outline());
      if (!grab.cell) {
        if (cell) {
          st.note = grab.reason; // 고르기는 됐지만 끌 수는 없다 — 왜인지 캡션이 말한다
          paintCaption();
        }
        return;
      }
      drag = { grab, scale: geom, x0: px, from: hit.mach, mach: hit.mach, moved: false, pointerId: ev.pointerId };
      canvas.setPointerCapture?.(ev.pointerId);
      globalThis.window?.addEventListener?.("keydown", onKey);
    });

    canvas.addEventListener("pointermove", (ev) => {
      const { px, py } = at(ev);
      if (!drag) {
        // 끌 수 있는 꼭짓점 위에서만 커서를 바꾼다(app.css는 건드리지 않는다 — wpmap 관례)
        if (!st.busy) {
          const h = hitAt(px, py);
          canvas.style.cursor = h && dragGrab(st.work, st.fuel, h, outline()).cell ? "ew-resize" : "default";
        }
        return;
      }
      // 문턱(lib/wpmap DRAG_PX — 클릭↔드래그 판별의 정본)을 넘기 전엔 고르기다: 누르기만 해도 값이 눈금에 붙어
      // 슬쩍 바뀌면(0.123 → 0.125) 고르려던 손이 문서를 고친다
      if (!drag.moved && !isDrag(px - drag.x0, 0)) return;
      drag.moved = true;
      const m = dragMach(drag.grab, px, drag.scale);
      if (m == null) return;
      drag.mach = m;
      paintCanvas();
      paintCaption();
    });

    canvas.addEventListener("pointerup", (ev) => endDrag(ev, !inPlot(at(ev))));
    canvas.addEventListener("pointercancel", (ev) => endDrag(ev, true));
    canvas.addEventListener("keydown", onKey); // 캔버스가 포커스를 가진 경우에도 Escape
  }

  function paintCaption() {
    const parts = [];
    const tip = (text, title) => el("span", { title }, text);
    if (st.loading) {
      clear(cap).append("기체 문서를 받는 중…");
      return;
    }
    if (st.loadError) {
      clear(cap).append(tip(`⚠ ${st.loadError}`, ""));
      return;
    }
    const p = st.preview;
    const w = st.work;
    parts.push(tip(draft() ? "요구영역 미확정" : "요구영역 확정", draft()
      ? (st.savedExists ? "저장하지 않은 편집 — [저장]해야 기체 문서의 요구영역이 됩니다"
        : "기체 문서에 요구 운용영역이 없어 기체 문서(기본 형상 — 형상 변형 공통)의 미션 템플릿 격자(trim_grid)에서 "
          + "만든 초안입니다 — [확정]하면 문서에 적힙니다")
      : `기체 문서 리비전 ${st.revision}의 operating_region`));
    if (currentSelection()?.variant) parts.push(tip("요구영역은 기체 전체(형상 변형 공통)", VARIANT_TIP));
    if (st.headMoved != null) {
      parts.push(el("span", { class: "re-errmsg", title: "다른 곳(다른 탭·사람·잡)이 이 기체를 저장했습니다 — "
        + "[최신 불러오기]로 최신 위에서 다시 고칩니다" },
      `⚠ 최신 리비전 ${st.headMoved} — 이 편집은 리비전 ${st.revision} 위의 것이라 저장하지 않습니다`));
    }
    if (!w) {
      parts.push(tip(p?.reason ?? (st.pending ? "미리 보기를 받는 중…" : "요구영역 없음"), ""));
    } else {
      parts.push(tip(`연료 ${num(st.fuel)} kg`, "그림·표가 보이는 연료 층"));
      parts.push(tip(`마하 ${num(w.mach[0])}–${num(w.mach[1])} · 고도 ${num(w.alt[0])}–${num(w.alt[1])} m`,
        `기본 범위 — 연료 ${num(w.fuel[0])}–${num(w.fuel[1])} kg`));
      parts.push(tip(boundarySummary(w), "경계표 행 사이·층 사이는 선형 보간, 표가 덮지 않는 조건은 요구 미정의"));
      if (p?.grid) {
        const pts = p.grid.points.filter((q) => Math.abs(q.fuel - (st.fuel ?? NaN)) < 1e-9);
        const stored = p.grid.points.filter((q) => q.stored?.converged).length;
        parts.push(tip(`기본 격자 ${p.grid.points.length}점 (이 연료 ${pts.length} · 수렴 기록 ${stored})`,
          `공통 마하 좌표 ${w.base_grid.n_mach}점 + 행 끝점 · 연료 ${w.base_grid.fuels.join(", ")} kg — 점은 기본 격자 `
          + "연료에만 있다. 수렴 기록은 트림 저장소에 수렴 해가 있는 점(다시 풀지 않는다)"));
      }
    }
    if (st.err) {
      // 보이지 않는 층의 오류는 그 층 연료를 이름으로 댄다 — 칸 강조가 화면에 없으니
      const c = errorCell(st.err.path);
      const t = errorTarget(st.err, st.err.work);
      const layerFuel = t?.fuel ?? (c.layer != null ? st.err.work?.boundary?.[c.layer]?.fuel : null);
      const where = layerFuel != null && !near(layerFuel, st.fuel) ? `연료 ${num(layerFuel)} kg 층: `
        : c.layer != null && c.cell == null ? `연료 층 ${c.layer + 1}: ` : "";
      parts.push(el("span", { class: "re-errmsg", title: st.err.path ?? "" }, `⚠ ${where}${st.err.message}`));
    } else if (p?.impact && w) {
      parts.push(tip(impactLine(p.impact, { changes: st.changes }), impactTip(p.impact)));
    }
    // 끄는 중의 읽음 — 값은 캡션에만 둔다(그림 위엔 글자를 쓰지 않는다). 영향 줄은 늘리지 않는다(놓으면 그 줄이 다시 잰다)
    if (drag?.moved && drag.mach != null) {
      parts.push(tip(`끄는 중 — 고도 ${num(drag.grab.alt)} m ${SIDE_NAME[drag.grab.side]} ${num(drag.from)} → `
        + `${num(drag.mach)}${drag.mach === drag.grab.min || drag.mach === drag.grab.max ? " (한계에 물림)" : ""}`
        + " · 놓으면 씁니다", DRAG_TIP));
    }
    // 오류가 있으면 안내(끌어 고침 등)는 내지 않는다 — 방금 쓴 값을 서버가 거부했다면 말할 것은 ⚠ 한 줄이다
    if (st.note && !st.err) parts.push(tip(st.note, ""));
    if (st.message) parts.push(tip(st.message, ""));
    clear(cap).append(...parts.flatMap((s, i) => (i ? [" · ", s] : [s])));
  }

  // 오류 칸 — 경계표 칸은 보낸 사본의 (연료, 고도)를 화면 행의 고도 칸 **글**과 짝짓는다(타자 중 재정렬돼도 맞는 칸)
  function badInput() {
    const t = errorTarget(st.err, st.err?.work ?? null);
    if (!t) return null;
    if (t.path != null) return inputs.get(t.path) ?? null;
    if (!near(t.fuel, st.fuel)) return null;
    return rowInputs.find((r) => near(Number(r.alt.value), t.alt))?.cells[t.col] ?? null;
  }

  // 칸 강조만 갈아 끼운다 — 표를 다시 만들면 타자 중인 칸의 포커스가 날아간다
  function paintMarks() {
    const bad = badInput();
    for (const [path, inp] of inputs) {
      inp.classList.toggle("re-err", inp === bad);
      inp.classList.toggle("re-sel", path === st.selected);
      inp.disabled = st.busy;
    }
    for (const c of tableCtl) c.disabled = st.busy;
  }

  // 포커스 칸의 정체 — 경계표 칸은 (연료, 행 고도 칸의 글, 칸 번호): 표를 다시 짜면 색인이 바뀌어도 같은 행을 찾는다
  function identityOf(path) {
    const m = /^\/boundary\/\d+\/rows\/\d+\/([012])$/.exec(path);
    const alt = m ? Number(rowInputs.find((r) => r.cells.includes(inputs.get(path)))?.alt.value) : NaN;
    return Number.isFinite(alt) ? { fuel: st.fuel, alt, col: Number(m[1]) } : { path };
  }

  function inputOf(id) {
    if (!id) return null;
    if (id.path != null) return inputs.get(id.path) ?? null;
    if (!near(id.fuel, st.fuel)) return null;
    return rowInputs.find((r) => near(Number(r.alt.value), id.alt))?.cells[id.col] ?? null;
  }

  function cellInput(path, value, { cls = "num", list = false } = {}) {
    const inp = el("input", { class: cls, value: value == null ? "" : list ? value.join(", ") : String(value),
      "data-cell": path });
    inp.addEventListener("focus", () => {
      if (st.cellBase?.path !== path) st.cellBase = { path, work: st.work, outline: outline() };
      focusId = identityOf(path);
      st.selected = path;
      paintMarks();
    });
    inp.addEventListener("input", () => edit(path, inp.value));
    inp.addEventListener("blur", () => {
      if (st.cellBase?.path === path) st.cellBase = null;
      if (focusId && inputOf(focusId) === inp) focusId = null;
    });
    // 칸을 떠나면 기준 사본을 놓고 표를 다시 짠다(경계표는 고도 순 — 화면 행이 사본 색인과 맞게). 한 박자 뒤에 —
    // Tab이면 change 뒤에 다음 칸 focus가 오므로 그 칸을 (고도, 칸)으로 기억한 뒤 짜고 되돌린다. 곧바로 짜면 다음
    // 칸이 옛 표와 함께 사라져 포커스가 날아간다
    inp.addEventListener("change", () => {
      st.cellBase = null;
      clearTimeout(rebuild);
      rebuild = setTimeout(() => {
        if (!st.editing) return;
        paintTable();
        paintCanvas();
      }, 0);
    });
    inputs.set(path, inp);
    return inp;
  }

  function paintTable(preventFocusScroll = false) {
    const keep = focusId; // 짜는 동안 옛 칸이 사라지며 blur가 와도 되돌릴 칸은 이것
    inputs.clear();
    rowInputs = [];
    tableCtl = [];
    const w = st.work;
    if (!w) {
      clear(tableBox);
      return;
    }
    const th = (t, title) => el("th", title ? { title } : {}, t);
    const range = (key, name, unit) => el("tr", {}, el("td", {}, `${name}${unit ? ` [${unit}]` : ""}`),
      el("td", {}, cellInput(`/${key}/0`, w[key][0])), el("td", {}, cellInput(`/${key}/1`, w[key][1])));
    const rows = tableRows(w, st.fuel, outline());
    const add = [el("input", { class: "num", placeholder: "고도" }), el("input", { class: "num", placeholder: "하한" }),
      el("input", { class: "num", placeholder: "상한" })];
    const ctl = (node) => {
      tableCtl.push(node);
      return node;
    };
    add.forEach(ctl);
    const run = (r) => {
      if (r.error) {
        st.err = r.error;
        paintCaption();
        return;
      }
      commit(r);
      paintTable();
    };
    clear(tableBox).append(
      el("div", { class: "re-cols" },
        el("table", {},
          el("thead", {}, el("tr", {}, th("기본 범위"), th("최솟값"), th("최댓값"))),
          el("tbody", {}, range("mach", "마하"), range("alt", "고도", "m"), range("fuel", "연료", "kg"))),
        el("table", {},
          el("thead", {}, el("tr", {}, th("기본 격자", "요구영역의 기본 격자 명세 — 공통 마하 좌표 점 수 · 고도 목록 · 연료 목록"),
            th(""))),
          el("tbody", {},
            el("tr", {}, el("td", {}, "마하 점 수"), el("td", {}, cellInput("/base_grid/n_mach", w.base_grid.n_mach))),
            el("tr", {}, el("td", {}, "고도 [m]"),
              el("td", {}, cellInput("/base_grid/alts", w.base_grid.alts, { cls: "", list: true }))),
            el("tr", {}, el("td", {}, "연료 [kg]"),
              el("td", {}, cellInput("/base_grid/fuels", w.base_grid.fuels, { cls: "", list: true })))))),
      el("table", {},
        el("thead", {}, el("tr", {},
          th(`경계표 — 연료 ${num(st.fuel)} kg`, w.boundary ? SCOPE_TIP[st.scope]
            : "경계표 없음 — 기본 마하 범위가 모든 행입니다. 칸을 고치면 연료 양끝 × 고도 양끝 행으로 경계표를 세웁니다"),
          th("마하 하한"), th("마하 상한"), th(""))),
        el("tbody", {},
          rows.map((r) => {
            const cells = [cellInput(r.paths[0], r.alt), cellInput(r.paths[1], r.lo), cellInput(r.paths[2], r.hi)];
            rowInputs.push({ alt: cells[0], cells });
            return el("tr", { class: r.virtual ? "re-virtual" : "" }, ...cells.map((c) => el("td", {}, c)),
              el("td", {}, r.virtual ? null : ctl(el("button", {
                type: "button", class: "danger", title: `이 고도 행을 지웁니다 (${SCOPE_LABEL[st.scope]})`,
                // 화면 행의 고도는 그 칸의 글 — 타자 중 재정렬돼도 이 행을 지운다
                onclick: () => run(removeRow(st.work, { fuel: st.fuel, alt: Number(cells[0].value), scope: st.scope })),
              }, "삭제"))));
          }),
          isLayerFuel(w, st.fuel) ? null : el("tr", {}, el("td", { colspan: "4", class: "hint" },
            `연료 ${num(st.fuel)} kg는 경계표 층이 아니다 — 층 사이 선형 보간이라 고칠 행이 없다(층 연료 칩에서 고친다)`)),
          !isLayerFuel(w, st.fuel) ? null : el("tr", {}, ...add.map((i) => el("td", {}, i)),
            el("td", {}, ctl(el("button", {
              type: "button", title: `새 고도 행 (${SCOPE_LABEL[st.scope]}) — 이미 있는 고도면 넣지 않습니다`,
              onclick: () => run(addRow(st.work, { fuel: st.fuel, row: add.map((i) => i.value), scope: st.scope,
                outline: outline() })),
            }, "행 추가")))))),
    );
    paintMarks();
    const back = inputOf(keep);
    focusId = keep;
    if (back) back.focus(preventFocusScroll ? { preventScroll: true } : undefined);
  }

  function paintLineage() {
    lineage.open = st.lineageOpen;
    const p = st.preview;
    const w = st.work;
    const kids = [];
    if (p?.region) {
      kids.push(el("p", { class: "hint" },
        `기본 격자 — 출처 ${p.region.source === "profile" ? "기체 문서 operating_region"
          : p.region.source === "draft:trim_grid" ? "초안 — 기체 문서(기본 형상)의 trim_grid" : `초안 (${p.region.source})`} · `
        + `규칙 공통 마하 좌표 ${w?.base_grid?.n_mach ?? "—"}점 + 행 끝점 · 판 ${p.region_key ?? "—"}`
        + (dirty() ? " (저장 전 편집의 판)" : "")));
    }
    if (st.historyError) kids.push(el("p", { class: "hint" }, `⚠ ${st.historyError}`));
    if (st.historyOmitted > 0) kids.push(el("p", { class: "hint" }, `이전 리비전 ${st.historyOmitted}개 생략 — 최신 리비전만 봅니다`));
    const savedKey = st.history?.length ? [...st.history].sort((a, b) => b.revision - a.revision)[0].region_key : null;
    const rows = lineageRows(st.history, { region_key: savedKey });
    if (rows.length) {
      kids.push(el("div", { class: "scroll-x" }, el("table", {},
        el("thead", {}, el("tr", {}, el("th", {}, "리비전"), el("th", {}, "판"), el("th", {}, "상태"), el("th", {}, "출처"),
          el("th", {}, "범위"), el("th", {}, "점"), el("th", {}, ""))),
        el("tbody", {}, rows.flatMap((r) => [
          el("tr", { class: r.current ? "selected" : "" },
            el("td", { class: "num" }, `리비전 ${r.revision}`), el("td", {}, el("code", {}, r.key ?? "—")),
            el("td", {}, r.state), el("td", {}, r.source), el("td", {}, r.range),
            el("td", { class: "num" }, r.points ?? "—"),
            el("td", {}, r.key == null ? null : el("button", { type: "button",
              title: "그 리비전의 요구영역 값을 읽기 전용으로 봅니다", onclick: () => showSource(r.revision) }, "출처 보기"))),
          st.source?.revision === r.revision ? el("tr", {}, el("td", { colspan: "7" }, sourceView(st.source))) : null,
        ].filter(Boolean))))));
    }
    const consumers = p?.impact?.stale ?? [];
    if (consumers.length) {
      kids.push(el("p", { class: "hint", style: "margin:6px 0 2px" }, "이 요구영역을 쓰면 —"),
        el("ul", { class: "hint" }, consumers.map((s) => el("li", {}, s.label ?? `${s.what}: ${s.status}`))));
    }
    clear(lineageBox).append(...kids);
  }

  async function showSource(revision) {
    const id = st.id;
    const mine = { revision, section: null, error: null, loading: true };
    st.source = mine;
    paintLineage();
    let next;
    try {
      const b = await api.get(`/profiles/${encodeURIComponent(id)}?revision=${revision}`);
      next = { revision, section: b.document?.operating_region ?? null, error: null, loading: false };
    } catch (e) {
      next = { revision, section: null, error: errorText(e), loading: false };
    }
    // 그사이 다른 [출처 보기]를 눌렀거나 기체가 바뀌었다 — 늦게 온 옛 답이 새 것을 덮지 않게
    if (st.source !== mine || st.id !== id) return;
    st.source = next;
    paintLineage();
  }

  function sourceView(src) {
    if (src.loading) return el("span", { class: "hint" }, "받는 중…");
    if (src.error) return el("span", { class: "hint" }, `⚠ ${src.error}`);
    const s = src.section;
    if (!s) return el("span", { class: "hint" }, "이 리비전의 문서엔 operating_region 절이 없다(trim_grid 초안)");
    const span = (v) => `${num(v[0])}–${num(v[1])}`;
    return el("div", { class: "hint" },
      el("div", {}, `마하 ${span(s.mach)} · 고도 ${span(s.alt)} m · 연료 ${span(s.fuel)} kg · 기본 격자 마하 `
        + `${s.base_grid?.n_mach}점 · 고도 ${(s.base_grid?.alts ?? []).join(", ")} · 연료 ${(s.base_grid?.fuels ?? []).join(", ")}`),
      ...(s.boundary ?? []).map((l) => el("div", {},
        `연료 ${num(l.fuel)} kg — ${l.rows.map((r) => `${num(r[0])} m: ${num(r[1])}–${num(r[2])}`).join(" · ")}`)));
  }

  paintToggle();
  if (st.editing) view.repaint();
  return view;
}
