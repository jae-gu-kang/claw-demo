/** 마진 맵 뷰 (02 §8 5단계) — 케이스 격자 × PI 개루프(다중) → 마진 맵·고유치·감쇠비·비행성 수준.

이 탭의 답은 **히트맵**이다: "전 구간에서 마진이 서는가, 어디가 얇은가." 그래서
PM·GM 맵이 카드 밖 전면에 놓이고(블록도 최상위·영향성과 같은 규약, views/stage.js),
격자·루프 편집과 고유치 맵·감쇠비 표는 패널에 들어간다 — 매번 보는 것과 가끔 보는
것을 같은 크기로 늘어놓으면 어느 것이 답인지가 화면에서 사라진다.

수치는 전부 서버(엔진 linearize/classify/pi_loop) 산출 — 여기서는 표시만.
루프 스펙(축·출력 상태·입력·kp·ki·sign)은 행 편집 — 서버 loops[] 계약 그대로
("설계값은 요청이 보유"). 사전검증은 lib/loops.js, 최종 판정은 서버 422.
루프 게인은 **고른 기체가 실제로 나는 k_rate**로 선다 — 엔진 조립과 같은 우선순위로, 문서 확정 게인 표
(law.gain_tables, 낡지 않았을 때)가 있으면 그 표, 없으면 규칙 스케줄(카탈로그 제안 표)을 읽는다(lib/loops.js
loopGainSources — 종전의 설계 상수 law.design은 확정 표가 있는 기체가 실제로 날지 않는 값이었다). 손대지 않은
문서 게인 루프는 kp를 싣지 않고 `gain_source: "profile"`로 보낸다 — 서버가 **칸마다** 그 칸의 운용점에서 조립 법칙의
게인을 읽으므로(엔진 openloop._effective_gain과 같은 자) 모든 칸이 그 칸의 실제 게인으로 잰 마진이다. 결과 캡션의
격자 게인 범위는 서버가 칸마다 실제로 쓴 게인(entry.gains)에서 낸다. 편집 표의 kp 칸은 「게인 읽을 마하」(비우면
고른 점의 가운데)의 값이고, 고치면 그 루프는 손으로 적은 한 값으로 전 칸을 잰다. 확정 게인 표가 낡았으면 서버 조립이
거부하므로(시뮬·코드와 같은 422) 그때만 종전대로 한 점에서 읽은 kp를 싣고, 그 kp가 그 칸의 게인인 칸이 몇인지를
캡션이 말한다(나머지 칸은 근사 — 칸별 보드선도도 그 칸의 게인을 덧붙인다). 손대지 않은 동안은 문서를 따라가고,
고치면 그 편집이 남는다. 문서에 게인이 없으면 루프도 없다(예제 값을 물려주지 않는다 — 기체 고정 금지).
트림 가능/불가·판정 색상 맵은 트림 플래그 재사용 (06 §4).
칸의 PM·GM은 나이퀴스트 여유다(엔진 nyquist_margins — −1까지의 거리, 폐루프 발산이면 「발산」). 같은 축의 나머지
루프는 닫고 그 루프를 끊는다(엔진 broken_loop — AS94900). 종전 control.margin 부호를 그대로 칠해 다중 교차 레이트
루프가 안정인데도 전 칸 음수로 칠해졌다(e2e D2). 그 뜻은 결과 캡션(lib/loops.js marginSemanticsText)이 그림 밑에서 말한다.

점은 요구영역의 기본 격자(서버 /grid/base — 트림 탭과 같은 점·같은 이름)에서 보낼 수 있는 점 전부가 기본이고, 공용
고르개(views/condpick.js — 영향성과 같은 부품)로 좁힌다(05 §11.13 5단계 나머지). 요구영역이 미정의면 [실행]이 막힌다 —
템플릿 격자로 되돌아가지 않는다. 「게인 읽을 마하」를 비우면 고른 점의 가운데(lib/opspace.js centrePoint)다.

쇼케이스 진행기 신호(lib/showcasecue.js): run() — 비행조건을 「전부」로 되돌려 기본 격자를 다시 받고, 루프를 문서
게인(칸별 법칙 게인)으로 세워 [실행]과 같은 길로 돌린 뒤, 최악 PM 칸의 보드선도를 열고 PM·GM 최악·비행성 최악과 루프 게인
출처를 보고한다.
*/

import { ApiError, api, errorText } from "../api.js";
import { clear, el, fmt } from "../dom.js";
import { FQ_BADGE, fqKey, fqLegendText, fqMeasureText, fqWorst, marginsCueReport } from "../lib/fq.js";
import { DOC_FAILED_HINT, MARGIN_ACT_FALLBACK } from "../lib/missiontemplate.js";
import { centrePoint, reuseLine, reuseTip } from "../lib/opspace.js";
import { applyUntouched, selectedDefaults } from "./missionfill.js";
import { createCondPicker } from "./condpick.js";
import {
  AXIS_NAMES, DELAY_TOOL_DEFAULT, LOOPS_LOADING_TEXT, bodeLawGainNote, bodeMarginNotes, bodeOthers, cellGainNote,
  delaySourceText, followDocRows, gainCueData, gainSourceText, gainSummaryTag, lawGainRecord,
  lawGainsPerCase, lawKpText, loopGainSources, loopKpTag, loopLoadState, loopsAt, marginCellView, marginSemanticsText,
  requestLoops, runGainInfo, stableMarginEntries, unstableCells, unstableTail, validateActuatorDelay,
  validateLoops,
} from "../lib/loops.js";
import { criteriaBadgeSpec, criteriaFreshness } from "../lib/freshness.js";
import { EXAMPLE_ID, currentSelection } from "../lib/profile.js";
import { effectiveOf } from "../lib/profileform.js";
import {
  OLD_RESULT_HINT, STATUS, STATUS_LABEL, criteriaLineText, fuelsOf, hasMarginStatuses,
  heatmapCanvasHeight, heatmapCellAt, marginCellStatus, marginLegendText, marginWorst, pivotCases, statusColor,
} from "../lib/plot.js";
import { revealPanel } from "../lib/reveal.js";
import { failCue, reportCue, takeCue, unknownAction } from "../lib/showcasecue.js";
import { toCanvasXY } from "../lib/wpmap.js";
import { bodeCanvas, heatmapCanvas, scatterCanvas } from "./plots.js";
import { attachProgress, cancelledWithoutResult } from "./progress.js";
import { errorWithSeedLink } from "./seedlink.js";
import { createDrawers, tabStage, tabTop } from "./stage.js";

// 신호 실패 사유 — 서버 오류는 errorText(422 배열·엔진 detail을 사람 글로), 그 밖은 메시지만("Error: " 접두 없이)
const cueReason = (e) => (e instanceof ApiError ? errorText(e) : (e?.message ?? String(e)));

let lastBody = null;
let runningJobId = null;
let marginCue = null; // 잡을 건 진행기 신호 — 잡이 끝나면 한 번 보고하고 지운다 (감시자가 둘이어도 한 번)
// 붙인 감시자 차례 — 잡이 끝났을 때 결과·신호는 **마지막에 붙은**(= 지금 화면의) 감시자만 맡는다. 먼저 끝난 쪽이
// 가져가면 버려진 화면의 감시자가 신호를 먹고 최악 칸 보드선도를 아무도 못 보는 DOM에 연다
let watchSeq = 0;
let marginsVisit = 0; // 탭을 그린 차례 — 떠난 방문의 늦은 신호 처리가 버려진 화면에서 잡을 걸지 않게
// 탭 재진입에도 루프 편집 상태 유지 (수치는 입력 문자열 — 제출 시 파싱). 처음엔 비어 있고 고른 기체의 게인
// 출처가 도착하면 선다 — 문서가 없거나 게인이 없으면 루프가 없다(예제 값을 물려주지 않는다).
// 행마다 touched(편집 표에서 고쳤거나 「루프 추가」로 만든 행)를 단다 — 손대지 않은 행만 **루프마다** 새 문서 게인을
// 따라간다(lib/loops.js followDocRows). 종전의 표 전체 비교(all-or-nothing)는 한 루프만 고쳐도 나머지 루프를 옛 점의
// kp로 굳혀 「손으로 적은 값」으로 불렀다(round1 #4)
let loopRows = [];
// 사용자가 지운 문서 루프 이름 — 문서 게인을 다시 읽어도 되살리지 않는다(「문서 게인으로 복원」이 비운다)
let removedDocLoops = [];
// 문서 게인 → 루프 {rows, skipped} | {rows: [], skipped: [], error} — 지금 격자·「게인 읽을 마하」의 점에서 (복원 버튼이 쓴다)
let designLoops = null;
// 루프 게인 출처(lib/loops.js loopGainSources — 확정 표 | 규칙 스케줄) | {error} — 탭을 그릴 때마다 다시 받는다
let gainSources = null;
// 「게인 읽을 마하」 칸 글 — 비면 고른 점의 가운데 마하 (탭 재진입에도 유지)
let refMachText = "";
// 제출·완료한 실행의 게인 기록(lib/loops.js runGainInfo) — 제출 시점에 굳혀 결과(lastBody)와 짝으로 산다
let runningGains = null;
let lastGains = null;
// 제출·완료한 실행의 지연 출처(lib/loops.js delaySourceText — 툴 기본값 | 입력값) — 게인 기록과 같은 짝 규약
let runningDelaySrc = null;
let lastDelaySrc = null;
// 판정선 — 고른 기체의 평가 기준(GET /profiles/{id}/criteria, 기준 통합 ①). **칸의 색은 이것으로 짜지 않는다**:
// 칸 색은 결과에 실린 서버 판정(margins[loop].pm_status·gm_status)이고, 이것은 범례·제목에 판정선을 적는 데만 쓴다.
// 탭을 그릴 때마다 다시 받는다(기체 편집기에서 기준을 바꿨을 수 있다). criteriaFor = 받은 기체 id
let criteria = null;
let criteriaErr = null;
let criteriaFor = null;
// 결과를 **계산한** 기체(body.profile.id)의 평가 기준 — id → {resp}(resp = GET /profiles/{id}/criteria 응답, 실패·404는
// null → 판정 기준 미상). 히트맵 제목의 판정선과 「기준 다름」 대조는 이것으로 한다 — 지금 고른 기체가 아니다(lastBody는
// 기체를 바꿔도 남는다). 탭을 그릴 때마다 비운다(기체 편집기에서 기준을 바꿨을 수 있다). 받는 중인 id는 resultCritPending
let resultCritCache = new Map();
let resultCritPending = new Set();
// 기준이 도착하면 부를 지금 화면의 결과 다시 그리기 — draw()가 갈아 끼운다(옛 클로저는 떨어진 DOM이라 부르지 않는다)
let redrawResult = null;

