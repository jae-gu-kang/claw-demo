// 매뉴얼 내용·색인 검증 — 글이 그림·스키마와 어긋나지 않는지의 계약.
//
// 매뉴얼은 코드가 아니라 글이라 조용히 낡는다: 페이지를 새로 만들고 설명을 안 쓰거나,
// 게인을 늘리고 어느 페이지에도 안 붙이거나, 소제목을 화면 쪽에 또 적어 두거나.
// 셋 다 화면에서는 멀쩡해 보이므로 여기서 잡는다.
import { test } from "node:test";
import assert from "node:assert/strict";

import { readFileSync } from "node:fs";

import {
  BACKGROUND, BLOCK_DOCS, GAIN_GROUPS, HEADINGS, HOME_SECTIONS, PAGE_DOCS, PAGE_GAINS,
  FLOW_HEADINGS, FOLD_KINDS, TUNING_ORDER, UNDRAWN_GAINS,
  docFor, gainCountFor, gainCoverage, gainsFor,
} from "./manualdoc.js";
import { resolvePath, walkPages } from "./blocks.js";
// 뷰 모듈이지만 순수 데이터라 node import 가능 (blocks.test.js와 같은 근거)
import { SUBSYSTEMS } from "../views/subsystems.js";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

// 엔진 레지스트리에 실존하는 카테고리/이름 — blocks.test.js REGISTRY_REFS와 같은 근거.
// 사본을 두는 이유도 같다: 서버 스키마 404는 화면에서 "단위·기본값 칸이 빈다"로만
// 나타나 아무도 못 알아챈다
const REGISTRY_REFS = new Set([
  "fcl/Autopilot", "fcl/ScasAxis", "fcl/Mixer",
  "actuator/SecondOrderActuator", "guidance/LOS", "nav/ErrorModel",
  "propulsion/SingleEngine", "propulsion/TwinEngine",
]);

/** 매뉴얼의 모든 본문 문자열 — innerHTML 계약 검사의 대상. */
function* allProse() {
  for (const b of BACKGROUND) {
    yield [`배경 "${b.q}"`, b.q];
    for (const a of b.a) yield [`배경 "${b.q}" 본문`, a];
  }
  for (const d of BLOCK_DOCS) {
    for (const f of ["what", "why", "effect"]) yield [`${d.page}.${f}`, d[f]];
    for (const t of d.tuning ?? []) yield [`${d.page} 튜닝`, t];
    for (const [sym, fix] of d.trouble) {
      yield [`${d.page} 증상`, sym];
      yield [`${d.page} 대처 "${sym}"`, fix];
    }
  }
  for (const g of GAIN_GROUPS) {
    yield [`${g.ref} lead`, g.lead];
    for (const [key, r] of Object.entries(g.rows)) {
      for (const f of ["what", "up", "down", "chain"]) {
        if (r[f]) yield [`${g.ref} ${key}.${f}`, r[f]];
      }
      for (const [sym, share] of r.sym ?? []) {
        yield [`${g.ref} ${key} 증상`, sym];
        yield [`${g.ref} ${key} 몫 "${sym}"`, share];
      }
    }
  }
  for (const t of TUNING_ORDER) yield ["튜닝 순서", t];
}

test("블록 문서: 서브시스템 루트 페이지와 1:1 (양방향)", () => {
  const docPages = BLOCK_DOCS.map((d) => d.page);
  assert.equal(new Set(docPages).size, docPages.length, "page 중복");
  // 새 루트 페이지가 설명 없이 나가는 것도, 죽은 문서가 남는 것도 막는다.
  // 매뉴얼이 낡는 첫 번째 방식이 후자다 — 화면에서는 안 보인다
  assert.deepEqual([...docPages].sort(), Object.keys(SUBSYSTEMS).sort());
  assert.deepEqual(PAGE_DOCS, Object.fromEntries(BLOCK_DOCS.map((d) => [d.page, d])));
});

test("블록 문서: 세 소제목 자리가 전부 차 있다", () => {
  for (const d of BLOCK_DOCS) {
    for (const f of Object.keys(HEADINGS)) {
      assert.ok(d[f]?.trim(), `${d.page}.${f} 비어 있음`);
    }
    assert.ok(d.title?.trim() && d.role?.trim(), `${d.page} 제목·역할 비어 있음`);
    assert.ok(d.trouble?.length > 0, `${d.page} 증상 항목 없음`);
  }
});

