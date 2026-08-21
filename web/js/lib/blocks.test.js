// 블록 다이어그램 데이터 검증 — 드릴다운 허브(블록 클릭 → 서브시스템 페이지)의 계약.
// 기하(SVG 좌표)는 views/diagram.js·subsystems.js 수작성 — 여기선 데이터 계약만 판다.
import { test } from "node:test";
import assert from "node:assert/strict";

import { BLOCKS, CHAIN, resolvePath } from "./blocks.js";
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

test("코드 생성 계약: editable 블록만 보유하고 접두사·변수명이 서로 겹치지 않음", () => {
  // 스냅샷은 세 블록을 한 파일에 담는다 — cPrefix가 겹치면 C 매크로가, varName이
  // 겹치면 Python 변수가 조용히 덮어써진다 (생성물만 보면 알아채기 어려움)
  const prefixes = new Set();
  const varNames = new Set();
  for (const b of BLOCKS) {
    const cg = b.detail.codegen;
    if (!b.detail.editable) {
      assert.equal(cg, undefined, `${b.id} 편집 불가인데 codegen 계약 있음`);
      continue;
    }
    assert.ok(cg, `${b.id} editable인데 codegen 계약 없음`);
    assert.match(cg.cPrefix, /^[A-Z][A-Z0-9_]*$/, `${b.id} cPrefix 형식`);
    assert.match(cg.varName, /^[a-z_][a-z0-9_]*$/, `${b.id} varName은 파이썬 식별자`);
    assert.ok(["object", "dict"].includes(cg.kind), `${b.id} kind`);
    assert.ok(!prefixes.has(cg.cPrefix), `cPrefix 중복 ${cg.cPrefix}`);
    assert.ok(!varNames.has(cg.varName), `varName 중복 ${cg.varName}`);
    prefixes.add(cg.cPrefix);
    varNames.add(cg.varName);
  }
  // 클래스·임포트 경로는 여기 두지 않는다 — 서버 validate가 엔진에서 얻어 주므로
  // (하드코딩하면 엔진 개명 시 생성 코드가 조용히 틀려진다)
  for (const b of BLOCKS) {
    assert.equal(b.detail.codegen?.pyClass, undefined, `${b.id} 클래스명 하드코딩`);
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

/** 드릴다운 트리 순회 — 루트 + children 재귀 (경로 라벨 포함). */
function* walk(id, node, path = [id]) {
  yield { node, path };
  for (const [cid, child] of Object.entries(node.children ?? {})) {
    yield* walk(cid, child, [...path, cid]);
  }
}

test("서브시스템 페이지 스펙 완결 (pagehead 메타·칩·이동 해시 — children 재귀)", () => {
  for (const [id, s] of Object.entries(SUBSYSTEMS)) {
    for (const { node, path } of walk(id, s)) {
      const p = path.join("/");
      for (const k of ["title", "eng", "svg", "notes"]) {
        assert.ok(node[k], `${p}.${k} 없음`);
      }
      // 루트는 단계 태그 필수, 자식은 crumb(브레드크럼 짧은 라벨) 필수 — 태그는 루트 상속
      if (path.length === 1) {
        for (const k of ["tag", "tagBg"]) assert.ok(node[k], `${p}.${k} 없음`);
      } else {
        assert.ok(node.crumb, `${p}.crumb 없음`);
      }
      for (const c of node.chips) assert.ok(CHIP_LABEL[c], `${p} 미정의 칩 ${c}`);
      for (const e of node.edits ?? []) assert.ok(VIEW_HASHES.has(e.hash), `${p} 무효 해시 ${e.hash}`);
    }
  }
});

test("드릴다운: SVG data-child ↔ children 키 양방향 정합 (오타 = 클릭 무반응/도달 불가)", () => {
  for (const [id, s] of Object.entries(SUBSYSTEMS)) {
    for (const { node, path } of walk(id, s)) {
      const p = path.join("/");
      const refs = [...node.svg.matchAll(/data-child="([^"]+)"/g)].map((m) => m[1]);
      // SVG 참조 → children 실존 (미실존이면 라우터가 조용히 절단 폴백해 무반응)
      for (const r of refs) assert.ok(node.children?.[r], `${p} SVG가 미실존 자식 참조: ${r}`);
      // children → SVG 진입 블록 실존 (없으면 해시 직접 입력 말고는 도달 불가)
      for (const cid of Object.keys(node.children ?? {})) {
        assert.ok(refs.includes(cid), `${p} 자식 ${cid}의 진입 블록(data-child) 없음`);
      }
      // 진입 블록은 키보드 도달 필수 — tabindex="0" (리뷰 사소 4)
      for (const m of node.svg.matchAll(/<g[^>]*data-child="([^"]+)"[^>]*>/g)) {
        assert.ok(/tabindex="0"/.test(m[0]), `${p} data-child=${m[1]} 블록에 tabindex="0" 없음`);
      }
    }
  }
});

test("resolvePath: 트리 하강·절단 폴백 (해시 → 드릴다운 경로 — 라우팅 정본)", () => {
  const s = SUBSYSTEMS;
  assert.deepEqual(resolvePath([], s), []); // 홈
  assert.deepEqual(resolvePath(["scas"], s), ["scas"]);
  assert.deepEqual(resolvePath(["scas", "pitch", "pi"], s), ["scas", "pitch", "pi"]); // 층4
  assert.deepEqual(resolvePath(["scas", "", "pitch"], s), ["scas"]); // 빈 세그먼트 절단
  assert.deepEqual(resolvePath(["scas", "PITCH"], s), ["scas"]); // 대소문자 불일치 절단
  assert.deepEqual(resolvePath(["verify", "anything"], s), ["verify"]); // children 없는 노드
  assert.deepEqual(resolvePath(["nope", "scas"], s), []); // 첫 세그먼트 미실존 → 홈
  // 프로토타입 상속 키는 페이지가 아님 — 렌더 크래시 방지 (hasOwn 가드)
  assert.deepEqual(resolvePath(["constructor"], s), []);
  assert.deepEqual(resolvePath(["scas", "constructor"], s), ["scas"]);
});

test("드릴다운 범위 스냅샷: SCAS 3축+공유 PI(층4) · AP 3채널 · 유도 2 · 플랜트 4", () => {
  const s = SUBSYSTEMS.scas;
  assert.deepEqual(Object.keys(s.children), ["pitch", "roll", "yaw"]);
  for (const axis of Object.values(s.children)) {
    assert.deepEqual(Object.keys(axis.children), ["pi"]);
  }
  // PI 층4는 공유 정의 — 세 축이 동일 객체 (축별 드리프트 방지)
  assert.equal(s.children.pitch.children.pi, s.children.roll.children.pi);
  assert.equal(s.children.pitch.children.pi, s.children.yaw.children.pi);
  assert.deepEqual(Object.keys(SUBSYSTEMS.autopilot.children), ["hdg", "alt", "spd"]);
  // 유도·플랜트 층3 — 엔진 모듈 단위와 1:1 (path.py·modes.py / aero·prop·eom·mass.py)
  assert.deepEqual(Object.keys(SUBSYSTEMS.guidance.children), ["path", "modes"]);
  assert.deepEqual(Object.keys(SUBSYSTEMS.plant.children), ["aero", "prop", "eom", "mass"]);
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
    "pos_std_h", "pos_std_v", "vel_std_h", "vel_std_v",
    "att_std", "psi_std", "rate_std",
    "bias_std_h", "bias_std_v", "bias_tau", "delay_s", "update_hz", "seed",
  ]),
};

test("서브시스템 SVG data-p는 루트 블록 스키마 파라미터명만 (children 포함 — 오타 = 영구 미갱신 수치)", () => {
  for (const [id, s] of Object.entries(SUBSYSTEMS)) {
    // 바인딩 소스는 루트 블록 스키마 — children도 같은 스키마로 채워짐 (views/blocks.js)
    const allowed = SVG_PARAM_NAMES[id];
    for (const { node, path } of walk(id, s)) {
      const p = path.join("/");
      const names = [...node.svg.matchAll(/data-p="([^"]+)"/g)].map((m) => m[1]);
      if (!allowed) {
        // 스키마 폼 없는 루트 아래의 data-p는 아무도 채우지 않음 — 도입 시 목록 등록
        assert.equal(names.length, 0, `${p}: 바인딩 소스 없는 페이지에 data-p ${names}`);
        continue;
      }
      for (const n of names) assert.ok(allowed.has(n), `${p}: 스키마에 없는 data-p "${n}"`);
    }
    if (allowed) {
      const rootNames = [...s.svg.matchAll(/data-p="([^"]+)"/g)].map((m) => m[1]);
      assert.ok(rootNames.length > 0, `${id}: 편집 가능 페이지인데 연동 수치 없음`);
    }
  }
});