/** 결과를 계산한 기체의 기준 {ready, resp}. 캐시에 없으면 받기 시작하고 ready=false — 도착하면 redrawResult. */
function resultCriteriaOf(body) {
  const id = body?.profile?.id;
  if (!id) return { ready: true, resp: null };
  const hit = resultCritCache.get(id);
  if (hit) return { ready: true, resp: hit.resp };
  if (!resultCritPending.has(id)) {
    const cache = resultCritCache;
    const pending = resultCritPending;
    pending.add(id);
    api.get(`/profiles/${encodeURIComponent(id)}/criteria`).catch(() => null).then((resp) => {
      pending.delete(id);
      if (!cache.has(id)) cache.set(id, { resp: resp ?? null });
      if (cache === resultCritCache) redrawResult?.(); // 버려진 방문의 캐시면 그리지 않는다
    });
  }
  return { ready: false, resp: null };
}
// 보드선도 요청 시퀀스 — **모듈 스코프**여야 한다. renderResults 지역이면 재진입이
// bodeSeq=0인 새 클로저를 만들어, 옛 클로저의 진행 중 요청이 자기 카운터로는
// 유효(seq === bodeSeq)라 **DOM에서 떨어진 슬롯**에 곡선을 그린다 — 사용자는
// "계산 중"만 보고 곡선은 영영 안 온다(조용한 비표시). 대시보드 재렌더 경로는
// 기체 평가 기준 응답 뒤와 탭 재진입 둘 다 있다. 인스턴스는 동시에 하나뿐이라
// 모듈로 올려도 서로 간섭하지 않는다
let bodeSeq = 0;
// 탭을 떠났다 와도 열어 둔 패널은 그대로 (모듈 스코프 규약)
let openDrawer = null;