test("소제목 문자열은 manualdoc.js 한 곳에만 (요구: 한 줄로 바꿀 수 있을 것)", () => {
  // 화면·CSS에 같은 소제목이 또 있으면 교체가 두 곳 편집이 되고, 한쪽만 고치면
  // 화면과 문서가 갈라진다. 원문 검사가 유일한 실효 수단이다.
  //
  // 단순 부분문자열 검사는 못 쓴다 — "기능"은 본문에도 나오는 낱말이라("재생 기능을
  // 쓰면 …") 정상적인 산문을 잡는다. 무해한 등장과 구분되는 것은 **소제목 자리**에
  // 있느냐이므로, JS 문자열 리터럴 통째와 <h1~h6> 안쪽만 본다
  const sources = ["../views/manual.js", "../views/blocks.js", "../views/subsystems.js",
    "../../css/app.css"];
  for (const [field, label] of [...Object.entries(HEADINGS), ...Object.entries(FLOW_HEADINGS)]) {
    const esc = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const asLiteral = new RegExp(`["']${esc}["']`);
    const asHeading = new RegExp(`<h[1-6][^>]*>\\s*${esc}\\s*</h[1-6]>`);
    for (const src of sources) {
      const text = read(src);
      assert.ok(!asLiteral.test(text),
        `${src}에 소제목 "${label}"(${field})이 문자열 리터럴로 박혀 있다 — HEADINGS만 쓸 것`);
      assert.ok(!asHeading.test(text),
        `${src}에 소제목 "${label}"(${field})이 제목 태그로 박혀 있다 — HEADINGS만 쓸 것`);
    }
  }
});

test("게인 사전: ref가 레지스트리 실존 + 행마다 '무엇을'이 있다", () => {
  const refs = GAIN_GROUPS.map((g) => g.ref);
  assert.equal(new Set(refs).size, refs.length, "ref 중복");
  for (const g of GAIN_GROUPS) {
    assert.ok(REGISTRY_REFS.has(g.ref), `${g.ref} 레지스트리에 없음 — 스키마 404`);
    assert.ok(g.page in SUBSYSTEMS, `${g.ref}의 page "${g.page}" 미실존`);
    assert.ok(g.lead?.trim(), `${g.ref} lead 비어 있음`);
    assert.ok(Object.keys(g.rows).length > 0, `${g.ref} 게인 0개`);
    for (const [key, r] of Object.entries(g.rows)) {
      assert.ok(r.what?.trim(), `${g.ref} ${key}: '무엇을'이 없다`);
    }
  }
});

test("본문 문자열: innerHTML 계약 (스크립트·핸들러·마크다운 별표 금지)", () => {
  // manual.js 머리주석이 "마크다운 별표는 렌더되지 않는다"고 경고만 하고 가드가
  // 없었다 — **강조**를 쓰면 화면에 별표가 그대로 뜬다
  for (const [where, s] of allProse()) {
    assert.equal(typeof s, "string", `${where}: 문자열이 아님`);
    assert.ok(!/<script/i.test(s), `${where}: <script 금지`);
    assert.ok(!/\son\w+\s*=/i.test(s), `${where}: on* 핸들러 속성 금지`);
    assert.ok(!/javascript:/i.test(s), `${where}: javascript: URL 금지`);
    assert.ok(!s.includes("**"), `${where}: 마크다운 별표는 안 렌더된다 — <b>를 쓸 것`);
    for (const tag of ["b", "code"]) {
      const open = (s.match(new RegExp(`<${tag}>`, "g")) ?? []).length;
      const close = (s.match(new RegExp(`</${tag}>`, "g")) ?? []).length;
      assert.equal(open, close, `${where}: <${tag}> 짝이 안 맞음`);
    }
  }
});

test("홈 구성은 데이터로 고정 — 상세는 블록 페이지 소관", () => {
  // 코드 모양이 아니라 계약으로 못박는다: 홈에 블록 상세·게인 사전을 되돌리려면
  // 이 목록을 명시적으로 고쳐야 한다 (실수로 되돌아가지 않게)
  assert.deepEqual(HOME_SECTIONS, ["background", "index", "order"]);
  assert.ok(BACKGROUND.length > 0 && TUNING_ORDER.length > 0);
  for (const b of BACKGROUND) assert.ok(b.q?.trim() && b.a?.length > 0, `배경 "${b.q}" 불완전`);
});

