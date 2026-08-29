/** 자동 설계 뷰 — 트림 자동화→게인 튜닝→스케줄 적합→마진 검증→원인별 처방 루프.

설계 루프 전체(M17 DesignSession)를 잡 하나로 돌리고, gated(기본)면 처방 카드에서
멈춘다 — 승인한 처방만 반영해 재개한다. 에스컬레이션(상위 설계 변경)은 어느
모드에서도 자동 적용되지 않고 보고 패널에만 남는다.

수치의 정본은 서버 /design/defaults(← 엔진 AutoDesignConfig) — 폼은 채운 칸만
config 덮어쓰기로 보낸다. "게인 확정"은 결과의 호환 반출(재샘플 테이블)을 기존
스토어 계약(`gainTables` + 출처 `gainTablesSource`)으로 주입한다 — 시뮬·Autocode·
구조도·영향성이 그대로 소비하고, 게인 탭은 그것을 **되읽어** 표·차트로 보여 준다
(자리마다 다른 breakpoint는 합집합 축으로 정렬 — lib/gainsched alignTables).

스타일은 app.css 비접촉 — 심각도 색은 값으로 지정 (duty.js 선례).
*/

import { api, errorText } from "../api.js";
import { clear, el, fmt } from "../dom.js";
import {
  VERDICT_LABEL, actionCards, adoptStorePayload, buildConfig, pointRows,
} from "../lib/autodesign.js";
import { store } from "../store.js";
import { attachProgress, cancelledWithoutResult } from "./progress.js";

const SEV_COLOR = { ok: "#34c759", warn: "#ff9500", fail: "#ff3b30", na: "#8e8e93" };
const ROLE_LABEL = { anchor: "앵커(트림·선형화)", breakpoint: "게인 breakpoint", validation: "검증점" };

// 탭 이탈·재진입에도 실행 중 잡·최근 결과를 잃지 않는다 (progress.js 재부착 규약)
let runningJobId = null;
let lastResultId = null;

export function render() {
  const errBox = el("div");
  const progressBox = el("div");
  const resultBox = el("div");
  const defaultsBox = el("p", { class: "hint" }, "기본값 불러오는 중…");

  const form = {
    mode: el("select", { "aria-label": "실행 모드" },
      el("option", { value: "gated", selected: true }, "승인 게이트 (gated)"),
      el("option", { value: "auto" }, "전자동 (auto)"),
    ),
    budgetPoints: el("input", { size: 5, placeholder: "200" }),
    budgetIters: el("input", { size: 3, placeholder: "5" }),
    nMach: el("input", { size: 3, placeholder: "5" }),
    altsText: el("input", { size: 16, placeholder: "0 1000 3000 5000" }),
    fuelsText: el("input", { size: 12, placeholder: "40 200 400" }),
  };

  const loadDefaults = async () => {
    try {
      const d = await api.get("/design/defaults");
      const c = d.config;
      form.mode.value = c.mode;
      defaultsBox.textContent =
        `합격기준 PM ≥ ${c.criteria.pm_min_deg}° · GM ≥ ${c.criteria.gm_min_db} dB · `
        + `ζ ≥ ${c.criteria.zeta_min} — 설계 목표 PM ${c.targets.pm_deg}° / GM `
        + `${c.targets.gm_db} dB · ζsp ${c.targets.zeta_sp} (정본: 엔진 AutoDesignConfig)`;
    } catch (e) {
      defaultsBox.textContent = `기본값 조회 실패: ${errorText(e)}`;
    }
  };

  const showResult = async (resultId) => {
    lastResultId = resultId;
    const body = await api.get(`/results/${resultId}`);
    renderResult(resultBox, body, resultId, { errBox, progressBox, showResult });
  };

  const onJobDone = async (job) => {
    runningJobId = null;
    if (cancelledWithoutResult(job)) return;
    try {
      await showResult(job.result_id);
    } catch (e) {
      clear(errBox).append(el("div", { class: "error-box" }, errorText(e)));
    }
  };

  const start = async () => {
    try {
      clear(errBox);
      const config = buildConfig({
        mode: form.mode.value,
        budgetPoints: form.budgetPoints.value,
        budgetIters: form.budgetIters.value,
        nMach: form.nMach.value,
        altsText: form.altsText.value,
        fuelsText: form.fuelsText.value,
      });
      const job = await api.post("/design/auto", { config });
      runningJobId = job.id;
      attachProgress(progressBox, job.id, {
        onDone: onJobDone,
        onError: (e) => clear(errBox).append(el("div", { class: "error-box" }, errorText(e))),
      });
    } catch (e) {
      clear(errBox).append(el("div", { class: "error-box" }, errorText(e)));
    }
  };

  const loadList = async () => {
    try {
      const items = (await api.get("/results")).filter((m) => m.kind === "auto_design");
      if (!items.length) return;
      const sel = el("select", { "aria-label": "자동 설계 결과 선택" },
        el("option", { value: "" }, "지난 결과 열기…"),
        ...items.map((m) => el("option", { value: m.id },
          `${m.id} · ${m.status ?? ""} ${m.stage ?? ""}`)),
      );
      sel.addEventListener("change", () => sel.value && showResult(sel.value).catch(
        (e) => clear(errBox).append(el("div", { class: "error-box" }, errorText(e)))));
      listBox.append(sel);
      if (lastResultId && items.some((m) => m.id === lastResultId)) {
        showResult(lastResultId).catch(() => {});
      }
    } catch { /* 목록 실패는 시작 흐름을 막지 않는다 */ }
  };

  const listBox = el("span");
  const root = el("div",
    {},
    el("h2", {}, "자동 설계"),
    el("p", { class: "hint" },
      "엔벨로프에서 coarse 트림 격자를 유도하고, 플랜트 변화량으로 격자를 세분화한 뒤 "
      + "운영점별 게인을 자동 튜닝·다항 적합하고, 보간 실효 게인으로 마진을 검증한다. "
      + "마진 부족은 원인별 처방(검증점 추가/앵커·breakpoint 승격/상위 설계 에스컬레이션)으로 순환한다."),
    defaultsBox,
    el("div", { class: "form-row" },
      el("label", {}, "모드 ", form.mode),
      el("label", {}, " 점 예산 ", form.budgetPoints),
      el("label", {}, " 이터 상한 ", form.budgetIters),
      el("label", {}, " mach 점수 ", form.nMach),
      el("label", {}, " 고도[m] ", form.altsText),
      el("label", {}, " 연료[kg] ", form.fuelsText),
      el("button", { onclick: start }, "자동 설계 시작"),
      " ", listBox,
    ),
    errBox, progressBox, resultBox,
  );

  if (runningJobId) {
    attachProgress(progressBox, runningJobId, {
      onDone: onJobDone,
      onError: (e) => clear(errBox).append(el("div", { class: "error-box" }, errorText(e))),
    });
  }
  loadDefaults();
  loadList();
  return root;
}

