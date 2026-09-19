/** 비행성 수준(FQ) 표시 계층 — 판정·수치는 서버(엔진 analysis/fq.py) 산출, 여기는 표현 변환만.
 *
 * 수준 키: 1·2·3(판정 수준) · "out"(수준 밖 — level가 null) · "na"(판정 없음 — 모드
 * 분류 불가이거나 판정이 실리기 전의 구버전 결과). "out"과 "na"는 다른 사실이다:
 * 밖은 "쟀는데 최하 수준에도 못 든다", na는 "잰 것이 없다" — 뭉치면 발산 모드가
 * 회색 뒤에 숨는다.
 *
 * 판정선은 화면이 재기술하지 않는다 — 서버가 결과에 동봉한 fq_criteria가 정본이고
 * (marginColor의 FALLBACK_CRITERIA와 같은 원칙, 단 여기는 결과 동봉이라 폴백도
 * 없다), 범례 문장은 그 값으로 만든다.
 */

import { STATUS } from "./plot.js";

// 수준 밖의 보라는 자동 설계 무효 처방(ineffective)과 같은 선택 — 판정 3색과 섞이지
// 않으면서 "나쁜 쪽"임이 드러나는 색 (views/autodesign.js LEDGER_COLOR 선례)
// short는 표 칸용 축약 — 문자열 치환으로 만들지 않는다: "수준 밖"이 "수준 "을 포함해
// replace 순서 하나로 "L밖"이 됐다(리뷰 지적 — 하필 이 기능의 존재 이유인 최악
// 케이스에서만 나는 표시 버그). 명시 맵이 정본이다
export const FQ_BADGE = {
  1: { label: "수준 1", short: "L1", color: STATUS.ok },
  2: { label: "수준 2", short: "L2", color: STATUS.warn },
  3: { label: "수준 3", short: "L3", color: STATUS.bad },
  out: { label: "수준 밖", short: "밖", color: "#af52de" },
  na: { label: "판정 없음", short: "—", color: STATUS.na },
};

// 최악 정렬 순서 — 클수록 나쁘다. na는 순서에 없다(잰 것이 없으므로 최악 후보가 아니다)
const RANK = { 1: 0, 2: 1, 3: 2, out: 3 };

/** 판정 dict(서버 fq 블록의 모드 하나) → FQ_BADGE 키. */
export function fqKey(j) {
  if (!j || j.level === undefined) return "na";
  return j.level == null ? "out" : j.level;
}

/** [모드 키, 표시 이름, 축] — 감쇠비 표의 열 순서와 같다. */
export const FQ_MODES = [
  ["short_period", "단주기", "lon"],
  ["phugoid", "장주기", "lon"],
  ["dutch_roll", "더치롤", "lat"],
  ["roll", "롤", "lat"],
  ["spiral", "나선", "lat"],
];

/** 같은 수준 안에서 "더 나쁜" 쪽 — 클수록 나쁘다. 수준(rank)이 먼저고 이것은 동률
 * 타이브레이크다: 나선·장주기는 발산 T₂ 짧은 쪽(안정이면 ζ 작은 쪽), 롤은 τ 큰 쪽,
 * 더치롤·단주기는 ζ 작은 쪽. 단주기 과감쇠 쪽(ζ 상한 초과) 동률은 이 근사가 못
 * 가른다 — 그 동률은 수준이 이미 갈라 준다(대역 밖은 다음 수준). */
function worseness(mode, j) {
  if (!j) return -Infinity;
  if (mode === "spiral") return j.stable ? -Infinity : 1.0 / j.t2_s;
  if (mode === "phugoid") return j.t2_s != null ? 1.0 / j.t2_s : -j.zeta;
  if (mode === "roll") return j.tau_s == null ? Infinity : j.tau_s;
  return -(j.zeta ?? 0); // short_period · dutch_roll
}

