/** 시뮬레이션 뷰 (02 §8 5단계) — 미션 편집 → 폐루프 시뮬 → 재생 + 엔벨로프.

미션 스펙 변환은 lib/mission.js, 재생 수치는 lib/replay.js. 검증·수치는 전부
서버(엔진) 소관 — 구성 오류는 422 텍스트로 표시.
*/

import { api, errorText } from "../api.js";
import { clear, el, flagBadge, fmt } from "../dom.js";
import { buildModes, buildWaypoints, COND_KINDS } from "../lib/mission.js";
import { planeViews } from "../lib/plot.js";
import { flaggedNames, modeSpans, strideFor } from "../lib/replay.js";
import { moveWaypoint } from "../lib/wpmap.js";
import { store } from "../store.js";
import { lineChartCanvas, profileCanvas, trackCanvas } from "./plots.js";
import { attachProgress, cancelledWithoutResult } from "./progress.js";
import { createWpMap } from "./wpmap.js";

// 기본 미션 = Phase 4 완주 회귀 미션 (test_mission — 상승→선회 항법→디센트→임무수행)
let modeRows = [
  { name: "climb", speed: "202", alt: "1300", heading: "0",
    exitKind: "alt_ge", exitValue: "1280", next: "wpnav" },
  { name: "wpnav", speed: "140", alt: "1300", heading: "path",
    exitKind: "path_done", exitValue: "", next: "descent" },
  { name: "descent", speed: "140", alt: "100", heading: "",
    exitKind: "alt_le", exitValue: "130", next: "mission" },
  { name: "mission", speed: "140", alt: "30", heading: "",
    exitKind: "time_ge", exitValue: "1e9", next: "" },
];
let wpRows = [{ n: "8000", e: "0" }, { n: "8000", e: "8000" }];
let lastReplay = null; // {body, waypoints, acceptRadius}
let runningJobId = null;
// 제출 시점 스냅샷 — 실행 중 편집이 재생 오버레이를 오염시키지 않도록 (리뷰 S3)
let runningSnapshot = { waypoints: [], acceptRadius: 0 };
// 지도 줌/팬 상태 — 탭 재진입 시 유지 (wpRows·lastReplay와 동렬)
let wpMapView = { view: null };

/* 실행 조건 폼 정렬 — 캡션 1줄(14px) + 컨트롤 1줄(30px) 고정.

app.css의 label.field는 컨트롤 높이가 제각각이라(체크박스 ~16px vs 입력 ~30px)
.field.check가 padding-bottom 7px 보정값으로 줄을 맞추고 있었다 — 폰트·패딩이
조금만 바뀌어도 어긋나고, 캡션 있는 필드와 없는 필드가 섞이면 바로 틀어진다.
두 줄 높이를 고정하면 모든 필드가 같은 박스가 되어 보정값 없이 정렬된다.

스타일을 app.css가 아니라 여기서 주는 이유: app.css는 병행 세션의 미커밋 변경이
올라가 있어 손대면 그 작업을 밟는다 (wpmap 선례 4dfaaeb와 동일한 회피). */
const CAPTION_ST = "height:14px; line-height:14px; font-size:11px; color:var(--muted);"
  + " white-space:nowrap; overflow:hidden; text-overflow:ellipsis;";
// 35px = 입력 실제 높이 (본문 14px/1.5 → 21px + 패딩 12 + 테두리 2). height가 아니라
// min-height — 브라우저별로 더 커지면 넘치는 대신 줄이 함께 자라 정렬이 유지된다.
const CONTROL_ST = "min-height:35px; display:flex; align-items:center; gap:6px;";
// 그룹은 같은 고정폭 박스 — 왼쪽부터 조밀하게 채우고 남는 폭으로 늘어나지 않는다.
// (격자 1fr로 늘리면 입력이 고정 90px이라 늘어난 만큼 빈 칸이 되어 패널만 휑해진다.
// 바깥 배치는 app.css .field-grid의 flex-wrap + align-items:stretch 그대로 사용.)
// shrink 1 — 좁은 화면에서는 줄었다가 wrap.
const GROUP_ST = "display:flex; flex-direction:column; flex:0 1 240px; min-width:0;";
// 그룹 안은 2열 고정 격자 — flex-wrap이면 필드 폭이 내용마다 달라 둘째 줄이
// 첫 줄 아래로 안 떨어진다(열이 어긋나 보이는 원인). 1fr 두 칸이면 어느 그룹이든
// 같은 자리에 열이 선다. minmax(0,1fr) — 내용이 칸보다 커도 밀어내지 않게.
const INNER_ST = "display:grid; grid-template-columns:repeat(2, minmax(0, 1fr));"
  + " gap:10px 12px; align-items:start;";
