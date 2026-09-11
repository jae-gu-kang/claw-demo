/** 가이드 투어(D1)의 가상환경 쪽 판정 — 순수 함수만 (WorldTab.tsx는 JSX라 테스트 불가).
 *
 * 조율자는 호스트(web/js/views/tour.js)다. 여기는 "지금 재생을 시작해도 되나 ·
 * 투어가 어긋났나 · 끝에 닿았나"만 답한다. store 키의 **수명은 조율자가 소유**한다 —
 * 이 번들은 읽기만 한다(React effect에서 읽고 지우면 dev StrictMode의 이중 마운트
 * 두 번째가 빈 키를 본다).
 */

export interface WorldTour {
  token: string;
  resultId: string;
  /** 준비된 교신 대본 id — null이면 교신 없이 재생한다(생성 실패가 투어를 멈추지 않는다). */
  commsId: string | null;
  speed: number;
  voice: boolean;
  /** 이 시각에 닿으면 끝낸다(정지 + 여유) — null이면 데이터 끝까지. */
  endT: number | null;
}

const str = (v: unknown): string | null => (typeof v === "string" && v !== "" ? v : null);
const num = (v: unknown): number | null =>
  (typeof v === "number" && Number.isFinite(v) ? v : null);

/** store 값 → 투어. 형상이 틀리면 null — 투어가 아닌 것으로 조용히 지나간다
 *  (여기서 던지면 남이 쓰는 키 하나가 가상환경 탭을 통째로 못 뜨게 만든다). */
export function readTour(v: unknown): WorldTour | null {
  if (v == null || typeof v !== "object") return null;
  const o = v as Record<string, unknown>;
  const token = str(o.token);
  const resultId = str(o.resultId);
  if (token == null || resultId == null) return null;
  const speed = num(o.speed);
  return {
    token,
    resultId,
    commsId: str(o.commsId),
    // 0·음수·NaN 배속은 재생이 흐르지 않는다 — 투어가 영영 끝나지 않는다
    speed: speed != null && speed > 0 ? speed : 1,
    voice: o.voice === true,
    endT: num(o.endT),
  };
}

export interface TourScene {
  chosen: string | null;
  shownId: string | null;
  playable: boolean;
  commsKey: string | null;
}

/** 재생을 시작해도 되나 — 투어 런이 **선택되고 화면에 실제로 서고** 재생 가능하며,
 *  대본이 있어야 하는 투어면 그 대본이 앉은 뒤여야 한다. */
export function tourReady(tour: WorldTour, s: TourScene): boolean {
  if (s.chosen !== tour.resultId || s.shownId !== tour.resultId || !s.playable) return false;
  return tour.commsId == null || s.commsKey === tour.commsId;
}

/** 투어가 어긋났나 — 사유 문장 또는 null. 목록을 아직 모르면 판단하지 않는다. */
export function tourMismatch(
  tour: WorldTour,
  s: { chosen: string | null; resultIds: readonly string[] },
): string | null {
  if (s.resultIds.length === 0) return null; // 아직 목록을 모른다 — 기다린다
  if (!s.resultIds.includes(tour.resultId)) {
    // 목록에 없으면 화면은 최신으로 **조용히 폴백**한다 — 그 런을 투어로 틀지 않는다
    return "투어가 돌린 런이 결과 목록에 없습니다 — 저장소 보존 상한에 밀렸을 수 있습니다.";
  }
  if (s.chosen !== tour.resultId) return "다른 결과를 골라 투어를 멈췄습니다.";
  return null;
}

/** 조율자가 투어를 거뒀나 — [중단]·실패·닫기에서 조율자는 `worldTour`를 지운다.
 *  되돌아오는 구독 창구가 없어(MountDeps.store는 get/set뿐) **재생 중 프레임에서**
 *  읽어 본다. 안 보면 카드는 "멈췄다"고 적어 둔 채 기체는 계속 날고 교신은 계속
 *  말한다 — 카드가 하지 않는 일을 말하게 되는 자리.
 *  토큰이 바뀐 경우(새 투어가 걸렸다)도, 형상이 깨진 경우도 멈춤으로 본다 —
 *  판정 불가를 "계속"으로 눙치면 옛 재생이 남의 투어 위에서 돈다. */
export function tourStopped(v: unknown, tour: WorldTour): boolean {
  return readTour(v)?.token !== tour.token;
}

/** 끝에 닿았나 — 기체가 선 뒤의 빈 구간(t_end까지)을 청중에게 보이지 않으려는 것. */
export function tourShouldEnd(tour: WorldTour, t: number | null): boolean {
  return tour.endT != null && t != null && t >= tour.endT;
}
