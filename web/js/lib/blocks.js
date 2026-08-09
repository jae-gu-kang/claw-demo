/** 블록 다이어그램 데이터 — 고정 구조(M7 조립 순서와 1:1)와 블록별 편집 경로.

시뮬링크 "블록 클릭 → 서브시스템 하위 페이지"의 대응물 (02 §4):
- schema: 레지스트리 {category, name} — 파라미터 폼의 원천 (서버 /registry 스키마)
- editable: 폼 편집 가능 여부 — 시뮬 요청에 주입 경로가 있는 블록만 true
  (진실이 두 곳이 되는 것 방지 — 작동기·항법은 시뮬 탭 실행 조건이 편집처)
- injectKey: 편집값을 담는 store 키 (editable=true일 때만)
- edit: {hash, label} — 정본 편집 화면으로 이동
배선은 고정 [확정 02 §4] — 이 데이터에 배선 편집 개념은 없다. SVG 기하(좌표·
배선 그림)는 views/diagram.js·subsystems.js 수작성 — 여기는 계약 데이터만.
*/

/** 주 신호 경로 (좌→우) — M7 FlightControlLaw 조립 순서의 정본. 테스트가
최상위 SVG(views/diagram.js TOP_SVG)의 블록 등장 순서와 대조한다. */
export const CHAIN = ["guidance", "autopilot", "limiter", "scas", "mixer", "actuator", "plant"];

export const BLOCKS = [
  {
    id: "planner",
    title: "미션플래너", sub: "웨이포인트 → 임무프로파일",
    detail: {
      desc: "웨이포인트 열로부터 임무프로파일(경로 + 비행모드 시퀀스) 생성. "
        + "미션(모드 테이블·웨이포인트·도달반경)은 시뮬레이션 탭이 편집처.",
      schema: null, editable: false, injectKey: null,
      edit: { hash: "sim", label: "시뮬 탭 — 미션(모드·웨이포인트) 편집" },
    },
  },
  {
    id: "schedule",
    title: "게인 스케줄링", sub: "K = f(Mach, 고도, 연료량)",
    detail: {
      desc: "AP·SCAS 게인을 비행조건으로 스케줄 [확정 01 §3.4 — Mach·고도·연료량] "
        + "(데모 기체는 동압 스케일 1D mach [기본값]). 테이블이 정본 — 편집은 게인 탭에서.",
      schema: null, editable: false, injectKey: null,
      edit: { hash: "gains", label: "게인 탭 — 스케줄 테이블 편집" },
    },
  },
  {
    id: "guidance",
    title: "유도 (M8)", sub: "모드 실행기 · 경로 추종",
    detail: {
      desc: "선언적 모드 테이블 + LOS 경로추종 → 속도·고도·헤딩 명령. "
        + "미션(모드·웨이포인트·도달반경)은 시뮬레이션 탭이 편집처.",
      schema: { category: "guidance", name: "LOS" }, editable: false, injectKey: null,
      edit: { hash: "sim", label: "시뮬 탭 — 모드 테이블·웨이포인트 편집" },
    },
  },
  {
    id: "autopilot",
    title: "오토파일럿", sub: "속도·고도·헤딩 (PI)",
    detail: {
      desc: "외루프 PI + 명령필터 + 선회 FF → θ·φ·스로틀 명령. "
        + "여기서 편집한 값은 '시뮬에 적용' 후 시뮬 탭 '편집 AP'로 주입 (전체 kwargs).",
      schema: { category: "fcl", name: "Autopilot" }, editable: true, injectKey: "autopilotParams",
      edit: null,
    },
  },
  {
    id: "limiter",
    title: "α 리미터", sub: "엔벨로프 보호",
    detail: {
      desc: "실속 진입 자체를 방지하는 엔벨로프 보호 [확정 01 §3.6] — "
        + "피치 명령 하드 클램프, 보호마진 0.05 rad [기본값]. "
        + "실속 테이블(공력 정본) 의존이라 파라미터 폼 대상 아님.",
      schema: null, editable: false, injectKey: null,
      edit: { hash: "envelope", label: "엔벨로프 탭 — V-n 선도·보호 경계" },
    },
  },
  {
    id: "scas",
    title: "SCAS", sub: "자세 안정화 (PI)",
    detail: {
      desc: "축 공통 구조: PI(자세오차) + k_rate·washout(각속도), 출력 클립. "
        + "kp·ki·k_rate의 정본은 게인 스케줄 — 편집은 게인 탭에서 (여긴 구조·범위 열람).",
      schema: { category: "fcl", name: "ScasAxis" }, editable: false, injectKey: null,
      edit: { hash: "gains", label: "게인 탭 — kp·ki·k_rate 스케줄 편집" },
    },
  },
  {
    id: "mixer",
    title: "제어면 혼합", sub: "+ 차동추력 보상",
    detail: {
      desc: "엘레본4 고정 믹싱(내/외측 1:1) + 러더 + 차동추력 보상 [기본값 01 §2.2]. "
        + "웹 주입 경로 없음 — 믹싱 비율·4면 배치는 기체 데이터 확인 시 [TBD].",
      schema: { category: "fcl", name: "Mixer" }, editable: false, injectKey: null,
      edit: null,
    },
  },
  {
    id: "actuator",
    title: "작동기", sub: "2차계 (기본값)",
    detail: {
      desc: "2차계 작동기 (wn·ζ·rate 한계) — rate ≥ 10 rad/s 요구 [도출 사양 01 v0.13]. "
        + "실행값은 시뮬 탭 '작동기' 그룹이 편집처.",
      schema: { category: "actuator", name: "SecondOrderActuator" }, editable: false, injectKey: null,
      edit: { hash: "sim", label: "시뮬 탭 — 실행 조건 '작동기' 편집" },
    },
  },
  {
    id: "plant",
    title: "기체 동역학", sub: "6DOF",
    detail: {
      desc: "6DOF 강체 + 공력 DB(데모 프로파일) + ISA, RK4 dt 10 ms [확정 02 §6]. "
        + "평형점·트림 가능 영역은 트림 탭에서.",
      schema: null, editable: false, injectKey: null,
      edit: { hash: "trim", label: "트림 탭 — 평형점·비행 엔벨로프 맵" },
    },
  },
  {
    id: "nav",
    title: "항법", sub: "등가 오차 모델",
    detail: {
      desc: "등가 오차 모델(참값 + 잡음 + 바이어스 + 지연) — 법칙·유도·스케줄은 "
        + "NavOutput만 소비 (참값 차단 계약 03 §4). "
        + "실행값(시드 등)은 시뮬 탭 '항법 오차 모델' 그룹이 편집처.",
      schema: { category: "nav", name: "ErrorModel" }, editable: false, injectKey: null,
      edit: { hash: "sim", label: "시뮬 탭 — 실행 조건 '항법' 편집" },
    },
  },
];
