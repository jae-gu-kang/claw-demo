"""진단 — "어떤 손잡이를 만질 것인가"를 폐루프 기록에서 판별한다 (처방 카드).

정량("얼마나")보다 먼저 "무엇을"이 와야 한다: 같은 추종 미달이라도 명령필터가
병목이면 게인을 올려도 소용없고, 포화를 레이트항이 주도하면 kp가 아니라 k_rate를
줄여야 한다. 이 모듈은 단계 1 텔레메트리(law.py INSTRUMENT_NODES/STATES가 기록한
기여항·필터 명령·적분기)에서 그 귀속을 계산해 Prescription(knobs = ParamRef id
문법 그대로 — 3단 스윕의 입력)으로 낸다. 스윕은 처방된 부분공간만 흔들면 된다.

규칙 (번호는 설계 계획의 규칙 번호):
  1 오차 분해   — e = (원본−필터) + (필터−응답). 전자 지배면 tau, 후자면 kp/ki
  2 포화 기여   — 포화 틱에서 |PI| vs |damp| vs |FF| — 지배 게인 그룹 귀속
  3 와인드업    — 적분기가 클램프에 "주차" (내부 클램프형 PID의 시그니처 —
                  "계속 성장"이 아니다, blocks/controllers.py PID 참조)
  5 리미터 귀속 — 작동 중 α 침투 동반(감쇠 문제) vs 무침투 지속(margin/임무)
  4 국소성      — 케이스 격자별 지표(`diagnose_grid`) — 단일런 규칙과 의존이 없어
                  격자 기준런(3단 스윕의 부수 산출물)이 생기면 소급 활성화된다
  6 동시 수정   — COUPLING 선언표(재확인 지표) + 1단 도달 원뿔 교집합(joint_with)

**처방 전 교차 규칙**: 스케줄이 덮는 자리(1단 param_impacts의 overridden/inert)는
편집해도 실행에 반영되지 않는다 — `table.<그룹>.<게인>` 곡선 배율 id로 자동
승격한다. 1단(구조 도달성)이 진단에 기여하는 자리가 바로 여기다.

방향(direction)은 **크기(|값|) 기준**이다 — 게인 부호는 설계값이 보유하므로
(fcl/scas.py) "decrease"는 음수 게인이면 0 쪽으로 움직인다는 뜻이다.

문턱값은 모듈 상수다 — 데모 규모의 판정선이며 응답에 함께 실어 화면이 해석
가능하게 한다 (duty의 deadband 동봉과 같은 이유). 판정은 이분이 아니라
evidence(수치)를 항상 동반한다.
"""

from dataclasses import dataclass, field

import numpy as np

from claw.analysis.duty import run_stats
from claw.fcl.graphs import AP_PARAM
from claw.pipeline.influence import Shape, param_impacts, param_universe
from claw.pipeline.metrics import metric_values, wrap_pi

# ── 문턱값 (데모 규모 판정선) ──────────────────────────────────────────────
# 추종 RMS: 데모 설계 성능(fcl/autopilot.py — 고도 +100 m 캡처 오버슈트 8.3%)의
# 정상 캡처 과도가 걸리지 않고 명백한 미달만 걸리는 수준.
RMS_THRESH = {"alt": 10.0, "spd": 2.0, "hdg": 0.1}  # m · m/s · rad
FILTER_DOMINANCE = 1.5  # rms_filter가 rms_loop의 이 배수를 넘으면 필터 병목
CONTRIB_DOMINANCE = 1.2  # 포화 기여 지배 판정 배수 (미만이면 동시 후보로 낸다)
SAT_FRAC_WARN = 0.05  # 축·타면 포화 시간 비율 — 이 위면 게인 과다 신호
WINDUP_FRAC = 0.02  # 적분기 클램프 주차 시간 비율
LIMITER_FRAC = 0.02  # α 리미터 작동 시간 비율
PARK_TOL_FRAC = 1e-3  # 클램프 span 대비 "주차" 판정 허용
SAT_TOL = 1e-9  # 포화 틱 판정: |포화 전 − 후| — 클램프 재기술이 필요 없는 기록값 비교
LOCAL_FRAC = 1.0 / 3.0  # 결함 케이스 비율이 이하면 국소(스케줄 형상), 넘으면 전역
JOINT_JACCARD = 0.5  # 도달 원뿔 교집합 — 이 이상 겹치면 동시 수정 후보

THRESHOLDS = {
    "rms": RMS_THRESH, "filter_dominance": FILTER_DOMINANCE,
    "contrib_dominance": CONTRIB_DOMINANCE, "sat_frac": SAT_FRAC_WARN,
    "windup_frac": WINDUP_FRAC, "limiter_frac": LIMITER_FRAC,
    "local_frac": LOCAL_FRAC,
}

