/** 게인 스케줄 뷰 (02 §8 4단계) — 스케줄 자리 선택 → 셀 편집 → 시뮬 주입 준비.

두 층이다. **자리 선택**(어떤 게인에 테이블을 붙이나)은 형상을 바꾸고 — 켠 자리는
탑재 C에 룩업이 생기고 뺀 자리는 설계점 상수로 접힌다 — **값 편집**은 그 안에서
게인을 바꾼다. 그래서 화면도 위(자리 격자)·아래(켠 것만 표·차트)로 나눈다.

주입은 전체 교체 (엔진 make_demo_fcl 계약)이고 **키 집합이 곧 선택**이다.
편집본은 store("gainTables")로 시뮬레이션 탭에 전달하며, 전부 끈 경우만 빈 dict로
표현할 수 없어(서버가 422) store("gainScheduleOff")를 함께 쓴다 — 판단은
lib/gainsched.js. 검증(그룹·키·형상·유한성)은 제출 시 서버/엔진이 수행.

**끈 자리의 상수도 여기서 고친다.** 그 값은 구조도 폼과 같은 스토어
(scasParams·autopilotParams)에 살고, 어느 쪽에서 고쳐도 다른 쪽에 그대로 보여야
한다 — 같은 게인이 화면마다 다르면 "지금 형상"이라는 말이 성립하지 않는다.
켜고 끌 때도 값이 이어진다: 켜면 그 상수에서 출발하는 표가 서고, 끄면 그 표의
설계점 값으로 굳는다 (lib/gainsync.js — 스케일 규칙은 서버 제안 표에서 온다).
*/

import { api, errorText } from "../api.js";
import { clear, el, fmt } from "../dom.js";
import {
  GAIN_KEYS, alignTables, appliedTables, defaultSelection, schedSummary, slotRows,
  storePayload, toggleSlot, zeroTables,
} from "../lib/gainsched.js";
import {
  constantOf, designCoord, foldToConstant, seedTable, selectedSlots, slotIndex,
  withConstant,
} from "../lib/gainsync.js";
import { gainPlotGroups } from "../lib/plot.js";
import { piecewisePolyfit, rawCoeffs, sampleFit } from "../lib/polyfit.js";
import { store } from "../store.js";
import { lineChartCanvas } from "./plots.js";

let catalog = null; // GET /gains/catalog — 자리 목록·설계 상수·제안 테이블
let selected = []; // 켠 자리 이름 (카탈로그 기본 = 서버가 지금 스케줄하는 6자리)
let tables = null; // 켠 자리만 추린 {name: {axes:{mach}, data, extrapolate}} — 편집 대상
let adopted = null; // 되읽은 형상 요약 {source, slots, aligned, points, unknown} | null
// 이 탭이 마지막으로 보거나 적용한 스토어 값 — **밖에서 바뀌었는지**만 판정한다.
// 매 재진입마다 되읽으면 미적용 편집 드래프트가 날아가고, 아예 안 읽으면 자동
// 설계가 확정한 형상이 이 화면에만 안 보인다
let seenTables;
let seenOff;
// 끈 자리의 상수 드래프트 {scas, autopilot} — 구조도 폼과 같은 스토어를 쓰는 값이라
// 테이블과 함께 '적용'에서 커밋한다 (여기만 즉시 반영되면 적용 전후가 갈린다)
let constants = null;

// 근사 곡선 설정 — 탭 이탈·재로드에도 유지 (경계 "0.3"은 데모 동압 스케일의
// 상한 클립 경계와 일치하는 시연 기본값, 검증은 piecewisePolyfit이 수행)
const fitCfg = { show: true, degree: 3, boundaries: "0.3", detailsOpen: false };

