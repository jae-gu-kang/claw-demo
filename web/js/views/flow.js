/** 설계 흐름 탭 — 사슬을 한 화면에: 검증 → 엔벨로프 → 시드 → 자동 설계 → 평가 → 채택·반영
 * (06 §3, v1.33 파이프라인 유기화 3단계 — 사용자 결정: 새 탭, [끝까지 실행]은 채택·반영만
 * 수동, 평가는 엔진 평가 전체. 탭 위치는 v1.35부터 기체·블록도 다음 — 대상 → 구조 → 실행).
 *
 * 화면은 표가 아니라 **스테퍼 레일 + 3D 블록 다이어그램**이다(v1.35, 사용자 요구 "진행 상황과
 * 저장 파일들이 어디에 있는지 확실히" + 디자인 선택 "레일은 두되 블록은 블록도처럼 3D, 실행 중은
 * 블록도 선택처럼 파랗게 둥둥"): 진행 레일이 이어 돈 구간을 잇고, 단계는 블록도 층판 팔레트의
 * 3면 입체 블록, 실행 중 블록은 블록도 선택 문법 그대로 파란 3면으로 부양한다(app.css .fd).
 * 판 발치 「저장」 줄(lib/flowsteps.stageArtifact)과 정본 문서 카드가 산출물이 남는 곳을 가리킨다.
 *
 * 이 탭은 **오케스트레이션 층**이다: 계산은 전부 기존 엔드포인트(검증·design-envelope·quick-seed·
 * design/auto·influence/evaluate·apply-gains)이고, 데이터 인계는 없다 — 각 단계가 정본(문서)에서
 * 다시 재는 구조는 그대로다(낡음 사고 차단). 여기는 순서대로 실행하고, 단계마다 한 줄 판정과
 * 드릴다운 링크를 세우고, 실패·승인 대기에서 멈춘다. 판정 문구는 lib/flowsteps.js(재료는 서버 응답).
 *
 * 단계별 기록은 실행 시점의 기체 지문(echo — 형상 변형이면 그 변형의 지문)을 남기고, 문서가 바뀌면
 * lib/freshness.js로 「낡음」을 단다 — 결과 탭 배지(v1.32)와 같은 자다(자동 설계 결과가 제 게인 표를
 * 반영해 달라진 것뿐이면 「문서에 반영됨」 — 서버 목록의 applied_design). 잡은 서버에서 계속 돌고 결과
 * 탭에 남는다(탭을 떠나도).
 *
 * **다시 그리기는 모듈의 repaint를 지난다** — 이 탭은 드릴다운·승인 워크플로우로 사용자를 밖으로
 * 보내는 구조라, 실행 중 탭을 떠났다 돌아오는 것이 정상 경로다. render 클로저의 paint를 늦은 콜백이
 * 직접 잡으면 떨어져 나간 옛 DOM에 그려 화면이 동결된다(리뷰 지적) — 콜백은 모듈 repaint(항상 지금
 * 화면의 paint)를 부르고, 상태줄·오류도 모듈 상태로 들어 paint가 그린다.
 *
 * 쇼케이스 신호 `overview`(lib/showcasecue.js) — 잡을 새로 걸지 않고 레일을 **지금 문서와 최근 결과로**
 * 채운다: 문서 검증·엔벨로프는 이 탭의 [실행]과 같은 러너(조회 계산), 초기 게인은 설계 게인이 있으면
 * 판정만(없으면 탐색 잡이 필요하므로 건드리지 않는다), 자동 설계는 이 기체의 가장 최근 auto_design
 * 결과를 이 탭이 직접 돈 것과 같은 판정으로 싣는다(낡음 배지 포함). 평가는 싣지 않는다 — 이 흐름의
 * 평가는 **문서 그대로**의 엔진 평가인데, 다른 탭의 평가 결과는 작업본(주입 게인)으로 잰 것일 수 있다.
 */

