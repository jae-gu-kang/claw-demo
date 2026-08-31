/** 시뮬레이션 뷰 (02 §8 5단계) — 미션 편집 → 폐루프 시뮬 → 재생 + 엔벨로프.

미션 스펙 변환은 lib/mission.js, 재생 수치는 lib/replay.js. 검증·수치는 전부
서버(엔진) 소관 — 구성 오류는 422 텍스트로 표시.
*/

import { api, errorText } from "../api.js";
import { clear, el, flagBadge, fmt } from "../dom.js";
import { buildModes, buildWaypoints, COND_KINDS } from "../lib/mission.js";
import { planeViews } from "../lib/plot.js";
import { flaggedNames, modeSpans, strideFor } from "../lib/replay.js";
import { defaultWaypointAlt, moveWaypoint, rowsToPoints } from "../lib/wpmap.js";
import { store } from "../store.js";
import { createTrack3d } from "./plot3d.js";
import { lineChartCanvas, profileCanvas, trackCanvas } from "./plots.js";
import { attachProgress, cancelledWithoutResult } from "./progress.js";
import { createProfileChart, createWpMap } from "./wpmap.js";

// 기본 미션 = 이륙점(원점) 출발 → 순항 → 원점 복귀. 고도는 **경로가 낸다**(alt="path")
// — 웨이포인트 세로 프로파일이 곧 이 미션의 고도 계획이고, 지도 옆 거리-고도 그래프가
// 그것을 그대로 그린다. 모드는 속도·헤딩만 맡는다. 웨이포인트가 고도를 갖는 순간
// 모드도 고도를 내면 주인이 둘이 되어 계획선과 실제선이 갈리므로, 한쪽으로 모았다.
//
// 종전 기본값은 엔진 회귀 미션(test_mission — 모드가 고도를 내는 climb→wpnav→descent→
// mission 4단)의 사본이었다. 웹 기본값이 그것과 갈라지는 것이 이 변경이고, **엔진
// 테스트는 그대로다**. 이 값들은 엔진 기본값의 사본이 아니라 미션 시나리오라
// 02 §5.5의 "엔진 기본값 재기술" 대상이 아니다 (lib/loops.js DEFAULT_LOOPS와 같은 부류).
//
// **출발점은 이륙 직후다.** 원점은 이륙점이고(docs/conventions.md) 트림 고도가 0이지만,
// 트림은 정상 수평비행이라 활주로에 서 있는 상태가 아니다 — 지상 반력·착륙장치 모델이
// 없어 지상 정지에서 출발할 수 없다(01 §7 백로그).
let modeRows = [
  { name: "wpnav", speed: "160", alt: "path", heading: "path",
    exitKind: "path_done", exitValue: "", next: "hold" },
  { name: "hold", speed: "140", alt: "path", heading: "",
    exitKind: "time_ge", exitValue: "1e9", next: "" },
];
let wpRows = [
  { n: "8000", e: "0", d: "700" }, // 상승 후 순항 진입 (700 = 기체가 낼 수 있는 경사 — lib CRUISE_ALT_DEFAULT)
  { n: "8000", e: "8000", d: "700" }, // 순항 다리
  { n: "0", e: "0", d: "0" }, // 원점 복귀 — 이륙점으로 돌아와 0
];
let lastReplay = null; // {body, waypoints, acceptRadius}
let runningJobId = null;
// 제출 시점 스냅샷 — 실행 중 편집이 재생 오버레이를 오염시키지 않도록 (리뷰 S3)
let runningSnapshot = { waypoints: [], acceptRadius: 0 };
// 세로 프로파일 다시 그리기 — render()가 채운다. renderWpTable은 모듈 함수라
// 클로저에 닿지 못하는데, 표에서 고도를 고쳐도 프로파일이 따라와야 한다
// (wpRows·lastReplay·wpMapView와 같은 모듈 상태 관례)
let redrawProfile = () => {};
// 도달 반경 읽기 — renderWpTable도 모듈 함수라 폼(f)에 닿지 못한다. 새 웨이포인트의
// 원점 판정에 쓰므로 지도·표 두 추가 경로가 같은 값을 봐야 한다 (redrawProfile과 같은 관례)
let acceptRadiusOf = () => 0;
// 지도 줌/팬 상태 — 탭 재진입 시 유지 (wpRows·lastReplay와 동렬)
let wpMapView = { view: null };
// 3D 시점(방위·고각) — 재렌더·탭 전환에도 돌려놓은 각도를 잃지 않게
let view3dRef = { view: null };
// 자동 재생 타이머 — 모듈 스코프에 두어야 재렌더·탭 전환에서 확실히 끌 수 있다.
// (뷰 안에만 두면 떨어져 나간 DOM을 향해 계속 도는 타이머가 남는다)
let playTimer = null;
const PLAY_FRAME_MS = 40; // 25 fps — 캔버스 3장 재그리기에 무리 없는 간격

