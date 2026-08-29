/** 상수 ↔ 스케줄 테이블 — 같은 게인을 구조도 폼과 게인 탭이 함께 쓰게 하는 층.

한 게인 자리는 두 상태 중 하나다.

- **스케줄 OFF** — 값은 스칼라 상수이고, 정본은 컴포넌트 kwargs 스토어
  (`scasParams` / `autopilotParams`)다. 구조도 폼과 게인 탭 자리 격자가 **같은
  값을 읽고 쓴다** — 어느 쪽에서 고쳐도 다른 쪽에 그대로 보여야 한다.
- **스케줄 ON** — 값은 테이블이고 정본은 `gainTables`다. 구조도는 그 자리를 잠그고
  설계점 값만 보여 준다. 안 잠그면 폼 상수와 룩업이 둘 다 "값"인 척하는데
  실행 시점에는 룩업이 이긴다 (fcl/graphs.py — 스케줄 포트가 있으면 상수 Gain
  대신 Product 노드가 선다).

자리 ↔ 파라미터 대응은 **여기서 만들지 않는다.** GET /gains/catalog의 slot이
`group`·`key`·`param`·`block`을 들고 오고, 그 정본은 엔진 `fcl/graphs.py`
SCHEDULABLE + `fcl/schedule.py` AP_GAIN_FIELD다 (`alt.k_rate = k_hdot` 같은 이름
차이도 거기서 흡수된다). 웹이 표를 다시 적으면 그룹이 늘거나 이름이 바뀔 때
조용히 어긋난다.

스케줄 **스케일 규칙**(데모는 동압 역비)도 다시 적지 않는다 — 서버가 제안 테이블과
설계점 인덱스(`design_index`)를 주므로, 시드는 제안 표의 **비율 재조정**이고
되접기는 설계점 한 칸 읽기다. 규칙이 바뀌거나 비행체 프로파일이 교체돼도 이
파일은 그대로다.

DOM·통신 없음 (lib/gainsched.js와 같은 층).
*/

/** 자리 이름 → slot (켤 수 있는 자리만). 불가 자리는 값이 없으므로 뺀다. */
export function slotIndex(catalog) {
  const out = new Map();
  for (const s of catalog?.slots ?? []) {
    if (s.available) out.set(s.name, s);
  }
  return out;
}

/** 그 자리 상수의 현재 값 — 편집된 스토어 값이 있으면 그것, 없으면 설계 상수.
 *
 * params = {scas: {pitch: {...}, …} | null, autopilot: {...} | null} (스토어 원본). */
export function constantOf(slot, params) {
  const cur = slot.block === "scas"
    ? params?.scas?.[slot.group]?.[slot.param]
    : params?.autopilot?.[slot.param];
  return typeof cur === "number" ? cur : slot.design;
}

/** 상수 갱신 → 새 {scas, autopilot}. 원본은 건드리지 않는다 (스토어 값 공유 방지).
 *
 * 두 스토어 모두 **전체 kwargs 계약**이라, 아직 편집본이 없으면 카탈로그의 설계
 * 상수로 나머지 자리를 채워 둔다 — 부분 dict를 보내면 서버 ParamDef 기본값(0)이
 * 들어차서 "안 건드린 게인"이 조용히 0이 된다. */
export function withConstant(catalog, slot, value, params) {
  const base = fullConstants(catalog, params);
  if (slot.block === "scas") {
    return {
      ...base,
      scas: {
        ...base.scas,
        [slot.group]: { ...base.scas[slot.group], [slot.param]: value },
      },
    };
  }
  return { ...base, autopilot: { ...base.autopilot, [slot.param]: value } };
}

/** 스토어 값에 카탈로그 설계 상수를 덧대 **빠진 자리가 없는** kwargs를 만든다.
 *
 * 카탈로그가 아는 것은 게인 자리뿐이다 — washout_tau·클램프·명령필터처럼 스케줄
 * 대상이 아닌 파라미터는 스토어에 있으면 그대로 살아남고, 없으면 여기서도 비어
 * 있다(그 자리는 구조도 폼이 스키마 기본값으로 채운다). */
export function fullConstants(catalog, params) {
  // SCAS는 게인 자리(kp·ki·k_rate)만 채우면 모자란다 — washout_tau·클램프가 빠진 채
  // 주입되면 서버 ParamDef 기본값(0·±무제한)이 들어차서 워시아웃과 출력 한계가
  // 조용히 사라진다. 그래서 축 kwargs 전량을 아는 scas_design에서 출발한다.
  // AP는 반대다: PARAM_DEFS 기본값이 곧 데모 설계값이라 부분 dict가 안전하다
  const scas = scasKwargs(catalog, params?.scas) ?? {};
  const autopilot = { ...(params?.autopilot ?? {}) };
  for (const slot of slotIndex(catalog).values()) {
    if (slot.block === "scas") {
      scas[slot.group] = scas[slot.group] ?? {};
      if (typeof scas[slot.group][slot.param] !== "number") {
        scas[slot.group][slot.param] = slot.design;
      }
    } else if (typeof autopilot[slot.param] !== "number") {
      autopilot[slot.param] = slot.design;
    }
  }
  return { scas, autopilot };
}

