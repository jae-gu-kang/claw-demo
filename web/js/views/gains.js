/** 게인 스케줄 뷰 (02 §8 4단계) — 스케줄 자리 선택 → 셀 편집 → 시뮬 주입 준비.

배치는 다른 탭과 같은 규약이다(views/stage.js): 곡선·계수·편집 표가 전면이고, 자리
선택 격자와 근사 곡선 설정은 패널이다. 순서는 **곡선 → 설정 패널 → 근사식 계수 → 편집
표**다. 자리나 근사 설정을 바꾸면 위의 곡선과 아래의 계수·잔차가 한눈에 보여야 해서
패널을 곡선과 계수 사이에 둔다(사용자 지적 — 종전엔 패널이 맨 아래라 스크롤을 오갔다).
편집 표는 패널에 넣지 않는다 — 칸을 고치면 곡선이 그 자리에서 움직이는 되먹임이 끊긴다.

두 층이다. **자리 선택**(어떤 게인에 테이블을 붙이나)은 형상을 바꾸고 — 켠 자리는
탑재 C에 룩업이 생기고 뺀 자리는 설계점 상수로 접힌다 — **값 편집**은 그 안에서
게인을 바꾼다. 곡선·계수·편집 표에는 켠 자리만 선다.

주입은 전체 교체 (엔진 make_demo_fcl 계약)이고 **키 집합이 곧 선택**이다.
편집본은 store("gainTables")로 시뮬레이션 탭에 전달하며, 전부 끈 경우만 빈 dict로
표현할 수 없어(서버가 422) store("gainScheduleOff")를 함께 쓴다 — 판단은
lib/gainsched.js. 검증(그룹·키·형상·유한성)은 제출 시 서버/엔진이 수행.

**끈 자리의 상수도 여기서 고친다.** 그 값은 블록도 폼과 같은 스토어
(scasParams·autopilotParams)에 살고, 어느 쪽에서 고쳐도 다른 쪽에 그대로 보여야
한다 — 같은 게인이 화면마다 다르면 "지금 형상"이라는 말이 성립하지 않는다.
켜고 끌 때도 값이 이어진다: 켜면 그 상수에서 출발하는 표가 서고, 끄면 그 표의
설계점 값으로 굳는다 (lib/gainsync.js — 스케일 규칙은 서버 제안 표에서 온다).

쇼케이스 진행기 신호(lib/showcasecue.js): overview() — 카탈로그를 다시 받아 곡선·확정 표 배너 ·
evaluate() — [지표 재계산 (선형)]과 같은 길 · fault({path, factor}) — 그 자리의 전 스케줄 점에 배율을
곱해 [시뮬·코드에 적용]과 같은 길로 작업 사본에 싣는다 · restore() — 작업 사본을 버리고 [설계값 다시
불러오기]로 되돌린다.
*/

import { ApiError, api, errorText, watchJob } from "../api.js";
import { clear, el, fmt } from "../dom.js";
import { evaluateRequest, normalizeEvalReport } from "../lib/evaluate.js";
import { defaultGridCases } from "../lib/grid.js";
import { selectedDefaults } from "./missionfill.js";
import { DOC_FAILED_HINT, MISSING_TEMPLATE_HINT } from "../lib/missiontemplate.js";
import {
  GAIN_KEYS, alignTables, appliedTables, axisMismatch, axisMismatchText, defaultSelection, evalStripLine,
  schedSummary, scheduleKnees, slotRows, storePayload, toggleSlot, zeroTables,
} from "../lib/gainsched.js";
import {
  constantOf, designCoord, dropWorkingCopy, faultSlot, faultSummary, foldToConstant, seedTable, selectedSlots,
  slotIndex, withConstant, workingCopyLine,
} from "../lib/gainsync.js";
import { EXAMPLE_ID, currentSelection } from "../lib/profile.js";
import { criteriaBadgeSpec, criteriaEchoCache, criteriaFreshness } from "../lib/freshness.js";
import { gainTablesStatus } from "../lib/quickseed.js";
import { effectiveOf } from "../lib/profileform.js";
import { josaOf } from "../lib/josa.js";
import { revealPanel } from "../lib/reveal.js";
import { haltReason } from "../lib/showcase.js";
import { failCue, reportCue, takeCue, unknownAction } from "../lib/showcasecue.js";
import { gainPlotGroups } from "../lib/plot.js";
import { piecewisePolyfit, rawCoeffs, sampleFit } from "../lib/polyfit.js";
import { store } from "../store.js";
import { renderEvalCards } from "./evalcards.js";
import { errorWithSeedLink } from "./seedlink.js";
import { lineChartCanvas } from "./plots.js";
import { createDrawers, tabStage, tabTop } from "./stage.js";

// 신호 실패 사유 — 서버 오류는 errorText(422 배열·엔진 detail을 사람 글로), 그 밖은 메시지만("Error: " 접두 없이)
const cueReason = (e) => (e instanceof ApiError ? errorText(e) : (e?.message ?? String(e)));

let catalog = null; // GET /gains/catalog — 자리 목록·설계 상수·제안 테이블
let selected = []; // 켠 자리 이름 (카탈로그 기본 = 서버가 지금 스케줄하는 6자리)
let tables = null; // 켠 자리만 추린 {name: {axes:{mach}, data, extrapolate}} — 편집 대상
let openDrawer = null; // 탭 재진입에도 열어 둔 패널 유지 (모듈 스코프 규약)
// 자리를 켜고 끄면 칩 배지의 수가 바뀐다 — 그린 쪽(renderTables)에서 칩에 알린다
let gainsDrawers = null;
let adopted = null; // 되읽은 형상 요약 {source, slots, aligned, points, unknown} | null
// 이 탭이 마지막으로 보거나 적용한 스토어 값 — **밖에서 바뀌었는지**만 판정한다.
// 매 재진입마다 되읽으면 미적용 편집 드래프트가 날아가고, 아예 안 읽으면 자동
// 설계가 확정한 형상이 이 화면에만 안 보인다
let seenTables;
let seenOff;
// 상수 드래프트의 '밖에서 바뀌었나' 판정 기준 (테이블과 같은 규약)
let seenScas;
let seenAp;
// 끈 자리의 상수 드래프트 {scas, autopilot} — 블록도 폼과 같은 스토어를 쓰는 값이라
// 테이블과 함께 '적용'에서 커밋한다 (여기만 즉시 반영되면 적용 전후가 갈린다)
let constants = null;

// 근사 곡선 설정 — 탭 이탈·재로드에도 유지. 경계는 null(아직 안 정함)로 시작해 **첫 카탈로그의 스케줄 표**에서
// 정한다 — 상한 클립이 풀리는 격자점들(lib/gainsched scheduleKnees). 종전 "0.3"은 1200 kg 기체 롤 상한의 꺾임이라
// 다른 기체에서는 뜻 없는 자리였다. 기체를 바꾸면 페이지를 다시 읽으므로 기체마다 새로 정해진다.
// 검증은 piecewisePolyfit이 수행
const fitCfg = { show: true, degree: 3, boundaries: null, detailsOpen: false };
const EVAL_DEPTHS = ["linear", "full"];

