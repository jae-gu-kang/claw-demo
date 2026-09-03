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
chips, svg, notes, children?} } — tag/tagBg는 루트 상속. 페이지 SVG 안의
<g class="blk" data-child="childId" tabindex="0"> 블록 클릭 → 한 층 하강
(#blocks/scas/pitch/pi — views/blocks.js 라우팅). data-child 참조는 그 페이지
children 키만 허용 (lib/blocks.test.js 가드 — 오타 = 클릭 무반응).

SVG 안의 <tspan data-p="이름">은 파라미터 연동 표시값 — views/blocks.js가 렌더 시
스키마 기본값(+적용된 편집값)으로 채우고, 편집 폼 입력과 실시간 동기화한다.
초기 텍스트는 참고용 폴백일 뿐 정본이 아님 (정본 = 엔진 레지스트리 스키마).
data-p 이름은 **루트 블록** 스키마의 파라미터명만 허용 — children 포함
(lib/blocks.test.js 가드). 스키마 폼 없는 루트(scas 등) 아래에서는 사용 금지.
data-code는 별개 축이다 — data-p 금지 루트에도 data-code는 붙는다.
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
  <g class="sblk"><rect class="body" x="30" y="138" width="36" height="24" rx="12"/><text class="pnum" x="48" y="154">1</text></g>
  <text class="pname" x="48" y="182">e (자세 오차)</text>
  <path class="wire" d="M66 150 H146"/>
  <circle class="branch" cx="150" cy="150" r="3.2"/>
  <path class="wire" d="M150 150 V86 H196" marker-end="url(#aw-pi)"/>
  <g class="sblk"><rect class="body" x="200" y="60" width="150" height="52" rx="3"/>
    <text class="ttl" x="275" y="82" style="font-size:13px">× kp</text>
    <text class="ttl2" x="275" y="100">비례항</text></g>
  <path class="wire" d="M350 86 H480 V132" marker-end="url(#aw-pi)"/>
  <path class="wire" d="M150 150 V222 H196" marker-end="url(#aw-pi)"/>
  <g class="sblk" data-code="blocks/controllers.py:PID.step"><rect class="body" x="200" y="190" width="250" height="64" rx="3"/>
    <text class="ttl" x="325" y="214" style="font-size:13px">적분기 (클램프 AW)</text>
    <text class="ttl2" x="325" y="236">I ← clip(I + dt·ki·e, out_lo~hi)</text></g>
  <path class="wire" d="M450 222 H480 V168" marker-end="url(#aw-pi)"/>
  <circle class="body" cx="480" cy="150" r="14"/>
  <text class="sumsign" x="480" y="143">+</text><text class="sumsign" x="480" y="163">+</text>
  <path class="wire" d="M494 150 H526" marker-end="url(#aw-pi)"/>
  <g class="sblk"><rect class="body" x="530" y="124" width="110" height="52" rx="3"/>
    <path d="M542 166 H558 L612 134 H628" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="585" y="194">출력 클립 out_lo~hi</text>
  <path class="wire" d="M640 150 H726" marker-end="url(#aw-pi)"/>
  <g class="sblk"><rect class="body" x="730" y="138" width="36" height="24" rx="12"/><text class="pnum" x="748" y="154">1</text></g>
  <text class="pname" x="748" y="182">u_PI → k_rate 합산</text>
  <text class="canvas-note" x="24" y="290">※ 안티와인드업 = 적분 '상태' 자체를 out_lo~hi로 클램프 — 포화 해제 시 즉시 복귀 · 이산화: 전진 오일러, dt는 제어주기에서 자동 [확정 §3.5]</text>
  <text class="canvas-note" x="24" y="308">※ kp·ki는 게인 스케줄이 스텝 인자로 덮어씀 (생성 후 게인 변경은 이 경로만) · 재관여 시 reset(state) 적분 웜스타트 [범프리스 계약]</text>
</svg>`,
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
  <g class="sblk"><rect class="body" x="30" y="110" width="36" height="24" rx="12"/><text class="pnum" x="48" y="126">1</text></g>
  <text class="pname" x="48" y="154">θ_cmd ← α 리미터</text>
  <path class="wire" d="M66 122 H326" marker-end="url(#aw-scas)"/>
  <g class="sblk"><rect class="body" x="30" y="220" width="36" height="24" rx="12"/><text class="pnum" x="48" y="236">2</text></g>
  <text class="pname" x="48" y="264">φ_cmd ← AP</text>
  <path class="wire" d="M66 232 H326" marker-end="url(#aw-scas)"/>
  <g class="sblk"><rect class="body" x="30" y="392" width="36" height="24" rx="12"/><text class="pnum" x="48" y="408">3</text></g>
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
  <g class="sblk"><rect class="body" x="810" y="110" width="36" height="24" rx="12"/><text class="pnum" x="828" y="126">1</text></g>
  <text class="pname a-start" x="856" y="126">δe → 믹서</text>
  <path class="wire" d="M630 232 H806" marker-end="url(#aw-scas)"/>
  <g class="sblk"><rect class="body" x="810" y="220" width="36" height="24" rx="12"/><text class="pnum" x="828" y="236">2</text></g>
  <text class="pname a-start" x="856" y="236">δa → 믹서</text>
  <path class="wire" d="M630 342 H806" marker-end="url(#aw-scas)"/>
  <g class="sblk"><rect class="body" x="810" y="330" width="36" height="24" rx="12"/><text class="pnum" x="828" y="346">3</text></g>
  <text class="pname a-start" x="856" y="346">δr → 믹서</text>
  <text class="canvas-note" x="24" y="462">※ 축 블록 클릭 → 내부 진입 (시뮬링크 더블클릭 대응) · 축 공통 평탄형 구조 [확정 M7] — 캐스케이드 아님 · θ·φ·β·p·q·r는 NavOutput 추출 — 참값 차단 계약</text>
</svg>`,
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
  <g class="sblk"><rect class="body" x="30" y="88" width="36" height="24" rx="12"/><text class="pnum" x="48" y="104">1</text></g>
  <text class="pname" x="48" y="132">θ_cmd ← α 리미터</text>
  <path class="wire" d="M66 100 H122" marker-end="url(#aw-scp)"/>
  <circle class="body" cx="140" cy="100" r="14"/>
  <text class="sumsign" x="131" y="104">+</text><text class="sumsign" x="140" y="113">−</text>
  <path class="wire" d="M154 100 H186" marker-end="url(#aw-scp)"/>
  <g class="blk" data-child="pi" data-code="blocks/controllers.py:PID" tabindex="0">
    <rect class="body" x="190" y="64" width="190" height="72" rx="3"/>
    <text class="ttl" x="285" y="94" style="font-size:14px">PI — 클램프 AW</text>
    <text class="ttl2" x="285" y="116">적분 한계 out_lo~hi · 클릭 → 내부</text>
  </g>
  <path class="wire" d="M380 100 H412" marker-end="url(#aw-scp)"/>
  <circle class="body" cx="430" cy="100" r="14"/>
  <text class="sumsign" x="421" y="104">+</text><text class="sumsign" x="430" y="113">+</text>
  <path class="wire" d="M444 100 H476" marker-end="url(#aw-scp)"/>
  <g class="sblk"><rect class="body" x="480" y="74" width="110" height="52" rx="3"/>
    <path d="M492 116 H508 L562 84 H578" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="535" y="144">최종 클립 out_lo~hi</text>
  <path class="wire" d="M590 100 H806" marker-end="url(#aw-scp)"/>
  <g class="sblk"><rect class="body" x="810" y="88" width="36" height="24" rx="12"/><text class="pnum" x="828" y="104">1</text></g>
  <text class="pname" x="828" y="132">δe → 믹서</text>
  <g class="sblk"><rect class="body" x="122" y="170" width="36" height="24" rx="12"/><text class="pnum" x="140" y="186">2</text></g>
  <text class="pname a-start" x="164" y="186">θ (NavOutput)</text>
  <path class="wire" d="M140 170 V118" marker-end="url(#aw-scp)"/>
  <g class="sblk"><rect class="body" x="388" y="156" width="84" height="36" rx="3"/>
    <text class="ttl2" x="430" y="178" style="font-weight:700">× k_rate</text></g>
  <path class="wire" d="M430 156 V118" marker-end="url(#aw-scp)"/>
  <g class="sblk"><rect class="body" x="412" y="212" width="36" height="24" rx="12"/><text class="pnum" x="430" y="228">3</text></g>
  <text class="pname a-start" x="454" y="228">q (NavOutput)</text>
  <path class="wire" d="M430 212 V192" marker-end="url(#aw-scp)"/>
  <rect x="640" y="180" width="292" height="56" rx="8" fill="none" stroke="#8a5cf6" stroke-width="1.4" stroke-dasharray="6 4"/>
  <text class="annot" x="786" y="204" text-anchor="middle">게인 스케줄링 주입 — kp·ki·k_rate</text>
  <text class="annot" x="786" y="224" text-anchor="middle">스텝별 덮어쓰기 (정본 = 게인 탭)</text>
  <text class="canvas-note" x="24" y="296">※ rate 항은 PI 클램프 밖 합산 — 최종 클립이 한 번 더 제한 · 재관여 시 적분 웜스타트 [범프리스 계약] · PI 블록 클릭 → 내부 (층4)</text>
</svg>`,
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
  <g class="sblk"><rect class="body" x="30" y="88" width="36" height="24" rx="12"/><text class="pnum" x="48" y="104">1</text></g>
  <text class="pname" x="48" y="132">φ_cmd ← AP</text>
  <path class="wire" d="M66 100 H122" marker-end="url(#aw-scr)"/>
  <circle class="body" cx="140" cy="100" r="14"/>
  <text class="sumsign" x="131" y="104">+</text><text class="sumsign" x="140" y="113">−</text>
  <text class="siglabel" x="140" y="72">wrap ±π</text>
  <path class="wire" d="M154 100 H186" marker-end="url(#aw-scr)"/>
  <g class="blk" data-child="pi" data-code="blocks/controllers.py:PID" tabindex="0">
    <rect class="body" x="190" y="64" width="190" height="72" rx="3"/>
    <text class="ttl" x="285" y="94" style="font-size:14px">PI — 클램프 AW</text>
    <text class="ttl2" x="285" y="116">적분 한계 out_lo~hi · 클릭 → 내부</text>
  </g>
  <path class="wire" d="M380 100 H412" marker-end="url(#aw-scr)"/>
  <circle class="body" cx="430" cy="100" r="14"/>
  <text class="sumsign" x="421" y="104">+</text><text class="sumsign" x="430" y="113">+</text>
  <path class="wire" d="M444 100 H476" marker-end="url(#aw-scr)"/>
  <g class="sblk"><rect class="body" x="480" y="74" width="110" height="52" rx="3"/>
    <path d="M492 116 H508 L562 84 H578" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="535" y="144">최종 클립 out_lo~hi</text>
  <path class="wire" d="M590 100 H806" marker-end="url(#aw-scr)"/>
  <g class="sblk"><rect class="body" x="810" y="88" width="36" height="24" rx="12"/><text class="pnum" x="828" y="104">1</text></g>
  <text class="pname" x="828" y="132">δa → 믹서</text>
  <g class="sblk"><rect class="body" x="122" y="170" width="36" height="24" rx="12"/><text class="pnum" x="140" y="186">2</text></g>
  <text class="pname a-start" x="164" y="186">φ (NavOutput)</text>
  <path class="wire" d="M140 170 V118" marker-end="url(#aw-scr)"/>
  <g class="sblk"><rect class="body" x="388" y="156" width="84" height="36" rx="3"/>
    <text class="ttl2" x="430" y="178" style="font-weight:700">× k_rate</text></g>
  <path class="wire" d="M430 156 V118" marker-end="url(#aw-scr)"/>
  <g class="sblk"><rect class="body" x="412" y="212" width="36" height="24" rx="12"/><text class="pnum" x="430" y="228">3</text></g>
  <text class="pname a-start" x="454" y="228">p (NavOutput)</text>
  <path class="wire" d="M430 212 V192" marker-end="url(#aw-scr)"/>
  <rect x="640" y="180" width="292" height="56" rx="8" fill="none" stroke="#8a5cf6" stroke-width="1.4" stroke-dasharray="6 4"/>
  <text class="annot" x="786" y="204" text-anchor="middle">게인 스케줄링 주입 — kp·ki·k_rate</text>
  <text class="annot" x="786" y="224" text-anchor="middle">스텝별 덮어쓰기 (정본 = 게인 탭)</text>
  <text class="canvas-note" x="24" y="296">※ 롤 오차는 wrap ±π — 배면 통과 시 2π 점프 방지 · rate 항은 PI 클램프 밖 합산 · 재관여 시 적분 웜스타트 [범프리스 계약]</text>
</svg>`,
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
  <g class="sblk"><rect class="body" x="30" y="88" width="36" height="24" rx="12"/><text class="pnum" x="48" y="104">1</text></g>
  <text class="pname" x="48" y="132">β (사이드슬립)</text>
  <path class="wire" d="M66 100 H96" marker-end="url(#aw-scy)"/>
  <g class="sblk"><rect class="body" x="100" y="74" width="70" height="52" rx="3"/>
    <text class="ttl" x="135" y="96" style="font-size:13px">× −1</text>
    <text class="ttl2" x="135" y="114">명령 없음</text></g>
  <path class="wire" d="M170 100 H186" marker-end="url(#aw-scy)"/>
  <g class="blk" data-child="pi" data-code="blocks/controllers.py:PID" tabindex="0">
    <rect class="body" x="190" y="64" width="190" height="72" rx="3"/>
    <text class="ttl" x="285" y="94" style="font-size:14px">PI — 클램프 AW</text>
    <text class="ttl2" x="285" y="116">적분 한계 out_lo~hi · 클릭 → 내부</text>
  </g>
  <path class="wire" d="M380 100 H412" marker-end="url(#aw-scy)"/>
  <circle class="body" cx="430" cy="100" r="14"/>
  <text class="sumsign" x="421" y="104">+</text><text class="sumsign" x="430" y="113">+</text>
  <path class="wire" d="M444 100 H476" marker-end="url(#aw-scy)"/>
  <g class="sblk"><rect class="body" x="480" y="74" width="110" height="52" rx="3"/>
    <path d="M492 116 H508 L562 84 H578" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="535" y="144">최종 클립 out_lo~hi</text>
  <path class="wire" d="M590 100 H806" marker-end="url(#aw-scy)"/>
  <g class="sblk"><rect class="body" x="810" y="88" width="36" height="24" rx="12"/><text class="pnum" x="828" y="104">1</text></g>
  <text class="pname" x="828" y="132">δr → 믹서</text>
  <g class="sblk"><rect class="body" x="30" y="196" width="36" height="24" rx="12"/><text class="pnum" x="48" y="212">2</text></g>
  <text class="pname" x="48" y="240">r (NavOutput)</text>
  <path class="wire" d="M66 208 H96" marker-end="url(#aw-scy)"/>
  <g class="sblk"><rect class="body" x="100" y="182" width="170" height="52" rx="3"/>
    <text class="ttl" x="185" y="204" style="font-size:13px">워시아웃 τs/(τs+1)</text>
    <text class="ttl2" x="185" y="222">정상 r 제거 — 선회 유지</text></g>
  <path class="wire" d="M270 208 H294" marker-end="url(#aw-scy)"/>
  <g class="sblk"><rect class="body" x="298" y="190" width="84" height="36" rx="3"/>
    <text class="ttl2" x="340" y="212" style="font-weight:700">× k_rate</text></g>
  <path class="wire" d="M382 208 H430 V118" marker-end="url(#aw-scy)"/>
  <rect x="640" y="180" width="292" height="56" rx="8" fill="none" stroke="#8a5cf6" stroke-width="1.4" stroke-dasharray="6 4"/>
  <text class="annot" x="786" y="204" text-anchor="middle">게인 스케줄링 주입 — kp·ki·k_rate</text>
  <text class="annot" x="786" y="224" text-anchor="middle">스텝별 덮어쓰기 (정본 = 게인 탭)</text>
  <text class="canvas-note" x="24" y="336">※ 요축은 자세 명령 없음 — 선회조화(β 억제) · 워시아웃이 지속 선회의 정상 r 제거 → 선회 유지 · 재관여 시 워시아웃 rate 시드 — k_rate·r 킥 방지 [범프리스]</text>
</svg>`,
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
  <g class="sblk"><rect class="body" x="30" y="110" width="36" height="24" rx="12"/><text class="pnum" x="48" y="126">3</text></g>
  <text class="pname" x="48" y="154">ψ_cmd ← 유도</text>
  <path class="wire" d="M66 122 H326" marker-end="url(#aw-ap)"/>
  <g class="sblk"><rect class="body" x="30" y="220" width="36" height="24" rx="12"/><text class="pnum" x="48" y="236">2</text></g>
  <text class="pname" x="48" y="264">h_cmd ← 유도</text>
  <path class="wire" d="M66 232 H326" marker-end="url(#aw-ap)"/>
  <g class="sblk"><rect class="body" x="30" y="330" width="36" height="24" rx="12"/><text class="pnum" x="48" y="346">1</text></g>
  <text class="pname" x="48" y="374">V_cmd ← 유도</text>
  <path class="wire" d="M66 342 H326" marker-end="url(#aw-ap)"/>
  <g class="sblk"><rect class="body" x="30" y="398" width="36" height="24" rx="12"/><text class="pnum" x="48" y="414">4</text></g>
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
  <g class="sblk"><rect class="body" x="810" y="110" width="36" height="24" rx="12"/><text class="pnum" x="828" y="126">2</text></g>
  <text class="pname a-start" x="856" y="126">φ_cmd → SCAS 롤</text>
  <path class="wire" d="M630 232 H806" marker-end="url(#aw-ap)"/>
  <g class="sblk"><rect class="body" x="810" y="220" width="36" height="24" rx="12"/><text class="pnum" x="828" y="236">1</text></g>
  <text class="pname a-start" x="856" y="236">θ_cmd → α 리미터</text>
  <path class="wire" d="M630 342 H806" marker-end="url(#aw-ap)"/>
  <g class="sblk"><rect class="body" x="810" y="330" width="36" height="24" rx="12"/><text class="pnum" x="828" y="346">3</text></g>
  <text class="pname a-start" x="856" y="346">δt_cmd (0~1)</text>
  <!-- 선회 FF — 주석 프레임 (실 배선·재클립은 채널 내부, 층3) -->
  <rect x="330" y="400" width="600" height="44" rx="8" fill="none" stroke="#b45309" stroke-width="1.4" stroke-dasharray="6 4"/>
  <text class="annot" x="630" y="427" text-anchor="middle" fill="#b45309">선회 피드포워드 — |φ_cmd| 분기 → 고도(θ)·속도(δt) 채널 내부 가산 · 상세는 채널 클릭</text>
  <text class="canvas-note" x="24" y="470">※ 채널 블록 클릭 → 내부 진입 (시뮬링크 더블클릭 대응) · 전 채널이 SCAS와 동일한 ScasAxis 재사용 (PI 클램프 AW) · V·h·ḣ·ψ는 NavOutput 추출 — 참값 차단 계약</text>
</svg>`,
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
  <g class="sblk"><rect class="body" x="30" y="88" width="36" height="24" rx="12"/><text class="pnum" x="48" y="104">1</text></g>
  <text class="pname" x="48" y="132">ψ_cmd ← 유도</text>
  <path class="wire" d="M66 100 H96" marker-end="url(#aw-aph)"/>
  <g class="sblk"><rect class="body" x="100" y="74" width="118" height="52" rx="3"/>
    <text class="ttl" x="159" y="93" style="font-size:13px">명령필터 wrap</text>
    <text class="ttl2" x="159" y="111">τ <tspan data-p="tau_hdg">1</tspan> s · 최단경로</text></g>
  <text class="siglabel" x="159" y="144">off: ψ 추적 · 적분 소거 · φ_cmd=0</text>
  <path class="wire" d="M218 100 H240" marker-end="url(#aw-aph)"/>
  <circle class="body" cx="258" cy="100" r="14"/>
  <text class="sumsign" x="249" y="104">+</text><text class="sumsign" x="258" y="113">−</text>
  <text class="siglabel" x="258" y="70">wrap ±π</text>
  <path class="wire" d="M272 100 H296" marker-end="url(#aw-aph)"/>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="300" y="74" width="150" height="52" rx="3"/>
    <text class="ttl" x="375" y="93" style="font-size:13px">헤딩 PI — 클램프 AW</text>
    <text class="ttl2" x="375" y="111">kp <tspan data-p="kp_hdg">4</tspan> · ki <tspan data-p="ki_hdg">0</tspan></text></g>
  <path class="wire" d="M450 100 H478" marker-end="url(#aw-aph)"/>
  <g class="sblk"><rect class="body" x="482" y="74" width="96" height="52" rx="3"/>
    <path d="M492 116 H506 L554 84 H568" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="530" y="144">클립 ±<tspan data-p="phi_max">0.7</tspan> rad</text>
  <path class="wire" d="M578 100 H806" marker-end="url(#aw-aph)"/>
  <circle class="branch" cx="640" cy="100" r="3.2"/>
  <g class="sblk"><rect class="body" x="810" y="88" width="36" height="24" rx="12"/><text class="pnum" x="828" y="104">1</text></g>
  <text class="pname" x="828" y="132">φ_cmd → SCAS 롤</text>
  <g class="sblk"><rect class="body" x="240" y="158" width="36" height="24" rx="12"/><text class="pnum" x="258" y="174">2</text></g>
  <text class="pname a-start" x="282" y="174">ψ (NavOutput)</text>
  <path class="wire" d="M258 158 V118" marker-end="url(#aw-aph)"/>
  <path class="wire ff" d="M640 100 V180" marker-end="url(#af-aph)"/>
  <text class="siglabel" x="640" y="200">→ 선회 FF (고도·속도 채널 가산)</text>
  <text class="canvas-note" x="24" y="272">※ 비활성(off) 시 필터는 ψ 추적 + 적분 소거 + φ_cmd=0 — 재관여 시 잔존 뱅크 킥 방지 · ±phi_max는 π/2 미만 강제 (선회 FF 부호 보전 가드)</text>
</svg>`,
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
  <g class="sblk"><rect class="body" x="30" y="88" width="36" height="24" rx="12"/><text class="pnum" x="48" y="104">1</text></g>
  <text class="pname" x="48" y="132">h_cmd ← 유도</text>
  <path class="wire" d="M66 100 H96" marker-end="url(#aw-apa)"/>
  <g class="sblk"><rect class="body" x="100" y="74" width="118" height="52" rx="3"/>
    <text class="ttl" x="159" y="93" style="font-size:13px">명령필터</text>
    <text class="ttl2" x="159" y="111">τ <tspan data-p="tau_alt">5</tspan> s</text></g>
  <text class="siglabel" x="159" y="144">off: h 추적 — 활성화 시 램프</text>
  <path class="wire" d="M218 100 H240" marker-end="url(#aw-apa)"/>
  <circle class="body" cx="258" cy="100" r="14"/>
  <text class="sumsign" x="249" y="104">+</text><text class="sumsign" x="258" y="113">−</text>
  <path class="wire" d="M272 100 H296" marker-end="url(#aw-apa)"/>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="300" y="74" width="140" height="52" rx="3"/>
    <text class="ttl" x="370" y="93" style="font-size:13px">고도 PI — 클램프 AW</text>
    <text class="ttl2" x="370" y="111">kp <tspan data-p="kp_alt">0.004</tspan> · ki <tspan data-p="ki_alt">0.0004</tspan></text></g>
  <path class="wire" d="M440 100 H446" marker-end="url(#aw-apa)"/>
  <circle class="body" cx="464" cy="100" r="14"/>
  <text class="sumsign" x="455" y="104">+</text><text class="sumsign" x="464" y="113">+</text>
  <path class="wire" d="M478 100 H492" marker-end="url(#aw-apa)"/>
  <g class="sblk"><rect class="body" x="496" y="74" width="90" height="52" rx="3"/>
    <path d="M506 116 H518 L564 84 H576" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="541" y="64">클립 <tspan data-p="theta_lo">−0.3</tspan>~<tspan data-p="theta_hi">0.3</tspan> rad</text>
  <path class="wire" d="M586 100 H612" marker-end="url(#aw-apa)"/>
  <circle class="body" cx="630" cy="100" r="14"/>
  <text class="sumsign" x="621" y="104">+</text><text class="sumsign" x="630" y="93">+</text>
  <path class="wire" d="M644 100 H700" marker-end="url(#aw-apa)"/>
  <g class="sblk"><rect class="body" x="704" y="74" width="82" height="52" rx="3"/>
    <path d="M712 116 H724 L766 84 H778" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="745" y="64">재클립 θ 한계</text>
  <path class="wire" d="M786 100 H806" marker-end="url(#aw-apa)"/>
  <g class="sblk"><rect class="body" x="810" y="88" width="36" height="24" rx="12"/><text class="pnum" x="828" y="104">1</text></g>
  <text class="pname" x="828" y="136">θ_cmd → α 리미터</text>
  <g class="sblk"><rect class="body" x="240" y="162" width="36" height="24" rx="12"/><text class="pnum" x="258" y="178">2</text></g>
  <text class="pname a-start" x="282" y="178">h = −z_n</text>
  <path class="wire" d="M258 162 V118" marker-end="url(#aw-apa)"/>
  <g class="sblk"><rect class="body" x="414" y="148" width="100" height="38" rx="3"/>
    <text class="ttl2" x="464" y="164" style="font-weight:700">× k_hdot</text>
    <text class="ttl2" x="464" y="180"><tspan data-p="k_hdot">−0.008</tspan> 승강률 댐핑</text></g>
  <path class="wire" d="M464 148 V118" marker-end="url(#aw-apa)"/>
  <g class="sblk"><rect class="body" x="446" y="210" width="36" height="24" rx="12"/><text class="pnum" x="464" y="226">3</text></g>
  <text class="pname a-start" x="490" y="226">ḣ = −v_z</text>
  <path class="wire" d="M464 210 V186" marker-end="url(#aw-apa)"/>
  <path class="wire ff" d="M630 190 V118" marker-end="url(#af-apa)"/>
  <text class="siglabel" x="630" y="210">선회 FF 피치 — <tspan data-p="k_pitch_turn">0.05</tspan>·(1/cosφ−1)</text>
  <text class="canvas-note" x="24" y="300">※ 선회 FF는 축 클립 후 가산 → 재클립 (이중 제한) · 트림 웜스타트: 고도 적분기 = 트림 θ [범프리스] · 비활성 시 필터가 h 추적 — 활성화 순간 현재값부터 램프</text>
</svg>`,
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
  <g class="sblk"><rect class="body" x="30" y="88" width="36" height="24" rx="12"/><text class="pnum" x="48" y="104">1</text></g>
  <text class="pname" x="48" y="132">V_cmd ← 유도</text>
  <path class="wire" d="M66 100 H96" marker-end="url(#aw-aps)"/>
  <g class="sblk"><rect class="body" x="100" y="74" width="118" height="52" rx="3"/>
    <text class="ttl" x="159" y="93" style="font-size:13px">명령필터</text>
    <text class="ttl2" x="159" y="111">τ <tspan data-p="tau_spd">2</tspan> s</text></g>
  <text class="siglabel" x="159" y="144">off: V 추적 · 트림 스로틀 홀드</text>
  <path class="wire" d="M218 100 H240" marker-end="url(#aw-aps)"/>
  <circle class="body" cx="258" cy="100" r="14"/>
  <text class="sumsign" x="249" y="104">+</text><text class="sumsign" x="258" y="113">−</text>
  <path class="wire" d="M272 100 H296" marker-end="url(#aw-aps)"/>
  <g class="sblk" data-code="fcl/autopilot.py:Autopilot.step"><rect class="body" x="300" y="74" width="140" height="52" rx="3"/>
    <text class="ttl" x="370" y="93" style="font-size:13px">속도 PI — 클램프 AW</text>
    <text class="ttl2" x="370" y="111">kp <tspan data-p="kp_spd">0.15</tspan> · ki <tspan data-p="ki_spd">0.03</tspan></text></g>
  <path class="wire" d="M440 100 H492" marker-end="url(#aw-aps)"/>
  <g class="sblk"><rect class="body" x="496" y="74" width="90" height="52" rx="3"/>
    <path d="M506 116 H518 L564 84 H576" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="541" y="144">클립 0~1</text>
  <path class="wire" d="M586 100 H612" marker-end="url(#aw-aps)"/>
  <circle class="body" cx="630" cy="100" r="14"/>
  <text class="sumsign" x="621" y="104">+</text><text class="sumsign" x="630" y="93">+</text>
  <path class="wire" d="M644 100 H700" marker-end="url(#aw-aps)"/>
  <g class="sblk"><rect class="body" x="704" y="74" width="82" height="52" rx="3"/>
    <path d="M712 116 H724 L766 84 H778" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="745" y="144">재클립 0~1</text>
  <path class="wire" d="M786 100 H806" marker-end="url(#aw-aps)"/>
  <g class="sblk"><rect class="body" x="810" y="88" width="36" height="24" rx="12"/><text class="pnum" x="828" y="104">1</text></g>
  <text class="pname" x="828" y="132">δt_cmd (0~1)</text>
  <g class="sblk"><rect class="body" x="240" y="162" width="36" height="24" rx="12"/><text class="pnum" x="258" y="178">2</text></g>
  <text class="pname a-start" x="282" y="178">V = |v_n| — 바람 0</text>
  <path class="wire" d="M258 162 V118" marker-end="url(#aw-aps)"/>
  <path class="wire ff" d="M630 190 V118" marker-end="url(#af-aps)"/>
  <text class="siglabel" x="560" y="210">선회 FF 스로틀 — <tspan data-p="k_thr_turn">0</tspan>·(1/cos²φ−1)</text>
  <text class="canvas-note" x="24" y="272">※ 선회 FF는 클립 후 가산 → 재클립 (이중 제한) · 트림 웜스타트: 속도 적분기 = 트림 스로틀 [범프리스] · δt_cmd는 믹서에서 차동추력 보상과 결합</text>
</svg>`,
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
  <g class="sblk"><rect class="body" x="30" y="48" width="36" height="24" rx="12"/><text class="pnum" x="48" y="64">1</text></g>
  <text class="pname" x="48" y="92">임무프로파일</text>
  <path class="wire soft" d="M66 60 H430 V146" marker-end="url(#as-guid)"/>
  <circle class="branch" cx="110" cy="60" r="3.2"/>
  <path class="wire soft" d="M110 60 V316 H356" marker-end="url(#as-guid)"/>
  <text class="siglabel" x="260" y="48">웨이포인트 열 · 모드 테이블 (편집: 시뮬 탭)</text>
  <!-- 항법 입력 → 유효성 게이트 -->
  <g class="sblk"><rect class="body" x="30" y="268" width="36" height="24" rx="12"/><text class="pnum" x="48" y="284">2</text></g>
  <text class="pname" x="48" y="312">NavOutput</text>
  <path class="wire" d="M66 280 H136" marker-end="url(#aw-guid)"/>
  <g class="sblk"><rect class="body" x="140" y="254" width="160" height="52" rx="3"/>
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
  <g class="sblk"><rect class="body" x="640" y="150" width="130" height="60" rx="3"/>
    <text class="ttl" x="705" y="170" style="font-size:13px">heading 선택</text>
    <text class="ttl2" x="705" y="186">"path" → ψ_wp</text>
    <text class="ttl2" x="705" y="200">그 외 → 모드값</text></g>
  <path class="wire" d="M770 180 H786 V296" marker-end="url(#aw-guid)"/>
  <text class="siglabel" x="810" y="176">ψ_cmd</text>
  <g class="sblk"><rect class="body" x="640" y="300" width="160" height="90" rx="3"/>
    <text class="ttl" x="720" y="322" style="font-size:13px">GuidanceCommand</text>
    <text class="ttl2" x="720" y="342">speed · alt · heading 구성</text>
    <text class="ttl2" x="720" y="358">None → 축 비활성 플래그</text>
    <text class="ttl2" x="720" y="374">mode 이름 포함</text></g>
  <path class="wire" d="M800 345 H866" marker-end="url(#aw-guid)"/>
  <g class="sblk"><rect class="body" x="870" y="333" width="36" height="24" rx="12"/><text class="pnum" x="888" y="349">1</text></g>
  <text class="pname" x="886" y="377">→ AP</text>
  <text class="canvas-note" x="24" y="440">※ 모드 전환 순간의 명령 점프는 오토파일럿 명령필터가 완충 [기본값] — Fader 페이딩은 백로그 · 경로추종은 헤딩만 담당 (고도·속도는 모드 테이블 소관)</text>
  <text class="canvas-note" x="24" y="462">모드 시퀀스 예: 이륙 → 상승 → (순항 · 고도유지 · 디센트 · 임무수행 · 웨이포인트 항법) → 착륙 · Stateflow 미사용 [확정]</text>
</svg>`,
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
  <g class="sblk"><rect class="body" x="30" y="96" width="36" height="24" rx="12"/><text class="pnum" x="48" y="112">1</text></g>
  <text class="pname" x="52" y="140">NavOutput</text>
  <path class="wire" d="M66 108 H96" marker-end="url(#aw-gpath)"/>
  <g class="sblk"><rect class="body" x="100" y="82" width="170" height="52" rx="3"/>
    <text class="ttl" x="185" y="101" style="font-size:13px">위치 추출</text>
    <text class="ttl2" x="185" y="119">(n, e) = pos_n 수평면</text></g>
  <path class="wire" d="M270 108 H316" marker-end="url(#aw-gpath)"/>
  <g class="sblk" data-code="guidance/path.py:LosPath.step"><rect class="body" x="320" y="72" width="260" height="72" rx="3"/>
    <text class="ttl" x="450" y="94" style="font-size:13px">도달 판정 — 연쇄 스킵 (while)</text>
    <text class="ttl2" x="450" y="112">dn·de = 활성 WP − (n, e)</text>
    <text class="ttl2" x="450" y="130">√(dn²+de²) ≤ 도달반경 → 다음 WP</text></g>
  <path class="wire" d="M580 108 H636" marker-end="url(#aw-gpath)"/>
  <text class="siglabel" x="608" y="96">미도달</text>
  <g class="sblk"><rect class="body" x="640" y="82" width="180" height="52" rx="3"/>
    <text class="ttl" x="730" y="101" style="font-size:13px">LOS 방위각</text>
    <text class="ttl2" x="730" y="119">ψ_wp = atan2(de, dn)</text></g>
  <path class="wire" d="M820 108 H866" marker-end="url(#aw-gpath)"/>
  <g class="sblk"><rect class="body" x="870" y="96" width="36" height="24" rx="12"/><text class="pnum" x="888" y="112">1</text></g>
  <text class="pname" x="884" y="140">ψ_wp → heading 선택</text>
  <path class="wire" d="M450 144 V196" marker-end="url(#aw-gpath)"/>
  <text class="siglabel" x="540" y="176">잔여 WP 없음 (소진)</text>
  <g class="sblk"><rect class="body" x="340" y="200" width="220" height="72" rx="3"/>
    <text class="ttl" x="450" y="222" style="font-size:13px">웨이포인트 소진</text>
    <text class="ttl2" x="450" y="242">done=True · 마지막 헤딩 유지</text>
    <text class="ttl2" x="450" y="260">미계산 소진 → 현재 침로 시드</text></g>
  <path class="wire" d="M560 236 H700" marker-end="url(#aw-gpath)"/>
  <g class="sblk"><rect class="body" x="704" y="224" width="36" height="24" rx="12"/><text class="pnum" x="722" y="240">2</text></g>
  <text class="pname" x="726" y="268">alt·done → 모드 시퀀서</text>
  <text class="canvas-note" x="24" y="320">※ 반경 내 연쇄 스킵 — 붙은 웨이포인트 여러 개를 한 스텝에 통과 · done 후 heading은 마지막 값 유지, alt는 마지막 웨이포인트 고도로 정착 — 계약은 (heading, alt, done)</text>
  <text class="canvas-note" x="24" y="340">※ 소진 안전: 첫 헤딩 계산 전 소진(빈 목록·반경 내 시작)이면 정북(0) 아닌 현재 침로 명령 — 조용한 급선회 방지 · 도달반경 엔진 기본 200 m [기본값] / 시뮬 탭 폼 1500 m — 편집: 시뮬 탭</text>
  <text class="canvas-note" x="24" y="360">※ 경로가 헤딩과 **세로 프로파일**을 낸다 — 모드가 alt=&quot;path&quot;일 때만 쓰인다(heading과 같은 규약) · 속도는 모드 소관 · 대안은 같은 step(nav)→(heading, alt, done) 계약 [TBD 01 §3.3]</text>
</svg>`,
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
  <g class="sblk"><rect class="body" x="370" y="36" width="330" height="80" rx="3"/>
    <text class="ttl" x="535" y="58" style="font-size:13px">모드 테이블 {name → ModeSpec}</text>
    <text class="ttl2" x="535" y="78">speed·alt·heading — None = 축 비활성</text>
    <text class="ttl2" x="535" y="94">heading: 숫자 | "path" | None</text>
    <text class="ttl2" x="535" y="110">구성 검증: 이름 중복·next 참조·조건 arity</text></g>
  <path class="wire soft" d="M535 116 V166" marker-end="url(#as-gmod)"/>
  <g class="sblk"><rect class="body" x="210" y="150" width="150" height="52" rx="3"/>
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
  <g class="sblk"><rect class="body" x="730" y="170" width="190" height="64" rx="3"/>
    <text class="ttl" x="825" y="192" style="font-size:13px">전환</text>
    <text class="ttl2" x="825" y="212">name ← next</text>
    <text class="ttl2" x="825" y="228">t_entry ← t (체류 리셋)</text></g>
  <path class="wire" d="M820 234 V330 H285 V206" marker-end="url(#aw-gmod)"/>
  <g class="sblk"><rect class="body" x="30" y="218" width="36" height="24" rx="12"/><text class="pnum" x="48" y="234">1</text></g>
  <text class="pname" x="52" y="262">NavOutput</text>
  <path class="wire" d="M66 230 H396" marker-end="url(#aw-gmod)"/>
  <g class="sblk"><rect class="body" x="30" y="288" width="36" height="24" rx="12"/><text class="pnum" x="48" y="304">2</text></g>
  <text class="pname" x="95" y="332">path_done ← 경로추종</text>
  <path class="wire" d="M66 300 H370 V262 H396" marker-end="url(#aw-gmod)"/>
  <path class="wire" d="M535 280 V360 H866" marker-end="url(#aw-gmod)"/>
  <text class="siglabel" x="620" y="352">cur — 전환 반영 후</text>
  <g class="sblk"><rect class="body" x="870" y="348" width="36" height="24" rx="12"/><text class="pnum" x="888" y="364">1</text></g>
  <text class="pname" x="870" y="392">활성 ModeSpec</text>
  <text class="pname" x="860" y="410">→ GuidanceCommand 구성</text>
  <text class="canvas-note" x="24" y="424">※ Stateflow 미사용 [확정 01 §3.3.1] — 순차 체인: 진입 = 이전 모드의 이탈 → next [기본값] · 초기 모드 진입 시각 = 첫 스텝 t · 항법 무효 시 상류 유효성 게이트가 동결</text>
</svg>`,
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
  <g class="sblk"><rect class="body" x="30" y="68" width="36" height="24" rx="12"/><text class="pnum" x="48" y="84">1</text></g>
  <text class="pname" x="56" y="112">θ_cmd ← AP</text>
  <path class="wire" d="M66 80 H556" marker-end="url(#aw-lim)"/>
  <g class="sblk"><rect class="body" x="560" y="50" width="120" height="60" rx="3"/>
    <path d="M572 96 L620 66 H648" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="620" y="134">min(θ_cmd, cap) — 상한만</text>
  <path class="wire" d="M680 80 H746" marker-end="url(#aw-lim)"/>
  <g class="sblk"><rect class="body" x="750" y="68" width="36" height="24" rx="12"/><text class="pnum" x="768" y="84">1</text></g>
  <text class="pname" x="768" y="112">θ_cmd′ → SCAS</text>
  <!-- 동적 상한: cap = θ + (α_stall(mach) − margin − α) -->
  <g class="sblk"><rect class="body" x="30" y="218" width="36" height="24" rx="12"/><text class="pnum" x="48" y="234">2</text></g>
  <text class="pname" x="48" y="262">Mach</text>
  <path class="wire" d="M66 230 H96" marker-end="url(#aw-lim)"/>
  <g class="sblk" data-code="fcl/limiter.py:AlphaLimiter.alpha_max"><rect class="body" x="100" y="200" width="190" height="60" rx="3"/>
    <path d="M112 246 L128 246 L142 224 L158 236 L172 218" stroke="#8a97a5" stroke-width="1.6" fill="none"/>
    <text class="ttl" x="234" y="224" style="font-size:13px">α_stall(mach)</text>
    <text class="ttl2" x="234" y="242">1D · 외삽 clip 강제</text></g>
  <path class="wire" d="M290 230 H316" marker-end="url(#aw-lim)"/>
  <g class="sblk"><rect class="body" x="320" y="200" width="130" height="60" rx="3"/>
    <text class="ttl" x="385" y="224" style="font-size:13px">− 보호마진</text>
    <text class="ttl2" x="385" y="242">0.05 rad ≈ 2.9°</text></g>
  <path class="wire" d="M450 230 H476" marker-end="url(#aw-lim)"/>
  <text class="siglabel" x="460" y="212">α_max</text>
  <circle class="body" cx="494" cy="230" r="14"/>
  <text class="sumsign" x="485" y="234">+</text><text class="sumsign" x="494" y="243">−</text>
  <path class="wire" d="M508 230 H602" marker-end="url(#aw-lim)"/>
  <text class="siglabel" x="554" y="212">Δα 실속 마진</text>
  <circle class="branch" cx="560" cy="230" r="3.2"/>
  <circle class="body" cx="620" cy="230" r="14"/>
  <text class="sumsign" x="611" y="234">+</text><text class="sumsign" x="629" y="234">+</text>
  <path class="wire" d="M620 216 V114" marker-end="url(#aw-lim)"/>
  <text class="siglabel" x="556" y="170">cap = θ + Δα</text>
  <!-- 실속 마진 출력 — 엔벨로프 감시 -->
  <path class="wire" d="M560 230 V380 H700" marker-end="url(#aw-lim)"/>
  <g class="sblk"><rect class="body" x="704" y="368" width="36" height="24" rx="12"/><text class="pnum" x="722" y="384">2</text></g>
  <text class="pname" x="722" y="412">실속 마진 Δα → 엔벨로프 감시</text>
  <!-- NavOutput 추출 -->
  <g class="sblk"><rect class="body" x="30" y="298" width="36" height="24" rx="12"/><text class="pnum" x="48" y="314">3</text></g>
  <text class="pname" x="52" y="342">NavOutput</text>
  <path class="wire" d="M66 310 H136" marker-end="url(#aw-lim)"/>
  <g class="sblk"><rect class="body" x="140" y="282" width="220" height="56" rx="3"/>
    <text class="ttl" x="250" y="304" style="font-size:13px">airdata · quat→euler</text>
    <text class="ttl2" x="250" y="324">α · θ 추출 — NavOutput만 소비</text></g>
  <path class="wire" d="M360 298 H450 V244" marker-end="url(#aw-lim)"/>
  <text class="siglabel" x="436" y="268">α</text>
  <path class="wire" d="M360 322 H680 V244 H634" marker-end="url(#aw-lim)"/>
  <text class="siglabel" x="666" y="268">θ</text>
  <text class="canvas-note" x="24" y="442">※ 반환 = (제한 θ_cmd′ · 작동 플래그 · 실속 마진 Δα) — 플래그·마진은 law 로깅 속성 → 엔벨로프 감시(02 §6.1) 소비 · mach는 law가 항법 고도의 ISA 음속으로 산출</text>
  <text class="canvas-note" x="24" y="462">※ 상한만 개입 — 하한 없음 · 근거: θ = γ + α 근사 (θ 증분 = α 증분 · γ 변화는 여유 회복 방향) · 1D (mach,) 외 테이블·clip 외 외삽은 생성 시 거부</text>
</svg>`,
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
    title: "엘레본 믹싱 (제어 할당)", eng: "Elevon Mixing / Control Allocation — 차동추력 보상 포함",
    chips: ["dft", "tbd"],
    svg: `
<svg viewBox="0 0 940 516" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-mix" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <!-- 엘레본 좌/우 — 교차 결합 (X자 1회 교차는 믹싱의 본질) -->
  <g class="sblk"><rect class="body" x="30" y="66" width="36" height="24" rx="12"/><text class="pnum" x="48" y="82">1</text></g>
  <text class="pname" x="48" y="112">피치 δe</text>
  <path class="wire" d="M66 78 H246" marker-end="url(#aw-mix)"/>
  <circle class="branch" cx="150" cy="78" r="3.2"/>
  <path class="wire" d="M150 78 V170 H246" marker-end="url(#aw-mix)"/>
  <g class="sblk"><rect class="body" x="30" y="182" width="36" height="24" rx="12"/><text class="pnum" x="48" y="198">2</text></g>
  <text class="pname" x="48" y="232">롤 δa</text>
  <path class="wire" d="M66 194 H246" marker-end="url(#aw-mix)"/>
  <circle class="branch" cx="110" cy="194" r="3.2"/>
  <path class="wire" d="M110 194 V102 H246" marker-end="url(#aw-mix)"/>
  <g class="sblk" data-code="fcl/mixer.py:Mixer.step"><rect class="body" x="250" y="64" width="150" height="52" rx="3"/>
    <text class="ttl" x="325" y="86" style="font-size:13px">좌측 = δe + δa</text>
    <text class="ttl2" x="325" y="104">내좌 = 외좌 (1:1 고정)</text></g>
  <g class="sblk"><rect class="body" x="250" y="156" width="150" height="52" rx="3"/>
    <text class="ttl" x="325" y="178" style="font-size:13px">우측 = δe − δa</text>
    <text class="ttl2" x="325" y="196">내우 = 외우 (1:1 고정)</text></g>
  <path class="wire" d="M400 90 H426" marker-end="url(#aw-mix)"/>
  <g class="sblk"><rect class="body" x="430" y="64" width="110" height="52" rx="3"/>
    <path d="M442 106 H458 L512 74 H528" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="485" y="134">elevon_lo~hi</text>
  <path class="wire" d="M540 90 H610"/>
  <circle class="branch" cx="614" cy="90" r="3.2"/>
  <path class="wire" d="M614 90 V78 H796" marker-end="url(#aw-mix)"/>
  <path class="wire" d="M614 90 V106 H796" marker-end="url(#aw-mix)"/>
  <g class="sblk"><rect class="body" x="800" y="66" width="36" height="24" rx="12"/><text class="pnum" x="818" y="82">1</text></g>
  <text class="pname" x="864" y="82">내좌</text>
  <g class="sblk"><rect class="body" x="800" y="94" width="36" height="24" rx="12"/><text class="pnum" x="818" y="110">2</text></g>
  <text class="pname" x="864" y="110">외좌</text>
  <path class="wire" d="M400 182 H426" marker-end="url(#aw-mix)"/>
  <g class="sblk"><rect class="body" x="430" y="156" width="110" height="52" rx="3"/>
    <path d="M442 198 H458 L512 166 H528" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="485" y="226">elevon_lo~hi</text>
  <path class="wire" d="M540 182 H610"/>
  <circle class="branch" cx="614" cy="182" r="3.2"/>
  <path class="wire" d="M614 182 V170 H796" marker-end="url(#aw-mix)"/>
  <path class="wire" d="M614 182 V198 H796" marker-end="url(#aw-mix)"/>
  <g class="sblk"><rect class="body" x="800" y="158" width="36" height="24" rx="12"/><text class="pnum" x="818" y="174">3</text></g>
  <text class="pname" x="864" y="174">내우</text>
  <g class="sblk"><rect class="body" x="800" y="186" width="36" height="24" rx="12"/><text class="pnum" x="818" y="202">4</text></g>
  <text class="pname" x="864" y="202">외우</text>
  <!-- 러더 + 차동추력 (클램프된 실 러더 기준) -->
  <g class="sblk"><rect class="body" x="30" y="270" width="36" height="24" rx="12"/><text class="pnum" x="48" y="286">3</text></g>
  <text class="pname" x="48" y="316">요 δr</text>
  <path class="wire" d="M66 282 H246" marker-end="url(#aw-mix)"/>
  <g class="sblk"><rect class="body" x="250" y="256" width="110" height="52" rx="3"/>
    <path d="M262 298 H278 L332 266 H348" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="305" y="326">rudder_lo~hi</text>
  <path class="wire" d="M360 282 H796" marker-end="url(#aw-mix)"/>
  <circle class="branch" cx="470" cy="282" r="3.2"/>
  <g class="sblk"><rect class="body" x="800" y="270" width="36" height="24" rx="12"/><text class="pnum" x="818" y="286">5</text></g>
  <text class="pname" x="818" y="314">러더</text>
  <path class="wire" d="M470 282 V326" marker-end="url(#aw-mix)"/>
  <g class="sblk"><rect class="body" x="410" y="330" width="120" height="46" rx="3"/>
    <text class="ttl" x="470" y="349" style="font-size:13px">× k_diff_thr</text>
    <text class="ttl2" x="470" y="366">클램프된 실 러더 기준</text></g>
  <path class="wire" d="M530 353 H620 V384" marker-end="url(#aw-mix)"/>
  <text class="siglabel" x="575" y="345">d</text>
  <g class="sblk"><rect class="body" x="30" y="408" width="36" height="24" rx="12"/><text class="pnum" x="48" y="424">4</text></g>
  <text class="pname" x="48" y="454">집합 스로틀 δt</text>
  <path class="wire" d="M66 420 H556" marker-end="url(#aw-mix)"/>
  <g class="sblk"><rect class="body" x="560" y="388" width="160" height="64" rx="3"/>
    <text class="ttl" x="640" y="408" style="font-size:13px">차동 분배</text>
    <text class="ttl2" x="640" y="426">좌 = δt − d · 우 = δt + d</text>
    <text class="ttl2" x="640" y="442">출력 0~1 클립</text></g>
  <path class="wire" d="M720 406 H796" marker-end="url(#aw-mix)"/>
  <g class="sblk"><rect class="body" x="800" y="394" width="36" height="24" rx="12"/><text class="pnum" x="818" y="410">6</text></g>
  <path class="wire" d="M720 434 H796" marker-end="url(#aw-mix)"/>
  <g class="sblk"><rect class="body" x="800" y="422" width="36" height="24" rx="12"/><text class="pnum" x="818" y="438">7</text></g>
  <text class="pname" x="818" y="470">스로틀 ×2 (좌·우)</text>
  <text class="canvas-note" x="24" y="502">※ 재구성 항등: 평균 = δe · (좌−우)/2 = δa — 믹싱이 정보를 잃지 않음 · rate 한계는 작동기(M5) 소관 · SurfaceCommand 순서 [내좌, 외좌, 내우, 외우]</text>
</svg>`,
    notes: `
<h4>설계 노트</h4>
<ul>
  <li>용어: 현 구현은 고정 행렬 <b>엘레본 믹싱</b> — 여유자유도 <b>최적 배분(제어 할당, control allocation)</b>으로의 승격은 추후 확장 <span class="chip dft">기본값 01 §2.2</span></li>
  <li>좌측(내·외) = δe + δa, 우측(내·외) = δe − δa — 내/외측 쌍 1:1 고정, 면별 elevon_lo~hi 클립 <span class="chip dft">기본값</span></li>
  <li>요축: 러더(rudder_lo~hi 클립) + <b>차동추력</b> d = k_diff_thr × <b>클램프된 실 러더</b> — 러더가 내지 못하는 명령에 추력이 반응하지 않음 · 포화 시 추력 인계는 별도 설계 <span class="chip tbd">TBD</span></li>
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
  <g class="sblk"><rect class="body" x="30" y="88" width="36" height="24" rx="12"/><text class="pnum" x="48" y="104">1</text></g>
  <text class="pname" x="48" y="128">δ_cmd</text>
  <path class="wire" d="M66 100 H136" marker-end="url(#aw-act)"/>
  <g class="sblk" data-code="plant/actuator.py:SecondOrderActuator.step"><rect class="body" x="140" y="64" width="190" height="72" rx="3"/>
    <text class="ttl2" x="235" y="90" style="font-size:13px">ωn²</text>
    <line x1="170" y1="98" x2="300" y2="98" stroke="#111" stroke-width="1.4"/>
    <text class="ttl2" x="235" y="118" style="font-size:12px">s² + 2ζωn·s + ωn²</text></g>
  <text class="bname" x="235" y="156">2차계 — wn <tspan data-p="wn">30</tspan> rad/s · ζ <tspan data-p="zeta">0.7</tspan></text>
  <path class="wire" d="M330 100 H396" marker-end="url(#aw-act)"/>
  <g class="sblk"><rect class="body" x="400" y="70" width="100" height="60" rx="3"/>
    <path d="M412 118 L438 82 L488 82" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="450" y="150">rate_max <tspan data-p="rate_max">10</tspan> rad/s (≥ 10 요구)</text>
  <path class="wire" d="M500 100 H566" marker-end="url(#aw-act)"/>
  <g class="sblk"><rect class="body" x="570" y="70" width="100" height="60" rx="3"/>
    <path d="M580 116 H598 L642 84 H660" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="620" y="150">위치 한계 = 믹서 타면 한계</text>
  <path class="wire" d="M670 100 H736" marker-end="url(#aw-act)"/>
  <g class="sblk"><rect class="body" x="740" y="88" width="36" height="24" rx="12"/><text class="pnum" x="758" y="104">1</text></g>
  <text class="pname" x="758" y="128">δ (타면 변위)</text>
</svg>`,
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
    title: "기체 동역학 (6DOF) — 트림 · 선형해석의 기반", eng: "Aircraft Dynamics · 델타윙 쌍발",
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
  <text class="pname" x="48" y="252">스로틀 ×2</text>
  <path class="wire" d="M66 220 H146" marker-end="url(#aw-pl)"/>
  <g class="blk" data-child="prop" data-code="plant/prop.py:TwinEngine" tabindex="0"><rect class="body" x="150" y="184" width="290" height="72" rx="3"/>
    <text class="ttl" x="295" y="206" style="font-size:13px">추진 — TwinEngine</text>
    <text class="ttl2" x="295" y="226">추력 맵 [기본 max_thrust·δt] · 0~1 클립</text>
    <text class="ttl2" x="295" y="244">M = r_L×F_L + r_R×F_R · 클릭 → 내부</text></g>
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
  <text class="pname" x="925" y="220">→ 항법만 (참값 차단)</text>
  <circle class="branch" cx="938" cy="166" r="3.2"/>
  <path class="wire soft" d="M938 166 V36 H295 V56" marker-end="url(#as-pl)"/>
  <text class="siglabel" x="610" y="28">상태 피드백 (참값): v_b · ω_b · q_nb · h</text>
  <g class="blk" data-child="mass" data-code="plant/mass.py:FuelMass" tabindex="0"><rect class="body" x="660" y="340" width="280" height="72" rx="3"/>
    <text class="ttl" x="800" y="362" style="font-size:13px">질량특성 — FuelMass.at(fuel)</text>
    <text class="ttl2" x="800" y="382">m · cg · J — 잔여 연료 선형 보간</text>
    <text class="ttl2" x="800" y="400">스텝 사이 갱신 [준정적] · 클릭 → 내부</text></g>
  <path class="wire soft" d="M800 340 V240" marker-end="url(#as-pl)"/>
  <text class="siglabel" x="836" y="300">m · J</text>
  <path class="wire soft" d="M660 376 H470 V318 H444" marker-end="url(#as-pl)"/>
  <text class="siglabel" x="556" y="368">m (중력)</text>
  <rect x="150" y="470" width="520" height="56" rx="8" fill="none" stroke="#7c3aed" stroke-width="1.4" stroke-dasharray="6 4"/>
  <text class="annot" x="410" y="494" text-anchor="middle" fill="#7c3aed">① 이 플랜트 기반 설계 1단계 — 트림 (100+ 케이스 배치)</text>
  <text class="annot" x="410" y="514" text-anchor="middle" fill="#7c3aed">→ 구간 선형화 → 고유치·감쇠비 · 이득·위상여유 마진 맵</text>
  <text class="canvas-note" x="24" y="560">※ 바람 0 가정 (v_air = v_b) — 바람·난류(Dryden)는 확장 항목 · 공력 부호·기준점은 DB가 정의 — 코드 무가정 (풍축 CL·CD는 변환 헬퍼)</text>
  <text class="canvas-note" x="24" y="580">※ 모멘트 CG 기준점 이전은 DB 규격 확정 시 조립 지점에서 [TBD] · 오일러 12-상태 미분도 제공 — 트림·수치섭동 선형화(M9) 전용</text>
</svg>`,
    notes: `
<h4>플랜트</h4>
<ul>
  <li>형상: <b>델타윙, 쌍발 엔진</b> · 조종면 엘레본×4 + 러더×1 · 요축 보조 차동추력 <span class="chip ok">확정</span></li>
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
        title: "추진 — TwinEngine", eng: "스로틀-추력 맵 + 엔진 배치 모멘트 (차동추력 부호 기준)",
        chips: ["ok", "dft", "tbd"],
        svg: `
<svg viewBox="0 0 960 250" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-pprop" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <g class="sblk" data-code="plant/prop.py:TwinEngine.forces"><rect class="body" x="30" y="92" width="36" height="24" rx="12"/><text class="pnum" x="48" y="108">1</text></g>
  <text class="pname" x="48" y="136">스로틀 [좌, 우]</text>
  <path class="wire" d="M66 104 H106" marker-end="url(#aw-pprop)"/>
  <g class="sblk" data-code="plant/prop.py:TwinEngine.forces"><rect class="body" x="110" y="78" width="140" height="52" rx="3"/>
    <text class="ttl" x="180" y="97" style="font-size:13px">0~1 클립</text>
    <text class="ttl2" x="180" y="115">좌·우 각각 (규약)</text></g>
  <path class="wire" d="M250 104 H286" marker-end="url(#aw-pprop)"/>
  <g class="sblk" data-code="plant/prop.py:TwinEngine.forces"><rect class="body" x="290" y="78" width="220" height="52" rx="3"/>
    <text class="ttl" x="400" y="97" style="font-size:13px">추력 맵 thrust_map(δt)</text>
    <text class="ttl2" x="400" y="115">기본 max_thrust·δt 선형 [기본값]</text></g>
  <path class="wire" d="M510 104 H546" marker-end="url(#aw-pprop)"/>
  <g class="sblk" data-code="plant/prop.py:TwinEngine.forces"><rect class="body" x="550" y="66" width="260" height="88" rx="3"/>
    <text class="ttl" x="680" y="88" style="font-size:13px">엔진 배치 모멘트</text>
    <text class="ttl2" x="680" y="108">r_L = (x, −y, z) · r_R = (x, +y, z)</text>
    <text class="ttl2" x="680" y="126">M = r_L×F_L + r_R×F_R</text>
    <text class="ttl2" x="680" y="142">좌 추력 우세 → +N (기수 우측)</text></g>
  <path class="wire" d="M810 104 H846" marker-end="url(#aw-pprop)"/>
  <g class="sblk" data-code="plant/prop.py:TwinEngine.forces"><rect class="body" x="850" y="92" width="36" height="24" rx="12"/><text class="pnum" x="868" y="108">1</text></g>
  <text class="pname" x="868" y="136">F_b · M_b → Σ</text>
  <text class="canvas-note" x="24" y="204">※ 요축 보조 차동추력의 부호 기준 [확정 01 §2.4] — 믹서의 d = k_diff_thr·러더 배분이 이 모멘트를 소비 · 추력은 동체 +X 정렬</text>
  <text class="canvas-note" x="24" y="224">※ thrust_map 콜러블 주입 가능 — 실기체 추력 맵 데이터 [TBD] 대비 · y_offset 음수는 생성 거부</text>
</svg>`,
        notes: `
<h4>설계 노트</h4>
<ul>
  <li>쌍발 — 요축 보조 <b>차동추력</b>의 부호 기준: 좌 추력 우세 → +N(기수 우측) <span class="chip ok">확정 01 §2.4</span> · 믹서의 차동 배분(d = k_diff_thr·러더)이 이 모멘트를 소비</li>
  <li>스로틀-추력: <span class="mono">thrust_map(δt)</span> 콜러블 주입 가능 — 실기체 추력 맵 데이터 <span class="chip tbd">TBD</span> 대비 · 기본은 max_thrust·δt 선형 <span class="chip dft">기본값</span></li>
  <li>엔진 위치 r_L·r_R는 CG 기준 동체축 — CG 이동 반영은 모멘트 기준점 이전과 같은 조립 지점에서 <span class="chip tbd">TBD</span></li>
  <li>입력은 SurfaceCommand 규약 [좌, 우] 0~1 — 범위 밖은 클립</li>
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
  <path class="wire" d="M910 104 H926" marker-end="url(#aw-peom)"/>
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
  <path class="wire note" d="M320 164 V196 H466 V580 H846" marker-end="url(#as-peom)"/>
  <g class="sblk nblk"><rect class="body" x="850" y="568" width="36" height="24" rx="12"/><text class="pnum" x="868" y="584">8</text></g>
  <text class="pname a-start" x="894" y="584">dω_b/dt — 표시 전용</text>
  <path class="wire note" d="M360 164 V208 H480 V620 H846" marker-end="url(#as-peom)"/>
  <g class="sblk nblk"><rect class="body" x="850" y="608" width="36" height="24" rx="12"/><text class="pnum" x="868" y="624">9</text></g>
  <text class="pname a-start" x="894" y="624">A_bb — 표시 전용</text>
  <text class="canvas-note" x="24" y="652">※ 출력 ②~⑨ = MathWorks 6DOF (Quaternion) 블록 출력 병기 — ③⑥⑦은 상태 원소, ②④⑤는 소비 측 파생 함수(색 블록), ⑧⑨(각가속도·동체 가속도)는 엔진 미구현: RK4 안에서 계산되고 버려진다 (표시 전용)</text>
  <text class="canvas-note" x="24" y="672">※ 상태 x(13) = [p_n(3) · v_b(3) · q_nb(4) · ω_b(3)] — NED · 동체 FRD · scalar-first Hamilton [conventions.md] · 중력 포함 여부는 조립자 몫 (플랜트 fm이 포함)</text>
  <text class="canvas-note" x="24" y="692">※ 질량 양수 · J 3×3 대칭 · 주대각 양수 아니면 생성 거부 · 오일러 12-상태 미분(deriv_euler)은 트림·수치섭동 선형화 전용 — θ=±π/2 특이점 근방 금지</text>
</svg>`,
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
<svg viewBox="0 0 1000 470" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-nav" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <g class="sblk"><rect class="body" x="30" y="128" width="36" height="24" rx="12"/><text class="pnum" x="48" y="144">1</text></g>
  <text class="pname" x="85" y="176">참값 VehicleState</text>
  <path class="wire" d="M66 140 H126" marker-end="url(#aw-nav)"/>
  <g class="sblk"><rect class="body" x="130" y="112" width="180" height="56" rx="3"/>
    <text class="ttl" x="220" y="134" style="font-size:13px">갱신 데시메이션</text>
    <text class="ttl2" x="220" y="152"><tspan data-p="update_hz">100</tspan> Hz · 틱 정수배 강제</text></g>
  <path class="wire" d="M310 140 H362" marker-end="url(#aw-nav)"/>
  <circle class="body" cx="380" cy="140" r="14"/>
  <text class="sumsign" x="371" y="144">+</text><text class="sumsign" x="380" y="131">+</text><text class="sumsign" x="380" y="153">+</text>
  <g class="sblk" data-code="nav/error_model.py:NavErrorModel.step"><rect class="body" x="250" y="16" width="260" height="70" rx="3"/>
    <text class="ttl" x="380" y="38" style="font-size:13px">1차 마르코프 바이어스 — 위치축</text>
    <text class="ttl2" x="380" y="56">σ 수평 <tspan data-p="bias_std_h">1</tspan> · 수직 <tspan data-p="bias_std_v">1.5</tspan> m · τ <tspan data-p="bias_tau">60</tspan> s</text>
    <text class="ttl2" x="380" y="74">b ← p·b + σ√(1−p²)·w · p=e^(−T/τ)</text></g>
  <path class="wire" d="M380 86 V122" marker-end="url(#aw-nav)"/>
  <g class="sblk"><rect class="body" x="250" y="196" width="260" height="70" rx="3"/>
    <text class="ttl" x="380" y="212" style="font-size:13px">백색잡음 (상태별 σ · 수평↔수직 분리)</text>
    <text class="ttl2" x="380" y="230">pos 수평 <tspan data-p="pos_std_h">3</tspan> · 수직 <tspan data-p="pos_std_v">4.5</tspan> m</text>
    <text class="ttl2" x="380" y="246">vel 수평 <tspan data-p="vel_std_h">0.3</tspan> · 수직 <tspan data-p="vel_std_v">0.45</tspan> m/s</text>
    <text class="ttl2" x="380" y="262">각속도 <tspan data-p="rate_std">0.001</tspan> rad/s</text></g>
  <path class="wire" d="M380 196 V158" marker-end="url(#aw-nav)"/>
  <path class="wire" d="M394 140 H426" marker-end="url(#aw-nav)"/>
  <g class="sblk"><rect class="body" x="430" y="104" width="260" height="72" rx="3"/>
    <text class="ttl" x="560" y="126" style="font-size:13px">자세 — q_nb ⊗ δq (노름 유지)</text>
    <text class="ttl2" x="560" y="146">δq = (1, ½ε) 소각 오차</text>
    <text class="ttl2" x="560" y="164">ε: 롤·피치 <tspan data-p="att_std">0.002</tspan> · 방위 <tspan data-p="psi_std">0.005</tspan> rad</text></g>
  <path class="wire" d="M690 140 H716" marker-end="url(#aw-nav)"/>
  <g class="sblk"><rect class="body" x="720" y="104" width="200" height="72" rx="3"/>
    <text class="ttl" x="820" y="126" style="font-size:13px">지연 큐 (deque)</text>
    <text class="ttl2" x="820" y="146">릴리스 지연 <tspan data-p="delay_s">0.03</tspan> s</text>
    <text class="ttl2" x="820" y="164">t_meas ≤ t − 지연 → 릴리스</text></g>
  <path class="wire" d="M820 176 V246" marker-end="url(#aw-nav)"/>
  <g class="sblk"><rect class="body" x="720" y="250" width="200" height="72" rx="3"/>
    <text class="ttl" x="820" y="272" style="font-size:13px">홀드 · valid 게이트</text>
    <text class="ttl2" x="820" y="292">다음 릴리스까지 유지 (ZOH)</text>
    <text class="ttl2" x="820" y="310">첫 릴리스 전 valid=False</text></g>
  <path class="wire" d="M920 286 H926" marker-end="url(#aw-nav)"/>
  <g class="sblk"><rect class="body" x="930" y="274" width="36" height="24" rx="12"/><text class="pnum" x="948" y="290">1</text></g>
  <text class="pname" x="948" y="322">NavOutput</text>
  <text class="canvas-note" x="24" y="404">※ 측정 = 참값 + 바이어스(위치) + 백색잡음 · 바이어스·잡음 갱신은 측정 틱마다 (T = 갱신주기) · fuel은 참값 통과 (연료 게이지) · 자세는 동체측 δq 곱 — 단위 노름 유지</text>
  <text class="canvas-note" x="24" y="426">※ 갱신주기가 틱 주기의 정수배 아니면 조립 시점 거부 · 항법이 틱보다 빠르면 틱마다 새 측정 · 릴리스는 배열 복사 — 소비자 훼손이 보관 측정을 오염시키지 않음</text>
  <text class="canvas-note" x="24" y="448">※ 난수 seed <tspan data-p="seed">0</tspan> 고정 결정적 (몬테카를로 재현성) · 법칙·유도·스케줄은 NavOutput만 소비 [참값 차단 계약 03 §4]</text>
</svg>`,
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
<svg viewBox="0 0 900 440" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="aw-gs2" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker>
    <marker id="as-gs2" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#8a97a5"/></marker>
  </defs>
  <g class="sblk"><rect class="body" x="30" y="78" width="36" height="24" rx="12"/><text class="pnum" x="48" y="94">1</text></g>
  <text class="pname" x="48" y="122">Mach</text>
  <text class="siglabel" x="52" y="138">V / a(h_ISA)</text>
  <path class="wire" d="M66 90 H126" marker-end="url(#aw-gs2)"/>
  <g class="sblk"><rect class="body" x="30" y="158" width="36" height="24" rx="12"/><text class="pnum" x="48" y="174">2</text></g>
  <text class="pname" x="48" y="202">고도 h</text>
  <text class="siglabel" x="48" y="218">−z_n</text>
  <path class="wire" d="M66 170 H126" marker-end="url(#aw-gs2)"/>
  <g class="sblk"><rect class="body" x="30" y="238" width="36" height="24" rx="12"/><text class="pnum" x="48" y="254">3</text></g>
  <text class="pname" x="48" y="282">연료 fuel</text>
  <text class="siglabel" x="52" y="298">항법 게이지</text>
  <path class="wire" d="M66 250 H126" marker-end="url(#aw-gs2)"/>
  <g class="sblk"><rect class="body" x="130" y="64" width="180" height="212" rx="3"/>
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
  <g class="sblk"><rect class="body" x="670" y="112" width="170" height="116" rx="3"/>
    <text class="ttl" x="755" y="136" style="font-size:13px">그룹.게인 분배</text>
    <text class="ttl2" x="755" y="156">"pitch.kp" → {pitch:{kp}}</text>
    <text class="ttl2" x="755" y="174">그룹: 피치·롤·요 ·</text>
    <text class="ttl2" x="755" y="190">속도·고도·헤딩</text>
    <text class="ttl2" x="755" y="208">키: kp·ki·k_rate (조립 검증)</text></g>
  <path class="wire" d="M840 170 H854" marker-end="url(#aw-gs2)"/>
  <g class="sblk"><rect class="body" x="858" y="158" width="36" height="24" rx="12"/><text class="pnum" x="876" y="174">1</text></g>
  <text class="pname" x="838" y="210">→ AP · SCAS</text>
  <text class="pname" x="838" y="228">스텝별 게인 덮어쓰기</text>
  <rect x="400" y="320" width="240" height="64" rx="8" fill="none" stroke="#8a5cf6" stroke-width="1.4" stroke-dasharray="6 4"/>
  <text class="annot" x="520" y="344" text-anchor="middle">설계 점검 — max_adjacent_jump</text>
  <text class="annot" x="520" y="364" text-anchor="middle">축별 인접 격자 최대 |Δ게인| (불연속 검출)</text>
  <path class="wire soft" d="M520 276 V316" marker-end="url(#as-gs2)"/>
  <text class="canvas-note" x="24" y="410">※ 스케줄 변수 mach·h·fuel은 law가 NavOutput에서 산출 (mach = V/음속(h_ISA)) — 참값 차단 · law 조립 시 그룹·키 오타는 시끄럽게 거부</text>
  <text class="canvas-note" x="24" y="430">※ 정본 = 게인 탭 테이블 (이 페이지는 구조 열람) · 보간 구간 마진 재계산은 마진 맵 재사용 · 필터가 게인 점프 완충 [확정 01 §3.4]</text>
</svg>`,
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
  <g class="sblk"><rect class="body" x="40" y="60" width="230" height="88" rx="3"/>
    <text class="ttl" x="155" y="84" style="font-size:13px">미션 편집 — 시뮬 탭</text>
    <text class="ttl2" x="155" y="104">모드 테이블 {명령 · 이탈 · next}</text>
    <text class="ttl2" x="155" y="120">웨이포인트 (N,E) · 도달반경</text>
    <text class="ttl2" x="155" y="136">NED 평면 지도 편집 (클릭·드래그·줌)</text></g>
  <path class="wire" d="M270 104 H306" marker-end="url(#aw-mp)"/>
  <g class="sblk" data-code="guidance/modes.py:validate_condition"><rect class="body" x="310" y="60" width="250" height="88" rx="3"/>
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
  <g class="sblk"><rect class="body" x="848" y="92" width="36" height="24" rx="12"/><text class="pnum" x="866" y="108">1</text></g>
  <text class="pname" x="864" y="148">→ 유도</text>
  <text class="canvas-note" x="24" y="204">※ 속도·고도 '경로 프로파일' 생성 없음 — 명령은 모드 테이블이 직접 보유 (경로추종은 헤딩만 담당) · 엔진에 별도 플래너 모듈 없음 — 시뮬 요청이 조립</text>
  <text class="canvas-note" x="24" y="226">※ 상세 임무 로직은 별도 설계 범위 [확정 01 §3.3.1] · 미션 편집처는 시뮬레이션 탭 미션 그룹</text>
</svg>`,
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
<svg viewBox="0 0 950 220" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-vf" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <g class="sblk"><rect class="body" x="30" y="66" width="150" height="68" rx="3"/>
    <text class="ttl" x="105" y="94">임무프로파일</text><text class="ttl2" x="105" y="114">시나리오 입력</text></g>
  <path class="wire" d="M180 100 H226" marker-end="url(#aw-vf)"/>
  <g class="sblk" data-code="sim/simulator.py:Simulator.run"><rect class="body" x="230" y="66" width="180" height="68" rx="3"/>
    <text class="ttl" x="320" y="94">폐루프 6DOF 시뮬</text><text class="ttl2" x="320" y="114">멀티레이트 · RK4 (기본값)</text></g>
  <path class="wire" d="M410 100 H456" marker-end="url(#aw-vf)"/>
  <g class="sblk"><rect class="body" x="460" y="66" width="170" height="68" rx="3"/>
    <text class="ttl" x="545" y="94">엔벨로프 감시</text><text class="ttl2" x="545" y="114">실속 마진 · DB 이탈 플래그</text></g>
  <path class="wire" d="M630 100 H676" marker-end="url(#aw-vf)"/>
  <g class="sblk"><rect class="body" x="680" y="66" width="220" height="68" rx="3"/>
    <text class="ttl" x="790" y="94">리포트 · Simulink 대조</text><text class="ttl2" x="790" y="114">허용오차 비교 (폐쇄망)</text></g>
</svg>`,
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
