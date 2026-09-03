/** 서브시스템 하위 페이지 데이터 — 시뮬링크 "블록 더블클릭 → 내부 진입" 대응 (02 §4).

각 페이지: pagehead 메타(단계 태그·영문·상태 칩) + 내부 블록도 SVG + 설계 노트.
SVG·노트는 수작성 정적 마크업 (fromMarkup으로 DOM화 — 사용자 데이터 삽입 금지).
페이지 id는 lib/blocks.js 블록 id + "verify"(설계 ⑤ — 블록 아닌 설계 단계 페이지).

## 2계층 시각 문법 — 코드 대응은 색, 설명은 무채색 (02 §4)

시뮬링크에 익숙한 독자가 블록만 보고 이해하도록 그림은 펼치되, **엔진 코드와의
대응 여부를 색으로 정직하게** 말한다 (lib/blocks.test.js가 실존을 검증):

- **코드 대응**: `data-code="plant/eom.py:RigidBody.deriv"` — engine/claw/ 기준
  경로:심볼 (`Class` | `Class.method` | `function`, 공백 구분 복수 허용). 면이
  페이지 설계 단계 색의 밝은 틴트로 칠해진다 (SUB_TINT → CSS --sub-tint).
  등록명(LOS ≠ LosPath)이 아니라 파일:심볼로 지목 — 테스트가 원문과 대조한다.
  포트 배지도 시그니처의 인자/반환이므로 코드 대응이다.
- **설명용**: 수정자 클래스 `nblk` (`class="sblk nblk"`, Σ원은 `class="body nblk"`,
  배선은 `class="wire note"`) — 흰 면 + 회색 점선. 엔진에 없는 도해 요소
  (버스 분기, 미구현 출력 등). data-code·data-child·data-p 금지 (테스트 가드).

구조 자체는 여전히 엔진과 1:1이고 자유 배선은 없다 (01 §3 유지) — 완화된 것은
"그리는 범위"뿐이며, 그린 것이 코드인지 도해인지는 색이 구분한다.

드릴다운 트리(깊이 무제한): 페이지의 children = { childId: {crumb, title, eng,
chips, svg, notes, children?, schema?} } — tag/tagBg는 루트 상속. 페이지 SVG 안의
<g class="blk" data-child="childId" tabindex="0"> 블록 클릭 → 한 층 하강
(#blocks/scas/pitch/pi — views/blocks.js 라우팅). data-child 참조는 그 페이지
children 키만 허용 (lib/blocks.test.js 가드 — 오타 = 클릭 무반응).

SVG 안의 <tspan data-p="이름">은 파라미터 연동 표시값 — views/blocks.js가 렌더 시
스키마 기본값(+적용된 편집값)으로 채우고, 편집 폼 입력과 실시간 동기화한다.
초기 텍스트는 참고용 폴백일 뿐 정본이 아님 (정본 = 엔진 레지스트리 스키마).
data-p 이름은 그 페이지의 **바인딩 소스** 스키마 파라미터명만 허용
(lib/blocks.test.js 가드). 바인딩 소스가 없는 루트(scas 등) 아래에서는 사용 금지.
data-code는 별개 축이다 — data-p 금지 루트에도 data-code는 붙는다.

## 하위 페이지 스키마 (`schema`)

`schema: {category, name}`을 붙이면 그 페이지가 **자기 바인딩 소스**를 갖는다 —
루트에 스키마가 없는 나무(plant)에서 하위(추진)의 레지스트리 파라미터를 보여 주는
유일한 길이다. **언제나 열람 전용**이다: 편집은 시뮬 요청에 주입 경로가 있는 블록만
연다는 계약(lib/blocks.js 헤더)이고 하위 페이지에는 그 경로가 없다. 그래서
editable·injectKey는 붙이지 않는다 (테스트 가드). 렌더는 views/blocks.js
loadSubSchema, 실존·이름 목록은 lib/blocks.test.js가 검증한다.
*/

import { DESIGN_ORDER } from "./diagram.js"; // 순환 없음: subsystems → diagram → lib/blocks

// 상태 칩 종류 → 라벨 (fcs-context 문서 태그와 동일 의미)
export const CHIP_LABEL = { ok: "확정", dft: "기본값", tbd: "TBD", note: "설계 유의" };

/** 코드 대응 블록의 면 틴트 — 루트 tagBg → {tint(면), edge(테두리)}.
설계 단계 ①~⑤의 5색은 최상위 보드 판 색(diagram.js LAYERS[].fill)이 정본이라
여기서 복사하지 않고 DESIGN_ORDER에서 뽑는다 (어긋나면 삼중 사본 — 테스트가 판다).
비층 3색(보호·배분/HW/입력·피드백)만 여기가 정본. 틴트 위에는 --text와 #4b5563
글자가 얹히므로 대비 4.5:1 이상이어야 한다 (lib/blocks.test.js가 계산). */
export const SUB_TINT = {
  ...Object.fromEntries(DESIGN_ORDER.map((s) => [s.color, { tint: s.tint, edge: s.edge }])),
  "#b3352b": { tint: "#f8ded9", edge: "#dd9a90" }, // α 리미터 — 보호
  "#5f6b78": { tint: "#e0e5eb", edge: "#aeb8c4" }, // 믹서·작동기·플래너 — 슬레이트
  "#0e7c86": { tint: "#d5edef", edge: "#86c2c8" }, // 항법 — 청록
};

// SCAS 축 공용 층4 — 엔진 blocks/controllers.py PID(kd=0)와 1:1.
// 세 축이 동일 구조라 정의 하나를 공유 (게인 값만 축별 상이 — 정본은 게인 탭).
const SCAS_PI_PAGE = {
  crumb: "PI",
  title: "PI — 클램프 안티와인드업", eng: "blocks.PID (kd=0) · y = clip(kp·e + I) · I ← clip(I + dt·ki·e)",
  chips: ["ok", "dft"],
  svg: `
<svg viewBox="0 0 900 320" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-pi" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <g class="sblk" data-code="blocks/controllers.py:PID.step"><rect class="body" x="30" y="138" width="36" height="24" rx="12"/><text class="pnum" x="48" y="154">1</text></g>
  <text class="pname" x="48" y="182">e (자세 오차)</text>
  <path class="wire" d="M66 150 H146"/>
  <circle class="branch" cx="150" cy="150" r="3.2"/>
  <path class="wire" d="M150 150 V86 H226" marker-end="url(#aw-pi)"/>
  <g class="sblk" data-code="blocks/controllers.py:PID.step"><polygon class="body" points="230,58 230,114 320,86"/>
    <text class="ttl2" x="258" y="90" style="font-weight:700" data-gain="kp">kp</text></g>
  <text class="bname" x="262" y="132">비례항</text>
  <path class="wire" d="M320 86 H480 V132" marker-end="url(#aw-pi)"/>
  <path class="wire" d="M150 150 V222 H196" marker-end="url(#aw-pi)"/>
  <g class="sblk" data-code="blocks/controllers.py:PID.step"><rect class="body" x="200" y="190" width="250" height="64" rx="3"/>
    <text class="ttl" x="325" y="214" style="font-size:13px">적분기 1/s — 클램프 AW</text>
    <text class="ttl2" x="325" y="236" data-gain="ki">I ← clip(I + dt·ki·e, out_lo~hi)</text></g>
  <path class="wire" d="M450 222 H480 V168" marker-end="url(#aw-pi)"/>
  <circle class="body" data-code="blocks/controllers.py:PID.step" cx="480" cy="150" r="14"/>
  <text class="sumsign" x="480" y="143">+</text><text class="sumsign" x="480" y="163">+</text>
  <path class="wire" d="M494 150 H526" marker-end="url(#aw-pi)"/>
  <g class="sblk" data-code="blocks/controllers.py:PID.step"><rect class="body" x="530" y="124" width="110" height="52" rx="3"/>
    <path d="M542 166 H558 L612 134 H628" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="585" y="194">출력 클립 out_lo~hi</text>
  <path class="wire" d="M640 150 H726" marker-end="url(#aw-pi)"/>
  <g class="sblk" data-code="blocks/controllers.py:PID.step"><rect class="body" x="730" y="138" width="36" height="24" rx="12"/><text class="pnum" x="748" y="154">1</text></g>
  <text class="pname" x="748" y="182">u_PI → k_rate 합산</text>
  <text class="canvas-note" x="24" y="290">※ 안티와인드업 = 적분 '상태' 자체를 out_lo~hi로 클램프 — 포화 해제 시 즉시 복귀 · 이산화: 전진 오일러, dt는 제어주기에서 자동 [확정 §3.5]</text>
  <text class="canvas-note" x="24" y="308">※ kp·ki는 게인 스케줄이 스텝 인자로 덮어씀 (생성 후 게인 변경은 이 경로만) · 재관여 시 reset(state) 적분 웜스타트 [범프리스 계약]</text>
</svg>`,
  flow: {
    lead: "e → kp·e 와 ∫ki·e 두 갈래 → 합 → 클립 → u_PI",
    reads: [
      "축이 만든 자세 오차 e가 ①로 들어와 곧바로 <b>두 갈래로</b> 갈린다 (분기점이 그 점이다).",
      "위쪽은 kp 삼각형 — 지금 이 순간의 오차에 비례해 친다.",
      "아래쪽은 적분기다. I ← clip(I + dt·ki·e, out_lo~hi) — 더한 뒤 <b>상태 자체를</b> 잘라 둔다.",
      "둘을 더하고(+ +) 다시 out_lo~hi로 클립한 것이 u_PI이고, 축으로 돌아가 k_rate 항과 합쳐진다.",
    ],
    why: [
      "이 그림에서 볼 것은 안티와인드업이 출력이 아니라 <b>적분 상태</b>를 클램프한다는 점이다. 출력만 자르면 포화 중에도 적분기는 계속 쌓이고, 포화가 풀린 뒤 그 쌓인 값을 게워낼 때까지 응답이 안 돌아온다. 상태를 잘라 두면 해제되는 순간 바로 복귀한다.",
      "미분항이 없다(kd=0). 감쇠는 축의 k_rate가 항법 각속도로 직접 하는 편이 낫다 — 오차를 미분하면 명령이 바뀌는 순간 킥이 생기고 잡음이 두 번 증폭된다.",
      "세 축이 이 <b>한 페이지</b>를 공유한다. 구조가 같고 값만 다르기 때문이고, 그래서 여기 설명도 한 벌이다.",
    ],
  },
  notes: `
<h4>설계 노트</h4>
<ul>
  <li>안티와인드업: <b>적분 상태 자체를 클램프</b> — 출력 클립과 같은 한계(out_lo~hi) 사용 <span class="chip dft">기본값 M7</span>. 포화 중 적분이 한계 밖으로 누적되지 않아 해제 시 즉시 응답</li>
  <li>이산화: 전진 오일러 — 계수는 제어주기(100 Hz)로부터 자동 계산 <span class="chip ok">확정 §3.5</span>, 미분항은 SCAS에서 미사용(kd=0)</li>
  <li>게인 kp·ki의 정본은 게인 탭 테이블 — 스케줄이 <b>스텝별 인자 덮어쓰기</b>로 주입 (생성자 게인은 스케줄 미사용 시 폴백)</li>
  <li>재관여(reset) 시 적분기 <b>웜스타트</b>(state 인자) — 모드 전환 킥 방지 <span class="chip ok">범프리스 계약</span></li>
</ul>`,
};

