"""Banshee Jet 80+ 기체 문서 — 서버가 처음 뜰 때 저장 기체로 심는 패키지 문서(load_banshee, 02 §5.6).

외형 치수·추력만 공개 값이고 질량·관성·공력은 추정이다(문서 description이 그렇게 말한다). 게인·δe_trim·확정 게인 표는
쇼케이스와 같은 생성 모듈(claw.profile.showcase)이 툴로 도출했다 — 이 테스트는 그 결과가 낡지 않았고, 문서의 미션
템플릿이 말하는 착륙 수치(플레어 속도·강하율·rollout_m)를 실제로 나는지 직선 미션으로 잰다.
"""

from pathlib import Path

import pytest

from claw.common.contracts import TrimCase
from claw.fcl.assemble import assemble_law
from claw.guidance import Guidance, ModeSpec
from claw.nav import NavErrorModel
from claw.pipeline.metrics import climb_rate
from claw.profile import BANSHEE_ID, build_profile, load_banshee
from claw.sim import Simulator
from claw.trim import trim_ground

DT = 0.01
CRUISE_S = 20.0
G0 = 9.80665
MODELS = Path(__file__).resolve().parents[3] / "models"


@pytest.fixture(scope="module")
def doc():
    return load_banshee()


@pytest.fixture(scope="module")
def built(doc):
    return build_profile(doc, validated=True)


def test_편집_가능한_저장_기체이고_표시_모델이_리포에_있다(doc):
    assert doc["id"] == BANSHEE_ID and doc["is_example"] is False
    assert doc["display"] == {"kind": "model", "model": "banshee.glb"}
    assert (MODELS / "banshee" / "banshee.glb").is_file()
    assert "추정" in doc["description"]  # 공개 값과 추정 값의 경계를 문서가 스스로 말한다


def test_load_banshee는_독립_사본을_준다():
    a = load_banshee()
    a["mass"]["m_empty"] = -1.0  # 안쪽 칸 — 얕은 사본이면 캐시가 오염된다
    assert load_banshee()["mass"]["m_empty"] > 0


def test_도출한_표와_게인이_낡지_않았다(doc, built):
    assert doc["law"]["design"] is not None
    assert doc["law"]["alloc"]["de_trim"]["source"] == "derived"
    assert built.de_trim_stale is False
    assert doc["law"]["gain_tables"] is not None and built.gain_tables_stale is False


def test_마지막_웨이포인트_도달_반경은_헤딩_루프_이월_거리다(doc):
    """test_profile_showcase의 같은 이름 테스트가 근거 — R_acc = V²/(g·kp_hdg)."""
    ap = doc["law"]["design"]["autopilot"]
    assert ap["ki_hdg"] == 0.0
    assert not any(k.startswith("heading.") for k in (doc["law"]["schedule"] or {}).get("scheduled", []))
    sim = doc["mission_template"]["sim"]
    lead = sim["cruise"]["speed"] ** 2 / (G0 * ap["kp_hdg"])
    assert sim["accept_radius"] == pytest.approx(lead, rel=0.1)


@pytest.fixture(scope="module")
def landed(built):
    m = built.doc["mission_template"]["sim"]
    c, cr, ap, fl = m["climb"], m["cruise"], m["approach"], m["flare"]
    modes = [
        ModeSpec(name="launch", speed=c["speed"], pitch=c["pitch"], heading=0.0, exit_when=("off_rail",), next="climb"),
        ModeSpec(name="climb", speed=c["speed"], pitch=c["pitch"], heading=0.0,
                 exit_when=("alt_ge", c["exit_alt"]), next="cruise"),
        ModeSpec(name="cruise", speed=cr["speed"], alt=cr["alt"], heading=0.0,
                 exit_when=("time_ge", CRUISE_S), next="approach"),
        ModeSpec(name="approach", speed=ap["speed"], hdot=ap["hdot"], heading=0.0,
                 exit_when=("alt_le", ap["exit_alt"]), next="flare"),
        ModeSpec(name="flare", speed=fl["speed"], hdot=fl["hdot"], heading=0.0,
                 exit_when=("on_ground",), next="rollout"),
        ModeSpec(name="rollout", speed=0.0, pitch=0.0, heading=0.0, exit_when=("speed_le", 0.5), next="stopped"),
        ModeSpec(name="stopped", speed=0.0, pitch=0.0, exit_when=("time_ge", 1e9)),
    ]
    ac = built.aircraft(ground=built.skid_gear())
    tr = trim_ground(ac, TrimCase("pad", mach=0.0, alt=0.0, fuel=m["fuel"], condition="ground"))
    assert tr.converged
    sim = Simulator(
        aircraft=ac, fcl=assemble_law(built), guidance=Guidance(modes),
        nav_model=NavErrorModel.rtk_fixed(seed=11), stall_table=built.stall_table(),
        db_ranges=built.db_ranges(), dt_plant=DT, control_hz=100.0, ground_elev=0.0,
        launch=built.launch_rail(), actuator_params=built.actuator_params(), fuel_flow=m["fuel_flow"],
    )
    return sim.run(tr, t_end=400.0, fingerprint="landing-banshee")


def test_발사에서_정지까지_순서대로_완주한다(landed):
    s = landed.signals
    seq = [x for i, x in enumerate(s["mode"]) if i == 0 or x != s["mode"][i - 1]]
    assert seq == ["launch", "climb", "cruise", "approach", "flare", "rollout", "stopped"]
    assert landed.meta["aborted"] is None


def test_플레어가_문서의_속도와_강하율로_접지한다(landed, doc):
    fl = doc["mission_template"]["sim"]["flare"]
    s = landed.signals
    k = int(round(landed.meta["phases"]["touchdown_t"] / DT))
    assert climb_rate(s, k) == pytest.approx(fl["hdot"], abs=0.15)
    assert s["V"][k] == pytest.approx(fl["speed"], rel=0.05)


def test_미끄럼_거리가_문서의_rollout_m이다(landed, doc):
    s, ph = landed.signals, landed.meta["phases"]
    k_td, k_st = int(round(ph["touchdown_t"] / DT)), int(round(ph["stop_t"] / DT))
    assert s["pn"][k_st] - s["pn"][k_td] == pytest.approx(doc["mission_template"]["sim"]["rollout_m"], rel=0.12)
