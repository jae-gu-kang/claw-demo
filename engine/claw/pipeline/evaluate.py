"""게인 평가 — A/B/C 등급 채점 (02 §2.4 확장, 사용자 확정 재편).

표면 셋이 한 계산에서 나온다:
- **A급 카드 7장**(CARDS) — 게인 튜닝 중 상시 표시: ①모드 안정성 ζ·ωn ②GM ③PM
  ④응답속도 BW·ω_gc ⑤과도응답 Ts·Mp ⑥추종 RMS ⑦제어권한(사용률·잔여).
  GM·PM은 **각각** 카드다 — GM은 이득류(공력효율·동압·제어이득) 불확실성 여유,
  PM은 지연류(필터·전송·고주파) 여유라 하나로 접으면 다른 위험이 섞인다.
- **B급 체크 9건**(CHECKS) — 항상 계산하고 "n/n PASS" 한 줄로 요약, 문제 시만
  전개: 전체 극점 · Tr · 정상상태 오차 · 시간지연 여유 · 교차축(동시명령) ·
  실속·엔벨로프 · 포화 지속 · 포화 회복 · 스케줄 전이.
- **원자료**(cases[].stages, 구 11항목 어휘 그대로) — 케이스 × 항목 격자와 상세
  전개의 근거. 카드·체크는 이 원자료의 집계이지 별도 계산이 아니다.

C급(강건성 코너·격자 중간점·지연 섭동·MC·미션·worst-case 탐색)은 `verify()`가
따로 돈다 — 후보 게인 스케줄을 걸러낸 **뒤** 실행하는 것이 비용 구조다(사용자
확정 "실행 단계 분리"). 격자 중간점 부가도 evaluate가 아니라 verify의 몫이다.

**실행 깊이(depth)**: "linear"는 트림+선형화만(시뮬 0 — 극점·ζ/ωn·GM/PM·BW,
전 게인 후보에 돌리는 단계 1), "full"은 표준 기동 런 + 동시명령 런까지(단계 2).
B급 교차축이 필수라 full에서 동시명령 런은 상시다.

**판정 구조**: 하드 게이트(HARD_CHECKS — 무엇이 하드인지는 이 코드 상수가 고정,
문턱값만 criteria가 보유) 위반이 하나라도 있으면 Fail이고 J는 None이다. 통과
후보 사이에서만 J(v2 — criteria.JWeights 참조)로 서열을 낸다. GM/PM은 목적함수가
아니라 제약이다. 어느 항이든 지표가 None이면 J도 None + 사유다(01 §4.2 0 위장 금지).

**중복 지표는 삭제가 아니라 대표/보조다**(사용자 확정): 전체 극점은 ζ·ωn의 보조,
시간지연 여유는 PM의 보조(같은 교차점의 환산 — 별도 판정선을 지어내지 않는다),
Tr은 BW의 보조, RMS가 추종의 대표(IAE/ISE 미도입).

**최적화기 이음새**: 이 함수가 향후 복수 게인 조정 최적화의 적합도 함수다 —
제안 생성기(선형모델이든 AI든)는 형상 후보를 만들고 채점은 언제나 여기로 온다.
"""

import math

import numpy as np

from claw.analysis.duty import (
    CHANNELS, _limits_for, _usage, rate_saturation, rate_series, saturation,
    surface_positions, zoh_decimate,
)
from claw.analysis.margins import loop_margins, pi_loop
from claw.analysis.modes import damp
from claw.analysis.schedule import table_smoothness
# 절대 판정의 조성 정본은 closure다 — 평탄 SISO 근사(openloop.GROUP_LOOPS)로 절대
# 판정을 하면 설계점조차 PM 12°(피치)·5.6°(롤)로 나온다(closure.py 머리말 실측).
# 그 선언은 게인 Δ의 민감도용이고, 여기서는 실효 게인 조회(_effective_gain)와
# 속도 루프 선언만 빌려 쓴다 (02 §5.5 재기술 금지)
from claw.design.closure import (
    att_margin_loop, axis_metrics, close_rates, oriented_margins,
    rate_loop_crossover,
)
from claw.guidance import Guidance, ModeSpec
from claw.nav import NavErrorModel
from claw.pipeline.criteria import GainEvalCriteria
# 적분기 "주차" 허용오차의 정본은 진단이다 — 회복(B급)과 진단 규칙 3이 같은 판정
from claw.pipeline.diagnose import PARK_TOL_FRAC, diagnose_grid, diagnose_run
from claw.pipeline.influence import Shape, make_law
from claw.pipeline.metrics import metric_values
from claw.pipeline.openloop import GROUP_LOOPS, _effective_filter, _effective_gain
from claw.pipeline.sweep import PROBE_DH, PROBE_DPSI, PROBE_DV, probe_mission
from claw.plant import make_demo_db_ranges, make_demo_stall_table
from claw.sim import Simulator
from claw.trim import linearize, split_axes, trim_batch
from claw.trim.trim import DE_BOUNDS

# ── 원자료 어휘 (구 11항목 — 케이스 × 항목 격자의 열) ─────────────────────────
# 표시·판정의 정본 표면은 CARDS/CHECKS다. 이 목록은 케이스별 상세(stages)의 키로
# 남는다 — 계산 로직이 사는 자리라 지우지 않는다(삭제가 아니라 소속 이동).
STAGE_ORDER = (
    "envelope", "actuator", "authority", "coupling",
    "stability", "damping", "margins", "tracking",
    "recovery", "robustness", "schedule",
)
ITEMS = {
    "stability": (1, "폐루프 안정성"),
    "damping": (2, "감쇠비·고유주파수"),
    "margins": (3, "이득·위상여유"),
    "tracking": (4, "명령 추종·대역폭"),
    "envelope": (5, "실속·엔벨로프 마진"),
    "actuator": (6, "타면 위치·레이트 여유"),
    "authority": (7, "제어권한·트림 여유"),
    "coupling": (8, "교차축·동시명령"),
    "robustness": (9, "강건성"),
    "recovery": (10, "포화 회복·안티와인드업"),
    "schedule": (11, "스케줄 전이"),
}

# ── A급 카드 — 순서 = 화면 순서 정본 (게인 튜닝 중 상시 표시) ────────────────
CARDS = ("mode_stability", "gm", "pm", "response_speed", "transient",
         "tracking_rms", "control_authority")
CARD_META = {
    "mode_stability": (1, "모드 안정성 ζ·ωn"),
    "gm": (2, "이득여유 GM"),
    "pm": (3, "위상여유 PM"),
    "response_speed": (4, "응답속도 BW·ω_gc"),
    "transient": (5, "과도응답 Ts·Mp"),
    "tracking_rms": (6, "추종 오차 RMS"),
    "control_authority": (7, "제어권한"),
}

# ── B급 체크 — 항상 계산, 요약 한 줄 (문제 시만 전개) ────────────────────────
CHECKS = ("poles_all", "tr", "sse", "delay_margin", "coupling",
          "envelope", "sat_duration", "recovery", "schedule_bump")
CHECK_META = {
    "poles_all": "전체 극점",
    "tr": "상승시간 Tr",
    "sse": "정상상태 오차",
    "delay_margin": "시간지연 여유",
    "coupling": "교차축·동시명령",
    "envelope": "실속·엔벨로프 마진",
    "sat_duration": "포화 지속",
    "recovery": "포화 회복·안티와인드업",
    "schedule_bump": "스케줄 전이",
}

# ── C급 검증 어휘 — verify()의 표면 (후보 확정 후 별도 실행) ─────────────────
VERIFY_META = {
    "mass_cg": "질량·CG 섭동",
    "aero_coeff": "공력계수 섭동",
    "actuator_sensor_delay": "액추에이터·센서 지연",
    "grid_midpoints": "격자 중간점",
    "monte_carlo": "Monte Carlo",
    "mission_profile": "미션 프로파일",
    "worst_case_search": "worst-case 탐색",
}

# 하드 게이트 — **무엇이** 하드인지는 여기가 고정한다 (설정으로 끌 수 있으면
# 게이트가 아니다). criteria는 문턱값만 쥔다. 이름은 hard_fails 항목의 check 키.
HARD_CHECKS = (
    "stability.unstable",  # Re(λ)>0 (나선 실근의 배진폭 허용선 밖·발산 진동쌍)
    "damping.zeta",  # ζ < ζ_min (v2 신규 — 사용자 확정 하드)
    "envelope.stall_margin",  # α 마진 부족
    "envelope.nz",  # Nz 한계 초과 (계측 신설 후 활성)
    "actuator.sat_frac",  # 타면 위치 포화
    "actuator.rate_sat_frac",  # 타율 포화
    "authority.remaining",  # 잔여 권한 < B_min (v2 신규 — 배분 계측 시 활성)
    "coupling.stall_margin",  # 동시명령 중 실속마진
    "coupling.sat_frac",  # 동시명령 중 포화
    "margins.pm", "margins.gm",  # 위상·이득여유 미달 (목적함수 아닌 제약)
)

_RANK = {"fail": 3, "warn": 2, "na": 1, "ok": 0}
_RMS_KEYS = {"alt": "alt_rms", "spd": "spd_rms", "hdg": "hdg_rms"}
# 회복(B급) 와인드업 — 적분기 논리 이름 → 클램프 메타 키 (sim _command_clamps)
_WINDUP_CLAMPS = {"i_pitch": "pitch", "i_roll": "roll", "i_yaw": "yaw",
                  "i_alt": "alt", "i_spd": "spd", "i_hdg": "hdg"}


