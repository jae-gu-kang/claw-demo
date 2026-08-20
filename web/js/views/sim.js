/** 시뮬레이션 뷰 (02 §8 5단계) — 미션 편집 → 폐루프 시뮬 → 재생 + 엔벨로프.

미션 스펙 변환은 lib/mission.js, 재생 수치는 lib/replay.js. 검증·수치는 전부
서버(엔진) 소관 — 구성 오류는 422 텍스트로 표시.
*/

import { api, errorText } from "../api.js";
import { clear, el, flagBadge, fmt } from "../dom.js";
import { buildModes, buildWaypoints, COND_KINDS } from "../lib/mission.js";
import { modeSpans, strideFor } from "../lib/replay.js";
import { store } from "../store.js";
import { lineChartCanvas, trackCanvas } from "./plots.js";
import { attachProgress, cancelledWithoutResult } from "./progress.js";

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

export function render() {
  const errBox = el("div");
  const progressBox = el("div");
  const replayBox = el("div");
  const modeBox = el("div");
  const wpBox = el("div");

  // 구조도 탭 '시뮬에 적용' 값 — 작동기는 필드에 프리필(최종 편집권은 여기),
  // 항법은 제출 시 기본 dict 대체 (시드만 이 탭이 우선)
  const actApplied = store.get("actuatorParams");
  const f = {
    mach: el("input", { class: "num", value: "0.6" }),
    alt: el("input", { class: "num", value: "1000" }),
    fuel: el("input", { class: "num", value: "300" }),
    tEnd: el("input", { class: "num", value: "180" }),
    accept: el("input", { class: "num", value: "1500" }),
    navOn: el("input", { type: "checkbox", checked: true }),
    seed: el("input", { class: "num", value: "11" }),
    actOn: el("input", { type: "checkbox", checked: true }),
    wn: el("input", { class: "num", value: String(actApplied?.wn ?? 30) }),
    zeta: el("input", { class: "num", value: String(actApplied?.zeta ?? 0.7) }),
    rate: el("input", { class: "num", value: String(actApplied?.rate_max ?? 10) }),
    fuelFlow: el("input", { class: "num", value: "0.3" }),
    useGains: el("input", { type: "checkbox" }),
    useAp: el("input", { type: "checkbox" }),
    fp: el("input", { value: "web-sim-v1" }),
  };

  const showErr = (e) =>
    clear(errBox).append(el("div", { class: "error-box" }, errorText(e)));

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
        // 구조도 항법 블록 적용값이 있으면 그것이 기본 dict를 대체 — 시드만 이 탭 우선
        const navBase = store.get("navParams")
          ?? { pos_std: 1.0, vel_std: 0.1, att_std: 0.001, psi_std: 0.002,
               rate_std: 0.0005, bias_std: 0.5, bias_tau: 60.0,
               delay_s: 0.02, update_hz: 50.0 };
        req.nav = { ...navBase, seed: Number(f.seed.value) };
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
      wpBox,
    ),
    el("div", { class: "panel" },
      el("h2", {}, "실행 조건"),
      el("div", { class: "field-grid" },
        el("div", { class: "opt-group" },
          el("div", { class: "g-title" }, "시작 트림점 · 시간"),
          el("div", { class: "row-inner" },
            el("label", { class: "field" }, "마하", f.mach),
            el("label", { class: "field" }, "고도 [m]", f.alt),
            el("label", { class: "field" }, "연료 [kg]", f.fuel),
            el("label", { class: "field" }, "t_end [s]", f.tEnd))),
        el("div", { class: "opt-group" },
          el("div", { class: "g-title" }, "항법 오차 모델"),
          el("div", { class: "row-inner" },
            el("label", { class: "field check" }, f.navOn, "사용"),
            el("label", { class: "field" }, "시드", f.seed)),
          store.get("navParams") && el("p", { class: "hint" },
            "구조도 항법 블록 적용값 사용 중 (시드만 여기서 우선)")),
        el("div", { class: "opt-group" },
          el("div", { class: "g-title" }, "작동기 (2차계)"),
          el("div", { class: "row-inner" },
            el("label", { class: "field check" }, f.actOn, "사용"),
            el("label", { class: "field" }, "wn [rad/s]", f.wn),
            el("label", { class: "field" }, "ζ", f.zeta),
            el("label", { class: "field" }, "rate [rad/s]", f.rate)),
          actApplied && el("p", { class: "hint" },
            "구조도 작동기 블록 적용값 프리필됨 — 여기 값이 최종")),
        el("div", { class: "opt-group" },
          el("div", { class: "g-title" }, "유도 · 연료 · 게인"),
          el("div", { class: "row-inner" },
            el("label", { class: "field" }, "도달반경 [m]", f.accept),
            el("label", { class: "field" }, "연료유량 [kg/s]", f.fuelFlow),
            el("label", { class: "field check" }, f.useGains, "편집 게인"),
            el("label", { class: "field check" }, f.useAp, "편집 AP"))),
        el("div", { class: "opt-group" },
          el("div", { class: "g-title" }, "계보"),
          el("div", { class: "row-inner" },
            el("label", { class: "field" }, "지문", f.fp))),
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
  renderWpTable(wpBox);
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

function renderWpTable(wpBox) {
  clear(wpBox).append(
    el("table", { class: "edit" },
      el("thead", {}, el("tr", {},
        el("th", {}, "#"), el("th", { class: "c-md" }, "N [m]"),
        el("th", { class: "c-md" }, "E [m]"), el("th", {}, ""))),
      el("tbody", {}, wpRows.map((r, i) => el("tr", {},
        el("td", {}, i + 1),
        el("td", {}, el("input", { value: r.n,
          onchange: (ev) => { r.n = ev.target.value; } })),
        el("td", {}, el("input", { value: r.e,
          onchange: (ev) => { r.e = ev.target.value; } })),
        el("td", {}, el("button", { class: "danger", onclick: () => {
          wpRows.splice(i, 1);
          renderWpTable(wpBox);
        } }, "삭제")),
      ))),
    ),
    el("div", { class: "row", style: "margin-top: 8px" },
      el("button", { onclick: () => {
        wpRows.push({ n: "0", e: "0" });
        renderWpTable(wpBox);
      } }, "웨이포인트 추가")),
  );
}

function renderReplay(replayBox) {
  const { body, waypoints, acceptRadius } = lastReplay;
  const sig = body.signals;
  const env = body.envelope;
  const spans = modeSpans(sig.mode);
  const seq = spans.map((s) => s.mode).join(" → ");

  const trackBox = el("div");
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
    clear(trackBox).append(trackCanvas(sig.pn, sig.pe, waypoints, acceptRadius,
      { markerIdx: i }));
  };
  slider.addEventListener("input", updateCursor);

  const chart = (title, series) =>
    lineChartCanvas(body.t, series, { title, bands: spans });

  clear(replayBox).append(
    el("p", {},
      `모드 체인: ${seq} · 절단: ${body.meta.aborted ?? "없음"} · `,
      "엔벨로프: ", flagBadge(!env.any_flag, "DB 이탈 없음", "DB 이탈 발생"),
      ` 최악 실속마진 ${fmt(env.worst_margin, 3)} rad @ ${fmt(env.worst_margin_t, 4)}s`,
      env.first_flag_t != null ? ` · 최초 플래그 ${fmt(env.first_flag_t, 4)}s` : "",
      ` · 최종 h ${fmt(sig.h[sig.h.length - 1], 4)} m · 잔여 연료 ${fmt(sig.fuel[sig.fuel.length - 1], 4)} kg`),
    el("div", { class: "row" }, slider, readout),
    el("div", { class: "row" },
      el("div", {},
        chart("고도 h [m]", [{ label: "h", data: sig.h, color: "#1a6feb" }]),
        chart("속도 V [m/s]", [{ label: "V", data: sig.V, color: "#1a6feb" }]),
        chart("자세 [rad]", [
          { label: "φ", data: sig.phi, color: "#b57908" },
          { label: "θ", data: sig.theta, color: "#1a6feb" }]),
        chart("받음각·실속마진 [rad]", [
          { label: "α", data: sig.alpha, color: "#c22f2f" },
          { label: "α_stall−α", data: env.stall_margin, color: "#157f3d" }]),
      ),
      trackBox,
    ),
  );
  updateCursor();
}
