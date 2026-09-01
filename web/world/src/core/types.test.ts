import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { finite } from "./types.ts";

describe("finite — 결측 규약의 한 줄", () => {
  it("유한한 수만 통과시킨다", () => {
    assert.equal(finite(0), 0);
    assert.equal(finite(-12.5), -12.5);
    assert.equal(finite(1e300), 1e300);
  });

  it("null·undefined는 null", () => {
    assert.equal(finite(null), null);
    assert.equal(finite(undefined), null);
  });

  it("NaN은 null — 0으로 메우지 않는다", () => {
    // 엔진은 계측되지 않은 채널을 NaN으로 두고 직렬화가 null로 바꾼다. 어느 쪽이든
    // **0이 되어서는 안 된다** — 0은 "값이 0이다"라는 다른 뜻이다.
    assert.equal(finite(NaN), null);
  });

  it('무한대 문자열 "inf"·"-inf"도 null', () => {
    // 이 두 값은 **직렬화기 때문에만 존재한다**(`serialize.py` — +inf → "inf").
    // `v ?? null`로 줄이면 문자열이 그대로 통과해 좌표 계산이 NaN이 되고,
    // 그 NaN이 바운딩 스피어를 오염시켜 메시가 통째로 사라진다.
    assert.equal(finite("inf"), null);
    assert.equal(finite("-inf"), null);
  });

  it("수가 아닌 것은 전부 null", () => {
    assert.equal(finite(Infinity), null);
    assert.equal(finite(-Infinity), null);
  });
});