import { ApiError, api, errorText, watchJob } from "../api.js";
import { clear, el } from "../dom.js";
import { adoptBlockedText, applyGateReason } from "../lib/autodesign.js";
import { envelopeQuery } from "../lib/envelope.js";
import { evaluateRequest, normalizeEvalReport } from "../lib/evaluate.js";
import {
  FLOW_STAGES, applyFreshnessBlock, applyStateVerdict, designVerdict, docVerdict, envelopeVerdict,
  evalVerdict, flowStepStates, flowSummaryLine, latestResultFor, seedStateVerdict, stageArtifact,
} from "../lib/flowsteps.js";
import { criteriaBadgeSpec, criteriaFreshness, resultFreshness } from "../lib/freshness.js";
// 잡 상태 코드 → 한국어 한 줄(「평가 취소됨」) — 영향성 탭과 같은 말(서버 jobs.py 어휘와 한 벌, 테스트 가드)
import { jobEndLine } from "../lib/influence.js";
import { EXAMPLE_ID, currentSelection } from "../lib/profile.js";
import { effectiveOf } from "../lib/profileform.js";
import { defaultRoleSelection, draftTag, reuseLine } from "../lib/opspace.js";
import { designSource, seedSummary } from "../lib/quickseed.js";
import { revealPanel } from "../lib/reveal.js";
import { failCue, reportCue, takeCue, unknownAction } from "../lib/showcasecue.js";
import { store } from "../store.js";
import { tabStage, tabTop } from "./stage.js";

// 단계 기록·실행 상태 — 탭 재진입에도 유지(모듈 스코프 규약). 기체 전환은 페이지를 다시 읽으므로
// (06 §8) 이 상태는 본질적으로 "지금 고른 기체"의 것이다.
// stages[key] = {state: "running"|"done", verdict, echo, resultId, report, note}
let stages = {};
let running = false; // 어떤 실행이든(개별·끝까지) 도는 중 — 이중 제출 방지(리뷰 지적)
let flowSeq = 0; // 실행 차례 — 늦은 콜백이 새 실행의 기록을 덮지 않게
let flowStatus = ""; // 상태줄 — paint가 그린다(늦은 콜백이 옛 DOM의 상태줄을 잡지 않게)
let flowError = null;
let profileRows = null; // GET /profiles — 이름·확정 표 상태·낡음 대조 재료 (실행 뒤마다 새로 받음)
let repaint = () => {}; // 지금 화면의 paint — render()가 갈아 끼운다
let revealRail = () => {}; // 지금 화면의 레일을 화면에 올린다(신호 끝) — repaint와 같은 이유로 render()가 갈아 끼운다

const selectedId = () => currentSelection()?.id ?? EXAMPLE_ID;
const selectedVariant = () => currentSelection()?.variant ?? null;

// 고른 기체의 지금 판정 기준 echo(GET /profiles/{id}/criteria) — 단계 결과의 criteria_echo 대조 재료
// (lib/freshness.js criteriaFreshness). 목록과 같이 새로 받는다. null = 못 받음(→ 판정 기준 미상)
let criteriaNow = null;

const refreshRows = async () => {
  const pid = selectedId();
  const [rows, crit] = await Promise.all([
    api.get("/profiles").catch(() => null), // 못 받으면 낡음 대조·확정 표 상태 없이 판정 줄만 — 다음 새로고침이 잡는다
    api.get(`/profiles/${encodeURIComponent(pid)}/criteria`).catch(() => null),
  ]);
  profileRows = rows;
  criteriaNow = crit?.echo ?? null;
};

/** 단계 결과의 판정 기준 배지 — 결과가 실은 기준 블록과 지금 기체 기준 대조. fresh·결과 없음은 조용하다. */
const criteriaChipOf = (st) => {
  if (!st?.resultId || !st.critKind || st.state !== "done") return null;
  // criteriaNow는 **고른 기체**의 기준이다 — 결과를 계산한 기체(st.echo = body.profile)가 다르면 대조하지 않는다
  // (다른 기체 기준과 대면 거짓 「재평가 필요」가 된다). 기체 전환은 페이지를 다시 읽어 stages가 비므로 드문 틈이다
  if (!st.echo?.id || st.echo.id !== selectedId()) return null;
  const spec = criteriaBadgeSpec(criteriaFreshness(st.critEcho, criteriaNow, st.critKind));
  return spec ? el("span", { class: `flag ${spec.tone}`, style: "margin-left:6px", title: spec.tip }, spec.label)
    : null;
};

const set = (seq, key, patch) => {
  if (seq !== flowSeq) return false; // 그사이 새 실행이 나갔다 — 늦은 콜백은 버린다
  stages[key] = { ...stages[key], ...patch };
  repaint();
  return true;
};

