import { strict as assert } from "node:assert";
import { describe, it } from "node:test";

import {
  HOLD_S, SPEECH_MAX_SPEED, lineAt, nextSpeech, normalizeScript, speakerLabel,
  type SpeechState,
} from "./comms.ts";

const L = (t: number, text = `대사 ${t}`, speaker = "TOWER") => ({ t, speaker, text });

describe("normalizeScript", () => {
  it("정상 대본은 시각 오름차순으로 정렬만 한다", () => {
    const out = normalizeScript([L(10), L(3), L(7)], null);
    assert.deepEqual(out.lines.map((l) => l.t), [3, 7, 10]);
    assert.deepEqual(out.notes, []);
  });

  it("규격 밖 대사는 버리되 버린 사실을 사유로 남긴다 — 조용한 폐기 금지", () => {
    const out = normalizeScript(
      [L(5), { t: Number.NaN, speaker: "TOWER", text: "x" },
        { t: 3, speaker: "UAV", text: "" }, { t: -1, speaker: "UAV", text: "y" },
        "문자열" as unknown],
      null,
    );
    assert.equal(out.lines.length, 1);
    assert.ok(out.notes.length >= 1);
    assert.match(out.notes.join(" "), /4줄 제외/);
  });

  it("tEnd를 주면 범위 밖 시각을 버린다 — 런보다 긴 대본은 화면이 못 보여준다", () => {
    const out = normalizeScript([L(5), L(500)], 100);
    assert.deepEqual(out.lines.map((l) => l.t), [5]);
    assert.match(out.notes.join(" "), /1줄 제외/);
  });

  it("배열이 아니면 빈 대본 + 사유", () => {
    const out = normalizeScript({ lines: [] }, null);
    assert.deepEqual(out.lines, []);
    assert.equal(out.notes.length, 1);
  });
});

describe("speakerLabel", () => {
  it("enum 화자는 우리말 콜사인, 그 밖은 위장 없이 그대로", () => {
    assert.equal(speakerLabel("TOWER"), "고흥 타워");
    assert.equal(speakerLabel("UAV"), "CLAW-01");
    assert.equal(speakerLabel("GCS"), "GCS"); // 스키마 밖 — CLAW-01로 뭉개지 않는다
  });
});

describe("lineAt", () => {
  const lines = [L(10), L(20), L(30)];

  it("현재 t 이하의 마지막 대사를 고른다 — 경계 포함 (hold 무시 시)", () => {
    assert.equal(lineAt(lines, 10, Infinity), 0);
    assert.equal(lineAt(lines, 19.9, Infinity), 0);
    assert.equal(lineAt(lines, 20, Infinity), 1);
    assert.equal(lineAt(lines, 31, Infinity), 2);
  });

  it("첫 대사 전·t 없음·빈 대본은 null", () => {
    assert.equal(lineAt(lines, 9.9), null);
    assert.equal(lineAt(lines, null), null);
    assert.equal(lineAt([], 15), null);
  });

  it("hold를 넘기면 내린다 — 자막이 화면에 영원히 붙어 있지 않게", () => {
    assert.equal(lineAt(lines, 30 + HOLD_S, HOLD_S), 2);
    assert.equal(lineAt(lines, 30 + HOLD_S + 0.1, HOLD_S), null);
    // 사이 공백: 10번 대사가 hold를 넘겨 내려간 뒤 20번 전까지는 빈 화면
    assert.equal(lineAt(lines, 10 + HOLD_S + 0.1, HOLD_S), null);
  });
});

