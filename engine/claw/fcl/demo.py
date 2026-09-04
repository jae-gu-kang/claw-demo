"""데모 델타윙 M7 조립 — 설계 게인·동압 스케줄·α 리미터·믹서 일습.

"비행체 프로파일" 교체 단위(03 §7.2)의 법칙 측 절반 — plant.demo와 짝.
SCAS·AP 게인은 설계점 M0.6 h1000 fuel200에서 선형모델 고유치 스캔 + 비선형
폐루프 확인으로 선정한 설계값 (증분 A·B 테스트가 성능 회귀 고정).

게인 스케줄 [기본값]: 동압 역비 스케일 f = min((M_design/M)², _F_CAP) — 저속에서
루프 강성 유지(피치·롤 PI·레이트 게인 공통). **상한은 저속 타면 포화 억제가 아니라
대역폭 한계에서 온다** — 사유·실측은 _F_CAP 주석에 있다(종전 4는 저속에서 내측
피치 루프를 리밋사이클에 넣었다). 폐루프 고유치 안정 확인은 상수 추력 시절의 M0.25~0.8 격자에서 한 것이고,
프로펠러 전환 뒤 수평비행 범위(해면 M0.21~0.60(연료 200 kg — 만재 400 kg면 M0.23~0.58))에서의 재확인은 [TBD]다. 1D mach 테이블이며 고도·연료 축 확장은 트림 격자 확보 후 [TBD].

**어느 게인을 스케줄할지는 형상의 일부다** — 기본은 DEFAULT_SCHEDULED 6자리이고,
전체 자리는 fcl/graphs.py SCHEDULABLE(16자리)이다. 뺀 자리는 설계점 상수로 굳어
생성 C에서 룩업이 사라진다.
"""

import numpy as np

from claw.fcl.autopilot import Autopilot
from claw.fcl.law import FlightControlLaw
from claw.fcl.limiter import AlphaLimiter
from claw.fcl.mixer import Mixer
from claw.fcl.scas import Scas, ScasAxis
from claw.fcl.schedule import GainSchedule, design_gains
from claw.plant import make_demo_stall_table
from claw.tables import Table

# 설계점 M0.6 h1000 fuel200 SCAS 게인 (증분 A 설계 스캔)
DEMO_PITCH = dict(kp=-2.0, ki=-0.5, k_rate=0.4, out_lo=-0.35, out_hi=0.35)
DEMO_ROLL = dict(kp=1.0, ki=0.1, k_rate=-0.2, out_lo=-0.35, out_hi=0.35)
DEMO_YAW = dict(kp=0.5, ki=0.0, k_rate=0.8, washout_tau=2.0, out_lo=-0.35, out_hi=0.35)