// 지표 카드(평가 어휘·값은 서버 정본) — 마지막 계산 결과와 신선도.
// 편집이 생기면 **stale 배지만** 켠다: 자동 재계산은 없다(서버 왕복 비용 — 버튼이
// 명시적 트리거다). 격자는 미션 템플릿 격자(없으면 lib/grid.js DEFAULT_GRID)다 — 영향성 탭은 이관 5단계부터 요구영역
// 기본 격자에서 점을 고른다(05 §11.13 5단계). 이 카드의 격자 이관은 5단계 나머지다.
let evalStrip = { status: null, result: null, error: null, stale: false, depth: null };
// 형상·값 편집 핸들러(모듈 함수)에서 카드 stale을 켜는 통로 — render()가 실제
// 구현으로 갈아 끼운다 (핸들러가 렌더 클로저 밖에 살기 때문)
let markStale = () => {};
// 고른 기체의 미션 템플릿 격자 — 영향성 격자 칸과 같은 원천(views/missionfill.js). 없으면 폴백(예제 격자)
let templateGrid = null;
let templateNote = ""; // 템플릿이 없거나 기체 문서를 못 받았으면 그 사실 — 케이스 수 줄에 붙인다

export function render() {
  // 조각으로 갈라 둔다 — 어느 것이 전면이고 어느 것이 패널인지는 아래 배치가 정한다
  const slots = {
    chart: el("div"),   // 전면 — 스케줄 곡선
    // 전면 — 근사식 계수·잔차·경계 연속성. 곡선 칸에서 떼어 패널 **뒤**에 둔다: 자리·근사
    // 설정을 바꾸면 위의 곡선과 아래의 계수가 동시에 보여야 한다 (사용자 지적)
    fitTable: el("div", { class: "tab-sheet" }),
    table: el("div", { class: "tab-sheet" }), // 전면 — 셀 편집 (곡선과 한 벌)
    grid: el("div"),    // 패널 — 자리 선택 격자 (형상을 바꾸는 조작)
    fit: el("div"),     // 패널 — 근사 곡선 설정
  };
  const errBox = el("div");
  const statusLine = el("p", { class: "tab-status" });
  const confirmedBox = el("div"); // 문서의 확정 게인 표(v2) 고지 — 이 화면(규칙 세계)과 조립 정본의 차이

  // ── 튜닝 지표 카드 (평가와 같은 카드, views/evalcards.js 공용) ──────
  const stripStatus = el("span", { class: "hint" });
  const stripCards = el("div", { style: "margin-top:8px" });
  const gridReady = selectedDefaults().then((d) => {
    templateGrid = d?.grid ?? null;
    templateNote = !d ? DOC_FAILED_HINT : d.hasTemplate ? "" : MISSING_TEMPLATE_HINT;
    if (!evalStrip.status) paintStrip(); // 아직 안 잰 상태의 케이스 수가 그 격자를 말하게
  });

  // 판정 기준 배지 — 평가 결과의 criteria_echo를 그 결과 기체의 지금 기준과 대조(lib/freshness.js).
  // 기체당 이 render에서 한 번 받는다. 조회 중엔 배지 없음, 받으면 띠를 다시 그린다. fresh는 조용하다
  const lookCriteria = criteriaEchoCache((path) => api.get(path));
  const critNow = new Map();
  const stripCriteriaChip = () => {
    const pid = evalStrip.profileId;
    let st;
    if (!evalStrip.criteriaEcho?.scheme || !pid) st = "unknown";
    else if (!critNow.has(pid)) {
      lookCriteria(pid).then((echo) => { critNow.set(pid, echo); paintStrip(); });
      return null;
    } else st = criteriaFreshness(evalStrip.criteriaEcho, critNow.get(pid), "influence_evaluate");
    const spec = criteriaBadgeSpec(st);
    return spec ? el("span", { class: `flag ${spec.tone}`, style: "margin-left:8px", title: spec.tip }, spec.label)
      : null;
  };

  function paintStrip() {
    clear(stripCards);
    const stale = evalStrip.stale
      ? " · 이후 편집 있음 — 카드는 이전 형상 기준" : "";
    if (!evalStrip.status) {
      // 케이스 수는 세어서 쓴다 — 손으로 적으면 DEFAULT_GRID가 바뀔 때
      // 화면만 옛 수를 말한다(v0.72까지 「15케이스」로 남아 있었다)
      stripStatus.textContent =
        `아직 안 쟀다 — 미션 템플릿 격자 ${defaultGridCases(templateGrid ?? undefined).length}케이스, `
        + "미적용 편집 포함 형상으로 잰다" + stale + (templateNote ? ` · ${templateNote}` : "");
      return;
    }
    stripStatus.textContent = evalStrip.status + stale;
    if (evalStrip.error) {
      stripCards.append(el("div", { class: "error-box" }, evalStrip.error));
    }
    const m = evalStrip.result;
    if (!m) return;
    renderEvalCards(stripCards, m.cards);
    stripCards.append(el("p", { class: "hint", style: "margin:8px 0 0" },
      `${evalStripLine(m)} · 상세는 영향성 탭 「평가」 패널`, stripCriteriaChip()));
  }

  // 평가 한 번 — {resultId, model} 또는 {error}. cue가 오면 잡을 건 순간 started를 알린다(진행기 [중단]용)
  async function runGainEval(depth, cue = null) {
    if (!catalog) return { error: "게인 카탈로그가 아직 없다 — 불러온 뒤 다시 잰다" };
    const cases = defaultGridCases(templateGrid ?? undefined);
    evalStrip = { status: `제출 중 — 케이스 ${cases.length}건`, result: null,
                  error: null, stale: false, depth };
    paintStrip();
    try {
      const job = await api.post("/influence/evaluate",
        evaluateRequest(editedShapeState(), { cases, depth }));
      if (cue) reportCue(cue, { phase: "started", jobId: job.id });
      const done = await watchJob(job.id, (j) => {
        evalStrip.status = `${Math.round((j.progress ?? 0) * 100)}% — ${j.message ?? ""}`;
        // 진행 중엔 상태 한 줄만 — 카드를 다시 세우면 버튼 포커스가 들려 나간다
        stripStatus.textContent = evalStrip.status;
      });
      if (done.status !== "done" || !done.result_id) {
        evalStrip.status = `평가 ${done.status}`;
        evalStrip.error = done.error ?? null;
        paintStrip();
        return { error: `평가 ${done.status}${done.error ? ` — ${done.error}` : ""}` };
      }
      const res = await api.get(`/results/${done.result_id}`);
      evalStrip.status = "완료";
      evalStrip.result = normalizeEvalReport(res);
      evalStrip.criteriaEcho = res.criteria_echo ?? null;
      evalStrip.profileId = res.profile?.id ?? null;
      paintStrip();
      return { resultId: done.result_id, model: evalStrip.result };
    } catch (e) {
      evalStrip.status = "실패";
      evalStrip.error = errorText(e);
      paintStrip();
      return { error: cueReason(e) };
    }
  }

  markStale = () => {
    if (evalStrip.result || evalStrip.status) {
      evalStrip.stale = true;
      paintStrip();
    }
  };

  /** 지표 계산용 형상 — **미적용 편집 포함**(지금 화면의 표·상수 그대로).
   *  적용된 store가 아니라 편집 버퍼를 실어야 카드가 "지금 만지는 게인"을 말한다 —
   *  대신 그 사실을 상태줄이 명시한다. */
  function editedShapeState() {
    const { tables: applied, scheduleOff } = storePayload(catalog, selected);
    return {
      autopilot: constants?.autopilot ?? store.get("autopilotParams"),
      scas: constants?.scas ?? store.get("scasParams"),
      nav: store.get("navParams"),
      actuators: store.get("actuatorParams"),
      gainTables: applied && JSON.parse(JSON.stringify(applied)),
      withSchedule: scheduleOff ? false : undefined,
    };
  }

  // 상수 드래프트를 **밖에서 바뀐 경우에만** 다시 읽는다 (테이블 드래프트와 같은 규약).
  //
  // 그 사이 블록도에서 고친 값을 안 읽으면 여기서 '적용'하는 순간 옛 드래프트가 그
  // 편집을 조용히 되돌린다 — 없애려던 이중 정본이 드래프트 층에서 되살아난다. 반대로
  // 매번 무조건 덮으면 여기서 고친 끈 자리 상수가 탭을 한 번 나갔다 오는 것만으로
  // 사라진다. 셀 편집은 살아남는데 상수만 되돌아가는 그 비대칭이 특히 혼란스럽다
  const syncFromStore = ({ force = false } = {}) => {
    const scas = store.get("scasParams") ?? null;
    const ap = store.get("autopilotParams") ?? null;
    if (force || constants === null || scas !== seenScas || ap !== seenAp) {
      constants = { scas, autopilot: ap };
      seenScas = scas;
      seenAp = ap;
      return true;
    }
    return false;
  };

  // 문서에 확정 게인 표가 있으면(자동 설계 반영, v2) 조립 정본은 이 화면의 규칙 표가 아니라 그
  // 표다 — 그 사실과 낡음을 여기서 말한다. 판정(stale)은 서버 응답이 동봉한다(재기술 없음)
  let confirmedSeq = 0; // 늦게 온 목록 응답이 다시 그린 배너 위에 덧쓰지 않게
  // 아래 「규칙 스케줄」 판정(gainTablesStatus 결과, 아니면 null) — 진행기 overview 보고가 **이 판정을 그대로** 읽는다.
  // 보고가 따로 판정하면 같은 화면에서 배너는 규칙 스케줄을, 보고는 「확정 게인 표 없음」을 말했다(EO/IR형)
  let confirmedRule = Promise.resolve(null);
  const paintConfirmed = () => {
    const c = catalog?.confirmed;
    clear(confirmedBox);
    const seq = ++confirmedSeq;
    confirmedRule = Promise.resolve(null);
    if (!c) {
      // 카탈로그는 고른 형상 변형을 적용한 문서에서 온다 — 기본형엔 확정 표가 있는데 변형 패치가 비웠으면(EO/IR형)
      // 그 형상은 규칙 스케줄로 난다. 빈 배너는 「이 기체엔 확정 표가 없다」로 읽히므로 그 사실을 말한다.
      // 판정은 서버 목록 요약(변형별 출처, 없으면 카탈로그가 말한 「변형 문서에 표 없음」) — lib/quickseed
      const sel = currentSelection();
      if (!sel?.variant) return;
      confirmedRule = api.get("/profiles").then((rows) => {
        const row = Array.isArray(rows) ? rows.find((r) => r?.id === sel.id) : null;
        const st = gainTablesStatus(row, { variant: sel.variant, effectiveTables: null });
        if (st.kind !== "rule") return null; // 기본형에도 표가 없다 — 종전처럼 말하지 않는다
        if (seq === confirmedSeq) {
          confirmedBox.append(el("p", { class: "hint", style: "margin:4px 0 0" },
            `${st.label}. 이 화면의 규칙 표가 곧 시뮬·코드의 조립 정본입니다.`));
        }
        return st;
      }).catch(() => null); // 목록을 못 받으면 배너 없이(종전) — 곡선·표는 이미 섰다
      return;
    }
    confirmedBox.append(el("p", { class: c.stale ? "error-box" : "hint", style: "margin:4px 0 0" },
      c.stale
        ? "문서의 확정 게인 표가 낡았습니다 — 반영한 뒤 문서가 바뀌어 시뮬·코드 조립이 거부합니다. "
          + "자동 설계를 다시 돌려 반영하거나 기체 탭에서 표를 지우세요."
        : `문서에 확정 게인 표가 있습니다(자리 ${c.slots.length}개 — 자동 설계 반영). 시뮬·코드는 그 표로 `
          + "조립됩니다. 이 화면의 편집을 [시뮬·코드에 적용]하면 작업본이 그 표를 덮습니다."));
  };

  // 카탈로그 받기 — 섰으면 null, 못 섰으면 그 오류(화면에는 이미 적었다)
  const load = async ({ fresh = false } = {}) => {
    try {
      clear(errBox);
      catalog = await api.get("/gains/catalog");
      // 설계점 **좌표**를 제안 표 기준으로 굳힌다 — 되읽기가 slot.table을 확정본으로
      // 갈아끼운 뒤에도 기준이 흔들리지 않게 (lib/gainsync designCoord)
      catalog.design_coord = designCoord(catalog);
      selected = defaultSelection(catalog);
      // 근사 경계는 처음 한 번 — 문서 스케줄 표(되읽기 전의 규칙 표)의 상한 꺾임에서
      if (fitCfg.boundaries == null) {
        fitCfg.boundaries = scheduleKnees(appliedTables(catalog, selected), catalog.axis).join(", ");
      }
      adopted = fresh ? null : adoptStored();
      if (fresh) markSeen();
      syncFromStore({ force: fresh });
      renderTables(slots, statusLine);
      paintConfirmed();
      statusLine.textContent = fresh
        ? "서버 설계 제안으로 되돌렸습니다 (미적용) — '시뮬·코드에 적용'을 눌러야 형상이 바뀝니다."
        : adoptedText(adopted);
      return null;
    } catch (e) {
      // 게인 미설계·스케줄 없는 기체면 오류 문구(엔진 detail) 아래에 채우러 가는 길이 선다 — seedlink.js
      clear(errBox).append(...errorWithSeedLink(e, "이 탭이 섭니다."));
      return e;
    }
  };

  const apply = () => {
    if (!catalog) return;
    const { tables: applied, scheduleOff } = storePayload(catalog, selected);
    const payload = applied && JSON.parse(JSON.stringify(applied));
    store.set("gainTables", payload);
    store.set("gainScheduleOff", scheduleOff);
    store.set("gainTablesSource", { kind: "gains" });
    markSeen();
    adopted = null; // 이제 이 화면이 곧 적용된 형상이다 — 되읽기 배너를 내린다
    // 끈 자리의 상수 — 블록도 폼이 읽는 바로 그 스토어. 여기서 고친 값이 저기 보인다
    if (constants?.scas) store.set("scasParams", constants.scas);
    if (constants?.autopilot) store.set("autopilotParams", constants.autopilot);
    statusLine.textContent = scheduleOff
      // 시뮬 탭은 아직 이 신호를 안 읽는다 — 조용히 다른 형상을 돌리지 않도록 명시한다
      ? "스케줄 없는 형상으로 적용됨 — Autocode 탑재코드에 반영됩니다. "
        + "시뮬레이션 탭은 아직 이 상태를 못 받아 설계 기본으로 돕니다."
      : `적용됨 (${schedSummary(catalog, selected)}) — 시뮬레이션 탭에서 `
        + "'편집 게인 사용'을 켜면 주입되고, Autocode 탑재코드에 바로 반영됩니다.";
  };

  const drawers = createDrawers({
    id: "gains-drawer",
    initial: openDrawer,
    onOpen: (k) => { openDrawer = k; },
    defs: [
      { key: "slots", label: "스케줄 자리", group: "형상",
        title: "어느 게인에 표를 붙일 것인가 — 켜면 탑재 C에 룩업이 생기고 빼면 상수로 접힌다",
        count: () => (catalog ? selected.length : null),
        build: () => [
          el("h2", {}, "스케줄 자리 — 어디에 표를 붙일 것인가"),
          el("p", { class: "hint", style: "margin:0 0 10px" },
            "이건 값이 아니라 형상을 바꾸는 조작이다 — 켠 자리는 탑재 C에 룩업이 생기고, "
            + "뺀 자리는 설계점 상수로 접힌다. 끈 자리의 상수도 여기서 고칠 수 있고, "
            + "그 값은 블록도 폼과 같은 스토어에 산다."),
          slots.grid,
        ] },
      { key: "fit", label: "근사 곡선", group: "표시",
        title: "구간 다항 근사 — 표의 점을 몇 차 곡선으로 볼 것인가",
        build: () => [
          el("h2", {}, "근사 곡선 (점선)"),
          el("p", { class: "hint", style: "margin:0 0 10px" },
            "표의 점은 그대로 두고 읽는 보조선만 얹는다 — 구간 경계에서 곡선이 "
            + "튀면 그 자리에 breakpoint를 하나 더 두어야 한다는 신호다."),
          slots.fit,
        ] },
    ],
  });

  const evalSheet = el("div", { class: "tab-sheet" },
    el("div", { class: "row", style: "gap:10px;align-items:center;flex-wrap:wrap" },
      el("strong", {}, "튜닝 지표 — 대표 카드"),
      el("button", { class: "primary", onclick: () => runGainEval("linear") },
        "지표 재계산 (선형 — 수 초)"),
      el("button", { onclick: () => runGainEval("full"),
                     title: "표준 기동 + 동시명령 런 포함 — 케이스당 수십 초" },
        "정밀 (단계 2)"),
      stripStatus),
    stripCards);
  const root = el("div", { class: "tab-page" },
    tabTop({
      title: "게인",
      lead: "설계점에서 정한 게인을 비행조건의 함수로 편다 — 표의 칸을 고치면 곡선이 "
        + "그 자리에서 움직인다. 자리 선택(형상)과 근사 곡선 설정은 아래 패널에.",
      actions: [
        el("button", {
          onclick: () => load({ fresh: true }),
          title: "적용해 둔 형상을 버리고 서버 설계 제안(동압 스케일)으로 되돌린다",
        }, "설계값 다시 불러오기"),
        el("button", { class: "primary", onclick: apply }, "시뮬·코드에 적용"),
      ],
      extra: [statusLine, confirmedBox, errBox],
    }),
    // 튜닝 지표 카드 — 게인을 만지는 화면에 상시로 서는 카드 표면(값·기준·최악
    // 운용점). 계산은 버튼 트리거(비용)고, 편집이 생기면 stale 배지가 먼저 말한다
    evalSheet,
    // 곡선은 카드 밖(자기 테두리를 갖는 캔버스). 그 바로 아래에 자리·근사 설정 패널,
    // 그다음 근사식 계수 — 설정을 바꾸면서 위(곡선)와 아래(계수·잔차·경계 점프)를
    // 한눈에 확인하게 한다(사용자 지적 — 종전엔 패널이 맨 아래라 스크롤을 오갔다).
    // 편집 표는 판독 시트로 그 뒤에 선다 — 패널 안에 넣으면 칸 편집 → 곡선 되먹임이 끊긴다
    tabStage(slots.chart),
    drawers.root,
    slots.fitTable,
    slots.table,
  );

  let loading = null; // 이번 그리기가 건 카탈로그 받기 — 신호가 그 끝을 기다린다
  if (catalog && !storeChanged()) {
    // 재진입 — 적용된 형상이 그대로면 캐시 카탈로그 위의 미적용 편집 드래프트를 지킨다
    syncFromStore();
    renderTables(slots, statusLine);
  } else {
    // 처음이거나, 적용된 형상이 밖에서 바뀌었다(자동 설계 '게인 확정'·영향성 [적용]·쇼케이스 [■ 중단]의 복원).
    // 카탈로그를 새로 받아 되읽는다 — 캐시의 자리 표는 앞선 되읽기·결함 주입이 덮어쓴 값이라, 그 위에 되읽으면
    // 새 작업 사본에 없는 자리가 옛 값을 들고 선다(작업 사본을 비웠으면 결함 표가 미적용 편집처럼 남는다)
    clear(slots.chart).append(el("p", { class: "hint" }, "게인 카탈로그를 불러오는 중…"));
    loading = load();
  }
  gainsDrawers = drawers;
  drawers.refresh();
  paintStrip();  // 재진입 — 모듈 스코프 결과·stale 상태 복원

  // ── 쇼케이스 신호 ──────────────────────────────────────────────────
  // 카탈로그는 이번 그리기가 받은 것이 아니면 다시 받는다 — 앞선 방문 뒤에 문서가 바뀌었을 수 있다
  // (자동 설계 [문서에 반영]이 확정 표 배너를 바꾼다). 받기는 [설계값 다시 불러오기]가 아닌 재진입 경로라
  // 적용해 둔 작업 사본(스토어)을 되읽는다
  const freshCatalog = async () => {
    const err = await (loading ?? load());
    if (err) throw err;
  };

  // 결함 주입의 기준 형상 — 계산이 **지금 실제로 쓰는** 형상이어야 결함만이 차이가 된다. 작업 사본(스토어)이
  // 있으면 그것(영향성·시뮬이 싣는 그 값), 없으면 문서 조립 정본 — 확정 게인 표가 있으면 그 표, 없으면 규칙 표.
  // 이 화면은 기본으로 규칙 표를 보여 주므로(배너가 말하는 차이) 확정 표는 여기서 명시로 세운다
  const faultBase = async () => {
    if (store.get("gainTables") != null || store.get("gainScheduleOff") === true) {
      if (adopted?.error) throw new Error(`작업 사본을 이 화면에 세우지 못해 결함을 넣을 수 없다 — ${adopted.error}`);
      return "작업 사본";
    }
    const conf = catalog.confirmed;
    if (!conf) return "문서 규칙 표";
    if (conf.stale) {
      throw new Error("문서의 확정 게인 표가 낡아 조립이 거부한다 — 결함 기준이 될 수 없다. "
        + "자동 설계를 다시 돌려 반영한다");
    }
    const sel = currentSelection();
    const body = await api.get(`/profiles/${encodeURIComponent(sel?.id ?? EXAMPLE_ID)}`);
    // 카탈로그(confirmed)는 고른 형상 변형을 적용한 문서에서 온다 — 기준도 같은 문서에서 읽는다
    const docTables = effectiveOf(body?.document, sel?.variant ?? null)?.law?.gain_tables?.tables;
    if (!docTables) throw new Error("카탈로그는 확정 게인 표가 있다는데 문서에 없다 — 기체 탭에서 새로고침한다");
    adopted = adoptTables(docTables, false, { kind: "document" });
    if (adopted.error) throw new Error(`문서 확정 게인 표를 세우지 못했다 — ${adopted.error}`);
    return "문서 확정 게인 표";
  };

  const handleCue = async (c) => {
    try {
      if (c.action === "overview") {
        await freshCatalog();
        const conf = catalog.confirmed;
        // 확정 표가 없으면 배너의 판정 그대로 — 변형이 규칙 스케줄로 나면 그 문구(목록을 못 받으면 종전 「없음」).
        // freshCatalog가 끝났으면 이 카탈로그로 배너를 그린 뒤다(load → paintConfirmed)
        const rule = conf ? null : await confirmedRule;
        revealPanel(root); // 머리(확정 표 배너)와 바로 아래 곡선을 화면 위로 (06 §2)
        reportCue(c, {
          phase: "done",
          summary: `${schedSummary(catalog, selected)} · `
            + (conf ? `문서 확정 게인 표 ${conf.slots.length}자리${conf.stale ? " (낡음)" : ""}`
              : rule ? rule.label : "문서 확정 게인 표 없음"),
          data: { gain_tables: conf != null, stale: conf?.stale === true, slots: selected.length,
            rule_schedule: rule !== null },
        });
      } else if (c.action === "evaluate") {
        await gridReady; // 고른 기체의 템플릿 격자로 잰다 — 폴백(예제 격자)으로 재지 않는다
        const loadErr = loading ? await loading : null;
        if (loadErr) throw loadErr; // 카탈로그를 못 받은 사유 그대로(게인 미설계 등) — 「아직 없다」로 뭉개지 않는다
        if (!templateGrid) throw new Error(templateNote || "고른 기체의 미션 템플릿 격자를 받지 못했다");
        const depth = c.args?.depth ?? "linear";
        if (!EVAL_DEPTHS.includes(depth)) throw new Error(`depth는 ${EVAL_DEPTHS.join("·")} 중 하나: ${depth}`);
        const r = await runGainEval(depth, c);
        if (r.error) throw new Error(r.error);
        revealPanel(evalSheet); // 지표 카드가 사는 판을 화면 위로
        reportCue(c, {
          phase: "done", resultId: r.resultId, summary: evalStripLine(r.model),
          data: { hard_fail: r.model.aggregate?.hard_fail ?? null, checks: r.model.checks },
        });
      } else if (c.action === "fault") {
        const { path, factor } = c.args ?? {};
        await freshCatalog();
        const base = await faultBase();
        // 받는 사이 진행기가 중단됐다 — 싣지 않는다(중단이 작업 사본을 문서 게인으로 되돌렸다, views/showcase.js).
        // 여기부터 apply()까지는 await가 없어 확인과 쓰기 사이에 중단이 끼지 못한다
        const stop = haltReason(store.get("showcaseBusy"));
        if (stop) throw new Error(stop);
        const r = faultSlot(catalog, { selected, constants }, path, factor);
        if (r.scheduled) r.slot.table = r.table; // 켠 자리 — 표가 정본 (셀 편집과 같은 자리)
        else constants = r.constants; // 끈 자리 — 상수가 정본 (자리 격자 입력과 같은 자리)
        renderTables(slots, statusLine);
        apply(); // [시뮬·코드에 적용]과 같은 길 — 스토어 작업 사본
        markStale();
        const line = faultSummary(r, factor);
        statusLine.textContent = `결함 주입 적용됨 — ${line} (기준: ${base})`;
        revealPanel(root); // 상태줄(결함 주입 적용됨)과 결함이 실린 곡선을 화면 위로
        reportCue(c, {
          phase: "done", summary: `${line} (기준: ${base})`,
          data: { path, before: r.before, after: r.after, scheduled: r.scheduled, base },
        });
      } else if (c.action === "restore") {
        if (loading) await loading;
        // 작업 사본 전량을 비운다 — 표·스케줄 끔 신호·출처와, 끈 자리 상수(블록도 폼과 같은 스토어)까지.
        // 비운 뒤의 계산은 서버가 문서 게인으로 조립한다(확정 표가 있으면 그 표). 진행기 [■ 중단]의 복원과
        // 같은 함수다(lib/gainsync dropWorkingCopy — 키 목록을 여기 다시 적지 않는다)
        const cleared = dropWorkingCopy(store);
        const err = await load({ fresh: true });
        if (err) throw err;
        statusLine.textContent = "작업 사본을 버렸습니다 — 시뮬·코드·평가는 문서 게인으로 조립됩니다 "
          + "(이 화면은 서버 설계 제안을 보여 줍니다).";
        revealPanel(root);
        reportCue(c, { phase: "done", summary: workingCopyLine(cleared), data: { cleared } });
      } else {
        unknownAction(c);
      }
    } catch (e) {
      failCue(c, cueReason(e));
    }
  };
  const cue = takeCue("gains");
  if (cue) handleCue(cue);
  return root;
}

