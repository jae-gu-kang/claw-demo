/** 미션 템플릿 — 기체 문서의 `mission_template`(화면 폼 초기값)을 폼 글로 옮긴다 (02 §5.6 · 06 §8).

미션 템플릿은 계산에 쓰이지 않는 **화면 기본값**이다 — 해석 격자(트림·마진 맵·영향성·게인 카드), 엔벨로프
폼, 시뮬 기본 미션의 속도·상승각·고도·연료, 착륙 미끄럼 거리. 기체 성능에 맞춰 잰 값이라 기체마다 다르다.
그래서 웹의 상수는 **예제 기체의 사본(폴백)**으로만 남고, 고른 기체 문서가 도착하면 **손대지 않은 칸만** 그
기체 값으로 바뀐다. 템플릿이 없는 기체(null)는 폴백을 쓰되 화면이 그렇다고 말한다 — 예제 값을 그 기체
값인 척하지 않는다. 사본과 예제 문서가 어긋나면 missiontemplate.test.js가 빨개진다.

엔벨로프 α 여유와 마진 맵 작동기 칸은 템플릿이 아니라 기체 문서 본문(`law.alpha_margin`·`actuator`)에서
읽는다 — 계산 입력이라 이미 문서에 있다.
*/

export const MISSING_TEMPLATE_HINT = "이 기체 문서에는 미션 템플릿이 없어 예제 기체에 맞춘 값입니다 — "
  + "기체 탭 「미션 템플릿」에서 채웁니다.";

export const DOC_FAILED_HINT = "고른 기체 문서를 받지 못해 예제 기체에 맞춘 값입니다 — 새로고침하거나 기체 탭을 "
  + "확인합니다.";

/** 엔벨로프 폼 폴백 — 예제 기체 사본. margin은 제어법칙의 α 리미터 여유(law.alpha_margin)다. */
export const ENVELOPE_FALLBACK = Object.freeze({
  alt: "1000", fuel: "200", margin: "0.05",
  scanFrom: "0.2", scanTo: "0.7", scanStep: "0.05", scanAlts: "0, 1000, 3000, 5000",
});

/** 마진 맵 작동기 칸 폴백 — 예제 기체 actuator.params 사본. */
export const MARGIN_ACT_FALLBACK = Object.freeze({ wn: "30", zeta: "0.7" });

/** 격자(수치) → 폼 글 — 트림·마진 맵·영향성 격자 칸과 같은 모양. */
export const gridStrings = (grid) => ({
  machFrom: String(grid.machFrom), machTo: String(grid.machTo), machStep: String(grid.machStep),
  alts: grid.alts.join(", "), fuels: grid.fuels.join(", "),
});

/** 기체 적용 문서 → 화면 기본값 묶음.
 *  {hasTemplate, grid(수치)|null, envelope{칸: 글}, margins{wn, zeta}, sim{form, rows}|null, rolloutM|null} */
export function templateDefaults(doc) {
  const tpl = doc?.mission_template ?? null;
  const out = { hasTemplate: tpl != null, grid: null, envelope: {}, margins: {}, sim: null, rolloutM: null };
  if (typeof doc?.law?.alpha_margin === "number") out.envelope.margin = String(doc.law.alpha_margin);
  const act = doc?.actuator;
  if (act?.type === "SecondOrderActuator" && act.params) {
    for (const k of ["wn", "zeta"]) if (typeof act.params[k] === "number") out.margins[k] = String(act.params[k]);
  }
  if (!tpl) return out;
  const g = tpl.trim_grid;
  out.grid = { machFrom: g.mach.from, machTo: g.mach.to, machStep: g.mach.step, alts: [...g.alt], fuels: [...g.fuel] };
  const e = tpl.envelope;
  Object.assign(out.envelope, {
    alt: String(e.alt), fuel: String(e.fuel),
    scanFrom: String(e.scan_mach.from), scanTo: String(e.scan_mach.to), scanStep: String(e.scan_mach.step),
    scanAlts: e.scan_alt.join(", "),
  });
  const s = tpl.sim;
  out.sim = {
    form: { fuel: String(s.fuel), fuelFlow: String(s.fuel_flow), tEnd: String(s.t_end), accept: String(s.accept_radius) },
    rows: {
      climbSpeed: String(s.climb.speed), climbPitch: String(s.climb.pitch), climbExitAlt: String(s.climb.exit_alt),
      cruiseSpeed: String(s.cruise.speed), cruiseAlt: String(s.cruise.alt),
      approachSpeed: String(s.approach.speed), approachHdot: String(s.approach.hdot),
      approachExitAlt: String(s.approach.exit_alt),
      flareSpeed: String(s.flare.speed), flareHdot: String(s.flare.hdot),
    },
  };
  out.rolloutM = s.rollout_m;
  return out;
}

/** 손대지 않은 칸만 바꿀 값 — 칸이 폴백 그대로이고 새 값이 다를 때만. 돌려주는 것: {칸: 새 글} */
export function untouchedUpdates(current, fallback, next) {
  const out = {};
  for (const [k, v] of Object.entries(next ?? {})) {
    // 폴백이 없는 칸은 「손대지 않았다」를 판정할 수 없다 — 건드리지 않는다
    if (v !== undefined && Object.hasOwn(fallback ?? {}, k) && current?.[k] === fallback[k] && current[k] !== v) out[k] = v;
  }
  return out;
}