# 동압 스케일의 **정규화 상수** — 비행조건이 아니다.
#
# 프로펠러 추력 모델로 옮기면서 비행 가능 범위가 해면 M0.21~0.60(연료 200 kg — 만재
# 400 kg면 M0.23~0.58)으로 좁아졌다. M0.6은 이제 **범위의 끝**이다 — 연료 200 kg
# 해면에서 스로틀 94.1%로 겨우 서고, 연료를 실으면 못 나는 조건이 된다. 그렇다고
# 이 값을 0.4로 내리면 안 된다: 스케줄이
# K(M) = K0·min((M_design/M)², cap)이라 M_design을 내리면 **전 구간의 실효 게인이
# (0.6/0.4)² = 2.25배 낮아진다**. K0는 M0.6에서 고른 값이지만 여기 쓰이는 방식은
# "그 자리에서 1이 되는 기준점"이고, 그 기준을 옮기면 아래 _F_CAP 실측(리밋사이클
# 파탄점 4.0, 채택 2.0)이 통째로 무의미해진다. 값을 유지해 **검증된 게인 곡선을
# 그대로 보존**한다 — 새 엔벨로프에서 이 곡선은 M0.42 아래가 상한에 걸리고
# M0.42~0.59에서 1/q̄ 법칙이 산다.
_M_DESIGN = 0.6
# 동압 스케일 상한 — **작동기·항법 지연이 정하는 값이지 동압이 정하는 값이 아니다.**
#
# 1/q̄ 스케일은 "동압이 낮으면 같은 모멘트를 내려고 타를 더 친다"는 뜻이라 원리는
# 맞지만, 대역폭은 동압이 아니라 작동기(wn 30 rad/s)와 항법 지연(delay_s 30 ms —
# rtk_fixed도 같다, nav/error_model.py)이 묶는다.
# 그 둘이 고정인데 게인만 올리면 위상여유를 잃고 내측 피치 루프가 리밋사이클에
# 든다 — 상한 4.0에서 실측한 것이 그것이다:
#
#   M0.26(88 m/s) 순항에서 de가 ±20°(전 스트로크) 2 Hz로 왕복, de σ 10.6°·q σ 15.5°/s.
#   자리별로 갈라 보면 pitch.kp(σ 11.0°·q 30.0°/s)와 pitch.k_rate(σ 12.1°)가 원인이고
#   pitch.ki와 롤 3개는 무관하다(σ 3.3° = 부스트 없음과 동일).
#
# 직진 미션은 그 진동을 안고도 착륙했지만 **타면 여유가 남지 않아**, 선회를 얹는
# 순간 고도를 못 잡고 나선 강하로 지면까지 갔다(경로추종 미션 36 s·−42.6 m/s,
# 최악 실속마진 −2.73). 상한만 낮추면 같은 미션이 산다:
#
#   상한  4.0 → 추락       (마진 −2.726)
#         3.0 → 정상        (+0.040, de σ 8.3°)
#         2.0 → 정상        (+0.046, de σ 4.0°)   ← 채택
#         1.0 → 정상        (+0.052, de σ 2.3°)
#
# 2.0을 고른 이유는 파탄점(4.0)에서 배수로 떨어져 있으면서도 스케줄이 여전히 일을
# 하기 때문이다 — 상한이 물리는 것은 M < 0.6/√2 = 0.42 아래뿐이고, 그 위에서는
# 1/q̄ 법칙이 그대로다. 순항 회귀(M0.41~0.6)는 2.14가 2.0으로 깎일 뿐이다.
# 저속에서 설계 의도보다 게인이 낮은 것은 **의도한 거래**다: 낼 수 없는 대역폭을
# 좇는 것보다 안정된 응답이 낫다.
#
# 자리별로 다른 상한을 두지 않는다 — make_demo_gain_tables의 "자리마다 다른 규칙을
# 쓰면 켜는 순간 형상이 튄다"와 같은 이유다. pitch.kp만 잡아도 되지만 그러면 스케줄
# 규칙이 자리마다 갈린다.
_F_CAP = 2.0


# 기본 스케줄 대상 [기본값] — 피치·롤의 PI·레이트 게인. 요축과 AP 게인은 설계점
# 고정이다. 이 구성은 **선택 가능**하고(웹 게인 탭), 바꾸면 탑재 C 구조와 지문이
# 함께 바뀐다 — 스케줄한 자리는 룩업 + 필터 상태가 생기고 뺀 자리는 상수로 접힌다.
DEFAULT_SCHEDULED = (
    "pitch.kp", "pitch.ki", "pitch.k_rate",
    "roll.kp", "roll.ki", "roll.k_rate",
)


def demo_design_gains() -> dict:
    """데모 기체의 자리별 설계점 상수 — `make_demo_fcl`이 조립하는 값 그대로."""
    return design_gains(
        {"pitch": DEMO_PITCH, "roll": DEMO_ROLL, "yaw": DEMO_YAW}, Autopilot().cfg
    )


