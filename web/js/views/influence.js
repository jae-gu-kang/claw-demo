/** 영향성 탭 — 파라미터 하나가 전체 시스템에 어떻게 번지는지 (02 §2.4, M15).

이 화면의 주 질문은 "이 값을 바꾸면 무엇이 얼마나 달라지나"이고, 답을 세 단으로 낸다:
구조 도달성(즉시) · 개루프 Δ(잡) · 폐루프 스윕(잡). 세 단이 다 붙어 있고, 2·3단
앞에는 진단이 선다 — "얼마나"를 재기 전에 "무엇을 만질지"(필터/게인/클램프/리미터/
스케줄, 단독/동시)를 저장된 런에서 귀속하고, 처방 카드의 손잡이만 스윕한다.

**표가 정본 표면이고 캔버스는 보조다.** 캔버스는 보조기술에 불투명하므로, 화면이
말하는 모든 사실(상태·도달 개수·도달 출력)은 아래 표에도 반드시 있다 — wpmap.js가
웨이포인트 표에 접근성을 맡긴 것과 같은 규약.

스타일은 인라인이다: app.css는 병행 세션 작업 중이라 건드리지 않는다.
*/

import { api, errorText, watchJob } from "../api.js";
import { clear, el } from "../dom.js";
import {
  BAND_COLOR, DIRECTION_LABEL, KNOB_CLASS, SKIN, STATE_COLOR, STATE_INK,
  STATE_LABEL, STATE_NOTE, WARN_INK,
  coneOf, diagnoseRequest, fmtDelta, fmtPercent, normalizeDiagnosis,
  normalizeGraph, pairsFor, radiusOf, structuralRequest, sweepRequest,
} from "../lib/influence.js";
import { conePlayback, graphDepth, summaryOf } from "../lib/influenceplay.js";
import { cascadeLayout, layeredLayout, radialLayout } from "../lib/influencelayout.js";
import { createInfluenceCanvas } from "./influencecanvas.js";
import { store } from "../store.js";

const CANVAS_W = 1180;
const CANVAS_H = 660;
const ROW_GAP = 19;

// 뷰 재생성마다 처음으로 돌아가지 않도록 모듈 스코프 (autocode.js·sim.js와 같은 패턴)
const state = {
  variant: "layered", selection: null, model: null, layout: null,
  cone: null, play: null, depth: 0,
  // 진단(2단 앞의 "무엇을") · 스윕(3단 "얼마나") — 탭을 떠났다 와도 결과 유지
  diag: null, sweep: null,
};
let canvas = null;

// 층 수는 **데이터에서 온다**. 문구에 박아 두면(전에는 "16층"이었다) 엔진이 노드를
// 하나 늘리는 순간 자막의 층 수와 어긋나 화면이 조용히 거짓말한다 (02 §5.5)
// d가 0인 경우가 **영구히 남을 수 있다**: rebuild()는 모델이 없으면 즉시 반환하므로
// 첫 로드가 실패하면 층 수가 영영 안 채워진다. 그때 「0층」을 내보이면 하드코딩을
// 걷어낸 자리에 더 틀린 수를 넣는 꼴이라, 수가 없으면 수를 말하지 않는다
const VARIANTS = [
  ["layered", "A · 레이어 활성망",
   (d) => `좌→우 ${d > 0 ? `${d}층` : "층 구조"}(파라미터·입력 → IR → 출력·기체·지표) — `
     + "IR 구간의 층 번호가 곧 실행 순서이자 생성 C의 문장 순서다. 경로 추적이 쉽다"],
  ["radial", "B · 영향 성운",
   () => "동심원 4겹 + 묶음 허브로 다발 묶기 — 바깥이 파라미터, 중심이 지표. 얽힘의 규모가 한눈에"],
  ["cascade", "C · 전파 폭포",
   (d) => `${d > 0 ? `${d}층을` : "층 구조를"} 모듈 밴드로 접어 굵은 흐름으로 — `
     + "어느 모듈을 지나는지가 덩어리로 읽힌다"],
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
    style: "position:relative;border-radius:16px;overflow:hidden;background:#000",
  });

  const variantRow = el("div", { class: "row", style: "gap:6px" });
  // 버튼은 한 번만 만들고 **제자리에서 고친다.** 행을 다시 만들면 방금 누른 버튼이 DOM에서
  // 들려 나가 키보드 포커스가 <body>로 떨어지고, aria-pressed가 바뀌어도 낭독되지 않는다
  const variantBtns = VARIANTS.map(([key, label]) =>
    el("button", {
      onclick: () => {
        state.variant = key;
        renderVariants();  // 눌린 버튼이 안 바뀌면 지금 무엇을 보고 있는지 알 수 없다
        rebuild();
      },
    }, label));
  variantRow.append(...variantBtns);
  function renderVariants() {
    VARIANTS.forEach(([key, , note], i) => {
      const on = key === state.variant;
      const b = variantBtns[i];
      b.className = on ? "primary" : "";
      b.setAttribute("aria-pressed", on ? "true" : "false");
      b.title = note(state.depth ?? 0);
    });
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
    renderVariants();  // 툴팁도 층 수를 쓴다 — 생성 시점의 state.depth는 아직 0이다
    renderTable();
    renderDetail();
    renderVariantNote();
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
    state.depth = graphDepth(state.model);
    state.cone = state.selection ? coneOf(state.model, state.selection) : null;
    state.play = state.cone ? conePlayback(state.model, state.cone) : null;
  }

  function select(id) {
    const n = id ? state.model?.byId.get(id) : null;
    // 노드를 눌러도 파라미터가 아니면 선택을 바꾸지 않는다 — 원뿔의 주어는 파라미터다
    state.selection = n?.kind === "param" ? id : id === null ? null : state.selection;
    recompute();
    if (!state.cone) playLine.textContent = "";
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
    variantNote.append(el("span", { class: "hint" }, note ? note(state.depth ?? 0) : ""));
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
                  ? `background:${WARN_INK}1a;color:${WARN_INK};font-weight:600`
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
    // 처방 카드 — knobs가 곧 3단 스윕의 입력이다
    diagBox.append(el("div", { class: "row", style: "gap:12px;flex-wrap:wrap;margin-top:10px" },
      d.prescriptions.map((p) => {
        const cls = KNOB_CLASS[p.knob_class] ?? { label: p.knob_class, ink: "#6c6c70" };
        return el("div", {
          style: "border:1px solid var(--border,#d0d0d5);border-radius:12px;" +
            "padding:10px 12px;min-width:280px;max-width:420px;flex:1",
        },
          el("div", { class: "row", style: "gap:8px;align-items:center" },
            el("span", {
              class: "flag",
              style: `background:${cls.ink}1a;color:${cls.ink};font-weight:600`,
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
  });
  canvasBox.append(canvas.root);

  load();
  // 탭을 떠났다 와도 진단·스윕 결과는 다시 그린다 (모듈 스코프 state 유지 규약)
  if (state.diag) renderDiag();
  if (state.sweep) renderSweep();

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
      playLine,
      el("div", { style: "margin-top:10px" }, legendBox),
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
