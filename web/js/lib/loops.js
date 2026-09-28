/** PI 개루프 스펙 편집 로직 — 마진 맵 다중 루프 폼 (서버 /analysis/margin-map loops[]).

서버 LoopIn(축·상태·입력 정합, 무의미 루프 거부)의 클라이언트 미러 — 제출 전
사전검증으로 배치 실행 전에 오타를 잡는다. 최종 판정은 서버(422)가 정본.
*/

import { slotIndex, valueAt } from "./gainsync.js";
import { parseFieldValue } from "./schemaform.js";

/** 축별 상태·입력 이름 — engine/claw/trim/linearize.py의 수동 사본 (정본은 엔진.
rename 시 여기와 loops.test.js 스냅샷도 갱신 — 낡으면 사전검증만 무뎌지고
서버 422가 최종 방어). */
export const AXIS_NAMES = {
  lon: { states: ["u", "w", "q", "theta"], inputs: ["de", "thr"] },
  lat: { states: ["v", "p", "r", "phi"], inputs: ["da", "dr"] },
};

/** 3축 레이트 루프 — SCAS 축 구성(피치 q←δe·롤 p←δa·요 r←δr)의 **구조**(축·상태·입력·부호)만.
엔진 pipeline/openloop.py GROUP_LOOPS의 레이트 루프 선언(kp ← 그 축 k_rate, sign −1)과 같은 루프다
(test_openloop이 이 대응을 핀한다). **게인은 여기 없다** — 고른 기체가 실제로 나는 게인에서 온다(loopGainSources).
종전에는 kp·ki를 여기 적어 두었는데(피치 0.5/0.8) 어느 기체의 설계값도 아니라 마진 맵이 문서와 무관한
루프를 재고 있었다 — 기체 의존 값을 코드에 두지 않는다. group은 게인 자리(「group.k_rate」)의 축 이름이다. */
export const DEFAULT_LOOPS = Object.freeze([
  Object.freeze({ name: "pitch_q", axis: "lon", x_out: "q", u_in: "de", sign: "-1", group: "pitch" }),
  Object.freeze({ name: "roll_p", axis: "lat", x_out: "p", u_in: "da", sign: "-1", group: "roll" }),
  Object.freeze({ name: "yaw_r", axis: "lat", x_out: "r", u_in: "dr", sign: "-1", group: "yaw" }),
]);

/** 레이트 루프 게인의 출처 — 기체가 **실제로 나는** 게인 (엔진 assemble_law의 스케줄 표 우선순위 그대로).
 *
 * 문서에 확정 게인 표(law.gain_tables — 자동 설계 반영)가 있고 낡지 않았으면 조립 정본은 그 표 **전체 교체**다 —
 * 표에 있는 자리는 표, 없는 자리는 설계 상수(law.design). 확정 표가 없거나 낡았으면(낡은 표는 조립이 거부한다)
 * 규칙 스케줄 — law.schedule.scheduled 자리는 규칙 표, 나머지는 설계 상수. 종전에는 설계 상수(시드 설계점 값)를
 * 칸마다 그대로 썼는데, 확정 표가 있는 기체는 그 값으로 날지 않는다(쇼케이스 기체 pitch.k_rate 설계값 0.173 ↔ 확정 표 M0.147 ≈ 0.40).
 *
 * 규칙 스케줄 산식은 여기 다시 적지 않는다 — 카탈로그의 제안 표(slot.table — 서버가 엔진 gain_tables()로 만든 표,
 * 격자점 사이는 엔진도 같은 표를 선형 보간한다)를 읽는다.
 *
 * catalog: GET /gains/catalog. confirmedTables: 카탈로그가 확정 표가 있다(confirmed, 낡지 않음)고 할 때 **같은
 * 리비전** 문서의 law.gain_tables.tables — 그 밖에는 읽지 않는다. 확정 표가 있다는데 표가 없거나 자리가 어긋나면
 * 던진다(그사이 문서가 바뀌었다 — 규칙 표로 조용히 갈음하지 않는다).
 * 반환 {basis: "confirmed"|"rule", staleConfirmed, loops: [{…DEFAULT_LOOPS 구조, slot, kind, table, constant}]} —
 * kind "confirmed"(확정 표)·"rule"(규칙 표)·"fixed"(스케줄 안 한 자리 — 설계 상수). */
export function loopGainSources(catalog, confirmedTables = null) {
  const conf = catalog?.confirmed ?? null;
  const useConfirmed = conf != null && conf.stale !== true;
  if (useConfirmed) {
    if (!confirmedTables || typeof confirmedTables !== "object") {
      throw new Error("카탈로그는 확정 게인 표가 있다는데 문서에서 그 표를 받지 못했다");
    }
    const have = Object.keys(confirmedTables).sort().join(", ");
    const want = [...(conf.slots ?? [])].sort().join(", ");
    if (have !== want) {
      throw new Error(`카탈로그와 문서의 확정 게인 표 자리가 다르다(${want} ↔ ${have}) — 그사이 문서가 바뀌었다. `
        + "탭을 다시 연다");
    }
  }
  const slots = slotIndex(catalog);
  const loops = DEFAULT_LOOPS.map((l) => {
    const slot = `${l.group}.k_rate`;
    const s = slots.get(slot);
    const constant = s?.design ?? catalog?.scas_design?.[l.group]?.k_rate ?? null;
    const base = { ...l, slot, constant, table: null, kind: "fixed" };
    if (useConfirmed) {
      return Object.hasOwn(confirmedTables, slot) ? { ...base, kind: "confirmed", table: confirmedTables[slot] } : base;
    }
    return s?.scheduled && s.table ? { ...base, kind: "rule", table: s.table } : base;
  });
  return { basis: useConfirmed ? "confirmed" : "rule", staleConfirmed: conf?.stale === true, loops };
}