def combined_probe(tr, *, dh=PROBE_DH, dpsi=PROBE_DPSI, t_settle=5.0, t_hold=30.0):
    """동시명령 기동 — 정착 → (고도 스텝 + 헤딩 스텝 **동시**) 유지 → (modes, t_end).

    표준 기동(probe_mission)은 축을 하나씩 밟아 경합이 없다. 델타익은 피치·롤이
    같은 엘레본 예산을 나눠 쓰므로(fcl/graphs.py 배분 — 헤딩 스텝이 뱅크를 만들어
    롤 예산 R을 잡는다) 피치 캡처가 도착했을 때 이미 롤이 권한을 쓰고 있는 조건이
    교차축 체크의 정의다. ModeSpec 한 모드에 alt·heading을 함께 설정할 뿐 — 새
    유도 기능이 아니다.
    """
    V0 = float(np.linalg.norm(tr.state.vel_b))
    alt0 = float(tr.case.alt)
    modes = [
        ModeSpec(name="settle", speed=V0, alt=alt0, heading=0.0,
                 exit_when=("time_ge", float(t_settle)), next="combined"),
        ModeSpec(name="combined", speed=V0, alt=alt0 + float(dh),
                 heading=float(dpsi), exit_when=("time_ge", 1e9)),
    ]
    return modes, float(t_settle) + float(t_hold)


def _worst(statuses):
    """상태 목록 → 최악 하나. fail > warn > na > ok — na가 warn보다 아래인 것은
    집계가 status 카운트를 함께 실어 판정 불가 수가 따로 보이기 때문이다."""
    if not statuses:
        return "na"
    return max(statuses, key=lambda s: _RANK.get(s, 1))


def _stage(status, item_key, **facts):
    item, label = ITEMS[item_key]
    return {"status": status, "item": item, "label": label, **facts}


# ═══ 원자료 스테이지 (구 11항목 계산부 — 카드·체크의 근거) ═══════════════════


def _case_gains(law, case):
    """케이스 실효 게인 일습 — 레이트 댐퍼 3축 + 자세 PI 2축 + 속도 PI.

    스케줄 자리는 테이블@케이스 실효값이다(_effective_gain — 조회 정본은 openloop).
    레이트 필터는 루프 선언에 달려 있으므로(GROUP_LOOPS의 filter 항, 데모 요축
    워시아웃) 같은 선언에서 읽는다.
    """
    rate_gains = {f"{g}.k_rate": _effective_gain(law, g, "k_rate", case)
                  for g in ("pitch", "roll", "yaw")}
    rate_filters = {}
    for group, decls in GROUP_LOOPS.items():
        for sp in decls:
            if sp.get("filter") is not None:
                fs = _effective_filter(law, group, sp)
                if fs is not None:
                    rate_filters[group] = fs
    att = {g: {"kp": _effective_gain(law, g, "kp", case),
               "ki": _effective_gain(law, g, "ki", case)}
           for g in ("pitch", "roll")}
    spd_sp = GROUP_LOOPS["speed"][0]
    spd = {p: _effective_gain(law, "speed", k, case)
           for p, k in spd_sp["gains"].items()}
    return rate_gains, rate_filters, att, spd


def _stability_stage(closed, crit):
    """전체 극점(B poles_all의 근거) — **레이트 폐쇄** 극점의 발산 검사.

    실근은 배진폭 허용선(나선 관례 — MIL-8785 Level 1: t₂ ≥ 20 s), 진동쌍은 무허용.
    ζ·ωn 카드(대표)의 보조 표면이다 — 자세·외곽 루프의 안정성은 마진·시뮬이 본다.
    """
    if not closed:
        return _stage("na", "stability", note="선형화 실패 — 검사할 극점이 없다"), []
    unstable = []
    for axis, model in closed.items():
        for m in damp(model.A):
            re = m["eig"].real
            if re <= 1e-9:
                continue
            osc = abs(m["eig"].imag) > 1e-9
            t2 = math.log(2.0) / re
            allowed = (not osc) and t2 >= crit.stability.t2_min_s
            unstable.append({
                "axis": axis, "eig": [float(re), float(m["eig"].imag)],
                "t2_s": float(t2), "oscillatory": bool(osc),
                "allowed": bool(allowed),
            })
    bad = [u for u in unstable if not u["allowed"]]
    status = "fail" if bad else ("warn" if unstable else "ok")
    fails = [{"check": "stability.unstable", "value": u["eig"],
              "limit": f"실근 배진폭 ≥ {crit.stability.t2_min_s}s, 진동쌍 발산 불허",
              "detail": u} for u in bad]
    note = ("허용된 완만한 실근 발산(나선 관례)" if unstable and not bad else None)
    return _stage(status, "stability", unstable=unstable, note=note), fails


def _damping_stage(models, rate_gains, rate_filters, crit, notes):
    """A① 카드의 근거 — 레이트 폐쇄 모드 지표 (closure.axis_metrics 정본).

    ζ_sp·ζ_dr을 judge_damping에 세우고, **ζ < ζ_min은 하드다**(v2 — 사용자 확정).
    롤 대역폭(λ)은 A④ 카드가 targets 대비로 판정한다(judge_bandwidth).
    """
    if not models:
        return _stage("na", "damping", note=" · ".join(notes) or "선형화 실패"), []
    try:
        lon_m = axis_metrics(models["lon"], rate_gains, rate_filters)
        lat_m = axis_metrics(models["lat"], rate_gains, rate_filters)
    except ValueError as e:  # 노치 등 미지원 필터 — 데이터이지 죽을 일이 아니다
        return _stage("na", "damping", note=str(e)), []
    j_sp = crit.margin.judge_damping(lon_m["zeta_sp"])
    j_dr = crit.margin.judge_damping(lat_m["zeta_dr"])
    fails = []
    for name, blk in (("sp", lon_m), ("dr", lat_m)):
        z = blk[f"zeta_{name}"]
        if math.isfinite(z) and z < crit.margin.zeta_min:
            fails.append({"check": "damping.zeta", "axis": name,
                          "value": float(z), "limit": crit.margin.zeta_min})
    return _stage(
        _worst([j_sp, j_dr]), "damping",
        zeta_sp={"value": lon_m["zeta_sp"], "wn": lon_m["wn_sp"], "judged": j_sp},
        zeta_dr={"value": lat_m["zeta_dr"], "wn": lat_m["wn_dr"], "judged": j_dr},
        roll_lambda={"value": lat_m["roll_lambda"],
                     "participation": lat_m["roll_participation"],
                     "unstable": lat_m["roll_unstable"]},
    ), fails


def _margins_stage(law, tr, models, rate_gains, rate_filters, att, spd, crit,
                   act_kw):
    """A②③ 카드의 근거 — 자세 PI 마진은 **레이트 폐쇄** 플랜트에서
    (closure.att_margin_loop), 속도 PI는 평탄 선언(GROUP_LOOPS) 그대로. 방향은
    oriented_margins가 정한다(자리마다 설계 게인 부호가 달라 고정 sign으로는
    절반이 음의 DC 루프다).

    루프마다 **시간지연 여유**를 환산해 싣는다: DM = PM[rad] / ω_gc(wcp) — PM과
    같은 교차점의 같은 사실을 지연 언어로 낸 것이라 별도 판정선을 지어내지 않는다
    (B delay_margin 체크는 PM 판정을 따른다). 레이트 자리는 마진으로 판정하지
    않는다 — 순수 P 레이트 루프의 SISO 마진은 병리적이고(closure 머리말) 고전
    기준은 모드 감쇠(A①)다. 대신 **레이트 교차 주파수**(BW의 근거)를 낸다.

    **작동기·지연을 포함한다**(criteria.composition — 자동설계와 같은 값). 빼면
    고주파 롤오프가 없어 −180° 교차가 의미 없는 자리로 가고, 거기서 읽은 GM은
    설계의 성질이 아니라 아티팩트다: 데모 설계점에서 롤 자세 GM이 −70 dB(교차
    0.012 rad/s)로 나와 **거짓 하드 실패**를 만들었고, 조성을 맞추면 9.5 dB로
    통과한다. 마진 맵의 "중립 계약"을 여기 가져온 것이 그 오류였다 — 탐색 화면은
    사용자가 조건을 고르지만 **판정은 실제로 날 플랜트에서** 해야 한다.
    """
    loops = {}
    judged = []
    fails = []

    def put(name, m, direction=None, note=None):
        verdict = crit.margin.judge(m)
        pm, gm, wcp = float(m["pm_deg"]), float(m["gm_db"]), float(m["wcp"])
        dm = (math.radians(pm) / wcp
              if math.isfinite(pm) and math.isfinite(wcp) and wcp > 0.0
              else float("nan"))
        loops[name] = {"status": verdict, "margins": m, "delay_margin_s": dm,
                       "direction": direction, "note": note}
        judged.append(verdict)
        if verdict == "fail":
            if not math.isnan(pm) and pm < crit.margin.pm_min_deg:
                fails.append({"check": "margins.pm", "loop": name,
                              "value": pm, "limit": crit.margin.pm_min_deg})
            if not math.isnan(gm) and gm < crit.margin.gm_min_db:
                fails.append({"check": "margins.gm", "loop": name,
                              "value": gm, "limit": crit.margin.gm_min_db})

    for group, axis in (("pitch", "lon"), ("roll", "lat")):
        kp, ki = att[group]["kp"], att[group]["ki"]
        if kp == 0.0 and ki == 0.0:
            loops[f"{group}_att"] = {"status": "zero", "margins": None,
                                     "delay_margin_s": None,
                                     "note": "이 케이스 자세 실효 게인이 전부 0"}
            continue
        loop = att_margin_loop(models[axis], rate_gains, kp, ki,
                               rate_filters=rate_filters, **act_kw)
        m, direction = oriented_margins(loop)
        put(f"{group}_att", m, direction=direction)

    spd_sp = GROUP_LOOPS["speed"][0]
    if any(v != 0.0 for v in spd.values()):
        m, direction = oriented_margins(pi_loop(
            models[spd_sp["axis"]], x_out=spd_sp["x_out"], u_in=spd_sp["u_in"],
            kp=spd.get("kp", 0.0), ki=spd.get("ki", 0.0), sign=1.0,
            actuator_wn=act_kw["actuator_wn"],
            actuator_zeta=act_kw["actuator_zeta"],
            delay_s=act_kw["delay_s"], pade_order=act_kw["pade_order"]))
        put(spd_sp["name"], m, direction=direction)
    else:
        loops[spd_sp["name"]] = {"status": "zero", "margins": None,
                                 "delay_margin_s": None,
                                 "note": "속도 실효 게인이 전부 0"}

    # 레이트 교차 주파수 — A④ 카드의 상세 (판정은 A④가 λ_roll로, 관례가 있는 자리만)
    crossovers = {}
    for axis, spec in (("lon", ("pitch", "q", "de")), ("lat", ("roll", "p", "da")),
                       ("lat", ("yaw", "r", "dr"))):
        group, x_rate, u_in = spec
        k = rate_gains.get(f"{group}.k_rate", 0.0)
        wc = rate_loop_crossover(models[axis], group, x_rate, u_in, k,
                                 rate_filters=rate_filters, **act_kw)
        crossovers[f"{group}_rate"] = None if math.isnan(wc) else float(wc)

    status = _worst(judged) if judged else "na"
    return _stage(status, "margins", loops=loops, crossovers=crossovers,
                  composition={
                      "text": "레이트 폐쇄 플랜트 + 작동기·지연 포함 "
                              "(자동설계와 같은 조성) — 레이트 자리는 모드 "
                              "감쇠(A①)로 판정",
                      **act_kw},
                  note=None if judged else "판정할 루프가 없다"), fails


