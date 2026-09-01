/** 미션 빌더 (02 §8 5단계) — 편집 행 → 서버 /api/sim/run 스펙 (순수 로직, 테스트 대상).

빈 문자열 = 축 off(null). 조건 DSL 인자수는 엔진 _COND_ARITY와 동일 테이블 —
불일치는 어차피 서버(엔진 validate_condition)가 422로 거부한다.
*/

export const COND_KINDS = {
  always: 0,
  time_ge: 1,
  alt_ge: 1,
  alt_le: 1,
  speed_ge: 1,
  speed_le: 1,
  hdot_ge: 1,
  hdot_le: 1,
  path_done: 0,
  on_ground: 0,
  airborne: 0,
  off_rail: 0,
};

/** 종방향 지령 축 — 셋은 **배타**다(엔진 validate_longitudinal).
 *
 * alt·pitch·hdot이 전부 θ_cmd로 가므로 둘을 켜면 누가 이기는지를 어딘가에 정해야
 * 하고, 그 순간 화면은 "무엇이 먹었는지"를 말할 수 없다. 그래서 편집 표도 축마다
 * 칸을 주지 않고 **하나를 고르게** 한다 — 배타 규칙이 UI 형태에 그대로 드러난다.
 *
 * value: 서버 ModeIn의 필드 이름. ""는 종방향 축 전부 끔(고도축 PI가 트림 θ 유지).
 */
export const LON_AXES = [
  { value: "", label: "off", unit: "" },
  { value: "alt", label: "고도", unit: "m | path" },
  { value: "pitch", label: "피치", unit: "rad" },
  { value: "hdot", label: "강하율", unit: "m/s (상승 +)" },
];

function num(text, what) {
  const s = String(text).trim();
  // Number("") === 0 함정 — 빈 필수 인자가 조용히 0으로 주입되는 것 차단 (리뷰 S1)
  if (s === "") throw new Error(`${what}: 값이 비어 있음`);
  const v = Number(s);
  if (!Number.isFinite(v)) throw new Error(`${what}: 수치가 아님 — ${JSON.stringify(text)}`);
  return v;
}

function numOrNull(text, what) {
  const s = String(text).trim();
  return s === "" ? null : num(s, what);
}

/** 수치 | "path" | null — heading·alt가 공유하는 규약 (엔진 ModeSpec).
 * 모드 테이블이 축마다 **명령 출처**를 고른다: "path"면 경로추종기가 낸다. */
function numOrPath(text, what) {
  const s = String(text).trim();
  if (s === "") return null;
  return s === "path" ? "path" : num(s, what);
}

/** 편집 행의 종방향 선택 → 서버 ModeIn의 세 필드 {alt, pitch, hdot}.
 *
 * 고른 축 하나에만 값이 들어가고 나머지는 null이다 — 배타가 여기서 구조적으로
 * 보장되므로 "둘 다 채운 행"이 만들어질 수 없다. "path"는 고도축에서만 뜻이 있다
 * (경로가 세로 프로파일을 낸다) — 피치·강하율에 넣으면 서버가 422로 거부하지만,
 * 그 전에 여기서 무엇이 잘못됐는지 짚어 준다.
 */
function lonAxes(r, name) {
  const axis = String(r.lonAxis ?? "").trim();
  const out = { alt: null, pitch: null, hdot: null };
  if (axis === "") return out;
  if (!Object.hasOwn(out, axis)) throw new Error(`${name}: 모르는 종방향 축 — ${axis}`);
  if (axis === "alt") {
    out.alt = numOrPath(r.lonValue, `${name}.고도`);
  } else {
    const s = String(r.lonValue ?? "").trim();
    if (s === "path") {
      throw new Error(
        `${name}: "path"는 고도축에서만 — 경로가 내는 것은 세로 프로파일(고도)이다`,
      );
    }
    out[axis] = numOrNull(s, `${name}.${axis === "pitch" ? "피치" : "강하율"}`);
  }
  return out;
}

export function buildModes(rows) {
  return rows.map((r) => {
    const name = String(r.name).trim();
    if (!name) throw new Error("모드 이름이 비어 있음");
    const exit = [r.exitKind];
    if (COND_KINDS[r.exitKind] === 1) exit.push(num(r.exitValue, `${name}.exit`));
    return {
      name,
      speed: numOrNull(r.speed, `${name}.speed`),
      ...lonAxes(r, name),
      heading: numOrPath(r.heading, `${name}.heading`),
      exit,
      next: String(r.next).trim() || null,
    };
  });
}

