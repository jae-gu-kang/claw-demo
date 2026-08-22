/** 구조도 배선별 신호 표시 — 어떤 배선에 어떤 시계열을 얹고 어떻게 포맷할지.

DOM 무접촉 순수 계층. 캔버스/SVG 주입은 views/replayoverlay.js.

배선 id(w_*)는 views/diagram.js의 `<text class="sigval" data-sig="...">`와 1:1
계약이다 — 한쪽만 바뀌면 값이 조용히 안 뜬다.

**각은 표시 전용으로 deg 변환한다.** 내부 규약은 SI+rad(conventions §3)이고
저장·전송·계산은 전부 rad 그대로다. 사람이 읽는 자리에서만 도로 바꾼다 —
0.7 rad보다 40°가 "뱅크가 얼마나 들어갔나"를 즉시 말해 주기 때문.

**계측 안 된 값은 0이 아니라 —**. 엔진은 프로브가 없는 형상(리미터 미장착 등)을
NaN으로 채우고(sim/simulator.py), 여기서는 그것과 "명령이 실제로 0"을 반드시
구분해 표시한다. 섞이면 그림이 거짓말을 한다.
*/

const DEG = 180 / Math.PI;

/** 블록 id → {items: [{key, label, as, digits}]}. as: rad(→deg 표시)|raw|text.

배선 **사이**가 아니라 블록 **아래**에 붙인다: 주 신호 흐름의 블록 간격이
46~76 px뿐이라 여러 값이 들어가지 않는다. 블록 폭(84~150 px)을 쓰면 축 3개도
들어가고, "이 블록이 지금 무엇을 내보내고 있나"로 읽혀 계기판에 가깝다.
*/
export const WIRE_SIGNALS = {
  // 미션플래너 — 현재 비행 모드 (유일한 문자열 신호)
  w_plan: { items: [{ key: "mode", label: "", as: "text" }] },
  // 유도 → AP 명령
  w_gui: {
    items: [
      { key: "cmd_speed", label: "V*", as: "raw", digits: 0 },
      { key: "cmd_alt", label: "h*", as: "raw", digits: 0 },
      { key: "cmd_heading", label: "ψ*", as: "rad", digits: 0 },
    ],
  },
  // 오토파일럿 → 자세 명령
  w_ap: {
    items: [
      { key: "theta_cmd", label: "θ*", as: "rad", digits: 1 },
      { key: "phi_cmd", label: "φ*", as: "rad", digits: 1 },
    ],
  },
  // α 리미터 — 통과 θ와 남은 여유. 보호가 물리면 θ*와 갈라지는 것이 요점
  w_lim: {
    items: [
      { key: "theta_lim", label: "θ", as: "rad", digits: 1 },
      { key: "alpha_margin", label: "여유", as: "rad", digits: 1 },
    ],
  },
  // SCAS 축별 출력 → 믹서
  w_scas: {
    items: [
      { key: "pitch", label: "", as: "rad", digits: 1 },
      { key: "roll", label: "", as: "rad", digits: 1 },
      { key: "yaw", label: "", as: "rad", digits: 1 },
    ],
  },
  // 작동기 통과 후 타면·추력 (로깅은 작동기 출력 기준)
  w_act: {
    items: [
      { key: "de", label: "δe", as: "rad", digits: 1 },
      { key: "da", label: "δa", as: "rad", digits: 1 },
      { key: "dr", label: "δr", as: "rad", digits: 1 },
    ],
  },
  // 기체 상태
  w_plant: {
    items: [
      { key: "V", label: "V", as: "raw", digits: 0 },
      { key: "h", label: "h", as: "raw", digits: 0 },
      { key: "alpha", label: "α", as: "rad", digits: 1 },
    ],
  },
  // 항법 출력 = 법칙이 실제로 보는 값 (참값 아님 — 03 §4 계약)
  w_nav: {
    items: [
      { key: "theta", label: "θ", as: "rad", digits: 1 },
      { key: "phi", label: "φ", as: "rad", digits: 1 },
      { key: "psi", label: "ψ", as: "rad", digits: 0 },
    ],
  },
};

/** 한 표본 원값 — 배열 없음·인덱스 밖은 null (미계측). 형 검사는 호출측이. */
function rawSampleOf(signals, key, i) {
  const arr = signals?.[key];
  if (!Array.isArray(arr) && !ArrayBuffer.isView(arr)) return null;
  if (i < 0 || i >= arr.length) return null;
  return arr[i];
}

/** 배선 spec + 신호 + 표본 인덱스 → 표시 문자열. 미계측 항목은 "—".

라벨이 빈 항목은 값만 찍는다 (SCAS 축처럼 자리로 뜻이 통하는 경우). */
export function wireText(spec, signals, i) {
  if (!spec) return "";
  return spec.items
    .map((it) => {
      const raw = rawSampleOf(signals, it.key, i);
      const pre = it.label ? `${it.label} ` : "";
      if (it.as === "text") return raw ? String(raw) : "—";
      if (typeof raw !== "number" || !Number.isFinite(raw)) return `${pre}—`;
      const shown = it.as === "rad" ? raw * DEG : raw;
      const unit = it.as === "rad" ? "°" : "";
      return `${pre}${shown.toFixed(it.digits)}${unit}`;
    })
    .join(" · ");
}

/** 표시에 쓰이는 신호 키 전체 — 재생 응답에 빠진 게 있는지 확인하는 용도. */
export function requiredSignals() {
  const out = new Set();
  for (const spec of Object.values(WIRE_SIGNALS)) {
    for (const it of spec.items) out.add(it.key);
  }
  return out;
}
