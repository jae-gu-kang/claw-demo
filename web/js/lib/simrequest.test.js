// 시뮬 요청 조립 — 시뮬 탭과 가이드 투어가 쓰는 한 벌 (sim.js run() 이식의 동등성 고정)
import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";

import { buildModes, buildWaypoints } from "./mission.js";
import { GOHEUNG } from "./site.js";
import {
  ACT_FALLBACK, AP_PHI_MAX_FALLBACK, DEFAULT_FORM, appliedFrom, applyProfileDefaults, buildSimRequest,
  defaultModeRows, defaultWpRows, initialForm, profileSimDefaults,
} from "./simrequest.js";

const NONE = appliedFrom(() => undefined); // store가 빈 상태

test("기본 폼 + 기본 미션 → 요청 전체가 골든과 같다 (sim.js run() 이식 동등성)", () => {
  // v0.92까지 run()이 기본 폼에서 내던 요청을 그대로 적는다 — 조립을 lib로 옮긴
  // 리팩터가 요청을 한 칸이라도 바꾸면 여기서 빨개진다 (sim.js엔 뷰 테스트가 없다)
  const { req, snapshot, missing } = buildSimRequest(
    DEFAULT_FORM, defaultModeRows(), defaultWpRows(), NONE);
  // 모드는 **리터럴로** 박는다 — buildModes(defaultModeRows())로 적으면 같은 원본을
  // 양쪽에서 계산해 비교하는 꼴이라 프로파일 수치(속도·이탈 조건·피치)가 바뀌어도
  // 통과한다(리뷰의 변이시험: climb 180→250, cruise 88→95가 안 잡혔다).
  // 웨이포인트는 아래 「장주 패턴」 테스트가 기하로 잡는다.
  const hdg = GOHEUNG.runwayHeadingRad;
  assert.deepEqual(req, {
    trim: { name: "start", mach: 0, alt: 0, fuel: 37.5, condition: "ground" },
    modes: [
      { name: "launch", speed: 44.9, alt: null, pitch: 0.3665, hdot: null,
        heading: hdg, exit: ["off_rail"], next: "climb" },
      { name: "climb", speed: 44.9, alt: null, pitch: 0.3665, hdot: null,
        heading: hdg, exit: ["alt_ge", 180], next: "cruise" },
      { name: "cruise", speed: 44, alt: 200, pitch: null, hdot: null,
        heading: "path", exit: ["path_done"], next: "approach" },
      { name: "approach", speed: 35.9, alt: null, pitch: null, hdot: -1.96,
        heading: hdg, exit: ["alt_le", 20], next: "flare" },
      { name: "flare", speed: 32.7, alt: null, pitch: null, hdot: -0.33,
        heading: hdg, exit: ["on_ground"], next: "rollout" },
      { name: "rollout", speed: 0, alt: null, pitch: 0, hdot: null,
        heading: hdg, exit: ["speed_le", 0.5], next: "stopped" },
      { name: "stopped", speed: 0, alt: null, pitch: 0, hdot: null,
        heading: null, exit: ["time_ge", 1e9], next: null },
    ],
    waypoints: buildWaypoints(defaultWpRows()),
    accept_radius: 75,
    t_end: 750,
    runway: { elevation: 0, heading: GOHEUNG.runwayHeadingRad, length: GOHEUNG.runwayLengthM },
    origin: { lat: GOHEUNG.originLatDeg, lon: GOHEUNG.originLonDeg },
    launch: { length: 10, elev_angle: 0.2618, exit_speed: 33.3 },
    fuel_flow: 0.02,
    fingerprint: "web-sim-v1",
    nav: { seed: 11 },
    nav_grade: "rtk",
    actuators: { wn: ACT_FALLBACK.wn, zeta: ACT_FALLBACK.zeta, rate_max: ACT_FALLBACK.rate },
  });
  assert.deepEqual(missing, []);
  assert.deepEqual(snapshot, { waypoints: req.waypoints, acceptRadius: 75 });
});

test("기본 미션은 발사 → 착륙 정지 사슬이고 순항만 경로를 따른다", () => {
  const rows = defaultModeRows();
  assert.deepEqual(rows.map((r) => r.name),
    ["launch", "climb", "cruise", "approach", "flare", "rollout", "stopped"]);
  // next 사슬이 첫 행에서 끝까지 끊김 없이 이어진다 (orphan 없음)
  for (let i = 0; i < rows.length - 1; i += 1) assert.equal(rows[i].next, rows[i + 1].name);
  assert.equal(rows.at(-1).next, "");
  assert.deepEqual(rows.filter((r) => r.heading === "path").map((r) => r.name), ["cruise"]);
});