export function render() {
  const box = el("div");
  const errBox = el("div");
  const statusLine = el("p", { class: "hint" });

  // 드래프트는 **탭에 들어올 때마다** 스토어에서 다시 뜬다. 모듈 스코프 상태는
  // 탭을 나가도 살아 있는데(뷰는 pull 방식이고 store.subscribe를 쓰지 않는다),
  // 그 사이 구조도에서 고친 값을 안 읽으면 여기서 '적용'하는 순간 옛 드래프트가
  // 그 편집을 조용히 되돌린다 — 없애려던 이중 정본이 드래프트 층에서 되살아난다
  const syncFromStore = () => {
    constants = {
      scas: store.get("scasParams") ?? null,
      autopilot: store.get("autopilotParams") ?? null,
    };
  };

  const load = async ({ fresh = false } = {}) => {
    try {
      clear(errBox);
      catalog = await api.get("/gains/catalog");
      // 설계점 **좌표**를 제안 표 기준으로 굳힌다 — 되읽기가 slot.table을 확정본으로
      // 갈아끼운 뒤에도 기준이 흔들리지 않게 (lib/gainsync designCoord)
      catalog.design_coord = designCoord(catalog);
      selected = defaultSelection(catalog);
      adopted = fresh ? null : adoptStored();
      if (fresh) markSeen();
      syncFromStore();
      renderTables(box, statusLine);
      statusLine.textContent = fresh
        ? "서버 설계 제안으로 되돌렸습니다 (미적용) — '시뮬·코드에 적용'을 눌러야 형상이 바뀝니다."
        : adoptedText(adopted);
    } catch (e) {
      clear(errBox).append(el("div", { class: "error-box" }, errorText(e)));
    }
  };

  const apply = () => {
    if (!catalog) return;
    const { tables: applied, scheduleOff } = storePayload(catalog, selected);
    const payload = applied && JSON.parse(JSON.stringify(applied));
    store.set("gainTables", payload);
    store.set("gainScheduleOff", scheduleOff);
    store.set("gainTablesSource", { kind: "gains" });
    markSeen();
    adopted = null; // 이제 이 화면이 곧 적용된 형상이다 — 되읽기 배너를 내린다
    // 끈 자리의 상수 — 구조도 폼이 읽는 바로 그 스토어. 여기서 고친 값이 저기 보인다
    if (constants?.scas) store.set("scasParams", constants.scas);
    if (constants?.autopilot) store.set("autopilotParams", constants.autopilot);
    statusLine.textContent = scheduleOff
      // 시뮬 탭은 아직 이 신호를 안 읽는다 — 조용히 다른 형상을 돌리지 않도록 명시한다
      ? "스케줄 없는 형상으로 적용됨 — Autocode 탑재코드에 반영됩니다. "
        + "시뮬레이션 탭은 아직 이 상태를 못 받아 설계 기본으로 돕니다."
      : `적용됨 (${schedSummary(catalog, selected)}) — 시뮬레이션 탭에서 `
        + "'편집 게인 사용'을 켜면 주입되고, Autocode 탑재코드에 바로 반영됩니다.";
  };

  const root = el("div", {},
    el("div", { class: "panel" },
      el("h2", {}, "게인 스케줄 (동압 스케일 1D mach — 설계점 M0.6)"),
      el("p", { class: "hint" },
        "신호흐름 구조는 구조도 탭 — SCAS·게인 스케줄 블록에서 여기로 진입한다. ",
        "스케줄 대상은 형상의 일부다 — 바꾸면 탑재 코드 구조와 형상 지문이 함께 바뀐다."),
      el("div", { class: "row" },
        el("button", {
          onclick: () => load({ fresh: true }),
          title: "적용해 둔 형상을 버리고 서버 설계 제안(동압 스케일)으로 되돌린다",
        }, "설계값 다시 불러오기"),
        el("button", { class: "primary", onclick: apply }, "시뮬·코드에 적용"),
      ),
      statusLine, errBox,
    ),
    el("div", { class: "panel" }, box),
  );

  if (catalog) {
    // 재진입 — 카탈로그는 캐시지만 상수도, **적용된 형상도** 그 사이 바뀌었을 수 있다
    // (자동 설계 탭의 '게인 확정'이 그 경로다). 밖에서 바뀐 경우에만 되읽어
    // 미적용 편집 드래프트를 지키면서 확정본을 놓치지 않는다
    if (storeChanged()) {
      selected = defaultSelection(catalog);
      adopted = adoptStored();
      statusLine.textContent = adoptedText(adopted);
    }
    syncFromStore();
    renderTables(box, statusLine);
  } else {
    load();
  }
  return root;
}

/** "M0.6" — 설계점 표기. 좌표는 로드 시점에 굳혀 둔 값(lib/gainsync designCoord). */
function axisLabel() {
  const at = designCoord(catalog);
  return at == null ? "설계점" : `${String(catalog?.axis).toUpperCase()[0]}${at}`;
}

/** 이 탭이 마지막으로 보거나 적용한 스토어 값으로 표시 — 이후 변경 감지의 기준. */
function markSeen() {
  seenTables = store.get("gainTables");
  seenOff = store.get("gainScheduleOff") === true;
}

