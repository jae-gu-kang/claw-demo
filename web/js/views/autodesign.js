/** 자동 설계 뷰 — 트림 자동화→게인 튜닝→스케줄 적합→마진 검증→원인별 처방 루프.

배치는 다른 탭과 같은 규약이다(views/stage.js): **보고서가 전면**이고 실행 설정·요구
조정은 패널이다. 이 탭의 답은 "이 형상이 전 구간에서 합격하는가, 아니면 무엇을
승인해야 하는가"이고 그건 보고서가 낸다 — 설정 폼이 그 위를 덮고 있으면 매 실행마다
답을 찾아 스크롤해야 한다.

설계 루프 전체(M17 DesignSession)를 잡 하나로 돌리고, gated(기본)면 처방 카드에서
멈춘다 — 승인한 처방만 반영해 재개한다. 에스컬레이션(상위 설계 변경)은 어느
모드에서도 자동 적용되지 않고 보고 패널에만 남는다.

수치의 정본은 서버 /design/defaults(← 엔진 AutoDesignConfig) — 폼은 채운 칸만
config 덮어쓰기로 보낸다. "게인 확정"은 결과의 반출 표(표 모드면 검증한 표 그 자체, 다항
모드면 재샘플 테이블 — lib/autodesign 머리말)를 기존 스토어 계약(`gainTables` + 출처 `gainTablesSource`)으로 주입한다 — 시뮬·Autocode·
블록도·영향성이 그대로 소비하고, 게인 탭은 그것을 **되읽어** 표·차트로 보여 준다
(자리마다 다른 breakpoint는 합집합 축으로 정렬 — lib/gainsched alignTables).

스타일은 app.css 비접촉 — 심각도 색은 값으로 지정 (duty.js 선례).

쇼케이스 신호(lib/showcasecue.js) — `design-and-apply`는 이 탭의 버튼 사슬을 **그 버튼들의 함수로**
끝까지 민다: [자동 설계 시작](신호 config를 칸에 채운 뒤) → 승인 대기면 기본 체크 그대로
[승인 반영 재개] → [게인 확정] → [문서에 반영]. `open`은 설계 흐름의 「결과 열기 →」와 같은 길이다.
사슬은 모듈 상태(`screen` — 지금 화면)로 그리므로 도중에 탭을 떠났다 와도 새 화면에 이어 그린다.
*/

import { ApiError, api, errorText } from "../api.js";
import { clear, el, fmt } from "../dom.js";
import {
  DEFAULT_FUEL_FRACS, VERDICT_LABEL, actionCards, actuatorLine,
  adoptBlockedText, adoptStorePayload, adoptWarnText, applyGateReason, approvedByDefault, buildConfig,
  configFormValues, coverageLines, criteriaSummaryModel, designCueSummary, emptyResultNotice, evidenceLines, excludedSamplesModel, fitFactsModel,
  fitQualityLines, fuelsPlaceholder, ledgerRows, ledgerTruncatedText, mergeDesignConfig, pointRows,
  reasonText, reportLine, resumable, resumeBlockedText, reverifyLines, statusCounts, statusSeverity,
  statusText, trimLabel, verdictLegend, warnNoteText,
} from "../lib/autodesign.js";
import { applyFreshnessBlock } from "../lib/flowsteps.js";
import { criteriaBadgeSpec, criteriaFreshness, resultFreshness } from "../lib/freshness.js";
import { slotIndex, withConstant } from "../lib/gainsync.js";
import { haltReason } from "../lib/showcase.js";
import { revealPanel } from "../lib/reveal.js";
import { failCue, reportCue, takeCue, unknownAction } from "../lib/showcasecue.js";
import { store } from "../store.js";
import { selectedDocument } from "./profilepick.js";
import { EXAMPLE_ID, currentSelection } from "../lib/profile.js";
import { attachProgress, cancelledWithoutResult } from "./progress.js";
import { errorWithSeedLink } from "./seedlink.js";
import { createDrawers, tabStage, tabTop } from "./stage.js";

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
let openDrawer = null; // 탭 재진입에도 열어 둔 패널 유지 (모듈 스코프 규약)
// /design/defaults 응답 전체 — 폼 placeholder와 사유 코드 사전(reason_text)의 출처.
// 사전은 서버가 정본이고 웹 폴백은 lib/autodesign.REASON_TEXT다
let designDefaults = null;
// 지금 화면 {errBox, progressBox, resultBox, form, start, showResult} — render()가 갈아 끼운다. 늦은 잡 콜백·
// 신호 사슬은 이것을 거쳐 그린다: 잡 도중 탭을 떠났다 오면 옛 화면(떨어져 나간 DOM)이 아니라
// 새 화면에 결과가 선다(flow.js repaint와 같은 규약)
let screen = null;
// 보고서 자리에 마지막으로 **요청한** 결과 — 늦게 온 옛 조회가 새로 고른 결과를 덮지 않게
let showTarget = null;
// 신호 사슬(design-and-apply)이 도는 중 — 두 번째 신호가 같은 잡을 겹쳐 걸지 않게
let cueBusy = false;
// 승인 → 재개 되풀이 상한 — 엔진 이터 예산(budget_iters)이 먼저 끊지만, 사슬이 영영 돌지 않게 둔다
const MAX_APPROVAL_ROUNDS = 20;

const errorLine = (msg) => el("div", { class: "error-box" }, msg);
const showErr = (msg) => { if (screen) clear(screen.errBox).append(errorLine(msg)); };

/** 잡 하나를 **지금 화면**의 진행바에 붙이고 끝까지 기다린 뒤 결과를 보고서 자리에 연다.
 *  버튼(시작·재개)과 신호 사슬이 같은 길이다. 돌려주는 것: {job, shown(보고서 손잡이)|null, error|null}.
 *  실패 문구는 오류 상자에도 그대로 선다 — watchJob은 error에서도 resolve하므로 가드가 없으면
 *  result_id=null로 조회해 "결과 없음 404"만 뜨고 정작 실패 사유가 안 나온다 (views/sim.js와 같은 가드). */
