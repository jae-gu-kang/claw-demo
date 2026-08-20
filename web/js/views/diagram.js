/** 고정 구조 신호흐름 다이어그램 (02 §4 (a)) — 시뮬링크 스타일 SVG 최상위.

자유 블록 배선 에디터는 [확정] 스코프 제외 — 아키텍처가 고정(01 §3)이므로
편집은 파라미터(게인·옵션·모드 테이블)로만 하고, 구조는 이 다이어그램이 정본을
표시한다. 블록 id·편집 경로 계약은 lib/blocks.js가 정본 (하위 페이지와 공유),
SVG 기하는 여기 수작성 — data-block 속성이 lib 블록 id와 1:1.

설계 순서 점선 프레임(①~⑤)은 "안쪽 루프부터 닫는" 설계 흐름(01 §1)을 표시한다.
프레임 설명은 다이어그램과 겹치지 않도록 우상단 범례로 분리 — 범례 항목 클릭 시
해당 서브시스템 페이지로 이동 (색 = 프레임 색, 애플 팔레트).
*/

import { BLOCKS } from "../lib/blocks.js";

const B = Object.fromEntries(BLOCKS.map((b) => [b.id, b]));

/** 정적 마크업 → DOM 요소. 반드시 정적(수작성) 문자열만 — 사용자 데이터 삽입 금지. */
export function fromMarkup(markup) {
  const box = document.createElement("div");
  box.innerHTML = markup;
  return box.firstElementChild;
}

/** 설계 순서 배너 (①~⑤) — page id로 이동. 색은 SVG 링·우상단 범례와 공유 (애플 팔레트). */
export const DESIGN_ORDER = [
  { page: "plant", label: "① 트림 · 선형해석", color: "#af52de" },
  { page: "scas", label: "② SCAS (내측 루프)", color: "#007aff" },
  { page: "autopilot", label: "③ 오토파일럿", color: "#34c759" },
  { page: "guidance", label: "④ 유도", color: "#ff9500" },
  { page: "verify", label: "⑤ 비선형 시뮬 검증", color: "#8e8e93" },
];