/** 실행이 **닿을 수 있는** 모드 행만 — 첫 행에서 next를 따라간 것.
 *
 * 엔진은 modes[0]에서 시작해 next로만 넘어간다(ModeSequencer). 그래서 아무도
 * 가리키지 않는 행은 표에 있어도 절대 실행되지 않는다 — "모드 추가" 버튼이
 * 만드는 행이 정확히 그것이다(next 빈 칸). 이걸 안 걸러 내면 사용자가 안내대로
 * 그 새 행에 "path"를 적는 순간 경고만 사라지고 비행은 한 비트도 안 바뀐다
 * (리뷰 지적) — 경고를 없애는 방법이 문제를 안 고치는 것이면 없느니만 못하다.
 *
 * 이름 중복·미정의 next는 엔진이 구성 시점에 거부하므로(서버 422) 여기서는
 * 먼저 나온 행이 이기고 모르는 이름은 끝으로 본다. 순환은 방문 집합으로 끊는다.
 */
function reachableModes(rows) {
  const byName = new Map();
  for (const r of rows) {
    const n = String(r?.name ?? "").trim();
    if (n && !byName.has(n)) byName.set(n, r);
  }
  const out = [];
  const seen = new Set();
  let cur = rows[0];
  while (cur && !seen.has(cur)) {
    seen.add(cur);
    out.push(cur);
    cur = byName.get(String(cur.next ?? "").trim());
  }
  return out;
}

/** 이 모드 표가 웨이포인트를 **실제로 쓰는가** — {heading, alt}.
 *
 * 웨이포인트를 찍어도 그것을 고르는 모드가 없으면 시뮬은 그냥 직진한다. 실측:
 * 기본 미션(헤딩 전부 "0")에 (3000, 2000, 600)·(6000, −1000, 400)을 넣고 돌리면
 * pe가 −6e-18 ~ 5e-16, 즉 동쪽으로 1 mm도 안 간다. 같은 미션의 cruise만
 * heading="path"로 바꾸면 pe가 −1495 ~ +2859로 움직인다.
 *
 * 그런데 화면은 지도에 주황 경로를 그리고 재생에도 웨이포인트를 찍는다 — 말하지
 * 않으면 화면이 스스로 모순된다("조용한 비표시 금지"). 엔진은 **반대 방향만**
 * 막는다(path인데 경로추종기 없음 → 422). 이쪽을 막을 수는 없다: 웨이포인트를
 * 날지 않고 **기준선으로만** 두고 경로오차(pipeline.metrics xtrack_rms)를 재는
 * 쓰임이 있어서다. 그래서 거부가 아니라 화면이 사실을 말하는 쪽으로 푼다.
 *
 * 반쯤 고친 행에서도 답해야 하므로 buildModes(던진다)를 거치지 않고 행을 직접 본다.
 */
export function pathUsage(rows) {
  const isPath = (v) => String(v ?? "").trim() === "path";
  const live = reachableModes(rows); // 실행이 닿지 않는 행의 "path"는 세지 않는다
  return {
    heading: live.some((r) => isPath(r.heading)),
    // 고도축일 때만 — 피치·강하율 칸의 "path"는 buildModes가 거부한다
    alt: live.some((r) => String(r.lonAxis ?? "").trim() === "alt" && isPath(r.lonValue)),
  };
}

/** 편집 행 → [[n, e], …] 또는 [[n, e, alt], …].
 *
 * 고도는 **전부 있거나 전부 없거나** — 엔진 set_waypoints와 같은 규칙을 제출
 * 시점에 먼저 건다. 섞인 채 보내면 서버가 422로 답하는데, 그때 사용자는 어느
 * 행이 빈지 표에서 눈으로 찾아야 한다. 여기서 막으면 행 번호를 짚어 준다.
 */
export function buildWaypoints(rows) {
  if (!rows.length) return null;
  const hasAlt = rows.map((r) => String(r.d ?? "").trim() !== "");
  if (hasAlt.some(Boolean) && !hasAlt.every(Boolean)) {
    const missing = hasAlt.map((ok, i) => (ok ? null : i + 1)).filter((v) => v !== null);
    throw new Error(
      `웨이포인트 고도는 전부 채우거나 전부 비워야 함 — 비어 있는 행: ${missing.join(", ")}`,
    );
  }
  return rows.map((r, i) => {
    const ne = [num(r.n, `wp${i}.N`), num(r.e, `wp${i}.E`)];
    return hasAlt[i] ? [...ne, num(r.d, `wp${i}.고도`)] : ne;
  });
}
