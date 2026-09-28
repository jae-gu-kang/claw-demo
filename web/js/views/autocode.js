/** Autocode 탭 — 생성 코드가 화면이다 (06 §4).

이 탭에 온 사람의 주 질문은 하나다: **"지금 형상에서 무슨 코드가 실리나."**
그 답은 코드 본문이므로 코드가 화면이고, 나머지(검토·추적성·설명)는 패널에 넣어
눌렀을 때만 나온다 — 블록도 최상위·영향성과 같은 규약(views/stage.js).

**페이지는 밝고 코드판만 어둡다.** 처음엔 탭 전체에 다크 스킨을 입혔는데, 다른 탭과
나란히 보면 이 탭만 페이지째 뒤집혀 보인다(사용자 지적) — 어두워야 하는 것은 편집기이지
탭이 아니다. 블록도 하위 페이지의 코드 패널이 이미 같은 모습이다.

선택은 세 단이고 **전부 코드 위에 남는다**. 패널에 넣으면 "무엇을 보고 있는지"가
클릭 뒤로 숨어, 화면의 코드가 어느 형상의 것인지 알 수 없게 된다:

    종류   [형상코드] [탑재코드]
    ├ 형상코드 → 대상 [통합] [오토파일럿] [작동기] [항법] · 형식 [Python] [C 헤더]
    └ 탑재코드 → 보기 [통합] [모듈별]  → (모듈별이면) 역할별로 묶인 파일 탭

기본은 **탑재코드 · 통합**이다. 두 종류는 성격이 다르다 — 형상코드는 설계 형상의
코드 표현(파라미터)이고, 탑재코드는 FCC에 그대로 실릴 제어법칙 코드다.

코드 텍스트·검토 패널 조립은 views/codegen.js가 조각으로 내주고 여기는 선택과 스펙
조달, 그리고 그 조각을 어디에 놓을지만 정한다. 판단이 드는 부분(스펙 조립·병합·
역할 묶음)은 lib/에 있다.

쇼케이스 신호 `overview({compareWith?})`(lib/showcasecue.js) — 탑재코드를 이 탭의 경로 그대로 생성하고,
compareWith가 오면 그 기체의 탑재 C도 같은 라우트(POST /codegen/flight, profile 참조)로 받아 두 지문을
대조한다 — 「같은 C(구조 지문 같음), 다른 파라미터 이미지」가 코드판 **아래 캡션**으로 선다(그림 위 글
최소). 대조 기체는 그 문서 그대로다(이 화면의 작업본 편집은 지금 기체에만 실린다).
*/

import { api, errorText } from "../api.js";
import { clear, el } from "../dom.js";
import { BLOCKS, blockDesign, codegenTargets, paramSource } from "../lib/blocks.js";
import { compareCacheHit } from "../lib/codegen.js";
import { schemaFields } from "../lib/schemaform.js";
import { compareCaption, fingerprintLine } from "../lib/flightcode.js";
import { revealPanel } from "../lib/reveal.js";
import { failCue, reportCue, takeCue, unknownAction } from "../lib/showcasecue.js";
import { makeMetaSource, makeSpecBuilder } from "../lib/specs.js";
import { store } from "../store.js";
import { createCodePanel } from "./codegen.js";
import { selectedDocument } from "./profilepick.js";
import { createDrawers, tabStage, tabTop } from "./stage.js";

const ALL = "__all__";
const SHAPE = "shape";
const FLIGHT = "flight";