const fail = (seq, key, e) => {
  // 던진 러너의 줄이 "실행 중…"에 얼어붙지 않게, 이전 실행의 기록(echo — 낡음 배지 재료,
  // resultId·report — 발치 「저장」 줄 재료)도 지운다(리뷰 지적 — 안 지우면 실패 카드의
  // 발치줄이 이전 실행의 결과를 이번 실행의 산출물처럼 보인다)
  set(seq, key, { state: "done", verdict: { tone: "bad", text: errorText(e) },
    echo: null, resultId: null, report: null });
};

// ── 단계 실행기 — 계산은 전부 기존 엔드포인트, 여기는 순서와 기록뿐 ──────────
const doc = async () => api.get(`/profiles/${encodeURIComponent(selectedId())}`);
// echo의 지문은 **고른 형상**의 것 — 변형이면 응답의 변형 지문(기본 문서 지문을 변형 이름표에
// 붙이면 낡음 배지가 거짓이 된다, 리뷰 지적). 계산 단계(엔벨로프·설계·평가)는 헤더 선택이 실려
// 변형 위에서 돌므로 대조도 같은 지문이어야 한다
const echoOf = (got) => {
  const variant = selectedVariant();
  return { id: got.document.id, variant, revision: got.revision,
    fingerprint: variant ? (got.variants?.[variant] ?? null) : got.fingerprint };
};
// 조회 조건은 **적용 문서**(형상 변형 반영)에서 읽는다 — 변형이 질량·마진을 바꾸면 조건도 그 값이다
const effectiveDoc = (got) => {
  const variant = selectedVariant();
  return variant ? effectiveOf(got.document, variant) : got.document;
};

const runDoc = async (seq) => {
  set(seq, "doc", { state: "running", verdict: null, note: null, progress: null, echo: null, resultId: null, report: null });
  const got = await doc();
  let v;
  if (got.document.is_example) {
    // 예제는 저장 규칙이 당연히 거부한다(예약 id·예제 표시 — validate는 저장과 같은 규칙) —
    // 이 단계의 질문은 저장이 아니라 **문서가 건강한가**라, 예제(패키지 동봉 = 스키마는 이미
    // 통과한 문서)는 GET이 동봉한 경고로 답한다. 안 그러면 기본 선택(예제)에서 ①이 항상
    // 실패로 선다(v1.35에서 잡은 v1.33 결함). 사실은 문구에 남긴다 — 조용한 우회 금지
    v = docVerdict({ ok: true, warnings: got.warnings ?? [] });
    v = { ...v, text: `${v.text} — 예제 기체(패키지 동봉 문서라 저장 규칙 검증은 해당 없음)` };
  } else {
    // 검증은 문서 전체(형상 변형 패치 포함)를 본다 — 스키마 검증기가 변형 적용까지 확인한다
    const res = await api.post("/profiles/validate", { document: got.document });
    v = docVerdict(res);
  }
  set(seq, "doc", { state: "done", verdict: v, echo: echoOf(got) });
  return v;
};

const runEnvelope = async (seq) => {
  set(seq, "envelope", { state: "running", verdict: null, note: null, progress: null, echo: null, resultId: null, report: null });
  const got = await doc();
  const eff = effectiveDoc(got);
  const res = await api.get("/analysis/design-envelope?" + envelopeQuery({
    // 시드 앵커와 같은 기본(연료 절반 — 엔진 seed.FUEL_FRAC의 취지) — 조회 조건일 뿐 저장 안 됨
    fuel: eff.mass.fuel_max / 2,
    alpha_margin: eff.law.alpha_margin,
  }));
  const v = envelopeVerdict(res);
  set(seq, "envelope", { state: "done", verdict: v, echo: echoOf(got) });
  return v;
};

