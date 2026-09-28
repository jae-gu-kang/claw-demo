/** 쇼케이스 진행기 — 쇼케이스 기체 하나로 전 탭의 기능을 차례로 보여 준다 (단계 목록 카드 + 자동 재생).

조립·순서 제어 전용이다. 판단(단계 표·LLM 게이트·진행 규칙·줄·보관 형식)은 lib/showcase.js,
탭과의 신호는 lib/showcasecue.js에 있다. 전역 body 크롬인 이유는 가이드 투어(views/tour.js)와
같다 — 탭 전환은 `#view`만 갈아끼우므로, 탭을 넘나들며 순서를 쥐려면 라우트 밖에 살아야 한다.

**진행기는 탭의 일을 대신하지 않는다.** 신호(postCue)를 걸고 그 탭으로 이동할 뿐이고, 탭이
자기 [실행]과 같은 길로 일을 한 뒤 보고한다(awaitReport). 청중은 탭의 진행바·결과 패널을
그대로 본다. 예외 셋은 탭이 아닌 것을 부른다:
- 준비 — `POST /profiles/_showcase/install` 뒤 `switchSelection`(페이지를 다시 읽는다 — 커서·상태를
  sessionStorage에 남기고 다시 읽은 뒤 이어 달린다). 자동 설계가 문서에 새 리비전을 쓴 뒤에도 같은 선택으로
  한 번 더 다시 읽는다(탭 캐시가 옛 리비전을 들고 있지 않게 — lib/showcase.js 단계 표 주석)
- 가상환경 — 투어의 `worldTour` 기구를 그대로(가상환경은 읽기만, 수명은 여기서). 교신은 LLM이
  되면 `/llm/comms`, 아니면 없이
- 질문 — 질문 위젯의 `askPreset`(같은 run 경로)

사용자가 손으로 탭을 옮기면 자동 재생은 **일시정지**다(실패 아님) — 지금 동작을 마치고 멈춘다.
투어와는 카드 자리(좌하단)와 탭 주도권을 나눠 쓰므로 서로 배타다(store `chromeCard`·`showcaseBusy`).
*/

import { api, cancelJob, errorText, sleep, watchJob } from "../api.js";
import { clear, el } from "../dom.js";
import { dropWorkingCopy } from "../lib/gainsync.js";
import { currentSelection } from "../lib/profile.js";
import * as sc from "../lib/showcase.js";
import { CUE_KEY, awaitReport, postCue } from "../lib/showcasecue.js";
import { captionFor, endTimeFor } from "../lib/tour.js";
import { store } from "../store.js";
import { askPreset } from "./ask.js";
import { selectedDocument, switchSelection } from "./profilepick.js";
import { tourBlockReason } from "./tour.js";

let mounted = false;
let S = sc.emptyState(); // 진행 상태 — 보관 대상(커서·단계 줄·참조)
let run = null;          // 도는 중 {token, mode, pause, manual, jobIds, live, navFree, world} — token이 곧 유효성
let seq = 0;
let llm = null;          // /llm/status — **성공만 캐시**(콜드 스타트 첫 실패로 굳지 않게, 투어와 같은 규약)
let llmErr = null;
let expectedHash = null; // 진행기가 방금 보낸 해시 — 이것과 다른 hashchange는 사용자 손이다

/** 재생 끝 시각(meta.phases.stop_t)만 읽는 요청의 stride — meta는 stride와 무관하게 원본이라(routes/sim.py
 *  sim_replay) 신호 표본을 줄여 전송만 줄인다. 착륙 요약 수치는 시뮬 탭이 제 stride로 보여 준다. */
const META_STRIDE = 1000;
/** 마무리 전에 말하던 교신이 끝나기를 기다리는 상한(views/tour.js SPEAK_WAIT_MS와 같은 값). */
const SPEAK_WAIT_MS = 8_000;
/** 다시 읽은 뒤 이어 달리기 전 여유 — 라우트가 첫 뷰를 그리고 헤더 선택기가 붙을 틈. */
const RESUME_DELAY_MS = 800;

const session = () => {
  try {
    return globalThis.sessionStorage ?? null;
  } catch {
    return null;
  }
};
/** 보관 — 실패해도 진행은 계속된다(다시 읽기를 건너 잇지 못할 뿐). 돌려주는 것: 썼나. */
const persist = (state = S) => {
  try {
    const ss = session();
    if (!ss) return false;
    ss.setItem(sc.STORAGE_KEY, sc.encodeState(state));
    return true;
  } catch {
    return false;
  }
};
const restore = () => {
  try {
    return sc.decodeState(session()?.getItem(sc.STORAGE_KEY) ?? null);
  } catch {
    return sc.emptyState();
  }
};

