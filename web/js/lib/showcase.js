/** 쇼케이스 진행기 판단 — 단계 표·LLM 게이트·진행 규칙·기록·보관 형식 (순수 로직).

조립·순서 제어는 views/showcase.js. 여기 있는 것은 **DOM 없이 답이 정해지는 질문**들이다
(lib/tour.js와 같은 자리). 진행기는 탭의 요청 조립·실행을 대신하지 않는다 — 탭에 신호를
걸고(lib/showcasecue.js) 그 탭이 자기 [실행]과 같은 길로 한 일을 보고받는다. 그래서 이 표에는
요청 본문이 없고 **동작 이름과 인자**만 있다(06 §9.3 계약).

줄(line)은 **탭이 보고한 summary 그대로**다 — 진행기가 새 해설을 쓰지 않는다(tour.js 캡션
규약). 진행기 자신의 문장은 건너뜀·실패·중단 사유와 선행 조건 안내뿐이다.

보관: 기체 선택 전환(준비 단계)과 자동 설계 반영 뒤의 새 리비전 다시 읽기는 페이지를 다시 읽는다 —
커서·단계 상태·이어 달리기 흔적(모드·기대 기체)을 sessionStorage에 판(v) 번호를 달아 두고, 읽을 때는
무엇이 와도 죽지 않는다(깨진 칸은 버리고 기본값).
*/

import { withoutCriteria } from "./autodesign.js";
import { workingCopyLine } from "./gainsync.js";
import { EXAMPLE_ID } from "./profile.js";
import { SPEECH_GATE, TOUR_SPEED, endTimeFor } from "./tour.js";

/** 쇼케이스 기체 문서 id — 서버 `/profiles/_showcase/install`이 설치하는 저장 기체(엔진 패키지 데이터).
 *  기체 값이 아니라 **문서 이름**이다(기체 데이터는 전부 그 문서에서 온다). */
export const SHOWCASE_ID = "showcase-delta";
export const STORAGE_KEY = "claw.showcase";
export const STATE_VERSION = 1;
/** 다시 읽기 뒤 이어 달리기를 믿는 창 — 이보다 오래된 흔적(탭을 닫았다 연 경우 등)으로 되살아나지 않는다. */
export const RESUME_WINDOW_MS = 120_000;

/** 공학 수정 — EO/IR 볼 항력 ΔCD0 (06 §9.4 단계 7). */
export const SHOWCASE_CD0_DELTA = 0.007;
/** 자동 설계 예산 — **템플릿 폴백 규칙의** 예산 몫이다(마하 격자 점 수·검증점 예산·이터 상한 — 기체 값이
 *  아니다). 문서가 제 확정 게인 표를 만든 설정을 적어 두었으면 그 기록이 먼저다(autodesignConfigFor — S1은
 *  생성기가 적는다). 고도·연료 축은 선택 기체 문서의 미션 템플릿에서 온다(기체 고정 금지).
 *  실측(S1 재생성본 — F6-regen·G4-s1·Y2-s1, 로컬 서버 TestClient 단독 — 엔진 기본 표현 「표」): 이 예산 + 템플릿
 *  2고도(0·3000 m) × 2연료(10·50 kg)에서 1차 3.0~3.5 s에 수렴(점 90 · 판정 425 · 실패 0 · 재개 없음) → 반영 200. 롤 속도
 *  루프 마진 가드(Q1-gate — AS94900 끊는 자리 GM 8 dB·PM 50°) 뒤에는(Q3-s1, 엔진 직접) 1차가 승인 대기로 선다(판정 425 ·
 *  실패 7 — 전부 roll_rate, 해면 10 kg: 마하 1축 표 하나가 한 마하에서 해면과 3000 m를 함께 못 맞춘다) → 제안 7건(promote)
 *  승인 재개 한 번에 수렴(점 91 · 판정 430 · 실패 0 · 약 25 s). 같은 자리의 문서 기록 설정
 *  (해면 한 줄 · 마하 7 · 연료 25 · ζsp 0.9 · 점 예산 90 — P5-s1: 마하 1축 표라 두 설계 고도의 점이 번갈아 놓이던 톱니를
 *  없앴다)은 재개 없이 수렴한다(점 81 · 판정 395 · 실패 0 — 세분화가 허용치까지 끝나고 보간 구간마다 검증점이 선다.
 *  마진 가드 뒤 서버 약 7 s · 가드 전 약 2.6 s).
 *  (위 실측은 요구영역 이관 전 — v1.66 재생성본의 기록 설정은 n_mach 없이 설계 줄 200 m / 25 kg이다.)
 *  이 폴백 규칙은 기체 문서에 설정 기록이 없을 때만 쓴다 — 템플릿 두 고도를 그대로 주므로 1축 표에 톱니가 생길 수 있다.
 *  n_mach는 요구영역(operating_region)이 없는 문서에만 싣는다 — 있으면 마하 격자의 원천은 그 기본 격자 명세(base_grid)이고
 *  (엔진 AutoDesignConfig.n_mach None = 영역 명세), 실으면 명세를 덮는다. alts·fuels는 어느 쪽이든 템플릿 축을 싣는다.
 *  budget_iters 2라 재개는 많아야 한 번이다(끝이 보장된다). */
