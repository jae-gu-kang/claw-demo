/** 영향성 탭 — 파라미터 하나가 전체 시스템에 어떻게 번지는지 (02 §2.4, M15).

이 화면의 주 질문은 "이 값을 바꾸면 무엇이 얼마나 달라지나"이고, 답을 세 단으로 낸다:
구조 도달성(즉시) · 개루프 Δ(잡) · 폐루프 스윕(잡). 세 단이 다 붙어 있고, 2·3단
앞에는 진단이 선다 — "얼마나"를 재기 전에 "무엇을 만질지"(필터/게인/클램프/리미터/
스케줄, 단독/동시)를 저장된 런에서 귀속하고, 처방 카드의 손잡이만 스윕한다.

## 배치 — 그래프가 화면이고 나머지는 서랍이다 (v0.49)

블록도 최상위와 같은 규약이다: **주 그림은 카드에 넣지 않는다.** 종전에는 패널
다섯 장이 세로로 쌓여 그래프가 그중 한 칸이었고, 첫 화면에서 그래프 아래로 표
넷이 동시에 펼쳐져 무엇이 이 탭의 답인지가 흐렸다. 지금은 그래프가 페이지 위에
그대로 놓이고, 파라미터 표·진단·개루프·스윕·구간 경향은 **칩을 눌러야** 열린다
(한 번에 하나 — 두 개를 동시에 여는 것은 다시 쌓기다). 범례만 예외로 그림 바로
아래에 남는다 — 색이 칠해진 그래프가 늘 떠 있는데 범례를 클릭 뒤로 숨기면 화면이
자기 문법을 설명하지 않게 된다.

## 구간 경향 (3단 C) — "전 구간에서 어느 쪽으로" (v0.52)

3단 B가 답하지 못하던 자리다. B의 요약은 런별 **최악 한 칸**만 내고(엔벨로프를
접는다), 케이스×런 전체 표는 15케이스 × 9런 = 135행이라 경향이 행 사이에 흩어진다.
같은 행들을 손잡이 하나 기준 (구간 × 지표) 한 장으로 접은 것이 이 서랍이고, 행이
구간이라 세로로 한 번 훑으면 "저고도에서만 좋아지고 고고도에서는 나빠진다"가
그대로 읽힌다. **새로 재지 않는다** — 저장된 런의 순수 변환(`trendMatrix`)이라
잡도 엔드포인트도 없다.

## 판독대 — "얼마에서 얼마로"

그래프 바로 아래가 **정량 판독대**다. 고른 파라미터 하나에 대해 세 단이 각각
한 줄씩, 큰 숫자로 `기준 → 섭동`을 낸다. 종전 화면은 세 단이 전부 Δ만 냈고(2단은
기준과 Δ가 다른 열에 있어 눈으로 더해야 했다) "48.3°에서 47.1°로"라는 문장이
화면 어디에도 없었다. 재는 값은 셋 다 서버가 이미 주던 것이다 — 짝짓기(`from`·`to`)는
`lib/influence.js`가 하고 여기서는 그리기만 한다.

없는 단은 빈칸이 아니라 **사유**를 낸다 (판정 불가를 0으로 위장하지 않는 이 화면의
규약과 같다) — "아직 안 쟀다"와 "재 봤는데 영향이 없다"는 다른 사실이다.

**표가 정본 표면이고 캔버스는 보조다.** 캔버스는 보조기술에 불투명하므로, 화면이
말하는 모든 사실(상태·도달 개수·도달 출력)은 파라미터 표에도 반드시 있다 —
wpmap.js가 웨이포인트 표에 접근성을 맡긴 것과 같은 규약. 서랍에 넣었어도 표는
그대로 있고 칩 하나로 열린다.

이 탭은 **전면 다크**다: 검은 캔버스가 화면의 중심이라 패널만 밝으면 경계마다
스킨이 끊긴다. DOM 쪽 다크는 app.css의 `.inf-dark` 스코프가 담당하고(루트에
클래스 하나 — 다른 탭 불변), JS가 그리는 색(캔버스·배지·경고)만 인라인이다.
*/

import { api, errorText, watchJob } from "../api.js";
import { clear, el } from "../dom.js";
import {
  BAND_COLOR, DIRECTION_LABEL, GOOD_INK, KNOB_CLASS, SKIN, STATE_COLOR, STATE_INK,
  STATE_LABEL, STATE_NOTE, TREND_LABEL, TREND_MARK, WARN_INK,
  byImpact, columnFormat, coneOf, diagnoseRequest, edgeVia, fmtChange, fmtDelta,
  fmtPair, fmtPercent, fmtSigned, nodeDetail,
  normalizeDiagnosis, normalizeGraph, openloopWorst, pairsFor, probeTransition,
  radiusOf, relOf, relReadable, fmtRel, scanRequest, scanSummary, structuralRequest,
  sweepCases, sweepKnobs, sweepRequest, trendInk, trendMatrix, worstTransitions,
} from "../lib/influence.js";
import { machRange, nameCases, parseNumberList, serpentineCases } from "../lib/grid.js";
import { conePlayback, summaryOf } from "../lib/influenceplay.js";
import { cascadeLayout, layeredLayout } from "../lib/influencelayout.js";
import { createInfluenceCanvas } from "./influencecanvas.js";
import { store } from "../store.js";

// 그래프가 카드 밖으로 나오면서 폭이 늘었다 (app.css가 이 탭만 main을 1580까지
// 연다). 캔버스는 `width:논리폭 + max-width:100%`라 좁은 화면에서는 비율을 지킨
// 채 줄어든다 — 논리폭을 키우는 것은 확대가 아니라 **배치에 주는 가로 여유**다
const CANVAS_W = 1500;
const CANVAS_H = 660;
const ROW_GAP = 19;

// 뷰 재생성마다 처음으로 돌아가지 않도록 모듈 스코프 (autocode.js·sim.js와 같은 패턴)
const state = {
  variant: "cascade", selection: null, model: null, layout: null,
  cone: null, play: null,
  // 열린 서랍 하나 (null = 전부 닫힘) — 탭을 떠났다 와도 보던 자리로 돌아온다
  drawer: null,
  // 진단(2단 앞의 "무엇을") · 스캔(3단 A "어느 케이스가") · 스윕(3단 B "얼마나")
  // — 탭을 떠났다 와도 결과 유지
  diag: null, openloop: null, scan: null, sweep: null,
  // 구간 경향(3단 C)이 보고 있는 손잡이·지표 — 결과가 아니라 **보는 자리**라
  // 스윕과 수명이 다르다(같은 스윕을 손잡이별로 훑는 것이 이 표의 용법이다)
  trendKnob: null, trendMetric: null,
  // 케이스 격자 입력 — 결과(scan.selected)와 수명이 같아야 한다. 입력만 기본값으로
  // 되돌아가면 재진입 직후 3단 B가 "격자가 바뀌었다"고 거절한다(사용자는 안 건드렸다)
  gridForm: { machFrom: "0.4", machTo: "0.8", machStep: "0.1",
    alts: "100, 1000, 3000", fuels: "200", tStep: "15" },
};
let canvas = null;

// 성운(radial)은 삭제됐고 **전파 폭포가 기본**이다. 재생 일정은 배치와 무관한 위상
// 랭크이므로(influenceplay.js) 「프로세스 뷰」(레이어 활성망)로 전환해도 같은 재생·
// 같은 경로 패널을 공유한다 — 배치만 바꿔 같은 파라미터의 전파를 비교할 수 있다
const LAYOUT_FN = { layered: layeredLayout, cascade: cascadeLayout };