// 뷰 재생성마다 처음으로 되돌아가지 않도록 모듈 스코프 (views/gains.js fitCfg 관행)
const state = { kind: FLIGHT, target: ALL, merged: true, drawer: null };
const buildSpec = makeSpecBuilder(api);
// 두 기체 대조 — 대조 기체의 생성 응답 지문 {id, revision, structure_fingerprint, param_fingerprint, profile}.
// 지금 기체 쪽은 매 생성마다 다시 대조한다(작업본을 고치면 파라미터 지문이 바뀐다). 대조 기체 쪽은 id+리비전으로만
// 다시 쓴다(lib/codegen compareCacheHit — 저장 기체는 그사이 고쳐 새 리비전이 됐을 수 있다)
let compareOther = null;
// 처리 중인 신호 — 탑재 C 응답이 자리를 잡으면(onFlight) 한 번 보고하고 지운다
let pendingCue = null;
let captionHost = null; // 지금 화면의 캡션 자리 — 늦은 대조 응답이 옛 DOM에 쓰지 않게

let catalogCache = null; // /gains/catalog — SCAS 축 설계 kwargs의 원천
/** 실패해도 코드 패널은 뜬다 (SCAS만 스키마 기본값으로 떨어진다).
 *
 * **성공만 캐시한다.** 실패를 캐시하면 첫 요청 한 번이 실패한 뒤로 페이지를 새로
 * 고치기 전까지 영영 축 설계값 없이 돈다 — 무료 플랜의 15분 유휴 슬립·1분 콜드
 * 스타트에서 그 첫 요청이 실패하는 것은 드문 일이 아니다. 재시도 비용은 요청 하나다.
 */
async function gainsCatalog() {
  if (catalogCache === null) {
    try {
      catalogCache = await api.get("/gains/catalog");
    } catch {
      return null;  // 캐시하지 않는다 — 다음 진입에서 다시 시도한다
    }
  }
  return catalogCache || null;
}
const codegenMeta = makeMetaSource(api);

const targets = () => BLOCKS.filter((b) => b.detail.editable && b.detail.codegen);

/** 블록의 기체 설계값 — codegenTargets의 design(편집이 없을 때의 값이자 「대비 변경」의 기준).
 *  AP·SCAS는 카탈로그 설계 kwargs(lib/blocks blockDesign), 문서에 절이 있는 블록(작동기)은 선택 기체
 *  문서 값이다 — 블록도 폼(views/blocks loadSchema)과 같은 출처(lib/blocks paramSource). 종전에는 작동기가
 *  null이라 레지스트리 기본값을 이 기체 값인 양 싣고 그것과 비교했다(기체 고정 금지). 문서 절은 스키마가
 *  전 칸 명시를 요구하므로(profile/schema _registry_params) 채울 빈칸이 없다 — 주입 예약 키(omit)만 뺀다.
 *  문서를 못 받았거나 형식이 다르면 null(레지스트리 기본값 — 블록도가 그 사유를 말한다). */
function designOf(block, catalog, doc) {
  const d = blockDesign(block, catalog);
  if (d) return d;
  const src = paramSource(block.detail.schema, doc);
  if (src?.kind !== "document") return null;
  const omit = new Set(block.detail.omit ?? []);
  return Object.fromEntries(Object.entries(src.values).filter(([k]) => !omit.has(k)));
}

const KIND_NOTE = {
  [SHAPE]: "현재 설계 형상을 코드로 적은 것입니다 — 파라미터가 대상이고 로직은 "
    + "담기지 않습니다. 검토·산출물 작성용입니다.",
  [FLIGHT]: "FCC에 통합되어 그대로 실릴 제어법칙 코드입니다 — 구조·블록 로직·"
    + "파라미터가 전부 들어 있고, 구조 정본인 IR에서 엔진이 생성합니다. "
    + "같은 템플릿이면 기체와 무관하게 커밋 산출물 flight/gen/ 과 바이트 단위로 같고, 기체는 파라미터 이미지만 다릅니다.",
};