export function render() {
  const visit = ++marginsVisit;
  resultCritCache = new Map(); // 기준 편집을 따라 다시 받는다
  resultCritPending = new Set();
  const errBox = el("div");
  const progressBox = el("div");
  const loopBox = el("div");
  // 결과를 한 덩이(resultBox)로 내면 어느 조각이 전면이고 어느 조각이 패널인지를
  // 부르는 쪽이 정할 수 없다 — 슬롯으로 갈라 renderResults가 각각 채운다
  const slots = {
    head: el("div"),   // 전면 — 몇 건·무엇을 포함했나·연료 선택
    plots: el("div"),  // 전면 — PM·GM 히트맵 (이 탭의 답)
    eig: el("div"),    // 패널 — 고유치 맵
    damp: el("div"),   // 패널 — 감쇠비 표
  };

  // 비행조건 — 이 탭은 격자를 따로 정하지 않는다(05 §11.13 5단계 나머지): 요구영역의 기본 격자(서버 /grid/base,
  // 트림 탭과 같은 점·같은 이름)에서 보낼 수 있는 점 **전부**가 기본이고, 공용 고르개(views/condpick.js — 영향성과
  // 같은 부품)로 좁힌다. 요구영역이 미정의면 보내지 않는다 — 템플릿 격자로 되돌아가지 않는다.
  // 고르개가 바뀌면(격자 도착·선택) 가운데 점도 바뀐다 — 손대지 않은 루프의 게인을 다시 읽는다(아래에서 갈아 끼운다)
  let onCondChange = () => {};
  const picker = createCondPicker({ key: "margins", onChange: () => onCondChange(), where: "위 「비행조건」" });
  const fFp = el("input", { value: "web-margin-v1" });
  // 작동기·지연 포함 — [기본값 01 §4.2] 체크 ON으로 시작, 꺼서 영향 분리 비교 가능
  const fUseAct = el("input", { type: "checkbox", checked: true });
  // 작동기 칸은 예제 기체 actuator 값의 사본(폴백) — 고른 기체 문서가 오면 손대지 않은 칸만 그 기체 값으로
  const fWn = el("input", { class: "num-sm", value: MARGIN_ACT_FALLBACK.wn });
  const fZeta = el("input", { class: "num-sm", value: MARGIN_ACT_FALLBACK.zeta });
  const fUseDelay = el("input", { type: "checkbox", checked: true });
  // 지연 칸은 툴 기본값(lib/loops.js DELAY_TOOL_DEFAULT) — 기체 문서에 지연 칸이 없어 기체에서 채울 수 없다.
  // 결과 캡션이 그 출처를 수치 옆에 단다(appliedSummary)
  const fDelay = el("input", { class: "num-sm", value: String(DELAY_TOOL_DEFAULT.delay_s) });
  const fPade = el("input", { class: "num-sm", value: String(DELAY_TOOL_DEFAULT.pade_order) });
  const defaultsReady = selectedDefaults().then((d) => {
    if (d) applyUntouched({ wn: fWn, zeta: fZeta }, MARGIN_ACT_FALLBACK, d.margins);
    return d;
  });

  // ── 루프 게인 — 고른 기체가 실제로 나는 k_rate (확정 표 | 규칙 스케줄, lib/loops.js loopGainSources) ──
  // 손대지 않은 루프는 서버가 칸마다 읽는다(gain_source "profile"). 편집 표의 kp 칸은 한 점의 값 — 「게인 읽을 마하」
  // 칸, 비우면 고른 점의 가운데(lib/opspace.js centrePoint). 고칠 때의 출발값이고, 확정 표가 낡아 칸별로 못 읽을 때
  // 전 칸에 싣는 값이다
  const fRefMach = el("input", {
    class: "num-sm", value: refMachText, placeholder: "격자 가운데",
    title: "편집 표의 kp 칸을 이 마하에서 기체가 실제로 나는 게인으로 세운다 — 비우면 고른 점의 가운데"
      + "(가운데 연료 → 가운데 고도 → 그 행의 가운데 마하). "
      + "손대지 않은 루프는 실행 때 서버가 칸마다 그 칸의 게인을 읽으므로 이 값과 무관하게 전 칸이 정확하다. "
      + "확정 게인 표가 낡았을 때만 이 한 값을 전 칸에 싣는다(그 마하 열만 정확)",
    oninput: (ev) => { refMachText = ev.target.value; refreshDocLoops(); },
  });
  // 고른 점 — 받는 중·요구 미정의·0점이면 null(사유는 고르개 요약이 말한다)
  const gridPoints = () => {
    try {
      return picker.selectedCases();
    } catch {
      return null;
    }
  };
  // 「게인 읽을 마하」 칸이 틀렸으면 그 사유
  const refMachErr = () => {
    const t = refMachText.trim();
    const m = Number(t);
    return t && !(Number.isFinite(m) && m > 0)
      ? `「게인 읽을 마하」가 양수가 아니다: ${refMachText} — 비우면 고른 점의 가운데 마하` : null;
  };
  // 게인을 읽을 점 {mach, alt, fuel} — 고른 점의 가운데(마하는 칸에 적었으면 그 값). 점이 없거나 칸 글이 틀리면 null
  const refPoint = () => {
    const centre = centrePoint(gridPoints());
    if (!centre || refMachErr()) return null;
    const t = refMachText.trim();
    return t ? { ...centre, mach: Number(t) } : centre;
  };
  // 문서 게인 행을 지금 점에서 다시 읽는다 — 손대지 않은 루프만, 루프마다 따라간다(복원 버튼용 designLoops는 늘
  // 갱신). force면 손댄 행·지운 루프도 버리고 문서 행 그대로. 점을 못 정하면 사유, 아니면 null
  const refreshDocLoops = ({ force = false } = {}) => {
    // 버려진 화면(재진입 전)의 늦은 격자 채움이 모듈의 편집 행을 옛 화면의 격자 점으로 다시 세우지 않게
    if (visit !== marginsVisit) return null;
    if (!gainSources || gainSources.error) return null;
    const ref = refPoint();
    if (!ref) {
      paintLoopNote();
      return refMachErr() ?? "게인을 읽을 점이 없다 — 위 「비행조건」의 기본 격자를 받은 뒤 점을 고른다";
    }
    designLoops = loopsAt(gainSources, ref);
    if (force) removedDocLoops = [];
    const next = followDocRows(force ? [] : loopRows, designLoops.rows, removedDocLoops);
    if (JSON.stringify(next) !== JSON.stringify(loopRows)) {
      loopRows = next;
      renderLoopEditor(loopBox);
      drawers.refresh();
    }
    paintLoopNote();
    return null;
  };
  const loopNote = el("div");
  const paintLoopNote = () => {
    clear(loopNote);
    if (loopLoadState(gainSources) === "loading") {
      loopNote.append(el("p", { class: "hint" }, LOOPS_LOADING_TEXT));
      return;
    }
    if (designLoops?.error) {
      loopNote.append(...errorWithSeedLink(designLoops.error, "여기 루프가 그 게인으로 섭니다."));
      return;
    }
    // 문서 게인 행이 무엇을 어디서 읽은 것인가 — 결과 캡션과 같은 글(제출 전 미리보기)
    const ref = refPoint();
    const points = gridPoints();
    const text = gainSources && !gainSources.error && ref && points
      ? gainSourceText(runGainInfo(gainSources, loopRows, designLoops?.rows ?? [], ref, points,
        lawGainsPerCase(gainSources)))
      : null;
    if (text) loopNote.append(el("p", { class: "hint" }, text));
    else if (gainSources && !gainSources.error && !ref) {
      loopNote.append(el("p", { class: "hint" }, refMachErr() ?? "게인을 읽을 점을 기다린다 — 위 「비행조건」"));
    }
    if (designLoops?.skipped.length) {
      loopNote.append(el("p", { class: "hint" },
        `문서 게인으로 세우지 않은 루프: ${designLoops.skipped.map((k) => `${k.name} — ${k.reason}`).join(" · ")}`));
    }
  };
  // 카탈로그 → (확정 표가 있고 낡지 않았으면) 같은 리비전 문서의 확정 표 → 출처. 확정 표 값은 카탈로그에 없다
  // (자리 이름·낡음만) — 게인 탭 결함 주입 기준(faultBase)과 같은 문서 읽기다
  const loadSources = async () => {
    const cat = await api.get("/gains/catalog");
    let tables = null;
    if (cat?.confirmed && cat.confirmed.stale !== true) {
      const p = cat.profile ?? {};
      const id = p.id ?? currentSelection()?.id ?? EXAMPLE_ID;
      const rev = typeof p.revision === "number" ? `?revision=${p.revision}` : "";
      const body = await api.get(`/profiles/${encodeURIComponent(id)}${rev}`);
      tables = effectiveOf(body?.document, p.variant ?? null)?.law?.gain_tables?.tables ?? null;
    }
    return loopGainSources(cat, tables);
  };
  const loopsReady = loadSources().then(
    (src) => ({ src }),
    (e) => ({ error: e }),
  ).then((r) => {
    if (visit !== marginsVisit) return; // 버려진 화면의 늦은 응답 — 새 화면이 자기 것을 받는다
    if (r.error) {
      gainSources = { error: r.error };
      designLoops = { rows: [], skipped: [], error: r.error };
      // 문서 게인이 없다 — 손대지 않은 행은 빠지고 손댄 행만 남는다
      const next = followDocRows(loopRows, [], removedDocLoops);
      if (next.length !== loopRows.length) {
        loopRows = next;
        renderLoopEditor(loopBox);
        drawers.refresh();
      }
      paintLoopNote();
      return;
    }
    gainSources = r.src;
    refreshDocLoops();
  });

  const showErr = (e) =>
    clear(errBox).append(el("div", { class: "error-box" }, errorText(e)));

  // 판정선 한 줄 — 고른 기체의 기준(applied.margin + lines)에서. 칸 색은 서버 판정이라 이 조회가 실패해도 색은
  // 그대로다 — 실패하면 판정선 수치만 못 적는다는 사실을 밝힌다(수치를 지어내지 않는다)
  const selId = () => currentSelection()?.id ?? EXAMPLE_ID;
  const criteriaBox = el("p", { class: "tab-status" }, "판정선 불러오는 중… (기체 평가 기준)");
  const drawCriteria = () => {
    clear(criteriaBox).append(
      marginLegendText(criteria),
      criteria
        ? ` — 기체 ${criteriaFor}의 평가 기준(${criteria?.echo?.source === "profile" ? "문서" : "도구 기본값"})`
        : ` — 기체 평가 기준 조회 실패로 판정선 수치는 적지 못한다 (${criteriaErr}). 칸 색은 서버 판정 그대로다.`,
    );
  };

  const loadCriteria = async () => {
    const id = selId();
    try {
      const d = await api.get(`/profiles/${encodeURIComponent(id)}/criteria`);
      if (visit !== marginsVisit) return; // 버려진 화면의 늦은 응답
      criteria = d?.applied?.margin && Array.isArray(d?.lines) ? d : null;
      criteriaErr = criteria ? null : "응답에 applied.margin·lines가 없다";
      // 같은 기체로 계산한 결과가 있으면 그 대조 재료로도 쓴다(중복 조회 방지). 받는 중인 조회는 스스로 다시 그린다
      if (!resultCritCache.has(id)) resultCritCache.set(id, { resp: d ?? null });
    } catch (e) {
      if (visit !== marginsVisit) return;
      criteria = null;
      criteriaErr = errorText(e);
    }
    criteriaFor = id;
    // 범례만 — 히트맵 제목의 판정선·「기준 다름」은 결과를 계산한 기체의 기준이라(resultCriteriaOf) 여기서 다시 그리지 않는다
    drawCriteria();
  };

  const watch = () => {
    const mine = ++watchSeq;
    attachProgress(progressBox, runningJobId, {
      onDone: async (job) => {
        // 재진입이 감시자를 새로 붙였으면 이 감시자는 버려진 화면의 것이다 — 결과·신호·보드선도는 새 감시자가 맡는다
        if (mine !== watchSeq) return;
        runningJobId = null;
        // 신호는 한 번만 — 잡이 끝난 뒤의 보고는 store에만 쓰므로 떠난 화면이어도 보낸다(그 뒤로 붙은 감시자가 없으면)
        const cue = marginCue;
        marginCue = null;
        // 이 잡의 게인 기록(제출 시점) — 결과를 받는 사이 새 제출이 runningGains를 덮을 수 있어 먼저 잡아 둔다
        const gains = runningGains;
        const delaySrc = runningDelaySrc;
        try {
          if (job.status === "error") throw new Error(job.error);
          if (cancelledWithoutResult(job)) {
            showErr(new Error("취소됨 — 저장된 결과 없음 (실행 전 취소)"));
            failCue(cue, "취소됨 — 저장된 결과 없음 (실행 전 취소)");
            return;
          }
          const body = await api.get(`/results/${job.result_id}`);
          lastBody = body;
          lastGains = gains; // 결과와 짝 — 캡션·칸별 보드선도 주석이 이 실행이 쓴 게인을 말한다
          lastDelaySrc = delaySrc;
          const shown = renderResults(slots, lastBody);
          // refresh(칩만)가 아니라 repaint — 패널이 열린 채였다면 "실행 후 표시됩니다"
          // 줄이 방금 채워진 캔버스 밑에 그대로 남는다
          drawers.repaint();
          // 손으로 누른 실행은 굴리지 않는다 — 결과는 **전면**이라 히트맵이 화면 위쪽에 온다. 진행기 신호는 아래에서
          // 최악 칸의 보드선도(히트맵 밑)를 화면 안으로 굴린다(e2e D4)
          if (!cue) return;
          if (job.status === "cancelled") {
            failCue(cue, `취소됨 — 완료분 ${lastBody.cases.length}케이스만 저장`);
            return;
          }
          // 최악 칸의 보드선도를 연다 — 청중이 「어디가 얇은가」와 그 곡선을 함께 본다. 이 루프를 닫은 폐루프가 발산하는
          // 칸이 있으면 그것이 먼저다(수가 좋아 보여도 여유가 아니다). 최악 PM·GM은 안정 칸의 여유끼리 비교한다
          const loops = loopsOf(lastBody);
          const bad = unstableCells(lastBody.cases, loops);
          const worst = marginWorst(stableMarginEntries(lastBody.cases), loops);
          const target = bad[0] ?? worst.pm;
          const box = target ? await shown.focus(target.loop, target.entry) : null;
          revealPanel(box ?? slots.plots); // 떠난 화면(떨어진 노드)이면 굴리지 않는다
          // 보고 꼬리에 루프 게인 출처 — 이 맵이 어느 게인으로 잰 것이고 몇 칸이 그 칸의 실제 게인인가(탭 캡션과 같은
          // 기록). 칸별 법칙 게인은 서버가 실제로 쓴 게인 기록(결과의 profile_gains·entry.gains)으로 말한다
          const rep = marginsCueReport(worst, fqWorst(lastBody.cases));
          const law = lawGainRecord(lastBody);
          const tag = gainSummaryTag(gains, law);
          reportCue(cue, { phase: "done", resultId: job.result_id,
            summary: [unstableTail(bad), rep.summary, tag].filter(Boolean).join(" · "), // 발산이 먼저 — 진행기가 긴 줄을 자른다
            data: { ...rep.data,
              unstable: bad.map((c) => ({ loop: c.loop, case: c.entry.trim.case.name, poles: c.poles })),
              gains: gainCueData(gains, law) } });
        } catch (e) {
          showErr(e);
          failCue(cue, cueReason(e));
        }
      },
      onError: (e) => {
        if (mine !== watchSeq) return; // 위와 같다 — 새 감시자가 같은 잡의 끝을 받는다
        runningJobId = null;
        showErr(e);
        const cue = marginCue;
        marginCue = null;
        failCue(cue, cueReason(e));
      },
    });
  };

  // 잡 걸기 — 걸었으면 null, 못 걸었으면 사유. cue가 오면 잡이 끝날 때 그 신호로 보고한다
  const run = async (cue = null) => {
    if (runningJobId || submitting) { // 이중 제출 방지 (리뷰 S4) — 무반응 대신 안내 (조용한 무시 금지)
      clear(errBox).append(el("div", { class: "error-box" },
        "이미 실행 중입니다 — 진행률 표시를 확인하세요."));
      return "이미 실행 중인 마진 맵이 있다 — 끝난 뒤 다시 건다";
    }
    submitting = true;
    try {
      clear(errBox);
      // 문서 게인 출처를 아직 못 받았으면 받은 뒤에 건다 — 그대로 걸면 루프 0개(고유치만) 맵이 조용히 돈다(round1 #5)
      if (loopLoadState(gainSources) === "loading") {
        clear(errBox).append(el("p", { class: "hint" }, LOOPS_LOADING_TEXT));
        await loopsReady;
        clear(errBox);
        if (visit !== marginsVisit) return "문서 게인을 받는 사이 탭이 다시 그려졌다 — 다시 누른다";
        if (loopLoadState(gainSources) === "loading") return "문서 게인을 받지 못했다 — 다시 누른다";
      }
      // 점은 고르개의 선택(기본 = 보낼 점 전부) — 이름은 서버(엔진 case_name)가 값 그대로 지은 것이라 트림 탭·영향성과
      // 같은 점이 같은 이름이다. 받는 중·요구 미정의·0점이면 던진다(아래 catch가 사유를 화면·신호에 싣는다)
      const cases = picker.selectedCases();
      // 손대지 않은 루프는 **지금 격자**의 점에서 문서 게인을 다시 읽는다 — 격자를 고친 뒤 옛 가운데 마하의 게인으로
      // 재지 않게. 점을 못 정하면(「게인 읽을 마하」 오타) 제출하지 않는다
      const refErr = refreshDocLoops();
      const v = validateLoops(loopRows);
      const ad = validateActuatorDelay({
        useActuator: fUseAct.checked, wn: fWn.value, zeta: fZeta.value,
        useDelay: fUseDelay.checked, delaySeconds: fDelay.value, padeOrder: fPade.value,
      });
      const errs = [...(refErr ? [refErr] : []), ...(v.errors ?? []), ...(ad.errors ?? [])];
      if (errs.length) {
        clear(errBox).append(el("div", { class: "error-box" }, errs.join("\n")));
        return errs.join(" · ");
      }
      for (const slot of Object.values(slots)) clear(slot);
      // 이 실행의 게인 기록 — 제출하는 행 그대로(사본)와 같은 점의 문서 게인 행을 대조해 굳힌다. 확정 표가 낡지 않았으면
      // 손대지 않은 문서 게인 루프는 칸별(서버가 칸마다 법칙에서 읽는다 — kp를 싣지 않는다), 손댄 루프는 적은 kp 그대로
      const sources = gainSources?.error ? null : gainSources;
      const gains = runGainInfo(sources, loopRows.map((r) => ({ ...r })),
        designLoops?.rows ?? [], refPoint(), cases, lawGainsPerCase(sources));
      const req = {
        cases, loops: requestLoops(v.loops, gains.perCase ? gains.loops.map((l) => l.name) : []),
        fingerprint: fFp.value, actuator: ad.actuator, delay_s: ad.delay_s, pade_order: ad.pade_order,
      };
      const submitted = await api.post("/analysis/margin-map", req);
      runningJobId = submitted.id;
      runningGains = gains;
      runningDelaySrc = delaySourceText(ad);
      if (cue) {
        marginCue = cue;
        reportCue(cue, { phase: "started", jobId: submitted.id });
      }
      watch();
      return null;
    } catch (e) {
      showErr(e);
      return cueReason(e);
    } finally {
      submitting = false;
    }
  };

  let submitting = false; // 문서 게인을 기다리며 제출 중 — 그사이 한 번 더 누르면 두 번 걸린다
  renderLoopEditor(loopBox);
  paintLoopNote();

  // [실행] — 요구영역이 미정의면 누를 수 없다(사유는 툴팁·고르개 요약). 템플릿 격자로 되돌아가 돌지 않는다
  // 인자 없이 부른다 — run(cue)에 클릭 이벤트가 들어가면 신호로 읽혀 가짜 보고(token 없음)를 store에 쓰고
  // 최악 칸 보드선도를 멋대로 연다
  const runBtn = el("button", { class: "primary", onclick: () => run() }, "실행");
  const paintRunBtn = () => {
    const g = picker.grid();
    const blocked = g && !g.region ? `요구영역 미정의 — ${g.reason}` : null;
    runBtn.disabled = Boolean(blocked);
    runBtn.title = blocked ?? "";
  };

  const drawers = createDrawers({
    id: "margins-drawer",
    initial: openDrawer,
    onOpen: (k) => { openDrawer = k; },
    defs: [
      { key: "grid", label: "계보", group: "입력",
        title: "결과에 남길 지문 — 점은 위 「비행조건」(요구영역 기본 격자)에서 고른다",
        build: () => [
          el("h2", {}, "계보"),
          el("div", { class: "row" },
            el("label", { class: "field" }, "지문", fFp)),
          el("p", { class: "hint" },
            "점은 요구영역의 기본 격자다 — 트림 탭 「운용영역·기본 격자」가 정한다. "
            + "스케줄 절점 사이까지 보려면 그 명세의 마하 점 수를 늘린다."),
        ] },
      { key: "loops", label: "개루프 정의", group: "입력",
        title: "축·출력 상태·입력·kp·ki·sign — 서버 loops[] 계약 그대로",
        count: () => loopRows.length,
        build: () => [
          el("h2", {}, "PI 개루프 (다중)"),
          el("div", { class: "row" },
            el("label", { class: "field" }, "게인 읽을 마하", fRefMach)),
          loopNote,
          loopBox,
          el("p", { class: "hint" },
            "트림 → 선형화 → 모드 분류 → 루프별 sign·PI·G(x_out←u_in) 마진 (엔진 M9·M10) — 같은 축의 나머지 루프는 "
            + "닫고 그 루프를 끊어 잰다(AS94900의 끊는 자리). "
            + "루프를 전부 지우면 고유치·감쇠비만 계산. 3축 레이트 루프는 고른 기체가 실제로 나는 k_rate로 선다 — "
            + "문서 확정 게인 표가 있으면 그 표, 없으면 규칙 스케줄. 손대지 않은 루프는 실행 때 서버가 칸마다 그 칸의 "
            + "게인을 읽어 전 칸이 정확하다(표의 kp 칸은 「게인 읽을 마하」의 값 — 비우면 고른 점의 가운데). kp를 고친 루프는 "
            + "그 한 값으로 전 칸을 잰다. 확정 게인 표가 낡았으면 칸별로 못 읽어 한 값을 싣고, 다른 마하 열은 근사다."),
        ] },
      { key: "plant", label: "작동기·지연", group: "입력",
        title: "미포함 마진은 낙관적 — 체크 해제로 영향 분리 비교",
        build: () => [
          el("h2", {}, "플랜트에 무엇을 포함할 것인가"),
          el("div", { class: "field-grid" },
            el("div", { class: "opt-group" },
              el("div", { class: "g-title" }, "작동기 포함 (2차계 — plant.actuator와 동일 모델)"),
              el("div", { class: "row-inner" },
                el("label", { class: "field check" }, fUseAct, "포함"),
                el("label", { class: "field" }, "wn [rad/s]", fWn),
                el("label", { class: "field" }, "ζ", fZeta))),
            el("div", { class: "opt-group" },
              el("div", { class: "g-title" }, "지연 포함 (항법 출력 + 제어주기 — Padé 근사)"),
              el("div", { class: "row-inner" },
                el("label", { class: "field check" }, fUseDelay, "포함"),
                el("label", { class: "field" }, "총 지연 [s]", fDelay),
                el("label", { class: "field" }, "Padé 차수", fPade)))),
          el("p", { class: "hint" },
            "작동기·지연 미포함 마진은 낙관적 (01 §4.2) — 기본은 포함, 체크 해제로 영향 "
            + "분리 비교. 작동기 wn·ζ는 고른 기체 문서(actuator)에서 채운다. 지연 칸의 처음 값 "
            + `${DELAY_TOOL_DEFAULT.delay_s} s·Padé ${DELAY_TOOL_DEFAULT.pade_order}차는 툴 기본값이다 — 기체 문서에 `
            + "지연 칸이 없어 기체별 값이 아니다(엔진 항법 오차 모델의 기본 출력 지연 0.03 s + 기본 제어주기 "
            + "100 Hz의 반주기 등가지연 0.005 s). 기체의 센서·연산 지연을 알면 고쳐 넣는다."),
        ] },
      { key: "eig", label: "고유치 맵", group: "결과",
        title: "전 케이스의 모드를 한 복소평면에 — 허수축 좌측이 안정",
        build: () => [
          el("h2", {}, "고유치 맵"),
          slots.eig,
          lastBody ? null : el("p", { class: "hint" }, "실행 후 표시됩니다."),
        ] },
      { key: "damp", label: "감쇠비·모드 표", group: "결과",
        title: "케이스별 모드 ω_n·ζ + 비행성 수준(1/2/3) — 어느 점의 어느 모드가 얇은가",
        build: () => [
          el("h2", {}, "모드별 감쇠비"),
          slots.damp,
          lastBody ? null : el("p", { class: "hint" }, "실행 후 표시됩니다."),
        ] },
    ],
  });

  const root = el("div", { class: "tab-page" },
    tabTop({
      title: "마진 맵",
      lead: "요구영역 기본 격자의 점마다 선형화해 개루프 마진을 잰다 — 설계점만이 아니라 그 사이까지 "
        + "훑어야 스케줄 경계에서 마진이 꺼지는 곳이 보인다. 루프·조건은 아래 패널에.",
      actions: [runBtn],
      // 판정선은 **패널에 넣지 않는다** — 히트맵 색이 무엇을 기준으로 갈리는지이고,
      // 폴백을 쓰는 중이라면 그 사실이 색과 같은 화면에 있어야 한다
      extra: [criteriaBox, picker.el, progressBox, errBox],
    }),
    // PM·GM 히트맵 — 카드 밖, 페이지 위에 그대로. 이 탭의 답이 여기 있다
    tabStage(slots.head, slots.plots),
    drawers.root,
  );
  if (lastBody) renderResults(slots, lastBody);
  else {
    clear(slots.head).append(el("p", { class: "hint" },
      "아직 실행하지 않았습니다 — [실행]을 누르면 격자 점마다 트림·선형화를 거쳐 "
      + "루프별 위상여유(PM)·이득여유(GM) 히트맵이 여기 그려집니다. "
      + "칸을 누르면 그 점의 보드선도가 열립니다."));
  }
  if (runningJobId) watch(); // 실행 중 재진입 — 진행 UI 재부착 (리뷰 S4)
  if (criteria && criteriaFor === selId()) drawCriteria(); // 받아 둔 것을 먼저 보이고, 기준 편집을 따라 다시 받는다
  loadCriteria();
  // 고르개가 바뀌면 — [실행] 막힘과 손대지 않은 루프의 게인(가운데 점이 바뀐다). 들어올 때마다 요구영역의 기본 격자를
  // 다시 받는다(그사이 요구영역을 고쳤으면 새 점을 따른다 — 고른 점은 이름으로 남는다)
  onCondChange = () => {
    paintRunBtn();
    refreshDocLoops();
  };
  paintRunBtn();
  picker.refresh();

  // 쇼케이스 신호 — 비행조건은 기본 격자의 보낼 점 전부, 루프는 문서 게인(서버가 칸마다 읽는 법칙 게인 — 편집 표는 가운데 마하 값),
  // 작동기는 문서 값으로 세운 뒤(손댄 칸도 — 진행기는 「문서의 기체」를 잰다) [실행]과 같은 길로. 요구영역·게인이
  // 없으면 예제 값으로 돌리지 않고 사유를 단다
  const handleCue = async (c) => {
    try {
      if (c.action !== "run") {
        unknownAction(c);
        return;
      }
      const [d] = await Promise.all([defaultsReady, loopsReady]);
      // 기다리는 사이 탭이 다시 그려졌으면 이 화면은 버려졌다 — 여기서 잡을 걸면 새 화면엔 감시자도 보드선도도 없다
      if (visit !== marginsVisit) throw new Error("신호를 처리하기 전에 탭이 다시 그려졌다");
      if (!d) throw new Error(DOC_FAILED_HINT);
      if (gainSources?.error) throw new Error(`문서 게인을 받지 못했다 — ${cueReason(gainSources.error)}`);
      // 비행조건은 손대지 않은 상태(보낼 점 전부)로 되돌리고 지금 요구영역의 격자를 다시 받는다 — 진행기는 「문서의
      // 기체」를 잰다. 요구영역이 미정의면 템플릿 격자로 돌지 않고 사유를 단다
      picker.reset();
      const g = await picker.latest();
      if (visit !== marginsVisit) throw new Error("신호를 처리하기 전에 탭이 다시 그려졌다");
      if (g.status !== "ok") throw new Error(g.reason);
      if (d.margins.wn) fWn.value = d.margins.wn;
      if (d.margins.zeta) fZeta.value = d.margins.zeta;
      // 손댄 「게인 읽을 마하」·루프도 문서 게인으로 되돌린다(편집 표는 고른 점 가운데 마하 값 — 실행은 칸별)
      refMachText = "";
      fRefMach.value = "";
      const refErr = refreshDocLoops({ force: true });
      if (refErr) throw new Error(refErr);
      if (!loopRows.length) throw new Error("문서 게인으로 설 루프가 없다 — 레이트 게인 k_rate가 전부 0이다");
      const err = await run(c); // 끝 보고는 잡 감시(watch)가 한다
      if (err) throw new Error(err);
    } catch (e) {
      failCue(c, cueReason(e));
    }
  };
  const cue = takeCue("margins");
  if (cue) handleCue(cue);
  return root;
}

