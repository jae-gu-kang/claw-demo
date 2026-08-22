/** 재생 진행 수치 — 경과 벽시계 → 표본 인덱스. DOM·타이머 무접촉 순수 함수.

프레임당 고정 샘플로 세지 않는 이유: 표본 간격(stride 적용 후)이 큰 결과에서는
저속 배속의 몫이 1샘플 미만이 되어 최소 1로 잘리고, 그만큼 요청 배속보다 빨리
재생된다 (stride 10 · 1× 가 실효 2.5×). 기준점에서의 경과 시간으로 매번 다시
계산하면 표본 간격과 무관하게 배속이 그대로 지켜진다.

소비처: 시뮬 탭 재생(views/sim.js)과 구조도 재생 오버레이(views/replayoverlay.js).
*/

/** 표본 간격 [s] — 재생 불가(표본 부족·비균일·비유한)는 0으로 알린다. */
export function dtOf(t) {
  if (!t || t.length < 2) return 0;
  const dt = t[1] - t[0];
  return Number.isFinite(dt) && dt > 0 ? dt : 0;
}

/** 기준점(fromIdx, fromWall)에서 now까지 speed배로 흐른 뒤의 표본 인덱스.

dtSample이 0이면(재생 불가) 기준점을 그대로 돌려준다 — 0-나눗셈으로 NaN 인덱스가
나와 슬라이더·캔버스가 조용히 망가지는 것을 막는다.
*/
export function indexAt({ fromIdx, fromWall, now, speed, dtSample, len }) {
  if (!(dtSample > 0)) return fromIdx;
  const simElapsed = ((now - fromWall) / 1000) * speed;
  const next = fromIdx + Math.round(simElapsed / dtSample);
  return Math.max(0, Math.min(next, len - 1));
}