/** "M0.6" — 설계점 표기. 좌표는 로드 시점에 굳혀 둔 값(lib/gainsync designCoord). */
function axisLabel() {
  const at = designCoord(catalog);
  return at == null ? "설계점" : `${String(catalog?.axis).toUpperCase()[0]}${at}`;
}

/** 이 탭이 마지막으로 보거나 적용한 스토어 값으로 표시 — 이후 변경 감지의 기준. */
function markSeen() {
  seenTables = store.get("gainTables");
  seenOff = store.get("gainScheduleOff") === true;
}

function storeChanged() {
  return store.get("gainTables") !== seenTables
    || (store.get("gainScheduleOff") === true) !== seenOff;
}

/** 적용해 둔 형상(스토어)을 편집 상태로 **되읽는다** — 자동 설계 확정본 포함.
 *
 * 이 탭은 지금까지 스토어에 쓰기만 했다: 자동 설계가 확정한 스케줄이 시뮬·Autocode
 * ·블록도에는 걸려 있는데 정작 게인 화면만 서버 제안을 보여 줬다. 적용된 형상과
 * 보이는 형상이 다르면 "지금 형상"이라는 말이 성립하지 않는다.
 *
 * 확정본은 자리마다 breakpoint가 다르므로(적합이 자리별 독립) 합집합 축으로 정렬해
 * 한 표에 담는다 — 조회 함수는 보존된다(lib/gainsched alignTables).
 * 반환 null = 아직 아무것도 적용한 적 없음(서버 기본 형상이 그대로 돈다). */
