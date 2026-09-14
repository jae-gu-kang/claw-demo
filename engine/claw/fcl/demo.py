"""예제 기체(구 데모 델타윙) 법칙 쪽 호환 이름 — 설계값과 조립은 기체 프로파일에 있다 (02 §5.6).

종전에는 이 모듈이 데모 기체의 SCAS·AP 설계 게인, 동압 스케줄(정규화 마하·축별 상한·스케줄 자리),
차동추력 계수, α 리미터 마진, 엘레본 할당 예약을 상수로 들고 조립 정본(make_demo_fcl)까지 겸했다.
이제 값은 예제 문서의 `law` 섹션에, 조립 정본은 `fcl/assemble.py assemble_law`에 있고, 여기 이름들은
기존 호출(주로 테스트·대조 하네스)을 위한 **얇은 호환 층**이다. 제품 코드가 import하면 가드
테스트(test_profile_guard.py)가 막는다.

수치의 근거(설계점 게인·정규화 마하·_F_CAP 파탄점 실측·축별 상한·차동추력 0·할당 예약 하한)는
02 §5.6.1로 옮겼다.
"""

from claw.fcl.assemble import assemble_law


def _example():
    # 지연 import — claw.profile의 검증기가 claw.fcl 레지스트리를 쓰므로 모듈 로드 시점에 부르면 순환한다
    from claw.profile import example_profile

    return example_profile()


def demo_design_gains() -> dict:
    return _example().design_gains()


def demo_rate_filters() -> dict:
    return _example().rate_filters()


def make_demo_gain_tables(names=None) -> dict:
    return _example().gain_tables(names)


def _cap_for(gain_name: str) -> float:
    return _example().cap_for(gain_name)


def make_demo_fcl(with_schedule=True, with_limiter=True, autopilot=None, gain_tables=None,
                  scas=None, mixer=None, alpha_margin=None, standard=False):
    return assemble_law(_example(), with_schedule=with_schedule, with_limiter=with_limiter,
                        autopilot=autopilot, gain_tables=gain_tables, scas=scas, mixer=mixer,
                        alpha_margin=alpha_margin, standard=standard)


def _legacy_axis(profile, axis):
    """종전 DEMO_* dict 모양 그대로 — washout_tau는 켜진 축(>0)에만 있었다."""
    a = profile.scas_axis_params(axis)
    out = {k: a[k] for k in ("kp", "ki", "k_rate")}
    if a["washout_tau"] > 0.0:
        out["washout_tau"] = a["washout_tau"]
    out["out_lo"], out["out_hi"] = a["out_lo"], a["out_hi"]
    return out


def _alloc_trim_table():
    return _example().alloc_trim_table()


_LAZY = {
    "DEMO_PITCH": lambda p: _legacy_axis(p, "pitch"),
    "DEMO_ROLL": lambda p: _legacy_axis(p, "roll"),
    "DEMO_YAW": lambda p: _legacy_axis(p, "yaw"),
    "DEMO_K_DIFF_THR": lambda p: p.k_diff_thr,
    "DEMO_ALPHA_MARGIN": lambda p: p.law["alpha_margin"],
    "DEMO_ALLOC_RESV_FRAC": lambda p: p.alloc_resv_frac,
    "DEMO_ALLOC_TRIM_TABLE": lambda p: _alloc_trim_table,
    "DEFAULT_SCHEDULED": lambda p: tuple(p.law["schedule"]["scheduled"]),
    "_M_DESIGN": lambda p: p.law["schedule"]["m_design"],
    "_F_CAP": lambda p: p.law["schedule"]["caps"]["default"],
    "_F_CAP_ROLL": lambda p: p.law["schedule"]["caps"]["by_group"]["roll"],
}


def __getattr__(name):
    # 모듈 상수도 문서에서 읽는다 — import 시점에 읽으면 위 순환이 생기므로 PEP 562 지연 속성
    if name in _LAZY:
        return _LAZY[name](_example())
    raise AttributeError(f"module 'claw.fcl.demo' has no attribute {name!r}")
