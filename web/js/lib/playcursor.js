/** 재생 커서 수치 — 벽시계 경과에서 샘플 인덱스를 낸다 (시뮬 탭과 3D 월드가 공유).

## 왜 이 계산이 lib으로 나왔나

진행은 프레임당 고정 샘플이 아니라 **경과 벽시계 시간**으로 센다. 프레임당 샘플로 세면
stride가 큰 결과(dtSample이 큰)에서 저속 배속의 몫이 1샘플 미만이 되어 최소 1로 잘리고,
그만큼 요청 배속보다 빨리 재생된다 — **1×가 1×가 아니게 된다.**

이 미묘함 때문에 두 화면이 각자 적으면 서로 다른 시각을 말하게 된다. 정본을 하나로 두고
양쪽이 같은 함수를 부른다(§5.5). 타이머는 화면마다 자기 것을 가진다 — 계산만 공유한다.
*/

/** 샘플 간격 [s] (stride 적용 후). 샘플이 1개 이하면 0. */
export function dtSample(t) {
  return t.length > 1 ? t[1] - t[0] : 0;
}

/** 재생 가능한 결과인가 — 샘플이 2개 이상이고 간격이 양수여야 한다. */
export function isPlayable(t) {
  return t.length > 1 && dtSample(t) > 0;
}

/** 기준점(fromIdx, fromWallMs)에서 nowMs까지 흐른 만큼 진행한 인덱스.
 *
 * 끝을 넘지 않도록 클램프한다. `speed`는 배속, `dt`는 dtSample, `n`은 샘플 수.
 */
export function indexAt(fromIdx, fromWallMs, nowMs, speed, dt, n) {
  if (!(dt > 0)) throw new Error(`샘플 간격은 양수여야 함: ${dt}`);
  if (!(n > 0)) throw new Error(`샘플 수는 양수여야 함: ${n}`);
  const simElapsed = ((nowMs - fromWallMs) / 1000) * speed;
  return Math.min(fromIdx + Math.round(simElapsed / dt), n - 1);
}

/** 인덱스가 끝에 닿았는가 — 닿으면 호출측이 재생을 멈춘다. */
export function atEnd(idx, n) {
  return idx >= n - 1;
}