/* 실행 조건 폼 정렬 — 캡션 1줄(14px) + 컨트롤 1줄(30px) 고정.

app.css의 label.field는 컨트롤 높이가 제각각이라(체크박스 ~16px vs 입력 ~30px)
.field.check가 padding-bottom 7px 보정값으로 줄을 맞추고 있었다 — 폰트·패딩이
조금만 바뀌어도 어긋나고, 캡션 있는 필드와 없는 필드가 섞이면 바로 틀어진다.
두 줄 높이를 고정하면 모든 필드가 같은 박스가 되어 보정값 없이 정렬된다.

스타일을 app.css가 아니라 여기서 주는 이유: app.css는 병행 세션의 미커밋 변경이
올라가 있어 손대면 그 작업을 밟는다 (wpmap 선례 4dfaaeb와 동일한 회피).
예외는 미디어 쿼리가 필요한 레이아웃 원시 — 인라인으로 표현할 수 없으므로
app.css에 둔다 (.triview). 그 경우 헝크 단위로 골라 담을 것. */
const CAPTION_ST = "height:14px; line-height:14px; font-size:11px; color:var(--muted);"
  + " white-space:nowrap; overflow:hidden; text-overflow:ellipsis;";
// 35px = 입력 실제 높이 (본문 14px/1.5 → 21px + 패딩 12 + 테두리 2). height가 아니라
// min-height — 브라우저별로 더 커지면 넘치는 대신 줄이 함께 자라 정렬이 유지된다.
const CONTROL_ST = "min-height:35px; display:flex; align-items:center; gap:6px;";
// 그룹은 같은 고정폭 박스 — 왼쪽부터 조밀하게 채우고 남는 폭으로 늘어나지 않는다.
// (격자 1fr로 늘리면 입력이 고정 90px이라 늘어난 만큼 빈 칸이 되어 패널만 휑해진다.
// 바깥 배치는 app.css .field-grid의 flex-wrap + align-items:stretch 그대로 사용.)
// shrink 1 — 좁은 화면에서는 줄었다가 wrap.
// 그룹은 내용 폭 그대로 (한 줄 배치라 필드 수만큼만 넓다). 힌트가 있는 그룹이
// 지나치게 좁아 힌트만 여러 줄로 늘어나지 않게 min-width만 받쳐 준다.
const GROUP_ST = "display:flex; flex-direction:column; flex:0 0 auto; min-width:200px;";
// 그룹 안은 한 줄 — 최대 5칸이라 접을 이유가 없다. 필드 폭을 고정해 두면
// 줄바꿈 없이도 칸 간격이 일정하다 (flex-wrap은 아주 좁은 화면의 안전망).
const INNER_ST = "display:flex; flex-wrap:wrap; gap:10px 12px; align-items:flex-start;";
const FIELD_W = "96px"; // 수치 입력 한 칸 — 최장 캡션 '연료유량 [kg/s]'이 들어가는 폭
// 입력은 칸 폭을 채운다 — .num의 고정 90px을 두면 칸마다 남는 여백이 제각각
const FILL_ST = "width:100%; box-sizing:border-box;";
// 소제목 줄 — 사용 토글을 여기 붙여 필드 칸은 수치 입력만 쓰게 한다
const TITLE_ST = "display:flex; align-items:center; gap:8px;";
// margin-top:auto — 힌트를 그룹 바닥에 붙인다. .field-grid의 align-items:stretch가
// 같은 줄 박스 높이를 맞춰 주므로, 바닥 정렬이면 힌트 줄도 나란히 선다
const HINT_ST = "margin:auto 0 0; padding-top:8px;";
// 궤적 뷰 한 변 [px] — 2열일 때 2×320 + 여백이 패널에 들어가는 크기.
// .triview에 --plane-px로 넘겨 열 상한이 된다. 이 값을 키우면 app.css의 2열 전환
// 폭(760px)도 같이 올리는 게 좋다 — 안 올리면 깨지지는 않고, 좁은 구간에서 캔버스가
// 균일 축소되어 흐려질 뿐이다 (축척은 .triview canvas.plot 규칙이 지킨다)
const PLANE_PX = 320;

/** 캡션+컨트롤 2줄 고정 필드. caption "" 이면 자리만 차지 (체크박스 줄맞춤용). */
function field(caption, ...control) {
  return el("label", { class: "field", style: `gap:4px; width:${FIELD_W}; flex:0 0 auto;` },
    el("span", { style: CAPTION_ST }, caption),
    el("div", { style: CONTROL_ST }, ...control));
}

/** 체크박스 필드 — 캡션 줄은 비우고 컨트롤 줄에 [✓] 라벨 (입력과 바닥 정렬). */
function checkField(input, label) {
  return field("", input, el("span", { style: "font-size:12px;" }, label));
}

/** 수치 입력 — 칸 폭을 채운다 (mono 글꼴은 .num이 준다). */
function numInput(value) {
  return el("input", { class: "num", style: FILL_ST, value });
}

/** 자유 텍스트용 넓은 필드 — 수치 한 칸(96px)으로는 좁은 입력. */
function wideField(caption, control) {
  const node = field(caption, control);
  node.style.width = "200px";
  return node;
}

/** 소제목 + 사용 토글 — 토글을 여기 두면 필드 칸이 수치 입력 몫으로 온전히 남는다. */
function groupTitle(text, toggle) {
  return el("div", { class: "g-title", style: TITLE_ST },
    el("span", {}, text),
    toggle && el("label", { style: "display:flex; align-items:center; gap:4px; cursor:pointer;" },
      toggle, "사용"));
}

