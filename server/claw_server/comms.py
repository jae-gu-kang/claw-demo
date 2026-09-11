"""교신 대본 준비 — sim 결과의 비행 로그 추출·프롬프트·출력 스키마 (순수 로직).

LLM 호출은 routes/llm.py에 있다(아웃바운드 단일 함수 선언 유지 — 여기는 httpx를
모른다). 여기 있는 것은 "무엇을 보낼 것인가": 최대 54MB짜리 sim 본문에서
관제 교신 대본이 설 수 있는 **유계 비행 로그**(≤4KB, brief.py와 같은 자로
잰다 — `exceeds` 공유)를 뽑는다.

brief.py에 더하지 않는 이유: brief는 "kind 무관·도메인 로직 아님"을 자기선언하고
sim 시계열을 통째 배제하는데, 교신은 바로 그 시계열의 **이벤트**가 필요하다 —
같은 파일에 두면 그 선언이 거짓이 된다.

## 계약 (test_comms.py가 지킨다)

- 접지·정지·사출 수치는 **meta.phases 값만** 쓴다 — 신호에서 재계산하지 않는다
  (stride 솎임이 −0.98을 −0.74로 보이게 한 웹 replay.js 사고의 서버판 방지).
  phases가 null이면 그 이벤트를 **내지 않는다** — 0초 접지로 위장하지 않는다.
- 뜬 엔벨로프 플래그는 **이름별로** 낸다 — any_flag 하나로 뭉개면 기준면 이탈이
  공력 DB 이탈로 오독된다 (웹 flaggedNames 규약).
- 표본은 시각 균등 stride + **모드 경계·이벤트 시각 강제 포함** — 균등만 쓰면
  0.25 s짜리 레일 구간이 통째로 빠진다. 솎은 사실은 `_n`/`_omitted`/`_stride`로
  데이터에 남는다 (brief 1층과 같은 정직성 마커).
- 결측 규약 승계: NaN→null·±inf→"inf" 문자열(serialize 정책)을 그대로 받아내고,
  값을 지어내지 않는다.
"""

import json
import math
from bisect import bisect_left

from claw_server.brief import exceeds

LOG_BUDGET = 4096       # brief KEEP_WHOLE_BYTES와 같은 급 — LLM에 싣는 축약의 자
TARGET_SAMPLES = 24     # 균등 표본 목표 — 예산 초과 시 축소 계획을 따라 줄인다
_MAX_LIMITER_SPANS = 10
_NAME_MAX = 40          # 모드 이름 표시 상한 — 이름은 사용자 입력이라 길이 무제한이다

# 예산 축소 계획 (표본 목표, 스팬 상한, 전이 이벤트 상한) — 순서대로 시도한다.
# 표본만 줄이는 것으로는 부족하다: 두 모드가 프레임마다 번갈아 드는 채터링 런
# (한계 접근 — 이 기능이 가장 필요한 종류의 런)에서는 modes 행과 스팬 강제
# 포함이 스팬 수만큼 자라 예산을 1.9MB까지 뚫는다(리뷰 재현). 마지막 계획은
# 어떤 입력에서도 유계다 — 모든 목록이 상수 상한을 갖는다.
_PLANS = ((TARGET_SAMPLES, 40, 40), (12, 20, 20), (6, 10, 10), (3, 6, 6), (0, 4, 4))


def _short(name):
    """표시용 이름 절단 — 미션 스펙의 모드 이름은 길이 상한이 없다."""
    if isinstance(name, str) and len(name) > _NAME_MAX:
        return name[:_NAME_MAX] + "…"
    return name