function followJob(jobId, failLabel) {
  runningJobId = jobId;
  const host = screen;
  host.syncEmpty(); // 빈 보고서 자리가 「아직 결과가 없습니다」 대신 도는 중이라고 말한다
  return new Promise((done) => {
    // 끝마다 빈 자리 안내를 되돌린다 — 성공이면 보고서가 이미 그 자리를 덮어 아무 일도 없다(먼저 풀면 본문을
    // 받는 사이 「아직 결과가 없습니다」가 비친다 — verify D11의 끝자락과 같은 순서 규약)
    const resolve = (v) => { screen?.syncEmpty(); done(v); };
    attachProgress(host.progressBox, jobId, {
      onDone: async (job) => {
        if (runningJobId === jobId) runningJobId = null;
        if (job.status === "error") {
          const msg = `${failLabel} — ${job.error ?? "사유 없음"}`;
          showErr(msg);
          resolve({ job, shown: null, error: msg });
          return;
        }
        if (cancelledWithoutResult(job)) {
          resolve({ job, shown: null, error: "취소됨 — 저장된 결과 없음" });
          return;
        }
        try {
          resolve({ job, shown: await screen.showResult(job.result_id), error: null });
        } catch (e) {
          showErr(errorText(e));
          resolve({ job, shown: null, error: errorText(e) });
        }
      },
      onError: (e) => {
        showErr(errorText(e));
        resolve({ job: null, shown: null, error: errorText(e) });
      },
    });
  });
}

