"""추진 모델 — 스로틀-추력 맵 + 엔진 배치 모멘트 (01 §2.1·§2.4).

세 형상이 있고 전부 레지스트리 "propulsion" 카테고리에 등록된다
(plant/__init__.py — 교체 가능 컴포넌트 02 §2.3):

- **PropEngine** — 중심선 프로펠러 1기. **데모 기체의 정본 형상**이다 (시각화 모델
  models/shahed-136: 2엽 푸셔 1기). 추력이 속도·밀도를 탄다. 요 모멘트를 못 낸다.
- **SingleEngine** — 중심선 1기, **상수 추력**(T = T_max·δ). thrust_map 주입으로
  임의 추력 맵을 넣을 수 있는 자리라 남는다 — PropEngine이 못 하는 일이다.
- **TwinEngine** — 좌우 2기, 상수 추력. 차동추력으로 요축을 보조할 수 있다:
  그 설계 선택지를 코드에서 지우면 다시 세우는 비용이 크다.

공통 계약: `forces(throttle, V, rho) -> (F_b, M_b)`, throttle은 SurfaceCommand
규약의 (2,) [좌, 우] 0~1 (범위 밖 클립). V는 공기속도[m/s], rho는 밀도[kg/m³]로
`plant/aircraft.py`가 공력에 넘기는 것과 **같은 값**을 넘긴다 (두 모델이 다른 대기를
보는 일이 없다). 상수 추력 두 형상은 받고 쓰지 않으며, 그 무시가 의도임을
tests/test_plant_models.py가 고정한다.

추력은 동체 +x축이고 모멘트는 r×F뿐이다 — 반토크·자이로·P-factor·후류는 **없다**
(프로펠러 2차 효과 [TBD]). 실기체 추력 맵 데이터도 아직 [TBD]다 (01 §2.6).

스키마에서 뺀 인자 (둘 다 의도된 제외, tests/test_plant_models.py가 목록을 핀한다):

- **TwinEngine.x_offset** — 추력이 순수 동체 x축(F_y = F_z = 0)이라 r×F가
  **(0, z·T, y·T)**가 되고, x_offset은 F_y·F_z와만 곱해지므로 어느 성분에도 안 남는다
  (엔진 간 상쇄가 아니다 — 비대칭 추력에서도 마찬가지다). 폼에 열면 "고쳐도 아무 일도
  일어나지 않는 칸"이 된다. 생성자 인자로는 남겨 둔다 — 추력선 경사(cant)가 도입되어
  F_z ≠ 0이 되면 그때 살아난다.
- **thrust_map** — 파이썬 콜러블이라 JSON 스키마 경계를 넘지 못한다
  (params/param.py의 타입 판정은 type(default) 디스패치다). 주입 경로는 그대로다.
"""

import numpy as np

from claw.env.constants import ISA_RHO0 as RHO_SL
from claw.params.param import ParamDef


def _clip01(x) -> float:
    """SurfaceCommand 스로틀 규약 — 0~1, 범위 밖은 클립."""
    return min(max(float(x), 0.0), 1.0)


class TwinEngine:
    """좌우 2기 — 차동추력으로 요축을 보조할 수 있는 형상 (데모 정본은 아니다).

    엔진 위치는 CG 기준 동체축 r_L = (x_offset, −y_offset, z_offset),
    r_R = (x_offset, +y_offset, z_offset). **좌측 추력 우세 시 +N(기수 우측)** —
    믹서의 차동추력 부호 기준이 이것이다 (fcl/graphs.py mixer_nodes).
    """

    NAME = "TwinEngine"
    # 좌우 추력차로 요 모멘트를 낼 수 있다 — 믹서 k_diff_thr의 전제
    # (sim/simulator.py가 조립 시점에 이 플래그로 기체·법칙 짝을 검사한다)
    differential_thrust = True
    PARAM_DEFS = (
        ParamDef("max_thrust", 4000.0, "N", "엔진 1기 최대 추력 (스로틀 1)", lo=0.0),
        ParamDef("y_offset", 0.5, "m", "엔진 중심선 이격 (반폭) — 차동추력 요 모멘트 팔", lo=0.0),
        ParamDef("z_offset", 0.0, "m", "추력선 CG 대비 하방 오프셋 (+면 기수 상승 모멘트)"),
    )

    def __init__(
        self, max_thrust=4000.0, y_offset=0.5, x_offset=0.0, z_offset=0.0, thrust_map=None
    ):
        if y_offset < 0:
            raise ValueError(f"y_offset은 음수 불가: {y_offset}")
        self.thrust_map = thrust_map if thrust_map is not None else (lambda th: max_thrust * th)
        self.r_left = np.array([x_offset, -y_offset, z_offset])
        self.r_right = np.array([x_offset, y_offset, z_offset])

    def forces(self, throttle, V=0.0, rho=RHO_SL):
        """throttle (2,) [좌, 우] 0~1 (SurfaceCommand 규약, 범위 밖 클립) → (F_b, M_b).

        V·rho는 상수 추력 모델이라 쓰지 않는다 — 계약 폭을 맞출 뿐이다.
        """
        t_left = float(self.thrust_map(_clip01(throttle[0])))
        t_right = float(self.thrust_map(_clip01(throttle[1])))
        f_left = np.array([t_left, 0.0, 0.0])
        f_right = np.array([t_right, 0.0, 0.0])
        force_b = f_left + f_right
        moment_b = np.cross(self.r_left, f_left) + np.cross(self.r_right, f_right)
        return force_b, moment_b


