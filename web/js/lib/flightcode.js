/** 탑재 C 패널의 순수 로직 — 요청 조립·파일 선택·안내문. DOM·통신 없음.

views/codegen.js가 소비한다. 뷰는 테스트 면제(.claude/verify-fleet-exempt.txt)라
판단이 들어가는 부분은 전부 여기 둔다.

기존 "코드 생성"(파라미터 표현)과 다른 물건이다 — 여기 대상은 **FCC에 통합되어
그대로 실릴 제어법칙 코드**이고 구조·블록 로직·파라미터가 전부 들어 있다.
생성은 엔진이 한다(POST /codegen/flight) — 웹이 C를 조립하지 않는다.
*/

/** 코드 생성 대상이지만 **제어법칙이 아닌** 블록 — 탑재 C에 없는 것이 정상이다.
 * 작동기·센서는 플랜트(M5), 항법은 M6이고 우리가 내는 것은 제어법칙 한 덩이다
 * (02 §1 — FCC 전체는 범위 밖). 화면이 이걸 말해 주지 않으면 "왜 내가 고친 게
 * 코드에 없지?"가 된다. */
export const NOT_IN_LAW = {
  "actuator/SecondOrderActuator": "작동기 — 플랜트(M5)이고 FCC 밖입니다",
  "nav/ErrorModel": "항법 오차 모델 — M6이고 실기에선 항법 장비가 대신합니다",
};

export const AP_KEY = "fcl/Autopilot";
export const SCAS_KEY = "fcl/ScasAxis";

/** SCAS 축 — 서버 req.scas가 **세 축 전부**를 요구한다(부분 주입은 422). 그래서
 * 한 축만 띄운 패널(블록도 축 페이지의 [코드 생성])은 scas를 아예 안 보내고 설계
 * 기본 형상을 보여 준다 — 422를 띄우는 것보다 낫고, 그 패널이 말할 수 있는 것도
 * 그 축 하나뿐이다. 축 이름의 정본은 엔진(fcl/graphs.py SCHEDULABLE)이고 서버가
 * 최종 판정한다 — 여기 목록이 낡으면 스냅샷이 조용히 scas를 빼먹는다. */
export const SCAS_GROUPS = ["pitch", "roll", "yaw"];

/** 진입점 — 목록이 바뀌어도 여기로 떨어지면 항상 읽을 게 있다. */
export const ENTRY = (artifact = "fcl") => `${artifact}.h`;

/** 코드 패널 스펙 + 적용된 게인 테이블 → POST /codegen/flight 요청 본문.
 *
 * 게인 스케줄이 있으면 함께 넘긴다 — 스케줄 유무가 **구조**를 바꾸므로(파일 하나가
 * 통째로 생기고 사라진다) 빼먹으면 실제와 다른 형상을 보여 주게 된다.
 *
 * 게인 쪽은 3-상태다. 셋을 뭉뚱그리면 조용히 다른 형상이 나온다:
 *   테이블 있음    → gain_tables (키 집합이 곧 스케줄 대상)
 *   scheduleOff    → with_schedule:false — 스케줄이 **없는** 형상
 *   둘 다 아님     → 아무것도 안 보냄 — 서버의 설계 기본(6자리)
 * 빈 dict를 보내는 선택지는 없다. 서버가 422로 막는다(조용한 무스케줄 방지).
 *
 * SCAS는 축 스펙 셋이 모두 있을 때만 싣는다 (SCAS_GROUPS 주석 참조). */
export function flightRequest(
  specs, gainTables, { controlHz = 100, scheduleOff = false } = {},
) {
  const req = { control_hz: controlHz };
  const ap = (specs ?? []).find((s) => s.key === AP_KEY);
  if (ap && ap.values && Object.keys(ap.values).length > 0) {
    req.autopilot = { ...ap.values };
  }
  const scas = {};
  for (const s of specs ?? []) {
    if (s.key === SCAS_KEY && s.group && s.values) scas[s.group] = { ...s.values };
  }
  if (SCAS_GROUPS.every((g) => scas[g])) req.scas = scas;
  if (scheduleOff) {
    // 테이블과 함께 보내면 엔진이 구성 오류로 거부한다 (demo.py make_demo_fcl)
    req.with_schedule = false;
  } else if (gainTables && Object.keys(gainTables).length > 0) {
    req.gain_tables = gainTables;
  }
  return req;
}

/** 이 패널의 스펙 중 탑재 C에 안 들어가는 것 — [{key, why}]. */
export function excludedSpecs(specs) {
  return (specs ?? [])
    .filter((s) => NOT_IN_LAW[s.key])
    .map((s) => ({ key: s.key, why: NOT_IN_LAW[s.key] }));
}

/** 표시할 파일 고르기 — 기억해 둔 선택이 사라졌으면(스케줄을 끄면 fcl_sched.c가
 * 없어진다) 진입점으로 떨어진다. 빈 목록이면 null. */
export function pickFile(files, wanted, artifact = "fcl") {
  if (!files || files.length === 0) return null;
  return (
    files.find((f) => f.name === wanted)
    ?? files.find((f) => f.name === ENTRY(artifact))
    ?? files[0]
  );
}

/** 역할별로 묶은 파일 — [{role, files}]. 서버가 준 읽는 순서를 그대로 유지한다.
 *
 * 파일 16개를 한 줄에 늘어놓으면 무엇이 무엇인지 안 보인다 — 진입점·자료형·
 * 조립부·서브시스템·데이터·런타임이라는 역할이 곧 읽는 단위다. */
export function groupByRole(files) {
  const out = [];
  for (const f of files ?? []) {
    const last = out[out.length - 1];
    if (last && last.role === f.role) last.files.push(f);
    else out.push({ role: f.role, files: [f] });
  }
  return out;
}

/** 전 파일을 읽기용 한 문서로 이어붙인다.
 *
 * **빌드 단위가 아니다** — 실제 산출물은 파일 여럿이고 이건 통째로 읽거나
 * 넘길 때 쓰는 열람본이다. 그 사실을 문서 머리에 박아 두지 않으면 이걸
 * 컴파일하려 드는 사람이 반드시 나온다. */
export function mergeFiles(data) {
  if (!data || !data.files || data.files.length === 0) return "";
  const { count, lines } = summarize(data.files);
  const bar = "═".repeat(70);
  const head = [
    `/* ${bar}`,
    `   CLAW 탑재 제어법칙 C — 통합 열람본 (${data.artifact})`,
    `   형상 지문 ${data.fingerprint} · 제어주기 ${data.dt} s`,
    `   파일 ${count}개 · ${lines}줄`,
    "",
    "   실제 산출물은 아래 파일들이고, 이 문서는 읽기 편하도록 이어붙인",
    "   열람본이다 — 그대로 컴파일하는 빌드 단위가 아니다.",
    "   순서: 진입점 → 자료형 → 조립부 → 서브시스템(실행 순서)",
    "         → 파라미터 데이터 → 공용 런타임",
    `   ${bar} */`,
  ];
  const body = data.files.flatMap((f) => [
    "",
    `/* ${"─".repeat(24)} ${f.name} · ${f.role} · ${f.lines}줄 ${"─".repeat(24)} */`,
    "",
    f.text.replace(/\n+$/, ""),
  ]);
  return head.concat(body).join("\n") + "\n";
}

/** 파일 목록 요약 — "12개 파일 · 693줄" 같은 한 줄. */
export function summarize(files) {
  const list = files ?? [];
  return {
    count: list.length,
    lines: list.reduce((n, f) => n + (f.lines ?? 0), 0),
  };
}
