// WorldTab.tsx는 JSX라 node가 못 세운다 — 투어 시작의 배선은 **원문에서 읽는다**(scene/sceneWiring.test.ts와 같은
// 가드). 판정 자체(tourReady·tourAwaitsVehicle)는 core/tour.test.ts가 잰다.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

const src = readFileSync(new URL("./WorldTab.tsx", import.meta.url), "utf8");

describe("WorldTab 투어 배선 — 기체가 선 뒤에 재생", () => {
  it("컨트롤러의 기체 신호를 받는다", () => {
    assert.match(src, /onVehicle: setVehicleSettled,/);
  });

  it("투어 시작은 기체(또는 상한 경과)를 조건에 넣고, 그 둘이 바뀌면 다시 본다", () => {
    const start = src.slice(src.indexOf("// 투어 시작"), src.indexOf("// 기체만 남았으면"));
    assert.ok(start.length > 0, "투어 시작 effect를 못 찾았다");
    assert.match(start, /tourReady\(tour, \{\n\s*chosen, shownId, playable, commsKey: commsKeyRef\.current, vehicleSettled: vehicleSettled \|\| vehicleLate,\n\s*\}\)/);
    assert.match(start, /\}, \[chosen, shownId, playable, comms, vehicleSettled, vehicleLate, style, emitTour, deps\.store\]\);/);
  });

  it("기체만 남으면 상한을 재고, 넘기면 기체 없이 시작한 사실을 알림줄이 말한다", () => {
    assert.match(src, /tourAwaitsVehicle\(tour, \{/);
    assert.match(src, /setTimeout\(\(\) => setVehicleLate\(true\), TOUR_VEHICLE_WAIT_MS\)/);
    assert.match(src, /return \(\) => clearTimeout\(id\);/);
    assert.match(src, /vehicleLate && !vehicleSettled \? TOUR_VEHICLE_LATE_NOTE/);
  });
});

describe("WorldTab 투어 배선 — 재생은 기체를 따라가는 시점으로", () => {
  it("투어 시작이 재생을 켜기 전에 추적 시점으로 옮긴다(컨트롤러 경유 — 버튼은 onMode가 맞춘다)", () => {
    const start = src.slice(src.indexOf("// 투어 시작"), src.indexOf("// 기체만 남았으면"));
    const cam = start.indexOf("ctl.setCamMode(TOUR_CAM_MODE);");
    assert.ok(cam > 0, "투어 시작 effect가 시점을 옮기지 않는다");
    assert.ok(cam < start.indexOf("ctl.setPlaying(true);"), "시점은 재생보다 먼저");
    assert.doesNotMatch(start, /setMode\(/); // UI 상태를 직접 만지면 버튼과 화면이 갈린다
  });
});