test("게인 배치: 49개 전부가 어느 페이지엔가 닿는다 (잔여 규칙 포함)", () => {
  // 게인을 늘리고 지도를 안 고치면 화면 어디에서도 안 보이는데, 사전이 홈에서
  // 사라진 뒤로는 눈으로 알아챌 방법이 없다 — 도달성은 테스트로만 지킬 수 있다
  assert.deepEqual(gainCoverage(), []);
  const total = GAIN_GROUPS.reduce((n, g) => n + Object.keys(g.rows).length, 0);
  assert.equal(total, 49, "게인 수가 변했다 — 지도(PAGE_GAINS)를 함께 고쳤는지 확인");
});

test("게인 배치: 지도의 경로·이름이 전부 실존 (양방향 오타 가드)", () => {
  const pageKeys = new Set([...walkPages(SUBSYSTEMS)].map((w) => w.key));
  for (const [key, names] of Object.entries(PAGE_GAINS)) {
    assert.ok(pageKeys.has(key), `PAGE_GAINS "${key}" — 그런 페이지가 없다`);
    // 해시로 실제로 도달 가능한 경로인가 (resolvePath가 잘라내지 않는가)
    assert.equal(resolvePath(key.split("/"), SUBSYSTEMS).join("/"), key);
    const root = key.split("/")[0];
    const group = GAIN_GROUPS.find((g) => g.page === root);
    assert.ok(group, `PAGE_GAINS "${key}" — 루트 ${root}에 게인 그룹이 없다`);
    assert.equal(new Set(names).size, names.length, `PAGE_GAINS "${key}" 이름 중복`);
    for (const n of names) {
      assert.ok(n in group.rows, `PAGE_GAINS "${key}"의 ${n} — ${group.ref}에 없는 게인`);
    }
  }
  for (const n of UNDRAWN_GAINS) {
    assert.ok(GAIN_GROUPS.some((g) => n in g.rows), `UNDRAWN_GAINS의 ${n} — 실존하지 않음`);
  }
});

test("게인 배치: PI 페이지는 rate 항을 갖지 않는다 (그림과 일치)", () => {
  // 축 캔버스 노트가 "rate 항은 PI 클램프 밖 합산"이라고 못박고 있다 — PI 페이지
  // 그림에 k_rate 삼각형은 없다. 컴포넌트 단위 매핑이면 여기가 조용히 어긋난다
  for (const axis of ["pitch", "roll", "yaw"]) {
    const keys = gainsFor(["scas", axis, "pi"]).flatMap((g) => g.rows.map((r) => r.key));
    assert.ok(!keys.includes("k_rate"), `scas/${axis}/pi에 k_rate가 붙었다`);
    assert.ok(!keys.includes("washout_tau"), `scas/${axis}/pi에 washout_tau가 붙었다`);
    assert.ok(keys.includes("kp") && keys.includes("ki"), `scas/${axis}/pi에 PI 게인이 없다`);
  }
  // washout은 요축에만 (피치·롤은 필터 없음 = 0)
  const yaw = gainsFor(["scas", "yaw"]).flatMap((g) => g.rows.map((r) => r.key));
  assert.ok(yaw.includes("washout_tau"));
  for (const axis of ["pitch", "roll"]) {
    const keys = gainsFor(["scas", axis]).flatMap((g) => g.rows.map((r) => r.key));
    assert.ok(!keys.includes("washout_tau"), `scas/${axis}에 washout_tau가 붙었다`);
  }
});

test("블록 문서 배정: 루트에만 붙고 하위는 루트를 가리킨다", () => {
  const root = docFor(["scas"]);
  assert.ok(root.isRoot && root.doc?.page === "scas" && root.root === "scas");
  const child = docFor(["scas", "pitch", "pi"]);
  // 하위 페이지도 같은 문서를 가리키되 isRoot=false — 뷰가 그걸 보고 전문 대신 띠를 그린다
  assert.ok(!child.isRoot && child.doc?.page === "scas" && child.root === "scas");
  for (const { path } of walkPages(SUBSYSTEMS)) {
    assert.ok(docFor(path).doc, `${path.join("/")} — 루트 문서를 못 찾는다`);
  }
});