/** 지금 스케줄이 켜져 있는 자리 이름 — 게인 탭이 적용해 둔 형상을 되읽는다.
 *
 * 게인 탭은 "켠 자리"를 따로 저장하지 않는다 — `gainTables`의 **키 집합이 곧 선택**
 * 이기 때문이다(lib/gainsched.js storePayload). 전부 끈 형상만 빈 dict로 표현할 수
 * 없어 `gainScheduleOff` 신호를 함께 쓴다. 아직 아무것도 적용하지 않았으면 서버
 * 기본(카탈로그 default)이 돌고 있는 형상이다. */
export function selectedSlots(catalog, gainTables, scheduleOff) {
  if (scheduleOff) return [];
  if (gainTables) return Object.keys(gainTables);
  return [...(catalog?.default ?? [])];
}

/** SCAS 축 kwargs 한 벌 — 카탈로그 설계값 위에 스토어 편집본을 덧댄다.
 *
 * 편집이 없어도 **설계값**이 나와야 한다: ScasAxis는 범용 축 컴포넌트라 스키마
 * 기본값이 전부 0이고, 그대로 쓰면 코드 표현·주입이 게인 없는 형상이 된다
 * (AP는 PARAM_DEFS 기본값이 곧 데모 설계값이라 이 문제가 없다).
 * 카탈로그가 없으면(서버 이탈) 스토어 값만 — 없으면 null로 "주입 없음". */
export function scasKwargs(catalog, stored) {
  const design = catalog?.scas_design ?? {};
  const groups = new Set([...Object.keys(design), ...Object.keys(stored ?? {})]);
  const out = {};
  for (const g of groups) out[g] = { ...(design[g] ?? {}), ...(stored?.[g] ?? {}) };
  return groups.size ? out : null;
}

/** 그 블록·그룹에서 **스케줄이 덮고 있는** 파라미터 이름 → 자리 이름.
 *
 * 구조도 폼이 잠글 입력을 고르는 데 쓴다. group을 안 주면 블록 전체(AP는 그룹이
 * 셋이지만 kwargs는 한 벌이라 group 구분이 없다). */
export function lockedParams(catalog, selected, block, group = null) {
  const want = new Set(selected ?? []);
  const out = new Map();
  for (const slot of slotIndex(catalog).values()) {
    if (slot.block !== block) continue;
    if (group !== null && slot.group !== group) continue;
    if (want.has(slot.name)) out.set(slot.param, slot.name);
  }
  return out;
}

/** 자리를 켤 때 심을 테이블 — 제안 표를 **현재 상수 비율로** 재조정.
 *
 * 설계점에서는 상수 그대로이므로 "켜기 전후로 설계점 거동이 같다"가 유지된다
 * (게인 탭 화면이 약속하는 것). 설계값이 0인 자리(요축 ki·헤딩 ki)는 비율을 못
 * 재므로 상수 평탄표로 심는다 — 표가 전부 0이라 편집 전엔 효과가 없다는 기존
 * 안내(lib/gainsched.js zeroTables)와 같은 상황이다. */
export function seedTable(catalog, slot, constant) {
  const t = slot.table;
  // 비율의 기준은 **그 표의 설계점 값**이다 (설계 상수가 아니라). 켰다 껐다를
  // 반복해도 형상이 누적 스케일되지 않는다 — 이미 맞는 표를 다시 심으면 그대로다
  const base = designPointValue(t, catalog?.design_index) ?? slot.design;
  const data = base
    ? t.data.map((v) => (v / base) * constant)
    : t.data.map(() => constant);
  return { axes: { ...t.axes }, data, extrapolate: t.extrapolate };
}

/** 설계점 한 칸 — 잠긴 폼 필드 배지("스케줄 중 M0.6: X")와 되접기가 함께 쓴다. */
export function designPointValue(table, designIndex) {
  const data = table?.data ?? [];
  if (!data.length) return null;
  const i = Number.isInteger(designIndex) && designIndex >= 0 && designIndex < data.length
    ? designIndex
    : 0;
  return data[i];
}

/** 자리를 끌 때 굳힐 상수 = 편집된 표의 설계점 값.
 *
 * 카탈로그의 원래 설계 상수로 되돌리면, 표를 고쳐 놓고 스케줄만 끈 사용자에게
 * "끄면 이 값으로 굳는다"는 화면 설명이 거짓말이 된다. */
export function foldToConstant(catalog, slot, tables) {
  const t = tables?.[slot.name];
  const v = t ? designPointValue(t, catalog?.design_index) : null;
  return typeof v === "number" ? v : slot.design;
}