_STEP_KEYS = ("tr", "ts", "mp", "sse")


def _tracking_stage(metrics, crit):
    """A⑤⑥ 카드·B tr/sse 체크의 근거 — RMS + 스텝 응답 특성(축별).

    RMS는 판정선이 있고(A⑥), Ts·Mp·Tr·sse는 판정선이 비어 있으면 값만 낸다 —
    판정선을 지어내지 않는다. 단 **∞(미정착·미도달)는 판정선 없이도 warn**이다:
    "창 안에서 그 일이 안 일어났다"는 사실 자체가 이상 신호다.
    """
    axes = {}
    judged = []
    limit_of = {"tr": crit.response.tr_max, "ts": crit.response.ts_max,
                "mp": crit.response.mp_max, "sse": crit.response.sse_max}
    for axis, mkey in _RMS_KEYS.items():
        entry = {}
        v = metrics.get(mkey)
        limit = crit.response.rms_max.get(axis)
        if v is None:
            entry["rms"] = {"value": None, "limit": limit, "judged": "na",
                            "note": "활성 구간 없음 또는 판정 불가"}
        elif limit is None:
            entry["rms"] = {"value": float(v), "limit": None, "judged": "na",
                            "note": "판정선 없음"}
        else:
            verdict = "fail" if float(v) > float(limit) else "ok"
            entry["rms"] = {"value": float(v), "limit": float(limit),
                            "judged": verdict}
            judged.append(verdict)
        for sk in _STEP_KEYS:
            sv = metrics.get(f"{axis}_{sk}")
            slimit = limit_of[sk].get(axis)
            blk = {"value": sv, "limit": slimit, "judged": None}
            if sv is None:
                blk["judged"] = "na"
                blk["note"] = "스텝 없음"
            elif slimit is not None:
                blk["judged"] = "fail" if float(sv) > float(slimit) else "ok"
                judged.append(blk["judged"])
            elif not math.isfinite(float(sv)):
                blk["judged"] = "warn"
                blk["note"] = "창 안에서 미정착·미도달 (∞)"
                judged.append("warn")
            else:
                blk["judged"] = "na"
                blk["note"] = "판정선 미설정 — 값만"
            entry[sk] = blk
        axes[axis] = entry
    return _stage(
        _worst(judged) if judged else "na", "tracking", axes=axes,
        note="대역폭 상한은 [TBD](구조모드 이격 근거가 데모에 없다) — "
             "응답속도는 A④ 카드가 λ_roll·교차 주파수로 낸다")


def _envelope_stage(metrics, crit):
    """B envelope 체크의 근거 — 실속마진(하드) + 엔벨로프 이탈 틱. Nz·q는 계측 전 na."""
    worst = metrics.get("worst_stall_margin")
    fails = []
    if worst is None:
        status = "na"
        note = "실속마진 판정 불가 — 런이 마진을 남기지 않았다"
    else:
        ok = float(worst) >= crit.envelope.alpha_margin_min
        status = "ok" if ok else "fail"
        note = None
        if not ok:
            fails.append({"check": "envelope.stall_margin", "value": float(worst),
                          "limit": crit.envelope.alpha_margin_min})
    return _stage(status, "envelope",
                  worst_stall_margin=worst, flags=metrics.get("envelope_flags"),
                  nz={"status": "na", "note": "Nz 계측 미구현 — 신호 신설 예정"},
                  q_rate={"status": "na", "note": "피치레이트 한계 계측 미구현"},
                  note=note), fails


def _actuator_stage(signals, meta, dt_plant, crit):
    """A⑦ 카드(사용률)·B sat_duration의 근거 — 채널별 위치/레이트 **여유**.

    포화는 하드, 여유 잠식은 warn. 작동기 미장착이면 로그가 명령 직결이라 타율이
    요구 slew다(zoh_decimate — 판정 정본은 duty와 공용). rate 한계 자체가 없으므로
    레이트 쪽은 na다 — 무제한이 아니라 부재.
    """
    limits = dict((meta or {}).get("limits") or {})
    try:
        surfaces = surface_positions(signals)
    except KeyError:
        return _stage("na", "actuator", note="타면 신호가 없다"), []
    has_act = bool((meta or {}).get("actuators"))
    decimate, _zoh_warn = zoh_decimate(meta, dt_plant)
    dt_rate = dt_plant * decimate
    rate_max = limits.get("rate_max")

    channels = {}
    judged = []
    fails = []
    for key, label, prefix in CHANNELS:
        lo, hi = _limits_for(limits, prefix)
        if lo is None and hi is None:
            channels[key] = {"label": label, "status": "na", "note": "한계 미상"}
            continue
        x = np.asarray(surfaces[key], dtype=float)
        span = max(abs(lo) if lo is not None else 0.0,
                   abs(hi) if hi is not None else 0.0)
        fin = x[np.isfinite(x)]
        max_abs = float(np.max(np.abs(fin))) if fin.size else None
        usage = _usage(max_abs, lo, hi)
        rms_frac = (float(np.sqrt(np.mean(fin ** 2)) / span)
                    if span > 0.0 and fin.size else None)
        # 유한 표본 기준 — NaN을 분모에 넣으면 근접 체류 비율이 조용히 희석된다
        near = (float(np.mean(np.abs(fin) >= crit.actuator.near_limit_band * span))
                if span > 0.0 and fin.size else None)
        sat = saturation(x, dt_plant, lo, hi)
        _xmid, xdot = rate_series(x, dt_plant, decimate)
        rsat = rate_saturation(xdot, dt_rate, rate_max) if has_act else None
        rate_usage = (float(np.max(np.abs(xdot)) / rate_max)
                      if has_act and rate_max and len(xdot) else None)
        rate_rms_frac = (float(np.sqrt(np.mean(np.asarray(xdot) ** 2)) / rate_max)
                         if has_act and rate_max and len(xdot) else None)

        ch = {
            "label": label,
            "pos": {"usage": usage, "margin_frac": None if usage is None else 1.0 - usage,
                    "near_limit_frac": near, "sat_frac": None if sat is None else sat["frac"],
                    "sat_events": None if sat is None else sat["events"],
                    "sat_longest": None if sat is None else sat["longest"],
                    "rms_frac": rms_frac},
            "rate": ({"usage": rate_usage,
                      "margin_frac": None if rate_usage is None else 1.0 - rate_usage,
                      "sat_frac": None if rsat is None else rsat["frac"],
                      "rms_frac": rate_rms_frac}
                     if has_act else
                     {"status": "na", "note": "작동기 미장착 — rate 한계 부재 "
                                              "(타율은 요구 slew일 뿐이라 판정하지 않는다)"}),
        }
        verdicts = []
        if sat is not None:
            if sat["frac"] > crit.actuator.sat_frac_max:
                verdicts.append("fail")
                fails.append({"check": "actuator.sat_frac", "channel": key,
                              "value": sat["frac"], "limit": crit.actuator.sat_frac_max})
            elif ((usage is not None and 1.0 - usage < crit.actuator.pos_margin_min_frac)
                  or (near is not None and near > crit.actuator.near_limit_frac_max)):
                verdicts.append("warn")
            else:
                verdicts.append("ok")
        if rsat is not None:
            if rsat["frac"] > crit.actuator.rate_sat_frac_max:
                verdicts.append("fail")
                fails.append({"check": "actuator.rate_sat_frac", "channel": key,
                              "value": rsat["frac"],
                              "limit": crit.actuator.rate_sat_frac_max})
            elif (rate_usage is not None
                  and 1.0 - rate_usage < crit.actuator.rate_margin_min_frac):
                verdicts.append("warn")
            else:
                verdicts.append("ok")
        ch["status"] = _worst(verdicts) if verdicts else "na"
        channels[key] = ch
        judged.extend(verdicts)
    return _stage(_worst(judged) if judged else "na", "actuator",
                  channels=channels), fails