// 흐름 설명이 아직 없는 페이지 — **비워 둔 사실을 눈에 보이게** 남기는 자리.
//
// 지금은 비어 있다: 26경로 전부에 설명이 있다. 페이지를 새로 만들고 설명을 안 쓰면
// 여기에 이름이 뜨면서 실패하므로, 새 페이지가 무설명으로 나갈 수 없다.
// (추진부 확정 전까지 plant/prop이 여기 있었다 — 그림이 바뀌는 중에 쓴 산문은
//  화살표 순서와 어긋난 채로 남기 때문이다.)
const FLOW_PENDING = [];

test("흐름 설명: 26개 페이지 전수 (미작성은 명시된 것만)", () => {
  const missing = [];
  for (const { node, key } of walkPages(SUBSYSTEMS)) {
    if (!node.flow) { missing.push(key); continue; }
    const { lead, reads, why } = node.flow;
    assert.ok(lead?.trim(), `${key}: flow.lead 비어 있음`);
    // 두 줄 미만이면 그림 읽는 순서가 아니라 한 줄 요약이다 — lead가 이미 그 자리다
    assert.ok(reads?.length >= 2, `${key}: flow.reads가 ${reads?.length ?? 0}줄 — 순서를 못 이룬다`);
    assert.ok(why?.length >= 1, `${key}: flow.why 없음 — 왜 이 구조인가가 이 필드의 전부다`);
    for (const t of [lead, ...reads, ...why]) {
      assert.ok(t?.trim(), `${key}: flow에 빈 문자열`);
    }
  }
  assert.deepEqual(missing.sort(), [...FLOW_PENDING].sort(),
    "흐름 설명 미작성 페이지가 명시 목록과 다르다");
});

test("흐름 설명: innerHTML 계약 (본문과 같은 규칙)", () => {
  for (const { node, key } of walkPages(SUBSYSTEMS)) {
    if (!node.flow) continue;
    for (const t of [node.flow.lead, ...node.flow.reads, ...node.flow.why]) {
      assert.ok(!/<script/i.test(t), `${key}: <script 금지`);
      assert.ok(!/\son\w+\s*=/i.test(t), `${key}: on* 핸들러 속성 금지`);
      assert.ok(!t.includes("**"), `${key}: 마크다운 별표는 안 렌더된다 — <b>를 쓸 것`);
      const open = (t.match(/<b>/g) ?? []).length;
      const close = (t.match(/<\/b>/g) ?? []).length;
      assert.equal(open, close, `${key}: <b> 짝이 안 맞음 — ${t.slice(0, 40)}`);
    }
  }
});

test("그림 앵커: data-gain은 그 페이지 게인만 가리킨다", () => {
  // 지도에 없는 이름을 그림이 가리키면 열 카드가 없어 **클릭이 죽은 것처럼** 보인다.
  // 단방향 포함이다: 그림은 지도가 아는 게인만 가리킬 수 있고, 지도의 모든 게인이
  // 그림에 있어야 하는 것은 아니다 (값이 안 그려진 자리가 있다)
  for (const { node, key, path } of walkPages(SUBSYSTEMS)) {
    const mine = new Set(gainsFor(path).flatMap((g) => g.rows.map((r) => r.key)));
    for (const m of node.svg.matchAll(/data-gain="([^"]+)"/g)) {
      assert.ok(mine.has(m[1]), `${key}: data-gain="${m[1]}"가 이 페이지 게인이 아니다`);
    }
  }
});

test("그림 앵커: 설명 전용(nblk)·드릴다운 블록에는 안 붙는다", () => {
  // nblk = 엔진 코드에 없는 도해 전용 (blocks.test.js가 data-code/child/p를 막는 것과 같은 이유).
  // data-child와 겹치면 클릭 하나에 뜻이 둘이 된다 — 들어갈 것인가 카드를 열 것인가
  for (const { node, key } of walkPages(SUBSYSTEMS)) {
    for (const tag of node.svg.match(/<[^>]*data-gain="[^"]*"[^>]*>/g) ?? []) {
      assert.ok(!/\bnblk\b/.test(tag), `${key}: 설명 전용(nblk)에 data-gain — ${tag.slice(0, 60)}`);
      assert.ok(!/data-child=/.test(tag), `${key}: 드릴다운 블록에 data-gain — ${tag.slice(0, 60)}`);
    }
  }
});

