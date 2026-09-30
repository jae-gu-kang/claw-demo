/** 고른 기체의 미션 템플릿으로 화면 칸을 채우는 배선 — 판단은 lib/missiontemplate.js (06 §8).

탭마다 같은 세 줄(문서 받기 → 손대지 않은 칸만 바꾸기 → 템플릿이 없으면 말하기)을 베끼면 탭마다 규칙이 갈린다.
여기 한 벌만 둔다.
*/

import {
  templateDefaults, untouchedUpdates,
} from "../lib/missiontemplate.js";
import { selectedDocument } from "./profilepick.js";

/** inputs {칸: <input>} 중 폴백 그대로인 칸만 next 값으로 바꾼다 — 바꾼 칸 이름을 돌려준다. */
export function applyUntouched(inputs, fallback, next) {
  const current = Object.fromEntries(Object.entries(inputs).map(([k, n]) => [k, n.value]));
  const up = untouchedUpdates(current, fallback, next);
  for (const [k, v] of Object.entries(up)) inputs[k].value = v;
  return Object.keys(up);
}

// 탭을 떠났다 와도 모듈에 사는 상태(엔벨로프 폼·시뮬 모드 표)는 **페이지당 한 번만** 채운다 —
// 다시 들어올 때마다 채우면, 사용자가 일부러 폴백과 같은 값으로 고친 칸을 「손대지 않았다」로 읽고 덮는다.
// 기체를 바꾸면 페이지를 다시 읽으므로(profilepick.js) 이 기록도 함께 비워진다
const filledOnce = new Set();
export const firstTimeThisPage = (key) => (filledOnce.has(key) ? false : (filledOnce.add(key), true));

/** 고른 기체의 화면 기본값 묶음(templateDefaults). 못 받으면 null — 폴백으로 동작하되 화면이 말한다(DOC_FAILED_HINT). */
export const selectedDefaults = () => selectedDocument().then(templateDefaults).catch(() => null);
