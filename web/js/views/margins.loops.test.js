// 마진 맵 탭 루프 편집 — 문서 게인을 **루프마다** 따라가고(round1 #4), 게인 출처가 오기 전의 [실행]이 루프 0개로
// 돌지 않는다(round1 #5). node --test, 가짜 DOM·가짜 fetch (margins.test.js와 같은 틀 — 모듈 상태가 섞이지 않게 파일을 나눈다)
import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";

import { installDom } from "./testdom.js";

installDom(); // 뷰 import보다 먼저

const { render } = await import("./margins.js");

const DOC = JSON.parse(readFileSync(
  new URL("../../../engine/claw/profile/examples/delta_demo.json", import.meta.url), "utf8"));

// 규칙 스케줄 두 자리(마하에 따라 게인이 바뀐다) + 스케줄 안 한 요 자리 — 가운데 마하와 「게인 읽을 마하」가 다른 kp를 준다
const CATALOG = {
  slots: [
    { name: "pitch.k_rate", available: true, scheduled: true, design: 0.6,
      table: { axes: { mach: [0.1, 0.3] }, data: [0.8, 0.4] } },
    { name: "roll.k_rate", available: true, scheduled: true, design: -0.4,
      table: { axes: { mach: [0.1, 0.3] }, data: [-0.5, -0.3] } },
    { name: "yaw.k_rate", available: true, scheduled: false, design: 1.2, table: null },
  ],
};

const posts = [];
let releaseCatalog = null;
const reply = (status, data) => ({ ok: status < 400, status, text: async () => JSON.stringify(data) });
globalThis.fetch = (url, opts = {}) => {
  const path = url.replace(/^\/api/, "");
  const method = opts.method ?? "GET";
  if (method === "POST") posts.push({ path, body: JSON.parse(opts.body) });
  const ok = (data) => Promise.resolve(reply(200, data));
  if (path.startsWith("/profiles/")) return ok({ document: DOC });
  // 카탈로그는 붙잡아 두었다가 시험이 푼다 — 느린 첫 호출(Render 냉간 기동)
  if (path === "/gains/catalog") return new Promise((resolve) => { releaseCatalog = () => resolve(reply(200, CATALOG)); });
  if (path === "/design/defaults") return ok({ config: {} });
  if (method === "POST" && path === "/analysis/margin-map") return ok({ id: `mjob${posts.length}` });
  if (path.startsWith("/jobs/")) return new Promise(() => {}); // 잡은 끝나지 않는다 — 요청 모양만 본다
  return Promise.resolve(reply(404, { detail: `stub에 없는 경로: ${method} ${path}` }));
};

const tick = () => new Promise((r) => setTimeout(r, 5));
async function waitFor(cond, what, ms = 2000) {
  for (let t = 0; t < ms; t += 5) {
    if (cond()) return;
    await tick();
  }
  assert.fail(`기다렸지만 오지 않았다: ${what}`);
}
const textOf = (n) => (typeof n === "string" ? n : n?.nodeType === 3 ? n.data : (n?.children ?? []).map(textOf).join(""));
const buttonOf = (root, label) => root.find("button").find((b) => textOf(b).startsWith(label));
const mapPosts = () => posts.filter((p) => p.path === "/analysis/margin-map");

test("게인 출처가 오기 전에 [실행] — 루프 0개로 걸지 않고, 받은 뒤 문서 게인 3루프로 건다 (round1 #5)", async () => {
  const root = render();
  await waitFor(() => releaseCatalog, "카탈로그 요청");
  // 루프 칸이 비어 있는 까닭을 말한다(「문서에 게인이 없다」로 읽히지 않게)
  buttonOf(root, "개루프 정의").emit("click");
  assert.ok(textOf(root).includes("문서 게인을 받는 중"), "받는 중이라고 말한다");
  buttonOf(root, "실행").emit("click");
  for (let i = 0; i < 10; i += 1) await tick();
  assert.equal(mapPosts().length, 0, "출처가 오기 전에는 잡을 걸지 않는다");
  buttonOf(root, "실행").emit("click"); // 기다리는 사이 한 번 더 — 두 번 걸리지 않는다
  releaseCatalog();
  await waitFor(() => mapPosts().length === 1, "받은 뒤의 마진 맵 요청");
  for (let i = 0; i < 10; i += 1) await tick();
  assert.equal(mapPosts().length, 1, "한 번만 건다");
  const loops = mapPosts()[0].body.loops;
  assert.deepEqual(loops.map((l) => [l.name, l.gain_source]),
    [["pitch_q", "profile"], ["roll_p", "profile"], ["yaw_r", "profile"]]);
});

test("yaw_r kp만 고친 뒤 「게인 읽을 마하」를 바꿔도 pitch_q·roll_p는 칸별 문서 게인이다 (round1 #4)", async () => {
  // 앞 시험의 잡이 아직 도는 중이라(가짜 잡은 끝나지 않는다) [실행]은 이중 제출 가드에 걸린다 — 여기서는 편집 표와
  // 루프 칸의 게인 기록 미리보기(제출과 같은 runGainInfo 조립)를 본다
  releaseCatalog = null;
  const root = render(); // 재진입 — 카탈로그를 다시 받는다
  await waitFor(() => releaseCatalog, "카탈로그 요청");
  releaseCatalog();
  await waitFor(() => root.find("tr").some((tr) => tr.find("input")[0]?.value === "yaw_r"), "문서 게인 루프 행");
  const rowOf = (name) => root.find("tr").find((tr) => tr.find("input")[0]?.value === name);
  const kpOf = (name) => rowOf(name).find("input")[1].value;
  const pitchBefore = kpOf("pitch_q");
  // yaw_r kp만 고친다
  const yawKp = rowOf("yaw_r").find("input")[1];
  yawKp.value = "1.1";
  yawKp.emit("input", { target: yawKp });
  // 「게인 읽을 마하」를 바꾼다 — 손대지 않은 두 루프는 새 점의 문서 게인으로 바뀌고 yaw_r은 적은 값 그대로
  const refMach = root.find("input").find((i) => i.attrs.placeholder === "격자 가운데");
  refMach.value = "0.25";
  refMach.emit("input", { target: refMach });
  await waitFor(() => kpOf("pitch_q") !== pitchBefore, "pitch_q가 새 점의 게인을 따라감");
  assert.equal(Number(kpOf("pitch_q")), 0.8 + (0.4 - 0.8) * 0.75);
  assert.equal(Number(kpOf("roll_p")), -0.5 + (-0.3 + 0.5) * 0.75);
  assert.equal(kpOf("yaw_r"), "1.1", "고친 루프는 그대로");
  // 루프 칸의 미리보기 — 손으로 적은 값은 yaw_r 하나뿐이다(종전: pitch_q·roll_p까지 「손으로 적은 값」)
  const note = textOf(root);
  assert.ok(note.includes("손으로 적은 루프(yaw_r)"), note);
  assert.ok(!note.includes("손으로 적은 루프(pitch_q"), "손대지 않은 루프를 손으로 적은 값이라 부르지 않는다");
});