// ── 루프 스펙 편집 표 ──────────────────────────────────────────────────

function renderLoopEditor(loopBox) {
  // 칸을 고친 행은 touched — 그 행만 문서 게인을 따라가지 않는다(lib/loops.js followDocRows)
  const numCell = (row, key) => el("input", {
    class: "num-sm", value: String(row[key]),
    oninput: (ev) => { row[key] = ev.target.value; row.touched = true; },
  });
  const nameSel = (row, key, names) => el("select", {
    onchange: (ev) => { row[key] = ev.target.value; row.touched = true; },
  }, names.map((n) => el("option", { value: n, selected: n === row[key] }, n)));

  const rowTr = (row) => {
    // 축 변경 시 상태·입력 선택지를 그 축 이름으로 재구성 (기존 값 무효 시 첫 항목)
    const xTd = el("td");
    const uTd = el("td");
    const fillSelects = () => {
      const ax = AXIS_NAMES[row.axis];
      if (!ax.states.includes(row.x_out)) row.x_out = ax.states[0];
      if (!ax.inputs.includes(row.u_in)) row.u_in = ax.inputs[0];
      clear(xTd).append(nameSel(row, "x_out", ax.states));
      clear(uTd).append(nameSel(row, "u_in", ax.inputs));
    };
    fillSelects();
    return el("tr", {},
      el("td", {}, el("input", {
        style: "width: 110px", value: row.name,
        oninput: (ev) => { row.name = ev.target.value; row.touched = true; },
      })),
      el("td", {}, el("select", {
        onchange: (ev) => { row.axis = ev.target.value; row.touched = true; fillSelects(); },
      }, ["lon", "lat"].map((a) =>
        el("option", { value: a, selected: a === row.axis }, a === "lon" ? "종축 (lon)" : "횡축 (lat)")))),
      xTd, uTd,
      el("td", {}, numCell(row, "kp")),
      el("td", {}, numCell(row, "ki")),
      el("td", {}, numCell(row, "sign")),
      el("td", {}, el("button", {
        class: "danger",
        onclick: () => {
          loopRows = loopRows.filter((r) => r !== row);
          // 문서 루프를 지웠으면 문서 게인을 다시 읽어도 되살리지 않는다
          if (!removedDocLoops.includes(row.name)) removedDocLoops = [...removedDocLoops, row.name];
          renderLoopEditor(loopBox);
        },
      }, "삭제")),
    );
  };

  clear(loopBox).append(
    el("div", { class: "scroll-x", style: "margin-top: 10px" }, el("table", {},
      el("thead", {}, el("tr", {},
        el("th", {}, "루프 이름"), el("th", {}, "축"), el("th", {}, "출력 상태"),
        el("th", {}, "입력"), el("th", {}, "kp"), el("th", {}, "ki"),
        el("th", {}, "sign"), el("th", {}, ""))),
      el("tbody", {}, loopRows.map(rowTr)))),
    el("div", { class: "row", style: "margin-top: 8px" },
      el("button", {
        onclick: () => {
          let i = loopRows.length + 1; // 삭제 후 추가해도 유일 이름 (리뷰 사소)
          while (loopRows.some((r) => r.name === `loop_${i}`)) i += 1;
          loopRows.push({
            name: `loop_${i}`, axis: "lon", x_out: "q", u_in: "de",
            kp: "0.5", ki: "0", sign: "-1", touched: true, // 문서 루프가 아니다 — 문서 게인을 따라가지 않는다
          });
          renderLoopEditor(loopBox);
        },
      }, "루프 추가"),
      el("button", {
        title: "고른 기체가 「게인 읽을 마하」에서 실제로 나는 k_rate로 3축 레이트 루프를 다시 세운다",
        onclick: () => {
          loopRows = (designLoops?.rows ?? []).map((r) => ({ ...r }));
          removedDocLoops = [];
          renderLoopEditor(loopBox);
        },
      }, "문서 게인으로 복원"),
    ),
  );
}