def _num(v):
    """수치면 float, 아니면 None — None·"inf" 문자열·bool을 수치로 위장하지 않는다."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def _r(v, digits):
    """반올림 — 유일한 실효 크기 레버다(0.9203377…의 꼬리가 예산을 먹는다).
    수치가 아니면(None·"inf") 그대로 — 값 위장 금지."""
    f = _num(v)
    if f is None:
        return v if isinstance(v, str) else None
    return round(f, digits)


def mode_spans(modes):
    """모드 문자열 시계열 → 연속 구간 [{mode, i0, i1}] (i1 배타).

    웹 lib/replay.js modeSpans와 같은 어휘 — 두 화면(시뮬 재생·교신)이 같은
    구간을 말해야 대조가 된다. 값은 미션 스펙의 모드 이름 그대로다(정수 코드 없음).
    """
    out = []
    for i, m in enumerate(modes):
        if out and out[-1]["mode"] == m:
            out[-1]["i1"] = i + 1
        else:
            out.append({"mode": m, "i0": i, "i1": i + 1})
    return out


def _bool_spans(arr):
    """참 구간 [(i0, i1)] (i1 배타) — bool 시계열을 배열로 싣지 않기 위한 접기."""
    out = []
    for i, v in enumerate(arr):
        if v:
            if out and out[-1][1] == i:
                out[-1][1] = i + 1
            else:
                out.append([i, i + 1])
    return [(a, b) for a, b in out]


def _idx_at(t, tv):
    """시각 → 최근접 표본 인덱스 (t 오름차순 전제 — arange 산)."""
    if not t:
        return None
    k = bisect_left(t, tv)
    if k <= 0:
        return 0
    if k >= len(t):
        return len(t) - 1
    return k if abs(t[k] - tv) < abs(t[k - 1] - tv) else k - 1


def _run_info(meta, payload):
    """실행 개요 — null 필드는 담지 않는다 (없는 것을 없다고 말하는 쪽은 이벤트다)."""
    out = {}
    for key in ("case", "t_end", "nav", "aborted"):
        v = meta.get(key)
        if v is not None:
            out[key] = v
    rw = meta.get("runway")
    if isinstance(rw, dict):
        out["runway"] = {k: rw.get(k) for k in ("elevation", "heading", "length")
                         if rw.get(k) is not None}
    la = meta.get("launch")
    if isinstance(la, dict):
        out["launch"] = {k: la.get(k) for k in ("elev_angle", "exit_speed")
                         if la.get(k) is not None}
    og = meta.get("origin")
    if isinstance(og, dict):
        out["origin"] = {k: og.get(k) for k in ("lat", "lon") if og.get(k) is not None}
    wps = meta.get("waypoints")
    if isinstance(wps, list):
        out["waypoints_n"] = len(wps)
    if meta.get("accept_radius") is not None:
        out["accept_radius"] = meta.get("accept_radius")
    out["n_total"] = payload.get("n_total") or len(payload.get("t") or [])
    return out


def _mode_rows(t, sig, spans, dropped):
    h = sig.get("h") or []
    v = sig.get("V") or []

    def at(arr, i):
        return _r(arr[i], 1) if i < len(arr) else None

    rows = []
    for s in spans:
        i0, i1 = s["i0"], s["i1"] - 1
        rows.append({
            "mode": _short(s["mode"]),
            "t0": _r(t[i0], 2) if i0 < len(t) else None,
            "t1": _r(t[i1], 2) if i1 < len(t) else None,
            "h0": at(h, i0), "h1": at(h, i1),
            "V0": at(v, i0), "V1": at(v, i1),
        })
    if dropped > 0:  # 자른 사실을 데이터에 남긴다 — 조용한 절단 금지
        rows.append({"_omitted_spans": dropped})
    return rows


def _env_scalars(env):
    """엔벨로프 스칼라 — 있는 키만, 값은 그대로("inf" 문자열 포함 — 위장 금지)."""
    return {k: env[k] for k in ("worst_margin", "worst_margin_t", "min_alt",
                                "min_alt_t", "any_flag", "first_flag_t")
            if k in env}


def _events(t, sig, env, meta, spans, trans_cap, dropped_spans):
    """이벤트 목록 + 표본에 강제 포함할 인덱스 집합. spans는 호출자가 이미
    상한을 걸었고(dropped_spans = 잘린 수), 전이 이벤트는 trans_cap이 한 번 더
    건다 (_PLANS 축소 대상)."""
    n = len(t)
    events = []
    forced = set()
    phases = meta.get("phases") or {}

    def phase_t(key):
        return _num(phases.get(key))

    le = phase_t("launch_exit_t")
    if le is not None:
        ev = {"t": round(le, 2), "kind": "launch_exit"}
        gx = [g for g in map(_num, sig.get("launch_gx") or []) if g is not None]
        if gx:
            ev["peak_gx"] = round(max(gx), 1)
        events.append(ev)
        k = _idx_at(t, le)
        if k is not None:
            forced.add(k)

    trans = spans[1:]
    for prev, cur in zip(spans, trans[:trans_cap]):
        i0 = cur["i0"]
        events.append({"t": _r(t[i0], 2) if i0 < n else None, "kind": "mode",
                       "note": f"{_short(prev['mode'])} → {_short(cur['mode'])}"})
        forced.add(i0)
    # 스팬 상한이 이미 잘라낸 전이 + 여기서 더 잘린 전이 — 자르면 말한다
    omitted_trans = dropped_spans + max(len(trans) - trans_cap, 0)
    if omitted_trans > 0:
        events.append({"kind": "note",
                       "note": f"모드 전이 {omitted_trans}건 생략 — 구간이 과도하게 잦다(채터링)"})

    wt = _num(env.get("worst_margin_t"))
    if wt is not None:
        events.append({"t": round(wt, 2), "kind": "worst_stall_margin",
                       "value": _r(env.get("worst_margin"), 3)})
        forced.add(_idx_at(t, wt))

    td = phase_t("touchdown_t")
    if td is not None:
        # 수치는 phases 그대로 — 신호 재계산 금지 (모듈 머리말)
        ev = {"t": round(td, 2), "kind": "touchdown",
              "sink_rate": _r(phases.get("td_sink_rate"), 2),
              "speed": _r(phases.get("td_speed"), 1)}
        rw = meta.get("runway") if isinstance(meta.get("runway"), dict) else None
        k = _idx_at(t, td)
        pn = sig.get("pn") or []
        pe = sig.get("pe") or []
        if rw is not None and k is not None and k < min(len(pn), len(pe)):
            hdg = _num(rw.get("heading"))
            n_ = _num(pn[k])
            e_ = _num(pe[k])
            if hdg is not None and n_ is not None and e_ is not None:
                # 활주로 축 좌표 — landingSummary와 같은 기하 (원점=남단 임계).
                # 위치는 phases가 아니라 접지 시각의 최근접 표본에서 온다 —
                # 전해상도 본문이라 오차가 dt 한 칸이지만, 그 사실은 사실이다
                ev["along"] = round(n_ * math.cos(hdg) + e_ * math.sin(hdg), 1)
                ev["cross"] = round(-n_ * math.sin(hdg) + e_ * math.cos(hdg), 1)
        events.append(ev)
        if k is not None:
            forced.add(k)

    mt = _num(env.get("min_alt_t"))
    if mt is not None:
        events.append({"t": round(mt, 2), "kind": "min_alt",
                       "value": _r(env.get("min_alt"), 1)})
        forced.add(_idx_at(t, mt))

    st = phase_t("stop_t")
    if st is not None:
        ev = {"t": round(st, 2), "kind": "stop"}
        pn = sig.get("pn") or []
        pe = sig.get("pe") or []
        if td is not None and pn and pe:
            k0, k1 = _idx_at(t, td), _idx_at(t, st)
            if k0 is not None and k1 is not None and k1 < min(len(pn), len(pe)) \
                    and k0 < min(len(pn), len(pe)):
                a = (_num(pn[k1]), _num(pe[k1]), _num(pn[k0]), _num(pe[k0]))
                if all(x is not None for x in a):
                    ev["rollout_m"] = round(math.hypot(a[0] - a[2], a[1] - a[3]))
        events.append(ev)
        forced.add(_idx_at(t, st))

    # bool 시계열은 t 길이로 자른다 — 신호가 t보다 길어도 인덱스가 새지 않게
    limiter = (sig.get("limiter_active") or [])[:n]
    lim_spans = _bool_spans(limiter)
    for i0, i1 in lim_spans[:_MAX_LIMITER_SPANS]:
        events.append({"kind": "limiter", "t0": _r(t[i0], 2), "t1": _r(t[i1 - 1], 2)})
        forced.add(i0)
    if len(lim_spans) > _MAX_LIMITER_SPANS:  # 자르면 말한다 — 전이 생략과 같은 규약
        events.append({"kind": "note",
                       "note": f"리미터 구간 {len(lim_spans) - _MAX_LIMITER_SPANS}건 생략"})

    # 뜬 플래그만 이름과 첫 시각으로 — any_flag로 뭉개지 않는다 (머리말)
    for name, arr in (env.get("flags") or {}).items():
        first = next((i for i, v in enumerate(arr[:n]) if v), None)
        if first is not None:
            events.append({"t": _r(t[first], 2), "kind": "flag", "name": name})
            forced.add(first)

    forced.discard(None)

    # note류(설명 이벤트)는 맨 뒤 — 설명 대상보다 먼저 오면 읽기가 뒤집힌다
    def sort_key(e):
        v = e.get("t")
        if v is None:
            v = e.get("t0")
        return v if isinstance(v, (int, float)) else float("inf")

    events.sort(key=sort_key)
    return events, forced


def _samples(t, sig, env, spans, forced, target):
    fields = ["t", "mode", "h", "V", "hdot", "theta", "phi", "stall_margin"]
    n = len(t)
    if n == 0 or target <= 0:
        return {"fields": fields, "rows": [], "_n": n, "_omitted": n, "_stride": None}
    stride = max(1, -(-n // target))
    idxs = set(range(0, n, stride))
    idxs.add(n - 1)
    idxs.update(s["i0"] for s in spans)
    idxs.update(i for i in forced if isinstance(i, int) and 0 <= i < n)
    modes = (sig.get("mode") or [])[:n]
    h = sig.get("h") or []
    v = sig.get("V") or []
    hdot = sig.get("hdot") or []
    theta = sig.get("theta") or []
    phi = sig.get("phi") or []
    sm = (env.get("stall_margin") or [])  # signals의 alpha_margin과 다른 것

    def at(arr, i, d):
        return _r(arr[i], d) if i < len(arr) else None

    rows = [[_r(t[i], 2),
             _short(modes[i]) if i < len(modes) else None,
             at(h, i, 1), at(v, i, 1), at(hdot, i, 1),
             at(theta, i, 3), at(phi, i, 3), at(sm, i, 3)]
            for i in sorted(idxs)]
    return {"fields": fields, "rows": rows,
            "_n": n, "_omitted": max(n - len(rows), 0), "_stride": stride}


def flight_log(payload: dict) -> dict:
    """sim 본문 → 유계 비행 로그. 예산을 넘으면 _PLANS를 따라 표본·스팬·전이를
    함께 줄인다 — 줄일수록 `_omitted`/`_omitted_spans`가 커져 자른 사실이
    저절로 데이터에 남고, 마지막 계획은 어떤 입력에서도 상수 상한이다."""
    t = payload.get("t") or []
    n = len(t)
    sig = payload.get("signals") or {}
    env = payload.get("envelope") or {}
    meta = payload.get("meta") or {}
    # 모드는 t 길이로 자른다 — 신호가 t보다 길어도 t[i]가 새지 않게 (결측 내성)
    spans_all = mode_spans((sig.get("mode") or [])[:n])
    run = _run_info(meta, payload)
    env_sc = _env_scalars(env)
    log = None
    for target, span_cap, trans_cap in _PLANS:
        spans = spans_all[:span_cap]
        events, forced = _events(t, sig, env, meta, spans, trans_cap,
                                 len(spans_all) - len(spans))
        log = {
            "run": run,
            "modes": _mode_rows(t, sig, spans, len(spans_all) - len(spans)),
            "events": events,
            "envelope": env_sc,
            "samples": _samples(t, sig, env, spans, forced, target),
        }
        if not exceeds(log, LOG_BUDGET):
            break
    return log


# ── LLM 출력 스키마 — {lines:[{t, speaker, text}], warnings} ────────────────
# speaker가 enum인 이유: 자유 문자열이면 같은 대본에서 "관제탑"/"TOWER"/"Tower"가
# 섞여 화면이 화자별 표기·정렬을 못 준다 (_LON_AXES·_EXIT_KINDS 선례).
# t가 number인 이유: 폼 칸이 아니라 시각 정렬 키다 (초안 스키마와 다른 자리).
COMMS_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "t": {"type": "number"},
                    "speaker": {"type": "string", "enum": ["TOWER", "UAV"]},
                    "text": {"type": "string"},
                },
                "required": ["t", "speaker", "text"],
                "additionalProperties": False,
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["lines", "warnings"],
    "additionalProperties": False,
}

COMMS_SYSTEM = """너는 CLAW 비행제어 설계툴 가상환경의 관제 교신 작가다. 무인기
시뮬레이션 런 하나의 비행 로그를 받아, 그 비행을 따라가는 관제탑–기체 교신
대본을 쓴다. 대본은 3D 재생 위에 자막으로 흐르고 음성으로도 읽힌다.

