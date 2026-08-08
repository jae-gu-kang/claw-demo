/** 시뮬레이션 뷰 (02 §8 5단계) — 미션 편집 → 폐루프 시뮬 → 재생 + 엔벨로프.

미션 스펙 변환은 lib/mission.js, 재생 수치는 lib/replay.js. 검증·수치는 전부
서버(엔진) 소관 — 구성 오류는 422 텍스트로 표시.
*/

import { api, cancelJob, errorText, watchJob } from "../api.js";
import { clear, el, flagBadge, fmt } from "../dom.js";
import { buildModes, buildWaypoints, COND_KINDS } from "../lib/mission.js";
import { modeSpans, strideFor } from "../lib/replay.js";
import { store } from "../store.js";
import { lineChartCanvas, trackCanvas } from "./plots.js";

// 기본 미션 = Phase 4 완주 회귀 미션 (test_mission — 상승→선회 항법→디센트→씨스키밍)
let modeRows = [
  { name: "climb", speed: "202", alt: "1300", heading: "0",
    exitKind: "alt_ge", exitValue: "1280", next: "wpnav" },
  { name: "wpnav", speed: "140", alt: "1300", heading: "path",
    exitKind: "path_done", exitValue: "", next: "descent" },
  { name: "descent", speed: "140", alt: "100", heading: "",
    exitKind: "alt_le", exitValue: "130", next: "seaskim" },
  { name: "seaskim", speed: "140", alt: "30", heading: "",
    exitKind: "time_ge", exitValue: "1e9", next: "" },
];
let wpRows = [{ n: "8000", e: "0" }, { n: "8000", e: "8000" }];
let lastReplay = null; // {body, waypoints, acceptRadius}

export function render() {
  const errBox = el("div");
  const progressBox = el("div");
  const replayBox = el("div");
  const modeBox = el("div");
  const wpBox = el("div");

  const f = {
    mach: el("input", { class: "num", value: "0.6" }),
    alt: el("input", { class: "num", value: "1000" }),
    fuel: el("input", { class: "num", value: "300" }),
    tEnd: el("input", { class: "num", value: "180" }),
    accept: el("input", { class: "num", value: "1500" }),
    navOn: el("input", { type: "checkbox", checked: true }),
    seed: el("input", { class: "num", value: "11" }),
    actOn: el("input", { type: "checkbox", checked: true }),
    wn: el("input", { class: "num", value: "30" }),
    zeta: el("input", { class: "num", value: "0.7" }),
    rate: el("input", { class: "num", value: "10" }),
    fuelFlow: el("input", { class: "num", value: "0.3" }),
    useGains: el("input", { type: "checkbox" }),
    fp: el("input", { value: "web-sim-v1" }),
  };

  const run = async () => {
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
      if (req.waypoints === null) delete req.waypoints;
      if (f.navOn.checked) {
        req.nav = { pos_std: 1.0, vel_std: 0.1, att_std: 0.001, psi_std: 0.002,
                    rate_std: 0.0005, bias_std: 0.5, bias_tau: 60.0,
                    delay_s: 0.02, update_hz: 50.0, seed: Number(f.seed.value) };
      }
      if (f.actOn.checked) {
        req.actuators = { wn: Number(f.wn.value), zeta: Number(f.zeta.value),
                          rate_max: Number(f.rate.value) };
      }
      if (f.useGains.checked && store.get("gainTables")) {
        req.gain_tables = store.get("gainTables");
      }
      const submitted = await api.post("/sim/run", req);
      const bar = el("div");
      const label = el("span", { class: "progress-label" }, "제출됨…");
      clear(progressBox).append(el("div", { class: "progress-line" },
        el("div", { class: "progress" }, bar), label,
        el("button", { onclick: () => cancelJob(submitted.id) }, "취소")));
      const job = await watchJob(submitted.id, (j) => {
        bar.style.width = `${Math.round(100 * j.progress)}%`;
        label.textContent = `${j.status} ${j.done}/${j.total} 스텝`;
      });
      clear(progressBox);
      if (job.status === "error") throw new Error(job.error);
      const stride = strideFor(job.total || 1);
      const body = await api.get(`/sim/${job.result_id}/replay?stride=${stride}`);
      lastReplay = {
        body,
        waypoints: (buildWaypoints(wpRows) ?? []),
        acceptRadius: Number(f.accept.value),
      };
      store.set("simResult", { id: job.result_id });
      renderReplay(replayBox);
    } catch (e) {
      clear(progressBox);
      clear(errBox).append(el("div", { class: "error-box" }, errorText(e)));
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
      el("div", { class: "row" },
        el("label", { class: "field" }, "트림 마하", f.mach),
        el("label", { class: "field" }, "고도 [m]", f.alt),
        el("label", { class: "field" }, "연료 [kg]", f.fuel),
        el("label", { class: "field" }, "t_end [s]", f.tEnd),
        el("label", { class: "field" }, "도달반경 [m]", f.accept),
        el("label", { class: "field" }, "연료유량 [kg/s]", f.fuelFlow),
        el("label", { class: "field" }, "지문", f.fp),
      ),
      el("div", { class: "row" },
        el("label", { class: "field" }, "항법 오차 모델", f.navOn),
        el("label", { class: "field" }, "시드", f.seed),
        el("label", { class: "field" }, "작동기", f.actOn),
        el("label", { class: "field" }, "wn [rad/s]", f.wn),
        el("label", { class: "field" }, "ζ", f.zeta),
        el("label", { class: "field" }, "rate [rad/s]", f.rate),
        el("label", { class: "field" }, "편집 게인 사용", f.useGains),
        el("button", { class: "primary", onclick: run }, "시뮬 실행"),
      ),
      el("p", { class: "hint" },
        "작동기 rate ≥ 10 rad/s 요구 [도출 사양] — 3 rad/s는 항법 지연·잡음과 결합해 리밋사이클 (01 v0.13). ",
        "편집 게인은 게인 탭에서 '시뮬에 적용' 후 사용 가능."),
      progressBox, errBox,
    ),
    el("div", { class: "panel" }, el("h2", {}, "재생 + 엔벨로프 감시"), replayBox),
  );

  renderModeTable(modeBox);
  renderWpTable(wpBox);
  if (lastReplay) renderReplay(replayBox);
  return root;
}

