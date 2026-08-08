/** 초소형 공유 상태 — 탭 간 최근 결과 전달용 (프레임워크 대체는 이 이상 하지 않음). */

const state = {};
const subs = new Set();

export const store = {
  get: (key) => state[key],
  set(key, value) {
    state[key] = value;
    for (const fn of subs) fn(key, value);
  },
  subscribe(fn) {
    subs.add(fn);
    return () => subs.delete(fn);
  },
};