## 화자와 문체
- speaker "TOWER" = 고흥 타워 관제사, "UAV" = 무인기 (콜사인 CLAW-01, 지상
  운용자가 대신 송신하는 설정).
- 실제 관제 교신처럼 짧고 규범적으로: 콜사인 먼저, 지시·복창·보고. 한국어
  관제 용어를 쓰되 수치는 로그의 단위 그대로 말한다(고도 m MSL, 속도 m/s).
- 8~20줄. 이륙(발사)·상승·순항 진입·접근·착륙 허가·접지·정지 같은 국면
  전환마다 한두 줄 — 로그의 modes/events가 그 국면이다.

## 규칙 (위반하면 화면이 거짓말을 하게 된다)
1. 수치·시각·사건은 준 로그에 있는 것만 쓴다 — 지어내지 않는다.
2. t는 로그에 있는 시각(events의 t, samples의 t)에서 고르고 **오름차순**이어야
   한다. 그 시각 부근에서 실제로 일어나는 일을 말한다.
3. `_n`·`_omitted`·`_stride` 마커는 표본을 솎았다는 뜻이다 — 표본 사이 구간을
   단정하지 않는다.
4. run.aborted가 있으면 교신이 반드시 그 중단을 드러낸다 (정상 종료 연기 금지).
5. events의 flag는 엔벨로프 감시다 — alpha/beta/mach는 공력 DB 유효범위 이탈,
   altitude는 기준면(활주로 표고) 여유 상실. limiter는 α 리미터 개입 구간.
   touchdown의 sink_rate는 하강 −, along/cross는 활주로 축 좌표(남단 임계 원점).
6. "inf"/"-inf"는 비유한값의 직렬화다 — 수치로 읽지 않는다.
7. warnings에는 로그가 부족해 말하지 못한 것을 적는다 (없으면 빈 배열)."""


def comms_user(meta: dict, log: dict) -> str:
    """LLM 사용자 메시지 — 메타(종류·시각·지문)와 비행 로그."""
    return (
        "다음 시뮬레이션 런의 관제 교신 대본을 써라.\n"
        f"메타: {json.dumps(meta, ensure_ascii=False)}\n"
        f"비행 로그: {json.dumps(log, ensure_ascii=False)}"
    )