export function render() {
  const errBox = el("div");
  const progressBox = el("div");
  const resultBox = el("div", { class: "tab-sheet" }); // 전면 — 이 탭의 답
  const defaultsBox = el("p", { class: "hint" }, "기본값 불러오는 중…");
  // 보고서 자리의 빈 안내 — 잡이 서 있으면 도는 중이라고 말한다(lib/autodesign emptyResultNotice).
  // 결과가 그 자리를 덮은 뒤에는 건드리지 않는다
  const emptyNote = el("p", { class: "hint" });
  const syncEmpty = () => {
    if (resultBox.firstChild === emptyNote) emptyNote.textContent = emptyResultNotice({ running: !!runningJobId });
  };

  const form = {
    mode: el("select", { "aria-label": "실행 모드" },
      el("option", { value: "gated", selected: true }, "승인 게이트 (gated)"),
      el("option", { value: "auto" }, "전자동 (auto)"),
    ),
    fitMode: el("select", { "aria-label": "게인 표현" },
      el("option", { value: "table", selected: true }, "표 (선형 보간)"),
      el("option", { value: "poly" }, "다항"),
    ),
    budgetPoints: el("input", { size: 5, placeholder: "200" }),
    budgetIters: el("input", { size: 3, placeholder: "5" }),
    nMach: el("input", { size: 3, placeholder: "5" }),
    nValidationBetween: el("input", { size: 3, placeholder: "1" }),
    altsText: el("input", { size: 16, placeholder: "0 1000 3000 5000" }),
    // 연료 기본은 기체 값이다(엔진: fuel_max × 비율) — 고른 기체 문서가 도착하면 loadDefaults가
    // 채운다. 옛 1200 kg 기체의 "40 200 400"을 자리표시로 물려주지 않는다(기체 고정 금지)
    fuelsText: el("input", { size: 12 }),
    actuatorWn: el("input", { size: 5 }),
    actuatorZeta: el("input", { size: 5 }),
    delayS: el("input", { size: 6 }),
  };
  // 판정선·튜닝 목표 — 읽기 전용. 선택 기체 문서의 /criteria·/tuning이 정본이고 서버가 그것으로 설계한다
  const criteriaBox = el("div", {}, el("p", { class: "hint" }, "판정선·튜닝 목표 불러오는 중…"));

  const loadDefaults = async () => {
    try {
      const d = await api.get("/design/defaults");
      designDefaults = d;
      const c = d.config;
      // 신호 사슬이 이미 칸을 채웠으면(모드·표현 포함) 늦게 온 기본값이 화면을 되돌리지 않는다
      if (!cueBusy) {
        form.mode.value = c.mode;
        // 기본 표현도 엔진이 정본이다 — 여기서 고정하면 엔진 기본값이 바뀌어도 화면이
        // 옛 표현을 보내고, 사용자는 안 고른 표현으로 도는 것을 모른다
        if (c.fit_mode) form.fitMode.value = c.fit_mode;
      }
      // 기본값은 placeholder로만 — 값으로 채우면 사용자가 안 건드린 칸까지 덮어쓰기로
      // 나가고, 서버 기본값이 바뀌어도 화면이 옛 수치를 계속 보낸다
      const ph = (input, v) => { if (v != null) input.placeholder = String(v); };
      ph(form.delayS, c.delay_s);
      // 격자 기본 — 서버가 내면(grid) 그쪽이 정본, 아니면 엔진 기본의 사본
      ph(form.altsText, Array.isArray(d.grid?.alts) ? d.grid.alts.join(" ") : null);
      defaultsBox.textContent = "판정선·튜닝 목표는 고른 기체 문서의 값으로 설계한다 — [판정선·튜닝 목표] 패널."
        + " 나머지 칸의 회색 수치가 서버 기본값이다(정본: 엔진 AutoDesignConfig).";
      // 연료·작동기 기본은 **고른 기체 문서**에서 — config 기본이 비어 있으면(기체 작동기를 쓰는 엔진)
      // 문서 actuator.params가 자리표시다. 문서를 못 받으면 칸을 비워 둔다(모르는 값을 수치로 위장 않음)
      const doc = await selectedDocument().catch(() => null);
      ph(form.fuelsText, fuelsPlaceholder(doc?.mass?.fuel_max, d.grid?.fuel_fracs ?? DEFAULT_FUEL_FRACS) || null);
      ph(form.actuatorWn, c.actuator_wn ?? doc?.actuator?.params?.wn);
      ph(form.actuatorZeta, c.actuator_zeta ?? doc?.actuator?.params?.zeta);
    } catch (e) {
      defaultsBox.textContent = `기본값 조회 실패: ${errorText(e)}`
        + " — 아래 [요구 조정] 칸은 기본값을 못 보여 주고, 사유 코드는 웹 폴백 문구로 뜬다.";
    }
  };

  const loadCriteria = async () => {
    const sel = currentSelection() ?? { id: EXAMPLE_ID };
    try {
      const body = await api.get(`/profiles/${encodeURIComponent(sel.id)}/criteria`);
      clear(criteriaBox).append(...criteriaSummary(body));
    } catch (e) {
      clear(criteriaBox).append(el("p", { class: "hint" },
        `판정선·튜닝 목표 조회 실패: ${errorText(e)} — 서버는 그래도 선택 기체 문서의 값으로 설계한다.`));
    }
  };

  /** 보고서 자리에 결과를 연다 — 손잡이(renderResult가 돌려준 재개·확정·반영 함수)를 돌려준다.
   *  그사이 **다른** 결과를 열라는 요청이 왔으면 늦은 이쪽은 그리지 않고 null(같은 결과면 둘 다 그린다 —
   *  잡 재부착과 신호 사슬이 같은 결과를 두 번 여는 것은 무해하다). */
  const showResult = async (resultId) => {
    showTarget = resultId;
    const body = await api.get(`/results/${resultId}`);
    if (showTarget !== resultId) return null;
    lastResultId = resultId;
    return renderResult(resultBox, body, resultId, { errBox });
  };

  // 재부착 전용 — 잡 도중 탭을 떠났다 온 화면이 그 잡의 끝을 받는다(시작·재개는 followJob)
  const onJobDone = async (job) => {
    if (runningJobId === job.id) runningJobId = null;
    try {
      await onJobSettled(job);
    } finally {
      syncEmpty(); // 결과 없이 끝났으면(실패·취소) 빈 안내를 쉬는 중으로
    }
  };
  const onJobSettled = async (job) => {
    if (job.status === "error") {
      clear(errBox).append(errorLine(`자동 설계 실패 — ${job.error ?? "사유 없음"}`));
      return;
    }
    if (cancelledWithoutResult(job)) return;
    try {
      await showResult(job.result_id);
    } catch (e) {
      clear(errBox).append(errorLine(errorText(e)));
    }
  };

  /** [자동 설계 시작] — 칸의 덮어쓰기(+ extra, 신호가 준 config)로 잡을 건다. 수치 목록 오류·제출
   *  거절은 던진다(부르는 쪽이 표시). 돌려주는 것: {jobId, done: followJob 약속}. */
  const start = async (extra = null) => {
    clear(errBox);
    const config = mergeDesignConfig(buildConfig({
      mode: form.mode.value,
      fitMode: form.fitMode.value,
      budgetPoints: form.budgetPoints.value,
      budgetIters: form.budgetIters.value,
      nMach: form.nMach.value,
      nValidationBetween: form.nValidationBetween.value,
      altsText: form.altsText.value,
      fuelsText: form.fuelsText.value,
      actuatorWn: form.actuatorWn.value,
      actuatorZeta: form.actuatorZeta.value,
      delayS: form.delayS.value,
    }), extra); // 판정선·튜닝 목표는 싣지 않는다 — mergeDesignConfig가 신호 config에서도 뗀다
    const job = await api.post("/design/auto", { config });
    return { jobId: job.id, done: followJob(job.id, "자동 설계 실패") };
  };
  // 게인 미설계 기체는 제출이 422다(튜너 브래킷이 설계값에서 나온다, 05 §7.4) — 채우러 가는 길이 선다
  const startClick = () => start().catch(
    (e) => clear(errBox).append(...errorWithSeedLink(e, "여기서 다듬습니다.")));

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
        (e) => clear(errBox).append(errorLine(errorText(e)))));
      listBox.append(sel);
      // 재진입 복원 — 다른 결과를 여는 중이면(인계·신호·잡 끝) 끼어들지 않는다
      if (lastResultId && showTarget === lastResultId && items.some((m) => m.id === lastResultId)) {
        showResult(lastResultId).catch(() => {});
      }
    } catch { /* 목록 실패는 시작 흐름을 막지 않는다 */ }
  };

  const listBox = el("span");

  const drawers = createDrawers({
    id: "autodesign-drawer",
    initial: openDrawer,
    onOpen: (k) => { openDrawer = k; },
    defs: [
      { key: "run", label: "실행 설정", group: "입력",
        title: "모드·예산·격자 — 매 실행 전에 정하는 것",
        build: () => [
          el("h2", {}, "실행 설정"),
          defaultsBox,
          el("div", { class: "form-row" },
            el("label", {}, "모드 ", form.mode),
            el("label", {}, " 게인 표현 ", form.fitMode),
            el("label", {}, " 점 예산 ", form.budgetPoints),
            el("label", {}, " 이터 상한 ", form.budgetIters),
            el("label", {}, " mach 점수 ", form.nMach),
            el("label", {}, " 구간당 검증점 ", form.nValidationBetween),
            el("label", {}, " 고도[m] ", form.altsText),
            el("label", {}, " 연료[kg] ", form.fuelsText)),
          el("p", { class: "hint" },
            "승인 게이트(gated)는 처방 카드에서 멈춘다 — 승인한 처방만 반영해 재개한다. "
            + "전자동(auto)은 예산이 다할 때까지 스스로 순환한다. "
            + "에스컬레이션(상위 설계 변경)은 어느 모드에서도 자동 적용되지 않는다."),
          el("p", { class: "hint" },
            "게인 표현 — 「표」는 튜닝값을 그대로 분할점에 놓는다(적합 없음): 급변을 "
            + "뭉개지 않고, 채택하는 표가 검증받은 그 표다. 대신 스케줄 축(기본 마하) 하나로 "
            + "펴면서 다른 축(고도·연료) 샘플을 평균하므로 값이 오르내릴 수 있다 — 그 거칠기는 결과의 "
            + "「적합 보고」 줄에 톱니·교차축 잔차로 나온다(적합 품질 문턱을 켜면 기울기 점프로 판정한다). "
            + "튜닝이 성립하지 않은 점의 표본은 두 표현 모두 적합에서 빼고 이웃 보간으로 채운다. "
            + "「다항」은 매끄럽고 계수가 적지만 급변을 뭉개고, 채택 시 재양자화 표로 판정을 다시 받는다."),
        ] },
      { key: "tuning", label: "요구 조정", group: "입력",
        title: "판정선·튜닝 목표(기체 문서 — 읽기 전용)·작동기·지연(비우면 서버 기본값)",
        build: () => [
          el("h2", {}, "요구 조정 — 판정선·튜닝 목표·작동기·지연"),
          el("p", { class: "hint" }, "판정선·튜닝 목표 (고른 기체 문서의 /criteria·/tuning — 읽기 전용)"),
          criteriaBox,
          el("p", { class: "hint" }, "작동기·지연 예산 (마진의 병목이 되는 상위 설계값 — 채운 칸만 덮어쓴다)"),
          el("div", { class: "form-row" },
            el("label", {}, "작동기 wn [rad/s] ", form.actuatorWn),
            el("label", {}, " 작동기 ζ ", form.actuatorZeta),
            el("label", {}, " 총 지연 [s] ", form.delayS)),
        ] },
      { key: "pipeline", label: "이 탭이 하는 일", group: "설명",
        build: () => [
          el("h2", {}, "설계 루프 한 바퀴"),
          el("p", { class: "hint", style: "max-width:96ch" },
            "엔벨로프에서 coarse 트림 격자를 유도하고, 플랜트 변화량으로 격자를 세분화한 뒤 "
            + "운영점별 게인을 자동 튜닝해 스케줄 표현(기본은 표, 다항은 선택)으로 세우고, "
            + "보간 실효 게인으로 마진을 검증한다. "
            + "마진 부족은 원인별 처방(검증점 추가/앵커·breakpoint 승격/상위 설계 "
            + "에스컬레이션)으로 순환한다."),
          el("p", { class: "hint", style: "max-width:96ch" },
            "엔벨로프 탭의 ④ 제어 설계·스케줄링과 ⑥ 검증·마진 층을 한 잡으로 잇는 것이 "
            + "이 탭이다 — 설계점을 고르고, 게인을 배치하고, 그 사이를 다시 재는 순환."),
        ] },
    ],
  });

  const root = el("div", { class: "tab-page" },
    tabTop({
      title: "자동 설계",
      lead: "설계 루프 전체를 잡 하나로 돈다 — 트림 자동화 → 게인 튜닝 → 스케줄 적합 "
        + "→ 마진 검증 → 원인별 처방. 실행 설정과 요구 조정은 아래 패널에.",
      actions: [
        el("button", { class: "primary", onclick: startClick }, "자동 설계 시작"),
        listBox,
      ],
      extra: [progressBox, errBox],
    }),
    // 보고서 — 무대 바로 아래 판독 시트. 표·칩·처방 카드라 자기 테두리가 없다
    tabStage(resultBox),
    drawers.root,
  );

  screen = { errBox, progressBox, resultBox, form, start, showResult, syncEmpty };
  if (runningJobId) {
    attachProgress(progressBox, runningJobId, {
      onDone: onJobDone,
      onError: (e) => clear(errBox).append(errorLine(errorText(e))),
    });
  }
  clear(resultBox).append(emptyNote);
  syncEmpty(); // 잡 도중 재진입이면 처음부터 「도는 중」
  loadDefaults();
  loadCriteria();
  // 설계 흐름 탭의 「결과 열기 →」·결과 탭 브리핑의 「자동 설계 탭에서 보고서 열기」 인계 — 그 실행의
  // 보고서를 바로 연다 (store 규약: 한 번 읽고 지운다). 실패(그사이 삭제 등)는 조용히 넘기지 않고
  // 오류 상자가 말한다
  const handed = store.get("designOpen");
  if (handed) {
    store.set("designOpen", null);
    showResult(handed.resultId).catch(
      (e) => clear(errBox).append(errorLine(
        `인계된 결과 ${handed.resultId}를 열지 못했습니다 — ${errorText(e)}`)));
  }
  // 쇼케이스 신호 — 한 번 읽고 지운다. 목록 자동 열림(loadList)보다 먼저 걸어 둔다: 신호가 여는
  // 결과가 늦게 온 목록의 「지난 결과」를 이긴다(showTarget)
  const cue = takeCue("autodesign");
  if (cue) runCue(cue);
  loadList();
  return root;
}

