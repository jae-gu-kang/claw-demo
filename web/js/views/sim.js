/** 시뮬레이션 뷰 (02 §8 7단계) — 미션 편집 → 폐루프 시뮬 → 재생 + 엔벨로프.

미션 스펙 변환은 lib/mission.js, 재생 수치는 lib/replay.js·lib/playcursor.js. 검증·수치는 전부
서버(엔진) 소관 — 구성 오류는 422 텍스트로 표시.
*/

import { api, errorText } from "../api.js";
import { clear, el, flagBadge, fmt } from "../dom.js";
import { COND_KINDS, LON_AXES, pathUsage } from "../lib/mission.js";
// 요청 조립·기본 미션·실행 조건 기본값은 lib가 정본 — 가이드 투어(views/tour.js)가
// **같은 조립**을 쓴다. 두 벌이면 투어가 돌린 미션과 이 표가 조용히 갈린다
import {
  applyActuatorSchema, appliedFrom, buildSimRequest, defaultModeRows, defaultWpRows,
  initialForm, RUNWAY_HDG,
} from "../lib/simrequest.js";
import { planeViews, wpMarks } from "../lib/plot.js";
import { atEnd as cursorAtEnd, dtSample, indexAt, isPlayable } from "../lib/playcursor.js";
import { dryRun, normalizeDraft } from "../lib/missiondraft.js";
import { flaggedNames, landingSummary, modeSpans, strideFor } from "../lib/replay.js";
import { GOHEUNG, touchdownWindowM } from "../lib/site.js";
import { fillMissingAltitudes, moveWaypoint, rowsToPoints } from "../lib/wpmap.js";
import { store } from "../store.js";
import { createTrack3d } from "./plot3d.js";
import { lineChartCanvas, profileCanvas, trackCanvas } from "./plots.js";
import { attachProgress, cancelledWithoutResult } from "./progress.js";
import { createDutyPanel, invalidate as dutyInvalidate } from "./duty.js";
import { createDrawers, tabStage, tabTop } from "./stage.js";
import { createProfileChart, createWpMap } from "./wpmap.js";

