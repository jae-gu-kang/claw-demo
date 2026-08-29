/** 블록 다이어그램 데이터 — 고정 구조(M7 조립 순서와 1:1)와 블록별 편집 경로.

시뮬링크 "블록 클릭 → 서브시스템 하위 페이지"의 대응물 (02 §4):
- schema: 레지스트리 {category, name} — 파라미터 폼의 원천 (서버 /registry 스키마)
- editable: 폼 편집 가능 여부 — 시뮬 요청에 주입 경로가 있는 블록만 true
  (AP=req.autopilot, SCAS=req.scas, 작동기=req.actuators, 항법=req.nav — 시뮬 탭은
  적용값을 프리필·병합해 소비하므로 진실은 store 한 곳)
- injectKey: 편집값을 담는 store 키 (editable=true일 때만)
- axes: 축이 여럿인 블록(SCAS)의 하위 페이지 id → {group, varName, cPrefix}.
  폼은 블록이 아니라 **축 페이지**에 붙고 store 값은 {축: kwargs} 한 벌이다
  (서버 req.scas 계약 — 세 축 전부가 한 요청)
- **스케줄이 덮는 자리는 폼에서 잠긴다** (editable과 별개 층): 게인 탭이 그 자리에
  테이블을 붙여 두면 실행 시점에 룩업이 상수를 이기므로(fcl/graphs.py), 상수 입력을
  열어 두면 값이 둘인 척하게 된다. 판정은 lib/gainsync.js lockedParams
- omit: 폼·주입에서 제외할 스키마 파라미터명 — 주입 경로의 예약 키
  (예: 작동기 pos_lo·pos_hi·initial은 Simulator가 믹서 한계·트림 웜스타트로 결정)
- edit: {hash, label} — 정본 편집 화면으로 이동
- codegen: 코드 생성의 표시 계약 {varName, cPrefix, kind, hint} (editable일 때만).
  kind="dict"는 주입 경로가 객체가 아니라 kwargs dict인 경우(작동기).
  파이썬 클래스·임포트 경로는 여기 두지 않는다 — 서버 /registry/…/validate가
  엔진 인스턴스에서 얻어 주므로 이름 드리프트가 생길 수 없다
배선은 고정 [확정 02 §4] — 이 데이터에 배선 편집 개념은 없다. SVG 기하(좌표·
배선 그림)는 views/diagram.js·subsystems.js 수작성 — 여기는 계약 데이터만.
*/

/** 주 신호 경로 (좌→우) — M7 FlightControlLaw 조립 순서의 정본. 테스트가
최상위 SVG(views/diagram.js TOP_SVG)의 블록 등장 순서와 대조한다. */
export const CHAIN = ["guidance", "autopilot", "limiter", "scas", "mixer", "actuator", "plant"];

/** 해시 세그먼트 → 드릴다운 트리 경로 (views/subsystems.js children 규약).

미실존 세그먼트에서 절단 — 빈 배열 = 홈. 하강 규칙의 정본은 이 순수 함수
(단위 테스트 대상), 뷰(views/blocks.js)는 해시 파싱·DOM만 담당.
hasOwn 검사: "constructor" 같은 프로토타입 상속 키가 실존 페이지로 오인되어
렌더 크래시하는 것을 방지 (손입력 해시 방어). */
export function resolvePath(segs, tree) {
  const path = [];
  let nodes = tree;
  for (const seg of segs) {
    if (!nodes || !Object.hasOwn(nodes, seg) || !nodes[seg]) break;
    path.push(seg);
    nodes = nodes[seg].children;
  }
  return path;
}

/** 코드 표현 대상 — 축이 여럿인 블록(SCAS)은 **축마다 한 줄**이다.
 *
 * lib/codegen.js의 spec은 변수 하나를 그리는 물건이라 `scas = ScasAxis(...)` 한 줄로는
 * 세 축을 표현할 수 없다. varName·cPrefix만 축 것으로 갈아 끼우면 kind는 그대로
 * "object"라 코드 생성 계층은 손댈 것이 없다.
 *
 * stored = 그 블록의 store 값 (SCAS는 {축: kwargs}), design = 축별 설계 kwargs
 * (/gains/catalog scas_design). **설계값을 모르는 축은 대상에서 뺀다** — ScasAxis의
 * 스키마 기본값은 전부 0이라, 카탈로그를 못 받은 채 내보내면 게인이 죽은 형상을
 * "지금 형상"이라고 보여 주게 된다. 구조도 축 폼이 같은 이유로 편집을 안 여는 것과
 * 같은 규칙이다 (views/blocks.js loadSchema).
 *
 * applied는 values와 따로다: 설계값으로 채운 줄은 값이 있어도 "편집값"이 아니다
 * — 그렇게 표시하면 아무것도 안 고친 사용자에게 "기본값 대비 5개 변경"이 뜬다. */
