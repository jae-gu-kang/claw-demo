/** LLM 미션 초안 정규화 (시뮬 탭 「미션 초안」 패널) — 순수 로직, 테스트 대상.

서버(routes/llm.py)가 structured output으로 형상을 강제하지만, 이 모듈은 그
계약이 어긋나도 조용히 죽지 않게 **방어적으로** 받는다: 값을 문자열로 강제하고
(표는 문자열 계약이다 — views/sim.js modeRows), 모르는 enum은 안전값으로 두되
**사유를 issues에 남긴다**(조용한 폐기 금지 — 안전값만 넣으면 표가 초안과 다른
것을 말하는데 아무도 모른다). 제출 가능성 판정은 buildModes·buildWaypoints
(검증 정본, lib/mission.js)를 그대로 돌려서 한다 — 여기서 재구현하지 않는다.
*/

import {
  COND_KINDS, LON_AXES, buildModes, buildWaypoints, pathUsage,
} from "./mission.js";

const AXES = new Set(LON_AXES.map((a) => a.value));
const MODE_KEYS = [
  "name", "speed", "lonAxis", "lonValue", "heading", "exitKind", "exitValue", "next",
];
// 실행 조건 중 초안이 만져도 되는 칸 — 미션 의도인 것만. 활주로 제원·측지 원점·
// 항법/작동기/게인 토글·지문은 사이트 사실·센서 구성이라 초안 대상이 아니다
// (routes/llm.py 스키마와 같은 목록 — 정본은 서버, 여기는 방어적 수용).
const RUN_STR = ["mach", "alt", "fuel", "tEnd", "accept"];
const RUN_BOOL = ["groundOn", "launchOn"];

// 퇴화 응답(수천 행)이 표·지도를 통째로 눌러앉히지 않게 하는 상한 — 자르면
// 반드시 issues가 말한다. 정상 미션은 모드 십수 행·WP 수십 개면 충분하다.
const MAX_MODES = 50;
const MAX_WPS = 200;

const str = (v) => (v == null ? "" : String(v));

const strList = (v) => (Array.isArray(v) ? v.map(str).filter((t) => t !== "") : []);

/** 서버 초안 JSON → 표에 앉을 수 있는 형태. 무엇을 고쳤든 issues가 말한다. */
export function normalizeDraft(json) {
  const issues = [];
  const out = {
    summary: "", assumptions: [], warnings: [],
    modeRows: [], wpRows: [], runConditions: {}, issues,
  };
  if (json == null || typeof json !== "object" || Array.isArray(json)) {
    issues.push("초안이 객체가 아니다 — 서버 응답을 확인할 것");
    return out;
  }
  out.summary = str(json.summary);
  out.assumptions = strList(json.assumptions);
  out.warnings = strList(json.warnings);

  let rows = Array.isArray(json.modeRows) ? json.modeRows : [];
  if (!rows.length) issues.push("모드 행이 없다 — 적용할 것이 없다");
  if (rows.length > MAX_MODES) {
    issues.push(`모드가 ${rows.length}행 — 앞 ${MAX_MODES}행만 받았다 (퇴화 응답 방어)`);
    rows = rows.slice(0, MAX_MODES);
  }
  out.modeRows = rows.map((r, i) => {
    const row = Object.fromEntries(MODE_KEYS.map((k) => [k, str(r?.[k])]));
    // enum 두 칸은 **trim해서 저장**한다 — 검사만 trim하고 값을 원본으로 두면
    // " alt"가 검사는 통과하는데 표의 select는 정확 일치라 off를 보여 주면서
    // buildModes는 trim해 alt로 실행한다(화면이 거짓말하는 행). " time_ge"는
    // 인자수 검사가 raw 키 조회라 생략되어 dryRun까지 침묵한다 (리뷰 3).
    row.lonAxis = row.lonAxis.trim();
    row.exitKind = row.exitKind.trim();
    const who = row.name.trim() || `${i + 1}번 행`;
    if (!AXES.has(row.lonAxis)) {
      // off로 두면 표시(select)와 데이터가 일치한다 — 모르는 값을 남기면 select가
      // 첫 항목을 보여 주면서 데이터는 딴 것을 쥔, 화면이 거짓말하는 행이 된다
      issues.push(`${who}: 모르는 종방향 축 ${JSON.stringify(row.lonAxis)} — off로 두었다`);
      row.lonAxis = "";
    }
    if (!Object.hasOwn(COND_KINDS, row.exitKind)) {
      issues.push(`${who}: 모르는 이탈 조건 ${JSON.stringify(row.exitKind)} — always로 두었다`);
      row.exitKind = "always";
      row.exitValue = ""; // always는 인자가 없다 — 남기면 쓰이는 척한다
    }
    return row;
  });

  let wps = Array.isArray(json.wpRows) ? json.wpRows : [];
  if (wps.length > MAX_WPS) {
    issues.push(`웨이포인트가 ${wps.length}개 — 앞 ${MAX_WPS}개만 받았다 (퇴화 응답 방어)`);
    wps = wps.slice(0, MAX_WPS);
  }
  out.wpRows = wps.map((r) => ({
    n: str(r?.n),
    e: str(r?.e),
    // 빈 고도는 키 자체를 생략 — "전부 있거나 전부 없거나" 규칙에 빈 문자열을
    // 섞지 않는다 (views/sim.js wpDraft 소비부와 같은 스프레드 생략)
    ...(str(r?.d).trim() === "" ? {} : { d: str(r.d) }),
  }));

  const rc = json.runConditions;
  if (rc != null && typeof rc === "object" && !Array.isArray(rc)) {
    for (const k of RUN_STR) {
      const v = str(rc[k]).trim();
      if (v !== "") out.runConditions[k] = v; // "" = 폼 유지 → 키를 담지 않는다
    }
    for (const k of RUN_BOOL) {
      if (typeof rc[k] === "boolean") out.runConditions[k] = rc[k];
      else if (rc[k] != null) {
        issues.push(`실행 조건 ${k}: 불리언이 아니다 — 무시했다 (${JSON.stringify(rc[k])})`);
      }
    }
    const known = new Set([...RUN_STR, ...RUN_BOOL]);
    const unknown = Object.keys(rc).filter((k) => !known.has(k));
    if (unknown.length) {
      issues.push(`실행 조건의 모르는 칸 무시: ${unknown.join(", ")}`);
    }
  }
  return out;
}

/** 제출 가능성 사전 판정 — 검증 정본을 그대로 돌려 던진 메시지를 모은다.
 *
 * 더하는 것은 하나뿐이다: "path"를 쓰는 모드(수평이든 세로든)가 있는데
 * 웨이포인트가 없으면 실행 시점에 서버가 422(경로추종기 없음)를 내므로 미리
 * 말한다. 반대 방향(웨이포인트만 있고 path 없음)은 거부가 아니라 기준선 쓰임이
 * 있어(lib/mission.js pathUsage 머리말) 탭의 wpNotice가 맡는다 — 여기서 겹쳐
 * 말하지 않는다.
 */
export function dryRun({ modeRows, wpRows }) {
  const issues = [];
  try {
    buildModes(modeRows);
  } catch (e) {
    issues.push(String(e?.message ?? e));
  }
  try {
    buildWaypoints(wpRows);
  } catch (e) {
    issues.push(String(e?.message ?? e));
  }
  if (modeRows.length && !wpRows.length) {
    const use = pathUsage(modeRows);
    if (use.heading || use.alt) {
      issues.push('"path"를 쓰는 모드가 있는데 웨이포인트가 없다 — 실행 시 서버가 거부한다(경로추종기 없음)');
    }
  }
  return issues;
}
