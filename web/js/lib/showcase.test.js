// 쇼케이스 진행기 판단 — 단계 표·LLM 게이트·진행 규칙·기록·보관 형식 (DOM 없이)
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";

import { EXAMPLE_ID } from "./profile.js";
import { TAB_HASHES } from "./ask.js";
import {
  AUTODESIGN_BUDGET, CAP_FACTOR, DWELL_MS, FIGURE_DWELL_MS, LINE_FULL_MAX, LINE_MAX, NAV_DWELL_MS, RESUME_WINDOW_MS,
  SHOWCASE_CD0_DELTA, SHOWCASE_EVAL_CASES, SHOWCASE_FAULT, SHOWCASE_ID, STATE_LABEL, STATE_VERSION, STEPS,
  WORLD_REPLAY_TARGET_S, WORLD_SPEEDS, actionTimeout, advance, applyOutcome, autodesignConfigFor, beginStep,
  cancelCleanup, cancelStep, cardCompact, cardRows, cleanupLine, clearResume, clip, decodeState, designConfigRecord, dwellFor,
  listScrollTop, runEnded,
  emptyState, encodeState, expectNote, fabLabel, faultBaseNote, haltReason, installSummary, interruptStep, lineFor,
  llmSkipReason, needsPackagedDoc, nextInStep, preconditionNotes, refKey, reloadResume, replayDurationS,
  resolveArgs, resumeStep, rowsModel, settleRunning, shortReason, stepIndex, stepState, stopBanner, stopCause,
  stopStep, verdictOf, waitText, waitVerdict, withResume, worldSpeedFor,
} from "./showcase.js";
import { workingCopyLine } from "./gainsync.js";
import { SPEECH_GATE, TOUR_SPEED } from "./tour.js";
import { machRange, nameCases, representativeGrid, serpentineCases } from "./grid.js";

const at = (key) => stepIndex(key);
const acts = (key) => STEPS[at(key)].actions;

// ── 단계 표 ──────────────────────────────────────────────────────────────────

test("단계 표는 06 §9.4의 순서 그대로다 — 준비부터 질문까지 17단계", () => {
  assert.deepEqual(STEPS.map((s) => s.key), [
    "prepare", "aircraft", "blocks", "envelope", "trim", "gains", "margins", "edit", "autodesign",
    "flow", "sim", "world", "influence", "autocode", "verify", "results", "ask",
  ]);
  assert.equal(new Set(STEPS.map((s) => s.label)).size, STEPS.length, "단계 이름이 겹치지 않는다");
});