/** 한 출처의 실효 게인 @ point {mach, alt, fuel} — 엔진 openloop._effective_gain과 같은 규칙(표@그 점, 표 밖은 clip ·
 * 스케줄 변수 필터는 정상상태라 생략). 표는 스케줄 변수 하나의 1축만 읽는다(문서 스키마·규칙 표 모두 마하 1축) —
 * 못 읽으면 null. */
export function gainAt(src, point) {
  if (src?.kind === "fixed") {
    return typeof src.constant === "number" && Number.isFinite(src.constant) ? src.constant : null;
  }
  const axes = Object.keys(src?.table?.axes ?? {});
  if (axes.length !== 1 || typeof point?.[axes[0]] !== "number") return null;
  const v = valueAt(src.table, axes[0], point[axes[0]]);
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** 출처 → 그 점에서 기체가 나는 게인으로 선 루프 편집 행 {rows, skipped}. 레이트 루프의 게인은 각속도 피드백
 * k_rate 하나다 — kp = k_rate, ki = 0 (부호는 게인이 보유 — 롤 k_rate가 음수면 kp도 음수다). 0이거나 읽지 못한
 * 루프는 서지 않는다(제로 개루프 — 서버 422): skipped에 사유와 함께 남겨 화면이 말하게 한다. */
export function loopsAt(sources, point) {
  const rows = [];
  const skipped = [];
  for (const s of sources?.loops ?? []) {
    const k = gainAt(s, point);
    if (k == null) {
      skipped.push({ name: s.name, reason: s.kind === "fixed"
        ? `문서 설계값에 ${s.slot}이 없다`
        : `${s.slot} 표를 이 점에서 읽지 못했다(스케줄 변수 1축 표가 아니다)` });
    } else if (k === 0) {
      skipped.push({ name: s.name, reason: `${s.slot} = 0 — 레이트 피드백이 없어 루프가 없다` });
    } else {
      rows.push({ name: s.name, axis: s.axis, x_out: s.x_out, u_in: s.u_in, kp: String(k), ki: "0", sign: s.sign });
    }
  }
  return { rows, skipped };
}

/** 편집 행 중 문서 게인으로 세운 그대로인 루프 이름 — 세운 행(seedRows)과 이름·구조·게인 글이 모두 같을 때만.
 * 손댄 루프의 kp는 문서 게인이 아니다 — 그 루프에는 출처를 붙이지 않는다(캡션이 「손으로 적은 값」으로 따로 말한다). */
export function docLoopNames(rows, seedRows) {
  const key = (r) => JSON.stringify([r.name, r.axis, r.x_out, r.u_in, String(r.kp), String(r.ki), String(r.sign)]);
  const seeds = new Set((seedRows ?? []).map(key));
  return (rows ?? []).filter((r) => seeds.has(key(r))).map((r) => r.name);
}

// 같은 게인인가 — 표를 같은 점에서 두 번 읽은 값끼리의 비교라 상대 1e-9면 충분하다
const sameGain = (a, b) => Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a), Math.abs(b));

/** 손대지 않은 문서 게인 루프를 서버가 **칸마다** 조립 법칙에서 읽게 할 수 있는가(margin-map loops[]의 gain_source
 * "profile") — 출처가 섰고 확정 표가 낡지 않았을 때. 낡은 확정 표는 서버 조립이 거부하므로(422 — 시뮬·코드와 같은
 * 판정) 그때는 종전대로 한 점에서 읽은 kp 하나를 싣는다(그 밖의 열은 근사라고 캡션이 말한다). */
export function lawGainsPerCase(sources) {
  return !!sources && !sources.error && Array.isArray(sources.loops) && sources.staleConfirmed !== true;
}

/** 검증한 루프 스펙(validateLoops) → 서버 loops[]. lawNames의 루프는 kp·ki 없이 gain_source "profile" — 서버가 칸마다
 * 그 칸의 운용점에서 조립 법칙의 게인을 읽는다(서버는 kp·ki를 함께 실으면 거절한다 — 게인을 두 곳에서 받지 않는다).
 * 나머지(손으로 적은 루프)는 적은 kp·ki 그대로다. */
export function requestLoops(loops, lawNames = []) {
  const law = new Set(lawNames);
  return (loops ?? []).map((l) => (law.has(l.name)
    ? { name: l.name, axis: l.axis, x_out: l.x_out, u_in: l.u_in, sign: l.sign, gain_source: "profile" }
    : l));
}

/** 제출 한 번의 게인 기록 — 결과 캡션·칸별 보드선도 주석·진행기 보고의 재료. 제출 시점에 굳힌다(뒤에 문서가
 * 바뀌어도 그 결과를 잰 게인을 말한다).
 *
 * perCase(lawGainsPerCase)이면 문서 게인 루프는 서버가 칸마다 읽는다 — 모든 칸이 그 칸의 실제 게인이고, 한 kp는 없다
 * (loops[].kp null). 아니면(확정 표 낡음) **요청이 루프마다 kp 하나**라 스케줄 게인은 한 점(ref)에서 읽어 전 칸에 쓰고,
 * 칸마다 기체가 실제로 나는 게인과 같은 칸이 몇인지를 함께 센다 — 같지 않은 칸의 마진은 근사다.
 * sources: loopGainSources(실패·미수신이면 null) · rows: 제출한 편집 행 · seedRows: 같은 점에서 문서 게인으로 세운 행 ·
 * ref: 게인을 읽은 점 {mach, alt, fuel} · points: 격자 케이스.
 * 반환 {basis, staleConfirmed, perCase, ref, nCases, exactCases, exactMachs,
 *       loops: [{name, slot, kind, perCase, kp, min, max, src}], edited}. */
