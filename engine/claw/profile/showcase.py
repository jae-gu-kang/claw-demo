"""쇼케이스 기체 문서 생성 — 툴이 내는 법칙 절을 툴로 채운다 (δe_trim → 초기 게인 → 자동 설계 → 게인 표 반영).

쇼케이스 기체(document.py `load_showcase`, examples/showcase_delta.json)의 값 중 **툴이 도출하는 것**은 손으로
적지 않는다 — 기체 고정 금지 원칙대로 예제 게인을 조용히 물려주지 않는다. 사람이 정하는 칸(공력·질량·추진·
한계·지상장치·미션 템플릿)은 문서에 있고, 이 모듈은 그 문서에서 서버·웹이 쓰는 **같은 엔진 함수**를 같은
순서·같은 인자로 불러 법칙 절을 채운다:

1. de_trim — δe_trim 표 도출(profile.derive.derive_de_trim). 서버 POST /profiles/{id}/derive-de-trim과 같은
   인자(기본 문서 + 형상 변형 전부, 검사 간격 기본값)이고 law.alloc를 통째로 바꾼다(서버 잡과 같다).
2. seed — 초기 게인 빠른 탐색(design.seed.quick_seed, 확인 평가 sim_check 켬). 서버 POST
   /profiles/{id}/quick-seed와 같다: 채택(ok)일 때만 law.design을 쓰고, 옛 확정 게인 표는 지운다(새 설계의
   출발). seed="basis"면 산출 근거 직행(design.basis.apply_seed_basis — 설계 마하·해면·연료 절반, 웹 기체 탭
   산출 근거 기본 조건과 같은 점. 설계 마하가 없는 문서는 미션 템플릿 순항 속도의 해면 마하 — basis_point)이다.
3. design — 자동 설계(design.DesignSession, 기본값 위 덧씀 — design_overrides). 승인 대기면 웹 [승인 반영 재개]의
   기본 체크(봉인·건너뜀이 아닌 처방 전부)로 재개하고, 재개마다 서버처럼 세션을 저장 형식으로 왕복시킨다.
   끝나면 반출 표(tables_resampled — 다항은 재샘플)를 law.gain_tables로 — 서버 POST /design/{id}/apply-gains와
   같은 표·같은 출처 칸(재샘플 허용치·오차·재검증 요약·기준 지문). 표는 기본 문서에서 확정되므로 문서를 바꾸는
   형상 변형에서는 낡음이라 조립이 거부한다 — 그 변형은 패치로 표를 비워 규칙 스케줄로 날게 한다
   (rule_schedule_variants — 확정 표는 기본형 설계 결과, 변형은 도구가 도출한 설계 게인 × q̄ 역비 스케줄).

출처(provenance)에는 서버가 적는 칸에 더해 generator를 적는다. 서버만 아는 칸(잡 id·결과 id·기준 리비전·
반영 시각)은 적지 않는다 — 결과 저장소가 없고, 시각을 적으면 같은 입력에서 같은 파일이 나오지 않는다.

같은 입력이면 같은 파일이다(바이트 단위). 자기 출력에 다시 돌려도 같다 — δe_trim 표·설계를 이 생성기가 **빈 자리에서**
만들었으면(출처 grid_input·seed_input "none") 다시 돌릴 때 그 자리를 비우고 처음부터 잰다. 그래서 패키지 JSON의
사람 몫 칸을 고친 뒤 `--write`를 다시 부르면 처음부터 돌린 것과 같은 문서가 나온다.

반출 표 조립(_gain_export)은 서버 routes/design.py `_gain_export`·`_reverify_summary`와 같은 규칙의 사본이다 —
엔진이 서버를 import할 수 없어서다. 두 곳이 갈리면 생성 문서가 웹 [문서에 반영]과 다른 표를 싣는다.

시드 경로와 자동 설계 설정은 인자로 고르고(--seed, --design-config), 인자가 없으면 입력 문서에 이 생성기가 남긴
출처(설계 출처 source, 확정 표 출처의 design.config)를 따른다 — 쇼케이스 문서는 산출 근거 직행(basis)과 문서가
적어 둔 설계 목표로 만들어졌고, 인자 없이 --write를 다시 불러도 그 길을 그대로 밟는다.

CLI: `python -m claw.profile.showcase [--write] [--stages de_trim seed design]` — 패키지 JSON을 읽어 단계를 돌리고
요약을 찍는다. --write면 같은 자리에 정규 형식(document_text)으로 다시 쓴다(--out이면 그 경로에).
"""

import argparse
import copy
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

from claw.profile.build import build_profile
from claw.profile.document import _SHOWCASE_FILE, SHOWCASE_ID
from claw.profile.errors import ProfileError
from claw.profile.schema import validate_document