test("신호 동작의 탭은 전부 실제 탭 해시다 — 죽은 탭으로 신호를 걸지 않는다", () => {
  for (const s of STEPS) {
    assert.ok(s.actions.length > 0, `${s.key}: 동작 없는 단계`);
    for (const a of s.actions) {
      assert.ok(typeof a.label === "string" && a.label, `${s.key}: 이름 없는 동작`);
      if (a.kind === "cue") assert.ok(TAB_HASHES.includes(a.tab), `${s.key}: 모르는 탭 ${a.tab}`);
      if (a.kind === "nav") assert.match(a.hash, /^#blocks(\/[a-z]+)*$/);
    }
  }
});

test("동작 이름·인자가 계약(06 §9.3)과 같다", () => {
  const sig = (key) => acts(key).map((a) => (a.kind === "cue" ? `${a.tab}:${a.action}` : a.kind));
  assert.deepEqual(sig("prepare"), ["install"]);
  assert.deepEqual(sig("aircraft"),
    ["aircraft:overview", "aircraft:aero", "aircraft:stability", "aircraft:seed-basis"]);
  assert.deepEqual(acts("blocks").map((a) => a.hash), ["#blocks", "#blocks/scas/yaw", "#blocks/plant/prop"]);
  assert.deepEqual(sig("envelope"), ["envelope:vn", "envelope:scan"]);
  assert.deepEqual(sig("trim"), ["trim:run"]);
  assert.deepEqual(sig("gains"), ["gains:overview", "gains:evaluate"]);
  assert.deepEqual(sig("margins"), ["margins:run"]);
  assert.deepEqual(sig("edit"), ["aircraft:edit-eoir-drag", "aircraft:derive-de-trim"]);
  assert.deepEqual(acts("edit")[0].args, { cd0_delta: SHOWCASE_CD0_DELTA });
  assert.deepEqual(sig("autodesign"), ["autodesign:design-and-apply", "reload", "autodesign:open"]);
  assert.deepEqual(acts("autodesign")[0].args, {}, "config는 상수가 아니라 신호를 걸 때 문서에서(docArgs)");
  assert.equal(typeof acts("autodesign")[0].docArgs, "function");
  assert.deepEqual(acts("autodesign")[2].args, { resultId: { $ref: "autodesign.design-and-apply" } },
    "다시 읽기가 지운 결과 화면을 방금 그 결과로 다시 연다");
  assert.deepEqual(sig("flow"), ["flow:overview"]);
  assert.deepEqual(sig("sim"), ["sim:draft", "sim:run", "sim:duty"]);
  assert.deepEqual(sig("world"), ["world"]);
  assert.deepEqual(sig("influence"), [
    "influence:diagnose", "influence:screen", "influence:evaluate", "gains:fault",
    "influence:evaluate", "influence:prescribe", "influence:evaluate", "gains:restore",
  ]);
  assert.deepEqual(acts("influence")[3].args, SHOWCASE_FAULT);
  assert.deepEqual(acts("influence").map((a) => a.expect ?? null),
    [null, null, null, null, "FAIL", null, "PASS", null]);
  for (const i of [2, 4, 6]) assert.equal(acts("influence")[i].args.cases, SHOWCASE_EVAL_CASES);
  assert.deepEqual(sig("autocode"), ["autocode:overview"]);
  assert.deepEqual(acts("autocode")[0].args, { compareWith: EXAMPLE_ID });
  assert.deepEqual(sig("verify"), ["verify:run"]);
  assert.deepEqual(sig("results"), ["results:open", "results:opinion"]);
  assert.deepEqual(sig("ask"), ["ask"]);
});

test("LLM 동작은 초안·소견서·질문뿐이다 (교신은 가상환경 단계가 선택적으로)", () => {
  const llm = STEPS.flatMap((s) => s.actions.filter((a) => a.llm).map((a) => `${s.key}:${a.kind === "cue" ? a.action : a.kind}`));
  assert.deepEqual(llm, ["sim:draft", "results:opinion", "ask:ask"]);
});

test("결함 시연 뒤에는 실패해도 문서 게인 복원이 돈다 (always)", () => {
  const last = acts("influence").at(-1);
  assert.equal(last.action, "restore");
  assert.equal(last.always, true);
  assert.equal(acts("influence").filter((a) => a.always).length, 1);
});

test("자리값 상수 — 결함 경로 꼴과 케이스 수가 계약 형식을 지킨다", () => {
  assert.match(SHOWCASE_FAULT.path, /^[a-z_]+\.[a-z_]+\.[a-z_]+$/);
  // 약화든 과대든 공학 결함이다(지금은 고도 루프 ḣ 되먹임 과대) — 배율 1은 결함이 아니다
  assert.ok(Number.isFinite(SHOWCASE_FAULT.factor) && SHOWCASE_FAULT.factor > 0 && SHOWCASE_FAULT.factor !== 1);
  assert.ok(Number.isInteger(SHOWCASE_EVAL_CASES) && SHOWCASE_EVAL_CASES > 0);
  assert.ok(Object.isFrozen(AUTODESIGN_BUDGET) && Object.isFrozen(SHOWCASE_FAULT));
  assert.equal(SHOWCASE_ID, "showcase-delta");
});

test("자동 설계 config 폴백 — 기록이 없으면 예산 + 선택 기체 문서의 템플릿 축(기체 값을 박지 않는다)", () => {
  // 일부러 흔치 않은 수 — 결과에 나오면 문서에서 왔다는 뜻이다
  const doc = { mission_template: { envelope: { alt: [111, 2222] }, trim_grid: { fuel: [7, 33] } } };
  const t = autodesignConfigFor(doc);
  assert.deepEqual(t.config, { ...AUTODESIGN_BUDGET, alts: [111, 2222], fuels: [7, 33] });
  assert.equal(t.source, "template");
  assert.match(t.note, /^설정 출처: 미션 템플릿 축/, "어느 출처인지 행에 남긴다");
  // 스칼라 고도(E2 이전 문서·예제)는 한 점 목록으로
  const scalar = { mission_template: { envelope: { alt: 900 }, trim_grid: { fuel: [12] } } };
  assert.deepEqual(autodesignConfigFor(scalar).config.alts, [900]);
  // 칸이 없으면 서버 기본 설정(빈 덧씀) + 그 사실 — 예제 값을 조용히 물려주지 않는다
  const noFuel = autodesignConfigFor({ mission_template: { envelope: { alt: [0] }, trim_grid: {} } });
  assert.deepEqual(noFuel.config, {});
  assert.equal(noFuel.source, "server");
  assert.match(noFuel.note, /trim_grid\.fuel/);
  assert.doesNotMatch(noFuel.note, /envelope\.alt/);
  const junk = autodesignConfigFor({ mission_template: { envelope: { alt: ["x"] }, trim_grid: { fuel: [] } } });
  assert.deepEqual(junk.config, {});
  assert.match(junk.note, /envelope\.alt · trim_grid\.fuel/);
  const none = autodesignConfigFor(null);
  assert.deepEqual(none.config, {});
  assert.equal(none.source, "server");
  assert.match(none.note, /서버 기본 설정/);
  // 단계 표의 문서 인자 — 신호 args와 안내 줄(출처 한 줄은 늘 있다)
  const da = acts("autodesign")[0].docArgs;
  assert.deepEqual(da(doc), { args: { config: autodesignConfigFor(doc).config }, notes: [t.note] });
  assert.deepEqual(da(null).args, { config: {} });
  assert.equal(da(null).notes.length, 1);
});

// S1 생성기가 law.gain_tables.provenance.design.config에 적는 모양 그대로(표 표현 재생성본 — P5-s1: 설계 고도 해면
// 한 줄 · 점 예산 90. 마하 1축 표라 두 고도를 주면 톱니가 됐다). 표 표현은 다항 적합 제한(max_degree·max_segments)을
// 쓰지 않아 적지 않는다
const S1_DESIGN_CONFIG = {
  n_mach: 7, budget_points: 90, budget_iters: 2, alts: [0], fuels: [25],
  targets: { zeta_sp: 0.9 }, fit_mode: "table",
};
// 요청으로 옮긴 모양 — 판정선·목표(criteria·targets)는 뗀다(기준 통합 ①: 목표는 기체 문서 /tuning이 정본)
const { targets: _S1_TARGETS, ...S1_REQUEST_CONFIG } = S1_DESIGN_CONFIG;
const withRecord = (config, extra = {}) => ({
  id: SHOWCASE_ID,
  mission_template: { envelope: { alt: [111, 2222] }, trim_grid: { fuel: [7, 33] } },
  law: { gain_tables: { tables: {}, provenance: { source: "auto_design", design: { status: "ok", config } } } },
  ...extra,
});

test("자동 설계 config — 문서가 적어 둔 설계 설정(provenance.design.config)이 템플릿 규칙보다 먼저다", () => {
  const doc = withRecord(S1_DESIGN_CONFIG);
  const r = autodesignConfigFor(doc);
  // 게인 표현까지 그대로 — 템플릿 축(111·2222 / 7·33)도 진행기 예산(n_mach 5)도 섞이지 않는다. 목표 ζsp는 뗀다
  assert.deepEqual(r.config, S1_REQUEST_CONFIG);
  assert.equal("targets" in r.config, false);
  assert.equal(r.source, "document");
  assert.match(r.note, /^설정 출처: 문서 확정 게인 표를 만든 설정\(law\.gain_tables\.provenance\.design\.config\)/);
  // 사본이다 — 신호 args를 고쳐도 문서 캐시(selectedDocument)가 안 바뀐다
  r.config.alts.push(9);
  assert.equal(doc.law.gain_tables.provenance.design.config.targets.zeta_sp, 0.9);
  assert.deepEqual(doc.law.gain_tables.provenance.design.config.alts, [0]);
  assert.deepEqual(designConfigRecord(doc), S1_DESIGN_CONFIG);
  // 단계 표의 문서 인자도 같은 출처
  const da = acts("autodesign")[0].docArgs(doc);
  assert.deepEqual(da.args, { config: S1_REQUEST_CONFIG });
  assert.deepEqual(da.notes, [r.note]);
  // 빈 기록·객체 아닌 기록은 기록이 아니다 — 템플릿 규칙으로
  for (const bad of [{}, null, [1, 2], "x", 7]) {
    assert.equal(designConfigRecord(withRecord(bad)), null, JSON.stringify(bad));
    assert.equal(autodesignConfigFor(withRecord(bad)).source, "template", JSON.stringify(bad));
  }
  assert.equal(designConfigRecord(null), null);
  assert.equal(designConfigRecord({ law: { gain_tables: null } }), null);
});

test("자동 설계 config — 반영 뒤 기록이 빠진 쇼케이스 문서는 같은 기체의 패키지 문서 기록으로", () => {
  // 서버 apply-gains가 새로 쓴 표의 provenance에는 design이 없다(단계 8 뒤 문서의 모양)
  const applied = { ...withRecord(null), law: { gain_tables: { tables: {}, provenance: { source: "auto_design" } } } };
  assert.equal(needsPackagedDoc(applied), true);
  assert.equal(needsPackagedDoc(withRecord(S1_DESIGN_CONFIG)), false, "기록이 있으면 패키지를 받지 않는다");
  assert.equal(needsPackagedDoc({ ...applied, id: EXAMPLE_ID }), false, "다른 기체는 패키지와 무관하다");
  assert.equal(needsPackagedDoc(null), false);
  const packaged = withRecord(S1_DESIGN_CONFIG);
  const r = autodesignConfigFor(applied, { packaged });
  assert.deepEqual(r.config, S1_REQUEST_CONFIG);
  assert.equal(r.source, "package");
  assert.match(r.note, new RegExp(`^설정 출처: ${SHOWCASE_ID} 패키지 문서의 확정 표 설정`));
  r.config.alts.push(9);
  assert.deepEqual(packaged.law.gain_tables.provenance.design.config.alts, [0], "패키지 문서도 사본으로");
  assert.equal(packaged.law.gain_tables.provenance.design.config.targets.zeta_sp, 0.9, "기록 자체는 그대로");
  // id가 다른 패키지(남의 기체)의 설정은 물려주지 않는다 — 템플릿 규칙
  const other = autodesignConfigFor({ ...applied, id: "other-plane" }, { packaged });
  assert.equal(other.source, "template");
  // 패키지를 못 받았으면(null) 템플릿 규칙 — 출처를 행에 남긴다
  const noPkg = autodesignConfigFor(applied, { packaged: null });
  assert.equal(noPkg.source, "template");
  assert.deepEqual(noPkg.config, { ...AUTODESIGN_BUDGET, alts: [111, 2222], fuels: [7, 33] });
  // 문서 자기 기록이 패키지보다 먼저다
  const own = withRecord({ ...S1_DESIGN_CONFIG, n_mach: 3 });
  assert.equal(autodesignConfigFor(own, { packaged }).config.n_mach, 3);
  // 단계 표의 문서 인자가 패키지를 넘겨받는다
  assert.deepEqual(acts("autodesign")[0].docArgs(applied, { packaged }).args, { config: S1_REQUEST_CONFIG });
});

test("자동 설계 config — 판정선·목표는 요청에 싣지 않는다(기체 문서 /tuning이 정본)", () => {
  const withCrit = { ...S1_DESIGN_CONFIG, criteria: { pm_min_deg: 50 } };
  for (const r of [autodesignConfigFor(withRecord(withCrit)),
    autodesignConfigFor({ ...withRecord(null), law: { gain_tables: { provenance: {} } } },
      { packaged: withRecord(withCrit) })]) {
    assert.equal("criteria" in r.config, false, r.source);
    assert.equal("targets" in r.config, false, r.source);
    assert.deepEqual(r.config, S1_REQUEST_CONFIG, r.source);
  }
});

const readS1 = () => JSON.parse(readFileSync(
  new URL("../../../engine/claw/profile/examples/showcase_delta.json", import.meta.url), "utf8"));
// 확정 표 값 지문 — 자리 이름순으로 축·값만(외삽 방식·출처 제외). 값이 한 비트라도 바뀌면 달라진다
const tablesDigest = (tables) => createHash("sha256")
  .update(JSON.stringify(Object.keys(tables).sort().map((n) => [n, tables[n].axes, tables[n].data])))
  .digest("hex").slice(0, 16);

test("결함 시연 상수 — S1 확정본에서 잰 창(×5.2~5.85, FAIL → 처방 → PASS)의 가운데다", () => {
  // P5-s1 실측(lib/showcase.js 머리 주석) — 설계 격자를 해면 한 줄로 바꿔 확정 표의 톱니를 없애자 창이 ×5.4~6.6에서
  // 옮았다(3000 m에서 게인이 해면 값이라 M0.18_h3000_f10의 동적 여유가 먼저 닳는다). 그 전의 창: 피치 명령 상한 0.35 rad
  // ×4.8~5.8, 0.3 rad ×5.4~6.6(요 댐퍼 표 수리·발진 웜스타트·요 목표 ζ_dr 0.6에서 그대로). 예제에서 잰 피치 댐퍼 ×4.8은
  // S1에서 FAIL이 안 난다. 창 폭이 0.65라 양끝 여유는 0.3 — 새 측정에서 어느 끝이 0.3 안으로 들어오면 창을 다시 고른다
  assert.deepEqual(SHOWCASE_FAULT, { path: "autopilot.alt.k_rate", factor: 5.5 });
  const [lo, hi] = [5.2, 5.85];
  assert.ok(SHOWCASE_FAULT.factor - lo >= 0.3 - 1e-9 && hi - SHOWCASE_FAULT.factor >= 0.3 - 1e-9, "창 끝에서 떨어져 있다");
});

test("결함 시연 상수 — 잰 기준(자동조종 설계값·확정 표·대표 케이스)이 실물 S1 문서 그대로다", () => {
  const s1 = readS1();
  const fix = "S1 문서가 바뀌었다 — 결함 창을 다시 재고 SHOWCASE_FAULT와 이 기준을 함께 고친다";
  // 끈 자리 상수 경로로 잰 값이다 — 확정 표에 이 자리가 생기면(표 경로) 곱해지는 값이 달라진다
  assert.ok(!Object.hasOwn(s1.law.gain_tables.tables, "alt.k_rate"), fix);
  // 곱해지는 설계점 상수(k_hdot)와 확정 표를 설계한 바탕 문서(기준 지문 — 표 값은 담지 않는다)
  assert.ok(Math.abs(s1.law.design.autopilot.k_hdot - -0.029986076721022634) < 1e-12, fix);
  assert.equal(s1.law.gain_tables.provenance.basis_fingerprint, "1ef8f8c05f21e515", fix);
  // 그 창을 만든 확정 표 값 자체 — 표 표현 재생성은 k_hdot·기준 지문을 그대로 두고 창만 옮겼다(×5.2~6.4 →
  // ×4.8~5.8). 요 댐퍼 표 수리(튜너 2차 패스 — yaw.k_rate·roll.kp·roll.ki 29점씩)도 기준 지문을 두고 표 값만 바꿨다(창은 그대로).
  // 요 설계 목표 ζ_dr 0.5 → 0.6은 시드 요·롤 게인이 바뀌어 기준 지문과 표 4자리(yaw.k_rate·roll.k_rate·roll.kp·
  // roll.ki)가 함께 바뀌었다 — 창은 그대로(Y2-s1 재측정). 설계 격자를 해면 한 줄로 바꾸고(톱니 제거 — 표 7자리 × 66점
  // → 40점) CL 표에 실속 꼭대기 행·열을 더한 재생성(P5-s1 — 기준 지문 2ecb… → 1ef8…)도 다시 쟀다(lib/showcase.js 머리
  // 주석). 단계 8 재설계 표도 같은 값이라 두 상태가 같은 창을 낸다(표 7자리 × 40점). 롤 속도 루프 마진 가드(Q1-gate —
  // AS94900 끊는 자리에서 GM 8 dB·PM 50°로 롤 댐퍼를 캡) 뒤 재생성(Q3-s1)은 기준 지문을 두고 roll.k_rate·roll.kp·
  // roll.ki·yaw.k_rate 값만 바꿨다(피치 3자리·설계 게인 그대로) — 다시 잰 창은 머리 주석
  assert.equal(s1.law.gain_tables.provenance.design?.config?.fit_mode, "table", fix);
  assert.equal(tablesDigest(s1.law.gain_tables.tables), "07dd528f85175841", fix);
  // 자동조종 상자 — 고도·승강률 PI의 출력 한계(θ 명령 상한)가 창에 든다. 레지스트리 기본값으로 잰 창이다
  assert.equal(s1.law.design.autopilot.theta_hi, 0.3, fix);
  assert.equal(s1.law.design.autopilot.tau_spd, 2.0, fix);
  // 대표 4케이스(웹 representativeGrid) — FAIL이 나는 고마하 두 모서리(M0.18)가 들어 있다
  const g = s1.mission_template.trim_grid;
  const r = representativeGrid({ machFrom: g.mach.from, machTo: g.mach.to, machStep: g.mach.step,
    alts: g.alt, fuels: g.fuel }, SHOWCASE_EVAL_CASES);
  const names = nameCases(serpentineCases(machRange(r.machFrom, r.machTo, r.machStep), r.alts, r.fuels))
    .map((c) => c.name);
  assert.deepEqual(names, ["M0.12_h200_f10", "M0.18_h200_f10", "M0.18_h3000_f10", "M0.12_h3000_f10"], fix);
});

test("실물 S1 패키지 문서 — 자동 설계 config는 생성기가 적은 기록에서 온다", () => {
  const s1 = readS1();
  assert.equal(s1.id, SHOWCASE_ID);
  const r = autodesignConfigFor(s1);
  assert.equal(r.source, "document");
  const { targets, ...rest } = s1.law.gain_tables.provenance.design.config;
  assert.deepEqual(r.config, rest);
  // 목표 ζsp(기본 0.7이면 피치 게인 표가 S1 띠 검사를 못 넘는다)는 요청에서 뗀다 — 문서 /tuning이 같은 값을 적어
  // 서버가 그것으로 설계한다(기준 통합 ①). 게인 표현(표)은 실려 간다(엔진 기본값이 바뀌어도 같은 표현으로)
  assert.equal(targets.zeta_sp, 0.9);
  assert.equal(s1.tuning.targets.zeta_sp, targets.zeta_sp);
  assert.equal("targets" in r.config, false);
  assert.equal("criteria" in r.config, false);
  assert.equal(r.config.fit_mode, "table");
  assert.equal(needsPackagedDoc(s1), false);
});

test("쇼케이스 진행기 뷰 — 자동 설계 인자에 패키지 문서를 필요할 때만 받아 넘긴다 (배선 가드)", () => {
  const src = readFileSync(new URL("../views/showcase.js", import.meta.url), "utf8");
  assert.match(src, /sc\.needsPackagedDoc\(doc\)/);
  assert.match(src, /api\.get\("\/profiles\/_showcase"\)/);
  assert.match(src, /a\.docArgs\(doc, \{ packaged \}\)/);
});

// ── LLM 게이트 ───────────────────────────────────────────────────────────────

test("LLM 게이트 — 가능하면 null, 불가면 서버 사유 그대로, 조회 실패도 사유", () => {
  assert.equal(llmSkipReason({ available: true, reason: null }), null);
  assert.equal(llmSkipReason({ available: false, reason: "키가 없습니다" }), "키가 없습니다");
  assert.equal(llmSkipReason({ available: false }), "LLM을 사용할 수 없다 (서버가 사유를 주지 않았다)");
  assert.equal(llmSkipReason(null, "연결 안 됨"), "LLM 상태 조회 실패 — 연결 안 됨");
  assert.equal(llmSkipReason(null), "LLM 상태를 아직 모른다");
  // 서버 사유는 길다(설정 안내까지) — 줄에는 첫 마디만, 전량은 카드 상태 줄 툴팁
  assert.equal(llmSkipReason({ available: false,
    reason: "LLM 백엔드가 설정되지 않았습니다 — LLM 기능이 꺼져 있습니다. 키를 설정하십시오." }),
  "LLM 백엔드가 설정되지 않았습니다");
  assert.equal(shortReason("키 없음. 설정하라"), "키 없음");
  assert.equal(shortReason(""), "");
});

// ── 인자·시간 ────────────────────────────────────────────────────────────────

test("인자 참조 — 앞 동작의 결과 id·성공 여부로 채우고, 모르면 칸을 뺀다", () => {
  const refs = { "results.open": { ok: true, resultId: "r9" }, "sim.draft": { ok: false, resultId: null } };
  assert.deepEqual(resolveArgs({ resultId: { $ref: "results.open" } }, refs), { resultId: "r9" });
  assert.deepEqual(resolveArgs({ resultId: { $ref: "verify.run" } }, refs), {});
  assert.deepEqual(resolveArgs({ useDraft: { $ok: "sim.draft" } }, refs), { useDraft: false });
  assert.deepEqual(resolveArgs({ useDraft: { $ok: "sim.draft" } },
    { "sim.draft": { ok: true, resultId: "d1" } }), { useDraft: true });
  assert.deepEqual(resolveArgs({ cases: 6, label: "기준" }, {}), { cases: 6, label: "기준" });
  assert.deepEqual(resolveArgs(undefined, {}), {});
  const simRun = acts("sim")[1];
  assert.deepEqual(simRun.args, { useDraft: { $ok: "sim.draft" } }, "초안이 앉았을 때만 초안으로");
  assert.deepEqual(acts("results")[1].args, { resultId: { $ref: "results.open" } });
});

test("동작별 시간 상한 — 긴 잡은 길게, 모르는 것은 기본값", () => {
  const ad = actionTimeout(acts("autodesign")[0]);
  const ov = actionTimeout(acts("aircraft")[0]);
  assert.ok(ov >= 60_000 && ov < ad);
  assert.ok(actionTimeout({ kind: "cue", tab: "x", action: "y" }) > 0);
  assert.equal(refKey(acts("sim")[1]), "sim.run");
  // 각 패키지가 요구한 하한(무료 플랜은 더 느리다) — 줄이면 여기서 걸린다. 시뮬·검증은 S1 확정본 실측으로
  // 올린 하한(S1-integrate: 시뮬 ≥ 300 s · 검증 ≥ 180 s · 자동 설계 ≥ 180 s · 도출 ≥ 120 s — 큰 쪽을 둔다)
  const floor = {
    "autodesign.design-and-apply": 10 * 60_000, "verify.run": 180_000, "sim.run": 300_000,
    "influence.evaluate": 90_000, "influence.prescribe": 300_000, "aircraft.derive-de-trim": 180_000,
    "influence.diagnose": 30_000, "influence.screen": 30_000,
  };
  const all = STEPS.flatMap((s) => s.actions);
  for (const [k, min] of Object.entries(floor)) {
    const a = all.find((x) => refKey(x) === k);
    assert.ok(a, `단계 표에 ${k}가 없다`);
    assert.ok(actionTimeout(a) >= min, `${k}: ${actionTimeout(a)} ms < ${min} ms`);
  }
});

test("기다림 시계 — 경과가 오면 다시 세고, 조용해지면 멈추고, 전체 상한이 있다", () => {
  const a = acts("sim")[1];
  const T = actionTimeout(a);
  assert.equal(waitVerdict(a, { startedAt: 0, lastEventAt: 0, now: T - 1 }), null);
  assert.equal(waitVerdict(a, { startedAt: 0, lastEventAt: 0, now: T }), "idle");
  // 상한 직전에 경과가 왔다 — 그로부터 다시 센다
  assert.equal(waitVerdict(a, { startedAt: 0, lastEventAt: T - 10, now: T + 10 }), null);
  // 경과가 계속 와도 전체 상한에서 멈춘다
  assert.equal(waitVerdict(a, { startedAt: 0, lastEventAt: CAP_FACTOR * T - 1, now: CAP_FACTOR * T }), "cap");
  assert.match(waitText(a, "idle"), new RegExp(`「sim」 탭이 ${Math.round(T / 1000)} s 동안 「run」`));
  assert.match(waitText(a, "cap"), new RegExp(`${Math.round((CAP_FACTOR * T) / 1000)} s 안에 「run」`));
});

// ── 선행 조건 ────────────────────────────────────────────────────────────────

test("선행 조건 — 기체가 쇼케이스가 아니면 준비부터, 앞 결과가 없으면 그 단계 이름", () => {
  const s = emptyState();
  assert.deepEqual(preconditionNotes(at("prepare"), s, { selectedId: null }), []);
  const n1 = preconditionNotes(at("trim"), s, { selectedId: EXAMPLE_ID });
  assert.equal(n1.length, 1);
  assert.match(n1[0], /준비/);
  assert.deepEqual(preconditionNotes(at("trim"), s, { selectedId: SHOWCASE_ID }), []);
  const n2 = preconditionNotes(at("world"), s, { selectedId: SHOWCASE_ID });
  assert.equal(n2.length, 1);
  assert.match(n2[0], /시뮬레이션/);
  const done = { ...s, states: { sim: { state: "done", lines: [] } } };
  assert.deepEqual(preconditionNotes(at("world"), done, { selectedId: SHOWCASE_ID }), []);
});

// ── 진행 규칙 ────────────────────────────────────────────────────────────────

test("advance — 단계 안에서는 다음 동작, 끝나면 다음 단계, 한 단계 모드는 거기서 멈춘다", () => {
  const i = at("aircraft");
  let r = advance({ cursor: { step: i, sub: 0 }, outcome: "done", mode: "all", pause: false, failing: false });
  assert.deepEqual(r, { cursor: { step: i, sub: 1 }, stepDone: false, failing: false, go: true, finished: false });
  r = advance({ cursor: { step: i, sub: 3 }, outcome: "done", mode: "all", pause: false, failing: false });
  assert.deepEqual(r, { cursor: { step: i + 1, sub: 0 }, stepDone: true, failing: false, go: true, finished: false });
  r = advance({ cursor: { step: i, sub: 3 }, outcome: "done", mode: "one", pause: false, failing: false });
  assert.equal(r.go, false);
  assert.deepEqual(r.cursor, { step: i + 1, sub: 0 }, "커서는 다음 단계로 — ▶가 거기서 잇는다");
  r = advance({ cursor: { step: i, sub: 0 }, outcome: "done", mode: "one", pause: false, failing: false });
  assert.equal(r.go, true, "한 단계 모드도 그 단계의 나머지 동작은 돈다");
});

test("advance — 일시정지는 지금 동작을 마치고 멈춘다(단계 한가운데여도 커서를 거기 둔다)", () => {
  const i = at("aircraft");
  const r = advance({ cursor: { step: i, sub: 1 }, outcome: "done", mode: "all", pause: true, failing: false });
  assert.deepEqual(r.cursor, { step: i, sub: 2 });
  assert.equal(r.go, false);
});

test("advance — 실패하면 남은 동작은 건너뛰되 always(복원)는 돌고, 자동 재생은 멈춘다", () => {
  const i = at("influence");
  let r = advance({ cursor: { step: i, sub: 3 }, outcome: "failed", mode: "all", pause: false, failing: false });
  assert.deepEqual(r.cursor, { step: i, sub: 7 }, "결함 주입 실패 → 곧장 복원");
  assert.equal(r.failing, true);
  assert.equal(r.go, true, "복원은 돈다");
  r = advance({ cursor: { step: i, sub: 7 }, outcome: "done", mode: "all", pause: false, failing: true });
  assert.equal(r.stepDone, true);
  assert.equal(r.go, false, "실패한 단계 뒤에서 자동 재생이 멈춘다");
  assert.deepEqual(r.cursor, { step: i + 1, sub: 0 });
});

test("advance — 건너뜀은 실패가 아니다(초안 없이 실행으로 간다)", () => {
  const i = at("sim");
  const r = advance({ cursor: { step: i, sub: 0 }, outcome: "skipped", mode: "all", pause: false, failing: false });
  assert.deepEqual(r.cursor, { step: i, sub: 1 });
  assert.equal(r.failing, false);
});

test("advance — 마지막 단계 뒤는 끝(커서 = 단계 수)", () => {
  const n = STEPS.length;
  const r = advance({ cursor: { step: n - 1, sub: 0 }, outcome: "skipped", mode: "all", pause: false, failing: false });
  assert.deepEqual(r.cursor, { step: n, sub: 0 });
  assert.equal(r.finished, true);
  assert.equal(r.go, false);
});

test("단계 상태 — 실패가 하나라도 있으면 실패, 전부 건너뜀이면 건너뜀, 안내 줄은 세지 않는다", () => {
  assert.equal(stepState([{ tone: "ok" }, { tone: "skip" }]), "done");
  assert.equal(stepState([{ tone: "skip" }]), "skipped");
  assert.equal(stepState([{ tone: "note" }, { tone: "skip" }]), "skipped");
  assert.equal(stepState([{ tone: "ok" }, { tone: "fail" }, { tone: "ok" }]), "failed");
  assert.equal(stepState([{ tone: "note" }]), "done");
});

// ── 기록 ─────────────────────────────────────────────────────────────────────

test("완료 줄은 탭 summary 그대로 — 새 해설을 붙이지 않는다", () => {
  const a = acts("trim")[0];
  assert.deepEqual(lineFor(a, { status: "done", summary: "15 케이스 — 통과 13 · 실속 근접 2" }),
    { text: "일괄 트림 — 15 케이스 — 통과 13 · 실속 근접 2", tone: "ok" });
  assert.deepEqual(lineFor(a, { status: "done" }), { text: "일괄 트림", tone: "ok" });
  assert.deepEqual(lineFor(a, { status: "skipped", reason: "키 없음" }),
    { text: "일괄 트림 — 건너뜀: 키 없음", tone: "skip" });
  assert.deepEqual(lineFor(a, { status: "failed", error: "422" }),
    { text: "일괄 트림 — 실패: 422", tone: "fail" });
  const long = lineFor(a, { status: "done", summary: "가".repeat(500) });
  assert.ok(long.text.length <= LINE_MAX);
  assert.ok(long.text.endsWith("…"));
});

test("판정 읽기·기대 대조 — 판정을 모르면 말하지 않는다", () => {
  assert.equal(verdictOf({ data: { verdict: "fail" } }), "FAIL");
  assert.equal(verdictOf({ data: { pass: true } }), "PASS");
  assert.equal(verdictOf({ data: {} }), null);
  assert.equal(verdictOf(null), null);
  // 영향성 평가 보고의 모양 — verdict가 없으면 hard_fail(불)로
  assert.equal(verdictOf({ data: { hard_fail: true } }), "FAIL");
  assert.equal(verdictOf({ data: { hard_fail: false } }), "PASS");
  assert.equal(verdictOf({ data: { hard_fail: null } }), null, "판정 불가는 판정이 아니다");
  assert.equal(verdictOf({ data: { verdict: "PASS", hard_fail: true } }), "PASS", "verdict가 먼저");
  assert.equal(expectNote(acts("influence")[6], { data: { hard_fail: true } }), "기대 판정 PASS — 실제 FAIL");
  const fa = acts("influence")[4];
  assert.equal(expectNote(fa, { data: { verdict: "FAIL" } }), null);
  assert.equal(expectNote(fa, { data: { verdict: "PASS" } }), "기대 판정 FAIL — 실제 PASS");
  assert.equal(expectNote(fa, { data: {} }), null);
  assert.equal(expectNote(acts("trim")[0], { data: { verdict: "PASS" } }), null);
});

test("applyOutcome — 줄·참조를 적고 단계가 끝나면 상태를 모은다", () => {
  let s = beginStep(emptyState(), at("sim"), ["먼저 무엇"]);
  assert.equal(s.states.sim.state, "running");
  assert.deepEqual(s.cursor, { step: at("sim"), sub: 0 });
  let r = applyOutcome(s, { status: "skipped", reason: "키 없음" }, { mode: "all", pause: false });
  s = r.state;
  assert.equal(s.refs["sim.draft"].ok, false);
  assert.equal(s.states.sim.state, "running");
  r = applyOutcome(s, { status: "done", summary: "접지 12 s", resultId: "sim1" }, { mode: "all", pause: false });
  s = r.state;
  assert.deepEqual(s.refs["sim.run"], { ok: true, resultId: "sim1" });
  r = applyOutcome(s, { status: "done", summary: "포화 0 %" }, { mode: "all", pause: false });
  s = r.state;
  assert.equal(s.states.sim.state, "done");
  assert.deepEqual(s.states.sim.lines.map((l) => l.tone), ["note", "skip", "ok", "ok"]);
  assert.deepEqual(s.cursor, { step: at("world"), sub: 0 });
  assert.equal(r.go, true);
});

test("applyOutcome — 기대와 다른 판정은 안내 줄로 남는다(실패로 바꾸지 않는다)", () => {
  let s = beginStep(emptyState(), at("influence"));
  s = { ...s, cursor: { step: at("influence"), sub: 4 } };
  const { state } = applyOutcome(s, { status: "done", summary: "PASS", data: { verdict: "PASS" } },
    { mode: "all", pause: false });
  assert.deepEqual(state.states.influence.lines.map((l) => l.tone), ["ok", "note"]);
  assert.match(state.states.influence.lines[1].text, /기대 판정 FAIL/);
});

test("applyOutcome — 결과에 딸린 안내(notes)는 안내 줄로", () => {
  const s = beginStep(emptyState(), at("world"));
  const { state } = applyOutcome(s, { status: "done", summary: "3D 재생", notes: ["교신 없음 — 키 없음"] },
    { mode: "one", pause: false });
  assert.deepEqual(state.states.world.lines.map((l) => l.tone), ["ok", "note"]);
  assert.equal(state.states.world.state, "done");
});

test("중단·끊김 — 단계는 대기로 돌아가고 사유 줄이 남는다", () => {
  let s = beginStep(emptyState(), at("world"));
  s = interruptStep(s, "가상환경을 떠나 멈췄다");
  assert.equal(s.states.world.state, "pending");
  assert.deepEqual(s.cursor, { step: at("world"), sub: 0 });
  assert.equal(s.states.world.lines.at(-1).tone, "note");
  let c = beginStep(emptyState(), at("influence"));
  c = { ...c, cursor: { step: at("influence"), sub: 3 }, failing: true };
  c = cancelStep(c);
  assert.equal(c.states.influence.state, "pending");
  assert.deepEqual(c.cursor, { step: at("influence"), sub: 0 });
  assert.equal(c.failing, false);
  assert.match(c.states.influence.lines.at(-2).text, /중단/);
  assert.match(c.states.influence.lines.at(-1).text, /문서 게인 복원/, "뒷정리가 안 돈 사실을 말한다");
  const t = cancelStep(beginStep(emptyState(), at("trim")));
  assert.match(t.states.trim.lines.at(-1).text, /중단/);
});

test("중단의 뒷정리 — 결함 주입에 닿은 뒤에만 문서 게인 복원을 진행기가 대신한다", () => {
  const inf = acts("influence");
  const fault = inf.findIndex((a) => a.action === "fault");
  const restore = inf.findIndex((a) => a.action === "restore");
  assert.deepEqual(inf.filter((a) => a.dirties).map(refKey), ["gains.fault"], "작업 사본을 더럽히는 동작은 결함 주입 하나");
  assert.equal(STEPS.flatMap((s) => s.actions).filter((a) => a.dirties).length, 1);
  const at_ = (sub) => ({ ...beginStep(emptyState(), at("influence")), cursor: { step: at("influence"), sub } });
  // 결함 주입 전(진단·선별·기준 평가) — 작업 사본을 건드리지 않았다. 사람이 적용해 둔 작업 사본을 지우지 않는다
  for (let sub = 0; sub < fault; sub += 1) assert.deepEqual(cancelCleanup(at_(sub)), [], `sub ${sub}`);
  // 결함 주입 중(도는 중 — 탭이 곧 실을 수 있다)부터 복원 중까지 — 복원 동작을 돌려준다
  for (let sub = fault; sub <= restore; sub += 1) {
    assert.deepEqual(cancelCleanup(at_(sub)).map(refKey), ["gains.restore"], `sub ${sub}`);
  }
  assert.deepEqual(cancelCleanup(beginStep(emptyState(), at("trim"))), []);
  assert.deepEqual(cancelCleanup({ ...emptyState(), cursor: { step: STEPS.length, sub: 0 } }), [], "끝 커서");
});

test("중단 줄 — 진행기가 작업 사본을 비웠으면 그렇다고, 이미 비었으면 그렇다고, 못 했으면 안 돈 사실을", () => {
  const at_ = (sub) => ({ ...beginStep(emptyState(), at("influence")), cursor: { step: at("influence"), sub } });
  const done = cancelStep(at_(5), { restored: ["gainTables", "gainTablesSource"] });
  const last = done.states.influence.lines.at(-1);
  assert.equal(last.tone, "note");
  assert.match(last.text, /문서 게인 복원/);
  assert.ok(last.text.includes(workingCopyLine(["gainTables"])), "게인 탭 restore 보고와 같은 말");
  assert.match(last.text, /중단하며/);
  assert.doesNotMatch(last.text, /돌지 않았다/);
  assert.match(done.states.influence.lines.at(-2).text, /중단함/);
  assert.equal(done.states.influence.state, "pending");
  assert.deepEqual(done.cursor, { step: at("influence"), sub: 0 });
  const empty = cancelStep(at_(4), { restored: [] }).states.influence.lines.at(-1).text;
  assert.ok(empty.includes(workingCopyLine([])), empty);
  // 비우지 못했다(진행기가 부르지 않음) — 종전처럼 안 돈 사실
  assert.match(cancelStep(at_(5)).states.influence.lines.at(-1).text, /「문서 게인 복원」가 돌지 않았다/);
  // 결함 주입 전 중단 — 뒷정리 줄 없이 중단 줄만
  const early = cancelStep(at_(1), { restored: null });
  assert.match(early.states.influence.lines.at(-1).text, /중단함/);
  assert.equal(early.states.influence.lines.filter((l) => /문서 게인 복원/.test(l.text)).length, 0);
});

test("탭 쪽 멈춤 확인 — 진행기가 끝낸 실행(showcaseBusy 거짓)만 멈춘다", () => {
  assert.match(haltReason(false), /쇼케이스가 중단됐다/);
  // 한 번도 안 돈 상태(undefined·null)와 도는 중(true)은 멈춤이 아니다 — 투어·버튼 경로를 막지 않는다
  for (const v of [true, undefined, null]) assert.equal(haltReason(v), null, String(v));
});

// ── 표시 ─────────────────────────────────────────────────────────────────────

test("행 모델 — 상태 이름·지금 커서·줄", () => {
  let s = beginStep(emptyState(), at("trim"));
  s = applyOutcome(s, { status: "done", summary: "15 케이스" }, { mode: "one", pause: false }).state;
  const rows = rowsModel(s);
  assert.equal(rows.length, STEPS.length);
  assert.equal(rows[at("trim")].state, "done");
  assert.equal(rows[at("trim")].stateLabel, STATE_LABEL.done);
  assert.equal(rows[at("gains")].current, true);
  assert.equal(rows[0].state, "pending");
  assert.deepEqual(rows[0].lines, []);
});

test("단추 글자 — 돌 때만 위치를 단다", () => {
  const s = { ...emptyState(), cursor: { step: 3, sub: 0 } };
  assert.equal(fabLabel(s, false), "◆ 쇼케이스");
  assert.equal(fabLabel(s, true), `◆ 쇼케이스 · 4/${STEPS.length}`);
});

test("설치 요약 — 서버 응답의 id·리비전·동작으로만", () => {
  assert.equal(installSummary({ id: "showcase-delta", revision: 3, action: "reset", volatile: false }),
    "showcase-delta r3 · 패키지 문서로 초기화");
  assert.equal(installSummary({ id: "showcase-delta", revision: 1, action: "created", volatile: true }),
    "showcase-delta r1 · 새로 설치 · 휘발 저장소");
  assert.equal(installSummary({ id: "x", revision: 2, action: "odd" }), "x r2 · odd");
});

// ── 보관 형식 (sessionStorage) ───────────────────────────────────────────────

test("보관 — 왕복하면 같은 상태, 진행 중 단계는 대기로 풀린다", () => {
  let s = beginStep(emptyState(), at("prepare"));
  s = applyOutcome(s, { status: "done", summary: "showcase-delta r1" }, { mode: "all", pause: false }).state;
  s = withResume(s, { mode: "all", now: 1000, expectId: SHOWCASE_ID });
  const back = decodeState(encodeState(s));
  assert.deepEqual(back, s);
  const mid = beginStep(emptyState(), at("trim"));
  const b2 = decodeState(encodeState(mid));
  assert.equal(b2.states.trim.state, "pending", "다시 읽기가 끊은 단계는 진행 중이 아니다");
  assert.equal(JSON.parse(encodeState(s)).v, STATE_VERSION);
});

test("보관 — 쓰레기·다른 판·깨진 칸을 견딘다", () => {
  for (const raw of [null, "", "{", "[]", "42", '{"v":999}', JSON.stringify({ v: STATE_VERSION, cursor: "x" })]) {
    const d = decodeState(raw);
    assert.deepEqual(d.cursor, { step: 0, sub: 0 }, `raw=${raw}`);
    assert.deepEqual(d.states, {});
  }
  const bad = JSON.stringify({
    v: STATE_VERSION,
    cursor: { step: 3, sub: 99 },
    states: {
      trim: { state: "done", lines: [{ text: "ok", tone: "ok" }, { text: 5, tone: "ok" }, { text: "y", tone: "zz" }] },
      nope: { state: "done", lines: [] },
      gains: { state: "weird", lines: "no" },
    },
    refs: { "sim.run": { ok: true, resultId: "r1" }, "bad key!": { ok: true }, "trim.run": { ok: "yes", resultId: 7 } },
    resumeMode: "yes",
    failing: 1,
    resumeAt: "soon",
    resumeId: "bad id!",
  });
  const d = decodeState(bad);
  assert.deepEqual(d.cursor, { step: 3, sub: 0 }, "없는 동작 번호는 단계 처음으로");
  assert.deepEqual(d.states.trim.lines, [{ text: "ok", tone: "ok" }]);
  assert.equal(d.states.nope, undefined);
  assert.deepEqual(d.states.gains, { state: "pending", lines: [] });
  assert.deepEqual(d.refs, { "sim.run": { ok: true, resultId: "r1" }, "trim.run": { ok: false, resultId: null } });
  assert.equal(d.resumeMode, null);
  assert.equal(d.failing, false);
  assert.equal(d.resumeAt, null);
  assert.equal(d.resumeId, null);
  const end = decodeState(JSON.stringify({ v: STATE_VERSION, cursor: { step: STEPS.length, sub: 0 } }));
  assert.deepEqual(end.cursor, { step: STEPS.length, sub: 0 }, "끝 커서는 유효하다");
  const over = decodeState(JSON.stringify({ v: STATE_VERSION, cursor: { step: 99, sub: 0 } }));
  assert.deepEqual(over.cursor, { step: 0, sub: 0 });
});

test("이어 달리기 — 다시 읽기 직후 창 안에서만, 남긴 모드로", () => {
  const s = withResume(emptyState(), { mode: "all", now: 10_000, expectId: SHOWCASE_ID });
  assert.deepEqual(reloadResume(s, 10_500), { fresh: true, mode: "all", expectId: SHOWCASE_ID });
  assert.deepEqual(reloadResume(s, 10_000 + RESUME_WINDOW_MS + 1), { fresh: false, mode: null, expectId: null },
    "오래된 흔적으로 되살아나지 않는다");
  assert.equal(reloadResume(s, 9_000).fresh, false, "미래 시각은 믿지 않는다");
  // 한 단계 모드의 한가운데(자동 설계 → 다시 읽기 → 결과 다시 열기)도 잇는다
  assert.equal(reloadResume(withResume(emptyState(), { mode: "one", now: 1 }), 2).mode, "one");
  // 멈출 자리(일시정지·한 단계 모드의 단계 끝) — 카드만 다시 연다
  const stop = reloadResume(withResume(emptyState(), { mode: null, now: 1 }), 2);
  assert.deepEqual(stop, { fresh: true, mode: null, expectId: null });
  assert.equal(withResume(emptyState(), { mode: "all", now: 1, expectId: "bad id!" }).resumeId, null);
  assert.deepEqual(clearResume(s), { ...s, resumeMode: null, resumeAt: null, resumeId: null });
  assert.equal(reloadResume(clearResume(s), 10_500).fresh, false, "한 번만 잇는다");
  const back = decodeState(encodeState(s));
  assert.deepEqual(reloadResume(back, 10_500), reloadResume(s, 10_500), "보관을 건너도 같다");
});

test("자동 설계 단계 — 반영 뒤 다시 읽고 결과를 다시 연다(한 단계 모드도 단계 끝까지 잇는다)", () => {
  const i = at("autodesign");
  for (const mode of ["one", "all"]) {
    let r = advance({ cursor: { step: i, sub: 0 }, outcome: "done", mode, pause: false, failing: false });
    assert.deepEqual([r.cursor, r.go], [{ step: i, sub: 1 }, true], `${mode}: 반영 → 다시 읽기`);
    r = advance({ cursor: { step: i, sub: 1 }, outcome: "done", mode, pause: false, failing: false });
    assert.deepEqual([r.cursor, r.go], [{ step: i, sub: 2 }, true], `${mode}: 다시 읽기 → 결과 열기 (다시 읽은 뒤 잇는다)`);
  }
  // 일시정지면 다시 읽기 전에 멈춘다 — ▶가 거기서 잇는다
  const p = advance({ cursor: { step: i, sub: 0 }, outcome: "done", mode: "all", pause: true, failing: false });
  assert.deepEqual([p.cursor, p.go], [{ step: i, sub: 1 }, false]);
  // 설계가 실패하면 다시 읽지 않는다(뒷정리 동작이 아니다)
  const f = advance({ cursor: { step: i, sub: 0 }, outcome: "failed", mode: "all", pause: false, failing: false });
  assert.equal(f.stepDone, true);
  assert.equal(f.go, false);
});

test("멈춘 뒤 — 단계 한가운데서 멈춘 행은 진행이 아니라 대기로 보인다(줄·커서는 그대로)", () => {
  let s = beginStep(emptyState(), at("blocks"));
  s = applyOutcome(s, { status: "done" }, { mode: "all", pause: true }).state;
  assert.equal(s.states.blocks.state, "running");
  const p = settleRunning(s);
  assert.equal(p.states.blocks.state, "pending");
  assert.deepEqual(p.cursor, { step: at("blocks"), sub: 1 });
  assert.equal(p.states.blocks.lines.length, 1);
  const done = applyOutcome(beginStep(emptyState(), at("trim")), { status: "done" }, { mode: "one", pause: false }).state;
  assert.deepEqual(settleRunning(done), done, "끝난 단계는 건드리지 않는다");
});

// ── 조립 원문 대조 (views/showcase.js는 테스트가 import하지 않는다 — 순서 규약만 원문으로 고정) ──────────

test("진행기는 끝 보고 구독을 탭 이동보다 먼저 건다 — 같은 해시의 동기 보고를 놓치지 않게", () => {
  const src = readFileSync(new URL("../views/showcase.js", import.meta.url), "utf8");
  const body = src.slice(src.indexOf("const doCue = async"), src.indexOf("const makeComms = async"));
  const sub = body.indexOf("awaitReport(");
  const nav = body.indexOf("goTo(`#${a.tab}`)");
  assert.ok(sub > 0 && nav > 0, "doCue 원문을 찾지 못했다");
  // 같은 해시면 goTo가 hashchange를 동기로 쏜다 — 탭이 렌더 안에서 곧바로 실패를 보고하면(첫 await 앞의
  // 사유 실패) 구독 전 보고는 사라지고 진행기는 동작 상한(처방 10 min)까지 기다렸다
  assert.ok(sub < nav, "awaitReport가 goTo보다 뒤에 있다");
  assert.equal(body.match(/goTo\(/g).length, 1, "doCue의 이동은 한 번");
});

test("[■ 중단]은 결함 주입 뒤면 작업 사본을 게인 restore와 같은 함수로 비우고 그 사실을 줄에 남긴다", () => {
  const src = readFileSync(new URL("../views/showcase.js", import.meta.url), "utf8");
  const body = src.slice(src.indexOf("const cancelRun = () =>"), src.indexOf("const unlockSpeech = () =>"));
  assert.ok(body.length > 0, "cancelRun 원문을 찾지 못했다");
  const busy = body.indexOf('store.set("showcaseBusy", false)');
  const clean = body.indexOf("sc.cancelCleanup(S)");
  const drop = body.indexOf("dropWorkingCopy(store)");
  const step = body.indexOf("sc.cancelStep(S, { restored })");
  assert.ok(busy > 0 && clean > 0 && drop > 0 && step > 0, "중단의 복원 배선이 없다");
  // 탭이 먼저 멈춰야(showcaseBusy 거짓 — 결함·처방이 작업 사본에 쓰지 않는다) 비운 뒤에 다시 써지지 않는다
  assert.ok(busy < drop, "작업 사본을 비운 뒤에 진행기 끝을 알린다 — 그 틈에 탭이 다시 쓴다");
  assert.ok(clean < drop && drop < step, "뒷정리 판단 → 비우기 → 줄 순서");
  assert.match(src, /import \{ dropWorkingCopy \} from "\.\.\/lib\/gainsync\.js";/);
});

// ── 부가 단계(LLM)의 실패 — 건너뜀처럼 이어 간다 (리뷰 1차 #0) ─────────────────────────

test("LLM 동작은 전부 부가(soft)이고, 부가 동작은 LLM뿐이다", () => {
  const all = STEPS.flatMap((s) => s.actions);
  assert.deepEqual(all.filter((a) => a.soft).map((a) => a.label), all.filter((a) => a.llm).map((a) => a.label));
  assert.ok(all.filter((a) => a.llm).every((a) => a.soft === true));
});

test("걸었는데 실패한 미션 초안은 실패 줄만 남기고 미션 실행으로 간다(초안 없이) — 자동 재생도 이어 간다", () => {
  // /llm/status는 설정만 본다 — 키 만료·429·백엔드 다운이면 초안 신호가 failed로 돌아온다
  let s = beginStep(emptyState(), at("sim"));
  let r = applyOutcome(s, { status: "failed", error: "LLM 429" }, { mode: "all", pause: false });
  s = r.state;
  assert.deepEqual(s.cursor, { step: at("sim"), sub: 1 }, "종전에는 단계를 실패로 끝내고 가상환경으로 넘어갔다");
  assert.equal(r.go, true);
  assert.equal(r.failing, false);
  assert.equal(s.failing, false);
  const draftLine = s.states.sim.lines.at(-1);
  assert.equal(draftLine.tone, "warn");
  assert.match(draftLine.text, /^미션 초안 — 부가 단계 실패\(없이 이어 간다\): LLM 429$/);
  // 미션 실행 인자 — 초안이 앉지 않았으니 초안 없이
  assert.deepEqual(resolveArgs(acts("sim")[1].args, s.refs), { useDraft: false });
  r = applyOutcome(s, { status: "done", summary: "접지 436.82 s", resultId: "sim1" }, { mode: "all", pause: false });
  r = applyOutcome(r.state, { status: "done", summary: "타면 3면" }, { mode: "all", pause: false });
  assert.equal(r.state.states.sim.state, "done", "시뮬은 돌았다 — 부가 단계 실패가 단계를 실패로 몰지 않는다");
  assert.deepEqual(r.state.cursor, { step: at("world"), sub: 0 });
  assert.equal(r.go, true, "가상환경으로 이어 간다");
  assert.equal(r.state.refs["sim.run"].resultId, "sim1");
});

test("소견서·질문도 부가 — 실패해도 자동 재생이 멈추지 않고, 부가 실패뿐인 단계는 실패로 보인다", () => {
  let r = applyOutcome(beginStep(emptyState(), at("results")), { status: "done", summary: "통과" },
    { mode: "all", pause: false });
  r = applyOutcome(r.state, { status: "failed", error: "백엔드 다운" }, { mode: "all", pause: false });
  assert.equal(r.go, true, "질문 단계로 간다");
  assert.equal(r.failing, false);
  assert.equal(r.state.states.results.state, "done");
  assert.equal(r.state.states.results.lines.at(-1).tone, "warn");
  const q = applyOutcome(beginStep(emptyState(), at("ask")), { status: "failed", error: "429" },
    { mode: "all", pause: false });
  assert.equal(q.finished, true);
  assert.equal(q.failing, false);
  assert.equal(q.state.states.ask.state, "failed", "한 일이 없다 — 완료로 위장하지 않는다");
  // 부가가 아닌 동작의 실패는 그대로 실패다
  const hard = applyOutcome(beginStep(emptyState(), at("sim")), { status: "failed", error: "x" },
    { mode: "all", pause: false });
  assert.equal(hard.state.cursor.sub, 0 + 1, "초안(부가)은 이어 간다");
  const run = applyOutcome({ ...beginStep(emptyState(), at("sim")), cursor: { step: at("sim"), sub: 1 } },
    { status: "failed", error: "422" }, { mode: "all", pause: false });
  assert.equal(run.failing, true);
  assert.equal(run.go, false);
  assert.equal(lineFor(acts("sim")[1], { status: "failed", error: "422" }).tone, "fail");
  assert.equal(stepState([{ tone: "warn" }, { tone: "ok" }]), "done");
  assert.equal(stepState([{ tone: "skip" }, { tone: "warn" }]), "failed");
  assert.equal(stepState([{ tone: "warn" }, { tone: "fail" }]), "failed");
});

// ── 결함 시연의 뒷정리 — 더럽히기 전 실패는 복원하지 않고, 멈춤은 결함 사본을 남기지 않는다 (#1·#2) ──────

test("결함 주입 전(진단·선별·기준 평가)의 실패는 문서 게인 복원을 돌리지 않는다 — 사람의 작업 사본을 지우지 않는다", () => {
  const inf = STEPS[at("influence")];
  const fault = inf.actions.findIndex((a) => a.dirties);
  const restore = inf.actions.findIndex((a) => a.always);
  for (let sub = 0; sub < fault; sub += 1) {
    const r = advance({ cursor: { step: at("influence"), sub }, outcome: "failed", mode: "all", pause: false,
      failing: false });
    assert.equal(r.stepDone, true, `sub ${sub}: 종전에는 곧장 복원(sub ${restore})으로 갔다`);
    assert.deepEqual(r.cursor, { step: at("influence") + 1, sub: 0 });
    assert.equal(r.go, false);
    assert.equal(nextInStep(inf, sub, true), -1);
    // 중단의 규칙과 같다
    assert.deepEqual(cancelCleanup({ ...emptyState(), cursor: { step: at("influence"), sub } }), []);
  }
  // 결함 주입 자신부터는 복원이 돈다(진행기가 결함 전에 작업 사본을 이미 비웠다)
  for (let sub = fault; sub < restore; sub += 1) {
    assert.equal(nextInStep(inf, sub, true), restore, `sub ${sub}`);
  }
  assert.equal(nextInStep(inf, 1, false), 2, "실패가 없으면 차례대로");
});

test("멈춤 뒤 정리 — 결함 주입 뒤에 멈추면 복원한 사실을 적고 단계 처음으로, 그 전이면 그대로(▶가 잇는다)", () => {
  const inf = at("influence");
  const fault = acts("influence").findIndex((a) => a.dirties);
  const at_ = (sub) => ({ ...beginStep(emptyState(), inf), cursor: { step: inf, sub } });
  for (let sub = fault; sub < acts("influence").length; sub += 1) {
    const s = stopStep(at_(sub), { restored: ["gainTables", "autopilotParams"] });
    assert.deepEqual(s.cursor, { step: inf, sub: 0 }, `sub ${sub}: 가운데서 이으면 되돌린 사본 위라 처방할 FAIL이 없다`);
    assert.equal(s.states.influence.state, "pending");
    const [head, line] = s.states.influence.lines.slice(-2).map((l) => l.text);
    assert.match(head, /결함 시연 한가운데서 멈췄다 — .*이 단계를 처음부터/);
    assert.equal(line, cleanupLine(acts("influence").at(-1), ["gainTables"], "멈추며"));
    assert.ok(line.includes(workingCopyLine(["gainTables"])), "게인 탭 restore 보고와 같은 말");
  }
  // 결함 주입 전·다른 단계·끝 커서 — 손대지 않는다
  for (const s of [at_(0), at_(fault - 1), beginStep(emptyState(), at("trim")),
    { ...emptyState(), cursor: { step: STEPS.length, sub: 0 } }]) {
    assert.equal(stopStep(s, { restored: [] }), s);
  }
  // 다시 읽기 뒤(메모리 store가 비었다) — 빈 목록으로 부르면 「이미 비어 있었다」
  assert.ok(stopStep(at_(5), { restored: [] }).states.influence.lines.at(-1).text.includes(workingCopyLine([])));
  // 중단 줄은 그대로(「중단하며」)
  assert.match(cancelStep(at_(5), { restored: [] }).states.influence.lines.at(-1).text, /중단하며 진행기가 대신/);
});

test("결함 주입 전 작업 사본 비움 — 비운 것이 있을 때만 줄을 남긴다", () => {
  assert.equal(faultBaseNote([]), null);
  assert.equal(faultBaseNote(null), null);
  assert.match(faultBaseNote(["gainTables", "autopilotParams"]), /결함은 문서 게인 위에/);
});

test("쇼케이스 진행기 뷰 — 결함 주입 직전에 작업 사본을 비우고(재주입 ×6·×6 방지), 멈추면 결함 사본을 거둔다 (배선 가드)", () => {
  const src = readFileSync(new URL("../views/showcase.js", import.meta.url), "utf8");
  const exec = src.slice(src.indexOf("const execAction = async"), src.indexOf("const hold = async"));
  assert.ok(exec.length > 0, "execAction 원문을 찾지 못했다");
  const drop = exec.indexOf("a.dirties ? [sc.faultBaseNote(dropWorkingCopy(store))]");
  const act = exec.indexOf("await runKind(a, token)");
  assert.ok(drop > 0 && act > 0 && drop < act, "결함 신호를 걸기 전에 비운다");
  const end = src.slice(src.indexOf("const endRun = () =>"), src.indexOf("/** mode \"all\""));
  assert.ok(end.length > 0, "endRun 원문을 찾지 못했다");
  const busy = end.indexOf('store.set("showcaseBusy", false)');
  const clean = end.indexOf("sc.cancelCleanup(S)");
  const dropE = end.indexOf("dropWorkingCopy(store)");
  const stop = end.indexOf("sc.stopStep(S, { restored })");
  assert.ok(busy > 0 && clean > busy && dropE > clean && stop > dropE, "멈춤의 복원 배선(중단과 같은 순서)");
  // 배너는 멈춘 까닭으로 — 손 이동 표지만으로 「일시정지」라 말하지 않는다(#3)
  assert.match(end, /sc\.stopBanner\(cause, manual\)/);
  assert.doesNotMatch(end, /if \(manual\) banner/);
  // 다시 읽은 뒤 결함 시연 한가운데 커서는 처음으로
  const mount = src.slice(src.indexOf("export function mount()"), src.indexOf("let open = false;"));
  assert.match(mount, /if \(sc\.cancelCleanup\(S\)\.length\) \{\s*S = sc\.stopStep\(S, \{ restored: \[\] \}\);/);
  // 복원 신호가 실패하면 진행기가 같은 함수로 대신한다
  assert.match(src, /outcome\.status === "failed" && sc\.refKey\(a\) === "gains\.restore"/);
});

// ── 멈춘 까닭과 배너 (#3) ───────────────────────────────────────────────────────

test("멈춘 까닭 — 실패·끝·한 단계 끝은 일시정지가 아니다(손 이동과 겹쳐도)", () => {
  const i = at("trim");
  // 리뷰 재현: 트림이 도는 사이 손으로 탭을 옮겼다(pause) → 잡이 실패로 보고
  const failed = applyOutcome(beginStep(emptyState(), i), { status: "failed", error: "잡 오류" },
    { mode: "all", pause: true });
  assert.equal(stopCause({ outcome: "failed", r: failed, mode: "all", pause: true }), "failed");
  assert.equal(stopBanner("failed", true), null, "실패를 「일시정지 — ▶로 이어서」로 가리지 않는다");
  const one = applyOutcome(beginStep(emptyState(), i), { status: "done" }, { mode: "one", pause: true });
  assert.equal(stopCause({ outcome: "done", r: one, mode: "one", pause: true }), "step");
  assert.equal(stopBanner("step", true), null);
  const fin = applyOutcome(beginStep(emptyState(), at("ask")), { status: "skipped", reason: "키 없음" },
    { mode: "all", pause: true });
  assert.equal(stopCause({ outcome: "skipped", r: fin, mode: "all", pause: true }), "finished");
  assert.equal(stopBanner("finished", true), null);
  // 정말 멈춤 때문에 — 단계 한가운데·단계 끝(자동 재생)·머무는 사이·끊김
  const mid = applyOutcome(beginStep(emptyState(), at("aircraft")), { status: "done" }, { mode: "all", pause: true });
  assert.equal(stopCause({ outcome: "done", r: mid, mode: "all", pause: true }), "paused");
  const endAll = applyOutcome(beginStep(emptyState(), i), { status: "done" }, { mode: "all", pause: true });
  assert.equal(stopCause({ outcome: "done", r: endAll, mode: "all", pause: true }), "paused");
  assert.equal(stopCause({ outcome: "done", r: { go: true }, mode: "all", dwellCut: true }), "paused");
  assert.equal(stopCause({ outcome: "interrupted", mode: "all" }), "interrupted");
  assert.match(stopBanner("paused", true), /탭을 손으로 옮겨 일시정지했습니다 — ▶로 이어서/);
  assert.match(stopBanner("interrupted", true), /일시정지/);
  assert.equal(stopBanner("paused", false), null, "⏸ 단추로 멈춘 것은 배너가 없다(종전과 같다)");
});

// ── 머묾 (e2e D1) ────────────────────────────────────────────────────────────

test("동작 뒤 머묾 — 그림 동작은 길게, 장부 동작은 0, 끝내지 못한 동작은 0", () => {
  const done = { status: "done" };
  const byKey = (k) => STEPS.flatMap((s) => s.actions).find((a) => refKey(a) === k);
  for (const k of ["aircraft.aero", "aircraft.stability", "envelope.vn", "envelope.scan", "margins.run",
    "gains.overview", "trim.run", "autodesign.open", "sim.run", "autocode.overview", "verify.run", "results.open"]) {
    assert.equal(dwellFor(byKey(k), done), FIGURE_DWELL_MS, k);
  }
  for (const k of ["aircraft.overview", "aircraft.seed-basis", "gains.evaluate", "influence.diagnose",
    "influence.evaluate", "gains.fault", "influence.prescribe", "flow.overview", "sim.duty"]) {
    assert.equal(dwellFor(byKey(k), done), DWELL_MS, k);
  }
  // 장부 — 설치·다시 읽기·복원, 곧 다시 읽기가 지울 반영, 제 안에서 머무는 이동·재생
  for (const k of ["install", "reload", "gains.restore", "autodesign.design-and-apply", "nav", "world"]) {
    assert.equal(dwellFor(byKey(k), done), 0, k);
  }
  assert.ok(NAV_DWELL_MS > 0, "이동 동작은 제 안에서 머문다");
  for (const st of ["skipped", "failed", "interrupted"]) {
    assert.equal(dwellFor(byKey("margins.run"), { status: st }), 0, st);
  }
  assert.ok(DWELL_MS >= 2000 && FIGURE_DWELL_MS > DWELL_MS, "청중이 읽을 틈");
  // 한 판의 머묾 합(LLM 없이 — 마지막 동작 뒤는 멈출 자리라 머물지 않는다)이 2분을 넘지 않는다
  const all = STEPS.flatMap((s) => s.actions).filter((a) => !a.llm);
  const total = all.slice(0, -1).reduce((sum, a) => sum + dwellFor(a, done), 0);
  assert.ok(total <= 120_000, `머묾 합 ${total} ms`);
});

test("쇼케이스 진행기 뷰 — 다음 동작이 이어질 때만 머물고, 머무는 사이 멈춤을 받는다 (배선 가드)", () => {
  const src = readFileSync(new URL("../views/showcase.js", import.meta.url), "utf8");
  const loop = src.slice(src.indexOf("const start = async"), src.indexOf("const pauseRun = () =>"));
  assert.ok(loop.length > 0, "start 원문을 찾지 못했다");
  const go = loop.indexOf("if (!r.go) {");
  const dwell = loop.indexOf("sc.dwellFor(a, outcome)");
  const hold = loop.indexOf("await hold(ms, token)");
  assert.ok(go > 0 && dwell > go && hold > dwell, "멈출 자리(go 거짓)를 먼저 가르고 머문다");
  const h = src.slice(src.indexOf("const hold = async"), src.indexOf("// ── 실행 제어"));
  assert.match(h, /run\.pause\) return false/, "⏸·손 이동이 머묾을 끊는다");
});

// ── 줄 자르기 (e2e D16) ──────────────────────────────────────────────────────

test("줄 자르기 — 구절 경계에서 끊고 전량은 툴팁(full)에", () => {
  // e2e의 마진 맵 줄 모양 — 종전에는 「(전 칸…」로 구절 한가운데서 잘렸다
  const margins = "PM 최악 -78.6° (pitch_q @ M0.12_h3000_f50) · GM 최악 -9.7 dB (roll_p @ M0.18_h3000_f50) · "
    + "FQ 최악 Level 2 (roll_p @ M0.18_h200_f10) · 전 칸 20 — PM 음수 20칸 · GM 음수 3칸 (전 칸 기준 — 선형 모델)";
  const line = lineFor(acts("margins")[0], { status: "done", summary: margins });
  assert.ok(line.text.length <= LINE_MAX, String(line.text.length));
  assert.ok(line.text.endsWith(" …"), line.text);
  const body = line.text.slice(0, -2);
  assert.ok(`마진 맵 — ${margins}`.startsWith(body), "앞은 그대로");
  const next = `마진 맵 — ${margins}`.slice(body.length);
  assert.ok([" · ", " — ", " / ", "; ", ", ", " ("].some((sep) => next.startsWith(sep)), `구분자 앞에서 끊었다: ${next.slice(0, 8)}`);
  assert.equal(line.full, `마진 맵 — ${margins}`, "전량은 툴팁에");
  // 구분자가 너무 앞이면 글자 경계에서 — 거의 다 버리지 않는다
  const odd = `가 · ${"나".repeat(400)}`;
  assert.equal(clip(odd), `${odd.slice(0, LINE_MAX - 1)}…`);
  // 짧은 줄은 full이 없다(보관을 부풀리지 않는다)
  assert.deepEqual(lineFor(acts("trim")[0], { status: "done", summary: "20 케이스" }),
    { text: "일괄 트림 — 20 케이스", tone: "ok" });
  assert.equal(lineFor(acts("trim")[0], { status: "failed", error: "x".repeat(5000) }).full.length, LINE_FULL_MAX);
});

test("보관 — 잘린 줄의 전량(full)과 부가 실패(warn)가 왕복한다, 깨진 full은 버린다", () => {
  let s = beginStep(emptyState(), at("margins"));
  s = applyOutcome(s, { status: "done", summary: "가 · ".repeat(60) }, { mode: "one", pause: false }).state;
  let t = beginStep(s, at("sim"));
  t = applyOutcome(t, { status: "failed", error: "429" }, { mode: "all", pause: false }).state;
  assert.ok(s.states.margins.lines[0].full);
  const back = decodeState(encodeState(t));
  assert.deepEqual(back.states.margins, t.states.margins);
  assert.deepEqual(back.states.sim.lines, t.states.sim.lines, "진행 중 단계는 대기로 풀리되 줄(warn)은 그대로");
  const raw = JSON.stringify({ v: STATE_VERSION, states: { trim: { state: "done", lines: [
    { text: "a", tone: "ok", full: 7 }, { text: "b", tone: "warn", full: "" }, { text: "c", tone: "ok", full: "c 전량" }] } } });
  assert.deepEqual(decodeState(raw).states.trim.lines,
    [{ text: "a", tone: "ok" }, { text: "b", tone: "warn" }, { text: "c", tone: "ok", full: "c 전량" }]);
});

// ── 도는 중 카드 (e2e D14) ────────────────────────────────────────────────────

test("카드 행 — 도는 중 접힘은 지금 단계 한 행·마지막 한 줄, 멈추면 둘레(±1), 펼치면 전부", () => {
  let s = beginStep(emptyState(), at("aircraft"));
  for (const summary of ["개요", "공력", "안정성"]) {
    s = applyOutcome(s, { status: "done", summary }, { mode: "all", pause: false }).state;
  }
  const compact = cardRows(s, { expanded: false, running: true });
  assert.deepEqual(compact.map((r) => r.key), ["aircraft"]);
  assert.deepEqual(compact[0].lines.map((l) => l.text), ["정적 안정성 — 안정성"]);
  assert.equal(s.states.aircraft.lines.length, 3, "상태의 줄은 그대로 — 보이는 것만 줄인다");
  assert.deepEqual(cardRows(s, { expanded: false, running: false }).map((r) => r.key), ["prepare", "aircraft", "blocks"]);
  assert.equal(cardRows(s, { expanded: true, running: true }).length, STEPS.length);
  const end = { ...emptyState(), cursor: { step: STEPS.length, sub: 0 } };
  assert.deepEqual(cardRows(end, { expanded: false, running: true }).map((r) => r.key), ["ask"], "끝 커서는 마지막 단계");
  const fresh = cardRows(beginStep(emptyState(), at("trim")), { expanded: false, running: true });
  assert.deepEqual(fresh[0].lines, [], "줄이 없으면 빈 채로");
  // 단계 끝 동작 뒤 머무는 동안 — 커서는 이미 다음 단계(대기, 줄 없음)라 방금 끝낸 단계를 보인다
  const trimDone = applyOutcome(beginStep(emptyState(), at("trim")), { status: "done", summary: "20 케이스" },
    { mode: "all", pause: false }).state;
  assert.equal(trimDone.cursor.step, at("gains"));
  const held = cardRows(trimDone, { expanded: false, running: true, focus: at("trim") });
  assert.deepEqual(held.map((r) => [r.key, r.lines.map((l) => l.text)]), [["trim", ["일괄 트림 — 20 케이스"]]]);
  assert.deepEqual(cardRows(trimDone, { expanded: false, running: true, focus: 99 }).map((r) => r.key), ["gains"],
    "엉뚱한 focus는 커서로");
  const src = readFileSync(new URL("../views/showcase.js", import.meta.url), "utf8");
  assert.match(src, /sc\.cardRows\(S, \{ expanded, running: !!run, focus: run\?\.holdStep \?\? null \}\)/);
  assert.equal(resumeStep(s).states.aircraft.state, "running");
});

test("카드 — 끝난 뒤에도 접힘(마지막 두 단계·한 줄씩), 펴면 전부 · 중간 멈춤은 펼침", () => {
  let end = { ...emptyState(), cursor: { step: STEPS.length, sub: 0 } };
  end = { ...end, states: { ...end.states,
    results: { state: "done", lines: [{ text: "브리핑", tone: "ok" }, { text: "소견서 건너뜀", tone: "skip" }] } } };
  assert.equal(runEnded(end), true);
  const rows = cardRows(end, { expanded: false, running: false });
  assert.deepEqual(rows.map((r) => r.key), ["results", "ask"]);
  assert.deepEqual(rows[0].lines.map((l) => l.text), ["소견서 건너뜀"], "마지막 한 줄만");
  assert.equal(cardRows(end, { expanded: true, running: false }).length, STEPS.length, "[목록 펴기]로 전부");
  assert.equal(cardCompact(end, { running: false, expanded: false }), true, "끝 — 540 px로 펴지 않는다");
  assert.equal(cardCompact(end, { running: false, expanded: true }), false);
  const mid = beginStep(emptyState(), at("trim"));
  assert.equal(runEnded(mid), false);
  assert.equal(cardCompact(mid, { running: true, expanded: false }), true);
  assert.equal(cardCompact(mid, { running: false, expanded: false }), false, "중간 멈춤은 행을 고르는 자리");
  const src = readFileSync(new URL("../views/showcase.js", import.meta.url), "utf8");
  assert.match(src, /sc\.cardCompact\(S, \{ running: !!run, expanded \}\)/);
});

test("카드 목록 굴림 — 목록 안에서만(문서 굴림 금지: 탭의 부드러운 굴림을 끊었다)", () => {
  const box = { listTop: 100, listBottom: 300, scrollTop: 50 };
  assert.equal(listScrollTop({ ...box, itemTop: 150, itemBottom: 180 }), 50, "보이면 그대로");
  assert.equal(listScrollTop({ ...box, itemTop: 80, itemBottom: 110 }), 30, "위로 벗어나면 머리를 맞춘다");
  assert.equal(listScrollTop({ ...box, itemTop: 290, itemBottom: 330 }), 80, "아래로 벗어나면 바닥을 맞춘다");
  assert.equal(listScrollTop({ ...box, itemTop: 350, itemBottom: 600 }), 300, "목록보다 큰 행은 머리를");
  const src = readFileSync(new URL("../views/showcase.js", import.meta.url), "utf8");
  assert.doesNotMatch(src, /\.scrollIntoView\??\.?\(/, "진행기 카드는 문서를 굴리지 않는다");
});

// ── 3D 재생 배속 (e2e D19) ────────────────────────────────────────────────────

test("3D 재생 배속 — 교신이 없으면 1분 안팎에, 있으면 음성 게이트 안에서", () => {
  // S1 착륙 런: 정지 449.62 s + 여유 3 s(e2e) — 투어 2×는 3.8 min, 교신 없으면 10×로 45 s
  const S1 = 452.62;
  assert.equal(worldSpeedFor({ comms: false, durationS: S1 }), 10);
  assert.ok(S1 / worldSpeedFor({ comms: false, durationS: S1 }) <= WORLD_REPLAY_TARGET_S);
  assert.equal(worldSpeedFor({ comms: true, durationS: S1 }), SPEECH_GATE, "교신은 게이트 값까지만 — 넘으면 자막만");
  // 짧은 런은 느리게(투어 배속보다 느리게는 아니다) — 긴 런은 가장 빠른 칸
  assert.equal(worldSpeedFor({ comms: false, durationS: 90 }), TOUR_SPEED);
  assert.equal(worldSpeedFor({ comms: false, durationS: 250 }), 5);
  assert.equal(worldSpeedFor({ comms: false, durationS: 5000 }), 20);
  assert.equal(worldSpeedFor({ comms: true, durationS: 5000 }), SPEECH_GATE);
  // 길이를 모르면 게이트 값
  for (const d of [null, NaN, 0, -3]) assert.equal(worldSpeedFor({ comms: false, durationS: d }), SPEECH_GATE, String(d));
  // 고른 값은 늘 고르개의 칸이다 — 교신이 있으면 게이트 이하
  for (const comms of [true, false]) {
    for (const d of [10, 60, 120, 300, 452.62, 900, 1800, 7200]) {
      const v = worldSpeedFor({ comms, durationS: d });
      assert.ok(WORLD_SPEEDS.includes(v) && v >= TOUR_SPEED && (!comms || v <= SPEECH_GATE), `${comms} ${d} → ${v}`);
    }
  }
});

test("3D 재생 배속 칸은 가상환경 탭 고르개의 칸과 같다 (번들 경계 원문 대조)", () => {
  // 칸 밖의 값을 걸면 React <select>가 첫 칸(1×)을 보인 채 다른 배속으로 돈다
  const tab = readFileSync(new URL("../../world/src/ui/WorldTab.tsx", import.meta.url), "utf8");
  const m = tab.match(/aria-label="재생 배속"[\s\S]{0,200}?\{\[([\d,\s]+)\]\.map\(/)
    ?? tab.match(/\{\[([\d,\s]+)\]\.map\(\(v\) => <option/);
  assert.ok(m, "가상환경 탭 배속 고르개를 찾지 못했다");
  assert.deepEqual(m[1].split(",").map((x) => Number(x.trim())), [...WORLD_SPEEDS]);
  const comms = readFileSync(new URL("../../world/src/core/comms.ts", import.meta.url), "utf8");
  assert.match(comms, new RegExp(`export const SPEECH_MAX_SPEED = ${SPEECH_GATE};`));
});

test("재생 길이 — 끝 시각(정지 + 여유), 없으면 본문의 마지막 시각", () => {
  assert.equal(replayDurationS({ meta: { phases: { stop_t: 449.62 } }, t: [0, 500] }), 452.62);
  assert.equal(replayDurationS({ meta: { phases: { stop_t: null } }, t: [0, 100, 475] }), 475);
  assert.equal(replayDurationS({ meta: {}, t: [] }), null);
  assert.equal(replayDurationS(null), null);
  const src = readFileSync(new URL("../views/showcase.js", import.meta.url), "utf8");
  const w = src.slice(src.indexOf("const doWorld = async"), src.indexOf("const doAsk = async"));
  assert.match(w, /sc\.worldSpeedFor\(\{ comms: comms\.n > 0, durationS: sc\.replayDurationS\(replay\) \}\)/);
  assert.match(w, /speed, voice, endT: endTimeFor\(replay\)/, "건 배속을 가상환경에 넘긴다");
  assert.equal((w.match(/captionFor\("play", \{ lines: comms\.n, voice, speed \}\)/g) ?? []).length, 2,
    "줄·경과 캡션이 실제로 건 배속을 말한다");
  assert.doesNotMatch(w, /TOUR_SPEED/);
});


test("recordedCriteriaGap — 기록에서 뗀 목표가 문서에 없으면 말한다(v1.51 전 사본)", async () => {
  const { recordedCriteriaGap } = await import("./showcase.js");
  const rec = { n_mach: 7, targets: { zeta_sp: 0.9 } };
  assert.equal(recordedCriteriaGap(rec, { tuning: { targets: { zeta_sp: 0.9 } } }), "");
  const gap = recordedCriteriaGap(rec, { tuning: null });
  assert.match(gap, /zeta_sp 기록 0\.9 · 문서 없음/);
  assert.match(gap, /다시 설치/);
  assert.equal(recordedCriteriaGap({ n_mach: 7 }, {}), "");
});
