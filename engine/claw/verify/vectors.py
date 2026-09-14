"""보강 시험 벡터 — 미션이 안 밟는 방향을 닫는 **이름 붙은 시험 케이스** (M12).

VectorCAST의 시험 케이스 목록에 해당하는 재료다. 전부 **결정적**이다(난수 없음) —
같은 형상이면 같은 벡터이고, 회귀 비교가 의미를 갖는다.

두 층이 있다:
  통합 케이스  전체 법칙(fcl) 입력 시퀀스 — 미션 종료 상태에서 이어 돌린다.
              축별 포화 왕복(안티와인드업 가드 4방향), 모드 토글·홀드, 스케줄
              스윕, 리미터 개입, 배분 극단, 각속도 극단.
  유닛 케이스  파티션(fcl_sched·fcl_ap·…) 임포트 시퀀스 — 유닛 하나를 떼어 돌린다.
              이름 기반 값 정책(_POLICY)으로 어떤 형상의 임포트 목록에도 값을
              만들 수 있고, 와인드업→언와인드→비활성→격자 4악장 구성이다.

값 정책의 크기는 물리 단위 기준으로 고른 극단이다 — 목적이 성능이 아니라
**분기·MC/DC 방향을 태우는 것**이므로 정상 운용 범위를 일부러 넘는다 (강건성
시험의 성격, NaN·Inf는 넣지 않는다: 비트 대조 자체를 오염시키고, 비행 중 예외
금지 원칙상 생성 코드에 NaN 분기가 없다).
"""

# ── 통합 케이스 (fcl 전체 입력) ───────────────────────────────────────────

# 순항 비슷한 기준 행 — 케이스는 여기서 필요한 축만 극단으로 민다
_BASE = {
    "nav_valid": 1.0, "theta": 0.05, "phi": 0.0, "psi": 0.0,
    "p": 0.0, "q": 0.0, "r": 0.0, "V": 150.0, "alpha": 0.05, "beta": 0.0,
    "h": 1000.0, "hdot": 0.0, "mach": 0.45,
    "cmd_speed": 150.0, "cmd_alt": 1000.0, "cmd_heading": 0.0,
    "cmd_pitch": 0.0, "cmd_hdot": 0.0,
    "speed_on": 1.0, "alt_on": 1.0, "heading_on": 1.0,
    "pitch_on": 0.0, "hdot_on": 0.0,
}


def _rows(n, **over):
    row = dict(_BASE)
    row.update(over)
    return [dict(row) for _ in range(n)]


def _sat_case(cid, title, hi_over, lo_over, n=250):
    """포화 왕복 — 한 방향으로 적분기를 채우고(가드 참측) 반대로 되민다(반대측).

    반전 직후가 요점이다: 축은 아직 포화 쪽인데 증분은 반대 부호라 가드의
    (c0 참, c1 거짓)류 벡터가 생긴다 — MC/DC 독립쌍의 재료.
    """
    return {"id": cid, "title": title,
            "rows": _rows(n, **hi_over) + _rows(n, **lo_over)}


# 단계 길이가 kp/ki에 비례한다 — ki_vs는 ParamDef 하한이 없어 웹에서 작게 둘 수 있고(0.001이면 약 166,000행) 그 행이
# Python·C 하네스·MC/DC 실행을 전부 지난다. 넘으면 붙이지 않는다 — 상한 조건이 미커버로 남아 판정이 fail로 말한다
_DROP_MAX_ROWS = 12_000


def _theta_hi_drop_case(autopilot, dt):
    """θ 상한 표가 스텝 사이에 내려가는 순간의 승강률 적분기(v1.11) — 가드 상한 조건의 (c0 참, c1 거짓) 벡터.

    상한이 신호(θ_hi(M))라 그 조건은 정당화할 수 없다(verify/autocode.py _coupled_guards) — 오차 ≤ 0인데 raw > hi는
    적분기가 새 상한보다 높을 때만 생기므로 측정으로 덮는다. 적분기를 올리는 것이 까다롭다: 조건부 적분은 raw가 한계를
    넘으면 적분을 멈추므로 **큰 오차로는 적분기가 안 오른다**(처음 넣은 고정 벡터가 그렇게 실패했다). 그래서 kp·e를
    0.3 → 0.1 → 0.02로 줄이며 적분기를 −0.3에서 hi − 0.02 근처까지 올린다 — 각 단계가 kp/ki에 비례하는 시간이라 게인에서
    길이를 정한다(두 예제 기체는 kp/ki = 4 s로 약 44 s). 마지막에 마하를 0.9로 올려 상한을 떨어뜨리고 kp·e = −0.01로 둔다.
    명령은 0에 두고 측정 hdot으로 오차를 만든다(명령 필터를 거치지 않아 단계 경계에서 오차가 바로 바뀐다).
    """
    kp, ki = float(autopilot.get("kp_vs", 0.0)), float(autopilot.get("ki_vs", 0.0))
    if not (kp > 0.0 and ki > 0.0 and dt and dt > 0.0):
        return None
    t = kp / ki

    def n(sec):
        return max(1, int(round(sec / dt)))

    if n(10.0) + n(1.2 * t) + n(2.4 * t) + n(4.8 * t) + n(0.5) > _DROP_MAX_ROWS:
        return None
    vs = dict(alt_on=0.0, hdot_on=1.0, cmd_hdot=0.0)
    rows = _rows(n(10.0), hdot=0.0, mach=0.1, **vs)  # 명령 필터를 0에 앉힌다
    for kpe, dur in ((0.3, 1.2 * t), (0.1, 2.4 * t), (0.02, 4.8 * t)):
        rows += _rows(n(dur), hdot=-kpe / kp, mach=0.1, **vs)
    rows += _rows(n(0.5), hdot=0.01 / kp, mach=0.9, **vs)
    return {"id": "TC-INT-THETA-HI-DROP", "title": "θ 상한 표 하강 중 승강률 적분기 (가드 상한 조건 거짓측)",
            "rows": rows}


