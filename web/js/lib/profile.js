/** 기체 선택 — 헤더에서 고른 기체를 계산 요청에 싣는 규칙 (02 §5.6 · 06 §8).

선택은 브라우저 localStorage에 둔다 — 새로고침·탭 전환을 넘어 유지되고, 서버·다른 사용자와는
무관하다. 계산 요청마다 `profile: {id, variant?}`를 싣는다(GET은 `profile_id`·`profile_variant`
쿼리). **리비전은 싣지 않는다** — 기체를 고치면 다음 계산부터 최신 리비전이 쓰이고, 어느 리비전으로
계산했는지는 결과의 `profile` 블록이 말한다. 고르지 않았으면 아무것도 싣지 않는다 — 서버가 예제
기체로 계산하고 `source: "default-example"`로 그 사실을 말한다.

**어느 요청이 기체를 받는가는 여기 한 곳이 정한다**(COMPUTE_POST·COMPUTE_GET). 서버에 라우트가
생기면 `profile.test.js`가 서버 라우트 전부를 이 목록 또는 NOT_AIRCRAFT(사유 포함)로 분류하라고
빨개진다 — 새 계산 라우트가 조용히 예제 기체로 계산하는 것을 막는다.
*/

export const EXAMPLE_ID = "example-delta";
export const STORAGE_KEY = "claw.profile";

const ID_RE = /^[A-Za-z0-9_-]{1,64}$/; // 서버 기체 id 규칙과 같다(`_` 시작은 저장소가 거부)

/** 본문에 `profile`을 싣는 계산 라우트 (서버 요청 모델의 `profile: ProfileRef`). */
export const COMPUTE_POST = new Set([
  "/trim/batch",
  "/analysis/margin-map", "/analysis/bode", "/analysis/design-envelope-scan",
  "/design/auto",
  "/sim/run",
  "/codegen/flight", "/verify/flight",
  "/influence/structural", "/influence/diagnose", "/influence/openloop", "/influence/sweep",
  "/influence/scan", "/influence/evaluate", "/influence/verify", "/influence/prescribe",
]);

/** 쿼리로 기체를 받는 GET 라우트 (서버 `Depends(profile_query)`). */
export const COMPUTE_GET = new Set([
  "/analysis/vn-envelope", "/analysis/design-envelope", "/gains/catalog", "/gains/demo",
]);

