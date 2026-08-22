/** 영향성 탭 — 파라미터 하나가 전체 시스템에 어떻게 번지는지 (02 §2.4, M15).

이 화면의 주 질문은 "이 값을 바꾸면 무엇이 얼마나 달라지나"이고, 답을 세 단으로 낸다:
구조 도달성(즉시) · 개루프 Δ(초) · 폐루프 스윕(작업). 지금은 1단이 붙어 있다.

**표가 정본 표면이고 캔버스는 보조다.** 캔버스는 보조기술에 불투명하므로, 화면이
말하는 모든 사실(상태·도달 개수·도달 출력)은 아래 표에도 반드시 있다 — wpmap.js가
웨이포인트 표에 접근성을 맡긴 것과 같은 규약.

스타일은 인라인이다: app.css는 병행 세션 작업 중이라 건드리지 않는다.
*/

import { api, errorText } from "../api.js";
import { clear, el } from "../dom.js";
import {
  BAND_COLOR, SKIN, STATE_COLOR, STATE_INK, STATE_LABEL, STATE_NOTE, WARN_INK,
  coneOf, normalizeGraph, radiusOf, structuralRequest,
} from "../lib/influence.js";
import { cascadeLayout, layeredLayout, radialLayout } from "../lib/influencelayout.js";
import { createInfluenceCanvas } from "./influencecanvas.js";
import { store } from "../store.js";

const CANVAS_W = 1180;
const CANVAS_H = 660;
const ROW_GAP = 19;

// 뷰 재생성마다 처음으로 돌아가지 않도록 모듈 스코프 (autocode.js·sim.js와 같은 패턴)
const state = { variant: "layered", selection: null, model: null, layout: null };
let canvas = null;

const VARIANTS = [
  ["layered", "A · 레이어 활성망",
   "좌→우 16층 — 층 번호가 곧 IR 실행 순서이자 생성 C의 문장 순서다. 경로 추적이 쉽다"],
  ["radial", "B · 영향 성운",
   "동심원 4겹 + 묶음 허브로 다발 묶기 — 바깥이 파라미터, 중심이 지표. 얽힘의 규모가 한눈에"],
  ["cascade", "C · 전파 폭포",
   "16층을 모듈 밴드로 접어 굵은 흐름으로 — 어느 모듈을 지나는지가 덩어리로 읽힌다"],
];
const LAYOUT_FN = { layered: layeredLayout, radial: radialLayout, cascade: cascadeLayout };