// ── 결과 대시보드 ──────────────────────────────────────────────────────

/** 결과에 포함된 루프 스펙 — 저장 결과의 loops가 정본 (재열람 시 폼 상태와 무관).
구형 결과 폴백: 케이스 margins 키에서 이름만 복원. */
function loopsOf(body) {
  if (body.loops?.length) return body.loops;
  const withMargins = (body.cases ?? []).find((e) => Object.keys(e.margins ?? {}).length);
  return Object.keys(withMargins?.margins ?? {}).map((name) => ({ name }));
}

/** 저장 결과의 작동기·지연 적용값 요약 — 재열람 시 현재 폼 상태와 무관하게
그 결과가 실제로 무엇을 포함해 계산됐는지 확인 (구형 결과는 필드 자체가 없음). */
function appliedSummary(body, delaySrc = null) {
  const act = body.actuator
    ? `작동기 포함 (wn=${body.actuator.wn} rad/s, ζ=${body.actuator.zeta})`
    : "작동기 미포함";
  // 지연 출처는 제출한 이 화면만 안다(결과 본문엔 수치뿐) — 다시 연 결과엔 수치만 낸다
  const delay = body.delay_s > 0
    ? `지연 포함 (${body.delay_s} s, Padé ${body.pade_order}차${delaySrc ? ` · ${delaySrc}` : ""})`
    : "지연 미포함";
  return `${act} · ${delay}`;
}