class SingleEngine:
    """단발 중심선 추진 — 정본 형상(models/shahed-136: 2엽 푸셔 1기).

    **집합 스로틀만 쓴다.** SurfaceCommand의 throttle은 (2,)로 고정된 계약이라
    (common/contracts.py — 믹서·트림·생성 C·3D가 전부 이 폭에 묶여 있다) 여기서도
    (2,)를 받되, 중심선 1기에는 좌우 구분이 없으므로 **평균**을 쓴다. 좌우가 갈린
    명령의 차분은 물리적으로 낼 데가 없어 버려진다.

    그 버림이 **조용하면 안 된다**: 차동추력이 켜진 채(k_diff_thr≠0) 이 엔진을 물리면
    법칙은 요축을 돕는다고 믿는데 기체는 아무 요 모멘트도 내지 않고, 스로틀이 상·하한에
    붙은 구간에서는 좌우 클립이 비대칭이라 **평균이 밀려 러더가 추력을 깎는** 진짜
    버그가 된다. 그래서 단발 프로파일은 k_diff_thr=0과 한 벌이고, 그 짝을
    tests/test_plant_models.py가 핀한다.

    y_offset이 없는 것은 기본값이 0이라서가 아니라 **중심선이 정의**이기 때문이다.
    중심선을 벗어난 단발(예: 비대칭 장착)은 다른 물건이라 다른 클래스가 맡는다.
    """

    NAME = "SingleEngine"
    # 중심선 1기 — 좌우 추력차 자체가 없다. 이 플래그가 False라서
    # sim/simulator.py가 k_diff_thr≠0인 법칙과의 조합을 조립 시점에 거부한다
    differential_thrust = False
    PARAM_DEFS = (
        ParamDef("max_thrust", 8000.0, "N", "최대 추력 (스로틀 1)", lo=0.0),
        ParamDef("z_offset", 0.0, "m", "추력선 CG 대비 하방 오프셋 (+면 기수 상승 모멘트)"),
    )

    def __init__(self, max_thrust=8000.0, z_offset=0.0, thrust_map=None):
        self.thrust_map = thrust_map if thrust_map is not None else (lambda th: max_thrust * th)
        self.r = np.array([0.0, 0.0, z_offset])

    def forces(self, throttle, V=0.0, rho=RHO_SL):
        """throttle (2,) [좌, 우] 0~1 → (F_b, M_b). 좌우 평균이 곧 집합 스로틀이다.

        V·rho는 상수 추력 모델이라 쓰지 않는다 — 계약 폭을 맞출 뿐이다.
        """
        th = 0.5 * (_clip01(throttle[0]) + _clip01(throttle[1]))
        force_b = np.array([float(self.thrust_map(th)), 0.0, 0.0])
        return force_b, np.cross(self.r, force_b)


