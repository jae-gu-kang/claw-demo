// 블록 다이어그램 데이터 검증 — 드릴다운 허브(블록 클릭 → 서브시스템 페이지)의 계약.
// 기하(SVG 좌표)는 views/diagram.js·subsystems.js 수작성 — 여기선 데이터 계약만 판다.
import { test } from "node:test";
import assert from "node:assert/strict";

import { BLOCKS, CHAIN } from "./blocks.js";
// 뷰 모듈이지만 모듈 스코프에서 DOM을 안 건드려 node import 가능 — 배선 드리프트 가드
import { DESIGN_ORDER, TOP_SVG } from "../views/diagram.js";
import { CHIP_LABEL, SUBSYSTEMS } from "../views/subsystems.js";

// main.js VIEWS의 수동 사본 — main.js가 DOM 의존이라 직접 import 불가. 보호는
// 단방향(blocks.js 오타만 검출): main.js에서 뷰 개명 시 이 목록도 갱신할 것
const VIEW_HASHES = new Set(["blocks", "trim", "margins", "envelope", "gains", "sim", "results"]);
// 엔진 레지스트리에 실존하는 카테고리/이름 (test_fcl_law·test_system이 핀)
const REGISTRY_REFS = new Set([
  "fcl/Autopilot", "fcl/ScasAxis", "fcl/Mixer",
  "actuator/SecondOrderActuator", "guidance/LOS", "nav/ErrorModel",
]);

test("블록: id 유일 + 상세 스펙 완결", () => {
  const ids = BLOCKS.map((b) => b.id);
  assert.equal(new Set(ids).size, ids.length);
  for (const b of BLOCKS) {
    assert.ok(b.title, `${b.id} title 없음`);
    // title/sub는 TOP_SVG 템플릿에 무이스케이프 보간됨 — 마크업 특수문자 금지 (리뷰 S2)
    assert.ok(!/[&<>]/.test(b.title + (b.sub ?? "")), `${b.id} title/sub에 &<> 금지`);
    const d = b.detail;
    assert.ok(d && typeof d.desc === "string" && d.desc.length > 0, `${b.id} desc 없음`);
    // 이동 대상 해시는 실제 뷰만 (라우터 폴백으로 무효 링크 은폐 방지)
    if (d.edit) assert.ok(VIEW_HASHES.has(d.edit.hash), `${b.id} 무효 해시 ${d.edit.hash}`);
    // 스키마 참조는 엔진 레지스트리 실존 컴포넌트만
    if (d.schema) {
      assert.ok(REGISTRY_REFS.has(`${d.schema.category}/${d.schema.name}`),
        `${b.id} 미등록 스키마 참조`);
    }
    // 편집 가능 = 시뮬 주입 경로 보유 — schema와 store 키가 모두 있어야 함
    if (d.editable) {
      assert.ok(d.schema, `${b.id} editable인데 schema 없음`);
      assert.ok(typeof d.injectKey === "string" && d.injectKey, `${b.id} injectKey 없음`);
    } else {
      assert.equal(d.injectKey, null, `${b.id} 편집 불가인데 injectKey 있음`);
    }
  }
});

test("주 신호 경로 CHAIN = M7 조립 순서, 전 항목이 실존 블록", () => {
  assert.deepEqual(CHAIN,
    ["guidance", "autopilot", "limiter", "scas", "mixer", "actuator", "plant"]);
  const ids = new Set(BLOCKS.map((b) => b.id));
  for (const id of CHAIN) assert.ok(ids.has(id), `CHAIN에 미실존 블록 ${id}`);
  // 주 경로 밖 블록 = 입력(미션플래너)·공통(게인 스케줄)·피드백(항법)뿐
  const offChain = [...ids].filter((id) => !CHAIN.includes(id)).sort();
  assert.deepEqual(offChain, ["nav", "planner", "schedule"]);
});