function adoptStored() {
  const stored = store.get("gainTables");
  const off = store.get("gainScheduleOff") === true;
  markSeen();
  return adoptTables(stored, off, store.get("gainTablesSource") ?? null);
}

/** 표 묶음을 편집 상태로 세운다 — 스토어 작업 사본(위)과 문서 확정 표(결함 주입 기준)가 같은 길을 쓴다. */
function adoptTables(stored, off, source) {
  if (!stored && !off) return null;
  selected = selectedSlots(catalog, stored, off);
  if (!stored) return { source, slots: 0, unknown: [], aligned: false };

  const idx = slotIndex(catalog);
  const unknown = Object.keys(stored).filter((n) => !idx.has(n));
  const known = {};
  for (const [name, t] of Object.entries(stored)) {
    if (idx.has(name)) known[name] = t;
  }
  const al = alignTables(known, catalog.axis);
  if (!al) {
    // 어느 자리가 어느 축인지 그대로 말한다 — 자동 설계가 고도 축으로 적합한 표가 여기 온다
    selected = defaultSelection(catalog);
    return { source, error: axisMismatchText(axisMismatch(known, catalog.axis), catalog.axis), unknown };
  }
  // 스토어 객체를 그대로 심으면 셀 편집이 '적용' 전에 다른 탭으로 새어 나간다
  for (const [name, t] of Object.entries(al.tables)) {
    idx.get(name).table = JSON.parse(JSON.stringify(t));
  }
  selected = Object.keys(al.tables);
  return {
    source, unknown, aligned: al.aligned,
    points: al.axis.length, slots: selected.length,
  };
}