export function render() {
  const kindRow = el("div", { class: "row", style: "gap:8px" });
  const subRow = el("div", { class: "tab-actions" });
  const stageBox = el("div");   // 파일 탭 + 코드 표면 — 카드 밖 전면
  const reviewBox = el("div");  // 패널 ①
  const traceBox = el("div");   // 패널 ②
  const footBox = el("div");    // 패널 ③
  const errBox = el("div");
  const lead = el("p", {}, KIND_NOTE[state.kind]);
  // 두 기체 대조 캡션 — 코드판 아래(그림 위 글 최소). 대조가 없으면 비어 있다
  const captionBox = el("div");
  captionHost = captionBox;

  // hidden 콜백은 createDrawers 안에서 **즉시** 불린다 — 선언이 아래 있으면 TDZ다
  let panel = null;

  // 패널은 **한 번만** 만든다. 코드 형식을 바꿀 때마다 다시 만들면 열어 둔 패널이
  // 매번 닫히고, 사용자는 검토를 보려고 형식을 못 바꾸게 된다
  const drawers = createDrawers({
    id: "autocode-drawer",
    initial: state.drawer,
    onOpen: (k) => { state.drawer = k; },
    defs: [
      { key: "review", label: "검토", group: "이 코드가 맞나",
        title: "엔진 검증 · 기본값 대비 변경 · 한계 근접 지적",
        build: () => reviewBox },
      { key: "trace", label: "추적성", group: "이 코드가 맞나",
        title: "파라미터 → 코드 줄 대응 (산출물에 그대로 옮기는 표)",
        // 탑재 코드에는 파라미터→줄 대응이 없다 — 없는 표의 빈 패널을 열게 두지 않는다
        hidden: () => !panel?.hasTrace(),
        build: () => traceBox },
      { key: "about", label: "이 코드는 무엇인가", group: "설명",
        build: () => footBox },
    ],
  });

  const paint = () => {
    clear(lead).append(KIND_NOTE[state.kind]);
    renderKindRow(kindRow, repaint);
    renderSubRow(subRow, repaint);
    load();
  };
  const repaint = () => paint();

  const load = async () => {
    clear(errBox);
    clear(captionBox);
    clear(stageBox).append(el("p", { class: "hint" }, "생성 중…"));
    try {
      const shape = state.kind === SHAPE;
      // 탑재코드는 형상 전체가 대상이다 — 블록 하나만 골라 실을 수는 없다
      const all = !shape || state.target === ALL;
      const blocks = all ? targets() : targets().filter((b) => b.id === state.target);
      // SCAS는 축마다 한 줄로 편다. 편집이 없어도 카탈로그 설계 kwargs로 채운다 —
      // ScasAxis의 스키마 기본값은 0이라 그대로 내면 게인 없는 형상이 나오고, 자동조종의
      // 스키마 기본값은 구 합성 기체의 설계값이라 다른 기체에서는 옛 경로 게인이 나온다
      // 문서 조회 실패는 코드 패널을 막지 않는다 — 작동기만 레지스트리 기본값으로 떨어진다
      const [catalog, doc] = await Promise.all([gainsCatalog(), selectedDocument().catch(() => null)]);
      const specTargets = blocks.flatMap((b) =>
        codegenTargets(b, store.get(b.detail.injectKey), designOf(b, catalog, doc))
          .map((t) => ({ block: b, ...t })));
      const [built, meta] = await Promise.all([
        Promise.all(specTargets.map((t) =>
          buildSpec(t.block, t.values, schemaFields, t.cg, t.applied, t.baseline))),
        codegenMeta(),
      ]);
      panel = createCodePanel({
        specs: built.map((r) => r.spec),
        validation: built.map((r) => r.validation),
        // 게인 스케줄은 형상 전체의 것이라 대상이 통합일 때만 싣는다. 전부 끈 상태는
        // 빈 dict로 표현할 수 없어 별도 신호로 간다 (lib/gainsched.js storePayload)
        gainTables: all ? (store.get("gainTables") ?? null) : null,
        scheduleOff: all ? (store.get("gainScheduleOff") ?? false) : false,
        meta,
        langs: shape ? ["python", "c"] : ["flight"],
        flightMerged: state.merged,
        // 형식이 바뀌면 추적성 칩이 서거나 사라진다 — 배지·숨김을 다시 묻게 한다
        onPaint: () => drawers.refresh(),
        onFlight: (data, error) => flightSettled(captionBox, data, error),
      });
      // 형식 버튼·복사는 코드 **바로 위**다. 아래에 두면 코드 높이만큼 눈이 왕복한다
      clear(subRow).append(...subRowKids(repaint), el("span", { class: "grow" }), panel.bar);
      clear(stageBox).append(panel.tabs, panel.stage);
      clear(reviewBox).append(panel.review);
      clear(traceBox).append(panel.trace);
      clear(footBox).append(panel.foot);
      drawers.refresh();
    } catch (e) {
      panel = null;
      clear(stageBox);
      clear(errBox).append(el("div", { class: "error-box" }, errorText(e)));
      drawers.refresh();
      if (pendingCue) {
        failCue(pendingCue, `탑재 C를 조립하지 못했다 — ${errorText(e)}`);
        pendingCue = null;
      }
    }
  };

  // 쇼케이스 신호 — 한 번 읽고 지운다. 탑재코드 화면으로 돌려 두고 생성이 끝나면(onFlight) 보고한다
  const cue = takeCue("autocode");
  if (cue) {
    if (cue.action === "overview") {
      state.kind = FLIGHT;
      pendingCue = cue;
    } else {
      unknownAction(cue);
    }
  }
  paint();
  // **페이지는 밝다** (v0.54, 사용자 요청). 어두운 것은 코드판뿐이다 — 블록도 하위
  // 페이지의 코드 패널과 같은 모습이고, 다른 밝은 탭들과 나란히 봤을 때 이 탭만
  // 페이지째 뒤집히지 않는다. 편집기가 어두운 것은 VS Code 규약 그대로다
  return el("div", { class: "tab-page" },
    tabTop({
      title: "Autocode",
      lead,
      actions: kindRow,
      extra: errBox,
    }),
    subRow,
    tabStage(stageBox),
    captionBox,
    drawers.root,
  );
}