/** 기체를 받지 않는 라우트와 그 사유 — "METHOD 경로" 키. 사유가 없는 분류는 분류가 아니다. */
export const NOT_AIRCRAFT = {
  "GET /health": "서버 상태",
  "POST /auth/login": "로그인 — 사람 계정, 기체 무관",
  "POST /auth/logout": "로그아웃 — 사람 계정, 기체 무관",
  "GET /auth/me": "세션 확인 — 사람 계정, 기체 무관",
  "POST /auth/signup": "가입 신청 — 사람 계정, 기체 무관",
  "GET /admin/users": "회원관리 — 사람 계정, 기체 무관",
  "POST /admin/users": "회원관리 — 사람 계정, 기체 무관",
  "PATCH /admin/users/{name}": "회원관리 — 사람 계정, 기체 무관",
  "DELETE /admin/users/{name}": "회원관리 — 사람 계정, 기체 무관",
  "GET /admin/sessions": "접속 현황 — 사람 계정, 기체 무관",
  "GET /admin/data": "결과 저장소 현황 — 결과가 자기 기체를 싣는다",
  "POST /admin/data/prune": "결과 저장소 정리 — 결과가 자기 기체를 싣는다",
  "GET /jobs": "작업 목록", "GET /jobs/{job_id}": "작업 상태", "POST /jobs/{job_id}/cancel": "작업 취소",
  "GET /results": "저장 결과 — 결과가 자기 기체(profile 블록)를 싣는다",
  "GET /results/{result_id}": "저장 결과 — 결과가 자기 기체(profile 블록)를 싣는다",
  "GET /sim/{result_id}/replay": "저장 런을 다시 읽는다 — 그 런의 기체로",
  "GET /sim/{result_id}/duty": "저장 런을 다시 읽는다 — 그 런의 기체로",
  "POST /design/{result_id}/resume": "세션에 기록된 기체 스냅숏으로 이어간다 — 지금 고른 기체가 아니다",
  "GET /design/defaults": "도구의 합격기준·예산 — 기체 무관",
  "GET /influence/criteria/defaults": "도구의 평가기준·어휘 — 기체 무관",
  "GET /registry": "블록 형식 목록 — 기체 무관",
  "GET /registry/{category}/{name}/schema": "블록 형식 스키마 — 기체 무관",
  "POST /registry/{category}/{name}/validate": "블록 파라미터 검증 — 기체 무관",
  "GET /llm/status": "LLM 연결 상태",
  "POST /llm/ask": "화면 안내 문답 — 기체 문맥은 9단계 [백로그]",
  "POST /llm/brief": "저장 결과의 소견서 — 결과가 자기 기체를 싣는다",
  "POST /llm/comms": "저장 런의 교신 대본 — 런이 자기 기체를 싣는다",
  "POST /llm/mission-draft": "미션 초안 — 기체 문맥은 9단계 [백로그]",
  "GET /world/manifest": "지형·표시 자산 — 기체 표시 모델은 10단계 [백로그]",
  "GET /world/model/{name}": "지형·표시 자산 — 기체 표시 모델은 10단계 [백로그]",
  "GET /world/terrain/{name}": "지형·표시 자산",
  "GET /profiles": "기체 문서 자체 — id가 경로·본문에 있다",
  "POST /profiles": "기체 문서 자체 — id가 경로·본문에 있다",
  "GET /profiles/{profile_id}": "기체 문서 자체 — id가 경로·본문에 있다",
  "PUT /profiles/{profile_id}": "기체 문서 자체 — id가 경로·본문에 있다",
  "DELETE /profiles/{profile_id}": "기체 문서 자체 — id가 경로·본문에 있다",
  "POST /profiles/validate": "기체 문서 자체 — id가 경로·본문에 있다",
  "POST /profiles/parse-table": "CSV 표 판독 — 기체 무관",
  "GET /profiles/_form": "편집 폼 서술(칸 이름·단위·선택지) — 기체 무관",
  "POST /profiles/aero-slice": "공력 DB 뷰어 — 기체 id가 아니라 편집 중인 문서를 본문으로 받는다",
  "POST /profiles/{profile_id}/quick-seed": "초기 게인 빠른 탐색 잡 — 저장된 기체 id가 경로에 있다(헤더 선택과 무관)",
  "POST /profiles/{profile_id}/derive-de-trim": "δe_trim 표 도출 잡 — 저장된 기체 id가 경로에 있다(헤더 선택과 무관)",
};

/** 저장값·입력 → {id, variant} 또는 null. 모양이 틀린 값은 버린다(손상된 저장값이 요청을 망치지 않게). */
export function normalizeSelection(v) {
  if (v == null || typeof v !== "object" || Array.isArray(v)) return null;
  if (typeof v.id !== "string" || !ID_RE.test(v.id)) return null;
  const variant = typeof v.variant === "string" && ID_RE.test(v.variant) ? v.variant : null;
  return { id: v.id, variant };
}

/** localStorage에서 읽는다 — 저장소가 없거나 막혀 있거나(사생활 창) 값이 손상돼도 null. */
export function loadSelection(storage) {
  try {
    const raw = storage?.getItem(STORAGE_KEY);
    return raw ? normalizeSelection(JSON.parse(raw)) : null;
  } catch {
    return null;
  }
}

/** 저장한다(null이면 지운다). 성공 여부를 돌려준다 — 못 쓰면 새로고침 뒤 선택이 사라지므로
 *  호출측이 전환을 멈추고 그 사실을 말해야 한다. */
export function saveSelection(storage, sel) {
  try {
    const norm = normalizeSelection(sel);
    if (norm) storage.setItem(STORAGE_KEY, JSON.stringify(norm));
    else storage.removeItem(STORAGE_KEY);
    return true;
  } catch {
    return false;
  }
}

let selection = null;

export const currentSelection = () => selection;

export function setSelection(sel) {
  selection = normalizeSelection(sel);
  return selection;
}

