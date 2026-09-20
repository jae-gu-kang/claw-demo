/** 설계 흐름 탭 — 사슬을 한 화면에: 검증 → 엔벨로프 → 시드 → 자동 설계 → 평가 → 채택·반영
 * (06 §3, v1.33 파이프라인 유기화 3단계 — 사용자 결정: 새 탭·기체 다음, [끝까지 실행]은 채택·반영만
 * 수동, 평가는 엔진 평가 전체).
 *
 * 이 탭은 **오케스트레이션 층**이다: 계산은 전부 기존 엔드포인트(검증·design-envelope·quick-seed·
 * design/auto·influence/evaluate·apply-gains)이고, 데이터 인계는 없다 — 각 단계가 정본(문서)에서
 * 다시 재는 구조는 그대로다(낡음 사고 차단). 여기는 순서대로 실행하고, 단계마다 한 줄 판정과
 * 드릴다운 링크를 세우고, 실패·승인 대기에서 멈춘다. 판정 문구는 lib/flowsteps.js(재료는 서버 응답).
 *
 * 단계별 기록은 실행 시점의 기체 지문(echo — 형상 변형이면 그 변형의 지문)을 남기고, 문서가 바뀌면
 * lib/freshness.js로 「낡음」을 단다 — 결과 탭 배지(v1.32)와 같은 자다. 잡은 서버에서 계속 돌고 결과
 * 탭에 남는다(탭을 떠나도).
 *
 * **다시 그리기는 모듈의 repaint를 지난다** — 이 탭은 드릴다운·승인 워크플로우로 사용자를 밖으로
 * 보내는 구조라, 실행 중 탭을 떠났다 돌아오는 것이 정상 경로다. render 클로저의 paint를 늦은 콜백이
 * 직접 잡으면 떨어져 나간 옛 DOM에 그려 화면이 동결된다(리뷰 지적) — 콜백은 모듈 repaint(항상 지금
 * 화면의 paint)를 부르고, 상태줄·오류도 모듈 상태로 들어 paint가 그린다.
 */

import { api, errorText, watchJob } from "../api.js";
import { clear, el } from "../dom.js";
import { adoptBlockedText } from "../lib/autodesign.js";
import { envelopeQuery } from "../lib/envelope.js";
import { evaluateRequest, normalizeEvalReport } from "../lib/evaluate.js";
import {
  FLOW_STAGES, applyStateVerdict, designVerdict, docVerdict, envelopeVerdict,
  evalVerdict, seedStateVerdict,
} from "../lib/flowsteps.js";
import { resultFreshness } from "../lib/freshness.js";
import { defaultGridCases } from "../lib/grid.js";
import { EXAMPLE_ID, currentSelection } from "../lib/profile.js";
import { effectiveOf } from "../lib/profileform.js";
import { designSource, seedSummary } from "../lib/quickseed.js";
import { selectedDefaults } from "./missionfill.js";
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

const selectedId = () => currentSelection()?.id ?? EXAMPLE_ID;
const selectedVariant = () => currentSelection()?.variant ?? null;

const refreshRows = async () => {
  try {
    profileRows = await api.get("/profiles");
  } catch {
    profileRows = null; // 낡음 대조·확정 표 상태 없이 판정 줄만 — 다음 새로고침이 잡는다
  }
};

const set = (seq, key, patch) => {
  if (seq !== flowSeq) return false; // 그사이 새 실행이 나갔다 — 늦은 콜백은 버린다
  stages[key] = { ...stages[key], ...patch };
  repaint();
  return true;
};

const fail = (seq, key, e) => {
  // 던진 러너의 줄이 "실행 중…"에 얼어붙지 않게, 이전 실행의 echo(낡음 배지 재료)도 지운다(리뷰 지적)
  set(seq, key, { state: "done", verdict: { tone: "bad", text: errorText(e) }, echo: null });
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
  set(seq, "doc", { state: "running", verdict: null });
  const got = await doc();
  // 검증은 문서 전체(형상 변형 패치 포함)를 본다 — 스키마 검증기가 변형 적용까지 확인한다
  const res = await api.post("/profiles/validate", { document: got.document });
  const v = docVerdict(res);
  set(seq, "doc", { state: "done", verdict: v, echo: echoOf(got) });
  return v;
};