function storeChanged() {
  return store.get("gainTables") !== seenTables
    || (store.get("gainScheduleOff") === true) !== seenOff;
}

/** 적용해 둔 형상(스토어)을 편집 상태로 **되읽는다** — 자동 설계 확정본 포함.
 *
 * 이 탭은 지금까지 스토어에 쓰기만 했다: 자동 설계가 확정한 스케줄이 시뮬·Autocode
 * ·구조도에는 걸려 있는데 정작 게인 화면만 서버 제안을 보여 줬다. 적용된 형상과
 * 보이는 형상이 다르면 "지금 형상"이라는 말이 성립하지 않는다.
 *
 * 확정본은 자리마다 breakpoint가 다르므로(적합이 자리별 독립) 합집합 축으로 정렬해
 * 한 표에 담는다 — 조회 함수는 보존된다(lib/gainsched alignTables).
 * 반환 null = 아직 아무것도 적용한 적 없음(서버 기본 형상이 그대로 돈다). */
function adoptStored() {
  const stored = store.get("gainTables");
  const off = store.get("gainScheduleOff") === true;
  markSeen();
  if (!stored && !off) return null;
  const source = store.get("gainTablesSource") ?? null;
  selected = selectedSlots(catalog, stored, off);
  if (!stored) return { source, slots: 0, unknown: [], aligned: false };

  const idx = slotIndex(catalog);
  const unknown = Object.keys(stored).filter((n) => !idx.has(n));
  const known = {};
  for (const [name, t] of Object.entries(stored)) {
    if (idx.has(name)) known[name] = t;
  }
  const al = alignTables(known, catalog.axis);
  if (!al) {
    selected = defaultSelection(catalog);
    return { source, error: `축 '${catalog.axis}'가 없는 표가 있어 되읽지 못했다`, unknown };
  }
  // 스토어 객체를 그대로 심으면 셀 편집이 '적용' 전에 다른 탭으로 새어 나간다
  for (const [name, t] of Object.entries(al.tables)) {
    idx.get(name).table = JSON.parse(JSON.stringify(t));
  }
  selected = Object.keys(al.tables);
  return {
    source, unknown, aligned: al.aligned,
    points: al.axis.length, slots: selected.length,
  };
}

function adoptedText(a) {
  if (!a) return "";
  const src = a.source?.kind === "autodesign"
    ? `자동 설계 확정본${a.source.resultId ? ` (${a.source.resultId})` : ""}`
    : "적용해 둔 형상";
  if (a.error) return `${src}을 되읽지 못했습니다 — ${a.error}. 서버 제안을 표시합니다.`;
  if (!a.slots) return `${src} — 스케줄 없는 형상이 적용돼 있습니다 (전 자리 설계점 고정).`;
  let out = `${src}을 되읽었습니다 — ${a.slots}자리`;
  if (a.aligned) {
    out += ` · 자리마다 다른 breakpoint를 합집합 ${a.points}점으로 정렬해 표시`
      + " (구간 선형 보간 결과는 그대로)";
  }
  if (a.unknown.length) out += ` · 이 카탈로그에 없는 자리는 제외: ${a.unknown.join(", ")}`;
  return `${out}. 편집 후 '시뮬·코드에 적용'을 눌러야 반영됩니다.`;
}

/** 스케줄 자리 격자 — 켜고/끄기 + **끈 자리의 상수 편집**.
 *
 * 끈 자리의 숫자는 표시가 아니라 값이다 — 구조도 폼과 같은 스토어에 살고, 여기서
 * 고치면 저기 보인다. 켠 자리는 아래 표가 정본이라 설계점 값만 읽기로 보여 준다
 * (여기서도 고칠 수 있으면 한 게인에 편집처가 둘이 된다).
 * 불가 자리는 빈칸이 아니라 사유를 단 "—"다 (빈칸은 버그로 읽힌다). */