// 입력은 칸 폭을 채운다 — .num의 고정 90px을 두면 칸마다 남는 여백이 제각각
const FILL_ST = "width:100%; box-sizing:border-box;";
// margin-top:auto — 힌트를 그룹 바닥에 붙인다. .field-grid의 align-items:stretch가
// 같은 줄 박스 높이를 맞춰 주므로, 바닥 정렬이면 힌트 줄도 나란히 선다
const HINT_ST = "margin:auto 0 0; padding-top:8px;";
// 3면도 한 변 [px] — 셋을 가로로 이어 붙였을 때 3×320 + 여백이 패널에 들어가는 크기
const PLANE_PX = 320;

/** 캡션+컨트롤 2줄 고정 필드. caption "" 이면 자리만 차지 (체크박스 줄맞춤용). */
function field(caption, ...control) {
  return el("label", { class: "field", style: "gap:4px; min-width:0;" },
    el("span", { style: CAPTION_ST }, caption),
    el("div", { style: CONTROL_ST }, ...control));
}

/** 체크박스 필드 — 캡션 줄은 비우고 컨트롤 줄에 [✓] 라벨 (입력과 바닥 정렬). */
function checkField(input, label) {
  return field("", input, el("span", { style: "font-size:12px;" }, label));
}

/** 수치 입력 — 2열 격자 칸을 채우는 폭 (mono 글꼴은 .num이 준다). */
function numInput(value) {
  return el("input", { class: "num", style: FILL_ST, value });
}

/** 2열을 다 쓰는 필드 — 자유 텍스트처럼 반 칸이면 좁은 입력용. */
function wideField(caption, control) {
  const node = field(caption, control);
  node.style.gridColumn = "1 / -1";
  return node;
}