/** 탑재 C 응답이 자리를 잡았다 — 대조 캡션을 다시 그리고, 걸린 신호가 있으면 대조까지 마쳐 보고한다. */
async function flightSettled(captionBox, data, error) {
  paintCaption(captionBox, data);
  const cue = pendingCue;
  if (!cue) return;
  pendingCue = null;
  if (error || !data) {
    failCue(cue, `탑재 C 생성 실패 — ${error ?? "응답 없음"}`);
    return;
  }
  const other = cue.args?.compareWith;
  if (other) {
    try {
      // 지금 리비전 — 캐시가 그 리비전의 것일 때만 다시 쓴다. 못 읽으면 null(다시 받는다 — 생성이 404 등을 말한다)
      const head = await api.get(`/profiles/${encodeURIComponent(other)}`).catch(() => null);
      if (!compareCacheHit(compareOther, other, head?.revision ?? null)) {
        // 같은 라우트·같은 조립 — 대조 기체는 참조로(그 문서 그대로). 본문에 profile을 실으면 헤더 선택이
        // 덮지 않는다(lib/profile.js withProfile)
        const got = await api.post("/codegen/flight", { control_hz: 100, profile: { id: other } });
        // 리비전은 생성 응답(그 조립이 실제로 쓴 문서)의 것 — 조회와 생성 사이에 저장이 끼어도 지문과 짝이 맞다
        compareOther = { id: other, revision: got.profile?.revision ?? null,
          structure_fingerprint: got.structure_fingerprint,
          param_fingerprint: got.param_fingerprint, profile: got.profile };
      }
    } catch (e) {
      failCue(cue, `대조 기체 ${other}의 탑재 C를 받지 못했다 — ${errorText(e)}`);
      return;
    }
    paintCaption(captionHost, data);
    // 캡션은 코드판 아래라 첫 화면 밖이다(y≈828, e2e D4) — 신호가 낸 대조는 청중이 보게 끌어올린다(결과가 사는
    // 자리를 연다). 공용 lib/reveal: 떠난 화면(떨어진 노드)은 굴리지 않는다. 대조가 없으면 캡션이 비므로
    // 굴리지 않는다 — 그때 결과(코드판)는 이미 첫 화면이다
    revealPanel(captionHost);
  }
  const cmp = other ? compareCaption(data, compareOther) : null;
  reportCue(cue, {
    phase: "done",
    summary: cmp ? cmp.text : fingerprintLine(data),
    data: {
      structure_fp: data.structure_fingerprint ?? null,
      param_fp: data.param_fingerprint ?? null,
      other_id: other ?? null,
      other_structure_fp: compareOther && other ? compareOther.structure_fingerprint : null,
      other_param_fp: compareOther && other ? compareOther.param_fingerprint : null,
      other_revision: compareOther && other ? compareOther.revision ?? null : null,
      same_structure: cmp ? cmp.sameStructure : null,
    },
  });
}