test("기본 웨이포인트는 활주로로 되돌아오는 장주다 — 방위 상수를 공유한다", () => {
  // 활주로 축 좌표(along = 시단에서 방위 방향, cross = 오른쪽)로 읽는다. 종전
  // 기본값은 축 위 2.6·3.3 km 둘이라 기체가 그대로 북진해 **시단 7 km 북쪽**에
  // 내렸다(실측 접지 7,010 m). 장주는 그 자리를 활주로 안으로 되돌린다.
  const h = GOHEUNG.runwayHeadingRad;
  const wps = defaultWpRows();
  const plan = [[3500, 0], [3500, 900], [-5800, 900], [-5800, 0], [-4400, 0]];
  assert.equal(wps.length, plan.length);
  wps.forEach((wp, i) => {
    const n = Number(wp.n);
    const e = Number(wp.e);
    const along = n * Math.cos(h) + e * Math.sin(h);
    const cross = -n * Math.sin(h) + e * Math.cos(h);
    assert.ok(Math.abs(along - plan[i][0]) < 1, `WP${i + 1} 축방향 ${along}`);
    assert.ok(Math.abs(cross - plan[i][1]) < 1, `WP${i + 1} 횡편차 ${cross}`);
    assert.equal(wp.d, ""); // 고도는 비운다 — 세로는 순항 고도 200이 낸다
  });
  // 장주 폭은 180° 되돌기 둘을 담아야 한다 — 순항 44 m/s·뱅크 0.7에서 2R = 469 m
  const R = (44 * 44) / (9.80665 * Math.tan(0.7));
  assert.ok(plan[1][1] >= 2 * R, `장주 폭 ${plan[1][1]} < 2R ${2 * R}`);
  // 마지막 점은 활주로 축 위에서 **시단 남쪽**이다 — 거기서 접근이 시작된다
  assert.ok(plan.at(-1)[0] < 0 && plan.at(-1)[1] === 0);
});

test("기본 행은 부를 때마다 새 사본이다 — 표 편집이 정본 기본값을 오염시키지 않는다", () => {
  const a = defaultModeRows();
  a[0].name = "edited";
  assert.equal(defaultModeRows()[0].name, "launch");
  const w = defaultWpRows();
  w[0].n = "0";
  assert.notEqual(defaultWpRows()[0].n, "0");
});

test("토글을 끄면 그 블록 자체가 빠진다 — 지면·원점·레일·항법·작동기", () => {
  const form = { ...DEFAULT_FORM, groundOn: false, originOn: false, launchOn: false,
    navOn: false, actOn: false };
  const { req } = buildSimRequest(form, defaultModeRows(), defaultWpRows(), NONE);
  assert.equal(req.trim.condition, "level");
  for (const k of ["runway", "origin", "launch", "nav", "nav_grade", "actuators"]) {
    assert.equal(Object.hasOwn(req, k), false, `${k}가 남았다`);
  }
});

test("빈 원점은 0이 아니라 NaN — (0,0)은 그럴듯한 틀린 값이라 서버 422로 보낸다", () => {
  const { req } = buildSimRequest({ ...DEFAULT_FORM, originLat: " " },
    defaultModeRows(), defaultWpRows(), NONE);
  assert.ok(Number.isNaN(req.origin.lat));
  assert.equal(req.origin.lon, GOHEUNG.originLonDeg);
});

test("활주로 표고는 시작 고도 칸과 같은 값이다 — 한 칸이 두 곳에 들어간다", () => {
  const { req } = buildSimRequest({ ...DEFAULT_FORM, alt: "12" },
    defaultModeRows(), defaultWpRows(), NONE);
  assert.equal(req.trim.alt, 12);
  assert.equal(req.runway.elevation, 12);
});

test("웨이포인트가 없으면 키를 지우되 스냅샷은 지우기 전에 뜬다", () => {
  const rows = defaultModeRows().map((r) => (r.heading === "path" ? { ...r, heading: "0" } : r));
  const { req, snapshot } = buildSimRequest(DEFAULT_FORM, rows, [], NONE);
  assert.equal(Object.hasOwn(req, "waypoints"), false);
  assert.deepEqual(snapshot, { waypoints: [], acceptRadius: 75 });
});

test("적용값 병합 — 항법은 시드만 폼이, 작동기는 wn·ζ·rate만 폼이 이긴다", () => {
  const applied = appliedFrom((k) => ({
    navParams: { pos_std: 1.5, seed: 99 },
    actuatorParams: { pos_min: -0.3, wn: 99 },
  })[k]);
  const { req } = buildSimRequest(DEFAULT_FORM, defaultModeRows(), defaultWpRows(), applied);
  assert.deepEqual(req.nav, { pos_std: 1.5, seed: 11 });
  assert.deepEqual(req.actuators, { pos_min: -0.3, wn: 30, zeta: 0.7, rate_max: 10 });
});