export function render() {
  const errBox = el("div");
  const progressBox = el("div");
  const replayBox = el("div");
  const modeBox = el("div");
  const wpBox = el("div");

  // 구조도 탭 '시뮬에 적용' 값 — 작동기는 필드에 프리필(최종 편집권은 여기),
  // 항법은 제출 시 병합 (시드만 이 탭이 우선, 나머지 미지정분은 엔진 기본값)
  const actApplied = store.get("actuatorParams");
  const f = {
    mach: numInput("0.6"),
    alt: numInput("1000"),
    fuel: numInput("300"),
    tEnd: numInput("180"),
    accept: numInput("1500"),
    navOn: el("input", { type: "checkbox", checked: true }),
    seed: numInput("11"),
    actOn: el("input", { type: "checkbox", checked: true }),
    wn: numInput(String(actApplied?.wn ?? 30)),
    zeta: numInput(String(actApplied?.zeta ?? 0.7)),
    rate: numInput(String(actApplied?.rate_max ?? 10)),
    fuelFlow: numInput("0.3"),
    useGains: el("input", { type: "checkbox" }),
    useAp: el("input", { type: "checkbox" }),
    fp: el("input", { value: "web-sim-v1", style: FILL_ST }),
  };

  // 작동기 프리필 폴백(위 30·0.7·10)은 엔진 기본값의 사본 — 폼이 즉시 유효해야 해서
  // 남기되, 스키마가 도착하면 사용자가 손대지 않은 값만 갱신해 스스로 어긋남을 고친다.
  // (항법 기본값이 7개나 어긋난 채 돌던 전례 — 01 v0.19. 실패는 무시: 폴백으로 동작)
  if (!actApplied) {
    api.get("/registry/actuator/SecondOrderActuator/schema").then((s) => {
      for (const [key, name, fallback] of
        [["wn", "wn", 30], ["zeta", "zeta", 0.7], ["rate", "rate_max", 10]]) {
        const d = s.properties?.[name]?.default;
        if (d !== undefined && f[key].value === String(fallback)) f[key].value = String(d);
      }
    }).catch(() => {});
  }

  const showErr = (e) =>
    clear(errBox).append(el("div", { class: "error-box" }, errorText(e)));

  // NED 평면 지도 편집기 — 표와 양방향 동기 (단일 소스 = wpRows)
  const wpMap = createWpMap({
    getRows: () => wpRows,
    getAcceptRadius: () => Number(f.accept.value) || 0,
    getTrack: () => lastReplay &&
      { pn: lastReplay.body.signals.pn, pe: lastReplay.body.signals.pe },
    onRowsChanged: () => renderWpTable(wpBox, wpMap),
    viewRef: wpMapView,
  });
  f.accept.addEventListener("input", () => wpMap.refresh()); // 도달반경 원 즉시 갱신

  const watch = () => attachProgress(progressBox, runningJobId, {
    onDone: async (job) => {
      runningJobId = null;
      try {
        if (job.status === "error") throw new Error(job.error);
        if (cancelledWithoutResult(job)) {
          showErr(new Error("취소됨 — 저장된 결과 없음 (실행 전 취소)"));
          return;
        }
        const stride = strideFor(job.total || 1);
        const body = await api.get(`/sim/${job.result_id}/replay?stride=${stride}`);
        lastReplay = {
          body,
          waypoints: runningSnapshot.waypoints,
          acceptRadius: runningSnapshot.acceptRadius,
        };
        store.set("simResult", { id: job.result_id });
        renderReplay(replayBox);
        wpMap.refresh(); // 지도 궤적 오버레이 갱신
      } catch (e) {
        showErr(e);
      }
    },
    onError: (e) => {
      runningJobId = null;
      showErr(e);
    },
  });

  const run = async () => {
    if (runningJobId) { // 이중 제출 방지 (리뷰 S4) — 무반응 대신 안내 (조용한 무시 금지)
      clear(errBox).append(el("div", { class: "error-box" },
        "이미 실행 중입니다 — 진행률 표시를 확인하세요."));
      return;
    }
    try {
      clear(errBox);
      clear(replayBox);
      const req = {
        trim: {
          name: "start",
          mach: Number(f.mach.value), alt: Number(f.alt.value), fuel: Number(f.fuel.value),
        },
        modes: buildModes(modeRows),
        waypoints: buildWaypoints(wpRows),
        accept_radius: Number(f.accept.value),
        t_end: Number(f.tEnd.value),
        fuel_flow: Number(f.fuelFlow.value),
        fingerprint: f.fp.value,
      };
      const snapshot = { // 제출 시점 캡처 (리뷰 S3)
        waypoints: req.waypoints ?? [],
        acceptRadius: req.accept_radius,
      };
      if (req.waypoints === null) delete req.waypoints;
      if (f.navOn.checked) {
        // 미지정 파라미터는 엔진 ParamDef 기본값이 채운다 — 여기서 기본값을 다시 적으면
        // 엔진과 조용히 어긋난다 (실제로 7개가 어긋난 채 돌고 있었다: pos_std·att_std·
        // psi_std·rate_std·bias_std·delay_s·update_hz). 빈 dict도 오차 모델은 장착 —
        // 미장착은 nav 필드 자체를 생략하는 경우뿐 (routes/sim.py::_build)
        req.nav = { ...(store.get("navParams") ?? {}), seed: Number(f.seed.value) };
      }
      if (f.actOn.checked) {
        // 구조도 작동기 블록 적용값(pos 한계·initial 포함) 위에 이 탭 필드가 최종 덮어씀
        req.actuators = { ...(store.get("actuatorParams") ?? {}),
                          wn: Number(f.wn.value), zeta: Number(f.zeta.value),
                          rate_max: Number(f.rate.value) };
      }
      // 편집본 체크됐는데 적용본이 없으면 기본값 실행을 조용히 하지 않고 알림 (리뷰 Nit3)
      const missing = [];
      if (f.useGains.checked) {
        if (store.get("gainTables")) req.gain_tables = store.get("gainTables");
        else missing.push("편집 게인 (게인 탭 '시뮬에 적용' 필요)");
      }
      if (f.useAp.checked) {
        // 구조도 AP 블록 편집값 (전체 kwargs)
        if (store.get("autopilotParams")) req.autopilot = store.get("autopilotParams");
        else missing.push("편집 AP (구조도 탭 오토파일럿 블록 '시뮬에 적용' 필요)");
      }
      if (missing.length) {
        errBox.append(el("div", { class: "error-box" },
          `적용된 편집값 없음 — 기본값으로 실행됨: ${missing.join(", ")}`));
      }
      const submitted = await api.post("/sim/run", req);
      runningJobId = submitted.id;
      runningSnapshot = snapshot;
      watch();
    } catch (e) {
      showErr(e);
    }
  };

  const root = el("div", {},
    el("div", { class: "panel" },
      el("h2", {}, "미션 정의 (선언적 모드 테이블 — 01 §3.1)"),
      modeBox,
      el("h2", {}, "웨이포인트 (N, E) [m]"),
      el("div", { class: "row" }, wpBox, wpMap.root),
    ),
    el("div", { class: "panel" },
      el("h2", {}, "실행 조건"),
      el("div", { class: "field-grid" },
        el("div", { class: "opt-group", style: GROUP_ST },
          el("div", { class: "g-title" }, "시작 트림점 · 시간"),
          el("div", { class: "row-inner", style: INNER_ST },
            field("마하", f.mach),
            field("고도 [m]", f.alt),
            field("연료 [kg]", f.fuel),
            field("t_end [s]", f.tEnd))),
        el("div", { class: "opt-group", style: GROUP_ST },
          el("div", { class: "g-title" }, "항법 오차 모델"),
          el("div", { class: "row-inner", style: INNER_ST },
            checkField(f.navOn, "사용"),
            field("시드", f.seed)),
          el("p", { class: "hint", style: HINT_ST }, store.get("navParams")
            ? "구조도 적용값 사용 중 (시드만 여기서 우선)"
            : "미지정 항목은 엔진 기본값 — 편집은 구조도 탭 항법 블록")),
        el("div", { class: "opt-group", style: GROUP_ST },
          el("div", { class: "g-title" }, "작동기 (2차계)"),
          el("div", { class: "row-inner", style: INNER_ST },
            checkField(f.actOn, "사용"),
            field("wn [rad/s]", f.wn),
            field("ζ", f.zeta),
            field("rate [rad/s]", f.rate)),
          el("p", { class: "hint", style: HINT_ST }, actApplied
            ? "구조도 적용값 프리필됨 — 여기 값이 최종"
            : "구조도 탭에서 '시뮬에 적용' 시 프리필")),
        el("div", { class: "opt-group", style: GROUP_ST },
          el("div", { class: "g-title" }, "유도 · 연료 · 게인"),
          el("div", { class: "row-inner", style: INNER_ST },
            field("도달반경 [m]", f.accept),
            field("연료유량 [kg/s]", f.fuelFlow),
            checkField(f.useGains, "편집 게인"),
            checkField(f.useAp, "편집 AP"))),
        el("div", { class: "opt-group", style: GROUP_ST },
          el("div", { class: "g-title" }, "계보"),
          el("div", { class: "row-inner", style: INNER_ST },
            wideField("지문", f.fp))),
      ),
      el("div", { class: "row", style: "margin-top: 12px" },
        el("button", { class: "primary", onclick: run }, "시뮬 실행"),
        el("span", { class: "hint" },
          "작동기 rate ≥ 10 rad/s 요구 [도출 사양] (01 v0.13) · 편집 게인은 게인 탭, ",
          "편집 AP는 구조도 탭 오토파일럿 블록에서 '시뮬에 적용' 후 사용")),
      progressBox, errBox,
    ),
    el("div", { class: "panel" }, el("h2", {}, "재생 + 엔벨로프 감시"), replayBox),
  );

  renderModeTable(modeBox);
  renderWpTable(wpBox, wpMap);
  if (lastReplay) renderReplay(replayBox);
  if (runningJobId) watch(); // 실행 중 재진입 — 진행 UI 재부착 (리뷰 S4)
  return root;
}