export function render() {
  // 탭을 떠났다 돌아오면 이전 DOM은 버려진다 — 그쪽을 밀던 타이머도 같이 정리
  if (playTimer) { clearInterval(playTimer); playTimer = null; }
  const errBox = el("div");
  const progressBox = el("div");
  const replayBox = el("div");
  const modeBox = el("div");
  const wpBox = el("div");

  // 구조도 탭 '시뮬에 적용' 값 — 작동기는 필드에 프리필(최종 편집권은 여기),
  // 항법은 제출 시 병합 (시드만 이 탭이 우선, 나머지 미지정분은 엔진 기본값)
  const actApplied = store.get("actuatorParams");
  const f = {
    mach: numInput("0.6"),
    alt: numInput("0"), // 이륙점 고도 — 프로파일 출발점이자 엔진 첫 구간의 시작
    fuel: numInput("300"),
    // 경로 27.3 km + 선회 여유. 길게 두면 path_done 뒤 hold가 마지막 웨이포인트
    // 고도(0)를 잡고 **기준면 아래로 진동**한다 — 엔진 실측: t_end 210이면 3041틱
    // 이탈에 최저 −21.6 m, 180이면 214틱에 −0.64 m(그 214는 복귀 고도를 30·50 m로
    // 올려도 같다 — 출발 트림이 정확히 0이라 생기는 이륙 직후 접지다)
    tEnd: numInput("180"),
    accept: numInput("1500"),
    navOn: el("input", { type: "checkbox", checked: true }),
    seed: numInput("11"),
    actOn: el("input", { type: "checkbox", checked: true }),
    wn: numInput(String(actApplied?.wn ?? 30)),
    zeta: numInput(String(actApplied?.zeta ?? 0.7)),
    rate: numInput(String(actApplied?.rate_max ?? 10)),
    fuelFlow: numInput("0.3"),
    useGains: el("input", { type: "checkbox" }),
    useAp: el("input", { type: "checkbox" }),
    useScas: el("input", { type: "checkbox" }),
    fp: el("input", { value: "web-sim-v1", style: FILL_ST }),
  };

  // 작동기 프리필 폴백(위 30·0.7·10)은 엔진 기본값의 사본 — 폼이 즉시 유효해야 해서
  // 남기되, 스키마가 도착하면 사용자가 손대지 않은 값만 갱신해 스스로 어긋남을 고친다.
  // (항법 기본값이 7개나 어긋난 채 돌던 전례 — 01 v0.19. 실패는 무시: 폴백으로 동작)
  if (!actApplied) {
    api.get("/registry/actuator/SecondOrderActuator/schema").then((s) => {
      for (const [key, name, fallback] of
        [["wn", "wn", 30], ["zeta", "zeta", 0.7], ["rate", "rate_max", 10]]) {
        const d = s.properties?.[name]?.default;
        if (d !== undefined && f[key].value === String(fallback)) f[key].value = String(d);
      }
    }).catch(() => {});
  }

  const showErr = (e) =>
    clear(errBox).append(el("div", { class: "error-box" }, errorText(e)));

  // 세로 프로파일 — 계획(입력한 WP 고도)과 최근 시뮬 실제 고도를 같은 거리축에.
  // 지도가 수평면을, 이쪽이 세로면을 맡아 웨이포인트 한 벌을 두 면으로 본다.
  // 캔버스는 차트가 소유하고(포인터 캡처가 요소에 붙는다) 여기서는 캡션만 다시 만든다
  const profileHints = el("div");
  const profileChart = createProfileChart({
    getRows: () => wpRows,
    // 출발 고도는 시작 트림 고도 — 엔진 LosPath도 첫 구간을 기체 시작 고도에서
    // 잇는다(guidance/path.py). 폼이 비면 null(미상)로 두고 지어내지 않는다
    getStartAlt: () => {
      const sAlt = String(f.alt.value).trim();
      return sAlt !== "" && Number.isFinite(Number(sAlt)) ? Number(sAlt) : null;
    },
    // 도달 반경을 넘겨야 계획선이 엔진 명령과 같은 모양이 된다 (램프 마루)
    getAcceptRadius: () => Number(f.accept.value) || 0,
    getTrack: () => lastReplay && lastReplay.body.signals,
    onRowsChanged: () => { renderWpTable(wpBox, wpMap); wpMap.refresh(); drawProfile(); },
    onSelect: (idx) => wpMap.select(idx), // 지도와 같은 점을 가리키게
  });
  // 지도와 같은 폭 규약 — 두 면이 나란히 서고 좁아지면 함께 접힌다
  const profileBox = el("div", { style: "flex: 0 1 396px; min-width: 240px" },
    profileChart.root, profileHints);
  const drawProfile = () => {
    // 차트가 **그린 것**을 그대로 받아 캡션을 고른다 — 같은 계산을 여기서 다시
    // 적으면 한쪽만 고쳤을 때 캡션이 그려지지 않은 선을 설명한다 (02 §5.5)
    const { plan, track } = profileChart.refresh();
    const pts = rowsToPoints(wpRows);
    const kids = [];
    // 출발점(트림 고도)은 planProfile이 항상 붙인다 — 그걸 세면 WP 고도가 하나도
    // 없어도 "계획"을 그리게 되고, 캡션이 사용자가 넣지 않은 선을 설명한다.
    // 사용법 안내(else)도 트림 고도 칸을 비워야만 나오는 죽은 문장이 된다
    const wpAlts = plan.filter((p) => p.idx >= 0 && p.alt != null);
    if (wpAlts.length || track.length) {
      // 계획이 없으면 주황을 설명하지 않는다 — 그 상태의 주황은 출발점 점 하나뿐이라
      // 없는 층을 설명하는 범례와 같은 거짓말이 된다 (02 v0.36과 같은 자리)
      kids.push(wpAlts.length
        ? el("p", { class: "hint" },
          "주황=계획(입력한 WP 고도, 구간 선형 — 램프는 도달 반경 경계에서 끝나고 그 뒤는 평평) · ",
          "파랑=최근 시뮬 실제 고도. ",
          '이 계획을 실제로 날려면 모드 테이블의 고도 칸에 "path"를 적습니다 — ',
          "비워 두면 그 모드의 고도 축은 꺼지고, 숫자를 적으면 그 숫자가 이깁니다.")
        : el("p", { class: "hint" },
          "파랑=최근 시뮬 실제 고도. 웨이포인트 고도를 입력하면 계획선이 함께 그려집니다."));
      // 두 곡선의 x는 같은 이름이지만 다른 양이다 — 선회로 부푼 만큼 파랑이
      // 오른쪽으로 밀리므로, 완벽히 추종해도 "늦게 도달"로 읽힐 수 있다
      if (track.length) {
        kids.push(el("p", { class: "hint" },
          "가로축은 계획선에서는 웨이포인트를 잇는 거리, 실제선에서는 날아간 경로장입니다 — ",
          "선회로 부푼 만큼 파랑이 오른쪽으로 밀리므로 두 선의 가로 어긋남은 지연이 아닙니다."));
      }
      // 고도가 빠진 행이 있으면 계획선이 그 자리에서 끊긴다 — 몇 번인지 말한다.
      // 제출 전까지 화면만 보면 "끊긴 이유"를 알 수 없어 조용한 비표시가 된다
      // **고도를 하나도 안 넣은 정상 상태**에서는 구멍이 아니다 — 시뮬을 한 번
      // 돌리면 track 때문에 이 분기에 들어오는데, 그때 전 행을 "빈 행"으로 세면
      // 방금 성공한 실행을 두고 "실행이 거부됩니다"라고 말한다 (리뷰 실측)
      const gaps = wpAlts.length
        ? pts.map((p, i) => (p.ok && p.d == null ? i + 1 : null)).filter((v) => v)
        : [];
      if (gaps.length) {
        kids.push(el("p", { class: "hint" },
          `⚠ 고도가 빈 웨이포인트 ${gaps.join(", ")}번에서 계획선이 끊깁니다 — 고도는 전부 `
          + "채우거나 전부 비워야 하고, 섞인 채로는 실행이 거부됩니다."));
      }
    } else {
      kids.push(el("p", { class: "hint" },
        "세로 프로파일 — 웨이포인트 고도를 입력하면 거리-고도로 그립니다 (표의 '고도' 열 또는 "
        + "지도의 '선택 WP 고도'). 시뮬을 돌리면 실제 고도가 겹쳐 그려집니다."));
    }
    clear(profileHints).append(...kids);
  };
  redrawProfile = drawProfile;
  acceptRadiusOf = () => Number(f.accept.value) || 0; // 다른 두 호출부와 같은 표기

  // NED 평면 지도 편집기 — 표와 양방향 동기 (단일 소스 = wpRows)
  const wpMap = createWpMap({
    getRows: () => wpRows,
    getAcceptRadius: () => Number(f.accept.value) || 0,
    getTrack: () => lastReplay &&
      { pn: lastReplay.body.signals.pn, pe: lastReplay.body.signals.pe },
    onRowsChanged: () => { renderWpTable(wpBox, wpMap); drawProfile(); },
    onSelect: (idx) => profileChart.refresh(idx), // 프로파일도 같은 점을 가리키게
    viewRef: wpMapView,
  });
  f.accept.addEventListener("input", () => wpMap.refresh()); // 도달반경 원 즉시 갱신
  // 시작 트림 고도가 계획선의 출발점이다 — 바꾸면 프로파일도 따라 움직여야 한다
  f.alt.addEventListener("input", drawProfile);

  const watch = () => attachProgress(progressBox, runningJobId, {
    onDone: async (job) => {
      runningJobId = null;
      try {
        if (job.status === "error") throw new Error(job.error);
        if (cancelledWithoutResult(job)) {
          showErr(new Error("취소됨 — 저장된 결과 없음 (실행 전 취소)"));
          return;
        }
        const stride = strideFor(job.total || 1);
        const body = await api.get(`/sim/${job.result_id}/replay?stride=${stride}`);
        lastReplay = {
          body,
          waypoints: runningSnapshot.waypoints,
          acceptRadius: runningSnapshot.acceptRadius,
        };
        store.set("simResult", { id: job.result_id });
        renderReplay(replayBox);
        wpMap.refresh(); // 지도 궤적 오버레이 갱신
        drawProfile(); // 세로 프로파일에 실제 고도 겹치기
      } catch (e) {
        showErr(e);
      }
    },
    onError: (e) => {
      runningJobId = null;
      showErr(e);
    },
  });

  const run = async () => {
    if (runningJobId) { // 이중 제출 방지 (리뷰 S4) — 무반응 대신 안내 (조용한 무시 금지)
      clear(errBox).append(el("div", { class: "error-box" },
        "이미 실행 중입니다 — 진행률 표시를 확인하세요."));
      return;
    }
    try {
      clear(errBox);
      clear(replayBox);
      const req = {
        trim: {
          name: "start",
          mach: Number(f.mach.value), alt: Number(f.alt.value), fuel: Number(f.fuel.value),
        },
        modes: buildModes(modeRows),
        waypoints: buildWaypoints(wpRows),
        accept_radius: Number(f.accept.value),
        t_end: Number(f.tEnd.value),
        fuel_flow: Number(f.fuelFlow.value),
        fingerprint: f.fp.value,
      };
      const snapshot = { // 제출 시점 캡처 (리뷰 S3)
        waypoints: req.waypoints ?? [],
        acceptRadius: req.accept_radius,
      };
      if (req.waypoints === null) delete req.waypoints;
      if (f.navOn.checked) {
        // 미지정 파라미터는 엔진 ParamDef 기본값이 채운다 — 여기서 기본값을 다시 적으면
        // 엔진과 조용히 어긋난다 (실제로 7개가 어긋난 채 돌고 있었다: pos_std·att_std·
        // psi_std·rate_std·bias_std·delay_s·update_hz). 빈 dict도 오차 모델은 장착 —
        // 미장착은 nav 필드 자체를 생략하는 경우뿐 (routes/sim.py::_build)
        req.nav = { ...(store.get("navParams") ?? {}), seed: Number(f.seed.value) };
      }
      if (f.actOn.checked) {
        // 구조도 작동기 블록 적용값(pos 한계·initial 포함) 위에 이 탭 필드가 최종 덮어씀
        req.actuators = { ...(store.get("actuatorParams") ?? {}),
                          wn: Number(f.wn.value), zeta: Number(f.zeta.value),
                          rate_max: Number(f.rate.value) };
      }
      // 편집본 체크됐는데 적용본이 없으면 기본값 실행을 조용히 하지 않고 알림 (리뷰 Nit3)
      const missing = [];
      if (f.useGains.checked) {
        if (store.get("gainTables")) req.gain_tables = store.get("gainTables");
        else missing.push("편집 게인 (게인 탭 '시뮬에 적용' 필요)");
      }
      if (f.useAp.checked) {
        // 구조도 AP 블록 편집값 (전체 kwargs)
        if (store.get("autopilotParams")) req.autopilot = store.get("autopilotParams");
        else missing.push("편집 AP (구조도 탭 오토파일럿 블록 '시뮬에 적용' 필요)");
      }
      if (f.useScas.checked) {
        // 구조도 SCAS 축 편집값 — 세 축이 한 벌이다 (서버가 부분 주입을 거부한다)
        if (store.get("scasParams")) req.scas = store.get("scasParams");
        else missing.push("편집 SCAS (구조도 탭 SCAS 축 페이지 '시뮬에 적용' 필요)");
      }
      if (missing.length) {
        errBox.append(el("div", { class: "error-box" },
          `적용된 편집값 없음 — 기본값으로 실행됨: ${missing.join(", ")}`));
      }
      const submitted = await api.post("/sim/run", req);
      runningJobId = submitted.id;
      runningSnapshot = snapshot;
      watch();
    } catch (e) {
      showErr(e);
    }
  };

  const root = el("div", {},
    el("div", { class: "panel" },
      el("h2", {}, "미션 정의 (선언적 모드 테이블 — 01 §3.1)"),
      modeBox,
      el("h2", {}, "웨이포인트 (N, E, 고도) [m]"),
      // 지도(수평면)와 프로파일(세로면)을 **한 묶음**으로 — 셋을 한 줄에 늘어놓으면
      // 표가 넓어(고도 열) 프로파일만 아래로 밀린다. 묶어 두면 표와 함께 접힐 뿐
      // 둘은 끝까지 나란히 선다 (라이브 확인)
      el("div", { class: "row" }, wpBox,
        el("div", { class: "row", style: "gap: 12px; align-items: flex-start" },
          wpMap.root, profileBox)),
    ),
    el("div", { class: "panel" },
      el("h2", {}, "실행 조건"),
      el("div", { class: "field-grid" },
        el("div", { class: "opt-group", style: GROUP_ST },
          el("div", { class: "g-title" }, "시작 트림점 · 시간"),
          el("div", { class: "row-inner", style: INNER_ST },
            field("마하", f.mach),
            field("고도 [m]", f.alt),
            field("연료 [kg]", f.fuel),
            field("t_end [s]", f.tEnd)),
          // t_end가 경로 완주 시간과 묶여 있다는 사실이 소스에만 있으면 편집이 조용한
          // 미완주로 끝난다 — 도달반경을 200(엔진 기본)으로, 속도를 140으로 내리면
          // 기본 미션이 완주 못 하고 150~260 m 상공에서 끝난다(리뷰 실측)
          el("p", { class: "hint", style: HINT_ST },
            "고도 0 = 이륙점(원점) — 트림은 정상 수평비행이라 활주로 정지가 아니라 ",
            "이륙 직후다. t_end는 경로 완주 시간을 덮어야 한다 (기본 미션 ~176 s) — ",
            "짧으면 복귀 전에 끊기고, 길면 착륙 고도 0을 잡은 채 기준면 아래로 진동한다.")),
        el("div", { class: "opt-group", style: GROUP_ST },
          groupTitle("항법 오차 모델", f.navOn),
          el("div", { class: "row-inner", style: INNER_ST },
            field("시드", f.seed)),
          el("p", { class: "hint", style: HINT_ST }, store.get("navParams")
            ? "구조도 적용값 사용 중 (시드만 여기서 우선)"
            : "미지정 항목은 엔진 기본값 — 편집은 구조도 탭 항법 블록")),
        el("div", { class: "opt-group", style: GROUP_ST },
          groupTitle("작동기 (2차계)", f.actOn),
          el("div", { class: "row-inner", style: INNER_ST },
            field("wn [rad/s]", f.wn),
            field("ζ", f.zeta),
            field("rate [rad/s]", f.rate)),
          el("p", { class: "hint", style: HINT_ST }, actApplied
            ? "구조도 적용값 프리필됨 — 여기 값이 최종"
            : "구조도 탭에서 '시뮬에 적용' 시 프리필")),
        el("div", { class: "opt-group", style: GROUP_ST },
          el("div", { class: "g-title" }, "유도 · 연료 · 게인"),
          el("div", { class: "row-inner", style: INNER_ST },
            field("도달반경 [m]", f.accept),
            field("연료유량 [kg/s]", f.fuelFlow),
            checkField(f.useGains, "편집 게인"),
            checkField(f.useAp, "편집 AP"),
            checkField(f.useScas, "편집 SCAS"))),
        el("div", { class: "opt-group", style: GROUP_ST },
          el("div", { class: "g-title" }, "계보"),
          el("div", { class: "row-inner", style: INNER_ST },
            wideField("지문", f.fp))),
      ),
      el("div", { class: "row", style: "margin-top: 12px" },
        el("button", { class: "primary", onclick: run }, "시뮬 실행"),
        el("span", { class: "hint" },
          "작동기 rate ≥ 10 rad/s 요구 [도출 사양] (01 v0.13) · 편집 게인은 게인 탭, ",
          "편집 AP는 구조도 탭 오토파일럿 블록에서 '시뮬에 적용' 후 사용")),
      progressBox, errBox,
    ),
    el("div", { class: "panel" }, el("h2", {}, "재생 + 엔벨로프 감시"), replayBox),
  );

  renderModeTable(modeBox);
  renderWpTable(wpBox, wpMap);
  drawProfile();
  if (lastReplay) renderReplay(replayBox);
  if (runningJobId) watch(); // 실행 중 재진입 — 진행 UI 재부착 (리뷰 S4)
  return root;
}