/** 신호 처리 — 동작 둘. 어느 쪽이든 끝에 done/failed를 반드시 보고한다. */
async function runCue(cue) {
  if (cue.action === "open") {
    const rid = cue.args?.resultId;
    if (!rid) {
      failCue(cue, "open에는 resultId가 필요하다");
      return;
    }
    try {
      const shown = await screen.showResult(rid);
      if (!shown) throw new Error("그사이 다른 결과가 열렸다");
      revealPanel(screen?.resultBox); // 보고서 — 결과가 사는 자리를 청중 앞에(06 §2)
      reportCue(cue, { phase: "done", summary: designCueSummary(shown.body), resultId: rid,
        data: { resultId: rid, verdict: shown.body.report?.status ?? null } });
    } catch (e) {
      // errorText는 ApiError가 아니면 "Error: …" 머리를 단다 — 사유 문장만 싣는다
      failCue(cue, `결과 ${rid}를 열지 못했다 — ${e instanceof ApiError ? errorText(e) : (e?.message ?? String(e))}`);
    }
    return;
  }
  if (cue.action !== "design-and-apply") {
    unknownAction(cue);
    return;
  }
  if (cueBusy || runningJobId) {
    failCue(cue, "자동 설계 잡이 이미 돌고 있다 — 끝난 뒤 다시 건다");
    return;
  }
  cueBusy = true;
  try {
    const summary = await designAndApply(cue);
    // 보고서(운영점 판정·처방·확정) — 신호가 끝나면 그 자리를 화면에 올린다. 사슬 도중 탭을 떠났으면
    // screen은 새 화면이거나 떨어진 옛 화면이다 — 떨어진 노드는 lib/reveal이 굴리지 않는다
    revealPanel(screen?.resultBox);
    reportCue(cue, { phase: "done", ...summary });
  } catch (e) {
    const msg = e instanceof ApiError ? errorText(e) : (e?.message ?? String(e)); // 서버 detail은 곱게(생 JSON 금지)
    // 사슬이 멈춘 사유는 이 탭의 오류 상자에도 선다 — 버튼 경로는 각자 자리에 쓰지만 사슬은 손잡이를
    // 직접 불러 그 catch를 안 지난다(청중이 진행기 카드만 보고 탭에서는 이유를 못 본다)
    showErr(`자동 설계 → 문서 반영 사슬이 멈췄다 — ${msg}`);
    failCue(cue, msg);
  } finally {
    cueBusy = false;
  }
}

/** design-and-apply — 이 탭의 버튼 사슬을 버튼의 함수로 민다. 단계마다 progress를 보고하고, 끝의
 *  보고 조각({summary, resultId, data})을 돌려준다. 어느 단계든 못 하면 사유를 던진다. */