function slotGrid(box, statusLine) {
  const rows = slotRows(catalog);
  const zeros = zeroTables(catalog, selected);
  const draft = "스케줄 대상 변경됨 (미적용) — '시뮬·코드에 적용'을 누르세요.";

  const cell = (slot) => {
    if (!slot) return el("span", { class: "hint" }, "—");
    if (!slot.available) {
      return el("span", { class: "hint", title: slot.reason }, "— 불가");
    }
    const on = selected.includes(slot.name);
    // 켠 자리의 값은 표의 설계점, 끈 자리의 값은 스토어 상수 — 정본이 다르다
    const cur = on ? foldToConstant(catalog, slot, tables) : constantOf(slot, constants);
    const toggle = el("input", {
      type: "checkbox", checked: on,
      onchange: () => {
        if (on) {
          // 끄기 — 편집한 표의 설계점 값으로 굳는다 (옛 설계 상수로 되돌리지 않는다)
          constants = withConstant(catalog, slot, foldToConstant(catalog, slot, tables), constants);
        } else {
          // 켜기 — 지금 상수에서 출발하는 표를 심는다 (설계점에서는 상수 그대로).
          // 상수는 여기서 다시 읽는다 — 렌더 때 잡아 둔 값은 방금 친 입력을 모른다
          slot.table = seedTable(catalog, slot, constantOf(slot, constants));
        }
        selected = toggleSlot(catalog, selected, slot.name);
        renderTables(box, statusLine);
        statusLine.textContent = draft;
      },
    });
    const title = `${slot.param} = ${fmt(cur, 6)} ${slot.unit ?? ""} · ${slot.desc ?? ""}`;
    if (on) {
      return el("label", { title: `${title}\n켠 자리 — 표가 정본. 끄면 표의 설계점 값으로 굳는다` },
        toggle, el("span", { class: "hint" }, ` ${fmt(cur, 3)} ▸표`));
    }
    return el("label", { title: `${title}\n끈 자리 — 이 상수가 값이다 (구조도 폼과 같은 값)` },
      toggle,
      el("input", {
        class: "num-sm", type: "text", value: String(cur),
        onchange: (ev) => {
          // 빈 값은 Number("")===0으로 통과한다 — 비우고 나가면 그 게인이 조용히
          // 0이 된다. 아래 표 셀 핸들러가 같은 함정을 막고 있는 그 가드다 (리뷰 S2)
          const raw = ev.target.value.trim();
          const v = Number(raw);
          if (raw === "" || !Number.isFinite(v)) {
            ev.target.value = String(constantOf(slot, constants));
            statusLine.textContent = `잘못된 수치 — ${slot.name} 원복됨.`;
            return;
          }
          constants = withConstant(catalog, slot, v, constants);
          statusLine.textContent = draft; // 재그리기 없음 — 입력 포커스를 잃지 않는다
        },
      }));
  };
  return el("div", {},
    el("div", { class: "scroll-x" },
      el("table", {},
        el("thead", {}, el("tr", {},
          el("th", {}, "스케줄 대상 \\ 게인"),
          GAIN_KEYS.map((k) => el("th", {}, k)))),
        el("tbody", {}, rows.map((r) => el("tr", {},
          el("td", {}, `${r.label} (${r.group})`),
          r.cells.map((c) => el("td", {}, cell(c))),
        ))))),
    el("p", { class: "hint" },
      `${schedSummary(catalog, selected)}. 칸의 수치는 설계점(${axisLabel()}) 값이다 — `,
      "끈 자리는 입력칸이고 그 값이 곧 상수다 — 구조도 폼과 같은 값이다. ",
      "켠 자리는 아래 표가 정본이라 읽기 전용 — 끄면 표의 설계점 값으로 굳고 ",
      "탑재 코드에서 룩업이 사라진다. 속도·헤딩의 k_rate는 그 축에 rate 입력이 없어 구조상 불가."),
    zeros.length
      ? el("p", { class: "hint" },
          `설계값이 0이라 표가 전부 0인 자리: ${zeros.join(" · ")} — 셀을 편집하기 전엔 `
          + "스케줄해도 거동이 같다 (구조만 바뀐다).")
      : null,
  );
}

/** 전 게인 구간별 회귀 — 실패 시 {error} (첫 실패에서 중단, 조건은 전 게인 공통). */
function computeFits(groups) {
  const items = fitCfg.boundaries.split(",").map((s) => s.trim()).filter((s) => s !== "");
  const values = items.map(Number);
  const bad = items.filter((_, i) => !Number.isFinite(values[i]));
  if (bad.length) return { error: `경계 형식 오류: ${bad.join(", ")}` };
  const overlays = new Map(); // group → 점선 시리즈 목록
  const rows = []; // {name, pw} — 근사식·잔차 표
  for (const g of groups) {
    const list = [];
    for (const s of g.series) {
      const pw = piecewisePolyfit(g.mach, s.data, values, fitCfg.degree);
      if (pw.error) return { error: pw.error };
      const sm = sampleFit(pw);
      list.push({ label: "", data: sm.y, x: sm.x, color: s.color, dash: [5, 4], markers: false });
      rows.push({ name: `${g.group}.${s.label}`, pw });
    }
    overlays.set(g.group, list);
  }
  return { overlays, rows };
}