# 손잡이 클래스별 재확인 지표 (METRICS 키) — "이걸 움직이면 함께 봐야 하는 것".
# kp/ki↑는 포화·마진을, tau↓는 급해진 명령의 포화를, 클램프 완화는 추종을 재확인.
COUPLING = {
    "loop_gain": ("surf_sat_frac", "worst_stall_margin"),
    "rate_gain": ("surf_sat_frac", "worst_stall_margin"),
    "filter": ("surf_sat_frac",),
    "clamp": ("alt_rms", "spd_rms", "hdg_rms"),
    "limiter": ("worst_stall_margin", "limiter_frac"),
    "schedule": ("surf_sat_frac", "worst_stall_margin"),
}

# 축 → 손잡이 id (ParamRef id 문법). 철자는 param_universe와 맞아야 하며
# test_diagnose가 실재를 검증한다 — 여기가 낡으면 스윕이 시작조차 못 한다.
_AP_AXIS = {
    "alt": {"tau": "fcl/Autopilot.tau_alt", "kp": "fcl/Autopilot.kp_alt",
            "ki": "fcl/Autopilot.ki_alt", "damp": "fcl/Autopilot.k_hdot",
            "ff": "fcl/Autopilot.k_pitch_turn",
            "clamp": ("fcl/Autopilot.theta_lo", "fcl/Autopilot.theta_hi")},
    "spd": {"tau": "fcl/Autopilot.tau_spd", "kp": "fcl/Autopilot.kp_spd",
            "ki": "fcl/Autopilot.ki_spd", "ff": "fcl/Autopilot.k_thr_turn",
            "clamp": ()},  # 스로틀 [0,1]은 조립 상수 — 흔들 자리가 없다
    "hdg": {"tau": "fcl/Autopilot.tau_hdg", "kp": "fcl/Autopilot.kp_hdg",
            "ki": "fcl/Autopilot.ki_hdg", "clamp": ("fcl/Autopilot.phi_max",)},
}
_SCAS_AXIS = {
    a: {"kp": f"fcl/ScasAxis.{a}.kp", "ki": f"fcl/ScasAxis.{a}.ki",
        "rate": f"fcl/ScasAxis.{a}.k_rate",
        "clamp": (f"fcl/ScasAxis.{a}.out_lo", f"fcl/ScasAxis.{a}.out_hi")}
    for a in ("pitch", "roll", "yaw")
}
# AP 파라미터 이름 → 스케줄 그룹·키 (승격용) — 정본 AP_PARAM(fcl/graphs.py)의 역방향
_AP_GROUP_OF = {param: gk for gk, param in AP_PARAM.items()}


@dataclass(frozen=True)
class Finding:
    """규칙 하나의 판정 — 처방과 별개로 evidence(수치)를 항상 남긴다."""

    rule: str  # 'error_split' | 'sat_attrib' | 'mix_sat' | 'windup' | 'limiter'
    axis: str
    severity: str  # 'info'(정상 범위) | 'warn'(처방 동반)
    verdict: str  # 사람이 읽는 한 줄
    evidence: dict

    def as_dict(self) -> dict:
        return {"rule": self.rule, "axis": self.axis, "severity": self.severity,
                "verdict": self.verdict, "evidence": dict(self.evidence)}


@dataclass
class Prescription:
    """처방 카드 — knobs는 ParamRef id 그대로 3단 스윕의 입력이 된다."""

    knobs: tuple  # 만질 손잡이 (승격 반영 후)
    knob_class: str  # 'filter'|'loop_gain'|'rate_gain'|'clamp'|'limiter'|'schedule'
    direction: str | None  # 'increase'|'decrease' — |값| 기준
    findings: tuple  # 근거 Finding 인덱스
    joint_with: tuple = ()  # 동시 수정 후보 (클램프 완화·도달 원뿔 겹침)
    recheck: tuple = ()  # 움직인 뒤 재확인할 지표 키 (COUPLING)
    notes: tuple = ()  # 승격·지배 불명확 등 부가 설명

    def as_dict(self) -> dict:
        return {"knobs": list(self.knobs), "knob_class": self.knob_class,
                "direction": self.direction, "findings": list(self.findings),
                "joint_with": list(self.joint_with), "recheck": list(self.recheck),
                "notes": list(self.notes)}


def _arr(signals, name, dtype=float):
    v = signals.get(name)
    return None if v is None else np.asarray(v, dtype=dtype)


def _rms(x):
    x = x[np.isfinite(x)]
    return None if x.size == 0 else float(np.sqrt(np.mean(x * x)))