function renderModeTable(modeBox) {
  clear(modeBox).append(
    el("div", { class: "scroll-x" }, el("table", { class: "edit" },
      el("thead", {}, el("tr", {},
        el("th", { class: "c-md" }, "모드"),
        el("th", { class: "c-sm" }, "속도 [m/s]"),
        el("th", { class: "c-sm" }, "고도 [m] | path"),
        el("th", { class: "c-md" }, "헤딩"),
        el("th", { class: "c-md" }, "이탈 조건"), el("th", { class: "c-sm" }, "값"),
        el("th", { class: "c-md" }, "다음"), el("th", {}, ""))),
      el("tbody", {}, modeRows.map((r, i) => el("tr", {},
        el("td", {}, el("input", { value: r.name,
          onchange: (ev) => { r.name = ev.target.value; } })),
        el("td", {}, el("input", { value: r.speed,
          onchange: (ev) => { r.speed = ev.target.value; } })),
        el("td", {}, el("input", { value: r.alt,
          onchange: (ev) => { r.alt = ev.target.value; } })),
        el("td", {}, el("input", { value: r.heading,
          onchange: (ev) => { r.heading = ev.target.value; } })),
        el("td", {}, el("select", {
          onchange: (ev) => { r.exitKind = ev.target.value; },
        }, Object.keys(COND_KINDS).map((k) =>
          el("option", { value: k, selected: k === r.exitKind }, k)))),
        el("td", {}, el("input", { value: r.exitValue,
          onchange: (ev) => { r.exitValue = ev.target.value; } })),
        el("td", {}, el("input", { value: r.next,
          onchange: (ev) => { r.next = ev.target.value; } })),
        el("td", {}, el("button", { class: "danger", onclick: () => {
          modeRows.splice(i, 1);
          renderModeTable(modeBox);
        } }, "삭제")),
      ))),
    )),
    el("div", { class: "row", style: "margin-top: 8px" },
      el("button", { onclick: () => {
        modeRows.push({ name: `mode${modeRows.length + 1}`, speed: "", alt: "",
                        heading: "", exitKind: "time_ge", exitValue: "1e9", next: "" });
        renderModeTable(modeBox);
      } }, "모드 추가"),
      el("span", { class: "hint" },
        '헤딩·고도: 수치 | "path"(경로추종이 낸다) | 빈=그 축 off. 속도는 수치 | 빈=off. ',
      '고도에 "path"를 적으면 웨이포인트의 세로 프로파일을 따라 난다 — 숫자를 적으면 그 숫자가 이긴다')),
  );
}