function sevChip(status) {
  const s = status ?? "na";
  return el("span", {
    style: `display:inline-block;padding:0 .5em;border-radius:8px;color:#fff;`
      + `background:${SEV_COLOR[s] ?? SEV_COLOR.na}`,
  }, s === "na" || status == null ? "미판정" : s);
}

function renderResult(box, body, resultId, ctx) {
  const report = body.report ?? {};
  const rows = pointRows(body);
  const cards = actionCards(body);

  const pointsTable = el("table", { class: "data" },
    el("thead", {}, el("tr", {},
      ...["이름", "mach", "고도", "연료", "역할", "트림", "판정"].map((h) => el("th", {}, h)))),
    el("tbody", {}, rows.map((r) => el("tr", {},
      el("td", {}, r.name),
      el("td", {}, fmt(r.mach)),
      el("td", {}, fmt(r.alt)),
      el("td", {}, fmt(r.fuel)),
      el("td", {}, ROLE_LABEL[r.role] ?? r.role),
      el("td", {}, r.trimmable === false ? "불가" : r.trimmable ? "OK" : "미판정"),
      el("td", {}, sevChip(r.status)),
    ))),
  );

  const approveBoxes = new Map();
  const cardEl = (a) => el("div", { class: "card" },
    el("label", {},
      a.action.type === "escalate" ? null
        : (() => {
          const cb = el("input", { type: "checkbox", checked: true });
          approveBoxes.set(a.id, cb);
          return cb;
        })(),
      el("strong", {}, ` ${VERDICT_LABEL[a.verdict] ?? a.verdict}`),
    ),
    el("div", { class: "hint" }, `${a.case} · ${a.loop}`),
    evidenceLine(a),
  );

  const resume = async () => {
    const approved = [...approveBoxes.entries()]
      .filter(([, cb]) => cb.checked).map(([id]) => id);
    if (!approved.length) {
      clear(ctx.errBox).append(el("div", { class: "error-box" },
        "승인한 처방이 없다 — 최소 1개를 선택하거나 세션을 종료 상태로 두세요."));
      return;
    }
    try {
      clear(ctx.errBox);
      const job = await api.post(`/design/${resultId}/resume`, { approved });
      runningJobId = job.id;
      attachProgress(ctx.progressBox, job.id, {
        onDone: async (j) => {
          runningJobId = null;
          if (!cancelledWithoutResult(j)) await ctx.showResult(j.result_id);
        },
        onError: (e) => clear(ctx.errBox).append(
          el("div", { class: "error-box" }, errorText(e))),
      });
    } catch (e) {
      clear(ctx.errBox).append(el("div", { class: "error-box" }, errorText(e)));
    }
  };

  const adopt = () => {
    const payload = adoptStorePayload(body);
    store.set("gainTables", payload.tables && JSON.parse(JSON.stringify(payload.tables)));
    store.set("gainScheduleOff", payload.scheduleOff);
    // 출처 — 게인 탭이 되읽을 때 "무엇이 걸려 있는지"를 이름으로 말해 준다
    store.set("gainTablesSource", { kind: "autodesign", resultId });
    clear(adoptMsg).append(el("span", { class: "hint" },
      " 확정됨 — 게인 탭·시뮬레이션·Autocode·구조도·영향성이 이 스케줄을 소비한다"
      + " (Autocode 형상 지문이 바뀌는 것으로 확인된다)."
      + " 게인 탭은 자리마다 다른 breakpoint를 합집합 축으로 정렬해 보여 주며,"
      + " 거기서 편집한 뒤 [시뮬·코드에 적용]을 누르면 이 확정을 덮어쓴다."
      + " 다항 정본은 결과 JSON의 gain_export.tables — API 직접 주입용."));
  };
  const adoptMsg = el("span");

  const sections = [
    el("h3", {}, `결과 ${resultId}`),
    el("p", {},
      "상태 ", sevChip(report.status === "converged" ? "ok"
        : report.status === "awaiting_approval" ? "warn" : "na"),
      ` ${report.status ?? "?"} · 스테이지 ${report.stage ?? "?"} · 이터레이션 `
      + `${report.iterations ?? 0} · 점 ${report.n_points ?? rows.length} `
      + `(앵커 ${report.points?.anchor ?? "?"} · bp ${report.points?.breakpoint ?? "?"} `
      + `· 검증 ${report.points?.validation ?? "?"}) · 실패 ${report.failures ?? 0}`),
    el("h4", {}, "운영점"),
    pointsTable,
  ];

  if (cards.approvable.length) {
    sections.push(
      el("h4", {}, "처방 카드 (승인 후 재개)"),
      ...cards.approvable.map(cardEl),
      el("button", { onclick: resume }, "승인 반영 재개"),
    );
  }
  if (cards.escalations.length) {
    sections.push(
      el("h4", {}, "에스컬레이션 — 상위 설계 변경 검토 (자동 적용 없음)"),
      ...cards.escalations.map(cardEl),
    );
  }
  if (body.gain_export && (Object.keys(body.gain_export.tables_resampled ?? {}).length
      || Object.keys(body.gain_export.constants ?? {}).length)) {
    sections.push(
      el("h4", {}, "게인 확정"),
      el("p", { class: "hint" },
        `스케줄 자리 ${Object.keys(body.gain_export.tables ?? {}).length}개 · `
        + `상수 자리 ${Object.keys(body.gain_export.constants ?? {}).length}개`),
      el("button", { onclick: adopt }, "게인 확정 (스토어 주입)"), adoptMsg,
    );
  }
  clear(box).append(...sections);
}

function evidenceLine(a) {
  const ev = a.evidence ?? {};
  const bits = [];
  const cur = ev.current ?? {};
  if (cur.pm_deg != null) bits.push(`현재 PM ${fmt(cur.pm_deg)}° / GM ${fmt(cur.gm_db)} dB`);
  if (cur.zeta != null) bits.push(`현재 ζ ${fmt(cur.zeta)}`);
  if (ev.interp_gap?.max != null) {
    bits.push(`보간 괴리 ${fmt(100 * ev.interp_gap.max, 3)}% (허용 ${fmt(100 * (ev.interp_gap.tol ?? 0), 2)}%)`);
  }
  if (ev.plant?.d_total != null) {
    bits.push(`플랜트 거리 ${fmt(ev.plant.d_total)} (허용 ${fmt(ev.plant.tol)})`);
  }
  if (ev.bottleneck) {
    bits.push(`ωc/작동기 ${fmt(ev.bottleneck.wc_over_actuator)} · 지연 위상 `
      + `${fmt(ev.bottleneck.delay_phase_deg_at_wc)}°`);
  }
  return el("div", { class: "hint" }, bits.join(" · ") || "—");
}