def _rule_error_split(signals, metrics, findings, pres, warnings):
    """규칙 1 — 추종 오차를 (원본−필터)와 (필터−응답)으로 분해해 귀속.

    필터 지배 자체는 결함이 아니다(명령 성형이 목적) — 해당 축 추종 RMS 지표가
    문턱을 넘을 때만 처방하고, 비율은 항상 evidence로 낸다. 비활성 스텝의 필터
    노드는 disabled_output=0이라 활성 게이팅이 필수다.
    """
    axes = (
        ("alt", "cmd_alt", "alt_cmd_filt", "h", "alt_on", False),
        ("spd", "cmd_speed", "spd_cmd_filt", "V", "speed_on", False),
        ("hdg", "cmd_heading", "hdg_cmd_filt", "psi", "heading_on", True),
    )
    for axis, cmd_k, filt_k, y_k, on_k, angular in axes:
        cmd, filt, y, on = (_arr(signals, k) for k in (cmd_k, filt_k, y_k, on_k))
        if cmd is None or filt is None or y is None:
            warnings.append(f"오차 분해(규칙 1) {axis}: 계측 채널 없음 — 구버전 결과")
            continue
        mask = (np.ones(cmd.shape, bool) if on is None else on > 0.5) & np.isfinite(filt)
        if not mask.any():
            continue
        e_f, e_l = cmd[mask] - filt[mask], filt[mask] - y[mask]
        if angular:
            e_f, e_l = wrap_pi(e_f), wrap_pi(e_l)
        r_f, r_l = _rms(e_f), _rms(e_l)
        metric = metrics.get(f"{axis}_rms")
        bad = metric is not None and metric > RMS_THRESH[axis]
        filter_led = r_f is not None and r_l is not None and r_f > FILTER_DOMINANCE * r_l
        ev = {"rms_filter": r_f, "rms_loop": r_l,
              "ratio": None if not r_l else r_f / r_l,
              "active_frac": float(mask.mean()), "metric": metric,
              "threshold": RMS_THRESH[axis]}
        if not bad:
            findings.append(Finding(
                "error_split", axis, "info",
                f"{axis} 추종 RMS {0.0 if metric is None else metric:.3g} — 문턱 안", ev))
            continue
        knobs_map = _AP_AXIS[axis]
        if filter_led:
            findings.append(Finding(
                "error_split", axis, "warn",
                f"{axis} 추종 미달의 지배 성분이 명령필터 지연 — 게인을 올려도 "
                "이 오차는 남는다", ev))
            pres.append(Prescription(
                knobs=(knobs_map["tau"],), knob_class="filter", direction="decrease",
                findings=(len(findings) - 1,), recheck=COUPLING["filter"]))
        else:
            findings.append(Finding(
                "error_split", axis, "warn",
                f"{axis} 추종 미달의 지배 성분이 루프 오차 — 필터는 명령을 다 냈다", ev))
            pres.append(Prescription(
                knobs=(knobs_map["kp"], knobs_map["ki"]), knob_class="loop_gain",
                direction="increase", findings=(len(findings) - 1,),
                recheck=COUPLING["loop_gain"]))