const SUP = ["", "", "²", "³", "⁴", "⁵", "⁶"];

function formulaText(fit) {
  let out = "";
  rawCoeffs(fit).forEach((v, k) => {
    const term = k === 0 ? fmt(Math.abs(v), 4) : `${fmt(Math.abs(v), 4)}·M${SUP[k]}`;
    if (k === 0) out = (v < 0 ? "−" : "") + term;
    else out += ` ${v < 0 ? "−" : "+"} ${term}`;
  });
  return out;
}

function fitDetails(rows) {
  return el("details", {
    open: fitCfg.detailsOpen,
    ontoggle: (ev) => { fitCfg.detailsOpen = ev.target.open; }, // 재그리기에도 접힘 유지
  },
    el("summary", {}, "근사식 계수·잔차·경계 연속성"),
    el("div", { class: "scroll-x" },
      el("table", { class: "fit-table" },
        el("thead", {}, el("tr", {},
          ["게인", "구간별 근사식 p(M)", "최대|잔차|", "RMS", "경계 점프 (값 / 기울기)"]
            .map((h) => el("th", {}, h)))),
        el("tbody", {}, rows.map(({ name, pw }) => el("tr", {},
          el("td", {}, name),
          el("td", { class: "col-lines" }, pw.segments.map((s) =>
            el("div", {}, `[M${fmt(s.x0, 3)}–M${fmt(s.x1, 3)}]  ${formulaText(s.fit)}`))),
          el("td", { class: "num" }, fmt(pw.maxResidual, 3)),
          el("td", { class: "num" }, fmt(pw.rms, 3)),
          el("td", { class: "col-lines" }, pw.joints.length
            ? pw.joints.map((j) => el("div", {},
                `M${fmt(j.x, 3)}: ${fmt(j.valueJump, 3)} / ${fmt(j.slopeJump, 3)}`))
            : "—"),
        ))))),
    el("p", { class: "hint" },
      "근사식은 검토·반출용 표시 — 시뮬 조회는 여전히 테이블 구간 선형 보간 (실주입은 백로그). ",
      "경계 점프 = 경계 마하에서 우측 구간식 − 좌측 구간식 (값·기울기). 허용치 판정은 설계자 소관 (01 §3.4)."));
}

function drawCharts(chartBox, fitStatus) {
  const { groups, skipped } = gainPlotGroups(tables);
  let overlays = null;
  let fitRows = [];
  fitStatus.textContent = "";
  if (fitCfg.show) {
    const r = computeFits(groups);
    if (r.error) fitStatus.textContent = `근사 불가: ${r.error}`;
    else { overlays = r.overlays; fitRows = r.rows; }
  }
  // 네이티브 append에 null·배열 직접 전달 금지 (문자열화 함정) — el 래핑으로 조립
  clear(chartBox).append(el("div", {},
    el("div", { class: "row" },
      groups.map(({ group, mach, series }) =>
        lineChartCanvas(mach, overlays ? [...series, ...overlays.get(group)] : series, {
          title: `${group} 게인`, width: 420, height: 200, xUnit: "M", markers: true,
        }))),
    el("p", { class: "hint" },
      "점 = 테이블 격자점(브레이크포인트), 실선 = 현재 조회 규칙(구간 선형 보간, 외삽 clip), ",
      "점선 = 구간별 다항식 회귀 근사 곡선(위 경계·차수 설정). 셀 편집 시 즉시 갱신."),
    skipped.length
      ? el("p", { class: "hint" },
          `차트 제외: ${skipped.map((s) => `${s.name} — ${s.reason}`).join(" · ")}`)
      : null,
    fitRows.length ? fitDetails(fitRows) : null,
  ));
}