async function designAndApply(cue) {
  const config = cue.args?.config ?? {};
  const apply = cue.args?.apply !== false;
  const progress = (summary) => reportCue(cue, { phase: "progress", summary });
  // 멈춤 확인 — 잡이 취소됐거나(진행바 [취소]·진행기 [■ 중단]) 진행기가 이 실행을 끝냈으면(중단·시간
  // 초과 — store showcaseBusy가 거짓, views/showcase.js) 다음 단계로 넘어가지 않는다. 잡 사이 틈(결과
  // 조회·재개 제출·확정·반영)에 [■ 중단]이 눌리면 취소할 잡이 아직 없어, 안 보면 중단 뒤에 재개 잡이
  // 돌고 문서에 새 리비전이 써진다. 취소된 잡의 부분 결과는 보고서 상태가 승인 대기일 수도 있다(반출
  // 재검증 도중 취소 — 세션은 끝났고 저장도 됐다) — 그래서 보고서 상태가 아니라 잡 상태로 본다
  // 진행기 쪽 규칙은 한 곳(lib/showcase haltReason — 게인·영향성 탭과 같은 판정)
  const halt = (r = null) => {
    if (r?.job?.status === "cancelled") throw new Error("자동 설계 잡이 취소됐다 — 사슬을 멈춘다");
    const stop = haltReason(store.get("showcaseBusy"));
    if (stop) throw new Error(stop);
  };

  // ① 신호 config를 칸에 보이게 채운다 — 칸을 먼저 비우므로 결과가 「서버 기본값 + 신호 config」와
  //    같다(전에 누가 칸에 적어 둔 값이 섞이지 않는다). 칸이 없는 키는 start가 그대로 덧씌운다
  fillForm(screen.form, config);
  const first = await screen.start(config);
  reportCue(cue, { phase: "started", jobId: first.jobId });
  let r = await first.done;
  halt(r);
  if (!r.shown) throw new Error(r.error ?? "자동 설계 결과를 열지 못했다");
  let shown = r.shown;
  progress(`설계 — ${designCueSummary(shown.body)}`);

  // ② 승인 대기면 기본 체크 그대로 [승인 반영 재개] — 끝날 때까지(엔진 이터 예산이 끊는다)
  let rounds = 0;
  while (shown.body.report?.status === "awaiting_approval") {
    rounds += 1;
    if (rounds > MAX_APPROVAL_ROUNDS) {
      throw new Error(`승인·재개를 ${MAX_APPROVAL_ROUNDS}번 했는데도 승인 대기다 — 자동 설계 탭에서 확인한다`);
    }
    if (!shown.resume) throw new Error("승인 대기인데 승인할 처방 카드가 없다 — 자동 설계 탭에서 확인한다");
    halt();
    const res = await shown.resume();
    if (res.error) throw new Error(res.error);
    reportCue(cue, { phase: "started", jobId: res.jobId });
    progress(`처방 ${res.approved.length}건 승인 — 재개 ${rounds}`);
    r = await res.done;
    halt(r);
    if (!r.shown) throw new Error(r.error ?? "재개 결과를 열지 못했다");
    shown = r.shown;
    progress(`재개 ${rounds} — ${designCueSummary(shown.body)}`);
  }
  const report = shown.body.report ?? {};
  if (report.status === "cancelled") {
    throw new Error("자동 설계가 취소되어 멈췄다 — 자동 설계 탭 [남은 스테이지 이어서 실행]");
  }

  // ③ [게인 확정] — 스토어 작업본 주입(게인 탭·시뮬·Autocode·영향성이 소비)
  if (!shown.adopt) throw new Error(shown.adoptBlocked ?? "확정할 게인 반출이 없는 결과다");
  halt();
  const adopted = await shown.adopt();
  progress(`게인 확정 — 스케줄 ${adopted.tables} · 상수 ${adopted.constants}`);

  // ④ [문서에 반영] — 정본 되쓰기(새 리비전). 막히면 사유로 실패한다(조용히 건너뛰지 않는다)
  let applied = null;
  if (apply) {
    if (!shown.applyToDoc) throw new Error(shown.applyBlocked ?? "문서에 반영할 수 없는 결과다");
    halt();
    const w = await shown.applyToDoc();
    applied = w.revision;
    progress(`문서에 반영 — 리비전 ${applied} · 자리 ${w.slots.length}개`);
  }
  return {
    summary: designCueSummary(shown.body) + (applied != null ? ` · 리비전 ${applied}에 반영` : ""),
    resultId: shown.resultId,
    data: { resultId: shown.resultId, verdict: report.status ?? null, applied_revision: applied },
  };
}

/** 신호 config → 실행 설정·요구 조정 칸 — 전부 비운 뒤 config에 있는 칸만 채운다(모드는 서버 기본). */
function fillForm(form, config) {
  const vals = configFormValues(config);
  form.mode.value = vals.mode ?? designDefaults?.config?.mode ?? "gated";
  // 게인 표현도 「서버 기본값 + 신호 config」 — 전에 누가 「다항」을 골라 뒀으면 신호 실행이 그 표현으로
  // 도는 것을 막는다(칸을 먼저 비운다는 사슬 계약). 기본값 도착 전이면 셀렉트 마크업 기본(표)
  form.fitMode.value = vals.fitMode ?? designDefaults?.config?.fit_mode ?? "table";
  for (const k of ["budgetPoints", "budgetIters", "nMach", "nValidationBetween", "altsText", "fuelsText",
    "actuatorWn", "actuatorZeta", "delayS"]) {
    form[k].value = vals[k] ?? "";
  }
}

const CRIT_SOURCE = { profile: "이 기체가 바꾼 값", default: "기본값" };

/** 판정선·튜닝 목표 요약(읽기 전용) — lib/autodesign criteriaSummaryModel의 표. 이 기체가 바꾼 칸은 굵게. */
function criteriaSummary(body) {
  const m = criteriaSummaryModel(body);
  const cell = (c) => c
    ? el("td", { title: `${c.key} — ${CRIT_SOURCE[c.source]}`, style: c.source === "profile" ? "font-weight:600" : "" },
      `${c.text} `, el("span", { class: "hint" }, `(${CRIT_SOURCE[c.source]})`))
    : el("td", {}, "—");
  const table = el("table", { class: "data" },
    el("thead", {}, el("tr", {}, ["지표", "합격선", "권장선", "튜닝 목표"].map((h) => el("th", {}, h)))),
    el("tbody", {}, m.rows.map((r) => el("tr", {},
      el("td", {}, r.unit ? `${r.label} [${r.unit}]` : r.label),
      ...["pass", "rec", "target"].map((k) => cell(r.cells.find((c) => c.kind === k)))))));
  const out = [
    el("p", { class: "hint" }, m.written
      ? "이 기체 문서가 판정선·목표 일부를 바꿨다 — 굵은 칸이 이 기체가 바꾼 값, 나머지는 도구 기본값이다."
      : "이 기체 문서는 판정선·목표를 적지 않았다 — 전부 도구 기본값이다."),
    table,
  ];
  if (m.extra.length) {
    out.push(el("p", { class: "hint" }, "그 밖의 판정 칸 — "
      + m.extra.map((x) => `${x.key} ${x.text}${x.source === "profile" ? " (이 기체)" : ""}`).join(" · ")));
  }
  for (const c of m.conflicts) {
    // 합격선 충돌만 거절이다(v1.56) — 권장선 충돌은 설계가 돌고 결과 보고에 경고로 남는다
    out.push(c.level === "pass"
      ? el("p", { class: "error-box" },
        `튜닝 목표 ${c.target_key} ${c.target}가 합격선 ${c.line_key} ${c.line}보다 느슨하다 — 자동 설계가 거절한다`
        + "(튜닝에 성공한 점이 곧바로 불합격). 기체 탭 「평가 기준」에서 고친다.")
      : el("p", { style: `color:${SEV_COLOR.warn}` },
        `튜닝 목표 ${c.target_key} ${c.target}가 권장선 ${c.line_key} ${c.line}보다 느슨하다 — 설계는 되지만 튜닝에`
        + " 성공한 점이 합격·주의로 찍힌다."));
  }
  out.push(el("p", { class: "hint" },
    "자동 설계는 이 값으로 튜닝·판정한다 — 이 탭에서 바꾸지 않는다. 값은 기체마다 기체 탭 「평가 기준」에서 편집한다."));
  return out;
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
      // 조건 판정(05 §11.3 · 이관 8단계)이 채택하지 않은 수렴 점. 여유 미달은 v1.65부터 채택이라 여기 없다(점 표에
      // 「채택 · 추진 여유 미달」로 뜬다). 항목·사유는 점 표의 「자동 설계 채택」 열
      ` · 채택 제외 ${c.outside} (제한 위반·모델 범위 밖 — 튜닝·처방 대상 밖이라 판정에서 제외, `
      + "까닭은 점 표의 자동 설계 채택 열)"));
  }
  if (c.unjudged) parts.push(el("span", { class: "hint" }, ` · 미판정 ${c.unjudged}`));
  return el("p", {}, "점 판정", ...parts);
}

