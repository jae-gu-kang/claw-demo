"""비행체 조립의 **단일 창구** — 라우트가 엔진 조립 함수를 직접 부르지 않는다.

## 왜 있나

종전에는 라우트 14곳이 각자 `make_demo_aircraft()`를 인자 없이 불렀다. 그래서
질량·제원을 바꿀 자리가 **어디에도 없었고**, 사용자가 엔벨로프 탭에서 값을 고쳐도
시뮬 탭은 다른 기체를 보고 있었다(연료 기본값이 탭마다 달라 엔벨로프 1,000 kg vs
시뮬 1,100 kg). 창구가 하나면 제원을 요청에서 받는 것이 **여기 한 줄**이 된다.

## 무엇을 하지 않나

- **기본값을 지어내지 않는다.** spec이 없으면 엔진 기본값(`MassSpec()`)이고, 그
  값의 정본은 엔진이다 — 서버가 재기술하면 두 수가 갈린다(02 §5.5).
- **CG는 아직 설계변수가 아니다.** `cg_empty = cg_full = 0` + 모멘트 기준점 이전
  [TBD]라 연료가 타도 CG가 안 움직인다. 즉 이 창구로 연료를 흔들면 **질량·관성
  효과만** 보이고, 연료-안정성 비교의 지배적 원인(CG 이동)은 빠진다. 그 사실을
  여기 적어 두는 이유는, 창구가 열리는 순간 "이제 연료를 바꿀 수 있으니 안정성
  비교도 된다"고 읽히기 때문이다 — 아직 아니다.
"""

from claw.plant import MassSpec, make_demo_aircraft, make_demo_skid_gear


def build_aircraft(*, mass: MassSpec | None = None, ground: bool = False,
                   dispersion=None):
    """라우트가 쓰는 유일한 조립 경로.

    `ground=True`면 스키드를 단다 — 지면이 없으면 기체가 h<0을 그대로 통과하고
    접지·정지 판정이 불가하다(조용한 미장착 금지, routes/sim.py의 그 규약).
    """
    return make_demo_aircraft(
        ground=make_demo_skid_gear() if ground else None,
        dispersion=dispersion,
        mass=mass,
    )
