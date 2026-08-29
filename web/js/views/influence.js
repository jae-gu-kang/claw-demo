/** 영향성 탭 — 파라미터 하나가 전체 시스템에 어떻게 번지는지 (02 §2.4, M15).

이 화면의 주 질문은 "이 값을 바꾸면 무엇이 얼마나 달라지나"이고, 답을 세 단으로 낸다:
구조 도달성(즉시) · 개루프 Δ(잡) · 폐루프 스윕(잡). 세 단이 다 붙어 있고, 2·3단
앞에는 진단이 선다 — "얼마나"를 재기 전에 "무엇을 만질지"(필터/게인/클램프/리미터/
스케줄, 단독/동시)를 저장된 런에서 귀속하고, 처방 카드의 손잡이만 스윕한다.

**표가 정본 표면이고 캔버스는 보조다.** 캔버스는 보조기술에 불투명하므로, 화면이
말하는 모든 사실(상태·도달 개수·도달 출력)은 아래 표에도 반드시 있다 — wpmap.js가
웨이포인트 표에 접근성을 맡긴 것과 같은 규약.

이 탭은 **전면 다크**다: 검은 캔버스가 화면의 중심이라 패널만 밝으면 경계마다
스킨이 끊긴다. DOM 쪽 다크는 app.css의 `.inf-dark` 스코프가 담당하고(루트에
클래스 하나 — 다른 탭 불변), JS가 그리는 색(캔버스·배지·경고)만 인라인이다.
*/

import { api, errorText, watchJob } from "../api.js";
import { clear, el } from "../dom.js";
import {
  BAND_COLOR, DIRECTION_LABEL, KNOB_CLASS, SKIN, STATE_COLOR, STATE_INK,
  STATE_LABEL, STATE_NOTE, WARN_INK,
  coneOf, diagnoseRequest, edgeVia, fmtDelta, fmtPercent, nodeDetail,
  normalizeDiagnosis, normalizeGraph, pairsFor, radiusOf, structuralRequest,
  sweepRequest,
} from "../lib/influence.js";
import { conePlayback, summaryOf } from "../lib/influenceplay.js";
import { cascadeLayout, layeredLayout } from "../lib/influencelayout.js";
import { createInfluenceCanvas } from "./influencecanvas.js";
import { store } from "../store.js";

const CANVAS_W = 1180;
const CANVAS_H = 660;
const ROW_GAP = 19;

// 뷰 재생성마다 처음으로 돌아가지 않도록 모듈 스코프 (autocode.js·sim.js와 같은 패턴)
const state = {
  variant: "cascade", selection: null, model: null, layout: null,
  cone: null, play: null,
  // 진단(2단 앞의 "무엇을") · 스윕(3단 "얼마나") — 탭을 떠났다 와도 결과 유지
  diag: null, sweep: null,
};
let canvas = null;