export const AUTODESIGN_BUDGET = Object.freeze({ n_mach: 5, budget_points: 90, budget_iters: 2 });
/** 공학 결함 — 고도 루프 ḣ 되먹임(자동조종 k_hdot — 절.축.칸 "autopilot.alt.k_rate") 과대. 확정 게인 표는 SCAS
 *  7자리뿐이라 이 자리는 설계점 상수 하나이고, 게인 탭은 끈 자리 상수 경로로 싣는다(lib/gainsync faultSlot).
 *  실측 방법(IB5-fault·T3-fault부터 같다): 게인 탭 fault 경로가 store에 싣는 작업 사본을 웹 lib로 그대로 지어 서버
 *  TestClient에서, 대표 4케이스 full → 첫 하드 규칙 카드 [얼마나 →] → 스윕 → 처방(확인 full) → 적용 → 재평가.
 *  - v1.70 — 설계점·절점 분리 재생성본(이관 3단계: 확정 표 7자리 × 7점 — 요구영역 공통 마하 절점 M0.10~0.22 위 최소제곱,
 *    기준 지문 9059… 그대로, 표 요약 ffef… → 66c0…. k_hdot·자동조종 상자·대표 4케이스 그대로) — Q가 같은 방법으로 다시 쟀다:
 *    창 ×5.25~6.0(잰 점 5.25·5.3·5.4·5.5·5.6·5.65·5.7·5.8·5.9·6.0 REPAIRED). ×4.9~5.2는 FAIL(M0.18_h3000_f10 동적 여유 하나 —
 *    ×5.2 0.000)인데 첫 카드가 고도 PI라 확인 런이 없고, ×4.8은 FAIL이 없고, ×6.05는 확인 런 FAIL(M0.18_h3000_f10 0.0367).
 *    아래 끝이 0.05 내려왔을 뿐 모양은 v1.66과 같아 ×5.65를 그대로 둔다(아래 0.4 · 위 0.35). ×5.65: FAIL M0.18_h200_f10
 *    0.0081 · M0.18_h3000_f10 0.000 → k_hdot +20 %(−0.1694 → −0.1355) → 재평가 PASS(J 5.57 @ M0.12_h3000_f10), 결함 전 기준
 *    PASS(J 3.34). 사슬 약 200 s(6개 동시).
 *  - v1.66 — 요구영역 격자 재생성본(이관 2·9·10단계: 설계 줄 200 m / 25 kg — 기록 설정에서 n_mach가 빠지고 마하 격자는
 *    요구영역 기본 격자 명세, 확정 표 7자리 × 36점, 기준 지문 e027… → 0035…. k_hdot·자동조종 상자·템플릿 대표 4케이스
 *    그대로) — 설치 직후 문서에서 G-s1이 다시 쟀다: 창 ×5.3~6.0(잰 점 5.3·5.4·5.5·5.6·5.65·5.7·5.8·5.85·5.9·6.0 전부
 *    REPAIRED). ×5.1·5.2·5.25는 FAIL이지만 첫 카드가 고도 PI(kp_alt·ki_alt)를 가리키고 제안 변화가 0이라 확인 런이
 *    없다(M0.18_h3000_f10 동적 여유 하나만 미달 — ×5.1 0.0004), ×6.05·6.1·6.15·6.2·6.4·6.6은 확인 런 FAIL(×6.05
 *    M0.18_h3000_f10 0.042). 해면 한 줄 표에서 가운데였던 ×5.5는 아래 끝에서 0.2라 창 가운데 ×5.65로 옮겼다(양끝 0.35).
 *    단계 7·8 뒤 문서는 다시 재지 않았다.
 *  - ×5.65: 설계점 상수 −0.0300 → −0.169. FAIL = authority.dynamic_reserve M0.18_h200_f10 0.000 · M0.18_h3000_f10
 *    0.000(한계 0.05). 지렛대 fcl/Autopilot.k_hdot +20 %(−0.169 → −0.136 — 탐색 한계에 붙은 해라 조합 해는
 *    solvable=false지만 확인 런 PASS) → 재평가 PASS(J 최악 5.57 @ M0.12_h3000_f10). 결함 전 기준 PASS(J 3.34 @
 *    M0.12_h3000_f10). 옛 가운데 ×5.5는 이 문서에서도 REPAIRED(FAIL 0.0165·0.000 → 재평가 J 5.52).
 *  - 시간(로컬, ×5.65 단독): 평가 21 s · 스윕 72 s(설계변수 1 × 스팬 4 × 4케이스 + 기준) · 처방 21 s · 재평가 21 s —
 *    사슬 135 s. 6개 사슬 동시에는 평가 34 s · 스윕 120 s · 처방 35 s · 재평가 30 s(사슬 약 225 s).
 *  이력(창 가운데를 고른 옛 측정 — 짧게):
 *  - 해면 한 줄 표(P5-s1 — 자동조종 문서 칸 전부 레지스트리 기본값: 피치 명령 상한 0.3 rad·속도 명령필터 2 s, 확정 표
 *    7자리 × 40점, 요 설계 목표 ζ_dr 0.6): 창 ×5.2~5.85 → 가운데 ×5.5(아래 0.3 · 위 0.35). ×4.8~5.1 확인 런 없음(고도 PI
 *    카드 · 제안 변화 0), ×5.9~6.8 확인 런 FAIL, ×7.0 확인 런 없음. ×5.5 FAIL M0.18_h200_f10 0.015 · M0.18_h3000_f10 0.000
 *    → k_hdot +20 % → 재평가 J 5.52 · 기준 J 3.34. 단계 7·8 뒤 문서도 같은 수(재설계 표가 출하 표와 비트 단위로 같았다).
 *    롤 속도 루프 마진 가드 뒤 재생성(Q3-s1 — 롤 댐퍼 캡, 피치 3자리 그대로)에서도 창 그대로. 사슬 단독 129~130 s ·
 *    5개 동시 약 191 s.
 *  - 창이 옮는 까닭은 확정 표다: 설계 고도 0·3000 m 두 줄의 톱니 표(66점)에서는 ×5.4~6.6이었다(해면 한 줄 표는 3000 m
 *    게인이 해면 값이라 M0.18_h3000_f10의 동적 여유가 먼저 닳았다). 아래 끝은 그 모서리 하나만 걸려 처방 카드가 고도
 *    PI로 바뀌는 자리, 위 끝은 처방 뒤에도 그 모서리가 남는 자리다(v1.66 재측정에서도 두 끝의 모양이 같다).
 *  - 톱니 표 이전: 피치 명령 상한 0.35 rad·속도 명령필터 0.5 s 출하본 ×4.8~5.8, 상한 0.3 뒤 ×5.4~6.6(×6.0 재평가 J
 *    5.64). 요 댐퍼 표 수리·발진 웜스타트·ζ_dr 0.6은 창을 옮기지 않았다(영향성 평가는 공중 트림점에서 출발한다).
 *  처방 폭은 탐색 한계(크기 ×0.8)라 처방 뒤 값은 ×(0.8·배율)이다 — ×5.65는 ×4.52로 든다.
 *  - 버린 후보(IB5-fault, 다항 표현 표에서 — 표 표현 재생성 뒤 다시 훑지 않았다): 예제에서 쓰던 scas.pitch.k_rate는
 *    ×3.0~7.0(0.1 간격) 전부 PASS — 리밋 사이클이 안 난다. ×20에서야 margins.pm FAIL(선형 지표 — 처방이 풀지 않는다).
 *    scas.yaw.k_rate ×7~10은 coupling.sat_frac FAIL이지만 소견 카드가 헤딩 루프를 가리켜 확인 런 FAIL. pitch·roll kp,
 *    pitch ki 과대는 margins FAIL(선형). roll.k_rate ≤×8 · heading.kp ≤×8 · speed.kp ≤×10은 FAIL 없음. 요 댐퍼
 *    약화(ζ_dr FAIL — 선형)는 예제에서 이미 같은 이유로 뺐다(W4b).
 *  S1 문서(자동조종 설계값·상자·확정 표 값·템플릿 격자)가 바뀌면 창을 다시 잰다 — 잰 기준을 테스트가 붙잡는다. */
export const SHOWCASE_FAULT = Object.freeze({ path: "autopilot.alt.k_rate", factor: 5.65 });
/** 영향성 2단 평가 점 — 요구영역 기본 격자에서 **이름으로** 고른다(05 §11.13 5단계: 영향성 탭은 조건 구간을 따로 두지
 *  않는다). 위 결함 창(×5.25~6.0 — v1.70)은 정확히 이 네 점에서 쟀다 — 종전 템플릿 격자의 대표 부분 격자(마하 양끝 × 고도 양끝 ×
 *  연료 가운데 = M0.12·0.18 × 200·3000 m × 10 kg)다. 기본 격자의 일반 대표점 규칙(lib/opspace.js representativePoints —
 *  행 끝점)으로는 M0.10·0.24·0.11이 골라져 **다른 점**이 되므로 규칙으로 파생하지 않고 적어 둔다. 네 점은 S1 기본 격자
 *  (M0.10~0.24, n_mach 8 → 0.02 간격)에 그대로 있다(showcase.test.js가 좌표 규칙까지 대조). 순서는 기본 격자 서펜타인
 *  순서이고 종전 부분 격자의 실행 순서와 같다. FAIL은 이 안의 고마하 두 모서리(M0.18)에서 난다(실측 — 4건 평가 약 20 s).
 *  이 목록을 바꾸면 결함 창을 다시 잰다. */
export const SHOWCASE_EVAL_POINTS = Object.freeze(["M0.12_h200_f10", "M0.18_h200_f10", "M0.18_h3000_f10", "M0.12_h3000_f10"]);
/** 미션 초안 의도 문장(LLM) — 투어 입력 칸 예시와 같은 꼴. TODO(통합): S1 미션(착륙 방식)에 맞춰 확정. */
export const SHOWCASE_INTENT = "발사해서 북쪽 4 km를 돌고 활주로에 착륙";
/** 질문 위젯에 던질 질문(LLM). TODO(통합): 답이 화면을 옮기는 것이 잘 보이는 문장으로 확정. */
export const SHOWCASE_QUESTION = "실속 마진은 어디서 봐?";

const numList = (v) => {
  const xs = Array.isArray(v) ? v : [v];
  return xs.length > 0 && xs.every((x) => typeof x === "number" && Number.isFinite(x)) ? [...xs] : null;
};

/** 문서가 적어 둔 자동 설계 설정 — 확정 게인 표를 만든 설계의 config 덧씀(`law.gain_tables.provenance.
 *  design.config` — S1 생성기가 목표 ζsp·게인 표현(fit_mode "table")까지 적는다). 기록이 없거나 빈 객체면 null.
 *  서버 apply-gains가 새로 쓴 표에는 이 기록이 없다 — 그때 부르는 쪽이 패키지 문서의 기록을 넘길 수 있다. */
export function designConfigRecord(doc) {
  const c = doc?.law?.gain_tables?.provenance?.design?.config;
  return isObj(c) && Object.keys(c).length ? c : null;
}

/** 기록에서 뗀 판정선·목표가 선택 문서에 **같은 값으로** 있는가 — 없으면 그렇다고 말하는 꼬리 글(있으면 빈 글).
 *  기록을 떼면 서버는 문서의 /criteria·/tuning(없으면 도구 기본값)으로 설계한다. v1.51 전에 저장한 쇼케이스 사본은
 *  기록(ζsp 0.9)만 있고 /tuning이 없다 — 그대로 재생하면 ζsp 0.7로 조용히 설계돼 S1 표 검사를 넘는 약한 피치 게인이
 *  난다. 요청에 다시 싣는 길은 닫혔다(서버가 요청 기준을 거절한다) — 사본을 다시 설치하라고 말한다. */