def _authority_stage(tr, metrics, crit):
    """A⑦ 카드의 근거 — 트림 소모(선형 단계에서도 가능) + 비행 중 잔여 권한(런 필요).

    잔여 권한 < b_min_frac은 **하드**다(v2 신규). 배분 미계측(신호 없음)·미실행
    (depth=linear)은 하드 판정에서 빠진다 — envelope.nz 패턴.
    트림 δe 소모율의 기준 한계는 트림 솔버의 경계(DE_BOUNDS)다.
    """
    de = abs(float(tr.control.elevon[0]))
    frac = de / DE_BOUNDS[1]
    if frac > crit.authority.de_frac_max:
        trim_status = "fail"
    elif frac > crit.authority.de_frac_warn:
        trim_status = "warn"
    else:
        trim_status = "ok"
    fails = []
    if metrics is None:
        inflight = {"status": "na",
                    "note": "비선형 런 없음(depth=linear) — 잔여 권한은 런에서 잰다"}
        statuses = [trim_status]
    else:
        vals = {k: metrics.get(k) for k in
                ("min_pitch_authority_frac", "min_roll_authority_frac")}
        measured = {k: v for k, v in vals.items() if v is not None}
        if not measured:
            inflight = {"status": "na",
                        "note": "엘레본 배분 신호 미계측 — 배분 미장착 형상이거나 "
                                "구버전 저장물이다"}
            statuses = [trim_status]
        else:
            worst_key = min(measured, key=measured.get)
            worst_v = float(measured[worst_key])
            ok = worst_v >= crit.authority.b_min_frac
            inflight = {"status": "ok" if ok else "fail", **vals,
                        "worst": {"key": worst_key, "value": worst_v},
                        "limit": crit.authority.b_min_frac}
            if not ok:
                fails.append({"check": "authority.remaining", "value": worst_v,
                              "limit": crit.authority.b_min_frac,
                              "axis": worst_key})
            statuses = [trim_status, inflight["status"]]
    return _stage(_worst(statuses), "authority",
                  trim={"de_rad": de, "frac": frac,
                        "warn_at": crit.authority.de_frac_warn,
                        "fail_at": crit.authority.de_frac_max,
                        "judged": trim_status},
                  inflight=inflight), fails


def _coupling_stage(metrics_c, crit):
    """B coupling 체크의 근거 — 동시명령 런의 실속마진·포화 (둘 다 하드)."""
    fails = []
    judged = []
    worst = metrics_c.get("worst_stall_margin")
    if worst is not None:
        ok = float(worst) >= crit.coupling.alpha_margin_min
        judged.append("ok" if ok else "fail")
        if not ok:
            fails.append({"check": "coupling.stall_margin", "value": float(worst),
                          "limit": crit.coupling.alpha_margin_min})
    sat = metrics_c.get("surf_sat_frac")
    if sat is not None:
        ok = float(sat) <= crit.coupling.sat_frac_max
        judged.append("ok" if ok else "fail")
        if not ok:
            fails.append({"check": "coupling.sat_frac", "value": float(sat),
                          "limit": crit.coupling.sat_frac_max})
    return _stage(
        _worst(judged) if judged else "na", "coupling",
        worst_stall_margin=worst, surf_sat_frac=sat,
        min_pitch_authority_frac=metrics_c.get("min_pitch_authority_frac"),
        min_roll_authority_frac=metrics_c.get("min_roll_authority_frac"),
        alt_rms=metrics_c.get("alt_rms"), hdg_rms=metrics_c.get("hdg_rms"),
        nz={"status": "na", "note": "Nz 계측 미구현"},
        note=None if judged else "동시명령 런이 판정 지표를 남기지 않았다"), fails


def _recovery_stage(signals, meta, crit):
    """B recovery 체크의 근거 — 안티와인드업(적분기 클램프 주차 시간비).

    주차 판정의 허용오차는 진단 규칙 3과 같은 상수(PARK_TOL_FRAC)다 — 두 표면이
    같은 사실을 다르게 판정하면 어느 쪽이 정본인지가 사라진다. 포화 **해제 후**
    재정착·재초과 계측은 [후속] — 그 자리가 비었음을 문장으로 남긴다.
    """
    clamps = dict((meta or {}).get("clamps") or {})
    fracs = {}
    for sig_name, clamp_key in _WINDUP_CLAMPS.items():
        i = signals.get(sig_name)
        c = clamps.get(clamp_key)
        if i is None or not isinstance(c, dict):
            continue
        lo, hi = float(c["lo"]), float(c["hi"])
        span = hi - lo
        if not span > 0.0:
            continue
        a = np.asarray(i, dtype=float)
        fin = a[np.isfinite(a)]
        if fin.size == 0:
            continue
        tol = PARK_TOL_FRAC * span
        fracs[sig_name] = float(np.mean((fin >= hi - tol) | (fin <= lo + tol)))
    if not fracs:
        return _stage("na", "recovery",
                      note="적분기·클램프 계측이 없다 — 판정 불가")
    worst_key = max(fracs, key=fracs.get)
    worst_v = fracs[worst_key]
    status = "ok" if worst_v <= crit.recovery.windup_frac_max else "fail"
    return _stage(status, "recovery",
                  windup={"fracs": fracs,
                          "worst": {"integrator": worst_key, "frac": worst_v},
                          "limit": crit.recovery.windup_frac_max},
                  resettle={"status": "na",
                            "note": "포화 해제 후 재정착·재초과 계측 [후속] — "
                                    "와인드업 시간비만 판정한다"})


def _schedule_stage(law, crit, midpoint_rollup):
    """B schedule_bump 체크의 근거 — dK/dV(테이블만, 시뮬 0) + 중간점 롤업.

    중간점 실측은 C급(verify)의 몫이다 — 여기서는 verify가 돌았을 때만 롤업이 찬다.
    """
    tables = law.schedule.tables if law.schedule is not None else {}
    if not tables:
        return _stage("na", "schedule", note="게인 스케줄 미장착 — 전이가 없다")
    smooth = table_smoothness(tables)
    dkdv = {}
    judged = []
    for name, s in smooth.items():
        limit = crit.schedule.limit_for(name)
        v = s["max_rel_step"]
        if v is None:
            dkdv[name] = {**s, "limit": limit, "judged": "na"}
            continue
        verdict = "fail" if v > limit else "ok"
        dkdv[name] = {**s, "limit": limit, "judged": verdict}
        judged.append(verdict)
    parts = [_worst(judged) if judged else "na"]
    if midpoint_rollup is not None:
        parts.append(midpoint_rollup["status"])
    return _stage(_worst(parts), "schedule", tables=dkdv,
                  midpoints=midpoint_rollup
                  if midpoint_rollup is not None else
                  {"status": "na",
                   "note": "중간점 실측은 C급 검증(verify)의 몫 — 여기는 테이블 "
                           "점프만 본다"})


# ═══ J (v2) ═══════════════════════════════════════════════════════════════════


def _shortfall_sq(achieved, target):
    """목표 대비 부족 비율² — 목표를 넘긴 쪽은 0이다 (넘치는 감쇠·대역폭을 벌하지
    않는다: J_ζ·J_BW는 "목표에 못 미친 만큼"의 항이라는 사용자 정의)."""
    if achieved is None or target is None or not math.isfinite(float(target)) \
            or float(target) <= 0.0:
        return None
    a = float(achieved)
    if not math.isfinite(a):
        return math.inf if a < 0 else 0.0
    return max(0.0, (float(target) - a) / float(target)) ** 2


def _j_for(metrics, act_stage, damping_stage, crit):
    """케이스 하나의 J (v2) = w_ζJ_ζ + w_BW·J_BW + w_RMS·J_RMS + w_Mp·J_Mp + w_δ·J_δ.

    항 정의(전부 무차원, GM/PM은 목적함수가 아니라 제약이라 여기 없다):
      J_ζ  = max(단주기·더치롤의 목표 대비 부족 비율²) — 목표는 criteria.targets
      J_BW = 롤 대역폭(roll_lambda)의 목표 대비 부족 비율² — 피치 BW 목표 [TBD]
      J_RMS = Σ_axes (추종 RMS / 판정선)²
      J_Mp = max_axes (오버슈트 비율)² — Ts는 J에 없다(카드 표시 전용)
      J_δ  = 위치·타율 정규화 RMS²의 평균 (0.5·surf + 0.5·rate; 작동기 미장착이면
             surf만 — rate 한계가 부재라 항이 성립하지 않는다)

    하드 실패 여부와 무관하게 항은 계산해 둔다 — J 자체는 호출자가 하드 실패면
    None으로 낸다. 어느 항이든 None이면 J도 None + 사유(0 위장 금지).
    """
    terms = {}
    reasons = []
    tg = crit.targets

    zs = []
    for key, target in (("zeta_sp", tg.zeta_sp), ("zeta_dr", tg.zeta_dr)):
        blk = damping_stage.get(key)
        v = blk.get("value") if isinstance(blk, dict) else None
        s = _shortfall_sq(v, target)
        if s is not None:
            zs.append(s)
    terms["zeta"] = max(zs) if zs else None
    if not zs:
        reasons.append("zeta: 폐쇄 모드 감쇠를 재지 못했다(선형화 실패)")

    rl = damping_stage.get("roll_lambda")
    if isinstance(rl, dict) and rl.get("value") is not None \
            and math.isfinite(float(rl["value"])):
        terms["bw"] = (math.inf if rl.get("unstable")
                       else _shortfall_sq(rl["value"], tg.roll_lambda))
    else:
        terms["bw"] = None
        reasons.append("bw: 롤 대역폭 판정 불가(실근 없음·참여도 부족) — "
                       "피치 BW 목표는 [TBD]")

    rms = 0.0
    ok = True
    for axis, mkey in _RMS_KEYS.items():
        v, limit = metrics.get(mkey), crit.response.rms_max.get(axis)
        if v is None or limit is None:
            ok = False
            reasons.append(f"rms: {axis} 판정 불가")
            break
        rms += (float(v) / float(limit)) ** 2
    terms["rms"] = rms if ok else None

    mps = [metrics.get(f"{a}_mp") for a in _RMS_KEYS]
    if any(v is None for v in mps):
        terms["mp"] = None
        reasons.append("mp: 스텝이 없는 축이 있다")
    else:
        terms["mp"] = float(max(float(v) ** 2 if math.isfinite(float(v)) else math.inf
                                for v in mps))

    surf, rate = [], []
    for ch in act_stage.get("channels", {}).values():
        for blk, acc in ((ch.get("pos"), surf), (ch.get("rate"), rate)):
            if isinstance(blk, dict) and blk.get("rms_frac") is not None:
                acc.append(float(blk["rms_frac"]) ** 2)
    if surf:
        parts = [float(np.mean(surf))] + ([float(np.mean(rate))] if rate else [])
        terms["delta"] = float(np.mean(parts))
    else:
        terms["delta"] = None
        reasons.append("delta: 잴 타면 채널이 없다")

    w = crit.weights
    weights = {"zeta": w.w_zeta, "bw": w.w_bw, "rms": w.w_rms,
               "mp": w.w_mp, "delta": w.w_delta}
    if any(v is None for v in terms.values()):
        return None, terms, " · ".join(reasons)
    return (sum(weights[k] * terms[k] for k in terms), terms, None)


