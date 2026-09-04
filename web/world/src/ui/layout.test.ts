import { strict as assert } from "node:assert";
import { describe, it } from "node:test";

import { MIN_H, VIEWPORT_FRAC, canvasHeight } from "./layout.ts";

describe("canvasHeight", () => {
  it("좁은 창에서는 2:1 — 종전 규칙 그대로다", () => {
    // 폭 상한(360)이 뷰포트 상한(0.62×1200=744)보다 작다
    assert.equal(canvasHeight(720, 1200), 360);
    assert.equal(canvasHeight(1000, 1600), 500);
  });

  it("넓은 창에서는 뷰포트가 이긴다 — 안 그러면 재생줄이 화면 밖으로 밀린다", () => {
    // 전면 배치 실측 구성: 폭 1352 → 2:1이면 676이지만 뷰포트 779의 62%가 483이다
    assert.equal(canvasHeight(1352, 779), 483);
    assert.ok(canvasHeight(1352, 779) < 1352 * 0.5, "2:1을 넘기면 컨트롤이 잘린다");
  });

  it("두 상한 중 **작은 쪽**이 이긴다 — 어느 쪽이든 화면을 넘지 않는다", () => {
    for (const w of [400, 900, 1352, 1560, 2400]) {
      for (const vh of [600, 779, 1100, 1600]) {
        const h = canvasHeight(w, vh);
        // 하한에 걸린 경우를 빼면 두 상한을 모두 지킨다
        if (h > MIN_H) {
          assert.ok(h <= Math.round(w * 0.5) + 1, `폭 상한 위반 w=${w} vh=${vh} h=${h}`);
          assert.ok(h <= Math.round(vh * VIEWPORT_FRAC) + 1,
            `뷰포트 상한 위반 w=${w} vh=${vh} h=${h}`);
        }
      }
    }
  });

  it("아래로는 안 줄인다 — 3D가 띠가 되면 지형을 못 읽는다", () => {
    assert.equal(canvasHeight(200, 300), MIN_H);
    assert.equal(canvasHeight(0, 0), MIN_H); // 탭 전환 중 0폭에서도 음수·0이 안 나온다
  });

  it("폭에 단조 증가한다 — 창을 넓혔는데 세계가 작아지지 않는다", () => {
    let prev = 0;
    for (const w of [300, 600, 900, 1200, 1500, 2000]) {
      const h = canvasHeight(w, 2000); // 뷰포트를 크게 두어 폭 상한이 이기게
      assert.ok(h >= prev, `w=${w}에서 줄었다 (${prev} → ${h})`);
      prev = h;
    }
  });
});
