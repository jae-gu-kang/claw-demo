/** 쇼케이스 진행기 ↔ 탭 신호 규약 (순수 로직 — store만 안다).

진행기(views/showcase.js)는 탭의 요청 조립·실행을 **대신하지 않는다** — 탭에 「이것을 해라」
신호(cue)를 걸고 그 탭으로 이동할 뿐이다. 탭은 렌더할 때 자기 앞으로 온 신호를 **한 번 읽고
지우고**(store 인계 규약 — designOpen·resultBrief와 같다), 자기 [실행] 버튼과 같은 길로 그
일을 한 뒤 결과를 보고(report)한다. 그래서 청중은 탭의 진행바·결과 패널을 그대로 보고, 요청
조립은 탭 한 벌뿐이다(투어가 lib/simrequest.js를 공유하는 것과 같은 사유 — 사본 금지).

신호 모양: `{ token, tab, action, args? }`
- token — 진행기 한 실행의 식별자. 보고가 이 값을 그대로 되돌려야 진행기가 제 것으로 받는다
- tab — 받을 탭(해시 이름: "aircraft"·"trim"…). 다른 탭은 이 신호를 건드리지 않는다
- action — 탭별 동작 이름(lib/showcase.js 단계 표). 모르는 동작은 실패로 보고한다(조용히 무시 금지)

보고 모양: `{ token, tab, action, phase, ok?, resultId?, jobId?, summary?, data?, error? }`
- phase "started" — 잡을 걸었다(jobId). 선택 — 진행기가 [중단] 때 잡을 취소할 수 있게
- phase "progress" — 긴 동작의 중간 경과(summary). 선택
- phase "done" — 끝(ok:true). summary는 **탭 자신의 산출물에서 만든** 한 줄 캡션
- phase "failed" — 끝(ok:false, error). 진행기는 첫 실패 사유를 그대로 싣는다
*/

import { store as defaultStore } from "../store.js";

export const CUE_KEY = "showcaseCue";
export const REPORT_KEY = "showcaseReport";
export const PHASES = Object.freeze(["started", "progress", "done", "failed"]);

/** 진행기가 신호를 건다 — 탭 이동(goTo)보다 **먼저** 불러야 렌더가 읽는다. */
export function postCue(cue, s = defaultStore) {
  if (!cue || typeof cue.token !== "string" || typeof cue.tab !== "string"
      || typeof cue.action !== "string") {
    throw new TypeError("cue에는 token·tab·action 문자열이 필요하다");
  }
  s.set(CUE_KEY, { args: {}, ...cue });
}

/** 이 탭 앞으로 온 신호를 한 번 읽고 지운다 — 없거나 다른 탭 것이면 null(건드리지 않는다). */
export function takeCue(tab, s = defaultStore) {
  const c = s.get(CUE_KEY);
  if (!c || c.tab !== tab) return null;
  s.set(CUE_KEY, null);
  return c;
}

/** 탭이 신호 처리 경과를 알린다. phase는 PHASES 중 하나, done/failed는 ok를 스스로 채운다. */
export function reportCue(cue, payload, s = defaultStore) {
  if (!cue) return;
  const phase = payload?.phase ?? "done";
  if (!PHASES.includes(phase)) throw new TypeError(`모르는 phase: ${phase}`);
  const ok = phase === "failed" ? false : phase === "done" ? payload?.ok !== false : undefined;
  s.set(REPORT_KEY, {
    ...payload, token: cue.token, tab: cue.tab, action: cue.action, phase,
    ...(ok === undefined ? {} : { ok }),
  });
}

/** 실패 보고 줄임 — 예외를 사유 문장으로. */
export function failCue(cue, error, s = defaultStore) {
  const msg = typeof error === "string" ? error : (error?.message ?? String(error));
  reportCue(cue, { phase: "failed", error: msg }, s);
}

/** 모르는 동작 — 조용히 무시하지 않고 실패로 알린다. */
export function unknownAction(cue, s = defaultStore) {
  failCue(cue, `이 탭(${cue?.tab})은 「${cue?.action}」 동작을 모른다`, s);
}

/** 진행기 쪽: 이 토큰·탭·동작의 **끝** 보고를 기다린다(started·progress는 onEvent로만 흘린다).
 *  timeoutMs가 지나면 사유와 함께 실패로 끝난다 — 탭이 신호를 못 읽었거나(렌더 전에 떠남)
 *  보고를 빠뜨리면 진행기가 영영 기다리는 자리. cancelled()가 참이 되면 null로 끝난다. */
export function awaitReport({ token, tab, action }, {
  timeoutMs = 60_000, onEvent = () => {}, cancelled = () => false, s = defaultStore,
} = {}) {
  return new Promise((resolve) => {
    let done = false;
    let unsub = () => {};
    let timer = null;
    let poll = null;
    const finish = (v) => {
      if (done) return;
      done = true;
      unsub();
      clearTimeout(timer);
      clearInterval(poll);
      resolve(v);
    };
    unsub = s.subscribe((key, v) => {
      if (key !== REPORT_KEY || !v || v.token !== token || v.tab !== tab || v.action !== action) return;
      if (v.phase === "done" || v.phase === "failed") finish(v);
      else onEvent(v);
    });
    timer = setTimeout(() => finish({
      token, tab, action, phase: "failed", ok: false,
      error: `「${tab}」 탭이 ${Math.round(timeoutMs / 1000)} s 안에 「${action}」을 끝냈다고 알리지 않았다`,
    }), timeoutMs);
    poll = setInterval(() => { if (cancelled()) finish(null); }, 250);
  });
}
