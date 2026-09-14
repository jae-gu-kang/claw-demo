"""제품 예제(200 kg급) 착륙 — 기체 문서 mission_template.sim이 말하는 착륙 수치를 실측으로 지킨다 (02 §5.6.1).

test_landing.py는 conftest가 예제 자리에 둔 구 합성 기체(1200 kg)를 난다. 기체 문서의 `rollout_m`과 그 사본인 웹 폴백
(web/js/lib/site.js GOHEUNG.rolloutM)은 **제품 예제**의 값이라 여기서 따로 잰다. 모드의 속도·강하율·고도·연료는 전부 문서에서
읽는다 — 사본을 두면 문서를 고쳐도 이 테스트가 자기 사본으로 통과한다. 경로는 웹 기본 미션(장주)이 아니라 직선이다 — 미끄럼은
플레어 속도·접지 강하율·스키드 마찰이 정하고 수평 경로와는 무관하다(웹 기본 미션 155 m · 여기 155.8 m).
"""

import pytest

from claw.common.contracts import TrimCase
from claw.fcl.assemble import assemble_law
from claw.guidance import Guidance, ModeSpec
from claw.nav import NavErrorModel
from claw.pipeline.metrics import climb_rate
from claw.profile import build_profile, load_shipped_example
from claw.sim import Simulator
from claw.trim import trim_ground

DT = 0.01
CRUISE_S = 20.0  # [s] 순항 체류 — test_landing과 같은 모양


@pytest.fixture(scope="module")
def shipped():
    return build_profile(load_shipped_example(), validated=True)


@pytest.fixture(scope="module")
def landed(shipped):
    m = shipped.doc["mission_template"]["sim"]
    c, cr, ap, fl = m["climb"], m["cruise"], m["approach"], m["flare"]
    modes = [
        ModeSpec(name="launch", speed=c["speed"], pitch=c["pitch"], heading=0.0,
                 exit_when=("off_rail",), next="climb"),
        ModeSpec(name="climb", speed=c["speed"], pitch=c["pitch"], heading=0.0,
                 exit_when=("alt_ge", c["exit_alt"]), next="cruise"),
        ModeSpec(name="cruise", speed=cr["speed"], alt=cr["alt"], heading=0.0,
                 exit_when=("time_ge", CRUISE_S), next="approach"),
        ModeSpec(name="approach", speed=ap["speed"], hdot=ap["hdot"], heading=0.0,
                 exit_when=("alt_le", ap["exit_alt"]), next="flare"),
        ModeSpec(name="flare", speed=fl["speed"], hdot=fl["hdot"], heading=0.0,
                 exit_when=("on_ground",), next="rollout"),
        ModeSpec(name="rollout", speed=0.0, pitch=0.0, heading=0.0,
                 exit_when=("speed_le", 0.5), next="stopped"),
        ModeSpec(name="stopped", speed=0.0, pitch=0.0, exit_when=("time_ge", 1e9)),
    ]
    ac = shipped.aircraft(ground=shipped.skid_gear())
    tr = trim_ground(ac, TrimCase("pad", mach=0.0, alt=0.0, fuel=m["fuel"], condition="ground"))
    assert tr.converged
    sim = Simulator(
        aircraft=ac, fcl=assemble_law(shipped), guidance=Guidance(modes),
        nav_model=NavErrorModel.rtk_fixed(seed=11), stall_table=shipped.stall_table(),
        db_ranges=shipped.db_ranges(), dt_plant=DT, control_hz=100.0, ground_elev=0.0,
        launch=shipped.launch_rail(), actuator_params=shipped.actuator_params(), fuel_flow=m["fuel_flow"],
    )
    return sim.run(tr, t_end=400.0, fingerprint="landing-shipped-example")


def test_발사에서_정지까지_순서대로_완주한다(landed):
    s = landed.signals
    seq = [x for i, x in enumerate(s["mode"]) if i == 0 or x != s["mode"][i - 1]]
    assert seq == ["launch", "climb", "cruise", "approach", "flare", "rollout", "stopped"]
    assert landed.meta["aborted"] is None


def test_플레어가_문서의_속도와_강하율로_접지한다(landed, shipped):
    """실측 −0.36 m/s · 32.72 m/s (문서 flare −0.33 m/s · 32.7 m/s) — 플레어가 강하를 실제로 세운다."""
    fl = shipped.doc["mission_template"]["sim"]["flare"]
    s = landed.signals
    k = int(round(landed.meta["phases"]["touchdown_t"] / DT))
    assert climb_rate(s, k) == pytest.approx(fl["hdot"], abs=0.15)
    assert s["V"][k] == pytest.approx(fl["speed"], rel=0.05)


def test_미끄럼_거리가_문서의_rollout_m이다(landed, shipped):
    """실측 155.8 m (RTK 시드 11 — 시드 12도 155.8 m, 순항 44 m/s). 허용대 rel 0.12는 site.js 폴백과 같은 회귀 밴드다."""
    s, ph = landed.signals, landed.meta["phases"]
    k_td, k_st = int(round(ph["touchdown_t"] / DT)), int(round(ph["stop_t"] / DT))
    rollout = s["pn"][k_st] - s["pn"][k_td]
    assert rollout == pytest.approx(shipped.doc["mission_template"]["sim"]["rollout_m"], rel=0.12)
    assert s["V"][-1] < 0.5
    assert s["wow"][-1], "끝까지 접지 상태"