function adoptedText(a) {
  if (!a) return "";
  // 조사는 이름(괄호 덧붙임 앞)의 받침으로 — 「문서의 확정 게인 표을」이 찍혔다
  const name = a.source?.kind === "autodesign" ? "자동 설계 확정본"
    : a.source?.kind === "document" ? "문서의 확정 게인 표" : "적용해 둔 형상";
  const src = `${name}${a.source?.kind === "autodesign" && a.source.resultId ? ` (${a.source.resultId})` : ""}`;
  const obj = `${src}${josaOf(name, "을/를")}`;
  if (a.error) return `${obj} 되읽지 못했습니다 — ${a.error}. 서버 제안을 표시합니다.`;
  if (!a.slots) return `${src} — 스케줄 없는 형상이 적용돼 있습니다 (전 자리 설계점 고정).`;
  let out = `${obj} 되읽었습니다 — ${a.slots}자리`;
  if (a.aligned) {
    out += ` · 자리마다 다른 breakpoint를 합집합 ${a.points}점으로 정렬해 표시`
      + " (구간 선형 보간 결과는 그대로)";
  }
  if (a.unknown.length) out += ` · 이 카탈로그에 없는 자리는 제외: ${a.unknown.join(", ")}`;
  return `${out}. 편집 후 '시뮬·코드에 적용'을 눌러야 반영됩니다.`;
}

