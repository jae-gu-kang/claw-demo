// 블록 다이어그램 데이터 검증 — 드릴다운 허브(블록 클릭 → 서브시스템 페이지)의 계약.
// 기하(SVG 좌표)는 views/diagram.js·subsystems.js 수작성 — 여기선 데이터 계약만 판다.
import { test } from "node:test";
import assert from "node:assert/strict";

import { readFileSync } from "node:fs";

import { BLOCKS, CHAIN, codegenTargets, resolvePath } from "./blocks.js";
// 뷰 모듈이지만 모듈 스코프에서 DOM을 안 건드려 node import 가능 — 배선 드리프트 가드
import { DESIGN_ORDER, TOP_SVG } from "../views/diagram.js";
import { CHIP_LABEL, SUBSYSTEMS } from "../views/subsystems.js";

// main.js는 모듈 스코프에서 DOM을 건드려 import할 수 없다 — 대신 **원문에서 읽는다**.
// 수동 사본을 두면 뷰가 늘 때 조용히 낡아 무효 링크·죽은 탭을 못 잡는다
const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");
const VIEW_HASHES = new Set(
  read("../main.js").match(/const VIEWS = \{([^}]*)\}/)[1]
    .split(",").map((s) => s.trim()).filter(Boolean),
);
const NAV_HASHES = [...read("../../index.html").matchAll(/data-view="([\w-]+)"/g)]
  .map((m) => m[1]);
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
    // title/sub는 TOP_SVG 템플릿에 무이스케이프 보간됨 — 마크업 특수문자 금지 (리뷰 S2).
    // title은 텍스트 노드뿐 아니라 **속성값**으로도 나간다(diagram.js aria-label) —
    // 큰따옴표 하나면 속성이 깨지므로 함께 막는다
    assert.ok(!/["&<>]/.test(b.title + (b.sub ?? "")), `${b.id} title/sub에 "&<> 금지`);
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
      assert.ok(!d.axes, `${b.id} 편집 불가인데 axes 있음`);
    }
    for (const [id, ax] of Object.entries(d.axes ?? {})) {
      assert.ok(ax.group && ax.varName && ax.cPrefix, `${b.id}/${id} 축 계약 불완전`);
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

/** #abc·#AABBCC → #aabbcc (CSS 표기 흔들림 흡수). */
function norm(hex) {
  const h = hex.slice(1).toLowerCase();
  return `#${h.length === 3 ? [...h].map((ch) => ch + ch).join("") : h}`;
}

/** WCAG 2.x 상대휘도 (sRGB 역감마). */
function relLum(hex) {
  const h = norm(hex).slice(1);
  const ch = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const [r, g, b] = ch.map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** 명도대비 — 어느 쪽이 밝은지 몰라도 되게 큰 쪽을 분자로. */
function contrast(a, b) {
  const [x, y] = [relLum(a), relLum(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

test("층 색이 한 벌이다 — diagram.js LAYERS ↔ app.css --l1~--l5 (색이 곧 층 정체성)", () => {
  // 판·칩(JS)과 단계 태그·게인 표기(CSS)가 같은 색이어야 "색으로 층을 되짚는" 독법이
  // 성립한다. 양쪽이 값을 따로 들고 있으므로 여기서 대조한다 (VIEW_HASHES와 같은 관례)
  const css = read("../../css/app.css");
  // 대소문자·3자리 축약까지 받는다 — 안 받으면 "--l1~--l5가 다 있어야 함"으로 실패해
  // 진짜 원인(표기 형식)과 메시지가 어긋난다
  const vars = Object.fromEntries(
    [...css.matchAll(/--l([1-5]):\s*(#[0-9a-fA-F]{3,6})\b/g)].map((m) => [Number(m[1]), norm(m[2])]),
  );
  assert.equal(Object.keys(vars).length, 5, "app.css에 --l1~--l5가 다 있어야 함");
  for (const s of DESIGN_ORDER) {
    assert.equal(s.color, vars[s.n], `층 ${s.n} 색 불일치: JS ${s.color} vs CSS ${vars[s.n]}`);
    // 사본이 하나 더 있다: 그 단계 페이지의 단계 태그 배경 (인라인 style이라 CSS가 못 닿는다)
    assert.equal(SUBSYSTEMS[s.page].tagBg, s.color,
      `층 ${s.n} 단계 태그 색 불일치: ${s.page} ${SUBSYSTEMS[s.page].tagBg} vs ${s.color}`);
  }
});

test("작은 글자 색 조합이 WCAG AA(4.5:1)를 넘는다 — 배지·태그·칩", () => {
  // 층 색은 판 틴트가 아니라 **흰 글자가 얹히는 배지·태그**다. 밝은 초록/주황으로
  // 잡으면 3.4/2.9까지 떨어진다 — 실제로 그렇게 회귀시킨 적이 있어 테스트로 못박는다.
  // 전부 11px 안팎이라 large text(18.66px bold) 예외가 안 걸린다
  const pairs = [
    ...DESIGN_ORDER.map((s) => [`층 ${s.n} 배지`, s.color, "#ffffff"]),
    ...Object.entries(SUBSYSTEMS).map(([id, s]) => [`${id} 단계 태그`, s.tagBg, "#ffffff"]),
  ];
  // 연한 배경 위 11px 칩·플래그 한 벌 — 색을 여기 적어 두면 CSS만 되돌려도 통과해
  // 가드가 헛돈다. **규칙 자체를 app.css에서 읽어** 전경·배경을 뽑는다
  const css = read("../../css/app.css");
  const cssVar = (name) => norm(css.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{3,6})\\b`))[1]);
  const resolve = (v) => (v.startsWith("var(") ? cssVar(v.slice(6, -1)) : norm(v));
  const rulePair = (selector) => {
    const esc = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const body = css.match(new RegExp(`^${esc}\\s*\\{([^}]*)\\}`, "m"));
    assert.ok(body, `app.css에서 규칙을 못 찾음: ${selector}`);
    const pick = (prop) => {
      // \b는 hex 뒤에만 — var(--ok)의 ')' 뒤에는 단어 경계가 없어 통째로 안 잡힌다
      const m = body[1].match(new RegExp(`(?:^|;)\\s*${prop}:\\s*(var\\(--\\w+\\)|#[0-9a-fA-F]{3,6}\\b)`));
      assert.ok(m, `${selector}에 ${prop} 없음`);
      return resolve(m[1]);
    };
    return [selector, pick("color"), pick("background")];
  };
  pairs.push(...[
    ".bd .chip.ok", ".bd .chip.dft", ".bd .chip.tbd", ".bd .chip.note",
    ".flag.ok", ".flag.bad", ".flag.na",
  ].map(rulePair));
  for (const [what, fg, bg] of pairs) {
    const r = contrast(fg, bg);
    assert.ok(r >= 4.5, `${what}: ${fg} on ${bg} → ${r.toFixed(2)} < 4.5`);
  }
});

test("최상위 SVG 기하가 유한하다 — viewBox NaN은 보드를 통째로 지운다", () => {
  // 기하는 이제 계산된다(views/diagram.js). BASE_Z·POS 키가 하나만 빠져도
  // P(u, v, undefined)가 NaN을 흘려 viewBox="NaN …"이 되고 보드가 안 그려지는데,
  // 아래 배선 가드는 data-block 정규식만 보므로 그대로 통과한다 — 여기서 잡는다
  const vb = TOP_SVG.match(/viewBox="([^"]+)"/)[1].split(/\s+/).map(Number);
  assert.equal(vb.length, 4);
  for (const n of vb) assert.ok(Number.isFinite(n), `viewBox에 비유한값: ${vb.join(" ")}`);
  assert.ok(vb[2] > 0 && vb[3] > 0, "viewBox 폭·높이가 양수여야 함");
  assert.ok(!/NaN|undefined/.test(TOP_SVG), "SVG 좌표에 NaN/undefined 유입");
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

test("코드 표현 대상: 축 블록은 축마다 한 줄 — 값을 모르는 축은 빼고 편집 여부는 따로", () => {
  const scas = BLOCKS.find((b) => b.id === "scas");
  const ap = BLOCKS.find((b) => b.id === "autopilot");
  const design = {
    pitch: { kp: -2.0 }, roll: { kp: 1.0 }, yaw: { kp: 0.5, washout_tau: 2.0 },
  };

  // 편집 없음 — 설계값으로 채우되 "편집값"은 아니다 (안 고쳤는데 Δ가 뜨면 안 된다)
  const base = codegenTargets(scas, null, design);
  assert.deepEqual(base.map((t) => t.cg.group), ["pitch", "roll", "yaw"]);
  assert.deepEqual(base.map((t) => t.applied), [false, false, false]);
  assert.equal(base[2].values.washout_tau, 2.0);
  assert.deepEqual(base.map((t) => t.cg.varName),
    ["scas_pitch", "scas_roll", "scas_yaw"]);

  // 한 축만 편집 — 그 축만 applied, 나머지는 설계값
  const one = codegenTargets(scas, { yaw: { kp: 0.9 } }, design);
  assert.deepEqual(one.map((t) => t.applied), [false, false, true]);
  assert.equal(one[2].values.kp, 0.9);

  // 설계값을 모르면(카탈로그 실패) 대상에서 뺀다 — 스키마 기본값 0이 "형상"으로
  // 나가면 게인이 죽은 탑재 C를 지금 형상이라고 보여 주게 된다
  assert.deepEqual(codegenTargets(scas, null, null), []);
  assert.deepEqual(codegenTargets(scas, { yaw: { kp: 0.9 } }, null).map((t) => t.cg.group),
    ["yaw"]);

  // 축이 없는 블록은 한 줄, cg는 블록 것 그대로
  assert.deepEqual(codegenTargets(ap, null), [{ values: null, applied: false, cg: ap.detail.codegen }]);
  assert.deepEqual(codegenTargets(ap, { kp_alt: 1 }),
    [{ values: { kp_alt: 1 }, applied: true, cg: ap.detail.codegen }]);
});

test("허브 계약: 시뮬 주입 경로 보유 블록(AP·SCAS·작동기·항법)만 편집 가능", () => {
  const byId = Object.fromEntries(BLOCKS.map((b) => [b.id, b.detail]));
  assert.equal(byId.autopilot.editable, true);
  assert.equal(byId.autopilot.injectKey, "autopilotParams"); // req.autopilot
  assert.equal(byId.actuator.editable, true);
  assert.equal(byId.actuator.injectKey, "actuatorParams"); // req.actuators
  // Simulator actuator_params 예약 키 — 폼·주입 제외 (engine test_sim이 핀)
  assert.deepEqual(byId.actuator.omit, ["pos_lo", "pos_hi", "initial"]);
  assert.equal(byId.nav.editable, true);
  assert.equal(byId.nav.injectKey, "navParams"); // req.nav
  // SCAS는 축이 셋이라 폼이 축 페이지에 붙는다 — store는 {축: kwargs} 한 벌(req.scas)
  assert.equal(byId.scas.editable, true);
  assert.equal(byId.scas.injectKey, "scasParams");
  assert.deepEqual(Object.keys(byId.scas.axes), ["pitch", "roll", "yaw"]);
  // 축 id ↔ 드릴다운 페이지가 어긋나면 폼이 안 붙는다 (views/blocks renderParams)
  assert.deepEqual(Object.keys(byId.scas.axes), Object.keys(SUBSYSTEMS.scas.children));
  assert.equal(byId.schedule.edit.hash, "gains");
  assert.equal(byId.scas.edit.hash, "gains"); // 스케줄 자리·표의 정본은 게인 탭
  // 믹서만 편집처가 없다 — 타면 한계·믹싱 비율은 값이 아니라 형상 결정 [TBD 01 §2.2]
  assert.equal(byId.mixer.editable, false);
  assert.equal(byId.mixer.edit, null);
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

test("헤더 탭이 전부 실제 라우트다 — 죽은 탭 금지", () => {
  assert.ok(NAV_HASHES.length >= 8, `nav 링크 ${NAV_HASHES.length}개 — 파싱 실패?`);
  for (const h of NAV_HASHES) {
    assert.ok(VIEW_HASHES.has(h), `#${h} 탭이 main.js VIEWS에 없다 (누르면 구조도로 폴백)`);
  }
  assert.ok(VIEW_HASHES.has("autocode"), "AUTO CODE 라우트 누락");
});