/** 판정어의 뜻 — 칩만 띄우고 뜻을 안 적으면 warn이 잡음인지 신호인지 알 수 없다.
 *  warn 문단은 표현(fit_mode)에 따라 다르다 — 표 모드에는 조일 적합이 없다(lib warnNoteText). */
function legendBox(criteria, fitMode) {
  return el("details", {},
    el("summary", { class: "hint" }, "판정어의 뜻 (ok · warn · fail · na)"),
    el("ul", { class: "hint" }, verdictLegend(criteria).map((l) =>
      el("li", {}, sevChip(l.key), ` ${l.text}`))),
    el("p", { class: "hint" }, warnNoteText(fitMode)));
}

/** 튜닝·검증이 본 작동기 한 줄 — 출처(기체 문서·설정·폴백)까지. 기록이 없으면 null. */
function actuatorBox(body) {
  const a = actuatorLine(body);
  if (!a) return null;
  return a.tone === "warn"
    ? el("p", { style: `color:${SEV_COLOR.warn};margin:4px 0` }, a.text)
    : el("p", { class: "hint", style: "margin:4px 0" }, a.text);
}

/** 적합에서 뺀 튜닝 표본 — 보류(그 표가 실패 표본을 담는다)는 경고로 펴 두고, 뺀 표본 내역(자리별 사유·
 *  점·뺀 값)은 접는다. 몇 개인지는 커버리지 절의 엔진 문장이 이미 말한다 — 여기는 **어느 점을 왜**다. */
function excludedBox(body) {
  const m = excludedSamplesModel(body);
  if (!m) return null;
  const reasonMap = designDefaults?.reason_text;
  const items = m.slots.flatMap((s) => s.items.map((x) => ({ slot: s.slot, ...x })));
  return el("div", {},
    m.withheld.map((h) => el("p", { style: `color:${SEV_COLOR.warn};margin:4px 0` }, el("strong", {}, h.text))),
    m.total
      ? el("details", {},
        el("summary", { class: "hint" }, `적합에서 뺀 튜닝 표본 ${m.total}개 — 자리별 내역 (점·뺀 값·사유)`),
        el("ul", { class: "hint" }, m.slots.map((s) => el("li", {}, el("strong", {}, s.slot), ` ${s.text}`))),
        el("div", { class: "scroll-x" }, el("table", { class: "data" },
          el("thead", {}, el("tr", {},
            ...["자리", "점", "뺀 값", "루프", "사유", "근거"].map((h) => el("th", {}, h)))),
          el("tbody", {}, items.map((x) => el("tr", {},
            el("td", {}, x.slot),
            el("td", {}, x.point),
            el("td", {}, fmt(x.value)),
            el("td", {}, x.loop ?? "—"),
            // 사유 문장은 길다 — 코드만 칸에 두고 뜻은 툴팁(서버 사전이 정본)
            el("td", { title: reasonText(x.reason, reasonMap) ?? "" }, x.reason ?? "—"),
            el("td", { style: "text-align:left" }, x.basisText)))))),
        el("p", { class: "hint" },
          "뺀 점의 스케줄 값은 튜닝값이 아니라 이웃 표본의 보간이고, 검증은 그 보간값으로 했다. "
          + "근거 「같은 축 레이트 루프가 실패한 위에서 튜닝」은 자세 PI가 자리값(0 댐퍼 등) 위에서 "
          + "성형돼 출하될 플랜트의 답이 아니라서 함께 뺀 것이다."))
      : null);
}