def _rule_saturation(signals, metrics, findings, pres, warnings):
    """규칙 2 — 포화 틱 판정은 기록값 비교(|포화 전 − 후| > tol)다: 클램프 값을
    재기술하지 않아도 두 채널의 괴리가 곧 포화다. 그 틱에서 기여항 평균을 비교해
    지배 게인 그룹을 귀속한다."""
    axes = (
        # (axis, pre, post, [(기여 신호, knobs, class), ...])
        ("pitch", "pitch_raw", "pitch",
         (("pitch_pi", (_SCAS_AXIS["pitch"]["kp"], _SCAS_AXIS["pitch"]["ki"]),
           "loop_gain"),
          ("pitch_damp", (_SCAS_AXIS["pitch"]["rate"],), "rate_gain"))),
        ("roll", "roll_raw", "roll",
         (("roll_pi", (_SCAS_AXIS["roll"]["kp"], _SCAS_AXIS["roll"]["ki"]),
           "loop_gain"),
          ("roll_damp", (_SCAS_AXIS["roll"]["rate"],), "rate_gain"))),
        ("yaw", "yaw_raw", "yaw",
         (("yaw_pi", (_SCAS_AXIS["yaw"]["kp"], _SCAS_AXIS["yaw"]["ki"]),
           "loop_gain"),
          ("yaw_damp", (_SCAS_AXIS["yaw"]["rate"],), "rate_gain"))),
        # AP 피치 명령 경로 — 축 클램프와 FF 재클램프가 같은 한계(theta_lo/hi)라
        # 최종 클램프 비교가 곧 경로 포화다 (fcl/graphs.py autopilot_nodes)
        ("alt", "ap_theta_raw", "theta_cmd",
         (("ap_alt_pi", (_AP_AXIS["alt"]["kp"], _AP_AXIS["alt"]["ki"]), "loop_gain"),
          ("ap_alt_damp", (_AP_AXIS["alt"]["damp"],), "rate_gain"),
          ("ap_pitch_ff", (_AP_AXIS["alt"]["ff"],), "loop_gain"))),
    )
    for axis, pre_k, post_k, contribs in axes:
        pre, post = _arr(signals, pre_k), _arr(signals, post_k)
        if pre is None or post is None:
            warnings.append(f"포화 기여(규칙 2) {axis}: 계측 채널 없음 — 구버전 결과")
            continue
        ok = np.isfinite(pre) & np.isfinite(post)
        if axis == "alt" and not ok.any():
            # FF 미장착 형상은 ap_theta_raw가 NaN — 축 클램프 전 합으로 대체
            pre = _arr(signals, "ap_alt_raw")
            if pre is None:
                continue
            ok = np.isfinite(pre) & np.isfinite(post)
        if not ok.any():
            continue
        sat = ok & (np.abs(np.where(ok, pre, 0.0) - np.where(ok, post, 0.0)) > SAT_TOL)
        frac = float(sat.mean())
        if frac == 0.0:
            continue
        means = []
        for sig_k, knobs, klass in contribs:
            c = _arr(signals, sig_k)
            if c is None:
                continue
            v = c[sat & np.isfinite(c)]
            if v.size:
                means.append((float(np.mean(np.abs(v))), sig_k, knobs, klass))
        means.sort(reverse=True)
        ev = {"sat_frac": frac, "threshold": SAT_FRAC_WARN}
        for m, sig_k, _kn, _kl in means:
            ev[f"mean_{sig_k.split('_')[-1]}"] = m
        if frac <= SAT_FRAC_WARN or not means:
            findings.append(Finding(
                "sat_attrib", axis, "info",
                f"{axis} 축 포화 {frac:.1%} — 문턱 안", ev))
            continue
        top = means[0]
        dominant = len(means) == 1 or top[0] > CONTRIB_DOMINANCE * means[1][0]
        findings.append(Finding(
            "sat_attrib", axis, "warn",
            f"{axis} 축 포화 {frac:.1%} — 지배 기여 {top[1]}", ev))
        notes = () if dominant else ("지배 불명확 — 차순위 기여를 joint_with로 낸다",)
        pres.append(Prescription(
            knobs=top[2], knob_class=top[3], direction="decrease",
            findings=(len(findings) - 1,),
            joint_with=() if dominant else means[1][2],
            recheck=COUPLING[top[3]], notes=notes))

    # 믹서(물리 타면) 포화 — 축 명령이 아니라 타면 예산의 문제. de·da 기여로
    # 피치/롤 어느 축이 예산을 먹는지 귀속한다 (엘레본은 두 축이 예산을 공유)
    frac = metrics.get("surf_sat_frac")
    if frac is not None and frac > SAT_FRAC_WARN:
        de, da = _arr(signals, "de"), _arr(signals, "da")
        if de is not None and da is not None:
            m_de, m_da = float(np.mean(np.abs(de))), float(np.mean(np.abs(da)))
            axis = "pitch" if m_de >= m_da else "roll"
            ev = {"surf_sat_frac": frac, "mean_de": m_de, "mean_da": m_da,
                  "threshold": SAT_FRAC_WARN}
            findings.append(Finding(
                "mix_sat", axis, "warn",
                f"타면 포화 {frac:.1%} — 엘레본 예산을 {axis} 축이 주도", ev))
            km = _SCAS_AXIS[axis]
            pres.append(Prescription(
                knobs=(km["kp"], km["ki"]), knob_class="loop_gain",
                direction="decrease", findings=(len(findings) - 1,),
                joint_with=(km["rate"],), recheck=COUPLING["loop_gain"]))


# 와인드업 시그니처가 **PID의 안티와인드업 형태를 따라간다** — 조건부 적분(현행)에서는
# 적분기가 클램프까지 못 가고 그 직전에서 얼어붙는다. 종전의 "클램프에 주차"만 보면
# 규칙이 조용히 죽는다 (blocks/controllers.py PID). 그래서 두 시그니처를 함께 본다:
#   ① 주차 — 적분기가 클램프에 붙어 있다 (클램프형에서 나오던 형태, 여전히 유효)
#   ② 동결 — PID **출력이 한계에 붙은 채** 적분기가 안 움직인다 (조건부 적분의 형태)
# 둘 중 하나면 "적분이 막힌 시간"이고, 그 비율이 곧 이 규칙이 재던 값이다.
_FROZEN_TOL = 1e-12  # 조건부 적분에서 막힌 스텝의 증분은 정확히 0이다