export function runGainInfo(sources, rows, seedRows, ref, points, perCase = false) {
  const doc = new Set(sources ? docLoopNames(rows, seedRows) : []);
  const pts = points ?? [];
  const loops = [];
  for (const src of sources?.loops ?? []) {
    if (!doc.has(src.name)) continue;
    const vals = pts.map((p) => gainAt(src, p)).filter((v) => v != null);
    loops.push({
      name: src.name, slot: src.slot, kind: src.kind, perCase: !!perCase,
      kp: perCase || !ref ? null : gainAt(src, ref),
      min: vals.length ? Math.min(...vals) : null, max: vals.length ? Math.max(...vals) : null, src,
    });
  }
  // 그 칸의 실제 게인으로 잰 칸 — 문서 게인 루프 전부가 칸별(서버가 그 칸에서 읽음)이거나 그 칸에서 ref와 같은 게인일 때
  const exact = pts.filter((p) => loops.every((l) => {
    if (l.perCase) return true;
    const g = gainAt(l.src, p);
    return g != null && l.kp != null && sameGain(g, l.kp);
  }));
  return {
    basis: sources?.basis ?? null, staleConfirmed: sources?.staleConfirmed === true,
    perCase: !!perCase && loops.length > 0, ref,
    nCases: pts.length, exactCases: exact.length, exactMachs: [...new Set(exact.map((p) => p.mach))],
    loops, edited: (rows ?? []).map((r) => r.name).filter((n) => !doc.has(n)),
  };
}

/** 결과의 법칙 게인 기록 — 서버가 칸마다 읽은 게인(entry.gains)과 그 출처(profile_gains: basis·자리·스케줄 여부) →
 * {basis, nCases, loops: [{name, slot, scheduled, min, max}]}. 법칙 게인 루프가 없는 결과(요청 게인만)는 null. 캡션의
 * 범위는 이 기록(서버가 실제로 쓴 게인)에서 낸다 — 화면이 표를 다시 읽어 짐작한 값이 아니다. */
export function lawGainRecord(body) {
  const pg = body?.profile_gains;
  if (!pg || typeof pg !== "object" || !pg.loops || typeof pg.loops !== "object") return null;
  const cases = body.cases ?? [];
  const loops = Object.entries(pg.loops).map(([name, args]) => {
    const vals = cases.map((e) => e?.gains?.[name]?.kp).filter((v) => typeof v === "number" && Number.isFinite(v));
    return {
      name, slot: args?.kp?.slot ?? null, scheduled: args?.kp?.scheduled === true,
      min: vals.length ? Math.min(...vals) : null, max: vals.length ? Math.max(...vals) : null,
    };
  });
  return loops.length ? { basis: pg.basis ?? null, nCases: cases.length, loops } : null;
}

// 제출 기록(perCase)만 있을 때의 법칙 게인 기록 꼴 — 실행 전 미리보기 캡션용(범위는 화면이 표에서 읽은 값)
function lawRecordOf(info) {
  if (!info?.perCase) return null;
  return {
    basis: info.basis, nCases: info.nCases,
    loops: info.loops.map((l) => ({ name: l.name, slot: l.slot, scheduled: l.kind !== "fixed", min: l.min, max: l.max })),
  };
}

const g3 = (v) => (typeof v === "number" && Number.isFinite(v) ? String(Number(v.toPrecision(3))) : "—");
const g4 = (v) => (typeof v === "number" && Number.isFinite(v) ? String(Number(v.toPrecision(4))) : "—");
const machTag = (m) => `M${m}`;

/** 출처 이름 — 루프 라벨·진행기 보고에 붙이는 짧은 꼴. */
function basisLabel(info) {
  if (info.basis === "confirmed") return "확정 게인 표";
  return info.staleConfirmed ? "규칙 스케줄(확정 표 낡음)" : "규칙 스케줄";
}

// 법칙 게인 기록에서 그 루프 — 결과 기록(서버)이 먼저, 없으면 제출 기록의 칸별 루프
const lawLoop = (info, law, name) => (law ?? lawRecordOf(info))?.loops.find((x) => x.name === name) ?? null;

/** 루프 하나의 게인 출처 꼬리표 — 「확정 게인 표 칸별」·「확정 게인 표 @M0.15」·「설계 상수」·「손으로 적은 값」. 모르면 null.
 * law: lawGainRecord(결과) — 있으면 그 루프의 출처는 서버 기록이다. */
export function loopKpTag(info, name, law = null) {
  if (info?.edited.includes(name)) return "손으로 적은 값";
  const ll = lawLoop(info, law, name);
  if (ll) {
    if (!ll.scheduled) return "설계 상수(스케줄 안 한 자리)";
    return `${(law ?? info).basis === "confirmed" ? "확정 게인 표" : "규칙 스케줄"} 칸별`;
  }
  if (!info) return null;
  const l = info.loops.find((x) => x.name === name);
  if (!l) return null;
  return l.kind === "fixed" ? "설계 상수(스케줄 안 한 자리)" : `${basisLabel(info)} @${machTag(info.ref.mach)}`;
}

