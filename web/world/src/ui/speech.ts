/** speechSynthesis 어댑터 — 부작용을 여기에 가둔다 (판정은 core/comms.ts nextSpeech).
 *
 * 브라우저 내장 합성이라 **외부 의존이 0이다** — CSP(`default-src 'self'`)도
 * 폐쇄망도 안 탄다. 지원이 없거나 실패하면 자막만 흐르고 사유를 문장으로
 * 남긴다(reason) — 조용한 비표시 금지 규약.
 */

export interface SpeechPort {
  readonly available: boolean;
  readonly reason: string | null;
  speak(text: string, speaker: string): void;
  cancel(): void;
}

export function makeSpeech(): SpeechPort {
  const synth =
    typeof globalThis !== "undefined" && "speechSynthesis" in globalThis
      ? (globalThis as unknown as { speechSynthesis: SpeechSynthesis }).speechSynthesis
      : null;
  if (synth == null) {
    return {
      available: false,
      reason: "이 브라우저에는 음성 합성(speechSynthesis)이 없습니다 — 자막만 흐릅니다.",
      speak() {},
      cancel() {},
    };
  }
  let active = false;
  // 예약된(아직 제출 전) 발화 — synth.cancel()은 이걸 못 막으므로 직접 지운다.
  // 안 지우면 「speak 예약 → cancel → 타이머 발화」 순서에서 음소거·언마운트
  // **뒤에** 한 줄이 끝까지 재생된다 (리뷰 재현 — 회피책이 연 창)
  let pending: ReturnType<typeof setTimeout> | null = null;
  const clearPending = () => {
    if (pending != null) {
      clearTimeout(pending);
      pending = null;
    }
  };
  return {
    available: true,
    reason: null,
    speak(text: string, speaker: string) {
      clearPending(); // 이전 예약이 남아 있으면 새 대사가 이긴다
      synth.cancel(); // 재생 중인 것도 — 겹치면 순차 재생이 되어 화면과 갈린다
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "ko-KR"; // 음성 선택은 브라우저 몫 — ko 음성이 없으면 기본 음성으로 읽는다
      u.rate = 1.05;
      // 화자 구분 — 목소리 목록은 브라우저마다 달라 고르지 않고 피치로 가른다
      u.pitch = speaker === "TOWER" ? 0.85 : 1.1;
      active = true;
      u.onend = () => { active = false; };
      u.onerror = () => { active = false; }; // 실패도 idempotence 가드를 정직하게
      // cancel() 직후의 동기 speak는 Chrome에서 간헐적으로 조용히 떨어진다
      // (알려진 결함 패턴) — 한 틱 미뤄 회피한다
      pending = setTimeout(() => {
        pending = null;
        synth.speak(u);
      }, 0);
    },
    cancel() {
      clearPending(); // 예약 발화가 취소를 뚫지 않게 — active 가드보다 먼저
      // idempotent — nextSpeech가 전이에서만 cancel을 내지만, 그래도 놀지 않는
      // cancel은 no-op이어야 안전하다 (언마운트 정리가 무조건 부른다)
      if (!active && !synth.speaking) return;
      active = false;
      synth.cancel();
    },
  };
}