export function mount() {
  if (mounted) return; // 한 번만 — main.js 재호출 방어
  mounted = true;
  S = restore();
  // 결함 시연 한가운데서 페이지가 다시 읽혔다(사람의 새로고침 — 진행기는 거기서 다시 읽지 않는다). 작업 사본은
  // 메모리 store라 결함 게인도 함께 사라졌다 — 가운데서 이으면 처방할 FAIL이 없으니 단계 처음으로
  if (sc.cancelCleanup(S).length) {
    S = sc.stopStep(S, { restored: [] });
    persist();
  }
  let open = false;
  let expanded = true;
  let banner = null; // {kind: "error"|"info", text}

  const statusLine = el("p", { class: "hint", style: "margin:0 0 8px" });
  const controls = el("div", { class: "sc-controls" });
  const bannerBox = el("div");
  const list = el("ol", { class: "sc-list" });
  const card = el("div", { class: "showcase-card", hidden: true },
    el("div", { class: "sc-head" },
      el("strong", {}, "쇼케이스"),
      el("button", { class: "tour-close", title: "닫기 (진행은 계속됩니다)", onclick: () => setOpen(false) }, "×")),
    statusLine, controls, bannerBox, list);
  const fab = el("button", {
    class: "ask-fab showcase-fab",
    title: "쇼케이스 기체로 전 탭의 기능을 차례로 — 단계를 눌러 하나씩, 또는 전체 자동 재생",
    "aria-expanded": "false",
  }, "◆ 쇼케이스");

  const alive = (token) => run?.token === token;

  // 이미 그 탭이면 hashchange가 안 난다 — main.js route()를 직접 다시 태운다(그때 신호가 읽힌다)
  const goTo = (hash) => {
    expectedHash = hash;
    if (location.hash === hash) window.dispatchEvent(new HashChangeEvent("hashchange"));
    else location.hash = hash;
  };

  const setOpen = (v) => {
    open = v;
    card.hidden = !v;
    fab.setAttribute("aria-expanded", v ? "true" : "false");
    if (v) store.set("chromeCard", "showcase"); // 투어 카드와 한 자리 — 저쪽이 닫힌다
    if (v && llm == null) void loadStatus();
    paint();
  };

  const loadStatus = async () => {
    try {
      llm = await api.get("/llm/status");
      llmErr = null;
    } catch (e) {
      llm = null; // 실패는 캐시하지 않는다 — 다음 실행·열기에서 다시 묻는다
      llmErr = errorText(e);
    }
    paint();
  };

  // ── 동작 하나씩 ───────────────────────────────────────────────────────────

  /** 다시 읽기 전 보관 — 이 동작의 결과를 적은 상태와 이어 달리기 흔적. 이을지는 진행 규칙이 정한다(일시정지·
   *  한 단계 모드의 단계 끝이면 잇지 않고 카드만 다시 연다). 돌려주는 것: 썼나. */
  const persistBeforeReload = (outcome, expectId) => {
    const r = sc.applyOutcome(S, outcome, { mode: run.mode, pause: run.pause });
    return persist(sc.withResume(r.state, { mode: r.go ? run.mode : null, now: Date.now(), expectId }));
  };

  /** 준비 — 설치·초기화 뒤 선택 전환. 다시 읽기 **전에** 이 동작의 결과와 다음 커서를 보관한다. */
  const doInstall = async (token) => {
    const res = await api.post("/profiles/_showcase/install");
    if (!alive(token)) return { status: "failed", error: "중단" };
    const id = res.id ?? sc.SHOWCASE_ID;
    // 보관을 못 해도 전환은 한다 — 이 단계의 목적이 선택 전환이다(다시 읽은 뒤 카드가 처음 상태로 뜰 뿐)
    persistBeforeReload({ status: "done", summary: sc.installSummary(res) }, id);
    const sw = switchSelection(id);
    if (!sw.ok) return { status: "failed", error: sw.reason ?? "기체 선택을 바꾸지 못했다" };
    return { status: "reloading" };
  };

  /** 새 리비전 다시 읽기 — 같은 선택(형상 변형 포함)으로 페이지를 다시 읽어 탭 캐시를 버린다. 보관을 못 하면
   *  다시 읽지 않는다 — 진행을 잃느니 옛 캐시일 수 있다는 사실을 줄로 남긴다. */
  const doReload = () => {
    const sel = currentSelection();
    const stale = "다른 탭이 옛 리비전을 보고 있을 수 있다 — 페이지를 새로 고치면 새로 읽는다";
    if (!sel) return { status: "done", notes: [`고른 기체가 없어 다시 읽지 않았다 — ${stale}`] };
    const summary = sel.variant ? `${sel.id} / ${sel.variant}` : sel.id;
    if (!persistBeforeReload({ status: "done", summary }, sel.id)) {
      return { status: "done", summary, notes: [`진행 상태를 보관하지 못해 다시 읽지 않았다 — ${stale}`] };
    }
    const sw = switchSelection(sel.id, sel.variant ?? null);
    if (!sw.ok) return { status: "failed", error: sw.reason ?? "같은 기체로 다시 읽지 못했다" };
    return { status: "reloading" };
  };

  /** 블록도 — 신호 없이 그 페이지에 머문다. */
  const doNav = async (a, token) => {
    goTo(a.hash);
    const end = Date.now() + a.dwellMs;
    while (Date.now() < end) {
      await sleep(200);
      if (!alive(token)) return { status: "failed", error: "중단" };
    }
    return { status: "done" };
  };

  /** 탭 신호 — 걸고, 가고, 끝 보고를 기다린다. 탭이 신호를 읽지도 않으면 긴 상한까지 기다리지 않는다.
   *  상한은 마지막 소식부터 잰다(sc.waitVerdict — 경과를 알리는 긴 잡은 기다린다). */
  const doCue = async (a, cursor, token) => {
    const actTok = `${token}.${cursor.step}.${cursor.sub}`; // 같은 탭·동작을 한 단계에서 여러 번 부른다(평가 셋)
    let args = sc.resolveArgs(a.args, S.refs);
    const notes = [];
    if (a.docArgs) {
      // 인자를 선택 기체 문서에서 짓는 동작(자동 설계 config) — 못 받으면 사유를 줄로 남기고, 대신할 길은
      // docArgs가 정한다(서버 기본 설정 — 예제 값을 물려주지 않는다)
      let doc = null;
      try {
        doc = await selectedDocument();
      } catch (e) {
        notes.push(`선택 기체 문서를 받지 못했다 — ${errorText(e)}`);
      }
      if (!alive(token)) return { status: "failed", error: "중단" };
      // 쇼케이스 기체인데 설계 설정 기록이 없다(단계 8이 이미 반영한 문서) — 같은 기체의 패키지 문서 기록을 받는다.
      // 못 받으면 docArgs가 템플릿 규칙으로 가고 그 출처를 줄로 남긴다
      let packaged = null;
      if (sc.needsPackagedDoc(doc)) {
        try {
          packaged = (await api.get("/profiles/_showcase"))?.document ?? null;
        } catch (e) {
          notes.push(`패키지 문서를 받지 못했다 — ${errorText(e)}`);
        }
        if (!alive(token)) return { status: "failed", error: "중단" };
      }
      const d = a.docArgs(doc, { packaged });
      args = { ...args, ...d.args };
      notes.push(...d.notes);
    }
    postCue({ token: actTok, tab: a.tab, action: a.action, args }); // 이동보다 먼저 — 렌더가 읽는다
    let unread = false;
    const unreadTimer = setTimeout(() => {
      if (store.get(CUE_KEY)?.token === actTok) unread = true;
    }, sc.UNREAD_CUE_MS);
    const startedAt = Date.now();
    let lastEventAt = startedAt;
    let stalled = null;
    // 기다림을 이동보다 **먼저** 건다 — 같은 해시면 goTo가 hashchange를 동기로 쏘아, 탭이 렌더 안에서 곧바로
    // 보고할 수 있다(첫 await 앞에서 던지는 실패·모르는 동작). 이동 뒤에 구독하면 그 보고를 놓치고 상한까지 기다린다
    const pending = awaitReport({ token: actTok, tab: a.tab, action: a.action }, {
      // 여기 시계(waitVerdict)가 먼저 잡는다 — awaitReport 자체 상한은 안전망
      timeoutMs: sc.actionTimeout(a) * sc.CAP_FACTOR + 60_000,
      onEvent: (ev) => {
        lastEventAt = Date.now(); // 경과가 오는 동안은 상한을 다시 센다
        if (!alive(token)) return;
        if (ev.phase === "started" && ev.jobId) run.jobIds.add(ev.jobId); // [■ 중단]이 취소할 잡(재개마다 새 잡)
        if (typeof ev.summary === "string" && ev.summary) {
          run.live = ev.summary; // 탭의 중간 경과 그대로
          paint();
        }
      },
      cancelled: () => {
        if (!alive(token) || unread) return true;
        stalled = sc.waitVerdict(a, { startedAt, lastEventAt, now: Date.now() });
        return stalled != null;
      },
    });
    goTo(`#${a.tab}`);
    const rep = await pending;
    clearTimeout(unreadTimer);
    // 안 읽힌 신호를 거둔다 — 남기면 한참 뒤 그 탭을 연 사람 앞에서 동작이 돈다
    if (store.get(CUE_KEY)?.token === actTok) store.set(CUE_KEY, null);
    const ids = alive(token) ? [...run.jobIds] : [];
    if (alive(token)) run.jobIds.clear();
    if (rep == null) {
      if (!alive(token)) return { status: "failed", error: "중단" };
      // 끝 보고 없이 멈췄다 — 걸어 둔 잡을 거둔다(단일 워커를 붙잡아 다음 단계를 막거나, 늦게 끝나 작업 사본·
      // 문서에 쓰지 않게)
      for (const id of ids) cancelJob(id).catch(() => {});
      const why = unread
        ? `「${a.tab}」 탭이 ${Math.round(sc.UNREAD_CUE_MS / 1000)} s 안에 신호를 읽지 않았다`
        : sc.waitText(a, stalled);
      // 사용자가 탭을 손으로 옮긴 뒤라면 실패가 아니라 끊김이다(대기로 — ▶가 이 동작부터 다시)
      if (run.manual) return { status: "interrupted", note: `탭을 손으로 옮긴 사이 멈췄다 — ${why}` };
      return { status: "failed", error: why, notes };
    }
    if (rep.phase === "done" && rep.ok !== false) {
      return { status: "done", summary: rep.summary, resultId: rep.resultId, data: rep.data, notes };
    }
    return { status: "failed", error: rep.error ?? rep.summary ?? "사유 없음", notes };
  };

  /** 교신 대본 — 실패해도 재생은 한다(사유를 줄로 남긴다). views/tour.js makeComms와 같은 길. */
  const makeComms = async (resultId, token) => {
    try {
      const sub = await api.post("/llm/comms", { result_id: resultId });
      if (alive(token)) run.jobIds.add(sub.id);
      const j = await watchJob(sub.id, () => {});
      if (alive(token)) run.jobIds.delete(sub.id);
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

  /** 가상환경 — 투어의 worldTour 기구. 끝(ended)·중단(aborted)·워치독·탭 이탈 중 먼저 오는 것으로 끝난다. */
  const doWorld = async (token) => {
    const rid = S.refs["sim.run"]?.resultId;
    if (!rid) return { status: "failed", error: "시뮬 결과가 없다 — 「시뮬레이션」 단계를 먼저" };
    const notes = [];
    let comms = { id: null, n: 0 };
    const why = sc.llmSkipReason(llm, llmErr);
    if (why) {
      notes.push(`교신 없음 — ${why}`);
    } else {
      run.live = captionFor("comms", {});
      paint();
      comms = await makeComms(rid, token);
      if (!alive(token)) return { status: "failed", error: "중단" };
      if (comms.failed) notes.push(captionFor("comms", { failed: comms.failed }));
    }
    const replay = await api.get(`/sim/${rid}/replay?stride=${META_STRIDE}`);
    if (!alive(token)) return { status: "failed", error: "중단" };
    const voice = typeof window !== "undefined" && "speechSynthesis" in window;
    // 배속 — 교신이 있으면 음성 게이트 안, 없으면 재생을 1분 안팎에(투어 2×는 475 s 런을 3.8 min 틀었다, e2e D19)
    const speed = sc.worldSpeedFor({ comms: comms.n > 0, durationS: sc.replayDurationS(replay) });
    const wTok = `${token}.world`;
    // 가상환경은 simResult의 런을 먼저 연다 — 투어처럼 여기서 맞춘다(이 단계를 따로 누르거나 다시 읽은 뒤에도
    // 시뮬 단계의 그 런이 재생되게. 다르면 가상환경이 투어를 「다른 결과」로 거절한다)
    if (store.get("simResult")?.id !== rid) store.set("simResult", { id: rid });
    store.set("worldTour", {
      token: wTok, resultId: rid, commsId: comms.id, speed, voice, endT: endTimeFor(replay),
    });
    run.live = captionFor("play", { lines: comms.n, voice, speed });
    paint();
    goTo("#world");
    const res = await new Promise((resolve) => {
      const w = { token: wTok, voiceNote: null, done: false, dog: null, cap: null };
      w.resolve = (v) => {
        if (w.done) return;
        w.done = true;
        clearTimeout(w.dog);
        clearTimeout(w.cap);
        resolve({ ...v, voiceNote: w.voiceNote });
      };
      w.dog = setTimeout(() => w.resolve({ status: "failed",
        error: "가상환경이 재생을 시작하지 못했다 — 3D가 떴는지, 그 런이 결과 목록에 있는지 확인" }),
      sc.WORLD_WATCHDOG_MS);
      w.cap = setTimeout(() => w.resolve({ status: "failed", error: "재생이 상한 안에 끝나지 않았다" }),
        sc.WORLD_CAP_MS);
      run.world = w;
    });
    if (alive(token)) run.world = null;
    if (res.status === "done") await waitSpeechIdle(); // 마지막 교신을 자르지 않게
    if (store.get("worldTour")?.token === wTok) store.set("worldTour", null); // 수명은 여기서 쥔다
    if (res.voiceNote) notes.push(res.voiceNote);
    if (res.status !== "done") return { ...res, notes };
    // 캡션 머리("3D 재생 — ")는 동작 이름과 겹친다 — 뒤(교신 줄 수·배속)만
    const cap = captionFor("play", { lines: comms.n, voice, speed });
    return { status: "done", summary: cap.split(" — ").slice(1).join(" — ") || cap, notes };
  };

  /** 질문 — 질문 위젯의 같은 run 경로. 답이 화면을 옮기므로 그 이동은 사용자 손이 아니다. */
  const doAsk = async (a, token) => {
    run.navFree = true;
    const out = await askPreset(a.question, { onJob: (id) => { if (alive(token)) run.jobIds.add(id); } });
    expectedHash = location.hash; // 답의 첫 액션 이동 — hashchange가 뒤늦게 와도 우리 것
    if (alive(token)) run.navFree = false;
    return out.ok
      ? { status: "done", summary: out.summary, resultId: out.resultId }
      : { status: "failed", error: out.error ?? "사유 없음" };
  };

  const runKind = async (a, token) => {
    switch (a.kind) {
      case "install": return await doInstall(token);
      case "reload": return doReload();
      case "nav": return await doNav(a, token);
      case "cue": return await doCue(a, S.cursor, token);
      case "world": return await doWorld(token);
      case "ask": return await doAsk(a, token);
      default: return { status: "failed", error: `모르는 동작 종류: ${a.kind}` };
    }
  };

  const execAction = async (token) => {
    const a = sc.STEPS[S.cursor.step].actions[S.cursor.sub];
    run.live = null;
    paint();
    if (a.llm) {
      const why = sc.llmSkipReason(llm, llmErr);
      if (why) return { status: "skipped", reason: why };
    }
    // 결함 주입은 언제나 문서 게인 위에 — 걸기 전에 작업 사본을 비운다(게인 탭 restore와 같은 함수). 앞선 멈춤이
    // 남긴 결함 사본에 또 곱하면 ×6·×6이 된다(리뷰 재현). 이 단계는 끝에 어차피 작업 사본을 비운다(뒷정리)
    const pre = a.dirties ? [sc.faultBaseNote(dropWorkingCopy(store))].filter(Boolean) : [];
    try {
      const out = await runKind(a, token);
      return pre.length ? { ...out, notes: [...pre, ...(out.notes ?? [])] } : out;
    } catch (e) {
      return { status: "failed", error: errorText(e), notes: pre };
    }
  };

  /** 동작 뒤 머묾 — 청중이 결과를 볼 틈. 도중에 멈춤(⏸·손 이동)이 오면 곧장 끝낸다(동작은 이미 끝났다).
   *  돌려주는 것: 끝까지 머물렀나. */
  const hold = async (ms, token) => {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      if (!alive(token) || run.pause) return false;
      await sleep(Math.min(200, end - Date.now()));
    }
    return alive(token) && !run.pause;
  };

  // ── 실행 제어 ─────────────────────────────────────────────────────────────

  const endRun = () => {
    const manual = !!run?.manual;
    const cause = run?.stopCause ?? null;
    const before = run?.expandedBefore ?? expanded;
    run = null;
    store.set("showcaseBusy", false);
    S = sc.settleRunning(S); // 한가운데서 멈춘 단계는 「진행」이 아니다
    // 중간에 멈추면 도는 동안 접은 목록을 되돌린다(행을 눌러 고르는 자리). 끝까지 갔으면 접힌 채 둔다 —
    // 마지막 탭(결과 브리핑)이 그 자리에 서 있다(e2e: 끝에 540 px로 펴져 결과 목록을 덮었다). [목록 펴기]로 전량
    expanded = sc.runEnded(S) ? false : before;
    // 결함 시연 한가운데서 멈췄다(일시정지·손 이동·끊김) — 결함 게인을 작업 사본에 남기지 않는다. 중단과 같은
    // 판단·같은 함수(탭은 위에서 끈 showcaseBusy를 보고 멈춘다 — 비운 뒤에 다시 싣지 않는다). 단계는 처음부터
    const restored = sc.cancelCleanup(S).some((a) => sc.refKey(a) === "gains.restore")
      ? dropWorkingCopy(store) : null;
    S = sc.stopStep(S, { restored });
    // 일시정지로 멈췄을 때만 「일시정지」라 말한다 — 실패·끝·한 단계 끝은 그 줄이 상태다
    const text = sc.stopBanner(cause, manual);
    if (text) banner = { kind: "info", text };
    persist();
    paint();
  };

  /** mode "all" = 커서부터 끝까지, "one" = stepIdx 단계만. */
  const start = async (mode, stepIdx = null) => {
    if (run) return;
    const tourWhy = tourBlockReason();
    if (tourWhy) {
      banner = { kind: "error", text: tourWhy };
      paint();
      return;
    }
    banner = null;
    // 끝에서 다시 누르면 목록은 끝이 접은 것이지 사용자가 접은 게 아니다 — 멈출 때 펼쳐 되돌린다
    const foldedByEnd = sc.runEnded(S) && !expanded;
    if (stepIdx == null && S.cursor.step >= sc.STEPS.length) S = sc.emptyState(); // 끝 → 처음부터 다시
    const i = stepIdx ?? S.cursor.step;
    const notes = sc.preconditionNotes(i, S, { selectedId: currentSelection()?.id ?? null });
    S = stepIdx == null && S.cursor.sub > 0 ? sc.resumeStep(S) : sc.beginStep(S, i, notes);
    S = sc.clearResume(S);
    const token = `sc${Date.now()}-${seq += 1}`;
    run = { token, mode, pause: false, manual: false, jobIds: new Set(), live: null, navFree: false, world: null,
      expandedBefore: foldedByEnd || expanded };
    store.set("showcaseBusy", true);
    expanded = false; // 도는 동안은 지금 단계 한 줄만 — 카드가 탭의 그림(3D 등)을 덜 가린다(sc.cardRows)
    persist();
    paint();
    if (llm == null) await loadStatus();
    try {
      let first = true;
      while (alive(token)) {
        // 새 단계로 넘어왔다 — 지난 실행의 줄을 비우고 「진행」으로(첫 단계는 위에서 이미)
        if (!first && S.cursor.sub === 0) {
          S = sc.beginStep(S, S.cursor.step, []);
          persist();
        }
        first = false;
        const stepAt = S.cursor.step;
        const a = sc.STEPS[stepAt].actions[S.cursor.sub];
        let outcome = await execAction(token);
        if (!alive(token)) return;
        if (outcome.status === "reloading") {
          run.reloading = true; // 페이지가 곧 다시 읽힌다 — 보관은 doInstall·doReload가 이미 했다
          paint();
          return;
        }
        if (outcome.status === "interrupted") {
          S = sc.interruptStep(S, outcome.note);
          run.stopCause = sc.stopCause({ outcome: outcome.status, mode });
          break;
        }
        if (outcome.status === "failed" && sc.refKey(a) === "gains.restore") {
          // 복원 신호가 실패했다(탭이 신호를 못 읽음 등) — 결함 게인을 남기지 않게 같은 함수로 대신한다
          outcome = { ...outcome,
            notes: [...(outcome.notes ?? []), sc.cleanupLine(a, dropWorkingCopy(store), "복원이 실패해")] };
        }
        const r = sc.applyOutcome(S, outcome, { mode, pause: run.pause });
        S = r.state;
        persist();
        paint();
        if (!r.go) {
          run.stopCause = sc.stopCause({ outcome: outcome.status, r, mode, pause: run.pause });
          break;
        }
        // 다음 동작으로 가기 전에 머문다(e2e D1 — 결과가 0.3~0.6 s에 지나갔다). 멈출 자리(go 거짓)면 화면이
        // 그대로 남으니 머물지 않는다 — 한 단계 모드도 단계 안의 동작 사이에서는 머문다(기체 탭의 네 패널)
        const ms = sc.dwellFor(a, outcome);
        if (ms > 0) {
          run.holdStep = stepAt; // 머무는 동안 카드는 방금 끝낸 단계의 줄을 보인다(커서는 이미 다음일 수 있다)
          paint();
          const held = await hold(ms, token);
          if (!alive(token)) return;
          run.holdStep = null;
          if (!held) {
            run.stopCause = sc.stopCause({ outcome: outcome.status, r, mode, dwellCut: true });
            break;
          }
        }
      }
    } finally {
      if (alive(token) && !run.reloading) endRun();
    }
  };

  const pauseRun = () => {
    if (!run || run.pause) return;
    run.pause = true; // 지금 동작을 마치고 멈춘다
    paint();
  };

  const cancelRun = () => {
    if (!run) return;
    const tok = run.token;
    const ids = [...run.jobIds];
    const w = run.world;
    expanded = run.expandedBefore ?? expanded;
    run = null; // 토큰 무효 — 늦게 온 보고·이벤트는 전부 버려진다
    store.set("showcaseBusy", false);
    if (String(store.get(CUE_KEY)?.token ?? "").startsWith(`${tok}.`)) store.set(CUE_KEY, null); // 신호 회수
    if (String(store.get("worldTour")?.token ?? "").startsWith(`${tok}.`)) store.set("worldTour", null);
    w?.resolve({ status: "failed", error: "중단" });
    for (const id of ids) cancelJob(id).catch(() => {}); // 서버 잡도 협조적으로 멈춘다
    // 결함 주입에 닿은 뒤의 중단 — 뒷정리(게인 restore)는 탭으로 가야 도는데 중단은 여기서 멈춘다. 그 신호가
    // 쓰는 같은 함수로 작업 사본을 비우고 그 사실을 줄에 남긴다(결함 게인이 뒤 탭의 계산에 남지 않게). 탭은
    // 위에서 끈 showcaseBusy를 보고 멈추므로(lib/showcase haltReason) 비운 뒤에 다시 싣지 않는다
    const restored = sc.cancelCleanup(S).some((a) => sc.refKey(a) === "gains.restore")
      ? dropWorkingCopy(store) : null;
    S = sc.cancelStep(S, { restored });
    persist();
    paint();
  };

  /** 교신 음성은 사용자 제스처 안의 첫 발화가 열어 둬야 한다(투어와 같은 사유) — 소리 없는 발화로. */
  const unlockSpeech = () => {
    const synth = typeof window !== "undefined" ? window.speechSynthesis : null;
    if (!synth || !llm?.available) return;
    try {
      const u = new SpeechSynthesisUtterance(" ");
      u.volume = 0;
      synth.speak(u);
    } catch { /* 음성이 없어도 진행한다 — 자막이 남는다 */ }
  };

  // ── 그리기 ────────────────────────────────────────────────────────────────

  const rowView = (row, compact) => {
    const current = row.current && S.cursor.step < sc.STEPS.length;
    const live = current && run?.live ? el("div", { class: "sc-line live", title: run.live }, run.live) : null;
    // 도는 중 접힘은 한 줄 — 경과가 있으면 경과가 마지막 줄을 대신한다(잘린 줄은 툴팁에 전량)
    const lines = compact && live ? [] : row.lines;
    return el("li", {
      class: `sc-row ${row.state}${current ? " current" : ""}`,
      role: "button",
      tabindex: run ? "-1" : "0",
      "aria-disabled": run ? "true" : "false",
      title: run ? null : "이 단계만 실행",
      onclick: () => { if (!run) { unlockSpeech(); void start("one", row.index); } },
      onkeydown: (ev) => {
        if ((ev.key === "Enter" || ev.key === " ") && !run) {
          ev.preventDefault();
          unlockSpeech(); // 키보드도 사용자 제스처다 — 클릭과 같은 길
          void start("one", row.index);
        }
      },
    },
    el("span", { class: "sc-n" }, String(row.index)),
    el("span", { class: "sc-label" }, row.label),
    el("span", { class: "sc-chip" }, row.stateLabel),
    lines.length || live
      ? el("div", { class: "sc-lines" },
          lines.map((l) => el("div", { class: `sc-line ${l.tone}`, title: l.full ?? (compact ? l.text : null) },
            l.text)), live)
      : null);
  };

  const paint = () => {
    // 도는 중 접힘 — 지금 단계 한 줄 + 조작만(카드가 탭의 그림을 덜 가리게, e2e D14). [목록 펴기]로 전량
    const compact = sc.cardCompact(S, { running: !!run, expanded });
    card.classList.toggle("compact", compact);
    statusLine.hidden = compact;
    clear(fab).append(sc.fabLabel(S, !!run));
    clear(statusLine).append(llm == null
      ? (llmErr ? `LLM 상태 조회 실패 — ${llmErr}` : "서버 상태 확인 중…")
      : llm.available ? "LLM 단계 포함" : `LLM 단계는 건너뜀 — ${sc.llmSkipReason(llm)}`);
    statusLine.title = llm?.reason ?? ""; // 서버 사유 전량(설정 안내)은 툴팁

    clear(controls);
    const atEnd = S.cursor.step >= sc.STEPS.length;
    if (run) {
      controls.append(
        el("button", { disabled: run.pause || run.reloading, onclick: pauseRun,
          title: "지금 동작을 마치고 멈춥니다" }, run.pause ? "⏸ 멈추는 중…" : "⏸ 일시정지"),
        el("button", { disabled: !!run.reloading, onclick: cancelRun,
          title: "도는 잡을 취소하고 신호를 거둡니다" }, "■ 중단"));
    } else {
      const from = sc.STEPS[S.cursor.step];
      controls.append(el("button", {
        class: "primary",
        title: atEnd ? "준비부터 다시" : `「${from.label}」부터 끝까지`,
        onclick: () => { unlockSpeech(); void start("all"); },
      }, atEnd ? "▶ 처음부터 다시" : "▶ 전체 자동 재생"));
    }
    controls.append(el("button", {
      class: "sc-toggle", title: expanded ? (run ? "지금 단계 한 줄만" : sc.runEnded(S) ? "마지막 단계만" : "지금 단계 둘레만") : "단계 전체",
      onclick: () => { expanded = !expanded; paint(); },
    }, expanded ? "목록 접기" : "목록 펴기"));

    clear(bannerBox);
    if (banner) {
      bannerBox.append(el("div", {
        class: banner.kind === "error" ? "error-box" : "hint", style: "margin:0 0 8px",
      }, banner.text));
    }
    if (run?.pause && run.manual) {
      bannerBox.append(el("p", { class: "hint", style: "margin:0 0 8px" },
        "탭을 손으로 옮겼습니다 — 이 동작을 마치고 멈춥니다."));
    }

    clear(list);
    list.append(...sc.cardRows(S, { expanded, running: !!run, focus: run?.holdStep ?? null })
      .map((row) => rowView(row, compact)));
    // 지금 행을 목록 **안에서만** 보인다 — scrollIntoView는 문서까지 굴려, 탭이 방금 건 부드러운 굴림(결과
    // 브리핑 revealPanel)을 크롬이 끊었다(e2e: 브리핑 y 1024에서 scrollY 0). 규칙은 lib/showcase listScrollTop
    const cur = open ? list.querySelector(".current") : null;
    if (cur) {
      const lr = list.getBoundingClientRect();
      const cr = cur.getBoundingClientRect();
      list.scrollTop = sc.listScrollTop({
        listTop: lr.top, listBottom: lr.bottom, itemTop: cr.top, itemBottom: cr.bottom, scrollTop: list.scrollTop });
    }
  };

  // ── 신호 수신 ─────────────────────────────────────────────────────────────

  // 투어 카드가 열렸다 — 카드만 닫는다(도는 진행은 그대로, 단추로 다시 연다)
  store.subscribe((key, value) => {
    if (key === "chromeCard" && value !== "showcase" && open) setOpen(false);
  });

  // 가상환경이 돌려주는 신호 — 지금 기다리는 재생의 토큰만
  store.subscribe((key, value) => {
    const w = run?.world;
    if (key !== "worldTourState" || !w || value?.token !== w.token) return;
    if (value.phase === "playing") clearTimeout(w.dog);
    else if (value.phase === "ended") w.resolve({ status: "done" });
    else if (value.phase === "aborted") w.resolve({ status: "failed", error: value.reason ?? "가상환경이 재생을 멈췄다" });
    else if (value.phase === "voice_error") w.voiceNote = `음성이 막혔다 (${value.reason ?? "사유 불명"}) — 자막만`;
  });

  // 사용자가 손으로 탭을 옮겼다 — 자동 재생은 이 동작을 마치고 멈춘다(실패가 아니다).
  // 재생 중 가상환경을 떠나면 그 재생은 이어질 수 없다 — 단계를 대기로 되돌린다
  window.addEventListener("hashchange", () => {
    if (!run || run.navFree || run.reloading || location.hash === expectedHash) return;
    run.pause = true;
    run.manual = true;
    if (run.world && location.hash !== "#world") {
      run.world.resolve({ status: "interrupted", note: "가상환경 탭을 떠나 재생을 멈췄다 — 다시 누르면 처음부터" });
    }
    paint();
  });

  fab.onclick = () => setOpen(!open);
  paint();
  document.body.append(fab, card);

  // 진행기가 방금 다시 읽었다(준비·새 리비전) — 카드를 열고, 이어 달릴 자리였으면 잇는다
  const rr = sc.reloadResume(S, Date.now());
  if (S.resumeAt != null) {
    S = sc.clearResume(S); // 한 번만 — 다음 새로고침이 다시 달리지 않게
    persist();
  }
  if (rr.fresh) {
    setOpen(true);
    if (rr.expectId && currentSelection()?.id !== rr.expectId) {
      banner = { kind: "error",
        text: `다시 읽은 뒤 기체 선택이 「${rr.expectId}」가 아닙니다 — 이어 달리지 않았습니다. 「준비」부터 다시 누르십시오.` };
      paint();
    } else if (rr.mode) {
      setTimeout(() => { void start(rr.mode); }, RESUME_DELAY_MS);
    }
  }
}