/** 스케줄 자리 격자 — 켜고/끄기 + **끈 자리의 상수 편집**.
 *
 * 끈 자리의 숫자는 표시가 아니라 값이다 — 블록도 폼과 같은 스토어에 살고, 여기서
 * 고치면 저기 보인다. 켠 자리는 아래 표가 정본이라 설계점 값만 읽기로 보여 준다
 * (여기서도 고칠 수 있으면 한 게인에 편집처가 둘이 된다).
 * 불가 자리는 빈칸이 아니라 사유를 단 "—"다 (빈칸은 버그로 읽힌다). */
function slotGrid(slots, statusLine) {
  const rows = slotRows(catalog);
  const zeros = zeroTables(catalog, selected);
  const draft = "스케줄 대상 변경됨 (미적용) — '시뮬·코드에 적용'을 누르세요.";

  const cell = (slot) => {
    if (!slot) return el("span", { class: "hint" }, "—");
    if (!slot.available) {
      return el("span", { class: "hint", title: slot.reason }, "— 불가");
    }
    const on = selected.includes(slot.name);
    // 켠 자리의 값은 표의 설계점, 끈 자리의 값은 스토어 상수 — 정본이 다르다
    const cur = on ? foldToConstant(catalog, slot, tables) : constantOf(slot, constants);
    const toggle = el("input", {
      type: "checkbox", checked: on,
      onchange: () => {
        if (on) {
          // 끄기 — 편집한 표의 설계점 값으로 굳는다 (옛 설계 상수로 되돌리지 않는다)
          constants = withConstant(catalog, slot, foldToConstant(catalog, slot, tables), constants);
        } else {
          // 켜기 — 지금 상수에서 출발하는 표를 심는다 (설계점에서는 상수 그대로).
          // 상수는 여기서 다시 읽는다 — 렌더 때 잡아 둔 값은 방금 친 입력을 모른다
          slot.table = seedTable(catalog, slot, constantOf(slot, constants));
        }
        selected = toggleSlot(catalog, selected, slot.name);
        renderTables(slots, statusLine);
        statusLine.textContent = draft;
        markStale();
      },
    });
    const title = `${slot.param} = ${fmt(cur, 6)} ${slot.unit ?? ""} · ${slot.desc ?? ""}`;
    if (on) {
      return el("label", { title: `${title}\n켠 자리 — 표가 정본. 끄면 표의 설계점 값으로 굳는다` },
        toggle, el("span", { class: "hint" }, ` ${fmt(cur, 3)} ▸표`));
    }
    return el("label", { title: `${title}\n끈 자리 — 이 상수가 값이다 (블록도 폼과 같은 값)` },
      toggle,
      el("input", {
        class: "num-sm", type: "text", value: String(cur),
        onchange: (ev) => {
          // 빈 값은 Number("")===0으로 통과한다 — 비우고 나가면 그 게인이 조용히
          // 0이 된다. 아래 표 셀 핸들러가 같은 함정을 막고 있는 그 가드다 (리뷰 S2)
          const raw = ev.target.value.trim();
          const v = Number(raw);
          if (raw === "" || !Number.isFinite(v)) {
            ev.target.value = String(constantOf(slot, constants));
            statusLine.textContent = `잘못된 수치 — ${slot.name} 원복됨.`;
            return;
          }
          constants = withConstant(catalog, slot, v, constants);
          statusLine.textContent = draft; // 재그리기 없음 — 입력 포커스를 잃지 않는다
          markStale();
        },
      }));
  };
  return el("div", {},
    el("div", { class: "scroll-x" },
      el("table", {},
        el("thead", {}, el("tr", {},
          el("th", {}, "스케줄 대상 \\ 게인"),
          GAIN_KEYS.map((k) => el("th", {}, k)))),
        el("tbody", {}, rows.map((r) => el("tr", {},
          el("td", {}, `${r.label} (${r.group})`),
          r.cells.map((c) => el("td", {}, cell(c))),
        ))))),
    el("p", { class: "hint" },
      `${schedSummary(catalog, selected)}. 칸의 수치는 설계점(${axisLabel()}) 값이다 — `,
      "끈 자리는 입력칸이고 그 값이 곧 상수다 — 블록도 폼과 같은 값이다. ",
      "켠 자리는 아래 표가 정본이라 읽기 전용 — 끄면 표의 설계점 값으로 굳고 ",
      "탑재 코드에서 룩업이 사라진다. 속도·헤딩의 k_rate는 그 축에 rate 입력이 없어 구조상 불가."),
    zeros.length
      ? el("p", { class: "hint" },
          `설계값이 0이라 표가 전부 0인 자리: ${zeros.join(" · ")} — 셀을 편집하기 전엔 `
          + "스케줄해도 거동이 같다 (구조만 바뀐다).")
      : null,
  );
}