# ═══ 케이스 하나의 평가 (evaluate·verify 공용) ═══════════════════════════════


def _simulate(aircraft, shape, law, tr, modes, t_end, stall, db_ranges, dt_plant):
    sim = Simulator(
        aircraft=aircraft,
        fcl=law,
        guidance=Guidance([ModeSpec(**vars(m)) for m in modes]),
        nav_model=NavErrorModel(**shape.nav) if shape.nav else None,
        stall_table=stall,
        db_ranges=db_ranges,
        dt_plant=dt_plant,
        control_hz=shape.control_hz,
        actuator_params=shape.actuators or None,
    )
    return sim.run(tr, t_end=t_end, fingerprint=shape.fingerprint())


def _na(item_key, note):
    return _stage("na", item_key, note=note)


def _eval_case(aircraft, tr, shape, law, criteria, *, depth, stall, db_ranges,
               dt_plant, t_settle, t_step, t_hold, dv, dh, dpsi, tick):
    """케이스 하나 → (row, cancelled). 취소 요청이 와도 **그 시점까지 계산한 단계는
    행에 남긴다** — 협조적 취소는 완료 작업 보존이다(리뷰 must-fix: 종전에는 최대
    비용 케이스가 마지막 tick에서 통째로 버려졌다).
    """
    stages = {}
    hard_fails = []
    cancelled = False
    metrics = None
    damping = None
    actuator = {"channels": {}}

    # ── 단계 1 선형 — 트림해 + 선형화 (시뮬 0) ───────────────────────────────
    # models·게인은 **이 케이스에서의 성공**이 확인된 뒤에만 쓴다 — 예외 후 직전
    # 케이스 바인딩으로 판정하면 조용히 남의 게인으로 채점한다(리뷰 must-fix)
    linear_ok = False
    notes = []
    try:
        lon, lat = split_axes(linearize(aircraft, tr))
        models = {"lon": lon, "lat": lat}
        rate_gains, rate_filters, att, spd = _case_gains(law, tr.case)
        closed = {axis: close_rates(models[axis], rate_gains, rate_filters)
                  for axis in ("lon", "lat")}
        linear_ok = True
    except (ValueError, ArithmeticError) as e:
        notes.append(str(e))

    if linear_ok:
        stages["stability"], f = _stability_stage(closed, criteria)
        hard_fails += f
        damping, f = _damping_stage(models, rate_gains, rate_filters,
                                    criteria, notes)
        stages["damping"] = damping
        hard_fails += f
        stages["margins"], f = _margins_stage(
            law, tr, models, rate_gains, rate_filters, att, spd, criteria,
            criteria.composition.act_kw(shape.actuators))
        hard_fails += f
    else:
        reason = " · ".join(notes) or "선형화 실패"
        stages["stability"] = _na("stability", reason)
        damping = stages["damping"] = _na("damping", reason)
        stages["margins"] = _na("margins", reason)
    cancelled = tick(f"선형: {tr.case.name}")

    # ── 단계 2 비선형 — 표준 기동 런 + 동시명령 런 (depth=full) ──────────────
    aborted_run = None
    res = None
    if depth == "full" and not cancelled:
        modes, t_end = probe_mission(tr, dv=dv, dh=dh, dpsi=dpsi,
                                     t_settle=t_settle, t_step=t_step)
        res = _simulate(aircraft, shape, law, tr, modes, t_end,
                        stall, db_ranges, dt_plant)
        metrics = metric_values(res.t, res.signals, res.envelope, res.meta)
        aborted_run = res.meta["aborted"]
        stages["tracking"] = _tracking_stage(metrics, criteria)
        stages["envelope"], f = _envelope_stage(metrics, criteria)
        hard_fails += f
        actuator, f = _actuator_stage(res.signals, res.meta, dt_plant, criteria)
        stages["actuator"] = actuator
        hard_fails += f
        stages["recovery"] = _recovery_stage(res.signals, res.meta, criteria)
        cancelled = tick(f"표준 런: {tr.case.name}")

    if depth == "full" and not cancelled:
        modes_c, t_end_c = combined_probe(
            tr, dh=criteria.coupling.dh, dpsi=criteria.coupling.dpsi,
            t_settle=t_settle, t_hold=t_hold)
        res_c = _simulate(aircraft, shape, law, tr, modes_c, t_end_c,
                          stall, db_ranges, dt_plant)
        metrics_c = metric_values(res_c.t, res_c.signals, res_c.envelope,
                                  res_c.meta)
        stages["coupling"], f = _coupling_stage(metrics_c, criteria)
        stages["coupling"]["aborted"] = res_c.meta["aborted"]
        hard_fails += f
        cancelled = tick(f"동시명령 런: {tr.case.name}")

    stages["authority"], f = _authority_stage(tr, metrics, criteria)
    hard_fails += f

    # ── 소견(원인 귀속) — **같은 런의 후처리다** ─────────────────────────────
    # 진단이 필요로 하는 입력(t·signals·envelope·meta)을 이 함수가 방금 만들었고
    # 지표만 뽑은 뒤 버리고 있었다. 실패한 케이스에 한해 그 런으로 귀속까지 내면
    # 새 시뮬 0회로 "무엇이 원인인가"가 판정 옆에 선다 — 사용자가 시뮬 탭에서
    # 같은 케이스를 손으로 다시 만들 이유가 없어진다.
    # 통과 케이스는 귀속하지 않는다: 고칠 것이 없는 자리의 처방은 소음이다.
    attribution = None
    if res is not None:
        worst_stage = _worst([v["status"] for v in stages.values()])
        if hard_fails or worst_stage in ("fail", "warn"):
            try:
                attribution = diagnose_run(
                    {"t": res.t, "signals": res.signals,
                     "envelope": res.envelope, "meta": res.meta},
                    shape, thresholds=criteria.to_diagnose_thresholds())
                # 지표는 이미 위에서 냈다 — 같은 수를 두 벌로 싣지 않는다
                attribution.pop("metrics", None)
                attribution["status"] = "ok"
            except (ValueError, TypeError, KeyError) as e:
                attribution = {"status": "na", "note": f"귀속 실패: {e}"}
        else:
            attribution = {"status": "na",
                           "note": "전 항목 통과 — 귀속할 결함이 없다"}
    else:
        attribution = {"status": "na",
                       "note": "비선형 런 없음(depth=linear) — 원인 귀속은 런의 "
                               "내부 기여항에서 나온다"}

    # 안 돌린 단계는 사유를 든 na — "안 잰 것"과 "잴 수 없는 것"은 다른 문장이다
    why = ("취소로 건너뜀 — 완료 단계는 보존" if cancelled and depth == "full"
           else "비선형 런 없음(depth=linear) — 단계 2에서 잰다")
    for key in ("tracking", "envelope", "actuator", "recovery", "coupling"):
        stages.setdefault(key, _na(key, why))
    stages["robustness"] = _na(
        "robustness", "C급 검증(verify)의 몫 — 후보 확정 후 별도 실행")

    if metrics is not None and damping is not None:
        j, j_terms, j_reason = _j_for(metrics, actuator, damping, criteria)
    else:
        j, j_terms = None, None
        j_reason = ("취소로 J 항이 비었다" if cancelled
                    else "비선형 항(RMS·Mp·δ) 미계측 — depth=linear")
    if hard_fails:
        j, j_reason = None, "하드 실패라 J를 매기지 않는다 (통과 후보 사이의 서열)"

    return {
        "case": tr.case.name,
        "aborted": aborted_run,
        "stages": stages,
        "attribution": attribution,
        "hard_fails": hard_fails,
        "metrics_raw": metrics or {},
        "J": j, "J_terms": j_terms, "J_reason": j_reason,
    }, cancelled


# ═══ 카드·체크 집계 ══════════════════════════════════════════════════════════


def _min_over(cases, pick):
    """케이스들에서 (값, 부가정보)를 뽑아 최소를 찾는다 — (value, info, case) | None."""
    best = None
    for c in cases:
        got = pick(c)
        if got is None:
            continue
        v, info = got
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        if best is None or v < best[0]:
            best = (v, info, c["case"])
    return best