def _pid_integrator_is_live(i) -> bool:
    """그 축에 **적분기가 실제로 있는가** — ki = 0이면 ②의 전제가 성립하지 않는다.

    요축은 설계상 ki = 0인 댐퍼다(fcl/demo.py). 적분기가 구조적으로 안 움직이므로
    "동결 + 출력 포화"가 항상 참이 되어 100% 오탐이 나고, 처방은 **이미 0인 게인을
    줄이라**고 말하게 된다 — 진단이 낼 수 있는 최악의 종류다.

    판정은 적분기 신호 자체로 한다: 런 전체에서 한 번도 안 움직였으면 적분기가 없는
    것과 구분할 수 없고, 어느 쪽이든 ②로 할 말이 없다. (게인은 스케줄 조회값일 수
    있어 형상 상수보다 실측 신호가 정확하다.)
    """
    fin = i[np.isfinite(i)]
    return fin.size > 1 and float(np.max(fin) - np.min(fin)) > _FROZEN_TOL

def _rule_windup(signals, meta, dt, t, findings, pres, warnings):
    """규칙 3 — 적분이 막힌 시간을 잰다 (주차 또는 출력 포화 중 동결).
    지속을 run_stats(duty)로 집계한다. 처방은 ki 감소가 1차, 클램프 완화
    (joint_with)가 동시 후보다."""
    clamps = (meta or {}).get("clamps") or {}
    # (축, 적분기 신호, PID 출력 신호, ki id, 클램프 id) — 출력은 시그니처 ②가 쓴다
    axes = (
        ("pitch", "i_pitch", "pitch_pi", _SCAS_AXIS["pitch"]["ki"], _SCAS_AXIS["pitch"]["clamp"]),
        ("roll", "i_roll", "roll_pi", _SCAS_AXIS["roll"]["ki"], _SCAS_AXIS["roll"]["clamp"]),
        ("yaw", "i_yaw", "yaw_pi", _SCAS_AXIS["yaw"]["ki"], _SCAS_AXIS["yaw"]["clamp"]),
        ("alt", "i_alt", "ap_alt_pi", _AP_AXIS["alt"]["ki"], _AP_AXIS["alt"]["clamp"]),
        ("spd", "i_spd", "ap_spd_pi", _AP_AXIS["spd"]["ki"], _AP_AXIS["spd"]["clamp"]),
        ("hdg", "i_hdg", "ap_hdg_pi", _AP_AXIS["hdg"]["ki"], _AP_AXIS["hdg"]["clamp"]),
    )
    # 계측 신호는 **제어 틱마다만 갱신되고 사이 스텝은 직전 값이 유지된다**
    # (sim/simulator.py). 그 사이 스텝을 "동결"로 읽으면 자유롭게 적분 중인 축이
    # 막힌 것으로 잡힌다 — control_hz는 스윕 노브라(pipeline/influence.py) 제어주기를
    # 낮추면 "와인드업이니 ki를 줄여라"가 나오는 오도가 생긴다. duty.py와 같은
    # 방식으로 제어 틱만 본다.
    control_hz = float((meta or {}).get("control_hz") or 0.0)
    if control_hz > 0 and dt > 0:
        step = max(1, int(round(1.0 / (control_hz * dt))))
    else:
        # step=1로 조용히 되돌아가면 ZOH 구간이 전부 "동결"로 잡혀 오탐이 돌아온다.
        # 지금은 clamps가 있으면 control_hz도 반드시 있지만(둘 다 sim meta), 그건
        # 커밋 순서에 기댄 안전이다 — 없으면 ②를 접고 경고를 남긴다.
        step = 0
    for axis, i_k, out_k, ki_id, clamp_ids in axes:
        i = _arr(signals, i_k)
        cl = clamps.get(axis)
        if i is None or cl is None:
            continue  # 구버전 결과·클램프 미상 — 판정 불가 (0으로 위장하지 않는다)
        lo, hi = float(cl["lo"]), float(cl["hi"])
        tol = max(PARK_TOL_FRAC * (hi - lo), 1e-12)
        ok = np.isfinite(i)
        parked = ok & ((i >= hi - tol) | (i <= lo + tol))
        # ② 조건부 적분의 형태 — 출력이 한계에 붙은 채 적분기가 안 움직인다.
        y = _arr(signals, out_k)
        if y is None or not np.isfinite(y).any():
            # 신호 부재·전량 NaN(미장착 형상의 프로브 규약)이면 ②를 못 본다.
            # ①만 낸 값은 조건부 적분에서 죽은 시그니처라 **근거 없는 0%**가 된다 —
            # 규칙 2와 같은 규약으로 경고를 남긴다 (0으로 위장하지 않는다)
            warnings.append(f"와인드업(규칙 3) {axis}: PID 출력 계측 채널 없음 — 주차만 판정")
        elif step == 0:
            warnings.append(f"와인드업(규칙 3) {axis}: control_hz 미상 — 주차만 판정")
        elif not (np.isfinite(y) & ((y >= hi - tol) | (y <= lo + tol))).any():
            pass  # 출력이 한 번도 한계에 안 닿았다 — ②의 전제가 없다, 할 말도 없다
        elif not _pid_integrator_is_live(i):
            # 출력은 포화했는데 적분기가 런 내내 한 칸도 안 움직였다. 대개 ki = 0인
            # 축이지만(요축), **런 전체가 100% 막힌 축**도 같은 모습이다 — 후자가 이
            # 규칙이 잡아야 할 최악인데 신호만으로는 구분이 안 된다. 조용히 넘기지 않는다.
            warnings.append(
                f"와인드업(규칙 3) {axis}: 출력 포화 중 적분기가 런 내내 정지 — "
                f"ki=0이거나 전 구간 막힘, 신호로는 구분 불가라 판정 보류")
        else:
            frozen = np.abs(np.diff(i)) <= _FROZEN_TOL
            saturated = np.isfinite(y) & ((y >= hi - tol) | (y <= lo + tol))
            blocked = np.zeros(i.shape, dtype=bool)
            # 제어 틱 표본만 판정한다 — 틱 사이는 ZOH 유지 구간이지 동결이 아니다.
            # 첫 틱은 직전 틱이 없어 증분을 못 재므로 제외한다.
            idx = np.arange(step, i.size, step)
            if idx.size == 0:
                # 런이 제어 틱 하나보다 짧다 — 증분을 잴 구간이 없다
                warnings.append(
                    f"와인드업(규칙 3) {axis}: 런이 제어주기보다 짧다 — 주차만 판정")
            else:
                verdict = frozen[idx - 1] & saturated[idx] & ok[idx]
                # 그리고 **그 구간 전체로 펼친다.** 틱 표본 하나로만 세면 판정량이
                # 제어주기에 매인다 — frac이 1/step로 희석되고(문턱 0.02는 step≥50에서
                # 구조적으로 도달 불가), events가 틱 수로 폭증하고, longest가 항상
                # dt_plant 한 칸이 되어 "51 s 연속 막힘"이 "최장 0.01 s"로 나간다.
                spread = np.repeat(verdict, step)[: i.size - step]
                blocked[step : step + spread.size] = spread
            parked = parked | blocked
        stats = run_stats(parked, dt, t)
        if stats["frac"] == 0.0:
            continue
        ev = {"parked_frac": stats["frac"], "events": stats["events"],
              "longest": stats["longest"], "first_t": stats["first_t"],
              "clamp": [lo, hi], "threshold": WINDUP_FRAC}
        if stats["frac"] <= WINDUP_FRAC:
            findings.append(Finding(
                "windup", axis, "info",
                f"{axis} 적분 막힘 {stats['frac']:.1%} — 문턱 안", ev))
            continue
        findings.append(Finding(
            "windup", axis, "warn",
            f"{axis} 적분이 {stats['frac']:.1%} 막혀 있었다 (최장 "
            f"{stats['longest']:.2g} s) — ki·출력 한계 상호작용", ev))
        pres.append(Prescription(
            knobs=(ki_id,), knob_class="loop_gain", direction="decrease",
            findings=(len(findings) - 1,), joint_with=clamp_ids,
            recheck=COUPLING["clamp"],
            notes=("클램프 완화(joint_with)가 동시 수정 후보 — ki만 줄이면 "
                   "정상상태 수렴이 느려진다",)))


