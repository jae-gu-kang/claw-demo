/** 가이드 투어(D1) 판단 — 단계·사전 판정·끝 시각·마무리·캡션 (순수 로직).

조립·순서 제어는 views/tour.js. 여기 있는 것은 **DOM 없이 답이 정해지는 질문**들이다
(lib/stage.js 규약). 캡션은 **기존 산출물**로만 만든다 — 투어의 LLM 호출은 미션
초안과 교신 대본 둘뿐이고(사용자 결정), 해설을 위해 한 번 더 부르지 않는다.
*/

import { dryRun } from "./missiondraft.js";
import { landingSummary } from "./replay.js";

/** 가상환경의 음성 게이트(core/comms.ts SPEECH_MAX_SPEED)와 같은 값 — 번들 경계를
 *  넘는 짝이라 주석만으로는 갈린다. 캡션이 이 상수로 **스스로 판정**하므로, 배속이
 *  게이트를 넘으면 "음성"이라 적지 않는다(적어 놓고 조용한 것이 더 나쁜 거짓말이다).
 *  관계는 tour.test.js가 수치로 고정한다. */
export const SPEECH_GATE = 5;
/** 투어 재생 배속 — 게이트 아래여야 교신이 들린다. 대사가 이륙·상승에 몰리는데
 *  빠르면 서로 끊는다(speak가 앞 발화를 끊는다). */
export const TOUR_SPEED = 2;
/** 정지 뒤 여유 [s] — 기체가 선 다음 t_end까지 남은 빈 구간을 청중에게 보이지 않는다. */
export const TAIL_S = 3;

export const STAGES = Object.freeze([
  { key: "draft", label: "미션 초안" },
  { key: "sim", label: "시뮬레이션" },
  { key: "comms", label: "교신 대본" },
  { key: "play", label: "3D 재생" },
  { key: "finale", label: "착륙 요약" },
]);

/** 시뮬을 걸기 전에 초안을 판정한다 — 422를 시뮬 탭에만 띄우고 투어가 조용히
 *  멈추는 일이 없게. 막는 것은 **검증 정본이 거부할 것**(dryRun)과 빈 미션이고,
 *  정규화가 이미 고친 것(모르는 축을 off로 등)은 경고로만 남긴다. */
export function precheck(norm) {
  const blockers = [];
  if (!norm.modeRows.length) blockers.push("모드 행이 없다 — 돌릴 미션이 없다");
  blockers.push(...dryRun(norm));
  // 같은 말을 막힘과 경고로 두 번 하지 않는다 (normalizeDraft도 빈 모드를 말한다)
  const warnings = norm.modeRows.length
    ? norm.issues
    : norm.issues.filter((m) => !m.startsWith("모드 행이 없다"));
  return { blockers, warnings };
}

/** 진행 스테퍼 — 지난 단계는 완료, 지금은 진행, 실패는 그 자리에 남는다.
 *  stage "done" = 투어 완주(전부 완료). */
export function stepperModel(stage, failedAt = null) {
  const at = STAGES.findIndex((s) => s.key === stage);
  const done = at < 0 ? STAGES.length : at;
  return STAGES.map((s, i) => ({
    key: s.key,
    label: s.label,
    state: s.key === failedAt ? "failed"
      : i < done ? "done"
      : i === done ? "active" : "todo",
  }));
}

/** 재생을 끝낼 시각 — 정지 + 여유. 정지가 없는 미션(착륙 안 함)은 null이라
 *  데이터 끝까지 재생한다. 값은 meta.phases에서만 온다(신호 재계산 금지 규약). */
export function endTimeFor(body) {
  const st = body?.meta?.phases?.stop_t;
  return typeof st === "number" && Number.isFinite(st) ? st + TAIL_S : null;
}

/** 마무리 카드 — **시뮬 탭과 같은 착륙 요약**을 쓴다(같은 stride로 받은 같은 본문이라
 *  두 화면의 수치가 같다). 없으면 빈 표가 아니라 그 사실을 문장으로 낸다. */
export function finaleModel(body) {
  const rows = landingSummary(body);
  return {
    rows,
    note: rows.length
      ? null
      : "착륙 구간이 없는 미션이다 — 접지·정지 시각이 없어 착륙 요약을 낼 것이 없다",
  };
}

/** 단계 캡션 — 전부 이미 있는 산출물에서 나온다(초안 요약·가정, 모드 사슬,
 *  잡 진행률, 교신 줄 수). 새 LLM 호출은 없다. */
export function captionFor(stage, ctx = {}) {
  switch (stage) {
    case "draft": {
      const d = ctx.draft;
      if (!d) return `「${ctx.intent ?? ""}」 — 미션 초안을 만드는 중`;
      const head = d.summary || "미션 초안을 받았다";
      // 가정은 앞 둘만 — 캡션은 한 줄이고, 전량은 초안 패널(시뮬 탭)에 있다
      const a = (d.assumptions ?? []).slice(0, 2);
      return a.length ? `${head} — 가정: ${a.join(" · ")}` : head;
    }
    case "sim": {
      const chain = (ctx.modes ?? []).join(" → ") || "미션";
      const pct = typeof ctx.progress === "number"
        ? ` (${Math.round(ctx.progress * 100)}%)` : "";
      return `폐루프 시뮬레이션 — ${chain}${pct}`;
    }
    case "comms":
      // 교신 실패는 투어를 멈추지 않는다 — 사유를 달고 재생으로 간다
      return ctx.failed ? `교신 없이 계속한다 — ${ctx.failed}` : "관제 교신 대본을 만드는 중";
    case "play": {
      const lines = ctx.lines ?? 0;
      // 배속이 게이트를 넘으면 가상환경이 자막만 흘린다 — 그때 "음성"이라 적으면
      // 카드가 하지 않는 일을 말하게 된다
      return `3D 재생 — ${lines > 0 ? `교신 ${lines}줄` : "교신 없음"} · ${TOUR_SPEED}×`
        + (ctx.voice && lines > 0 && TOUR_SPEED <= SPEECH_GATE ? " · 음성" : "");
    }
    case "finale":
    case "done":
      return "착륙 요약";
    default:
      return "";
  }
}