/** 법칙 게인 루프의 kp 글 — 칸마다 다르면 격자 범위 「0.313~0.4747」, 같으면 그 값(칸별이라는 사실은 loopKpTag가 말한다).
 * 법칙 게인 루프가 아니면 null. */
export function lawKpText(law, name) {
  const l = law?.loops.find((x) => x.name === name);
  if (!l || l.min == null) return null;
  return l.min === l.max ? g4(l.min) : `${g4(l.min)}~${g4(l.max)}`;
}

/** 마진 맵이 쓴 루프 게인의 출처 캡션 — 무엇을 어디서 읽었는지, 칸마다 그 칸의 실제 게인인지. 루프가 없으면 null.
 * law(lawGainRecord — 결과의 서버 기록)가 있거나 제출 기록이 칸별(perCase)이면 칸마다 정확하다고 말하고 격자의 게인
 * 범위를 낸다. 그 밖(확정 표 낡음)은 한 kp로 잰 근사의 크기를 말한다 — 확정 표가 낡았으면 그 표로는 기체가 날 수
 * 없다는 사실을 먼저 말한다(규칙 표 값을 실제 비행 게인인 척하지 않는다). */
export function gainSourceText(info, law = null) {
  const rec = law ?? lawRecordOf(info);
  const edited = info?.edited ?? [];
  if (!rec && (!info || (!info.loops.length && !edited.length))) return null;
  const parts = [];
  if (rec) {
    const vals = rec.loops.map((l) => (l.scheduled
      ? `${l.name} ${l.min === l.max ? g3(l.min) : `${g3(l.min)}~${g3(l.max)}`}`
      : `${l.name} ${g3(l.min)}(스케줄 안 한 자리 — 설계 상수)`)).join(" · ");
    // 조사는 괄호 앞 낱말에 붙는다 — 표를 · 스케줄을
    const where = rec.basis === "confirmed"
      ? "문서 확정 게인 표(자동 설계 반영 — 시뮬·코드가 조립하는 표)를"
      : "문서 규칙 스케줄(law.schedule — 시뮬·코드가 조립하는 표)을";
    parts.push(`루프 kp는 칸마다 그 칸에서 기체가 실제로 나는 k_rate다 — 서버가 조립 법칙의 ${where} 칸의 `
      + `운용점에서 읽는다(루프 gain_source "profile"). 격자 ${rec.nCases}칸 모두 그 칸의 실제 게인으로 잰 마진이다 — `
      + `이 격자의 게인: ${vals}.`);
  } else if (info.loops.length) {
    const vals = info.loops.map((l) => `${l.name} ${g3(l.kp)}${l.kind === "fixed" ? "(스케줄 안 한 자리 — 설계 상수)" : ""}`)
      .join(" · ");
    const at = machTag(info.ref.mach);
    if (info.basis === "confirmed") {
      parts.push(`루프 kp는 문서 확정 게인 표(자동 설계 반영 — 시뮬·코드가 조립하는 표)를 ${at}에서 읽은, 기체가 실제로 `
        + `나는 k_rate다: ${vals}.`);
    } else if (info.staleConfirmed) {
      parts.push("문서의 확정 게인 표가 낡아 조립이 거부한다(시뮬·코드 422) — 이 문서로는 기체가 날 게인이 없다. "
        + `루프 kp는 그 대신 규칙 스케줄(law.schedule)을 ${at}에서 읽은 k_rate다: ${vals}.`);
    } else {
      parts.push(`루프 kp는 문서 규칙 스케줄(law.schedule — 시뮬·코드가 조립하는 표)을 ${at}에서 읽은, 기체가 실제로 `
        + `나는 k_rate다: ${vals}.`);
    }
    // 확정 표가 낡았으면 기체가 나는 게인이 없다 — 칸의 기준은 「실제 게인」이 아니라 그 칸의 규칙 스케줄 게인이다
    const own = info.staleConfirmed ? "그 칸의 규칙 스케줄 게인" : "그 칸의 실제 게인";
    if (info.exactCases === info.nCases) {
      parts.push(`이 격자에서는 칸마다 게인이 같아 모든 칸이 ${own}으로 잰 마진이다.`);
    } else {
      const spans = info.loops.filter((l) => l.min !== l.max).map((l) => `${l.name} ${g3(l.min)}~${g3(l.max)}`).join(" · ");
      // 칸별 요청(gain_source "profile")을 못 쓴 까닭 — 낡은 확정 표는 서버 조립이 거부한다
      parts.push((info.staleConfirmed
        ? "낡은 확정 표는 서버 조립이 거부해 칸마다 법칙 게인을 읽게 할 수 없고, 요청은 루프마다 kp 하나라 "
        : "요청은 루프마다 kp 하나라 ")
        + "칸마다 다른 스케줄 게인을 싣지 못한다 — "
        + (info.exactCases
          ? `격자 ${info.nCases}칸 중 ${info.exactCases}칸(${info.exactMachs.map(machTag).join("·")})만 ${own}으로 `
            + "잰 마진이고, 나머지 칸은 다른 게인으로 잰 값이라 판정까지 뒤집힐 수 있는 근사다."
          : `격자 ${info.nCases}칸 중 ${own}으로 잰 칸이 없다(게인을 읽은 ${at}가 격자에 없다) — 전부 `
            + "다른 게인으로 잰, 판정까지 뒤집힐 수 있는 근사다.")
        + ` ${info.staleConfirmed ? "이 격자의 규칙 스케줄 게인" : "이 격자에서 기체가 실제로 나는 게인"}: ${spans}.`);
    }
  }
  if (edited.length) {
    parts.push(`손으로 적은 루프(${edited.join(", ")})의 kp는 문서 게인이 아니다 — 적은 값 하나로 전 칸을 잰다.`);
  }
  return parts.join(" ");
}