def _rule_limiter(signals, dt, t, findings, pres, warnings):
    """규칙 5 — 리미터 작동 구간의 귀속: α 마진 침투 동반이면 피치 응답이 경계를
    넘는 것(감쇠 문제), 침투 없이 지속이면 margin이 임무 대비 보수적이거나 임무가
    경계에 붙어 있는 것(margin/임무 문제)."""
    active = signals.get("limiter_active")
    if active is None:
        return
    active = np.asarray(active, dtype=bool)
    if not active.any():
        return
    stats = run_stats(active, dt, t)
    am = _arr(signals, "alpha_margin")
    min_margin = None
    if am is not None:
        v = am[active & np.isfinite(am)]
        min_margin = float(v.min()) if v.size else None
    ev = {"active_frac": stats["frac"], "events": stats["events"],
          "longest": stats["longest"], "min_alpha_margin_while_active": min_margin,
          "threshold": LIMITER_FRAC}
    if stats["frac"] <= LIMITER_FRAC:
        findings.append(Finding(
            "limiter", "pitch", "info",
            f"리미터 작동 {stats['frac']:.1%} — 문턱 안", ev))
        return
    penetrated = min_margin is not None and min_margin < 0.0
    if penetrated:
        findings.append(Finding(
            "limiter", "pitch", "warn",
            f"리미터 작동 {stats['frac']:.1%} 중 α 보호 경계 침투 "
            f"(min {min_margin:.3g} rad) — 피치 감쇠 부족", ev))
        pres.append(Prescription(
            knobs=(_SCAS_AXIS["pitch"]["rate"],), knob_class="rate_gain",
            direction="increase", findings=(len(findings) - 1,),
            joint_with=(_SCAS_AXIS["pitch"]["kp"],),
            recheck=COUPLING["rate_gain"]))
    else:
        findings.append(Finding(
            "limiter", "pitch", "warn",
            f"리미터 작동 {stats['frac']:.1%}, α 침투 없음 — margin이 보수적이거나 "
            "임무가 경계에 붙어 있다", ev))
        pres.append(Prescription(
            knobs=("fcl/AlphaLimiter.margin",), knob_class="limiter",
            direction="decrease", findings=(len(findings) - 1,),
            recheck=COUPLING["limiter"],
            notes=("임무 프로파일 완화가 대안 — margin은 보호 여유와 맞바꾼다",)))