/** 대조 캡션 — 대조 기체 응답이 있고 지금 탑재 C가 있을 때만. 매 생성마다 지금 지문으로 다시 낸다. */
function paintCaption(box, data) {
  if (!box) return;
  clear(box);
  if (!compareOther || !data || state.kind !== FLIGHT) return;
  const c = compareCaption(data, compareOther);
  // 대조 기체 쪽은 신호가 받은 그 리비전의 지문이다 — 그 뒤 그 기체를 고쳤을 수 있어 어느 리비전인지 밝힌다
  const rev = Number.isInteger(compareOther.revision) && !compareOther.profile?.is_example
    ? ` (대조 기체는 리비전 ${compareOther.revision} 기준)` : "";
  box.append(el("p", { class: "hint", style: "margin-top:8px" },
    c.sameStructure ? el("strong", {}, c.text) : c.text, rev));
}

const btn = (label, on, opts) => el("button", { class: on ? "primary" : "", ...opts }, label);

function renderKindRow(row, paint) {
  const pick = (k) => () => { state.kind = k; paint(); };
  clear(row).append(
    el("span", { class: "hint" }, "종류"),
    btn("형상코드", state.kind === SHAPE, {
      title: "설계 형상의 코드 표현 (파라미터)", onclick: pick(SHAPE),
    }),
    btn("탑재코드", state.kind === FLIGHT, {
      title: "FCC에 실릴 제어법칙 코드 (구조·로직·파라미터)", onclick: pick(FLIGHT),
    }),
  );
}

/** 종류에 딸린 2단 — 형상코드는 대상, 탑재코드는 보기 범위. */
function subRowKids(paint) {
  if (state.kind === SHAPE) {
    const pick = (id) => () => { state.target = id; paint(); };
    return [
      el("span", { class: "hint" }, "대상"),
      btn("통합 (형상 전체)", state.target === ALL, {
        title: "편집 블록 전부 + 게인 스케줄 테이블을 한 파일로", onclick: pick(ALL),
      }),
      ...targets().map((b) =>
        btn(b.title ?? b.id, state.target === b.id, {
          title: b.detail.desc ?? "", onclick: pick(b.id),
        })),
    ];
  }
  const pick = (m) => () => { state.merged = m; paint(); };
  return [
    el("span", { class: "hint" }, "보기"),
    btn("통합 (전체 이어보기)", state.merged, {
      title: "탑재되는 모든 파일을 읽는 순서대로 이어붙인 열람본", onclick: pick(true),
    }),
    btn("모듈별", !state.merged, {
      title: "역할·서브시스템 단위로 파일 하나씩", onclick: pick(false),
    }),
  ];
}

function renderSubRow(row, paint) {
  clear(row).append(...subRowKids(paint));
}