export function recordedCriteriaGap(record, doc) {
  const gaps = [];
  for (const [sec, grp, rec] of [["criteria", "margin", record?.criteria], ["tuning", "targets", record?.targets]]) {
    if (!isObj(rec)) continue;
    const have = doc?.[sec]?.[grp] ?? {};
    for (const [k, v] of Object.entries(rec)) {
      if (have[k] !== v) gaps.push(`${k} 기록 ${v} · 문서 ${have[k] ?? "없음(도구 기본값)"}`);
    }
  }
  return gaps.length
    ? ` — 주의: 기록의 판정선·목표가 문서 /${"criteria·/tuning"}와 다르다(${gaps.join(", ")}). 서버는 문서 값으로 `
      + "설계하므로 기록한 표와 다른 게인이 날 수 있다 — 쇼케이스 기체를 다시 설치하면 맞춰진다"
    : "";
}

/** 자동 설계 config — 출처 순서:
 *  ① 선택 기체 문서의 기록(designConfigRecord) — 출하 표와 같은 설정이라 다시 설계해도 같은 표가 난다(단계 7 뒤
 *     재설계도 출하 표와 비트 단위로 같았다 — 수렴 · 점 81 · 판정 395 · 실패 0). S1은 기본 목표 ζsp 0.7이면 피치 게인이
 *     약하게 잡혀 기록이 정본이다 — 표 표현 실측: pitch.kp −0.30…−0.79(기록 설정 −1.18…−1.25), pitch.ki가 −0.003까지
 *     떨어져 마하 0.01 띠 안 변화 ×19.7(S1 표 검사 상한 2.5). 기본형 착륙은 됐다. 다항 표현(차수 4·구간 4) 때는
 *     발진·플레어에서 추락했다(S1-integrate).
 *  ② 같은 기체(id가 같다)의 패키지 문서 기록(`packaged` — 부르는 쪽이 /profiles/_showcase에서 받아 넘긴다).
 *     단계 8이 한 번 반영한 뒤의 문서는 ①이 비었다(서버 apply-gains는 설계 요약 — 판정 수·표현·적합에서 뺀 표본 수 —
 *     만 적고 설정은 적지 않는다).
 *  ③ 예산(AUTODESIGN_BUDGET) + 선택 기체 문서의 미션 템플릿 축(고도 envelope.alt · 연료 trim_grid.fuel,
 *     스칼라는 한 점 목록으로). 요구영역이 있는 문서면 예산에서 n_mach를 뺀다(마하 격자는 영역 기본 격자 명세).
 *  ④ 템플릿에 그 칸이 없거나 문서를 못 받았으면 빈 덧씀(서버 기본 설정) — 예제 값을 조용히 물려주지 않는다.
 *  ①② 기록에서 판정선·목표(criteria·targets)는 뗀다 — 기준 통합 ①: 목표는 이제 기체 문서의 /tuning이 정본이고
 *  서버가 선택 기체의 그 값으로 설계한다(쇼케이스 문서는 기록과 같은 ζsp 0.9를 /tuning에 적었다). 요청에 실으면
 *  서버가 곧 거절한다.
 *  어느 출처를 썼는지는 행에 남긴다(note — 늘 한 줄). 돌려주는 것: {config, source, note},
 *  source ∈ "document" | "package" | "template" | "server". config는 문서와 떨어진 사본이다. */
export function autodesignConfigFor(doc, { packaged = null } = {}) {
  if (!doc || typeof doc !== "object") {
    return { config: {}, source: "server", note: "설정 출처: 서버 기본 설정 — 선택 기체 문서 없음" };
  }
  const own = designConfigRecord(doc);
  if (own) {
    return { config: withoutCriteria(structuredClone(own)), source: "document",
      note: "설정 출처: 문서 확정 게인 표를 만든 설정(law.gain_tables.provenance.design.config)"
        + recordedCriteriaGap(own, doc) };
  }
  const pkg = packaged?.id != null && packaged.id === doc.id ? designConfigRecord(packaged) : null;
  if (pkg) {
    return { config: withoutCriteria(structuredClone(pkg)), source: "package",
      note: `설정 출처: ${doc.id} 패키지 문서의 확정 표 설정 — 지금 문서에는 설계 설정 기록이 없다`
        + recordedCriteriaGap(pkg, doc) };
  }
  const mt = doc.mission_template;
  const alts = numList(mt?.envelope?.alt);
  const fuels = numList(mt?.trim_grid?.fuel);
  const missing = [alts ? null : "envelope.alt", fuels ? null : "trim_grid.fuel"].filter(Boolean);
  if (missing.length) {
    return { config: {}, source: "server",
      note: `설정 출처: 서버 기본 설정 — 설계 설정 기록도 미션 템플릿 칸(${missing.join(" · ")})도 없다` };
  }
  // 요구영역이 있으면 마하 격자는 그 기본 격자 명세가 정한다 — 예산의 n_mach를 실으면 명세를 덮는다(AUTODESIGN_BUDGET 주석)
  const region = isObj(doc.operating_region);
  const { n_mach: _nMach, ...regionBudget } = AUTODESIGN_BUDGET;
  return { config: { ...(region ? regionBudget : AUTODESIGN_BUDGET), alts, fuels }, source: "template",
    note: "설정 출처: 미션 템플릿 축(envelope.alt · trim_grid.fuel) + 진행기 예산"
      + (region ? " · 마하 격자는 요구영역 기본 격자 명세" : "") + " — 문서에 설계 설정 기록이 없다" };
}

/** 자동 설계 인자를 지으려면 패키지 문서(/profiles/_showcase)가 필요한가 — 쇼케이스 기체인데 문서에 설계 설정
 *  기록이 없을 때만(단계 8이 한 번 반영한 뒤). 다른 기체는 패키지와 무관하다(남의 설정을 물려주지 않는다). */
export const needsPackagedDoc = (doc) => doc?.id === SHOWCASE_ID && !designConfigRecord(doc);

/** 블록도 페이지에 머무는 시간 — 신호가 없는 이동 전용 단계. */
export const NAV_DWELL_MS = 3500;
/** 동작이 끝난 뒤 그 화면에 머무는 시간 — 청중이 결과를 볼 틈. 종전에는 머묾이 이동 동작에만 있어 기체 탭의
 *  네 패널이 0.6 s에, V-n이 0.3 s에 지나갔다(e2e D1). 결과 패널을 펴는 것은 탭이 제 보고 직전에 한다. */
export const DWELL_MS = 3000;
/** 그림이 주인공인 동작(공력 곡선·안정성 띠·V-n·스캔·히트맵+Bode·결과 보고서 등)의 머묾. */
export const FIGURE_DWELL_MS = 5000;
/** 동작별 머묾 [ms] — 없으면 DWELL_MS. 0 = 장부 동작(보여 줄 화면이 없거나, 다음 동작이 같은 화면을 다시 연다). */
const DWELLS = {
  "aircraft.aero": FIGURE_DWELL_MS,
  "aircraft.stability": FIGURE_DWELL_MS,
  "envelope.vn": FIGURE_DWELL_MS,
  "envelope.scan": FIGURE_DWELL_MS,
  "trim.run": FIGURE_DWELL_MS,
  "gains.overview": FIGURE_DWELL_MS,
  "margins.run": FIGURE_DWELL_MS,
  // 반영 직후 다시 읽기가 화면을 지운다 — 보고서는 다시 연 뒤(autodesign.open)에 머문다
  "autodesign.design-and-apply": 0,
  "autodesign.open": FIGURE_DWELL_MS,
  "sim.run": FIGURE_DWELL_MS,
  "gains.restore": 0,
  "autocode.overview": FIGURE_DWELL_MS,
  "verify.run": FIGURE_DWELL_MS,
  "results.open": FIGURE_DWELL_MS,
  "results.opinion": FIGURE_DWELL_MS,
  install: 0,
  reload: 0,
  nav: 0,   // 이동 동작은 제 안에서 머문다(NAV_DWELL_MS)
  world: 0, // 재생 자체가 보여 줌이고, 끝은 정지 + 여유(lib/tour TAIL_S)에서 이미 멈춰 선다
};
/** 이 동작 뒤에 머물 시간 — 끝낸(done) 동작만. 건너뜀·실패는 보여 줄 결과가 없다. 머묾은 다음 동작이 이어질
 *  때만 부른다(멈출 자리면 화면이 그대로 남는다 — views/showcase.js). */