/** 진행기 보고 꼬리 — 「루프 게인 확정 게인 표 칸별 (전 칸 정확)」·「루프 게인 규칙 스케줄(확정 표 낡음) @M0.15 (20칸 중
 * 4칸 정확)」. 문서 게인 루프가 없으면 null. */
export function gainSummaryTag(info, law = null) {
  const rec = law ?? lawRecordOf(info);
  if (rec) return `루프 게인 ${rec.basis === "confirmed" ? "확정 게인 표" : "규칙 스케줄"} 칸별 (전 칸 정확)`;
  if (!info?.loops.length) return info?.edited.length ? "루프 게인 손으로 적은 값" : null;
  const exact = info.exactCases === info.nCases ? "전 칸 정확" : `${info.nCases}칸 중 ${info.exactCases}칸 정확`;
  return `루프 게인 ${basisLabel(info)} @${machTag(info.ref.mach)} (${exact})`;
}

/** 진행기 보고 data.gains — 표·함수 없이 수만. law(결과의 서버 기록)가 있으면 칸별 루프의 범위는 그 기록의 것이다. */
export function gainCueData(info, law = null) {
  const rec = law ?? lawRecordOf(info);
  if (!info && !rec) return null;
  const perCase = !!rec;
  const loops = perCase
    ? rec.loops.map(({ name, slot, scheduled, min, max }) => ({ name, slot, kind: scheduled ? rec.basis : "fixed", kp: null, min, max }))
    : info.loops.map(({ name, slot, kind, kp, min, max }) => ({ name, slot, kind, kp, min, max }));
  return {
    basis: rec?.basis ?? info?.basis ?? null, stale_confirmed: info?.staleConfirmed === true, per_case: perCase,
    ref_mach: perCase ? null : info.ref?.mach ?? null,
    n_cases: rec?.nCases ?? info.nCases, exact_cases: perCase ? rec.nCases : info.exactCases,
    edited: [...(info?.edited ?? [])], loops,
  };
}

/** 누른 칸에서 기체가 실제로 나는 게인이 맵이 쓴 kp와 다르면 한 줄 — 같거나 모르면 null (칸별 보드선도 주석).
 * 칸별 루프(서버가 그 칸에서 읽음)는 늘 그 칸의 게인이라 null이다. */
export function cellGainNote(info, loopName, point, usedKp) {
  const l = info?.loops.find((x) => x.name === loopName);
  if (!l || l.perCase || typeof usedKp !== "number") return null;
  const flown = gainAt(l.src, point);
  if (flown == null || sameGain(flown, usedKp)) return null;
  const pct = Math.round((flown / usedKp - 1) * 100);
  const whose = info.staleConfirmed ? "규칙 스케줄" : "기체가 실제로 나는";
  // 수 바로 뒤에 조사를 붙이지 않는다(읽는 소리에 따라 은/는·로/으로가 갈린다) — 「= 값」과 괄호로 둔다
  return `이 칸(${machTag(point.mach)})에서 ${whose} ${l.slot} = ${g3(flown)} — 이 곡선과 맵은 `
    + `${machTag(info.ref.mach)}에서 읽은 kp(${g3(usedKp)})로 쟀다(이 칸 게인은 그보다 ${pct >= 0 ? "+" : ""}${pct} %)`;
}

/** 법칙 게인 루프의 보드선도 응답(서버 gains·profile_gains) → 이 곡선을 그린 이 칸의 게인 한 줄. 요청 게인 루프면 null. */
export function bodeLawGainNote(res) {
  const kp = res?.gains?.kp;
  if (typeof kp !== "number") return null;
  const [name, args] = Object.entries(res.profile_gains?.loops ?? {})[0] ?? [];
  const slot = args?.kp?.slot ?? "k_rate";
  const where = args?.kp?.scheduled === false
    ? "스케줄 안 한 자리 — 설계 상수"
    : `${res.profile_gains?.basis === "confirmed" ? "문서 확정 게인 표를" : "문서 규칙 스케줄을"} 이 칸의 운용점에서 읽음`;
  return `이 곡선의 kp = ${g4(kp)} — 이 칸에서 기체가 실제로 나는 ${slot} 값이다(${where}). 맵의 이 칸`
    + `${name ? `(${name})` : ""}과 같은 게인이다`;
}

const NUM = (name) => ({ name, type: "number", lo: null, hi: null });