/** 결과를 네 슬롯에 나눠 그린다 — 어디에 놓을지는 부르는 쪽이 정한다.
 *  slots: {head, plots, eig, damp}. 연료를 바꾸면 네 슬롯이 함께 다시 그려진다
 *  (한 슬롯만 갱신하면 히트맵과 감쇠비 표가 서로 다른 연료를 말하게 된다). */
function renderResults(slots, body) {
  const entries = body.cases;
  const loops = loopsOf(body);
  // 이 결과를 잰 루프 게인의 기록(제출 시점) — 라벨 꼬리표·출처 캡션·칸별 보드선도 주석
  const gainsInfo = lastBody === body ? lastGains : null;
  // 서버가 칸마다 법칙에서 읽은 게인의 기록(법칙 게인 루프가 있는 결과만) — 칸별 루프의 범위·출처는 이것이 정본
  const law = lawGainRecord(body);
  const fuels = fuelsOf(entries);
  const fuelSel = el("select", { "aria-label": "연료 선택" },
    fuels.map((f) => el("option", { value: f }, `연료 ${f} kg`)));
  const plotBox = el("div");
  const HEAT_W = 560; // heatmapCanvas 기본 폭 — 클릭 역매핑이 같은 값을 써야 한다

  /** 히트맵 칸 클릭 → 그 운용점·그 루프의 보드선도. GM·PM이 주파수축 어디에
   * 있는지는 히트맵 두 장으로는 원리적으로 안 보인다 (01 §4.2).
   * bodeSeq(늦게 도착한 응답 폐기)는 모듈 스코프 — 머리말 참조. */
  // 루프 구간마다 상세 슬롯 — 보드선도는 **누른 칸 바로 밑**에 연다. 종전처럼
  // 대시보드 맨 아래 한 자리에 열면 위쪽 루프를 누른 사람은 히트맵과 곡선을 나란히
  // 못 보고 화면 밖으로 스크롤해야 했다 (사용자 제기). draw()마다 새로 만든다.
  // **키는 이름이 아니라 루프 객체**다 — 이름은 서버 echo라 유일성 보장이 없고,
  // 겹치면 위 루프를 눌렀는데 아래 루프 자리에 곡선이 열린다
  let detailBoxes = new Map();
  /** 모든 슬롯을 비우고 그 루프의 슬롯을 돌려준다 — 한 번에 하나만 연다
   * (루프마다 남겨 두면 어느 것이 방금 누른 것인지 흐려진다). */
  const slotFor = (lp) => {
    for (const b of detailBoxes.values()) clear(b);
    return detailBoxes.get(lp) ?? null;
  };
  /** 계산 없이 사유만 내는 자리 — bodeSeq를 올려 **진행 중인 요청이 이 문장을
   * 덮지 않게** 한다. 안 올리면 미수렴 칸을 누른 직후 앞서 보낸 응답이 도착해
   * 사유를 지우고 남의 칸 곡선을 그린다. */
  const showNote = (lp, node) => {
    bodeSeq += 1;
    slotFor(lp)?.append(node);
  };
  const openBode = async (lp, entry) => {
    const seq = ++bodeSeq;
    const box = slotFor(lp);
    if (!box) return; // 그사이 다시 그려져 슬롯이 사라졌다
    box.append(el("p", { class: "hint" },
      `보드선도 계산 중 — ${entry.trim.case.name} · ${lp.name}`));
    try {
      const res = await api.post("/analysis/bode", {
        case: entry.trim.case, loop: lp,
        // 칸이 닫아 둔 같은 축의 루프(closed_with)를 그대로 — 곡선이 칸과 같은 조립이어야 같은 수다
        others: bodeOthers(loops, entry.margins?.[lp.name]),
        actuator: lastBody.actuator ?? null,
        delay_s: lastBody.delay_s ?? 0.0,
        pade_order: lastBody.pade_order ?? 2,
        // 이 칸의 트림 해를 씨앗으로 — 마진 맵은 웜스타트로 풀었으므로 냉간으로
        // 다시 풀면 다른 선형화점에 앉아 곡선과 칸이 어긋난다(칸은 수렴인데
        // 보드만 422가 나기도 한다). 수평비행 트림은 θ = α라 euler[1]이 α다
        z0: [entry.trim.euler[1], entry.trim.control.elevon[0], entry.trim.control.throttle[0]],
      });
      if (seq !== bodeSeq) return; // 그사이 다른 칸을 눌렀다 — 옛 응답을 버린다
      // 이 칸에서 기체가 실제로 나는 게인이 맵의 kp와 다르면 그 사실을 곡선 밑에 — 한 kp 요청의 근사를 칸에서 말한다.
      // 법칙 게인 루프는 서버가 이 칸의 게인으로 그렸다 — 그 값을 곡선 밑에(bodeLawGainNote)
      renderBode(box, lp, entry, res, cellGainNote(gainsInfo, lp.name, entry.trim.case, lp.kp), bodeLawGainNote(res));
    } catch (e) {
      if (seq !== bodeSeq) return;
      clear(box).append(el("div", { class: "error-box" }, errorText(e)));
    }
  };

  /** 캔버스에 클릭·커서를 붙인다 — 좌표 변환은 lib/wpmap.js toCanvasXY(CSS 축소 보정). */
  const wireCells = (canvas, pivot, lp) => {
    const hitAt = (ev) => {
      // 논리 크기를 넘긴다 — clientHeight(축소된 렌더 높이)를 넘기면 y 배율이
      // 1이 되어 좁은 화면에서 세로 좌표가 안 풀린다
      const { x, y } = toCanvasXY(ev.clientX, ev.clientY,
        canvas.getBoundingClientRect(), HEAT_W, heatmapCanvasHeight(pivot.alts.length));
      return heatmapCellAt(pivot, x, y, { width: HEAT_W });
    };
    canvas.addEventListener("pointermove", (ev) => {
      const hit = hitAt(ev);
      canvas.style.cursor = hit && hit.entry ? "pointer" : "default";
    });
    canvas.addEventListener("click", (ev) => {
      const hit = hitAt(ev);
      if (!hit || !hit.entry) return; // 여백·격자 밖 — 가까운 칸으로 끌어붙이지 않는다
      // 열려 있던 슬롯이 **이 캔버스보다 위**에 있으면 비우는 순간 그만큼 페이지가
      // 위로 밀려 방금 누른 히트맵이 손가락 밑에서 튄다(상세 높이가 노트북 한 화면쯤
      // 된다). Chrome·Firefox는 scroll anchoring이 흡수하지만 Safari에는 없다 —
      // 눌린 자리를 화면상 제자리에 붙들어 둔다
      const top0 = canvas.getBoundingClientRect().top;
      const keepAnchored = () => {
        const d = canvas.getBoundingClientRect().top - top0;
        if (d) window.scrollBy(0, d);
      };
      if (!hit.entry.trim.converged) {
        showNote(lp, el("p", { class: "hint" },
          `${hit.entry.trim.case.name}: 트림 미수렴이라 선형화점이 없습니다 — 보드선도를 낼 수 없습니다.`));
        keepAnchored();
        return;
      }
      if (!hit.entry.margins?.[lp.name]) {
        // 이 루프의 마진이 없는 칸(해석 실패로 회색) — 열어 봐야 서버도 같은
        // 이유로 못 푼다. 색칠된 칸만 열린다는 약속을 여기서 지킨다
        showNote(lp, el("p", { class: "hint" },
          `${hit.entry.trim.case.name}: 이 루프의 마진이 없는 칸입니다`
          + (hit.entry.note ? ` — ${hit.entry.note}` : " (해석 실패)")));
        keepAnchored();
        return;
      }
      if (!lp.x_out) { // 구버전 결과(loopsOf 폴백) — 루프 스펙이 없어 재조립 불가
        showNote(lp, el("p", { class: "hint" },
          "이 결과에는 루프 스펙이 저장돼 있지 않아(구버전) 보드선도를 낼 수 없습니다 — 다시 실행하세요."));
        keepAnchored();
        return;
      }
      openBode(lp, hit.entry); // 동기 구간(슬롯 비우기 + "계산 중")까지 끝난 뒤 보정
      keepAnchored();
    });
  };

  const draw = () => {
    // 칸 색은 결과에 실린 서버 판정(lib/plot.js marginCellStatus). 판정선은 제목에만 — **이 결과를 계산한 기체**의
    // 기준에서(지금 고른 기체가 아니다). 기준이 뒤늦게 오면 다시 그린다
    // 단, 보드선도가 열려 있거나 요청 중이면(슬롯에 「계산 중」·곡선이 있다) 다시 그리지 않는다 — draw가 bodeSeq를
    // 올리고 슬롯을 새로 만들어 그 상세를 조용히 버린다(리뷰 지적). 제목의 판정선은 다음 그리기에 맞춰진다
    redrawResult = () => {
      if (!plotBox.isConnected) return;
      if ([...detailBoxes.values()].some((b) => b.childNodes.length > 0)) return;
      draw();
    };
    const rc = resultCriteriaOf(body);
    const pmLine = criteriaLineText(rc.resp, "pm_deg");
    const gmLine = criteriaLineText(rc.resp, "gm_db");
    // 결과 기준 ↔ 그 기체의 지금 기준 — 공용 대조기(lib/freshness.js). 받는 중엔 말하지 않는다
    const critState = rc.ready ? criteriaFreshness(body.criteria_echo, rc.resp?.echo ?? null, "margin_map") : "fresh";
    const critSpec = criteriaBadgeSpec(critState);
    const resultPid = body?.profile?.id ?? null;
    const selPid = currentSelection()?.id ?? EXAMPLE_ID;
    const fuel = Number(fuelSel.value);
    const pivot = pivotCases(entries, fuel);
    // 연료가 바뀌면 다른 격자다 — 옛 상세도, **진행 중인 요청도** 무효다
    bodeSeq += 1;
    detailBoxes = new Map(); // 슬롯도 새로 만든다 (옛 노드는 곧 버려진다)
    const loopPlots = loops.flatMap((lp) => {
      // 게인도 라벨에 싣는다 — 이 칸들이 **어느 게인으로** 잰 마진인지(문서 설계값이 바뀌면 같은 이름의 다른 루프다)
      // 출처 꼬리표도 — 확정 표·규칙 스케줄을 어느 마하에서 읽었나, 손으로 적은 값인가 (lib/loops.js loopKpTag)
      const tag = loopKpTag(gainsInfo, lp.name, law);
      // 법칙 게인 루프는 kp가 칸마다 다르다 — 격자 범위(서버 기록)를 싣는다
      const lawKp = lp.gain_source === "profile" ? lawKpText(law, lp.name) : null;
      const gains = typeof lp.kp === "number"
        ? ` · kp ${fmt(lp.kp, 4)}${lp.ki ? ` · ki ${fmt(lp.ki, 4)}` : ""}${tag ? ` (${tag})` : ""}`
        : lawKp ? ` · kp ${lawKp}${tag ? ` (${tag})` : ""}` : "";
      const label = lp.x_out
        ? `${lp.name} — ${lp.sign < 0 ? "−" : "+"}PI·G(${lp.x_out} ← ${lp.u_in}) [${lp.axis}]${gains}`
        : lp.name;
      // 칸의 수는 나이퀴스트 여유(−1까지의 거리 — 엔진 nyquist_margins). 이 루프를 닫은 폐루프가 발산하는 칸은 글이
      // 「발산」(lib/loops.js marginCellView)이고, 색은 다른 칸처럼 서버 판정 — 서버가 발산을 판정에 접어 넣는다
      const pmCanvas = heatmapCanvas(pivot, (e) => {
        if (!e.trim.converged) return { color: STATUS.na, text: "트림×" };
        const v = marginCellView(e.margins[lp.name], "pm_deg");
        return v ? { color: statusColor(marginCellStatus(e.margins[lp.name], "pm_deg")), text: v.text }
          : { color: STATUS.na, text: "—" };
      }, { title: `위상여유 PM [deg] — ${lp.name}${pmLine ? ` (${pmLine})` : ""}`, width: HEAT_W });
      const gmCanvas = heatmapCanvas(pivot, (e) => {
        if (!e.trim.converged) return { color: STATUS.na, text: "트림×" };
        const v = marginCellView(e.margins[lp.name], "gm_db");
        return v ? { color: statusColor(marginCellStatus(e.margins[lp.name], "gm_db")), text: v.text }
          : { color: STATUS.na, text: "—" };
      }, { title: `이득여유 GM [dB] — ${lp.name}${gmLine ? ` (${gmLine})` : ""}`, width: HEAT_W });
      // PM·GM 두 장 다 같은 루프의 같은 칸이므로 어느 쪽을 눌러도 같은 선도가 뜬다
      wireCells(pmCanvas, pivot, lp);
      wireCells(gmCanvas, pivot, lp);
      const detail = el("div"); // 이 구간의 보드선도 자리 — 누른 칸 바로 밑
      detailBoxes.set(lp, detail);
      return [
        el("h3", { style: "font-size: 13px; margin: 14px 0 4px" }, label),
        pmCanvas, gmCanvas, detail,
      ];
    });
    const points = [];
    for (const e of entries) {
      if (e.trim.case.fuel !== fuel || !e.lon) continue;
      for (const m of e.lon.modes) points.push({ x: m.eig[0], y: m.eig[1], color: "#007aff" });
      for (const m of e.lat.modes) points.push({ x: m.eig[0], y: m.eig[1], color: "#ff9500" });
    }
    clear(plotBox).append(
      // el() 래핑 필수 — 네이티브 append는 배열을 문자열화 (리뷰 Must: 상습 함정군)
      el("div", {}, loopPlots),
      el("div", { class: "legend" },
        Object.entries(STATUS_LABEL).map(([k, name]) => el("span", {},
          el("span", { class: "chip", style: `background:${statusColor(k)}` }),
          k === "na" ? `${name} · 트림 불가` : name))),
      // 옛 결과(칸 판정 없음)는 전 칸 판정 불가 — 브라우저가 다시 판정하지 않고 사실을 말한다.
      // 판정이 있어도 지금 기체 기준과 다른 기준으로 낸 결과면 그 사실을 말한다
      // (네이티브 append라 null을 넘기면 글자 "null"이 된다 — 배열로 걸러 펼친다)
      ...[
        !hasMarginStatuses(body) ? OLD_RESULT_HINT
          : critSpec
            ? `${critSpec.label} — ` + (critState === "reeval"
              ? `이 결과는 기체 ${resultPid}의 지금 평가 기준과 다른 기준으로 판정됐다 — 칸 색은 계산할 때의 기준이다, `
                + "다시 계산하면 지금 기준으로 선다"
              : critSpec.tip)
            : null,
        resultPid && resultPid !== selPid
          ? `이 결과는 기체 ${resultPid}로 계산했다 — 제목의 판정선도 그 기체의 기준이다 (지금 고른 기체: ${selPid})`
          : null,
      ].filter(Boolean).map((t) => el("p", { class: "hint", style: "margin:6px 0 0" }, t)),
      // 칸의 수가 무엇인가(끊는 자리·나이퀴스트 거리·발산·게인 탭 판정 범위)와 루프 게인 출처 — 그림 아래 캡션
      ...[marginSemanticsText(body), gainSourceText(gainsInfo, law)].filter(Boolean)
        .map((t) => el("p", { class: "hint", style: "margin:6px 0 0" }, t)),
    );
    // 고유치·감쇠비는 패널이다 — 같은 연료로 함께 갈아 끼운다
    clear(slots.eig).append(
      el("div", { class: "scroll-x" },
        scatterCanvas(points, { title: "고유치 맵 (파랑=종축, 주황=횡축) — 허수축 좌측이 안정" })),
      el("p", { class: "hint" },
        `연료 ${fmt(fuel, 4)} kg 격자의 전 케이스 모드를 한 평면에 겹친 것 — 점 하나가 `
        + "케이스 하나의 모드 하나다. 어느 점이 어느 케이스인지는 아래 감쇠비 표가 낸다."),
    );
    const fuelEntries = entries.filter((e) => e.trim.case.fuel === fuel);
    clear(slots.damp).append(el("div", {},
      fqSummaryLine(fuelEntries),
      dampingTable(fuelEntries),
      el("p", { class: "hint" }, fqLegendText(body.fq_criteria)),
    ));
  };
  fuelSel.addEventListener("change", draw);
  /** 그 루프·그 칸의 보드선도를 연다 — 칸의 연료로 히트맵을 바꿔 그 칸이 보이게 한 뒤 (쇼케이스 최악 칸).
   *  클릭과 같은 길(openBode)이다. 곡선이 열린 노드, 루프·칸을 못 찾으면 null. */
  const focus = async (loopName, entry) => {
    const lp = loops.find((l) => l.name === loopName);
    if (!lp || !entry || !lp.x_out) return null;
    fuelSel.value = String(entry.trim.case.fuel);
    draw();
    await openBode(lp, entry);
    return detailBoxes.get(lp) ?? null; // 곡선이 열린 자리 — 진행기가 화면 안으로 굴린다
  };
  // el()로 감싼다 — 아래 `loops.length > 0 && …`는 거짓일 때 **false**를 낳고,
  // clear().append()는 네이티브라 그것을 "false" 텍스트로 붙인다 (el은 걸러 낸다)
  clear(slots.head).append(el("div", {},
    el("p", { style: "margin:0 0 4px" },
      el("b", {}, `계산 완료 — 케이스 ${entries.length}건 · 루프 ${loops.length}개`),
      reuseLine(body.trim_reuse)
        ? el("span", { class: "hint", title: reuseTip(body.trim_reuse) }, ` · ${reuseLine(body.trim_reuse)}`) : null),
    el("p", { class: "hint", style: "margin:0 0 6px" }, appliedSummary(body, lastBody === body ? lastDelaySrc : null)),
    el("div", { class: "row" }, fuelSel),
    // 안내가 플롯 **앞**에 있어야 한다 — 상세가 루프 구간마다 열리므로 맨 아래
    // 한 줄로는 어디를 눌러야 하는지 읽을 자리가 없다. 루프가 0개면(루프를 전부
    // 지웠거나 전 케이스 해석 실패) 히트맵이 한 장도 없으므로 안내도 내지 않는다 —
    // 맨 앞자리라 "루프 0개" 헤더 바로 밑에서 없는 것을 누르라고 하게 된다
    loops.length > 0 && el("p", { class: "hint", style: "margin:6px 0 0" },
      "히트맵 칸을 클릭하면 그 운용점·그 루프의 보드선도가 그 구간 바로 아래에 열립니다 — 한 번에 한 곳만."),
  ));
  clear(slots.plots).append(plotBox);
  draw();
  return { focus };
}

