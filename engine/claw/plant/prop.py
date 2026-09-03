"""추진 모델 — 스로틀-추력 맵 + 엔진 배치 모멘트 (01 §2.1·§2.4).

두 형상이 있고 둘 다 레지스트리 "propulsion" 카테고리에 등록된다
(plant/__init__.py — 교체 가능 컴포넌트 02 §2.3):

- **SingleEngine** — 중심선 1기. **데모 기체의 정본 형상**이다 (시각화 모델
  models/shahed-136: 2엽 푸셔 1기). 요 모멘트를 못 낸다.
- **TwinEngine** — 좌우 2기. 차동추력으로 요축을 보조할 수 있다. 정본은 아니지만
  남긴다: 쌍발 기체 스터디의 자리이고, 차동추력 요축 보조라는 설계 선택지를
  코드에서 지우면 다시 세우는 비용이 크다.

공통 계약: `forces(throttle) -> (F_b, M_b)`, throttle은 SurfaceCommand 규약의
(2,) [좌, 우] 0~1 (범위 밖 클립). 추력은 동체 +x축이고 모멘트는 r×F뿐이다 —
반토크·자이로·P-factor·후류는 **없다** (프로펠러 2차 효과 [TBD]). thrust_map
주입으로 비선형 추력 맵을 넣을 수 있으나 속도·밀도 의존은 아직 없다
(전용 추력 모델 [TBD] — 01 §2.6).

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

    def forces(self, throttle):
        """throttle (2,) [좌, 우] 0~1 (SurfaceCommand 규약, 범위 밖 클립) → (F_b, M_b)."""
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

    def forces(self, throttle):
        """throttle (2,) [좌, 우] 0~1 → (F_b, M_b). 좌우 평균이 곧 집합 스로틀이다."""
        th = 0.5 * (_clip01(throttle[0]) + _clip01(throttle[1]))
        force_b = np.array([float(self.thrust_map(th)), 0.0, 0.0])
        return force_b, np.cross(self.r, force_b)