def integration_cases(autopilot=None, dt=None, *, theta_hi=False):
    """통합 보강 케이스 목록 [{id, title, rows}] — 미션 뒤에 이 순서로 잇는다.

    theta_hi=True(법칙에 θ 상한 표가 있다)이고 autopilot·dt를 주면 게인에서 길이를 정하는 케이스(θ 상한 하강)를 덧붙인다 —
    이름 기반 값 정책만으로는 적분기를 원하는 높이에 올릴 수 없는 경로다. 표가 없으면(리미터 끔) 상한이 상수라 그 조건은
    정당화되므로 붙이지 않는다.
    """
    cases = [
        _sat_case("TC-INT-SAT-ALT", "고도축 포화 왕복 (θ 상·하한, 안티와인드업 4방향)",
                  dict(cmd_alt=60000.0), dict(cmd_alt=-40000.0)),
        _sat_case("TC-INT-SAT-VS", "승강률축 포화 왕복",
                  dict(alt_on=0.0, hdot_on=1.0, cmd_hdot=200.0),
                  dict(alt_on=0.0, hdot_on=1.0, cmd_hdot=-200.0)),
        _sat_case("TC-INT-SAT-SPD", "속도축 포화 왕복 (스로틀 0·1)",
                  dict(cmd_speed=900.0), dict(cmd_speed=0.0), n=350),
        _sat_case("TC-INT-SAT-SCAS", "SCAS 피치·롤 포화 왕복 (배분 한계 기준)",
                  dict(cmd_pitch=1.2, pitch_on=1.0, alt_on=0.0,
                       cmd_heading=3.0, theta=-0.4, phi=-0.8),
                  dict(cmd_pitch=-1.2, pitch_on=1.0, alt_on=0.0,
                       cmd_heading=-3.0, theta=0.4, phi=0.8)),
        # 헤딩 ±π 경계 — wrap_pi의 보정 가지(r<0)와 각도 필터 최단 경로.
        # 꺼진 스텝이 필터를 ψ에 앉히므로(on_disable) 경계 통과가 재현 가능해진다
        {"id": "TC-INT-HDG-WRAP", "title": "헤딩 ±π 경계 통과 (wrap_pi 보정 가지)",
         "rows": _rows(5, heading_on=0.0, psi=-3.1)
                 + _rows(120, psi=-3.1, cmd_heading=3.1)
                 + _rows(5, heading_on=0.0, psi=3.1)
                 + _rows(120, psi=3.1, cmd_heading=-3.1)},
        {"id": "TC-INT-MODES", "title": "모드 플래그 조합·항법 무효 홀드",
         "rows": _rows(20, speed_on=0.0, alt_on=0.0, heading_on=0.0)
                 + _rows(20, nav_valid=0.0)
                 + _rows(20, pitch_on=1.0, alt_on=0.0, cmd_pitch=0.2)
                 + _rows(20, hdot_on=1.0, alt_on=0.0, cmd_hdot=-5.0)
                 + _rows(20)},
        {"id": "TC-INT-SCHED-SWEEP", "title": "mach 스윕 (룩업 클립 양끝·구간 전체)",
         "rows": [dict(_BASE, mach=0.02 + 0.96 * k / 199.0) for k in range(200)]},
        {"id": "TC-INT-LIMITER", "title": "α 리미터 개입·해제 (min2·gt 양방향)",
         "rows": [dict(_BASE, pitch_on=1.0, alt_on=0.0, cmd_pitch=0.5,
                       alpha=-0.1 + 0.7 * k / 149.0) for k in range(150)]},
        _sat_case("TC-INT-RATE", "각속도·측미끄럼 극단 (워시아웃·댐퍼 양부호)",
                  dict(p=4.0, q=4.0, r=4.0, beta=0.5),
                  dict(p=-4.0, q=-4.0, r=-4.0, beta=-0.5), n=120),
    ]
    drop = _theta_hi_drop_case(autopilot, dt) if (theta_hi and autopilot is not None) else None
    if drop is not None:
        cases.append(drop)
    return cases


# ── 유닛 케이스 (파티션 임포트) ───────────────────────────────────────────