// 성운(radial)은 삭제됐고 **전파 폭포가 기본**이다. 재생 일정은 배치와 무관한 위상
// 랭크이므로(influenceplay.js) 「프로세스 뷰」(레이어 활성망)로 전환해도 같은 재생·
// 같은 경로 패널을 공유한다 — 배치만 바꿔 같은 파라미터의 전파를 비교할 수 있다
const LAYOUT_FN = { layered: layeredLayout, cascade: cascadeLayout };

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
  const detailBox = el("div");
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
    renderDetail();
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
    renderDetail();
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
      // 재생이 보여 주는 순서를 **글로도** 남긴다 — 캔버스만 아는 사실을 만들지 않는다.
      // 캔버스 아래 줄은 재생 중 흘러가지만 이쪽은 선택마다 한 번 갱신되는 정적 사실이라
      // 스크린리더가 요청할 때 읽는다(그래서 저쪽이 aria-hidden이어도 손실이 없다)
      state.play
        ? el("p", { class: "hint", style: "margin:6px 0 0" },
            summaryOf(state.play, (id) => m.byId.get(id)?.label ?? id))
        : el("span"),
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
              // 선택 강조 .25 — 라이트 시절의 .09는 #1c1c1e 위에서 식별 불가
              style: `cursor:pointer${p.id === state.selection ? ";background:rgba(10,132,255,.25)" : ""}`,
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
  const sweepStatusLine = el("p", { class: "hint", style: "margin:6px 0 0" });
  const sweepBox = el("div");
  const resultInput = el("input", {
    type: "text", placeholder: "sim 결과 id",
    value: store.get("simResult")?.id ?? "",
    style: `${mono()};width:230px`,
  });
  const numIn = (val, width = 70) =>
    el("input", { type: "number", value: val, step: "any", style: `width:${width}px` });
  const machIn = numIn(0.6);
  const altIn = numIn(1000);
  const fuelIn = numIn(200);
  const stepIn = numIn(15);

  const metricLabel = (key) =>
    (state.model?.metrics ?? []).find((m) => m.key === key)?.label ?? key;

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
            }, "이 부분공간 스윕 (3단)"),
          ),
        );
      })));
  }

  const olStatusLine = el("p", { class: "hint", style: "margin:6px 0 0" });
  const olBox = el("div");

  async function runOpenloop(card) {
    const cases = [{
      name: "sweep",
      mach: Number(machIn.value), alt: Number(altIn.value), fuel: Number(fuelIn.value),
    }];
    olStatusLine.textContent = "개루프 Δ 계산 중…";
    clear(olBox);
    try {
      const job = await api.post("/influence/openloop", {
        ...structuralRequest(shapeState()),
        cases, params: card.knobs, fingerprint: state.diag?.fingerprint,
      });
      const done = await watchJob(job.id, (j) => {
        olStatusLine.textContent =
          `개루프 ${Math.round((j.progress ?? 0) * 100)}% — ${j.message ?? ""}`;
      });
      if (done.status !== "done" || !done.result_id) {
        olStatusLine.textContent = `개루프 ${done.status}`;
        return;
      }
      const res = await api.get(`/results/${done.result_id}`);
      olStatusLine.textContent = "";
      renderOpenloop(card, res);
    } catch (e) {
      olStatusLine.textContent = "개루프 실패";
      clear(olBox).append(el("div", { class: "error-box" }, errorText(e)));
    }
  }

  function renderOpenloop(card, res) {
    clear(olBox);
    const rows = [];
    for (const pid of card.knobs) {
      const p = res.params?.[pid];
      if (!p) continue;
      if (p.status !== "ok") {
        rows.push([pid, "—", "—", "—", "—", p.reason ?? p.status]);
        continue;
      }
      for (const [loopName, byCase] of Object.entries(p.loops ?? {})) {
        for (const [caseName, e] of Object.entries(byCase)) {
          rows.push([pid, loopName, caseName,
            e?.base ? `${fmtDelta(e.base.pm_deg)}° / ${fmtDelta(e.base.gm_db)} dB` : "—",
            e?.delta ? `${fmtDelta(e.delta.pm_deg)}° / ${fmtDelta(e.delta.gm_db)} dB` : "—",
            e?.note ?? ""]);
        }
      }
    }
    olBox.append(
      el("h3", { style: "margin:12px 0 4px;font-size:14px" },
        `개루프 마진 근거 (2단) — 섭동 ${fmtPercent(res.probe_rel)}`),
      el("div", { class: "scroll-x" },
        el("table", {},
          el("thead", {}, el("tr", {},
            ["손잡이", "루프", "케이스", "기준 PM/GM", "Δ PM/GM", "비고"].map((h) =>
              el("th", {}, h)))),
          el("tbody", {}, rows.map((r) =>
            el("tr", {}, r.map((c, i) =>
              el("td", i < 2 ? {} : { class: "num" },
                i < 2 ? el("code", { style: mono() }, c) : c))))),
        )),
      el("p", { class: "hint", style: "margin:6px 0 0" },
        "개루프는 피드백이 얼어 있는 근사다 — 스케줄이 덮는 자리·루프 선언이 없는 " +
        "자리는 Δ=0으로 위장하지 않고 사유로 남는다. 폐루프 확증은 스윕(3단) 몫이다."),
    );
  }

  async function runSweep(card) {
    const cases = [{
      name: "sweep",
      mach: Number(machIn.value), alt: Number(altIn.value), fuel: Number(fuelIn.value),
    }];
    state.sweep = { card, status: "제출 중…", result: null, error: null };
    renderSweep();
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
      });
      if (done.status !== "done") {
        state.sweep.status = `스윕 ${done.status} — 완료 런은 보존된다`;
      } else {
        state.sweep.status = "완료";
      }
      if (done.result_id) state.sweep.result = await api.get(`/results/${done.result_id}`);
      renderSweep();
    } catch (e) {
      state.sweep.status = "실패";
      state.sweep.error = errorText(e);
      renderSweep();
    }
  }

  function renderSweep() {
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
    sweepBox.append(
      el("div", { class: "scroll-x", style: "margin-top:8px" },
        el("table", {},
          el("thead", {}, el("tr", {},
            [el("th", {}, "런"), el("th", {}, "케이스"),
             keys.map((k) => el("th", {}, `Δ ${metricLabel(k)}`))])),
          el("tbody", {}, res.rows.map((r) =>
            el("tr", {},
              el("td", {}, el("code", { style: mono() }, r.label)),
              el("td", {}, r.case),
              keys.map((k) => el("td", { class: "num" },
                r.label === "base"
                  ? `기준 ${fmtDelta(r.metrics?.[k])}`
                  : fmtDelta(r.delta?.[k]))),
            ))),
        )),
      el("p", { class: "hint", style: "margin:6px 0 0" },
        "Δ는 base 런 대비다 — 행마다 형상 지문이 계보로 저장되어 있다."),
    );
    if (res.nonadditivity?.length) {
      sweepBox.append(
        el("h3", { style: "margin:12px 0 4px;font-size:14px" }, "쌍별 비가산성 dAB − (dA+dB)"),
        el("div", { class: "scroll-x" },
          el("table", {},
            el("thead", {}, el("tr", {},
              [el("th", {}, "쌍"), keys.map((k) => el("th", {}, metricLabel(k)))])),
            el("tbody", {}, res.nonadditivity.map((na) =>
              el("tr", {},
                el("td", {}, na.knobs.map((k) =>
                  el("code", { style: `${mono()};margin-right:6px` }, k))),
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
  // 탭을 떠났다 와도 진단·스윕 결과는 다시 그린다 (모듈 스코프 state 유지 규약)
  if (state.diag) renderDiag();
  if (state.sweep) renderSweep();

  return el("div", { class: "inf-dark" },
    el("div", { class: "panel" },
      el("h2", {}, "영향성 — 설계값 연계·정량 영향성 평가 (02 §2.4)"),
      el("div", { class: "row", style: "gap:14px;align-items:center" },
        el("span", { class: "grow" }),
        processBtn,
        el("button", { onclick: load }, "다시 계산"),
      ),
      el("div", { class: "row", style: "margin-top:6px" }, statusLine),
      warnBox,
      errBox,
    ),
    el("div", { class: "panel" },  // 다크 표면은 .inf-dark 스코프가 준다 — 인라인 중복 금지
      canvasBox,
      playLine,
      pathBox,
      el("div", { style: "margin-top:10px" }, legendBox),
      conservedNote,
    ),
    el("div", { class: "panel" }, detailBox),
    el("div", { class: "panel" },
      el("h2", {}, "파라미터"),
      tableBox,
    ),
    el("div", { class: "panel" },
      el("h2", {}, "진단 → 처방 → 스윕 — 무엇을 만질지, 그다음 얼마나 (2·3단)"),
      el("p", { class: "hint", style: "margin:0 0 8px" },
        "저장된 폐루프 런에서 결함을 귀속한다: 필터 병목인지 게인 미달인지, " +
        "포화를 어느 항이 주도하는지, 적분기가 클램프에 주차했는지. 처방 카드의 " +
        "손잡이(스케줄이 덮는 자리는 table.* 배율로 자동 승격)가 그대로 3단 스윕의 " +
        "입력이 된다 — 전 게인 공간이 아니라 처방 부분공간만 흔든다."),
      el("div", { class: "row", style: "gap:10px;align-items:center;flex-wrap:wrap" },
        resultInput,
        el("button", { class: "primary", onclick: runDiagnose }, "진단 실행"),
        el("span", { class: "grow" }),
        el("span", { class: "hint" }, "스윕 케이스"),
        el("label", { class: "hint" }, "mach ", machIn),
        el("label", { class: "hint" }, "alt ", altIn),
        el("label", { class: "hint" }, "fuel ", fuelIn),
        el("label", { class: "hint" }, "스텝 s ", stepIn),
      ),
      el("div", { class: "row", style: "margin-top:6px" }, diagStatus),
      diagBox,
      olStatusLine,
      olBox,
      sweepStatusLine,
      sweepBox,
    ),
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
