/** 블록 다이어그램 데이터 — 고정 구조(M7 조립 순서와 1:1)와 블록별 편집 경로.

시뮬링크 "블록 더블클릭 → 파라미터 대화상자"의 대응물 (02 §4):
- schema: 레지스트리 {category, name} — 파라미터 폼의 원천 (서버 /registry 스키마)
- editable: 폼 편집 가능 여부 — 시뮬 요청에 주입 경로가 있는 블록만 true
  (진실이 두 곳이 되는 것 방지 — 작동기·항법은 시뮬 탭 실행 조건이 편집처)
- injectKey: 편집값을 담는 store 키 (editable=true일 때만)
- edit: {hash, label} — 정본 편집 화면으로 이동
배선은 고정 [확정 02 §4] — 이 데이터에 배선 편집 개념은 없다.
*/

const Y = 110; // 주 신호 경로 행
const BH = 52;

export const DIAGRAM_W = 1060;
export const DIAGRAM_H = 330;

export const BLOCKS = [
  {
    id: "schedule", x: 330, y: 18, w: 260, h: 44,
    title: "게인 스케줄 (M7)", sub: "mach·alt·fuel → kp·ki·k_rate",
    detail: {
      desc: "AP·SCAS 게인을 비행조건(동압 스케일 1D mach)으로 스케줄. "
        + "테이블이 정본 — 편집은 게인 탭에서.",
      schema: null, editable: false, injectKey: null,
      edit: { hash: "gains", label: "게인 탭 — 스케줄 테이블 편집" },
    },
  },
  {
    id: "guidance", x: 15, y: Y, w: 105, h: BH,
    title: "유도 (M8)", sub: "모드 테이블·LOS",
    detail: {
      desc: "선언적 모드 테이블 + LOS 경로추종 → 속도·고도·헤딩 명령. "
        + "미션(모드·웨이포인트·도달반경)은 시뮬레이션 탭이 편집처.",
      schema: { category: "guidance", name: "LOS" }, editable: false, injectKey: null,
      edit: { hash: "sim", label: "시뮬 탭 — 모드 테이블·웨이포인트 편집" },
    },
  },
  {
    id: "autopilot", x: 158, y: Y, w: 128, h: BH,
    title: "오토파일럿", sub: "속도·고도·헤딩 PI",
    detail: {
      desc: "외루프 PI + 명령필터 + 선회 FF → θ·φ·스로틀 명령. "
        + "여기서 편집한 값은 '시뮬에 적용' 후 시뮬 탭 '편집 AP'로 주입 (전체 kwargs).",
      schema: { category: "fcl", name: "Autopilot" }, editable: true, injectKey: "autopilotParams",
      edit: null,
    },
  },
  {
    id: "limiter", x: 324, y: Y, w: 118, h: BH,
    title: "α 리미터", sub: "θ_cmd ≤ f(α_stall)",
    detail: {
      desc: "실속 진입 자체를 방지하는 엔벨로프 보호 [확정 01 §3.6] — "
        + "피치 명령 하드 클램프, 보호마진 0.05 rad [기본값]. "
        + "실속 테이블(공력 정본) 의존이라 파라미터 폼 대상 아님.",
      schema: null, editable: false, injectKey: null,
      edit: { hash: "envelope", label: "엔벨로프 탭 — V-n 선도·보호 경계" },
    },
  },
  {
    id: "scas", x: 478, y: Y, w: 122, h: BH,
    title: "SCAS", sub: "자세 PI + 레이트",
    detail: {
      desc: "축 공통 구조: PI(자세오차) + k_rate·washout(각속도), 출력 클립. "
        + "kp·ki·k_rate의 정본은 게인 스케줄 — 편집은 게인 탭에서 (여긴 구조·범위 열람).",
      schema: { category: "fcl", name: "ScasAxis" }, editable: false, injectKey: null,
      edit: { hash: "gains", label: "게인 탭 — kp·ki·k_rate 스케줄 편집" },
    },
  },
  {
    id: "mixer", x: 636, y: Y, w: 122, h: BH,
    title: "믹서", sub: "엘레본4·차동추력",
    detail: {
      desc: "엘레본4 고정 믹싱(내/외측 1:1) + 러더 + 차동추력 보상 [기본값 01 §2.2]. "
        + "웹 주입 경로 없음 — 믹싱 비율·4면 배치는 기체 데이터 확인 시 [TBD].",
      schema: { category: "fcl", name: "Mixer" }, editable: false, injectKey: null,
      edit: null,
    },
  },
  {
    id: "actuator", x: 794, y: Y, w: 116, h: BH,
    title: "작동기", sub: "2차계 rate≥10",
    detail: {
      desc: "2차계 작동기 (wn·ζ·rate 한계) — rate ≥ 10 rad/s 요구 [도출 사양 01 v0.13]. "
        + "실행값은 시뮬 탭 '작동기' 그룹이 편집처.",
      schema: { category: "actuator", name: "SecondOrderActuator" }, editable: false, injectKey: null,
      edit: { hash: "sim", label: "시뮬 탭 — 실행 조건 '작동기' 편집" },
    },
  },
  {
    id: "plant", x: 942, y: Y, w: 103, h: BH,
    title: "플랜트", sub: "6DOF RK4",
    detail: {
      desc: "6DOF 강체 + 공력 DB(데모 프로파일) + ISA, RK4 dt 10 ms [확정 02 §6]. "
        + "평형점·트림 가능 영역은 트림 탭에서.",
      schema: null, editable: false, injectKey: null,
      edit: { hash: "trim", label: "트림 탭 — 평형점·비행 엔벨로프 맵" },
    },
  },
  {
    id: "nav", x: 430, y: 230, w: 190, h: 44,
    title: "항법 (M6 오차 모델)", sub: "잡음·바이어스·지연·주기",
    detail: {
      desc: "등가 오차 모델 — 법칙·유도·스케줄은 NavOutput만 소비 (참값 차단 계약 03 §4). "
        + "실행값(시드 등)은 시뮬 탭 '항법 오차 모델' 그룹이 편집처.",
      schema: { category: "nav", name: "ErrorModel" }, editable: false, injectKey: null,
      edit: { hash: "sim", label: "시뮬 탭 — 실행 조건 '항법' 편집" },
    },
  },
];

/** 논리 좌표 (x, y) → 블록 또는 null. 경계 포함. */
export function hitBlock(x, y, blocks = BLOCKS) {
  for (const b of blocks) {
    if (x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h) return b;
  }
  return null;
}