export const SUBSYSTEMS = {

  // ── SCAS — 내측 루프 (설계 ②) ─────────────────────────────────────────
  // 층2 = 축 서브시스템 블록 개요 (시뮬링크식) — 축 상세는 children (층3),
  // PI 내부는 층4 (SCAS_PI_PAGE 공유)
  scas: {
    tag: "설계 ②", tagBg: "#2563eb",
    title: "SCAS — 내측 루프 (자세 안정화)", eng: "축 공통 구조: PI(자세오차) + k_rate·각속도 — LQR 제외",
    chips: ["ok", "dft"],
    svg: `
<svg viewBox="0 0 960 470" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-scas" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <!-- 게인 스케줄 주입 (공통) — 주석 프레임 -->
  <rect x="640" y="18" width="292" height="56" rx="8" fill="none" stroke="#8a5cf6" stroke-width="1.4" stroke-dasharray="6 4"/>
  <text class="annot" x="786" y="42" text-anchor="middle">게인 스케줄링 주입 — kp·ki·k_rate</text>
  <text class="annot" x="786" y="62" text-anchor="middle">스텝별 덮어쓰기 (정본 = 게인 탭 테이블)</text>
  <!-- 입력 포트 -->
  <g class="sblk" data-code="fcl/scas.py:Scas.step"><rect class="body" x="30" y="110" width="36" height="24" rx="12"/><text class="pnum" x="48" y="126">1</text></g>
  <text class="pname" x="48" y="154">θ_cmd ← α 리미터</text>
  <path class="wire" d="M66 122 H326" marker-end="url(#aw-scas)"/>
  <g class="sblk" data-code="fcl/scas.py:Scas.step"><rect class="body" x="30" y="220" width="36" height="24" rx="12"/><text class="pnum" x="48" y="236">2</text></g>
  <text class="pname" x="48" y="264">φ_cmd ← AP</text>
  <path class="wire" d="M66 232 H326" marker-end="url(#aw-scas)"/>
  <g class="sblk" data-code="fcl/scas.py:Scas.step"><rect class="body" x="30" y="392" width="36" height="24" rx="12"/><text class="pnum" x="48" y="408">3</text></g>
  <text class="pname a-start" x="30" y="444">NavOutput (θ·φ·β · p·q·r)</text>
  <path class="wire" d="M66 404 H120 V146 H326" marker-end="url(#aw-scas)"/>
  <circle class="branch" cx="120" cy="366" r="3.2"/>
  <path class="wire" d="M120 366 H326" marker-end="url(#aw-scas)"/>
  <circle class="branch" cx="120" cy="256" r="3.2"/>
  <path class="wire" d="M120 256 H326" marker-end="url(#aw-scas)"/>
  <text class="siglabel" x="296" y="140">θ·q</text>
  <text class="siglabel" x="296" y="250">φ·p</text>
  <text class="siglabel" x="296" y="360">β·r</text>
  <!-- 축 서브시스템 블록 (클릭 → 층3) -->
  <g class="blk" data-child="pitch" data-code="fcl/scas.py:ScasAxis" tabindex="0">
    <rect class="body" x="330" y="84" width="300" height="76" rx="3"/>
    <text class="ttl" x="480" y="116">피치축 (ScasAxis)</text>
    <text class="ttl2" x="480" y="140">PI + k_rate·q → δe · 클릭 → 내부</text>
  </g>
  <g class="blk" data-child="roll" data-code="fcl/scas.py:ScasAxis" tabindex="0">
    <rect class="body" x="330" y="194" width="300" height="76" rx="3"/>
    <text class="ttl" x="480" y="226">롤축 (ScasAxis)</text>
    <text class="ttl2" x="480" y="250">wrap ±π 오차 PI + k_rate·p → δa · 클릭 → 내부</text>
  </g>
  <g class="blk" data-child="yaw" data-code="fcl/scas.py:ScasAxis" tabindex="0">
    <rect class="body" x="330" y="304" width="300" height="76" rx="3"/>
    <text class="ttl" x="480" y="336">요축 (ScasAxis + 워시아웃)</text>
    <text class="ttl2" x="480" y="360">−β PI + k_rate·washout(r) → δr · 클릭 → 내부</text>
  </g>
  <!-- 출력 포트 -->
  <path class="wire" d="M630 122 H806" marker-end="url(#aw-scas)"/>
  <g class="sblk" data-code="fcl/scas.py:Scas.step"><rect class="body" x="810" y="110" width="36" height="24" rx="12"/><text class="pnum" x="828" y="126">1</text></g>
  <text class="pname a-start" x="856" y="126">δe → 믹서</text>
  <path class="wire" d="M630 232 H806" marker-end="url(#aw-scas)"/>
  <g class="sblk" data-code="fcl/scas.py:Scas.step"><rect class="body" x="810" y="220" width="36" height="24" rx="12"/><text class="pnum" x="828" y="236">2</text></g>
  <text class="pname a-start" x="856" y="236">δa → 믹서</text>
  <path class="wire" d="M630 342 H806" marker-end="url(#aw-scas)"/>
  <g class="sblk" data-code="fcl/scas.py:Scas.step"><rect class="body" x="810" y="330" width="36" height="24" rx="12"/><text class="pnum" x="828" y="346">3</text></g>
  <text class="pname a-start" x="856" y="346">δr → 믹서</text>
  <text class="canvas-note" x="24" y="462">※ 축 블록 클릭 → 내부 진입 (시뮬링크 더블클릭 대응) · 축 공통 평탄형 구조 [확정 M7] — 캐스케이드 아님 · θ·φ·β·p·q·r는 NavOutput 추출 — 참값 차단 계약</text>
</svg>`,
    flow: {
      lead: "θ_cmd·φ_cmd + NavOutput → 축 셋이 나란히 → δe·δa·δr → 믹서",
      reads: [
        "명령이 두 갈래로 들어온다 — θ_cmd는 α 리미터를 거쳐(①), φ_cmd는 오토파일럿에서 곧장(②). 요축에는 명령이 없다.",
        "세 번째 입력은 <b>NavOutput 하나</b>다(③). 여기서 θ·φ·β와 p·q·r을 뽑아 축마다 갈라 보낸다 — 참값이 아니라 항법이 추정한 값이다.",
        "축 셋이 <b>나란히</b> 선다. 쌓인 것이 아니라 병렬이다: 피치는 θ·q, 롤은 φ·p, 요는 β·r만 본다.",
        "각 축이 타면각을 하나씩 내고(δe·δa·δr), 셋 다 믹서로 나간다.",
        "위쪽 점선 프레임은 게인 스케줄이다 — kp·ki·k_rate를 스텝마다 덮어쓴다. 신호가 아니라 값의 출처를 그린 것이다.",
      ],
      why: [
        "축이 병렬인 것은 <b>평탄형</b>이기 때문이다 — 자세→레이트 2단 캐스케이드가 아니다. 2단으로 쌓으면 루프가 하나 더 생겨 대역폭이 그만큼 깎이고, 축마다 두 벌을 튜닝해야 한다. 여기서는 축마다 한 벌이고 세 축을 따로 잡는다.",
        "오차를 만드는 합산점이 축 블록 <b>밖</b>(Scas.step)에 있다. 롤은 wrap ±π가 필요하고 요는 명령 자체가 없어서, 오차를 만드는 방식이 축마다 다르다 — 공통 축 컴포넌트 안에 넣을 수 없는 부분이다.",
        "세 축이 전부 NavOutput만 보는 것은 <b>참값 차단</b> 계약이다. 참 상태로 튜닝하면 항법 오차가 0인 세상에서 게인을 고르게 되고, 그 게인은 실기체에서 안 맞는다.",
      ],
    },
    notes: `
<h4>설계 노트</h4>
<ul>
  <li>축 공통 구조: <b>PI(자세오차) + k_rate·각속도</b>, 출력 클립 — 캐스케이드(자세→레이트 2단) 아닌 평탄형 <span class="chip ok">확정 M7</span> · 축 내부·PI 내부는 블록 클릭으로 진입</li>
  <li>안티와인드업: 적분항 클램프 <span class="chip dft">기본값 M7</span> · 이산화: 제어주기 100 Hz 시작(50 Hz 비교 예정), 계수 자동 계산 <span class="chip ok">확정</span> · 멀티레이트 입력 전제 <span class="chip note">설계 유의</span></li>
  <li>rate 항은 PI 클램프 <b>밖</b>에서 합산 → 축 출력은 최종 클립이 한 번 더 제한 · 재관여 시 적분 웜스타트 + 워시아웃 rate 시드 <span class="chip ok">범프리스 계약</span></li>
  <li>데모 설계점(M0.6·h1000·fuel200): 피치 kp −2.0 / ki −0.5 / k_rate 0.4 · 롤 1.0 / 0.1 / −0.2 · 요 kβ 0.5 / kr 0.8 · 게인 부호는 설계값(게인 테이블) 소관 — 코드는 공력 부호 무가정</li>
</ul>`,
    children: {
      pitch: {
        crumb: "피치축",
        title: "피치축 — ScasAxis", eng: "δe = clip( PI(θ_cmd − θ) + k_rate·q, out_lo~hi )",
        chips: ["ok", "dft"],
        svg: `
<svg viewBox="0 0 960 320" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-scp" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <g class="sblk" data-code="fcl/scas.py:Scas.step"><rect class="body" x="30" y="88" width="36" height="24" rx="12"/><text class="pnum" x="48" y="104">1</text></g>
  <text class="pname" x="48" y="132">θ_cmd ← α 리미터</text>
  <path class="wire" d="M66 100 H122" marker-end="url(#aw-scp)"/>
  <circle class="body" data-code="fcl/scas.py:Scas.step" cx="140" cy="100" r="14"/>
  <text class="sumsign" x="131" y="104">+</text><text class="sumsign" x="140" y="113">−</text>
  <path class="wire" d="M154 100 H186" marker-end="url(#aw-scp)"/>
  <g class="blk" data-child="pi" data-code="blocks/controllers.py:PID" tabindex="0">
    <rect class="body" x="190" y="64" width="190" height="72" rx="3"/>
    <text class="ttl" x="285" y="94" style="font-size:14px">PI — 클램프 AW</text>
    <text class="ttl2" x="285" y="116">적분 한계 out_lo~hi · 클릭 → 내부</text>
  </g>
  <path class="wire" d="M380 100 H412" marker-end="url(#aw-scp)"/>
  <circle class="body" data-code="fcl/scas.py:ScasAxis.step" cx="430" cy="100" r="14"/>
  <text class="sumsign" x="421" y="104">+</text><text class="sumsign" x="430" y="113">+</text>
  <path class="wire" d="M444 100 H476" marker-end="url(#aw-scp)"/>
  <g class="sblk" data-code="fcl/scas.py:ScasAxis.step"><rect class="body" x="480" y="74" width="110" height="52" rx="3"/>
    <path d="M492 116 H508 L562 84 H578" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="535" y="144">최종 클립 out_lo~hi</text>
  <path class="wire" d="M590 100 H806" marker-end="url(#aw-scp)"/>
  <g class="sblk" data-code="fcl/scas.py:ScasAxis.step"><rect class="body" x="810" y="88" width="36" height="24" rx="12"/><text class="pnum" x="828" y="104">1</text></g>
  <text class="pname" x="828" y="132">δe → 믹서</text>
  <g class="sblk" data-code="fcl/scas.py:Scas.step"><rect class="body" x="122" y="170" width="36" height="24" rx="12"/><text class="pnum" x="140" y="186">2</text></g>
  <text class="pname a-start" x="164" y="186">θ (NavOutput)</text>
  <path class="wire" d="M140 170 V118" marker-end="url(#aw-scp)"/>
  <g class="sblk" data-code="fcl/scas.py:ScasAxis.step"><polygon class="body" points="398,198 462,198 430,154"/>
    <text class="ttl2" x="430" y="190" style="font-weight:700" data-gain="k_rate">k_rate</text></g>
  <path class="wire" d="M430 154 V118" marker-end="url(#aw-scp)"/>
  <g class="sblk" data-code="fcl/scas.py:ScasAxis.step"><rect class="body" x="412" y="212" width="36" height="24" rx="12"/><text class="pnum" x="430" y="228">3</text></g>
  <text class="pname a-start" x="454" y="228">q (NavOutput)</text>
  <path class="wire" d="M430 212 V200" marker-end="url(#aw-scp)"/>
  <rect x="640" y="180" width="292" height="56" rx="8" fill="none" stroke="#8a5cf6" stroke-width="1.4" stroke-dasharray="6 4"/>
  <text class="annot" x="786" y="204" text-anchor="middle">게인 스케줄링 주입 — kp·ki·k_rate</text>
  <text class="annot" x="786" y="224" text-anchor="middle">스텝별 덮어쓰기 (정본 = 게인 탭)</text>
  <text class="canvas-note" x="24" y="296">※ rate 항은 PI 클램프 밖 합산 — 최종 클립이 한 번 더 제한 · 재관여 시 적분 웜스타트 [범프리스 계약] · PI 블록 클릭 → 내부 (층4)</text>
</svg>`,
        flow: {
          lead: "θ_cmd − θ → PI → + k_rate·q → 클립 → δe",
          reads: [
            "α 리미터를 거친 θ_cmd가 ①로 들어온다.",
            "항법이 준 θ(②)를 빼서 자세 오차를 만든다 — +/− 부호가 붙은 합산점이 그 자리다.",
            "오차는 PI로 간다. 비례·적분·클램프가 들어 있는 안쪽은 블록을 클릭하면 열린다.",
            "각속도 q(③)는 <b>PI를 거치지 않고</b> k_rate 삼각형만 지나 곧장 합산점으로 온다.",
            "둘을 더한 값을 out_lo~out_hi로 자른 것이 δe이고, 믹서로 나간다.",
          ],
          why: [
            "k_rate가 PI 밖으로 빠져 있는 이유: 감쇠는 오차가 아니라 <b>움직이는 속도</b>에 대한 반작용이라 적분되면 안 된다. PI 안에 넣으면 항법 각속도 잡음이 적분기에 그대로 쌓인다.",
            "그래서 클립이 두 번 나온다 — PI 안의 적분 클램프와 합산 뒤의 최종 클립. 앞의 것은 와인드업을, 뒤의 것은 타면 한계를 지킨다. 하나로 합치면 rate 항이 커졌을 때 적분기가 대신 잘려 나간다.",
            "명령이 리미터를 거쳐 오는 것도 이 그림의 전제다. θ_cmd를 그대로 믿으면 실속각을 넘는 자세도 충실히 따라간다.",
          ],
        },
        notes: `
<h4>설계 노트</h4>
<ul>
  <li><span class="mono">δe = clip( PI(θ_cmd − θ) + k_rate·q, out_lo~hi )</span> — 명령은 α 리미터를 거친 θ_cmd <span class="chip ok">확정 M7</span></li>
  <li>데모 설계값: kp −2.0 · ki −0.5 · k_rate 0.4 (설계점 M0.6·h1000·fuel200) — 동압 스케일 1D mach 스케줄 적용 <span class="chip dft">기본값</span></li>
  <li>PI 내부(비례·적분기 클램프 AW·출력 클립)는 PI 블록 클릭 — 층4</li>
</ul>`,
        children: { pi: SCAS_PI_PAGE },
      },
      roll: {
        crumb: "롤축",
        title: "롤축 — ScasAxis", eng: "δa = clip( PI(wrap(φ_cmd − φ)) + k_rate·p, out_lo~hi )",
        chips: ["ok", "dft"],
        svg: `
<svg viewBox="0 0 960 320" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-scr" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <g class="sblk" data-code="fcl/scas.py:Scas.step"><rect class="body" x="30" y="88" width="36" height="24" rx="12"/><text class="pnum" x="48" y="104">1</text></g>
  <text class="pname" x="48" y="132">φ_cmd ← AP</text>
  <path class="wire" d="M66 100 H122" marker-end="url(#aw-scr)"/>
  <circle class="body" data-code="fcl/scas.py:Scas.step" cx="140" cy="100" r="14"/>
  <text class="sumsign" x="131" y="104">+</text><text class="sumsign" x="140" y="113">−</text>
  <text class="siglabel" x="140" y="72">wrap ±π</text>
  <path class="wire" d="M154 100 H186" marker-end="url(#aw-scr)"/>
  <g class="blk" data-child="pi" data-code="blocks/controllers.py:PID" tabindex="0">
    <rect class="body" x="190" y="64" width="190" height="72" rx="3"/>
    <text class="ttl" x="285" y="94" style="font-size:14px">PI — 클램프 AW</text>
    <text class="ttl2" x="285" y="116">적분 한계 out_lo~hi · 클릭 → 내부</text>
  </g>
  <path class="wire" d="M380 100 H412" marker-end="url(#aw-scr)"/>
  <circle class="body" data-code="fcl/scas.py:ScasAxis.step" cx="430" cy="100" r="14"/>
  <text class="sumsign" x="421" y="104">+</text><text class="sumsign" x="430" y="113">+</text>
  <path class="wire" d="M444 100 H476" marker-end="url(#aw-scr)"/>
  <g class="sblk" data-code="fcl/scas.py:ScasAxis.step"><rect class="body" x="480" y="74" width="110" height="52" rx="3"/>
    <path d="M492 116 H508 L562 84 H578" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="535" y="144">최종 클립 out_lo~hi</text>
  <path class="wire" d="M590 100 H806" marker-end="url(#aw-scr)"/>
  <g class="sblk" data-code="fcl/scas.py:ScasAxis.step"><rect class="body" x="810" y="88" width="36" height="24" rx="12"/><text class="pnum" x="828" y="104">1</text></g>
  <text class="pname" x="828" y="132">δa → 믹서</text>
  <g class="sblk" data-code="fcl/scas.py:Scas.step"><rect class="body" x="122" y="170" width="36" height="24" rx="12"/><text class="pnum" x="140" y="186">2</text></g>
  <text class="pname a-start" x="164" y="186">φ (NavOutput)</text>
  <path class="wire" d="M140 170 V118" marker-end="url(#aw-scr)"/>
  <g class="sblk" data-code="fcl/scas.py:ScasAxis.step"><polygon class="body" points="398,198 462,198 430,154"/>
    <text class="ttl2" x="430" y="190" style="font-weight:700" data-gain="k_rate">k_rate</text></g>
  <path class="wire" d="M430 154 V118" marker-end="url(#aw-scr)"/>
  <g class="sblk" data-code="fcl/scas.py:ScasAxis.step"><rect class="body" x="412" y="212" width="36" height="24" rx="12"/><text class="pnum" x="430" y="228">3</text></g>
  <text class="pname a-start" x="454" y="228">p (NavOutput)</text>
  <path class="wire" d="M430 212 V200" marker-end="url(#aw-scr)"/>
  <rect x="640" y="180" width="292" height="56" rx="8" fill="none" stroke="#8a5cf6" stroke-width="1.4" stroke-dasharray="6 4"/>
  <text class="annot" x="786" y="204" text-anchor="middle">게인 스케줄링 주입 — kp·ki·k_rate</text>
  <text class="annot" x="786" y="224" text-anchor="middle">스텝별 덮어쓰기 (정본 = 게인 탭)</text>
  <text class="canvas-note" x="24" y="296">※ 롤 오차는 wrap ±π — 배면 통과 시 2π 점프 방지 · rate 항은 PI 클램프 밖 합산 · 재관여 시 적분 웜스타트 [범프리스 계약]</text>
</svg>`,
        flow: {
          lead: "wrap(φ_cmd − φ) → PI → + k_rate·p → 클립 → δa",
          reads: [
            "오토파일럿이 준 φ_cmd가 ①로 들어온다.",
            "항법의 φ(②)를 빼는데, 그 결과에 <b>wrap ±π</b>가 걸린다 — 피치축에 없는 한 단계다.",
            "wrap된 오차가 PI로 가고, 롤레이트 p(③)는 k_rate를 지나 따로 합산점으로 온다.",
            "합을 out_lo~out_hi로 자른 것이 δa이고, 믹서로 나간다.",
          ],
          why: [
            "wrap이 없으면 배면을 지날 때 오차가 뒤집힌다. φ가 179°에서 −179°로 넘어가는 순간 뺄셈은 358°를 내놓고, 제어는 <b>가까운 2°가 아니라 먼 358°</b>를 따라 반대로 친다. 각도를 다루는 루프에서만 생기는 문제라 피치축에는 이 단계가 없다.",
            "나머지 골격이 피치와 같은 것은 우연이 아니다 — 같은 ScasAxis 컴포넌트다. 축마다 다른 것은 무엇을 빼서 오차를 만드느냐와 게인 값뿐이다.",
          ],
        },
        notes: `
<h4>설계 노트</h4>
<ul>
  <li><span class="mono">δa = clip( PI(wrap(φ_cmd − φ)) + k_rate·p, out_lo~hi )</span> — 오차 <b>wrap ±π</b>로 배면 통과 시 2π 점프 방지 <span class="chip ok">확정 M7</span></li>
  <li>데모 설계값: kp 1.0 · ki 0.1 · k_rate −0.2 (δa 부호 관례상 음수가 정상 판독) <span class="chip dft">기본값</span></li>
  <li>PI 내부는 PI 블록 클릭 — 층4</li>
</ul>`,
        children: { pi: SCAS_PI_PAGE },
      },
      yaw: {
        crumb: "요축",
        title: "요축 — ScasAxis + 워시아웃", eng: "δr = clip( PI(−β) + k_rate·washout(r), out_lo~hi ) — 선회조화",
        chips: ["ok", "dft"],
        svg: `
<svg viewBox="0 0 960 360" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-scy" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <g class="sblk" data-code="fcl/scas.py:Scas.step"><rect class="body" x="30" y="88" width="36" height="24" rx="12"/><text class="pnum" x="48" y="104">1</text></g>
  <text class="pname" x="48" y="132">β (사이드슬립)</text>
  <path class="wire" d="M66 100 H96" marker-end="url(#aw-scy)"/>
  <g class="sblk" data-code="fcl/scas.py:Scas.step"><polygon class="body" points="100,76 100,124 166,100"/>
    <text class="ttl2" x="122" y="104" style="font-weight:700">−1</text></g>
  <text class="bname" x="130" y="142">명령 없음</text>
  <path class="wire" d="M166 100 H186" marker-end="url(#aw-scy)"/>
  <g class="blk" data-child="pi" data-code="blocks/controllers.py:PID" tabindex="0">
    <rect class="body" x="190" y="64" width="190" height="72" rx="3"/>
    <text class="ttl" x="285" y="94" style="font-size:14px">PI — 클램프 AW</text>
    <text class="ttl2" x="285" y="116">적분 한계 out_lo~hi · 클릭 → 내부</text>
  </g>
  <path class="wire" d="M380 100 H412" marker-end="url(#aw-scy)"/>
  <circle class="body" data-code="fcl/scas.py:ScasAxis.step" cx="430" cy="100" r="14"/>
  <text class="sumsign" x="421" y="104">+</text><text class="sumsign" x="430" y="113">+</text>
  <path class="wire" d="M444 100 H476" marker-end="url(#aw-scy)"/>
  <g class="sblk" data-code="fcl/scas.py:ScasAxis.step"><rect class="body" x="480" y="74" width="110" height="52" rx="3"/>
    <path d="M492 116 H508 L562 84 H578" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="535" y="144">최종 클립 out_lo~hi</text>
  <path class="wire" d="M590 100 H806" marker-end="url(#aw-scy)"/>
  <g class="sblk" data-code="fcl/scas.py:ScasAxis.step"><rect class="body" x="810" y="88" width="36" height="24" rx="12"/><text class="pnum" x="828" y="104">1</text></g>
  <text class="pname" x="828" y="132">δr → 믹서</text>
  <g class="sblk" data-code="fcl/scas.py:ScasAxis.step"><rect class="body" x="30" y="196" width="36" height="24" rx="12"/><text class="pnum" x="48" y="212">2</text></g>
  <text class="pname" x="48" y="240">r (NavOutput)</text>
  <path class="wire" d="M66 208 H96" marker-end="url(#aw-scy)"/>
  <g class="sblk" data-code="blocks/filters.py:Washout"><rect class="body" x="100" y="182" width="170" height="52" rx="3"/>
    <text class="ttl" x="185" y="204" style="font-size:13px" data-gain="washout_tau">워시아웃 τs/(τs+1)</text>
    <text class="ttl2" x="185" y="222">정상 r 제거 — 선회 유지</text></g>
  <path class="wire" d="M270 208 H298" marker-end="url(#aw-scy)"/>
  <g class="sblk" data-code="fcl/scas.py:ScasAxis.step"><polygon class="body" points="302,188 302,228 368,208"/></g>
  <text class="bname" x="334" y="248" data-gain="k_rate">k_rate</text>
  <path class="wire" d="M368 208 H430 V118" marker-end="url(#aw-scy)"/>
  <rect x="640" y="180" width="292" height="56" rx="8" fill="none" stroke="#8a5cf6" stroke-width="1.4" stroke-dasharray="6 4"/>
  <text class="annot" x="786" y="204" text-anchor="middle">게인 스케줄링 주입 — kp·ki·k_rate</text>
  <text class="annot" x="786" y="224" text-anchor="middle">스텝별 덮어쓰기 (정본 = 게인 탭)</text>
  <text class="canvas-note" x="24" y="336">※ 요축은 자세 명령 없음 — 선회조화(β 억제) · 워시아웃이 지속 선회의 정상 r 제거 → 선회 유지 · 재관여 시 워시아웃 rate 시드 — k_rate·r 킥 방지 [범프리스]</text>
</svg>`,
        flow: {
          lead: "−β → PI → + k_rate·washout(r) → 클립 → δr",
          reads: [
            "입력이 β(사이드슬립) 하나다(①). <b>자세 명령이 없다</b> — 요축은 어디를 향하라가 아니라 옆으로 미끄러지지 마라만 한다.",
            "−1 삼각형에서 부호를 뒤집는다. β를 0으로 끌고 가는 방향으로 러더를 치기 위해서다 (게인이 아니라 부호 반전기다).",
            "그 값이 PI로 간다.",
            "요레이트 r(②)은 곧장 오지 않고 <b>워시아웃 τs/(τs+1)</b>을 먼저 지난다 — 지속하는 회전은 걸러지고 변화만 남는다.",
            "걸러진 r에 k_rate를 곱해 합산하고, 클립한 것이 δr이다.",
          ],
          why: [
            "워시아웃이 감쇠 경로에만 있는 것이 이 그림의 핵심이다. 필터가 없으면 지속 선회의 정상 요레이트를 재워야 할 흔들림으로 오인해, <b>러더가 선회를 방해한다</b> — 사이드슬립이 남고 선회 반경이 커진다. β 경로에는 필터가 없다: 사이드슬립은 지속하든 아니든 없애야 한다.",
            "명령이 없는 이유는 헤딩을 오토파일럿이 <b>뱅크로</b> 만들기 때문이다(선회조화). 요축이 헤딩을 직접 잡으려 들면 두 채널이 같은 일을 두고 다툰다.",
            "워시아웃은 상태를 갖는 필터라 재관여할 때 rate 시드가 필요하다 — 없으면 첫 스텝에 k_rate·r 킥이 나간다.",
          ],
        },
        notes: `
<h4>설계 노트</h4>
<ul>
  <li><span class="mono">δr = clip( PI(−β) + k_rate·washout(r), out_lo~hi )</span> — 자세 명령 없음, β 억제(선회조화) <span class="chip ok">확정 M7</span></li>
  <li><b>워시아웃</b> τs/(τs+1)이 지속 선회의 정상 요레이트를 제거 — 선회 유지 <span class="chip ok">확정</span> · τ = 2 s <span class="chip dft">기본값</span> (washout_tau=0이면 생략)</li>
  <li>데모 설계값: kβ 0.5 · kr 0.8 · 러더는 믹서에서 차동추력 보상과 결합</li>
  <li>PI 내부는 PI 블록 클릭 — 층4</li>
</ul>`,
        children: { pi: SCAS_PI_PAGE },
      },
    },
  },


  // ── 오토파일럿 — 외측 루프 (설계 ③) ──────────────────────────────────
  autopilot: {
    tag: "설계 ③", tagBg: "#1f7a4d",
    title: "오토파일럿 — 외측 루프", eng: "Autopilot / Outer Loop — 채널별 PI + 명령필터",
    chips: ["ok", "dft"],
    svg: `
<svg viewBox="0 0 960 480" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-ap" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <!-- 게인 스케줄 주입 (공통) — 주석 프레임 -->
  <rect x="620" y="16" width="312" height="56" rx="8" fill="none" stroke="#8a5cf6" stroke-width="1.4" stroke-dasharray="6 4"/>
  <text class="annot" x="776" y="38" text-anchor="middle">게인 스케줄링 주입 — speed·alt·heading 그룹</text>
  <text class="annot" x="776" y="58" text-anchor="middle">kp·ki 스텝별 덮어쓰기 (정본 = 게인 탭)</text>
  <!-- 입력 포트 (헤딩이 위 — φ_cmd를 선회 FF가 소비) -->
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="30" y="110" width="36" height="24" rx="12"/><text class="pnum" x="48" y="126">3</text></g>
  <text class="pname" x="48" y="154">ψ_cmd ← 유도</text>
  <path class="wire" d="M66 122 H326" marker-end="url(#aw-ap)"/>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="30" y="220" width="36" height="24" rx="12"/><text class="pnum" x="48" y="236">2</text></g>
  <text class="pname" x="48" y="264">h_cmd ← 유도</text>
  <path class="wire" d="M66 232 H326" marker-end="url(#aw-ap)"/>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="30" y="330" width="36" height="24" rx="12"/><text class="pnum" x="48" y="346">1</text></g>
  <text class="pname" x="48" y="374">V_cmd ← 유도</text>
  <path class="wire" d="M66 342 H326" marker-end="url(#aw-ap)"/>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="30" y="398" width="36" height="24" rx="12"/><text class="pnum" x="48" y="414">4</text></g>
  <text class="pname a-start" x="30" y="446">NavOutput (ψ · h·ḣ · V)</text>
  <path class="wire" d="M66 410 H120 V146 H326" marker-end="url(#aw-ap)"/>
  <circle class="branch" cx="120" cy="366" r="3.2"/>
  <path class="wire" d="M120 366 H326" marker-end="url(#aw-ap)"/>
  <circle class="branch" cx="120" cy="256" r="3.2"/>
  <path class="wire" d="M120 256 H326" marker-end="url(#aw-ap)"/>
  <text class="siglabel" x="302" y="140">ψ</text>
  <text class="siglabel" x="302" y="250">h·ḣ</text>
  <text class="siglabel" x="302" y="360">V</text>
  <!-- 채널 서브시스템 블록 (클릭 → 층3) -->
  <g class="blk" data-child="hdg" data-code="fcl/autopilot.py:Autopilot.step" tabindex="0">
    <rect class="body" x="330" y="84" width="300" height="76" rx="3"/>
    <text class="ttl" x="480" y="116">헤딩 채널</text>
    <text class="ttl2" x="480" y="140">필터 wrap τ <tspan data-p="tau_hdg">1</tspan> s · PI · 클립 ±phi_max · 클릭 → 내부</text>
  </g>
  <g class="blk" data-child="alt" data-code="fcl/autopilot.py:Autopilot.step" tabindex="0">
    <rect class="body" x="330" y="194" width="300" height="76" rx="3"/>
    <text class="ttl" x="480" y="226">고도 채널</text>
    <text class="ttl2" x="480" y="250">필터 τ <tspan data-p="tau_alt">5</tspan> s · PI + k_hdot·ḣ · θ 클립 · 클릭 → 내부</text>
  </g>
  <g class="blk" data-child="spd" data-code="fcl/autopilot.py:Autopilot.step" tabindex="0">
    <rect class="body" x="330" y="304" width="300" height="76" rx="3"/>
    <text class="ttl" x="480" y="336">속도 채널</text>
    <text class="ttl2" x="480" y="360">필터 τ <tspan data-p="tau_spd">2</tspan> s · PI · 0~1 클립 · 클릭 → 내부</text>
  </g>
  <!-- 출력 포트 -->
  <path class="wire" d="M630 122 H806" marker-end="url(#aw-ap)"/>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="810" y="110" width="36" height="24" rx="12"/><text class="pnum" x="828" y="126">2</text></g>
  <text class="pname a-start" x="856" y="126">φ_cmd → SCAS 롤</text>
  <path class="wire" d="M630 232 H806" marker-end="url(#aw-ap)"/>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="810" y="220" width="36" height="24" rx="12"/><text class="pnum" x="828" y="236">1</text></g>
  <text class="pname a-start" x="856" y="236">θ_cmd → α 리미터</text>
  <path class="wire" d="M630 342 H806" marker-end="url(#aw-ap)"/>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="810" y="330" width="36" height="24" rx="12"/><text class="pnum" x="828" y="346">3</text></g>
  <text class="pname a-start" x="856" y="346">δt_cmd (0~1)</text>
  <!-- 선회 FF — 주석 프레임 (실 배선·재클립은 채널 내부, 층3) -->
  <rect x="330" y="400" width="600" height="44" rx="8" fill="none" stroke="#b45309" stroke-width="1.4" stroke-dasharray="6 4"/>
  <text class="annot" x="630" y="427" text-anchor="middle" fill="#b45309">선회 피드포워드 — |φ_cmd| 분기 → 고도(θ)·속도(δt) 채널 내부 가산 · 상세는 채널 클릭</text>
  <text class="canvas-note" x="24" y="470">※ 채널 블록 클릭 → 내부 진입 (시뮬링크 더블클릭 대응) · 전 채널이 SCAS와 동일한 ScasAxis 재사용 (PI 클램프 AW) · V·h·ḣ·ψ는 NavOutput 추출 — 참값 차단 계약</text>
</svg>`,
    flow: {
      lead: "V·h·ψ 명령 + NavOutput → 채널 셋 → δt_cmd · θ_cmd · φ_cmd",
      reads: [
        "유도가 준 명령 셋이 들어온다 — V_cmd(①)·h_cmd(②)·ψ_cmd(③). 넷째 입력은 NavOutput 하나(④)로, 여기서 V·h·ḣ·ψ를 뽑아 채널마다 갈라 보낸다.",
        "채널 셋이 나란히 선다. 서로 신호를 주고받지 않는다 — 속도는 V만, 고도는 h·ḣ만, 헤딩은 ψ만 본다.",
        "채널 셋의 골격이 같다: <b>명령필터(τ) → 오차 → PI → 클립</b>. 안쪽은 블록을 클릭하면 열린다.",
        "나가는 것은 타면이 아니라 <b>자세·스로틀 명령</b>이다: 헤딩 → φ_cmd(SCAS 롤로), 고도 → θ_cmd(α 리미터를 거쳐), 속도 → δt_cmd.",
        "채널을 <b>가로지르는</b> 선이 하나 있다 — 헤딩이 만든 φ_cmd가 고도·속도 채널 안으로 들어가 선회 피드포워드로 가산된다. 아래 점선 프레임이 그 경로다.",
      ],
      why: [
        "세 채널을 독립으로 두고 <b>실제로 섞이는 한 곳만</b> 피드포워드로 잇는다. 뱅크를 걸면 양력의 수직 성분이 cosφ로 줄어 고도가 떨어지는데, 이걸 고도 루프의 피드백에 맡기면 <b>이미 떨어진 뒤에야</b> 반응한다. 선회 FF는 그 강하를 미리 상쇄한다 — 되먹임으로는 늦는 자리라 앞먹임이다.",
        "명령필터가 채널마다 맨 앞에 있는 이유: 유도의 명령은 웨이포인트가 바뀌는 순간 <b>계단으로</b> 튄다. 그대로 PI에 넣으면 첫 스텝에 큰 명령이 나가 타면이 포화한다. τ가 그 계단을 경사로 바꾼다.",
        "출력이 전부 SCAS를 거친다 — 오토파일럿은 타면을 직접 치지 않는다. 자세를 <b>부탁</b>하고, 자세를 만드는 일은 안쪽 루프가 한다. 그래서 SCAS가 흔들리면 여기 게인은 의미가 없다. 설계 순서가 안쪽부터인 이유가 이 그림에 있다.",
      ],
    },
    notes: `
<h4>설계 노트</h4>
<ul>
  <li>속도 / 고도 / 헤딩 <b>독립 PI 채널</b> — 고도→θ_cmd, 속도→δt_cmd, 헤딩→φ_cmd <span class="chip ok">확정</span> · 전 채널이 SCAS와 동일한 <b>ScasAxis</b>(PI 클램프 AW + 출력 클립) 재사용</li>
  <li>명령 경로 <b>1차 명령필터</b> — 급명령의 타면 포화·과도 하중 방지 · 첫 스텝 현재 측정 시드(캡처) · 헤딩 필터는 wrap 최단경로 보간 · τ 속도 2 · 고도 5 · 헤딩 1 s <span class="chip dft">기본값 M7</span></li>
  <li>비활성 축: 필터는 측정 추적(reset_to) — 활성화 순간 현재값부터 램프 · 오차 0 적분 → <b>트림 홀드</b> · 헤딩 off는 적분 소거 + φ_cmd=0 (재관여 시 잔존 뱅크 킥 방지)</li>
  <li>선회 <b>피드포워드 보상</b>(델타윙 유도항력) — θ += k_pitch_turn·(1/cosφ−1), δt += k_thr_turn·(1/cos²φ−1) · 축 클립 후 합산 → 재클립 (이중 제한) · 데모 튜닝: 피치 0.05, 스로틀 0(역효과) <span class="chip dft">기본값</span></li>
  <li>피치 명령은 θ 한계 클립 후 <b>α 리미터</b>를 거쳐 SCAS로 · 뱅크는 ±phi_max — π/2 미만 강제 (선회 FF 부호 보전 가드) · 요축 별도 출력 없음 (요 안정화는 SCAS, 차동추력은 믹서)</li>
  <li>트림 웜스타트: 속도 적분기 = 트림 스로틀 · 고도 적분기 = 트림 θ <span class="chip ok">범프리스 계약</span> · 게인은 게인 스케줄링 적용 대상 · 이 페이지 폼 편집 → 시뮬 주입 가능</li>
  <li>데모 설계점 성능 (M0.6 h1000 fuel200 폐루프 스캔): 고도 +100 m 오버슈트 8.3% · 속도 +10 m/s 3.7% · 헤딩 0.5 rad 무오버슈트·고도 강하 1.1 m <span class="chip dft">기본값</span></li>
  <li>채널 내부(필터·PI·클립·FF 합류)는 채널 블록 클릭 — 층3 <span class="chip ok">확정</span></li>
</ul>`,
    children: {
      hdg: {
        crumb: "헤딩 채널",
        title: "헤딩 채널", eng: "φ_cmd = clip( PI(wrap(ψ_ref − ψ)), ±phi_max ) — ScasAxis 재사용",
        chips: ["ok", "dft"],
        svg: `
<svg viewBox="0 0 960 300" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="aw-aph" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker>
    <marker id="af-aph" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#b45309"/></marker>
  </defs>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="30" y="88" width="36" height="24" rx="12"/><text class="pnum" x="48" y="104">1</text></g>
  <text class="pname" x="48" y="132">ψ_cmd ← 유도</text>
  <path class="wire" d="M66 100 H96" marker-end="url(#aw-aph)"/>
  <g class="sblk" data-code="blocks/filters.py:CommandFilter"><rect class="body" x="100" y="74" width="118" height="52" rx="3"/>
    <text class="ttl" x="159" y="93" style="font-size:13px">명령필터 wrap</text>
    <text class="ttl2" x="159" y="111">τ <tspan data-p="tau_hdg">1</tspan> s · 최단경로</text></g>
  <text class="siglabel" x="159" y="144">off: ψ 추적 · 적분 소거 · φ_cmd=0</text>
  <path class="wire" d="M218 100 H240" marker-end="url(#aw-aph)"/>
  <circle class="body" data-code="fcl/autopilot.py:Autopilot.step" cx="258" cy="100" r="14"/>
  <text class="sumsign" x="249" y="104">+</text><text class="sumsign" x="258" y="113">−</text>
  <text class="siglabel" x="258" y="70">wrap ±π</text>
  <path class="wire" d="M272 100 H296" marker-end="url(#aw-aph)"/>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="300" y="74" width="150" height="52" rx="3"/>
    <text class="ttl" x="375" y="93" style="font-size:13px">헤딩 PI — 클램프 AW</text>
    <text class="ttl2" x="375" y="111">kp <tspan data-p="kp_hdg">4</tspan> · ki <tspan data-p="ki_hdg">0</tspan></text></g>
  <path class="wire" d="M450 100 H478" marker-end="url(#aw-aph)"/>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="482" y="74" width="96" height="52" rx="3"/>
    <path d="M492 116 H506 L554 84 H568" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="530" y="144">클립 ±<tspan data-p="phi_max">0.7</tspan> rad</text>
  <path class="wire" d="M578 100 H806" marker-end="url(#aw-aph)"/>
  <circle class="branch" cx="640" cy="100" r="3.2"/>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="810" y="88" width="36" height="24" rx="12"/><text class="pnum" x="828" y="104">1</text></g>
  <text class="pname" x="828" y="132">φ_cmd → SCAS 롤</text>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="240" y="158" width="36" height="24" rx="12"/><text class="pnum" x="258" y="174">2</text></g>
  <text class="pname a-start" x="282" y="174">ψ (NavOutput)</text>
  <path class="wire" d="M258 158 V118" marker-end="url(#aw-aph)"/>
  <path class="wire ff" d="M640 100 V180" marker-end="url(#af-aph)"/>
  <text class="siglabel" x="640" y="200">→ 선회 FF (고도·속도 채널 가산)</text>
  <text class="canvas-note" x="24" y="272">※ 비활성(off) 시 필터는 ψ 추적 + 적분 소거 + φ_cmd=0 — 재관여 시 잔존 뱅크 킥 방지 · ±phi_max는 π/2 미만 강제 (선회 FF 부호 보전 가드)</text>
</svg>`,
        flow: {
          lead: "ψ_cmd → 필터(wrap) → 오차 wrap → PI → 클립 ±phi_max → φ_cmd",
          reads: [
            "유도가 준 ψ_cmd가 ①로 들어와 명령필터(τ 1 s)를 지난다. 이 필터도 wrap을 안다 — <b>최단경로로</b> 보간한다.",
            "항법의 ψ(②)를 빼고, 그 오차에 다시 wrap ±π를 건다.",
            "PI를 지난다 (데모는 kp 4 · ki 0).",
            "±phi_max로 클립한 것이 φ_cmd이고, SCAS 롤축으로 간다.",
            "같은 φ_cmd가 옆으로 갈라져 고도·속도 채널의 <b>선회 FF 입력</b>이 된다 — 이 채널이 다른 두 채널을 건드리는 유일한 경로다.",
          ],
          why: [
            "헤딩을 러더가 아니라 <b>뱅크로</b> 잡는다. 비행기는 기울여서 도는 것이지 옆으로 미끄러뜨려 도는 것이 아니다 — 러더로 돌리면 사이드슬립이 남고 항력이 는다. 그래서 이 채널의 출력이 δr이 아니라 φ_cmd다.",
            "wrap이 필터와 오차 <b>양쪽에</b> 걸려 있다. 한쪽만 걸면 359° → 1° 명령에서 필터가 먼 길로 358°를 돌아간다.",
            "±phi_max가 π/2 미만으로 강제되는 이유는 선회 FF에 있다: 보상식이 1/cosφ라 φ가 90°에 닿으면 발산한다. 이 클립이 그 앞을 막는 가드다.",
            "데모가 ki 0인 것은 값의 선택이지 구조의 결함이 아니다 — 설계점 폐루프 스캔에서 헤딩 0.5 rad 스텝이 무오버슈트였다.",
          ],
        },
        notes: `
<h4>설계 노트</h4>
<ul>
  <li><span class="mono">φ_cmd = clip( PI(wrap(ψ_ref − ψ)), ±phi_max )</span> — 오차·명령필터 모두 wrap 최단경로 <span class="chip ok">확정 M7</span></li>
  <li>φ_cmd 분기가 <b>선회 피드포워드</b> 입력 — 고도(θ)·속도(δt) 채널 내부에서 가산 <span class="chip note">설계 유의</span></li>
  <li>데모 설계값: kp 4 · ki 0 · τ 1 s · phi_max 0.7 rad <span class="chip dft">기본값</span> · 헤딩 0.5 rad 스텝 무오버슈트 (설계점 폐루프 스캔)</li>
</ul>`,
      },
      alt: {
        crumb: "고도 채널",
        title: "고도 채널", eng: "θ_cmd = 재클립( clip(PI(h_ref−h) + k_hdot·ḣ) + 선회 FF )",
        chips: ["ok", "dft"],
        svg: `
<svg viewBox="0 0 960 330" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="aw-apa" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker>
    <marker id="af-apa" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#b45309"/></marker>
  </defs>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="30" y="88" width="36" height="24" rx="12"/><text class="pnum" x="48" y="104">1</text></g>
  <text class="pname" x="48" y="132">h_cmd ← 유도</text>
  <path class="wire" d="M66 100 H96" marker-end="url(#aw-apa)"/>
  <g class="sblk" data-code="blocks/filters.py:CommandFilter"><rect class="body" x="100" y="74" width="118" height="52" rx="3"/>
    <text class="ttl" x="159" y="93" style="font-size:13px">명령필터</text>
    <text class="ttl2" x="159" y="111">τ <tspan data-p="tau_alt">5</tspan> s</text></g>
  <text class="siglabel" x="159" y="144">off: h 추적 — 활성화 시 램프</text>
  <path class="wire" d="M218 100 H240" marker-end="url(#aw-apa)"/>
  <circle class="body" data-code="fcl/autopilot.py:Autopilot.step" cx="258" cy="100" r="14"/>
  <text class="sumsign" x="249" y="104">+</text><text class="sumsign" x="258" y="113">−</text>
  <path class="wire" d="M272 100 H296" marker-end="url(#aw-apa)"/>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="300" y="74" width="140" height="52" rx="3"/>
    <text class="ttl" x="370" y="93" style="font-size:13px">고도 PI — 클램프 AW</text>
    <text class="ttl2" x="370" y="111">kp <tspan data-p="kp_alt">0.004</tspan> · ki <tspan data-p="ki_alt">0.0004</tspan></text></g>
  <path class="wire" d="M440 100 H446" marker-end="url(#aw-apa)"/>
  <circle class="body" data-code="fcl/autopilot.py:Autopilot.step" cx="464" cy="100" r="14"/>
  <text class="sumsign" x="455" y="104">+</text><text class="sumsign" x="464" y="113">+</text>
  <path class="wire" d="M478 100 H492" marker-end="url(#aw-apa)"/>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="496" y="74" width="90" height="52" rx="3"/>
    <path d="M506 116 H518 L564 84 H576" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="541" y="64">클립 <tspan data-p="theta_lo">−0.3</tspan>~<tspan data-p="theta_hi">0.3</tspan> rad</text>
  <path class="wire" d="M586 100 H612" marker-end="url(#aw-apa)"/>
  <circle class="body" data-code="fcl/autopilot.py:Autopilot.step" cx="630" cy="100" r="14"/>
  <text class="sumsign" x="621" y="104">+</text><text class="sumsign" x="630" y="93">+</text>
  <path class="wire" d="M644 100 H700" marker-end="url(#aw-apa)"/>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="704" y="74" width="82" height="52" rx="3"/>
    <path d="M712 116 H724 L766 84 H778" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="745" y="64">재클립 θ 한계</text>
  <path class="wire" d="M786 100 H806" marker-end="url(#aw-apa)"/>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="810" y="88" width="36" height="24" rx="12"/><text class="pnum" x="828" y="104">1</text></g>
  <text class="pname" x="828" y="136">θ_cmd → α 리미터</text>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="240" y="162" width="36" height="24" rx="12"/><text class="pnum" x="258" y="178">2</text></g>
  <text class="pname a-start" x="282" y="178">h = −z_n</text>
  <path class="wire" d="M258 162 V118" marker-end="url(#aw-apa)"/>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><polygon class="body" points="426,192 502,192 464,152"/>
    <text class="ttl2" x="464" y="186" style="font-weight:700">k_hdot</text></g>
  <text class="bname" x="384" y="216"><tspan data-p="k_hdot">−0.008</tspan> · 승강률 댐핑</text>
  <path class="wire" d="M464 152 V118" marker-end="url(#aw-apa)"/>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="446" y="210" width="36" height="24" rx="12"/><text class="pnum" x="464" y="226">3</text></g>
  <text class="pname a-start" x="490" y="226">ḣ = −v_z</text>
  <path class="wire" d="M464 210 V196" marker-end="url(#aw-apa)"/>
  <path class="wire ff" d="M630 190 V118" marker-end="url(#af-apa)"/>
  <text class="siglabel" x="630" y="210">선회 FF 피치 — <tspan data-p="k_pitch_turn">0.05</tspan>·(1/cosφ−1)</text>
  <text class="canvas-note" x="24" y="300">※ 선회 FF는 축 클립 후 가산 → 재클립 (이중 제한) · 트림 웜스타트: 고도 적분기 = 트림 θ [범프리스] · 비활성 시 필터가 h 추적 — 활성화 순간 현재값부터 램프</text>
</svg>`,
        flow: {
          lead: "h_cmd → 필터 τ5 → 오차 → PI → + k_hdot·ḣ → 클립 → + 선회 FF → 재클립 → θ_cmd",
          reads: [
            "h_cmd가 ①로 들어와 명령필터를 지난다. τ 5 s — 세 채널 중 <b>가장 느리다</b>.",
            "항법의 h(②)를 빼서 오차를 만들고 PI로 보낸다.",
            "승강률 ḣ(③)는 PI를 거치지 않고 k_hdot을 지나 곧장 합산점으로 온다 — SCAS의 k_rate와 같은 자리다.",
            "합을 θ 한계(−0.3~0.3 rad)로 클립한다.",
            "그 뒤 헤딩 채널에서 온 <b>선회 FF가 더해지고, 다시 한 번</b> 클립한다.",
            "나온 θ_cmd는 α 리미터를 거쳐 SCAS 피치로 간다.",
          ],
          why: [
            "클립이 두 번인 것이 이 그림에서 볼 것이다. FF를 클립 <b>전에</b> 더하면 축 클립이 FF까지 먹어 선회 보상이 사라진다. 클립한 뒤에 더하고 다시 자르면 보상은 살고 한계는 지킨다.",
            "k_hdot이 PI 밖에 있는 이유는 SCAS의 k_rate와 같다 — 승강률은 오차가 아니라 <b>속도</b>라 적분되면 안 된다.",
            "τ가 5 s로 가장 느린 이유: 고도 명령의 계단은 곧 큰 θ 요구가 되고, θ는 받음각을 바꿔 <b>실속에 가장 가까이</b> 가는 축이다. 급하게 굴 이유가 없는 채널이다.",
            "데모 설계점에서 고도 +100 m 오버슈트 8.3% (폐루프 스캔).",
          ],
        },
        notes: `
<h4>설계 노트</h4>
<ul>
  <li><span class="mono">θ_cmd = 재클립( clip(PI(h_ref−h) + k_hdot·ḣ, θ한계) + FF, θ한계 )</span> — FF 가산 후 <b>재클립</b>으로 이중 제한 <span class="chip ok">확정 M7</span></li>
  <li>승강률 댐핑 k_hdot·ḣ — PI 클램프 <b>밖</b>·θ 클립 <b>안</b>(FF 가산 전)에서 합산 (SCAS의 k_rate 자리 재사용) · θ_cmd는 α 리미터를 거쳐 SCAS로</li>
  <li>데모 설계값: kp 0.004 · ki 0.0004 · k_hdot −0.008 · τ 5 s <span class="chip dft">기본값</span> · 고도 +100 m 오버슈트 8.3% (설계점 폐루프 스캔)</li>
</ul>`,
      },
      spd: {
        crumb: "속도 채널",
        title: "속도 채널", eng: "δt_cmd = 재클립( clip(PI(V_ref−V), 0~1) + 선회 FF, 0~1 )",
        chips: ["ok", "dft"],
        svg: `
<svg viewBox="0 0 960 300" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="aw-aps" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker>
    <marker id="af-aps" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#b45309"/></marker>
  </defs>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="30" y="88" width="36" height="24" rx="12"/><text class="pnum" x="48" y="104">1</text></g>
  <text class="pname" x="48" y="132">V_cmd ← 유도</text>
  <path class="wire" d="M66 100 H96" marker-end="url(#aw-aps)"/>
  <g class="sblk" data-code="blocks/filters.py:CommandFilter"><rect class="body" x="100" y="74" width="118" height="52" rx="3"/>
    <text class="ttl" x="159" y="93" style="font-size:13px">명령필터</text>
    <text class="ttl2" x="159" y="111">τ <tspan data-p="tau_spd">2</tspan> s</text></g>
  <text class="siglabel" x="159" y="144">off: V 추적 · 트림 스로틀 홀드</text>
  <path class="wire" d="M218 100 H240" marker-end="url(#aw-aps)"/>
  <circle class="body" data-code="fcl/autopilot.py:Autopilot.step" cx="258" cy="100" r="14"/>
  <text class="sumsign" x="249" y="104">+</text><text class="sumsign" x="258" y="113">−</text>
  <path class="wire" d="M272 100 H296" marker-end="url(#aw-aps)"/>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="300" y="74" width="140" height="52" rx="3"/>
    <text class="ttl" x="370" y="93" style="font-size:13px">속도 PI — 클램프 AW</text>
    <text class="ttl2" x="370" y="111">kp <tspan data-p="kp_spd">0.15</tspan> · ki <tspan data-p="ki_spd">0.03</tspan></text></g>
  <path class="wire" d="M440 100 H492" marker-end="url(#aw-aps)"/>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="496" y="74" width="90" height="52" rx="3"/>
    <path d="M506 116 H518 L564 84 H576" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="541" y="144">클립 0~1</text>
  <path class="wire" d="M586 100 H612" marker-end="url(#aw-aps)"/>
  <circle class="body" data-code="fcl/autopilot.py:Autopilot.step" cx="630" cy="100" r="14"/>
  <text class="sumsign" x="621" y="104">+</text><text class="sumsign" x="630" y="93">+</text>
  <path class="wire" d="M644 100 H700" marker-end="url(#aw-aps)"/>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="704" y="74" width="82" height="52" rx="3"/>
    <path d="M712 116 H724 L766 84 H778" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="745" y="144">재클립 0~1</text>
  <path class="wire" d="M786 100 H806" marker-end="url(#aw-aps)"/>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="810" y="88" width="36" height="24" rx="12"/><text class="pnum" x="828" y="104">1</text></g>
  <text class="pname" x="828" y="132">δt_cmd (0~1)</text>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="240" y="162" width="36" height="24" rx="12"/><text class="pnum" x="258" y="178">2</text></g>
  <text class="pname a-start" x="282" y="178">V = |v_n| — 바람 0</text>
  <path class="wire" d="M258 162 V118" marker-end="url(#aw-aps)"/>
  <path class="wire ff" d="M630 190 V118" marker-end="url(#af-aps)"/>
  <text class="siglabel" x="560" y="210">선회 FF 스로틀 — <tspan data-p="k_thr_turn">0</tspan>·(1/cos²φ−1)</text>
  <text class="canvas-note" x="24" y="272">※ 선회 FF는 클립 후 가산 → 재클립 (이중 제한) · 트림 웜스타트: 속도 적분기 = 트림 스로틀 [범프리스] · δt_cmd는 믹서에서 차동추력 보상과 결합</text>
</svg>`,
        flow: {
          lead: "V_cmd → 필터 τ2 → 오차 → PI → 클립 0~1 → + 선회 FF → 재클립 → δt_cmd",
          reads: [
            "V_cmd가 ①로 들어와 명령필터(τ 2 s)를 지난다.",
            "항법의 V(②)를 빼서 오차를 만들고 PI로 보낸다.",
            "0~1로 클립한다 — 스로틀의 물리적 범위다.",
            "선회 FF가 더해지고 다시 0~1로 재클립한 것이 δt_cmd다.",
            "δt_cmd는 믹서를 거쳐 스로틀로 간다. 믹서에 차동추력 배분 경로가 있지만 <b>이 기체는 계수가 0</b>이라(단발 중심선) 여기서 나온 값이 그대로 엔진에 닿는다.",
          ],
          why: [
            "구조에 선회 FF 자리가 있는데 <b>데모 값은 0</b>이다 — 실측에서 역효과였다. 구조가 있다고 켜야 하는 것은 아니라는 자리이고, 값이 0이어도 경로를 지워 두지 않은 것은 기체가 바뀌면 다시 필요해지기 때문이다.",
            "적분기를 <b>트림 스로틀로</b> 시드한다(웜스타트). 0에서 시작하면 채널이 활성화되는 순간 추력이 사라졌다가 적분이 다시 쌓일 때까지 가라앉는다.",
            "튜닝을 속도부터 하는 이유가 이 채널에 있다: 스로틀은 추력만이 아니라 <b>동압</b>을 바꾼다. 동압이 흔들리면 같은 타면각이 다른 모멘트를 내므로 SCAS의 실효 게인까지 함께 흔들린다.",
            "데모 설계점에서 속도 +10 m/s 오버슈트 3.7% (폐루프 스캔).",
          ],
        },
        notes: `
<h4>설계 노트</h4>
<ul>
  <li><span class="mono">δt_cmd = 재클립( clip(PI(V_ref−V), 0~1) + FF, 0~1 )</span> — FF 가산 후 <b>재클립</b> <span class="chip ok">확정 M7</span></li>
  <li>비활성 시 필터는 V 추적 + 오차 0 적분 → <b>트림 스로틀 홀드</b> · 스로틀 FF는 데모에서 0 (역효과 확인) <span class="chip dft">기본값</span></li>
  <li>데모 설계값: kp 0.15 · ki 0.03 · τ 2 s <span class="chip dft">기본값</span> · 속도 +10 m/s 오버슈트 3.7% (설계점 폐루프 스캔)</li>
</ul>`,
      },
    },
  },

  // ── 유도 (설계 ④) ────────────────────────────────────────────────────
  guidance: {
    tag: "설계 ④", tagBg: "#b45309",
    title: "유도 — 모드별 유도 + 경로 추종", eng: "Guidance (M8)",
    chips: ["ok", "dft", "tbd"],
    svg: `
<svg viewBox="0 0 940 490" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-guid" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker>
  <marker id="as-guid" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#8a97a5"/></marker></defs>
  <!-- 구성 입력 (점선) — 모드 테이블·웨이포인트는 임무프로파일이 정의 -->
  <g class="sblk" data-code="guidance/guidance.py:Guidance"><rect class="body" x="30" y="48" width="36" height="24" rx="12"/><text class="pnum" x="48" y="64">1</text></g>
  <text class="pname" x="48" y="92">임무프로파일</text>
  <path class="wire soft" d="M66 60 H430 V146" marker-end="url(#as-guid)"/>
  <circle class="branch" cx="110" cy="60" r="3.2"/>
  <path class="wire soft" d="M110 60 V316 H356" marker-end="url(#as-guid)"/>
  <text class="siglabel" x="260" y="48">웨이포인트 열 · 모드 테이블 (편집: 시뮬 탭)</text>
  <!-- 항법 입력 → 유효성 게이트 -->
  <g class="sblk" data-code="guidance/guidance.py:Guidance.step"><rect class="body" x="30" y="268" width="36" height="24" rx="12"/><text class="pnum" x="48" y="284">2</text></g>
  <text class="pname" x="48" y="312">NavOutput</text>
  <path class="wire" d="M66 280 H136" marker-end="url(#aw-guid)"/>
  <g class="sblk" data-code="guidance/guidance.py:Guidance.step"><rect class="body" x="140" y="254" width="160" height="52" rx="3"/>
    <text class="ttl" x="220" y="276" style="font-size:13px">유효성 게이트</text>
    <text class="ttl2" x="220" y="294">invalid → 동결 · 명령 유지</text></g>
  <path class="wire" d="M300 280 H326"/>
  <circle class="branch" cx="330" cy="280" r="3.2"/>
  <path class="wire" d="M330 280 V190 H356" marker-end="url(#aw-guid)"/>
  <path class="wire" d="M330 280 V350 H356" marker-end="url(#aw-guid)"/>
  <!-- 경로추종 (레지스트리 교체 가능) -->
  <g class="blk" data-child="path" data-code="guidance/path.py:LosPath" tabindex="0"><rect class="body" x="360" y="150" width="200" height="80" rx="3"/>
    <text class="ttl" x="460" y="172" style="font-size:13px">경로추종 — LOS [기본값]</text>
    <text class="ttl2" x="460" y="190">현위치→활성 WP 방위각</text>
    <text class="ttl2" x="460" y="204">도달반경 진입 → 다음 WP (연쇄 스킵)</text>
    <text class="ttl2" x="460" y="218">소진 → done · 유지 · 클릭 → 내부</text></g>
  <path class="wire" d="M560 175 H636" marker-end="url(#aw-guid)"/>
  <text class="siglabel" x="598" y="163">ψ_wp</text>
  <path class="wire" d="M560 215 H590 V270 H480 V296" marker-end="url(#aw-guid)"/>
  <text class="siglabel" x="540" y="262">path_done</text>
  <!-- 모드 시퀀서 -->
  <g class="blk" data-child="modes" data-code="guidance/modes.py:ModeSequencer" tabindex="0"><rect class="body" x="360" y="300" width="200" height="100" rx="3"/>
    <text class="ttl" x="460" y="324" style="font-size:13px">모드 시퀀서</text>
    <text class="ttl2" x="460" y="344">선언 테이블 {명령·이탈·next}</text>
    <text class="ttl2" x="460" y="360">이탈: time·alt·speed·path_done</text>
    <text class="ttl2" x="460" y="376">순차 체인 · 스텝당 1회 · 클릭 → 내부</text></g>
  <path class="wire" d="M560 350 H636" marker-end="url(#aw-guid)"/>
  <text class="siglabel" x="598" y="338">활성 모드</text>
  <circle class="branch" cx="610" cy="350" r="3.2"/>
  <path class="wire" d="M610 350 V240 H690 V214" marker-end="url(#aw-guid)"/>
  <!-- heading 선택 · 명령 구성 -->
  <g class="sblk" data-code="guidance/guidance.py:Guidance.step"><rect class="body" x="640" y="150" width="130" height="60" rx="3"/>
    <text class="ttl" x="705" y="170" style="font-size:13px">heading 선택</text>
    <text class="ttl2" x="705" y="186">"path" → ψ_wp</text>
    <text class="ttl2" x="705" y="200">그 외 → 모드값</text></g>
  <path class="wire" d="M770 180 H786 V296" marker-end="url(#aw-guid)"/>
  <text class="siglabel" x="810" y="176">ψ_cmd</text>
  <g class="sblk" data-code="guidance/guidance.py:Guidance.step common/contracts.py:GuidanceCommand"><rect class="body" x="640" y="300" width="160" height="90" rx="3"/>
    <text class="ttl" x="720" y="322" style="font-size:13px">GuidanceCommand</text>
    <text class="ttl2" x="720" y="342">speed · alt · heading 구성</text>
    <text class="ttl2" x="720" y="358">None → 축 비활성 플래그</text>
    <text class="ttl2" x="720" y="374">mode 이름 포함</text></g>
  <path class="wire" d="M800 345 H866" marker-end="url(#aw-guid)"/>
  <g class="sblk" data-code="guidance/guidance.py:Guidance.step"><rect class="body" x="870" y="333" width="36" height="24" rx="12"/><text class="pnum" x="888" y="349">1</text></g>
  <text class="pname" x="886" y="377">→ AP</text>
  <text class="canvas-note" x="24" y="440">※ 모드 전환 순간의 명령 점프는 오토파일럿 명령필터가 완충 [기본값] — Fader 페이딩은 백로그 · 경로추종은 헤딩만 담당 (고도·속도는 모드 테이블 소관)</text>
  <text class="canvas-note" x="24" y="462">모드 시퀀스 예: 이륙 → 상승 → (순항 · 고도유지 · 디센트 · 임무수행 · 웨이포인트 항법) → 착륙 · Stateflow 미사용 [확정]</text>
</svg>`,
    flow: {
      lead: "임무프로파일 + NavOutput → 유효성 게이트 → 경로추종 · 모드 시퀀서 → GuidanceCommand → AP",
      reads: [
        "입력은 둘이다 — 임무프로파일(①: 웨이포인트 열 + 모드 테이블, 편집은 시뮬 탭)과 NavOutput(②).",
        "NavOutput은 먼저 <b>유효성 게이트</b>를 지난다. 항법이 무효면 여기서 동결하고 마지막 명령을 유지한다 — 아래 블록 전부가 갱신을 멈춘다.",
        "그 뒤 두 갈래다. 위는 경로추종(LOS)이 현위치에서 활성 웨이포인트를 겨눈 방위각 ψ_wp를 내고, 아래는 모드 시퀀서가 선언 테이블을 돌려 활성 모드를 고른다.",
        "두 갈래가 서로 이어진 지점이 하나 있다 — 경로추종의 path_done이 시퀀서로 들어간다. 웨이포인트 소진이 그대로 모드 이탈 조건이 될 수 있다.",
        "heading 선택 블록이 둘을 합친다: 모드가 heading을 path라고 적었으면 ψ_wp를, 아니면 모드가 적은 숫자를 쓴다.",
        "GuidanceCommand가 speed·alt·heading을 묶어 AP로 나간다. None인 축은 <b>비활성 플래그</b>가 된다 — 명령이 0이 아니라 그 축을 안 쓴다는 뜻이다.",
      ],
      why: [
        "유효성 게이트가 맨 앞인 이유: 항법이 무효인데 경로·모드를 갱신하면 <b>틀린 위치로 웨이포인트를 통과 처리</b>하거나 모드를 넘겨 버린다. 되돌릴 수 없는 상태 변화라, 명령을 틀리게 내는 것보다 갱신 자체를 멈추는 편이 낫다.",
        "경로와 모드가 나란한데 우선순위 규칙이 없다. 축마다 출처를 <b>하나만</b> 고르기 때문이다 — 모드가 alt를 path로 적어야만 경로의 세로 프로파일이 쓰인다. 둘 다 켜졌을 때 누가 이기나라는 상황을 애초에 만들지 않는다.",
        "Stateflow식 상태머신이 없다. 순차 체인이다 — 각 모드가 next 하나를 갖고, 이탈 조건이 충족되면 그리로 간다. 전이 그래프를 자유롭게 그리면 그림과 코드가 1:1로 안 붙는다.",
        "모드 전환 순간의 명령 점프를 여기서 다루지 않는다 — AP의 명령필터가 완충한다. 여기서 또 페이딩하면 완충이 두 겹이 되어 어느 쪽이 느린지 화면에서 말할 수 없게 된다.",
      ],
    },
    notes: `
<h4>비행모드 실행기 — 선언적 모드 테이블 + Sequencer <span class="chip ok">확정</span></h4>
<div class="chain">
  <span class="ctl">이륙</span><span class="arr">→</span><span class="ctl">상승</span><span class="arr">→</span>
  <span class="sig">순항 · 고도유지 · 디센트 · 임무수행 · 웨이포인트 항법</span><span class="arr">→</span>
  <span class="ctl">착륙</span>
</div>
<ul>
  <li>각 모드 = { 진입조건, 활성 명령, 이탈조건 } — 전환 조건·우선순위·비상 처리 <span class="chip tbd">TBD</span></li>
  <li>저고도 임무 기준 고도: 해수면 0 ft (MSL) <span class="chip ok">확정</span></li>
</ul>
<h4>경로 추종</h4>
<ul>
  <li>웨이포인트 열 → 경로 추종 <span class="chip ok">확정</span> · M8 1차는 <b>LOS</b> <span class="chip dft">기본값</span> — L1/벡터필드 선정은 <span class="chip tbd">TBD</span></li>
  <li>모드·게인 전환 시 범프리스 처리 (적분기 초기화 · 명령 페이딩 — Fader) <span class="chip tbd">TBD</span></li>
  <li>항법 무효(valid=False) 시 전환·경로 갱신 <b>동결 + 마지막 명령 유지</b> <span class="chip dft">기본값</span> — 첫 유효 이전엔 전 축 비활성 (M7 웜스타트 홀드와 결합)</li>
  <li>경로추종·모드 시퀀서 내부는 블록 클릭 — 층3</li>
</ul>`,

    children: {
      path: {
        crumb: "경로추종",
        title: "경로추종 — LOS", eng: "LosPath — step(nav) → (heading, done) · 레지스트리 교체 가능 컴포넌트",
        chips: ["ok", "dft", "tbd"],
        svg: `
<svg viewBox="0 0 960 380" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-gpath" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <g class="sblk" data-code="guidance/path.py:LosPath.step"><rect class="body" x="30" y="96" width="36" height="24" rx="12"/><text class="pnum" x="48" y="112">1</text></g>
  <text class="pname" x="52" y="140">NavOutput</text>
  <path class="wire" d="M66 108 H96" marker-end="url(#aw-gpath)"/>
  <g class="sblk" data-code="guidance/path.py:LosPath.step"><rect class="body" x="100" y="82" width="170" height="52" rx="3"/>
    <text class="ttl" x="185" y="101" style="font-size:13px">위치 추출</text>
    <text class="ttl2" x="185" y="119">(n, e) = pos_n 수평면</text></g>
  <path class="wire" d="M270 108 H316" marker-end="url(#aw-gpath)"/>
  <g class="sblk" data-code="guidance/path.py:LosPath.step"><rect class="body" x="320" y="72" width="260" height="72" rx="3"/>
    <text class="ttl" x="450" y="94" style="font-size:13px">도달 판정 — 연쇄 스킵 (while)</text>
    <text class="ttl2" x="450" y="112">dn·de = 활성 WP − (n, e)</text>
    <text class="ttl2" x="450" y="130" data-gain="accept_radius">√(dn²+de²) ≤ 도달반경 → 다음 WP</text></g>
  <path class="wire" d="M580 108 H636" marker-end="url(#aw-gpath)"/>
  <text class="siglabel" x="608" y="96">미도달</text>
  <g class="sblk" data-code="guidance/path.py:LosPath.step"><rect class="body" x="640" y="82" width="180" height="52" rx="3"/>
    <text class="ttl" x="730" y="101" style="font-size:13px">LOS 방위각</text>
    <text class="ttl2" x="730" y="119">ψ_wp = atan2(de, dn)</text></g>
  <path class="wire" d="M820 108 H866" marker-end="url(#aw-gpath)"/>
  <g class="sblk" data-code="guidance/path.py:LosPath.step"><rect class="body" x="870" y="96" width="36" height="24" rx="12"/><text class="pnum" x="888" y="112">1</text></g>
  <text class="pname" x="884" y="140">ψ_wp → heading 선택</text>
  <path class="wire" d="M450 144 V196" marker-end="url(#aw-gpath)"/>
  <text class="siglabel" x="540" y="176">잔여 WP 없음 (소진)</text>
  <g class="sblk" data-code="guidance/path.py:LosPath.step"><rect class="body" x="340" y="200" width="220" height="72" rx="3"/>
    <text class="ttl" x="450" y="222" style="font-size:13px">웨이포인트 소진</text>
    <text class="ttl2" x="450" y="242">done=True · 마지막 헤딩 유지</text>
    <text class="ttl2" x="450" y="260">미계산 소진 → 현재 침로 시드</text></g>
  <path class="wire" d="M560 236 H700" marker-end="url(#aw-gpath)"/>
  <g class="sblk" data-code="guidance/path.py:LosPath.step"><rect class="body" x="704" y="224" width="36" height="24" rx="12"/><text class="pnum" x="722" y="240">2</text></g>
  <text class="pname" x="726" y="268">alt·done → 모드 시퀀서</text>
  <text class="canvas-note" x="24" y="320">※ 반경 내 연쇄 스킵 — 붙은 웨이포인트 여러 개를 한 스텝에 통과 · done 후 heading은 마지막 값 유지, alt는 마지막 웨이포인트 고도로 정착 — 계약은 (heading, alt, done)</text>
  <text class="canvas-note" x="24" y="340">※ 소진 안전: 첫 헤딩 계산 전 소진(빈 목록·반경 내 시작)이면 정북(0) 아닌 현재 침로 명령 — 조용한 급선회 방지 · 도달반경 엔진 기본 200 m [기본값] / 시뮬 탭 폼 1500 m — 편집: 시뮬 탭</text>
  <text class="canvas-note" x="24" y="360">※ 경로가 헤딩과 **세로 프로파일**을 낸다 — 모드가 alt=&quot;path&quot;일 때만 쓰인다(heading과 같은 규약) · 속도는 모드 소관 · 대안은 같은 step(nav)→(heading, alt, done) 계약 [TBD 01 §3.3]</text>
</svg>`,
        flow: {
          lead: "NavOutput → (n, e) 추출 → 도달 판정(연쇄 스킵) → LOS 방위각 → ψ_wp · alt · done",
          reads: [
            "NavOutput(①)에서 <b>수평 위치 (n, e)만</b> 뽑는다 — 고도는 이 판정에 안 쓴다.",
            "활성 웨이포인트까지 거리를 재서 도달반경 안이면 다음 웨이포인트로 넘어간다. while이라 <b>붙어 있는 웨이포인트 여러 개를 한 스텝에</b> 통과한다(연쇄 스킵).",
            "미도달이면 ψ_wp = atan2(de, dn) — 현위치에서 활성 웨이포인트를 곧장 겨눈 방향이다.",
            "잔여 웨이포인트가 없으면 done=True를 내고 마지막 헤딩을 유지한다.",
            "나가는 것은 셋이다 — 방위각은 heading 선택으로(①), alt와 done은 모드 시퀀서로(②).",
          ],
          why: [
            "연쇄 스킵이 if가 아니라 while인 이유: 도달반경(데모 1500 m)이 웨이포인트 간격보다 크면 한 스텝에 여러 개가 반경 안에 든다. 하나씩만 넘기면 <b>이미 지나친 웨이포인트를 계속 겨누고</b> 뒤로 돌아간다.",
            "헤딩을 한 번도 계산하기 전에 소진되면(빈 목록이거나 반경 안에서 시작) 정북 0이 아니라 <b>현재 침로</b>를 명령한다. 0을 내면 그 순간 조용히 급선회가 난다 — 아무도 명령하지 않은 기동이다.",
            "LOS인 것은 1차 선택이다. 교체 계약 step(nav) → (heading, alt, done)만 지키면 L1이나 벡터필드로 갈아 끼울 수 있고, 그래서 이 블록이 레지스트리 컴포넌트다.",
          ],
        },
        notes: `
<h4>설계 노트</h4>
<ul>
  <li>교체 계약: <span class="mono">step(nav) → (heading_cmd, alt_cmd, done)</span> — L1·벡터필드 등 대안 알고리즘 선정 <span class="chip tbd">TBD 01 §3.3</span> · M8 1차는 <b>LOS</b> <span class="chip dft">기본값</span></li>
  <li>도달 반경 진입 시 다음 웨이포인트 — <b>반경 내 연쇄 스킵</b> 허용 (while) · 도달반경 accept_radius — <b>엔진 기본값 200 m</b> <span class="chip dft">기본값</span>이지만 <b>시뮬 탭 폼 기본값은 1500 m</b>다(데모 미션 스케일에 맞춘 값, 웹이 항상 명시 전송). 세로 프로파일의 램프 마루와 새 웨이포인트의 "원점 판정"도 이 값을 쓴다 — 편집은 시뮬 탭 미션 그룹</li>
  <li>소진 안전: 헤딩을 한 번도 계산하기 전 소진(빈 목록·반경 내 시작)이면 정북(0)이 아닌 <b>현재 침로</b>를 명령 — 조용한 급선회 방지 <span class="chip ok">확정</span></li>
  <li>웨이포인트는 <span class="mono">(n, e)</span> 또는 <span class="mono">(n, e, alt)</span>[m] — 고도를 주면 <b>경로가 세로 프로파일도 낸다</b>(구간 선형, 램프는 도달 반경 경계에서 종료). 모드가 <span class="mono">alt="path"</span>일 때만 쓰이므로 <b>heading과 같은 규약</b>이고, 그래서 "경로와 모드 중 누가 이기나"라는 우선순위 규칙이 따로 없다. 속도는 모드 소관 <span class="chip ok">확정</span></li>
  <li><b>종방향 지령은 고도·피치·강하율 중 하나</b> — 셋 다 θ 명령으로 가므로 둘을 켜면 화면이 "무엇이 먹었는지"를 말할 수 없다. 우선순위를 두는 대신 <b>모드 구성 시점에 거부</b>한다(<span class="mono">validate_longitudinal</span>) — 위 "축마다 출처를 고른다"를 검증으로 못박은 것 <span class="chip ok">확정</span></li>
  <li>이탈 조건에 강하율(<span class="mono">hdot_ge/le</span>)·접지(<span class="mono">on_ground/airborne</span>)·레일 이탈(<span class="mono">off_rail</span>). 뒤 넷은 <b>항법에 없는 정보</b>라 시뮬이 착륙장치·레일에서 읽어 넣는다 — 그 형상이 아니면 <b>판정 불가</b>로 멈춘다(False로 눙치면 모드가 조용히 그 자리에 선다). <span class="mono">airborne</span>은 <b>레일 이탈이 아니다</b>: 레일이 받치는 동안 기어는 닿지 않아 t=0부터 참이다 <span class="chip ok">확정</span></li>
</ul>`,
      },
      modes: {
        crumb: "모드 시퀀서",
        title: "모드 시퀀서 — 선언 테이블 실행기", eng: "ModeSequencer + ModeSpec · 이탈조건 DSL · 전환 스텝당 1회",
        chips: ["ok", "dft", "tbd"],
        svg: `
<svg viewBox="0 0 960 430" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="aw-gmod" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker>
    <marker id="as-gmod" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#8a97a5"/></marker>
  </defs>
  <rect x="30" y="48" width="300" height="84" rx="8" fill="none" stroke="#8a5cf6" stroke-width="1.4" stroke-dasharray="6 4"/>
  <text class="annot" x="180" y="72" text-anchor="middle">이탈조건 DSL — 직렬화 튜플 (웹 편집 대상)</text>
  <text class="annot" x="180" y="92" text-anchor="middle">(always) (time_ge s) (alt_ge m) (alt_le m)</text>
  <text class="annot" x="180" y="112" text-anchor="middle">(speed_ge) (speed_le) (path_done)</text>
  <g class="sblk" data-code="guidance/modes.py:ModeSpec guidance/modes.py:ModeSequencer"><rect class="body" x="370" y="36" width="330" height="80" rx="3"/>
    <text class="ttl" x="535" y="58" style="font-size:13px">모드 테이블 {name → ModeSpec}</text>
    <text class="ttl2" x="535" y="78">speed·alt·heading — None = 축 비활성</text>
    <text class="ttl2" x="535" y="94">heading: 숫자 | "path" | None</text>
    <text class="ttl2" x="535" y="110">구성 검증: 이름 중복·next 참조·조건 arity</text></g>
  <path class="wire soft" d="M535 116 V166" marker-end="url(#as-gmod)"/>
  <g class="sblk" data-code="guidance/modes.py:ModeSequencer.step"><rect class="body" x="210" y="150" width="150" height="52" rx="3"/>
    <text class="ttl" x="285" y="169" style="font-size:13px">활성 모드 name</text>
    <text class="ttl2" x="285" y="187">t_entry 보관</text></g>
  <path class="wire" d="M360 176 H396" marker-end="url(#aw-gmod)"/>
  <g class="sblk" data-code="guidance/modes.py:ModeSequencer.step"><rect class="body" x="400" y="170" width="270" height="110" rx="3"/>
    <text class="ttl" x="535" y="194" style="font-size:13px">이탈 판정 — 스텝당 1회</text>
    <text class="ttl2" x="535" y="214">next 없으면 종단 — 평가 생략·유지</text>
    <text class="ttl2" x="535" y="232">eval_condition(exit_when, nav, ctx)</text>
    <text class="ttl2" x="535" y="250">ctx: t_mode = t − t_entry · path_done</text>
    <text class="ttl2" x="535" y="268">충족 → 전환 · 미충족 → 현행 유지</text></g>
  <path class="wire" d="M670 200 H726" marker-end="url(#aw-gmod)"/>
  <text class="siglabel" x="698" y="192">충족</text>
  <g class="sblk" data-code="guidance/modes.py:ModeSequencer.step"><rect class="body" x="730" y="170" width="190" height="64" rx="3"/>
    <text class="ttl" x="825" y="192" style="font-size:13px">전환</text>
    <text class="ttl2" x="825" y="212">name ← next</text>
    <text class="ttl2" x="825" y="228">t_entry ← t (체류 리셋)</text></g>
  <path class="wire" d="M820 234 V330 H285 V206" marker-end="url(#aw-gmod)"/>
  <g class="sblk" data-code="guidance/modes.py:eval_condition"><rect class="body" x="30" y="218" width="36" height="24" rx="12"/><text class="pnum" x="48" y="234">1</text></g>
  <text class="pname" x="52" y="262">NavOutput</text>
  <path class="wire" d="M66 230 H396" marker-end="url(#aw-gmod)"/>
  <g class="sblk" data-code="guidance/modes.py:ModeSequencer.step"><rect class="body" x="30" y="288" width="36" height="24" rx="12"/><text class="pnum" x="48" y="304">2</text></g>
  <text class="pname" x="95" y="332">path_done ← 경로추종</text>
  <path class="wire" d="M66 300 H370 V262 H396" marker-end="url(#aw-gmod)"/>
  <path class="wire" d="M535 280 V360 H866" marker-end="url(#aw-gmod)"/>
  <text class="siglabel" x="620" y="352">cur — 전환 반영 후</text>
  <g class="sblk" data-code="guidance/modes.py:ModeSequencer.step"><rect class="body" x="870" y="348" width="36" height="24" rx="12"/><text class="pnum" x="888" y="364">1</text></g>
  <text class="pname" x="870" y="392">활성 ModeSpec</text>
  <text class="pname" x="860" y="410">→ GuidanceCommand 구성</text>
  <text class="canvas-note" x="24" y="424">※ Stateflow 미사용 [확정 01 §3.3.1] — 순차 체인: 진입 = 이전 모드의 이탈 → next [기본값] · 초기 모드 진입 시각 = 첫 스텝 t · 항법 무효 시 상류 유효성 게이트가 동결</text>
</svg>`,
        flow: {
          lead: "모드 테이블 + NavOutput·path_done → 이탈 판정(스텝당 1회) → 전환 → 활성 ModeSpec",
          reads: [
            "왼쪽 점선 프레임은 신호가 아니라 <b>이탈조건 DSL의 어휘</b>다 — always · time_ge · alt_ge · alt_le · speed_ge · speed_le · path_done 7종.",
            "모드 테이블은 {이름 → ModeSpec}이고, ModeSpec 하나가 speed·alt·heading과 이탈조건·next를 들고 있다.",
            "실행기는 활성 모드 이름과 <b>진입 시각 t_entry</b>를 보관한다.",
            "스텝마다 이탈 판정을 <b>한 번</b> 한다. 판정 문맥에 t_mode = t − t_entry와 path_done이 들어간다.",
            "충족되면 전환한다: name ← next, t_entry ← t (체류 시간 리셋). next가 없으면 종단 모드라 평가 자체를 건너뛴다.",
            "전환이 반영된 활성 ModeSpec이 GuidanceCommand 구성으로 나간다.",
          ],
          why: [
            "상태머신이 아니라 <b>선언 테이블 + 실행기</b>인 이유: 전환 논리가 코드가 아니라 데이터라 웹에서 편집하고 직렬화할 수 있다. 그래서 조건이 튜플 DSL이고, 구성 시점에 종류·인자 개수를 시끄럽게 거부한다 — 배치 시뮬 <b>도중에</b> 터지면 그 실행분이 통째로 날아간다.",
            "전환이 스텝당 한 번인 이유: 여러 번 넘기면 조건이 겹친 모드 사슬을 한 스텝에 통째로 지나쳐 버린다. 100 Hz면 한 번으로 충분하다.",
            "t_entry를 전환마다 리셋하는 것이 time_ge의 의미를 정한다 — 절대 시각이 아니라 <b>모드 체류 시간</b> 기준이다.",
          ],
        },
        notes: `
<h4>설계 노트</h4>
<ul>
  <li>선언적 모드 테이블 + 실행기 — Stateflow식 상태머신 없음 <span class="chip ok">확정 01 §3.3.1</span> · 진입조건은 순차 체인(이전 모드의 이탈 → next)으로 대체 <span class="chip dft">기본값</span> — 진입·이탈 상세 <span class="chip tbd">TBD</span></li>
  <li>이탈조건 DSL 7종 — <span class="mono">always · time_ge · alt_ge · alt_le · speed_ge · speed_le · path_done</span> · validate_condition이 구성 시점에 kind·인자 개수·수치 타입을 시끄럽게 거부 (배치 시뮬 도중 오류 방지)</li>
  <li>time_ge는 모드 <b>체류 시간</b> 기준 (진입 시각부터) · path_done은 경로추종 웨이포인트 소진</li>
  <li>next=None은 종단 모드 — 이탈 평가 자체를 건너뛰고 유지 · 전환은 스텝당 1회 <span class="chip dft">기본값</span> (100 Hz에서 충분)</li>
  <li>명령 None = 해당 축 비활성 (오토파일럿 트림 홀드와 결합) · 전환 순간의 명령 점프는 AP 명령필터가 완충 — Fader 페이딩은 백로그</li>
</ul>`,
      },
    },
  },

  // ── α 리미터 (보호) ──────────────────────────────────────────────────
  limiter: {
    tag: "보호", tagBg: "#b3352b",
    title: "α 리미터 — 엔벨로프 보호", eng: "피치축 명령 경로 · 동적 상한 하드 클램프",
    chips: ["ok", "dft", "tbd"],
    svg: `
<svg viewBox="0 0 900 470" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-lim" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <!-- 피치 명령 경로 — 상한 단방향 클램프 -->
  <g class="sblk" data-code="fcl/limiter.py:AlphaLimiter.step"><rect class="body" x="30" y="68" width="36" height="24" rx="12"/><text class="pnum" x="48" y="84">1</text></g>
  <text class="pname" x="56" y="112">θ_cmd ← AP</text>
  <path class="wire" d="M66 80 H556" marker-end="url(#aw-lim)"/>
  <g class="sblk" data-code="fcl/limiter.py:AlphaLimiter.step"><rect class="body" x="560" y="50" width="120" height="60" rx="3"/>
    <path d="M572 96 L620 66 H648" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="620" y="134">min(θ_cmd, cap) — 상한만</text>
  <path class="wire" d="M680 80 H746" marker-end="url(#aw-lim)"/>
  <g class="sblk" data-code="fcl/limiter.py:AlphaLimiter.step"><rect class="body" x="750" y="68" width="36" height="24" rx="12"/><text class="pnum" x="768" y="84">1</text></g>
  <text class="pname" x="768" y="112">θ_cmd′ → SCAS</text>
  <!-- 동적 상한: cap = θ + (α_stall(mach) − margin − α) -->
  <g class="sblk" data-code="fcl/limiter.py:AlphaLimiter.step"><rect class="body" x="30" y="218" width="36" height="24" rx="12"/><text class="pnum" x="48" y="234">2</text></g>
  <text class="pname" x="48" y="262">Mach</text>
  <path class="wire" d="M66 230 H96" marker-end="url(#aw-lim)"/>
  <g class="sblk" data-code="fcl/limiter.py:AlphaLimiter.alpha_max"><rect class="body" x="100" y="200" width="190" height="60" rx="3"/>
    <path d="M112 246 L128 246 L142 224 L158 236 L172 218" stroke="#8a97a5" stroke-width="1.6" fill="none"/>
    <text class="ttl" x="234" y="224" style="font-size:13px">α_stall(mach)</text>
    <text class="ttl2" x="234" y="242">1D · 외삽 clip 강제</text></g>
  <path class="wire" d="M290 230 H316" marker-end="url(#aw-lim)"/>
  <g class="sblk" data-code="fcl/limiter.py:AlphaLimiter.alpha_max"><rect class="body" x="320" y="200" width="130" height="60" rx="3"/>
    <text class="ttl" x="385" y="224" style="font-size:13px">− 보호마진</text>
    <text class="ttl2" x="385" y="242">0.05 rad ≈ 2.9°</text></g>
  <path class="wire" d="M450 230 H476" marker-end="url(#aw-lim)"/>
  <text class="siglabel" x="468" y="210">α_max</text>
  <circle class="body" data-code="fcl/limiter.py:AlphaLimiter.step" cx="494" cy="230" r="14"/>
  <text class="sumsign" x="485" y="234">+</text><text class="sumsign" x="494" y="243">−</text>
  <path class="wire" d="M508 230 H602" marker-end="url(#aw-lim)"/>
  <text class="siglabel" x="554" y="212">Δα 실속 마진</text>
  <circle class="branch" cx="560" cy="230" r="3.2"/>
  <circle class="body" data-code="fcl/limiter.py:AlphaLimiter.step" cx="620" cy="230" r="14"/>
  <text class="sumsign" x="611" y="234">+</text><text class="sumsign" x="629" y="234">+</text>
  <path class="wire" d="M620 216 V114" marker-end="url(#aw-lim)"/>
  <text class="siglabel" x="556" y="170">cap = θ + Δα</text>
  <!-- 실속 마진 출력 — 엔벨로프 감시 -->
  <path class="wire" d="M560 230 V380 H700" marker-end="url(#aw-lim)"/>
  <g class="sblk" data-code="fcl/limiter.py:AlphaLimiter.step"><rect class="body" x="704" y="368" width="36" height="24" rx="12"/><text class="pnum" x="722" y="384">2</text></g>
  <text class="pname" x="722" y="412">실속 마진 Δα → 엔벨로프 감시</text>
  <!-- NavOutput 추출 -->
  <g class="sblk" data-code="fcl/limiter.py:AlphaLimiter.step"><rect class="body" x="30" y="298" width="36" height="24" rx="12"/><text class="pnum" x="48" y="314">3</text></g>
  <text class="pname" x="52" y="342">NavOutput</text>
  <path class="wire" d="M66 310 H136" marker-end="url(#aw-lim)"/>
  <g class="sblk" data-code="fcl/airdata.py:airdata_from_nav common/attitude.py:quat_to_euler"><rect class="body" x="140" y="282" width="220" height="56" rx="3"/>
    <text class="ttl" x="250" y="304" style="font-size:13px">airdata · quat→euler</text>
    <text class="ttl2" x="250" y="324">α · θ 추출 — NavOutput만 소비</text></g>
  <path class="wire" d="M360 298 H494 V244" marker-end="url(#aw-lim)"/>
  <text class="siglabel" x="478" y="290">α</text>
  <path class="wire" d="M360 322 H680 V230 H634" marker-end="url(#aw-lim)"/>
  <text class="siglabel" x="666" y="256">θ</text>
  <text class="canvas-note" x="24" y="442">※ 반환 = (제한 θ_cmd′ · 작동 플래그 · 실속 마진 Δα) — 플래그·마진은 law 로깅 속성 → 엔벨로프 감시(02 §6.1) 소비 · mach는 law가 항법 고도의 ISA 음속으로 산출</text>
  <text class="canvas-note" x="24" y="462">※ 상한만 개입 — 하한 없음 · 근거: θ = γ + α 근사 (θ 증분 = α 증분 · γ 변화는 여유 회복 방향) · 1D (mach,) 외 테이블·clip 외 외삽은 생성 시 거부</text>
</svg>`,
    flow: {
      lead: "θ_cmd + Mach·NavOutput → cap = θ + (α_max − α) → min(θ_cmd, cap) → θ_cmd′",
      reads: [
        "AP가 준 θ_cmd가 ①로 들어온다. 왼쪽 위 한 줄이 명령 경로 전부다 — 나머지는 전부 <b>상한을 만드는</b> 부분이다.",
        "Mach(②)로 α_stall(mach)을 1D 룩업하고, 보호마진 0.05 rad(≈2.9°)를 뺀 것이 α_max다.",
        "NavOutput(③)에서 α와 θ를 뽑는다.",
        "α_max − α가 <b>실속 마진 Δα</b>이고, 여기에 현재 θ를 더한 것이 cap이다.",
        "min(θ_cmd, cap) — <b>상한만</b> 건다. 나온 θ_cmd′가 SCAS 피치로 간다.",
        "Δα는 따로 갈라져 엔벨로프 감시로 나간다(②) — 제어에 쓰이는 값이 그대로 감시 지표다.",
      ],
      why: [
        "cap이 상수가 아니라 θ + Δα인 것이 이 그림의 전부다. 제한해야 하는 것은 자세가 아니라 <b>받음각</b>인데 명령 경로에 있는 것은 θ뿐이다. θ = γ + α 근사에서 θ 증분이 곧 α 증분이므로, 지금 자세에 남은 받음각 여유를 더한 값이 넘지 말아야 할 자세가 된다.",
        "하한이 없는 이유도 같은 근사에서 나온다 — 기수를 내리는 방향은 받음각 여유를 <b>회복하는</b> 쪽이라 막을 이유가 없다.",
        "리미터가 SCAS <b>앞</b>, 즉 명령 경로에 있는 것이 핵심이다. 피드백으로 뒤에서 잡으면 이미 실속각에 들어간 뒤다. 명령 자체가 못 넘게 하는 것이 실속을 구조로 막는 방법이다. 폐루프 검증에서 리미터 없이 α > 0.34였고 장착 후 α ≤ 0.31이었다.",
        "제한이 걸려도 적분기가 부풀지 않는다 — 제한된 명령으로 계속 적분하는데 그 방향이 오차를 <b>줄이는</b> 쪽이기 때문이다.",
      ],
    },
    notes: `
<h4>설계 노트</h4>
<ul>
  <li>실속 <b>진입 자체를 방지</b> — 피치축 명령 경로에서 제한 <span class="chip ok">확정 01 §3.6</span> · <span class="mono">α_max = α_stall(Mach, 형상) − 보호마진</span></li>
  <li>M7 1차 구현: θ 명령 하드 클램프 <span class="mono">θ_cmd ≤ θ + (α_max − α)</span> · 보호마진 0.05 rad(≈2.9°) <span class="chip dft">기본값</span> — 폐루프 검증: 리미터 없음 α&gt;0.34 → 장착 α≤0.31</li>
  <li>적분기는 제한된 명령으로 계속 적분(오차 축소 방향 — 와인드업 없음 확인)</li>
  <li>실속 경계 정본: <b>공력팀 제공 테이블</b> (툴 DB 추출값은 교차확인용) · 동일 경계를 실속 마진 감시·엔벨로프 표시와 공유</li>
  <li>보호마진 실값 · 소프트 리미터 필요성 <span class="chip tbd">TBD</span> — 실속 경계 실데이터 확보 시 재검토</li>
  <li>하중배수(Nz) 제한 필요 여부 <span class="chip tbd">TBD</span> — 구조 하중 데이터 확보 시 (동일하게 피치 명령 경로 제한으로 구현 가능)</li>
</ul>`,
  },

  // ── 엘레본 믹싱 (제어 할당) ──────────────────────────────────────────
  mixer: {
    tag: "배분", tagBg: "#5f6b78",
    title: "엘레본 믹싱 (제어 할당)", eng: "Elevon Mixing / Control Allocation — 차동추력 배분 포함 (이 기체는 계수 0)",
    chips: ["dft", "tbd"],
    svg: `
<svg viewBox="0 0 940 516" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-mix" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <!-- 엘레본 좌/우 — 교차 결합 (X자 1회 교차는 믹싱의 본질) -->
  <g class="sblk" data-code="fcl/mixer.py:Mixer.step"><rect class="body" x="30" y="66" width="36" height="24" rx="12"/><text class="pnum" x="48" y="82">1</text></g>
  <text class="pname" x="48" y="112">피치 δe</text>
  <path class="wire" d="M66 78 H246" marker-end="url(#aw-mix)"/>
  <circle class="branch" cx="150" cy="78" r="3.2"/>
  <path class="wire" d="M150 78 V170 H246" marker-end="url(#aw-mix)"/>
  <g class="sblk" data-code="fcl/mixer.py:Mixer.step"><rect class="body" x="30" y="182" width="36" height="24" rx="12"/><text class="pnum" x="48" y="198">2</text></g>
  <text class="pname" x="48" y="232">롤 δa</text>
  <path class="wire" d="M66 194 H246" marker-end="url(#aw-mix)"/>
  <circle class="branch" cx="110" cy="194" r="3.2"/>
  <path class="wire" d="M110 194 V102 H246" marker-end="url(#aw-mix)"/>
  <g class="sblk" data-code="fcl/mixer.py:Mixer.step"><rect class="body" x="250" y="64" width="150" height="52" rx="3"/>
    <text class="ttl" x="325" y="86" style="font-size:13px">좌측 = δe + δa</text>
    <text class="ttl2" x="325" y="104">내좌 = 외좌 (1:1 고정)</text></g>
  <g class="sblk" data-code="fcl/mixer.py:Mixer.step"><rect class="body" x="250" y="156" width="150" height="52" rx="3"/>
    <text class="ttl" x="325" y="178" style="font-size:13px">우측 = δe − δa</text>
    <text class="ttl2" x="325" y="196">내우 = 외우 (1:1 고정)</text></g>
  <path class="wire" d="M400 90 H426" marker-end="url(#aw-mix)"/>
  <g class="sblk" data-code="fcl/mixer.py:Mixer.step"><rect class="body" x="430" y="64" width="110" height="52" rx="3"/>
    <path d="M442 106 H458 L512 74 H528" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="485" y="134">elevon_lo~hi</text>
  <path class="wire" d="M540 90 H610"/>
  <circle class="branch" cx="614" cy="90" r="3.2"/>
  <path class="wire" d="M614 90 V78 H796" marker-end="url(#aw-mix)"/>
  <path class="wire" d="M614 90 V106 H796" marker-end="url(#aw-mix)"/>
  <g class="sblk" data-code="fcl/mixer.py:Mixer.step"><rect class="body" x="800" y="66" width="36" height="24" rx="12"/><text class="pnum" x="818" y="82">1</text></g>
  <text class="pname" x="864" y="82">내좌</text>
  <g class="sblk" data-code="fcl/mixer.py:Mixer.step"><rect class="body" x="800" y="94" width="36" height="24" rx="12"/><text class="pnum" x="818" y="110">2</text></g>
  <text class="pname" x="864" y="110">외좌</text>
  <path class="wire" d="M400 182 H426" marker-end="url(#aw-mix)"/>
  <g class="sblk" data-code="fcl/mixer.py:Mixer.step"><rect class="body" x="430" y="156" width="110" height="52" rx="3"/>
    <path d="M442 198 H458 L512 166 H528" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="485" y="226">elevon_lo~hi</text>
  <path class="wire" d="M540 182 H610"/>
  <circle class="branch" cx="614" cy="182" r="3.2"/>
  <path class="wire" d="M614 182 V170 H796" marker-end="url(#aw-mix)"/>
  <path class="wire" d="M614 182 V198 H796" marker-end="url(#aw-mix)"/>
  <g class="sblk" data-code="fcl/mixer.py:Mixer.step"><rect class="body" x="800" y="158" width="36" height="24" rx="12"/><text class="pnum" x="818" y="174">3</text></g>
  <text class="pname" x="864" y="174">내우</text>
  <g class="sblk" data-code="fcl/mixer.py:Mixer.step"><rect class="body" x="800" y="186" width="36" height="24" rx="12"/><text class="pnum" x="818" y="202">4</text></g>
  <text class="pname" x="864" y="202">외우</text>
  <!-- 러더 + 차동추력 (클램프된 실 러더 기준) -->
  <g class="sblk" data-code="fcl/mixer.py:Mixer.step"><rect class="body" x="30" y="270" width="36" height="24" rx="12"/><text class="pnum" x="48" y="286">3</text></g>
  <text class="pname" x="48" y="316">요 δr</text>
  <path class="wire" d="M66 282 H246" marker-end="url(#aw-mix)"/>
  <g class="sblk" data-code="fcl/mixer.py:Mixer.step"><rect class="body" x="250" y="256" width="110" height="52" rx="3"/>
    <path d="M262 298 H278 L332 266 H348" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="305" y="326">rudder_lo~hi</text>
  <path class="wire" d="M360 282 H796" marker-end="url(#aw-mix)"/>
  <circle class="branch" cx="400" cy="282" r="3.2"/>
  <g class="sblk" data-code="fcl/mixer.py:Mixer.step"><rect class="body" x="800" y="270" width="36" height="24" rx="12"/><text class="pnum" x="818" y="286">5</text></g>
  <text class="pname" x="818" y="314">러더</text>
  <path class="wire" d="M400 282 V353 H416" marker-end="url(#aw-mix)"/>
  <g class="sblk" data-code="fcl/mixer.py:Mixer.step"><polygon class="body" points="420,330 420,376 500,353"/></g>
  <text class="bname" x="460" y="322" data-gain="k_diff_thr">× k_diff_thr</text>
  <text class="bname" x="460" y="394">클램프된 실 러더 기준</text>
  <path class="wire" d="M500 353 H620 V384" marker-end="url(#aw-mix)"/>
  <text class="siglabel" x="575" y="345">d</text>
  <g class="sblk" data-code="fcl/mixer.py:Mixer.step"><rect class="body" x="30" y="408" width="36" height="24" rx="12"/><text class="pnum" x="48" y="424">4</text></g>
  <text class="pname" x="48" y="454">집합 스로틀 δt</text>
  <path class="wire" d="M66 420 H556" marker-end="url(#aw-mix)"/>
  <g class="sblk" data-code="fcl/mixer.py:Mixer.step"><rect class="body" x="560" y="388" width="160" height="64" rx="3"/>
    <text class="ttl" x="640" y="408" style="font-size:13px">차동 분배</text>
    <text class="ttl2" x="640" y="426">좌 = δt − d · 우 = δt + d</text>
    <text class="ttl2" x="640" y="442">출력 0~1 클립</text></g>
  <path class="wire" d="M720 406 H796" marker-end="url(#aw-mix)"/>
  <g class="sblk" data-code="fcl/mixer.py:Mixer.step"><rect class="body" x="800" y="394" width="36" height="24" rx="12"/><text class="pnum" x="818" y="410">6</text></g>
  <path class="wire" d="M720 434 H796" marker-end="url(#aw-mix)"/>
  <g class="sblk" data-code="fcl/mixer.py:Mixer.step"><rect class="body" x="800" y="422" width="36" height="24" rx="12"/><text class="pnum" x="818" y="438">7</text></g>
  <text class="pname" x="818" y="470">스로틀 ×2 (좌·우)</text>
  <text class="canvas-note" x="24" y="502">※ 재구성 항등: 평균 = δe · (좌−우)/2 = δa — 믹싱이 정보를 잃지 않음 · rate 한계는 작동기(M5) 소관 · SurfaceCommand 순서 [내좌, 외좌, 내우, 외우]</text>
</svg>`,
    flow: {
      lead: "δe·δa → 좌우 엘레본 4면 · δr → 러더 + 차동추력 d · δt ∓ d → 좌우 스로틀",
      reads: [
        "SCAS의 세 축 명령이 들어온다 — 피치 δe(①)·롤 δa(②)·요 δr(③), 그리고 AP의 집합 스로틀 δt(④).",
        "위쪽에서 δe와 δa가 <b>더해지고 빼진다</b>: 좌측 = δe + δa, 우측 = δe − δa. 같은 면이 피치와 롤을 나눠 쓴다.",
        "각각 elevon_lo~hi로 클립해 네 면으로 나간다 — 내좌·외좌·내우·외우(①~④). 내측과 외측은 1:1 고정이다.",
        "δr은 rudder_lo~hi로 클립해 러더(⑤)로 간다.",
        "<b>클램프된 실 러더</b>에 k_diff_thr를 곱한 것이 차동추력 d다 — 클립 전 명령이 아니라 클립 후 값이 기준이다.",
        "좌 = δt − d, 우 = δt + d로 나누고 0~1 클립해 좌우 스로틀(⑥⑦)로 나간다. <b>이 기체에서는 k_diff_thr = 0이라 d도 0</b>이고, 두 출력이 같은 값이 된다 — 그 둘을 추진 블록이 다시 평균 내므로 결국 δt가 그대로 간다. 구조는 그려져 있지만 지금 형상에서는 놀고 있는 경로다.",
      ],
      why: [
        "피치와 롤이 <b>같은 네 면을 나눠 쓴다</b>는 것이 이 그림의 제약 전부다. 델타윙에는 승강타와 보조익이 따로 없다. 한 축이 타면 여유를 다 쓰면 다른 축에 남는 것이 없고, SCAS의 out_lo~hi를 축마다 정하는 일이 여기서 의미를 갖는다.",
        "요축이 <b>러더뿐</b>인 것은 이 기체가 단발 중심선이기 때문이다 — 좌우 추력차를 낼 엔진이 없어 k_diff_thr = 0이다. 그런데도 배분 구조를 지우지 않았다: 쌍발 형상을 물리면 계수만 되살리면 되고, 0인 계수는 그림에서 <b>무엇이 빠져 있는지</b>를 말해 준다.",
        "그 배분이 <b>클램프된 실 러더</b>를 기준으로 하는 이유: 러더가 이미 포화해 못 내는 명령에 추력이 반응하면, 화면의 러더 명령과 실제 요 모멘트가 어긋난다. 명령이 아니라 실제로 나간 것에 비례시킨다.",
        "재구성 항등이 성립한다 — 네 면의 평균이 δe, (좌−우)/2가 δa다. 고정 행렬 믹싱이라 클립 전이라면 <b>정보가 없어지지 않는다</b>: 타면각에서 축 명령을 되짚을 수 있다.",
        "rate 한계가 여기 없는 것은 그것이 작동기 소관이기 때문이다. 믹서는 각도를 나누기만 한다 — 시간은 다음 블록의 일이다.",
      ],
    },
    notes: `
<h4>설계 노트</h4>
<ul>
  <li>용어: 현 구현은 고정 행렬 <b>엘레본 믹싱</b> — 여유자유도 <b>최적 배분(제어 할당, control allocation)</b>으로의 승격은 추후 확장 <span class="chip dft">기본값 01 §2.2</span></li>
  <li>좌측(내·외) = δe + δa, 우측(내·외) = δe − δa — 내/외측 쌍 1:1 고정, 면별 elevon_lo~hi 클립 <span class="chip dft">기본값</span></li>
  <li>요축: <b>이 기체는 러더뿐이다</b>(rudder_lo~hi 클립) — 단발 중심선이라 차동추력 계수 k_diff_thr = 0이다. 배분 구조는 남아 있다: d = k_diff_thr × <b>클램프된 실 러더</b>, 좌우 스로틀 = δt ∓ d — 쌍발 형상을 물리면 계수만 되살리면 된다. 러더가 내지 못하는 명령에 추력이 반응하지 않음 · 포화 시 추력 인계는 별도 설계 <span class="chip tbd">TBD</span></li>
  <li>스로틀 좌/우 = δt ∓ d (0~1 클립) — 데모 프로파일 부호 기준 k&gt;0가 러더 보조 방향</li>
  <li>4면 배치(내/외측 쌍 여부) · 믹싱 비율 · 타면각 한계 실값 <span class="chip tbd">TBD</span> — 기체 데이터 확인 시 · rate 한계는 작동기 모델(M5) 소관</li>
</ul>`,
  },

  // ── 작동기 ───────────────────────────────────────────────────────────
  actuator: {
    tag: "HW 모델", tagBg: "#5f6b78",
    title: "작동기", eng: "Actuator — 2차계 모델 (파라미터화)",
    chips: ["dft", "tbd"],
    svg: `
<svg viewBox="0 0 900 220" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-act" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <g class="sblk" data-code="plant/actuator.py:SecondOrderActuator.step"><rect class="body" x="30" y="88" width="36" height="24" rx="12"/><text class="pnum" x="48" y="104">1</text></g>
  <text class="pname" x="48" y="128">δ_cmd</text>
  <path class="wire" d="M66 100 H136" marker-end="url(#aw-act)"/>
  <g class="sblk" data-code="plant/actuator.py:SecondOrderActuator.step"><rect class="body" x="140" y="64" width="190" height="72" rx="3"/>
    <text class="ttl2" x="235" y="90" style="font-size:13px">ωn²</text>
    <line x1="170" y1="98" x2="300" y2="98" stroke="#111" stroke-width="1.4"/>
    <text class="ttl2" x="235" y="118" style="font-size:12px">s² + 2ζωn·s + ωn²</text></g>
  <text class="bname" x="235" y="156">2차계 — wn <tspan data-p="wn">30</tspan> rad/s · ζ <tspan data-p="zeta">0.7</tspan></text>
  <path class="wire" d="M330 100 H396" marker-end="url(#aw-act)"/>
  <g class="sblk" data-code="plant/actuator.py:SecondOrderActuator.step"><rect class="body" x="400" y="70" width="100" height="60" rx="3"/>
    <path d="M412 118 L438 82 L488 82" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="450" y="150">rate_max <tspan data-p="rate_max">10</tspan> rad/s (≥ 10 요구)</text>
  <path class="wire" d="M500 100 H566" marker-end="url(#aw-act)"/>
  <g class="sblk" data-code="plant/actuator.py:SecondOrderActuator.step"><rect class="body" x="570" y="70" width="100" height="60" rx="3"/>
    <path d="M580 116 H598 L642 84 H660" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="620" y="150">위치 한계 = 믹서 타면 한계</text>
  <path class="wire" d="M670 100 H736" marker-end="url(#aw-act)"/>
  <g class="sblk" data-code="plant/actuator.py:SecondOrderActuator.step"><rect class="body" x="740" y="88" width="36" height="24" rx="12"/><text class="pnum" x="758" y="104">1</text></g>
  <text class="pname" x="758" y="128">δ (타면 변위)</text>
</svg>`,
    flow: {
      lead: "δ_cmd → 2차계(wn·ζ) → rate 한계 → 위치 한계 → δ",
      reads: [
        "믹서가 준 타면각 명령 δ_cmd가 ①로 들어온다.",
        "2차계 ωn²/(s² + 2ζωn·s + ωn²)를 지난다 — wn 30 rad/s · ζ 0.7. 여기서 명령과 실제 사이에 <b>시간</b>이 생긴다.",
        "rate_max 10 rad/s로 변화율을 자른다.",
        "위치 한계로 한 번 더 자른다 — 이 값은 믹서의 타면 한계와 같아야 한다.",
        "나온 δ가 실제 타면 변위이고, 기체로 간다. 이 블록 뒤로는 제어가 개입할 자리가 없다.",
      ],
      why: [
        "이 블록이 <b>제어 대역폭의 천장</b>이다. 위에서 아무리 빠른 게인을 골라도 타면이 그 속도로 못 움직이면 소용이 없다. 위상지연이 여기서 생기고, 그 지연이 그대로 SCAS의 위상여유를 깎는다.",
        "rate 한계가 특히 위험한 이유: 포화하면 명령이 <b>삼각파로 잘려 실효 위상지연이 더 커진다</b>. M11 폐루프 스터디에서 rate 3 rad/s는 항법 지연(20 ms)·잡음과 결합해 피치·롤 리밋사이클을 만들었고 α가 실속 경계를 넘었다. rate ≥ 10 rad/s가 요구 사양이 된 근거가 그 실측이다.",
        "값이 전부 가정값인 이유는 실기체 작동기 특성 데이터가 없기 때문이다. 그래서 파라미터로 열어 두었고, 마진 해석에 작동기를 포함할지도 고를 수 있다.",
        "위치 한계를 믹서와 맞춰야 하는 이유: 어긋나면 명령이 <b>두 번</b> 잘려 화면의 타면 명령과 실제 변위가 달라 보인다.",
      ],
    },
    notes: `
<h4>설계 노트</h4>
<ul>
  <li>특성 데이터 미보유 → <b>2차계 가정값</b>으로 시작, 파라미터화 <span class="chip dft">기본값</span> — wn 30 rad/s · ζ 0.7 · rate 10 rad/s</li>
  <li><b>rate ≥ 10 rad/s 요구 사양</b> [도출 01 v0.13] — M11 폐루프 스터디: rate 3 rad/s는 항법 지연(20 ms)·잡음과 결합 시 피치·롤 리밋사이클 유발(α 실속 경계 초과). 실기체 작동기 선정 시 필수 확인</li>
  <li>대역폭 · rate/position limit 실값 <span class="chip tbd">TBD</span> — 데이터 확보 시 대체</li>
  <li>실행값 편집은 시뮬 탭 '작동기' 그룹 (마진 해석의 작동기 포함 여부 선택도 지원)</li>
</ul>`,
  },

  // ── 기체 동역학 (설계 ①) ─────────────────────────────────────────────
  plant: {
    tag: "설계 ①", tagBg: "#7c3aed",
    title: "기체 동역학 (6DOF) — 트림 · 선형해석의 기반", eng: "Aircraft Dynamics · 델타윙 단발",
    chips: ["ok", "dft"],
    svg: `
<svg viewBox="0 0 1000 600" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="aw-pl" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker>
    <marker id="as-pl" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#8a97a5"/></marker>
  </defs>
  <g class="sblk" data-code="plant/aircraft.py:Aircraft.fm"><rect class="body" x="30" y="96" width="36" height="24" rx="12"/><text class="pnum" x="48" y="112">1</text></g>
  <text class="pname" x="48" y="140">타면 변위</text>
  <path class="wire" d="M66 108 H146" marker-end="url(#aw-pl)"/>
  <g class="blk" data-child="aero" data-code="plant/aero.py:AeroModel" tabindex="0"><rect class="body" x="150" y="60" width="290" height="96" rx="3"/>
    <text class="ttl" x="295" y="82" style="font-size:13px">공력 — AeroModel</text>
    <text class="ttl2" x="295" y="100">DB 계수 → 동체축 {CX·CY·CZ·Cl·Cm·Cn}</text>
    <text class="ttl2" x="295" y="116">무차원 p̂·q̂·r̂ = pb/2V · qc̄/2V · rb/2V</text>
    <text class="ttl2" x="295" y="132">F = q̄S·C · M = q̄S·[b·Cl, c̄·Cm, b·Cn]</text>
    <text class="ttl2" x="295" y="148">ρ·a ← ISA(h) — q̄=½ρV² · 클릭 → 내부</text></g>
  <g class="sblk" data-code="plant/aircraft.py:Aircraft.fm"><rect class="body" x="30" y="208" width="36" height="24" rx="12"/><text class="pnum" x="48" y="224">2</text></g>
  <text class="pname" x="48" y="252">스로틀 [좌, 우]</text>
  <path class="wire" d="M66 220 H146" marker-end="url(#aw-pl)"/>
  <g class="blk" data-child="prop" data-code="plant/prop.py:SingleEngine" tabindex="0"><rect class="body" x="150" y="184" width="290" height="72" rx="3"/>
    <text class="ttl" x="295" y="206" style="font-size:13px">추진 — SingleEngine</text>
    <text class="ttl2" x="295" y="226">단발 중심선 · 추력 맵 [기본 max_thrust·δt]</text>
    <text class="ttl2" x="295" y="244">M = r×F (요 없음) · 클릭 → 내부</text></g>
  <g class="sblk" data-code="env/atmosphere.py:isa_atmosphere plant/eom.py:gravity_body"><rect class="body" x="150" y="286" width="290" height="64" rx="3"/>
    <text class="ttl" x="295" y="308" style="font-size:13px">환경 — ISA 대기 · 중력</text>
    <text class="ttl2" x="295" y="328">f_grav = C_bn·[0, 0, m·g] (동체축)</text>
    <text class="ttl2" x="295" y="344">ρ · 음속 a — 고도 h로 조회 (공력 소비)</text></g>
  <path class="wire" d="M440 108 H460 V150 H486" marker-end="url(#aw-pl)"/>
  <path class="wire" d="M440 220 H486" marker-end="url(#aw-pl)"/>
  <path class="wire" d="M440 318 H460 V250 H486" marker-end="url(#aw-pl)"/>
  <g class="sblk" data-code="plant/aircraft.py:Aircraft.fm"><rect class="body" x="490" y="120" width="110" height="160" rx="3"/>
    <text class="ttl" x="545" y="192">Σ F_b</text>
    <text class="ttl" x="545" y="214">· M_b</text></g>
  <path class="wire" d="M600 200 H656" marker-end="url(#aw-pl)"/>
  <g class="blk" data-child="eom" data-code="plant/eom.py:RigidBody" tabindex="0"><rect class="body" x="660" y="96" width="270" height="140" rx="3"/>
    <text class="ttl" x="795" y="120" style="font-size:13px">6DOF 강체 — RigidBody · RK4</text>
    <text class="ttl2" x="795" y="142">x(13) = [p_n · v_b · q_nb · ω_b]</text>
    <text class="ttl2" x="795" y="160">ṗ = C_nb·v · v̇ = F/m − ω×v</text>
    <text class="ttl2" x="795" y="178">q̇ = ½ q⊗(0,ω) · ω̇ = J⁻¹(M − ω×Jω)</text>
    <text class="ttl2" x="795" y="196">RK4 dt 10 ms · q 재정규화 · 클릭 → 내부</text></g>
  <path class="wire" d="M930 166 H948" marker-end="url(#aw-pl)"/>
  <g class="sblk" data-code="common/contracts.py:VehicleState"><rect class="body" x="952" y="154" width="36" height="24" rx="12"/><text class="pnum" x="970" y="170">1</text></g>
  <text class="pname" x="952" y="202">참값 상태</text>
  <text class="pname" x="925" y="250">→ 항법만 (참값 차단)</text>
  <circle class="branch" cx="938" cy="166" r="3.2"/>
  <path class="wire soft" d="M938 166 V36 H295 V56" marker-end="url(#as-pl)"/>
  <text class="siglabel" x="610" y="28">상태 피드백 (참값): v_b · ω_b · q_nb · h</text>
  <g class="blk" data-child="mass" data-code="plant/mass.py:FuelMass" tabindex="0"><rect class="body" x="660" y="340" width="280" height="72" rx="3"/>
    <text class="ttl" x="800" y="362" style="font-size:13px">질량특성 — FuelMass.at(fuel)</text>
    <text class="ttl2" x="800" y="382">m · cg · J — 잔여 연료 선형 보간</text>
    <text class="ttl2" x="800" y="400">스텝 사이 갱신 [준정적] · 클릭 → 내부</text></g>
  <path class="wire soft" d="M800 340 V240" marker-end="url(#as-pl)"/>
  <text class="siglabel" x="836" y="300">m · J</text>
  <path class="wire soft" d="M660 376 H470 V340 H444" marker-end="url(#as-pl)"/>
  <text class="siglabel" x="556" y="368">m (중력)</text>
  <rect x="150" y="470" width="520" height="56" rx="8" fill="none" stroke="#7c3aed" stroke-width="1.4" stroke-dasharray="6 4"/>
  <text class="annot" x="410" y="494" text-anchor="middle" fill="#7c3aed">① 이 플랜트 기반 설계 1단계 — 트림 (100+ 케이스 배치)</text>
  <text class="annot" x="410" y="514" text-anchor="middle" fill="#7c3aed">→ 구간 선형화 → 고유치·감쇠비 · 이득·위상여유 마진 맵</text>
  <text class="canvas-note" x="24" y="560">※ 바람 0 가정 (v_air = v_b) — 바람·난류(Dryden)는 확장 항목 · 공력 부호·기준점은 DB가 정의 — 코드 무가정 (풍축 CL·CD는 변환 헬퍼)</text>
  <text class="canvas-note" x="24" y="580">※ 모멘트 CG 기준점 이전은 DB 규격 확정 시 조립 지점에서 [TBD] · 오일러 12-상태 미분도 제공 — 트림·수치섭동 선형화(M9) 전용</text>
</svg>`,
    flow: {
      lead: "타면 변위·스로틀 → 공력 + 추진 + 중력 → ΣF·ΣM → 6DOF RK4 → 참값 상태",
      reads: [
        "입력은 둘이다 — 작동기가 <b>실제로 움직인</b> 타면 변위(①)와 스로틀(②). 명령이 아니라 변위다.",
        "세 갈래가 힘과 모멘트를 만든다: 공력(DB 계수를 동체축 F·M으로), 추진(스로틀을 추력으로 — 중심선 1기라 모멘트는 0), 환경(중력을 동체축으로 내린 것).",
        "ΣF_b · ΣM_b로 합산한다 — 여기가 이 그림의 허리다. 어떤 힘이든 이 지점을 지나야 기체를 움직인다.",
        "6DOF 강체가 RK4(dt 10 ms)로 적분한다. 상태는 13개 — [p_n · v_b · q_nb · ω_b].",
        "나온 참값 상태는 <b>항법으로만</b> 간다(①). 제어로 곧장 가는 선이 이 그림에 없다.",
        "동시에 상태가 <b>왼쪽으로 되돌아온다</b> — v_b·ω_b·q_nb·h가 공력과 환경으로. 힘이 상태에 의존한다는 뜻이고, 이 되먹임이 이 그림을 미분방정식으로 만든다.",
        "아래에서 질량특성이 m·J를 준다. 연료가 줄면 스텝 사이에 갱신된다.",
      ],
      why: [
        "이 페이지가 <b>설계 1단계</b>인 이유는 여기가 제어기가 아니라 제어할 <b>대상</b>이기 때문이다. 트림을 잡고 선형화해 고유치·마진을 보는 일이 여기서 끝나야 위층 게인이 의미를 갖는다. 순서를 뒤집으면 무엇을 상대로 튜닝하는지 모르는 채 숫자를 만지게 된다.",
        "참값이 항법으로만 나가는 것은 이 저장소의 <b>참값 차단 계약</b>이다. 제어가 참값을 보면 항법 오차가 0인 세상에서 게인을 고르게 된다.",
        "상태 되먹임 화살표가 왼쪽으로 도는 이유: 공력계수가 α·β·p̂·q̂·r̂의 함수라 힘이 상태에 의존한다. 그래서 RK4가 부단계 k1~k4마다 fm(x)를 <b>다시</b> 부른다 — 한 번 계산해 네 번 쓰면 더 이상 RK4가 아니다.",
        "부호를 코드가 정하지 않는다 — 공력 DB가 정의한다. 코드가 모멘트 부호를 가정하면 DB가 바뀔 때 조용히 반대로 난다.",
      ],
    },
    notes: `
<h4>플랜트</h4>
<ul>
  <li>형상: <b>델타윙, 단발 중심선</b> · 조종면 엘레본×4 + 러더×1 · <b>요축 효과기는 러더뿐</b> — 중심선 1기는 좌우 추력차를 못 내므로 믹서의 차동추력 계수가 0이다 <span class="chip ok">확정</span> (정본은 시각화 모델 models/shahed-136 · 종전 쌍발 상정에서 전환)</li>
  <li>공력: CFD 기반 DB — 축: <span class="mono">Mach, α, β, 타면각, 고도</span> (정미 + 동미계수) <span class="chip ok">확정</span> · 현재는 데모 프로파일 (CFD DB 결선 대기) · 보간/외삽 정책 <span class="chip tbd">TBD</span></li>
  <li>실속: <b>명시적 실속 경계 테이블</b> <span class="mono">α_stall = f(Mach, 형상조건)</span> — 공력팀 정본 <span class="chip ok">확정</span></li>
  <li>환경: WGS-84, ISA <span class="chip ok">확정</span> (바람/난류 Dryden은 추후 확장) · RK4 dt 10 ms <span class="chip ok">확정 02 §6</span></li>
  <li>공력·추진·6DOF·질량특성 내부는 블록 클릭 — 층3</li>
  <li><b>지면(스키드 접촉·발사 레일)</b>은 선택 항목 — 활주로를 켠 런에서만 붙는다. 접촉은 <span class="mono">fm</span>의 네 번째 항(공력+추진+중력에 이어)이고 <b>착륙장치의 M += r×F가 여기서 처음 실제로 걸린다</b>. 레일은 힘이 아니라 <b>구속</b>이라 RK4를 타지 않고 등가속 해석해로 전진한다. 공력 DB 기준점 이전은 규격 미확정이라 여전히 <span class="chip tbd">TBD</span></li>
</ul>
<h4>설계 1단계 — 트림 · 선형해석</h4>
<ul>
  <li>트림: 비행조건별 구속조건 하 비용함수 최소화 — 수평정상비행부터, 정상선회·상승은 추후 <span class="chip ok">확정</span></li>
  <li>케이스: 트림 컨디션 × 속도 × 고도 × 연료량 → <b>100+ 케이스 배치</b> · 자동 판정 플래그(잔차·포화·α 여유·연속성) <span class="chip dft">기본값 01 §4.1</span></li>
  <li>선형화: 트림점별 구간 선형화(수치섭동) · 종축 / 횡·방향축 분리 <span class="chip ok">확정</span> · 작동기·지연 포함이 기본(제외 마진은 낙관적) <span class="chip dft">기본값 01 §4.2</span></li>
  <li>평가: 고유치·감쇠비(단주기·장주기·더치롤·롤·스파이럴) · 이득·위상여유 <span class="chip dft">기본값</span> · <b>마진 맵</b>(Mach-고도-연료 격자) <span class="chip ok">확정</span></li>
</ul>`,

    children: {
      aero: {
        crumb: "공력",
        title: "공력 — AeroModel", eng: "공력 DB 계수 함수 소비 · 무차원화·차원화 담당 (M5.aero)",
        chips: ["ok", "tbd"],
        svg: `
<svg viewBox="0 0 960 440" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="aw-paero" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker>
    <marker id="as-paero" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#8a97a5"/></marker>
  </defs>
  <g class="sblk" data-code="plant/aero.py:AeroModel.forces"><rect class="body" x="30" y="96" width="36" height="24" rx="12"/><text class="pnum" x="48" y="112">1</text></g>
  <text class="pname" x="48" y="140">v_b · ω_b</text>
  <path class="wire" d="M66 108 H106" marker-end="url(#aw-paero)"/>
  <g class="sblk" data-code="common/frames.py:wind_angles"><rect class="body" x="110" y="72" width="200" height="72" rx="3"/>
    <text class="ttl" x="210" y="94" style="font-size:13px">바람각 — wind_angles</text>
    <text class="ttl2" x="210" y="114">V · α · β 산출 (바람 0: v_air = v_b)</text>
    <text class="ttl2" x="210" y="132">V = 0 → 힘·모멘트 0 (가드)</text></g>
  <path class="wire" d="M310 108 H336" marker-end="url(#aw-paero)"/>
  <g class="sblk" data-code="plant/aero.py:AeroModel.forces"><rect class="body" x="340" y="72" width="220" height="72" rx="3"/>
    <text class="ttl" x="450" y="94" style="font-size:13px">무차원 각속도</text>
    <text class="ttl2" x="450" y="114">p̂ = pb/2V · q̂ = qc̄/2V</text>
    <text class="ttl2" x="450" y="132">r̂ = rb/2V</text></g>
  <path class="wire" d="M560 108 H606" marker-end="url(#aw-paero)"/>
  <g class="sblk" data-code="plant/aero.py:AeroModel"><rect class="body" x="610" y="60" width="270" height="96" rx="3"/>
    <text class="ttl" x="745" y="82" style="font-size:13px">coef_fn — 공력 DB 조회</text>
    <text class="ttl2" x="745" y="102">입력 α·β·V·mach·p̂·q̂·r̂ + 타면각</text>
    <text class="ttl2" x="745" y="120">출력 동체축 {CX·CY·CZ·Cl·Cm·Cn}</text>
    <text class="ttl2" x="745" y="138">부호·기준점은 DB 정의 — 코드 무가정</text></g>
  <path class="wire" d="M745 156 V196" marker-end="url(#aw-paero)"/>
  <g class="sblk" data-code="plant/aero.py:AeroModel.forces"><rect class="body" x="610" y="200" width="270" height="76" rx="3"/>
    <text class="ttl" x="745" y="222" style="font-size:13px">차원화 — q̄ = ½ρV²</text>
    <text class="ttl2" x="745" y="242">F_b = q̄S·[CX, CY, CZ]</text>
    <text class="ttl2" x="745" y="258">M_b = q̄S·[b·Cl, c̄·Cm, b·Cn]</text></g>
  <path class="wire" d="M745 276 V316" marker-end="url(#aw-paero)"/>
  <g class="sblk" data-code="plant/aero.py:AeroModel.forces"><rect class="body" x="727" y="320" width="36" height="24" rx="12"/><text class="pnum" x="745" y="336">1</text></g>
  <text class="pname" x="745" y="364">F_b · M_b → Σ</text>
  <g class="sblk" data-code="plant/aero.py:AeroModel.forces"><rect class="body" x="30" y="196" width="36" height="24" rx="12"/><text class="pnum" x="48" y="212">2</text></g>
  <text class="pname" x="95" y="240">타면각 (작동기 후)</text>
  <path class="wire" d="M66 208 H590 V102 H606" marker-end="url(#aw-paero)"/>
  <g class="sblk" data-code="plant/aircraft.py:Aircraft.fm env/atmosphere.py:isa_atmosphere"><rect class="body" x="110" y="290" width="200" height="52" rx="3"/>
    <text class="ttl2" x="210" y="312" style="font-weight:700">ISA(h) — ρ · mach</text>
    <text class="ttl2" x="210" y="330">플랜트 조립(fm)이 주입</text></g>
  <path class="wire soft" d="M310 316 H560 V240 H606" marker-end="url(#as-paero)"/>
  <text class="canvas-note" x="24" y="408">※ 풍축 DB(CL·CD) 헬퍼 wind_to_body_coeffs [기본값 변환]: CX = CL·sinα − CD·cosα·cosβ · CY = −CD·sinβ · CZ = −CL·cosα − CD·sinα·cosβ</text>
  <text class="canvas-note" x="24" y="428">※ 기준값 S·c̄·b 양수 검증 (생성 거부) · 현재 데모 프로파일 — CFD DB 규격 확정 시 M3 Table 조회를 이 인터페이스로 래핑 [TBD 02 §5.1]</text>
</svg>`,
        flow: {
          lead: "v_b·ω_b·타면각 → 바람각(V·α·β) → 무차원화 → DB 계수 → 차원화 → F_b·M_b",
          reads: [
            "상태 v_b·ω_b(①)와 작동기 후 타면각(②)이 들어온다.",
            "먼저 바람각을 낸다 — V·α·β. 바람 0 가정이라 v_air = v_b다. V = 0이면 힘·모멘트를 0으로 두는 가드가 붙어 있다.",
            "각속도를 <b>무차원화</b>한다: p̂ = pb/2V · q̂ = qc̄/2V · r̂ = rb/2V.",
            "이 값들과 타면각으로 공력 DB를 조회해 동체축 계수 {CX·CY·CZ·Cl·Cm·Cn}를 받는다.",
            "동압 q̄ = ½ρV²로 차원화한다 — F_b = q̄S·[CX, CY, CZ], M_b = q̄S·[b·Cl, c̄·Cm, b·Cn].",
            "ρ와 mach는 ISA(h)에서 오는데, 이 블록이 직접 조회하지 않고 플랜트 조립부가 <b>주입</b>한다.",
          ],
          why: [
            "각속도를 무차원화하는 이유: 동미계수는 무차원 각속도의 함수로 정의된다. 그대로 넣으면 같은 회전이 속도에 따라 다른 계수를 부르고 DB의 축과 어긋난다.",
            "V = 0 가드가 필요한 것은 그 무차원화에 V가 <b>분모로</b> 들어가기 때문이다 — 지상 정지 상태에서 0으로 나눈다.",
            "인터페이스가 동체축 계수를 <b>직접</b> 받는 것이 이 블록의 계약이다. 부호와 기준점은 DB가 정의하고 코드는 가정하지 않는다. 풍축(CL·CD) 형태의 DB를 위한 변환 헬퍼는 따로 두었다 — 기본 경로에 넣으면 그 변환이 곧 가정이 된다.",
            "ρ를 주입받는 이유: 같은 ISA 모델에서 나온 값을 제어법칙도 쓴다(고도 → 음속 → mach로 리미터·게인 스케줄이 소비). 블록마다 따로 조회하면 같은 고도에서 서로 다른 대기를 쓰는 일이 생긴다 — 추진은 지금 속도·밀도에 의존하지 않아 이 값을 안 쓴다.",
          ],
        },
        notes: `
<h4>설계 노트</h4>
<ul>
  <li>규약 원칙: 계수·모멘트 부호는 <b>공력 DB가 정의</b> — 코드는 가정하지 않음 → coef_fn은 동체축 계수 {CX·CY·CZ·Cl·Cm·Cn}를 직접 반환 <span class="chip ok">확정 conventions.md</span></li>
  <li>풍축(양력·항력) 형태 DB를 위한 <span class="mono">wind_to_body_coeffs</span> 헬퍼 제공 <span class="chip dft">기본값 변환식</span></li>
  <li>무차원 각속도 p̂=pb/2V · q̂=qc̄/2V · r̂=rb/2V — 동미계수 축 · V=0이면 출력 0 (0 나눗셈 가드)</li>
  <li>실제 CFD DB 축 규격 <span class="chip tbd">TBD 02 §5.1</span> — 확정 시 M3 Table 조회를 이 인터페이스로 감쌈 · 모멘트 기준점 CG 이전은 플랜트 조립 지점에서 <span class="chip tbd">TBD</span></li>
</ul>`,
      },
      prop: {
        crumb: "추진",
        title: "추진 — SingleEngine", eng: "단발 중심선 · 스로틀-추력 맵 + 추력선 오프셋 모멘트 (M5.prop)",
        chips: ["ok", "dft", "tbd"],
        // 하위 페이지 스키마 — 루트(plant)는 스키마가 없어서, 여기 안 걸면 추력·엔진
        // 배치가 화면 어디에도 안 나온다. 읽기 전용이다 (views/blocks.js renderParams)
        schema: { category: "propulsion", name: "SingleEngine" },
        svg: `
<svg viewBox="0 0 960 270" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-pprop" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <g class="sblk" data-code="plant/prop.py:SingleEngine.forces"><rect class="body" x="30" y="92" width="36" height="24" rx="12"/><text class="pnum" x="48" y="108">1</text></g>
  <text class="pname" x="48" y="136">스로틀 [좌, 우]</text>
  <path class="wire" d="M66 104 H106" marker-end="url(#aw-pprop)"/>
  <g class="sblk" data-code="plant/prop.py:SingleEngine.forces"><rect class="body" x="110" y="78" width="150" height="52" rx="3"/>
    <text class="ttl" x="185" y="97" style="font-size:13px">0~1 클립</text>
    <text class="ttl2" x="185" y="115">좌·우 각각 (규약)</text></g>
  <path class="wire" d="M260 104 H296" marker-end="url(#aw-pprop)"/>
  <g class="sblk" data-code="plant/prop.py:SingleEngine.forces"><rect class="body" x="300" y="78" width="150" height="52" rx="3"/>
    <text class="ttl" x="375" y="97" style="font-size:13px">평균 (집합)</text>
    <text class="ttl2" x="375" y="115">중심선 1기 — 차분은 버린다</text></g>
  <path class="wire" d="M450 104 H486" marker-end="url(#aw-pprop)"/>
  <g class="sblk" data-code="plant/prop.py:SingleEngine.forces"><rect class="body" x="490" y="78" width="210" height="52" rx="3"/>
    <text class="ttl" x="595" y="97" style="font-size:13px">추력 맵 thrust_map(δt)</text>
    <text class="ttl2" x="595" y="115">기본 <tspan data-p="max_thrust">8000</tspan> N · δt 선형 [기본값]</text></g>
  <path class="wire" d="M700 104 H736" marker-end="url(#aw-pprop)"/>
  <g class="sblk" data-code="plant/prop.py:SingleEngine.forces"><rect class="body" x="740" y="70" width="170" height="68" rx="3"/>
    <text class="ttl" x="825" y="90" style="font-size:13px">추력선 오프셋</text>
    <text class="ttl2" x="825" y="110">r = (0, 0, <tspan data-p="z_offset">0</tspan>) · M = r×F</text>
    <text class="ttl2" x="825" y="128">요 모멘트 없음</text></g>
  <path class="wire" d="M825 138 V166" marker-end="url(#aw-pprop)"/>
  <g class="sblk" data-code="plant/prop.py:SingleEngine.forces"><rect class="body" x="807" y="170" width="36" height="24" rx="12"/><text class="pnum" x="825" y="186">1</text></g>
  <text class="pname" x="825" y="214">F_b · M_b → Σ</text>
  <text class="canvas-note" x="24" y="224">※ 정본 형상은 <tspan style="font-weight:700">중심선 1기</tspan>(models/shahed-136: 2엽 푸셔) — 좌우 추력차로 요를 못 내므로 믹서의 차동추력 계수 k_diff_thr = 0이다</text>
  <text class="canvas-note" x="24" y="244">※ 입력은 SurfaceCommand 규약 (2,)를 그대로 받되 <tspan style="font-weight:700">평균만</tspan> 쓴다 · thrust_map 콜러블 주입 가능 — 실기체 추력 맵 [TBD] 대비 · 속도·밀도 의존 없음</text>
</svg>`,
        flow: {
          lead: "스로틀 [좌, 우] → 0~1 클립 → 평균 → 추력 맵 → 추력선 오프셋 → F_b · M_b",
          reads: [
            "입력은 SurfaceCommand 규약대로 스로틀 <b>[좌, 우] 두 칸</b>이다(①) — 엔진이 하나인데도 계약 폭이 (2,)로 고정이다.",
            "좌·우 각각 0~1로 클립한다 (규약).",
            "<b>평균을 낸다.</b> 중심선 1기라 좌우 차분은 낼 데가 없어 여기서 버려진다 — 이 한 칸이 단발 형상의 전부다.",
            "집합 스로틀을 추력 맵 thrust_map(δt)에 넣는다. 기본은 max_thrust·δt 선형(8000 N)이고, <b>속도·밀도에 의존하지 않는다</b>.",
            "추력선 오프셋으로 모멘트를 만든다 — M = r×F. 지금 r = (0, 0, 0)이라 <b>모멘트가 0</b>이고, 요 모멘트는 특히 없다.",
            "F_b·M_b가 Σ로 나가 공력·중력과 합쳐진다(①).",
          ],
          why: [
            "두 칸을 받아 <b>평균만 쓰는</b> 것이 이 그림에서 볼 것이다. 계약 폭 (2,)를 그대로 두는 이유는 믹서·작동기·로깅이 전부 그 폭에 맞춰져 있어 쌍발로 되돌릴 때 배선을 다시 그리지 않아도 되기 때문이다. 대신 <b>차분이 조용히 사라진다</b> — 믹서의 k_diff_thr = 0이 그 사실을 위층에서 못박는 짝이다. 계수를 켜면 법칙은 요축을 돕는다고 믿는데 기체는 아무것도 안 한다.",
            "총추력을 종전 쌍발과 같게(4 kN × 2 = 8 kN) 둔 것은 <b>전환의 영향을 한 가지로 좁히려는</b> 선택이다. 종방향은 그대로이고 달라진 것은 차동추력 요 모멘트가 사라진 것 하나뿐이라, 무엇을 재튜닝해야 하는지 판단이 선다. 실측에서 러더 변위가 +2~7% 늘었을 뿐(한계 0.35의 30% 이내)이라 요축 재튜닝은 필요 없었다.",
            "속도·밀도 의존이 <b>없다는 것이 이 그림에서 빠져 있는 것</b>이다. 프로펠러는 T ≈ ηP/V라 고속에서 추력이 급감하는데 이 모델은 어느 속도에서나 같은 추력을 낸다 — 고속 구간이 낙관적으로 나온다는 뜻이고, 전용 추력 모델이 들어와야 맞는다.",
            "r = (0, 0, 0)이라 오프셋 블록이 지금은 아무 일도 안 하는데도 남겨 두었다. 추력선이 CG에서 위아래로 어긋나면 <b>스로틀이 피치 모멘트를 만들어</b> 속도 채널과 고도 채널이 커플링되는데, 그 커플링이 생기는 자리가 여기뿐이기 때문이다. 쌍발(TwinEngine)도 같은 이유로 레지스트리에 남아 있다.",
          ],
        },
        notes: `
<h4>설계 노트</h4>
<ul>
  <li><b>단발 중심선</b>이 정본 형상이다 — 시각화 모델(2엽 푸셔 1기)이 기준이고 동역학을 거기 맞췄다. 중심선 1기는 <b>요 모멘트를 못 낸다</b> → 믹서의 차동추력 계수 <span class="mono">k_diff_thr</span> = 0 <span class="chip ok">확정</span></li>
  <li>총추력은 종전 쌍발(4 kN×2)과 같게 뒀다(값은 위 블록도의 추력 맵 — 스키마 연동) — 전환으로 <b>종방향은 바뀌지 않는다</b>. 달라진 것은 차동추력 요 모멘트가 사라진 것 하나다. 실측상 요축 재튜닝은 불필요했다(러더 변위 +2~7%, 한계 0.35의 30% 이내) <span class="chip dft">기본값</span></li>
  <li>입력은 SurfaceCommand 규약 [좌, 우] 0~1 (범위 밖 클립) — 계약 폭이 (2,)로 고정이라 그대로 받되 <b>평균(집합 스로틀)만</b> 쓴다. 갈린 명령의 차분은 중심선 1기가 낼 데가 없다</li>
  <li>스로틀-추력: <span class="mono">thrust_map(δt)</span> 콜러블 주입 가능 — 실기체 추력 맵 데이터 <span class="chip tbd">TBD</span> 대비 · 기본은 max_thrust·δt 선형 <span class="chip dft">기본값</span>. <b>속도·밀도 의존은 없다</b> — 프로펠러는 T ≈ ηP/V로 고속에서 추력이 급감하므로 전용 추력 모델 <span class="chip tbd">TBD 01 §2.6</span>이 들어와야 맞는다</li>
  <li>추력은 동체 +X 정렬 — 추력선 경사(cant)·반토크·자이로·P-factor·후류는 <b>없다</b> (프로펠러 2차 효과 <span class="chip tbd">TBD</span>)</li>
  <li>추력선 오프셋 z는 CG 기준 동체축 — CG 이동 반영은 모멘트 기준점 이전과 같은 조립 지점에서 <span class="chip tbd">TBD</span></li>
  <li>쌍발(<span class="mono">TwinEngine</span>)은 레지스트리에 남아 있다 — 차동추력 요축 보조라는 설계 선택지를 코드에서 지우면 다시 세우는 비용이 크다</li>
</ul>`,
      },
      eom: {
        crumb: "6DOF",
        title: "6DOF 강체 — RigidBody · RK4", eng: "13-상태 쿼터니언 운동방정식 · 고정스텝 RK4 (M5.eom)",
        chips: ["ok", "dft"],
        svg: `
<svg viewBox="0 0 1000 700" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="aw-peom" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker>
    <marker id="as-peom" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#8a97a5"/></marker>
  </defs>
  <g class="sblk" data-code="plant/eom.py:RigidBody.deriv"><rect class="body" x="30" y="96" width="36" height="24" rx="12"/><text class="pnum" x="48" y="112">1</text></g>
  <text class="pname" x="48" y="140">F_b · M_b ← Σ</text>
  <path class="wire" d="M66 108 H106" marker-end="url(#aw-peom)"/>
  <g class="sblk" data-code="plant/eom.py:RigidBody.deriv"><rect class="body" x="110" y="52" width="290" height="112" rx="3"/>
    <text class="ttl" x="255" y="76" style="font-size:13px">상태미분 — RigidBody.deriv</text>
    <text class="ttl2" x="255" y="96">ṗ_n = C_nb·v_b</text>
    <text class="ttl2" x="255" y="112">v̇_b = F_b/m − ω×v_b</text>
    <text class="ttl2" x="255" y="128">q̇ = ½ q ⊗ (0, ω)</text>
    <text class="ttl2" x="255" y="144">ω̇ = J⁻¹(M_b − ω×Jω)</text></g>
  <path class="wire" d="M400 108 H436" marker-end="url(#aw-peom)"/>
  <g class="sblk" data-code="plant/eom.py:rk4_step plant/eom.py:RigidBody.step"><rect class="body" x="440" y="64" width="250" height="88" rx="3"/>
    <text class="ttl" x="565" y="86" style="font-size:13px">RK4 고정스텝 — dt 10 ms</text>
    <text class="ttl2" x="565" y="106">k1~k4 — fm(x) 부단계마다 재평가</text>
    <text class="ttl2" x="565" y="124">x⁺ = x + dt/6·(k1+2k2+2k3+k4)</text>
    <text class="ttl2" x="565" y="140">[확정 02 §6]</text></g>
  <path class="wire" d="M690 108 H726" marker-end="url(#aw-peom)"/>
  <g class="sblk" data-code="common/attitude.py:quat_normalize"><rect class="body" x="730" y="72" width="180" height="64" rx="3"/>
    <text class="ttl" x="820" y="94" style="font-size:13px">쿼터니언 재정규화</text>
    <text class="ttl2" x="820" y="114">스텝마다 — 드리프트 방지</text></g>
  <path class="wire" d="M910 104 H930"/>
  <circle class="branch" cx="930" cy="104" r="3.2"/>
  <path class="wire" d="M934 104 H941" marker-end="url(#aw-peom)"/>
  <g class="sblk" data-code="plant/eom.py:RigidBody.step"><rect class="body" x="945" y="92" width="36" height="24" rx="12"/><text class="pnum" x="963" y="108">1</text></g>
  <text class="pname" x="963" y="136">상태 x(13)</text>
  <g class="sblk" data-code="plant/eom.py:RigidBody.set_mass_inertia"><rect class="body" x="110" y="220" width="330" height="72" rx="3"/>
    <text class="ttl" x="275" y="242" style="font-size:13px">준정적 질량 — set_mass_inertia</text>
    <text class="ttl2" x="275" y="262">FuelMass.at(fuel) 결과 소비 · J⁻¹ 캐시 재계산</text>
    <text class="ttl2" x="275" y="280">스텝 사이 갱신 — J 직접 대입 금지</text></g>
  <path class="wire soft" d="M275 220 V168" marker-end="url(#as-peom)"/>
  <!-- 출력 펼침 — MathWorks 6DOF (Quaternion) 블록의 출력 8종 병기.
       버스 분기 자체는 코드에 없는 도해(nblk)지만, 각 갈래는 실존한다:
       ③⑥⑦은 x의 원소(unpack), ②④⑤는 소비 측 파생 함수(색 블록), ⑧⑨는 엔진
       미구현이라 상태미분 블록에서 회색 점선으로만 나온다(계산 후 폐기와 부합) -->
  <path class="wire" d="M930 104 V250 H547 V281" marker-end="url(#aw-peom)"/>
  <g class="sblk nblk"><rect class="body" x="520" y="285" width="54" height="275" rx="3"/></g>
  <text class="bname" x="547" y="308">버스</text>
  <text class="bname" x="547" y="322">분기</text>
  <path class="wire" d="M574 310 H606" marker-end="url(#aw-peom)"/>
  <g class="sblk" data-code="common/frames.py:body_to_ned"><rect class="body" x="610" y="293" width="190" height="34" rx="3"/>
    <text class="ttl" x="705" y="314" style="font-size:12px">body_to_ned — C_nb·v_b</text></g>
  <path class="wire" d="M800 310 H846" marker-end="url(#aw-peom)"/>
  <g class="sblk" data-code="common/contracts.py:VehicleState.vel_n"><rect class="body" x="850" y="298" width="36" height="24" rx="12"/><text class="pnum" x="868" y="314">2</text></g>
  <text class="pname a-start" x="894" y="314">V_e · 관성계 속도</text>
  <path class="wire" d="M574 355 H846" marker-end="url(#aw-peom)"/>
  <g class="sblk" data-code="plant/eom.py:unpack"><rect class="body" x="850" y="343" width="36" height="24" rx="12"/><text class="pnum" x="868" y="359">3</text></g>
  <text class="pname a-start" x="894" y="359">X_e · pos_n (NED)</text>
  <path class="wire" d="M574 400 H606" marker-end="url(#aw-peom)"/>
  <g class="sblk" data-code="common/attitude.py:quat_to_euler"><rect class="body" x="610" y="383" width="190" height="34" rx="3"/>
    <text class="ttl" x="705" y="404" style="font-size:12px">quat_to_euler</text></g>
  <path class="wire" d="M800 400 H846" marker-end="url(#aw-peom)"/>
  <g class="sblk" data-code="common/contracts.py:VehicleState.euler"><rect class="body" x="850" y="388" width="36" height="24" rx="12"/><text class="pnum" x="868" y="404">4</text></g>
  <text class="pname a-start" x="894" y="404">φ θ ψ · 오일러각</text>
  <path class="wire" d="M574 445 H606" marker-end="url(#aw-peom)"/>
  <g class="sblk" data-code="common/attitude.py:quat_to_dcm"><rect class="body" x="610" y="428" width="190" height="34" rx="3"/>
    <text class="ttl" x="705" y="449" style="font-size:12px">quat_to_dcm — C_bn</text></g>
  <path class="wire" d="M800 445 H846" marker-end="url(#aw-peom)"/>
  <g class="sblk" data-code="common/attitude.py:quat_to_dcm"><rect class="body" x="850" y="433" width="36" height="24" rx="12"/><text class="pnum" x="868" y="449">5</text></g>
  <text class="pname a-start" x="894" y="449">DCM_be (3×3)</text>
  <path class="wire" d="M574 490 H846" marker-end="url(#aw-peom)"/>
  <g class="sblk" data-code="plant/eom.py:unpack"><rect class="body" x="850" y="478" width="36" height="24" rx="12"/><text class="pnum" x="868" y="494">6</text></g>
  <text class="pname a-start" x="894" y="494">V_b · vel_b (동체)</text>
  <path class="wire" d="M574 535 H846" marker-end="url(#aw-peom)"/>
  <g class="sblk" data-code="plant/eom.py:unpack"><rect class="body" x="850" y="523" width="36" height="24" rx="12"/><text class="pnum" x="868" y="539">7</text></g>
  <text class="pname a-start" x="894" y="539">ω_b · omega_b</text>
  <path class="wire note" d="M360 164 V196 H480 V580 H846" marker-end="url(#as-peom)"/>
  <g class="sblk nblk"><rect class="body" x="850" y="568" width="36" height="24" rx="12"/><text class="pnum" x="868" y="584">8</text></g>
  <text class="pname a-start" x="894" y="584">dω_b/dt — 표시 전용</text>
  <path class="wire note" d="M320 164 V208 H466 V620 H846" marker-end="url(#as-peom)"/>
  <g class="sblk nblk"><rect class="body" x="850" y="608" width="36" height="24" rx="12"/><text class="pnum" x="868" y="624">9</text></g>
  <text class="pname a-start" x="894" y="624">A_bb — 표시 전용</text>
  <text class="canvas-note" x="24" y="652">※ 출력 ②~⑨ = MathWorks 6DOF (Quaternion) 블록 출력 병기 — ③⑥⑦은 상태 원소, ②④⑤는 소비 측 파생 함수(색 블록), ⑧⑨(각가속도·동체 가속도)는 엔진 미구현: RK4 안에서 계산되고 버려진다 (표시 전용)</text>
  <text class="canvas-note" x="24" y="672">※ 상태 x(13) = [p_n(3) · v_b(3) · q_nb(4) · ω_b(3)] — NED · 동체 FRD · scalar-first Hamilton [conventions.md] · 중력 포함 여부는 조립자 몫 (플랜트 fm이 포함)</text>
  <text class="canvas-note" x="24" y="692">※ 질량 양수 · J 3×3 대칭 · 주대각 양수 아니면 생성 거부 · 오일러 12-상태 미분(deriv_euler)은 트림·수치섭동 선형화 전용 — θ=±π/2 특이점 근방 금지</text>
</svg>`,
        flow: {
          lead: "F_b·M_b → 상태미분 → RK4(dt 10 ms) → 쿼터니언 재정규화 → x(13) + 파생 출력",
          reads: [
            "합산된 F_b·M_b가 ①로 들어온다.",
            "상태미분을 만든다 — ṗ_n = C_nb·v_b · v̇_b = F_b/m − ω×v_b · q̇ = ½q⊗(0,ω) · ω̇ = J⁻¹(M_b − ω×Jω).",
            "RK4가 k1~k4를 계산한다. 부단계마다 fm(x)를 <b>다시 불러</b> 힘을 재평가한다.",
            "스텝마다 쿼터니언을 재정규화한다.",
            "나온 x(13)이 버스에서 갈라진다 — ③⑥⑦은 상태 원소 그대로, ②④⑤는 소비 측 파생(NED 속도·오일러각·DCM), ⑧⑨는 <b>표시 전용</b>이다.",
            "질량·관성은 옆에서 준정적으로 갱신된다 — set_mass_inertia로만 들어간다.",
          ],
          why: [
            "v̇에 −ω×v가 붙는 이유: 동체축은 <b>회전하는</b> 좌표계라, 그 안에서 본 속도 변화에는 실제 가속 말고 회전 때문에 생기는 항이 섞인다. 그 항을 빼야 F/m이 남는다.",
            "쿼터니언을 매 스텝 재정규화하는 이유: 수치적분은 노름을 정확히 보존하지 못해 조금씩 어긋나고, 누적되면 <b>회전이 아닌 것</b>이 된다. 그 상태로 좌표변환을 하면 벡터 길이가 변한다.",
            "상태가 오일러각이 아니라 쿼터니언인 것은 θ = ±90°의 특이점 때문이다. 오일러 12-상태 미분도 따로 두었지만 트림·수치섭동 선형화 <b>전용</b>이다 — 그 용도에서는 θ가 특이점 근처에 가지 않는다.",
            "J를 직접 대입하면 안 되는 이유: J⁻¹이 캐시되어 있어 낡은 역행렬이 남는다. 갱신 경로를 하나로 좁혀 둔 자리다.",
            "⑧⑨가 표시 전용인 것은 정직하게 그린 것이다 — RK4 안에서 계산되고 버려진다. 있는 것처럼 그려 두면 나중에 소비하려다 없다는 걸 알게 된다.",
          ],
        },
        notes: `
<h4>설계 노트</h4>
<ul>
  <li>상태 벡터 x(13) = [pos_n, vel_b, q_nb, omega_b] — NED · 동체 FRD · 쿼터니언 scalar-first Hamilton <span class="chip ok">확정 conventions.md</span></li>
  <li>고정스텝 <b>RK4 dt 10 ms</b> <span class="chip ok">확정 02 §6</span> — 상태 의존 힘·모멘트 fm(x)를 부단계(k1~k4)마다 재평가 · 스텝마다 쿼터니언 재정규화</li>
  <li>연료 질량·관성 변화는 준정적 — 조립자가 스텝 사이에 <span class="mono">set_mass_inertia</span>로 갱신 (J 직접 대입은 J⁻¹ 캐시를 낡은 값으로 남김 — 금지)</li>
  <li>중력 포함 여부는 조립자 몫 — 플랜트 fm이 gravity_body(C_bn·[0,0,mg])를 합산 <span class="chip dft">기본값</span></li>
</ul>`,
      },
      mass: {
        crumb: "질량특성",
        title: "질량특성 — FuelMass", eng: "잔여 연료 선형 보간 [기본값] — m · cg · J 준정적 (02 §5.5)",
        chips: ["dft", "tbd"],
        svg: `
<svg viewBox="0 0 960 230" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-pmass" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <g class="sblk" data-code="plant/mass.py:FuelMass.at"><rect class="body" x="30" y="92" width="36" height="24" rx="12"/><text class="pnum" x="48" y="108">1</text></g>
  <text class="pname" x="52" y="136">fuel [kg]</text>
  <path class="wire" d="M66 104 H106" marker-end="url(#aw-pmass)"/>
  <g class="sblk" data-code="plant/mass.py:FuelMass.at"><rect class="body" x="110" y="78" width="170" height="52" rx="3"/>
    <text class="ttl" x="195" y="97" style="font-size:13px">범위 클립</text>
    <text class="ttl2" x="195" y="115">0 ~ fuel_max</text></g>
  <path class="wire" d="M280 104 H316" marker-end="url(#aw-pmass)"/>
  <g class="sblk" data-code="plant/mass.py:FuelMass.at"><rect class="body" x="320" y="60" width="300" height="96" rx="3"/>
    <text class="ttl" x="470" y="84" style="font-size:13px">선형 보간 [기본값]</text>
    <text class="ttl2" x="470" y="104">r = f / fuel_max · m = m_empty + f</text>
    <text class="ttl2" x="470" y="122">cg = cg_e + r·(cg_f − cg_e)</text>
    <text class="ttl2" x="470" y="140">J = J_e + r·(J_f − J_e)</text></g>
  <path class="wire" d="M620 104 H846" marker-end="url(#aw-pmass)"/>
  <g class="sblk" data-code="plant/mass.py:FuelMass.at"><rect class="body" x="850" y="92" width="36" height="24" rx="12"/><text class="pnum" x="868" y="108">1</text></g>
  <text class="pname" x="868" y="136">m · cg · J</text>
  <text class="pname" x="850" y="154">→ RigidBody · 중력</text>
  <text class="canvas-note" x="24" y="200">※ 준정적(quasi-static) 취급 [확정 02 §5.5] — 시뮬 루프가 스텝 사이에 at(fuel) 조회 → RigidBody.set_mass_inertia 갱신 (운동방정식 내 ṁ 항 없음)</text>
  <text class="canvas-note" x="24" y="220">※ cg는 모멘트 기준점 CG 이전에서 소비 예정 [TBD — DB 규격 확정 시] · m_empty 양수·fuel_max 음수는 생성 거부 · fuel ← 시뮬 소모 적분</text>
</svg>`,
        flow: {
          lead: "fuel → 범위 클립 → 선형 보간 → m · cg · J",
          reads: [
            "잔여 연료 fuel(①)이 들어와 0~fuel_max로 클립된다.",
            "비율 r = f / fuel_max를 만든다.",
            "m = m_empty + f, cg와 J는 공허↔만재 사이를 r로 선형 보간한다.",
            "나온 m·cg·J가 6DOF 강체(관성)와 중력(질량)으로 간다.",
          ],
          why: [
            "<b>준정적</b>으로 다루는 이유: 운동방정식에 ṁ 항을 넣지 않는다. 연료 소모는 기체 운동보다 훨씬 느려서, 스텝 사이에 값을 갈아 끼우는 것으로 충분하다. 넣으면 방정식이 복잡해지는 만큼의 정확도를 못 얻는다.",
            "질량이 상수가 아니라는 것이 게인 스케줄에 fuel 축이 있는 이유다 — 연료가 줄면 관성이 줄어 <b>같은 타면각이 더 큰 각가속도</b>를 낸다. 만재에서 맞춘 게인이 공허에서 과하다.",
            "선형 보간은 기본값이다. 실제 탱크 형상과 소모 순서가 오면 바뀔 자리이고, 그래서 이 블록이 따로 있다.",
          ],
        },
        notes: `
<h4>설계 노트</h4>
<ul>
  <li>잔여 연료 <b>선형 보간</b> — m = m_empty + f · cg·J는 공허↔만재 사이 비율 보간 <span class="chip dft">기본값 02 §5.5</span> · 범위 밖 fuel은 클립</li>
  <li>준정적 취급: 시뮬 루프가 스텝 사이에 at(fuel) 조회 → RigidBody 질량·관성 갱신 — 운동방정식에 ṁ 항 없음 <span class="chip ok">확정</span></li>
  <li>cg는 모멘트 기준점 CG 이전(aero 조립 지점)에서 소비 예정 <span class="chip tbd">TBD — DB 규격 확정 시</span></li>
</ul>`,
      },
    },
  },

  // ── 항법 (피드백) ────────────────────────────────────────────────────
  nav: {
    tag: "피드백", tagBg: "#0e7c86",
    title: "항법 — 등가 오차 모델", eng: "Navigation (M6 · EKF 미구현 — 인터페이스 개방)",
    chips: ["ok", "dft"],
    svg: `
<svg viewBox="0 0 1000 760" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-nav" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <g class="sblk" data-code="nav/error_model.py:NavErrorModel.step"><rect class="body" x="30" y="128" width="36" height="24" rx="12"/><text class="pnum" x="48" y="144">1</text></g>
  <text class="pname" x="85" y="176">참값 VehicleState</text>
  <path class="wire" d="M66 140 H126" marker-end="url(#aw-nav)"/>
  <g class="sblk" data-code="nav/error_model.py:NavErrorModel.step"><rect class="body" x="130" y="112" width="180" height="56" rx="3"/>
    <text class="ttl" x="220" y="134" style="font-size:13px">갱신 데시메이션</text>
    <text class="ttl2" x="220" y="152"><tspan data-p="update_hz">100</tspan> Hz · 틱 정수배 강제</text></g>
  <path class="wire" d="M310 140 H362" marker-end="url(#aw-nav)"/>
  <circle class="body" data-code="nav/error_model.py:NavErrorModel.step" cx="380" cy="140" r="14"/>
  <text class="sumsign" x="371" y="144">+</text><text class="sumsign" x="380" y="131">+</text><text class="sumsign" x="380" y="153">+</text>
  <g class="sblk" data-code="nav/error_model.py:NavErrorModel.step"><rect class="body" x="250" y="16" width="260" height="70" rx="3"/>
    <text class="ttl" x="380" y="38" style="font-size:13px">1차 마르코프 바이어스 — 위치축</text>
    <text class="ttl2" x="380" y="56">σ 수평 <tspan data-p="bias_std_h">1</tspan> · 수직 <tspan data-p="bias_std_v">1.5</tspan> m · τ <tspan data-p="bias_tau">60</tspan> s</text>
    <text class="ttl2" x="380" y="74">b ← p·b + σ√(1−p²)·w · p=e^(−T/τ)</text></g>
  <path class="wire" d="M380 86 V122" marker-end="url(#aw-nav)"/>
  <g class="sblk" data-code="nav/error_model.py:NavErrorModel.step"><rect class="body" x="250" y="196" width="260" height="70" rx="3"/>
    <text class="ttl" x="380" y="212" style="font-size:13px">백색잡음 (상태별 σ · 수평↔수직 분리)</text>
    <text class="ttl2" x="380" y="230">pos 수평 <tspan data-p="pos_std_h">3</tspan> · 수직 <tspan data-p="pos_std_v">4.5</tspan> m</text>
    <text class="ttl2" x="380" y="246">vel 수평 <tspan data-p="vel_std_h">0.3</tspan> · 수직 <tspan data-p="vel_std_v">0.45</tspan> m/s</text>
    <text class="ttl2" x="380" y="262">각속도 <tspan data-p="rate_std">0.001</tspan> rad/s</text></g>
  <path class="wire" d="M380 196 V158" marker-end="url(#aw-nav)"/>
  <path class="wire" d="M394 140 H426" marker-end="url(#aw-nav)"/>
  <g class="sblk" data-code="nav/error_model.py:NavErrorModel.step"><rect class="body" x="430" y="104" width="260" height="72" rx="3"/>
    <text class="ttl" x="560" y="126" style="font-size:13px">자세 — q_nb ⊗ δq (노름 유지)</text>
    <text class="ttl2" x="560" y="146">δq = (1, ½ε) 소각 오차</text>
    <text class="ttl2" x="560" y="164">ε: 롤·피치 <tspan data-p="att_std">0.002</tspan> · 방위 <tspan data-p="psi_std">0.005</tspan> rad</text></g>
  <path class="wire" d="M690 140 H716" marker-end="url(#aw-nav)"/>
  <g class="sblk" data-code="nav/error_model.py:NavErrorModel.step"><rect class="body" x="720" y="104" width="200" height="72" rx="3"/>
    <text class="ttl" x="820" y="126" style="font-size:13px">지연 큐 (deque)</text>
    <text class="ttl2" x="820" y="146">릴리스 지연 <tspan data-p="delay_s">0.03</tspan> s</text>
    <text class="ttl2" x="820" y="164">t_meas ≤ t − 지연 → 릴리스</text></g>
  <path class="wire" d="M820 176 V246" marker-end="url(#aw-nav)"/>
  <g class="sblk" data-code="nav/error_model.py:NavErrorModel.step"><rect class="body" x="720" y="250" width="200" height="72" rx="3"/>
    <text class="ttl" x="820" y="272" style="font-size:13px">홀드 · valid 게이트</text>
    <text class="ttl2" x="820" y="292">다음 릴리스까지 유지 (ZOH)</text>
    <text class="ttl2" x="820" y="310">첫 릴리스 전 valid=False</text></g>
  <path class="wire" d="M920 286 H926" marker-end="url(#aw-nav)"/>
  <g class="sblk" data-code="common/contracts.py:NavOutput"><rect class="body" x="930" y="274" width="36" height="24" rx="12"/><text class="pnum" x="948" y="290">1</text></g>
  <text class="pname" x="952" y="264">NavOutput</text>
  <!-- 출력 펼침 — NavOutput 버스의 실제 필드와 소비처 병기 (6DOF 페이지와 같은 문법).
       버스 분기는 도해(nblk)지만 필드는 전부 contracts.py NavOutput 정의에 실존한다 -->
  <path class="wire" d="M820 322 V380 H387 V396" marker-end="url(#aw-nav)"/>
  <g class="sblk nblk"><rect class="body" x="360" y="400" width="54" height="250" rx="3"/></g>
  <text class="bname" x="387" y="423">버스</text>
  <text class="bname" x="387" y="437">분기</text>
  <path class="wire" d="M414 430 H646" marker-end="url(#aw-nav)"/>
  <g class="sblk" data-code="common/contracts.py:NavOutput"><rect class="body" x="650" y="418" width="36" height="24" rx="12"/><text class="pnum" x="668" y="434">2</text></g>
  <text class="pname a-start" x="694" y="434">pos_n · NED 위치 — 유도 경로추종·AP 고도</text>
  <path class="wire" d="M414 470 H646" marker-end="url(#aw-nav)"/>
  <g class="sblk" data-code="common/contracts.py:NavOutput"><rect class="body" x="650" y="458" width="36" height="24" rx="12"/><text class="pnum" x="668" y="474">3</text></g>
  <text class="pname a-start" x="694" y="474">vel_n · NED 속도 — AP·airdata (α β V)</text>
  <path class="wire" d="M414 510 H646" marker-end="url(#aw-nav)"/>
  <g class="sblk" data-code="common/contracts.py:NavOutput"><rect class="body" x="650" y="498" width="36" height="24" rx="12"/><text class="pnum" x="668" y="514">4</text></g>
  <text class="pname a-start" x="694" y="514">q_nb · 자세 — SCAS·AP·리미터</text>
  <path class="wire" d="M414 550 H646" marker-end="url(#aw-nav)"/>
  <g class="sblk" data-code="common/contracts.py:NavOutput"><rect class="body" x="650" y="538" width="36" height="24" rx="12"/><text class="pnum" x="668" y="554">5</text></g>
  <text class="pname a-start" x="694" y="554">ω_b · 각속도 — SCAS rate 항</text>
  <path class="wire" d="M414 590 H646" marker-end="url(#aw-nav)"/>
  <g class="sblk" data-code="common/contracts.py:NavOutput"><rect class="body" x="650" y="578" width="36" height="24" rx="12"/><text class="pnum" x="668" y="594">6</text></g>
  <text class="pname a-start" x="694" y="594">valid · t_meas — 유효성 게이트·지연 메타</text>
  <path class="wire" d="M414 630 H646" marker-end="url(#aw-nav)"/>
  <g class="sblk" data-code="common/contracts.py:NavOutput"><rect class="body" x="650" y="618" width="36" height="24" rx="12"/><text class="pnum" x="668" y="634">7</text></g>
  <text class="pname a-start" x="694" y="634">fuel — 참값 통과 · 게인 스케줄</text>
  <text class="canvas-note" x="24" y="700">※ 측정 = 참값 + 바이어스(위치) + 백색잡음 · 바이어스·잡음 갱신은 측정 틱마다 (T = 갱신주기) · fuel은 참값 통과 (연료 게이지) · 자세는 동체측 δq 곱 — 단위 노름 유지</text>
  <text class="canvas-note" x="24" y="722">※ 갱신주기가 틱 주기의 정수배 아니면 조립 시점 거부 · 항법이 틱보다 빠르면 틱마다 새 측정 · 릴리스는 배열 복사 — 소비자 훼손이 보관 측정을 오염시키지 않음</text>
  <text class="canvas-note" x="24" y="744">※ 난수 seed <tspan data-p="seed">0</tspan> 고정 결정적 (몬테카를로 재현성) · 법칙·유도·스케줄은 NavOutput만 소비 [참값 차단 계약 03 §4] — 필드 ②~⑦은 VehicleState 동형 + 유효성</text>
</svg>`,
    flow: {
      lead: "참값 → 데시메이션 → 바이어스 + 백색잡음 → 자세 δq → 지연 큐 → 홀드·valid → NavOutput",
      reads: [
        "참값 VehicleState가 ①로 들어온다 — 이 블록이 <b>참값을 보는 유일한 자리</b>다.",
        "갱신 데시메이션: 항법은 제어(100 Hz)보다 느릴 수 있다. 갱신주기는 틱 주기의 정수배로 강제된다.",
        "위치에 1차 마르코프 바이어스를 더한다 (수평 σ 1 · 수직 1.5 m · τ 60 s) — 천천히 표류하는 성분이다.",
        "그 위에 상태별 백색잡음을 더한다. 위치·속도는 <b>수평과 수직이 따로</b>다.",
        "자세만은 더하지 않고 <b>곱한다</b> — q_nb ⊗ δq, 소각 오차 쿼터니언.",
        "지연 큐가 0.03 s를 붙든다. 측정 시각이 t − 지연보다 오래된 것만 릴리스된다.",
        "릴리스 사이에는 홀드(ZOH)한다. 첫 릴리스 전에는 valid=False다.",
        "나가는 것은 NavOutput <b>버스 하나</b>이고, 오른쪽에서 필드로 갈라진다 — pos_n(②)·vel_n(③)·q_nb(④)·ω_b(⑤)·valid·t_meas(⑥)·fuel(⑦).",
      ],
      why: [
        "EKF를 구현하지 않고 <b>등가 오차 모델</b>을 둔 이유: 제어 설계에 필요한 것은 추정기의 내부가 아니라 그 출력의 통계적 성질이다. 나중에 항법팀 EKF가 오면 같은 자리에 갈아 끼운다.",
        "위치·속도 오차를 수평과 수직으로 나눈 근거는 GNSS 기하다. 수신기 아래에는 위성이 없어 수직 기하가 나쁘다(VDOP &gt; HDOP). 등방으로 가정하면 수직 채널을 후하게 모사해 <b>저고도 임무의 고도 마진이 낙관적으로</b> 보인다 — 고도 루프가 pos_n[2]·vel_n[2]를 직접 먹는다.",
        "자세를 곱으로 섞는 이유: 쿼터니언에 잡음을 더하면 노름이 깨져 <b>회전이 아닌 것</b>이 된다. 소각 δq를 곱하면 단위 노름이 유지된다.",
        "이 블록이 <b>제어 성능의 천장</b>이다 — 여기 σ보다 정밀하게 제어할 방법은 없다. SCAS의 k_rate가 rate_std를 그대로 증폭해 타면을 떨게 하는 것이 그 천장의 가장 눈에 띄는 얼굴이다.",
        "시드를 고정하는 이유: 같은 설정이 같은 결과를 내야 게인을 바꾼 효과와 난수를 바꾼 효과를 구분할 수 있다.",
      ],
    },
    notes: `
<h4>설계 노트</h4>
<ul>
  <li>EKF는 구현하지 않음 — 실제 항법 출력의 <b>통계적 특성 재현</b> <span class="chip ok">확정</span> · 추후 항법팀 EKF를 그대로 교체 장착 가능(레지스트리)</li>
  <li>법칙·유도·스케줄은 <b>NavOutput만 소비</b> — 참값 차단 계약 (03 §4)</li>
  <li>파라미터: 상태별 잡음 σ · 바이어스(초기+상관시간) · transport delay · 갱신주기 · 시드</li>
  <li>초기 수치는 GPS/INS 통합항법 일반 수준 <span class="chip dft">기본값</span> — 항법팀 자료 확보 시 대체</li>
  <li>위치·속도 오차는 <b>수평(N·E)과 수직(D) 분리</b> — GNSS는 수신기 아래 위성이 없어 수직 기하가 나쁘다(VDOP &gt; HDOP). 등방 가정은 수직 채널을 후하게 모사해 <b>저고도 임무 고도 마진을 낙관적으로</b> 보이게 한다 (고도 루프가 pos_n[2]·vel_n[2] 직접 소비). 수직 기본값 = 수평 × 1.5 <span class="chip dft">기본값</span></li>
  <li>갱신주기가 제어주기(100 Hz)보다 낮을 수 있음 → 제어법칙은 <b>멀티레이트</b> 전제 <span class="chip note">설계 유의</span></li>
</ul>`,
  },

  // ── 게인 스케줄링 (공통) ─────────────────────────────────────────────
  schedule: {
    tag: "공통", tagBg: "#7c3aed",
    title: "게인 스케줄링", eng: "오토파일럿 · SCAS 게인에 적용",
    chips: ["ok", "dft", "tbd"],
    svg: `
<svg viewBox="0 0 1000 440" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="aw-gs2" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker>
    <marker id="as-gs2" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#8a97a5"/></marker>
  </defs>
  <g class="sblk" data-code="fcl/schedule.py:GainSchedule.step"><rect class="body" x="30" y="78" width="36" height="24" rx="12"/><text class="pnum" x="48" y="94">1</text></g>
  <text class="pname" x="48" y="122">Mach</text>
  <text class="siglabel" x="52" y="138">V / a(h_ISA)</text>
  <path class="wire" d="M66 90 H126" marker-end="url(#aw-gs2)"/>
  <g class="sblk" data-code="fcl/schedule.py:GainSchedule.step"><rect class="body" x="30" y="158" width="36" height="24" rx="12"/><text class="pnum" x="48" y="174">2</text></g>
  <text class="pname" x="48" y="202">고도 h</text>
  <text class="siglabel" x="48" y="218">−z_n</text>
  <path class="wire" d="M66 170 H126" marker-end="url(#aw-gs2)"/>
  <g class="sblk" data-code="fcl/schedule.py:GainSchedule.step"><rect class="body" x="30" y="238" width="36" height="24" rx="12"/><text class="pnum" x="48" y="254">3</text></g>
  <text class="pname" x="48" y="282">연료 fuel</text>
  <text class="siglabel" x="52" y="298">항법 게이지</text>
  <path class="wire" d="M66 250 H126" marker-end="url(#aw-gs2)"/>
  <g class="sblk" data-code="fcl/schedule.py:GainSchedule.step"><rect class="body" x="130" y="64" width="180" height="212" rx="3"/>
    <text class="ttl" x="220" y="150" style="font-size:13px">1차 필터 ×3</text>
    <text class="ttl2" x="220" y="170">τ 0.5 s — 채터링 방지</text>
    <text class="ttl2" x="220" y="188">첫 스텝 측정 시드 · τ=0 통과</text></g>
  <path class="wire" d="M310 90 H396" marker-end="url(#aw-gs2)"/>
  <path class="wire" d="M310 170 H396" marker-end="url(#aw-gs2)"/>
  <path class="wire" d="M310 250 H396" marker-end="url(#aw-gs2)"/>
  <g class="sblk" data-code="fcl/schedule.py:GainSchedule.step"><rect class="body" x="400" y="64" width="240" height="212" rx="3"/>
    <path d="M418 140 L436 140 L452 112 L470 126 L486 100" stroke="#8a97a5" stroke-width="1.8" fill="none"/>
    <text class="ttl" x="520" y="170" style="font-size:13px">게인 테이블 (M3 Table)</text>
    <text class="ttl2" x="520" y="190">축 ⊆ {mach·alt·fuel} · 1D~3D 보간</text>
    <text class="ttl2" x="520" y="208">외삽 clip 강제 [생성 시 검증]</text>
    <text class="ttl2" x="520" y="226">데모: 동압 스케일 1D mach</text></g>
  <path class="wire" d="M640 170 H666" marker-end="url(#aw-gs2)"/>
  <g class="sblk" data-code="fcl/schedule.py:GainSchedule.step"><rect class="body" x="670" y="112" width="170" height="116" rx="3"/>
    <text class="ttl" x="755" y="136" style="font-size:13px">그룹.게인 분배</text>
    <text class="ttl2" x="755" y="156">"pitch.kp" → {pitch:{kp}}</text>
    <text class="ttl2" x="755" y="174">그룹: 피치·롤·요 ·</text>
    <text class="ttl2" x="755" y="190">속도·고도·헤딩</text>
    <text class="ttl2" x="755" y="208">키: kp·ki·k_rate (조립 검증)</text></g>
  <path class="wire" d="M840 170 H854" marker-end="url(#aw-gs2)"/>
  <g class="sblk" data-code="fcl/schedule.py:GainSchedule.step"><rect class="body" x="858" y="158" width="36" height="24" rx="12"/><text class="pnum" x="876" y="174">1</text></g>
  <text class="pname a-start" x="902" y="166">→ AP · SCAS</text>
  <text class="pname a-start" x="902" y="184">스텝별 게인 덮어쓰기</text>
  <rect x="400" y="320" width="240" height="64" rx="8" fill="none" stroke="#8a5cf6" stroke-width="1.4" stroke-dasharray="6 4"/>
  <text class="annot" x="520" y="344" text-anchor="middle">설계 점검 — max_adjacent_jump</text>
  <text class="annot" x="520" y="364" text-anchor="middle">축별 인접 격자 최대 |Δ게인| (불연속 검출)</text>
  <path class="wire soft" d="M520 276 V316" marker-end="url(#as-gs2)"/>
  <text class="canvas-note" x="24" y="410">※ 스케줄 변수 mach·h·fuel은 law가 NavOutput에서 산출 (mach = V/음속(h_ISA)) — 참값 차단 · law 조립 시 그룹·키 오타는 시끄럽게 거부</text>
  <text class="canvas-note" x="24" y="430">※ 정본 = 게인 탭 테이블 (이 페이지는 구조 열람) · 보간 구간 마진 재계산은 마진 맵 재사용 · 필터가 게인 점프 완충 [확정 01 §3.4]</text>
</svg>`,
    flow: {
      lead: "Mach·h·fuel → 1차 필터 ×3 → 테이블 보간 → 그룹.게인 분배 → AP·SCAS 덮어쓰기",
      reads: [
        "스케줄 변수 셋이 들어온다 — Mach(①)·고도 h(②)·연료(③). 전부 항법에서 산출한 값이다 (참값이 아니다).",
        "각각 1차 필터(τ 0.5 s)를 지난다. 첫 스텝은 측정값으로 시드한다.",
        "게인 테이블을 조회한다 — 축은 {mach·alt·fuel}의 부분집합, 1D~3D 보간. 외삽은 clip으로 강제된다.",
        "나온 값을 그룹.게인 이름으로 분배한다 — pitch.kp → {pitch:{kp}}.",
        "매 스텝 AP·SCAS의 게인을 <b>덮어쓴다</b>. 이 화살표는 신호가 아니라 값의 출처가 바뀌는 경로다.",
      ],
      why: [
        "필터가 테이블 <b>앞</b>에 있는 이유: 스케줄 변수가 잡음으로 떨면 게인이 따라 떨고, 게인이 떨면 제어가 채터링한다. 게인은 신호보다 훨씬 천천히 변해야 하는 값이다.",
        "외삽을 금지하고 경계값을 고정하는 이유: 테이블 밖에서 선형 외삽하면 <b>설계한 적 없는 게인</b>이 나온다. 그 값의 마진을 아무도 본 적이 없다.",
        "인접 격자 최대 |Δ게인| 점검이 있는 것이 이 페이지의 숨은 요점이다 — 설계점끼리는 마진을 봤어도 그 <b>사이</b>는 안 봤다. 점프가 크면 보간 구간에서 마진이 무너진다.",
        "정본이 게인 탭 테이블이고 이 페이지가 구조 열람인 이유: 스케줄이 덮는 자리에 상수를 입력해 두면 실행 시점에 룩업이 이기므로, 값이 둘인 척하게 된다.",
      ],
    },
    notes: `
<h4>설계 노트</h4>
<ul>
  <li>스케줄 변수: <b>Mach · 고도 · 연료량</b> — 조건 조합의 트림점에서 설계 <span class="chip ok">확정 01 §3.4</span> · 데모 기체는 동압 스케일 1D mach <span class="chip dft">기본값</span></li>
  <li>스케줄 검증 요구: 설계점 사이 <b>보간 구간</b>에서 마진 재계산(마진 맵 재사용) · 테이블 불연속 검출 <span class="chip ok">확정</span></li>
  <li>유효범위 밖 외삽 금지(경계값 고정) · 스케줄 변수 입력 필터링으로 게인 채터링 방지 <span class="chip dft">기본값</span></li>
  <li>설계점 격자 · 보간 · 전환 시 범프리스 처리 <span class="chip tbd">TBD</span> — 트림 결과 확보 후</li>
</ul>`,
  },

  // ── 미션플래너 (입력) ────────────────────────────────────────────────
  planner: {
    tag: "입력", tagBg: "#5f6b78",
    title: "미션플래너", eng: "Mission Planner",
    chips: ["ok"],
    svg: `
<svg viewBox="0 0 900 250" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-mp" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <g class="sblk nblk"><rect class="body" x="40" y="60" width="230" height="88" rx="3"/>
    <text class="ttl" x="155" y="84" style="font-size:13px">미션 편집 — 시뮬 탭</text>
    <text class="ttl2" x="155" y="104">모드 테이블 {명령 · 이탈 · next}</text>
    <text class="ttl2" x="155" y="120">웨이포인트 (N,E) · 도달반경</text>
    <text class="ttl2" x="155" y="136">NED 평면 지도 편집 (클릭·드래그·줌)</text></g>
  <path class="wire" d="M270 104 H306" marker-end="url(#aw-mp)"/>
  <g class="sblk" data-code="guidance/modes.py:validate_condition guidance/modes.py:ModeSequencer"><rect class="body" x="310" y="60" width="250" height="88" rx="3"/>
    <text class="ttl" x="435" y="84" style="font-size:13px">검증 — 서버 · 엔진</text>
    <text class="ttl2" x="435" y="104">이탈 DSL: time · alt · speed · path_done</text>
    <text class="ttl2" x="435" y="120">heading: 숫자 | "path" | 없음(null)</text>
    <text class="ttl2" x="435" y="136">next 참조 · 초기 모드 존재 검사</text></g>
  <path class="wire" d="M560 104 H596" marker-end="url(#aw-mp)"/>
  <g class="sblk" data-code="guidance/guidance.py:Guidance"><rect class="body" x="600" y="60" width="230" height="88" rx="3"/>
    <text class="ttl" x="715" y="84" style="font-size:13px">임무프로파일 조립</text>
    <text class="ttl2" x="715" y="104">ModeSpec 목록 (모드 시퀀스)</text>
    <text class="ttl2" x="715" y="120">+ LosPath (웨이포인트 · 반경)</text>
    <text class="ttl2" x="715" y="136">→ Guidance(modes, path, initial)</text></g>
  <path class="wire" d="M830 104 H846" marker-end="url(#aw-mp)"/>
  <g class="sblk" data-code="guidance/guidance.py:Guidance"><rect class="body" x="848" y="92" width="36" height="24" rx="12"/><text class="pnum" x="866" y="108">1</text></g>
  <text class="pname" x="864" y="148">→ 유도</text>
  <text class="canvas-note" x="24" y="204">※ 속도·고도 '경로 프로파일' 생성 없음 — 명령은 모드 테이블이 직접 보유 (경로추종은 헤딩만 담당) · 엔진에 별도 플래너 모듈 없음 — 시뮬 요청이 조립</text>
  <text class="canvas-note" x="24" y="226">※ 상세 임무 로직은 별도 설계 범위 [확정 01 §3.3.1] · 미션 편집처는 시뮬레이션 탭 미션 그룹</text>
</svg>`,
    flow: {
      lead: "시뮬 탭 편집 → 서버·엔진 검증 → 임무프로파일 조립 → 유도",
      reads: [
        "왼쪽은 편집이다 — 모드 테이블과 웨이포인트를 시뮬 탭에서 만든다 (NED 평면 지도에서 클릭·드래그·줌).",
        "검증을 거친다: 이탈 DSL의 종류와 인자 개수, heading이 숫자인지 path인지 없음인지, next 참조가 실존하는지, 초기 모드가 있는지.",
        "통과하면 임무프로파일로 조립된다 — ModeSpec 목록 + LosPath(웨이포인트·도달반경) → Guidance(modes, path, initial).",
        "그것이 유도로 나간다(①).",
      ],
      why: [
        "엔진에 플래너 <b>모듈이 없다</b>는 것이 이 그림에서 볼 것이다. 미션은 코드가 아니라 데이터이고, 시뮬 요청이 그 데이터를 조립한다. 그래서 미션을 바꾸는 데 코드 수정이 필요 없다.",
        "검증이 조립 시점에 있는 이유: 배치 시뮬 <b>도중에</b> 거부하면 그 실행분이 통째로 날아간다. 오타는 시작 전에 시끄럽게 걸러야 한다.",
        "속도·고도 프로파일을 생성하지 않는다 — 명령은 모드 테이블이 직접 갖는다. 경로추종은 헤딩(과 모드가 alt를 path로 적었을 때의 세로 프로파일)만 담당한다. 축마다 출처를 하나로 두는 규칙이 여기서도 같다.",
      ],
    },
    notes: `
<h4>설계 노트</h4>
<ul>
  <li>웨이포인트 열 + 선언적 모드 테이블 = <b>임무프로파일</b> — 엔진에 별도 플래너 모듈 없음 (시뮬 요청 → 서버 검증 → Guidance 조립)</li>
  <li>편집처: 시뮬레이션 탭 미션 그룹(모드 테이블·웨이포인트·도달반경) — NED 평면 캔버스 지도 편집 구현 (실지도 타일은 폐쇄망 반입 검토 시)</li>
  <li>임무수행 단계의 상세 임무 로직은 별도 설계 범위 <span class="chip ok">확정 01 §3.3.1</span></li>
</ul>`,
  },

  // ── 비선형 시뮬 검증 (설계 ⑤ — 블록 아닌 설계 단계 페이지) ───────────
  verify: {
    tag: "설계 ⑤", tagBg: "#6b7280",
    title: "비선형 시뮬레이션 검증", eng: "임무프로파일 → 모드별 유도 → 폐루프 6DOF",
    chips: ["ok", "dft"],
    svg: `
<svg viewBox="0 0 1000 510" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="aw-vf" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker>
    <marker id="as-vf" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#8a97a5"/></marker>
  </defs>
  <!-- Simulator.run의 실제 폐루프 — 최상위 블록도와 같은 사슬이 코드에서도 이 순서다 -->
  <g class="sblk" data-code="sim/simulator.py:Simulator.run"><rect class="body" x="30" y="88" width="36" height="24" rx="12"/><text class="pnum" x="48" y="104">1</text></g>
  <text class="pname" x="48" y="132">TrimResult</text>
  <path class="wire" d="M66 100 H106" marker-end="url(#aw-vf)"/>
  <g class="sblk" data-code="guidance/guidance.py:Guidance.step"><rect class="body" x="110" y="64" width="170" height="72" rx="3"/>
    <text class="ttl" x="195" y="88" style="font-size:13px">유도 — Guidance.step</text>
    <text class="ttl2" x="195" y="108">모드·경로 → GuidanceCommand</text>
    <text class="ttl2" x="195" y="124">제어 틱 100 Hz</text></g>
  <path class="wire" d="M280 100 H316" marker-end="url(#aw-vf)"/>
  <g class="sblk" data-code="fcl/law.py:FlightControlLaw.step"><rect class="body" x="320" y="64" width="200" height="72" rx="3"/>
    <text class="ttl" x="420" y="88" style="font-size:13px">제어법칙 — FlightControlLaw</text>
    <text class="ttl2" x="420" y="108">AP → α리미터 → SCAS → 믹서</text>
    <text class="ttl2" x="420" y="124">→ SurfaceCommand</text></g>
  <path class="wire" d="M520 100 H556" marker-end="url(#aw-vf)"/>
  <g class="sblk" data-code="plant/actuator.py:SecondOrderActuator.step"><rect class="body" x="560" y="64" width="140" height="72" rx="3"/>
    <text class="ttl" x="630" y="88" style="font-size:13px">작동기 ×5</text>
    <text class="ttl2" x="630" y="108">2차계 · rate/위치 한계</text></g>
  <path class="wire" d="M700 100 H736" marker-end="url(#aw-vf)"/>
  <g class="sblk" data-code="plant/aircraft.py:Aircraft.fm plant/eom.py:RigidBody.step"><rect class="body" x="740" y="52" width="220" height="96" rx="3"/>
    <text class="ttl" x="850" y="76" style="font-size:13px">플랜트 — RK4 dt 10 ms</text>
    <text class="ttl2" x="850" y="96">Aircraft.fm → RigidBody.step</text>
    <text class="ttl2" x="850" y="112">준정적 질량 갱신 · ZOH 제어</text>
    <text class="ttl2" x="850" y="128">발사 레일 구간은 해석해 전진</text></g>
  <path class="wire" d="M850 148 V190 H509 V206" marker-end="url(#aw-vf)"/>
  <text class="siglabel" x="700" y="182">참값 상태 (VehicleState)</text>
  <circle class="branch" cx="700" cy="190" r="3.2"/>
  <g class="sblk" data-code="nav/error_model.py:NavErrorModel.step"><rect class="body" x="395" y="210" width="220" height="72" rx="3"/>
    <text class="ttl" x="505" y="234" style="font-size:13px">항법 — NavErrorModel.step</text>
    <text class="ttl2" x="505" y="254">잡음·바이어스·지연 → NavOutput</text>
    <text class="ttl2" x="505" y="270">참값은 항법만 소비 [차단 계약]</text></g>
  <path class="wire" d="M395 246 H90 V124 H106" marker-end="url(#aw-vf)"/>
  <circle class="branch" cx="300" cy="246" r="3.2"/>
  <path class="wire" d="M300 246 V124 H316" marker-end="url(#aw-vf)"/>
  <text class="siglabel" x="262" y="266">NavOutput — 유도·법칙의 유일한 상태 입력</text>
  <g class="sblk" data-code="sim/simulator.py:Simulator.run"><rect class="body" x="118" y="10" width="36" height="24" rx="12"/><text class="pnum" x="136" y="26">2</text></g>
  <text class="pname a-start" x="162" y="26">임무프로파일 (시뮬 탭)</text>
  <path class="wire soft" d="M136 34 V60" marker-end="url(#as-vf)"/>
  <g class="sblk" data-code="sim/simulator.py:Simulator.run sim/simulator.py:Simulator._envelope"><rect class="body" x="640" y="210" width="260" height="84" rx="3"/>
    <text class="ttl" x="770" y="234" style="font-size:13px">신호 로깅 · 엔벨로프 감시</text>
    <text class="ttl2" x="770" y="254">기본 26 + 명령 사슬 50 신호</text>
    <text class="ttl2" x="770" y="270">실속 마진 · DB 이탈 플래그 · 페이즈</text></g>
  <path class="wire soft" d="M700 190 V206" marker-end="url(#as-vf)"/>
  <path class="wire" d="M900 252 H946" marker-end="url(#aw-vf)"/>
  <circle class="branch" cx="925" cy="252" r="3.2"/>
  <g class="sblk" data-code="common/contracts.py:SimResult"><rect class="body" x="950" y="240" width="36" height="24" rx="12"/><text class="pnum" x="968" y="256">1</text></g>
  <text class="pname" x="962" y="288">SimResult</text>
  <text class="pname" x="954" y="306">→ 결과 탭</text>
  <path class="wire note" d="M925 252 V366 H904" marker-end="url(#as-vf)"/>
  <g class="sblk nblk"><rect class="body" x="640" y="330" width="260" height="72" rx="3"/>
    <text class="ttl" x="770" y="354">리포트 · Simulink 대조</text>
    <text class="ttl2" x="770" y="376">허용오차 비교 (폐쇄망 절차)</text></g>
  <text class="canvas-note" x="24" y="452">※ 멀티레이트 — 유도·법칙은 제어 틱(100 Hz, k % n_ctrl == 0)마다, 플랜트는 dt 10 ms RK4로 매 스텝 (제어는 ZOH) · 발사 레일 구간은 적분하지 않고 등가속 해석해로 전진</text>
  <text class="canvas-note" x="24" y="474">※ 발산 런은 ISA 범위 이탈 직전 조기 절단 — 부분 결과·엔벨로프 보존 · 접지·레일 상태는 유도 이탈 조건(on_ground·off_rail)이 소비하므로 제어 틱보다 먼저 잰다</text>
  <text class="canvas-note" x="24" y="496">※ 합격기준(오버슈트·정착시간·경로오차)은 폐쇄망 Simulink 대조 시 확정 [01 §5] — 대조 절차는 엔진 밖(점선)</text>
</svg>`,
    flow: {
      lead: "TrimResult + 임무프로파일 → 유도 → 법칙 → 작동기 → 플랜트 → 항법 → 로깅 → SimResult",
      reads: [
        "시작점은 트림 결과(①)다 — 평형에서 출발해야 과도가 설계 때문인지 초기값 때문인지 구분된다.",
        "유도가 모드·경로를 돌려 GuidanceCommand를 낸다 (제어 틱 100 Hz).",
        "제어법칙이 AP → α 리미터 → SCAS → 믹서를 지나 SurfaceCommand를 만든다.",
        "작동기 5개가 그것을 실제 타면 변위로 바꾼다.",
        "플랜트가 RK4 dt 10 ms로 적분한다 — <b>제어보다 빠르다</b>. 제어는 그 사이 ZOH로 유지된다.",
        "참값 상태는 항법으로만 간다. 항법이 낸 NavOutput이 유도·법칙의 <b>유일한</b> 상태 입력이고, 이 그림의 폐루프는 거기서 닫힌다.",
        "로깅·엔벨로프 감시가 신호와 실속 마진·DB 이탈 플래그를 기록해 SimResult로 낸다(①).",
        "오른쪽 점선은 엔진 밖이다 — 폐쇄망 Simulink 대조 절차.",
      ],
      why: [
        "<b>멀티레이트가 기본</b>인 이유: 제어를 플랜트와 같은 주기로 돌리면 실기체보다 좋게 나온다. 실제 제어기는 이산이고 그 사이 명령을 유지한다 — 그 유지 구간이 곧 위상지연이다.",
        "선형해석이 있는데 이 페이지가 또 필요한 이유: 선형해석은 트림점 <b>근처의 작은 흔들림만</b> 본다. 큰 기동·모드 전환·포화는 비선형으로만 확인되고, 리밋사이클이 정확히 그 사례다 — 마진이 있다고 나와도 여기서 떨어질 수 있다.",
        "발산 런을 ISA 범위 이탈 직전에 조기 절단하는 이유: 그 뒤 숫자는 의미가 없는데, 부분 결과와 엔벨로프는 <b>어디서 어긋나기 시작했는지</b>를 짚는 데 쓸모가 있다.",
        "접지·레일 상태를 제어 틱보다 먼저 재는 이유는 유도의 이탈 조건(on_ground·off_rail)이 그걸 소비하기 때문이다. 순서가 뒤집히면 한 틱 늦은 정보로 모드를 넘긴다.",
      ],
    },
    notes: `
<h4>설계 노트</h4>
<ul>
  <li>합격기준: 오버슈트 · 정착시간 · 정상상태 오차 · 경로오차 한계 <span class="chip dft">기본값</span> — 수치는 폐쇄망 Simulink 대조 시 확정, 파라미터 관리 계층으로 관리 <span class="chip ok">확정 01 §5</span></li>
  <li>엔벨로프 감시: 실속 마진(α_stall − α) 시계열 · 임무 전체 최악 마진 요약 · DB 유효범위 이탈 플래그 <span class="chip ok">확정</span></li>
  <li>멀티레이트: 플랜트 적분 주기(dt 10 ms)와 제어기 이산 주기(100 Hz) 분리 <span class="chip ok">확정</span> · 고정스텝 RK4 <span class="chip dft">기본값</span></li>
  <li>최종 검증: 기존 Simulink 모델과 대조 (완성 후 폐쇄망에서) <span class="chip ok">확정</span> · 몬테카를로 분산 대상 <span class="chip tbd">TBD 02 §6</span></li>
</ul>`,
    // 블록이 아닌 설계 단계 페이지 — 실행·열람은 시뮬/결과 탭
    edits: [
      { hash: "sim", label: "시뮬레이션 탭 — 폐루프 실행" },
      { hash: "results", label: "결과 탭 — 시계열·엔벨로프 감시·재생" },
    ],
  },
};