test("최상위 SVG 배선 ↔ 페이지 데이터 드리프트 가드 (리뷰 S1)", () => {
  // 오타 id는 currentPage()가 조용히 홈으로 폴백해 무반응이 됨 — 여기서 잡는다
  const refs = [...TOP_SVG.matchAll(/data-(?:block|page)="([^"]+)"/g)].map((m) => m[1]);
  for (const id of refs) assert.ok(SUBSYSTEMS[id], `SVG 배선이 미실존 페이지 참조: ${id}`);
  for (const s of DESIGN_ORDER) assert.ok(SUBSYSTEMS[s.page], `배너가 미실존 페이지 참조: ${s.page}`);
  // 모든 블록은 그림에 정확히 1회 등장 + 하위 페이지 보유 (클릭 무반응 방지)
  const blockRefs = [...TOP_SVG.matchAll(/data-block="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual([...blockRefs].sort(), BLOCKS.map((b) => b.id).sort());
  for (const b of BLOCKS) assert.ok(SUBSYSTEMS[b.id], `${b.id} 서브시스템 페이지 없음`);
  // 주 경로 블록의 그림 등장 순서 = CHAIN (M7 조립 순서) — 그림·데이터 어긋남 불가
  assert.deepEqual(blockRefs.filter((id) => CHAIN.includes(id)), CHAIN);
});

test("서브시스템 페이지 스펙 완결 (pagehead 메타·칩·이동 해시)", () => {
  for (const [id, s] of Object.entries(SUBSYSTEMS)) {
    for (const k of ["tag", "tagBg", "title", "eng", "svg", "notes"]) {
      assert.ok(s[k], `${id}.${k} 없음`);
    }
    for (const c of s.chips) assert.ok(CHIP_LABEL[c], `${id} 미정의 칩 ${c}`);
    for (const e of s.edits ?? []) assert.ok(VIEW_HASHES.has(e.hash), `${id} 무효 해시 ${e.hash}`);
  }
});

test("허브 계약: 시뮬 주입 경로 보유 블록(AP·작동기·항법)만 편집 가능", () => {
  const byId = Object.fromEntries(BLOCKS.map((b) => [b.id, b.detail]));
  assert.equal(byId.autopilot.editable, true);
  assert.equal(byId.autopilot.injectKey, "autopilotParams"); // req.autopilot
  assert.equal(byId.actuator.editable, true);
  assert.equal(byId.actuator.injectKey, "actuatorParams"); // req.actuators
  // Simulator actuator_params 예약 키 — 폼·주입 제외 (engine test_sim이 핀)
  assert.deepEqual(byId.actuator.omit, ["pos_lo", "pos_hi", "initial"]);
  assert.equal(byId.nav.editable, true);
  assert.equal(byId.nav.injectKey, "navParams"); // req.nav
  assert.equal(byId.schedule.edit.hash, "gains");
  assert.equal(byId.scas.edit.hash, "gains"); // 게인 정본은 스케줄 — 폼은 열람 전용
  assert.equal(byId.scas.editable, false);
  assert.equal(byId.limiter.edit.hash, "envelope");
  assert.equal(byId.actuator.edit.hash, "sim"); // 최종 확인처 — 시뮬 탭 필드가 프리필·최종
  assert.equal(byId.nav.edit.hash, "sim");
  assert.equal(byId.planner.edit.hash, "sim"); // 미션(모드·웨이포인트)은 시뮬 탭이 편집처
  assert.equal(byId.plant.edit.hash, "trim");
});

// 편집 가능 블록 스키마의 파라미터명 사본 — 정본은 엔진 레지스트리
// (engine claw/fcl·plant·nav 생성자 kwargs). 이름 변경 시 이 목록도 갱신할 것.
const SVG_PARAM_NAMES = {
  autopilot: new Set([
    "kp_spd", "ki_spd", "tau_spd", "kp_alt", "ki_alt", "k_hdot", "tau_alt",
    "kp_hdg", "ki_hdg", "tau_hdg", "theta_lo", "theta_hi",
    "phi_max", "k_pitch_turn", "k_thr_turn",
  ]),
  // pos_lo·pos_hi·initial은 omit(주입 예약 키) — SVG에서도 바인딩 금지 (아무도 안 채움)
  actuator: new Set(["wn", "zeta", "rate_max"]),
  nav: new Set([
    "pos_std", "vel_std", "att_std", "psi_std", "rate_std",
    "bias_std", "bias_tau", "delay_s", "update_hz", "seed",
  ]),
};

test("서브시스템 SVG data-p는 해당 블록 스키마 파라미터명만 (오타 = 영구 미갱신 수치)", () => {
  for (const [id, s] of Object.entries(SUBSYSTEMS)) {
    const names = [...s.svg.matchAll(/data-p="([^"]+)"/g)].map((m) => m[1]);
    const allowed = SVG_PARAM_NAMES[id];
    if (!allowed) {
      // 스키마 폼 없는 페이지의 data-p는 아무도 채우지 않음 — 도입 시 이 목록에 등록
      assert.equal(names.length, 0, `${id}: 바인딩 소스 없는 페이지에 data-p ${names}`);
      continue;
    }
    for (const n of names) assert.ok(allowed.has(n), `${id}: 스키마에 없는 data-p "${n}"`);
    assert.ok(names.length > 0, `${id}: 편집 가능 페이지인데 연동 수치 없음`);
  }
});