/** 편집 행(수치는 입력 문자열) 목록 → {loops: 파싱된 스펙[]} | {errors: 문구[]}.
빈 목록은 유효 — 루프 없이 고유치·감쇠비만 보는 실행. */
export function validateLoops(rows) {
  const loops = [];
  const errors = [];
  const seen = new Set();
  for (const r of rows) {
    const name = (r.name ?? "").trim();
    const tag = name || `(${rows.indexOf(r) + 1}번째 행)`;
    if (!name) errors.push(`${tag}: 루프 이름 필요`);
    else if (seen.has(name)) errors.push(`${tag}: 루프 이름 중복`);
    seen.add(name);
    const ax = AXIS_NAMES[r.axis];
    if (!ax) {
      errors.push(`${tag}: 미지 축 ${r.axis}`);
      continue;
    }
    if (!ax.states.includes(r.x_out)) errors.push(`${tag}: ${r.axis}축에 없는 상태 ${r.x_out}`);
    if (!ax.inputs.includes(r.u_in)) errors.push(`${tag}: ${r.axis}축에 없는 입력 ${r.u_in}`);
    const nums = {};
    for (const k of ["kp", "ki", "sign"]) {
      const p = parseFieldValue(NUM(`${tag}.${k}`), String(r[k]));
      if (p.error) errors.push(p.error);
      else nums[k] = p.value;
    }
    if (nums.sign === 0) errors.push(`${tag}: sign=0 (무의미 루프)`);
    if (nums.kp === 0 && nums.ki === 0) errors.push(`${tag}: kp=ki=0 (제로 개루프)`);
    loops.push({ name, axis: r.axis, x_out: r.x_out, u_in: r.u_in, ...nums });
  }
  return errors.length ? { errors } : { loops };
}

const POS = (name) => ({ name, type: "number", lo: Number.MIN_VALUE, hi: null }); // >0 (gt)
const NONNEG = (name) => ({ name, type: "number", lo: 0, hi: null }); // ≥0 (ge)
const INT_POS = (name) => ({ name, type: "integer", lo: 1, hi: null }); // ≥1 (ge)

/** 작동기·지연 포함 옵션(체크박스+수치 문자열) → 서버 MarginMapIn.actuator/delay_s/
pade_order 미러. 꺼진 그룹의 필드는 검증하지 않음(빈 값이어도 통과) — 서버 필드
자체가 안 보내지므로 무의미. row: {useActuator, wn, zeta, useDelay, delaySeconds,
padeOrder}. */
export function validateActuatorDelay(row) {
  const errors = [];
  let actuator = null;
  if (row.useActuator) {
    const wn = parseFieldValue(POS("wn"), row.wn);
    const zeta = parseFieldValue(POS("zeta"), row.zeta);
    if (wn.error) errors.push(wn.error);
    if (zeta.error) errors.push(zeta.error);
    if (!wn.error && !zeta.error) actuator = { wn: wn.value, zeta: zeta.value };
  }
  let delay_s = 0;
  let pade_order = 2;
  if (row.useDelay) {
    const d = parseFieldValue(NONNEG("delay_s"), row.delaySeconds);
    const p = parseFieldValue(INT_POS("pade_order"), row.padeOrder);
    if (d.error) errors.push(d.error);
    else delay_s = d.value;
    if (p.error) errors.push(p.error);
    else pade_order = p.value;
  }
  return errors.length ? { errors } : { actuator, delay_s, pade_order };
}

/** 지연 칸의 처음 값 — **툴 기본값**이다. 기체 문서(스키마)에 센서·작동기 지연 칸이 없어 고른 기체에서 읽을 수
 *  없다(작동기 wn·ζ는 문서 actuator에서 읽는다 — lib/missiontemplate templateDefaults). 0.035 s = 엔진 항법 오차
 *  모델의 기본 출력 지연 0.03 s(nav/error_model.py delay_s) + 기본 제어주기 100 Hz의 반주기 등가지연 0.005 s. */
export const DELAY_TOOL_DEFAULT = Object.freeze({ delay_s: 0.035, pade_order: 2 });

/** 실행한 지연의 출처 한 마디(validateActuatorDelay 결과) — 지연을 뺐으면 null, 툴 기본값 그대로면 그렇다고
 *  (기체 값이 아니다), 칸을 고쳤으면 「입력값」. 결과 캡션이 지연 수치 옆에 단다. */
export function delaySourceText(ad) {
  if (!(ad?.delay_s > 0)) return null;
  return ad.delay_s === DELAY_TOOL_DEFAULT.delay_s && ad.pade_order === DELAY_TOOL_DEFAULT.pade_order
    ? "툴 기본값 — 기체 문서에 지연 칸이 없어 기체별 값이 아니다"
    : "입력값";
}

// ── 편집 행이 문서 게인을 따라가는가 — 루프마다 (round1 #4) ────────────────────────────────────────────

/** 편집 행을 새 문서 게인 행(seedRows — 지금 격자·「게인 읽을 마하」의 점에서 세운 loopsAt 행)으로 갈아 끼운다 —
 * **루프마다**. 손대지 않은 행(touched 없음)은 같은 이름의 새 문서 행으로 바뀌고, 새 점에서 문서 루프가 사라졌으면
 * (게인 0 등) 함께 빠진다. 손댄 행(편집 표에서 칸을 고쳤거나 「루프 추가」로 만든 행 — touched: true)은 그대로 남는다.
 * 문서 행 중 편집 표에 없는 것은 끝에 붙는다 — 단 사용자가 지운 이름(removed)은 되살리지 않는다.
 *
 * 종전에는 표 전체가 문서 행과 같을 때만 따라갔다(all-or-nothing) — kp 하나를 고친 뒤 격자나 「게인 읽을 마하」를
 * 바꾸면 손대지 않은 루프까지 옛 점의 kp로 굳고, 새 점의 문서 행과 kp 글이 달라져 「손으로 적은 값」으로 불리며
 * 칸별 법칙 게인(gain_source "profile") 대신 옛 kp 하나로 전 칸을 쟀다.
 * 반환은 새 배열(행 객체도 문서 행은 사본). */