// 스캔(3단 A) 판정 칩 — local/global은 그 판정이 함의하는 처방 클래스의 잉크와
// 정렬한다 (국소 → 스케줄 셀, 전역 → 루프 게인 수준). ok만 별도 초록.
const VERDICT_LABEL = { ok: "정상", local: "국소", global: "전역" };
const VERDICT_INK = {
  ok: GOOD_INK, local: KNOB_CLASS.schedule.ink, global: KNOB_CLASS.loop_gain.ink,
};

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
  // 폭포(기본)의 굵은 흐름은 유량처럼 읽히지만 영향은 보존량이 아니다 — 이 캐비앳의
  // 소비처가 없어지면 layout의 meta.conserved 계약이 공중에 뜬다(influencelayout.js)
  const conservedNote = el("p", { style: "margin:6px 0 0" });
  const tableBox = el("div");
  const readoutBox = el("div", { class: "inf-readout" });
  // 재생 상태 줄 — 캔버스가 시계를 쥐고 있으므로 캔버스가 문자열을 밀어 준다.
  // `aria-live`는 쓰지 않는다: 이 캔버스는 보조 표면이고 정본은 아래 표인데,
  // 무한 반복이라 6초마다 층 문구 십수 개를 영구히 읽어 정본을 덮는다.
  // 지속되는 사실은 상세 패널에 정적 텍스트로 남는다(스크린리더가 요청할 때 읽는다)
  const playLine = el("p", {
    class: "hint", "aria-hidden": "true",
    style: `margin:8px 0 0;color:${SKIN.inkDim};white-space:nowrap;`
      + "overflow:hidden;text-overflow:ellipsis;min-height:20px",
  });
  const canvasBox = el("div", {
    // 캔버스는 max-width:100% + aspect-ratio로 비율을 지킨 채 줄어든다(캔버스 쪽
    // resize() 참조) — 좁은 화면에서도 넘치지 않으므로 가로 스크롤이 필요 없다
    style: "position:relative;border-radius:16px;background:#000",
  });
  // 전파 경로 패널 — 캔버스가 층을 켜는 것과 **같은 박자**로 층 칩이 켜진다.
  // 칩 목록(층·노드·값)은 선택마다 한 번 만들고, 동기화는 색·배경만 제자리에서
  // 바꾼다 — 갱신은 25 fps가 아니라 층이 바뀌는 프레임에만 온다(캔버스 onLayer 규약).
  // 캔버스는 보조기술에 불투명하므로 재생이 보여 주는 경로가 DOM에도 살게 하는 자리다
  const pathBox = el("div");
  let pathChips = [];   // [0]은 시작(파라미터) 칩, 이후 층 순서
  let pathInfo = null;  // 클릭한 층의 상세 — 칩을 눌렀을 때만 채워진다(showPathInfo)
  let pathInk = "#409cff";
  let curLayer = null;  // 캔버스가 마지막으로 알린 층 — 재생성 직후 칩에 되입힌다

  // 프로세스 뷰 토글 — 기본은 전파 폭포, 누르면 레이어 활성망(층별 실행 순서)으로.
  // 버튼은 한 번만 만들고 **제자리에서 고친다** — 다시 만들면 방금 누른 버튼이 DOM에서
  // 들려 나가 키보드 포커스가 <body>로 떨어지고, aria-pressed가 바뀌어도 낭독되지 않는다
  const processBtn = el("button", {
    title: "층별 실행 순서 배치로 전환 — 층 번호가 곧 생성 C의 문장 순서다",
    onclick: () => {
      state.variant = state.variant === "layered" ? "cascade" : "layered";
      renderProcessBtn();  // 눌림 상태가 안 바뀌면 지금 무엇을 보고 있는지 알 수 없다
      rebuild();
    },
  }, "프로세스 뷰");
  function renderProcessBtn() {
    const on = state.variant === "layered";
    processBtn.className = on ? "primary" : "";
    processBtn.setAttribute("aria-pressed", on ? "true" : "false");
  }
  renderProcessBtn();

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
    const fn = LAYOUT_FN[state.variant] ?? cascadeLayout;
    const probe = fn(graph, { ...opts, height: CANVAS_H });
    const height =
      Math.max(360, probe.bounds.maxRows * (state.variant === "cascade" ? 18 : ROW_GAP) + 96);
    state.layout = fn(graph, { ...opts, height });
    if (canvas) canvas.setSize(CANVAS_W, height);
    clear(conservedNote);
    if (state.layout?.meta?.conserved === false) {
      // 리본 폭을 유량으로 읽으면 "상류 = 하류 합"이라는 없는 성질을 믿게 된다
      conservedNote.append(el("span", { style: `font-size:12px;color:${WARN_INK}` },
        "⚠ 흐름 굵기는 보존량이 아니다 — 파라미터 하나가 여러 노드를 흔들고 하류 합은 상류와 같지 않다"));
    }
    renderTable();
    renderReadout();
  }

  // 원뿔과 재생 일정은 (모델, 선택)에만 의존한다 — **배치와 무관**하므로 배치를
  // 바꿔도 다시 만들지 않는다. 매 프레임 돌던 coneOf(간선 264개 스캔)도 여기로 모인다
  function recompute() {
    // 모델이 없을 수 있다: 첫 응답 전이거나 /influence/structural가 실패한 뒤.
    // 캔버스의 Escape 핸들러는 pointermove·click과 달리 layout 가드가 없어
    // 그 상태에서도 select(null)이 들어온다 — 여기서 막지 않으면 TypeError다
    if (!state.model) {
      state.cone = null;
      state.play = null;
      return;
    }
    state.cone = state.selection ? coneOf(state.model, state.selection) : null;
    state.play = state.cone ? conePlayback(state.model, state.cone) : null;
  }

  function select(id) {
    const n = id ? state.model?.byId.get(id) : null;
    // 노드를 눌러도 파라미터가 아니면 선택을 바꾸지 않는다 — 원뿔의 주어는 파라미터다
    state.selection = n?.kind === "param" ? id : id === null ? null : state.selection;
    recompute();
    if (!state.cone) playLine.textContent = "";
    renderPath();
    renderReadout();
    renderTable();
    // 동작 축소 설정에서는 타이머가 아예 없다 — frame()이 선택을 읽는 유일한 자리이므로
    // 여기서 직접 다시 그리지 않으면 캔버스가 "선택 없음"에 영원히 얼어 있고,
    // 표만 바뀐 채 그림은 전체를 밝게 유지해 "이 값이 전부를 건드린다"로 읽힌다
    canvas?.redraw();
  }

  // ── 전파 경로 — 층 칩 + 클릭한 층의 경로·설명 (두 배치가 같은 일정을 공유한다) ──
  // 상세는 **칩을 눌렀을 때만** 나온다. 재생을 따라 자동으로 띄우면 층마다 설명
  // 길이가 달라 아래 내용이 위아래로 계속 출렁여 오히려 읽을 수 없다 — 재생 중에는
  // 칩 점등과 캔버스 라벨·자막(playLine)이 순서를 말하고, 읽기는 클릭이 연다

  let pinnedChip = null;  // null = 재생을 따라감, 0 = 시작(파라미터) 칩, 1.. = 층 칩

  // "-"는 엔진의 무단위 센티널 — 시작 칩과 고정 상세가 같은 문자열을 내야 한다
  const unitOf = (n) => (n.unit && n.unit !== "-" ? ` ${n.unit}` : "");

  const pathChip = (text, i) => el("button", {
    // 인라인이 app.css의 .inf-dark button을 덮는다 — 칩은 버튼이되 버튼처럼 크면 안 된다
    style: "padding:2px 8px;border-radius:8px;border:1px solid rgba(255,255,255,.14);" +
      "background:rgba(255,255,255,.04);color:rgba(235,235,245,.45);" +
      "font-size:11px;line-height:16px;white-space:nowrap;cursor:pointer",
    "aria-pressed": "false",
    onclick: () => {
      pinnedChip = pinnedChip === i ? null : i;
      pathChips.forEach((c, j) => {
        c.setAttribute("aria-pressed", pinnedChip === j ? "true" : "false");
        c.style.outline = pinnedChip === j ? `2px solid ${pathInk}` : "none";
        c.style.outlineOffset = "1px";
      });
      showPathInfo();
    },
  }, text);

  function renderPath() {
    clear(pathBox);
    pathChips = [];
    pathInfo = null;
    pinnedChip = null;  // 고정은 선택에 속한다 — 다른 파라미터의 층 번호로 이월하지 않는다
    const m = state.model;
    const play = state.play;
    const sel = state.selection ? m?.byId.get(state.selection) : null;
    if (!m || !sel || !play) return;
    pathInk = STATE_INK[sel.state] ?? "#409cff";
    if (play.nLayer === 0) {
      pathBox.append(el("p", { class: "hint", style: "margin:8px 0 0;font-size:12px" },
        "전파 경로 없음 — 이 상수는 그래프에 방출되지 않는다."));
      return;
    }
    const labelOf = (id) => m.byId.get(id)?.label ?? id;
    const row = el("div", {
      class: "row", style: "gap:4px 2px;flex-wrap:wrap;align-items:center;margin-top:10px",
    });
    // 시작 칩 — 파라미터는 층 1(랭크 0)에 고정이고, 값이 있는 유일한 종류다
    pathChips.push(pathChip(`층 1 · ${sel.label} = ${fmtNum(sel.value)}${unitOf(sel)}`, 0));
    pathChips[0].title = sel.desc ?? "";
    row.append(pathChips[0]);
    play.layers.forEach((L, i) => {
      row.append(el("span", {
        style: "color:rgba(235,235,245,.3);font-size:11px;margin:0 2px",
      }, "→"));
      // 대표 노드(headline)만 칩에 세운다 — 나머지는 +n으로 접고 상세 줄이 푼다.
      // headline 부재는 captionAt과 같은 폴백 — 가드 없이 찍으면 「층 X · null」이 된다
      const name = L.headline ? labelOf(L.headline) : `노드 ${L.arrive.length}개`;
      const extra = L.headline && L.arrive.length > 1 ? ` +${L.arrive.length - 1}` : "";
      const c = pathChip(`층 ${L.rank + 1} · ${name}${extra}`, i + 1);
      c.title = nodeDetail(m.byId.get(L.headline), m.bands);  // 데스크톱 훑기용 툴팁
      pathChips.push(c);
      row.append(c);
    });
    // 내용은 클릭했을 때만 채워진다 — 자동으로 바뀌지 않으므로 보조기술에도 그대로
    // 연다(aria-hidden 불필요). 높이도 예약하지 않는다: 비어 있을 때 공간을 잡아 두면
    // 그게 또 "출렁임 방지용 여백"이라는 이름의 빈 칸이 된다
    pathInfo = el("div", { style: "margin-top:6px;font-size:12px" });
    pathBox.append(row,
      el("p", { class: "hint", style: "margin:4px 0 0;font-size:11px" },
        "칩을 누르면 그 층의 노드·경로·설명이 아래에 나온다 — 다시 누르면 닫힌다."),
      pathInfo);
    // 재생성 직후(탭 복귀 등) 캔버스는 층이 **바뀔 때만** 알린다 — 마지막으로 알린
    // 층을 되입히지 않으면 다음 층 변화까지 칩이 전부 꺼진 채 남는다
    if (curLayer != null) setActiveLayer(curLayer);
  }

  function setActiveLayer(k) {
    curLayer = k;
    if (k == null || !pathChips.length || !pathInfo) return;
    const nLayers = pathChips.length - 1;      // 시작 칩 제외
    const done = k >= nLayers;
    const active = done ? -1 : k + 1;          // 층 k가 자라는 중 = 칩 k+1이 진행 중
    pathChips.forEach((c, i) => {
      const lit = done || i <= k + 1;
      c.style.color = lit ? pathInk : "rgba(235,235,245,.45)";
      c.style.borderColor = lit ? `${pathInk}66` : "rgba(255,255,255,.14)";
      c.style.background = i === active ? `${pathInk}26` : "rgba(255,255,255,.04)";
      c.style.fontWeight = i === active ? "600" : "400";
    });
    // 상세는 건드리지 않는다 — 내용이 (모델·선택·클릭한 칩)에만 걸려 있어 재생이
    // 바꿀 것이 없고, 층마다 다시 그리면 사용자가 잡은 텍스트 선택이 무너진다
  }

  /** 상세 줄이 보여 줄 것을 한 자리에서 고른다 — **클릭한 칩이 있을 때만** 채운다.
   *  재생을 따라 자동으로 띄우면 층마다 설명 길이가 달라 아래 내용이 계속 출렁인다.
   *  재생 중 순서는 칩 점등·캔버스 라벨·자막(playLine)이 이미 말하고 있다. */
  function showPathInfo() {
    if (!pathInfo) return;
    clear(pathInfo);
    if (pinnedChip == null) return;
    if (pinnedChip === 0) return renderStartInfo();
    renderLayerInfo(pinnedChip - 1);
  }

  /** 시작 칩 — 파라미터 자신: 값·설명과 씨앗 간선(값이 **어떻게** 들어가는지). */
  function renderStartInfo() {
    const m = state.model;
    const sel = state.selection ? m?.byId.get(state.selection) : null;
    if (!m || !sel) return;
    const seeds = [];
    m.edges.forEach((e, i) => {
      if (e.src === sel.id && state.cone?.edges.has(i)) {
        seeds.push(`${m.byId.get(e.dst)?.label ?? e.dst} (${edgeVia(e)})`);
      }
    });
    pathInfo.append(
      el("div", {},
        el("strong", { style: `color:${pathInk}` }, "층 1"),
        el("span", {}, ` — ${sel.label} = ${fmtNum(sel.value)}${unitOf(sel)}`),
        el("span", { class: "hint" }, `  ${m.bands?.[sel.band]?.label ?? ""}`),
      ),
      sel.desc ? el("div", { class: "hint", style: "margin-top:2px" }, sel.desc) : "",
      seeds.length
        ? el("div", { class: "hint", style: "margin-top:2px" }, `건드리는 노드: ${seeds.join(" · ")}`)
        : "",
    );
  }

  /** 층 상세 — 그 층에 도달하는 **모든** 노드를 한 줄씩: 들어온 간선(출발지·포트)과
   *  노드 설명(블록·파라미터 값·연산·지표 정의). 대표만 말하면 "함께 도달 3개"가
   *  영영 이름 없는 노드로 남는다. */
  function renderLayerInfo(k) {
    const m = state.model;
    const play = state.play;
    const L = play?.layers[k];
    if (!m || !L) return;
    const labelOf = (id) => m.byId.get(id)?.label ?? id;
    pathInfo.append(el("div", {},
      el("strong", { style: `color:${pathInk}` }, `층 ${L.rank + 1}/${play.maxRank + 1}`),
      el("span", { class: "hint" }, ` · 노드 ${L.arrive.length}개 도달`)));
    const MAX_ROWS = 5;
    for (const id of L.arrive.slice(0, MAX_ROWS)) {
      // 이 층에서 이 노드로 들어온 간선 — 출발지와 포트가 곧 경로의 문법이다:
      // 같은 화살표라도 입력·게인·인에이블·비활성 폴백은 서로 다른 이야기다
      const inc = L.edges
        .filter((i) => m.edges[i]?.dst === id)
        .map((i) => `${labelOf(m.edges[i].src)} (${edgeVia(m.edges[i])})`);
      const shown = inc.slice(0, 3).join(" · ") + (inc.length > 3 ? ` 외 ${inc.length - 3}` : "");
      const det = nodeDetail(m.byId.get(id), m.bands);
      pathInfo.append(el("div", { style: "margin-top:2px" },
        el("strong", {}, labelOf(id)),
        shown ? el("span", { class: "hint" }, ` ← ${shown}`) : "",
        det ? el("div", { class: "hint", style: "margin-left:12px" }, det) : ""));
    }
    if (L.arrive.length > MAX_ROWS) {
      pathInfo.append(el("div", { class: "hint", style: "margin-top:2px" },
        `… 외 ${L.arrive.length - MAX_ROWS}개: ${L.arrive.slice(MAX_ROWS).map(labelOf).join(", ")}`));
    }
  }

  // ── 정량 판독대 — 「얼마에서 얼마로」 (이 화면의 주 표면) ─────────────────
  // 세 단이 각각 한 줄씩. 값은 전부 서버가 이미 주던 것이고, 짝짓기(from·to)는
  // lib이 한다 — 여기서는 고르고 그리기만 한다.

  /** 큰 숫자 한 줄: `기준 → 섭동 단위`. 이 화면에서 제일 큰 글자가 여기다.
   *  자릿수는 fmtPair가 정한다 — 두 값이 같은 표기로 뭉개지면 판독대가 죽는다. */
  function numLine(from, to, unit) {
    const [a, b] = fmtPair(from, to);
    return el("span", { class: "inf-num" },
      el("span", { class: "from" }, a),
      el("span", { class: "arrow" }, "→"),
      el("span", { class: "to" }, b),
      unit ? el("span", { class: "unit" }, unit) : null);
  }

  /** 변화량 칩 — 표기 규칙은 lib(fmtChange)이 쥔다. 색은 칠하지 않는다:
   *  **이 값 하나가 좋은지 나쁜지는 문턱이 정하는데 판독대는 문턱을 모른다** —
   *  초록/빨강을 입히면 화면이 진단(2·3단 문턱)의 판정을 참칭한다.
   *
   *  구간 경향 표(trendInk)는 같은 `MetricDef.better`로 색을 칠하는데 모순이 아니다:
   *  저기서 색이 붙는 대상은 값이 아니라 **부호**이고(문턱과 무관하다), "이 손잡이를
   *  올리면 이 지표는 나빠지는 쪽으로 간다"는 선언된 극성 그대로다. 여기는 값,
   *  저기는 방향 — 문턱을 아는 척하는 쪽만 금지다. */
  function chgChip(delta, rel, unit) {
    return el("span", { class: "inf-chg" }, fmtChange(delta, rel, unit));
  }

  function roRow(tier, ink, what, from, to, unit, delta, rel, at) {
    return el("div", { class: "inf-rorow" },
      el("span", { class: "inf-tier", style: `color:${ink}` }, tier),
      el("span", { class: "inf-what" }, what),
      numLine(from, to, unit),
      el("span", {}, chgChip(delta, rel, unit),
        at ? el("span", { class: "inf-at" }, ` @${at}`) : null));
  }

  /** 단이 답을 못 내는 이유 — 빈칸으로 두면 "영향 없음"으로 읽힌다. */
  function roWhy(tier, ink, text) {
    return el("div", { class: "inf-rorow" },
      el("span", { class: "inf-tier", style: `color:${ink}` }, tier),
      el("span", { class: "inf-what" }, "—"),
      el("span", { class: "inf-why" }, text));
  }

  /** 저장된 2·3단 결과가 **지금 형상의 것인가.**
   *
   * 결과는 모듈 스코프라 탭을 떠났다 와도 살아 있는데, 그 사이 게인 탭에서 값을
   * 바꾸면 형상이 달라진다. 그때 옛 수치를 그냥 띄우면 화면에 없는 기체의 마진·지표를
   * 지금 것으로 읽게 된다 — 지문이 그 계보를 위해 있는 것이므로(02 §2.4) 여기서 쓴다.
   */
  const staleOf = (res) => {
    const fp = state.model?.fingerprint;
    return res?.fingerprint && fp && res.fingerprint !== fp ? res.fingerprint : null;
  };

  /** 2단 — 이 손잡이의 (루프별) 마진 전이 중 |ΔPM|이 가장 큰 루프 하나.
   *
   * "안 쟀다"와 "쟀는데 이 손잡이가 대상이 아니었다"는 **다른 사실**이다 — 뭉치면
   * 화면이 방금 돌린 계산을 다시 돌리라고 시키고, 다시 돌려도 문구가 안 바뀐다. */
  function openloopFor(pid) {
    const res = state.openloop?.result;
    if (!res) return null;                              // 아직 안 쟀다
    const params = res.params;
    if (!params?.[pid]) return { missing: true, stale: staleOf(res) };  // 대상이 아니었다
    const rows = openloopWorst(params, [pid]);
    const stale = staleOf(res);
    if (!rows.length) {
      return { reason: params[pid].reason ?? params[pid].status, stale };
    }
    const best = rows.reduce((a, b) =>
      (Math.abs(b.pm?.value ?? 0) > Math.abs(a.pm?.value ?? 0) ? b : a));
    return { best, stale };
  }

  /** 3단 — 이 손잡이 **단독** 런들만 모아 지표별 최악 전이. 쌍 런(A&B)은 제외한다:
   *  두 손잡이가 같이 움직인 Δ를 한 손잡이의 영향으로 읽으면 귀속이 틀린다. */
  function sweepFor(pid) {
    const res = state.sweep?.result;
    const rows = res?.rows;
    if (!rows?.length) return null;                     // 아직 안 쟀다
    const stale = staleOf(res);
    const solo = rows.filter((r) => r.label === "base"
      || (Object.keys(r.overrides ?? {}).length === 1 && r.overrides[pid] != null));
    if (!solo.some((r) => r.label !== "base")) return { missing: true, stale };
    const knobTo = new Map(solo.map((r) => [r.label, r.overrides?.[pid]]));
    const best = new Map();
    for (const [label, byMetric] of Object.entries(worstTransitions(solo))) {
      for (const [k, t] of Object.entries(byMetric)) {
        const cur = best.get(k);
        if (!cur || Math.abs(t.delta) > Math.abs(cur.t.delta)) {
          best.set(k, { label, t, knobTo: knobTo.get(label) });
        }
      }
    }
    // 단위가 제각각이라 |Δ|로는 줄을 못 세운다 — 순위 규칙은 lib이 쥔다(byImpact)
    const list = [...best.entries()]
      .map(([metric, v]) => ({ metric, ...v }))
      .sort((a, b) => byImpact(a.t, b.t));
    return { list, stale };
  }

  function renderReadout() {
    clear(readoutBox);
    const m = state.model;
    if (!m) return;
    const sel = state.selection ? m.byId.get(state.selection) : null;
    if (!sel) {
      readoutBox.append(el("p", { class: "hint", style: "margin:0" },
        "그래프의 왼쪽 파라미터 열에서 하나를 고르면 여기에 " +
        "「얼마에서 얼마로」가 뜬다 — 1단은 즉시, 2·3단은 재 둔 결과가 있을 때. " +
        "층 번호는 IR 실행 순서이자 생성 C의 문장 순서다."));
      return;
    }
    const note = STATE_NOTE[sel.state];
    readoutBox.append(el("div", { class: "inf-rohead" },
      badge(sel.state),
      el("span", { class: "name" }, sel.param_id),
      el("span", { class: "hint", style: "font-size:12px" },
        m.bands?.[sel.band]?.label ?? sel.band),
      el("span", { class: "grow" }),
      el("button", { onclick: () => select(null) }, "선택 해제")));

    const rows = el("div", { class: "inf-rorows" });
    // ① 1단 — 파라미터 자신이 얼마에서 얼마로. 유한 차분이지 미분이 아니다
    const probe = probeTransition(sel);
    rows.append(probe
      ? roRow("1단 구조", STATE_INK.live, `${sel.label} · 탐침 (유한 차분)`,
          probe.from, probe.to, probe.unit, probe.delta, probe.rel,
          `도달 노드 ${sel.n_reach ?? 0}`)
      : roWhy("1단 구조", STATE_INK.live,
          sel.error ?? "섭동값을 만들 수 없다 — 범위·교차조건이 막는다"));

    // 저장된 결과가 다른 형상의 것이면 수치보다 그 사실이 먼저다
    const staleNote = (fp) =>
      `⚠ 이 수치는 형상 ${fp}에서 잰 것이다 — 지금 형상(${state.model.fingerprint})과 ` +
      "다르므로 다시 재야 한다.";

    // ② 2단 — 개루프 마진 전이
    const ol = openloopFor(sel.param_id);
    if (!ol) {
      rows.append(roWhy("2단 개루프", "#409cff",
        "아직 안 쟀다 — 아래 「진단·처방」 서랍의 [개루프 근거]가 이 자리를 채운다."));
    } else if (ol.missing) {
      rows.append(roWhy("2단 개루프", "#409cff",
        "이 손잡이는 잰 적이 없다 — 개루프는 처방 카드가 고른 손잡이만 잰다. " +
        "이 값을 재려면 이 손잡이를 포함하는 카드에서 [개루프 근거]를 누른다."));
    } else if (!ol.best) {
      rows.append(roWhy("2단 개루프", "#409cff",
        `유효한 Δ 없음 — ${ol.reason ?? "선언된 SISO 루프가 없다"}`));
    } else {
      const b = ol.best;
      if (b.pm) {
        rows.append(roRow("2단 개루프", "#409cff", `${b.loop} 위상여유 (PM)`,
          b.pm.from, b.pm.to, "°", b.pm.value, relOf(b.pm.from, b.pm.to), b.pm.case));
      }
      if (b.gm) {
        rows.append(roRow("", "#409cff", `${b.loop} 이득여유 (GM)`,
          b.gm.from, b.gm.to, "dB", b.gm.value, relOf(b.gm.from, b.gm.to), b.gm.case));
      }
    }
    if (ol?.stale) rows.append(roWhy("", WARN_INK, staleNote(ol.stale)));

    // ③ 3단 — 설계 지표 전이 (상위 3개). 폐루프 재시뮬 실측이라 이 화면의 최종 답이다
    const sw = sweepFor(sel.param_id);
    if (!sw) {
      rows.append(roWhy("3단 폐루프", "#ffb340",
        "아직 안 쟀다 — 「진단·처방」의 [이 부분공간 스윕]이 이 자리를 채운다. " +
        "여기가 폐루프 실측이고, 위 두 단은 그 전에 범위를 좁히는 근사다."));
    } else if (sw.missing) {
      rows.append(roWhy("3단 폐루프", "#ffb340",
        "이 손잡이는 흔든 적이 없다 — 스윕은 처방 부분공간만 흔든다(전 게인 공간이 " +
        "아니다). 이 값을 재려면 이 손잡이를 포함하는 카드에서 [이 부분공간 스윕]을 누른다."));
    } else {
      for (const s of sw.list.slice(0, 3)) {
        // 손잡이를 **얼마로** 놓았을 때인지가 함께 있어야 지표 전이가 뜻을 갖는다.
        // 기준값은 붙이지 않는다: 여기 있는 sel.value는 **지금** 모델의 값이고
        // knobTo는 저장된 런의 값이라, 둘을 화살표로 이으면 실제로 일어난 적 없는
        // 전이가 만들어진다(게인 탭에서 값을 바꾸고 돌아오면 바로 그렇게 된다).
        // 런이 쓴 값 하나만 사실이다 — 형상이 어긋나면 위 stale 줄이 말한다
        const at = s.knobTo == null ? s.t.case
          : `${s.t.case} · ${sel.label}=${fmtNum(s.knobTo)}`;
        rows.append(roRow("3단 폐루프", "#ffb340", metricLabel(s.metric),
          s.t.from, s.t.to, metricUnit(s.metric), s.t.delta, s.t.rel, at));
      }
      if (sw.list.length > 3) {
        rows.append(el("div", { class: "inf-rorow" },
          el("span", { class: "inf-why" },
            `… 외 지표 ${sw.list.length - 3}개 — 「스윕 Δ」 서랍에 전부 있다`)));
      }
    }
    if (sw?.stale) rows.append(roWhy("", WARN_INK, staleNote(sw.stale)));
    readoutBox.append(rows);

    // 꼬리 — 상태 주석·설명·전파 요약. 숫자가 아니라 문장이라 아래에 작게 둔다
    const foot = el("div", { style: "margin-top:10px" });
    if (note) {
      foot.append(el("p", {
        style: `margin:0 0 4px;color:${STATE_INK[sel.state]};font-size:12px`,
      }, note));
    }
    foot.append(el("p", { class: "hint", style: "margin:0;font-size:12px" }, sel.desc));
    if (sel.added?.length) {
      foot.append(el("p", { style: `margin:4px 0 0;color:${WARN_INK};font-size:12px` },
        `이 값을 올리면 생기는 노드: ${sel.added.join(", ")} — 탑재 C도 달라진다`));
    }
    foot.append(el("div", { class: "row", style: "gap:18px;margin-top:6px;font-size:12px" },
      stat("건드리는 노드", (sel.seeds ?? []).join(", ") || "—"),
      stat("도달 출력", (sel.outputs ?? []).join(", ") || "—")));
    // 재생이 보여 주는 순서를 **글로도** 남긴다 — 캔버스만 아는 사실을 만들지 않는다.
    // 캔버스 아래 줄은 재생 중 흘러가지만 이쪽은 선택마다 한 번 갱신되는 정적 사실이라
    // 스크린리더가 요청할 때 읽는다(그래서 저쪽이 aria-hidden이어도 손실이 없다)
    if (state.play) {
      foot.append(el("p", { class: "hint", style: "margin:4px 0 0;font-size:12px" },
        summaryOf(state.play, (id) => m.byId.get(id)?.label ?? id)));
    }
    readoutBox.append(foot);
  }

  function renderTable() {
    clear(tableBox);
    const m = state.model;
    if (!m) return;
    const rows = [...m.params].sort((a, b) =>
      (b.n_reach ?? 0) - (a.n_reach ?? 0) || a.param_id.localeCompare(b.param_id));
    tableBox.append(
      el("div", { class: "scroll-x", style: "max-height:420px;overflow-y:auto" },
        el("table", {},
          el("thead", {}, el("tr", {},
            ["파라미터", "묶음", "값 → 탐침", "단위", "상태", "도달 노드", "도달 출력"]
              .map((h) => el("th", {}, h)))),
          el("tbody", {}, rows.map((p) => {
            const t = probeTransition(p);
            return el("tr", {
              // 선택 강조 .25 — 라이트 시절의 .09는 #1c1c1e 위에서 식별 불가
              style: `cursor:pointer${p.id === state.selection ? ";background:rgba(10,132,255,.25)" : ""}`,
              onclick: () => select(p.id),
            },
              el("td", {}, el("code", { style: mono() }, p.param_id)),
              el("td", {}, m.bands?.[p.band]?.label ?? p.band),
              // 값만 있던 열을 전이로 바꾼다 — 이 표에서도 "얼마에서 얼마로"가
              // 읽혀야 판독대와 같은 사실을 말하는 표가 된다
              el("td", { class: "num" }, t
                ? transCell(t.from, t.to, t.delta, "")
                : fmtNum(p.value)),
              el("td", {}, p.unit),
              el("td", {}, badge(p.state)),
              el("td", { class: "num" }, String(p.n_reach ?? 0)),
              el("td", {}, (p.outputs ?? []).join(", ") || "—"),
            );
          })),
        )),
      el("p", { class: "hint", style: "margin:6px 0 0" },
        "표가 이 화면의 정본이다 — 캔버스가 말하는 것은 전부 여기에도 있다. " +
        "탐침은 상대 1% 유한 차분이지 미분이 아니다. " +
        "「도달 노드」는 영향의 크기가 아니라 영향이 있을 수 있는 범위다 — " +
        "포화된 가지나 0 게인을 지나는 경로도 도달로 잡힌다."),
    );
  }

  function renderLegend(m) {
    clear(legendBox);
    // 잉크는 app.css `.inf-dark .legend`가 준다 — 라이트 muted가 #1c1c1e 위에서
    // 3.4:1로 떨어지던 자리를 스코프 규칙(특이도 2)이 `.legend`(1)를 이겨서 덮는다
    legendBox.append(
      el("div", { class: "legend" },
        Object.entries(STATE_LABEL).map(([k, label]) =>
          el("span", {},
            el("span", { class: "chip", style: `background:${STATE_COLOR[k]}` }),
            label))),
      el("div", { class: "legend", style: "margin-top:2px" },
        Object.entries(m.bands ?? {}).map(([k, b]) =>
          el("span", {},
            el("span", { class: "chip", style: `background:${BAND_COLOR[k] ?? SKIN.gray}` }),
            b.label + (b.in_law ? "" : " (법칙 밖)")))),
    );
  }

  // 게인 탭이 자리를 전부 끄면 `{gainTables: null, gainScheduleOff: true}`를 쓴다 —
  // 빈 dict로는 "껐다"를 표현할 수 없어서 짝으로 두는 키다(lib/gainsched.js).
  // 이걸 안 읽으면 사용자가 끈 스케줄을 켜진 것으로 해석해, 있지도 않은
  // 「스케줄에 덮임」 경고를 띄우고 지문도 Autocode 탭과 어긋난다.
  // 진단·스윕 요청도 **같은 형상**을 실어야 한다 — 여기서 갈라지면 승격 판정이
  // 실제 런 형상과 어긋난다 (그래서 한 함수다)
  const shapeState = () => ({
    autopilot: store.get("autopilotParams"),
    scas: store.get("scasParams"),
    nav: store.get("navParams"),
    actuators: store.get("actuatorParams"),
    gainTables: store.get("gainTables"),
    withSchedule: store.get("gainScheduleOff") ? false : undefined,
  });

  async function load() {
    try {
      clear(errBox);
      const body = structuralRequest(shapeState());
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
      recompute();
      renderPath();
      renderLegend(m);
      renderTabCounts();  // 파라미터 개수·경고 개수가 여기서 정해진다
      renderDrawer();     // 열려 있던 서랍이 새 모델의 내용으로 다시 그려진다
      rebuild();
      canvas.invalidate();
    } catch (e) {
      statusLine.textContent = "불러오지 못했습니다";
      clear(errBox).append(el("div", { class: "error-box" }, errorText(e)));
    }
  }

  // ── 진단 → 처방 → 스윕 (2·3단 표면 — 표가 정본, 캔버스 연동은 보조) ──────

  const diagStatus = el("span", { class: "hint" },
    "시뮬레이션 탭의 최근 런을 진단한다 — 런이 없으면 먼저 하나 만든다.");
  const diagBox = el("div");
  const scanStatusLine = el("p", { class: "hint", style: "margin:6px 0 0" });
  const scanBox = el("div");
  const sweepStatusLine = el("p", { class: "hint", style: "margin:6px 0 0" });
  const sweepBox = el("div");
  const resultInput = el("input", {
    type: "text", placeholder: "sim 결과 id",
    value: store.get("simResult")?.id ?? "",
    style: `${mono()};width:230px`,
  });
  const numIn = (val, width = 70) =>
    el("input", { type: "number", value: val, step: "any", style: `width:${width}px` });
  // 케이스 격자 — margins 탭과 같은 기본값(15케이스). 2단은 케이스당 ~10 ms라
  // 격자 전체가 공짜지만, 3단은 케이스 × 런 곱이라 A(전 케이스 base 스캔)로
  // 결함 케이스를 좁힌 뒤 B(부분 풀 스윕)로 간다.
  const g = state.gridForm;
  const machFromIn = numIn(g.machFrom, 55);
  const machToIn = numIn(g.machTo, 55);
  const machStepIn = numIn(g.machStep, 55);
  const altsIn = el("input", { type: "text", value: g.alts, style: "width:120px" });
  const fuelsIn = el("input", { type: "text", value: g.fuels, style: "width:60px" });
  const stepIn = numIn(g.tStep, 55);
  const caseCountHint = el("span", { class: "hint" });

  // 이름은 클라이언트가 명시 부여한다(lib/grid.js nameCases — 유일성 보장) —
  // 스캔 결과의 bad_cases(이름 문자열)를 3단 B의 케이스 객체로 되돌리는 매핑이
  // 서버 자동 명명 형식에 묶이지 않게
  function gridCases() {
    return nameCases(serpentineCases(
      machRange(Number(machFromIn.value), Number(machToIn.value),
        Number(machStepIn.value)),
      parseNumberList(altsIn.value),
      parseNumberList(fuelsIn.value),
    ));
  }
  function renderCaseCount() {
    try {
      caseCountHint.textContent = `케이스 ${gridCases().length}건`;
    } catch {
      caseCountHint.textContent = "격자 입력 오류";
    }
  }
  for (const [key, inp] of Object.entries({
    machFrom: machFromIn, machTo: machToIn, machStep: machStepIn,
    alts: altsIn, fuels: fuelsIn, tStep: stepIn,
  })) {
    inp.addEventListener("input", () => {
      state.gridForm[key] = inp.value;  // 재진입 때 되살릴 값
      renderCaseCount();
    });
  }
  renderCaseCount();

  const metricDef = (key) => (state.model?.metrics ?? []).find((m) => m.key === key);
  const metricLabel = (key) => metricDef(key)?.label ?? key;
  // 무단위 센티널 "-"는 단위가 아니다 (엔진 규약 — 판독대가 "0.12 -"를 찍지 않게)
  const metricUnit = (key) => {
    const u = metricDef(key)?.unit;
    return u && u !== "-" ? u : "";
  };

  async function runDiagnose() {
    const rid = resultInput.value.trim() || store.get("simResult")?.id;
    if (!rid) {
      diagStatus.textContent = "진단할 런이 없다 — 시뮬레이션 탭에서 런을 만들거나 결과 id를 입력";
      return;
    }
    diagStatus.textContent = "진단 중…";
    clear(diagBox);
    try {
      state.diag = normalizeDiagnosis(
        await api.post("/influence/diagnose", diagnoseRequest(shapeState(), rid)));
      diagStatus.textContent =
        `결과 ${state.diag.resultId} · 형상 지문 ${state.diag.fingerprint} · ` +
        `처방 ${state.diag.prescriptions.length}건`;
      renderDiag();
    } catch (e) {
      diagStatus.textContent = "진단 실패";
      clear(diagBox).append(el("div", { class: "error-box" }, errorText(e)));
    }
  }

  function renderDiag() {
    renderTabCounts();  // 결과 유무가 칩 배지로 먼저 보인다 (서랍이 닫혀 있어도)
    clear(diagBox);
    const d = state.diag;
    if (!d) return;
    // 지표 줄 — 진단의 입력이자 스윕 Δ의 기준
    diagBox.append(
      el("div", { class: "row", style: "gap:14px;flex-wrap:wrap;margin-top:8px;font-size:12px" },
        Object.entries(d.metrics).map(([k, v]) =>
          stat(metricLabel(k), k.endsWith("_frac") ? fmtPercent(v) : fmtDelta(v)))),
    );
    for (const w of d.warnings) {
      diagBox.append(el("p", { style: `margin:4px 0;font-size:12px;color:${WARN_INK}` }, `⚠ ${w}`));
    }
    // 판정 표 — 처방이 없어도 "왜 없는지"(evidence)가 남아야 한다
    diagBox.append(
      el("div", { class: "scroll-x", style: "margin-top:8px" },
        el("table", {},
          el("thead", {}, el("tr", {},
            ["규칙", "축", "판정", "근거"].map((h) => el("th", {}, h)))),
          el("tbody", {}, d.findings.map((f) =>
            el("tr", {},
              el("td", {}, el("code", { style: mono() }, f.rule)),
              el("td", {}, f.axis),
              el("td", {}, el("span", {
                class: "flag",
                style: f.severity === "warn"
                  ? `background:${WARN_INK}26;color:${WARN_INK};font-weight:600`
                  : "",
              }, f.severity === "warn" ? "처방" : "정상")),
              el("td", { style: "max-width:520px" },
                f.verdict,
                el("span", { class: "hint", style: "margin-left:8px;font-size:11px" },
                  Object.entries(f.evidence)
                    .filter(([, v]) => typeof v === "number")
                    .map(([k, v]) => `${k}=${fmtDelta(v)}`).join(" · ")),
              ),
            ))),
        )),
    );
    if (!d.prescriptions.length) {
      diagBox.append(el("p", { class: "hint", style: "margin:8px 0 0" },
        "처방 없음 — 모든 지표가 문턱 안이다. 문턱은 서버 응답(thresholds)이 들고 있다."));
      return;
    }
    // 처방 카드 — knobs가 곧 3단 스윕의 입력이다.
    // stretch: .row 기본(align-items:end)은 카드 아래를 맞춰 위가 들쭉날쭉해진다
    diagBox.append(el("div", {
      class: "row", style: "gap:12px;flex-wrap:wrap;margin-top:10px;align-items:stretch",
    },
      d.prescriptions.map((p) => {
        const cls = KNOB_CLASS[p.knob_class] ?? { label: p.knob_class, ink: "#98989d" };
        return el("div", { class: "knob-card" },
          el("div", { class: "row", style: "gap:8px;align-items:center" },
            el("span", {
              class: "flag",
              style: `background:${cls.ink}26;color:${cls.ink};font-weight:600`,
            }, cls.label),
            el("span", { style: "font-size:12px" }, DIRECTION_LABEL[p.direction] ?? ""),
          ),
          el("p", { style: "margin:6px 0 0" },
            p.knobs.map((k) => el("code", { style: `${mono()};margin-right:6px` }, k))),
          p.joint_with.length
            ? el("p", { class: "hint", style: "margin:4px 0 0;font-size:12px" },
                "동시 수정 후보: ", p.joint_with.map((k) =>
                  el("code", { style: `${mono()};margin-right:6px` }, k)))
            : null,
          p.recheck.length
            ? el("p", { class: "hint", style: "margin:4px 0 0;font-size:12px" },
                `움직인 뒤 재확인: ${p.recheck.map(metricLabel).join(", ")}`)
            : null,
          p.notes.map((n) =>
            el("p", { style: `margin:4px 0 0;font-size:12px;color:${WARN_INK}` }, n)),
          el("p", { class: "hint", style: "margin:4px 0 0;font-size:11px" },
            `근거: ${p.findings.map((i) => d.findings[i]?.rule ?? i).join(", ")}`),
          el("div", { class: "row", style: "gap:8px;margin-top:8px" },
            el("button", { onclick: () => runOpenloop(p) }, "개루프 근거 (2단)"),
            el("button", {
              class: "primary", onclick: () => runSweep(p),
            }, "이 부분공간 스윕 (3단 B)"),
          ),
        );
      })));
  }

  const olStatusLine = el("p", { class: "hint", style: "margin:6px 0 0" });
  const olBox = el("div");

  async function runOpenloop(card) {
    let cases;
    try {
      cases = gridCases();
    } catch (e) {
      state.openloop = { card, result: null, error: errorText(e) };
      renderOpenloop();
      runStatus("개루프: 격자 입력 오류", { open: "openloop", bad: true });
      return;
    }
    runStatus(`개루프 Δ 계산 중 — 케이스 ${cases.length}건…`);
    clear(olBox);
    try {
      const job = await api.post("/influence/openloop", {
        ...structuralRequest(shapeState()),
        cases, params: card.knobs, fingerprint: state.diag?.fingerprint,
      });
      const done = await watchJob(job.id, (j) => {
        runStatus(`개루프 ${Math.round((j.progress ?? 0) * 100)}% — ${j.message ?? ""}`);
      });
      if (done.status !== "done" || !done.result_id) {
        runStatus(`개루프 ${done.status}`, { bad: true });
        return;
      }
      const res = await api.get(`/results/${done.result_id}`);
      state.openloop = { card, result: res, error: null };
      renderOpenloop();
      // 판독대의 2단 줄이 여기서 채워진다 — 결과를 안 알리면 방금 잰 수치가
      // 서랍 안에만 있고 화면의 주 표면은 여전히 "아직 안 쟀다"라고 말한다
      renderReadout();
      runStatus("개루프 Δ 완료", { open: "openloop" });
    } catch (e) {
      state.openloop = { card, result: null, error: errorText(e) };
      renderOpenloop();
      renderReadout();  // 실패했는데 판독대가 "아직 안 쟀다"로 남으면 거짓말이다
      runStatus("개루프 실패", { open: "openloop", bad: true });
    }
  }

  /** 전이 셀 — `기준 → 섭동 (Δ)`. 종전에는 기준과 Δ가 다른 열에 있어 "얼마로
   *  가는지"를 사용자가 눈으로 더해야 했다. inf 문자열은 fmtDelta가 ∞로 받는다. */
  function transCell(from, to, delta, unit, fmt) {
    if (from == null && to == null) return "—";
    const [a, b] = fmtPair(from, to, fmt);
    return el("span", { style: "white-space:nowrap" },
      el("span", { style: `color:${SKIN.inkDim}` }, a),
      " → ",
      el("strong", {}, b),
      unit ? ` ${unit}` : "",
      el("span", { style: `color:${SKIN.inkDim};margin-left:6px` },
        `(${fmtSigned(delta)})`));
  }

  function renderOpenloop() {
    renderTabCounts();  // 결과 유무가 칩 배지로 먼저 보인다 (서랍이 닫혀 있어도)
    clear(olBox);
    const s = state.openloop;
    if (s?.error) olBox.append(el("div", { class: "error-box" }, s.error));
    const res = s?.result;
    if (!res) return;
    const card = s.card;
    const rows = [];
    for (const pid of card.knobs) {
      const p = res.params?.[pid];
      if (!p) continue;
      if (p.status !== "ok") {
        rows.push({ pid, reason: p.reason ?? p.status });
        continue;
      }
      for (const [loopName, byCase] of Object.entries(p.loops ?? {})) {
        for (const [caseName, e] of Object.entries(byCase)) {
          rows.push({ pid, loop: loopName, case: caseName, e });
        }
      }
    }
    // 요약이 정본 표면이다 — 케이스 격자에서 답할 질문은 "최악이 어디서 얼마나"이고,
    // 케이스별 전체 표는 접힌 근거로 남는다 (전 행을 펼치면 15케이스 × 루프 수가 된다)
    const worst = openloopWorst(res.params, card.knobs);
    // 자릿수는 열마다 하나 (스윕 표와 같은 이유 — 같은 수가 다르게 찍히면 다른 수다)
    const fKnob = columnFormat(worst.map((w) => [w.knobFrom, w.knobTo]));
    const fPm = columnFormat(worst.map((w) => [w.pm?.from, w.pm?.to]));
    const fGm = columnFormat(worst.map((w) => [w.gm?.from, w.gm?.to]));
    const fRowPm = columnFormat(rows.map((r) => [r.e?.base?.pm_deg, r.e?.perturbed?.pm_deg]));
    const fRowGm = columnFormat(rows.map((r) => [r.e?.base?.gm_db, r.e?.perturbed?.gm_db]));
    olBox.append(
      el("h3", { style: "margin:0 0 4px;font-size:14px" },
        `개루프 마진 (2단) — 섭동 ${fmtPercent(res.probe_rel)} · 케이스 전체에서 최악`),
      // 요약 대상이 없으면 표 대신 사유 — 빈 표는 버그로 읽힌다
      !worst.length
        ? el("p", { class: "hint", style: "margin:4px 0 0" },
            "요약 없음 — 이 손잡이에는 선언된 루프의 유효한 Δ가 없다 " +
            "(스케줄이 덮거나 루프 미선언). 사유는 케이스별 전체 표에 있다.")
        : el("div", { class: "scroll-x" },
            el("table", {},
              el("thead", {}, el("tr", {},
                ["손잡이 (얼마→얼마)", "루프", "케이스 수", "최악 PM (기준→섭동)",
                 "최악 GM (기준→섭동)"].map((h) => el("th", {}, h)))),
              el("tbody", {}, worst.map((w) =>
                el("tr", {},
                  el("td", {},
                    el("code", { style: `${mono()};white-space:nowrap` }, w.param),
                    // 같은 전이를 판독대와 여기가 다른 자릿수로 찍으면 두 수로 읽힌다
                    el("div", { style: `font-size:11px;color:${SKIN.inkDim}` },
                      fmtPair(w.knobFrom, w.knobTo, fKnob).join(" → "))),
                  el("td", {}, el("code", { style: mono() }, w.loop)),
                  el("td", { class: "num" }, String(w.nCases)),
                  el("td", { class: "num" },
                    w.pm ? transCell(w.pm.from, w.pm.to, w.pm.value, "°", fPm) : "—",
                    w.pm ? el("div", { style: `font-size:11px;color:${SKIN.inkDim}` },
                      `@${w.pm.case}`) : null),
                  el("td", { class: "num" },
                    w.gm ? transCell(w.gm.from, w.gm.to, w.gm.value, "dB", fGm) : "—",
                    w.gm ? el("div", { style: `font-size:11px;color:${SKIN.inkDim}` },
                      `@${w.gm.case}`) : null),
                ))),
            )),
      el("details", { style: "margin-top:8px" },
        el("summary", { class: "hint", style: "cursor:pointer" },
          `케이스별 전체 표 (${rows.length}행)`),
        el("div", { class: "scroll-x", style: "margin-top:6px" },
          el("table", {},
            el("thead", {}, el("tr", {},
              ["손잡이", "루프", "케이스", "PM (기준→섭동)", "GM (기준→섭동)", "비고"]
                .map((h) => el("th", {}, h)))),
            el("tbody", {}, rows.map((r) =>
              el("tr", {},
                el("td", {}, el("code", { style: mono() }, r.pid)),
                el("td", {}, r.loop ? el("code", { style: mono() }, r.loop) : "—"),
                el("td", {}, r.case ?? "—"),
                el("td", { class: "num" }, r.e?.delta
                  ? transCell(r.e.base?.pm_deg, r.e.perturbed?.pm_deg, r.e.delta.pm_deg,
                      "°", fRowPm)
                  : "—"),
                el("td", { class: "num" }, r.e?.delta
                  ? transCell(r.e.base?.gm_db, r.e.perturbed?.gm_db, r.e.delta.gm_db,
                      "dB", fRowGm)
                  : "—"),
                el("td", { class: "hint" }, r.reason ?? r.e?.note ?? ""),
              ))),
          ))),
      el("p", { class: "hint", style: "margin:6px 0 0" },
        "개루프는 피드백이 얼어 있는 근사다 — 스케줄이 덮는 자리·루프 선언이 없는 " +
        "자리는 Δ=0으로 위장하지 않고 사유로 남는다. 폐루프 확증은 스윕(3단) 몫이다."),
    );
  }

  async function runScan() {
    let cases;
    try {
      cases = gridCases();
    } catch (e) {
      state.scan = { status: "격자 입력 오류", result: null,
        error: errorText(e), selected: null };
      renderScan();
      runStatus("스캔: 격자 입력 오류", { open: "sweep", bad: true });
      return;
    }
    state.scan = { status: `전 케이스 스캔 제출 — 케이스 ${cases.length}건`,
      result: null, error: null, selected: null };
    renderScan();
    runStatus(state.scan.status);
    try {
      const job = await api.post("/influence/scan", scanRequest(shapeState(), {
        cases, tSettle: 5, tStep: Number(stepIn.value) || 15,
        fingerprint: state.diag?.fingerprint,
      }));
      const done = await watchJob(job.id, (j) => {
        state.scan.status =
          `스캔 ${Math.round((j.progress ?? 0) * 100)}% — ${j.message ?? ""}`;
        scanStatusLine.textContent = state.scan.status;
        runStatus(state.scan.status);
      });
      state.scan.status = done.status === "done"
        ? "완료" : `스캔 ${done.status} — 완료 케이스는 보존된다`;
      if (done.result_id) {
        state.scan.result = await api.get(`/results/${done.result_id}`);
        // 결함 케이스 전부가 기본 선택 — 체크박스로 3단 B 대상을 조정한다
        state.scan.selected = new Set(scanSummary(state.scan.result).badCaseNames);
      }
      renderScan();
      runStatus(`전 케이스 스캔 ${state.scan.status}`,
        { open: "sweep", bad: done.status !== "done" });
    } catch (e) {
      state.scan.status = "실패";
      state.scan.error = errorText(e);
      renderScan();
      runStatus("전 케이스 스캔 실패", { open: "sweep", bad: true });
    }
  }

  // 결함 케이스 선택 — 판정이 난 경우와 전부 잘려 판정이 없는 경우 양쪽에서 쓴다
  // (잘린 케이스도 B 대상이라 선택 자리가 없으면 손으로 넣을 방법이 사라진다)
  function appendCaseSelect(sum, s) {
    if (!sum.badCaseNames.length) {
      // 고를 것이 없는 이유가 두 가지다 — 잰 결과가 전부 문턱 안(정상)인 것과
      // 아예 잰 것이 없는 것. 후자를 "정상"이라 쓰면 한 번도 안 잰 격자를
      // 정상으로 위장하게 된다 (판정 0건 ≠ 전 케이스 정상)
      scanBox.append(el("p", { class: "hint", style: "margin:8px 0 0" },
        sum.verdicts.length
          ? "전 케이스 정상 — 부분 스윕으로 좁힐 결함 케이스가 없다. " +
            "3단 B는 격자 전체로 제출된다."
          : "고를 결함 케이스가 없다 — 판정이 없어 좁힐 근거도 없다. " +
            "3단 B는 격자 전체로 제출된다."));
      return;
    }
    const aborted = new Set(sum.abortedCases);
    scanBox.append(
      el("p", { class: "hint", style: "margin:8px 0 0" },
        "결함 케이스 — 체크된 케이스만 3단 B(부분 풀 스윕)에 들어간다" +
        (aborted.size ? " (발산으로 잘린 케이스 포함 — 판정은 못 냈지만 확인 대상이다)" : "") +
        ":"),
      el("div", { class: "row", style: "gap:12px;flex-wrap:wrap;margin-top:4px" },
        sum.badCaseNames.map((name) => {
          const cb = el("input", {
            type: "checkbox",
            onchange: () => {
              if (cb.checked) s.selected.add(name);
              else s.selected.delete(name);
            },
          });
          // result가 실린 스캔은 selected(Set)도 함께 실린다(runScan 불변식) —
          // 위 onchange의 s.selected.add와 같은 전제로 읽는다
          cb.checked = s.selected.has(name);
          return el("label", {
            class: "hint", style: "display:flex;gap:4px;align-items:center",
          }, cb, el("code", { style: mono() }, name),
            aborted.has(name)
              ? el("span", { style: `color:${WARN_INK};font-size:11px` }, "발산")
              : null);
        })),
    );
  }

  function renderScan() {
    renderTabCounts();  // 결과 유무가 칩 배지로 먼저 보인다 (서랍이 닫혀 있어도)
    clear(scanBox);
    const s = state.scan;
    scanStatusLine.textContent = s?.status ?? "";
    if (!s) return;
    if (s.error) {
      scanBox.append(el("div", { class: "error-box" }, s.error));
      return;
    }
    const res = s.result;
    if (!res) return;
    const sum = scanSummary(res);
    const fmtVal = (k, v) => (k.endsWith("_frac") ? fmtPercent(v) : fmtDelta(v));
    const appendWarnings = () => {
      for (const w of res.warnings ?? []) {
        scanBox.append(
          el("p", { style: `margin:4px 0;font-size:12px;color:${WARN_INK}` }, `⚠ ${w}`));
      }
    };
    // 판정 0건 ≠ 전 케이스 정상 — 잰 케이스가 없거나 전부 잘렸으면 판정 불가다.
    // 사유는 갈라진다: 취소로 안 돈 것과 다 돌았지만 전부 발산한 것은 다른 사실이다
    if (!sum.verdicts.length) {
      scanBox.append(el("p", { class: "hint", style: "margin:8px 0 0" },
        sum.abortedCases.length
          ? `판정 없음 — 잰 케이스가 전부 발산으로 잘렸다 (${sum.abortedCases.length}건). ` +
            "지표가 잘린 구간만의 값이라 국소성을 낼 수 없다 — 아래 케이스를 3단 B로 확인한다."
          : "판정 없음 — 완료된 케이스가 없다 (스캔이 케이스 완료 전에 취소·실패). " +
            "다시 스캔해야 3단 B 대상을 좁힐 수 있다."));
      appendCaseSelect(sum, s);
      appendWarnings();
      return;
    }
    // ① 지표별 국소성 판정 — 서버 diagnose_grid 판정을 그대로 그린다 (재계산 금지)
    scanBox.append(
      el("h3", { style: "margin:12px 0 4px;font-size:14px" },
        `전 케이스 스캔 (3단 A) — base 지표 케이스 ${res.rows?.length ?? 0}건 · ` +
        "국소성 판정"),
      el("div", { class: "scroll-x" },
        el("table", {},
          el("thead", {}, el("tr", {},
            ["지표", "판정", "처방 클래스", "결함 케이스", "문턱"].map((h) =>
              el("th", {}, h)))),
          el("tbody", {}, sum.verdicts.map((v) => {
            const ink = VERDICT_INK[v.verdict] ?? "#98989d";
            const cls = v.knobClass
              ? (KNOB_CLASS[v.knobClass]?.label ?? v.knobClass) : "—";
            return el("tr", {},
              el("td", {}, metricLabel(v.metric)),
              el("td", {}, el("span", {
                class: "flag",
                style: `background:${ink}26;color:${ink};font-weight:600`,
              }, VERDICT_LABEL[v.verdict] ?? v.verdict)),
              el("td", {}, cls),
              el("td", { class: "num" },
                `${v.nBad}/${v.nCases} (${fmtPercent(v.badFrac)})`),
              el("td", { class: "num" }, fmtVal(v.metric, v.threshold)),
            );
          })),
        )),
      el("p", { class: "hint", style: "margin:6px 0 0" },
        `국소(결함 ≤ ${fmtPercent(sum.localFrac)})면 스케줄 셀이, 전역이면 설계점 ` +
        "게인 수준이 처방 클래스다 — 어느 자리를 얼마나는 3단 B가 정량으로 답한다."),
    );
    // ② 케이스 × 지표 표 — 결함 셀 강조 (판정 소속은 서버 bad_cases가 정본)
    const keys = sum.verdicts.map((v) => v.metric);
    const badBy = new Map(sum.verdicts.map((v) => [v.metric, new Set(v.badCases)]));
    scanBox.append(
      el("div", { class: "scroll-x", style: "margin-top:8px" },
        el("table", {},
          el("thead", {}, el("tr", {},
            [el("th", {}, "케이스"), keys.map((k) => el("th", {}, metricLabel(k)))])),
          el("tbody", {}, (res.rows ?? []).map((r) =>
            el("tr", {},
              el("td", { style: "white-space:nowrap" }, r.case,
                // 발산으로 잘린 런의 지표는 잘린 구간만의 값 — 판정에서도 제외된다
                r.aborted
                  ? el("span", { style: `color:${WARN_INK}` }, " · 발산 중단")
                  : null),
              keys.map((k) =>
                el("td", {
                  class: "num",
                  style: badBy.get(k)?.has(r.case)
                    ? `color:${WARN_INK};font-weight:600` : "",
                }, fmtVal(k, r.metrics?.[k]))),
            ))),
        )),
    );
    // ③ 결함 케이스 선택 — 3단 B의 입력
    appendCaseSelect(sum, s);
    appendWarnings();
  }

  async function runSweep(card) {
    let cases;
    try {
      // 대상 결정은 순수 로직 — lib이 쥔다 (격자·스캔·선택 → 케이스 목록)
      cases = sweepCases(gridCases(), state.scan);
    } catch (e) {
      // submitted는 **표시 문자열과 분리된 판정**이다 — 구간 경향의 빈 상태가
      // "재지 않았다"와 "돌다가 깨졌다"를 갈라야 하는데, status 리터럴로 가르면
      // 문구에 사유 한 조각만 덧붙여도(「제출 불가 — 격자 불일치」) 조용히 반대편
      // 문장으로 떨어진다. 구분해야 할 사실은 "잡이 뜬 적이 있는가" 하나뿐이다
      state.sweep = { card, status: "제출 불가", result: null, submitted: false,
        error: errorText(e) };
      renderSweep();
      runStatus("스윕 제출 불가", { open: "sweep", bad: true });
      return;
    }
    // 런 수 추정: base + knob당 스팬 4점 + 쌍당 (동반 단독 + AB) 2점 — 실수로
    // 격자 전체를 제출해도 규모가 먼저 보이게 한다 (정확한 수는 sweep_plan 몫)
    const nRuns = 1 + card.knobs.length * 4 + pairsFor(card).length * 2;
    state.sweep = { card,
      status: `제출 중 — 케이스 ${cases.length}건 × 런 ~${nRuns}`,
      result: null, error: null, submitted: true };
    renderSweep();
    runStatus(state.sweep.status);
    try {
      const body = sweepRequest(shapeState(), {
        cases, knobs: card.knobs, pairs: pairsFor(card),
        tSettle: 5, tStep: Number(stepIn.value) || 15,
        fingerprint: state.diag?.fingerprint,
      });
      const job = await api.post("/influence/sweep", body);
      const done = await watchJob(job.id, (j) => {
        state.sweep.status =
          `스윕 ${Math.round((j.progress ?? 0) * 100)}% — ${j.message ?? ""}`;
        sweepStatusLine.textContent = state.sweep.status;
        runStatus(state.sweep.status);
        // 구간 경향의 빈 상태가 그 status를 문장에 끼워 넣는다 — 여기서 안 부르면
        // 5분짜리 스윕이 도는 내내 제출 시점 문구를 붙들고 있고 옆 서랍만 움직인다.
        // (돌고 있는 동안 이 서랍은 항상 빈 갈래라 텍스트 한 줄 교체가 전부다)
        renderTrend();
      });
      if (done.status !== "done") {
        state.sweep.status = `스윕 ${done.status} — 완료 런은 보존된다`;
      } else {
        state.sweep.status = "완료";
      }
      if (done.result_id) state.sweep.result = await api.get(`/results/${done.result_id}`);
      renderSweep();
      renderReadout();  // 판독대 3단 줄 — 서랍 안에만 두면 주 표면이 계속 "안 쟀다"다
      runStatus(`폐루프 스윕 ${state.sweep.status}`,
        { open: "sweep", bad: done.status !== "done" });
    } catch (e) {
      state.sweep.status = "실패";
      state.sweep.error = errorText(e);
      renderSweep();
      renderReadout();  // 실패했는데 판독대가 "아직 안 쟀다"로 남으면 거짓말이다
      runStatus("폐루프 스윕 실패", { open: "sweep", bad: true });
    }
  }

  function renderSweep() {
    renderTabCounts();  // 결과 유무가 칩 배지로 먼저 보인다 (서랍이 닫혀 있어도)
    // 같은 런에서 나오는 두 표면 — 한쪽만 갱신하면 서로 다른 스윕을 말한다.
    // 아래에 여러 조기 반환(오류·결과 없음)이 있으므로 **맨 앞**이어야 전부 덮는다
    renderTrend();
    clear(sweepBox);
    const s = state.sweep;
    sweepStatusLine.textContent = s?.status ?? "";
    if (!s) return;
    if (s.error) {
      sweepBox.append(el("div", { class: "error-box" }, s.error));
      return;
    }
    const res = s.result;
    if (!res) return;
    const keys = [...new Set(res.rows.flatMap((r) => Object.keys(r.metrics ?? {})))];
    const caseNames = [...new Set(res.rows.map((r) => r.case))];
    // 케이스별 기준값 — 전체 표의 각 행이 "얼마에서 얼마로"를 스스로 말하게 한다
    const baseOf = new Map(res.rows.filter((r) => r.label === "base")
      .map((r) => [r.case, r.metrics ?? {}]));
    // 자릿수는 **열마다 하나**다 — 행마다 정하면 같은 기준값이 40.8·40.847·40.85로
    // 세 번 다르게 찍혀, 한 열 안에서 다른 수처럼 읽힌다 (라이브에서 그렇게 나왔다)
    const fullFmt = Object.fromEntries(keys.map((k) => [k, columnFormat(
      res.rows.filter((r) => r.label !== "base")
        .map((r) => [baseOf.get(r.case)?.[k], r.metrics?.[k]]))]));
    const fullTable = el("div", { class: "scroll-x", style: "margin-top:8px" },
      el("table", {},
        el("thead", {}, el("tr", {},
          [el("th", {}, "런"), el("th", {}, "케이스"),
           keys.map((k) => el("th", {}, metricLabel(k)))])),
        el("tbody", {}, res.rows.map((r) =>
          el("tr", {},
            el("td", {},
              el("code", { style: `${mono()};white-space:nowrap` }, r.label)),
            el("td", { style: "white-space:nowrap" }, r.case),
            keys.map((k) => el("td", { class: "num" },
              r.label === "base"
                // 기준 행도 같은 자릿수 — 아래 행들의 왼쪽 수와 글자 그대로 같아야 한다
                ? `기준 ${fmtPair(r.metrics?.[k], r.metrics?.[k], fullFmt[k])[0]}`
                : transCell(baseOf.get(r.case)?.[k], r.metrics?.[k], r.delta?.[k], "",
                    fullFmt[k]))),
          ))),
      ));
    if (caseNames.length > 1) {
      // 다중 케이스 — 런별 최악 전이 요약이 정본 표면, 케이스×런 전체 표는 접힌 근거
      const worst = worstTransitions(res.rows);
      const worstFmt = Object.fromEntries(keys.map((k) => [k, columnFormat(
        Object.values(worst).map((m) => m[k]).filter(Boolean)
          .map((t) => [t.from, t.to]))]));
      sweepBox.append(
        el("h3", { style: "margin:0 0 4px;font-size:14px" },
          `폐루프 스윕 (3단 B) — 케이스 ${caseNames.length}건 · 런별 최악 (기준→섭동)`),
        el("div", { class: "scroll-x" },
          el("table", {},
            el("thead", {}, el("tr", {},
              [el("th", {}, "런"),
               keys.map((k) => el("th", {},
                 `${metricLabel(k)}${metricUnit(k) ? ` [${metricUnit(k)}]` : ""}`))])),
            el("tbody", {}, Object.entries(worst).map(([label, m]) =>
              el("tr", {},
                // nowrap — 좁은 셀에서 라벨이 세로로 꺾이면 행이 비대해진다.
                // 넘침은 scroll-x 컨테이너가 받는다
                el("td", {},
                  el("code", { style: `${mono()};white-space:nowrap` }, label)),
                keys.map((k) => el("td", { class: "num" },
                  m[k] ? transCell(m[k].from, m[k].to, m[k].delta, "", worstFmt[k]) : "—",
                  m[k] ? el("div", { style: `font-size:11px;color:${SKIN.inkDim}` },
                    `@${m[k].case}`) : null)),
              ))),
          )),
        el("details", { style: "margin-top:8px" },
          el("summary", { class: "hint", style: "cursor:pointer" },
            `케이스×런 전체 표 (${res.rows.length}행)`),
          fullTable),
      );
    } else {
      sweepBox.append(fullTable);
    }
    sweepBox.append(
      el("p", { class: "hint", style: "margin:6px 0 0" },
        "기준은 같은 케이스의 base 런이고 괄호 안이 Δ다 — " +
        "행마다 형상 지문이 계보로 저장되어 있다. " +
        "이 행들을 구간 × 지표 한 장으로 접은 것이 「구간 경향」 칩이다."),
    );
    if (res.nonadditivity?.length) {
      sweepBox.append(
        el("h3", { style: "margin:12px 0 4px;font-size:14px" }, "쌍별 비가산성 dAB − (dA+dB)"),
        el("div", { class: "scroll-x" },
          el("table", {},
            el("thead", {}, el("tr", {},
              [el("th", {}, "쌍"), el("th", {}, "케이스"),
               keys.map((k) => el("th", {}, metricLabel(k)))])),
            el("tbody", {}, res.nonadditivity.map((na) =>
              el("tr", {},
                el("td", {}, na.knobs.map((k) =>
                  el("code", { style: `${mono()};margin-right:6px` }, k))),
                el("td", {}, na.case),
                keys.map((k) => el("td", { class: "num" }, fmtDelta(na.values?.[k]))),
              ))),
          )),
        el("p", { class: "hint", style: "margin:6px 0 0" },
          "0에 가까우면 두 손잡이는 독립(따로 튜닝 가능), 크면 상호작용(같이 움직여야 한다). " +
          "판정 불가는 0이 아니라 —다."),
      );
    }
    for (const w of [...(res.warnings ?? []), ...(res.notes ?? [])]) {
      sweepBox.append(el("p", { style: `margin:4px 0;font-size:12px;color:${WARN_INK}` }, `⚠ ${w}`));
    }
  }

  // ── 구간 경향 (3단 C) — 손잡이 하나가 **전 구간**을 어느 쪽으로 미는가 ────
  //
  // 3단 B는 이 질문에 답하지 못했다. 요약 표는 런별 **최악 한 칸**만 내고(어디가
  // 제일 나쁜지는 알지만 엔벨로프를 따라 어느 쪽으로 기우는지는 모른다), 케이스×런
  // 전체 표는 사실을 다 갖고도 15케이스 × 9런 = 135행이라 경향이 행 사이에 흩어진다
  // — 사람이 눈으로 피벗해야 했다. 여기서는 **행이 구간**이라 세로로 한 번 훑으면
  // "이 게인을 올리면 저고도에서만 좋아지고 고고도에서는 나빠진다"가 그대로 읽힌다.
  //
  // 새로 재지 않는다: 3단 B가 이미 돈 런을 다시 세울 뿐이라 잡도 비용도 없다.
  // 그래서 서랍을 열기만 하면 즉시 뜬다(스캔·스윕과 달리 실행 버튼이 없다).
  const trendHead = el("div");
  const trendKnobRow = el("div", {
    class: "row", style: "gap:8px;flex-wrap:wrap;align-items:center;margin-top:8px",
  });
  const trendMetricRow = el("div", {
    class: "row", style: "gap:8px;flex-wrap:wrap;align-items:center;margin-top:10px",
  });
  // 서랍 안 순서: 머리 · 손잡이 칩 · ①구간×지표 · 지표 칩 · ②구간×스팬.
  // 지표 칩이 ①보다 위에 서면 "무엇을 고르는 칩인지"가 그 아래 표와 어긋난다
  const trendMatrixBox = el("div");
  const trendSpanBox = el("div");
  const trendKnobBtns = new Map();
  const trendMetricBtns = new Map();

  /** 선택 칩 줄 — 목록이 그대로면 **제자리에서** 눌림만 고친다.
   *
   * 다시 만들면 방금 누른 버튼이 DOM에서 들려 나가 포커스가 <body>로 떨어지고,
   * aria-pressed가 바뀌어도 낭독되지 않는다 — 프로세스 뷰 버튼과 같은 이유다.
   * 이 표는 손잡이·지표를 연달아 눌러 가며 읽는 화면이라 그 손실이 매번 일어난다.
   */
  function syncChips(row, btns, items, current, { caption, label, style, onPick }) {
    const same = btns.size === items.length && items.every((k) => btns.has(k));
    if (!same) {
      btns.clear();
      clear(row);
      if (items.length) row.append(el("span", { class: "hint" }, caption));
      for (const k of items) {
        const b = el("button", { style, onclick: () => onPick(k) }, label(k));
        btns.set(k, b);
        row.append(b);
      }
    }
    for (const [k, b] of btns) {
      const on = k === current;
      b.className = on ? "primary" : "";
      b.setAttribute("aria-pressed", on ? "true" : "false");
    }
  }

  // 스팬 라벨 — 「+10%」. 0.1 미만 스팬(사용자 지정)은 한 자리 더 낸다:
  // 0.5%가 「1%」로 뭉개지면 두 열이 같은 이름을 달고 선다
  const spanLabel = (s) =>
    `${s > 0 ? "+" : "−"}${fmtPercent(Math.abs(s), Math.abs(s) < 0.1 ? 1 : 0)}`;

  function renderTrend() {
    clear(trendHead);
    clear(trendMatrixBox);
    clear(trendSpanBox);
    const res = state.sweep?.result;
    const knobs = res?.rows?.length ? sweepKnobs(res.rows) : [];
    const noChips = { caption: "", label: (k) => k, style: "", onPick: () => {} };
    if (!knobs.length) {
      syncChips(trendKnobRow, trendKnobBtns, [], null, noChips);
      syncChips(trendMetricRow, trendMetricBtns, [], null, noChips);
      // 빈 이유 다섯은 **다른 사실**이다 — 뭉치면 지금 도는 스윕을 두고 "돌리면
      // 채워진다"고 하고, 실패한 스윕을 두고 "아직 없다"고 한다(v0.50이 판독대에서
      // 이미 한 번 고친 거짓말이다: 실패는 안 잰 것이 아니다).
      //
      // 마지막 갈래는 **상태를 단언하지 않는다.** "도는 중이다"라고 쓰면 종료된
      // 스윕까지 덮는다: 전 케이스 트림 미수렴은 `rows: []`로 **완료**되고, 제출
      // 직후 취소는 result_id 없이 끝난다 — 둘 다 error도 result도 없는 자리라
      // 「스윕이 도는 중이다 (완료)」 같은 자기모순이 나온다. 상태 문자열은 그대로
      // 보여 주되 그 해석은 status에 맡긴다
      const sw = state.sweep;
      const why = res?.rows?.length
        // 쌍 런만 돈 스윕 — 사실이 없는 것이 아니라 **이 표의 주어가 없는** 것이다
        ? "단독 런이 없다 — 이 스윕은 쌍 런(A&B)만 돌았다. 두 손잡이가 같이 움직인 Δ를 "
          + "한쪽의 경향으로 읽으면 귀속이 틀리므로 여기서는 세우지 않는다."
        // 제출 불가는 **정말 안 잰 것**이다 — 잡이 뜬 적이 없다. 돌다가 깨진 것과
        // 같은 문장으로 묶으면 "안 잰 것이 아니다"가 거짓말이 된다
        : sw?.error
          ? (sw.submitted
            ? "스윕이 돌다가 실패했다 — 안 잰 것이 아니다. 사유는 「스캔·스윕 Δ」 서랍에 "
              + "있고, 다시 돌리면 여기가 채워진다."
            : "스윕이 제출되지 않았다 — 아직 재지 않았다. 사유는 「스캔·스윕 Δ」 서랍에 "
              + "있고, 고쳐서 다시 누르면 여기가 채워진다.")
          : res
            ? "스윕은 끝났는데 행이 0건이다 — 케이스가 하나도 안 돌았다(전 케이스 트림 "
              + "미수렴 등). 사유는 「스캔·스윕 Δ」 서랍의 경고에 있다."
            : sw
              ? `스윕 상태: ${sw.status} — 결과가 저장되면 여기가 채워진다. `
                + "이 표는 새로 재지 않는다: 그 런을 구간별로 다시 세울 뿐이다."
              : "아직 없다 — 「진단·처방」에서 [이 부분공간 스윕 (3단 B)]을 돌리면 여기가 "
                + "채워진다. 이 표는 새로 재지 않는다: 3단 B가 이미 돈 런을 구간별로 "
                + "다시 세울 뿐이다.";
      trendHead.append(el("p", { class: "hint", style: "margin:0" }, why));
      return;
    }
    const knob = knobs.includes(state.trendKnob) ? state.trendKnob : knobs[0];
    state.trendKnob = knob;
    const tm = trendMatrix(res.rows, knob);
    syncChips(trendKnobRow, trendKnobBtns, knobs, knob, {
      caption: "손잡이", label: (k) => k, style: mono(),
      onPick: (k) => { state.trendKnob = k; renderTrend(); },
    });

    const stale = staleOf(res);
    trendHead.append(
      el("h3", { style: "margin:0 0 4px;font-size:14px" },
        `구간 경향 (3단 C) — 구간 ${tm.cases.length}건 × 스팬 ${tm.points.length}점 `
        + `(${tm.points.map((p) => spanLabel(p.span)).join(" · ")})`),
      el("p", { class: "hint", style: "margin:0" },
        "행이 구간이고 열이 지표다. 색은 방향이 아니라 **좋고 나쁨**이다 — 같은 ↑가 "
        + "실속마진에서는 개선이고 추종 RMS에서는 악화다. 기호는 색과 별도로 읽힌다."),
      el("p", { class: "hint", style: "margin:4px 0 0" },
        "이 표의 구간은 스윕이 **실제로 돈** 케이스뿐이다 — 3단 A에서 결함 케이스로 "
        + "좁혔다면 격자 전체가 아니다. 격자 전체의 base 지표는 스캔 표가 들고 있다."),
    );
    // el()과 달리 Node.append는 null을 **문자열 "null"로 붙인다** — 조건부 줄은
    // 삼항으로 넘기지 말고 여기서 가른다 (라이브에서 머리에 "null"이 찍혔다)
    if (stale) {
      trendHead.append(el("p", { style: `margin:4px 0 0;font-size:12px;color:${WARN_INK}` },
        `⚠ 이 수치는 형상 ${stale}에서 잰 것이다 — 지금 형상(${state.model?.fingerprint})과 `
        + "다르므로 다시 재야 한다."));
    }

    // 세울 지표가 **하나도 없으면** 여기서 끝낸다. 두 가지가 걸려 있다:
    // ① 없는 지표로 아래 ②를 지으려 들면 TypeError인데, renderTrend는 마운트에서
    //    불리므로 그 예외가 renderTabCounts·renderDrawer를 건너뛰어 **탭 전체가 안
    //    그려진다**(이 서랍만 비는 것이 아니다) ② 표를 먼저 짓고 나서 막으면 데이터
    //    열 0개에 합계 꼬리만 달린 껍데기가 남는다. 일부 지표가 판정 불가인 경우는
    //    아래 unmeasured가 이미 사유로 내고 있었고, 전부인 경우만 무방비였다
    if (!tm.metrics.length) {
      syncChips(trendMetricRow, trendMetricBtns, [], null, noChips);
      trendMatrixBox.append(el("p", { class: "hint", style: "margin:12px 0 0" },
        "이 손잡이로 세울 지표가 하나도 없다 — 전 구간에서 잰 값이 없다. "
        + "스윕이 케이스를 하나도 못 끝냈거나(취소·발산) 저장된 런에 지표가 없다."
        + (tm.unmeasured.length
          ? ` 값이 없는 지표: ${tm.unmeasured.map(metricLabel).join(", ")}.` : "")));
      return;
    }

    // ① 구간 × 지표 — 이 서랍의 「한눈에」. 칸 하나가 그 구간에서 이 지표가 어느
    //    쪽으로 가는지(기호·색)와 얼마나 가는지(+10%당 변화)를 함께 낸다
    const better = (k) => metricDef(k)?.better;
    const markCell = (t, k, text, title) => el("span", {
      style: `white-space:nowrap;color:${trendInk(t, better(k))}`, title,
    }, el("strong", {}, TREND_MARK[t]), text ? ` ${text}` : "");
    trendMatrixBox.append(
      el("div", { class: "scroll-x", style: "margin-top:12px" },
        el("table", {},
          el("thead", {}, el("tr", {},
            [el("th", {}, "구간"),
             tm.metrics.map((k) => el("th", { title: metricDef(k)?.desc ?? null },
               metricLabel(k),
               // 단위는 장식이 아니라 이 열의 수를 읽는 법이다 — inkFaint(30%)로
               // 두면 헤더가 「+10%당」만 읽히고 [rad]·[m]이 사라진다
               el("div", { style: `font-weight:400;color:${SKIN.inkDim}` },
                 `+10%당${metricUnit(k) ? ` [${metricUnit(k)}]` : ""}`)))])),
          el("tbody", {}, tm.cases.map((c) =>
            el("tr", {},
              el("td", { style: "white-space:nowrap" },
                el("code", { style: mono() }, c.name),
                // 잘린 런·안 돈 런이 섞인 구간은 곡선이 아니라 서로 다른 실험의
                // 나열이다 — 경향은 그대로 내되 그 사실을 행에 붙인다
                c.aborted.length
                  ? el("span", { style: `color:${WARN_INK};font-size:11px;margin-left:6px`,
                      title: `발산으로 잘린 런: ${c.aborted.join(", ")}` },
                      `발산 ${c.aborted.length}`)
                  : null,
                c.missing.length
                  ? el("span", { style: `color:${SKIN.inkFaint};font-size:11px;margin-left:6px`,
                      title: `안 돈 런: ${c.missing.join(", ")}` },
                      `미실행 ${c.missing.length}`)
                  : null),
              tm.metrics.map((k) => {
                const cell = c.cells[k];
                return el("td", { class: "num" }, markCell(cell.trend, k,
                  cell.slope == null ? "" : fmtChange(cell.slope, cell.rel, metricUnit(k)),
                  cell.reason ?? `${TREND_LABEL[cell.trend]} · +10%당 `
                    + `${fmtSigned(cell.slope)}${metricUnit(k) ? ` ${metricUnit(k)}` : ""}`
                    + ` · 폭 ${fmtDelta(cell.swing)}`));
              }),
            ))),
          // 열 하나를 세로로 다 훑지 않아도 그 지표의 전 구간 판정이 여기 선다
          el("tfoot", {}, el("tr", {},
            [el("th", {}, `합계 (구간 ${tm.cases.length})`),
             tm.metrics.map((k) => el("td", { class: "num" },
               Object.entries(tm.counts[k]).filter(([, n]) => n).map(([t, n]) =>
                 el("span", { style: `margin-left:8px;color:${trendInk(t, better(k))}`,
                   title: TREND_LABEL[t] }, `${TREND_MARK[t]}${n}`))))])),
        )),
    );
    if (tm.unmeasured.length) {
      trendMatrixBox.append(el("p", { class: "hint", style: "margin:6px 0 0" },
        `전 구간 판정 불가라 열에서 뺀 지표: ${tm.unmeasured.map(metricLabel).join(", ")} — `
        + "표준 진단 기동에는 접지도 웨이포인트도 없다. 「—」 열로 표를 채우는 대신 "
        + "여기 이름으로 남긴다(없는 지표가 아니라 이 기동이 못 재는 지표다)."));
    }

    // ② 지표 하나의 구간 × 스팬 — ①이 접은 곡선을 그대로 펼친 자리.
    //    ①은 기울기 한 수라 "어디서 꺾이는지"를 말할 수 없다
    const rank = (k) => Math.max(0, ...tm.cases.map((c) => Math.abs(c.cells[k].rel ?? 0)));
    const metric = tm.metrics.includes(state.trendMetric)
      ? state.trendMetric
      // 기본은 이 손잡이가 **가장 세게 미는** 지표 — 첫 화면이 곧 답인 경우가 많다
      : tm.metrics.reduce((a, b) => (rank(b) > rank(a) ? b : a), tm.metrics[0]);
    state.trendMetric = metric;
    syncChips(trendMetricRow, trendMetricBtns, tm.metrics, metric, {
      caption: "펼쳐 볼 지표", label: metricLabel, style: "",
      onPick: (k) => { state.trendMetric = k; renderTrend(); },
    });
    // 자릿수·표기는 **표마다 하나**다 (열마다 하나인 스윕 표의 확장) — 열이 전부
    // 같은 지표라, 열마다 따로 정하면 같은 값이 스팬 열마다 다르게 찍힌다
    const fmt = columnFormat(tm.cases.flatMap((c) =>
      c.cells[metric].values.map((v) => [c.cells[metric].base, v])));
    const unit = metricUnit(metric);
    trendSpanBox.append(
      el("h3", { style: "margin:14px 0 4px;font-size:14px" },
        `${metricLabel(metric)} — 구간 × 스팬${unit ? ` [${unit}]` : ""}`),
      el("div", { class: "scroll-x" },
        el("table", {},
          el("thead", {}, el("tr", {},
            [el("th", {}, "구간"),
             el("th", {}, "기준"),
             tm.points.map((p) => el("th", {},
               spanLabel(p.span),
               // 손잡이가 그때 실제로 놓인 값 — 두 열의 값이 같으면 범위 클립이다
               // (사유는 아래 스윕 서랍의 엔진 notes가 낸다)
               el("div", { style: `font-weight:400;color:${SKIN.inkDim};${mono()}` },
                 `=${fmtDelta(p.knobValue)}`))),
             el("th", {}, "경향"),
             el("th", {}, "감도 (+10%당)")])),
          el("tbody", {}, tm.cases.map((c) => {
            const cell = c.cells[metric];
            return el("tr", {},
              el("td", {}, el("code", { style: mono() }, c.name)),
              el("td", { class: "num", style: `color:${SKIN.inkDim}` },
                cell.base == null
                  ? fmtDelta(cell.rawBase) : fmtPair(cell.base, cell.base, fmt)[0]),
              // 유한값이 없으면 **서버가 준 것**을 그대로 낸다 — fmtDelta가 "inf"를
              // ∞로 찍는다. 발산한 런의 자리를 「—」로 적으면 같은 행의 「발산」
              // 배지와 정반대를 말한다(값이 없는 것과 ∞인 것은 다른 사실이다)
              cell.values.map((v, i) => el("td", { class: "num" },
                v == null ? fmtDelta(cell.raw[i]) : el("span", {},
                  fmtPair(cell.base ?? v, v, fmt)[1],
                  cell.base == null ? null
                    : el("div", { style: `font-size:11px;color:${SKIN.inkDim}` },
                        fmtSigned(v - cell.base))))),
              el("td", {}, markCell(cell.trend, metric, TREND_LABEL[cell.trend],
                cell.reason)),
              // 퍼센트 줄은 **읽힐 때만** 붙인다 — 0은 「−0.0%」로 찍혀 0에 방향이
              // 생기고, 0.1% 미만은 「±0.0%」로 뭉개져 "안 변했다"고 거짓말한다
              // (fmtChange가 절대 Δ로 갈아타는 바로 그 문턱 — 손으로 다시 찍으면서
              // 그 규칙만 빠져 있었다). 절대값은 바로 위 줄이 이미 낸다
              el("td", { class: "num" }, cell.slope == null ? "—" : el("span", {},
                `${fmtSigned(cell.slope)}${unit ? ` ${unit}` : ""}`,
                relReadable(cell.rel)
                  ? el("div", { style: `font-size:11px;color:${SKIN.inkDim}` },
                      fmtRel(cell.rel))
                  : null)),
            );
          })),
        )),
      el("p", { class: "hint", style: "margin:6px 0 0" },
        "값 아래 작은 수는 같은 구간 기준(base 런) 대비 Δ다. 감도는 기준을 포함한 "
        + "점들의 최소제곱 기울기라 **비단조 행에서는 평균일 뿐**이다 — 그 행은 "
        + "위 스팬 값을 직접 읽어야 어디서 꺾이는지가 보인다."),
    );
  }

  // ── 서랍 — 그래프 아래는 전부 여기 들어간다 (한 번에 하나) ────────────────
  // 두 개를 동시에 열 수 있게 하면 결국 다시 세로로 쌓인 패널 다섯 장이 된다.
  // 내용 박스(tableBox·diagBox…)는 **재사용**한다: 매번 새로 만들면 진단·스캔
  // 결과를 그린 DOM이 서랍을 닫을 때마다 버려져 다시 그려야 한다

  const drawerBox = el("div", { class: "tab-drawer" });

  // ── 실행 상태 — **서랍 밖**에 산다 ───────────────────────────────────────
  // 잡 셋(스캔·개루프·스윕)은 전부 진단 서랍의 버튼에서 출발하는데 결과는 다른
  // 서랍에 산다. 한 번에 하나만 열리므로, 진행률·실패를 그 서랍 안에만 쓰면 사용자가
  // 방금 누른 화면에서는 **아무것도 안 보인다** (스캔은 칩 배지도 안 붙어서 15케이스가
  // 통째로 무음이었다 — 재배치가 만든 회귀다). 그래서 여기 한 줄을 서랍 밖에 두고,
  // 끝나면 결과가 있는 서랍을 **열어 준다**: 결과를 찾아 헤매게 하지 않는다.
  const runLine = el("p", { class: "hint", style: "margin:8px 0 0;min-height:18px" });

  /** 잡 한 건의 상태 — text는 서랍 밖 한 줄, open은 끝난 뒤 열어 줄 서랍. */
  function runStatus(text, { open = null, bad = false } = {}) {
    clear(runLine);
    if (!text) return;
    runLine.append(el("span", { style: bad ? `color:${WARN_INK}` : "" }, text));
    if (open) {
      state.drawer = open;
      renderTabCounts();
      renderDrawer();
    }
  }

  const DRAWERS = [
    { key: "params", label: "파라미터",
      count: () => state.model?.params.length ?? 0,
      build: () => [el("h2", {}, "파라미터 — 이 형상에서 흔들 수 있는 전부"), tableBox] },
    { key: "diag", label: "진단·처방",
      count: () => state.diag?.prescriptions.length ?? null,
      build: () => [
        el("h2", {}, "진단 → 처방 → 스윕 — 무엇을 만질지, 그다음 얼마나 (2·3단)"),
        el("p", { class: "hint", style: "margin:0 0 8px" },
          "저장된 폐루프 런에서 결함을 귀속한다: 필터 병목인지 게인 미달인지, " +
          "포화를 어느 항이 주도하는지, 적분이 얼마나 막혀 있었는지. 처방 카드의 " +
          "손잡이(스케줄이 덮는 자리는 table.* 배율로 자동 승격)가 그대로 3단 스윕의 " +
          "입력이 된다 — 전 게인 공간이 아니라 처방 부분공간만 흔든다."),
        el("div", { class: "row", style: "gap:10px;align-items:center;flex-wrap:wrap" },
          resultInput,
          el("button", { class: "primary", onclick: runDiagnose }, "진단 실행")),
        el("div", {
          class: "row", style: "gap:10px;align-items:center;flex-wrap:wrap;margin-top:6px",
        },
          el("span", { class: "hint" }, "케이스 격자"),
          el("label", { class: "hint" }, "mach ", machFromIn, " ~ ", machToIn),
          el("label", { class: "hint" }, "간격 ", machStepIn),
          el("label", { class: "hint" }, "alt[m] ", altsIn),
          el("label", { class: "hint" }, "fuel[kg] ", fuelsIn),
          el("label", { class: "hint" }, "스텝 s ", stepIn),
          caseCountHint,
          el("span", { class: "grow" }),
          el("button", { onclick: runScan }, "전 케이스 스캔 (3단 A)")),
        el("div", { class: "row", style: "margin-top:6px" }, diagStatus),
        diagBox,
      ] },
    { key: "openloop", label: "개루프 Δ",
      count: () => (state.openloop?.result ? 1 : null),
      build: () => [olStatusLine, olBox, state.openloop?.result ? null
        : el("p", { class: "hint", style: "margin:0" },
            "아직 없다 — 「진단·처방」에서 진단을 돌린 뒤 처방 카드의 " +
            "[개루프 근거 (2단)]를 누르면 여기 채워진다.")] },
    { key: "sweep", label: "스캔·스윕 Δ",
      // 스캔도 센다 — 스윕만 세면 스캔 15케이스를 돌려도 칩에 아무 표시가 없어,
      // 서랍 밖에서는 그 일이 일어났다는 사실 자체가 안 보인다
      count: () => ((state.scan?.result ? 1 : 0) + (state.sweep?.result ? 1 : 0)) || null,
      build: () => [scanStatusLine, scanBox, sweepStatusLine, sweepBox,
        state.scan || state.sweep ? null
          : el("p", { class: "hint", style: "margin:0" },
              "아직 없다 — 「진단·처방」에서 [전 케이스 스캔]으로 결함 케이스를 좁힌 뒤 " +
              "처방 카드의 [이 부분공간 스윕]을 누른다. 여기가 폐루프 실측이다.")] },
    // 같은 스윕의 두 표면이지만 **묻는 것이 다르다**: 위는 "얼마나"(런별 최악 한 칸),
    // 여기는 "전 구간에서 어느 쪽으로". 한 서랍에 붙이면 표 넷이 다시 세로로 쌓인다
    { key: "trend", label: "구간 경향",
      count: () => (state.sweep?.result?.rows?.length
        ? sweepKnobs(state.sweep.result.rows).length || null : null),
      build: () => [trendHead, trendKnobRow, trendMatrixBox,
        trendMetricRow, trendSpanBox] },
    // 경고는 **있을 때만** 칩이 선다 — 항상 서 있으면 0을 세는 칩이 되고,
    // 그러면 경고가 생겼다는 사실 자체가 화면에서 안 보인다.
    // 범례는 여기 없다: 색이 칠해진 그래프가 늘 떠 있는데 범례를 클릭 뒤로 숨기면
    // 화면이 자기가 쓴 색을 설명하지 않는 상태가 된다 (캔버스 바로 아래에 둔다)
    { key: "warn", label: "⚠ 경고", hidden: () => !state.model?.warnings.length,
      count: () => (state.model?.warnings.length || null),
      build: () => [warnBox] },
  ];

  const drawerTabs = new Map();

  function renderDrawer() {
    for (const [key, btn] of drawerTabs) {
      btn.setAttribute("aria-expanded", state.drawer === key ? "true" : "false");
    }
    clear(drawerBox);
    const d = DRAWERS.find((x) => x.key === state.drawer);
    if (!d) return;
    for (const node of d.build()) if (node) drawerBox.append(node);
  }

  const tabBar = el("div", { class: "tab-chips" },
    DRAWERS.map((d) => {
      const btn = el("button", {
        class: "tab-chip", "aria-expanded": "false", "aria-controls": "influence-drawer",
        onclick: () => {
          state.drawer = state.drawer === d.key ? null : d.key;
          renderDrawer();
        },
      }, d.label);
      drawerTabs.set(d.key, btn);
      return btn;
    }));
  drawerBox.id = "influence-drawer";

  /** 칩의 개수 배지 — 결과가 생겼는데 서랍이 닫혀 있으면 무슨 일이 있었는지가
   *  화면에서 사라진다. 셀 것이 없는 칩(count가 null)은 배지 자체가 없다.
   *  숨은 칩이 열려 있던 상태로 남으면 서랍만 떠 있고 여는 버튼이 없다 — 같이 닫는다. */
  function renderTabCounts() {
    let closed = false;
    for (const d of DRAWERS) {
      const btn = drawerTabs.get(d.key);
      const hidden = d.hidden?.() ?? false;
      btn.hidden = hidden;
      if (hidden && state.drawer === d.key) {
        state.drawer = null;
        closed = true;
      }
      const n = d.count();
      clear(btn).append(d.label);
      if (n) btn.append(el("span", { class: "n" }, String(n)));
    }
    // 여는 버튼이 사라졌으면 서랍도 여기서 닫는다 — 호출부에 맡기면 어느 한 곳이
    // 잊는 순간 닫을 수 없는 서랍이 남는다 (renderDrawer는 여기를 안 부르므로 재귀 없음)
    if (closed) renderDrawer();
  }

  canvas = createInfluenceCanvas({
    width: CANVAS_W,
    height: CANVAS_H,
    getModel: () => state.model,
    getLayout: () => state.layout,
    getSelection: () => state.selection,
    getCone: () => state.cone,
    getPlay: () => state.play,
    onSelect: select,
    onCaption: (text) => { playLine.textContent = text; },
    onLayer: setActiveLayer,
  });
  canvasBox.append(canvas.root);

  load();
  // 탭을 떠났다 와도 진단·개루프·스캔·스윕 결과는 다시 그린다 (모듈 스코프 state 규약)
  if (state.diag) renderDiag();
  if (state.openloop?.result) renderOpenloop();
  if (state.scan) renderScan();
  // 스윕이 있으면 renderSweep이 renderTrend까지 부른다. 없어도 한 번은 불러야
  // 서랍이 **왜 비었는지**를 말한다 (안 부르면 첫 방문에 빈 서랍이 열린다)
  if (state.sweep) renderSweep();
  else renderTrend();
  renderTabCounts();
  renderDrawer();

  return el("div", { class: "inf-dark tab-dark tab-page" },
    // 카드 없는 머리 — 블록도 최상위(.bd .pagetop)와 같은 자리
    el("div", { class: "tab-top" },
      el("h1", {}, "영향성"),
      el("div", { class: "tab-subline" },
        el("p", {}, "값 하나를 고르면 ", el("b", {}, "얼마에서 얼마로"),
          " 가는지, 그때 마진과 설계 지표가 얼마에서 얼마로 가는지."),
        el("div", { class: "row", style: "gap:8px" },
          processBtn,
          el("button", { onclick: load }, "다시 계산"))),
      el("div", { class: "row", style: "margin-top:6px" }, statusLine),
      errBox,
    ),
    // 그래프 — 카드 밖, 페이지 위에 그대로 (캔버스가 자기 테두리를 갖는다).
    // 범례·보존 캐비앳은 그림 바로 아래: 그림이 쓴 색과 굵기를 설명하는 자리라
    // 클릭 뒤로 숨기면 화면이 자기 문법을 말하지 않게 된다
    el("div", { class: "inf-stage" },
      canvasBox, playLine, pathBox,
      el("div", { style: "margin-top:10px" }, legendBox),
      conservedNote),
    readoutBox,
    tabBar,
    runLine,  // 잡 상태는 서랍 밖 — 버튼이 있는 서랍과 결과가 사는 서랍이 다르다
    drawerBox,
  );
}

function badge(stateKey) {
  // 바탕 알파 26(15%) — 다크 표면에서 1a(10%)는 칩 윤곽이 사라진다
  return el("span", {
    class: "flag",
    style: `background:${STATE_INK[stateKey]}26;color:${STATE_INK[stateKey]};` +
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