export function codegenTargets(block, stored, design = null) {
  const { axes, codegen } = block.detail;
  if (!axes) return [{ values: stored ?? null, applied: stored != null, cg: codegen }];
  const out = [];
  for (const ax of Object.values(axes)) {
    const edited = stored?.[ax.group] ?? null;
    const values = edited ?? design?.[ax.group] ?? null;
    if (!values) continue; // 편집값도 설계값도 없다 = 값을 모른다
    out.push({
      values,
      applied: edited != null,
      cg: { ...codegen, varName: ax.varName, cPrefix: ax.cPrefix, group: ax.group },
    });
  }
  return out;
}

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
      codegen: { varName: "ap", cPrefix: "AP", kind: "object" },
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
        + "축 페이지(피치·롤·요)에서 편집하고 '시뮬에 적용' — 세 축이 한 벌로 주입된다. "
        + "스케줄이 붙은 자리는 테이블이 정본이라 잠기고, 게인 탭이 편집처다.",
      schema: { category: "fcl", name: "ScasAxis" }, editable: true,
      injectKey: "scasParams",
      axes: {
        pitch: { group: "pitch", varName: "scas_pitch", cPrefix: "SCAS_PITCH" },
        roll: { group: "roll", varName: "scas_roll", cPrefix: "SCAS_ROLL" },
        yaw: { group: "yaw", varName: "scas_yaw", cPrefix: "SCAS_YAW" },
      },
      edit: { hash: "gains", label: "게인 탭 — 스케줄 자리·테이블 편집" },
      codegen: { varName: "scas", cPrefix: "SCAS", kind: "object" },
    },
  },
  {
    id: "mixer",
    title: "엘레본 믹싱", sub: "제어 할당 · 차동추력",
    detail: {
      desc: "엘레본4 고정 믹싱(내/외측 1:1) + 러더 + 차동추력 보상 [기본값 01 §2.2] — "
        + "여유자유도 최적 배분(제어 할당)으로의 확장은 추후. "
        + "여기만 폼이 없는 이유: 타면 한계·믹싱 비율은 값 튜닝이 아니라 **형상 결정**이라 "
        + "기체 데이터 확인 시 정해진다 [TBD 01 §2.2]. 같은 블록의 k_diff_thr는 성격이 "
        + "다른 튜닝 파라미터지만, 파라미터 단위로 여는 계약이 아직 없어 함께 잠겨 있다.",
      schema: { category: "fcl", name: "Mixer" }, editable: false, injectKey: null,
      edit: null,
    },
  },
  {
    id: "actuator",
    title: "작동기", sub: "2차계 (기본값)",
    detail: {
      desc: "2차계 작동기 (wn·ζ·rate 한계) — rate ≥ 10 rad/s 요구 [도출 사양 01 v0.13]. "
        + "여기서 '시뮬에 적용'한 값이 시뮬 탭 '작동기' 그룹에 프리필·병합된다. "
        + "위치 한계·초기값은 믹서 타면 한계·트림 웜스타트가 결정 (편집 대상 아님).",
      schema: { category: "actuator", name: "SecondOrderActuator" }, editable: true,
      injectKey: "actuatorParams",
      omit: ["pos_lo", "pos_hi", "initial"], // Simulator actuator_params 예약 키 (test_sim 핀)
      edit: { hash: "sim", label: "시뮬 탭 — 실행 조건 '작동기'에서 최종 확인" },
      codegen: {
        varName: "actuator_params", cPrefix: "ACT", kind: "dict",
        hint: "Simulator(actuator_params=…)로 전달 — 위치 한계·초기값은 믹서 타면 한계와 "
          + "트림 웜스타트가 결정하므로 생성 코드에도 넣지 않는다.",
      },
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
        + "여기서 '시뮬에 적용'한 값이 시뮬 실행의 항법 파라미터가 된다 (시드는 시뮬 탭 우선).",
      schema: { category: "nav", name: "ErrorModel" }, editable: true, injectKey: "navParams",
      edit: { hash: "sim", label: "시뮬 탭 — 실행 조건 '항법'에서 최종 확인" },
      codegen: {
        varName: "nav", cPrefix: "NAV", kind: "object",
        hint: "시뮬 실행 시 seed만 시뮬 탭 값이 최종 — 나머지는 이 형상 그대로 주입된다.",
      },
    },
  },
];
