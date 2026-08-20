/** 서브시스템 하위 페이지 데이터 — 시뮬링크 "블록 더블클릭 → 내부 진입" 대응 (02 §4).

각 페이지: pagehead 메타(단계 태그·영문·상태 칩) + 내부 블록도 SVG + 설계 노트.
SVG·노트는 수작성 정적 마크업 (fromMarkup으로 DOM화 — 사용자 데이터 삽입 금지).
내부 구조는 엔진 구현(M6~M8)과 1:1 — 코드에 없는 구조를 그리지 않는다.
페이지 id는 lib/blocks.js 블록 id + "verify"(설계 ⑤ — 블록 아닌 설계 단계 페이지).

SVG 안의 <tspan data-p="이름">은 파라미터 연동 표시값 — views/blocks.js가 렌더 시
스키마 기본값(+적용된 편집값)으로 채우고, 편집 폼 입력과 실시간 동기화한다.
초기 텍스트는 참고용 폴백일 뿐 정본이 아님 (정본 = 엔진 레지스트리 스키마).
data-p 이름은 해당 블록 스키마의 파라미터명만 허용 (lib/blocks.test.js 가드).
*/

// 상태 칩 종류 → 라벨 (fcs-context 문서 태그와 동일 의미)
export const CHIP_LABEL = { ok: "확정", dft: "기본값", tbd: "TBD", note: "설계 유의" };