def demo_rate_filters() -> dict:
    """레이트 경로 필터 스펙 {그룹: 스펙} — 위 DEMO_* 프로파일이 실제로 조립하는 것.

    자동 설계(M17)가 **출하되는 조성**을 보고 튜닝·검증하도록 넘기는 값이다.
    이 dict를 안 넘기면 해석은 필터 없는 A′를 보는데, 데모 요축은 워시아웃 τ=2 s가
    켜져 있어 그 차이가 ζ_dr를 움직인다 (01 §4.2 실측 M0.3/h0 0.5951 → 0.6612).

    `washout_tau == 0`은 "그 축에 필터 없음"이라는 법칙 쪽 관용(graphs.py는 0이면
    노드를 아예 안 만든다)을 그대로 따라 목록에서 뺀다 — 해석이 법칙에 없는
    필터를 만들어 내지 않는다. 어휘 정본은 blocks.RATE_FILTERS.
    """
    out = {}
    for group, cfg in (("pitch", DEMO_PITCH), ("roll", DEMO_ROLL), ("yaw", DEMO_YAW)):
        tau = float(cfg.get("washout_tau", 0.0))
        if tau > 0.0:
            out[group] = {"kind": "washout", "tau": tau}
    return out


def make_demo_gain_tables(names=None) -> dict:
    """동압 스케일 1D mach 게인 테이블 — 기본은 피치·롤 PI·레이트 게인 6개.

    `names`로 스케줄 자리를 골라 만들 수 있다 (웹 게인 탭의 대상 선택 경로).
    새로 켠 자리도 **같은 동압 스케일**로 채운다 — 자리마다 다른 규칙을 쓰면 켜는
    순간 형상이 튀어서, 켜기 전후를 비교할 수가 없다. 설계점(M0.6)에서는 어느
    자리든 설계 상수 그대로다.
    """
    # 격자 상단을 **자르지 않는다.** 프로펠러 전환으로 수평비행 상단이 M0.60으로
    # 내려왔지만, Table이 extrapolate="clip"이라 격자를 M0.6에서 끊으면 그 위에서
    # 1/q̄ 롤오프가 사라지고 게인이 설계값에 붙박인다 — _F_CAP이 리밋사이클을 만든다고
    # 실측한 바로 그 방향(게인 과다)이다. 게다가 M0.6 위는 **강하로 도달한다**:
    # 3000 m에서 de +0.02·thr 1.0이면 M0.816, 스로틀 0에서도 M0.730이다. 종말 강하가
    # 정확히 그 구간이고, 스케줄 변수는 마하가 아니라 동압이라 거기서 더 중요하다.
    # (하단 0.15→0.20은 무해하다 — M0.424 아래는 _F_CAP이 이미 평평하게 만든다.
    #  그래서 굳이 안 건드리고 종전 격자를 그대로 둔다.)
    machs = np.round(np.arange(0.15, 0.951, 0.05), 4)
    f = np.minimum((_M_DESIGN / machs) ** 2, _F_CAP)
    design = demo_design_gains()
    wanted = DEFAULT_SCHEDULED if names is None else tuple(names)
    unknown = [n for n in wanted if n not in design]
    if unknown:
        raise ValueError(f"스케줄 불가 자리 {unknown} — 허용: {sorted(design)}")
    return {
        name: Table({"mach": machs}, design[name] * f, name=name, extrapolate="clip")
        for name in wanted
    }