/** 필터 스펙 한 줄 — 파라미터 이름·단위는 블록 PARAM_DEFS 그대로 (엔진 filter_tf
 * 규격). kind와 무관하게 τ로 적으면 저역통과(fc)·노치(f0·q)에서 "τ=— s"가 된다. */
function filterText(f) {
  if (f.kind === "washout") return `washout τ=${fmt(f.tau, 3)} s`;
  if (f.kind === "lowpass") return `lowpass fc=${fmt(f.fc, 3)} Hz`;
  if (f.kind === "notch") return `notch f0=${fmt(f.f0, 3)} Hz · Q=${fmt(f.q, 3)}`;
  return f.kind;
}

/** 보드선도 상세 — 어느 칸인지, 무엇이 기준인지, 교차가 몇 개인지를 문장으로. */
function renderBode(box, lp, entry, body, gainNote = null, lawNote = null) {
  const c = entry.trim.case;
  const m = body.margins;
  const nGain = body.crossings.gain.length;
  const nPhase = body.crossings.phase.length;
  const kids = [
    el("h3", { style: "font-size: 13px; margin: 14px 0 4px" },
      `보드선도 — ${lp.name} @ M${fmt(c.mach, 3)} · ${fmt(c.alt, 5)} m · 연료 ${fmt(c.fuel, 4)} kg`),
    el("div", { class: "scroll-x" },
      bodeCanvas(body, { title: `${lp.name} — ${lp.sign < 0 ? "−" : "+"}PI·G(${lp.x_out} ← ${lp.u_in}) [${lp.axis}]` })),
    el("p", { class: "hint" },
      `실선이 기준입니다 — 클릭한 칸의 PM ${fmt(m.pm_deg, 4)}° · GM `
      + `${m.gm_db === "inf" ? "∞" : fmt(m.gm_db, 4)} dB가 이 곡선에서 읽은 값입니다. `
      + "PM은 |L|=0 dB인 wcp(초록)에서, GM은 ∠L=−180°인 wcg(주황)에서 읽습니다 — "
      + "두 수가 서로 다른 주파수의 값이라는 것이 두 수직선의 간격입니다."),
  ];
  // 보고한 마진이 무엇인가 — 닫아 둔 루프·발산·방향(진상 쪽·이득 감소 쪽)·교차가 여럿일 때 어느 것인가(lib/loops.js).
  // 교차가 여럿이면 보고된 마진은 그중 하나다 — 01 §4.2의 yaw_rate 사례가 이것이다
  for (const line of bodeMarginNotes(m)) kids.push(el("p", { class: "hint" }, line));
  // 엔진 교차 공개(margins.crossings)가 없는 응답(교차가 하나씩)인데 표본 곡선이 여럿을 봤을 때만 곡선 쪽 개수를 말한다
  if ((nGain > 1 || nPhase > 1) && !m.crossings) {
    kids.push(el("p", { class: "hint" },
      `곡선의 0 dB 교차 ${nGain}개 · −180° 교차 ${nPhase}개 — 채운 원이 보고한 자리, 빈 원이 나머지다.`));
  }
  if (body.filtered) {
    const f = body.filtered.margins;
    kids.push(el("p", { class: "hint" },
      `파선은 법칙에 실제로 있는 레이트 필터(${filterText(body.filtered.filter)})를 `
      + `넣은 조립입니다 — PM ${fmt(f.pm_deg, 4)}° · `
      + `GM ${f.gm_db === "inf" ? "∞" : fmt(f.gm_db, 4)} dB. 마진 맵은 이 필터를 정적 게인으로 `
      + "보므로(01 §4.2 [한계]) 두 곡선의 간격이 곧 그 한계의 크기입니다 — 히트맵 숫자가 "
      + "틀린 것이 아니라 필터를 안 본 값입니다."));
  } else if (body.filtered_note) {
    kids.push(el("p", { class: "hint" }, `필터 반영 곡선 없음 — ${body.filtered_note}.`));
  }
  // 법칙 게인 루프 — 서버가 이 칸의 게인으로 그렸다(맵의 이 칸과 같은 게인)
  if (lawNote) kids.push(el("p", { class: "hint" }, `${lawNote}.`));
  // 한 kp로 잰 루프(손으로 적은 값·낡은 확정 표) — 이 칸에서 기체가 실제로 나는 게인이 다르면 이 곡선은 근사다
  if (gainNote) {
    kids.push(el("p", { class: "hint" },
      `${gainNote}. 이 칸의 게인으로 재려면 [개루프 정의]의 「게인 읽을 마하」를 `
      + `${entry.trim.case.mach}로 두고 다시 실행한다.`));
  }
  clear(box).append(...kids);
}