export const SUBSYSTEMS = {

  // ── SCAS — 내측 루프 (설계 ②) ─────────────────────────────────────────
  scas: {
    tag: "설계 ②", tagBg: "#1a6fb5",
    title: "SCAS — 내측 루프 (자세 안정화)", eng: "축 공통 구조: PI(자세오차) + k_rate·각속도 — LQR 제외",
    chips: ["ok", "dft"],
    svg: `
<svg viewBox="0 0 900 470" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-scas" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <!-- 피치축 -->
  <g class="sblk"><rect class="body" x="30" y="68" width="36" height="24" rx="12"/><text class="pnum" x="48" y="84">1</text></g>
  <text class="pname" x="48" y="108">θ_cmd</text>
  <path class="wire" d="M66 80 H152" marker-end="url(#aw-scas)"/>
  <circle class="body" cx="170" cy="80" r="14" fill="#fff" stroke="#4a4a4a" stroke-width="1.6"/>
  <text class="sumsign" x="161" y="84">+</text><text class="sumsign" x="170" y="93">−</text>
  <path class="wire" d="M184 80 H216" marker-end="url(#aw-scas)"/>
  <g class="sblk"><rect class="body" x="220" y="53" width="120" height="54" rx="3"/><text class="ttl" x="280" y="81">PI</text><text class="ttl2" x="280" y="99">kp · ki (클램프 AW)</text></g>
  <path class="wire" d="M340 80 H416" marker-end="url(#aw-scas)"/>
  <circle class="body" cx="434" cy="80" r="14" fill="#fff" stroke="#4a4a4a" stroke-width="1.6"/>
  <text class="sumsign" x="425" y="84">+</text><text class="sumsign" x="434" y="93">+</text>
  <path class="wire" d="M448 80 H494" marker-end="url(#aw-scas)"/>
  <g class="sblk"><rect class="body" x="498" y="50" width="110" height="60" rx="3"/>
    <path d="M510 96 H528 L578 64 H596" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="553" y="128">출력 클립 (out_lo~hi)</text>
  <path class="wire" d="M608 80 H674" marker-end="url(#aw-scas)"/>
  <g class="sblk"><rect class="body" x="678" y="68" width="36" height="24" rx="12"/><text class="pnum" x="696" y="84">1</text></g>
  <text class="pname" x="696" y="108">피치 명령</text>
  <g class="sblk"><rect class="body" x="152" y="140" width="36" height="24" rx="12"/><text class="pnum" x="170" y="156">4</text></g>
  <text class="pname" x="204" y="156">θ</text>
  <path class="wire" d="M170 140 V98" marker-end="url(#aw-scas)"/>
  <g class="sblk"><rect class="body" x="416" y="140" width="36" height="24" rx="12"/><text class="pnum" x="434" y="156">5</text></g>
  <text class="pname" x="474" y="156">q × k_rate</text>
  <path class="wire" d="M434 140 V98" marker-end="url(#aw-scas)"/>
  <!-- 롤축 -->
  <g class="sblk"><rect class="body" x="30" y="208" width="36" height="24" rx="12"/><text class="pnum" x="48" y="224">2</text></g>
  <text class="pname" x="48" y="248">φ_cmd</text>
  <path class="wire" d="M66 220 H152" marker-end="url(#aw-scas)"/>
  <circle class="body" cx="170" cy="220" r="14" fill="#fff" stroke="#4a4a4a" stroke-width="1.6"/>
  <text class="sumsign" x="161" y="224">+</text><text class="sumsign" x="170" y="233">−</text>
  <path class="wire" d="M184 220 H216" marker-end="url(#aw-scas)"/>
  <g class="sblk"><rect class="body" x="220" y="193" width="120" height="54" rx="3"/><text class="ttl" x="280" y="221">PI</text><text class="ttl2" x="280" y="239">kp · ki</text></g>
  <path class="wire" d="M340 220 H416" marker-end="url(#aw-scas)"/>
  <circle class="body" cx="434" cy="220" r="14" fill="#fff" stroke="#4a4a4a" stroke-width="1.6"/>
  <text class="sumsign" x="425" y="224">+</text><text class="sumsign" x="434" y="233">+</text>
  <path class="wire" d="M448 220 H494" marker-end="url(#aw-scas)"/>
  <g class="sblk"><rect class="body" x="498" y="190" width="110" height="60" rx="3"/>
    <path d="M510 236 H528 L578 204 H596" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="553" y="268">출력 클립</text>
  <path class="wire" d="M608 220 H674" marker-end="url(#aw-scas)"/>
  <g class="sblk"><rect class="body" x="678" y="208" width="36" height="24" rx="12"/><text class="pnum" x="696" y="224">2</text></g>
  <text class="pname" x="696" y="248">롤 명령</text>
  <g class="sblk"><rect class="body" x="152" y="280" width="36" height="24" rx="12"/><text class="pnum" x="170" y="296">6</text></g>
  <text class="pname" x="204" y="296">φ</text>
  <path class="wire" d="M170 280 V238" marker-end="url(#aw-scas)"/>
  <g class="sblk"><rect class="body" x="416" y="280" width="36" height="24" rx="12"/><text class="pnum" x="434" y="296">7</text></g>
  <text class="pname" x="474" y="296">p × k_rate</text>
  <path class="wire" d="M434 280 V238" marker-end="url(#aw-scas)"/>
  <!-- 요축 (β 유지 + 워시아웃 요레이트) -->
  <g class="sblk"><rect class="body" x="30" y="348" width="36" height="24" rx="12"/><text class="pnum" x="48" y="364">3</text></g>
  <text class="pname" x="48" y="388">β_cmd = 0</text>
  <path class="wire" d="M66 360 H152" marker-end="url(#aw-scas)"/>
  <circle class="body" cx="170" cy="360" r="14" fill="#fff" stroke="#4a4a4a" stroke-width="1.6"/>
  <text class="sumsign" x="161" y="364">+</text><text class="sumsign" x="170" y="373">−</text>
  <path class="wire" d="M184 360 H216" marker-end="url(#aw-scas)"/>
  <g class="sblk"><rect class="body" x="220" y="333" width="120" height="54" rx="3"/><text class="ttl" x="280" y="361">PI</text><text class="ttl2" x="280" y="379">kβ</text></g>
  <path class="wire" d="M340 360 H416" marker-end="url(#aw-scas)"/>
  <circle class="body" cx="434" cy="360" r="14" fill="#fff" stroke="#4a4a4a" stroke-width="1.6"/>
  <text class="sumsign" x="425" y="364">+</text><text class="sumsign" x="434" y="373">+</text>
  <path class="wire" d="M448 360 H494" marker-end="url(#aw-scas)"/>
  <g class="sblk"><rect class="body" x="498" y="330" width="110" height="60" rx="3"/>
    <path d="M510 376 H528 L578 344 H596" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="553" y="408">출력 클립</text>
  <path class="wire" d="M608 360 H674" marker-end="url(#aw-scas)"/>
  <g class="sblk"><rect class="body" x="678" y="348" width="36" height="24" rx="12"/><text class="pnum" x="696" y="364">3</text></g>
  <text class="pname" x="696" y="388">요 명령</text>
  <g class="sblk"><rect class="body" x="80" y="416" width="36" height="24" rx="12"/><text class="pnum" x="98" y="432">8</text></g>
  <text class="pname" x="130" y="432">β</text>
  <path class="wire" d="M116 428 H170 V378" marker-end="url(#aw-scas)"/>
  <g class="sblk"><rect class="body" x="200" y="416" width="36" height="24" rx="12"/><text class="pnum" x="218" y="432">9</text></g>
  <text class="pname" x="248" y="432">r</text>
  <path class="wire" d="M236 428 H266" marker-end="url(#aw-scas)"/>
  <g class="sblk"><rect class="body" x="270" y="404" width="130" height="48" rx="3"/>
    <text class="ttl2" x="335" y="424" style="font-weight:700">워시아웃 × kr</text><text class="ttl2" x="335" y="441">s / (s + 1/τ) · τ = 2 s</text></g>
  <path class="wire" d="M400 428 H434 V378" marker-end="url(#aw-scas)"/>
  <!-- 게인 스케줄 주석 -->
  <rect x="660" y="410" width="220" height="50" rx="8" fill="none" stroke="#8a5cf6" stroke-width="1.4" stroke-dasharray="6 4"/>
  <text class="annot" x="770" y="431" text-anchor="middle">게인 스케줄링 적용</text>
  <text class="annot" x="770" y="449" text-anchor="middle">kp·ki·k_rate = f(비행조건)</text>
</svg>`,
    notes: `
<h4>설계 노트</h4>
<ul>
  <li>축 공통 구조: <b>PI(자세오차) + k_rate·각속도</b>, 출력 클립 — 캐스케이드(자세→레이트 2단) 아닌 평탄형 <span class="chip ok">확정 M7</span></li>
  <li>요축: β 유지(kβ) + <b>워시아웃</b> 요레이트(kr) — 지속 선회 시 정상분 제거로 선회 유지 <span class="chip ok">확정</span> · τ = 2 s <span class="chip dft">기본값</span></li>
  <li>안티와인드업: 적분항 클램프 <span class="chip dft">기본값 M7</span> — 실데이터 튜닝 시 재검토</li>
  <li>이산화: 제어주기 <b>100 Hz</b> 시작 → 50 Hz 하향 영향성 비교 예정 · 계수는 주기로부터 자동 계산 <span class="chip ok">확정</span></li>
  <li>항법 갱신주기 ≤ 제어주기 가능 → <b>멀티레이트 입력</b> 전제 설계 <span class="chip note">설계 유의</span></li>
  <li>데모 설계점(M0.6·h1000·fuel200): 피치 kp −2.0 / ki −0.5 / k_rate 0.4 · 롤 1.0 / 0.1 / −0.2 · 요 kβ 0.5 / kr 0.8</li>
</ul>`,
  },

  // ── 오토파일럿 — 외측 루프 (설계 ③) ──────────────────────────────────
  autopilot: {
    tag: "설계 ③", tagBg: "#1a7f4b",
    title: "오토파일럿 — 외측 루프", eng: "Autopilot / Outer Loop — 채널별 PI + 명령필터",
    chips: ["ok", "dft"],
    svg: `
<svg viewBox="0 0 900 480" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="aw-ap" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker>
    <marker id="af-ap" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#b45309"/></marker>
  </defs>
  <!-- 고도 채널 -->
  <g class="sblk"><rect class="body" x="30" y="68" width="36" height="24" rx="12"/><text class="pnum" x="48" y="84">1</text></g>
  <text class="pname" x="48" y="108">h_cmd</text>
  <path class="wire" d="M66 80 H96" marker-end="url(#aw-ap)"/>
  <g class="sblk"><rect class="body" x="100" y="56" width="96" height="48" rx="3"/><text class="ttl2" x="148" y="76" style="font-weight:700">명령필터</text><text class="ttl2" x="148" y="93">τ = <tspan data-p="tau_alt">5</tspan> s</text></g>
  <path class="wire" d="M196 80 H238" marker-end="url(#aw-ap)"/>
  <circle class="body" cx="256" cy="80" r="14" fill="#fff" stroke="#4a4a4a" stroke-width="1.6"/>
  <text class="sumsign" x="247" y="84">+</text><text class="sumsign" x="256" y="93">−</text>
  <path class="wire" d="M270 80 H302" marker-end="url(#aw-ap)"/>
  <g class="sblk"><rect class="body" x="306" y="53" width="130" height="54" rx="3"/><text class="ttl" x="371" y="74">고도 PI</text><text class="ttl2" x="371" y="90">kp <tspan data-p="kp_alt">0.004</tspan> · ki <tspan data-p="ki_alt">0.0004</tspan></text><text class="ttl2" x="371" y="103">k_hdot <tspan data-p="k_hdot">−0.008</tspan> 승강률</text></g>
  <path class="wire" d="M436 80 H478" marker-end="url(#aw-ap)"/>
  <g class="sblk"><rect class="body" x="482" y="50" width="100" height="60" rx="3"/>
    <path d="M492 96 H508 L556 64 H572" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="532" y="128">θ 한계 <tspan data-p="theta_lo">−0.3</tspan> ~ <tspan data-p="theta_hi">0.3</tspan> rad</text>
  <path class="wire" d="M582 80 H644" marker-end="url(#aw-ap)"/>
  <g class="sblk"><rect class="body" x="648" y="68" width="36" height="24" rx="12"/><text class="pnum" x="666" y="84">1</text></g>
  <text class="pname" x="678" y="108">θ_cmd → α 리미터</text>
  <g class="sblk"><rect class="body" x="238" y="140" width="36" height="24" rx="12"/><text class="pnum" x="256" y="156">4</text></g>
  <text class="pname" x="290" y="156">h</text>
  <path class="wire" d="M256 140 V98" marker-end="url(#aw-ap)"/>
  <!-- 속도 채널 -->
  <g class="sblk"><rect class="body" x="30" y="208" width="36" height="24" rx="12"/><text class="pnum" x="48" y="224">2</text></g>
  <text class="pname" x="48" y="248">V_cmd</text>
  <path class="wire" d="M66 220 H96" marker-end="url(#aw-ap)"/>
  <g class="sblk"><rect class="body" x="100" y="196" width="96" height="48" rx="3"/><text class="ttl2" x="148" y="216" style="font-weight:700">명령필터</text><text class="ttl2" x="148" y="233">τ = <tspan data-p="tau_spd">2</tspan> s</text></g>
  <path class="wire" d="M196 220 H238" marker-end="url(#aw-ap)"/>
  <circle class="body" cx="256" cy="220" r="14" fill="#fff" stroke="#4a4a4a" stroke-width="1.6"/>
  <text class="sumsign" x="247" y="224">+</text><text class="sumsign" x="256" y="233">−</text>
  <path class="wire" d="M270 220 H302" marker-end="url(#aw-ap)"/>
  <g class="sblk"><rect class="body" x="306" y="193" width="130" height="54" rx="3"/><text class="ttl" x="371" y="217">속도 PI</text><text class="ttl2" x="371" y="237">kp <tspan data-p="kp_spd">0.15</tspan> · ki <tspan data-p="ki_spd">0.03</tspan></text></g>
  <path class="wire" d="M436 220 H494" marker-end="url(#aw-ap)"/>
  <circle class="body" cx="512" cy="220" r="14" fill="#fff" stroke="#4a4a4a" stroke-width="1.6"/>
  <text class="sumsign" x="503" y="224">+</text><text class="sumsign" x="512" y="211">+</text>
  <path class="wire" d="M526 220 H584" marker-end="url(#aw-ap)"/>
  <g class="sblk"><rect class="body" x="588" y="208" width="36" height="24" rx="12"/><text class="pnum" x="606" y="224">2</text></g>
  <text class="pname" x="620" y="248">δt_cmd (스로틀)</text>
  <g class="sblk"><rect class="body" x="238" y="276" width="36" height="24" rx="12"/><text class="pnum" x="256" y="292">5</text></g>
  <text class="pname" x="290" y="292">V</text>
  <path class="wire" d="M256 276 V238" marker-end="url(#aw-ap)"/>
  <!-- 헤딩 채널 -->
  <g class="sblk"><rect class="body" x="30" y="348" width="36" height="24" rx="12"/><text class="pnum" x="48" y="364">3</text></g>
  <text class="pname" x="48" y="388">ψ_cmd</text>
  <path class="wire" d="M66 360 H96" marker-end="url(#aw-ap)"/>
  <g class="sblk"><rect class="body" x="100" y="336" width="96" height="48" rx="3"/><text class="ttl2" x="148" y="356" style="font-weight:700">명령필터</text><text class="ttl2" x="148" y="373">τ = <tspan data-p="tau_hdg">1</tspan> s</text></g>
  <path class="wire" d="M196 360 H238" marker-end="url(#aw-ap)"/>
  <circle class="body" cx="256" cy="360" r="14" fill="#fff" stroke="#4a4a4a" stroke-width="1.6"/>
  <text class="sumsign" x="247" y="364">+</text><text class="sumsign" x="256" y="373">−</text>
  <path class="wire" d="M270 360 H302" marker-end="url(#aw-ap)"/>
  <g class="sblk"><rect class="body" x="306" y="333" width="130" height="54" rx="3"/><text class="ttl" x="371" y="357">헤딩 PI</text><text class="ttl2" x="371" y="377">kp <tspan data-p="kp_hdg">4</tspan> · ki <tspan data-p="ki_hdg">0</tspan> · wrap</text></g>
  <path class="wire" d="M436 360 H478" marker-end="url(#aw-ap)"/>
  <g class="sblk"><rect class="body" x="482" y="330" width="100" height="60" rx="3"/>
    <path d="M492 376 H508 L556 344 H572" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="532" y="408">φ 한계 ±<tspan data-p="phi_max">0.7</tspan> rad</text>
  <path class="wire" d="M582 360 H644" marker-end="url(#aw-ap)"/>
  <g class="sblk"><rect class="body" x="648" y="348" width="36" height="24" rx="12"/><text class="pnum" x="666" y="364">3</text></g>
  <text class="pname" x="666" y="388">φ_cmd</text>
  <g class="sblk"><rect class="body" x="238" y="416" width="36" height="24" rx="12"/><text class="pnum" x="256" y="432">6</text></g>
  <text class="pname" x="290" y="432">ψ</text>
  <path class="wire" d="M256 416 V378" marker-end="url(#aw-ap)"/>
  <!-- 선회 피드포워드 -->
  <rect x="618" y="270" width="252" height="70" rx="8" fill="#fdf2d7" stroke="#b45309" stroke-width="1.4" stroke-dasharray="6 4"/>
  <text x="744" y="298" text-anchor="middle" style="font-size:12.5px;font-weight:800" fill="#b45309">선회 피드포워드 보상</text>
  <text x="744" y="317" text-anchor="middle" style="font-size:11px" fill="#b45309">|φ_cmd| 기반 — 피치 <tspan data-p="k_pitch_turn">0.05</tspan> · 스로틀 <tspan data-p="k_thr_turn">0</tspan></text>
  <path class="wire ff" d="M660 270 V220 H530" marker-end="url(#af-ap)"/>
  <path class="wire ff" d="M720 270 V115 H371 V111" marker-end="url(#af-ap)"/>
</svg>`,
    notes: `
<h4>설계 노트</h4>
<ul>
  <li>속도 / 고도 / 헤딩 <b>독립 PI 채널</b> — 고도→θ_cmd, 속도→δt_cmd, 헤딩→φ_cmd <span class="chip ok">확정</span></li>
  <li>명령 경로 <b>1차 명령필터</b> — 급격한 명령의 타면 포화·과도 하중 방지 <span class="chip dft">기본값</span> · 시정수 속도 2 · 고도 5 · 헤딩 1 s <span class="chip dft">기본값 M7</span></li>
  <li>선회 시 <b>피드포워드 보상</b>(피치·스로틀) — 델타윙 유도항력의 속도·고도 손실 방지 <span class="chip note">설계 유의</span> · 데모 튜닝: 피치 FF 0.05, 스로틀 FF 0(역효과) <span class="chip dft">기본값</span></li>
  <li>피치 명령은 θ 한계(theta_lo~hi) 클립 후 <b>α 리미터</b>를 거쳐 SCAS로 · 뱅크는 ±phi_max(π/2 미만 — 선회 FF 부호 보전)</li>
  <li>요축 별도 출력 없음 — 요 안정화는 SCAS(β·r), 차동추력 보상은 제어면 혼합에서</li>
  <li>게인은 게인 스케줄링(Mach·고도·연료) 적용 대상 · 이 페이지 폼에서 편집 → 시뮬 주입 가능</li>
</ul>`,
  },

  // ── 유도 (설계 ④) ────────────────────────────────────────────────────
  guidance: {
    tag: "설계 ④", tagBg: "#b45309",
    title: "유도 — 모드별 유도 + 경로 추종", eng: "Guidance (M8)",
    chips: ["ok", "dft", "tbd"],
    svg: `
<svg viewBox="0 0 900 330" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-guid" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <g class="sblk"><rect class="body" x="30" y="88" width="36" height="24" rx="12"/><text class="pnum" x="48" y="104">1</text></g>
  <text class="pname" x="48" y="128">임무프로파일</text>
  <path class="wire" d="M66 100 H136" marker-end="url(#aw-guid)"/>
  <g class="sblk"><rect class="body" x="140" y="66" width="200" height="68" rx="3"/>
    <text class="ttl" x="240" y="94">모드 테이블 + 시퀀서</text><text class="ttl2" x="240" y="114">{진입, 활성 명령, 이탈}</text></g>
  <path class="wire" d="M340 100 H406" marker-end="url(#aw-guid)"/>
  <g class="sblk"><rect class="body" x="410" y="66" width="190" height="68" rx="3"/>
    <text class="ttl" x="505" y="94">경로 추종 — LOS</text><text class="ttl2" x="505" y="114">웨이포인트 열 · 도달반경</text></g>
  <path class="wire" d="M600 100 H666" marker-end="url(#aw-guid)"/>
  <g class="sblk"><rect class="body" x="670" y="88" width="36" height="24" rx="12"/><text class="pnum" x="688" y="104">1</text></g>
  <text class="pname" x="688" y="128">V·h·ψ_cmd</text>
  <g class="sblk"><rect class="body" x="487" y="240" width="36" height="24" rx="12"/><text class="pnum" x="505" y="256">2</text></g>
  <text class="pname" x="585" y="256">항법 (위치 · 속도)</text>
  <path class="wire" d="M505 240 V138" marker-end="url(#aw-guid)"/>
  <text class="canvas-note" x="120" y="180">모드 시퀀스: 이륙 → 상승 → (순항·고도유지·디센트·임무수행·웨이포인트 항법) → 착륙</text>
  <text class="canvas-note" x="120" y="200">활성 명령 셋(속도/고도/헤딩 유지 방식)은 모드 테이블이 결정 · Stateflow 미사용 [확정]</text>
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
</ul>`,
  },

  // ── α 리미터 (보호) ──────────────────────────────────────────────────
  limiter: {
    tag: "보호", tagBg: "#b3352b",
    title: "α 리미터 — 엔벨로프 보호", eng: "피치축 명령 경로 · 동적 상한 하드 클램프",
    chips: ["ok", "dft", "tbd"],
    svg: `
<svg viewBox="0 0 900 330" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-lim" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <g class="sblk"><rect class="body" x="30" y="78" width="36" height="24" rx="12"/><text class="pnum" x="48" y="94">1</text></g>
  <text class="pname" x="48" y="118">θ_cmd</text>
  <path class="wire" d="M66 90 H436" marker-end="url(#aw-lim)"/>
  <g class="sblk"><rect class="body" x="440" y="60" width="110" height="60" rx="3"/>
    <line x1="452" y1="90" x2="538" y2="90" stroke="#b8c4d0" stroke-width="1"/>
    <line x1="495" y1="66" x2="495" y2="114" stroke="#b8c4d0" stroke-width="1"/>
    <path d="M452 106 H470 L520 74 H538" stroke="#111" stroke-width="2" fill="none"/></g>
  <text class="bname" x="495" y="140">하드 클램프 θ_cmd ≤ 상한</text>
  <path class="wire" d="M550 90 H616" marker-end="url(#aw-lim)"/>
  <g class="sblk"><rect class="body" x="620" y="78" width="36" height="24" rx="12"/><text class="pnum" x="638" y="94">1</text></g>
  <text class="pname" x="638" y="118">θ_cmd′ → SCAS</text>
  <!-- 동적 상한 경로 -->
  <g class="sblk"><rect class="body" x="30" y="208" width="36" height="24" rx="12"/><text class="pnum" x="48" y="224">2</text></g>
  <text class="pname" x="48" y="248">Mach</text>
  <path class="wire" d="M66 220 H106" marker-end="url(#aw-lim)"/>
  <g class="sblk"><rect class="body" x="110" y="192" width="170" height="56" rx="3"/>
    <path d="M122 236 L140 236 L156 214 L174 226 L190 208" stroke="#8a97a5" stroke-width="1.6" fill="none"/>
    <text class="ttl2" x="230" y="215" style="font-weight:700">실속 경계 테이블</text>
    <text class="ttl2" x="230" y="233">α_stall = f(·) — 공력 정본</text></g>
  <path class="wire" d="M280 220 H316" marker-end="url(#aw-lim)"/>
  <g class="sblk"><rect class="body" x="320" y="192" width="130" height="56" rx="3"/>
    <text class="ttl" x="385" y="215" style="font-size:13px">− 보호마진</text><text class="ttl2" x="385" y="233">0.05 rad (기본값)</text></g>
  <path class="wire" d="M450 220 H486" marker-end="url(#aw-lim)"/>
  <g class="sblk"><rect class="body" x="490" y="192" width="180" height="56" rx="3"/>
    <text class="ttl2" x="580" y="215" style="font-weight:700">상한 = θ + (α_max − α)</text>
    <text class="ttl2" x="580" y="233">θ = γ + α 근사</text></g>
  <path class="wire" d="M670 220 H690 V123" marker-end="url(#aw-lim)"/>
  <text class="siglabel" x="722" y="170">동적 상한</text>
  <g class="sblk"><rect class="body" x="562" y="288" width="36" height="24" rx="12"/><text class="pnum" x="580" y="304">3</text></g>
  <text class="pname" x="650" y="304">θ · α (항법 출력)</text>
  <path class="wire" d="M580 288 V252" marker-end="url(#aw-lim)"/>
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

  // ── 제어면 혼합 ──────────────────────────────────────────────────────
  mixer: {
    tag: "배분", tagBg: "#8a97a5",
    title: "제어면 혼합 + 차동추력 보상", eng: "Control Allocation / Mixing",
    chips: ["dft", "tbd"],
    svg: `
<svg viewBox="0 0 900 380" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-mix" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <g class="sblk"><rect class="body" x="40" y="58" width="36" height="24" rx="12"/><text class="pnum" x="58" y="74">1</text></g>
  <text class="pname" x="58" y="104">피치 명령</text>
  <path class="wire" d="M76 70 H336" marker-end="url(#aw-mix)"/>
  <g class="sblk"><rect class="body" x="40" y="128" width="36" height="24" rx="12"/><text class="pnum" x="58" y="144">2</text></g>
  <text class="pname" x="58" y="174">롤 명령</text>
  <path class="wire" d="M76 140 H336" marker-end="url(#aw-mix)"/>
  <g class="sblk"><rect class="body" x="40" y="198" width="36" height="24" rx="12"/><text class="pnum" x="58" y="214">3</text></g>
  <text class="pname" x="58" y="244">요 명령</text>
  <path class="wire" d="M76 210 H336" marker-end="url(#aw-mix)"/>
  <g class="sblk"><rect class="body" x="40" y="268" width="36" height="24" rx="12"/><text class="pnum" x="58" y="284">4</text></g>
  <text class="pname" x="58" y="314">δt_cmd</text>
  <path class="wire" d="M76 280 H336" marker-end="url(#aw-mix)"/>
  <g class="sblk"><rect class="body" x="340" y="46" width="220" height="260" rx="3"/>
    <text class="ttl" x="450" y="150">믹싱 행렬</text>
    <text class="ttl2" x="450" y="172">내/외측 쌍 1:1 고정 (기본값)</text>
    <text class="ttl2" x="450" y="192">피치 = 동시 · 롤 = 차동</text>
    <text class="ttl2" x="450" y="212">요 = 러더 + 차동추력(k_diff_thr)</text></g>
  <path class="wire" d="M560 76 H646" marker-end="url(#aw-mix)"/>
  <g class="sblk"><rect class="body" x="650" y="64" width="42" height="24" rx="12"/><text class="pnum" x="671" y="80">1–4</text></g>
  <text class="pname" x="768" y="80">엘레본 ×4 (내/외측 쌍)</text>
  <path class="wire" d="M560 176 H646" marker-end="url(#aw-mix)"/>
  <g class="sblk"><rect class="body" x="650" y="164" width="36" height="24" rx="12"/><text class="pnum" x="668" y="180">5</text></g>
  <text class="pname" x="730" y="180">러더 ×1</text>
  <path class="wire" d="M560 276 H646" marker-end="url(#aw-mix)"/>
  <g class="sblk"><rect class="body" x="650" y="264" width="42" height="24" rx="12"/><text class="pnum" x="671" y="280">6–7</text></g>
  <text class="pname" x="778" y="280">스로틀 ×2 (차동추력 보상)</text>
  <text class="canvas-note" x="340" y="340">δe(내측/외측) = 피치(동시 성분) ± 롤(차동 성분) — 4면 여유자유도, 최적화 기반 할당은 추후 확장</text>
</svg>`,
    notes: `
<h4>설계 노트</h4>
<ul>
  <li>면 4개 → 여유자유도 존재. 내측/외측 쌍 <b>고정 믹싱 행렬</b>(1:1)로 시작 <span class="chip dft">기본값 01 §2.2</span> · 최적화 기반 할당은 추후 확장</li>
  <li>요축: 러더 명령 + <b>차동 추력</b> 보조 (k_diff_thr) · 타면각 한계 elevon/rudder lo~hi 클립</li>
  <li>4면 배치(내/외측 쌍 여부) · 믹싱 비율 · 타면각/rate 한계 <span class="chip tbd">TBD</span> — 기체 데이터 확인 시</li>
</ul>`,
  },

  // ── 작동기 ───────────────────────────────────────────────────────────
  actuator: {
    tag: "HW 모델", tagBg: "#8a97a5",
    title: "작동기", eng: "Actuator — 2차계 모델 (파라미터화)",
    chips: ["dft", "tbd"],
    svg: `
<svg viewBox="0 0 900 220" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-act" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <g class="sblk"><rect class="body" x="30" y="88" width="36" height="24" rx="12"/><text class="pnum" x="48" y="104">1</text></g>
  <text class="pname" x="48" y="128">δ_cmd</text>
  <path class="wire" d="M66 100 H136" marker-end="url(#aw-act)"/>
  <g class="sblk"><rect class="body" x="140" y="64" width="190" height="72" rx="3"/>
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
<svg viewBox="0 0 1000 430" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="aw-pl" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker>
    <marker id="as-pl" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#8a97a5"/></marker>
  </defs>
  <g class="sblk"><rect class="body" x="30" y="78" width="36" height="24" rx="12"/><text class="pnum" x="48" y="94">1</text></g>
  <text class="pname" x="48" y="118">타면 변위</text>
  <path class="wire" d="M66 90 H176" marker-end="url(#aw-pl)"/>
  <g class="sblk"><rect class="body" x="180" y="60" width="200" height="70" rx="3"/>
    <text class="ttl" x="280" y="88">공력 DB (CFD)</text>
    <text class="ttl2" x="280" y="110">축: Mach, α, β, δ, h</text></g>
  <g class="sblk"><rect class="body" x="30" y="158" width="36" height="24" rx="12"/><text class="pnum" x="48" y="174">2</text></g>
  <text class="pname" x="48" y="198">스로틀 ×2</text>
  <path class="wire" d="M66 170 H176" marker-end="url(#aw-pl)"/>
  <g class="sblk"><rect class="body" x="180" y="145" width="150" height="52" rx="3"/>
    <text class="ttl" x="255" y="168" style="font-size:13px">추진 모델</text>
    <text class="ttl2" x="255" y="186">스로틀-추력 맵</text></g>
  <g class="sblk"><rect class="body" x="180" y="228" width="180" height="56" rx="3"/>
    <text class="ttl" x="270" y="251" style="font-size:13px">대기 · 중력 · 지구</text>
    <text class="ttl2" x="270" y="271">ISA · WGS-84</text></g>
  <path class="wire" d="M380 95 H430 V130 H462" marker-end="url(#aw-pl)"/>
  <path class="wire" d="M330 171 H462" marker-end="url(#aw-pl)"/>
  <path class="wire" d="M360 256 H430 V186 H462" marker-end="url(#aw-pl)"/>
  <g class="sblk"><rect class="body" x="466" y="105" width="110" height="100" rx="3"/>
    <text class="ttl" x="521" y="150">Σ 힘 ·</text><text class="ttl" x="521" y="172">모멘트</text></g>
  <path class="wire" d="M576 155 H636" marker-end="url(#aw-pl)"/>
  <g class="sblk"><rect class="body" x="640" y="112" width="180" height="86" rx="3"/>
    <text class="ttl" x="730" y="148">6DOF 운동방정식</text>
    <text class="ttl2" x="730" y="170">쿼터니언 · RK4 dt 10 ms</text></g>
  <path class="wire" d="M820 155 H886" marker-end="url(#aw-pl)"/>
  <g class="sblk"><rect class="body" x="890" y="143" width="36" height="24" rx="12"/><text class="pnum" x="908" y="159">1</text></g>
  <text class="pname" x="908" y="183">상태 (참값)</text>
  <circle class="branch" cx="850" cy="155" r="3.2"/>
  <path class="wire soft" d="M850 155 V36 H280 V56" marker-end="url(#as-pl)"/>
  <text class="siglabel" x="560" y="28" fill="#8a97a5">상태 피드백: Mach, α, β, q̄ …</text>
  <rect x="466" y="330" width="460" height="72" rx="8" fill="none" stroke="#7c3aed" stroke-width="1.4" stroke-dasharray="6 4"/>
  <text class="annot" x="696" y="358" text-anchor="middle" fill="#7c3aed">① 이 플랜트를 기반으로 설계 1단계 수행:</text>
  <text class="annot" x="696" y="380" text-anchor="middle" fill="#7c3aed">트림 (100+ 케이스 배치) → 구간 선형화 → 고유치·감쇠비 · 마진 맵</text>
</svg>`,
    notes: `
<h4>플랜트</h4>
<ul>
  <li>형상: <b>델타윙, 쌍발 엔진</b> · 조종면 엘레본×4 + 러더×1 · 요축 보조 차동추력 <span class="chip ok">확정</span></li>
  <li>공력: CFD 기반 DB — 축: <span class="mono">Mach, α, β, 타면각, 고도</span> (정미 + 동미계수) <span class="chip ok">확정</span> · 현재는 데모 프로파일 (CFD DB 결선 대기) · 보간/외삽 정책 <span class="chip tbd">TBD</span></li>
  <li>실속: <b>명시적 실속 경계 테이블</b> <span class="mono">α_stall = f(Mach, 형상조건)</span> — 공력팀 정본 <span class="chip ok">확정</span></li>
  <li>환경: WGS-84, ISA <span class="chip ok">확정</span> (바람/난류 Dryden은 추후 확장) · RK4 dt 10 ms <span class="chip ok">확정 02 §6</span></li>
</ul>
<h4>설계 1단계 — 트림 · 선형해석</h4>
<ul>
  <li>트림: 비행조건별 구속조건 하 비용함수 최소화 — 수평정상비행부터, 정상선회·상승은 추후 <span class="chip ok">확정</span></li>
  <li>케이스: 트림 컨디션 × 속도 × 고도 × 연료량 → <b>100+ 케이스 배치</b> · 자동 판정 플래그(잔차·포화·α 여유·연속성) <span class="chip dft">기본값 01 §4.1</span></li>
  <li>선형화: 트림점별 구간 선형화(수치섭동) · 종축 / 횡·방향축 분리 <span class="chip ok">확정</span> · 작동기·지연 포함이 기본(제외 마진은 낙관적) <span class="chip dft">기본값 01 §4.2</span></li>
  <li>평가: 고유치·감쇠비(단주기·장주기·더치롤·롤·스파이럴) · 이득·위상여유 <span class="chip dft">기본값</span> · <b>마진 맵</b>(Mach-고도-연료 격자) <span class="chip ok">확정</span></li>
</ul>`,
  },

  // ── 항법 (피드백) ────────────────────────────────────────────────────
  nav: {
    tag: "피드백", tagBg: "#0e7c86",
    title: "항법 — 등가 오차 모델", eng: "Navigation (M6 · EKF 미구현 — 인터페이스 개방)",
    chips: ["ok", "dft"],
    svg: `
<svg viewBox="0 0 1000 320" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-nav" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <g class="sblk"><rect class="body" x="30" y="148" width="36" height="24" rx="12"/><text class="pnum" x="48" y="164">1</text></g>
  <text class="pname" x="48" y="188">참값 상태 (6DOF)</text>
  <path class="wire" d="M66 160 H382" marker-end="url(#aw-nav)"/>
  <circle class="body" cx="400" cy="160" r="14" fill="#fff" stroke="#4a4a4a" stroke-width="1.6"/>
  <text class="sumsign" x="391" y="164">+</text><text class="sumsign" x="400" y="152">+</text><text class="sumsign" x="400" y="174">+</text>
  <g class="sblk"><rect class="body" x="200" y="33" width="140" height="54" rx="3"/>
    <text class="ttl" x="270" y="56" style="font-size:13px">백색잡음</text><text class="ttl2" x="270" y="75">σ pos <tspan data-p="pos_std">3</tspan> m · vel <tspan data-p="vel_std">0.3</tspan></text></g>
  <path class="wire" d="M340 60 H400 V142" marker-end="url(#aw-nav)"/>
  <g class="sblk"><rect class="body" x="180" y="233" width="180" height="54" rx="3"/>
    <text class="ttl" x="270" y="256" style="font-size:13px">바이어스</text><text class="ttl2" x="270" y="275">σ <tspan data-p="bias_std">1</tspan> m · τ <tspan data-p="bias_tau">60</tspan> s</text></g>
  <path class="wire" d="M360 260 H400 V178" marker-end="url(#aw-nav)"/>
  <path class="wire" d="M414 160 H466" marker-end="url(#aw-nav)"/>
  <g class="sblk"><rect class="body" x="470" y="133" width="140" height="54" rx="3"/>
    <text class="ttl" x="540" y="156" style="font-size:13px">지연</text><text class="ttl2" x="540" y="175"><tspan data-p="delay_s">0.03</tspan> s</text></g>
  <path class="wire" d="M610 160 H656" marker-end="url(#aw-nav)"/>
  <g class="sblk"><rect class="body" x="660" y="133" width="140" height="54" rx="3"/>
    <text class="ttl" x="730" y="156" style="font-size:13px">갱신주기</text><text class="ttl2" x="730" y="175"><tspan data-p="update_hz">100</tspan> Hz · ZOH</text></g>
  <path class="wire" d="M800 160 H866" marker-end="url(#aw-nav)"/>
  <g class="sblk"><rect class="body" x="870" y="148" width="36" height="24" rx="12"/><text class="pnum" x="888" y="164">1</text></g>
  <text class="pname" x="888" y="188">NavOutput</text>
</svg>`,
    notes: `
<h4>설계 노트</h4>
<ul>
  <li>EKF는 구현하지 않음 — 실제 항법 출력의 <b>통계적 특성 재현</b> <span class="chip ok">확정</span> · 추후 항법팀 EKF를 그대로 교체 장착 가능(레지스트리)</li>
  <li>법칙·유도·스케줄은 <b>NavOutput만 소비</b> — 참값 차단 계약 (03 §4)</li>
  <li>파라미터: 상태별 잡음 σ · 바이어스(초기+상관시간) · transport delay · 갱신주기 · 시드</li>
  <li>초기 수치는 GPS/INS 통합항법 일반 수준 <span class="chip dft">기본값</span> — 항법팀 자료 확보 시 대체</li>
  <li>갱신주기가 제어주기(100 Hz)보다 낮을 수 있음 → 제어법칙은 <b>멀티레이트</b> 전제 <span class="chip note">설계 유의</span></li>
</ul>`,
  },

  // ── 게인 스케줄링 (공통) ─────────────────────────────────────────────
  schedule: {
    tag: "공통", tagBg: "#8a5cf6",
    title: "게인 스케줄링", eng: "오토파일럿 · SCAS 게인에 적용",
    chips: ["ok", "dft", "tbd"],
    svg: `
<svg viewBox="0 0 900 300" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-gs2" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <g class="sblk"><rect class="body" x="40" y="58" width="36" height="24" rx="12"/><text class="pnum" x="58" y="74">1</text></g>
  <text class="pname" x="110" y="74">Mach</text>
  <path class="wire" d="M76 70 H246" marker-end="url(#aw-gs2)"/>
  <g class="sblk"><rect class="body" x="40" y="138" width="36" height="24" rx="12"/><text class="pnum" x="58" y="154">2</text></g>
  <text class="pname" x="110" y="154">고도</text>
  <path class="wire" d="M76 150 H246" marker-end="url(#aw-gs2)"/>
  <g class="sblk"><rect class="body" x="40" y="218" width="36" height="24" rx="12"/><text class="pnum" x="58" y="234">3</text></g>
  <text class="pname" x="110" y="234">연료량</text>
  <path class="wire" d="M76 230 H246" marker-end="url(#aw-gs2)"/>
  <g class="sblk"><rect class="body" x="250" y="46" width="230" height="208" rx="3"/>
    <path d="M275 120 L300 120 L320 90 L345 105 L365 78" stroke="#8a97a5" stroke-width="1.8" fill="none"/>
    <text class="ttl" x="365" y="160">게인 테이블</text>
    <text class="ttl2" x="365" y="182">트림점 기반 설계 · 보간</text>
    <text class="ttl2" x="365" y="202">데모: 동압 스케일 1D mach</text></g>
  <path class="wire" d="M480 150 H546" marker-end="url(#aw-gs2)"/>
  <g class="sblk"><rect class="body" x="550" y="138" width="36" height="24" rx="12"/><text class="pnum" x="568" y="154">1</text></g>
  <text class="pname" x="700" y="154">kp·ki·k_rate → AP · SCAS 전체 PI</text>
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
    tag: "입력", tagBg: "#8a97a5",
    title: "미션플래너", eng: "Mission Planner",
    chips: ["ok"],
    svg: `
<svg viewBox="0 0 900 220" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-mp" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <g class="sblk"><rect class="body" x="50" y="66" width="190" height="68" rx="3"/>
    <text class="ttl" x="145" y="94">웨이포인트 편집</text><text class="ttl2" x="145" y="114">시뮬 탭 · 지도는 백로그</text></g>
  <path class="wire" d="M240 100 H296" marker-end="url(#aw-mp)"/>
  <g class="sblk"><rect class="body" x="300" y="66" width="180" height="68" rx="3"/>
    <text class="ttl" x="390" y="94">경로 프로파일 생성</text><text class="ttl2" x="390" y="114">속도 · 고도 계획 포함</text></g>
  <path class="wire" d="M480 100 H536" marker-end="url(#aw-mp)"/>
  <g class="sblk"><rect class="body" x="540" y="66" width="180" height="68" rx="3"/>
    <text class="ttl" x="630" y="94">모드 시퀀스 부여</text><text class="ttl2" x="630" y="114">비행단계별 (이륙→착륙)</text></g>
  <path class="wire" d="M720 100 H786" marker-end="url(#aw-mp)"/>
  <g class="sblk"><rect class="body" x="790" y="88" width="36" height="24" rx="12"/><text class="pnum" x="808" y="104">1</text></g>
  <text class="pname" x="808" y="128">임무프로파일</text>
</svg>`,
    notes: `
<h4>설계 노트</h4>
<ul>
  <li>웨이포인트 열(列)로부터 <b>임무프로파일</b>(경로 + 비행모드 시퀀스) 생성</li>
  <li>편집처: 시뮬레이션 탭 미션 그룹(모드 테이블·웨이포인트·도달반경) — 지도 위 편집(오프라인 타일 폴백)은 백로그</li>
  <li>임무수행 단계의 상세 임무 로직은 별도 설계 범위 <span class="chip ok">확정 01 §3.3.1</span></li>
</ul>`,
  },

  // ── 비선형 시뮬 검증 (설계 ⑤ — 블록 아닌 설계 단계 페이지) ───────────
  verify: {
    tag: "설계 ⑤", tagBg: "#64748b",
    title: "비선형 시뮬레이션 검증", eng: "임무프로파일 → 모드별 유도 → 폐루프 6DOF",
    chips: ["ok", "dft"],
    svg: `
<svg viewBox="0 0 950 220" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="aw-vf" markerWidth="9" markerHeight="8" refX="7.5" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#3b3b3b"/></marker></defs>
  <g class="sblk"><rect class="body" x="30" y="66" width="150" height="68" rx="3"/>
    <text class="ttl" x="105" y="94">임무프로파일</text><text class="ttl2" x="105" y="114">시나리오 입력</text></g>
  <path class="wire" d="M180 100 H226" marker-end="url(#aw-vf)"/>
  <g class="sblk"><rect class="body" x="230" y="66" width="180" height="68" rx="3"/>
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