# 설계 기본값 — 조립이 쓰는 값 그대로. 주입 인자가 None일 때 여기서 만든다
# 차동추력 러더 보조 — **0이다. 데모 기체가 단발이기 때문이다** (plant/demo.py:
# PropEngine 중심선 1기). 중심선 1기는 좌우 추력차로 요 모멘트를 못 내므로 이
# 계수를 켜면 법칙은 요축을 돕는다고 믿는데 기체는 아무것도 안 하고, 스로틀이
# 상·하한에 붙은 구간에서는 좌우 클립이 비대칭이라 **평균이 밀려 러더가 추력을 깎는**
# 진짜 버그가 된다 (plant/prop.py PropEngine·SingleEngine 참조).
#
# 구조는 지운 게 아니라 값으로 껐다 — 믹서의 차동추력 노드는 그대로 있고(생성 C도
# 같다) 쌍발 형상(TwinEngine)을 물리면 계수만 되살리면 된다. 부호 기준은 그대로
# "Cn_dr<0 프로파일에서 +".
#
# **요축 재튜닝은 하지 않았다 — 실측으로 불필요하다고 판정했다.** 헤딩 30° 스텝
# 폐루프 비교(쌍발+0.1 vs 단발+0):
#   M0.6/1000 m  t90 13.78 s 동일, |δr|max 0.0320→0.0327 (+2%), ψ 차이 0.00°
#   M0.25/200 m  t90 7.06→6.97 s,  |δr|max 0.0986→0.1059 (+7%), ψ 차이 0.50°
# 이유: 이 기체의 선회는 뱅크로 만들고 요축 SCAS는 댐퍼다(ki=0). 러더 변위 자체가
# 작아(≤0.11 rad, 한계 0.35의 30%) 거기 비례하는 추력차 기여도 작았다. 저속에서
# 비중이 커지는 것은 차동추력이 동압과 무관한 반면 러더 모멘트는 q̄에 비례하기
# 때문인데, 그 저속에서도 러더 여유가 충분해 게인을 올릴 이유가 없었다.
DEMO_K_DIFF_THR = 0.0
DEMO_ALPHA_MARGIN = 0.05  # α 리미터 실속 마진 [rad] (01 §3.6)


def make_demo_fcl(
    with_schedule: bool = True,
    with_limiter: bool = True,
    autopilot: Autopilot | None = None,
    gain_tables: dict | None = None,
    scas: Scas | None = None,
    mixer: Mixer | None = None,
    alpha_margin: float | None = None,
) -> FlightControlLaw:
    """데모 기체 FCL 조립 — init(dt) 후 reset(트림 웜스타트)으로 사용.

    **조립 정본은 이 함수 하나다** (02 v0.24) — 생성기·서버·해석 모듈이 전부 여기를
    지난다. 아래 주입 인자들은 그 정본을 우회하는 통로가 아니라, 정본이 받는 손잡이다.

    autopilot·scas·mixer·alpha_margin 주입은 **파라미터 스터디용** (파이프라인
    Δ리포트·민감도 스윕에서 게인을 흔들 때, M15) — None이면 설계 기본값.
    gain_tables 주입은 게인 스케줄 편집 경로 (M13/M14, 02 §8 4단계) — None이면
    설계 테이블. 주입은 **전체 교체**(설계 테이블과 병합 아님 — 일부만 주입하면
    나머지 게인은 스케줄 없이 설계점 고정값). 그룹·키 검증은 FCL 조립이 수행.

    alpha_margin은 with_limiter=True에서만 뜻이 있다 — 리미터 없는 형상에 마진을
    주는 것은 조용히 무시되면 안 되는 모순이라 예외로 막는다.
    """
    if gain_tables is not None and not with_schedule:
        raise ValueError("gain_tables 주입은 with_schedule=True에서만 유효")
    if alpha_margin is not None and not with_limiter:
        raise ValueError("alpha_margin 주입은 with_limiter=True에서만 유효")
    scas = scas if scas is not None else Scas(
        ScasAxis(**DEMO_PITCH), ScasAxis(**DEMO_ROLL), ScasAxis(**DEMO_YAW)
    )
    ap = autopilot if autopilot is not None else Autopilot()  # 기본값 = 증분 B 설계값
    mixer = mixer if mixer is not None else Mixer(k_diff_thr=DEMO_K_DIFF_THR)
    schedule = (
        GainSchedule(
            gain_tables if gain_tables is not None else make_demo_gain_tables(),
            filter_tau=0.5,
        )
        if with_schedule
        else None
    )
    limiter = (
        AlphaLimiter(
            make_demo_stall_table(),
            margin=DEMO_ALPHA_MARGIN if alpha_margin is None else float(alpha_margin),
        )
        if with_limiter
        else None
    )
    return FlightControlLaw(scas, ap, mixer, schedule=schedule, alpha_limiter=limiter)