/** 요청에 싣는 기체 선택 — 고르지 않았으면 null. */
export function profileRef(sel = selection) {
  const norm = normalizeSelection(sel);
  if (!norm) return null;
  return norm.variant ? { id: norm.id, variant: norm.variant } : { id: norm.id };
}

/** 같은 기체·같은 형상 변형인가 — 목록의 행과 지금 선택을 대조할 때. */
export const sameSelection = (a, b) => {
  const x = normalizeSelection(a);
  const y = normalizeSelection(b);
  return x === y || (x != null && y != null && x.id === y.id && x.variant === y.variant);
};

/** 요청 한 건에 기체 선택을 싣는다 — 계산 라우트만, 호출측이 이미 실었으면 건드리지 않는다. */
export function withProfile(method, path, body, sel = selection) {
  const ref = profileRef(sel);
  if (!ref) return { path, body };
  const q = path.indexOf("?");
  const pathname = q < 0 ? path : path.slice(0, q);
  if (method === "POST" && COMPUTE_POST.has(pathname)
      && body != null && typeof body === "object" && !Array.isArray(body) && body.profile == null) {
    // `profile: undefined`도 "안 실음"이다 — JSON.stringify가 그 키를 지워 서버는 예제로 계산한다
    return { path, body: { ...body, profile: ref } };
  }
  if (method === "GET" && COMPUTE_GET.has(pathname)) {
    const query = q < 0 ? "" : path.slice(q + 1);
    if (/(^|&)profile_id=/.test(query)) return { path, body };
    const add = `profile_id=${encodeURIComponent(ref.id)}`
      + (ref.variant ? `&profile_variant=${encodeURIComponent(ref.variant)}` : "");
    return { path: q < 0 ? `${path}?${add}` : `${path}${query ? "&" : ""}${add}`, body };
  }
  return { path, body };
}

/** 저장된 선택이 목록에 아직 있는가 — 없으면 사유(지워짐·형상 변형 없음·읽을 수 없음). */
export function selectionProblem(list, sel) {
  const norm = normalizeSelection(sel);
  if (!norm) return null;
  const row = (list ?? []).find((p) => p.id === norm.id);
  if (!row) return `선택했던 기체 「${norm.id}」가 서버에 없습니다`;
  if (row.unreadable) return `선택했던 기체 「${norm.id}」를 서버가 읽을 수 없습니다`;
  if (norm.variant && !row.variants?.some((v) => v.id === norm.variant)) {
    return `선택했던 형상 변형 「${norm.id} / ${norm.variant}」가 없습니다`;
  }
  return null;
}

/** 복제 문서 — 이름표만 바꾸고 예제 표시를 뗀다(값·형상 변형은 그대로, 원본은 안 고친다). */
export function cloneDocument(doc, { id, name, description = null } = {}) {
  const out = JSON.parse(JSON.stringify(doc));
  out.id = id;
  out.name = name;
  out.is_example = false;
  out.description = description ?? `${doc.name} (${doc.id})에서 복제`;
  return out;
}

/** 편집기 글 → 문서. JSON이 아니거나 객체가 아니면 사유 — 서버에 보내기 전에 걸러 경로 없는 422를 막는다. */
export function parseDocumentText(text) {
  let v;
  try {
    v = JSON.parse(text);
  } catch (e) {
    return { doc: null, error: `JSON이 아닙니다 — ${e.message}` };
  }
  if (v == null || typeof v !== "object" || Array.isArray(v)) {
    return { doc: null, error: "기체 문서는 JSON 객체여야 합니다" };
  }
  return { doc: v, error: null };
}

/** 서버 검증 오류 detail({path, message}) → 한 줄. 경로를 앞에 둔다 — 편집기에서 그 칸을 찾게.
 *  그 모양이 아니면 null(호출측이 일반 오류 문구로). */
export function profileErrorText(detail) {
  if (detail == null || typeof detail !== "object" || Array.isArray(detail) || !("message" in detail)) return null;
  return detail.path ? `${detail.path}: ${detail.message}` : String(detail.message);
}

export const exportFileName = (id, revision) => `${id}-rev${revision}.json`;
