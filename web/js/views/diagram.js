/** 고정 구조 신호흐름 다이어그램 (02 §4 (a)) — 시뮬링크 스타일 SVG 최상위.

자유 블록 배선 에디터는 [확정] 스코프 제외 — 아키텍처가 고정(01 §3)이므로
편집은 파라미터(게인·옵션·모드 테이블)로만 하고, 구조는 이 다이어그램이 정본을
표시한다. 블록 id·편집 경로 계약은 lib/blocks.js가 정본 (하위 페이지와 공유),
SVG 기하는 여기 수작성 — data-block 속성이 lib 블록 id와 1:1.

설계 순서 점선 프레임(①~⑤)은 "안쪽 루프부터 닫는" 설계 흐름(01 §1)을 표시하며
프레임 라벨 클릭 시 해당 서브시스템 페이지로 이동한다.
*/

import { BLOCKS } from "../lib/blocks.js";

const B = Object.fromEntries(BLOCKS.map((b) => [b.id, b]));

/** 정적 마크업 → DOM 요소. 반드시 정적(수작성) 문자열만 — 사용자 데이터 삽입 금지. */
export function fromMarkup(markup) {
  const box = document.createElement("div");
  box.innerHTML = markup;
  return box.firstElementChild;
}

/** 설계 순서 배너 (①~⑤) — page id로 이동. */
export const DESIGN_ORDER = [
  { page: "plant", label: "① 트림 · 선형해석", color: "#7c3aed" },
  { page: "scas", label: "② SCAS (내측 루프)", color: "#1a6fb5" },
  { page: "autopilot", label: "③ 오토파일럿", color: "#1a7f4b" },
  { page: "guidance", label: "④ 유도", color: "#b45309" },
  { page: "verify", label: "⑤ 비선형 시뮬 검증", color: "#64748b" },
];