/** 마진 맵 entries → 모드별 최악 수준 [{mode, label, key, j, caseName}].
 *
 * na(판정 없음)는 최악 후보에서 뺀다 — 전 케이스가 na면 key도 "na"다. 같은 수준끼리는
 * worseness가 가른다 — 발산 나선의 "가장 짧은 T₂가 어느 케이스인가"가 이 표의
 * 답이다(v1.10에서 손으로 찾던 것). 수준만 보면 T₂ 19 s와 8.5 s가 둘 다 수준 2일 때
 * 먼저 온 케이스가 대표가 되어 실제 최악이 숨는다(리뷰 지적).
 */
export function fqWorst(entries) {
  return FQ_MODES.map(([mode, label, axis]) => {
    let worst = null;
    for (const e of entries) {
      const j = e[axis]?.fq?.[mode];
      const key = fqKey(j);
      if (key === "na") continue;
      if (!worst || RANK[key] > RANK[worst.key]
        || (RANK[key] === RANK[worst.key] && worseness(mode, j) > worseness(mode, worst.j))) {
        worst = { key, j, caseName: e.trim.case.name };
      }
    }
    return { mode, label, ...(worst ?? { key: "na", j: null, caseName: null }) };
  });
}

const num = (v, d = 2) => (typeof v === "number" && Number.isFinite(v)
  ? String(Math.round(v * 10 ** d) / 10 ** d) : "—");

/** 최악 수준 한 자리의 근거 수치 문장 — 배지 옆 괄호에 들어갈 짧은 글. */
export function fqMeasureText(mode, j) {
  if (!j) return "";
  if (mode === "short_period") return `ζ ${num(j.zeta)}`;
  if (mode === "phugoid") return j.t2_s != null ? `발산 T₂ ${num(j.t2_s, 1)} s` : `ζ ${num(j.zeta, 3)}`;
  if (mode === "dutch_roll") return `ζ ${num(j.zeta)} · ωn ${num(j.wn)} · ζωn ${num(j.zwn)}`;
  if (mode === "roll") return j.tau_s != null ? `τ ${num(j.tau_s)} s` : "발산 실근";
  if (mode === "spiral") return j.stable ? "안정" : `T₂ ${num(j.t2_s, 1)} s`;
  return "";
}

/** 판정선 요약문 — 서버가 동봉한 fq_criteria로 만든다 (재기술 금지).
 *  null(구버전 결과)이면 그 사실을 말한다 — 조용한 생략 금지. */
export function fqLegendText(c) {
  if (!c) {
    return "비행성 수준 판정선 정보가 없습니다 — 판정이 실리기 전의 결과입니다. "
      + "배치를 다시 실행하면 모드마다 수준이 실립니다.";
  }
  return `비행성 수준 판정선(무증강 기체 모드 — MIL-F-8785C 관례, 수준 1/2/3 순, 지문 ${c.fingerprint}): `
    + `단주기 ζ ${c.sp_zeta_l1_lo}–${c.sp_zeta_l1_hi} / ${c.sp_zeta_l2_lo}–${c.sp_zeta_l2_hi} / ≥ ${c.sp_zeta_l3_lo} · `
    + `장주기 ζ ≥ ${c.ph_zeta_l1} / 안정 / 발산 T₂ ≥ ${c.ph_t2_l3} s · `
    + `더치롤 ζ ≥ ${c.dr_zeta_l1}, ζωn ≥ ${c.dr_zwn_l1}, ωn ≥ ${c.dr_wn_l1} / `
    + `ζ ≥ ${c.dr_zeta_l2}, ζωn ≥ ${c.dr_zwn_l2} / ζ ≥ ${c.dr_zeta_l3}, ωn ≥ ${c.dr_wn_l3} · `
    + `롤 τ ≤ ${c.roll_tau_l1} / ${c.roll_tau_l2} / ${c.roll_tau_l3} s · `
    + `나선 T₂ ≥ ${c.spiral_t2_l1} / ${c.spiral_t2_l2} / ${c.spiral_t2_l3} s (안정 나선 = 수준 1). `
    + "무증강 모드의 수준 미달은 결함이 아니라 비행제어가 메꿀 몫이다 — 폐루프 판정은 마진 합격기준이 한다.";
}