export function followDocRows(rows, seedRows, removed = []) {
  const seeds = new Map((seedRows ?? []).map((r) => [r.name, r]));
  const gone = new Set(removed ?? []);
  const out = [];
  for (const r of rows ?? []) {
    if (r.touched) out.push(r);
    else if (seeds.has(r.name)) out.push({ ...seeds.get(r.name) });
    // 손대지 않았는데 새 점에 문서 행이 없다 — 문서를 따라 빠진다
  }
  const have = new Set(out.map((r) => r.name));
  for (const s of seedRows ?? []) {
    if (!have.has(s.name) && !gone.has(s.name)) out.push({ ...s });
  }
  return out;
}

/** 루프 게인 출처를 받았나 — "loading"(카탈로그 대기 — 실행하면 루프 0개로 돈다) · "error" · "ready". */
export function loopLoadState(sources) {
  if (sources == null) return "loading";
  return sources.error ? "error" : "ready";
}

/** 게인 출처를 받는 중일 때 루프 칸의 한 줄 — 비어 있는 표가 「문서에 게인이 없다」로 읽히지 않게. */
export const LOOPS_LOADING_TEXT = "문서 게인을 받는 중 — 루프가 곧 섭니다(지금 [실행]을 누르면 받은 뒤에 겁니다).";

// ── 마진의 뜻 — 나이퀴스트 여유 · 끊는 자리 (엔진 nyquist_margins·broken_loop, e2e D2) ─────────────────

/** 칸의 마진 dict → 이 루프를 닫은 폐루프가 발산하는가(엔진 closed_loop.stable === false). 발산이면 PM·GM은 안정
 * 여유가 아니라 루프 교차의 고전 판독이다 — 칸은 수와 무관하게 부족으로 칠하고 「발산」이라 적는다. */
export function marginUnstable(m) {
  return m?.closed_loop?.stable === false;
}

/** 히트맵 칸 한 장의 {value, text, unstable} — key "pm_deg" | "gm_db". 발산 칸은 value −Infinity(색 판정이 부족으로
 * 가게), 글은 「발산」. 그 밖은 수 그대로(PM은 °, GM은 dB, 서버 "inf"는 ∞). 마진이 없으면 null. */
export function marginCellView(m, key) {
  if (!m) return null;
  if (marginUnstable(m)) return { value: -Infinity, text: "발산", unstable: true };
  const v = m[key];
  if (v === "inf") return { value: "inf", text: key === "pm_deg" ? "∞°" : "∞ dB", unstable: false };
  if (typeof v !== "number") return { value: null, text: "—", unstable: false };
  const s = String(Number(v.toPrecision(3)));
  return { value: v, text: key === "pm_deg" ? `${s}°` : `${s} dB`, unstable: false };
}

/** 폐루프가 발산하는 칸 [{loop, entry, poles}] — 격자 순서. 최악 칸 보고는 이것을 먼저 말한다(수가 좋아 보여도 발산이다). */
export function unstableCells(entries, loops) {
  const out = [];
  for (const e of entries ?? []) {
    if (!e?.trim?.converged) continue;
    for (const lp of loops ?? []) {
      const m = e.margins?.[lp.name];
      if (marginUnstable(m)) out.push({ loop: lp.name, entry: e, poles: m.closed_loop.unstable ?? [] });
    }
  }
  return out;
}

/** 발산 칸을 뺀 칸 목록 사본 — 최악 PM·GM(lib/plot.js marginWorst)을 안정 여유끼리만 비교하게. 발산 칸의 PM·GM은
 * 루프 교차의 판독이라 여유끼리의 최소에 섞으면 「최악 PM 82°」 같은 거짓 안심이 된다(발산은 unstableCells가 말한다). */
export function stableMarginEntries(entries) {
  return (entries ?? []).map((e) => {
    const ms = e?.margins ?? {};
    if (!Object.values(ms).some(marginUnstable)) return e;
    return { ...e, margins: Object.fromEntries(Object.entries(ms).filter(([, m]) => !marginUnstable(m))) };
  });
}

const poleText = ([re, im]) => (im > 0 ? `${g3(re)} ± ${g3(im)}j` : `${g3(re)}`);

/** 진행기 보고 꼬리 — 발산 칸이 있으면 「폐루프 발산 N칸 — pitch_q @ M0.14_h100_f25 (극 +1.97 ± 21.6j)」, 없으면 null. */
export function unstableTail(cells) {
  if (!cells?.length) return null;
  const c = cells[0];
  const p = c.poles?.[0];
  return `폐루프 발산 ${cells.length}칸 — ${c.loop} @ ${c.entry.trim.case.name}${p ? ` (극 ${poleText(p)} rad/s)` : ""}`;
}

/** 결과 캡션(그림 아래) — 칸의 수가 무엇인가. 루프가 없으면 null.
 * ① 끊는 자리: 같은 축의 나머지 루프를 닫고 이 루프를 끊은 개루프(AS94900) — 닫은 루프가 한 칸이라도 있으면 그 이름을.
 * ② 나이퀴스트 여유: PM·GM은 −1까지의 거리(교차가 여럿이면 가장 가까운 것) — 진상 쪽·이득 감소 쪽이 가장 가까운
 *    칸이 있으면 그 개수를 말한다(부호를 부족으로 읽지 않게).
 * ③ 발산 칸이 있으면 그 사실. ④ 게이트와의 관계: 게인 탭의 하드 게이트도 v1.48부터 레이트 루프 GM·PM을 같은
 *    끊는 자리(작동기·지연 포함)에서 잰다(04 §5.3) — 다만 같은 축 레이트 루프만 닫고 루프 대역 교차만 읽으므로
 *    (tune.rate_loop_margins) 칸 값이 게이트와 다를 수 있다. 종전 문구 「게이트가 이 여유를 재지 않는다」는 그
 *    게이트 변경으로 거짓이 됐다. */