/** 최상위 블록도 마크업 — export는 테스트의 배선 드리프트 가드용 (data-block/
data-page id ↔ SUBSYSTEMS 키·CHAIN 순서 대조, lib/blocks.test.js). */
export const TOP_SVG = `
<svg viewBox="0 0 1660 692" xmlns="http://www.w3.org/2000/svg" role="img"
     aria-label="제어법칙 블록도 최상위 (시뮬링크 스타일)">
  <defs>
    <marker id="arrw" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto">
      <path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/>
    </marker>
    <marker id="arrgs" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto">
      <path d="M0,0 L8,4 L0,8 z" fill="#8a5cf6"/>
    </marker>
  </defs>

  <!-- 설계 순서 중첩 프레임 (안쪽 루프부터 바깥으로) -->
  <rect class="ring" x="10" y="70" width="1638" height="572" rx="10" stroke="#64748b"/>
  <text class="ringlabel" data-page="verify" x="24" y="92" fill="#64748b" tabindex="0">⑤ 비선형 시뮬레이션 검증 — 전 계통 폐루프 (엔벨로프 감시 · Simulink 대조)</text>

  <rect class="ring" x="218" y="96" width="1412" height="528" rx="10" stroke="#b45309"/>
  <text class="ringlabel" data-page="guidance" x="232" y="118" fill="#b45309" tabindex="0">④ 유도 설계 — 경로 추종 · 모드 실행</text>

  <rect class="ring" x="455" y="122" width="1155" height="484" rx="10" stroke="#1a7f4b"/>
  <text class="ringlabel" data-page="autopilot" x="469" y="144" fill="#1a7f4b" tabindex="0">③ 오토파일럿 설계 — 속도 · 고도 · 헤딩</text>

  <rect class="ring" x="800" y="150" width="790" height="438" rx="10" stroke="#1a6fb5"/>
  <text class="ringlabel" data-page="scas" x="814" y="172" fill="#1a6fb5" tabindex="0">② SCAS 설계 — 내측 루프 (자세 안정화)</text>

  <rect class="ring" x="1376" y="186" width="178" height="130" rx="10" stroke="#7c3aed"/>
  <text class="ringlabel" data-page="plant" x="1384" y="308" fill="#7c3aed" tabindex="0">① 트림 · 선형해석</text>

  <!-- 게인 스케줄링 (공통 — AP·SCAS 게인 주입) -->
  <g class="blk" data-block="schedule" tabindex="0">
    <rect class="body" x="620" y="40" width="220" height="54" rx="3" style="stroke-dasharray:6 4;stroke:#8a5cf6"/>
    <text class="ttl" x="730" y="62" style="font-size:13.5px;fill:#6d28d9">${B.schedule.title}</text>
    <text class="ttl2" x="730" y="80" style="fill:#7c5cd6">${B.schedule.sub}</text>
  </g>
  <path class="wire gs" d="M690 94 V132 H555 V196" marker-end="url(#arrgs)"/>
  <path class="wire gs" d="M770 94 V132 H900 V196" marker-end="url(#arrgs)"/>

  <!-- 주 신호 흐름 (좌 → 우) -->
  <g class="blk" data-block="planner" tabindex="0">
    <rect class="body" x="40" y="200" width="140" height="68" rx="3"/>
    <text class="ttl" x="110" y="240">${B.planner.title}</text>
  </g>
  <text class="bname" x="110" y="286">${B.planner.sub}</text>
  <path class="wire" d="M180 218 H246" marker-end="url(#arrw)"/>
  <text class="siglabel" x="215" y="207">임무프로파일</text>

  <g class="blk" data-block="guidance" tabindex="0">
    <rect class="body" x="250" y="200" width="150" height="68" rx="3"/>
    <text class="ttl" x="325" y="240">유도</text>
  </g>
  <text class="bname" x="325" y="286">${B.guidance.sub}</text>
  <path class="wire" d="M400 218 H476" marker-end="url(#arrw)"/>
  <text class="siglabel" x="440" y="207">V·h·ψ_cmd</text>

  <g class="blk" data-block="autopilot" tabindex="0">
    <rect class="body" x="480" y="200" width="150" height="68" rx="3"/>
    <text class="ttl" x="555" y="240">${B.autopilot.title}</text>
  </g>
  <text class="bname" x="555" y="286">${B.autopilot.sub}</text>
  <path class="wire" d="M630 218 H686" marker-end="url(#arrw)"/>
  <text class="siglabel" x="659" y="207">θ·φ_cmd</text>

  <g class="blk" data-block="limiter" tabindex="0">
    <rect class="body" x="690" y="200" width="84" height="68" rx="3"/>
    <line x1="700" y1="234" x2="764" y2="234" stroke="#b8c4d0" stroke-width="1"/>
    <line x1="732" y1="206" x2="732" y2="262" stroke="#b8c4d0" stroke-width="1"/>
    <path d="M700 252 H716 L748 216 H764" stroke="#111" stroke-width="2" fill="none"/>
  </g>
  <text class="bname" x="732" y="286">${B.limiter.title}</text>
  <path class="wire" d="M774 218 H826" marker-end="url(#arrw)"/>

  <g class="blk" data-block="scas" tabindex="0">
    <rect class="body" x="830" y="200" width="140" height="68" rx="3"/>
    <text class="ttl" x="900" y="240">${B.scas.title}</text>
  </g>
  <text class="bname" x="900" y="286">${B.scas.sub}</text>
  <path class="wire" d="M970 218 H1026" marker-end="url(#arrw)"/>
  <text class="siglabel" x="1000" y="207">피치·롤·요</text>

  <g class="blk" data-block="mixer" tabindex="0">
    <rect class="body" x="1030" y="200" width="150" height="68" rx="3"/>
    <text class="ttl" x="1105" y="233" style="font-size:14px">${B.mixer.title}</text>
    <text class="ttl2" x="1105" y="252">${B.mixer.sub}</text>
  </g>
  <text class="bname" x="1105" y="286">엘레본 4면 믹싱</text>
  <path class="wire" d="M1180 218 H1236" marker-end="url(#arrw)"/>
  <text class="siglabel" x="1209" y="207">δ 명령</text>

  <g class="blk" data-block="actuator" tabindex="0">
    <rect class="body" x="1240" y="200" width="100" height="68" rx="3"/>
    <text class="ttl" x="1290" y="240" style="font-size:14px">${B.actuator.title}</text>
  </g>
  <text class="bname" x="1290" y="286">${B.actuator.sub}</text>
  <path class="wire" d="M1340 218 H1386" marker-end="url(#arrw)"/>
  <text class="siglabel" x="1363" y="207">타면·추력</text>

  <g class="blk" data-block="plant" tabindex="0">
    <rect class="body" x="1390" y="200" width="150" height="68" rx="3"/>
    <text class="ttl" x="1465" y="233" style="font-size:14px">${B.plant.title}</text>
    <text class="ttl2" x="1465" y="252">${B.plant.sub}</text>
  </g>
  <text class="bname" x="1465" y="286" style="font-size:10.5px">델타윙 · 쌍발 · 엘레본×4 · 러더</text>

  <!-- 피드백 (참값 → 항법 → NavOutput만 소비: 참값 차단 계약 03 §4) -->
  <path class="wire" d="M1540 218 H1570 V512 H1334" marker-end="url(#arrw)"/>
  <g class="blk" data-block="nav" tabindex="0">
    <rect class="body" x="1150" y="480" width="180" height="64" rx="3"/>
    <text class="ttl" x="1240" y="506" style="font-size:14px">${B.nav.title}</text>
    <text class="ttl2" x="1240" y="526">${B.nav.sub}</text>
  </g>
  <text class="bname" x="1240" y="562">참값 + 잡음 + 바이어스 + 지연</text>

  <path class="wire" d="M1150 512 H236 V252 H246" marker-end="url(#arrw)"/>
  <text class="siglabel" x="690" y="530">항법 출력 (위치 · 속도 · 자세 · 각속도) — 법칙·유도·스케줄은 이것만 소비</text>
  <circle class="branch" cx="818" cy="512" r="3.4"/>
  <path class="wire" d="M818 512 V252 H826" marker-end="url(#arrw)"/>
  <text class="siglabel" x="806" y="388" transform="rotate(-90 806 388)">θ φ q p r</text>
  <circle class="branch" cx="472" cy="512" r="3.4"/>
  <path class="wire" d="M472 512 V252 H476" marker-end="url(#arrw)"/>
  <text class="siglabel" x="460" y="388" transform="rotate(-90 460 388)">V h ψ</text>
  <text class="siglabel" x="224" y="388" transform="rotate(-90 224 388)">위치 · 속도</text>

  <text class="canvas-note" x="24" y="656">※ 스로틀 명령(δt)은 오토파일럿 속도 루프에서 생성되어 차동추력 보상과 합쳐져 스로틀×2로 출력 · 블록 클릭 시 서브시스템으로 진입</text>
  <text class="canvas-note" x="24" y="674">제어 100 Hz (틱 사이 ZOH) · 플랜트 dt 10 ms RK4 · 항법 자체 갱신주기/지연 — 멀티레이트 [확정 02 §6] · 자유 배선 없음 [확정 02 §4]</text>
</svg>`;

/** 최상위 블록도 SVG. onNavigate(pageId) — 블록·프레임 라벨 클릭 시 호출. */
export function topDiagramSvg(onNavigate) {
  const svg = fromMarkup(TOP_SVG);
  for (const node of svg.querySelectorAll("[data-block], [data-page]")) {
    const page = node.dataset.block ?? node.dataset.page;
    const nav = () => onNavigate(page);
    node.addEventListener("click", nav);
    node.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); nav(); }
    });
  }
  return svg;
}