function renderWpTable(wpBox, wpMap) {
  // 표·지도 양방향 동기 — 단일 소스는 wpRows, 지도는 refresh()로 재그리기만
  const sync = () => {
    renderWpTable(wpBox, wpMap);
    wpMap?.refresh();
    redrawProfile();
  };
  clear(wpBox).append(
    el("table", { class: "edit" },
      el("thead", {}, el("tr", {},
        el("th", {}, "#"), el("th", { class: "c-md" }, "N [m]"),
        el("th", { class: "c-md" }, "E [m]"),
        el("th", { class: "c-md" }, "고도 [m]"),
        el("th", {}, "순서"), el("th", {}, ""))),
      el("tbody", {}, wpRows.map((r, i) => el("tr", {},
        el("td", {}, i + 1),
        // N·E도 프로파일을 갱신한다 — x축이 N/E로 만든 **누적 수평거리**라,
        // 지도만 다시 그리면 두 화면이 서로 다른 미션을 말한다 (리뷰 실측)
        el("td", {}, el("input", { value: r.n,
          onchange: (ev) => { r.n = ev.target.value; wpMap?.refresh(); redrawProfile(); } })),
        el("td", {}, el("input", { value: r.e,
          onchange: (ev) => { r.e = ev.target.value; wpMap?.refresh(); redrawProfile(); } })),
        // 고도는 선택 — 빈 칸은 "고도 없음"이지 0이 아니다. 빈 칸으로 되돌리면
        // 키 자체를 지운다(rowsToPoints·buildWaypoints가 그 규약을 공유한다)
        el("td", {}, el("input", { value: r.d ?? "", placeholder: "선택",
          onchange: (ev) => {
            if (ev.target.value.trim() === "") delete r.d;
            else r.d = ev.target.value;
            sync();
          } })),
        el("td", {},
          el("button", { title: "위로", onclick: () => {
            if (moveWaypoint(wpRows, i, i - 1)) sync();
          } }, "▲"),
          el("button", { title: "아래로", onclick: () => {
            if (moveWaypoint(wpRows, i, i + 1)) sync();
          } }, "▼")),
        el("td", {}, el("button", { class: "danger", onclick: () => {
          wpRows.splice(i, 1);
          sync();
        } }, "삭제")),
      ))),
    ),
    el("div", { class: "row", style: "margin-top: 8px" },
      el("button", { onclick: () => {
        // 새 행은 좌표 (0,0) = 원점이라 고도 있는 목록에서는 "0"(착륙점)이 붙고,
        // **고도 없는 목록이면 null이라 d 키를 생략**한다. 규칙은 지도 클릭 추가와
        // 같은 함수다 — 두 곳에 따로 적으면 추가 경로마다 다른 고도가 붙는다
        const d = defaultWaypointAlt(0, 0, wpRows, { acceptRadius: acceptRadiusOf() });
        wpRows.push({ n: "0", e: "0", ...(d == null ? {} : { d }) });
        sync();
      } }, "웨이포인트 추가"),
      el("span", { class: "hint" }, "지도에서 클릭 추가 · 드래그 이동 · 우클릭 삭제 가능")),
  );
}