GENERATOR = "claw.profile.showcase"
STAGES = ("de_trim", "seed", "design")
# 툴이 낸 설계 게인의 출처 — 빠른 탐색(design.seed.SEED_SOURCE)과 산출 근거 직행(design.basis가 적는 값)
SEED_SOURCES = ("quick_seed", "seed_basis")
# 자동 설계 덧씀 중 **기체 값이 아닌** 예산·밀도 [기본값] — 고도·연료 격자는 문서에서 뽑는다(design_overrides).
# 이터 3: 처방 두 바퀴를 받고 끝낸다(가벼운 설정 — 쇼케이스 진행기의 자동 설계 단계와 같은 결)
DESIGN_BUDGET = {"n_mach": 5, "budget_iters": 3}
# 승인·재개 상한 — 웹 views/autodesign.js MAX_APPROVAL_ROUNDS와 같은 값(엔진 이터 예산이 먼저 끊는다)
MAX_APPROVAL_ROUNDS = 20
# 반출 재샘플 허용치 — 서버 routes/design.py _RESAMPLE_TOL과 같은 값(보고한 값과 쓴 값이 같아야 한다)
RESAMPLE_TOL = 0.01
_RESAMPLE_PROBE = 401  # 재샘플 오차 재측정 격자 — routes/design.py _RESAMPLE_PROBE와 같다
# 형상 변형이 확정 표를 비우는 자리 — 그 변형은 규칙 스케줄(build.gain_tables)로 조립된다
GAIN_TABLES_PTR = "/law/gain_tables"


class ShowcaseError(RuntimeError):
    """단계가 채택할 결과를 못 냈다 — 어느 단계인지(stage)와 사유. 조용히 건너뛰지 않는다."""

    def __init__(self, stage: str, message: str, detail=None):
        super().__init__(f"[{stage}] {message}")
        self.stage, self.message, self.detail = stage, message, detail


def packaged_path() -> Path:
    """패키지 쇼케이스 JSON의 소스 트리 경로 — --write가 쓰는 자리(로더가 읽는 그 파일)."""
    return Path(__file__).resolve().parent / _SHOWCASE_FILE