/** 전 게인 구간별 회귀 — 실패 시 {error} (첫 실패에서 중단, 조건은 전 게인 공통). */
function computeFits(groups) {
  const items = (fitCfg.boundaries ?? "").split(",").map((s) => s.trim()).filter((s) => s !== "");
  const values = items.map(Number);
  const bad = items.filter((_, i) => !Number.isFinite(values[i]));
  if (bad.length) return { error: `경계 형식 오류: ${bad.join(", ")}` };
  const overlays = new Map(); // group → 점선 시리즈 목록
  const rows = []; // {name, pw} — 근사식·잔차 표
  for (const g of groups) {
    const list = [];
    for (const s of g.series) {
      const pw = piecewisePolyfit(g.mach, s.data, values, fitCfg.degree);
      if (pw.error) return { error: pw.error };
      const sm = sampleFit(pw);
      list.push({ label: "", data: sm.y, x: sm.x, color: s.color, dash: [5, 4], markers: false });
      rows.push({ name: `${g.group}.${s.label}`, pw });
    }
    overlays.set(g.group, list);
  }
  return { overlays, rows };
}

const SUP = ["", "", "²", "³", "⁴", "⁵", "⁶"];

function formulaText(fit) {
  let out = "";
  rawCoeffs(fit).forEach((v, k) => {
    const term = k === 0 ? fmt(Math.abs(v), 4) : `${fmt(Math.abs(v), 4)}·M${SUP[k]}`;
    if (k === 0) out = (v < 0 ? "−" : "") + term;
    else out += ` ${v < 0 ? "−" : "+"} ${term}`;
  });
  return out;
}

function fitDetails(rows) {
  return el("details", {
    open: fitCfg.detailsOpen,
    ontoggle: (ev) => { fitCfg.detailsOpen = ev.target.open; }, // 재그리기에도 접힘 유지
  },
    el("summary", {}, "근사식 계수·잔차·경계 연속성"),
    el("div", { class: "scroll-x" },
      el("table", { class: "fit-table" },
        el("thead", {}, el("tr", {},
          ["게인", "구간별 근사식 p(M)", "최대|잔차|", "RMS", "경계 점프 (값 / 기울기)"]
            .map((h) => el("th", {}, h)))),
        el("tbody", {}, rows.map(({ name, pw }) => el("tr", {},
          el("td", {}, name),
          el("td", { class: "col-lines" }, pw.segments.map((s) =>
            el("div", {}, `[M${fmt(s.x0, 3)}–M${fmt(s.x1, 3)}]  ${formulaText(s.fit)}`))),
          el("td", { class: "num" }, fmt(pw.maxResidual, 3)),
          el("td", { class: "num" }, fmt(pw.rms, 3)),
          el("td", { class: "col-lines" }, pw.joints.length
            ? pw.joints.map((j) => el("div", {},
                `M${fmt(j.x, 3)}: ${fmt(j.valueJump, 3)} / ${fmt(j.slopeJump, 3)}`))
            : "—"),
        ))))),
    el("p", { class: "hint" },
      "근사식은 검토·반출용 표시 — 시뮬 조회는 여전히 테이블 구간 선형 보간 (실주입은 백로그). ",
      "경계 점프 = 경계 마하에서 우측 구간식 − 좌측 구간식 (값·기울기). 허용치 판정은 설계자 소관 (01 §3.4)."));
}

function drawCharts(chartBox, fitBox, fitStatus) {
  const { groups, skipped } = gainPlotGroups(tables);
  let overlays = null;
  let fitRows = [];
  fitStatus.textContent = "";
  if (fitCfg.show) {
    const r = computeFits(groups);
    if (r.error) fitStatus.textContent = `근사 불가: ${r.error}`;
    else { overlays = r.overlays; fitRows = r.rows; }
  }
  // 네이티브 append에 null·배열 직접 전달 금지 (문자열화 함정) — el 래핑으로 조립
  clear(chartBox).append(el("div", {},
    el("div", { class: "row" },
      groups.map(({ group, mach, series }) =>
        lineChartCanvas(mach, overlays ? [...series, ...overlays.get(group)] : series, {
          title: `${group} 게인`, width: 420, height: 200, xUnit: "M", markers: true,
        }))),
    el("p", { class: "hint" },
      "점 = 테이블 격자점(브레이크포인트), 실선 = 현재 조회 규칙(구간 선형 보간, 외삽 clip), ",
      "점선 = 구간별 다항식 회귀 근사 곡선(아래 「근사 곡선」 패널의 경계·차수). 셀 편집 시 즉시 갱신."),
    skipped.length
      ? el("p", { class: "hint" },
          `차트 제외: ${skipped.map((s) => `${s.name} — ${s.reason}`).join(" · ")}`)
      : null,
  ));
  // 계수 표는 패널 뒤 자기 시트에 — 곡선과 같은 재그리기에서 갱신되어 둘이 어긋나지 않는다.
  // 근사를 껐거나 실패하면 시트를 비운다(.tab-sheet:not(:empty) — 빈 카드가 남지 않는다)
  clear(fitBox);
  if (fitRows.length) fitBox.append(fitDetails(fitRows));
}