describe("nextSpeech", () => {
  const init: SpeechState = { scriptKey: null, spokenIdx: null, lastT: null, active: false };
  const now = (over: Partial<Parameters<typeof nextSpeech>[1]> = {}) => ({
    t: 10, playing: true, speed: 1, enabled: true, index: 0 as number | null,
    scriptKey: "s1" as string | null, ...over,
  });

  it("새 대사 인덱스에 도달하면 한 번만 말한다 — rAF가 같은 인덱스를 초당 60번 들고 온다", () => {
    const r1 = nextSpeech({ ...init, scriptKey: "s1" }, now());
    assert.deepEqual(r1.action, { kind: "speak", index: 0 });
    const r2 = nextSpeech(r1.state, now({ t: 10.02 }));
    assert.equal(r2.action.kind, "none"); // 같은 인덱스 재발화 금지
    const r3 = nextSpeech(r2.state, now({ t: 20, index: 1 }));
    assert.deepEqual(r3.action, { kind: "speak", index: 1 });
  });

  it("대본이 바뀌면 백지에서 시작한다 — 다른 런의 진행을 이어받지 않는다", () => {
    const st: SpeechState = { scriptKey: "s1", spokenIdx: 2, lastT: 30, active: true };
    const r = nextSpeech(st, now({ scriptKey: "s2", t: 5, index: null }));
    assert.equal(r.action.kind, "cancel");
    assert.equal(r.state.spokenIdx, null);
    assert.equal(r.state.scriptKey, "s2");
  });

  it("되감기·뒤로 점프는 끊고 리셋한다 — 안 하면 되감아도 다시 안 말한다", () => {
    const st: SpeechState = { scriptKey: "s1", spokenIdx: 1, lastT: 25, active: true };
    const r = nextSpeech(st, now({ t: 12, index: 0 }));
    assert.equal(r.action.kind, "cancel");
    assert.equal(r.state.spokenIdx, null);
    const r2 = nextSpeech(r.state, now({ t: 12.1, index: 0 }));
    assert.deepEqual(r2.action, { kind: "speak", index: 0 }); // 다시 말한다
  });

  it("일시정지는 끊되 진행은 기억한다 — 재개 시 같은 대사를 또 읽지 않는다", () => {
    const st: SpeechState = { scriptKey: "s1", spokenIdx: 1, lastT: 25, active: true };
    const r = nextSpeech(st, now({ t: 25, index: 1, playing: false }));
    assert.equal(r.action.kind, "cancel"); // 말하던 문장이 정지 후에도 이어지면 화면과 소리가 갈린다
    assert.equal(r.state.spokenIdx, 1);
    const r2 = nextSpeech(r.state, now({ t: 25.1, index: 1 }));
    assert.equal(r2.action.kind, "none"); // 재개 — 재발화 없음
  });

  it("고배속에서는 음성을 내지 않고 지나간 대사도 몰아 읽지 않는다", () => {
    const st: SpeechState = { scriptKey: "s1", spokenIdx: 0, lastT: 10, active: true };
    const r = nextSpeech(st, now({ t: 40, index: 2, speed: SPEECH_MAX_SPEED * 2 }));
    assert.equal(r.action.kind, "cancel");
    assert.equal(r.state.spokenIdx, 2); // 따라잡기 — 저배속 복귀 시 연발 방지
    const r2 = nextSpeech(r.state, now({ t: 41, index: 2, speed: 1 }));
    assert.equal(r2.action.kind, "none");
  });

  it("음성을 끄면 즉시 조용해지고, 켜면 현재 대사부터 다시 산다", () => {
    const st: SpeechState = { scriptKey: "s1", spokenIdx: 0, lastT: 10, active: true };
    const r = nextSpeech(st, now({ t: 20, index: 1, enabled: false }));
    assert.equal(r.action.kind, "cancel");
    const r2 = nextSpeech(r.state, now({ t: 20.1, index: 1, enabled: false }));
    assert.equal(r2.action.kind, "none"); // 꺼진 동안 cancel 연발 없음 (전이에서만)
    const r3 = nextSpeech(r2.state, now({ t: 30, index: 2, enabled: true }));
    assert.deepEqual(r3.action, { kind: "speak", index: 2 });
  });

  it("끝에 닿은 정지는 말하던 대사를 끊지 않는다 — 일시정지와 다르다", () => {
    const st: SpeechState = { scriptKey: "s1", spokenIdx: 2, lastT: 40, active: true };
    const r = nextSpeech(st, now({ t: 40, index: 2, playing: false, ended: true }));
    assert.equal(r.action.kind, "none"); // cancel이면 마지막 교신이 늘 잘린다
    assert.equal(r.state.active, true);
    assert.equal(r.state.spokenIdx, 2);
  });

  it("끝에 닿으며 새 대사에 도달했으면 그것까지 말한다 — 마지막 줄이 통째로 빠지지 않게", () => {
    const st: SpeechState = { scriptKey: "s1", spokenIdx: 1, lastT: 38, active: false };
    const r = nextSpeech(st, now({ t: 40, index: 2, playing: false, ended: true }));
    assert.deepEqual(r.action, { kind: "speak", index: 2 });
  });

  it("음성이 꺼져 있으면 끝에서도 조용하다 — 끝 분기가 꺼짐을 덮지 않는다", () => {
    const st: SpeechState = { scriptKey: "s1", spokenIdx: 1, lastT: 38, active: true };
    const r = nextSpeech(st,
      now({ t: 40, index: 2, playing: false, ended: true, enabled: false }));
    assert.equal(r.action.kind, "cancel");
  });

  it("표시 대사가 없으면(홀드 만료) 말하던 문장은 자연히 끝나게 둔다", () => {
    const st: SpeechState = { scriptKey: "s1", spokenIdx: 1, lastT: 25, active: true };
    const r = nextSpeech(st, now({ t: 28, index: null }));
    assert.equal(r.action.kind, "none");
    assert.equal(r.state.spokenIdx, 1);
  });
});
