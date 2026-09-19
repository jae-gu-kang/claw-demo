/** seedlink — 다섯 탭(게인·자동 설계·시뮬·Autocode·검증)이 한 벌로 쓰는 오류 표시 + 안내 링크.
 *
 * 한 벌이 깨지면 다섯 탭이 같이 깨진다(v1.29에서 공용화) — 링크가 서는 조건(경로 대조)과
 * 오류 문구(엔진 detail 그대로·비프로파일 오류는 종전과 동일)를 여기서 핀한다.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { installDom } from "./testdom.js";

installDom(); // import보다 먼저 — seedlink.js가 dom.js el()을 쓴다

const { ApiError } = await import("../api.js");
const { errorWithSeedLink } = await import("./seedlink.js");

test("게인 미설계 detail(경로 대조)에만 링크가 선다 — 오류 문구는 path: message", () => {
  const seed = errorWithSeedLink(
    new ApiError(422, { path: "/law/design", message: "게인 미설계 — 초기 게인 탐색이 필요함" }),
    "이 탭이 섭니다.");
  assert.equal(seed.length, 2);
  assert.equal(seed[0].className, "error-box");
  assert.equal(seed[0].text, "/law/design: 게인 미설계 — 초기 게인 탐색이 필요함");
  assert.match(seed[1].find("BUTTON")[0].text, /기체 탭에서 초기 게인 채우기/);
  assert.match(seed[1].text, /이 탭이 섭니다\./);
  // 스케줄 없음도 같은 안내다 — quick_seed가 스케줄을 만든다
  const sched = errorWithSeedLink(new ApiError(422, { path: "/law/schedule", message: "게인 스케줄 없음" }), "x");
  assert.equal(sched.length, 2);
});

test("다른 오류는 상자 하나 — 하위 경로·문자열 detail·일반 Error 모두 링크 없음", () => {
  for (const e of [
    new ApiError(422, { path: "/law/design/scas/pitch/kp", message: "수여야 함" }),
    new ApiError(422, "문자열 detail"),
    new Error("일반 오류"),
  ]) {
    const out = errorWithSeedLink(e, "x");
    assert.equal(out.length, 1, String(e));
    assert.equal(out[0].className, "error-box");
  }
  // 비프로파일 오류의 문구는 종전(errorText)과 동일 — 문자열 detail은 그대로다
  assert.equal(errorWithSeedLink(new ApiError(422, "그냥 오류"), "x")[0].text, "그냥 오류");
});
