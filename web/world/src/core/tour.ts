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
  /** 이 런의 기체가 섰나 — 모델·도식·「궤적만」 어느 쪽이든 **판정이 끝났나**(SceneController `onVehicle`).
   *  기다림 상한(`TOUR_VEHICLE_WAIT_MS`)을 넘기면 호스트가 참으로 넘기고 그 사실을 화면에 적는다. */
  vehicleSettled: boolean;
}

/** 기체 말고 다 섰나 — 투어 런이 선택되고 화면에 서고 재생 가능하며, 대본이 있어야 하면 앉았다. */
function sceneReady(tour: WorldTour, s: TourScene): boolean {
  if (s.chosen !== tour.resultId || s.shownId !== tour.resultId || !s.playable) return false;
  return tour.commsId == null || s.commsKey === tour.commsId;
}

/** 재생을 시작해도 되나 — 투어 런이 **선택되고 화면에 실제로 서고** 재생 가능하며,
 *  대본이 있어야 하는 투어면 그 대본이 앉은 뒤여야 하고, **기체가 선 뒤**여야 한다.
 *
 *  기체 모델은 장면 뒤에 따라온다(SceneController `syncVehicle` — 이 런의 기체 문서를 받고 GLB를 받는다).
 *  장면만 보고 시작하면 투어가 보여 주려던 바로 그 발사 장면이 빈 레일로 흘러간다(리뷰 확정 — 예전에는
 *  자산 단계에서 모델을 먼저 읽어 이 틈이 없었다). */
export function tourReady(tour: WorldTour, s: TourScene): boolean {
  return sceneReady(tour, s) && s.vehicleSettled;
}

/** 기체만 남았나 — 호스트가 이때부터 기다림 상한을 잰다(모델 요청이 멈추면 투어가 영영 안 서지 않게). */
export function tourAwaitsVehicle(tour: WorldTour, s: TourScene): boolean {
  return sceneReady(tour, s) && !s.vehicleSettled;
}

/** 기체를 기다리는 상한 [ms] — 조율자 워치독(views/tour.js·lib/showcase.js 90 s) 안쪽이라, 넘겨도 투어는
 *  기체 없이라도 시작하고 **그 사실을 말한다**(워치독이 "재생이 안 섰다"로 멈추는 것보다 낫다). */
export const TOUR_VEHICLE_WAIT_MS = 15_000;

/** 기다림 상한을 넘겨 기체 없이 시작했다는 한 줄 — 기체가 서면 화면이 거둔다. */
export const TOUR_VEHICLE_LATE_NOTE =
  `기체가 ${TOUR_VEHICLE_WAIT_MS / 1000}초 안에 서지 않아 투어 재생을 기체 없이 시작했습니다 — `
  + "기체가 도착하면 그 자리부터 그립니다(사유는 「캡션」).";

/** 투어 재생의 시점 — **추적**. 화면의 첫 시점(자유 궤도, SceneController `mode`)은 바다·해안을 보이려고
 *  장면 규모(수백 m)로 멀리 서 있어, 그대로 재생하면 기체가 점도 안 된다(쇼케이스 e2e 실측: 가상환경 단계
 *  내내 기체가 안 보였고, 손으로 [추적]을 누르자 기체·발사관이 섰다). 투어·쇼케이스가 보여 주려는 것은
 *  이 런의 비행이라 재생을 켜는 그 자리에서 기체를 따라가는 시점으로 옮긴다 — 사용자는 재생 중에도 버튼으로
 *  다른 시점을 고를 수 있다. 문자열 값은 lib/camera `CamMode`의 한 원소다(core는 lib를 들이지 않는다). */
export const TOUR_CAM_MODE = "chase" as const;

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