def _table_id(pid):
    """손잡이 id → 스케줄 곡선 배율 id (승격 대상). 없으면 None."""
    if pid.startswith("fcl/ScasAxis."):
        _, axis, key = pid.split(".", 2)
        return f"table.{axis}.{key}"
    if pid.startswith("fcl/Autopilot."):
        gk = _AP_GROUP_OF.get(pid.split(".", 1)[1])
        return None if gk is None else f"table.{gk[0]}.{gk[1]}"
    return None


def _cross_check(shape, pres, warnings, probe_rel):
    """교차 규칙 — 승격(overridden/inert → table.*) + 도달 원뿔 교집합(joint_with).

    param_impacts는 처방에 등장한 손잡이(+승격 후보)만 계산한다 — 전 우주를 다시
    돌리면 진단이 1단 전체 비용을 지불한다.
    """
    universe = {r.id: r for r in param_universe(shape)}
    wanted = set()
    for p in pres:
        for pid in (*p.knobs, *p.joint_with):
            wanted.add(pid)
            promo = _table_id(pid)
            if promo:
                wanted.add(promo)
    refs = [universe[i] for i in sorted(wanted) if i in universe]
    impacts = param_impacts(shape, refs, probe_rel=probe_rel) if refs else {}

    def resolve(ids):
        out, notes = [], []
        for pid in ids:
            if pid not in universe:
                warnings.append(f"처방 손잡이가 이 형상에 없다: {pid} — 무시")
                continue
            imp = impacts.get(pid)
            if imp is not None and (imp.overridden or imp.inert):
                promo = _table_id(pid)
                if promo and promo in universe:
                    notes.append(f"{pid} → {promo} 승격 — 스케줄이 덮는 자리라 "
                                 "곡선 배율이 실효 손잡이다")
                    out.append(promo)
                    continue
                warnings.append(
                    f"{pid}: 스케줄이 덮는 자리인데 승격 대상이 없다 — 편집해도 "
                    "실행에 반영되지 않는다")
            out.append(pid)
        return tuple(dict.fromkeys(out)), tuple(notes)

    for p in pres:
        knobs, notes = resolve(p.knobs)
        joint, jnotes = resolve(p.joint_with)
        p.knobs, p.joint_with = knobs, tuple(k for k in joint if k not in knobs)
        p.notes = (*p.notes, *notes, *jnotes)

    # 도달 원뿔 교집합 — 서로 다른 처방의 손잡이가 같은 하류를 크게 공유하면
    # 한쪽만 움직이는 것은 반쪽 처방이다 (동시 수정 후보로 표시만 한다)
    reach = {}
    for pid in {k for p in pres for k in p.knobs}:
        imp = impacts.get(pid)
        if imp is not None and imp.reach:
            reach[pid] = set(imp.reach)
    for i, a in enumerate(pres):
        for b in pres[i + 1:]:
            hit = False
            for ka in a.knobs:
                for kb in b.knobs:
                    ra, rb = reach.get(ka), reach.get(kb)
                    if not ra or not rb:
                        continue
                    if len(ra & rb) / len(ra | rb) >= JOINT_JACCARD:
                        hit = True
            if hit:
                a.joint_with = tuple(dict.fromkeys(
                    (*a.joint_with, *(k for k in b.knobs if k not in a.knobs))))
                b.joint_with = tuple(dict.fromkeys(
                    (*b.joint_with, *(k for k in a.knobs if k not in b.knobs))))


