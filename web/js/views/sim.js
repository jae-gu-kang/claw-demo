/** 시뮬레이션 뷰 (02 §8 5단계) — 미션 편집 → 폐루프 시뮬 → 재생 + 엔벨로프.

미션 스펙 변환은 lib/mission.js, 재생 수치는 lib/replay.js·lib/playcursor.js. 검증·수치는 전부
서버(엔진) 소관 — 구성 오류는 422 텍스트로 표시.
*/

import { api, errorText } from "../api.js";
import { clear, el, flagBadge, fmt } from "../dom.js";
import { buildModes, buildWaypoints, COND_KINDS, LON_AXES, pathUsage } from "../lib/mission.js";
import { planeViews, wpMarks } from "../lib/plot.js";
import { atEnd as cursorAtEnd, dtSample, indexAt, isPlayable } from "../lib/playcursor.js";
import { flaggedNames, landingSummary, modeSpans, strideFor } from "../lib/replay.js";
import { GOHEUNG, touchdownWindowM } from "../lib/site.js";
import { fillMissingAltitudes, moveWaypoint, rowsToPoints } from "../lib/wpmap.js";
import { store } from "../store.js";
import { createTrack3d } from "./plot3d.js";
import { lineChartCanvas, profileCanvas, trackCanvas } from "./plots.js";
import { attachProgress, cancelledWithoutResult } from "./progress.js";
import { createProfileChart, createWpMap } from "./wpmap.js";