function renderTables(slots, statusLine) {
  // 칩 배지는 여기 머리에서 갱신한다 — 자리를 끄면 아래에 조기 반환 경로가 둘 있고,
  // 끝에서 부르면 그 두 경로가 옛 수를 들고 남는다 (selected는 이미 갱신된 뒤다)
  gainsDrawers?.refresh();
  // 편집 대상은 **켠 자리만**. 카탈로그의 표를 참조로 들고 있어 셀 편집이 그대로
  // 남는다 — 자리를 껐다 켜도 고쳐 둔 값이 살아 있어야 비교가 성립한다
  tables = appliedTables(catalog, selected);
  // **표를 그리기 직전에 축을 맞춘다.** 이 표는 행=축 격자·열=자리인데 격자를
  // 첫 열에서만 읽는다 — 자리마다 축이 다르면(확정본을 되읽은 뒤 다른 자리를 새로
  // 켜면 서버 제안 격자가 섞여 든다) 셀 편집이 **다른 비행조건 칸에 기록되고**
  // 짧은 열은 화면 밖으로 사라진다. 되읽기에서만 맞추면 그 이후 토글이 어긋난다
  const aligned = alignTables(tables, catalog.axis);
  if (aligned === null) {
    clear(slots.grid).append(slotGrid(slots, statusLine));
    clear(slots.chart);
    clear(slots.fitTable); // 곡선이 없으면 그 계수도 없다 — 옛 표가 남지 않게
    clear(slots.fit).append(el("p", { class: "hint" },
      "축이 어긋나 곡선을 세우지 못했습니다 — 아래 사유를 먼저 해결하세요."));
    clear(slots.table).append(el("p", { class: "error-box" },
      `편집 표를 세울 수 없습니다 — ${axisMismatchText(axisMismatch(tables, catalog.axis), catalog.axis)}.`));
    return;
  }
  if (aligned.aligned) {
    // 정렬본을 카탈로그에 되심어 편집 경로(slot.table 참조 공유)를 잇는다
    const idx = slotIndex(catalog);
    for (const [name, t] of Object.entries(aligned.tables)) idx.get(name).table = t;
    tables = appliedTables(catalog, selected);
  }
  clear(slots.grid).append(slotGrid(slots, statusLine));
  const names = Object.keys(tables);
  if (names.length === 0) {
    clear(slots.chart);
    clear(slots.fitTable);
    // 빈 패널을 남기지 않는다 — 왜 비었는지가 화면에 없으면 고장으로 읽힌다
    clear(slots.fit).append(el("p", { class: "hint" },
      "켠 자리가 없어 근사할 곡선이 없습니다 — 「스케줄 자리」에서 자리를 켜세요."));
    clear(slots.table).append(el("p", { class: "hint" },
      "스케줄된 자리가 없습니다 — 전 게인이 설계점 상수로 고정된 형상입니다. ",
      "탑재 코드에서 게인 스케줄 서브시스템(fcl_sched.c)이 통째로 사라집니다. ",
      "「스케줄 자리」 패널에서 자리를 켜면 여기에 표와 곡선이 섭니다."));
    return;
  }
  const machs = tables[names[0]].axes[catalog.axis];
  const chartBox = clear(slots.chart);
  const fitStatus = el("span", { class: "hint" });
  const redraw = () => drawCharts(chartBox, slots.fitTable, fitStatus);
  // 컨트롤은 redraw 대상 밖 — 입력 도중 재그리기로 포커스를 잃지 않게
  const fitControls = el("div", { class: "row" },
    el("label", {},
      el("input", {
        type: "checkbox", checked: fitCfg.show,
        onchange: (ev) => { fitCfg.show = ev.target.checked; redraw(); },
      }),
      " 근사 곡선(점선) 표시"),
    el("label", { title: "처음 값은 문서 스케줄 표의 상한 클립이 풀리는 격자점(꺾임) — 비우면 한 구간" },
      "구간 경계 (마하, 쉼표 구분) ",
      el("input", {
        class: "num-sm", type: "text", value: fitCfg.boundaries ?? "",
        onchange: (ev) => { fitCfg.boundaries = ev.target.value; redraw(); },
      })),
    el("label", {}, "차수 ",
      el("input", {
        class: "num-sm", type: "number", min: "1", max: "6", step: "1",
        value: String(fitCfg.degree),
        onchange: (ev) => { fitCfg.degree = Number(ev.target.value); redraw(); },
      })),
    fitStatus,
  );
  redraw();
  clear(slots.fit).append(fitControls);
  // 전치 배열: 행 = 마하(비행조건), 열 = 게인 6개 — 폭이 패널에 들어오고
  // 한 비행조건의 게인 세트를 한 줄에서 편집
  clear(slots.table).append(
    el("div", { class: "scroll-x" },
      el("table", {},
        el("thead", {}, el("tr", {},
          el("th", {}, "마하 \\ 게인"),
          names.map((name) => el("th", {}, name)))),
        el("tbody", {}, machs.map((m, i) => el("tr", {},
          el("td", {}, `M${m}`),
          names.map((name) => el("td", {},
            el("input", {
              class: "num-sm",
              type: "number",
              step: "any",
              value: String(tables[name].data[i]),
              onchange: (ev) => {
                // badInput(오타)이면 value가 ""가 되어 Number("")===0으로 제로
                // 게인이 조용히 주입됨 — 원복 + 경고 (리뷰 S2)
                const raw = ev.target.value.trim();
                const num = Number(raw);
                if (raw === "" || ev.target.validity.badInput || !Number.isFinite(num)) {
                  ev.target.value = String(tables[name].data[i]);
                  statusLine.textContent = `잘못된 수치 — M${m} ${name} 원복됨.`;
                  return;
                }
                tables[name].data[i] = num;
                redraw(); // 편집값 즉시 반영 (data 참조 공유) — 근사 곡선 포함
                statusLine.textContent = "편집됨 (미적용) — '시뮬·코드에 적용'을 누르세요.";
                markStale();
              },
            }))),
        ))),
      ),
    ),
    el("p", { class: "hint" },
      "열 = 위에서 켠 자리 (\"그룹.게인\" = 스텝 게인 덮어쓰기 인자), 행 = 스케줄 변수 마하. ",
      "외삽 clip 고정 — 그룹·키·형상 검증은 제출 시 엔진이 수행."),
  );
}
