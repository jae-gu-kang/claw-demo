"""속도 명령필터 추월 동기화 — 레일 발진에서 기준이 V = 0에 붙잡혀 이탈 뒤 스로틀을 끄던 결함 (fcl/graphs.py 속도 절).

발진 행은 속도 축이 켜진 채 레일 위 정지에서 출발하고, 속도는 스로틀이 아니라 사출기가 올린다. 고치기 전에는 필터가 0에서
τ_spd로 기어오르는 동안 「명령 < 속도」라 스로틀 PI가 0으로 떨어졌다 — 쇼케이스 기체 기본형(τ_spd 2 s)에서 이탈 뒤 약
2.7 s 스로틀 0, 고도 18.3 → 13.6 m 처짐. 이제 기체가 기준을 목표 쪽으로 앞지르면 기준을 측정으로 다시 시드한다.
"""

import pytest

from claw.blocks.filters import CommandFilter
from claw.codegen import GraphRunner
from claw.fcl.assemble import assemble_law
from claw.fcl.autopilot import Autopilot
from claw.fcl.graphs import autopilot_graph
from claw.profile import example_profile

DT = 0.01


@pytest.mark.parametrize("standard", [False, True], ids=["분석", "표준"])
def test_추월_동기화는_속도_명령필터에만_달린다(standard):
    """고도·승강률·헤딩·스케줄 필터에 달면 착륙·순항 거동이 함께 바뀐다 — 발진과 무관한 자리는 그대로 둔다.

    분석 그래프(시뮬)와 표준 템플릿(탑재 C)이 같은 자리에 같은 것을 달아야 시뮬·C가 한 법칙이다.

    **고도·승강률 필터에도 추월은 실제로 일어난다 — 그래도 달지 않는다(G3 측정).** 피치 상승 → 고도 모드 진입 때 기체는
    상승률(4.4~13.4 m/s)을 안고 들어오는데 기준은 h에서 τ_alt로 출발하므로, 목표에 닿기 전 기체가 기준을 최대 2.7~3.8 m·
    4.4~8.3 s 앞선다(예제·쇼케이스 기본형 40·EO/IR형 만재·구 기체). 순항 → 접근의 승강률 필터도 1.2~2.1 m/s·0.3~2.6 s.
    그러나 여기서는 뒤처진 기준이 **포획 제동**이다 — 기체가 목표 쪽 운동량을 가진 채 들어오므로, 뒤처진 기준이 만드는
    반대 방향 오차가 상승·강하를 미리 꺾는다. 동기화를 달아 재 보면 고도 포획 초과가 4.5 → 7.4 m(예제), 2.2 → 5.4 m(기본형),
    3.7 → 5.3 m(EO/IR형), 4.1 → 6.4 m(구 기체)로 커지고, 승강률 진입 초과가 0.24 → 1.97 m/s(예제), 0.36 → 2.43 m/s(구 기체)로
    커져 접지점이 51~82 m 당겨진다. 속도 축과 다른 점은 운동량이다: 발진에서는 사출기가 준 속도가 항력으로 **목표 반대쪽**으로
    빠지는 중이라 뒤처진 기준이 스로틀을 끄는 것이 곧 처짐이었다.
    """
    fcl = assemble_law(example_profile(), standard=standard).init(DT)
    filters = {n.id: n.resync for n in fcl.runner.graph.nodes if n.kind == "block" and n.block is CommandFilter}
    assert filters.pop("ap_fv") is True
    assert filters and not any(filters.values()), filters


def _rail_launch(runner, n_rail=67, v_exit=42.0, n_after=150, decel=1.2):
    """레일 발진 모양의 입력 — 0.67 s 등가속으로 42 m/s, 이탈 뒤 항력으로 감속. 목표 45 m/s, θ 직접 지령.

    웜스타트 스로틀은 지상 평형 트림의 0이다(simulator가 넣는 값). → (V, 기준, 스로틀) 스텝 목록
    """
    runner.reset({"spd_pid": 0.0, "alt_pid": 0.26})
    rows = []
    for k in range(n_rail + n_after):
        v = v_exit * k / n_rail if k <= n_rail else v_exit - decel * DT * (k - n_rail)
        out = runner.step(psi=0.0, h=3.0, hdot=0.0, V=v, cmd_heading=0.0, cmd_alt=0.0, cmd_speed=45.0,
                          cmd_pitch=0.3, cmd_hdot=0.0, heading_on=1.0, alt_on=0.0, speed_on=1.0,
                          pitch_on=1.0, hdot_on=0.0)
        rows.append((v, runner.last_env["fv"], out["throttle"]))
    return rows


def test_레일_위에서_기준이_기체를_따라가_이탈_직후_스로틀이_산다():
    """레지스트리 기본 τ_spd(2 s)로 — S1이 0.5 s로 우회하던 그 값에서 고쳐져야 한다."""
    cfg = {d.name: d.default for d in Autopilot.PARAM_DEFS}
    assert cfg["tau_spd"] == 2.0
    rows = _rail_launch(GraphRunner(autopilot_graph(**cfg), DT))
    rail = rows[:68]
    assert all(ref >= v for v, ref, _thr in rail), "레일 위에서 속도 기준이 기체보다 뒤처졌다"
    v_exit, ref_exit, _ = rows[67]
    assert ref_exit >= v_exit
    # 이탈 뒤 0.3 s 안에 스로틀이 들어온다 — 고치기 전에는 기준이 16 m/s 근처라 약 3 s 동안 0이었다
    after = [thr for _v, _ref, thr in rows[68:98]]
    assert max(after) > 0.02, after[-5:]
    # 이탈 뒤에는 기준이 목표로 램프하고 기체는 감속하니 오차가 벌어지며 스로틀이 계속 오른다
    assert rows[-1][2] > max(after)