class PropEngine:
    """단발 중심선 **프로펠러** — 데모 기체의 정본 형상.

    추력이 속도와 밀도를 탄다. 프로펠러는 축동력을 추력으로 바꾸는 물건이라
    `T = η·P/V`이고, V→0에서 발산하므로 정지추력이 상한을 준다:

        T = δ · σ · min(T_static, η·P_max / V),   σ = ρ/ρ_SL

    **이게 상수 추력과 갈리는 지점이 이 도구의 요점이다.** T = T_max·δ는 고속에서
    추력이 남아돈다고 말하지만 프로펠러는 정확히 거기서 힘이 빠진다 — 엔벨로프
    상단을 정하는 것이 항력이 아니라 **추력**이 되고, 그래야 엔벨로프 탭의
    "추력 대리 경계"(스로틀 포화 전선)가 진짜 추력 한계가 된다.

    교차속도 V_c = η·P_max/T_static 아래에서는 정지추력이 상한이다 — 그 위가
    `1/V` 구간이다. 데모 기본값(500 kW·η 0.8·6 kN)에서 V_c = 66.7 m/s다.

    **정지추력 6 kN은 임의 값이 아니다** — 시각화 모델의 프로펠러 반경 0.45 m를
    원판이론에 넣은 값이다: T³ = 2ρA·P_ideal², A = πR² = 0.636 m²,
    P_ideal = η·P_max = 400 kW → T = 6.3 kN. 라운드해서 6.0을 쓴다(약간 보수적).

    **[기본값] 근사 셋** (실기체 추력 맵 [TBD] 대비):
    - η는 상수다 — 실제로는 전진비(J = V/nD)의 함수이고 고속에서 급락한다.
      그래서 이 모델은 **고속을 낙관한다**. 또 η가 두 역할을 겸한다 — 1/V 가지에서는
      추진효율(TV/P)이고 정지추력 유도에서는 figure of merit다. V→0에서 추진효율은
      정의상 0이라 같은 기호일 수 없는데, 값이 비슷해 하나로 쓴다 [기본값].
    - 축동력은 밀도비에 선형(σ) — 자연흡기 근사. Gagg-Ferrar 형(σ − (1−σ)/7.55)이
      더 정확하지만 두 자릿수 차이가 아니라 라운드 값을 택했다.
    - 정지추력도 σ로 준다. 이건 **근사가 아니다**: 원판이론 T ∝ ρ^(1/3)P^(2/3)에
      위의 P = σP₀를 넣으면 σ^(1/3)·σ^(2/3) = σ¹로 정확히 선형이다.
    - 스로틀은 δ에 선형 — 정지추력 쪽은 엄밀히 δ^(2/3)이다.

    반토크·자이로·P-factor·후류는 여전히 **없다** (프로펠러 2차 효과 [TBD]).
    중심선 1기라 요 모멘트를 못 낸다 — SingleEngine과 같은 이유로
    differential_thrust = False다.
    """

    NAME = "PropEngine"
    differential_thrust = False
    PARAM_DEFS = (
        ParamDef("power_max", 500_000.0, "W", "최대 축동력 (해면·스로틀 1)", lo=0.0),
        ParamDef("eta", 0.8, "-", "프로펠러 효율 (전진비 무관 상수 [기본값])", lo=1e-9, hi=1.0),
        ParamDef("static_thrust", 6000.0, "N", "정지추력 상한 (V→0 발산 방지)", lo=0.0),
        ParamDef("z_offset", 0.0, "m", "추력선 CG 대비 하방 오프셋 (+면 기수 상승 모멘트)"),
    )

    def __init__(self, power_max=500_000.0, eta=0.8, static_thrust=6000.0, z_offset=0.0):
        if not 0.0 < eta <= 1.0:
            raise ValueError(f"eta는 (0, 1] 범위: {eta}")
        self.power_max = float(power_max)
        self.eta = float(eta)
        self.static_thrust = float(static_thrust)
        self.r = np.array([0.0, 0.0, z_offset])

    @property
    def crossover_speed(self) -> float:
        """정지추력 상한과 1/V 구간이 만나는 속도 [m/s] — 설계 검토용 조회."""
        if self.static_thrust <= 0.0:
            return 0.0
        return self.eta * self.power_max / self.static_thrust

    def available_thrust(self, V, rho=RHO_SL) -> float:
        """스로틀 1에서 낼 수 있는 추력 [N] — 엔벨로프 추력 한계의 정본.

        해석·표시가 "여기서 최대 얼마 나오나"를 물을 때 forces()를 두 번 부르는
        대신 이걸 부른다 (같은 식을 두 곳에 적지 않는다).
        """
        sigma = float(rho) / RHO_SL
        v = max(float(V), 0.0)
        if v <= 0.0:
            return self.static_thrust * sigma
        return sigma * min(self.static_thrust, self.eta * self.power_max / v)

    def forces(self, throttle, V=0.0, rho=RHO_SL):
        """throttle (2,) [좌, 우] 0~1, 공기속도 V[m/s], 밀도 rho → (F_b, M_b)."""
        th = 0.5 * (_clip01(throttle[0]) + _clip01(throttle[1]))
        force_b = np.array([th * self.available_thrust(V, rho), 0.0, 0.0])
        return force_b, np.cross(self.r, force_b)