/** 최상위 블록도 마크업 — export는 테스트의 배선 드리프트 가드용 (data-block/
data-page id ↔ SUBSYSTEMS 키·CHAIN 순서 대조, lib/blocks.test.js). */
export const TOP_SVG = `
<svg viewBox="0 0 1920 716" xmlns="http://www.w3.org/2000/svg" role="img"
     aria-label="제어법칙 블록도 최상위 (시뮬링크 스타일)">
  <defs>
    <marker id="arrw" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto">
      <path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/>
    </marker>
    <marker id="arrgs" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto">
      <path d="M0,0 L8,4 L0,8 z" fill="#8a5cf6"/>
    </marker>
  </defs>

  <!-- 설계 순서 중첩 프레임 (안쪽 루프부터 바깥으로) — 라벨은 우상단 범례로 분리
       (프레임 선·블록·텍스트 비겹침 원칙). ⑤ 상단은 게인 스케줄 블록 위(y30)까지 -->
  <rect class="ring" x="10" y="30" width="1638" height="612" rx="10" stroke="#8e8e93"/>
  <rect class="ring" x="218" y="96" width="1412" height="528" rx="10" stroke="#ff9500"/>
  <rect class="ring" x="455" y="122" width="1155" height="484" rx="10" stroke="#34c759"/>
  <rect class="ring" x="800" y="150" width="790" height="438" rx="10" stroke="#007aff"/>
  <rect class="ring" x="1376" y="186" width="178" height="130" rx="10" stroke="#af52de"/>

  <!-- 우상단 범례 — 프레임(설계 순서) 설명 전용 공간 (프레임 밖 x1670~, 겹침 없음) -->
  <g class="legend">
    <text class="leg-cap" x="1672" y="52">설계 순서 (프레임)</text>
    <g class="legend-item" data-page="plant" tabindex="0">
      <rect x="1672" y="70" width="14" height="14" rx="4" fill="#af52de"/>
      <text class="leglabel" x="1694" y="82">① 트림 · 선형해석</text>
    </g>
    <g class="legend-item" data-page="scas" tabindex="0">
      <rect x="1672" y="102" width="14" height="14" rx="4" fill="#007aff"/>
      <text class="leglabel" x="1694" y="114">② SCAS — 내측 루프</text>
    </g>
    <g class="legend-item" data-page="autopilot" tabindex="0">
      <rect x="1672" y="134" width="14" height="14" rx="4" fill="#34c759"/>
      <text class="leglabel" x="1694" y="146">③ 오토파일럿</text>
    </g>
    <g class="legend-item" data-page="guidance" tabindex="0">
      <rect x="1672" y="166" width="14" height="14" rx="4" fill="#ff9500"/>
      <text class="leglabel" x="1694" y="178">④ 유도 — 경로 · 모드</text>
    </g>
    <g class="legend-item" data-page="verify" tabindex="0">
      <rect x="1672" y="198" width="14" height="14" rx="4" fill="#8e8e93"/>
      <text class="leglabel" x="1694" y="210">⑤ 비선형 시뮬 검증</text>
    </g>
    <text class="leg-note" x="1672" y="238">항목 클릭 → 해당 설계 화면</text>
  </g>

  <!-- 게인 스케줄링 (공통 — AP·SCAS 게인 주입). 주입 배선의 가로 구간은 프레임
       상단선들 사이 좁은 띠(122~150)를 피해 빈 공간(y172)으로 — 프레임과는
       90° 수직 교차만 (평행 근접 금지) -->
  <g class="blk" data-block="schedule" tabindex="0">
    <rect class="body gs-body" x="620" y="36" width="220" height="52" rx="10"/>
    <text class="ttl gs-ink" x="730" y="58">${B.schedule.title}</text>
    <text class="ttl2 gs-ink2" x="730" y="76">${B.schedule.sub}</text>
  </g>
  <path class="wire gs" d="M690 88 V172 H555 V194" marker-end="url(#arrgs)"/>
  <path class="wire gs" d="M770 88 V172 H900 V194" marker-end="url(#arrgs)"/>

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
    <text class="ttl" x="1105" y="233">${B.mixer.title}</text>
    <text class="ttl2" x="1105" y="252">${B.mixer.sub}</text>
  </g>
  <text class="bname" x="1105" y="286">고정 믹싱 행렬 (내/외 1:1)</text>
  <path class="wire" d="M1180 218 H1236" marker-end="url(#arrw)"/>
  <text class="siglabel" x="1209" y="207">δ 명령</text>

  <g class="blk" data-block="actuator" tabindex="0">
    <rect class="body" x="1240" y="200" width="100" height="68" rx="3"/>
    <text class="ttl" x="1290" y="240">${B.actuator.title}</text>
  </g>
  <text class="bname" x="1290" y="286">${B.actuator.sub}</text>
  <path class="wire" d="M1340 218 H1386" marker-end="url(#arrw)"/>
  <text class="siglabel" x="1363" y="207">타면·추력</text>

  <g class="blk" data-block="plant" tabindex="0">
    <rect class="body" x="1390" y="200" width="150" height="68" rx="3"/>
    <text class="ttl" x="1465" y="233">${B.plant.title}</text>
    <text class="ttl2" x="1465" y="252">${B.plant.sub}</text>
  </g>
  <text class="bname" x="1465" y="286" style="font-size:14px">델타윙 · 쌍발 · 엘레본×4 · 러더</text>

  <!-- 피드백 (참값 → 항법 → NavOutput만 소비: 참값 차단 계약 03 §4).
       리턴 리서(세로선)는 프레임·블록 엣지와 평행 근접 금지 — 간격 채널 중앙 배치.
       소비 신호 라벨은 회전 텍스트 대신 버스(y512) 위 가로 텍스트 — 각 분기점 옆 -->
  <path class="wire" d="M1540 218 H1570 V512 H1334" marker-end="url(#arrw)"/>
  <g class="blk" data-block="nav" tabindex="0">
    <rect class="body" x="1150" y="480" width="180" height="64" rx="3"/>
    <text class="ttl" x="1240" y="506">${B.nav.title}</text>
    <text class="ttl2" x="1240" y="526">${B.nav.sub}</text>
  </g>
  <text class="bname" x="1240" y="562">참값 + 잡음 + 바이어스 + 지연</text>

  <path class="wire" d="M1150 512 H236 V252 H246" marker-end="url(#arrw)"/>
  <circle class="branch" cx="818" cy="512" r="3.4"/>
  <path class="wire" d="M818 512 V252 H826" marker-end="url(#arrw)"/>
  <circle class="branch" cx="466" cy="512" r="3.4"/>
  <path class="wire" d="M466 512 V252 H476" marker-end="url(#arrw)"/>
  <!-- 버스 태그 — 전부 버스 위 한 줄(y498)·시작 정렬·분기점 우측 (배치 규칙 통일) -->
  <text class="bustag" x="250" y="498">위치 · 속도 → 유도</text>
  <text class="bustag" x="480" y="498">V h ψ → AP</text>
  <text class="bustag" x="832" y="498">θ φ q p r → SCAS</text>
  <text class="bustag" x="1024" y="498">NavOutput</text>

  <text class="canvas-note" x="24" y="660">※ 항법 출력(NavOutput: 위치·속도·자세·각속도) — 법칙·유도·스케줄은 이것만 소비, plant 참값 직접 참조 금지 [확정 03 §4 참값 차단 계약]</text>
  <text class="canvas-note" x="24" y="682">※ 스로틀 명령(δt)은 오토파일럿 속도 루프에서 생성되어 차동추력 보상과 합쳐져 스로틀×2로 출력 · 블록 클릭 시 서브시스템으로 진입</text>
  <text class="canvas-note" x="24" y="704">제어 100 Hz (틱 사이 ZOH) · 플랜트 dt 10 ms RK4 · 항법 자체 갱신주기/지연 — 멀티레이트 [확정 02 §6] · 자유 배선 없음 [확정 02 §4]</text>
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
