/** 자동 설계 뷰 — 트림 자동화→게인 튜닝→스케줄 적합→마진 검증→원인별 처방 루프.

설계 루프 전체(M17 DesignSession)를 잡 하나로 돌리고, gated(기본)면 처방 카드에서
멈춘다 — 승인한 처방만 반영해 재개한다. 에스컬레이션(상위 설계 변경)은 어느
모드에서도 자동 적용되지 않고 보고 패널에만 남는다.

수치의 정본은 서버 /design/defaults(← 엔진 AutoDesignConfig) — 폼은 채운 칸만
config 덮어쓰기로 보낸다. "게인 확정"은 결과의 호환 반출(재샘플 테이블)을 기존
스토어 계약(`gainTables` + 출처 `gainTablesSource`)으로 주입한다 — 시뮬·Autocode·
블록도·영향성이 그대로 소비하고, 게인 탭은 그것을 **되읽어** 표·차트로 보여 준다
(자리마다 다른 breakpoint는 합집합 축으로 정렬 — lib/gainsched alignTables).

스타일은 app.css 비접촉 — 심각도 색은 값으로 지정 (duty.js 선례).
*/

import { api, errorText } from "../api.js";
import { clear, el, fmt } from "../dom.js";
import {
  CRITERIA_FIELDS, TARGET_FIELDS, VERDICT_LABEL, actionCards, adoptBlockedText,
  adoptStorePayload, adoptWarnText, buildConfig, coverageLines, evidenceLines,
  ledgerRows, ledgerTruncatedText, pointRows, reportLine, resumable, resumeBlockedText,
  statusCounts, statusSeverity, statusText, trimLabel, verdictLegend,
} from "../lib/autodesign.js";
import { slotIndex, withConstant } from "../lib/gainsync.js";
import { store } from "../store.js";
import { attachProgress, cancelledWithoutResult } from "./progress.js";

const SEV_COLOR = { ok: "#34c759", warn: "#ff9500", fail: "#ff3b30", na: "#8e8e93" };
// 무효 처방은 "미달"이면서 동시에 "예산을 태운 처방"이라 다른 미달과 같은 색으로
// 두면 눈에 안 띈다 — 판정 4색과 섞이지 않는 보라를 따로 준다 (lib ledgerTone)
const LEDGER_COLOR = { ...SEV_COLOR, ineffective: "#af52de" };
// 범례 색을 고르는 순서 — 한 종류가 여러 색으로 뜰 때 가장 심한 쪽을 세운다
const LEDGER_TONE_RANK = { ok: 0, na: 1, warn: 2, ineffective: 3, fail: 4 };
const ROLE_LABEL = { anchor: "앵커(트림·선형화)", breakpoint: "게인 breakpoint", validation: "검증점" };
// 원장은 수십 행이 될 수 있다 — 심각도 상위만 펼치고 나머지는 접는다
const LEDGER_TOP_N = 20;