const runSeed = async (seq) => {
  set(seq, "seed", { state: "running", verdict: null, note: null, progress: null, echo: null, resultId: null, report: null });
  const got = await doc();
  const src = designSource(got.document);
  const state = seedStateVerdict(src.kind === "none" ? null : src.kind);
  if (!state.run) {
    set(seq, "seed", { state: "done", verdict: state, echo: echoOf(got), resultId: null });
    return state;
  }
  if (got.document.is_example) {
    const v = { tone: "bad", text: "예제 기체는 고칠 수 없습니다 — 기체 탭에서 복제한 뒤 그 기체로 진행합니다" };
    set(seq, "seed", { state: "done", verdict: v, echo: echoOf(got), resultId: null });
    return v;
  }
  const job = await api.post(`/profiles/${encodeURIComponent(selectedId())}/quick-seed`,
    { base_revision: got.revision });
  const done = await watchJob(job.id, (j) => set(seq, "seed",
    { state: "running", note: `빠른 탐색 ${Math.round((j.progress ?? 0) * 100)}%`,
      progress: j.progress ?? null }));
  if (done.status !== "done" || !done.result_id) {
    const v = { tone: "bad", text: `${jobEndLine("빠른 탐색", done)} — ${done.error ?? "사유 없음"}` };
    set(seq, "seed", { state: "done", verdict: v, echo: null, resultId: null });
    return v;
  }
  const body = await api.get(`/results/${done.result_id}`);
  const s = seedSummary(body);
  // 채택돼도 **저장이 안 됐으면**(충돌·삭제) 사슬을 잇지 않는다 — 다음 단계가 게인 없는 문서 위에서
  // 엉뚱한 실패를 낸다(리뷰 지적). headline이 이미 사유(충돌 리비전·write_error)를 말한다
  const v = { tone: s.ok && body.written ? "ok" : "bad", text: s.headline };
  // resultId — 산출물 발치줄이 결과 저장소의 그 결과를 가리키게 (v1.35 다이어그램)
  set(seq, "seed", { state: "done", verdict: v, echo: echoOf(await doc()), resultId: done.result_id });
  return v;
};

const runDesign = async (seq) => {
  set(seq, "design", { state: "running", verdict: null, note: null, progress: null, echo: null, resultId: null, report: null });
  const job = await api.post("/design/auto", { config: {} }); // 서버 기본(gated) — 승인 원칙 유지
  const done = await watchJob(job.id, (j) => set(seq, "design",
    { state: "running", note: `자동 설계 ${Math.round((j.progress ?? 0) * 100)}% — ${j.message ?? ""}`,
      progress: j.progress ?? null }));
  if (done.status !== "done" || !done.result_id) {
    const v = { tone: "bad", text: `${jobEndLine("자동 설계", done)} — ${done.error ?? "사유 없음"}` };
    set(seq, "design", { state: "done", verdict: v, echo: null, resultId: null, report: null });
    return v;
  }
  return settleDesign(seq, done.result_id);
};

/** 자동 설계 결과 하나를 이 단계의 기록으로 — 이 탭이 돈 실행과 개요(overview)가 싣는 최근 결과가
 *  같은 판정·같은 기록 모양을 쓴다(echo = 결과의 기체 — 낡음 배지 재료). */
const settleDesign = async (seq, resultId) => {
  const body = await api.get(`/results/${resultId}`);
  const v = designVerdict(body);
  set(seq, "design", { state: "done", verdict: v, resultId,
    report: body.report ?? null, echo: body.profile ?? null,
    critEcho: body.criteria_echo ?? null, critKind: "auto_design" });
  return v;
};

