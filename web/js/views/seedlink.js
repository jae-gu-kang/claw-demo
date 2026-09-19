/** 게인 미설계 오류 표시 + 「기체 탭 → 초기 게인」 안내 링크 (06 §4·§8).

게인·자동 설계·시뮬·Autocode·검증 탭이 같은 안내를 세운다 — 문구·링크가 여기 한 벌이다(v1.28의
게인·자동 설계 두 벌을 여기로 접고 나머지 탭에 넓혔다). 판정은 서버 detail의 **경로 대조**
(lib/profile.js needsSeed — /law/design·/law/schedule), 오류 문구는 엔진 detail
그대로(profileErrorText)다 — 여기서 다시 적지 않는다.
*/

import { errorText } from "../api.js";
import { el } from "../dom.js";
import { needsSeed, profileErrorText } from "../lib/profile.js";
import { requestSeedPanel } from "./aircraft.js";

/** 안내 링크 한 줄 — followup은 "…채우면 " 뒤에 붙는 그 탭의 다음 일("이 탭이 섭니다." 등). */
export function seedLinkLine(followup) {
  return el("p", {},
    el("button", { onclick: () => { requestSeedPanel(); location.hash = "#aircraft"; } },
      "기체 탭에서 초기 게인 채우기"),
    el("span", { class: "hint" },
      ` — 초기 게인 빠른 탐색(기체 탭 「게인·δe_trim」 패널)이 부호·크기와 스케줄을 채우면 ${followup}`));
}

/** 오류 → [오류 상자(, 게인 미설계면 링크)] — clear(box).append(...errorWithSeedLink(e, "…")). */
export function errorWithSeedLink(e, followup) {
  const box = el("div", { class: "error-box" }, profileErrorText(e?.detail) ?? errorText(e));
  return needsSeed(e?.detail) ? [box, seedLinkLine(followup)] : [box];
}