// 탭 이탈·재진입에도 실행 중 잡·최근 결과를 잃지 않는다 (progress.js 재부착 규약)
let runningJobId = null;
let lastResultId = null;
// /design/defaults 응답 전체 — 폼 placeholder와 사유 코드 사전(reason_text)의 출처.
// 사전은 서버가 정본이고 웹 폴백은 lib/autodesign.REASON_TEXT다
let designDefaults = null;

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
    actuatorWn: el("input", { size: 5 }),
    actuatorZeta: el("input", { size: 5 }),
    delayS: el("input", { size: 6 }),
    // 중첩 덮어쓰기 칸 — 채운 것만 config.criteria / config.targets로 나간다
    criteria: Object.fromEntries(CRITERIA_FIELDS.map(([k]) => [k, el("input", { size: 5 })])),
    targets: Object.fromEntries(TARGET_FIELDS.map(([k]) => [k, el("input", { size: 5 })])),
  };

  const loadDefaults = async () => {
    try {
      const d = await api.get("/design/defaults");
      designDefaults = d;
      const c = d.config;
      form.mode.value = c.mode;
      // 기본값은 placeholder로만 — 값으로 채우면 사용자가 안 건드린 칸까지 덮어쓰기로
      // 나가고, 서버 기본값이 바뀌어도 화면이 옛 수치를 계속 보낸다
      const ph = (input, v) => { if (v != null) input.placeholder = String(v); };
      for (const [k] of CRITERIA_FIELDS) ph(form.criteria[k], c.criteria?.[k]);
      for (const [k] of TARGET_FIELDS) ph(form.targets[k], c.targets?.[k]);
      ph(form.actuatorWn, c.actuator_wn);
      ph(form.actuatorZeta, c.actuator_zeta);
      ph(form.delayS, c.delay_s);
      defaultsBox.textContent =
        `합격기준 PM ≥ ${c.criteria.pm_min_deg}° · GM ≥ ${c.criteria.gm_min_db} dB · `
        + `ζ ≥ ${c.criteria.zeta_min} — 설계 목표 PM ${c.targets.pm_deg}° / GM `
        + `${c.targets.gm_db} dB · ζsp ${c.targets.zeta_sp} (정본: 엔진 AutoDesignConfig)`;
    } catch (e) {
      defaultsBox.textContent = `기본값 조회 실패: ${errorText(e)}`
        + " — 아래 [요구 조정] 칸은 기본값을 못 보여 주고, 사유 코드는 웹 폴백 문구로 뜬다.";
    }
  };

  const showResult = async (resultId) => {
    lastResultId = resultId;
    const body = await api.get(`/results/${resultId}`);
    renderResult(resultBox, body, resultId, { errBox, progressBox, showResult });
  };

  const onJobDone = async (job) => {
    runningJobId = null;
    // watchJob은 error에서도 resolve한다 — 가드가 없으면 result_id=null로 조회해
    // "결과 없음 404"만 뜨고 **정작 실패 사유가 화면에 안 나온다**. 이 잡의 가장
    // 흔한 실패가 예산 초과처럼 사유 문장이 전부인 경우다 (views/sim.js와 같은 가드)
    if (job.status === "error") {
      clear(errBox).append(el("div", { class: "error-box" },
        `자동 설계 실패 — ${job.error ?? "사유 없음"}`));
      return;
    }
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
      const values = (inputs) =>
        Object.fromEntries(Object.entries(inputs).map(([k, i]) => [k, i.value]));
      const config = buildConfig({
        mode: form.mode.value,
        budgetPoints: form.budgetPoints.value,
        budgetIters: form.budgetIters.value,
        nMach: form.nMach.value,
        altsText: form.altsText.value,
        fuelsText: form.fuelsText.value,
        actuatorWn: form.actuatorWn.value,
        actuatorZeta: form.actuatorZeta.value,
        delayS: form.delayS.value,
        criteria: values(form.criteria),
        targets: values(form.targets),
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

  const fieldRow = (fields, inputs) => el("div", { class: "form-row" },
    fields.map(([k, label]) => el("label", {}, `${label} `, inputs[k])));

  // 서버는 이 중첩 덮어쓰기를 이미 받는다(routes/design.py _build_config) — 화면만
  // 안 내주고 있었다. 접어 두는 이유는 기본값이 정본이고 조정이 예외이기 때문이다
  const tuningBox = el("details", {},
    el("summary", { class: "hint" },
      "요구 조정 — 합격기준·튜닝 목표·작동기·지연 (비우면 서버 기본값)"),
    el("p", { class: "hint" },
      "채운 칸만 config 덮어쓰기로 나간다. 회색 수치가 서버 기본값이다. "
      + "튜닝 목표가 합격선보다 낮으면 서버가 422로 거절한다 — 튜닝이 성공한 점이 "
      + "곧바로 fail로 찍히기 때문이다(PM은 목표 ≥ 합격선, GM은 목표 ≥ 목표선). "
      + "여기서 바꾼 합격기준은 결과에 동봉되어 마진 탭 색과 판정어 설명에도 그대로 쓰인다."),
    el("p", { class: "hint" }, "합격기준 (판정선)"),
    fieldRow(CRITERIA_FIELDS, form.criteria),
    el("p", { class: "hint" }, "튜닝 목표 (설계선)"),
    fieldRow(TARGET_FIELDS, form.targets),
    el("p", { class: "hint" }, "작동기·지연 예산 (마진의 병목이 되는 상위 설계값)"),
    el("div", { class: "form-row" },
      el("label", {}, "작동기 wn [rad/s] ", form.actuatorWn),
      el("label", {}, " 작동기 ζ ", form.actuatorZeta),
      el("label", {}, " 총 지연 [s] ", form.delayS),
    ),
  );

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
    tuningBox,
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

/** 판정 개수 한 줄 — 표를 눈으로 세지 않아도 규모를 알 수 있게. */
function countsLine(rows) {
  const c = statusCounts(rows);
  const parts = [];
  for (const k of ["ok", "warn", "fail", "na"]) {
    if (c[k]) parts.push(el("span", {}, " ", sevChip(k), ` ${c[k]}`));
  }
  if (c.outside) {
    parts.push(el("span", { class: "hint" },
      ` · 엔벨로프 경계 ${c.outside} (포화·α 여유 미달 — 튜닝·처방 대상 밖이라 판정에서 제외)`));
  }
  if (c.unjudged) parts.push(el("span", { class: "hint" }, ` · 미판정 ${c.unjudged}`));
  return el("p", {}, "점 판정", ...parts);
}

/** 판정어의 뜻 — 칩만 띄우고 뜻을 안 적으면 warn이 잡음인지 신호인지 알 수 없다. */
function legendBox(criteria) {
  return el("details", {},
    el("summary", { class: "hint" }, "판정어의 뜻 (ok · warn · fail · na)"),
    el("ul", { class: "hint" }, verdictLegend(criteria).map((l) =>
      el("li", {}, sevChip(l.key), ` ${l.text}`))),
    el("p", { class: "hint" },
      "warn은 자동 설계가 실패한 것이 아니다 — 튜닝은 목표를 맞췄는데 그 사이를 잇는 "
      + "스케줄 곡선이 목표선 아래로 내려온 자리다. 줄이려면 그 구간에 breakpoint를 "
      + "늘리거나(처방 카드가 이미 그것을 제안한다) 적합 허용치를 조인다. "
      + "fail은 다르다 — 합격선 미달이라 그대로 확정하면 안 된다."));
}

/** 검증 커버리지 — 무엇을 안 봤나. 볼 것이 없으면 null (el은 null 자식을 거른다).
 *
 * 상태 줄 바로 아래 자리다. 판정·실패 수는 **본 것만** 세므로, 안 본 것이 많을수록
 * 그 수치는 오히려 건강해 보인다 — 검증점이 0이면 실패도 0이다. 공백이 있으면
 * 회색 hint가 아니라 경고 톤으로 낸다. */
function coverageBox(report) {
  const lines = coverageLines(report);
  if (!lines.length) return null;
  const strong = lines.some((l) => l.tone !== "hint");
  return el("div", {},
    el("p", { class: strong ? null : "hint" }, strong
      ? el("strong", {}, "검증 커버리지 — 이 실행이 안 본 것")
      : "검증 커버리지"),
    ...lines.map((l) => {
      if (l.tone === "hint") return el("div", { class: "hint" }, l.text);
      const color = l.tone === "fail" ? SEV_COLOR.fail : SEV_COLOR.warn;
      return el("div", { style: `color:${color}` },
        l.tone === "fail" ? el("strong", {}, l.text) : l.text);
    }),
  );
}

/** 원장 표 한 벌 — 상위 N행과 접힌 나머지가 같은 모양이라 함수로 뽑는다. */
function ledgerTable(rows) {
  const cell = (line, kind) => {
    if (!line) return el("td", { class: "hint" }, "—");
    const color = kind === "short" ? SEV_COLOR.fail
      : kind === "spare" ? SEV_COLOR.ok : SEV_COLOR.na;
    return el("td", { style: `color:${color};text-align:left` }, line);
  };
  return el("table", { class: "data" },
    el("thead", {}, el("tr", {},
      ...["점", "자리", "종류 · 심각도", "판정", "요구 / 달성 / 부족", "사유", "처방"]
        .map((h) => el("th", {}, h)))),
    el("tbody", {}, rows.map((r) => el("tr", {},
      el("td", {}, r.point ?? "—"),
      // 점 단위 항목은 자리가 없다 — 빈칸으로 두면 앞 행의 자리로 읽힌다
      el("td", {}, r.loop ?? el("span", { class: "hint" }, "(점 전체)")),
      el("td", { style: "text-align:left" },
        el("div", { style: `color:${LEDGER_COLOR[r.tone] ?? SEV_COLOR.na}` },
          el("strong", {}, r.kindLabel)),
        // 못 잰 심각도를 0으로 그리면 최악이 최선처럼 보인다 — 낱말로 적는다
        el("div", { class: "hint" }, `심각도 ${r.severityText}`)),
      el("td", {}, r.status == null
        ? el("span", { class: "hint" }, "—") : sevChip(r.status)),
      cell(r.shortfallLine, r.shortfallKind),
      el("td", { style: "text-align:left" },
        r.reasonLine ? el("div", {}, r.reasonLine) : null,
        // 엔진이 낸 "왜 이 행이 있는가" 한 줄 — 사유 코드가 없는 종류는 이것뿐이다
        // (사유 줄과 같은 문장이면 lib이 이미 걸렀다)
        r.noteLine ? el("div", { class: "hint" }, r.noteLine) : null,
        !r.reasonLine && !r.noteLine ? el("div", { class: "hint" }, "—") : null),
      el("td", { style: "text-align:left" }, r.actionLine
        ? el("div", { style: r.action?.changed === false
          ? `color:${LEDGER_COLOR.ineffective}` : null }, r.actionLine)
        : el("span", { class: "hint" }, "처방 없음")),
    ))),
  );
}

/** 미달 원장 — 처방이 안 나온 미달까지 한 표에.
 *
 * 종전 화면은 처방 카드가 붙는 실패만 보여 줬다. 실제로는 튜닝이 설계 목표를 못
 * 채운 자리, 판정 불가, 엔벨로프 경계, 건너뛴 점, 트림 미수렴, 반영했는데 안 바뀐
 * 처방이 더 많고, 그것들은 화면 어디에도 없었다. **failures가 0이어도 원장이 비지
 * 않으면 이 절은 뜬다** — 실패 0이 곧 미달 0이 아니기 때문이다. */
function ledgerSection(rows, truncated) {
  const top = rows.slice(0, LEDGER_TOP_N);
  const rest = rows.slice(LEDGER_TOP_N);
  // 종류의 뜻은 표에 나온 종류만 — 안 나온 종류까지 설명하면 목록이 사전이 된다.
  // 한 종류가 두 색으로 뜰 수 있으므로(verify는 fail·warn 둘 다) 범례 색은 그 종류가
  // 실제로 낸 것 중 가장 심한 쪽으로 고정한다 — 먼저 만난 행의 색을 쓰면 같은 결과를
  // 다시 열 때마다 범례 색이 달라 보인다
  const kinds = new Map();
  for (const r of rows) {
    const k = r.kind ?? "?";
    const prev = kinds.get(k);
    if (!prev) kinds.set(k, r);
    else if (LEDGER_TONE_RANK[r.tone] > LEDGER_TONE_RANK[prev.tone]) kinds.set(k, r);
  }
  const out = [
    el("h4", {}, `미달 원장 (${rows.length}행)`),
    el("p", { class: "hint" },
      "처방 카드가 붙는 실패는 이 표의 일부다 — 처방이 안 나온 미달(튜닝 목표 미달·"
      + "판정 불가·엔벨로프 경계·트림 미수렴·튜닝 건너뜀·무효 처방)도 여기 모인다. "
      + "실패 0인 실행에도 행이 남을 수 있다. 심각도(요구선 대비 부족 비율) 내림차순이고, "
      + "못 잰 것이 맨 앞이다 — 얼마나 나쁜지 모르는 것이 가장 먼저 볼 자리다."),
  ];
  // 잘린 원장을 그대로 그리면 "미달은 이게 전부"라고 말하는 표가 된다
  if (truncated) {
    out.push(el("p", { style: `color:${SEV_COLOR.warn}` }, el("strong", {}, truncated)));
  }
  out.push(ledgerTable(top));
  if (rest.length) {
    out.push(el("details", {},
      el("summary", { class: "hint" },
        `나머지 ${rest.length}행 — 심각도 하위 (접힘)`),
      ledgerTable(rest)));
  }
  out.push(el("details", {},
    el("summary", { class: "hint" }, "종류의 뜻과 다음에 할 일"),
    el("ul", { class: "hint" }, [...kinds.values()].map((r) => el("li", {},
      el("strong", { style: `color:${LEDGER_COLOR[r.tone] ?? SEV_COLOR.na}` }, r.kindLabel),
      ` — ${r.kindText}`)))));
  return out;
}

function renderResult(box, body, resultId, ctx) {
  const report = body.report ?? {};
  const rows = pointRows(body);
  const cards = actionCards(body);
  const ledger = ledgerRows(body, designDefaults?.reason_text);

  const pointsTable = el("table", { class: "data" },
    el("thead", {}, el("tr", {},
      ...["이름", "mach", "고도", "연료", "역할", "트림", "판정"].map((h) => el("th", {}, h)))),
    el("tbody", {}, rows.map((r) => el("tr", {},
      el("td", {}, r.name),
      el("td", {}, fmt(r.mach)),
      el("td", {}, fmt(r.alt)),
      el("td", {}, fmt(r.fuel)),
      el("td", {}, ROLE_LABEL[r.role] ?? r.role),
      el("td", {}, trimLabel(r)),
      el("td", {}, r.outsideEnvelope
        ? el("span", { class: "hint" }, `(${r.status ?? "미판정"}) 판정 제외`)
        : sevChip(r.status)),
    ))),
  );

  const approveBoxes = new Map();
  // canApprove=false는 카드는 보이되 승인할 수 없는 자리다 (재개 불가 상태·에스컬레이션)
  // — 체크박스를 그리면 누를 수 있는 것처럼 보이고 재개는 서버가 409로 막는다
  const cardEl = (a, canApprove = true) => el("div", { class: "card" },
    el("label", {},
      !canApprove || a.action.type === "escalate" ? null
        : (() => {
          // 봉인·건너뜀 처방은 기본 해제 — 엔진 apply_actions는 승인만 하면 봉인된
          // 것도 그대로 반영한다(그리고 다시 봉인된다). 기본 체크로 두면 무효인 줄
          // 아는 처방에 이터 예산이 나간다. 끄기만 하고 막지는 않는다
          const dead = Boolean(a.sealed || a.skipped);
          const cb = el("input", { type: "checkbox", checked: !dead });
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
    // 취소 재개는 승인할 것이 없는 것이 정상이다 — 승인 대기일 때만 최소 1건을 요구한다
    if (!approved.length && report.status !== "cancelled") {
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
          if (j.status === "error") {
            clear(ctx.errBox).append(el("div", { class: "error-box" },
              `재개 실패 — ${j.error ?? "사유 없음"}`));
            return;
          }
          if (!cancelledWithoutResult(j)) await ctx.showResult(j.result_id);
        },
        onError: (e) => clear(ctx.errBox).append(
          el("div", { class: "error-box" }, errorText(e))),
      });
    } catch (e) {
      clear(ctx.errBox).append(el("div", { class: "error-box" }, errorText(e)));
    }
  };

  const adopt = async () => {
    const payload = adoptStorePayload(body);
    store.set("gainTables", payload.tables && JSON.parse(JSON.stringify(payload.tables)));
    store.set("gainScheduleOff", payload.scheduleOff);
    // 출처 — 게인 탭이 되읽을 때 "무엇이 걸려 있는지"를 이름으로 말해 준다
    store.set("gainTablesSource", { kind: "autodesign", resultId });

    // **상수 자리도 함께 채택한다.** 적합이 평탄하다고 판정한 자리는 테이블이 아니라
    // 상수로 나오는데(gain_export.constants), 그걸 빠뜨리면 시뮬·Autocode가 새 스케줄과
    // 옛 설계 상수를 섞어 돌린다 — 이 실행이 검증한 마진이 채택한 형상에 해당하지 않게
    // 된다. 자리→파라미터 대응은 카탈로그가 정본이라 여기서 불러 온다
    const consts = payload.constants;
    const constNames = Object.keys(consts);
    let constNote = "";
    if (constNames.length) {
      try {
        const cat = await api.get("/gains/catalog");
        const idx = slotIndex(cat);
        let params = {
          scas: store.get("scasParams") ?? null,
          autopilot: store.get("autopilotParams") ?? null,
        };
        const unknown = [];
        for (const [name, value] of Object.entries(consts)) {
          const slot = idx.get(name);
          if (!slot) { unknown.push(name); continue; }
          params = withConstant(cat, slot, Number(value), params);
        }
        store.set("scasParams", params.scas);
        store.set("autopilotParams", params.autopilot);
        constNote = ` 상수 자리 ${constNames.length - unknown.length}개도 함께 적용했다`
          + (unknown.length ? ` (카탈로그에 없는 자리 제외: ${unknown.join(", ")})` : "")
          + ".";
      } catch (e) {
        constNote = ` 상수 자리 ${constNames.length}개는 적용하지 못했다`
          + ` (${errorText(e)}) — 검증한 형상과 다르므로 다시 시도할 것.`;
      }
    }
    clear(adoptMsg).append(el("span", { class: "hint" },
      " 확정됨 — 게인 탭·시뮬레이션·Autocode·블록도·영향성이 이 스케줄을 소비한다"
      + " (Autocode 형상 지문이 바뀌는 것으로 확인된다)."
      + constNote
      + " 게인 탭은 자리마다 다른 breakpoint를 합집합 축으로 정렬해 보여 주며,"
      + " 거기서 편집한 뒤 [시뮬·코드에 적용]을 누르면 이 확정을 덮어쓴다."
      + " 다항 정본은 결과 JSON의 gain_export.tables — API 직접 주입용."));
  };
  const adoptMsg = el("span");

  const covBox = coverageBox(report);
  const sections = [
    el("h3", {}, `결과 ${resultId}`),
    el("p", {},
      "상태 ", sevChip(statusSeverity(report.status)), ` ${report.status ?? "?"} · `,
      // 계산해 놓고 안 내던 수치들 — 특히 판정 수가 없으면 "실패 0"의 뜻이 갈리지 않는다
      reportLine(report, rows.length).join(" · ")),
    // 영어 토큰만 찍으면 상태를 말하되 뜻과 다음 행동을 말하지 않는다
    el("p", { class: "hint" }, statusText(report.status)),
    // 상태 줄 바로 아래 — 이 실행이 무엇을 안 봤는지가 상태의 전제다.
    // sections는 native append로 펼쳐지므로 null을 넣으면 터진다 (el과 다르다)
    ...(covBox ? [covBox] : []),
    el("h4", {}, "운영점"),
    countsLine(rows),
    pointsTable,
    legendBox(body.margin_out?.criteria),
  ];

  // 실패가 0이어도 원장이 비지 않으면 뜬다 — 실패 0이 곧 미달 0이 아니다
  if (ledger.length) sections.push(...ledgerSection(ledger, ledgerTruncatedText(body)));

  if (cards.approvable.length && resumable(report)) {
    sections.push(
      el("h4", {}, "처방 카드 (승인 후 재개)"),
      ...cards.approvable.map((a) => cardEl(a)),
      el("button", { onclick: resume }, "승인 반영 재개"),
    );
  } else if (cards.approvable.length) {
    // 처방은 남았으나 서버가 재개를 거절하는 상태다(budget_exhausted 등). 종전에는
    // 카드 수만 보고 버튼을 그려, 누르면 409만 돌아오는 죽은 버튼이 떴다
    sections.push(
      el("h4", {}, "남은 처방 — 반영되지 않았다 (재개 불가)"),
      ...cards.approvable.map((a) => cardEl(a, false)),
      el("p", {}, el("strong", {}, resumeBlockedText(report))),
    );
  } else if (report.status === "cancelled") {
    // 취소된 세션은 승인할 처방이 없다 — 그렇다고 막다른 길이면 안 된다.
    // 서버는 남은 스테이지부터 이어 돌 수 있고(design.py), 트림·선형모델·튜닝
    // 결과가 세션에 그대로 남아 있어 재계산이 아니라 **이어붙이기**다
    sections.push(
      el("h4", {}, "중단된 세션"),
      el("p", { class: "hint" },
        "스테이지 도중에 취소되어 승인할 처방이 없습니다 — 완료된 트림·선형모델·"
        + "튜닝 결과는 그대로 남아 있어 남은 스테이지부터 이어서 돌 수 있습니다."),
      el("button", { onclick: resume }, "남은 스테이지 이어서 실행"),
    );
  }
  if (cards.escalations.length) {
    sections.push(
      el("h4", {}, "에스컬레이션 — 상위 설계 변경 검토 (자동 적용 없음)"),
      ...cards.escalations.map((a) => cardEl(a)),
    );
  }
  if (body.gain_export && (Object.keys(body.gain_export.tables_resampled ?? {}).length
      || Object.keys(body.gain_export.constants ?? {}).length)) {
    sections.push(
      el("h4", {}, "게인 확정"),
      el("p", { class: "hint" },
        `스케줄 자리 ${Object.keys(body.gain_export.tables ?? {}).length}개 · `
        + `상수 자리 ${Object.keys(body.gain_export.constants ?? {}).length}개`),
      // 확정 버튼만 있고 그다음이 없으면 "자동 설계를 돌린 뒤 무엇을 하라는 건지"가
      // 화면 어디에도 없다 — 소비 순서를 여기서 밝힌다
      el("p", { class: "hint" },
        "확정하면 이 스케줄이 게인 탭·시뮬레이션·마진·Autocode·블록도·영향성의 정본이 된다. "
        + "권장 순서: ① 게인 탭에서 곡선과 breakpoint를 확인한다(필요하면 편집 후 "
        + "[시뮬·코드에 적용] — 이 확정을 덮어쓴다) → ② 시뮬레이션 탭에서 비선형 응답을 "
        + "본다 → ③ 마진 탭에서 스케줄 게인으로 재검증한다 → ④ Autocode로 탑재 C를 "
        + "생성한다(형상 지문이 바뀌는 것으로 확정이 걸렸는지 확인된다)."),
    );
    if (report.failures) {
      sections.push(el("p", {}, el("strong", {},
        `실패 ${report.failures}건이 남아 있다 — 그대로 확정하면 그 운영점은 합격선 `
        + "미달인 채로 굳는다. 처방 카드를 승인해 재개하거나, 에스컬레이션이면 "
        + "작동기·지연 예산 같은 상위 설계를 먼저 정한 뒤 다시 돌릴 것.")));
    }
    // 실패 0은 통과의 근거가 못 된다 — 판정 수가 0이면 볼 것이 없었던 실행이고,
    // 그 게인을 확정하면 **아무것도 검증하지 않은 게인이 정본이 된다**
    const adoptBlocked = adoptBlockedText(report);
    if (adoptBlocked) {
      sections.push(el("p", {}, el("strong", {}, adoptBlocked)));
    } else {
      // 확정을 막지는 않는다 — 다만 무엇을 모르고 확정하는지는 버튼 옆에 적는다.
      // 커버리지 줄이 화면 위쪽에 있어도, 확정하는 순간에 다시 보이지 않으면
      // 스크롤 한 번에 잊힌다
      const warn = adoptWarnText(report);
      if (warn) {
        sections.push(el("p", { style: `color:${SEV_COLOR.warn}` }, el("strong", {}, warn)));
      }
      sections.push(
        el("button", { onclick: () => adopt().catch((e) =>
          clear(adoptMsg).append(el("span", { class: "error-box" }, errorText(e)))) },
          "게인 확정 (스토어 주입)"), adoptMsg,
      );
    }
  }
  clear(box).append(...sections);
}

/** 처방 카드의 근거 — 수치 계층은 lib/autodesign.evidenceLines, 여기는 배치만.
 *
 * 종전에는 카드에 실려 온 것의 절반이 버려졌다: 요구선·부족량(shortfall), 심각도,
 * 자유 게인 결과와 그 사유, 반영 효과, 봉인·건너뜀 사유, 완화 프로브의 from/to.
 * 그래서 화면은 "현재 PM 38.2°"만 말하고 그게 얼마나 모자란지를 말하지 못했다. */
function evidenceLine(a) {
  const reasonMap = designDefaults?.reason_text;
  const ev = evidenceLines(a, reasonMap);
  const lines = [];
  if (ev.head.length) lines.push(el("div", { class: "hint" }, ev.head.join(" · ")));
  // 요구 대비 부족이 이 카드에서 가장 먼저 읽어야 할 줄이다 — 흐린 회색에 묻히면
  // 안 된다. 부족은 빨강, 여유는 초록, 판정 불가는 회색 (SEV_COLOR 규약 그대로)
  for (const s of ev.shortfall) {
    const color = s.kind === "short" ? SEV_COLOR.fail
      : s.kind === "spare" ? SEV_COLOR.ok : SEV_COLOR.na;
    lines.push(el("div", { style: `color:${color}` }, s.text));
  }
  for (const t of ev.tuned) lines.push(el("div", { class: "hint" }, t));
  // 완화 프로브가 에스컬레이션 카드의 실질이다 — ωc/작동기와 지연 위상은 둘 다 ωc에
  // 비례해 같이 커지므로 어느 예산이 병목인지 알려 주지 못한다. 하나씩 풀어 본
  // 결과를 수치(무엇을 얼마에서 얼마로)와 함께 보인다
  for (const p of ev.relief) {
    lines.push(el("div", { style: `color:${p.resolves ? SEV_COLOR.ok : SEV_COLOR.na}` }, p.text));
  }
  if (ev.effect) {
    lines.push(ev.effect.ineffective
      ? el("div", { style: `color:${SEV_COLOR.warn}` }, ev.effect.text)
      : el("div", { class: "hint" }, ev.effect.text));
  }
  // "무엇을 바꾸면 통과하는가"가 결론이다 — 흐린 회색 나열에 묻히면 사용자는 이
  // 카드를 보고도 다음 행동을 정할 수 없다
  for (const n of ev.notes) {
    lines.push(el("div", { class: "hint" }, el("strong", {}, n)));
  }
  for (const f of ev.flags) lines.push(el("div", { style: `color:${SEV_COLOR.warn}` }, f));
  if (!lines.length) lines.push(el("div", { class: "hint" }, "—"));
  return el("div", {}, ...lines);
}