function renderReplay(replayBox) {
  // 이전 렌더의 타이머가 살아 있으면 떨어져 나간 슬라이더를 계속 민다 — 먼저 정리
  if (playTimer) { clearInterval(playTimer); playTimer = null; }
  const { body, waypoints, acceptRadius } = lastReplay;
  const sig = body.signals;
  const env = body.envelope;
  const spans = modeSpans(sig.mode);
  const seq = spans.map((s) => s.mode).join(" → ");

  // 3면도 (평면도·측면도·정면도) — 축 배정·등축 여부는 lib/plot.js planeViews가 정본.
  // 정사각이어야 한다 — N–E 평면이 등축이려면 폭=높이여야 한다
  // (trackCanvas는 같은 span을 폭·높이에 각각 사상하므로 직사각이면 축척이 어긋난다)
  const views = planeViews(sig);
  const planeBoxes = views.map(() => el("div"));
  // 3D는 캔버스를 유지하는 컴포넌트 — 포인터 캡처가 요소에 붙어 있어 매 프레임
  // 새로 만들면 회전 드래그가 끊긴다 (wpmap과 같은 이유)
  const track3d = createTrack3d({
    getSignals: () => sig,
    getWaypoints: () => waypoints,
    viewRef: view3dRef,
    size: PLANE_PX,
  });
  const readout = el("span", { class: "progress-label" });
  const slider = el("input", {
    type: "range", min: "0", max: String(body.t.length - 1), value: "0",
    style: "width: 340px", "aria-label": "재생 시각 커서",
  });
  const updateCursor = () => {
    const i = Number(slider.value);
    readout.textContent =
      `t=${fmt(body.t[i], 4)}s ${sig.mode[i]} | h=${fmt(sig.h[i], 4)} m ` +
      `V=${fmt(sig.V[i], 4)} m/s α=${fmt(sig.alpha[i], 3)} rad ` +
      `실속마진=${fmt(env.stall_margin[i], 3)}`;
    // 시각 커서는 세 평면 모두에서 같은 시점을 가리켜야 한다 — 한 곳만 갱신하면
    // 나머지가 이전 커서를 들고 있어 서로 다른 시점처럼 읽힌다
    views.forEach((v, k) => {
      const cv = v.equal
        ? trackCanvas(sig.pn, sig.pe, waypoints, acceptRadius,
          { markerIdx: i, width: PLANE_PX, height: PLANE_PX })
        : profileCanvas(v.xs, v.ys, {
          xLabel: v.xLabel, yLabel: v.yLabel, markerIdx: i,
          wpXs: waypoints.map((w) => w[v.wpIdx]),
          width: PLANE_PX, height: PLANE_PX,
        });
      // 평면 이름은 축 라벨로 읽히므로 그리지 않는다 — 대신 보조기술용으로 남긴다
      cv.setAttribute("aria-label", `궤적 ${v.title}`);
      clear(planeBoxes[k]).append(cv);
    });
    track3d.refresh(i);
  };
  // 자동 재생 — 손으로 슬라이더를 끄는 것 외에 시간을 흘려보낼 방법이 없었다.
  // 샘플 간격(stride 적용 후)을 기준으로 배속을 곱해 진행하므로, 표시 시각은
  // 실제 시뮬 시간과 배속의 곱으로 흐른다 (프레임을 세는 게 아니라).
  const dtSample = body.t.length > 1 ? body.t[1] - body.t[0] : 0;
  const playable = body.t.length > 1 && dtSample > 0;
  const playBtn = el("button", { disabled: !playable },
    playable ? "▶ 재생" : "▶ 재생 (샘플 부족)");
  const speedSel = el("select", { "aria-label": "재생 배속" },
    ...[1, 2, 5, 10, 20].map((x) =>
      el("option", { value: String(x), selected: x === 5 }, `${x}×`)));
  const atEnd = () => Number(slider.value) >= body.t.length - 1;

  // 진행은 프레임당 고정 샘플이 아니라 **경과 벽시계 시간**으로 센다. 프레임당
  // 샘플로 세면 stride가 큰 결과(dtSample이 큰)에서 저속 배속의 몫이 1샘플 미만이
  // 되어 최소 1로 잘리고, 그만큼 요청 배속보다 빨리 재생된다 (1×가 1×가 아니게 됨).
  let fromIdx = 0;
  let fromWall = 0;
  const stopPlay = () => {
    if (playTimer) clearInterval(playTimer);
    playTimer = null;
    playBtn.textContent = "▶ 재생";
  };
  const anchor = () => { fromIdx = Number(slider.value); fromWall = performance.now(); };
  const startPlay = () => {
    if (atEnd()) { slider.value = "0"; updateCursor(); } // 끝에서 누르면 처음부터
    anchor();
    playTimer = setInterval(() => {
      const simElapsed = (performance.now() - fromWall) / 1000 * Number(speedSel.value);
      const next = Math.min(fromIdx + Math.round(simElapsed / dtSample), body.t.length - 1);
      if (next !== Number(slider.value)) { slider.value = String(next); updateCursor(); }
      if (next >= body.t.length - 1) stopPlay(); // 끝에 닿으면 자동 정지
    }, PLAY_FRAME_MS);
    playBtn.textContent = "⏸ 일시정지";
  };
  // 배속을 바꾸면 기준점을 다시 잡는다 — 안 하면 지난 경과분까지 새 배속으로 곱해져 튄다
  speedSel.addEventListener("change", () => { if (playTimer) anchor(); });
  playBtn.addEventListener("click", () => (playTimer ? stopPlay() : startPlay()));
  slider.addEventListener("input", () => {
    if (playTimer) stopPlay(); // 손으로 잡으면 재생 중단 — 커서를 둘이 끌지 않게
    updateCursor();
  });

  const chart = (title, series) =>
    lineChartCanvas(body.t, series, { title, bands: spans });

  clear(replayBox).append(
    el("p", {},
      `모드 체인: ${seq} · 절단: ${body.meta.aborted ?? "없음"} · `,
      // 플래그는 DB 유효범위(α·β·M) + 기준면 여유(고도) 통합 요약 — 어느 항목이
      // 떴는지 이름으로 밝힌다 (뭉뚱그리면 고도 이탈이 DB 이탈로 오독됨)
      "엔벨로프: ", flagBadge(!env.any_flag, "이탈 없음", `이탈: ${flaggedNames(env)}`),
      ` 최악 실속마진 ${fmt(env.worst_margin, 3)} rad @ ${fmt(env.worst_margin_t, 4)}s`,
      env.min_alt != null
        ? ` · 최저 고도 ${fmt(env.min_alt, 4)} m @ ${fmt(env.min_alt_t, 4)}s` : "",
      env.first_flag_t != null ? ` · 최초 플래그 ${fmt(env.first_flag_t, 4)}s` : "",
      ` · 최종 h ${fmt(sig.h[sig.h.length - 1], 4)} m · 잔여 연료 ${fmt(sig.fuel[sig.fuel.length - 1], 4)} kg`),
    el("div", { class: "row" }, playBtn, speedSel, slider, readout),
    // 궤적 뷰 — 입체·평면·측면·정면 순. 배치는 .triview가 폭에 따라 1열/2열로
    // 고르며, 열 수를 4의 약수로만 두어 마지막 줄에 외톨이가 남지 않게 한다.
    // 시계열 위에 두어 커서 조작(바로 위 슬라이더)과 그 반응이 눈에 같이 들어오게 한다
    el("div", { style: "display:flex; flex-direction:column; gap:6px; margin-bottom:12px;" },
      el("div", { class: "hint" },
        "궤적 3D + 3면도 (NED) — N–E 평면만 등축(선회반경 판독용), 연직 평면과 3D는 ",
        "비등축이라 경사각을 눈으로 재면 안 됨. 주황 세로선·점은 웨이포인트의 수평좌표"),
      // --plane-px로 열 상한을 넘겨 PLANE_PX를 단일 정본으로 유지한다 (CSS에 320을
      // 또 박지 않기 위함). 2열 전환 폭만은 미디어 쿼리라 app.css와 수동 동기.
      el("div", { class: "triview", style: `--plane-px: ${PLANE_PX}px` },
        track3d.root, planeBoxes[0], planeBoxes[1], planeBoxes[2])),
    el("div", { class: "row" },
      el("div", {},
        chart("고도 h [m]", [{ label: "h", data: sig.h, color: "#007aff" }]),
        chart("속도 V [m/s]", [{ label: "V", data: sig.V, color: "#007aff" }]),
        chart("자세 [rad]", [
          { label: "φ", data: sig.phi, color: "#ff9500" },
          { label: "θ", data: sig.theta, color: "#007aff" }]),
        chart("받음각·실속마진 [rad]", [
          { label: "α", data: sig.alpha, color: "#ff3b30" },
          { label: "α_stall−α", data: env.stall_margin, color: "#34c759" }]),
      ),
    ),
  );
  updateCursor();
}