/** 적합 보고 — 자리별 표현과 스케줄 축 밖 변동·교차축 잔차·톱니. 요약은 접힌 채로도 읽힌다. */
function fitFactsBox(fits) {
  const m = fitFactsModel(fits);
  if (!m) return null;
  return el("details", {},
    el("summary", { class: "hint" }, m.summary ?? "적합 보고 — 자리별 표현"),
    el("ul", { class: "hint" }, m.rows.map((r) => el("li", {}, r.text))),
    el("p", { class: "hint" },
      "스케줄 표는 마하 1축(sched_axes)이다 — 고도·연료로 변하는 게인은 버려지지 않고 마하 분할점 "
      + "하나에 평균되거나(교차축 잔차 = 그 어긋남 ÷ 자리 스케일), 표 모드에서는 고도가 다른 표본이 "
      + "마하 축 위에 번갈아 놓여 값이 오르내린다(톱니 = 인접 변화의 방향이 뒤집힌 횟수). 판정은 검증이 "
      + "그 표로 했다 — 적합 품질 문턱은 기본 꺼짐이라 여기서는 판정하지 않고 사실만 적는다."));
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
        // 튜닝 실패로 이 점의 표본을 적합에서 뺀 게인 자리 — 그 값은 이웃 보간이다
        r.excludedLine ? el("div", { class: "hint" }, r.excludedLine) : null,
        !r.reasonLine && !r.noteLine && !r.excludedLine ? el("div", { class: "hint" }, "—") : null),
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
 * 채운 자리, 판정 불가, 채택 제외, 건너뛴 점, 트림 미수렴, 반영했는데 안 바뀐
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
      + "판정 불가·채택 제외·트림 미수렴·튜닝 건너뜀·무효 처방)도 여기 모인다. "
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
      // 채택 열은 조건 판정(트림·모델·제한)의 자동 설계 채택 여부이고, 판정 열은 스케줄 마진 성능 판정이다 — 둘을
      // 한 낱말(OK)로 섞지 않는다
      ...["이름", "mach", "고도", "연료", "역할"].map((h) => el("th", {}, h)),
      el("th", { title: "조건 판정(트림 성립·모델 범위·적용 제한)으로 정한 자동 설계 채택 여부 — 성능 판정이 아니다. "
        + "여유 미달은 채택하고 표시만 한다" }, "자동 설계 채택"),
      el("th", { title: "스케줄 게인으로 잰 마진 성능 판정(ok · warn · fail · na)" }, "성능 판정"))),
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

  // 게인 확정·문서 반영이 설 수 있는가 — 섹션과 손잡이(신호 사슬)가 같은 판정을 쓴다
  const hasExport = Boolean(body.gain_export && (Object.keys(body.gain_export.tables_resampled ?? {}).length
    || Object.keys(body.gain_export.constants ?? {}).length));
  const canAdopt = hasExport && !adoptBlockedText(report);
  const applyBlocked = applyGateReason(body.profile);

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
          const cb = el("input", { type: "checkbox", checked: approvedByDefault(a) });
          approveBoxes.set(a.id, cb);
          return cb;
        })(),
      el("strong", {}, ` ${VERDICT_LABEL[a.verdict] ?? a.verdict}`),
    ),
    el("div", { class: "hint" }, `${a.case} · ${a.loop}`),
    evidenceLine(a),
  );

  /** [승인 반영 재개] — 화면 체크박스가 승인 목록이다(신호 사슬도 손대지 않은 기본 체크를 그대로 읽는다).
   *  돌려주는 것: {jobId, approved, done: followJob 약속} 또는 {error}. 제출 거절은 던진다. */
  const resume = async () => {
    const approved = [...approveBoxes.entries()]
      .filter(([, cb]) => cb.checked).map(([id]) => id);
    // 취소 재개는 승인할 것이 없는 것이 정상이다 — 승인 대기일 때만 최소 1건을 요구한다
    if (!approved.length && report.status !== "cancelled") {
      const msg = "승인한 처방이 없다 — 최소 1개를 선택하거나 세션을 종료 상태로 두세요.";
      clear(ctx.errBox).append(errorLine(msg));
      return { error: msg };
    }
    clear(ctx.errBox);
    const job = await api.post(`/design/${resultId}/resume`, { approved });
    return { jobId: job.id, approved, done: followJob(job.id, "재개 실패") };
  };
  const resumeClick = () => resume().catch((e) => clear(ctx.errBox).append(errorLine(errorText(e))));

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
      + " 반출 정본(표 모드면 그 표, 다항 모드면 다항)은 결과 JSON의 gain_export.tables"
      + " — API 직접 주입용."));
    return { tables: Object.keys(payload.tables ?? {}).length, constants: constNames.length };
  };
  const adoptMsg = el("span");
  const applyMsg = el("span");
  // 판정 기준 배지 — 결과의 criteria_echo를 그 기체의 지금 기준과 대조(lib/freshness.js). 조회는 비동기로 채운다
  const critSlot = el("span", { style: "font-size:12px;font-weight:normal" });
  (async () => {
    const pid = body.profile?.id;
    const now = pid && body.criteria_echo?.scheme
      ? await api.get(`/profiles/${encodeURIComponent(pid)}/criteria`).then((r) => r?.echo ?? null, () => null)
      : null;
    const spec = criteriaBadgeSpec(criteriaFreshness(body.criteria_echo, now, "auto_design"));
    if (spec) critSlot.append(el("span", { class: `flag ${spec.tone}`, style: "margin-left:8px", title: spec.tip },
      spec.label));
  })();

  const covBox = coverageBox(report);
  // 상태 줄 아래 사실 셋 — 무엇으로 설계했나(작동기)·표에서 무엇을 뺐나(튜닝 실패 표본)·표가 무엇을
  // 뭉갰나(스케줄 축 밖 변동·톱니). sections는 native append라 null을 걸러 넣는다
  const facts = [actuatorBox(body), excludedBox(body), fitFactsBox(body.fits)].filter(Boolean);
  const sections = [
    el("h3", {}, `결과 ${resultId}`, critSlot),
    el("p", {},
      "상태 ", sevChip(statusSeverity(report.status)), ` ${report.status ?? "?"} · `,
      // 계산해 놓고 안 내던 수치들 — 특히 판정 수가 없으면 "실패 0"의 뜻이 갈리지 않는다
      reportLine(report, rows.length).join(" · ")),
    // 평가 체계(영향성 탭 「평가」·게인 탭 카드)와의 정렬 — 이 화면의 미달
    // 원장·조치 카드가 곧 "나머지 판정: 항상 판정하되 문제일 때만 전개"의 자동설계판이고,
    // 판정선(pm·gm·ζ)은 같은 MarginCriteria 한 정의를 쓴다 (pipeline/criteria.py 합성)
    el("p", { class: "hint", style: "margin:4px 0 0" },
      "판정 체계는 영향성 평가와 한 벌이다 — 아래 미달 원장·조치 카드가 평가의 "
      + "「문제 시 전개」에 해당하고, 확정한 게인의 대표 카드는 게인 탭 상단에서 "
      + "[지표 재계산]으로 본다."),
    // 영어 토큰만 찍으면 상태를 말하되 뜻과 다음 행동을 말하지 않는다
    el("p", { class: "hint" }, statusText(report.status)),
    // 상태 줄 바로 아래 — 이 실행이 무엇을 안 봤는지가 상태의 전제다.
    // sections는 native append로 펼쳐지므로 null을 넣으면 터진다 (el과 다르다)
    ...(covBox ? [covBox] : []),
    // 적합 품질 — 문턱을 켠 실행의 경고(04 §10 렌더 경로). 문턱이 꺼진 실행은 줄이
    // 없다: 판정하지 않은 것을 "확인 완료"처럼 말하지 않는다 (수치는 결과 JSON에)
    ...fitQualityLines(body.fits).map((l) => (l.tone === "hint"
      ? el("p", { class: "hint" }, l.text)
      : el("p", { style: `color:${SEV_COLOR.warn}` }, el("strong", {}, l.text)))),
    ...facts,
    el("h4", {}, "운영점"),
    countsLine(rows),
    pointsTable,
    legendBox(body.margin_out?.criteria, report.fit_mode),
    // 권장선보다 느슨한 목표로 설계했다 — warn 판정이 「목표 미달」이 아니라 설정이 예고한 결과임을 결과 곁에 둔다
    ...(report.target_warnings ?? []).map((w) => el("p", { style: `color:${SEV_COLOR.warn}` }, w)),
  ];

  // 실패가 0이어도 원장이 비지 않으면 뜬다 — 실패 0이 곧 미달 0이 아니다
  if (ledger.length) sections.push(...ledgerSection(ledger, ledgerTruncatedText(body)));

  if (cards.approvable.length && resumable(report)) {
    sections.push(
      el("h4", {}, "처방 카드 (승인 후 재개)"),
      ...cards.approvable.map((a) => cardEl(a)),
      el("button", { onclick: resumeClick }, "승인 반영 재개"),
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
      el("button", { onclick: resumeClick }, "남은 스테이지 이어서 실행"),
    );
  }
  if (cards.escalations.length) {
    sections.push(
      el("h4", {}, "에스컬레이션 — 상위 설계 변경 검토 (자동 적용 없음)"),
      ...cards.escalations.map((a) => cardEl(a)),
    );
  }
  if (hasExport) {
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
    // 채택 표 재검증 — "확정되는 표로 다시 판정하면 무엇이 움직이나". 게인 오차
    // 고지(resample_error)와 별개다: 오차가 허용치 안이어도 판정이 움직일 수 있다
    for (const l of reverifyLines(body.gain_export)) {
      sections.push(l.tone === "hint"
        ? el("p", { class: "hint" }, l.text)
        : el("p", { style: `color:${SEV_COLOR[l.tone === "fail" ? "fail" : "warn"]}` },
            el("strong", {}, l.text)));
    }
    // 실패 0은 통과의 근거가 못 된다 — 판정 수가 0이면 볼 것이 없었던 실행이고,
    // 그 게인을 확정하면 **아무것도 검증하지 않은 게인이 정본이 된다**
    if (!canAdopt) {
      sections.push(el("p", {}, el("strong", {}, adoptBlockedText(report))));
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
      // 정본 되쓰기(v2) — 확정 표를 기체 문서(law.gain_tables) 새 리비전으로. 스토어 주입(위)이
      // 세션 작업본이라면 이쪽은 정본이다: 페이지를 다시 읽어도, 어느 세션에서도 계산이 이 표로
      // 조립된다. 예제·형상 변형 결과는 반영 대상이 없다(서버도 거부한다 — 버튼을 안 세운다).
      // 관문은 lib applyGateReason — 재개 결과(스냅숏)도 반영 대상이고, 명시로 고른 예제는 막는다
      if (!applyBlocked) {
        sections.push(
          el("div", { style: "margin-top:6px" },
            el("button", { onclick: () => applyToDoc().catch((e) =>
              clear(applyMsg).append(el("span", { class: "error-box" }, errorText(e)))) },
              "문서에 반영 (새 리비전)"), applyMsg),
          el("p", { class: "hint", style: "margin:4px 0 0" },
            "반영하면 조립 우선순위가 「작업본 주입 > 문서의 확정 표 > 규칙 스케줄」이 된다 — "
            + "확정(작업본)이 걸려 있으면 그것이 문서 표를 덮는다. 반영한 뒤 문서를 고치면 표가 "
            + "낡음으로 거부된다(자동 설계를 다시 돌려 반영). 다항은 재양자화 표로 반영되고 그 "
            + "오차 고지가 출처에 함께 적힌다."),
        );
      } else {
        sections.push(el("p", { class: "hint" }, applyBlocked));
      }
    }
  }
  clear(box).append(...sections);

  // 반영 가능성 사전 확인 — 설계가 잰 문서와 지금 문서의 지문 대조(서버 409 가드와 같은 판정을
  // 미리 말한다). 조회 실패는 조용히 — 최종 판정은 어차피 서버 가드다.
  // 이미 반영한 결과를 다시 열면 지문이 다르다(반영이 표를 써서 문서가 바뀌었다) — 그걸 "다시 설계하라"로
  // 말하면 틀린 조언이다. 목록 행의 applied_design 대조(lib/freshness.js — 결과·설계 흐름 탭과 같은 판정)가
  // applied면 안내로 말하고, 아니면 종전 지문 대조. 목록 조회 실패는 판정 불가(unknown)로 종전 대조에 맡긴다
  if (canAdopt && !applyBlocked) {
    (async () => {
      try {
        const [head, rows] = await Promise.all([
          api.get(`/profiles/${encodeURIComponent(body.profile.id)}`),
          api.get("/profiles").catch(() => null),
        ]);
        // 그사이 사용자가 반영을 눌렀으면(성공 메시지·오류가 이미 섰으면) 덮지 않는다 — 반영이
        // 지문을 바꾸므로 늦은 사전 확인이 성공한 반영을 "거부됩니다"로 뒤집어 읽게 만든다(리뷰 지적)
        if (applyMsg.hasChildNodes()) return;
        const fresh = resultFreshness(body.profile, rows, resultId);
        if (fresh.state === "applied") {
          clear(applyMsg).append(el("span", { class: "hint", title: fresh.label },
            ` ${applyFreshnessBlock(fresh.state)}`));
        } else if (head.fingerprint !== body.profile.fingerprint) {
          clear(applyMsg).append(el("span", { class: "error-box" },
            ` 설계가 잰 문서(리비전 ${body.profile.revision ?? "—"})와 지금 문서(리비전 ${head.revision})가 `
            + "다릅니다 — 반영은 거부됩니다. 자동 설계를 다시 돌리세요."));
        }
      } catch { /* 조회 실패 — 서버 가드가 최종 판정 */ }
    })();
  }

  async function applyToDoc() {
    const pid = body.profile.id;
    const head = await api.get(`/profiles/${encodeURIComponent(pid)}`);
    const r = await api.post(`/design/${encodeURIComponent(resultId)}/apply-gains`,
      { base_revision: head.revision });
    clear(applyMsg).append(el("span", { class: "hint" },
      ` 리비전 ${r.revision}로 반영 — 자리 ${r.slots.length}개. 기체 탭 「게인·δe_trim」 패널이 상태를 보인다.`));
    return r;
  }

  // 손잡이 — 이 보고서의 버튼들이 부르는 **바로 그 함수**다(신호 사슬이 같은 길을 밟는다).
  // 버튼이 서지 않는 상태면 null이고, 그 사유를 함께 싣는다
  return {
    body, resultId,
    resume: cards.approvable.length && resumable(report) ? resume : null,
    adopt: canAdopt ? adopt : null,
    adoptBlocked: hasExport ? adoptBlockedText(report) : "반출 게인(표·상수)이 없는 결과다",
    applyToDoc: canAdopt && !applyBlocked ? applyToDoc : null,
    applyBlocked,
  };
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