const runEval = async (seq) => {
  set(seq, "eval", { state: "running", verdict: null, note: null, progress: null, echo: null, resultId: null, report: null });
  // 점 — 요구영역 기본 격자의 보낼 점 전부(게인 카드·마진 맵과 같은 집합, 04 §5). 요구영역이 미정의면 재지 않고
  // 그 사유로 멈춘다 — 템플릿 격자로 되돌아가지 않는다(05 §11.13 5단계 나머지)
  const grid = await api.post("/grid/base", {});
  const { cases, reason } = defaultRoleSelection("metric", grid);
  if (reason) {
    const v = { tone: "bad", text: reason };
    set(seq, "eval", { state: "done", verdict: v, echo: null, resultId: null });
    return v;
  }
  const pts = [`기본 격자 ${cases.length}점`, draftTag(grid)].filter(Boolean).join(" · ");
  set(seq, "eval", { note: `평가 제출 — ${pts}` });
  // 주입 없음 — 정본(문서) 그대로의 평가. 게인 탭·자동 설계의 확정(작업본)이 걸려 있어도 이 흐름은
  // 문서로 잰다(작업본 평가는 영향성 탭 몫) — 힌트가 그 사실을 말한다
  const job = await api.post("/influence/evaluate",
    evaluateRequest({}, { cases, depth: "full" }));
  const done = await watchJob(job.id, (j) => set(seq, "eval",
    { state: "running", note: `평가 ${Math.round((j.progress ?? 0) * 100)}% · ${pts} — ${j.message ?? ""}`,
      progress: j.progress ?? null }));
  if (done.status !== "done" || !done.result_id) {
    const v = { tone: "bad", text: `${jobEndLine("평가", done)} — ${done.error ?? "사유 없음"}` };
    set(seq, "eval", { state: "done", verdict: v, echo: null, resultId: null });
    return v;
  }
  const body = await api.get(`/results/${done.result_id}`);
  const reuse = reuseLine(body.trim_reuse);
  const judged = evalVerdict(normalizeEvalReport(body));
  const v = { ...judged, text: [judged.text, pts, reuse].filter(Boolean).join(" · ") };
  set(seq, "eval", { state: "done", verdict: v, resultId: done.result_id,
    echo: body.profile ?? null, critEcho: body.criteria_echo ?? null, critKind: "influence_evaluate" });
  return v;
};

const RUNNERS = { doc: runDoc, envelope: runEnvelope, seed: runSeed, design: runDesign, eval: runEval };

/** [문서에 반영]을 막는 사유 — null이면 반영 가능. 자동 설계 탭의 adoptBlocked(판정 0 = 아무것도
 *  검증 안 한 게인)와 서버 가드(예제·변형)를 **버튼 앞에서** 같은 기준으로 말한다(리뷰 지적 —
 *  서버 apply-gains에는 judged 관문이 없어 이 관문이 그 자리다). */
const applyBlockReason = () => {
  const d = stages.design;
  if (!d?.resultId) return "자동 설계를 먼저 돌린다";
  if (d.verdict?.stop) return "승인 대기 결과는 반영하지 않는다 — 자동 설계 탭에서 승인·재개한 결과로";
  if (d.verdict?.tone === "bad") return "실패한 실행의 결과는 반영하지 않는다";
  const blocked = d.report ? adoptBlockedText(d.report) : null;
  if (blocked) return blocked;
  // 예제·변형·기록 없음 — 자동 설계 탭 버튼과 같은 관문(lib). 종전 관문은 source가 "request"인지만
  // 봐서, 헤더에서 예제를 명시로 고르면 지나가 서버 403을 받았고 재개 결과(스냅숏)는 막혔다
  const gate = applyGateReason(d.echo);
  if (gate) return gate;
  // 설계가 잰 문서와 지금 문서가 다르면 서버가 409로 거절한다 — 같은 판정을 버튼 앞에서(반영 자체도
  // 문서를 바꾸므로 한 번 반영한 결과는 여기 걸린다 — 「문서에 반영됨」도 막되 문구를 가른다, lib)
  return applyFreshnessBlock(resultFreshness(d.echo, profileRows, d.resultId).state);
};

/** 채택·반영 단계 판정 — 화면 칩과 신호 보고가 같은 것을 말한다. */
const applyVerdictNow = () => applyStateVerdict(
  profileRows?.find((p) => p.id === selectedId())?.gain_tables ?? null,
  Boolean(stages.design?.resultId), applyBlockReason());

/** 레일 단계 상태 — 신호 보고(data.steps)용. 낡음 대조는 화면 배지와 같은 판정(결과 id 포함 —
 *  반영 직후의 자동 설계는 「문서에 반영됨」). */
const stepStates = () => flowStepStates(stages, applyVerdictNow(),
  (echo, rid) => resultFreshness(echo, profileRows, rid).state);