def _card(key, status, value, threshold, worst_case, note=None, primary=None):
    """카드 하나. primary는 **이 카드를 대표하는 스칼라 하나**다 — 큰 숫자로 찍고
    재측정 델타(얼마에서 얼마로)를 그 위에서 잰다. 값 사전의 모양은 카드마다
    다르므로, 대표를 카드 자신이 선언하지 않으면 소비자가 카드별 분기를 또 짠다.
    """
    no, label = CARD_META[key]
    return {"key": key, "card": no, "label": label, "status": status,
            "value": value, "threshold": threshold, "primary": primary,
            "worst_case": worst_case, "note": note}


def _primary(value, unit, better):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return {"value": float(value), "unit": unit, "better": better}


def _build_cards(cases, criteria):
    """A급 카드 7장 — 케이스 전체의 **최악 운용점**으로 집계한다 (값·기준·자리).

    카드는 원자료(stages)의 집계이지 재계산이 아니다 — 케이스 상세와 카드가 다른
    수를 말하면 화면 신뢰가 무너진다.
    """
    cr = criteria
    cards = []

    # ① 모드 안정성 — ζ 최악(그 모드 wn 동반)
    worst = None
    for c in cases:
        d = c["stages"]["damping"]
        for name in ("zeta_sp", "zeta_dr"):
            blk = d.get(name)
            if not isinstance(blk, dict) or blk.get("value") is None:
                continue
            v = float(blk["value"])
            if worst is None or v < worst["zeta"]:
                worst = {"mode": name, "zeta": v, "wn": blk.get("wn"),
                         "judged": blk.get("judged"), "case": c["case"]}
    cards.append(_card(
        "mode_stability",
        worst["judged"] if worst else "na",
        worst, {"zeta_min": cr.margin.zeta_min, "zeta_good": cr.margin.zeta_good},
        worst["case"] if worst else None,
        note=None if worst else "폐쇄 모드 감쇠를 잰 케이스가 없다",
        primary=_primary(worst["zeta"] if worst else None, "-", "higher")))

    # ②③ GM·PM — 루프 전체 최솟값 (inf GM은 그 루프에 이득 교차가 없다는 사실)
    def margins_pick(metric):
        def pick(c):
            m = c["stages"]["margins"]
            best = None
            for name, lp in (m.get("loops") or {}).items():
                mm = lp.get("margins")
                if not mm:
                    continue
                v = float(mm[metric])
                if math.isnan(v):
                    continue
                if best is None or v < best[0]:
                    best = (v, {"loop": name})
            return best
        return pick

    gm = _min_over(cases, margins_pick("gm_db"))
    gm_status = ("na" if gm is None else
                 "fail" if gm[0] < cr.margin.gm_min_db else
                 "warn" if gm[0] < cr.margin.gm_good_db else "ok")
    cards.append(_card(
        "gm", gm_status,
        None if gm is None else {"gm_db": gm[0], **gm[1]},
        {"gm_min_db": cr.margin.gm_min_db, "gm_good_db": cr.margin.gm_good_db},
        gm[2] if gm else None,
        note=None if gm else "판정할 루프 마진이 없다",
        primary=_primary(gm[0] if gm else None, "dB", "higher")))

    pm = _min_over(cases, margins_pick("pm_deg"))
    # PM의 보조 — 같은 교차점의 시간지연 환산 (B delay_margin 체크와 같은 수)
    dm = _min_over(cases, lambda c: min(
        ((lp["delay_margin_s"], {"loop": n})
         for n, lp in (c["stages"]["margins"].get("loops") or {}).items()
         if lp.get("delay_margin_s") is not None
         and not math.isnan(lp["delay_margin_s"])),
        default=None, key=lambda x: x[0]))
    pm_status = ("na" if pm is None else
                 "fail" if pm[0] < cr.margin.pm_min_deg else "ok")
    cards.append(_card(
        "pm", pm_status,
        None if pm is None else {"pm_deg": pm[0], **pm[1],
                                 "delay_margin_s": None if dm is None else dm[0]},
        {"pm_min_deg": cr.margin.pm_min_deg},
        pm[2] if pm else None,
        note=None if pm else "판정할 루프 마진이 없다",
        primary=_primary(pm[0] if pm else None, "deg", "higher")))

    # ④ 응답속도 — λ_roll(관례 판정이 있는 유일한 자리) + 교차 주파수 상세
    rl = _min_over(cases, lambda c: (
        (float(c["stages"]["damping"]["roll_lambda"]["value"]),
         {"participation": c["stages"]["damping"]["roll_lambda"].get("participation"),
          "unstable": c["stages"]["damping"]["roll_lambda"].get("unstable")})
        if isinstance(c["stages"]["damping"].get("roll_lambda"), dict)
        and c["stages"]["damping"]["roll_lambda"].get("value") is not None
        and math.isfinite(float(c["stages"]["damping"]["roll_lambda"]["value"]))
        else None))
    if rl is None:
        speed_status = "na"
        speed_val = None
    else:
        speed_status = cr.margin.judge_bandwidth(
            rl[0], cr.targets.roll_lambda,
            unstable=bool(rl[1].get("unstable")),
            participation=rl[1].get("participation"))
        # 교차 주파수 최솟값(전 케이스·전 레이트 루프) — 정보
        wc = _min_over(cases, lambda c: min(
            ((v, {"loop": n})
             for n, v in (c["stages"]["margins"].get("crossovers") or {}).items()
             if v is not None and v > 0.0),
            default=None, key=lambda x: x[0]))
        speed_val = {"roll_lambda": rl[0], **rl[1],
                     "target": cr.targets.roll_lambda,
                     "min_crossover": None if wc is None
                     else {"value": wc[0], **wc[1], "case": wc[2]}}
    cards.append(_card(
        "response_speed", speed_status, speed_val,
        {"roll_lambda_target": cr.targets.roll_lambda,
         "lam_min_frac": cr.margin.lam_min_frac},
        rl[2] if rl else None,
        note=None if rl else "롤 대역폭 판정 불가 — 실근 없음·참여도 부족·선형화 실패. "
                             "피치 BW 목표는 [TBD]",
        primary=_primary(rl[0] if rl else None, "rad/s", "higher")))

    # ⑤ 과도응답 — Ts·Mp 최악 (∞ 포함 — 정착 실패가 카드에서 사라지면 안 된다)
    def step_pick(sk):
        def pick(c):
            axes = c["stages"]["tracking"].get("axes") or {}
            best = None
            for axis, entry in axes.items():
                blk = entry.get(sk)
                if not isinstance(blk, dict) or blk.get("value") is None:
                    continue
                v = float(blk["value"])
                if best is None or v > best[0]:
                    best = (v, {"axis": axis, "judged": blk.get("judged")})
            return None if best is None else (-best[0], best[1])  # max를 min틀로
        return pick

    ts = _min_over(cases, step_pick("ts"))
    mp = _min_over(cases, step_pick("mp"))
    tstat = []
    for got in (ts, mp):
        if got is not None:
            tstat.append(got[1].get("judged") or "na")
    cards.append(_card(
        "transient", _worst(tstat) if tstat else "na",
        {"ts_worst": None if ts is None else
         {"value": -ts[0], "axis": ts[1]["axis"], "case": ts[2]},
         "mp_worst": None if mp is None else
         {"value": -mp[0], "axis": mp[1]["axis"], "case": mp[2]}},
        {"ts_max": cr.response.ts_max or None, "mp_max": cr.response.mp_max or None},
        (ts or mp)[2] if (ts or mp) else None,
        note=None if (ts or mp) else "스텝 응답을 잰 런이 없다(depth=linear)",
        # 대표는 Mp다 — J에 들어가는 항이 그쪽이고 Ts는 표시 전용(사용자 정의)
        primary=_primary(-mp[0] if mp else None, "-", "lower")))

    # ⑥ 추종 RMS — 판정선 대비 최악 비율
    rms = _min_over(cases, lambda c: min(
        ((-(float(e["rms"]["value"]) / float(e["rms"]["limit"])),
          {"axis": axis, "value": e["rms"]["value"], "limit": e["rms"]["limit"],
           "judged": e["rms"]["judged"]})
         for axis, e in (c["stages"]["tracking"].get("axes") or {}).items()
         if isinstance(e.get("rms"), dict) and e["rms"].get("value") is not None
         and e["rms"].get("limit")),
        default=None, key=lambda x: x[0]))
    cards.append(_card(
        "tracking_rms",
        rms[1]["judged"] if rms else "na",
        None if rms is None else {"rel_worst": -rms[0], **rms[1]},
        {"rms_max": cr.response.rms_max},
        rms[2] if rms else None,
        note=None if rms else "추종을 잰 런이 없다(depth=linear)",
        # 판정선 대비 비율 — 축마다 단위가 달라 절대값으로는 한 카드에 못 세운다
        primary=_primary(-rms[0] if rms else None, "×기준", "lower")))

    # ⑦ 제어권한 — 사용률 최악 + 트림 소모 최악 + 잔여 권한 최악
    usage = _min_over(cases, lambda c: min(
        ((-(blk["usage"]), {"channel": key, "kind": kind})
         for key, ch in (c["stages"]["actuator"].get("channels") or {}).items()
         for kind, blk in (("pos", ch.get("pos")), ("rate", ch.get("rate")))
         if isinstance(blk, dict) and blk.get("usage") is not None),
        default=None, key=lambda x: x[0]))
    trim = _min_over(cases, lambda c: (
        (-(c["stages"]["authority"]["trim"]["frac"]),
         {"judged": c["stages"]["authority"]["trim"]["judged"]})
        if isinstance(c["stages"]["authority"].get("trim"), dict) else None))
    rem = _min_over(cases, lambda c: (
        (c["stages"]["authority"]["inflight"]["worst"]["value"],
         {"axis": c["stages"]["authority"]["inflight"]["worst"]["key"]})
        if isinstance(c["stages"]["authority"].get("inflight"), dict)
        and isinstance(c["stages"]["authority"]["inflight"].get("worst"), dict)
        else None))
    auth_status = _worst([c["stages"]["authority"]["status"] for c in cases]
                         + [c["stages"]["actuator"]["status"] for c in cases]) \
        if cases else "na"
    cards.append(_card(
        "control_authority", auth_status,
        {"usage_worst": None if usage is None else
         {"value": -usage[0], **usage[1], "case": usage[2]},
         "trim_frac_worst": None if trim is None else
         {"value": -trim[0], "case": trim[2]},
         "remaining_worst": None if rem is None else
         {"value": rem[0], **rem[1], "case": rem[2]}},
        {"sat_frac_max": cr.actuator.sat_frac_max,
         "de_frac_max": cr.authority.de_frac_max,
         "b_min_frac": cr.authority.b_min_frac},
        (rem or usage or trim)[2] if (rem or usage or trim) else None,
        # 대표는 **남은 여유**다 — 잔여 권한이 계측되면 그것, 아니면 사용률의 여집합
        primary=_primary(rem[0] if rem else (1.0 + usage[0] if usage else None),
                         "-", "higher")))
    return cards