// 기본 미션 = **발사대에서 떠서 활주로에 선다** (01 §3.3.1 이륙~착륙).
// 발사 → 상승 → 순항 → 접근 → 플레어 → 미끄럼 → 정지.
//
// 종방향 축이 단계마다 갈린다 — launch·climb·rollout은 **피치**(고도 루프를 거칠
// 이유가 없는 자세 구간), approach·flare는 **강하율**(어느 고도가 아니라 내려가는
// 속도를 잡는 구간), cruise만 **고도**다. 셋은 배타라 한 모드에 하나씩만 들어간다.
//
// 수치는 엔진 실측으로 정했다. 이탈속도·플레어 개시·미끄럼은 engine test_landing과
// 같은 값이고, **climb·cruise는 일부러 다르다** — 저쪽은 250/300 m라 다운레인지가
// 10.8 km인데, 이쪽은 지형 팩 안에 들어오도록 180/200 m로 낮춰 8.0 km로 줄였다
// (7.9였다가 cruise 이탈이 time_ge 15 → path_done으로 바뀌며 264 m 늘었다 — 여전히
//  core ±12 km 안):
//   이탈 81.5 m/s = 1.15 × 트림 실속속도 70.9 — α_stall 0.40에서 CL 1.40이 나오지만
//   거기까지 가려면 상향 엘러본이 필요하고 그것이 양력을 깎아 실제 최대 트림 CL은 1.169다
//   플레어 개시 20 m·kp_vs 0.08 → 접지 −1.0 m/s (5 m에서는 0.9 s뿐이라 −4.6)
//   접지 후 미끄럼 870 m — 고흥 활주로 실측 1,205 m에서 접지 창은 335 m뿐이다
//   (기본 미션은 활주로가 아니라 한참 북쪽에 내린다 — 화면이 그것을 숨기지 않도록
//    착륙 요약이 "접지 지점" 행에 활주로 축 기준 실제 값을 낸다. 여기에 그 수를 적어
//    두면 프로파일이 바뀔 때마다 조용히 낡는다 — lib/replay.js landingSummary)
//
// 이 값들은 엔진 기본값의 사본이 아니라 **미션 시나리오**라 02 §5.5의 "엔진 기본값
// 재기술" 대상이 아니다 (lib/loops.js DEFAULT_LOOPS와 같은 부류). 엔진 회귀 미션
// (test_mission — 지면 미장착 순항 시나리오)은 그대로 남아 있다.
const CLIMB_PITCH = "0.3665"; // [rad] 21° — α 리미터 한계까지 기수를 든다
// 고흥 활주로 진방위 실측 (lib/site.js ← data/geo/goheung-runway.json). 미션 헤딩과
// 활주로 칸의 **초기값**이 같은 상수에서 나온다 — 헤딩 0으로 날던 때는 10 km 뒤에
// 축에서 595 m 벌어져 있었고, 맞추고 나니 29 m다. 다만 렌더 뒤로는 두 칸이 독립이라
// 한쪽만 고치면 다시 벌어진다. 그때 어긋남을 말해 주는 것은 이 상수가 아니라
// 착륙 요약의 접지 위치 줄이다.
const RUNWAY_HDG = String(GOHEUNG.runwayHeadingRad); // [rad] 3.417°
let modeRows = [
  { name: "launch", speed: "110", lonAxis: "pitch", lonValue: CLIMB_PITCH, heading: RUNWAY_HDG,
    exitKind: "off_rail", exitValue: "", next: "climb" },
  { name: "climb", speed: "110", lonAxis: "pitch", lonValue: CLIMB_PITCH, heading: RUNWAY_HDG,
    exitKind: "alt_ge", exitValue: "180", next: "cruise" },
  // 순항 헤딩은 "path" — 기본 웨이포인트(아래 wpRows)를 따라 날고, 소진(path_done)이
  // 접근 진입을 정한다. 종전 time_ge 15는 경로를 15 s만 따르다 시계로 포기하고
  // 활주로 방위로 되돌아갔다(실측: 왼쪽 −3° WP 열에서 pe −100까지 갔다가 +4로 복귀)
  // — 웨이포인트를 찍어도 비행이 안 바뀌는 첫 번째 이유였다 (사용자 제기).
  { name: "cruise", speed: "88", lonAxis: "alt", lonValue: "200", heading: "path",
    exitKind: "path_done", exitValue: "", next: "approach" },
  // 3° 활공: 88 m/s · sin3° ≈ 4.6 m/s
  { name: "approach", speed: "88", lonAxis: "hdot", lonValue: "-4.8", heading: RUNWAY_HDG,
    exitKind: "alt_le", exitValue: "20", next: "flare" },
  { name: "flare", speed: "80", lonAxis: "hdot", lonValue: "-0.8", heading: RUNWAY_HDG,
    exitKind: "on_ground", exitValue: "", next: "rollout" },
  { name: "rollout", speed: "0", lonAxis: "pitch", lonValue: "0", heading: RUNWAY_HDG,
    exitKind: "speed_le", exitValue: "0.5", next: "stopped" },
  { name: "stopped", speed: "0", lonAxis: "pitch", lonValue: "0", heading: "",
    exitKind: "time_ge", exitValue: "1e9", next: "" },
];
// 기본 웨이포인트 — 활주로 축 위 2.6·3.3 km. cruise가 heading="path"라 웨이포인트
// 없이는 엔진이 구성을 거부한다(422: 경로추종기 없음) — 기본 상태가 실행 불가면
// 안 되므로 직진 이착륙 미션을 **축 위 웨이포인트로** 그대로 재현한다. 좌표를
// 리터럴 대신 방위에서 계산하는 이유는 RUNWAY_HDG와 같은 상수를 공유하기 위해서다
// (활주로 방위가 바뀌면 함께 돈다 — 리터럴이면 조용히 축을 벗어난다).
//
// 거리 실측 근거: 순항 진입이 t=15.06 s·1,440 m라 2.6 km 첫 점이 즉시 소진되지
// 않고, path_done이 3,197 m에서 떠 종전 time_ge 15의 이탈 지점(2,921 m)과 비슷하다.
// 정지 101.4 s·다운레인지 8.0 km — t_end 200 안이고 지형 팩 core(±12 km) 안이다.
// 고도 칸은 비워 둔다(세로는 cruise의 고도 200이 낸다) — 고도를 넣는 순간
// "전부 있거나 전부 없거나" 규칙과 alt="path" 전환이 사용자 몫이 된다.
const axisWp = (dist) => ({
  n: String(Math.round(dist * Math.cos(GOHEUNG.runwayHeadingRad))),
  e: String(Math.round(dist * Math.sin(GOHEUNG.runwayHeadingRad))),
  d: "",
});
let wpRows = [axisWp(2600), axisWp(3300)];
let lastReplay = null; // {body, waypoints, acceptRadius}
let runningJobId = null;
// 제출 시점 스냅샷 — 실행 중 편집이 재생 오버레이를 오염시키지 않도록 (리뷰 S3)
let runningSnapshot = { waypoints: [], acceptRadius: 0 };
// 세로 프로파일 다시 그리기 — render()가 채운다. renderWpTable은 모듈 함수라
// 클로저에 닿지 못하는데, 표에서 고도를 고쳐도 프로파일이 따라와야 한다
// (wpRows·lastReplay·wpMapView와 같은 모듈 상태 관례)
let redrawProfile = () => {};
// 웨이포인트가 미션에 반영되는지 다시 판정 — 모드 표(헤딩·종방향 값)와 웨이포인트
// 표 양쪽이 부른다. 둘 다 모듈 함수라 render()의 노드에 닿지 못한다 (redrawProfile 관례)
let renderWpNotice = () => {};
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
// 힌트에 폭 상한을 둔다 — opt-group이 flex:0 0 auto라 **내용이 폭을 정하므로**,
// 긴 문장 하나가 그룹을 늘려 실행 조건 패널 전체를 화면 밖으로 밀어낸다(라이브에서
// 실제로 잘렸다). 상한을 두면 문장이 접히고 그리드가 열로 나뉜다.
const HINT_ST = "margin:auto 0 0; padding-top:8px; max-width:360px;";
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

/** 빈 칸은 0이 아니라 NaN — JSON에서 null이 되어 서버가 422로 답한다.
 *  `Number("")`가 0인 것이 조용한 오답의 통로다. */
