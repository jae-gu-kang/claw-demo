/** 로그인 게이트 로직 — DOM 없이 판정·수치만 (조립은 views/login.js).

블록도 해체·조립 연출의 수치 계획이 여기 있다: 어느 방향으로 얼마나 흩어지고
(scatterPlan), 어떤 간격으로 착착 되돌아오는가(snapDelays). 화면 조립과 분리해
node --test로 고정한다 — 연출 튜닝이 회귀 없이 가능하도록.
*/

import { ApiError, errorText } from "../api.js";

/** /api/auth/me 응답으로 게이트를 세울지 판정. 응답이 없으면(서버 무응답 등)
부팅을 막지 않는다 — 이후 첫 401이 claw:auth-required로 게이트를 다시 세운다. */
export function needsGate(me) {
  return Boolean(me && me.mode === "session" && !me.user);
}

/** 결정적 의사난수 (mulberry32) — 같은 seed면 같은 흩뿌리기.
새로고침마다 다른 그림이면 "어제와 다르게 보인다"가 버그인지 우연인지 알 수 없다. */
function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** 블록 n개의 해체 배치 — viewBox 단위(px 아님, 보드 폭 ~1300 기준).
dx·dy: 흩어진 변위, rot: 기울기(deg), dur·delay: 둥둥(float) 주기·위상(s),
fx·fy: 떠다니는 진폭. delay는 음수 — 시작부터 위상이 갈라져 있어야
"방금 일제히 출발했다"가 아니라 "원래 떠다니고 있었다"로 읽힌다. */
export function scatterPlan(n, seed = 7) {
  const rnd = mulberry32(seed);
  const plan = [];
  for (let i = 0; i < n; i++) {
    const dir = i % 2 ? 1 : -1; // 좌우 번갈아 — 한쪽으로 몰리면 해체가 아니라 이동으로 보인다
    plan.push({
      dx: dir * (120 + rnd() * 300),
      dy: (rnd() - 0.5) * 2 * 230,
      rot: (rnd() - 0.5) * 2 * 24,
      dur: 3.5 + rnd() * 3,
      delay: -rnd() * 4,
      fx: (4 + rnd() * 14) * (rnd() < 0.5 ? -1 : 1),
      fy: 6 + rnd() * 12,
    });
  }
  return plan;
}

/** 조립 스태거 — DOM의 .blk 등장 순서(= 뒷줄 → CHAIN → 항법)대로 ms 지연. */
export function snapDelays(n, stepMs = 80) {
  return Array.from({ length: n }, (_, i) => i * stepMs);
}

/** 로그인 실패 문구 — 403 pending/rejected는 서버 detail의 message를 그대로 쓴다
(문구 정본은 서버 routes/auth.py 한 곳). 그 외는 errorText 공통 규칙. */
export function loginFailText(err) {
  if (err instanceof ApiError && err.detail && typeof err.detail === "object"
      && typeof err.detail.message === "string") {
    return err.detail.message;
  }
  return errorText(err);
}