function renderModeTable(modeBox) {
  clear(modeBox).append(
    el("div", { class: "scroll-x" }, el("table", { class: "edit" },
      el("thead", {}, el("tr", {},
        el("th", { class: "c-md" }, "모드"),
        el("th", { class: "c-sm" }, "속도 [m/s]"), el("th", { class: "c-sm" }, "고도 [m]"),
        el("th", { class: "c-md" }, "헤딩"),
        el("th", { class: "c-md" }, "이탈 조건"), el("th", { class: "c-sm" }, "값"),
        el("th", { class: "c-md" }, "다음"), el("th", {}, ""))),
      el("tbody", {}, modeRows.map((r, i) => el("tr", {},
        el("td", {}, el("input", { value: r.name,
          onchange: (ev) => { r.name = ev.target.value; } })),
        el("td", {}, el("input", { value: r.speed,
          onchange: (ev) => { r.speed = ev.target.value; } })),
        el("td", {}, el("input", { value: r.alt,
          onchange: (ev) => { r.alt = ev.target.value; } })),
        el("td", {}, el("input", { value: r.heading,
          onchange: (ev) => { r.heading = ev.target.value; } })),
        el("td", {}, el("select", {
          onchange: (ev) => { r.exitKind = ev.target.value; },
        }, Object.keys(COND_KINDS).map((k) =>
          el("option", { value: k, selected: k === r.exitKind }, k)))),
        el("td", {}, el("input", { value: r.exitValue,
          onchange: (ev) => { r.exitValue = ev.target.value; } })),
        el("td", {}, el("input", { value: r.next,
          onchange: (ev) => { r.next = ev.target.value; } })),
        el("td", {}, el("button", { class: "danger", onclick: () => {
          modeRows.splice(i, 1);
          renderModeTable(modeBox);
        } }, "삭제")),
      ))),
    )),
    el("div", { class: "row", style: "margin-top: 8px" },
      el("button", { onclick: () => {
        modeRows.push({ name: `mode${modeRows.length + 1}`, speed: "", alt: "",
                        heading: "", exitKind: "time_ge", exitValue: "1e9", next: "" });
        renderModeTable(modeBox);
      } }, "모드 추가"),
      el("span", { class: "hint" },
        '헤딩: 수치 | "path"(경로 추종) | 빈=유지 안 함 · 속도/고도도 빈 칸이면 해당 루프 off')),
  );
}