export function dwellFor(a, outcome) {
  if (outcome?.status !== "done") return 0;
  return DWELLS[refKey(a)] ?? DWELL_MS;
}
/** 가상환경 탭 배속 고르개의 칸(web/world/src/ui/WorldTab.tsx `[1, 2, 5, 10, 20].map`) — 번들 경계를 넘는 짝이라
 *  테스트가 원문으로 붙잡는다. 칸 밖의 값을 걸면 고르개는 첫 칸(1×)을 보인 채 다른 배속으로 돈다. */
export const WORLD_SPEEDS = Object.freeze([1, 2, 5, 10, 20]);
/** 3D 재생 벽시계 목표 [s] — 쇼케이스 한 판(로컬 목표 3~5분)에서 한 단계가 1분을 넘지 않게. 투어 배속(2×)은
 *  475 s 런을 3.8 min 재생해 한 판을 9.1 min으로 늘렸다(e2e D19). 기체 값이 아니라 발표 시간 몫이다. */
export const WORLD_REPLAY_TARGET_S = 60;

/** 재생 길이 [s] — 끝 시각(정지 + 여유, 투어와 같은 lib/tour endTimeFor), 없으면(착륙 안 함) 본문의 마지막 시각. */
export function replayDurationS(body) {
  const end = endTimeFor(body);
  if (end != null) return end;
  const t = body?.t;
  const last = Array.isArray(t) && t.length ? t[t.length - 1] : null;
  return typeof last === "number" && Number.isFinite(last) && last > 0 ? last : null;
}

/** 3D 재생 배속 — 고르개 칸 중 재생을 목표(WORLD_REPLAY_TARGET_S) 안에 넣는 가장 느린 칸, 없으면 허용 칸 중
 *  가장 빠른 칸. 교신이 있으면 음성 게이트(SPEECH_GATE) 이하만 — 넘으면 가상환경이 자막만 흘린다. 교신이 없으면
 *  게이트 위도 쓴다(말할 것이 없다). 투어 배속(TOUR_SPEED)보다 느리게는 돌지 않는다. 길이를 모르면 게이트 값. */
export function worldSpeedFor({ comms = false, durationS = null } = {}) {
  const allowed = WORLD_SPEEDS.filter((v) => v >= TOUR_SPEED && (!comms || v <= SPEECH_GATE));
  const top = allowed[allowed.length - 1];
  if (!(typeof durationS === "number" && Number.isFinite(durationS) && durationS > 0)) {
    return Math.min(SPEECH_GATE, top);
  }
  return allowed.find((v) => durationS / v <= WORLD_REPLAY_TARGET_S) ?? top;
}
/** 신호를 걸고 이 시간 안에 탭이 읽지(takeCue) 않으면 — 탭이 신호를 모르거나 렌더가 막혔다. */
export const UNREAD_CUE_MS = 15_000;
/** 가상환경이 재생을 시작했다고 말하지 않으면 멈추는 상한(views/tour.js WATCHDOG_MS와 같은 값). */
export const WORLD_WATCHDOG_MS = 90_000;
/** 재생 전체 상한 — 끝 시각이 없는 런(착륙 안 함)이 영영 붙잡지 않게. */
export const WORLD_CAP_MS = 20 * 60_000;
/** 줄 한 개의 길이 상한 — 카드는 캡션이지 보고서가 아니다(전량은 각 탭에, 잘린 줄은 툴팁에). */
export const LINE_MAX = 160;
/** 잘린 줄의 전량(툴팁) 상한 — 보관(sessionStorage)이 사유 전문(추적 등)으로 부풀지 않게. */
export const LINE_FULL_MAX = 2000;

export const STATE_LABEL = Object.freeze({
  pending: "대기", running: "진행", done: "완료", failed: "실패", skipped: "건너뜀",
});
const STATES = Object.keys(STATE_LABEL);
// warn — 부가 단계(LLM)의 실패: 줄은 실패를 말하되 단계를 실패로 몰지 않는다
const TONES = ["ok", "skip", "fail", "note", "warn"];

const cue = (tab, action, label, extra = {}) => ({ kind: "cue", tab, action, label, args: {}, ...extra });
/** LLM 동작 — 부가 기능이다(06 §0.4: 키가 없어도, 호출이 실패해도 나머지는 끝까지 돈다). 불가면 건너뜀(게이트),
 *  걸었는데 실패하면(키 만료·429·백엔드 다운 — /llm/status는 설정만 본다) soft: 실패 줄을 남기고 단계는 잇는다. */
const llmCue = (tab, action, label, extra = {}) => cue(tab, action, label, { llm: true, soft: true, ...extra });
/** 자동 설계 신호의 문서 인자 — {args, notes}(notes는 안내 줄 — 설정 출처 한 줄). ctx.packaged: 패키지 문서
 *  (문서에 설계 설정 기록이 없을 때만 부르는 쪽이 받아 온다 — needsPackagedDoc). */
const autodesignArgs = (doc, ctx = {}) => {
  const { config, note } = autodesignConfigFor(doc, ctx);
  return { args: { config }, notes: [note] };
};
const nav = (hash, label) => ({ kind: "nav", hash, label, dwellMs: NAV_DWELL_MS });
// 동작 이름에 label을 싣지 않는다 — 탭 summary가 label로 시작한다(「기준 — PASS …」)
const evalCase = (label, expect) => cue("influence", "evaluate", "2단 평가",
  { args: { points: [...SHOWCASE_EVAL_POINTS], label }, ...(expect ? { expect } : {}) });

/** 단계 표 — 순서 = 탭 순서 + 설계 사슬(06 §9.4). `needs`는 **데이터가 실제로 이어지는** 앞 단계만
 *  (행을 따로 누를 때 안내용 — 막지는 않는다. 없으면 탭이 사유와 함께 실패한다). */