/** 쇼케이스 신호 `overview` — 잡을 걸지 않고 레일을 지금 문서·최근 결과로 채운다(머리말). */
async function overview(cue) {
  if (running) {
    failCue(cue, "설계 흐름이 이미 실행 중이다 — 끝난 뒤 다시 건다");
    return;
  }
  flowError = null;
  const seq = ++flowSeq;
  running = true;
  flowStatus = "";
  repaint();
  // 러너가 던지면 그 줄을 실패로 닫는다 — 러너는 먼저 「실행 중」을 세우므로 안 닫으면 그 칩이
  // 「실행 중…」에 언다(runOne·runAll의 fail과 같은 규약)
  const step = async (key, runner) => {
    try {
      return await runner(seq);
    } catch (e) {
      fail(seq, key, e);
      throw e;
    }
  };
  try {
    await step("doc", runDoc);
    await step("envelope", runEnvelope);
    const got = await doc();
    // 설계 게인이 있으면 이 탭의 러너가 판정만 한다(잡 없음). 없으면 러너가 탐색 잡을 걸므로 건너뛴다
    if (designSource(got.document).kind !== "none") await step("seed", runSeed);
    const metas = await api.get("/results");
    const last = latestResultFor(metas, "auto_design",
      { id: selectedId(), variant: selectedVariant() });
    if (last) await settleDesign(seq, last.id);
  } catch (e) {
    running = false;
    await refreshRows();
    repaint();
    failCue(cue, e instanceof ApiError ? errorText(e) : e); // 서버 detail은 곱게(생 JSON 금지)
    return;
  }
  running = false;
  await refreshRows();
  repaint();
  const steps = stepStates();
  flowStatus = flowSummaryLine(steps);
  repaint();
  revealRail(); // 레일 — 진행기가 다음 단계로 가기 전에 청중 앞에(06 §2)
  reportCue(cue, { phase: "done", summary: flowSummaryLine(steps), data: { steps } });
}