function renderWpTable(wpBox, wpMap) {
  // 표·지도 양방향 동기 — 단일 소스는 wpRows, 지도는 refresh()로 재그리기만
  const sync = () => {
    renderWpTable(wpBox, wpMap);
    wpMap?.refresh();
  };
  clear(wpBox).append(
    el("table", { class: "edit" },
      el("thead", {}, el("tr", {},
        el("th", {}, "#"), el("th", { class: "c-md" }, "N [m]"),
        el("th", { class: "c-md" }, "E [m]"),
        el("th", {}, "순서"), el("th", {}, ""))),
      el("tbody", {}, wpRows.map((r, i) => el("tr", {},
        el("td", {}, i + 1),
        el("td", {}, el("input", { value: r.n,
          onchange: (ev) => { r.n = ev.target.value; wpMap?.refresh(); } })),
        el("td", {}, el("input", { value: r.e,
          onchange: (ev) => { r.e = ev.target.value; wpMap?.refresh(); } })),
        el("td", {},
          el("button", { title: "위로", onclick: () => {
            if (moveWaypoint(wpRows, i, i - 1)) sync();
          } }, "▲"),
          el("button", { title: "아래로", onclick: () => {
            if (moveWaypoint(wpRows, i, i + 1)) sync();
          } }, "▼")),
        el("td", {}, el("button", { class: "danger", onclick: () => {
          wpRows.splice(i, 1);
          sync();
        } }, "삭제")),
      ))),
    ),
    el("div", { class: "row", style: "margin-top: 8px" },
      el("button", { onclick: () => {
        wpRows.push({ n: "0", e: "0" });
        sync();
      } }, "웨이포인트 추가"),
      el("span", { class: "hint" }, "지도에서 클릭 추가 · 드래그 이동 · 우클릭 삭제 가능")),
  );
}