def _check(key, status, worst_case=None, value=None, note=None):
    return {"key": key, "label": CHECK_META[key], "status": status,
            "worst_case": worst_case, "value": value, "note": note}


def _stage_check(cases, key, stage_key, value_of=None):
    stats = [c["stages"][stage_key]["status"] for c in cases]
    worst = _worst(stats)
    wc = next((c["case"] for c in cases
               if c["stages"][stage_key]["status"] == worst), None)
    note = next((c["stages"][stage_key].get("note") for c in cases
                 if c["stages"][stage_key]["status"] == worst), None)
    value = value_of(cases) if value_of else None
    return _check(key, worst if cases else "na", worst_case=wc,
                  value=value, note=note)


def _build_checks(cases, criteria, pm_card_status):
    """B급 체크 9건 + 요약 카운트. na는 PASS 분모에서 빠지되 **반드시 병기**된다 —
    "숨기지 않는다"(웹 checksSummary가 이 규칙의 표시 정본)."""
    checks = []
    checks.append(_stage_check(cases, "poles_all", "stability"))

    # Tr·sse — 축·케이스 최악값. 판정선이 비면 na(값만) — 지어내지 않는다
    for key, sk in (("tr", "tr"), ("sse", "sse")):
        worst = None
        judged = []
        for c in cases:
            for axis, e in (c["stages"]["tracking"].get("axes") or {}).items():
                blk = e.get(sk)
                if not isinstance(blk, dict) or blk.get("value") is None:
                    continue
                v = float(blk["value"])
                if worst is None or v > worst["value"]:
                    worst = {"value": v, "axis": axis, "case": c["case"]}
                if blk.get("judged") in ("ok", "warn", "fail"):
                    judged.append(blk["judged"])
        status = (_worst(judged) if judged else
                  ("na" if worst is None else "na"))
        checks.append(_check(
            key, status, worst_case=worst["case"] if worst else None,
            value=worst,
            note=None if judged else
            ("잰 런이 없다" if worst is None else "판정선 미설정 — 값만")))

    # 시간지연 여유 — PM의 보조: 같은 교차점의 환산이라 판정은 PM 카드를 따른다
    dm = None
    for c in cases:
        for name, lp in (c["stages"]["margins"].get("loops") or {}).items():
            v = lp.get("delay_margin_s")
            if v is None or math.isnan(v):
                continue
            if dm is None or v < dm["value"]:
                dm = {"value": v, "loop": name, "case": c["case"]}
    checks.append(_check(
        "delay_margin", pm_card_status if dm else "na",
        worst_case=dm["case"] if dm else None, value=dm,
        note="판정은 PM과 한 몸(같은 교차점의 지연 환산) — 별도 판정선을 "
             "지어내지 않는다" if dm else "잰 마진이 없다"))

    checks.append(_stage_check(cases, "coupling", "coupling"))
    checks.append(_stage_check(
        cases, "envelope", "envelope",
        value_of=lambda cs: min(
            ({"value": c["stages"]["envelope"]["worst_stall_margin"],
              "case": c["case"]}
             for c in cs
             if c["stages"]["envelope"].get("worst_stall_margin") is not None),
            default=None, key=lambda d: d["value"])))

    # 포화 지속 — 0이면 ok, 있으면 warn(사실: 포화가 있었다 — 비율 하드와 별개 질문)
    sat = None
    for c in cases:
        for key2, ch in (c["stages"]["actuator"].get("channels") or {}).items():
            blk = ch.get("pos")
            if isinstance(blk, dict) and blk.get("sat_longest") is not None:
                v = float(blk["sat_longest"])
                if sat is None or v > sat["value"]:
                    sat = {"value": v, "channel": key2, "case": c["case"]}
    checks.append(_check(
        "sat_duration",
        "na" if sat is None else ("ok" if sat["value"] == 0.0 else "warn"),
        worst_case=sat["case"] if sat else None, value=sat,
        note=None if sat else "잰 런이 없다"))

    checks.append(_stage_check(cases, "recovery", "recovery"))
    checks.append(_stage_check(cases, "schedule_bump", "schedule"))

    counts = {"ok": 0, "warn": 0, "fail": 0, "na": 0}
    for ch in checks:
        counts[ch["status"]] = counts.get(ch["status"], 0) + 1
    return {"list": checks,
            "n_pass": counts["ok"], "n_warn": counts["warn"],
            "n_fail": counts["fail"], "n_na": counts["na"],
            "n_judged": counts["ok"] + counts["warn"] + counts["fail"]}


# ═══ 진입점 ══════════════════════════════════════════════════════════════════


def evaluate(aircraft, trs, shape: Shape, criteria: GainEvalCriteria, *,
             depth="full", dt_plant=0.01, t_settle=5.0, t_step=30.0, t_hold=None,
             dv=PROBE_DV, dh=PROBE_DH, dpsi=PROBE_DPSI,
             midpoint_names=(), on_progress=None) -> dict:
    """트림해 목록 + 형상 + 기준 → A급 카드 + B급 체크 + 원자료 (케이스별 + 집계).

    depth: "linear"(단계 1 — 시뮬 0, 전 후보용) | "full"(단계 2 포함 — 표준·동시명령
    런). on_progress(done, total, msg) truthy → 협조적 취소(완료 단계 보존).
    midpoint_names: verify가 부가한 중간점 케이스 이름(태그 전달용 — evaluate는
    스스로 케이스를 만들지 않는다).
    """
    if depth not in ("linear", "full"):
        raise ValueError(f"depth는 'linear'|'full': {depth}")
    law = make_law(shape)
    stall = make_demo_stall_table()
    db_ranges = make_demo_db_ranges()
    midpoint_names = set(midpoint_names)
    if t_hold is None:
        t_hold = t_step

    good = [tr for tr in trs if tr.converged]
    warnings = [f"트림 미수렴 케이스 — 전 항목 판정 불가: {tr.case.name}"
                for tr in trs if not tr.converged]
    per_case = 1 if depth == "linear" else 3
    total = len(good) * per_case
    done = 0
    aborted = None

    def tick(msg):
        nonlocal done
        done += 1
        return (on_progress is not None
                and bool(on_progress(done, total, msg)))

    cases = []
    for tr in good:
        row, cancelled = _eval_case(
            aircraft, tr, shape, law, criteria,
            depth=depth, stall=stall, db_ranges=db_ranges, dt_plant=dt_plant,
            t_settle=t_settle, t_step=t_step, t_hold=t_hold,
            dv=dv, dh=dh, dpsi=dpsi, tick=tick)
        row["midpoint"] = tr.case.name in midpoint_names
        cases.append(row)
        if cancelled:
            aborted = "cancelled"
            break

    # 스케줄 전이(B) — 테이블은 케이스와 무관하다. 중간점 롤업은 verify의 몫이라
    # evaluate에서는 항상 None(사유는 _schedule_stage가 든다)
    schedule = _schedule_stage(law, criteria, None)
    for c in cases:
        c["stages"]["schedule"] = schedule

    # ── 국소성 (어디서 나쁜가) — 격자 재기의 부수 산출 ──────────────────────
    # 종전에는 같은 표준 기동을 스캔이 한 번, 평가가 또 한 번 돌았다(케이스당 95초
    # 시뮬 한 벌이 통째로 중복). 격자를 재는 것이 곧 국소성 판정이므로 여기서 낸다:
    # 결함이 일부 구간에 몰리면 스케줄 셀, 전반이면 설계점 게인 수준이 처방 층이다.
    locality = None
    if cases and depth == "full":
        per_case = [{"case": c["case"], "aborted": c["aborted"],
                     "metrics": c.get("metrics_raw") or {}} for c in cases]
        if any(pc["metrics"] for pc in per_case):
            locality = diagnose_grid(
                per_case, thresholds=criteria.to_grid_thresholds(),
                local_frac=criteria.schedule.local_frac)

    def stage_agg(key):
        stats = [c["stages"][key]["status"] for c in cases]
        counts = {s: stats.count(s) for s in ("fail", "warn", "na", "ok")}
        worst = _worst(stats)
        worst_case = next((c["case"] for c in cases
                           if c["stages"][key]["status"] == worst), None)
        return {"status": worst, "counts": counts, "worst_case": worst_case}

    agg_stages = {k: stage_agg(k) for k in STAGE_ORDER} if cases else {}
    all_fails = [dict(f, case=c["case"]) for c in cases for f in c["hard_fails"]]
    cards = _build_cards(cases, criteria) if cases else [
        _card(k, "na", None, None, None, note="평가된 케이스가 없다") for k in CARDS]
    pm_status = next(cd["status"] for cd in cards if cd["key"] == "pm")
    checks = (_build_checks(cases, criteria, pm_status) if cases else
              {"list": [_check(k, "na", note="평가된 케이스가 없다")
                        for k in CHECKS],
               "n_pass": 0, "n_warn": 0, "n_fail": 0, "n_na": len(CHECKS),
               "n_judged": 0})

    js = [(c["J"], c["case"]) for c in cases]
    if cases and all(j is not None for j, _ in js):
        jw = max(js)
        agg_j = {"worst": jw[0], "case": jw[1]}
        agg_j_reason = None
    else:
        agg_j = None
        agg_j_reason = ("평가된 케이스가 없다" if not cases else
                        "J 미산정 케이스가 있다 — 사유는 케이스별 J_reason에")

    return {
        "fingerprint": shape.fingerprint(),
        "criteria_fingerprint": criteria.fingerprint(),
        "criteria": criteria.to_dict(),
        "depth": depth,
        "cards": cards,
        "checks": checks,
        "stage_order": list(STAGE_ORDER),
        "items": {k: {"item": ITEMS[k][0], "label": ITEMS[k][1]} for k in STAGE_ORDER},
        "hard_checks": list(HARD_CHECKS),
        "cases": cases,
        "aggregate": {
            # 케이스 0건이면 통과도 실패도 아니다 — False로 두면 "합격"으로 읽힌다
            "hard_fail": (None if not cases else bool(all_fails)),
            "hard_fails": all_fails,
            "stages": agg_stages,
            "J": agg_j, "J_reason": agg_j_reason,
            "locality": locality,
            "n_cases": len(cases),
            "n_midpoint": sum(1 for c in cases if c["midpoint"]),
        },
        "warnings": warnings,
        "aborted": aborted,
    }