// 기본 미션(발사 → 상승 → 순항 → 접근 → 플레어 → 미끄럼 → 정지)과 기본 웨이포인트,
// 그 수치의 근거는 **lib/simrequest.js가 정본**이다 — 가이드 투어가 폼 없이 같은
// 미션을 조립해야 해서 옮겼다. 여기서는 표의 초기값으로 사본을 받아 쓴다(표 편집이
// 행을 제자리에서 고치므로 매번 새 사본이어야 한다).
let modeRows = defaultModeRows();
let wpRows = defaultWpRows();
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
// 탭을 떠났다 와도 열어 둔 패널은 그대로 (모듈 스코프 규약)
let openDrawer = null;
// 잡이 끝나면 결과가 사는 패널을 열어 준다 — 화면에 결과가 있는데 패널이 닫혀
// 있으면 "돌긴 돌았나"만 남고 무슨 일이 있었는지가 안 보인다 (영향성 runStatus 선례)
let simDrawers = null;
// LLM 미션 초안 — 잡·결과·입력 문구를 탭 재진입에도 유지 (runningJobId와 같은 규약).
// lastDraft는 normalizeDraft 산출(+model) — 적용 전 초안이 탭 이탈로 사라지지 않게
let draftJobId = null;
let draftIntent = "";
let lastDraft = null;

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
// 전면 무대 크기 — 지도는 **정사각이어야 한다**(N-E 등축). 프로파일은 거리축이
// 길어야 읽히므로 가로로 넓다. 좁은 화면에서는 canvas.plot의 max-width가 줄인다
const STAGE_MAP_PX = 520;
const STAGE_PROFILE_W = 640;

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

  // 가이드 투어 인계 (views/tour.js) — **한 번 읽고 지운다**(wpDraft와 같은 규약).
  // 투어가 이미 조립·제출한 미션을 이 탭이 같은 표·지도·진행바로 보여 준다:
  // 조립이 lib 한 벌이라(lib/simrequest.js) 투어가 돌린 것과 이 표가 갈리지 않는다.
  // jobId가 null이면 초안이 사전 판정에 막힌 것 — 표에만 앉히고 실행하지 않는다
  // (사유는 투어 카드가 말하고, 고쳐서 [시뮬 실행]하는 것은 여기서).
  const tourSim = store.get("tourSim");
  let tourApply = false;
  let tourTookOver = null; // 투어 인계가 밀어낸 이전 실행 — 화면이 그 사실을 말한다
  if (tourSim?.draft) {
    store.set("tourSim", null);
    lastDraft = tourSim.draft;
    tourApply = true;
    if (tourSim.jobId) {
      // 이 탭에 돌던 잡이 있으면 감시를 놓게 된다 — 이 탭의 [시뮬 실행]은 이중 제출을
      // 막고 사유를 내는데, 인계 경로가 그것을 조용히 지나치면 안 된다 (리뷰 지적)
      if (runningJobId && runningJobId !== tourSim.jobId) tourTookOver = runningJobId;
      runningJobId = tourSim.jobId;
      runningSnapshot = tourSim.snapshot ?? { waypoints: [], acceptRadius: 0 };
    }
  }
  const errBox = el("div");
  const progressBox = el("div");
  const replayBox = el("div");
  const modeBox = el("div");
  const wpBox = el("div");

  // 블록도 탭 '시뮬에 적용' 값 — 작동기는 필드에 프리필(최종 편집권은 여기),
  // 항법은 제출 시 병합 (시드만 이 탭이 우선, 나머지 미지정분은 엔진 기본값)
  const actApplied = store.get("actuatorParams");
  // 칸의 초기값은 **lib가 정본**이다(lib/simrequest.js DEFAULT_FORM — 각 값의 근거도
  // 거기 있다). 가이드 투어가 폼 없이 조립할 때 쓰는 값과 같아야 "투어가 돌린 미션"과
  // "이 표가 말하는 미션"이 갈리지 않는다. 작동기는 블록도 적용값이 있으면 그것이
  // 앉는다(최종 편집권은 여기 폼).
  const init = initialForm(actApplied);
  const f = {
    mach: numInput(init.mach),
    alt: numInput(init.alt), // 활주로 표고 — 기준면 감시도 이 값이 된다
    fuel: numInput(init.fuel),
    groundOn: el("input", { type: "checkbox", checked: init.groundOn }),
    rwHeading: numInput(init.rwHeading),
    rwLength: numInput(init.rwLength),
    launchOn: el("input", { type: "checkbox", checked: init.launchOn }),
    railLen: numInput(init.railLen),
    railAngle: numInput(init.railAngle),
    railExit: numInput(init.railExit),
    rtkOn: el("input", { type: "checkbox", checked: init.rtkOn }),
    originOn: el("input", { type: "checkbox", checked: init.originOn }),
    originLat: numInput(init.originLat),
    originLon: numInput(init.originLon),
    tEnd: numInput(init.tEnd),
    accept: numInput(init.accept),
    navOn: el("input", { type: "checkbox", checked: init.navOn }),
    seed: numInput(init.seed),
    actOn: el("input", { type: "checkbox", checked: init.actOn }),
    wn: numInput(init.wn),
    zeta: numInput(init.zeta),
    rate: numInput(init.rate),
    fuelFlow: numInput(init.fuelFlow),
    useGains: el("input", { type: "checkbox", checked: init.useGains }),
    useAp: el("input", { type: "checkbox", checked: init.useAp }),
    useScas: el("input", { type: "checkbox", checked: init.useScas }),
    fp: el("input", { value: init.fp, style: FILL_ST }),
  };

  // 폼 DOM → 값 객체 (lib DEFAULT_FORM과 같은 키) — 조립은 lib가 한다.
  // **제출 순간에** 읽는다: 폼을 연 시점이 아니라.
  const readForm = () => Object.fromEntries(Object.entries(f).map(
    ([k, node]) => [k, node.type === "checkbox" ? node.checked : node.value]));

  // 작동기 폴백(lib ACT_FALLBACK)은 엔진 기본값의 사본이라 조용히 어긋날 수 있다 —
  // 스키마가 도착하면 **손대지 않은 칸만** 갱신한다(판정은 lib, 여기는 DOM 대입).
  // 실패는 무시: 폴백으로 동작한다 (항법 기본값 7개가 어긋난 채 돌던 전례 — 01 v0.19)
  if (!actApplied) {
    api.get("/registry/actuator/SecondOrderActuator/schema").then((s) => {
      const next = applyActuatorSchema(
        { wn: f.wn.value, zeta: f.zeta.value, rate: f.rate.value }, s);
      for (const key of ["wn", "zeta", "rate"]) f[key].value = next[key];
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
    width: STAGE_PROFILE_W, height: STAGE_MAP_PX,
  });
  // 지도와 같은 폭 규약 — 두 면이 나란히 서고 좁아지면 함께 접힌다
  const profileBox = el("div", { style: `flex: 0 1 ${STAGE_PROFILE_W + 16}px; min-width: 240px` },
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
    width: STAGE_MAP_PX, height: STAGE_MAP_PX,
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
        dutyInvalidate(); // 새 런이다 — 타면 패널을 다음에 열 때 다시 집계한다
        simDrawers?.open("replay"); // 결과를 찾아 헤매게 하지 않는다
        syncHandoff(); // 넘길 런이 생겼다 — 다음 단계 버튼이 살아난다
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
      // 조립은 **lib 한 벌**이다 — 가이드 투어(views/tour.js)가 같은 함수로 같은
      // 요청을 만든다. 표가 틀리면 여기서 던진다(검증 정본 buildModes·buildWaypoints).
      // 적용값(store 5키)은 **제출 순간에** 읽는다.
      const { req, snapshot, missing } = buildSimRequest(
        readForm(), modeRows, wpRows, appliedFrom((k) => store.get(k)));
      if (missing.length) {
        // 편집본 체크됐는데 적용본이 없으면 기본값 실행을 조용히 하지 않고 알림 (리뷰 Nit3)
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

  // ── 미션 초안 (LLM) — 자연어 → 표 드래프트 (서버 routes/llm.py) ────────────
  // 판단(정규화·사전 판정)은 lib/missiondraft.js. 적용이 이 클로저 안에 있는
  // 이유: 표·지도·프로파일 재그리기(wpMap·profileChart·f)가 전부 render() 로컬이라
  // 모듈 스코프에서는 닿지 못한다. 초안은 표에만 앉고 실행·검증 경로는 기존
  // 그대로다 — [시뮬 실행]과 서버 422가 정본 (wpDraft를 안 쓰는 이유: 그 경로는
  // 탭 진입 시 1회 소비라 탭 안 즉시 반영에 맞지 않는다).
  const draftStatusLine = el("p", { class: "hint", style: "margin:0 0 8px" });
  const draftIntentInput = el("textarea", {
    rows: 3,
    style: "width:100%; box-sizing:border-box; resize:vertical",
    placeholder: "예: 발사 후 북쪽으로 5 km 나가 웨이포인트 둘을 돌고 되돌아와 활주로에 착륙",
  });
  draftIntentInput.value = draftIntent;
  draftIntentInput.oninput = () => { draftIntent = draftIntentInput.value; };
  const draftRunBtn = el("button", { class: "primary" }, "초안 생성");
  const draftProgressBox = el("div");
  const draftErrBox = el("div");
  const draftResultBox = el("div");
  const draftAppliedNote = el("span", { class: "hint" });
  let llmStatus = null; // {available, model, reason} — 패널을 처음 열 때 조회

  const showDraftErr = (e) =>
    clear(draftErrBox).append(el("div", { class: "error-box" }, errorText(e)));

  const syncDraftUi = () => {
    const avail = !!llmStatus?.available;
    draftIntentInput.disabled = !avail || !!draftJobId;
    draftRunBtn.disabled = !avail || !!draftJobId;
    clear(draftRunBtn).append(draftJobId ? "생성 중…" : "초안 생성");
    clear(draftStatusLine);
    if (llmStatus == null) draftStatusLine.append("서버 상태 확인 중…");
    // 키 없는 배포 — 숨기지 않고 서버가 준 사유 문장을 그대로 낸다 (조용한 비표시 금지)
    else if (!avail) draftStatusLine.append(llmStatus.reason ?? "사용할 수 없습니다.");
    else {
      draftStatusLine.append(
        `모델 ${llmStatus.model} — 서버가 대신 호출한다 (브라우저는 밖으로 나가지 않는다).`);
    }
  };

  const loadLlmStatus = async () => {
    try {
      llmStatus = await api.get("/llm/status");
    } catch (e) {
      llmStatus = { available: false, reason: `상태 조회 실패 — ${errorText(e)}` };
    }
    syncDraftUi();
  };

  const applyDraft = () => {
    const d = lastDraft;
    if (!d || !d.modeRows.length) return; // 버튼 disabled와 같은 조건 — 방어만
    modeRows = d.modeRows.map((r) => ({ ...r }));
    wpRows = d.wpRows.map((r) => ({ ...r }));
    const rc = d.runConditions;
    for (const [k, input] of [["mach", f.mach], ["alt", f.alt], ["fuel", f.fuel],
      ["tEnd", f.tEnd], ["accept", f.accept]]) {
      if (rc[k] != null) input.value = rc[k];
    }
    if (typeof rc.groundOn === "boolean") f.groundOn.checked = rc.groundOn;
    if (typeof rc.launchOn === "boolean") f.launchOn.checked = rc.launchOn;
    wpMapView.view = null; // 새 목록에 맞춰 지도 시야 재fit (wpDraft 소비부와 동일)
    renderModeTable(modeBox);
    renderWpTable(wpBox, wpMap);
    // f.accept·f.alt의 프로그램 대입은 input 리스너를 깨우지 않는다 — 지도의
    // 도달반경 원과 프로파일 출발점을 여기서 직접 갱신한다
    wpMap.refresh();
    drawProfile();
    drawWpNotice();
    drawers.refresh(); // 웨이포인트·모드 칩의 개수 배지
    clear(draftAppliedNote).append(
      "적용됨 — 웨이포인트 표·비행 모드 표에서 다듬은 뒤 [시뮬 실행].");
  };

  const paintDraftResult = () => {
    clear(draftResultBox);
    const d = lastDraft;
    if (!d) return;
    // 정규화가 고친 것 + 검증 정본이 거부할 것 — 적용 전에 한자리에서 보인다
    const problems = [...d.issues, ...dryRun(d)];
    draftResultBox.append(
      el("h3", { style: "margin:14px 0 4px; font-size:14px" }, "초안 미리보기",
        d.model ? el("span", { class: "hint", style: "font-weight:400" }, ` — ${d.model}`) : null),
      el("p", { style: "margin:0 0 4px" }, d.summary || "(요약 없음)"),
      el("p", { class: "hint", style: "margin:0 0 4px" },
        `모드 ${d.modeRows.length}행 (${d.modeRows.map((r) => r.name).join(" → ") || "—"})`
        + ` · 웨이포인트 ${d.wpRows.length}개`
        + (Object.keys(d.runConditions).length
          ? ` · 실행 조건 ${Object.keys(d.runConditions).length}칸` : "")),
      d.assumptions.length
        ? el("p", { class: "hint", style: "margin:0 0 4px" },
            "모델이 채운 가정 — ", d.assumptions.join(" · "))
        : null,
      d.warnings.length
        ? el("p", { class: "hint", style: "margin:0 0 4px" },
            "⚠ 모델 주의 — ", d.warnings.join(" · "))
        : null,
      problems.length
        ? el("div", { class: "error-box" },
            el("div", {}, "적용 전 확인 — 일부가 고쳐졌거나 그대로는 실행이 거부된다:"),
            ...problems.map((m) => el("div", {}, `· ${m}`)))
        : null,
      el("div", { class: "row", style: "margin-top:8px; gap:8px; align-items:center" },
        el("button", {
          class: "primary",
          onclick: applyDraft,
          disabled: !d.modeRows.length,
          title: d.modeRows.length
            ? "현재 모드·웨이포인트 표를 이 초안으로 통째로 바꾼다"
            : "모드 행이 없어 적용할 것이 없다",
        }, "표에 적용"),
        draftAppliedNote),
    );
  };

  const watchDraft = () => attachProgress(draftProgressBox, draftJobId, {
    onDone: async (job) => {
      draftJobId = null;
      syncDraftUi();
      try {
        if (job.status === "error") throw new Error(job.error);
        if (cancelledWithoutResult(job)) {
          showDraftErr(new Error("취소됨 — 저장된 초안 없음"));
          return;
        }
        const body = await api.get(`/results/${job.result_id}`);
        lastDraft = normalizeDraft(body.draft);
        lastDraft.model = body.model;
        clear(draftAppliedNote); // 새 초안 — 옛 "적용됨"이 남으면 이 초안을 말하는 것처럼 읽힌다
        paintDraftResult();
      } catch (e) {
        showDraftErr(e);
      }
    },
    onError: (e) => {
      draftJobId = null;
      syncDraftUi();
      showDraftErr(e);
    },
  });

  // await 앞의 동기 플래그 — draftJobId만 보면 POST 왕복 사이의 더블클릭이
  // 유료 잡을 두 번 만든다 (결과 탭 브리핑 리뷰가 잡은 같은 모양의 창)
  let draftSubmitting = false;
  const runDraft = async () => {
    if (draftJobId || draftSubmitting) return; // 버튼이 이미 꺼져 있다 — 방어만
    const intent = draftIntentInput.value.trim();
    if (!intent) {
      showDraftErr(new Error("의도 문장을 입력하십시오 — 무엇을 비행할지 한두 문장이면 된다."));
      return;
    }
    draftSubmitting = true;
    try {
      clear(draftErrBox);
      const submitted = await api.post("/llm/mission-draft", { intent });
      draftJobId = submitted.id;
      syncDraftUi();
      watchDraft();
    } catch (e) {
      showDraftErr(e);
    } finally {
      draftSubmitting = false;
    }
  };
  draftRunBtn.onclick = runDraft;

  // ── 실행 조건 — 여덟 묶음을 넷으로 다시 묶는다 ────────────────────────────
  // 종전에는 여덟 개가 한 카드 안에 격자로 늘어서 있었다. 그 배치의 문제는 개수가
  // 아니라 **위계가 없다**는 것이다: 매 실행마다 만지는 칸(시작점·t_end)과 한 번
  // 정하면 안 건드리는 칸(측지 원점·계보)이 같은 크기로 나란히 서 있었다.
  // 여기서는 "얼마나 자주 만지나"로 묶어 패널에 넣고, 실행 버튼만 전면에 남긴다.
  const optGroup = (title, toggle, fields, hint) =>
    el("div", { class: "opt-group", style: GROUP_ST },
      toggle ? groupTitle(title, toggle) : el("div", { class: "g-title" }, title),
      el("div", { class: "row-inner", style: INNER_ST }, ...fields),
      hint ? el("p", { class: "hint", style: HINT_ST }, ...hint) : null);

  const startGroup = () => optGroup("시작 트림점 · 시간", null, [
    field("마하", f.mach), field("고도 [m]", f.alt),
    field("연료 [kg]", f.fuel), field("t_end [s]", f.tEnd),
  ], [
    // t_end가 완주 시간과 묶여 있다는 사실이 소스에만 있으면 편집이 조용한
    // 미완주로 끝난다 — 짧으면 서기 전에 끊긴다
    "활주로를 켜면 발사대·활주로 위 정지에서 출발합니다 — 그때 마하는 0이고 ",
    "고도는 비행 고도가 아니라 활주로 표고입니다(지상 평형해). 끄면 종전처럼 ",
    "수평비행 트림에서 출발하고 마하 > 0이 필요합니다. ",
    "t_end는 정지까지 덮어야 합니다 — 기본 미션은 100 s 안팎에 서므로 ",
    "200 s면 여유가 남습니다. 실제 접지·정지 시각은 실행 후 착륙 요약에 나옵니다.",
  ]);

  const groundGroups = () => [
    optGroup("활주로 · 지면", f.groundOn,
      [field("방위 [rad]", f.rwHeading), field("길이 [m]", f.rwLength)], [
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
        "활주로에 내렸는지는 판정하지 않습니다.",
      ]),
    optGroup("발사 레일", f.launchOn,
      [field("길이 [m]", f.railLen), field("앙각 [rad]", f.railAngle),
       field("이탈속도 [m/s]", f.railExit)], [
        "레일 구간은 힘이 아니라 구속이라, 자세가 고정된 등가속 운동입니다 ",
        "— 해석해로 정확히 적분하므로 스텝 수와 무관합니다. ",
        "이탈속도 81.5 m/s는 트림 실속속도 70.9의 1.15배이고, 레일 10 m에서 ",
        "그 속도는 33.9 g를 요구합니다 — 종방향 발사하중 한계가 아직 없어 ",
        "(구조 한계표의 6.0은 Nz입니다) 결과에 '미판정'으로 표시됩니다.",
      ]),
    optGroup("측지 원점", f.originOn,
      [field("위도 [deg]", f.originLat), field("경도 [deg]", f.originLon)], [
        "NED 원점 (0,0)이 지구상 어디인지 적습니다. 엔진은 이 값을 보지 않고 ",
        "결과에만 실립니다 — 가상환경이 지형을 얹으려면 지형 팩과 이 원점이 같아야 ",
        "합니다. 기본값은 고흥 시험장 활주로 ",
        el("strong", {}, "남단 임계"),
        "를 항공영상에서 측정한 값입니다(34.601303 / 127.212067). 측정 방법과 ",
        "공표 제원 대조는 data/geo/goheung-runway.json에 있습니다.",
      ]),
  ];

  const sensorGroups = () => [
    optGroup("항법 오차 모델", f.navOn, [
      field("시드", f.seed),
      el("label", { class: "chk" }, f.rtkOn, " RTK 고정해"),
    ], [
      store.get("navParams")
        ? "블록도 적용값 사용 중 (시드만 여기서 우선). "
        : "미지정 항목은 엔진 기본값 — 편집은 블록도 탭 항법 블록. ",
      "RTK는 접지를 부드럽게 하지 않습니다 — 접지 지점을 반복 가능하게 합니다. ",
      `활주로 ${GOHEUNG.runwayLengthM} m라도 미끄럼 ${GOHEUNG.rolloutM} m는 `,
      `굴러가므로, 활주로 안에 서려면 ${touchdownWindowM()} m 안에 접지해야 `,
      "합니다 — 산포를 활주로 전장과 견주면 안 됩니다. ",
      // **수치를 옮겨 적지 않는다.** 산포는 항법 등급·접근 프로파일·게인
      // 스케줄의 함수라 여기 적으면 낡는데, 웹은 엔진을 읽지 않고 엔진은
      // 여기를 읽지 않아 **낡아도 아무것도 빨개지지 않는다**. UI 결정(RTK 토글)에
      // 필요한 것은 정밀한 수가 아니라 **순서**이고, 그것은 재측정을 견딘다
      "기본 항법의 접지 산포는 그 창을 넘고 RTK는 그 안에 듭니다 — ",
      "현재 수치는 엔진 test_landing이 5시드로 잽니다. ",
      "fix 유지가 전제입니다 — 보정 링크가 끊겨 강등되는 상황은 미모델입니다.",
    ]),
    optGroup("작동기 (2차계)", f.actOn,
      [field("wn [rad/s]", f.wn), field("ζ", f.zeta), field("rate [rad/s]", f.rate)],
      [actApplied
        ? "블록도 적용값 프리필됨 — 여기 값이 최종"
        : "블록도 탭에서 '시뮬에 적용' 시 프리필",
       " · 작동기 rate ≥ 10 rad/s 요구 [도출 사양] (01 v0.13)"]),
  ];

  const guideGroups = () => [
    optGroup("유도 · 연료 · 게인", null, [
      field("도달반경 [m]", f.accept), field("연료유량 [kg/s]", f.fuelFlow),
      checkField(f.useGains, "편집 게인"), checkField(f.useAp, "편집 AP"),
      checkField(f.useScas, "편집 SCAS"),
    ], [
      // 반경이 너무 작으면 경로가 안 끝나는데, 그때 화면에 뜨는 것은 오류가
      // 아니라 "순항에서 멈춘 모드 체인"뿐이라 성공처럼 읽힌다.
      // **선회 반경을 문턱으로 적지 않는다** — 바로 다음 문장의 100 m가 940 m보다
      // 작으면서 완주하므로 자기 예시가 반증한다. 선회 반경은 왜 임의로 작은 원을
      // 못 잡는지를 설명할 뿐 문턱이 아니고, 실제 문턱은 유도가 내는 접근 거리이며
      // 그것은 상수가 아니라 웨이포인트 기하 × 기체 선회 성능의 함수다
      "다음 웨이포인트로 넘어가는 통과 판정 반경입니다 — ",
      el("b", {}, "너무 작으면 경로가 끝나지 않습니다"),
      ". 데모 기체는 순항 88 m/s·뱅크 한계 0.7 rad에서 선회 반경이 940 m라 ",
      "임의로 작은 원은 못 잡습니다 — 기본 미션 실측상 첫 접근 최근접이 13 m라 ",
      "20 m는 완주하지만, 13 m로 줄이면 14 m로 스친 뒤 바퀴마다 되레 멀어져",
      "(14 → 69 → 81 m) 끝내 통과하지 못합니다. 그 경계는 웨이포인트 기하마다 ",
      "다릅니다 — 다른 기하에서는 20 m도 같은 식으로 발산했습니다. ",
      "경로가 안 끝나면(모드 체인이 순항에서 멈추면) 이 값을 먼저 의심하십시오. ",
      "편집 게인은 게인 탭, 편집 AP는 블록도 탭 오토파일럿 블록에서 '시뮬에 적용' 후 사용.",
    ]),
    optGroup("계보", null, [wideField("지문", f.fp)], null),
  ];

  const fieldGrid = (...groups) => el("div", { class: "field-grid" }, ...groups);

  // ── 패널 ─────────────────────────────────────────────────────────────────
  const dutyPanel = createDutyPanel();
  const drawers = createDrawers({
    id: "sim-drawer",
    initial: openDrawer,
    onOpen: (k) => { openDrawer = k; },
    defs: [
      { key: "wp", label: "웨이포인트 표", group: "미션",
        title: "지도·프로파일과 같은 목록 — 숫자로 정확히 찍을 때",
        count: () => wpRows.length,
        build: () => [
          el("h2", {}, "웨이포인트 (N, E, 고도) [m]"),
          wpDraftNote ? el("p", { class: "hint" }, wpDraftNote) : null,
          wpNotice,
          wpBox,
        ] },
      { key: "modes", label: "비행 모드 표", group: "미션",
        title: "선언적 모드 테이블 — 무엇을 잡고, 언제 다음 모드로 넘어가나",
        count: () => modeRows.length,
        build: () => [
          el("h2", {}, "미션 정의 (선언적 모드 테이블 — 01 §3.1)"),
          el("p", { class: "hint", style: "margin:0 0 10px" },
            "종방향 축은 모드마다 하나다 — 피치(자세 구간)·강하율(내려가는 속도를 잡는 "
            + "구간)·고도(순항) 중 하나. 헤딩에 \"path\"를 적은 모드만 웨이포인트를 따른다."),
          modeBox,
        ] },
      // 초안은 「미션」 그룹 — wp·modes와 연속 배치여야 그룹 라벨이 한 번만 선다
      // (stage.js startsGroup이 직전 def와 비교). 키가 없어도 칩은 숨기지 않는다 —
      // 열면 서버가 준 사유 문장이 뜬다 (기능 부재와 키 부재를 화면이 구분해 말한다)
      { key: "draft", label: "미션 초안 (AI)", group: "미션",
        title: "자연어로 미션을 만들어 표에 채운다 — 서버 경유 LLM 호출, 실행은 사람이 한다",
        build: () => {
          // 이 render 안에서 한 번 — 탭 재진입이면 다시 조회한다 (서버
          // 재기동·키 변경을 따라가는 부수 효과라 캐시로 굳히지 않는다)
          if (llmStatus == null) loadLlmStatus();
          return [
            el("h2", {}, "미션 초안 — 자연어로"),
            draftStatusLine,
            el("p", { class: "hint", style: "margin:0 0 8px" },
              "생성된 초안은 검토 후 [표에 적용]을 눌러야 표에 들어가고, 적용은 현재 "
              + "모드·웨이포인트 표를 통째로 바꾼다. 비행 값의 검증은 기존 그대로다 — "
              + "표의 검증과 실행 시점 서버 판정(422)이 정본이고 초안은 드래프트일 뿐이다."),
            draftIntentInput,
            el("div", { class: "row", style: "margin-top:8px; gap:8px" }, draftRunBtn),
            draftProgressBox,
            draftErrBox,
            draftResultBox,
          ];
        } },
      { key: "start", label: "시작·시간", group: "실행 조건",
        title: "매 실행마다 만지는 칸 — 시작 트림점과 t_end",
        build: () => fieldGrid(startGroup()) },
      { key: "ground", label: "활주로·발사·측지", group: "실행 조건",
        title: "지면이 있나, 어디서 뜨나, NED 원점이 지구상 어디인가",
        build: () => fieldGrid(...groundGroups()) },
      { key: "sensors", label: "항법·작동기", group: "실행 조건",
        title: "무엇으로 재고 무엇으로 움직이나",
        build: () => fieldGrid(...sensorGroups()) },
      { key: "guide", label: "유도·연료·게인·계보", group: "실행 조건",
        title: "도달반경·연료유량·편집값 주입·지문",
        build: () => fieldGrid(...guideGroups()) },
      // 타면 사용은 **이 층이 맞다** — 설계 단계가 아니라 시뮬 런 하나를 다시 읽는
      // 한 가지 방법이라 재생·엔벨로프 감시와 같은 줄이다. 최상위 탭이던 시절에는
      // 시뮬을 돌린 뒤 탭을 옮겨 같은 결과를 다시 골라야 했고, 그 선택이 방금 돌린
      // 런과 어긋날 수 있었다 (v0.54, 사용자 지적 "레벨이 맞는 것 같다")
      { key: "duty", label: "타면 사용", group: "결과",
        title: "조종면을 어느 타각에 얼마나 오래 썼나 — 포화·타율 반전·작동기 능력",
        // 패널이 열릴 때 집계한다 — 한 번도 안 여는 사람에게 20000표본 왕복을 물리지 않는다
        build: () => { dutyPanel.ensure(); return dutyPanel.root; } },
      { key: "replay", label: "재생 + 엔벨로프 감시", group: "결과",
        title: "시계열·3면도·3D 궤적·모드 밴드·착륙 요약",
        count: () => (lastReplay ? 1 : null),
        build: () => [replayBox, lastReplay ? null : el("p", { class: "hint" },
          "아직 결과가 없습니다 — 위 [시뮬 실행]을 누르면 끝난 뒤 이 패널이 열립니다.")] },
    ],
  });
  simDrawers = drawers;

  // ── 인계 — 이 런을 다음 단계로 넘긴다 (v0.66) ─────────────────────────────
  // 상단 탭이 자동 설계 → **시뮬레이션 → 가상환경 → 영향성**이 된 이상, 그 순서는
  // 화면에서 넘어갈 수단을 함께 줘야 한다. 순서만 바꾸고 배선이 없으면 "돌려서
  // 확인은 했는데 판정은 딴 런"이 되고, 그때 탭 줄은 하지 않는 일을 말하게 된다.
  //
  // 넘기는 것은 **런 하나**고 그 지목은 store `simResult` 하나로 통일돼 있다 —
  // 가상환경이 목록에서 다른 런을 고르면 그쪽도 같은 키를 갱신하므로
  // (web/world WorldTab.tsx), 영향성은 "마지막으로 본 런"을 이어받는다.
  // 영향성행만 별도 키(`influenceHandoff`)를 더 싣는다: 그 탭은 넘어온 런을
  // 칸에 채우는 데 그치지 않고 **패널을 열어 보여 줘야** 하는데, 그 열림은 명시
  // 인계일 때만 옳다(그냥 탭을 누른 사람의 화면을 바꾸면 안 된다). 받는 쪽이
  // 한 번 읽고 지운다 — 가상환경 → 시뮬 `wpDraft`와 같은 규약(이 파일 위쪽).
  const handoffBtns = [
    { label: "가상환경에서 보기 →", title: "이 런의 궤적을 3D 지형 위에서 확인한다",
      go: () => { location.hash = "#world"; } },
    { label: "영향성에서 진단 →",
      title: "이 런의 결함을 설계변수에 귀속한다 (영향성 「감도 (보조 진단)」 수동 진단)",
      go: (id) => {
        store.set("influenceHandoff", { resultId: id, from: "sim" });
        location.hash = "#influence";
      } },
  ].map((d) => {
    const btn = el("button", {
      title: d.title,
      onclick: () => {
        const id = store.get("simResult")?.id;
        if (!id) return; // disabled와 같은 조건 — 방어만, 사유는 title이 낸다
        d.go(id);
      },
    }, d.label);
    btn.dataset.baseTitle = d.title;
    return btn;
  });
  // 넘길 런이 없으면 **끈다** — 눌리는데 아무 일도 안 일어나는 버튼은 고장으로 읽힌다.
  // 끈 이유는 title로 낸다(조용한 비활성 금지 — 이 탭의 이중 제출 안내와 같은 규약)
  function syncHandoff() {
    const id = store.get("simResult")?.id;
    for (const btn of handoffBtns) {
      btn.disabled = !id;
      btn.title = id ? btn.dataset.baseTitle
        : "넘길 런이 없습니다 — 먼저 [시뮬 실행]으로 하나 만듭니다";
    }
  }

  const root = el("div", { class: "tab-page" },
    tabTop({
      title: "시뮬레이션",
      lead: "웨이포인트를 지도(수평면)와 프로파일(세로면) 두 면에서 편집하고, "
        + "그대로 폐루프로 날린다. 실행 조건과 결과(재생·타면 사용)는 아래 패널에 있다. "
        + "여기서 나온 런 하나가 가상환경(3D 확인)과 영향성(귀속 진단)으로 그대로 넘어간다.",
      actions: [
        el("button", { class: "primary", onclick: run }, "시뮬 실행"),
        el("button", {
          onclick: () => { drawers.open("replay"); },
          title: "마지막 실행 결과 패널을 연다",
        }, "결과 보기"),
        ...handoffBtns,
      ],
      extra: [progressBox, errBox],
    }),
    // 지도와 프로파일 — 카드 밖, 페이지 위에 그대로. 둘은 **한 벌**이다:
    // 같은 웨이포인트를 수평면·세로면으로 나눠 본 것이라 떨어뜨리면 뜻이 반쪽이 된다
    tabStage(el("div", { class: "stage-pair" }, wpMap.root, profileBox)),
    drawers.root,
  );

  renderModeTable(modeBox);
  renderWpTable(wpBox, wpMap);
  drawProfile();
  drawWpNotice();
  if (lastReplay) renderReplay(replayBox);
  if (runningJobId) watch(); // 실행 중 재진입 — 진행 UI 재부착 (리뷰 S4)
  paintDraftResult(); // 재진입 — 적용 전 초안이 남아 있으면 미리보기 복원
  // 투어가 넘긴 미션을 표·지도·폼에 앉힌다 — 위에서 runningJobId도 이어받았으므로
  // watch() 재부착이 그 잡의 진행바를 그대로 붙인다(같은 런을 두 화면이 말한다)
  if (tourApply) applyDraft();
  if (tourTookOver) {
    // 조용히 놓지 않는다 — 그 잡은 서버에서 계속 돌지만 이 화면은 더 이상 안 본다
    errBox.append(el("div", { class: "error-box" },
      `이전 실행(${tourTookOver})의 진행 표시를 놓았습니다 — 투어가 건 런으로 바꿉니다. `
      + "그 결과는 끝나면 결과 탭에 남습니다."));
  }
  if (draftJobId) watchDraft(); // 초안 생성 중 재진입 — 같은 재부착 규약
  syncDraftUi();
  syncHandoff(); // 재진입 — 이전 런이 남아 있으면 인계 버튼이 켜진 채로 선다
  drawers.refresh();
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