def diagnose_run(payload, shape: Shape, *, probe_rel: float = 0.01) -> dict:
    """폐루프 런 하나 → 진단(findings) + 처방 카드(prescriptions).

    payload는 SimResult의 (t, signals, envelope, meta) — JSON 왕복본 수용
    (duty_report와 같은 계약: 저장된 원본을 쥔 서버가 부른다). shape는 이 런을
    만든 형상 — 처방 승격(스케줄 자리 판정)과 스윕 계보의 기준이다.
    """
    t = np.asarray(payload["t"], dtype=float)
    signals = payload.get("signals") or {}
    envelope = payload.get("envelope") or {}
    meta = payload.get("meta") or {}
    dt = float(meta.get("dt_plant") or (t[1] - t[0] if t.size > 1 else 1.0))

    metrics = metric_values(t, signals, envelope, meta)
    findings: list[Finding] = []
    pres: list[Prescription] = []
    warnings: list[str] = []

    _rule_error_split(signals, metrics, findings, pres, warnings)
    _rule_saturation(signals, metrics, findings, pres, warnings)
    _rule_windup(signals, meta, dt, t, findings, pres, warnings)
    _rule_limiter(signals, dt, t, findings, pres, warnings)
    _cross_check(shape, pres, warnings, probe_rel)

    return {
        "fingerprint": shape.fingerprint(),
        "metrics": metrics,
        "findings": [f.as_dict() for f in findings],
        "prescriptions": [p.as_dict() for p in pres],
        "warnings": warnings,
        "thresholds": THRESHOLDS,
    }


# ── 규칙 4: 국소성 (케이스 격자별 지표 — 3단 스윕의 기준런이 입력) ─────────

# 지표별 결함 판정 — (문턱, 초과가 나쁨 여부). worst_stall_margin만 미만이 나쁨.
_GRID_CHECKS = {
    "alt_rms": (RMS_THRESH["alt"], True),
    "spd_rms": (RMS_THRESH["spd"], True),
    "hdg_rms": (RMS_THRESH["hdg"], True),
    "surf_sat_frac": (SAT_FRAC_WARN, True),
    "limiter_frac": (LIMITER_FRAC, True),
    "worst_stall_margin": (0.0, False),
}


def diagnose_grid(per_case, thresholds=None) -> dict:
    """규칙 4 — 케이스 격자별 지표의 국소성 판정.

    per_case: [{"case": {...}, "metrics": {...}, "aborted": ...}]. 결함이 격자
    일부에 몰리면 스케줄(테이블 형상 — 그 구간 셀), 전반이면 설계점 게인 수준이
    처방 클래스다. 구체 knobs는 정하지 않는다 — 어느 자리가 얼마나인지는 3단
    스윕이 정량으로 답한다. 단일런 진단(diagnose_run)과 의존이 없다 — 격자 런이
    생기면 소급 활성화되는 별도 입력이다.

    **잘린 런(aborted)은 통째로 뺀다** — 발산으로 중단된 런의 지표는 잘린 구간
    만의 값이라 문턱 안으로 보일 수 있고, 그러면 판정 불가가 "정상"으로 위장된다.
    n_cases는 실제로 잰 케이스 수다.
    """
    checks = dict(_GRID_CHECKS)
    if thresholds:
        for k, v in thresholds.items():
            if k in checks:
                checks[k] = (float(v), checks[k][1])
    usable = [pc for pc in per_case if not pc.get("aborted")]
    out = {}
    for key, (thresh, above_is_bad) in checks.items():
        rows = [(pc.get("case") or {}, (pc.get("metrics") or {}).get(key))
                for pc in usable]
        known = [(c, v) for c, v in rows if v is not None]
        if not known:
            continue
        bad = [c for c, v in known
               if (v > thresh) == above_is_bad and v != thresh]
        frac = len(bad) / len(known)
        if not bad:
            verdict, klass = "ok", None
        elif frac <= LOCAL_FRAC:
            verdict, klass = "local", "schedule"
        else:
            verdict, klass = "global", "loop_gain"
        out[key] = {
            "threshold": thresh, "n_cases": len(known), "n_bad": len(bad),
            "bad_frac": frac, "bad_cases": bad, "verdict": verdict,
            "knob_class": klass,
        }
    return {"metrics": out, "local_frac": LOCAL_FRAC}
