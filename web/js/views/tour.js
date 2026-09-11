/** 가이드 투어 (D1) — 문장 하나가 미션 → 시뮬 → 3D 재생 + 교신 → 착륙 요약이 된다.

조립·순서 제어 전용이다. 판단(단계·사전 판정·끝 시각·마무리·캡션)은 lib/tour.js,
요청 조립은 lib/simrequest.js(**시뮬 탭과 같은 한 벌**), 초안 정규화는
lib/missiondraft.js에 있다. 전역 body 크롬인 이유(views/ask.js 선례): 탭 전환은
`#view`만 갈아끼우므로, 탭을 넘나들며 순서를 쥐려면 라우트 밖에 살아야 한다.

인계 두 개:
- `tourSim` — 시뮬 탭이 **한 번 읽고 지운다**(wpDraft 규약). 투어가 이미 조립·제출한
  미션을 그 탭이 같은 표·진행바로 보여 준다. 조립이 한 벌이라 둘이 갈리지 않는다.
- `worldTour` — 가상환경이 **읽기만** 하고 수명은 이 모듈이 쥔다(끝·실패·취소에
  지운다). React effect에서 읽고 지우면 dev StrictMode 이중 마운트의 두 번째가 빈
  키를 본다. 되돌아오는 신호는 `worldTourState`(store.subscribe).

LLM 호출은 **초안 1 + 교신 1** 두 번뿐이다(사용자 결정) — 단계 해설은 이미 있는
산출물(초안 요약·모드 사슬·잡 진행률·교신 줄 수·착륙 요약)로 만든다.
*/

import { api, cancelJob, errorText, sleep, watchJob } from "../api.js";
import { clear, el } from "../dom.js";
import { normalizeDraft } from "../lib/missiondraft.js";
import { strideFor } from "../lib/replay.js";
import {
  applyActuatorSchema, appliedFrom, buildSimRequest, initialForm,
} from "../lib/simrequest.js";
import {
  TOUR_SPEED, captionFor, endTimeFor, finaleModel, precheck, stepperModel,
} from "../lib/tour.js";
import { store } from "../store.js";

let mounted = false;
let run = null;       // 진행 중 투어 (null = 없음) — token이 곧 유효성이다
let seq = 0;
let llm = null;       // /llm/status — **성공만 캐시**(콜드 스타트 첫 실패로 굳지 않게)
let statusErr = null;
let submitting = false; // await 앞 동기 플래그 — 유료 이중 제출 방지
let intent = "";

/** 가상환경이 재생을 시작했다고 말하지 않으면 사유와 함께 멈춘다 — 3D가 못 뜨거나
 *  결과 목록이 비면 투어가 영영 기다리게 되는 자리. */
const WATCHDOG_MS = 90_000;
/** 마무리를 열기 전에 말하던 교신이 끝나기를 기다리는 상한. */
const SPEAK_WAIT_MS = 8_000;