function blankIsNaN(value) {
  return String(value).trim() === "" ? NaN : Number(value);
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

  // 가상환경 게임 모드가 보낸 웨이포인트 초안 — **한 번 읽고 지운다.** store에 남기면
  // 탭을 오갈 때마다 이 표의 편집이 초안으로 되돌아간다. 행 형식(문자열 n·e·d,
  // d = 고도[m])은 이 파일 wpRows가 정본이고, 보낸 쪽(web/world WorldTab)이 그걸 따른다.
  const wpDraft = store.get("wpDraft");
  let wpDraftNote = null;
  if (Array.isArray(wpDraft?.rows) && wpDraft.rows.length > 0) {
    wpRows = wpDraft.rows.map((r) => ({
      n: String(r.n ?? ""), e: String(r.e ?? ""),
      // 빈 고도는 키 자체를 생략한다 — "전부 있거나 전부 없거나"(lib/mission.js) 규칙에
      // 빈 문자열 d를 섞으면 제출이 거부된다.
      ...(r.d == null || String(r.d).trim() === "" ? {} : { d: String(r.d) }),
    }));
    store.set("wpDraft", null);
    wpMapView.view = null; // 새 목록에 맞춰 지도 시야를 다시 맞춘다 (fitView)
    // 고도 추종을 약속하지 않는다 — 기본 미션의 순항 종방향은 "고도 200"이라 세로
    // 프로파일이 비행에 반영되지 않고, 바로 아래 wpNotice가 그 사실을 경고한다. 여기서
    // "고도 그대로"라고 말하면 같은 화면의 두 문장이 서로 반대를 말하게 된다(리뷰 확정).
    wpDraftNote = `가상환경 게임 모드에서 웨이포인트 ${wpRows.length}개를 가져왔습니다 — `
      + "표·지도에서 다듬은 뒤 실행하세요. 수평 경로는 순항(헤딩 \"path\")이 따라가고, "
      + "고도까지 따르게 하려면 순항 종방향 축을 '고도'로 두고 값에 \"path\"를 적으세요.";
  }
  const errBox = el("div");
  const progressBox = el("div");
  const replayBox = el("div");
  const modeBox = el("div");
  const wpBox = el("div");

  // 구조도 탭 '시뮬에 적용' 값 — 작동기는 필드에 프리필(최종 편집권은 여기),
  // 항법은 제출 시 병합 (시드만 이 탭이 우선, 나머지 미지정분은 엔진 기본값)
  const actApplied = store.get("actuatorParams");
  const f = {
    // 기본 미션은 **발사대 위 정지**에서 출발한다 — 지상 평형해라 mach는 0이고
    // alt는 비행 고도가 아니라 활주로 표고다 (엔진 trim_ground)
    mach: numInput("0"),
    alt: numInput("0"), // 활주로 표고 — 기준면 감시도 이 값이 된다
    fuel: numInput("300"),
    groundOn: el("input", { type: "checkbox", checked: true }),
    // 방위·길이는 고흥 활주로 실측이다 — data/geo/goheung-runway.json 참조.
    // 미끄럼 870 m가 1,205 m 안에 들어가지만, 그것은 **미끄럼이 짧다**는 뜻일 뿐
    // 활주로에 내렸다는 뜻이 아니다 (lib/replay.js landingSummary는 접지 위치를 본다).
    rwHeading: numInput(RUNWAY_HDG),
    rwLength: numInput(String(GOHEUNG.runwayLengthM)),
    launchOn: el("input", { type: "checkbox", checked: true }),
    railLen: numInput("10"),
    railAngle: numInput("0.2618"), // [rad] 15°
    railExit: numInput("81.5"), // 1.15 × 트림 실속속도 70.9 → 33.9 g
    rtkOn: el("input", { type: "checkbox", checked: true }),
    // 측지 원점 — NED (0,0)이 지구상 어디인가. 엔진은 보지 않고 결과 meta에만 실린다.
    // 이것이 없으면 3D 월드가 지형을 얹을 수 없다(같은 N·E가 어디인지 모르므로).
    // 기본값은 고흥 활주로 **남단 임계** 실측값이다(항공영상에서 측정 —
    // data/geo/goheung-runway.json에 방법과 검산이 있다). 남단인 이유는 활주로가
    // 화면·판정 양쪽에서 "원점에서 heading 방향 length 구간"이기 때문이다.
    // 기본 켜짐 — 끄면 결과에 원점이 없어 3D 월드가 지형을 얹지 못한다.
    originOn: el("input", { type: "checkbox", checked: true }),
    originLat: numInput(String(GOHEUNG.originLatDeg)),
    originLon: numInput(String(GOHEUNG.originLonDeg)),
    // 기본 미션은 100 s 안팎에 선다(순항 고도를 낮추며 짧아졌다 — 107/130은 엔진
    // test_landing 쪽 시각이지 이제 이 미션의 시각이 아니다). 200은 그 두 배 여유다.
    // 짧으면 서기 전에 끊긴다. **정확한 시각은 실행 후 착륙 요약이 말한다** — 여기에
    // 적어 두면 프로파일이나 스케줄이 바뀔 때마다 조용히 낡는다
    tEnd: numInput("200"),
    // 도달 반경 [기본값] — 100 m. 종전 1,500 m는 선회 반경(940 m)보다 크게 잡아
    // 확실히 잡히지만 통과 판정이 매우 헐거웠다.
    //
    // **하한은 유도가 실제로 내는 접근 거리가 정한다.** 순항 88 m/s·뱅크 한계
    // 0.7 rad에서 선회 반경이 V²/(g·tanφ) ≈ 940 m라, LOS 추종은 임의로 작은 원을
    // 잡지 못한다 — 목표를 지나쳤다 되돌기를 반복한다(순수추종의 알려진 거동).
    // 실측(현 기본 미션 — 축 위 WP 2개): 첫 접근 최근접이 13.0 m라 20 m는 첫
    // 바퀴에 잡고 완주하지만, 13 m로 줄이면 14.4 m로 스친 뒤 **바퀴마다 되레
    // 멀어진다**(14 → 69 → 81 → 85 m, 주기 ~70 s) — 수렴이 아니라 발산이라
    // t_end를 늘려도 못 잡고, 미션이 순항에서 멈춘 채 끝난다(touchdown None).
    // 100 m는 WP 곁 7.8 m를 지나며 완주한다. 90° 선회를 낀 기하도 6.2 m까지
    // 좁혔다. 종전 기본 웨이포인트(다른 기하)에서는 20 m가 28→36→47로 발산했다
    // — 같은 값이 기하에 따라 되기도 안 되기도 한다는 실측.
    //
    // 그 하한은 **상수가 아니다** — 웨이포인트 기하 × 기체 선회 성능의 함수라
    // 화면이 미리 판정할 수 없다. 그래서 폼은 값을 막지 않고 사유를 적어 둔다.
    // 경로가 안 끝나면(path_done이 안 뜨면) 이 값을 먼저 의심할 것.
    accept: numInput("100"),
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

  // 웨이포인트를 **쓰는 모드가 있는가**. 없으면 지도·재생은 주황 경로를 그리는데
  // 기체는 그 옆을 직진한다 — 화면이 스스로 모순되는 자리라 말해 준다.
  // 실측(WP 2개): 헤딩이 전부 숫자면 pe가 5e-16, cruise만 "path"로
  // 바꾸면 −1495~+2859. 기본 미션의 cruise가 "path"가 된 지금도 이 경고는 남는다 —
  // 헤딩 칸을 숫자로 되돌리거나 "path" 모드가 사슬에서 빠지면 같은 자리가 재발한다.
  // 엔진은 반대 방향만 막는다(path인데 경로 없음 → 422);
  // 이쪽은 막을 수 없다 — 날지 않고 경로오차(xtrack_rms) 기준선으로만 두는 쓰임이 있다
  const wpNotice = el("div");
  const drawWpNotice = () => {
    clear(wpNotice);
    const pts = rowsToPoints(wpRows).filter((p) => p.ok);
    if (!pts.length) return;
    const use = pathUsage(modeRows);
    const hasAlt = pts.some((p) => p.d != null);
    // 축을 따로 센다 — 수평만 따르는 미션이 흔한데(고도는 모드가 낸다) 그때
    // "웨이포인트가 반영되지 않습니다"라고 뭉뚱그리면 화면이 사실이 아닌 말을 한다
    // 안내 문장은 축마다 **통째로** 든다 — 이름에 조사를 붙여 조립하면
    // "수평 경로이"·"세로 프로파일는"이 된다(라이브 확인). 목록 자리도 조사를 피한다
    const miss = [];
    if (!use.heading) {
      miss.push(["수평 경로",
        '수평 경로는 어느 모드의 헤딩 칸에 "path"를 적어야 따릅니다.']);
    }
    if (hasAlt && !use.alt) {
      miss.push(["세로 프로파일",
        '세로 프로파일은 종방향 축을 ‘고도’로 두고 값에 "path"를 적어야 따릅니다.']);
    }
    if (!miss.length) return;
    clear(wpNotice).append(el("div", { class: "error-box" },
      `⚠ 웨이포인트 ${pts.length}개 — 비행에 반영되지 않는 축: `,
      el("b", {}, miss.map((m) => m[0]).join(" · ")),
      ". ",
      miss.map((m) => m[1]).join(" "),
      " 지금 실행해도 그 축은 결과에 기준선으로만 실립니다(경로오차 지표) — ",
      "기체는 모드 표의 값대로 날아갑니다."));
  };
  renderWpNotice = drawWpNotice;

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
          // 지상 평형인지 수평비행인지 — 활주로가 있으면 발사대/활주로 위 정지에서
          // 출발한다. 엔진이 mach=0을 요구하므로 둘이 어긋나면 서버가 422로 답한다
          condition: f.groundOn.checked ? "ground" : "level",
        },
        modes: buildModes(modeRows),
        waypoints: buildWaypoints(wpRows),
        accept_radius: Number(f.accept.value),
        t_end: Number(f.tEnd.value),
        // 활주로가 있어야 스키드가 달린다 — 없으면 지면 자체가 없어서 기체가
        // h<0을 그대로 통과한다(접지·정지 판정도 불가)
        ...(f.groundOn.checked ? { runway: {
          elevation: Number(f.alt.value),
          heading: Number(f.rwHeading.value),
          length: Number(f.rwLength.value),
        } } : {}),
        // 빈 칸을 Number()에 그대로 넘기면 0이 된다 — 오타(NaN→null→422)와 달리
        // (0,0)은 **유효하고 그럴듯한 틀린 값**이라 기니만 앞바다가 결과 meta에 박힌 채
        // 저장된다. 다른 칸은 서버 제약(length gt=0 등)이 막아 주지만 원점은 안 막힌다.
        // 빈 칸은 오타와 같은 길로 보내 서버가 422로 답하게 한다 (리뷰 지적).
        ...(f.originOn.checked ? { origin: {
          lat: blankIsNaN(f.originLat.value),
          lon: blankIsNaN(f.originLon.value),
        } } : {}),
        ...(f.launchOn.checked ? { launch: {
          length: Number(f.railLen.value),
          elev_angle: Number(f.railAngle.value),
          exit_speed: Number(f.railExit.value),
        } } : {}),
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
        // 등급은 **이름으로** 고른다 — RTK 수치를 여기 적으면 엔진 RTK_FIXED와
        // 조용히 어긋난다(§5.5, 항법 기본값 7개가 어긋난 채 돌던 전례와 같은 자리)
        if (f.rtkOn.checked) req.nav_grade = "rtk";
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
      wpDraftNote && el("p", { class: "hint" }, wpDraftNote),
      wpNotice,
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
          // t_end가 완주 시간과 묶여 있다는 사실이 소스에만 있으면 편집이 조용한
          // 미완주로 끝난다 — 짧으면 서기 전에 끊긴다
          el("p", { class: "hint", style: HINT_ST },
            "활주로를 켜면 발사대·활주로 위 정지에서 출발합니다 — 그때 마하는 0이고 ",
            "고도는 비행 고도가 아니라 활주로 표고입니다(지상 평형해). 끄면 종전처럼 ",
            "수평비행 트림에서 출발하고 마하 > 0이 필요합니다. ",
            "t_end는 정지까지 덮어야 합니다 — 기본 미션은 100 s 안팎에 서므로 ",
            "200 s면 여유가 남습니다. 실제 접지·정지 시각은 실행 후 착륙 요약에 나옵니다.")),
        el("div", { class: "opt-group", style: GROUP_ST },
          groupTitle("활주로 · 지면", f.groundOn),
          el("div", { class: "row-inner", style: INNER_ST },
            field("방위 [rad]", f.rwHeading),
            field("길이 [m]", f.rwLength)),
          el("p", { class: "hint", style: HINT_ST },
            "이걸 켜야 스키드가 달립니다 — 끄면 지면 자체가 없어 기체가 지면을 ",
            "그대로 통과하고, 접지·정지 판정(on_ground·speed_le)도 성립하지 않습니다. ",
            "지면은 표고 하나짜리 평면입니다 — 지형·파고는 미모델입니다. ",
            "표고는 위 '고도' 칸이고 기준면 감시도 그 값을 씁니다. ",
            `방위 ${RUNWAY_HDG} rad(3.417°)·길이 ${GOHEUNG.runwayLengthM} m는 고흥 `,
            "활주로를 항공영상에서 잰 값입니다 — 공표 제원 1.2 km와 0.4% 안에서 맞습니다. ",
            `접지 후 미끄럼이 ${GOHEUNG.rolloutM} m라, 활주로 안에 서려면 `,
            `${touchdownWindowM()} m 안에 접지해야 합니다. `,
            "아래 착륙 요약은 접지→정지 ", el("strong", {}, "거리"), "만 이 길이와 ",
            "견주고 접지 ", el("strong", {}, "위치"), "는 보지 않습니다 — ",
            "활주로에 내렸는지는 판정하지 않습니다.")),
        el("div", { class: "opt-group", style: GROUP_ST },
          groupTitle("측지 원점", f.originOn),
          el("div", { class: "row-inner", style: INNER_ST },
            field("위도 [deg]", f.originLat),
            field("경도 [deg]", f.originLon)),
          el("p", { class: "hint", style: HINT_ST },
            "NED 원점 (0,0)이 지구상 어디인지 적습니다. 엔진은 이 값을 보지 않고 ",
            "결과에만 실립니다 — 가상환경이 지형을 얹으려면 지형 팩과 이 원점이 같아야 ",
            "합니다. 기본값은 고흥 시험장 활주로 ",
            el("strong", {}, "남단 임계"),
            "를 항공영상에서 측정한 값입니다(34.601303 / 127.212067). 측정 방법과 ",
            "공표 제원 대조는 data/geo/goheung-runway.json에 있습니다.")),
        el("div", { class: "opt-group", style: GROUP_ST },
          groupTitle("발사 레일", f.launchOn),
          el("div", { class: "row-inner", style: INNER_ST },
            field("길이 [m]", f.railLen),
            field("앙각 [rad]", f.railAngle),
            field("이탈속도 [m/s]", f.railExit)),
          el("p", { class: "hint", style: HINT_ST },
            "레일 구간은 힘이 아니라 구속이라, 자세가 고정된 등가속 운동입니다 ",
            "— 해석해로 정확히 적분하므로 스텝 수와 무관합니다. ",
            "이탈속도 81.5 m/s는 트림 실속속도 70.9의 1.15배이고, 레일 10 m에서 ",
            "그 속도는 33.9 g를 요구합니다 — 종방향 발사하중 한계가 아직 없어 ",
            "(구조 한계표의 6.0은 Nz입니다) 결과에 '미판정'으로 표시됩니다.")),
        el("div", { class: "opt-group", style: GROUP_ST },
          groupTitle("항법 오차 모델", f.navOn),
          el("div", { class: "row-inner", style: INNER_ST },
            field("시드", f.seed)),
          el("div", { class: "row-inner", style: INNER_ST },
            el("label", { class: "chk" }, f.rtkOn, " RTK 고정해")),
          el("p", { class: "hint", style: HINT_ST }, store.get("navParams")
            ? "구조도 적용값 사용 중 (시드만 여기서 우선). "
            : "미지정 항목은 엔진 기본값 — 편집은 구조도 탭 항법 블록. ",
            "RTK는 접지를 부드럽게 하지 않습니다 — 접지 지점을 반복 가능하게 합니다. ",
            `활주로 ${GOHEUNG.runwayLengthM} m라도 미끄럼 ${GOHEUNG.rolloutM} m는 `,
            `굴러가므로, 활주로 안에 서려면 ${touchdownWindowM()} m 안에 접지해야 `,
            "합니다 — 산포를 활주로 전장과 견주면 안 됩니다. ",
            // **수치를 옮겨 적지 않는다.** 산포는 항법 등급·접근 프로파일·게인
            // 스케줄의 함수라 여기 적으면 낡는데, 웹은 엔진을 읽지 않고 엔진은
            // 여기를 읽지 않아 **낡아도 아무것도 빨개지지 않는다**. 실제로 이번에
            // 게인 스케줄 상한을 내리면서 874/92가 512/12가 됐고, 그때 출처만
            // 덧붙였더니 낡음을 기록만 하고 해결하지는 못했다(리뷰 지적).
            // UI 결정(RTK 토글)에 필요한 것은 정밀한 수가 아니라 **순서**이고,
            // 그것은 재측정을 견딘다. 현재 수치가 필요하면 엔진이 집이다
            "기본 항법의 접지 산포는 그 창을 넘고 RTK는 그 안에 듭니다 — ",
            "현재 수치는 엔진 test_landing이 5시드로 잽니다. ",
            "fix 유지가 전제입니다 — 보정 링크가 끊겨 강등되는 상황은 미모델입니다.")),
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
            checkField(f.useScas, "편집 SCAS")),
          // 반경이 너무 작으면 경로가 안 끝나는데, 그때 화면에 뜨는 것은 오류가
          // 아니라 "순항에서 멈춘 모드 체인"뿐이라 성공처럼 읽힌다 — 그 사실이
          // 소스 주석에만 있었다.
          //
          // **선회 반경을 문턱으로 적지 않는다.** 처음엔 "선회 반경보다 작으면
          // 끝나지 않는다"고 굵게 적었는데, 바로 다음 문장의 100 m가 940 m보다
          // 작으면서 완주하므로 **자기 예시가 반증한다**(리뷰 지적). 게다가 틀린
          // 방향이 비싸다 — 그 말을 따르면 필요보다 한 자릿수 헐거운 940 m를 잡게
          // 되고, 그건 사용자가 20 m를 요청한 이유(정밀한 통과)를 되돌리는 것이다.
          // 선회 반경은 **왜 임의로 작은 원을 못 잡는지**를 설명할 뿐 문턱이 아니고,
          // 실제 문턱은 유도가 내는 접근 거리(이 미션 28.5 m)이며 그것은 상수가
          // 아니라 웨이포인트 기하 × 기체 선회 성능의 함수다. 그래서 수를 단정하지
          // 않고 실측만 늘어놓는다.
          el("p", { class: "hint", style: HINT_ST },
            "다음 웨이포인트로 넘어가는 통과 판정 반경입니다 — ",
            // 마크다운 **는 여기서 글자 그대로 나온다 (텍스트 노드) — 강조는 노드로
            el("b", {}, "너무 작으면 경로가 끝나지 않습니다"),
            ". 데모 기체는 순항 88 m/s·뱅크 한계 0.7 rad에서 선회 반경이 940 m라 ",
            "임의로 작은 원은 못 잡습니다 — 기본 미션 실측상 첫 접근 최근접이 13 m라 ",
            "20 m는 완주하지만, 13 m로 줄이면 14 m로 스친 뒤 바퀴마다 되레 멀어져",
            "(14 → 69 → 81 m) 끝내 통과하지 못합니다. 그 경계는 웨이포인트 기하마다 ",
            "다릅니다 — 다른 기하에서는 20 m도 같은 식으로 발산했습니다. ",
            "경로가 안 끝나면(모드 체인이 순항에서 멈추면) 이 값을 먼저 의심하십시오.")),
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
        el("th", { class: "c-md" }, "종방향"), el("th", { class: "c-sm" }, "값"),
        el("th", { class: "c-md" }, "헤딩"),
        el("th", { class: "c-md" }, "이탈 조건"), el("th", { class: "c-sm" }, "값"),
        el("th", { class: "c-md" }, "다음"), el("th", {}, ""))),
      el("tbody", {}, modeRows.map((r, i) => el("tr", {},
        // 이름·next는 **어느 모드가 실행에 닿는지**를 정한다 (엔진은 첫 행에서
        // next로만 넘어간다) — 사슬이 끊기면 그 뒤의 "path"는 죽은 값이므로
        // 웨이포인트 안내도 다시 판정해야 한다
        el("td", {}, el("input", { value: r.name,
          onchange: (ev) => { r.name = ev.target.value; renderWpNotice(); } })),
        el("td", {}, el("input", { value: r.speed,
          onchange: (ev) => { r.speed = ev.target.value; } })),
        // 종방향은 **하나를 고르게** 한다 — alt·pitch·hdot이 전부 θ_cmd로 가므로
        // 축마다 칸을 주면 둘을 채운 행이 만들어지고, 그때 화면은 "무엇이 먹었는지"를
        // 말할 수 없다. 배타 규칙이 편집 형태에 그대로 드러난다
        el("td", {}, el("select", {
          onchange: (ev) => { r.lonAxis = ev.target.value; renderModeTable(modeBox); },
        }, LON_AXES.map((a) =>
          el("option", { value: a.value, selected: a.value === (r.lonAxis ?? "") },
            a.label)))),
        el("td", {}, el("input", {
          value: r.lonValue ?? "",
          // 축이 off면 값 칸도 잠근다 — 적어 둔 숫자가 나가지 않는데 남아 있으면
          // "이 값이 쓰인다"고 읽힌다
          disabled: !(r.lonAxis ?? ""),
          title: LON_AXES.find((a) => a.value === (r.lonAxis ?? ""))?.unit ?? "",
          // 이 칸의 "path"가 세로 프로파일을 켜는 곳이라, 고치면 웨이포인트 안내도
          // 다시 판정해야 한다 (헤딩 칸도 같은 이유)
          onchange: (ev) => { r.lonValue = ev.target.value; renderWpNotice(); },
        })),
        el("td", {}, el("input", { value: r.heading,
          onchange: (ev) => { r.heading = ev.target.value; renderWpNotice(); } })),
        el("td", {}, el("select", {
          onchange: (ev) => { r.exitKind = ev.target.value; },
        }, Object.keys(COND_KINDS).map((k) =>
          el("option", { value: k, selected: k === r.exitKind }, k)))),
        el("td", {}, el("input", { value: r.exitValue,
          onchange: (ev) => { r.exitValue = ev.target.value; } })),
        el("td", {}, el("input", { value: r.next,
          onchange: (ev) => { r.next = ev.target.value; renderWpNotice(); } })),
        el("td", {}, el("button", { class: "danger", onclick: () => {
          modeRows.splice(i, 1);
          renderModeTable(modeBox);
        } }, "삭제")),
      ))),
    )),
    el("div", { class: "row", style: "margin-top: 8px" },
      el("button", { onclick: () => {
        modeRows.push({ name: `mode${modeRows.length + 1}`, speed: "",
                        lonAxis: "", lonValue: "",
                        heading: "", exitKind: "time_ge", exitValue: "1e9", next: "" });
        renderModeTable(modeBox);
      } }, "모드 추가"),
      el("span", { class: "hint" },
        "종방향은 고도·피치·강하율 중 하나만 — 셋 다 θ 명령으로 가므로 함께 켤 수 없습니다. ",
        'off면 고도축이 트림 자세를 유지합니다. 고도축에만 "path"를 적을 수 있고, 그러면 ',
        "웨이포인트의 세로 프로파일을 따라 납니다. 강하율은 상승이 + 라 강하는 음수입니다. ",
        '헤딩: 수치 | "path"(경로추종) | 빈=off. 속도는 수치 | 빈=off. ',
        // 경고는 next 사슬만 본다 — 그 이탈 조건이 실제로 성립하는지는 돌려 봐야
        // 안다(정적으로 판정 불가). 판정 못 하는 것을 정상으로 보이게 두지 않으려면
        // 화면이 그 한계를 말해야 한다: 사슬로 이어 두면 경고는 사라진다
        // 마크다운 ** 는 여기서 글자 그대로 나온다 — 강조는 노드로 (이전 실측)
        '"path" 모드는 사슬로 잇는 것만으로는 부족하고 ', el("b", {}, "들어가야"),
        " 씁니다 — 앞 모드의 이탈 조건이 실제로 성립해야 합니다. ",
        "위 경고는 next 연결만 보므로, 예컨대 ",
        "이탈이 time_ge 1e9인 모드 뒤에 붙이면 경고는 사라져도 그 모드는 끝내 실행되지 ",
        "않습니다.")),
  );
  // 축 선택·모드 추가·삭제도 "웨이포인트를 쓰는 모드"를 없앨 수 있다
  renderWpNotice();
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
        // 지도만 다시 그리면 두 화면이 서로 다른 미션을 말한다 (리뷰 실측).
        // 안내도 함께다: 좌표가 유효한지가 곧 "웨이포인트가 있는가"라, 빈 N에
        // 수치를 넣으면 그 순간 안 쓰이는 축이 생기고 지우면 사라진다. 이 두 칸만
        // sync()를 안 거쳐 안내가 남거나 안 뜨는 상태로 얼어 있었다 (리뷰 지적)
        el("td", {}, el("input", { value: r.n,
          onchange: (ev) => {
            r.n = ev.target.value; wpMap?.refresh(); redrawProfile(); renderWpNotice();
          } })),
        el("td", {}, el("input", { value: r.e,
          onchange: (ev) => {
            r.e = ev.target.value; wpMap?.refresh(); redrawProfile(); renderWpNotice();
          } })),
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
        // 새 행은 좌표 (0,0) = 원점. 지도 클릭 추가와 **같은 함수**로 빈 고도를
        // 전부 채운다(사용자 요청) — 두 곳에 따로 적으면 추가 경로마다 다른 고도가 붙는다
        wpRows.push({ n: "0", e: "0" });
        fillMissingAltitudes(wpRows, { acceptRadius: acceptRadiusOf() });
        sync();
      } }, "웨이포인트 추가"),
      el("span", { class: "hint" }, "지도에서 클릭 추가 · 드래그 이동 · 우클릭 삭제 가능")),
  );
  // 행이 하나 생기거나 사라질 때마다 "이 경로를 쓰는 모드가 있는가"를 다시 묻는다 —
  // 표를 다시 그리는 모든 경로(지도 클릭·드래그·추가·삭제·순서)가 여기를 지난다
  renderWpNotice();
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
          // 가로좌표 **와 고도**를 함께 넘긴다 — 종전엔 w[v.wpIdx]만 넘겨,
          // 고도 화면이 평면 정보만 그렸다 (사용자 제기). 색인 정본은 lib
          wps: wpMarks(waypoints, v.wpIdx),
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
  // 수치는 lib/playcursor.js가 정본 — 3D 월드 탭과 **같은 함수**를 쓴다. 두 화면이 각자
  // 적으면 같은 결과를 보면서 서로 다른 시각을 말하게 된다.
  const dt = dtSample(body.t);
  const playable = isPlayable(body.t);
  const playBtn = el("button", { disabled: !playable },
    playable ? "▶ 재생" : "▶ 재생 (샘플 부족)");
  const speedSel = el("select", { "aria-label": "재생 배속" },
    ...[1, 2, 5, 10, 20].map((x) =>
      el("option", { value: String(x), selected: x === 5 }, `${x}×`)));
  const atEnd = () => cursorAtEnd(Number(slider.value), body.t.length);

  // 진행은 프레임당 고정 샘플이 아니라 **경과 벽시계 시간**으로 센다 (그 사유는
  // lib/playcursor.js 독스트링 — 프레임당 샘플로 세면 1×가 1×가 아니게 된다).
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
      const next = indexAt(fromIdx, fromWall, performance.now(),
        Number(speedSel.value), dt, body.t.length);
      if (next !== Number(slider.value)) { slider.value = String(next); updateCursor(); }
      if (cursorAtEnd(next, body.t.length)) stopPlay(); // 끝에 닿으면 자동 정지
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
    // 이착륙 요약 — 단계가 없으면 **행 자체가 없다**(0으로 채우면 착륙하지 않은 런이
    // "접지 강하율 0 = 완벽한 착륙"으로 읽힌다). 판정 기준이 없는 사출 하중은
    // 값과 함께 "미판정"을 낸다 — 초록 배지를 주면 34 g가 통과한 것처럼 보인다
    ...landingSummary(body).map((r) => el("p", { class: "hint" },
      el("b", {}, `${r.label} `), r.value,
      r.note ? " — " : "", r.note ?? "",
      r.unjudged ? " " : "", r.unjudged ? flagBadge(null) : "",
      r.over ? " " : "", r.over ? flagBadge(false, "", r.overLabel ?? "활주로 초과") : "")),
    el("div", { class: "row" }, playBtn, speedSel, slider, readout),
    // 궤적 뷰 — 입체·평면·측면·정면 순. 배치는 .triview가 폭에 따라 1열/2열로
    // 고르며, 열 수를 4의 약수로만 두어 마지막 줄에 외톨이가 남지 않게 한다.
    // 시계열 위에 두어 커서 조작(바로 위 슬라이더)과 그 반응이 눈에 같이 들어오게 한다
    el("div", { style: "display:flex; flex-direction:column; gap:6px; margin-bottom:12px;" },
      el("div", { class: "hint" },
        "궤적 3D + 3면도 (NED) — N–E 평면만 등축(선회반경 판독용), 연직 평면과 3D는 ",
        "비등축이라 경사각을 눈으로 재면 안 됨. 주황 세로선은 웨이포인트의 수평좌표, ",
        // 이 캡션은 3D 패널까지 덮는다 — 3D는 고도가 없으면 선이 아니라 바닥 점을
        // 찍으므로 "선만 그립니다"는 그쪽에서 거짓이 된다 (리뷰 지적)
        "그 위의 점은 입력한 고도입니다 — 고도를 넣지 않은 목록에서는 3면도는 선만, ",
        "3D는 바닥 점만 그립니다"),
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