const runEnvelope = async (seq) => {
  set(seq, "envelope", { state: "running", verdict: null });
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
  set(seq, "seed", { state: "running", verdict: null });
  const got = await doc();
  const src = designSource(got.document);
  const state = seedStateVerdict(src.kind === "none" ? null : src.kind);
  if (!state.run) {
    set(seq, "seed", { state: "done", verdict: state, echo: echoOf(got) });
    return state;
  }
  if (got.document.is_example) {
    const v = { tone: "bad", text: "예제 기체는 고칠 수 없습니다 — 기체 탭에서 복제한 뒤 그 기체로 진행합니다" };
    set(seq, "seed", { state: "done", verdict: v, echo: echoOf(got) });
    return v;
  }
  const job = await api.post(`/profiles/${encodeURIComponent(selectedId())}/quick-seed`,
    { base_revision: got.revision });
  const done = await watchJob(job.id, (j) => set(seq, "seed",
    { state: "running", note: `빠른 탐색 ${Math.round((j.progress ?? 0) * 100)}%` }));
  if (done.status !== "done" || !done.result_id) {
    const v = { tone: "bad", text: `빠른 탐색 ${done.status} — ${done.error ?? "사유 없음"}` };
    set(seq, "seed", { state: "done", verdict: v, echo: null });
    return v;
  }
  const body = await api.get(`/results/${done.result_id}`);
  const s = seedSummary(body);
  // 채택돼도 **저장이 안 됐으면**(충돌·삭제) 사슬을 잇지 않는다 — 다음 단계가 게인 없는 문서 위에서
  // 엉뚱한 실패를 낸다(리뷰 지적). headline이 이미 사유(충돌 리비전·write_error)를 말한다
  const v = { tone: s.ok && body.written ? "ok" : "bad", text: s.headline };
  set(seq, "seed", { state: "done", verdict: v, echo: echoOf(await doc()) });
  return v;
};

const runDesign = async (seq) => {
  set(seq, "design", { state: "running", verdict: null });
  const job = await api.post("/design/auto", { config: {} }); // 서버 기본(gated) — 승인 원칙 유지
  const done = await watchJob(job.id, (j) => set(seq, "design",
    { state: "running", note: `자동 설계 ${Math.round((j.progress ?? 0) * 100)}% — ${j.message ?? ""}` }));
  if (done.status !== "done" || !done.result_id) {
    const v = { tone: "bad", text: `자동 설계 ${done.status} — ${done.error ?? "사유 없음"}` };
    set(seq, "design", { state: "done", verdict: v, echo: null, resultId: null, report: null });
    return v;
  }
  const body = await api.get(`/results/${done.result_id}`);
  const v = designVerdict(body);
  set(seq, "design", { state: "done", verdict: v, resultId: done.result_id,
    report: body.report ?? null, echo: body.profile ?? null });
  return v;
};