test("그림 앵커: 한 페이지에서 같은 게인을 두 번 가리키지 않는다", () => {
  // 둘이면 클릭한 쪽이 아니라 먼저 걸린 쪽이 강조된다 (역방향 버튼도 한 곳만 안다)
  for (const { node, key } of walkPages(SUBSYSTEMS)) {
    const names = [...node.svg.matchAll(/data-gain="([^"]+)"/g)].map((m) => m[1]);
    assert.equal(new Set(names).size, names.length, `${key}: data-gain 중복 — ${names}`);
  }
});

test("홈 목차 배지: 블록이 가진 게인 전부를 센다 (잔여분이 아니라)", () => {
  // gainsFor(루트)를 배지에 쓰면 SCAS 0개·오토파일럿 3개로 떠서 "여긴 게인이 없다"로
  // 읽힌다 — 실제로는 6개·18개가 하위 페이지에 흩어져 있을 뿐이다
  for (const g of GAIN_GROUPS) {
    assert.equal(gainCountFor(g.page), Object.keys(g.rows).length, `${g.page} 배지 수 불일치`);
  }
  assert.equal(gainCountFor("scas"), 6);
  assert.equal(gainCountFor("autopilot"), 18);
  assert.equal(gainCountFor("planner"), 0, "게인 없는 블록은 0 (배지 자체가 안 붙는다)");
});

test("게인 배치: 잔여는 '그림에 없는 것'뿐이어야 한다 (도달성 말고 배치를 판다)", () => {
  // gainCoverage()는 도달성만 본다: 새 게인을 PAGE_GAINS에 안 넣어도 잔여 규칙이
  // 루트에 조용히 얹어 주므로 커버리지는 통과한다. 그러면 그 게인은 "그림에 없음"
  // 배지도 없이 엉뚱한 페이지에 앉는다. 잔여의 **내용**을 고정해 그 문을 닫는다
  assert.deepEqual(gainsFor(["scas"]), [], "SCAS 잔여는 없어야 한다 — 세 축이 다 가져간다");
  assert.deepEqual(gainsFor(["guidance"]), [], "유도 잔여는 없어야 한다 — 경로추종이 가져간다");
  const apResidual = gainsFor(["autopilot"]).flatMap((g) => g.rows.map((r) => r.key));
  assert.deepEqual([...apResidual].sort(), [...UNDRAWN_GAINS].sort(),
    "오토파일럿 잔여는 '그림에 없는 게인'과 정확히 같아야 한다 — 다르면 배치를 빠뜨린 것");
});

test("그림 앵커: 게인인 data-p도 페이지 안에서 유일해야 한다", () => {
  // data-p 중복 자체는 표시값 동기 계약상 정상이다(bindSvgParams가 전부 갱신한다).
  // 하지만 그게 게인 앵커를 겸하면 '그림에서 보기'가 문서 순서상 먼저 걸린 쪽으로만
  // 간다 — 어느 쪽인지 사용자는 알 수 없다
  for (const { node, key, path } of walkPages(SUBSYSTEMS)) {
    const mine = new Set(gainsFor(path).flatMap((g) => g.rows.map((r) => r.key)));
    const names = [...node.svg.matchAll(/data-p="([^"]+)"/g)].map((m) => m[1])
      .filter((n) => mine.has(n));
    assert.equal(new Set(names).size, names.length,
      `${key}: 게인을 겸하는 data-p가 중복 — ${names}`);
  }
});

test("접는 섹션 종류는 데이터로 고정 — 늘리고 줄이는 것이 명시적 편집이 되게", () => {
  // 열림 상태를 기억하는 키이자 "무엇을 접는가"의 계약. 화면 쪽에서 문자열을 새로
  // 지어내면 그 섹션만 기억이 안 되는데, 그건 눌러 보기 전엔 안 보인다
  assert.deepEqual(FOLD_KINDS,
    ["flow", "why", "doc", "gains", "notes", "background", "order"]);
  assert.equal(new Set(FOLD_KINDS).size, FOLD_KINDS.length, "종류 중복");
  // 흐름 소제목은 두 fold(flow·why)의 라벨이라 짝이 맞아야 한다
  assert.deepEqual(Object.keys(FLOW_HEADINGS), ["reads", "why"]);
  for (const label of Object.values(FLOW_HEADINGS)) assert.ok(label.trim());
});