export const STEPS = Object.freeze([
  { key: "prepare", label: "준비", needs: [], actions: [{ kind: "install", label: "쇼케이스 기체 설치·선택" }] },
  { key: "aircraft", label: "기체", needs: [], actions: [
    cue("aircraft", "overview", "기체 개요"),
    cue("aircraft", "aero", "공력 곡선"),
    cue("aircraft", "stability", "정적 안정성"),
    cue("aircraft", "seed-basis", "초기 게인 근거"),
  ] },
  { key: "blocks", label: "블록도", needs: [], actions: [
    nav("#blocks", "블록도"),
    nav("#blocks/scas/yaw", "SCAS 요 축"),
    nav("#blocks/plant/prop", "추진"),
  ] },
  { key: "envelope", label: "엔벨로프", needs: [], actions: [
    cue("envelope", "vn", "V-n · M-h"),
    cue("envelope", "scan", "설계 엔벨로프 스캔"),
  ] },
  { key: "trim", label: "트림", needs: [], actions: [cue("trim", "run", "일괄 트림")] },
  { key: "gains", label: "게인", needs: [], actions: [
    cue("gains", "overview", "스케줄 곡선"),
    cue("gains", "evaluate", "튜닝 지표"),
  ] },
  { key: "margins", label: "마진 맵", needs: [], actions: [cue("margins", "run", "마진 맵")] },
  { key: "edit", label: "공학 수정", needs: [], actions: [
    cue("aircraft", "edit-eoir-drag", "EO/IR 볼 항력", { args: { cd0_delta: SHOWCASE_CD0_DELTA } }),
    cue("aircraft", "derive-de-trim", "δe_trim 재도출"),
  ] },
  { key: "autodesign", label: "자동 설계", needs: ["edit"], actions: [
    // config는 신호를 걸 때 선택 기체 문서에서 짓는다(docArgs — 진행기가 문서를 받아 부른다)
    cue("autodesign", "design-and-apply", "자동 설계 → 문서 반영", { docArgs: autodesignArgs }),
    // 7·8단계가 문서에 새 리비전을 썼다(CD0·δe_trim·게인 표) — 탭들이 옛 리비전에서 만든 캐시(선택 문서·
    // 게인 카탈로그·블록도 값)를 버리게 같은 선택으로 다시 읽는다. 이 뒤 단계는 문서를 쓰지 않는다
    // (결함·처방은 작업 사본뿐)라 여기 한 번이면 된다. 다시 읽기가 지운 결과 화면은 다음 동작이 다시 연다
    { kind: "reload", label: "새 리비전 다시 읽기" },
    cue("autodesign", "open", "결과 다시 열기",
      { args: { resultId: { $ref: "autodesign.design-and-apply" } } }),
  ] },
  { key: "flow", label: "설계 흐름", needs: [], actions: [cue("flow", "overview", "설계 흐름 레일")] },
  { key: "sim", label: "시뮬레이션", needs: [], actions: [
    llmCue("sim", "draft", "미션 초안", { args: { intent: SHOWCASE_INTENT } }),
    cue("sim", "run", "미션 실행", { args: { useDraft: { $ok: "sim.draft" } } }),
    cue("sim", "duty", "타면 사용"),
  ] },
  { key: "world", label: "가상환경", needs: ["sim"], actions: [{ kind: "world", label: "3D 재생" }] },
  { key: "influence", label: "영향성", needs: ["sim"], actions: [
    cue("influence", "diagnose", "수동 진단"),
    cue("influence", "screen", "1단 선별"),
    evalCase("기준"),
    // dirties — 작업 사본을 더럽힌다. 여기 닿은 뒤의 [■ 중단]·멈춤은 아래 복원을 진행기가 대신한다(cancelCleanup ·
    // stopStep). 걸기 직전에 진행기가 작업 사본을 비운다 — 결함은 언제나 문서 게인 위에(앞선 멈춤이 남긴 결함 사본에
    // 또 곱해 ×6·×6이 되지 않게, views/showcase.js)
    cue("gains", "fault", "결함 주입", { args: SHOWCASE_FAULT, dirties: true }),
    evalCase("결함", "FAIL"),
    cue("influence", "prescribe", "처방 적용"),
    evalCase("처방 후", "PASS"),
    // 결함 시연이 중간에 실패해도 작업 사본을 문서 게인으로 되돌린다 — 뒤 단계(Autocode·검증)가
    // 결함 게인으로 돌지 않게. 결함 주입(dirties)에 닿기 전의 실패면 돌지 않는다(nextInStep — 사람의 작업 사본을
    // 진행기가 지우지 않는다, cancelCleanup과 같은 규칙)
    cue("gains", "restore", "문서 게인 복원", { always: true }),
  ] },
  { key: "autocode", label: "Autocode", needs: [], actions: [
    cue("autocode", "overview", "비행 코드 · 지문 대조", { args: { compareWith: EXAMPLE_ID } }),
  ] },
  { key: "verify", label: "검증", needs: [], actions: [cue("verify", "run", "검증")] },
  { key: "results", label: "결과", needs: [], actions: [
    cue("results", "open", "결과 브리핑"),
    llmCue("results", "opinion", "소견서", { args: { resultId: { $ref: "results.open" } } }),
  ] },
  { key: "ask", label: "질문", needs: [], actions: [
    { kind: "ask", label: "질문", llm: true, soft: true, question: SHOWCASE_QUESTION },
  ] },
]);

export const stepIndex = (key) => STEPS.findIndex((s) => s.key === key);

/** 동작의 참조 키 — 보고를 모아 두는 이름("tab.action"). 신호가 아닌 동작은 종류 이름. */
export const refKey = (a) => (a.kind === "cue" ? `${a.tab}.${a.action}` : a.kind);

/** 동작별 시간 상한 [ms] — 탭이 신호를 **읽었는데** 끝 보고가 안 오는 자리의 상한이다(안 읽은
 *  자리는 UNREAD_CUE_MS가 먼저 잡는다). 상한은 **마지막 소식부터** 잰다(waitVerdict — 탭이 started·
 *  progress를 알리면 다시 센다). 무료 플랜의 느린 CPU를 감안해 넉넉히 — 각 패키지 실측(로컬)의 수 배이고
 *  패키지가 요구한 하한(자동 설계 ≥ 10 min · 검증 ≥ 180 s · 시뮬 ≥ 300 s · 영향성 평가 ≥ 90 s ·
 *  처방 ≥ 300 s · δe_trim 도출 ≥ 180 s)을 모두 넘는다. S1 확정본 로컬 실측(S1-integrate, 서버 TestClient):
 *  시뮬 69 s(t_end 475) · 검증 30~39 s · 자동 설계+재개 9~26 s · δe_trim 도출 8~21 s — 그쪽 권장 하한(시뮬
 *  300 · 검증 180 · 자동 설계 180 · 도출 120 s)보다 여기 값이 크다. 모르는 동작은 기본값. */
const TIMEOUTS = {
  "envelope.scan": 5 * 60_000,
  "trim.run": 3 * 60_000,
  "gains.evaluate": 3 * 60_000,
  "margins.run": 3 * 60_000,
  "aircraft.derive-de-trim": 5 * 60_000,
  "autodesign.design-and-apply": 20 * 60_000,
  "sim.draft": 3 * 60_000,
  "sim.run": 8 * 60_000,
  "sim.duty": 3 * 60_000,
  "influence.diagnose": 3 * 60_000,
  "influence.screen": 3 * 60_000,
  "influence.evaluate": 10 * 60_000,
  "influence.prescribe": 10 * 60_000,
  "verify.run": 6 * 60_000,
  "results.opinion": 3 * 60_000,
};
const DEFAULT_TIMEOUT = 2 * 60_000;
export const actionTimeout = (a) => TIMEOUTS[refKey(a)] ?? DEFAULT_TIMEOUT;
/** 끝 보고 기다림의 전체 상한 = 동작 상한 × 이 배수 — 경과를 알리는 동안은 늘려 주되 끝은 있다. */
export const CAP_FACTOR = 3;

/** 끝 보고를 기다리는 시계 — 동작 상한은 마지막 소식(신호를 건 때·started·progress)부터 잰다: 긴 잡이
 *  경과를 알리는 동안은 기다리고, 조용해진 채 상한이 지나면 멈춘다. 전체 상한은 CAP_FACTOR배.
 *  돌려주는 것: null(계속) | "idle"(소식 끊김) | "cap"(전체 상한). */
export function waitVerdict(a, { startedAt, lastEventAt, now }) {
  const limit = actionTimeout(a);
  if (now - startedAt >= limit * CAP_FACTOR) return "cap";
  if (now - lastEventAt >= limit) return "idle";
  return null;
}

/** 시계가 멈춘 사유 한 줄(waitVerdict의 답). */
export function waitText(a, kind) {
  const s = Math.round((actionTimeout(a) * (kind === "cap" ? CAP_FACTOR : 1)) / 1000);
  return kind === "cap"
    ? `「${a.tab}」 탭이 ${s} s 안에 「${a.action}」을 끝냈다고 알리지 않았다`
    : `「${a.tab}」 탭이 ${s} s 동안 「${a.action}」의 경과도 끝도 알리지 않았다`;
}

/** 서버 사유의 첫 마디 — /llm/status reason은 설정 안내까지 한 문단이라 카드 줄에는 앞 마디만
 *  (전량은 카드 상태 줄의 툴팁). 새 문구를 만들지 않고 자르기만 한다. */
export function shortReason(text) {
  const t = String(text ?? "").trim();
  return t.split(/ — |[.。](?:\s|$)/)[0].trim() || t;
}

/** LLM 게이트 — 쓸 수 있으면 null, 아니면 건너뜀 사유(서버 /llm/status의 reason, 첫 마디). */
export function llmSkipReason(status, err = null) {
  if (status?.available) return null;
  if (status) return shortReason(status.reason) || "LLM을 사용할 수 없다 (서버가 사유를 주지 않았다)";
  return err ? `LLM 상태 조회 실패 — ${err}` : "LLM 상태를 아직 모른다";
}

/** 인자 참조를 푼다 — `{$ref: "tab.action"}` → 그 동작이 보고한 결과 id, `{$ok: …}` → 그 동작의
 *  성공 여부. 모르는 참조는 칸째 뺀다(탭이 기본값 — 없으면 최신 — 으로 간다). */