export function render() {
  const errBox = el("div");
  const rowsBox = el("div", { class: "tab-sheet" });
  const statusLine = el("p", { class: "tab-status" });

  const showErr = (e) => {
    flowError = errorText(e);
    repaint();
  };

  const paint = () => {
    statusLine.textContent = flowStatus;
    clear(errBox);
    if (flowError) errBox.append(el("div", { class: "error-box" }, flowError));
    const row = profileRows?.find((p) => p.id === selectedId());
    const variant = selectedVariant();
    const applyBlocked = applyBlockReason();
    const applyVerdict = applyVerdictNow();
    const toneChip = (v) => el("span", { class: `flag ${v?.tone ?? "na"}` },
      ({ ok: "통과", warn: "주의", bad: "실패", na: "—" })[v?.tone ?? "na"]);
    // 산출물 발치줄의 링크 — 결과 인계는 시뮬 → 영향성과 같은 store 규약(목적 탭이 한 번 읽고
    // 지운다). 어디에 남았는지의 판정·문구는 lib/flowsteps.stageArtifact가 정본이고 여기는 배선뿐
    const artLink = (key, entry) => {
      if (!entry.to) return el("span", {}, entry.label);
      const rid = stages[key]?.resultId;
      const attrs = {
        brief: { href: "#results", title: "이 결과의 브리핑을 결과 탭에서 연다",
          onclick: () => store.set("resultBrief", { resultId: rid, from: "flow" }) },
        design: { href: "#autodesign", title: "이 실행의 보고서(운영점 판정·처방·승인)를 자동 설계 탭에서 연다",
          onclick: () => store.set("designOpen", { resultId: rid, from: "flow" }) },
        aircraft: { href: "#aircraft", title: "기체 탭 — 문서 리비전·게인 출처" },
        gains: { href: "#gains", title: "게인 탭 — 확정 표 상태·값" },
      }[entry.to];
      return el("a", attrs, `${entry.label} →`);
    };
    // 정본 문서 카드 — "저장 파일이 어디에 있나"의 반쪽: 모든 단계가 읽고 두 관문이 쓰는 곳
    const docCard = el("div", { class: "fd-doc" },
      el("span", { class: "fd-doc-t" }, "정본 문서"),
      row
        ? el("span", {},
            `${row.name ?? row.id} · 리비전 ${row.revision}`,
            variant ? ` · 형상 변형 ${variant}` : "",
            row.gain_tables ? ` · 확정 표 ${row.gain_tables.stale ? "낡음" : "유효"}` : " · 확정 표 없음")
        : el("span", { class: "hint" }, "기체 목록을 불러오는 중이거나 조회에 실패했습니다"),
      el("a", { href: "#aircraft" }, "기체 탭 →"));
    // 진행 레일 채움 — 앞에서부터 **이어서** 기록이 있는 데까지만 잇는다(띄엄 실행은 채우지
    // 않는다 — 마디 색이 각자의 상태를 말하고, 레일은 이어 돈 구간만). 마지막 마디(반영)는
    // 문서의 확정 표가 유효할 때만 닿는다
    let reach = 0;
    for (let i = 0; i < FLOW_STAGES.length; i++) {
      const k = FLOW_STAGES[i].key;
      if (k === "apply") {
        if (row?.gain_tables && !row.gain_tables.stale) reach = i;
        break;
      }
      if (stages[k]?.state) reach = i; else break;
    }
    const rail = el("div", { class: "fd-rail" },
      el("div", { class: "fd-bar" }),
      el("div", { class: "fd-fill", style: `width:${(reach * 100 / FLOW_STAGES.length).toFixed(2)}%` }));
    FLOW_STAGES.forEach((s, i) => {
      const st = stages[s.key];
      // 채택·반영 칩 — 설계 결과 유무와 막힌 사유를 따로 넘긴다(종전 !applyBlocked 인자 오류:
      // 승인 대기 결과가 있어도 "자동 설계를 먼저 돌립니다"가 떴다)
      const v = s.key === "apply" ? applyVerdict : st?.verdict;
      const busy = st?.state === "running";
      // 실행 시점 지문과 지금 문서의 대조 — 결과 탭 배지(v1.32)와 같은 판정. 결과 id를 함께 넘긴다:
      // 제 표를 반영해 달라진 것뿐인 자동 설계 결과는 낡음이 아니라 「문서에 반영됨」이다
      const fresh = st?.echo ? resultFreshness(st.echo, profileRows, st.resultId ?? null) : { state: "unknown" };
      const arts = stageArtifact(s.key, st);
      rail.append(el("div", { class: "fd-step", "data-key": s.key,
        "data-tone": busy ? "run" : (v?.tone ?? "na") },
        el("div", { class: "fd-node" }, String(i + 1)), // 큰 숫자 마디 — 원 없이(사용자 결정)
        // 3면 입체 블록 — 블록도 문법. 실행 중엔 CSS가 파란 3면으로 부양시킨다(선택 문법 통일)
        el("div", { class: "fd-blk3" },
          el("div", { class: "f-top" }), el("div", { class: "f-side" }),
          el("div", { class: "f-front" }, s.label,
            s.manual ? el("span", { class: "fd-manual" }, "수동 관문") : null),
          el("div", { class: "fd-ground" })),
        el("div", { class: "fd-panel" },
          el("div", { class: "fd-status" },
            busy ? el("span", { class: "hint" }, st.note ?? "실행 중…")
              : v ? el("span", {}, toneChip(v), " ", v.text)
              : el("span", { class: "hint" }, "아직 안 돌림"),
            fresh.state === "stale"
              ? el("span", { class: "flag bad", style: "margin-left:6px", title: fresh.label }, "낡음")
              : fresh.state === "applied"
                ? el("span", { class: "flag ok", style: "margin-left:6px", title: fresh.label }, "문서에 반영됨")
                : null,
            busy ? null : criteriaChipOf(st)),
          busy && typeof st?.progress === "number"
            ? el("div", { class: "fd-prog" },
                el("i", { style: `width:${Math.round(st.progress * 100)}%` }))
            : null,
          el("div", { class: "fd-act" },
            s.key === "apply"
              ? el("button", {
                  disabled: !!applyBlocked || running,
                  title: applyBlocked
                    ?? "이 흐름의 자동 설계 결과를 문서(law.gain_tables) 새 리비전으로 반영한다 — 정본 되쓰기",
                  onclick: () => runApply().catch(showErr),
                }, "문서에 반영")
              : el("button", { disabled: running, onclick: () => runOne(s.key) }, "실행"),
            el("a", { href: s.tab }, "탭 열기 →")),
          el("div", { class: "fd-art" },
            el("span", { class: "fd-art-t" }, "저장"),
            ...arts.flatMap((a, k) => [k ? " · " : null, artLink(s.key, a)]).filter(Boolean)))));
    });
    clear(rowsBox).append(
      el("div", { class: "scroll-x" }, el("div", { class: "fd" }, docCard, rail)),
      el("p", { class: "hint", style: "margin-top:8px" },
        "각 단계는 정본(문서)에서 다시 잽니다 — 단계끼리 결과를 물려주지 않아 낡음 사고가 없고, "
        + "게인 탭·자동 설계의 확정(작업본)이 걸려 있어도 이 흐름은 문서로 잽니다(작업본 평가는 영향성 "
        + "탭). 실행 시점과 문서가 달라지면 「낡음」이 붙습니다(다시 실행) — 자동 설계 결과가 제 게인 표를 "
        + "반영해 달라진 것뿐이면 「문서에 반영됨」입니다. 카드 발치의 「저장」 줄이 "
        + "그 단계 산출물이 남는 곳입니다 — 잡 결과는 결과 탭에, 채택·반영은 정본 문서 새 리비전에. "
        + "자동 설계가 승인 대기(gated)로 멈추면 자동 설계 탭에서 승인·재개한 뒤 이어 갑니다."));
  };
  repaint = paint; // 이 화면이 지금 화면 — 이전 render의 늦은 콜백도 이제 여기 그린다
  revealRail = () => revealPanel(rowsBox);

  const runOne = async (key) => {
    if (running) return;
    flowError = null;
    const seq = ++flowSeq;
    running = true;
    repaint();
    try {
      await RUNNERS[key](seq);
    } catch (e) {
      fail(seq, key, e);
    } finally {
      running = false;
      await refreshRows();
      repaint();
    }
  };

  const runAll = async () => {
    if (running) return;
    flowError = null;
    const seq = ++flowSeq;
    running = true;
    flowStatus = "";
    repaint();
    try {
      for (const s of FLOW_STAGES) {
        if (s.manual) break; // 채택·문서 반영은 수동 관문(사용자 결정) — 자동 직행하지 않는다
        let v;
        try {
          v = await RUNNERS[s.key](seq);
        } catch (e) {
          fail(seq, s.key, e);
          flowStatus = `「${s.label}」에서 오류로 멈춤`;
          return;
        }
        if (seq !== flowSeq) return;
        await refreshRows();
        repaint();
        if (v.tone === "bad" || v.stop) {
          flowStatus = `「${s.label}」에서 멈춤 — ${v.text}`;
          return;
        }
      }
      flowStatus = "평가까지 완료 — 판정을 확인하고 마지막 줄 [문서에 반영]으로 정본에 씁니다(수동 관문).";
    } finally {
      if (seq === flowSeq) running = false;
      await refreshRows();
      repaint();
    }
  };

  const runApply = async () => {
    if (running) return;
    flowError = null;
    const rid = stages.design?.resultId;
    if (!rid || applyBlockReason()) return;
    // running 게이트 — 반영 POST가 나가는 사이 더블클릭·다른 단계 실행을 막는다(안 막으면
    // 두 번째 반영이 낡은 base_revision으로 409를 받아 억울한 오류가 선다, 리뷰 지적)
    running = true;
    repaint();
    try {
      const head = await doc();
      const r = await api.post(`/design/${encodeURIComponent(rid)}/apply-gains`,
        { base_revision: head.revision });
      flowStatus = `리비전 ${r.revision}로 반영 — 이후 계산이 문서의 확정 표로 조립됩니다.`;
    } finally {
      running = false;
      await refreshRows();
      repaint();
    }
  };

  refreshRows().then(() => repaint());
  paint();
  // 쇼케이스 신호 — 한 번 읽고 지운다(store 인계 규약)
  const cue = takeCue("flow");
  if (cue) {
    if (cue.action === "overview") overview(cue);
    else unknownAction(cue);
  }

  return el("div", { class: "tab-page" },
    tabTop({
      title: "설계 흐름",
      lead: "헤더에서 고른 기체를 사슬 하나로: 검증 → 엔벨로프 → 초기 게인 → 자동 설계 → 평가 → "
        + "채택·문서 반영. 실행은 자동으로 잇고, 정본에 쓰는 마지막 관문만 사람이 누릅니다.",
      actions: [el("button", { class: "primary", disabled: running,
        onclick: () => runAll().catch(showErr) }, running ? "실행 중…" : "끝까지 실행")],
      extra: [statusLine, errBox],
    }),
    tabStage(rowsBox),
  );
}