function renderReplay(replayBox) {
  const { body, waypoints, acceptRadius } = lastReplay;
  const sig = body.signals;
  const env = body.envelope;
  const spans = modeSpans(sig.mode);
  const seq = spans.map((s) => s.mode).join(" → ");

  // 3면도 (평면도·측면도·정면도) — 축 배정·등축 여부는 lib/plot.js planeViews가 정본.
  // 셋을 가로로 잇대므로 정사각 — N–E 평면이 등축이려면 폭=높이여야 한다
  // (trackCanvas는 같은 span을 폭·높이에 각각 사상하므로 직사각이면 축척이 어긋난다)
  const views = planeViews(sig);
  const planeBoxes = views.map(() => el("div"));
  const readout = el("span", { class: "progress-label" });
  const slider = el("input", {
    type: "range", min: "0", max: String(body.t.length - 1), value: "0",
    style: "width: 340px", "aria-label": "재생 시각 커서",
  });
  const updateCursor = () => {
    const i = Number(slider.value);
    readout.textContent =
      `t=${fmt(body.t[i], 4)}s ${sig.mode[i]} | h=${fmt(sig.h[i], 4)} m ` +
      `V=${fmt(sig.V[i], 4)} m/s α=${fmt(sig.alpha[i], 3)} rad ` +
      `실속마진=${fmt(env.stall_margin[i], 3)}`;
    // 시각 커서는 세 평면 모두에서 같은 시점을 가리켜야 한다 — 한 곳만 갱신하면
    // 나머지가 이전 커서를 들고 있어 서로 다른 시점처럼 읽힌다
    views.forEach((v, k) => {
      clear(planeBoxes[k]).append(v.equal
        ? trackCanvas(sig.pn, sig.pe, waypoints, acceptRadius,
          { markerIdx: i, title: v.title, width: PLANE_PX, height: PLANE_PX })
        : profileCanvas(v.xs, v.ys, {
          title: v.title, xLabel: v.xLabel, yLabel: v.yLabel, markerIdx: i,
          wpXs: waypoints.map((w) => w[v.wpIdx]),
          width: PLANE_PX, height: PLANE_PX,
        }));
    });
  };
  slider.addEventListener("input", updateCursor);

  const chart = (title, series) =>
    lineChartCanvas(body.t, series, { title, bands: spans });

  clear(replayBox).append(
    el("p", {},
      `모드 체인: ${seq} · 절단: ${body.meta.aborted ?? "없음"} · `,
      // 플래그는 DB 유효범위(α·β·M) + 기준면 여유(고도) 통합 요약 — 어느 항목이
      // 떴는지 이름으로 밝힌다 (뭉뚱그리면 고도 이탈이 DB 이탈로 오독됨)
      "엔벨로프: ", flagBadge(!env.any_flag, "이탈 없음", `이탈: ${flaggedNames(env)}`),
      ` 최악 실속마진 ${fmt(env.worst_margin, 3)} rad @ ${fmt(env.worst_margin_t, 4)}s`,
      env.min_alt != null
        ? ` · 최저 고도 ${fmt(env.min_alt, 4)} m @ ${fmt(env.min_alt_t, 4)}s` : "",
      env.first_flag_t != null ? ` · 최초 플래그 ${fmt(env.first_flag_t, 4)}s` : "",
      ` · 최종 h ${fmt(sig.h[sig.h.length - 1], 4)} m · 잔여 연료 ${fmt(sig.fuel[sig.fuel.length - 1], 4)} kg`),
    el("div", { class: "row" }, slider, readout),
    // 3면도 — 세 평면을 가로로 잇대 한 줄로 (좁으면 wrap). 시계열 위에 두어
    // 커서 조작(바로 위 슬라이더)과 그 반응이 눈에 같이 들어오게 한다
    el("div", { style: "display:flex; flex-direction:column; gap:6px; margin-bottom:12px;" },
      el("div", { class: "hint" },
        "궤적 3면도 (NED) — N–E 평면만 등축(선회반경 판독용), 연직 평면은 비등축이라 ",
        "경사각을 눈으로 재면 안 됨. 주황 세로선은 웨이포인트의 수평좌표"),
      el("div", { style: "display:flex; flex-wrap:wrap; gap:8px; align-items:flex-start;" },
        planeBoxes[0], planeBoxes[1], planeBoxes[2])),
    el("div", { class: "row" },
      el("div", {},
        chart("고도 h [m]", [{ label: "h", data: sig.h, color: "#007aff" }]),
        chart("속도 V [m/s]", [{ label: "V", data: sig.V, color: "#007aff" }]),
        chart("자세 [rad]", [
          { label: "φ", data: sig.phi, color: "#ff9500" },
          { label: "θ", data: sig.theta, color: "#007aff" }]),
        chart("받음각·실속마진 [rad]", [
          { label: "α", data: sig.alpha, color: "#ff3b30" },
          { label: "α_stall−α", data: env.stall_margin, color: "#34c759" }]),
      ),
    ),
  );
  updateCursor();
}