export function resolveArgs(args, refs = {}) {
  const out = {};
  for (const [k, v] of Object.entries(args ?? {})) {
    if (v && typeof v === "object" && "$ref" in v) {
      const id = refs[v.$ref]?.resultId;
      if (typeof id === "string" && id) out[k] = id;
    } else if (v && typeof v === "object" && "$ok" in v) {
      out[k] = !!refs[v.$ok]?.ok;
    } else {
      out[k] = v;
    }
  }
  return out;
}

/** 행을 따로 누를 때의 선행 조건 안내 — 막지 않는다(탭이 사유로 실패하면 그것이 답이다). */
export function preconditionNotes(stepIdx, state, { selectedId } = {}) {
  const step = STEPS[stepIdx];
  if (!step || step.key === "prepare") return [];
  const notes = [];
  if (selectedId !== SHOWCASE_ID) {
    notes.push(`지금 기체가 쇼케이스 기체(${SHOWCASE_ID})가 아니다 — 「준비」가 설치·선택한다`);
  }
  for (const k of step.needs) {
    if (state?.states?.[k]?.state === "done") continue;
    const label = STEPS[stepIndex(k)]?.label ?? k;
    notes.push(`먼저 「${label}」 — 그 결과가 없으면 탭이 사유와 함께 실패한다`);
  }
  return notes;
}

/** 이 단계가 작업 사본을 더럽히는 동작(dirties — 결함 주입)에 닿았나 — sub번 동작이 돌았거나 도는 중. */
const dirtied = (actions, sub) => actions.some((a, j) => a.dirties && j <= sub);

/** 이 단계에서 다음에 돌 동작 번호 — 실패 중이면 always(뒷정리)만, 그것도 더럽히는 동작에 닿은 뒤에만(그 전의
 *  실패는 뒷정리할 것이 없다 — 돌리면 사람이 적용해 둔 작업 사본을 지운다, cancelCleanup과 같은 규칙). 없으면 -1. */
export function nextInStep(step, sub, failing) {
  const cleanup = failing && dirtied(step.actions, sub);
  for (let j = sub + 1; j < step.actions.length; j += 1) {
    if (!failing || (cleanup && step.actions[j].always)) return j;
  }
  return -1;
}

/** 동작 하나가 끝난 뒤 — 커서를 어디로, 계속 도나.
 *  - 단계 안: 다음 동작(실패면 뒷정리만), 일시정지면 거기 커서를 두고 멈춘다
 *  - 단계 끝: 다음 단계로. 자동 재생(all)이고 멈춤·실패가 없을 때만 계속
 *  - 마지막 뒤: 커서 = 단계 수(끝)
 *  부가 동작(soft — LLM)의 실패는 실패로 세지 않는다: 줄만 남기고 다음 동작으로(초안 없이 미션 실행 등). */
export function advance({ cursor, outcome, mode, pause, failing }, steps = STEPS) {
  const step = steps[cursor.step];
  const soft = !!step.actions[cursor.sub]?.soft;
  const nowFailing = !!failing || (outcome === "failed" && !soft);
  const j = nextInStep(step, cursor.sub, nowFailing);
  if (j >= 0) {
    return { cursor: { step: cursor.step, sub: j }, stepDone: false, failing: nowFailing, go: !pause, finished: false };
  }
  const finished = cursor.step + 1 >= steps.length;
  return {
    cursor: { step: cursor.step + 1, sub: 0 },
    stepDone: true,
    failing: nowFailing,
    go: mode === "all" && !pause && !nowFailing && !finished,
    finished,
  };
}

/** 단계 상태 — 줄의 어조로 모은다(안내 줄은 세지 않는다). 부가 단계의 실패(warn)는 단계를 실패로 몰지 않지만,
 *  단계에 그것과 건너뜀뿐이면(한 일이 없다) 실패다. */
export function stepState(lines) {
  const tones = (lines ?? []).map((l) => l.tone).filter((t) => t !== "note");
  if (tones.includes("fail")) return "failed";
  if (tones.length && tones.every((t) => t === "skip")) return "skipped";
  if (tones.length && tones.every((t) => t === "skip" || t === "warn")) return "failed";
  return "done";
}

/** 자를 때 찾는 구분자 — 탭 summary가 구절을 잇는 말들. 괄호 앞도 구절 경계다. */
const SEPS = [" · ", " — ", " / ", "; ", ", ", " ("];

/** 상한 안에서 자른다 — 마지막 구분자 앞에서 끊어 구절 한가운데(「(전 칸…」)로 끝나지 않게(e2e D16). 구분자가
 *  상한의 절반보다 앞이면 글자 경계에서. */
export function clip(s) {
  if (s.length <= LINE_MAX) return s;
  const room = s.slice(0, LINE_MAX - 1);
  const cut = Math.max(...SEPS.map((sep) => room.lastIndexOf(sep)));
  return cut >= LINE_MAX / 2 ? `${room.slice(0, cut).trimEnd()} …` : `${room}…`;
}

/** 줄 하나 — 잘렸으면 전량을 full에(카드가 툴팁으로 보인다). */
const mkLine = (text, tone) => {
  const c = clip(text);
  return c === text ? { text, tone } : { text: c, tone, full: text.slice(0, LINE_FULL_MAX) };
};

/** 동작 결과 한 줄 — 완료는 탭 summary 그대로. 부가 동작(soft)의 실패는 warn — 이어 간다는 사실을 앞에 둔다
 *  (사유가 길어 잘려도 그 말은 남게). */
export function lineFor(a, o) {
  if (o.status === "skipped") return mkLine(`${a.label} — 건너뜀: ${o.reason ?? "사유 없음"}`, "skip");
  if (o.status === "failed" && a.soft) {
    return mkLine(`${a.label} — 부가 단계 실패(없이 이어 간다): ${o.error ?? "사유 없음"}`, "warn");
  }
  if (o.status === "failed") return mkLine(`${a.label} — 실패: ${o.error ?? "사유 없음"}`, "fail");
  const s = typeof o.summary === "string" ? o.summary.trim() : "";
  return mkLine(s ? `${a.label} — ${s}` : a.label, "ok");
}

/** 보고의 판정 — data.verdict("PASS"/"FAIL"), 없으면 data.pass(불), 그것도 없으면 data.hard_fail(불 — 영향성
 *  평가 보고의 모양: 참이면 FAIL). 모르면 null. */
export function verdictOf(report) {
  const d = report?.data;
  if (typeof d?.verdict === "string" && d.verdict) return d.verdict.toUpperCase();
  if (typeof d?.pass === "boolean") return d.pass ? "PASS" : "FAIL";
  if (typeof d?.hard_fail === "boolean") return d.hard_fail ? "FAIL" : "PASS";
  return null;
}

/** 기대 판정과 다르면 그 사실 — 실패로 바꾸지는 않는다(탭은 제 일을 했다). 판정을 모르면 말하지 않는다. */
export function expectNote(a, report) {
  if (!a.expect) return null;
  const v = verdictOf(report);
  return v && v !== a.expect ? `기대 판정 ${a.expect} — 실제 ${v}` : null;
}

export const emptyState = () => ({
  cursor: { step: 0, sub: 0 }, failing: false, states: {}, refs: {}, resumeMode: null, resumeAt: null, resumeId: null,
});

const setStep = (state, key, patch) => ({
  ...state,
  states: { ...state.states, [key]: { state: "pending", lines: [], ...state.states[key], ...patch } },
});

/** 단계를 처음부터 시작 — 그 단계의 지난 줄을 비우고 선행 조건 안내를 첫 줄로. */
export function beginStep(state, stepIdx, notes = []) {
  const key = STEPS[stepIdx].key;
  return {
    ...setStep(state, key, { state: "running", lines: notes.map((text) => mkLine(text, "note")) }),
    cursor: { step: stepIdx, sub: 0 },
    failing: false,
  };
}

/** 단계 한가운데서 이어 간다(일시정지 뒤 ▶) — 지난 줄을 둔다. */
export const resumeStep = (state) => setStep(state, STEPS[state.cursor.step].key, { state: "running" });

/** 동작 결과를 적고 커서를 옮긴다. 돌려주는 것: {state, go, finished, stepDone, failing}(failing — 이 단계가
 *  실패 중이다: 이 동작이나 앞 동작이 실패했다. 부가 동작의 실패는 세지 않는다). */