function renderModeTable(modeBox) {
  clear(modeBox).append(
    el("table", {},
      el("thead", {}, el("tr", {},
        el("th", {}, "모드"), el("th", {}, "속도 [m/s]"), el("th", {}, "고도 [m]"),
        el("th", {}, 'heading (수치 | "path" | 빈=off)'),
        el("th", {}, "이탈 조건"), el("th", {}, "값"), el("th", {}, "다음"), el("th", {}, ""))),
      el("tbody", {}, modeRows.map((r, i) => el("tr", {},
        el("td", {}, el("input", { class: "num", value: r.name,
          onchange: (ev) => { r.name = ev.target.value; } })),
        el("td", {}, el("input", { class: "num", value: r.speed,
          onchange: (ev) => { r.speed = ev.target.value; } })),
        el("td", {}, el("input", { class: "num", value: r.alt,
          onchange: (ev) => { r.alt = ev.target.value; } })),
        el("td", {}, el("input", { class: "num", value: r.heading,
          onchange: (ev) => { r.heading = ev.target.value; } })),
        el("td", {}, el("select", {
          onchange: (ev) => { r.exitKind = ev.target.value; },
        }, Object.keys(COND_KINDS).map((k) =>
          el("option", { value: k, selected: k === r.exitKind }, k)))),
        el("td", {}, el("input", { class: "num", value: r.exitValue,
          onchange: (ev) => { r.exitValue = ev.target.value; } })),
        el("td", {}, el("input", { class: "num", value: r.next,
          onchange: (ev) => { r.next = ev.target.value; } })),
        el("td", {}, el("button", { class: "danger", onclick: () => {
          modeRows.splice(i, 1);
          renderModeTable(modeBox);
        } }, "삭제")),
      ))),
    ),
    el("button", { onclick: () => {
      modeRows.push({ name: `mode${modeRows.length + 1}`, speed: "", alt: "",
                      heading: "", exitKind: "time_ge", exitValue: "1e9", next: "" });
      renderModeTable(modeBox);
    } }, "모드 추가"),
  );
}

function renderWpTable(wpBox) {
  clear(wpBox).append(
    el("table", {},
      el("thead", {}, el("tr", {},
        el("th", {}, "#"), el("th", {}, "N [m]"), el("th", {}, "E [m]"), el("th", {}, ""))),
      el("tbody", {}, wpRows.map((r, i) => el("tr", {},
        el("td", {}, i + 1),
        el("td", {}, el("input", { class: "num", value: r.n,
          onchange: (ev) => { r.n = ev.target.value; } })),
        el("td", {}, el("input", { class: "num", value: r.e,
          onchange: (ev) => { r.e = ev.target.value; } })),
        el("td", {}, el("button", { class: "danger", onclick: () => {
          wpRows.splice(i, 1);
          renderWpTable(wpBox);
        } }, "삭제")),
      ))),
    ),
    el("button", { onclick: () => {
      wpRows.push({ n: "0", e: "0" });
      renderWpTable(wpBox);
    } }, "웨이포인트 추가"),
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
    style: "width: 340px",
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