def document_text(doc: dict) -> str:
    """정규 형식 — 검증된 문서의 키 순서, 들여쓰기 2, 한글 그대로, 끝 줄바꿈(예제 파일과 같은 모양).

    비유한 수는 거부한다(allow_nan=False) — NaN이 새면 저장소·브라우저가 못 읽는 JSON이 된다."""
    return json.dumps(doc, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def _plain(v):
    """출처에 싣는 값 — numpy 수는 파이썬 수로, 비유한 수는 null(design.seed._clean과 같은 규칙)."""
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if isinstance(v, (bool, str)) or v is None:
        return v
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return f if math.isfinite(f) else None
    return v


# ── 1. δe_trim ─────────────────────────────────────────────────────────────


def _own(section) -> dict | None:
    """이 생성기가 쓴 절의 출처(생성기 표시가 있으면) — 없으면 None."""
    prov = (section or {}).get("provenance")
    return prov if isinstance(prov, dict) and prov.get("generator") == GENERATOR else None


def _stage_de_trim(doc: dict, log) -> tuple:
    from claw.profile.derive import CHECK_STEP, derive_de_trim

    # 다시 돌리면 처음 돌린 자리에서 — 도출은 문서 표의 마하 격자를 이어 쓰므로(서버 잡과 같다), 이 생성기가 표 없이
    # 시작해 만든 표면 표를 비우고 다시 잰다. 안 그러면 두 번째 실행이 첫 실행이 잘라 낸 격자에서 시작해 출처(잘린
    # 격자점)가 달라진다 — 같은 입력에서 같은 파일이 나와야 한다
    own = _own(doc["law"]["alloc"]["de_trim"] if doc["law"]["alloc"] else None)
    if own is not None and own.get("grid_input") == "none":
        doc = copy.deepcopy(doc)
        doc["law"]["alloc"]["de_trim"] = None
    grid_input = "document" if doc["law"]["alloc"] and doc["law"]["alloc"]["de_trim"] else "none"
    built = build_profile(doc, validated=True)
    variants = [build_profile(doc, v["id"], validated=True) for v in doc["variants"]]
    out = derive_de_trim(built, variants=variants, check_step=CHECK_STEP)
    if not out["ok"]:
        raise ShowcaseError("de_trim", out["reason_text"] or out["reason"])
    alloc = copy.deepcopy(out["alloc"])
    alloc["de_trim"]["provenance"].update(generator=GENERATOR, grid_input=grid_input)
    new = copy.deepcopy(doc)
    new["law"]["alloc"] = alloc
    t = alloc["de_trim"]["table"]
    prov = alloc["de_trim"]["provenance"]
    log(f"  표 {len(t['axes']['mach'])}점 M{t['axes']['mach'][0]:g}–{t['axes']['mach'][-1]:g} · "
        f"{math.degrees(max(t['data'])):.2f}°→{math.degrees(min(t['data'])):.2f}° · 검사 {len(out['requirement']['mach'])}점 · "
        f"부족 {prov['shortfall']} · 보정 {prov['iterations']}회 · 형상 {prov['configurations']}")
    return new, {"table": t, "shortfall": prov["shortfall"], "iterations": prov["iterations"],
                 "excluded_trims": prov["excluded_trims"], "configurations": prov["configurations"]}


# ── 2. 초기 게인 ───────────────────────────────────────────────────────────


def basis_point(doc: dict) -> tuple:
    """산출 근거 직행의 트림점 (마하, 고도, 연료) — 웹 기체 탭 산출 근거의 기본 조건(설계 마하·고도 0·연료 절반).

    스케줄이 없는 문서(게인 미설계 — 스키마가 설계 없는 스케줄을 막는다)는 설계 마하가 없으므로 미션 템플릿 순항
    속도의 해면 마하를 쓴다(기체가 실제로 나는 점). 둘 다 없으면 사유와 함께 실패한다 — 마하를 지어내지 않는다."""
    from claw.env import isa_atmosphere

    fuel = doc["mass"]["fuel_max"] * 0.5
    sched = doc["law"]["schedule"]
    if sched is not None:
        return float(sched["m_design"]), 0.0, fuel
    cruise = ((doc.get("mission_template") or {}).get("sim") or {}).get("cruise")
    if not cruise:
        raise ShowcaseError("seed", "산출 근거 직행 점을 못 정한다 — 설계 마하(law.schedule)도 미션 템플릿 순항 속도도 없다")
    return round(cruise["speed"] / isa_atmosphere(0.0).a, 4), 0.0, fuel


def _stage_seed(doc: dict, log, *, seed: str, sim_check: bool) -> tuple:
    # 다시 돌리면 처음 돌린 자리에서 — 탐색은 문서의 설계가 있으면 그 설계의 비유도 칸(명령필터 시정수·자세 한계·
    # 워시아웃)을 이어 쓰고 출처를 「document」로 적는다. 이 생성기가 설계 없이 시작해 쓴 설계면 설계·스케줄·확정 표를
    # 비우고 다시 탐색한다 — 두 번째 실행이 레지스트리 기본값을 문서 값이라고 적지 않게
    own = _own(doc["law"]["design"])
    if own is not None and own.get("seed_input") == "none":
        doc = copy.deepcopy(doc)
        doc["law"].update(design=None, schedule=None, gain_tables=None)
    seed_input = "document" if doc["law"]["design"] is not None else "none"
    built = build_profile(doc, validated=True)
    if seed == "quick":
        from claw.design.seed import quick_seed

        out = quick_seed(built, sim_check=sim_check)
        if not out["ok"]:
            failed = {n: s["reason"] for n, s in out["slots"].items() if s.get("reason")}
            raise ShowcaseError("seed", f"빠른 탐색 미채택 — {out['reason_text'] or out['reason']}"
                                + (f" · 자리 {failed}" if failed else "")
                                + (f" · fail 루프 {out['failed_loops']}" if out["failed_loops"] else ""),
                                detail={"slots": out["slots"], "failed_loops": out["failed_loops"]})
        info = {"anchors": [a["name"] for a in out["anchors"]], "warnings": out["warnings"],
                "sim_check": out["sim_check"]}
    elif seed == "basis":
        from claw.design.basis import apply_seed_basis

        mach, alt, fuel = basis_point(doc)
        out = apply_seed_basis(built, mach, alt, fuel)
        if not out["ok"]:
            raise ShowcaseError("seed", f"산출 근거 직행 불가 — {out['reason_text'] or out['reason']}")
        info = {"point": {"mach": mach, "alt": alt, "fuel": fuel}}
    else:
        raise ValueError(f"seed는 'quick'|'basis': {seed!r}")
    design = copy.deepcopy(out["design"])
    design["provenance"].update(generator=GENERATOR, seed_input=seed_input)
    new = copy.deepcopy(doc)
    # 새 시드는 새 설계의 출발 — 옛 확정 게인 표는 이 설계값과 무관해 지운다(서버 quick-seed·apply-seed-basis와 같은 규칙)
    new["law"].update({"design": design, "gain_tables": None,
                       **({"schedule": out["schedule"]} if out["schedule_created"] else {})})
    scas = design["scas"]
    log("  " + " · ".join(f"{g} kp {scas[g]['kp']:.4g} ki {scas[g]['ki']:.4g} k_rate {scas[g]['k_rate']:.4g}"
                          for g in ("pitch", "roll", "yaw"))
        + (" · 스케줄 새로 만듦" if out["schedule_created"] else ""))
    if info.get("sim_check") is not None:
        sc = info["sim_check"]
        log(f"  확인 평가 {sc['case']}: hard_fail {sc['hard_fail']} · 카드 {sc['cards']}")
    for w in info.get("warnings") or ():
        log(f"  경고: {w}")
    return new, {"source": design["provenance"]["source"], "scas": scas,
                 "schedule_created": out["schedule_created"], **info}


# ── 3. 자동 설계 → 게인 표 반영 ────────────────────────────────────────────


def design_overrides(doc: dict) -> dict:
    """생성용 자동 설계 덧씀 — 예산·밀도(DESIGN_BUDGET) + 문서에서 뽑은 고도·연료 격자.

    고도는 설계 기본 고도(design.grid.DEFAULT_ALTS)를 운용 고도 범위로 거르고 끝을 더한 것(BuiltProfile.alts_within —
    δe_trim 도출·빠른 탐색과 같은 규칙), 연료는 기본 비율 × 문서 fuel_max다. 운용 천장 위 고도에 설계점을 두지 않는다.
    예산은 격자 점 수 + 여유(REFINE·검증점 몫)로 정한다 — 서버 상한(MAX_POINTS 200)을 넘지 않는다."""
    from claw.design.grid import DEFAULT_ALTS, DEFAULT_FUEL_FRACS

    built = build_profile(doc, validated=True)
    alts = built.alts_within(DEFAULT_ALTS)
    fuels = [round(doc["mass"]["fuel_max"] * f, 6) for f in DEFAULT_FUEL_FRACS]
    n_coarse = DESIGN_BUDGET["n_mach"] * len(alts) * len(fuels)
    return {**DESIGN_BUDGET, "alts": alts, "fuels": fuels, "budget_points": min(200, 2 * n_coarse)}


# 판정선·튜닝 목표는 설계 설정이 아니라 기체 문서의 것이다(기준 통합 ① — /criteria·/tuning). 덧씀·기록 설정에서 뺀다
CRITERIA_KEYS = ("criteria", "targets")


def _criteria_conflicts(ev, overrides: dict) -> list:
    """덧씀·기록 설정이 적은 criteria·targets 중 문서의 적용값(ev = build_profile(doc).eval_criteria)과 다른 칸.

    생성기는 그 칸을 쓰지 않고 문서 값으로 설계한다 — 다르면 조용히 무시하지 않고 부르는 쪽이 문서를 고치게 한다."""
    applied = {"criteria": ev.margin.to_dict(), "targets": ev.targets.to_dict()}
    return [f"{sec}.{k}: 설정 {v!r} ≠ 문서 {applied[sec].get(k)!r}"
            for sec in CRITERIA_KEYS for k, v in (overrides.get(sec) or {}).items() if applied[sec].get(k) != v]


def _config(overrides: dict, doc: dict):
    """기본값 위 부분 덧씀 + 문서의 판정선·튜닝 목표 — 서버 routes/design.py _build_config와 같은 길(기준은 선택 기체
    문서의 /criteria·/tuning에서, 없는 칸은 도구 기본값). 덧씀의 criteria·targets는 떼어 낸다 — 문서 값과 다르면 거부."""
    from claw.design import AutoDesignConfig

    base = AutoDesignConfig().to_dict()
    unknown = sorted(set(overrides) - set(base))
    if unknown:
        raise ValueError(f"미정의 config 키 {unknown}")
    ev = build_profile(doc, validated=True).eval_criteria
    conflicts = _criteria_conflicts(ev, overrides)
    if conflicts:
        raise ValueError("설계 설정의 판정선·튜닝 목표가 기체 문서와 다르다 — 문서의 /criteria·/tuning을 고친다: "
                         + "; ".join(conflicts))
    merged = {**base, **{k: v for k, v in overrides.items() if k not in CRITERIA_KEYS},
              "criteria": ev.margin.to_dict(), "targets": ev.targets.to_dict()}
    return AutoDesignConfig.from_dict(merged)


def _stored(x):
    """결과 저장 형식 왕복 — 서버 serialize.to_jsonable의 비유한값 정책(NaN→null, ±inf→"inf"/"-inf")."""
    if isinstance(x, np.ndarray):
        return _stored(x.tolist())
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, (np.floating, np.integer)):
        return _stored(x.item())
    if isinstance(x, complex):
        return [_stored(x.real), _stored(x.imag)]
    if isinstance(x, float):
        return None if x != x else ("inf" if x == math.inf else ("-inf" if x == -math.inf else x))
    if isinstance(x, dict):
        return {k: _stored(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_stored(v) for v in x]
    return x


def _resample_error(poly, tab) -> dict:
    """routes/design.py _resample_error와 같은 정의 — 다항 대비 재샘플 표의 최대 어긋남."""
    axis = poly.axis_names[0]
    xs = np.linspace(float(poly.knots[0]), float(poly.knots[-1]), _RESAMPLE_PROBE)
    p = np.asarray(poly.interp(**{axis: xs}), dtype=float)
    err = np.abs(p - np.asarray(tab.interp(**{axis: xs}), dtype=float))
    i = int(np.argmax(err))
    scale = float(np.max(np.abs(p))) or 1.0
    return {"max_abs": float(err[i]), "max_frac": float(err[i]) / scale,
            "at": float(xs[i]), "n_points": int(tab.data.size)}


def _gain_export(session, aircraft) -> dict:
    """routes/design.py _gain_export와 같은 반출 — {tables_resampled, resample_error, reverify}. 다항은 재샘플
    (resample_to_table, RESAMPLE_TOL), 표는 그대로. 재검증은 반출 표로 같은 점을 다시 판정한 결과다."""
    from claw.design import resample_to_table
    from claw.tables import PolyTable

    tables, errors, export = {}, {}, {}
    for slot, tab in session.sched_tables.items():
        if isinstance(tab, PolyTable):
            rt = resample_to_table(tab, tol_interp=RESAMPLE_TOL)
            export[slot] = rt
            tables[slot] = {"axes": {rt.axis_names[0]: rt.axes[0].tolist()}, "data": rt.data.tolist(),
                            "extrapolate": "clip"}
            errors[slot] = _resample_error(tab, rt)
        else:
            export[slot] = tab
            tables[slot] = {"axes": {n: a.tolist() for n, a in zip(tab.axis_names, tab.axes)},
                            "data": tab.data.tolist(), "extrapolate": tab.extrapolate}
            errors[slot] = {"max_abs": 0.0, "max_frac": 0.0, "at": None, "n_points": int(tab.data.size)}
    return {"tables_resampled": _stored(tables), "resample_error": _stored(errors),
            "reverify": _stored(session.reverify_resampled(aircraft, export))}


def _reverify_summary(rv: dict | None) -> dict:
    """routes/design.py _reverify_summary와 같다 — 수치 목록은 개수로 접는다."""
    if not rv:
        return {"n_judged": None, "worse": None, "better": None, "changed": None,
                "note": "재검증 없음 — 이 결과가 반출될 때는 재검증이 없었다"}
    out = {"n_judged": rv.get("n_judged"), "worse": rv.get("worse"),
           "better": rv.get("better"), "changed": len(rv.get("changed") or [])}
    if rv.get("note"):
        out["note"] = rv["note"]
    return out


def rule_schedule_variants(doc: dict) -> tuple:
    """확정 게인 표를 못 쓰는 형상 변형을 규칙 스케줄로 돌린다 — 그 변형 패치에 /law/gain_tables = null.

    표는 기본 문서에서 확정된다(출처 basis_fingerprint = 기본 적용 문서의 지문). 문서를 바꾸는 형상 변형(질량·관성 등)
    위에서는 그 지문이 어긋나 조립이 표를 거부한다(build.confirmed_gain_tables — 서버 시뮬·조립·영향성 422). 기본형에서
    설계한 표를 그 변형의 표라고 우기지 않고, 변형은 도구가 도출한 설계 게인 × q̄ 역비 스케줄(build.gain_tables — 표가
    없을 때의 조립)로 난다. 표가 그대로 맞는 변형(지문 밖만 바꾸는 변형 — 표시 모델 등)은 건드리지 않는다.

    판정은 그 자리를 뺀 패치로 한다 — 결과는 **지금 문서의 표와 변형만의 함수**다: 낡으면 null을 두고, 안 낡으면(표가
    그대로 맞는 변형, 기본 문서에 표가 없을 때도) 있던 null을 **뺀다**. 그래서 자기 출력에 다시 돌려도, 전에 넣은 null이
    남은 문서에 돌려도 같은 문서다 — 예전 실행이 넣은 null이 남아 표가 맞는 변형을 출처 기록 없이 규칙 스케줄로 날리던
    이력 의존을 막는다. 그 자리의 null은 이 규칙이 소유한다(사람이 변형을 규칙 스케줄로 날리려면 표가 낡는 편집이 곧
    그 사유다). 변형이 그 자리에 표를 직접 실었으면(null이 아닌 값) 사람 몫이라 두고, 낡았으면 generate 요약의
    stale이 말한다.
    돌려주는 것: (새 문서, 규칙 스케줄로 돌린 변형 id 목록 — 문서 순서)."""
    new = copy.deepcopy(doc)
    moved = []
    for item in new["variants"]:
        if item["patch"].get(GAIN_TABLES_PTR) is not None:
            continue
        stale = False
        if new["law"]["gain_tables"] is not None:
            probe = copy.deepcopy(new)
            next(v for v in probe["variants"] if v["id"] == item["id"])["patch"].pop(GAIN_TABLES_PTR, None)
            stale = build_profile(probe, item["id"], validated=True).gain_tables_stale
        if stale:
            item["patch"][GAIN_TABLES_PTR] = None  # 이미 있으면 그 자리 그대로(키 순서 불변)
            moved.append(item["id"])
        else:
            item["patch"].pop(GAIN_TABLES_PTR, None)
    return new, moved


def _stage_design(doc: dict, log, *, overrides: dict | None) -> tuple:
    from claw.design import DesignSession, design_inputs
    from claw.profile.fingerprint import gain_tables_basis_fingerprint

    built = build_profile(doc, validated=True)
    overrides = design_overrides(doc) if overrides is None else overrides
    try:
        inp = design_inputs(built)
    except ProfileError as e:
        raise ShowcaseError("design", f"자동 설계 입력을 못 만든다 — {e.path}: {e}") from e
    try:
        cfg = _config(overrides, doc)
    except ValueError as e:
        raise ShowcaseError("design", str(e)) from e
    session = DesignSession(cfg)

    def run(s):
        s.run(inp["aircraft"], inp["stall_table"], inp["limits"], inp["db_ranges"], inp["design"],
              rate_filters=inp["rate_filters"], actuator=inp["actuator"], fingerprint="")

    t0 = time.perf_counter()
    run(session)
    rounds, approved_total = 0, 0
    while session.status == "awaiting_approval":
        rounds += 1
        if rounds > MAX_APPROVAL_ROUNDS:
            raise ShowcaseError("design", f"승인·재개를 {MAX_APPROVAL_ROUNDS}번 했는데도 승인 대기다")
        # 웹 [승인 반영 재개]의 기본 체크 — 에스컬레이션 제외(엔진도 거부), 봉인·건너뜀 제외(approvedByDefault)
        ids = [a["id"] for a in session.proposed_actions()
               if a["action"]["type"] != "escalate" and not a.get("sealed") and not a.get("skipped")]
        if not ids:
            raise ShowcaseError("design", "승인 대기인데 승인할 처방이 없다")
        rep = session.report()
        log(f"  이터 {rep['iterations']}: 판정 {rep['judged']} · 실패 {rep['failures']} → 처방 {len(ids)}건 승인·재개")
        # 서버 재개와 같은 길 — 저장 형식으로 왕복한 세션에 승인을 반영하고 이어 돈다
        session = DesignSession.from_dict(json.loads(json.dumps(_stored(session.to_dict()), allow_nan=False)))
        session.apply_actions(ids)
        approved_total += len(ids)
        run(session)
    rep = session.report()
    elapsed = time.perf_counter() - t0
    # 표현과 적합에서 뺀 표본도 찍는다 — 표 표현에서 뺀 점의 분할점 값은 이웃 보간이고(튜닝 불성립 표본 제외), 보류된
    # 자리는 실패 표본을 담은 채다. 재생성한 사람이 표를 읽기 전에 알아야 할 것이다
    withheld = rep["exclusion_withheld"]
    log(f"  종료 {rep['status']} · 이터 {rep['iterations']} · 점 {rep['n_points']} · 판정 {rep['judged']} · "
        f"실패 {rep['failures']} · 에스컬레이션 {rep['escalations']} · 표현 {rep['fit_mode']} · "
        f"적합에서 뺀 표본 {len(rep['excluded_samples'])}" + (f" (보류 {withheld})" if withheld else "")
        + f" · {elapsed:.1f} s")
    if rep["status"] == "cancelled":
        raise ShowcaseError("design", "자동 설계가 취소돼 멈췄다")

    export = _gain_export(session, inp["aircraft"])
    tables = export["tables_resampled"]
    if not tables:
        raise ShowcaseError("design", "반출 게인 표가 없는 결과 — 반영할 것이 없다", detail=rep)
    # 문서의 확정 표는 마하 1축뿐이다(스키마 _table_mach) — 서버 apply-gains가 422로 거부하는 결과를 조용히
    # 넘기지 않는다(자동 설계가 고도·연료 축으로 적합한 결과 — E2가 고치는 결함)
    off_axis = {slot: sorted(t["axes"]) for slot, t in tables.items() if sorted(t["axes"]) != ["mach"]}
    if off_axis:
        raise ShowcaseError("design", "기체 문서의 확정 게인 표는 마하 1축 표만 받는다 — 자동 설계가 다른 축으로"
                                      f" 적합한 자리가 있다: {off_axis} (서버 apply-gains도 422로 거부한다)",
                            detail=off_axis)
    new = copy.deepcopy(doc)
    new["law"]["gain_tables"] = {
        "tables": copy.deepcopy(tables),
        "provenance": {
            "source": "auto_design", "generator": GENERATOR,
            # 판정 개수 + 표현·적합에서 뺀 표본 수·보류 자리 — 서버 apply-gains(routes/design.py _design_summary)와 같은
            # 칸·같은 접기(목록은 개수로, 보류는 정렬한 자리 목록). 생성기만 아는 칸(승인 수·설정)은 그 뒤에 붙인다
            "design": {"status": rep["status"], "iterations": rep["iterations"], "judged": rep["judged"],
                       "failures": rep["failures"], "escalations": rep["escalations"], "fit_mode": rep["fit_mode"],
                       "excluded_samples": len(rep["excluded_samples"]),
                       "exclusion_withheld": sorted(rep["exclusion_withheld"]),
                       # config는 받은 덧씀 그대로 — criteria·targets 칸이 있으면 _config가 문서 값과 같음을 확인했다
                       # (설계는 문서 /criteria·/tuning으로 했다). 그 칸을 빼면 출하 파일의 기록이 바뀐다
                       "approved_actions": approved_total, "config": _plain(overrides)},
            "resample_tol": RESAMPLE_TOL,
            "resample_error": copy.deepcopy(export["resample_error"]),
            "reverify": _reverify_summary(export["reverify"]),
            # 낡음 판정의 기준 — 표 절을 뺀 지금 문서의 지문 (build.gain_tables_stale이 대조)
            "basis_fingerprint": gain_tables_basis_fingerprint(built.doc),
        },
    }
    # 표는 기본형 설계 결과다 — 문서를 바꾸는 형상 변형은 표를 비워 규칙 스케줄로 난다. 그 사실을 표 출처에도 적는다
    # (서버 반영은 출처를 새로 쓰므로 이 기록은 거기서 사라지지만, 변형 패치는 남아 같은 조립이 이어진다)
    new, moved = rule_schedule_variants(new)
    if moved:
        names = ", ".join(f"{v['name']}({v['id']})" for v in new["variants"] if v["id"] in moved)
        new["law"]["gain_tables"]["provenance"].update(
            rule_schedule_variants=moved,
            variant_note=f"확정 표는 기본형 설계 결과 — 규칙 스케줄(설계 게인 × q̄ 역비)로 나는 형상 변형: {names}."
                         " 기본 문서에서 확정한 표는 문서를 바꾸는 그 변형에서 낡음(조립 거부)이라 변형 패치가"
                         f" {GAIN_TABLES_PTR}를 null로 둔다")
    try:
        new = validate_document(new)
    except ProfileError as e:
        raise ShowcaseError("design", f"반영한 문서가 검증을 못 넘는다 — {e.path}: {e}") from e
    for slot, t in sorted(tables.items()):
        log(f"  {slot}: {len(t['data'])}점 M{t['axes']['mach'][0]:.3f}–{t['axes']['mach'][-1]:.3f}"
            f" · {min(t['data']):.4g}…{max(t['data']):.4g}")
    if moved:
        log(f"  규칙 스케줄로 나는 형상 변형: {moved} (패치 {GAIN_TABLES_PTR} = null)")
    return new, {"report": {k: rep[k] for k in ("status", "iterations", "n_points", "judged", "failures",
                                                  "failures_by_role", "escalations", "coverage", "coverage_gaps",
                                                  "fit_mode", "excluded_samples", "exclusion_withheld")},
                 "approved_actions": approved_total, "slots": sorted(tables),
                 "reverify": _reverify_summary(export["reverify"]), "config": _plain(overrides),
                 "rule_schedule_variants": moved, "elapsed_s": elapsed}


# ── 조립 ──────────────────────────────────────────────────────────────────


def resolve_seed(doc: dict, seed: str | None) -> str:
    """시드 방식 — 인자가 없으면 이 생성기가 전에 쓴 방식(설계 출처가 seed_basis면 "basis"), 그것도 없으면 "quick".

    자기 출력에 --write를 다시 부를 때 처음과 같은 경로를 밟게 한다 — 인자를 빠뜨렸다고 다른 시드 경로로 게인이
    바뀌면 「같은 입력이면 같은 파일」이 깨진다."""
    if seed is not None:
        return seed
    own = _own(doc["law"]["design"])
    return "basis" if own is not None and own.get("source") == "seed_basis" else "quick"


def resolve_design_config(doc: dict, design_config: dict | None) -> dict | None:
    """자동 설계 덧씀 — 인자가 없으면 이 생성기가 전에 반영한 표의 출처에 적힌 config(같은 설정으로 다시 설계),
    그것도 없으면 None(= design_overrides(문서)). 목표(targets) 같은 설계 선택이 재실행에서 조용히 기본값으로
    돌아가지 않게 한다 — 그 선택은 문서(표의 출처)에 남아 있다."""
    if design_config is not None:
        return design_config
    own = _own(doc["law"]["gain_tables"])
    cfg = ((own or {}).get("design") or {}).get("config")
    return copy.deepcopy(cfg) if isinstance(cfg, dict) else None


def generate(doc: dict, *, stages=STAGES, seed: str | None = None, sim_check: bool = True,
             design_config: dict | None = None, log=None) -> tuple:
    """문서 → (새 문서, 요약). 단계는 STAGES 순서로 돈다(인자 순서와 무관). 입력 문서는 고치지 않는다.

    seed·design_config가 None이면 입력 문서의 이 생성기 출처에서 되짚는다(resolve_seed·resolve_design_config) —
    자기 출력에 다시 돌리면 처음 준 인자 없이도 같은 파일이 나온다.

    어느 단계든 채택할 결과를 못 내면 ShowcaseError — 반쪽 문서를 돌려주지 않는다. 요약에는 단계별 결과와
    끝 문서의 지문·낡음 판정이 있다(끝에 기본형이나 형상 변형에서 δe_trim·확정 게인 표가 낡았으면 stale에 적는다)."""
    unknown = [s for s in stages if s not in STAGES]
    if unknown:
        raise ValueError(f"단계는 {list(STAGES)} 중에서: {unknown}")
    log = log or (lambda msg: None)
    cur = validate_document(doc)
    # 시드 단계가 확정 표를 지우기 전에 되짚는다 — 표의 출처에 설계 설정이 있다
    seed = resolve_seed(cur, seed)
    design_config = resolve_design_config(cur, design_config)
    summary = {"stages": {}, "seed": seed, "design_config": design_config}
    for stage in (s for s in STAGES if s in stages):
        t0 = time.perf_counter()
        log(f"[{stage}]")
        if stage == "de_trim":
            cur, info = _stage_de_trim(cur, log)
        elif stage == "seed":
            cur, info = _stage_seed(cur, log, seed=seed, sim_check=sim_check)
        else:
            cur, info = _stage_design(cur, log, overrides=design_config)
        cur = validate_document(cur)
        summary["stages"][stage] = {**info, "elapsed_s": time.perf_counter() - t0}
        log(f"  ({time.perf_counter() - t0:.1f} s)")
    # 변형 패치의 표 비움은 어느 단계 조합으로 돌려도 끝 문서의 표에서 정한다 — 시드 단계가 표를 지우고 설계 단계를 안
    # 돌렸으면 전에 넣은 null이 할 일 없이 남는다(설계 단계는 이미 같은 규칙을 거쳐 여기서 바뀌는 것이 없다)
    cur = validate_document(rule_schedule_variants(cur)[0])
    base = build_profile(cur, validated=True)
    stale, variant_fps = [], {}
    # 기본형과 형상 변형마다 — 끝 문서로 조립이 거부될 자리(낡은 δe_trim·낡은 확정 표)를 모두 적는다
    for v in [None, *(x["id"] for x in cur["variants"])]:
        b = base if v is None else build_profile(cur, v, validated=True)
        if v is not None:
            variant_fps[v] = {"fingerprint": b.fingerprint, "plant_fingerprint": b.plant_fingerprint}
        if b.de_trim_stale:
            stale.append(f"δe_trim@{v or 'base'}")
        if b.gain_tables_stale:
            stale.append(f"gain_tables@{v or 'base'}")
    summary.update(fingerprint=base.fingerprint, plant_fingerprint=base.plant_fingerprint,
                   variant_fingerprints=variant_fps, stale=stale)
    return cur, summary


def build_showcase(doc: dict, *, stages=STAGES, **kw) -> dict:
    """문서 → 툴 도출 부분을 채운 새 문서(출처 포함). 인자는 generate와 같다."""
    return generate(doc, stages=stages, **kw)[0]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m claw.profile.showcase",
                                 description="쇼케이스 기체 문서의 툴 도출 부분(δe_trim·초기 게인·확정 게인 표)을 채운다")
    ap.add_argument("--in", dest="src", type=Path, default=None, help="입력 문서(기본: 패키지 JSON)")
    ap.add_argument("--write", action="store_true", help="결과를 쓴다(기본 자리: 패키지 JSON)")
    ap.add_argument("--out", type=Path, default=None, help="쓸 경로(--write와 함께, 기본: 패키지 JSON)")
    ap.add_argument("--stages", nargs="+", default=list(STAGES), choices=STAGES)
    ap.add_argument("--seed", choices=("quick", "basis"), default=None,
                    help="초기 게인 경로(기본: 입력 문서의 이 생성기 출처를 따름, 없으면 quick)")
    ap.add_argument("--no-sim-check", action="store_true", help="빠른 탐색의 확인 평가를 끈다")
    ap.add_argument("--design-config", type=json.loads, default=None,
                    help="자동 설계 덧씀 JSON(기본: 입력 문서의 확정 표 출처에 적힌 config, 없으면 design_overrides(문서))")
    args = ap.parse_args(argv)

    src = args.src or packaged_path()
    doc = json.loads(src.read_text(encoding="utf-8"))
    if doc.get("id") != SHOWCASE_ID and args.src is None:
        print(f"경고: 패키지 문서 id가 {doc.get('id')!r} — {SHOWCASE_ID!r}가 아니다", file=sys.stderr)
    t0 = time.perf_counter()
    try:
        new, summary = generate(doc, stages=args.stages, seed=args.seed, sim_check=not args.no_sim_check,
                                design_config=args.design_config, log=print)
    except ShowcaseError as e:
        print(f"실패 {e}", file=sys.stderr)
        return 2
    print(f"끝 — {time.perf_counter() - t0:.1f} s · 시드 {summary['seed']} · 설계 설정 "
          f"{json.dumps(summary['design_config'], ensure_ascii=False) if summary['design_config'] else '기본(design_overrides)'}"
          f" · 지문 {summary['fingerprint']} · 플랜트 {summary['plant_fingerprint']}"
          + "".join(f" · 변형 {v} 지문 {f['fingerprint']}·플랜트 {f['plant_fingerprint']}"
                    for v, f in summary["variant_fingerprints"].items())
          + (f" · 낡음 {summary['stale']}" if summary["stale"] else " · 낡은 표 없음"))
    if args.write:
        out = args.out or packaged_path()
        text = document_text(new)
        before = out.read_text(encoding="utf-8") if out.exists() else None
        out.write_text(text, encoding="utf-8")
        print(f"썼다 {out} ({'바뀜' if before != text else '같음'}, {len(text)} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
