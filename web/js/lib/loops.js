/** PI 개루프 스펙 편집 로직 — 마진 맵 다중 루프 폼 (서버 /analysis/margin-map loops[]).

서버 LoopIn(축·상태·입력 정합, 무의미 루프 거부)의 클라이언트 미러 — 제출 전
사전검증으로 배치 실행 전에 오타를 잡는다. 최종 판정은 서버(422)가 정본.
*/

import { parseFieldValue } from "./schemaform.js";

/** 축별 상태·입력 이름 — engine/claw/trim/linearize.py의 수동 사본 (정본은 엔진.
rename 시 여기와 loops.test.js 스냅샷도 갱신 — 낡으면 사전검증만 무뎌지고
서버 422가 최종 방어). */
export const AXIS_NAMES = {
  lon: { states: ["u", "w", "q", "theta"], inputs: ["de", "thr"] },
  lat: { states: ["v", "p", "r", "phi"], inputs: ["da", "dr"] },
};

/** 3축 레이트 루프 프리셋 — SCAS 축 구성(피치 q←δe·롤 p←δa·요 r←δr) 대응.
kp·ki는 출발 후보값 (설계값은 사용자가 편집 — 서버 계약 "설계값은 요청이 보유").
롤 kp가 음수인 것은 데모 기체 δa 부호 관례 대응 (SCAS 롤 k_rate −0.2와 동일
방향 — 양수로 넣으면 PM이 음수로 나와 오독 유발). */
export const DEFAULT_LOOPS = [
  { name: "pitch_q", axis: "lon", x_out: "q", u_in: "de", kp: "0.5", ki: "0.8", sign: "-1" },
  { name: "roll_p", axis: "lat", x_out: "p", u_in: "da", kp: "-0.2", ki: "0", sign: "-1" },
  { name: "yaw_r", axis: "lat", x_out: "r", u_in: "dr", kp: "0.8", ki: "0", sign: "-1" },
];

const NUM = (name) => ({ name, type: "number", lo: null, hi: null });

/** 편집 행(수치는 입력 문자열) 목록 → {loops: 파싱된 스펙[]} | {errors: 문구[]}.
빈 목록은 유효 — 루프 없이 고유치·감쇠비만 보는 실행. */
export function validateLoops(rows) {
  const loops = [];
  const errors = [];
  const seen = new Set();
  for (const r of rows) {
    const name = (r.name ?? "").trim();
    const tag = name || `(${rows.indexOf(r) + 1}번째 행)`;
    if (!name) errors.push(`${tag}: 루프 이름 필요`);
    else if (seen.has(name)) errors.push(`${tag}: 루프 이름 중복`);
    seen.add(name);
    const ax = AXIS_NAMES[r.axis];
    if (!ax) {
      errors.push(`${tag}: 미지 축 ${r.axis}`);
      continue;
    }
    if (!ax.states.includes(r.x_out)) errors.push(`${tag}: ${r.axis}축에 없는 상태 ${r.x_out}`);
    if (!ax.inputs.includes(r.u_in)) errors.push(`${tag}: ${r.axis}축에 없는 입력 ${r.u_in}`);
    const nums = {};
    for (const k of ["kp", "ki", "sign"]) {
      const p = parseFieldValue(NUM(`${tag}.${k}`), String(r[k]));
      if (p.error) errors.push(p.error);
      else nums[k] = p.value;
    }
    if (nums.sign === 0) errors.push(`${tag}: sign=0 (무의미 루프)`);
    if (nums.kp === 0 && nums.ki === 0) errors.push(`${tag}: kp=ki=0 (제로 개루프)`);
    loops.push({ name, axis: r.axis, x_out: r.x_out, u_in: r.u_in, ...nums });
  }
  return errors.length ? { errors } : { loops };
}