# 임포트 이름 → (극단 A, 극단 B, 격자) 값 정책. 없는 이름은 _DEFAULT — 파티션 경계
# 신호(…_y)는 대부분 타면·명령 스케일이라 ±0.5가 안전한 극단이다.
#
# **A·B는 "저·고"가 아니라 서로 반대편이라는 뜻뿐이다.** 어느 쪽이 큰 값인지는
# 항목마다 다르고(게인 신호는 A가 +3), 그래야 하는 이유가 있다: 상태 있는 유닛은
# 악장 **순서가 곧 궤적**이라 조합에 따라 밟는 분기가 달라진다. 지금 순서는
# 커버리지 실측으로 고른 것이고(뒤집으면 가드 분기 하나가 닫히지 않는다),
# 순서를 바꾸려면 커버리지를 다시 재야 한다.
_POLICY = {
    "mach": (0.05, 0.95, (0.05, 0.2, 0.45, 0.7, 0.95)),
    "h": (0.0, 8000.0, (0.0, 1000.0, 5000.0)),
    "V": (60.0, 250.0, (60.0, 150.0, 250.0)),
    "hdot": (-80.0, 80.0, (-40.0, 0.0, 40.0)),
    "psi": (-3.1, 3.1, (-3.1, -1.0, 0.0, 2.0, 3.1)),
    "theta": (-1.0, 1.0, (-0.5, 0.0, 0.5)),
    "phi": (-1.0, 1.0, (-0.7, 0.0, 0.7)),
    "alpha": (-0.2, 0.6, (-0.1, 0.1, 0.4)),
    "beta": (-0.5, 0.5, (-0.3, 0.0, 0.3)),
    "p": (-4.0, 4.0, (-2.0, 0.0, 2.0)),
    "q": (-4.0, 4.0, (-2.0, 0.0, 2.0)),
    "r": (-4.0, 4.0, (-2.0, 0.0, 2.0)),
    "cmd_speed": (0.0, 400.0, (0.0, 150.0, 400.0)),
    "cmd_alt": (-500.0, 20000.0, (0.0, 1000.0, 9000.0)),
    "cmd_heading": (-3.1, 3.1, (-3.1, 0.0, 3.1)),
    "cmd_pitch": (-1.0, 1.0, (-0.5, 0.0, 0.5)),
    "cmd_hdot": (-60.0, 60.0, (-30.0, 0.0, 30.0)),
    "ap_spd_sat_y": (0.0, 1.0, (0.0, 0.5, 1.0)),
}
_DEFAULT = (-0.5, 0.5, (-0.5, -0.1, 0.2, 0.5))
_FLAG = (1.0, 1.0, (0.0, 1.0))  # 와인드 구간엔 켠다 — 꺼진 축은 아무것도 안 태운다
_GAIN = (3.0, -3.0, (-3.0, -0.4, 0.4, 3.0))  # 스케줄 게인 신호 — 부호 양쪽

# 격자 악장에서 임포트마다 다른 주기로 돌려 조합이 겹치지 않게 한다 (결정적)
_STRIDES = (1, 2, 3, 5, 7, 11, 13)


def _policy(name):
    if name.endswith("_on") or name == "nav_valid":
        return _FLAG
    if name.startswith("sched_"):
        return _GAIN
    return _POLICY.get(name, _DEFAULT)


def unit_cases(group, imports, n_wind=220, n_grid=260):
    """파티션 유닛 케이스 [{id, title, rows}] — rows는 {임포트 이름: 값}.

    4악장: 와인드(전부 고값·플래그 켬) → 언와인드(전부 저값) → 비활성(플래그 끔,
    on_disable 경로) → 격자(서로소 주기 순환 — 조합 공간을 결정적으로 훑는다).
    상태 있는 유닛(적분기·필터)은 앞 두 악장의 지속 시간이 곧 와인드업 깊이다.
    """
    g = group.upper()
    a_row = {u: _policy(u)[0] for u in imports}
    b_row = {u: _policy(u)[1] for u in imports}
    off_row = {u: (0.0 if _policy(u) is _FLAG else _policy(u)[2][0]) for u in imports}
    grid = []
    for k in range(n_grid):
        row = {}
        for i, u in enumerate(imports):
            vals = _policy(u)[2]
            row[u] = vals[(k // _STRIDES[i % len(_STRIDES)]) % len(vals)]
        grid.append(row)
    return [
        {"id": f"TC-U-{g}-WIND", "title": f"{group} 유닛 — 극단 A 지속 (와인드업·한계 도달)",
         "rows": [dict(a_row) for _ in range(n_wind)]},
        {"id": f"TC-U-{g}-UNWIND", "title": f"{group} 유닛 — 극단 B 지속 (반대 방향 언와인드)",
         "rows": [dict(b_row) for _ in range(n_wind)]},
        {"id": f"TC-U-{g}-OFF", "title": f"{group} 유닛 — 비활성 (on_disable 경로)",
         "rows": [dict(off_row) for _ in range(30)]},
        {"id": f"TC-U-{g}-GRID", "title": f"{group} 유닛 — 값 격자 순환 (조합 훑기)",
         "rows": grid},
    ]