export function applyOutcome(state, outcome, { mode, pause }) {
  const { step: i, sub } = state.cursor;
  const step = STEPS[i];
  const a = step.actions[sub];
  const prev = state.states[step.key]?.lines ?? [];
  const extra = [expectNote(a, outcome), ...(outcome.notes ?? [])]
    .filter(Boolean).map((text) => mkLine(text, "note"));
  const lines = [...prev, lineFor(a, outcome), ...extra];
  const refs = {
    ...state.refs,
    [refKey(a)]: {
      ok: outcome.status === "done",
      resultId: outcome.status === "done" && typeof outcome.resultId === "string" ? outcome.resultId : null,
    },
  };
  const r = advance({ cursor: state.cursor, outcome: outcome.status, mode, pause, failing: state.failing });
  const next = setStep({ ...state, refs, cursor: r.cursor, failing: r.stepDone ? false : r.failing },
    step.key, { lines, state: r.stepDone ? stepState(lines) : "running" });
  return { state: next, go: r.go, finished: r.finished, stepDone: r.stepDone, failing: r.failing };
}

const noteOn = (state, text) => {
  const key = STEPS[state.cursor.step].key;
  const lines = [...(state.states[key]?.lines ?? []), mkLine(text, "note")];
  return setStep(state, key, { state: "pending", lines });
};

/** 진행이 멈췄다(일시정지·실패 뒤 끝) — 아직 「진행」으로 남은 단계를 대기로(줄·커서는 둔다, ▶가 거기서 잇는다). */
export function settleRunning(state) {
  let out = state;
  for (const [key, v] of Object.entries(state.states)) {
    if (v.state === "running") out = setStep(out, key, { state: "pending" });
  }
  return out;
}

/** 재생이 끊겼다(사용자가 가상환경을 떠남 등) — 실패가 아니다. 대기로 두고 그 동작에서 다시. */
export const interruptStep = (state, text) => noteOn(state, text);

/** [■ 중단] 때 남은 뒷정리 — 이 단계가 작업 사본을 더럽히는 동작(dirties — 결함 주입)에 이미 닿았는데(돌았거나
 *  도는 중 — 탭이 곧 실을 수 있다) 뒷정리(always)가 아직 안 끝났다. 중단은 탭 이동 없이 그 자리에서 멈추므로
 *  뒷정리 신호를 걸 수 없다 — 진행기가 그 신호와 같은 lib 함수로 대신한다(게인 restore = lib/gainsync
 *  dropWorkingCopy, views/showcase.js). 더럽히기 전의 중단은 빈 목록이다 — 사람이 적용해 둔 작업 사본을
 *  진행기가 지우지 않는다. 돌려주는 것: 뒷정리 동작 목록. */
export function cancelCleanup(state) {
  const { step: i, sub } = state.cursor;
  const acts = STEPS[i]?.actions ?? [];
  if (!acts.some((a, j) => a.dirties && j <= sub)) return [];
  return acts.filter((a, j) => a.always && j >= sub);
}

/** 진행기가 뒷정리(게인 restore)를 대신한 줄 — how: 어느 자리에서 대신했나(「중단하며」·「멈추며」 등). 말은 게인
 *  탭 restore 보고와 같다(lib/gainsync workingCopyLine). */
export const cleanupLine = (a, restored, how) => `「${a.label}」 — ${how} 진행기가 대신: ${workingCopyLine(restored)}`;

/** [■ 중단] — 그 단계를 대기로, 커서는 단계 처음으로(반쯤 돈 단계를 가운데서 잇지 않는다).
 *  restored: 진행기가 게인 restore를 대신했으면 dropWorkingCopy의 답(비운 키 목록), 아니면 null. 대신하지 못한
 *  뒷정리는 안 돈 사실을 말한다 — 결함 게인 등 작업 사본이 남았을 수 있다. head·how는 멈춤(stopStep)이 바꾼다. */
export function cancelStep(state, { restored = null, head = "중단함 — 다시 누르면 이 단계를 처음부터", how = "중단하며" } = {}) {
  const { step: i } = state.cursor;
  let out = noteOn(state, head);
  for (const a of cancelCleanup(state)) {
    out = noteOn(out, refKey(a) === "gains.restore" && Array.isArray(restored)
      ? cleanupLine(a, restored, how)
      : `「${a.label}」가 돌지 않았다 — 필요하면 그 탭에서 직접`);
  }
  return { ...out, cursor: { step: i, sub: 0 }, failing: false };
}

/** 멈춤(일시정지·손 이동·끊김·실패로 끝, 그리고 다시 읽기) 뒤 — 결함 시연 한가운데(cancelCleanup이 비지 않는다)면
 *  중단과 같이 뒷정리를 대신한 사실을 적고 단계 처음으로 되돌린다: 결함 게인이 작업 사본에 남으면 행을 다시 누른
 *  기준 평가가 결함 게인으로 돌고, 뒤 단계(Autocode·검증)도 그 게인을 쓴다(리뷰 재현 — 재주입은 ×6·×6). 가운데서
 *  잇지 않는 까닭: 되돌린 작업 사본 위에서는 처방할 FAIL이 없다. 그 밖의 멈춤은 그대로(▶가 커서에서 잇는다). */
export function stopStep(state, { restored = null } = {}) {
  if (!cancelCleanup(state).length) return state;
  return cancelStep(state, {
    restored, how: "멈추며", head: "결함 시연 한가운데서 멈췄다 — 결함 게인을 남기지 않게 이 단계를 처음부터",
  });
}

/** 결함 주입 직전에 진행기가 작업 사본을 비웠다는 줄 — 비운 것이 없으면 null(말할 것이 없다). */
export function faultBaseNote(cleared) {
  return cleared?.length ? "결함 주입 전 작업 사본 해제 — 결함은 문서 게인 위에 건다(앞선 결함·편집에 곱하지 않는다)" : null;
}

/** 자동 재생 고리가 멈춘 까닭 — 배너가 쓴다. outcome: 마지막 동작의 결과 상태, r: applyOutcome의 답(끊김이면
 *  없다), dwellCut: 머무는 사이 멈춤이 들어왔다. 돌려주는 것: "interrupted" | "finished" | "failed" | "step"(한
 *  단계 모드의 단계 끝) | "paused". 실패·끝·단계 끝이 일시정지와 겹쳐도 그쪽이 까닭이다 — 멈춤이 없었어도 거기서
 *  멈췄다. */
export function stopCause({ outcome, r = null, mode, pause = false, dwellCut = false }) {
  if (outcome === "interrupted") return "interrupted";
  if (dwellCut) return "paused";
  if (r?.finished) return "finished";
  if (r?.failing) return "failed";
  if (r?.stepDone && mode === "one") return "step";
  return pause ? "paused" : "step";
}

/** 멈춘 뒤 배너 — 손으로 탭을 옮겨 **그 때문에** 멈췄을 때만(일시정지·끊김). 실패·끝·한 단계 끝은 그 줄이
 *  상태다 — 「일시정지했다 · ▶로 이어서」라 적으면 실패를 가린다(리뷰 지적). */
export function stopBanner(cause, manual) {
  return manual && (cause === "paused" || cause === "interrupted")
    ? "탭을 손으로 옮겨 일시정지했습니다 — ▶로 이어서."
    : null;
}

/** 탭 쪽 멈춤 확인 — 진행기가 이 실행을 끝냈으면(store `showcaseBusy`가 **거짓** — [■ 중단]·실패로 끝남,
 *  views/showcase.js) 신호로 시작한 사슬은 다음 잡을 걸거나 작업 사본에 쓰지 않는다. 잡 사이 틈(결과 조회·다음
 *  잡 제출)에 중단이 오면 진행기가 취소할 잡 id가 아직 없어 탭이 스스로 멈춰야 한다 — views/autodesign.js
 *  halt()와 같은 규칙. 한 번도 안 돈 상태(undefined·null)는 멈춤이 아니다. 돌려주는 것: 사유 | null. */
export function haltReason(busy) {
  return busy === false ? "쇼케이스가 중단됐다 — 신호로 시작한 일을 여기서 멈춘다" : null;
}

const MODES = ["all", "one"];
const ID_RE = /^[A-Za-z0-9_-]{1,64}$/; // 기체 id 규칙(lib/profile.js와 같다)