export function mount() {
  if (mounted) return; // 한 번만 — main.js 재호출 방어
  mounted = true;
  let open = false;
  let watchdog = null;

  const statusLine = el("p", { class: "hint", style: "margin:0 0 8px" });
  const input = el("input", {
    class: "tour-input",
    placeholder: "예: 발사해서 북쪽 4 km를 돌고 활주로에 착륙",
    oninput: (ev) => { intent = ev.target.value; },
    onkeydown: (ev) => { if (ev.key === "Enter") startClicked(); },
  });
  const startBtn = el("button", { class: "primary", onclick: () => startClicked() }, "시작");
  const bodyBox = el("div");
  const card = el("div", { class: "tour-card", hidden: true },
    el("div", { class: "tour-head" },
      el("strong", {}, "가이드 투어"),
      el("button", { class: "tour-close", title: "닫기", onclick: () => setOpen(false) }, "×")),
    statusLine, bodyBox);
  const fab = el("button", {
    class: "ask-fab tour-fab",
    title: "문장 하나로 미션·시뮬·3D 재생·착륙 요약까지 (서버 경유 LLM 2회)",
    "aria-expanded": "false",
  }, "▶ 투어");

  const live = (token) => run?.token === token;
  /** 이 run은 손대면 안 된다 — 없거나(중단·닫기) 이미 실패했다. 같은 술어가 fail·
   *  finish·구독자로 흩어져 리뷰가 한 자리씩 덧대 왔다(사본 금지) — 새 진입점이
   *  생겨도 이 한 줄만 부르면 빠뜨릴 자리가 없다. */
  const dead = () => !run || !!run.failedAt;
  /** 긴 대기(await)를 건널 때마다 묻는 것 — 이 토큰의 run이 **아직 그것이고 실패하지도
   *  않았나**. `live`만 물으면 실패가 찍힌 뒤에도 참이라, 선형 경로가 그대로 이어져
   *  유료 교신 호출이 한 번 더 나가고 죽은 런으로 `worldTour`를 다시 건다 (리뷰 지적) */
  const alive = (token) => live(token) && !dead();
  const clearWatchdog = () => { if (watchdog) { clearTimeout(watchdog); watchdog = null; } };

  // 이미 그 탭이면 hashchange가 안 난다 — main.js route()를 직접 다시 태운다
  // (route는 같은 뷰도 다시 render하므로 인계 키가 그때 소비된다)
  const goTo = (hash) => {
    if (location.hash === hash) window.dispatchEvent(new HashChangeEvent("hashchange"));
    else location.hash = hash;
  };

  const setOpen = (v) => {
    open = v;
    card.hidden = !v;
    fab.setAttribute("aria-expanded", v ? "true" : "false");
    if (v && llm == null) void loadStatus();
    paint();
    if (v && run == null) input.focus();
  };

  const loadStatus = async () => {
    try {
      llm = await api.get("/llm/status");
      statusErr = null;
    } catch (e) {
      // **실패는 캐시하지 않는다** — 이 위젯은 앱 수명 크롬이라 콜드 스타트(~1분)의
      // 첫 실패를 담아 두면 새로고침 전까지 투어가 죽는다 (질문 위젯과 같은 규약)
      llm = null;
      statusErr = `상태 조회 실패 — ${errorText(e)} · 카드를 다시 열면 재시도합니다.`;
    }
    paint();
  };

  const reset = () => {
    run = null;
    clearWatchdog();
    store.set("worldTour", null);
    // **인계도 거둔다** — 초안이 막혀 넘겨 둔 tourSim을 남기면, 한참 뒤 아무 이유로
    // 시뮬 탭을 연 사람의 표가 그 초안으로 통째로 바뀐다(그 사람은 투어를 닫았다).
    // 정리 경로 둘(중단·닫기)이 같은 것을 거둬야 한다 (리뷰 지적)
    store.set("tourSim", null);
    paint();
  };

  const cancelTour = () => {
    if (!run) return;
    const id = run.jobId;
    run = null; // 토큰 무효 — 늦게 온 결과·이벤트는 전부 버려진다
    clearWatchdog();
    store.set("worldTour", null);
    store.set("tourSim", null); // 아직 안 읽힌 인계도 거둔다
    if (id) cancelJob(id).catch(() => {}); // 서버 잡도 협조적으로 멈춘다
    paint();
  };

  const setStage = (stage, caption) => {
    if (dead()) return;
    run.stage = stage;
    if (caption != null) run.caption = caption;
    paint();
  };

  const fail = (stage, message, opts = {}) => {
    // **첫 사유가 남는다** — fail은 run.stage를 남겨 두므로 워치독이 fail("play")를
    // 부른 뒤에도 stage는 "play"다. 그 뒤 사용자가 탭을 옮기면 hashchange가 다시
    // fail을 불러 "재생을 시작하지 못했다"가 "탭을 떠나 멈췄다"로 덮인다 — 기계 탓이
    // 사용자 탓 문장으로 바뀐다 (리뷰 재현)
    if (dead()) return;
    run.stage = stage;
    run.failedAt = stage;
    run.error = message;
    run.fixable = !!opts.fixable;
    clearWatchdog();
    store.set("worldTour", null); // 가상환경에 걸어 둔 투어를 거둔다
    paint();
  };

  const armWatchdog = (token) => {
    clearWatchdog();
    watchdog = setTimeout(() => {
      if (!alive(token) || run.stage !== "play") return;
      fail("play", "가상환경이 재생을 시작하지 못했습니다 — 3D가 떴는지, 그 런이 "
        + "목록에 있는지 확인하십시오.");
    }, WATCHDOG_MS);
  };

  /** 교신 대본 — 실패해도 **투어를 멈추지 않는다**(사유를 달고 교신 없이 재생한다).
   *  방금 돈 런이라 기존 대본이 있을 수 없어 재사용 조회는 하지 않는다 — 그 몫은
   *  가상환경 탭의 캐시 조회다. */
  const makeComms = async (resultId, token) => {
    try {
      const sub = await api.post("/llm/comms", { result_id: resultId });
      if (alive(token)) run.jobId = sub.id; // [중단]이 이 잡을 취소할 수 있게
      const j = await watchJob(sub.id, () => {});
      if (j.status !== "done" || !j.result_id) throw new Error(j.error ?? `교신 ${j.status}`);
      const body = await api.get(`/results/${j.result_id}`);
      return { id: j.result_id, n: Array.isArray(body.lines) ? body.lines.length : 0 };
    } catch (e) {
      return { id: null, n: 0, failed: errorText(e) };
    }
  };

  const waitSpeechIdle = async () => {
    const synth = typeof window !== "undefined" ? window.speechSynthesis : null;
    if (!synth) return;
    const deadline = Date.now() + SPEAK_WAIT_MS;
    while (synth.speaking && Date.now() < deadline) await sleep(250);
  };

  const finish = async () => {
    if (dead()) return;
    const token = run.token;
    clearWatchdog();
    setStage("finale");
    await waitSpeechIdle(); // 카드가 마지막 교신을 자르지 않게
    // 생존 판정이 **토큰뿐이면** 기다리는 동안 들어온 fail()을 놓친다 — 토큰은 그대로라
    // 실패한 run에 "done"을 찍고 마무리 카드까지 연다 (리뷰 재현)
    if (!alive(token)) return;
    store.set("worldTour", null);
    run.stage = "done";
    setOpen(true); // 마무리는 닫아 뒀어도 보여 준다 — 투어의 결말이다
  };

  const startTour = async (text) => {
    if (run || submitting) return;
    submitting = true;
    const token = `tour${Date.now()}-${seq += 1}`;
    run = {
      token, stage: "draft", failedAt: null, error: null, fixable: false,
      caption: captionFor("draft", { intent: text }), warnings: [], commsNote: null,
      voiceNote: null, jobId: null, draft: null, resultId: null, finale: null,
    };
    paint();
    try {
      // ① 미션 초안 — LLM 1회
      const sub = await api.post("/llm/mission-draft", { intent: text });
      if (!alive(token)) return;
      run.jobId = sub.id;
      const dj = await watchJob(sub.id, () => {});
      if (!alive(token)) return;
      if (dj.status !== "done" || !dj.result_id) throw new Error(dj.error ?? `초안 ${dj.status}`);
      const dbody = await api.get(`/results/${dj.result_id}`);
      if (!alive(token)) return;
      const norm = normalizeDraft(dbody.draft);
      norm.model = dbody.model;
      run.draft = norm;
      const { blockers, warnings } = precheck(norm);
      run.warnings = warnings;
      if (blockers.length) {
        // 그대로는 422다 — 돌리지 않고 표에 앉혀 손으로 고치게 한다 (조용한 실패 금지)
        store.set("tourSim", { draft: norm, jobId: null, snapshot: null });
        fail("draft", `초안이 그대로는 실행되지 않습니다 — ${blockers.join(" · ")}`,
          { fixable: true });
        return;
      }

      // ② 폐루프 시뮬 — 시뮬 탭과 같은 조립(lib/simrequest.js)
      const applied = appliedFrom((k) => store.get(k));
      let schema = null;
      if (!applied.actuatorParams) {
        // 적용본이 없을 때만 스키마로 폴백을 고친다 — 시뮬 탭과 같은 규칙
        try {
          schema = await api.get("/registry/actuator/SecondOrderActuator/schema");
        } catch { /* 폴백으로 돈다 */ }
        if (!alive(token)) return;
      }
      let form = { ...initialForm(applied.actuatorParams), ...norm.runConditions };
      if (schema) form = applyActuatorSchema(form, schema);
      const { req, snapshot } = buildSimRequest(form, norm.modeRows, norm.wpRows, applied);
      const simSub = await api.post("/sim/run", req);
      if (!alive(token)) { cancelJob(simSub.id).catch(() => {}); return; }
      run.jobId = simSub.id;
      store.set("tourSim", { draft: norm, jobId: simSub.id, snapshot });
      goTo("#sim"); // 같은 미션의 표·지도·진행바를 보면서 기다린다
      const modes = norm.modeRows.map((r) => r.name);
      setStage("sim", captionFor("sim", { modes }));
      const sj = await watchJob(simSub.id, (j) => {
        // 캡션을 실제로 갱신하는 자리가 여기다(setStage가 아니라) — 통합한 술어를
        // 여기까지 밀지 않으면 실패한 run의 캡션이 계속 덮인다 (리뷰 지적)
        if (!alive(token)) return;
        run.caption = captionFor("sim", { modes, progress: j.progress });
        paint();
      });
      if (!alive(token)) return;
      if (sj.status !== "done" || !sj.result_id) throw new Error(sj.error ?? `시뮬 ${sj.status}`);
      run.resultId = sj.result_id;
      store.set("simResult", { id: sj.result_id });

      // ③ 재생 준비 — 교신 대본(LLM 2회차)과 재생 본문을 나란히.
      // stride는 시뮬 탭과 **같은 값**이라 두 화면의 착륙 요약 수치가 같다
      setStage("comms", captionFor("comms", {}));
      const [replay, comms] = await Promise.all([
        api.get(`/sim/${sj.result_id}/replay?stride=${strideFor(sj.total || 1)}`),
        makeComms(sj.result_id, token),
      ]);
      if (!alive(token)) return;
      run.finale = finaleModel(replay);
      if (comms.failed) run.commsNote = captionFor("comms", { failed: comms.failed });

      // ④ 3D 재생 — 가상환경이 조건을 보고 켠다 (수명은 이 모듈이 쥔다)
      const voice = typeof window !== "undefined" && "speechSynthesis" in window;
      store.set("worldTour", {
        token,
        resultId: sj.result_id,
        commsId: comms.id,
        speed: TOUR_SPEED,
        voice,
        endT: endTimeFor(replay), // 기체가 선 뒤의 빈 구간은 보이지 않는다
      });
      setStage("play", captionFor("play", { lines: comms.n, voice }));
      goTo("#world");
      armWatchdog(token);
      // ⑤ 마무리는 worldTourState "ended"가 연다 (store.subscribe 아래)
    } catch (e) {
      if (!alive(token)) return;
      fail(run.stage, errorText(e));
    } finally {
      submitting = false;
    }
  };

  const startClicked = () => {
    if (run || submitting) return; // 이미 도는 투어 — Enter 연타가 unlock 발화를 반복하지 않게
    const text = input.value.trim();
    if (!text) {
      statusErr = "무엇을 비행할지 한 문장으로 적으십시오.";
      paint();
      return;
    }
    // 브라우저 자동재생 정책 — 첫 발화가 **사용자 제스처 안**에 있어야 뒤의 교신
    // 음성이 허용된다(특히 Safari). 시작 신호를 겸한다.
    unlockSpeech();
    void startTour(text);
  };

  const unlockSpeech = () => {
    const synth = typeof window !== "undefined" ? window.speechSynthesis : null;
    if (!synth) return;
    try {
      const u = new SpeechSynthesisUtterance("가이드 투어를 시작합니다");
      u.lang = "ko-KR";
      synth.speak(u);
    } catch { /* 음성이 없어도 투어는 돈다 — 자막이 남는다 */ }
  };

  // ── 그리기 ────────────────────────────────────────────────────────────────
  const stepper = () => el("div", { class: "tour-steps" },
    stepperModel(run.stage, run.failedAt).map((s) =>
      el("span", { class: `tour-step ${s.state}` }, s.label)));

  const finaleView = (m) => (m.rows.length
    ? el("div", { class: "tour-rows" }, m.rows.map((r) => el("div", { class: "tour-row" },
        el("span", { class: "k" }, r.label),
        el("span", { class: "v" }, r.value),
        r.over ? el("span", { class: "flag bad" }, r.overLabel ?? "초과") : null,
        r.unjudged ? el("span", { class: "flag na" }, "미판정") : null,
        r.note ? el("span", { class: "hint" }, r.note) : null)))
    : el("p", { class: "hint" }, m.note));

  const paint = () => {
    clear(bodyBox);
    clear(statusLine);
    clear(fab).append(run ? "▶ 투어 · 진행 중" : "▶ 투어");
    if (run == null) {
      const avail = !!llm?.available;
      statusLine.append(llm == null
        ? (statusErr ?? "서버 상태 확인 중…")
        : avail
          ? `${llm.model} — 초안·교신 두 번만 부릅니다 (해설은 결과로 만듭니다).`
          : (llm.reason ?? "사용할 수 없습니다."));
      input.disabled = !avail;
      startBtn.disabled = !avail || submitting;
      bodyBox.append(
        el("p", { class: "hint", style: "margin:0 0 8px" },
          "문장 하나로 미션을 만들고, 시뮬을 돌리고, 3D에서 교신과 함께 재생한 뒤 "
          + "착륙 요약까지 갑니다 — 화면이 단계마다 따라갑니다."),
        el("div", { class: "tour-row-input" }, input, startBtn),
      );
      return;
    }
    bodyBox.append(stepper());
    if (run.failedAt) {
      bodyBox.append(
        el("div", { class: "error-box", style: "margin-top:6px" }, run.error ?? "실패"),
        el("div", { class: "tour-actions" },
          run.fixable
            ? el("button", { class: "primary", onclick: () => goTo("#sim") },
                "시뮬 탭에서 고치기")
            : null,
          el("button", {
            // 시작과 **같은 길**로 보낸다 — 공백 검증·음성 unlock을 [다시]만 건너뛰면
            // 빈 문장으로 유료 잡이 돌거나 교신 음성이 정책에 막힌다
            onclick: () => { const t = intent; reset(); input.value = t; startClicked(); },
          }, "다시"),
          el("button", { onclick: reset }, "닫기")),
      );
      return;
    }
    if (run.stage === "done") {
      bodyBox.append(
        el("h3", { style: "margin:8px 0 6px; font-size:14px" }, "착륙 요약"),
        finaleView(run.finale ?? { rows: [], note: "재생 본문을 받지 못했습니다." }),
        run.commsNote ? el("p", { class: "hint", style: "margin:6px 0 0" }, run.commsNote) : null,
        el("div", { class: "tour-actions" },
          el("button", { class: "primary", onclick: () => goTo("#sim") }, "시뮬 탭에서 자세히"),
          el("button", { onclick: () => goTo("#results") }, "결과 탭"),
          el("button", { onclick: reset }, "새 투어")),
      );
      return;
    }
    bodyBox.append(
      el("p", { style: "margin:6px 0 4px" }, run.caption ?? ""),
      run.draft?.summary && run.stage !== "draft"
        ? el("p", { class: "hint", style: "margin:0 0 4px" }, run.draft.summary) : null,
      run.warnings.length
        ? el("p", { class: "hint", style: "margin:0 0 4px" }, `⚠ ${run.warnings.join(" · ")}`)
        : null,
      run.commsNote ? el("p", { class: "hint", style: "margin:0 0 4px" }, run.commsNote) : null,
      run.voiceNote ? el("p", { class: "hint", style: "margin:0 0 4px" }, run.voiceNote) : null,
      el("div", { class: "tour-actions" }, el("button", { onclick: cancelTour }, "중단")),
    );
  };

  // 가상환경이 돌려주는 신호 — 토큰이 다르면 지난 투어의 것이라 버린다
  store.subscribe((key, value) => {
    if (key !== "worldTourState" || !run || value?.token !== run.token) return;
    // 이미 실패로 끝난 투어 — 늦게 온 신호가 카드를 덮어쓰지 않는다. 워치독이 먼저
    // 울린 뒤 가상환경이 늦게 재생을 시작하면, 이 가드가 없을 때 카드는 "재생을
    // 시작하지 못했다"를 붙든 채 마무리까지 조용히 삼킨다 (리뷰 재현)
    if (dead()) return;
    if (value.phase === "playing") {
      clearWatchdog();
      setStage("play");
    } else if (value.phase === "ended") {
      void finish();
    } else if (value.phase === "aborted") {
      fail("play", value.reason ?? "가상환경이 투어를 멈췄습니다.");
    } else if (value.phase === "voice_error") {
      run.voiceNote = `음성이 막혔습니다 (${value.reason ?? "사유 불명"}) — 자막만 흐릅니다.`;
      paint();
    }
  });

  // 재생 중 가상환경을 떠나면 투어는 이어질 수 없다 — 사유와 함께 멈춘다
  // (조용히 진행 중인 척하면 카드가 하지 않는 일을 말하게 된다)
  window.addEventListener("hashchange", () => {
    if (run?.stage === "play" && location.hash !== "#world") {
      fail("play", "가상환경 탭을 떠나 투어를 멈췄습니다.");
    }
  });

  fab.onclick = () => setOpen(!open);
  paint();
  document.body.append(fab, card);
}
