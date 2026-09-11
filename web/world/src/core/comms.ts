/** 교신 대본 판정 — 순수 함수만 (WorldTab.tsx는 JSX라 node --test가 못 읽는다).
 *
 * 서버(routes/llm.py `/llm/comms`)가 LLM으로 만든 대본 {t, speaker, text}[]를
 * 받아 (1) 방어적으로 정규화하고 (2) 재생 시각에 맞는 자막을 고르고 (3) 음성
 * 발화 여부를 **순수 상태 전이**로 판정한다. speechSynthesis 부작용은
 * ui/speech.ts 어댑터가, 화면 조립은 WorldTab이 맡는다 — 판정은 전부 여기라
 * 테스트가 이 파일 하나로 닫힌다 (ui/layout.ts 선례).
 */

export interface CommsLine {
  t: number;
  speaker: string; // 서버 스키마는 "TOWER" | "UAV" enum — 방어적으로 string
  text: string;
}

/** 화자 표기 — 오버레이·드로어 두 표면이 같은 이름을 쓰도록 한 곳에.
 *  스키마 enum 밖의 화자는 위장하지 않고 그대로 보인다. */
export function speakerLabel(s: string): string {
  return s === "TOWER" ? "고흥 타워" : s === "UAV" ? "CLAW-01" : s;
}

/** 자막 유지 시간 [s] — 다음 대사가 없을 때 이만큼 지나면 내린다.
 *  안 내리면 마지막 대사가 화면에 영원히 붙어 있다. */
export const HOLD_S = 6;
/** 이 배속을 넘으면 음성을 내지 않는다 — 대사가 겹쳐 쏟아진다 (자막만). */
export const SPEECH_MAX_SPEED = 5;
/** 되감기 판정 여유 [s] — 부동소수 흔들림을 점프로 오독하지 않게. */
const REWIND_EPS = 0.25;

/** LLM 산출 대본의 방어적 정규화 — 버린 것은 사유(notes)로 남긴다.
 *
 * structured output이 형상을 보장하지만 이 계약이 어긋나도 조용히 죽지 않는다
 * (missiondraft.js normalizeDraft와 같은 자리). tEnd를 주면 런 길이 밖 시각도
 * 버린다 — 화면이 보여줄 수 없는 대사다.
 */
export function normalizeScript(
  raw: unknown,
  tEnd: number | null,
): { lines: CommsLine[]; notes: string[] } {
  const notes: string[] = [];
  if (!Array.isArray(raw)) {
    notes.push("대본이 배열이 아니다 — 서버 응답을 확인할 것");
    return { lines: [], notes };
  }
  const lines: CommsLine[] = [];
  let dropped = 0;
  for (const item of raw) {
    const r = item as { t?: unknown; speaker?: unknown; text?: unknown } | null;
    const t = typeof r?.t === "number" && Number.isFinite(r.t) ? r.t : null;
    const text = typeof r?.text === "string" ? r.text.trim() : "";
    const speaker = typeof r?.speaker === "string" ? r.speaker : "";
    const inRange = t !== null && t >= 0 && (tEnd == null || t <= tEnd);
    if (t === null || !inRange || text === "" || speaker === "") {
      dropped += 1;
      continue;
    }
    lines.push({ t, speaker, text });
  }
  lines.sort((a, b) => a.t - b.t);
  if (dropped > 0) {
    notes.push(`대사 ${dropped}줄 제외 — 시각이 유한하지 않거나 범위 밖이거나 내용이 비었다`);
  }
  return { lines, notes };
}

/** 현재 시각에 보여줄 대사 인덱스 — t 이하의 마지막 대사, hold를 넘기면 null. */
export function lineAt(
  lines: readonly CommsLine[],
  t: number | null,
  holdS: number = HOLD_S,
): number | null {
  if (t == null || lines.length === 0) return null;
  // 이분탐색 — t 이하의 마지막 인덱스
  let lo = 0;
  let hi = lines.length - 1;
  let idx = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const line = lines[mid];
    if (line == null) break; // 도달 불가 — noUncheckedIndexedAccess 몫
    if (line.t <= t) {
      idx = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  const hit = idx >= 0 ? lines[idx] : undefined;
  if (hit == null) return null;
  return t - hit.t > holdS ? null : idx;
}

/** 발화 상태 — 컴포넌트 ref에 사는 값. active는 "지금 소리가 날 수 있는 상태"다
 *  (speak 이후, cancel 전) — 전이에서만 cancel을 내보내 60fps cancel 연발을 막는다. */
export interface SpeechState {
  scriptKey: string | null;
  spokenIdx: number | null;
  lastT: number | null;
  active: boolean;
}

export interface SpeechInput {
  t: number | null;
  playing: boolean;
  speed: number;
  enabled: boolean;
  index: number | null; // lineAt 결과 — 지금 화면에 있는 대사
  scriptKey: string | null; // 대본 식별(결과 id) — 바뀌면 백지
}

export type SpeechAction =
  | { kind: "speak"; index: number }
  | { kind: "cancel" }
  | { kind: "none" };

/** 발화 판정 — rAF마다 불려도 안전한 순수 전이.
 *
 * 답하는 질문들(테스트가 하나씩 고정한다): 같은 인덱스를 두 번 말하지 않는가 ·
 * 되감기/뒤로 점프에서 끊고 다시 말할 수 있는가 · 일시정지에서 끊되 재개 시
 * 재발화하지 않는가 · 고배속에서 몰아 읽지 않는가 · 꺼짐이 즉시 조용한가.
 */
export function nextSpeech(
  prev: SpeechState,
  now: SpeechInput,
): { state: SpeechState; action: SpeechAction } {
  const stop = (state: SpeechState): { state: SpeechState; action: SpeechAction } => ({
    state,
    action: prev.active ? { kind: "cancel" } : { kind: "none" },
  });

  // 대본 교체 — 다른 런의 진행 상태를 이어받지 않는다. 항상 cancel(안전측).
  if (now.scriptKey !== prev.scriptKey) {
    return {
      state: { scriptKey: now.scriptKey, spokenIdx: null, lastT: now.t, active: false },
      action: { kind: "cancel" },
    };
  }
  const key = prev.scriptKey;
  // 되감기·뒤로 점프 — 진행을 백지로 (다음 프레임이 현재 대사를 다시 말한다)
  if (now.t != null && prev.lastT != null && now.t < prev.lastT - REWIND_EPS) {
    return stop({ scriptKey: key, spokenIdx: null, lastT: now.t, active: false });
  }
  const lastT = now.t ?? prev.lastT;
  // 꺼짐·고배속 — 조용히, spokenIdx는 현재 대사로 따라잡아 복귀 시 연발 방지
  if (!now.enabled || now.speed > SPEECH_MAX_SPEED) {
    return stop({
      scriptKey: key,
      spokenIdx: now.index ?? prev.spokenIdx,
      lastT,
      active: false,
    });
  }
  // 일시정지 — 끊되 진행은 기억 (재개 시 같은 대사 재발화 금지)
  if (!now.playing) {
    return stop({ scriptKey: key, spokenIdx: prev.spokenIdx, lastT, active: false });
  }
  // 새 대사 도달 — 말한다. 표시 대사가 없으면(index null) 말하던 것을 자연히 끝낸다.
  if (now.index != null && now.index !== prev.spokenIdx) {
    return {
      state: { scriptKey: key, spokenIdx: now.index, lastT, active: true },
      action: { kind: "speak", index: now.index },
    };
  }
  return {
    state: { scriptKey: key, spokenIdx: prev.spokenIdx, lastT, active: prev.active },
    action: { kind: "none" },
  };
}