test("편집값을 쓰겠다는데 적용본이 없으면 조용히 기본으로 돌지 않고 missing으로 말한다", () => {
  const form = { ...DEFAULT_FORM, useGains: true, useAp: true, useScas: true };
  const none = buildSimRequest(form, defaultModeRows(), defaultWpRows(), NONE);
  assert.equal(none.missing.length, 3);
  assert.match(none.missing[0], /편집 게인/);
  const tables = { k: 1 };
  const got = buildSimRequest({ ...DEFAULT_FORM, useGains: true }, defaultModeRows(),
    defaultWpRows(), appliedFrom((k) => (k === "gainTables" ? tables : undefined)));
  assert.equal(got.req.gain_tables, tables);
  assert.deepEqual(got.missing, []);
});

test("표가 틀리면 조립이 검증 정본의 문장으로 던진다 — 조용히 고치지 않는다", () => {
  const rows = defaultModeRows();
  rows[1] = { ...rows[1], exitValue: "" }; // alt_ge인데 인자 없음
  assert.throws(() => buildSimRequest(DEFAULT_FORM, rows, defaultWpRows(), NONE),
    /climb\.exit: 값이 비어 있음/);
});

test("작동기 폼 초기값 — 적용본이 있으면 그 값, 없으면 폴백", () => {
  assert.equal(initialForm(undefined).wn, String(ACT_FALLBACK.wn));
  const f = initialForm({ wn: 45, zeta: 0.8 });
  assert.equal(f.wn, "45");
  assert.equal(f.zeta, "0.8");
  assert.equal(f.rate, String(ACT_FALLBACK.rate)); // 적용본에 없는 칸은 폴백
  assert.equal(f.tEnd, DEFAULT_FORM.tEnd); // 나머지는 기본 폼 그대로
});

test("기체 문서 기본값 — 폴백은 예제 문서의 사본이고, 손대지 않은 칸만 고른 기체 값으로 바뀐다", () => {
  const example = JSON.parse(readFileSync(
    new URL("../../../engine/claw/profile/examples/delta_demo.json", import.meta.url), "utf8"));
  const d = profileSimDefaults(example);
  // 폴백 사본이 예제 문서와 어긋나면 여기서 빨개진다 (앙각만 네 자리로 줄였다)
  assert.equal(d.form.railLen, DEFAULT_FORM.railLen);
  assert.equal(d.form.railExit, DEFAULT_FORM.railExit);
  assert.ok(Math.abs(Number(d.form.railAngle) - Number(DEFAULT_FORM.railAngle)) < 5e-5);
  assert.deepEqual([d.form.wn, d.form.zeta, d.form.rate], [DEFAULT_FORM.wn, DEFAULT_FORM.zeta, DEFAULT_FORM.rate]);
  assert.equal(d.phiMax, AP_PHI_MAX_FALLBACK);
  assert.deepEqual([d.form.launchOn, d.form.groundOn], [true, true]);

  const other = JSON.parse(JSON.stringify(example));
  other.actuator.params.wn = 45;
  other.ground.rail = null; // 발사 레일이 없는 기체
  other.law.design.autopilot.phi_max = 0.5;
  const o = profileSimDefaults(other);
  assert.deepEqual([o.form.launchOn, o.form.railLen, o.form.wn, o.phiMax], [false, "", "45", 0.5]);
  const out = applyProfileDefaults({ ...DEFAULT_FORM, zeta: "0.75", railLen: "12" }, o.form);
  assert.equal(out.wn, "45", "폴백 그대로였다 → 기체 값");
  assert.equal(out.zeta, "0.75", "사용자가 고쳤다 → 유지");
  assert.equal(out.railLen, "12", "고친 칸은 둔다 — 토글이 꺼져 요청에 실리지 않는다");
  assert.equal(out.launchOn, false);
  assert.equal(applyProfileDefaults(DEFAULT_FORM, o.form, { skip: ["wn"] }).wn, DEFAULT_FORM.wn,
    "블록도 작동기 적용값이 있으면 작동기 칸은 채우지 않는다");
  other.law.design = null;
  other.ground.skid = null;
  assert.deepEqual([profileSimDefaults(other).phiMax, profileSimDefaults(other).form.groundOn], [null, false]);
  assert.deepEqual(profileSimDefaults(null), { form: {}, phiMax: null });
});