/** 모드별 최악 수준 한 줄 — 표를 읽기 전에 "어디가 최악이고 몇 수준인가"부터 답한다.
 *  v1.10의 나선 T₂ 14 s는 이 줄이 처음부터 말했어야 하는 사실이다. */
function fqSummaryLine(entries) {
  return el("p", { style: "margin:0 0 6px" },
    el("b", {}, "비행성 수준 (모드별 최악) — "),
    ...fqWorst(entries).flatMap(({ mode, label, key, j, caseName }) => {
      const b = FQ_BADGE[key];
      const measure = fqMeasureText(mode, j);
      return [
        el("span", { style: "margin-right:10px; white-space:nowrap" },
          `${label} `,
          el("span", { class: "flag", style: `background:${b.color}22; color:${b.color}` }, b.label),
          caseName ? el("span", { class: "hint" }, ` (${measure} @ ${caseName})`) : null),
      ];
    }));
}

/** 수준 배지 — 판정 dict가 없으면(na) 배지도 없다: 표가 "잰 것이 없다"를 회색 글로 말한다. */
function fqBadge(j) {
  const key = fqKey(j);
  if (key === "na") return null;
  const b = FQ_BADGE[key];
  return el("span", { class: "flag", style: `background:${b.color}22; color:${b.color}; margin-left:6px` },
    b.short);
}

function dampingTable(entries) {
  const modeCell = (m, j) => (m
    ? el("span", {}, `${fmt(m.wn, 3)} / ${fmt(m.zeta, 2)}`, fqBadge(j))
    : "—");
  return el("table", {},
    el("thead", {}, el("tr", {},
      el("th", {}, "케이스"),
      el("th", {}, "단주기 wn/ζ"), el("th", {}, "장주기 wn/ζ"),
      el("th", {}, "더치롤 wn/ζ"),
      el("th", { title: "실근 λ [1/s] — 판정은 시정수 τ = −1/λ" }, "롤 λ"),
      el("th", { title: "실근 λ [1/s] — 발산이면 배가 시간 T₂ = ln2/λ로 판정" }, "나선 λ"))),
    el("tbody", {}, entries.map((e) => {
      const lonC = e.lon && e.lon.classified;
      const latC = e.lat && e.lat.classified;
      const lonJ = e.lon?.fq ?? {};
      const latJ = e.lat?.fq ?? {};
      const spiralExtra = latJ.spiral && !latJ.spiral.stable && latJ.spiral.t2_s != null
        ? ` (T₂ ${fmt(latJ.spiral.t2_s, 3)} s)` : "";
      return el("tr", {},
        el("td", {}, e.trim.case.name),
        el("td", { class: "num" }, modeCell(lonC && lonC.short_period, lonJ.short_period)),
        el("td", { class: "num" }, modeCell(lonC && lonC.phugoid, lonJ.phugoid)),
        el("td", { class: "num" }, modeCell(latC && latC.dutch_roll, latJ.dutch_roll)),
        el("td", { class: "num" }, latC
          ? el("span", {}, fmt(latC.roll.eig[0], 3), fqBadge(latJ.roll)) : "—"),
        el("td", { class: "num" }, latC
          ? el("span", {}, `${fmt(latC.spiral.eig[0], 3)}${spiralExtra}`, fqBadge(latJ.spiral)) : "—"),
      );
    })),
  );
}