export function marginSemanticsText(body) {
  const loops = body?.loops ?? [];
  if (!loops.length) return null;
  const entries = (body.cases ?? []).filter((e) => e?.trim?.converged);
  const closed = new Map();
  let lead = 0;
  let lower = 0;
  for (const e of entries) {
    for (const [name, m] of Object.entries(e.margins ?? {})) {
      if (m?.closed_with?.length) closed.set(name, m.closed_with);
      if (m?.pm_lead) lead += 1;
      if (m?.gm_lower) lower += 1;
    }
  }
  const parts = [];
  if (closed.size) {
    const which = [...closed].map(([n, w]) => `${n}(닫음: ${w.join(", ")})`).join(" · ");
    parts.push(`칸의 PM·GM은 이 루프를 끊고 같은 축의 나머지 루프는 닫은 개루프에서 잰다(AS94900의 끊는 자리) — ${which}.`);
  } else {
    parts.push("칸의 PM·GM은 이 루프 하나를 끊은 개루프에서 잰다(같은 축에 닫아 둘 다른 루프가 없다).");
  }
  let nyq = "PM·GM은 나이퀴스트 선도에서 −1까지의 거리다 — 0 dB·−180° 교차가 여럿이면 가장 가까운 교차의 값이다.";
  const dirs = [];
  if (lead) dirs.push(`${lead}칸은 위상이 앞서는(진상) 쪽이`);
  if (lower) dirs.push(`${lower}칸은 이득을 줄이는 쪽이`);
  if (dirs.length) nyq += ` ${dirs.join(", ")} 가장 가깝다(값은 그 방향의 여유 — 칸을 누르면 보드선도가 방향을 말한다).`;
  parts.push(nyq);
  const bad = unstableCells(body.cases, loops);
  if (bad.length) {
    parts.push(`${bad.length}칸은 이 루프를 닫은 폐루프가 발산한다(「발산」 칸) — 여유가 아니라 결함이다.`);
  }
  parts.push("게인 탭의 하드 게이트도 레이트 루프 GM·PM을 같은 끊는 자리(작동기·지연 포함)에서 잰다(04 §5.3) — 다만 "
    + "같은 축의 레이트 루프만 닫고 루프 대역 교차만 읽으므로(나선·장주기 대역 교차는 뺀다) 칸 값이 게이트와 다를 수 "
    + "있다. 판정선 아래 칸은 실제로 얇은 자리다.");
  return parts.join(" ");
}

/** 보드선도 밑 주석 — 보고한 마진이 어느 교차의 무엇인가(엔진 nyquist_margins 응답). 줄 목록. */
export function bodeMarginNotes(margins) {
  const m = margins ?? {};
  const out = [];
  if (m.closed_with?.length) {
    out.push(`이 곡선은 이 루프를 끊고 같은 축의 ${m.closed_with.join(", ")}를 닫은 개루프다 — 맵의 이 칸과 같은 조립.`);
  }
  if (marginUnstable(m)) {
    const poles = (m.closed_loop.unstable ?? []).map(poleText).join(", ");
    out.push(`⚠ 이 루프를 닫은 폐루프가 발산한다(극 ${poles} rad/s) — 안정 여유는 정의되지 않는다. 표시한 PM·GM은 루프 교차`
      + "(가장 높은 0 dB 교차)와 그에 가장 가까운 −180° 교차의 고전 판독이다(음수면 그 자리에서 이미 넘었다).");
    return out;
  }
  if (m.pm_lead) {
    out.push("PM은 교차점이 −1보다 위쪽(진상 쪽)에 있는 거리다 — 지연이 늘면 오히려 멀어지고, 위상이 그만큼 앞서면 넘는다.");
  }
  if (m.gm_lower) {
    out.push("GM은 이득을 그만큼 줄이면 −1에 닿는 거리다(조건부 안정 — 이득을 올리는 쪽은 더 멀다).");
  }
  const nG = m.crossings?.gain?.length ?? 0;
  const nP = m.crossings?.phase?.length ?? 0;
  if (nG > 1 || nP > 1) {
    const top = [...(m.crossings?.gain ?? [])].sort((a, b) => b.w - a.w)[0];
    out.push(`0 dB 교차 ${nG}개 · −180° 교차 ${nP}개 — 보고한 값은 −1에 가장 가까운 교차다(채운 원). `
      + (top ? `루프 교차(가장 높은 0 dB 교차 ${g3(top.w)} rad/s)의 PM은 ${g3(Math.abs(top.pm_deg))}°다.` : ""));
  }
  return out;
}

/** 칸을 연 보드선도 요청의 닫아 둘 루프 — 결과의 루프 echo 중 그 칸의 closed_with 이름(순서는 결과 echo 순서). */
export function bodeOthers(loops, margins) {
  const names = new Set(margins?.closed_with ?? []);
  return (loops ?? []).filter((l) => names.has(l.name));
}