export function render() {
  // 탭을 떠났다 돌아오면 이전 DOM은 버려진다 — 그쪽을 밀던 타이머도 같이 정리
  if (canvas) {
    canvas.dispose();
    canvas = null;
  }

  const errBox = el("div");
  const statusLine = el("span", { class: "hint" }, "형상 그래프를 불러오는 중…");
  const warnBox = el("div");
  const legendBox = el("div");
  const variantNote = el("div", { style: "margin-top:4px" });
  const tableBox = el("div");
  const detailBox = el("div");
  const canvasBox = el("div", {
    style: "position:relative;border-radius:16px;overflow:hidden;background:#000",
  });

  const variantRow = el("div", { class: "row", style: "gap:6px" });
  function renderVariants() {
    clear(variantRow).append(...VARIANTS.map(([key, label, note]) =>
      el("button", {
        class: key === state.variant ? "primary" : "",
        title: note,
        "aria-pressed": key === state.variant ? "true" : "false",
        onclick: () => {
          state.variant = key;
          renderVariants();  // 눌린 버튼이 안 바뀌면 지금 무엇을 보고 있는지 알 수 없다
          rebuild();
        },
      }, label)));
  }
  renderVariants();

  function rebuild() {
    if (!state.model) return;
    const graph = { nodes: state.model.nodes, edges: state.model.edges };
    const opts = {
      width: CANVAS_W, paramCols: 3, rowGap: ROW_GAP, colGap: 62,
      pad: 26, padRight: 168,  // 오른쪽은 지표 라벨 자리 (넘치면 캔버스가 왼쪽으로 뒤집는다)
      radiusOf: (n) => radiusOf(n, { maxReach: state.model.graph.n_nodes }),
      // 묶음·IR 그룹 이름은 서버가 준 것을 그대로 넘긴다 (배치가 베껴 두지 않게)
      groups: state.model.graph.groups ?? [],
      bandOrder: Object.keys(state.model.bands ?? {}),
    };
    // 두 번 돈다: 첫 배치로 **가장 높은 열이 몇 행인지** 알아낸 뒤 캔버스 높이를 거기
    // 맞춘다. 고정 높이로 두면 파라미터 열(22행)과 IR 층(최대 12행)의 차이만큼
    // 아래가 통째로 비거나 넘친다 — 열 수를 바꾸면 그 슬랙도 같이 변한다
    const fn = LAYOUT_FN[state.variant] ?? layeredLayout;
    const probe = fn(graph, { ...opts, height: CANVAS_H });
    const height = state.variant === "radial"
      ? 760  // 성운은 원반이라 행 수가 아니라 지름이 높이를 정한다
      : Math.max(360, probe.bounds.maxRows * (state.variant === "cascade" ? 18 : ROW_GAP) + 96);
    state.layout = fn(graph, { ...opts, height });
    if (canvas) canvas.setSize(CANVAS_W, height);
    renderTable();
    renderDetail();
    renderVariantNote();
  }

  function select(id) {
    const n = id ? state.model?.byId.get(id) : null;
    // 노드를 눌러도 파라미터가 아니면 선택을 바꾸지 않는다 — 원뿔의 주어는 파라미터다
    state.selection = n?.kind === "param" ? id : id === null ? null : state.selection;
    renderDetail();
    renderTable();
    // 동작 축소 설정에서는 타이머가 아예 없다 — frame()이 선택을 읽는 유일한 자리이므로
    // 여기서 직접 다시 그리지 않으면 캔버스가 "선택 없음"에 영원히 얼어 있고,
    // 표만 바뀐 채 그림은 전체를 밝게 유지해 "이 값이 전부를 건드린다"로 읽힌다
    canvas?.redraw();
  }

  function renderVariantNote() {
    clear(variantNote);
    const [, , note] = VARIANTS.find(([k]) => k === state.variant) ?? [];
    variantNote.append(el("span", { class: "hint" }, note ?? ""));
    if (state.layout?.meta?.conserved === false) {
      // 리본 폭을 유량으로 읽으면 "상류 = 하류 합"이라는 없는 성질을 믿게 된다
      variantNote.append(el("span", {
        style: `margin-left:10px;font-size:12px;color:${WARN_INK}`,
      }, "⚠ 굵기는 보존량이 아니다 — 파라미터 하나가 여러 노드를 흔들고 하류 합은 상류와 같지 않다"));
    }
  }

  function renderDetail() {
    clear(detailBox);
    const m = state.model;
    if (!m) return;
    const sel = state.selection ? m.byId.get(state.selection) : null;
    if (!sel) {
      detailBox.append(el("p", { class: "hint" },
        "왼쪽 파라미터 열에서 하나를 고르면 그 값이 건드리는 노드에서 시작해 " +
        "층을 타고 파급이 번진다. 층 번호는 IR 실행 순서이자 생성 C의 문장 순서다."));
      return;
    }
    const note = STATE_NOTE[sel.state];
    detailBox.append(
      el("div", { class: "row", style: "gap:10px;align-items:center" },
        badge(sel.state),
        el("strong", {}, sel.label),
        el("code", { style: mono() }, sel.param_id),
        el("span", { class: "hint" }, `${fmtNum(sel.value)} ${sel.unit}`),
        el("button", { onclick: () => select(null) }, "선택 해제"),
      ),
      el("p", { class: "hint", style: "margin:6px 0 0" }, sel.desc),
      note ? el("p", { style: `margin:6px 0 0;color:${STATE_INK[sel.state]};font-size:12px` }, note) : el("span"),
      el("div", { class: "row", style: "gap:18px;margin-top:8px;font-size:12px" },
        stat("건드리는 노드", (sel.seeds ?? []).join(", ") || "—"),
        stat("도달 노드", String(sel.n_reach ?? 0)),
        stat("도달 출력", (sel.outputs ?? []).join(", ") || "—"),
        stat("탐침", sel.probe_to == null ? "—"
          : `${fmtNum(sel.value)} → ${fmtNum(sel.probe_to)} (유한 차분, 미분 아님)`),
      ),
      sel.added?.length
        ? el("p", { style: `margin:6px 0 0;color:${WARN_INK};font-size:12px` },
            `이 값을 올리면 생기는 노드: ${sel.added.join(", ")} — 탑재 C도 달라진다`)
        : el("span"),
      el("p", { class: "hint", style: "margin:8px 0 0" },
        "기체 → 지표 구간은 점선이다 — 폐루프가 IR 밖에서 닫히므로 도달은 " +
        "선언이고, 「얼마나」는 폐루프 스윕(3단)에서만 나온다. " +
        "지금 화면은 1단(구조 도달성)이라 굵기는 영향의 크기가 아니다."),
    );
  }

  function renderTable() {
    clear(tableBox);
    const m = state.model;
    if (!m) return;
    const rows = [...m.params].sort((a, b) =>
      (b.n_reach ?? 0) - (a.n_reach ?? 0) || a.param_id.localeCompare(b.param_id));
    tableBox.append(
      el("div", { class: "scroll-x", style: "max-height:340px;overflow-y:auto" },
        el("table", {},
          el("thead", {}, el("tr", {},
            ["파라미터", "묶음", "값", "단위", "상태", "도달 노드", "도달 출력"].map((h) =>
              el("th", {}, h)))),
          el("tbody", {}, rows.map((p) =>
            el("tr", {
              style: `cursor:pointer${p.id === state.selection ? ";background:rgba(10,132,255,.09)" : ""}`,
              onclick: () => select(p.id),
            },
              el("td", {}, el("code", { style: mono() }, p.param_id)),
              el("td", {}, m.bands?.[p.band]?.label ?? p.band),
              el("td", { class: "num" }, fmtNum(p.value)),
              el("td", {}, p.unit),
              el("td", {}, badge(p.state)),
              el("td", { class: "num" }, String(p.n_reach ?? 0)),
              el("td", {}, (p.outputs ?? []).join(", ") || "—"),
            ))),
        )),
      el("p", { class: "hint", style: "margin:6px 0 0" },
        "표가 이 화면의 정본이다 — 캔버스가 말하는 것은 전부 여기에도 있다. " +
        "「도달 노드」는 영향의 크기가 아니라 영향이 있을 수 있는 범위다 — " +
        "포화된 가지나 0 게인을 지나는 경로도 도달로 잡힌다."),
    );
  }

  function renderLegend(m) {
    clear(legendBox);
    // 색은 `.legend` div **자신**에 건다 — 부모(어두운 패널)에 인라인으로 걸어 봐야
    // app.css의 `.legend { color: var(--muted) }`가 이긴다(상속은 캐스케이드에서 가장 약하다).
    // 라이트 테마 muted가 #1c1c1e 위에 그려져 3.4:1로 떨어지던 자리
    const inkStyle = `color:${SKIN.inkDim}`;
    legendBox.append(
      el("div", { class: "legend", style: inkStyle },
        Object.entries(STATE_LABEL).map(([k, label]) =>
          el("span", {},
            el("span", { class: "chip", style: `background:${STATE_COLOR[k]}` }),
            label))),
      el("div", { class: "legend", style: `${inkStyle};margin-top:2px` },
        Object.entries(m.bands ?? {}).map(([k, b]) =>
          el("span", {},
            el("span", { class: "chip", style: `background:${BAND_COLOR[k] ?? SKIN.gray}` }),
            b.label + (b.in_law ? "" : " (법칙 밖)")))),
    );
  }

  async function load() {
    try {
      clear(errBox);
      // 게인 탭이 자리를 전부 끄면 `{gainTables: null, gainScheduleOff: true}`를 쓴다 —
      // 빈 dict로는 "껐다"를 표현할 수 없어서 짝으로 두는 키다(lib/gainsched.js).
      // 이걸 안 읽으면 사용자가 끈 스케줄을 켜진 것으로 해석해, 있지도 않은
      // 「스케줄에 덮임」 경고를 띄우고 지문도 Autocode 탭과 어긋난다
      const body = structuralRequest({
        autopilot: store.get("autopilotParams"),
        nav: store.get("navParams"),
        actuators: store.get("actuatorParams"),
        gainTables: store.get("gainTables"),
        withSchedule: store.get("gainScheduleOff") ? false : undefined,
      });
      const payload = await api.post("/influence/structural", body);
      const m = normalizeGraph(payload);
      state.model = m;
      if (state.selection && !m.byId.has(state.selection)) state.selection = null;
      statusLine.textContent =
        `형상 지문 ${m.fingerprint} · 제어주기 ${m.controlHz} Hz · ` +
        `노드 ${m.nodes.length} · 간선 ${m.edges.length} · ` +
        `파라미터 ${m.params.length} · 서버 ${m.elapsedMs} ms`;
      clear(warnBox);
      for (const w of m.warnings) {
        warnBox.append(el("p", {
          style: `margin:4px 0;font-size:12px;color:${WARN_INK}`,
        }, `⚠ ${w}`));
      }
      renderLegend(m);
      rebuild();
      canvas.redraw();
    } catch (e) {
      statusLine.textContent = "불러오지 못했습니다";
      clear(errBox).append(el("div", { class: "error-box" }, errorText(e)));
    }
  }

  canvas = createInfluenceCanvas({
    width: CANVAS_W,
    height: CANVAS_H,
    getModel: () => state.model,
    getLayout: () => state.layout,
    getSelection: () => state.selection,
    onSelect: select,
  });
  canvasBox.append(canvas.root);

  load();

  return el("div", {},
    el("div", { class: "panel" },
      el("h2", {}, "영향성 — 설계값 연계·정량 영향성 평가 (02 §2.4)"),
      el("div", { class: "row", style: "gap:14px;align-items:center" },
        variantRow,
        el("span", { class: "grow" }),
        el("button", { onclick: load }, "다시 계산"),
      ),
      variantNote,
      el("div", { class: "row", style: "margin-top:6px" }, statusLine),
      warnBox,
      errBox,
    ),
    el("div", {
      class: "panel",
      style: `background:${SKIN.raised};border-color:${SKIN.hairline};border-radius:14px`,
    },
      canvasBox,
      el("div", { style: "margin-top:10px" }, legendBox),
    ),
    el("div", { class: "panel" }, detailBox),
    el("div", { class: "panel" },
      el("h2", {}, "파라미터"),
      tableBox,
    ),
  );
}

function badge(stateKey) {
  return el("span", {
    class: "flag",
    style: `background:${STATE_INK[stateKey]}1a;color:${STATE_INK[stateKey]};` +
      "font-weight:600;white-space:nowrap",
  }, STATE_LABEL[stateKey] ?? stateKey);
}

function stat(label, value) {
  return el("span", {},
    el("span", { class: "hint" }, `${label} `),
    el("strong", { style: mono() }, value));
}

const mono = () => "font-family:var(--mono);font-size:12px";

function fmtNum(v) {
  if (v == null || !Number.isFinite(v)) return "—";
  if (Number.isInteger(v)) return String(v);
  const a = Math.abs(v);
  if (a >= 1e4 || a < 1e-3) return v.toExponential(1);
  return String(Number(v.toPrecision(4)));
}