# ═══ C급 검증 (verify) — 후보 확정 후 별도 실행 ══════════════════════════════


def _corner_dispersions(crit):
    """강건성 코너 — 결정적 축별 ±(기본). vertices(2^n)는 corners='vertices'일 때.

    CG는 목록에 없다 — plant/demo.py DispersionSet 머리말의 [TBD] 사유. 축이 0이면
    (frac=0) 그 축은 코너를 만들지 않는다(흔드는 시늉 금지).
    """
    from claw.plant.demo import DispersionSet

    axes = [(name, frac) for name, frac in
            (("mass", crit.robustness.mass_frac),
             ("cmalpha", crit.robustness.cmalpha_frac),
             ("cmq", crit.robustness.cmq_frac)) if frac > 0.0]
    if crit.robustness.corners == "axis":
        return [DispersionSet(**{n: s * f}) for n, f in axes for s in (+1.0, -1.0)]
    import itertools

    out = []
    for signs in itertools.product((+1.0, -1.0), repeat=len(axes)):
        out.append(DispersionSet(**{n: s * f for (n, f), s in zip(axes, signs)}))
    return out


def verify(aircraft_factory, cases, shape: Shape, criteria: GainEvalCriteria, *,
           depth="full", midpoint_cases=(), dt_plant=0.01,
           t_settle=5.0, t_step=30.0, t_hold=None, on_progress=None) -> dict:
    """C급 검증 — 강건성 코너(질량·Cmα·Cmq) + 격자 중간점. 코너마다 **재트림**한다
    (기체가 다르면 트림해도 다르다 — 명목 트림해로 섭동 기체를 평가하면 시작부터
    비평형이라 전 지표가 과도응답에 오염된다).

    aircraft_factory(dispersion=DispersionSet|None) → Aircraft (키워드 호출). MC·미션 프로파일·지연 섭동·
    worst-case 탐색은 어휘와 자리만 있다([자리] — 구현 스코프 밖, 사유 동봉).
    on_progress(done, total, msg) truthy → 협조적 취소(완료 코너 보존).
    """
    corners = _corner_dispersions(criteria)
    mids = list(midpoint_cases)
    per_case = 1 if depth == "linear" else 3
    # 진행 총량: (코너 × 케이스) + 중간점 케이스 — 트림은 케이스 단위에 포함해 셈
    total = (len(corners) * len(cases) + len(mids)) * (per_case + 1)
    done = 0
    aborted = None
    warnings = []

    def tick(msg):
        nonlocal done
        done += 1
        return (on_progress is not None and bool(on_progress(done, total, msg)))

    def eval_block(aircraft, block_cases, midpoint_names=()):
        nonlocal aborted
        law = make_law(shape)
        stall = make_demo_stall_table()
        db = make_demo_db_ranges()
        trs = trim_batch(aircraft, block_cases)
        rows = []
        unconv = []
        for tr in trs:
            if not tr.converged:
                unconv.append(tr.case.name)
                tick(f"트림 미수렴: {tr.case.name}")
                continue
            tick(f"트림: {tr.case.name}")
            row, cancelled = _eval_case(
                aircraft, tr, shape, law, criteria,
                depth=depth, stall=stall, db_ranges=db, dt_plant=dt_plant,
                t_settle=t_settle, t_step=t_step,
                t_hold=t_step if t_hold is None else t_hold,
                dv=PROBE_DV, dh=PROBE_DH, dpsi=PROBE_DPSI, tick=tick)
            row["midpoint"] = tr.case.name in set(midpoint_names)
            rows.append(row)
            if cancelled:
                aborted = "cancelled"
                break
        # 스케줄 전이 — 중간점 블록에서는 **실측 롤업**이 찬다(여기가 C급의 정의)
        rollup = None
        if midpoint_names:
            mrows = [r for r in rows if r["midpoint"]]
            watch = ("stability", "damping", "margins", "actuator")
            rollup = {
                "status": (_worst([r["stages"][k]["status"]
                                   for r in mrows for k in watch])
                           if mrows else "na"),
                "cases": [r["case"] for r in mrows],
                "watch": list(watch),
                "note": None if mrows else "중간점 케이스가 전부 미수렴/취소",
            }
        schedule = _schedule_stage(law, criteria, rollup)
        for r in rows:
            r["stages"]["schedule"] = schedule
        return rows, unconv

    def summarize(rows, unconv):
        fails = [dict(f, case=r["case"]) for r in rows for f in r["hard_fails"]]
        return {
            "hard_fail": None if not rows else bool(fails),
            "hard_fails": fails,
            "stage_status": ({k: _worst([r["stages"][k]["status"] for r in rows])
                              for k in STAGE_ORDER} if rows else {}),
            "n_cases": len(rows),
            "unconverged": unconv,
            "cases": [{"case": r["case"], "hard_fails": len(r["hard_fails"]),
                       "stages": {k: r["stages"][k]["status"]
                                  for k in STAGE_ORDER}} for r in rows],
        }

    corner_rows = []
    for disp in corners:
        if aborted:
            break
        ac = aircraft_factory(dispersion=disp)
        rows, unconv = eval_block(ac, cases)
        corner_rows.append({
            "label": disp.label(),
            "dispersion": {"mass": disp.mass, "cmalpha": disp.cmalpha,
                           "cmq": disp.cmq},
            **summarize(rows, unconv),
        })

    mid_summary = None
    if mids and not aborted:
        ac0 = aircraft_factory(dispersion=None)
        rows, unconv = eval_block(ac0, mids,
                                  midpoint_names={c.name for c in mids})
        mid_summary = summarize(rows, unconv)

    def split_axis(names):
        rows = [r for r in corner_rows
                if any(r["dispersion"][n] != 0.0 for n in names)]
        judged = [r for r in rows if r["hard_fail"] is not None]
        return {
            "status": ("na" if not judged else
                       "fail" if any(r["hard_fail"] for r in judged) else "ok"),
            "corners": rows,
            "n_pass": sum(1 for r in judged if not r["hard_fail"]),
            "n_judged": len(judged),
        }

    out_verify = {
        "mass_cg": {**split_axis(("mass",)),
                    "note": "CG축은 [TBD] — 모멘트 기준점 이전 미구현이라 흔들어도 "
                            "동역학이 안 변한다(plant/demo.py). 질량축만 실측"},
        "aero_coeff": {**split_axis(("cmalpha", "cmq")), "note": None},
        "grid_midpoints": (
            {**mid_summary,
             "status": ("na" if mid_summary["hard_fail"] is None else
                        "fail" if mid_summary["hard_fail"] else "ok"),
             "note": None} if mid_summary is not None else
            {"status": "na",
             "note": ("취소로 중간점 블록 미실행" if mids else
                      "중간점 케이스가 요청에 없다")}),
        "actuator_sensor_delay": {
            "status": "na",
            "note": "[자리] 지연 섭동은 마진 조성의 delay_s 재계산으로 붙는다 — 후속"},
        "monte_carlo": {
            "status": "na",
            "note": "[자리] monte_carlo_n>0 활성화는 스코프 밖 — 코너가 1차다"},
        "mission_profile": {
            "status": "na", "note": "[자리] 미션 프로파일 재생 검증 — 후속"},
        "worst_case_search": {
            "status": "na", "note": "[자리] 코너 전수 대신 탐색 — 후속"},
    }
    statuses = [b["status"] for b in out_verify.values()]
    return {
        "fingerprint": shape.fingerprint(),
        "criteria_fingerprint": criteria.fingerprint(),
        "depth": depth,
        "verify_meta": dict(VERIFY_META),
        "verify": out_verify,
        "status": _worst([s for s in statuses if s != "na"] or ["na"]),
        "warnings": warnings,
        "aborted": aborted,
    }