const runEval = async (seq) => {
  set(seq, "eval", { state: "running", verdict: null });
  const grid = (await selectedDefaults())?.grid ?? undefined;
  const cases = defaultGridCases(grid);
  // 주입 없음 — 정본(문서) 그대로의 평가. 게인 탭·자동 설계의 확정(작업본)이 걸려 있어도 이 흐름은
  // 문서로 잰다(작업본 평가는 영향성 탭 몫) — 힌트가 그 사실을 말한다
  const job = await api.post("/influence/evaluate",
    evaluateRequest({}, { cases, depth: "full" }));
  const done = await watchJob(job.id, (j) => set(seq, "eval",
    { state: "running", note: `평가 ${Math.round((j.progress ?? 0) * 100)}% — ${j.message ?? ""}` }));
  if (done.status !== "done" || !done.result_id) {
    const v = { tone: "bad", text: `평가 ${done.status} — ${done.error ?? "사유 없음"}` };
    set(seq, "eval", { state: "done", verdict: v, echo: null });
    return v;
  }
  const body = await api.get(`/results/${done.result_id}`);
  const v = evalVerdict(normalizeEvalReport(body));
  set(seq, "eval", { state: "done", verdict: v, resultId: done.result_id,
    echo: body.profile ?? null });
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
  if (d.echo?.source !== "request") return "예제 기체 결과는 문서에 반영할 수 없다 — 복제한 기체에서 진행한다";
  if (d.echo?.variant) return "형상 변형 위에서 돈 설계는 기본 문서에 반영할 수 없다";
  return null;
};

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
    const applyBlocked = applyBlockReason();
    const toneChip = (v) => el("span", { class: `flag ${v?.tone ?? "na"}` },
      ({ ok: "통과", warn: "주의", bad: "실패", na: "—" })[v?.tone ?? "na"]);
    clear(rowsBox).append(
      el("div", { class: "scroll-x" }, el("table", {},
        el("thead", {}, el("tr", {}, el("th", {}, "단계"), el("th", {}, "판정"),
          el("th", {}, "상태"), el("th", {}, ""))),
        el("tbody", {}, FLOW_STAGES.map((s) => {
          const st = stages[s.key];
          const v = s.key === "apply"
            ? applyStateVerdict(row?.gain_tables ?? null, !applyBlocked)
            : st?.verdict;
          // 실행 시점 지문과 지금 문서의 대조 — 결과 탭 배지(v1.32)와 같은 판정
          const fresh = st?.echo ? resultFreshness(st.echo, profileRows) : { state: "unknown" };
          return el("tr", {},
            el("td", { style: "white-space:nowrap" }, s.label),
            el("td", {},
              st?.state === "running" ? el("span", { class: "hint" }, st.note ?? "실행 중…")
                : v ? el("span", {}, toneChip(v), " ", v.text) : el("span", { class: "hint" }, "아직 안 돌림"),
              fresh.state === "stale"
                ? el("span", { class: "flag bad", style: "margin-left:6px", title: fresh.label }, "낡음") : null),
            el("td", { style: "white-space:nowrap" },
              s.key === "apply"
                ? el("button", {
                    disabled: !!applyBlocked || running,
                    title: applyBlocked
                      ?? "이 흐름의 자동 설계 결과를 문서(law.gain_tables) 새 리비전으로 반영한다 — 정본 되쓰기",
                    onclick: () => runApply().catch(showErr),
                  }, "문서에 반영")
                : el("button", { disabled: running, onclick: () => runOne(s.key) }, "실행")),
            el("td", {}, el("a", { href: s.tab }, "탭 열기 →")));
        })))),
      el("p", { class: "hint", style: "margin-top:8px" },
        "각 단계는 정본(문서)에서 다시 잽니다 — 단계끼리 결과를 물려주지 않아 낡음 사고가 없고, "
        + "게인 탭·자동 설계의 확정(작업본)이 걸려 있어도 이 흐름은 문서로 잽니다(작업본 평가는 영향성 "
        + "탭). 실행 시점과 문서가 달라지면 「낡음」이 붙습니다(다시 실행). 잡은 서버에서 돌고 결과 "
        + "탭에 남습니다. 자동 설계가 승인 대기(gated)로 멈추면 자동 설계 탭에서 승인·재개한 뒤 이어 "
        + "갑니다."));
  };
  repaint = paint; // 이 화면이 지금 화면 — 이전 render의 늦은 콜백도 이제 여기 그린다

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
    flowError = null;
    const rid = stages.design?.resultId;
    if (!rid || applyBlockReason()) return;
    const head = await doc();
    const r = await api.post(`/design/${encodeURIComponent(rid)}/apply-gains`,
      { base_revision: head.revision });
    flowStatus = `리비전 ${r.revision}로 반영 — 이후 계산이 문서의 확정 표로 조립됩니다.`;
    await refreshRows();
    repaint();
  };

  refreshRows().then(() => repaint());
  paint();

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