/** 다시 읽기 직전 — 이어 달리기 흔적. mode: 다시 읽은 뒤 이을 실행 모드("all" 끝까지 · "one" 그 단계의
 *  나머지) — 멈출 자리(일시정지·단계 끝의 한 단계 모드)면 null이라 카드만 다시 연다. expectId: 다시 읽은 뒤
 *  골라져 있어야 할 기체 id(아니면 잇지 않는다). */
export const withResume = (state, { mode = null, now, expectId = null } = {}) => ({
  ...state,
  resumeMode: MODES.includes(mode) ? mode : null,
  resumeAt: now,
  resumeId: typeof expectId === "string" && ID_RE.test(expectId) ? expectId : null,
});

/** 다시 읽은 뒤 — 방금(창 안) 남긴 흔적인가(fresh: 카드를 다시 연다), 이을 모드(mode, null이면 잇지 않는다),
 *  골라져 있어야 할 기체(expectId). 오래됐거나 미래 시각인 흔적은 없는 것으로 친다. */
export function reloadResume(state, now) {
  const t = state?.resumeAt;
  const fresh = typeof t === "number" && now >= t && now - t <= RESUME_WINDOW_MS;
  return {
    fresh,
    mode: fresh && MODES.includes(state.resumeMode) ? state.resumeMode : null,
    expectId: fresh ? (state.resumeId ?? null) : null,
  };
}

/** 흔적을 지운다 — 한 번만 잇는다(다음 새로고침이 다시 달리지 않게). */
export const clearResume = (state) => ({ ...state, resumeMode: null, resumeAt: null, resumeId: null });

/** 카드 행 — 단계마다 상태·줄·지금 커서. */
export function rowsModel(state) {
  return STEPS.map((s, i) => {
    const st = state.states[s.key];
    const key = st?.state ?? "pending";
    return {
      key: s.key, label: s.label, index: i, state: key, stateLabel: STATE_LABEL[key],
      lines: st?.lines ?? [], current: state.cursor.step === i,
    };
  });
}

/** 카드에 보일 행 — 펼침: 전 단계. 접힘: 지금 단계 둘레(±1). 도는 중 접힘: 지금 단계 한 행에 마지막 한 줄만 —
 *  카드가 탭의 그림(M–h·게인 곡선·영향성 그래프 등) 왼쪽을 덮지 않게(e2e D14: 접혀도 ~340 px였다). 전량은
 *  [목록 펴기]로. focus: 커서 대신 보일 단계 — 단계 끝 동작 뒤 머무는 동안은 커서가 이미 다음 단계라, 청중이 보는
 *  결과의 줄(방금 끝낸 단계)을 보인다. */
export function cardRows(state, { expanded, running, focus = null }) {
  const rows = rowsModel(state);
  if (expanded) return rows;
  const c = Number.isInteger(focus) && focus >= 0 && focus < STEPS.length
    ? focus : Math.min(state.cursor.step, STEPS.length - 1);
  if (running) return rows.filter((r) => r.index === c).map((r) => ({ ...r, lines: r.lines.slice(-1) }));
  // 끝(커서가 목록 밖) — 마지막 두 단계에 마지막 한 줄씩. 도는 중 접힘과 같은 키(e2e: 끝나자 카드가 540 px로
  // 펴져 결과 탭 목록 왼쪽을 덮었다). 전량은 [목록 펴기]
  if (runEnded(state)) return rows.filter((r) => r.index >= c - 1).map((r) => ({ ...r, lines: r.lines.slice(-1) }));
  return rows.filter((r) => r.index >= c - 1 && r.index <= c + 1);
}

/** 끝까지 갔나 — 커서가 마지막 단계 뒤. */
export const runEnded = (state) => state.cursor.step >= STEPS.length;

/** 카드를 접힘(작은 폭·한 줄 자르기)으로 그리나 — 도는 중이거나 **끝난 뒤**, 사용자가 펴지 않았으면.
 *  끝난 뒤에도 접는 이유: 마지막 단계(결과 탭)의 브리핑·목록이 그 자리에 서 있다(e2e — 끝에 540 px로 펴져
 *  결과 목록을 덮었다). 멈춤(중간)은 행을 눌러 고르는 자리라 펼친다. */
export function cardCompact(state, { running, expanded }) {
  return !expanded && (running || runEnded(state));
}

/** 카드 목록 안에서만 지금 행을 보이게 할 scrollTop — 창(문서)은 건드리지 않는다.
 *  scrollIntoView는 문서까지 굴리는 요청이라, 탭이 방금 건 부드러운 굴림(lib/reveal revealPanel — 결과 탭
 *  브리핑)을 크롬이 그 자리에서 끊었다(e2e: 브리핑 y 1024에서 scrollY 0 그대로). 사각형은 getBoundingClientRect. */
export function listScrollTop({ listTop, listBottom, itemTop, itemBottom, scrollTop }) {
  if (itemTop < listTop) return scrollTop - (listTop - itemTop);
  if (itemBottom > listBottom) {
    // 행이 목록보다 크면 머리를 맞춘다(block: "nearest"와 같은 규칙)
    const down = Math.min(itemBottom - listBottom, itemTop - listTop);
    return scrollTop + down;
  }
  return scrollTop;
}

export const fabLabel = (state, running) =>
  (running ? `◆ 쇼케이스 · ${Math.min(state.cursor.step + 1, STEPS.length)}/${STEPS.length}` : "◆ 쇼케이스");

const INSTALL_LABEL = { created: "새로 설치", reset: "패키지 문서로 초기화", unchanged: "그대로" };

/** 준비 단계 줄 — 서버 설치 응답(id·리비전·동작·휘발)으로만. */
export function installSummary(res) {
  const act = INSTALL_LABEL[res?.action] ?? String(res?.action ?? "");
  return `${res?.id} r${res?.revision} · ${act}${res?.volatile ? " · 휘발 저장소" : ""}`;
}

// ── 보관 형식 ────────────────────────────────────────────────────────────────

export function encodeState(state) {
  return JSON.stringify({ v: STATE_VERSION, ...state });
}

const isObj = (v) => v != null && typeof v === "object" && !Array.isArray(v);
const isInt = (v) => Number.isInteger(v) && v >= 0;
const REF_RE = /^[a-z]+(\.[a-z-]+)?$/;

/** 보관본 → 상태. 무엇이 와도 던지지 않는다 — 판이 다르거나 깨졌으면 빈 상태, 칸 하나가 깨졌으면 그 칸만 버린다.
 *  진행 중(running)으로 남은 단계는 다시 읽기가 끊은 것이라 대기로 푼다. */
export function decodeState(raw) {
  const out = emptyState();
  let o;
  try {
    o = typeof raw === "string" ? JSON.parse(raw) : null;
  } catch {
    return out;
  }
  if (!isObj(o) || o.v !== STATE_VERSION) return out;
  const c = o.cursor;
  if (isObj(c) && isInt(c.step) && c.step <= STEPS.length) {
    const acts = STEPS[c.step]?.actions ?? [];
    out.cursor = { step: c.step, sub: isInt(c.sub) && c.sub < acts.length ? c.sub : 0 };
  }
  if (isObj(o.states)) {
    for (const s of STEPS) {
      const v = o.states[s.key];
      if (!isObj(v)) continue;
      const state = STATES.includes(v.state) && v.state !== "running" ? v.state : "pending";
      const lines = Array.isArray(v.lines)
        ? v.lines.filter((l) => isObj(l) && typeof l.text === "string" && TONES.includes(l.tone))
          .map((l) => {
            const line = mkLine(l.text, l.tone);
            return typeof l.full === "string" && l.full ? { ...line, full: l.full.slice(0, LINE_FULL_MAX) } : line;
          })
        : [];
      out.states[s.key] = { state, lines };
    }
  }
  if (isObj(o.refs)) {
    for (const [k, v] of Object.entries(o.refs)) {
      if (!REF_RE.test(k) || !isObj(v)) continue;
      out.refs[k] = {
        ok: v.ok === true,
        resultId: typeof v.resultId === "string" && v.resultId ? v.resultId : null,
      };
    }
  }
  out.failing = o.failing === true;
  out.resumeMode = MODES.includes(o.resumeMode) ? o.resumeMode : null;
  out.resumeAt = typeof o.resumeAt === "number" && Number.isFinite(o.resumeAt) ? o.resumeAt : null;
  out.resumeId = typeof o.resumeId === "string" && ID_RE.test(o.resumeId) ? o.resumeId : null;
  return out;
}