function renderTables(box, statusLine) {
  // 편집 대상은 **켠 자리만**. 카탈로그의 표를 참조로 들고 있어 셀 편집이 그대로
  // 남는다 — 자리를 껐다 켜도 고쳐 둔 값이 살아 있어야 비교가 성립한다
  tables = appliedTables(catalog, selected);
  // **표를 그리기 직전에 축을 맞춘다.** 이 표는 행=축 격자·열=자리인데 격자를
  // 첫 열에서만 읽는다 — 자리마다 축이 다르면(확정본을 되읽은 뒤 다른 자리를 새로
  // 켜면 서버 제안 격자가 섞여 든다) 셀 편집이 **다른 비행조건 칸에 기록되고**
  // 짧은 열은 화면 밖으로 사라진다. 되읽기에서만 맞추면 그 이후 토글이 어긋난다
  const aligned = alignTables(tables, catalog.axis);
  if (aligned === null) {
    clear(box).append(slotGrid(box, statusLine),
      el("p", { class: "error-box" },
        `축 '${catalog.axis}'가 없는 표가 섞여 있어 편집 표를 세울 수 없습니다.`));
    return;
  }
  if (aligned.aligned) {
    // 정렬본을 카탈로그에 되심어 편집 경로(slot.table 참조 공유)를 잇는다
    const idx = slotIndex(catalog);
    for (const [name, t] of Object.entries(aligned.tables)) idx.get(name).table = t;
    tables = appliedTables(catalog, selected);
  }
  const grid = slotGrid(box, statusLine);
  const names = Object.keys(tables);
  if (names.length === 0) {
    clear(box).append(grid,
      el("p", { class: "hint" },
        "스케줄된 자리가 없습니다 — 전 게인이 설계점 상수로 고정된 형상입니다. ",
        "탑재 코드에서 게인 스케줄 서브시스템(fcl_sched.c)이 통째로 사라집니다."));
    return;
  }
  const machs = tables[names[0]].axes[catalog.axis];
  const chartBox = el("div");
  const fitStatus = el("span", { class: "hint" });
  const redraw = () => drawCharts(chartBox, fitStatus);
  // 컨트롤은 redraw 대상 밖 — 입력 도중 재그리기로 포커스를 잃지 않게
  const fitControls = el("div", { class: "row" },
    el("label", {},
      el("input", {
        type: "checkbox", checked: fitCfg.show,
        onchange: (ev) => { fitCfg.show = ev.target.checked; redraw(); },
      }),
      " 근사 곡선(점선) 표시"),
    el("label", {}, "구간 경계 (마하, 쉼표 구분) ",
      el("input", {
        class: "num-sm", type: "text", value: fitCfg.boundaries,
        onchange: (ev) => { fitCfg.boundaries = ev.target.value; redraw(); },
      })),
    el("label", {}, "차수 ",
      el("input", {
        class: "num-sm", type: "number", min: "1", max: "6", step: "1",
        value: String(fitCfg.degree),
        onchange: (ev) => { fitCfg.degree = Number(ev.target.value); redraw(); },
      })),
    fitStatus,
  );
  redraw();
  // 전치 배열: 행 = 마하(비행조건), 열 = 게인 6개 — 폭이 패널에 들어오고
  // 한 비행조건의 게인 세트를 한 줄에서 편집
  clear(box).append(
    grid,
    fitControls,
    chartBox,
    el("div", { class: "scroll-x" },
      el("table", {},
        el("thead", {}, el("tr", {},
          el("th", {}, "마하 \\ 게인"),
          names.map((name) => el("th", {}, name)))),
        el("tbody", {}, machs.map((m, i) => el("tr", {},
          el("td", {}, `M${m}`),
          names.map((name) => el("td", {},
            el("input", {
              class: "num-sm",
              type: "number",
              step: "any",
              value: String(tables[name].data[i]),
              onchange: (ev) => {
                // badInput(오타)이면 value가 ""가 되어 Number("")===0으로 제로
                // 게인이 조용히 주입됨 — 원복 + 경고 (리뷰 S2)
                const raw = ev.target.value.trim();
                const num = Number(raw);
                if (raw === "" || ev.target.validity.badInput || !Number.isFinite(num)) {
                  ev.target.value = String(tables[name].data[i]);
                  statusLine.textContent = `잘못된 수치 — M${m} ${name} 원복됨.`;
                  return;
                }
                tables[name].data[i] = num;
                redraw(); // 편집값 즉시 반영 (data 참조 공유) — 근사 곡선 포함
                statusLine.textContent = "편집됨 (미적용) — '시뮬·코드에 적용'을 누르세요.";
              },
            }))),
        ))),
      ),
    ),
    el("p", { class: "hint" },
      "열 = 위에서 켠 자리 (\"그룹.게인\" = 스텝 게인 덮어쓰기 인자), 행 = 스케줄 변수 마하. ",
      "외삽 clip 고정 — 그룹·키·형상 검증은 제출 시 엔진이 수행."),
  );
}
