"""pipeline.openloop 검증 — 2단: 게인 Δ → 케이스별 개루프 마진 변화.

핵심 계약: ① LinearModel은 게인과 무관하므로 케이스당 선형화 1회로 기준/섭동
마진을 다 낸다 ② 스케줄이 덮는 상수는 Δ=0이 아니라 "개루프가 볼 수 없음"으로
분리 보고한다(influence 머리말의 "1단은 잡는데 2단이 0인 자리") ③ 루프에 대응
없는 파라미터는 no_loop — 조용한 0으로 위장하지 않는다.
"""

import numpy as np
import pytest

from claw.common.contracts import TrimCase
from claw.pipeline.influence import Shape
from claw.pipeline.openloop import GROUP_LOOPS, openloop_delta
from claw.plant import make_demo_aircraft
from claw.trim import trim_level


@pytest.fixture(scope="module")
def design_trim():
    ac = make_demo_aircraft()
    tr = trim_level(ac, TrimCase("design", mach=0.6, alt=1000.0, fuel=200.0))
    assert tr.converged
    return ac, tr


def test_스케줄_배율은_마진_델타가_나오고_상수는_분리_보고된다(design_trim):
    ac, tr = design_trim
    out = openloop_delta(
        ac, [tr], Shape(),
        ["table.pitch.k_rate", "fcl/ScasAxis.pitch.kp", "fcl/ScasAxis.yaw.kp",
         "fcl/Autopilot.kp_spd", "fcl/Mixer.k_diff_thr"],
    )
    assert out["cases"] == ["design"]
    p = out["params"]

    # 스케줄이 덮는 상수 — 개루프가 볼 수 없다 (Δ=0으로 위장 금지)
    assert p["fcl/ScasAxis.pitch.kp"]["status"] == "overridden"
    # 선언된 루프가 없는 자리 — 요축 자세 게인·믹서
    assert p["fcl/ScasAxis.yaw.kp"]["status"] == "no_loop"
    assert p["fcl/Mixer.k_diff_thr"]["status"] == "no_loop"

    # 스케줄 곡선 배율 — 케이스 실효 게인(테이블@케이스)으로 레이트 루프 마진 Δ
    rate = p["table.pitch.k_rate"]
    assert rate["status"] == "ok"
    entry = rate["loops"]["pitch_rate"]["design"]
    assert np.isfinite(entry["base"]["pm_deg"])
    assert entry["delta"]["pm_deg"] == pytest.approx(
        entry["perturbed"]["pm_deg"] - entry["base"]["pm_deg"])
    assert entry["delta"]["pm_deg"] != 0.0

    # AP 속도 루프 (u←thr) — 스케줄 밖 상수라 직접 Δ
    spd = p["fcl/Autopilot.kp_spd"]
    assert spd["status"] == "ok"
    assert "spd_u" in spd["loops"]


def test_스케줄_끄면_설계점_상수가_직접_루프에_잡힌다(design_trim):
    ac, tr = design_trim
    out = openloop_delta(
        ac, [tr], Shape(with_schedule=False), ["fcl/ScasAxis.pitch.kp"])
    p = out["params"]["fcl/ScasAxis.pitch.kp"]
    assert p["status"] == "ok"
    assert "pitch_att" in p["loops"]
    assert np.isfinite(p["loops"]["pitch_att"]["design"]["base"]["pm_deg"])


def test_취소는_완료_케이스를_보존한다(design_trim):
    ac, tr = design_trim
    tr2 = trim_level(ac, TrimCase("slow", mach=0.4, alt=1000.0, fuel=200.0))
    assert tr2.converged
    calls = []

    def cancel_after_first(done, total):
        calls.append((done, total))
        return done >= 1  # 첫 케이스 후 취소

    out = openloop_delta(ac, [tr, tr2], Shape(with_schedule=False),
                         ["fcl/ScasAxis.pitch.kp"], on_progress=cancel_after_first)
    assert out["cases"] == ["design"]  # 완료분 보존
    assert out["aborted"] == "cancelled"
    assert calls[0] == (1, 2)


def test_루프_선언은_웹_기본_루프와_정합이다():
    """GROUP_LOOPS는 유도가 아니라 선언이다 — 웹 마진 탭의 DEFAULT_LOOPS
    (pitch q←de · roll p←da · yaw r←dr, sign −1)와 어긋나면 두 화면이 다른
    루프를 같은 이름으로 부르게 된다."""
    rate = {g: next(sp for sp in specs if "k_rate" in sp["gains"].values())
            for g, specs in GROUP_LOOPS.items()
            if any("k_rate" in sp["gains"].values() for sp in specs)}
    assert (rate["pitch"]["x_out"], rate["pitch"]["u_in"]) == ("q", "de")
    assert (rate["roll"]["x_out"], rate["roll"]["u_in"]) == ("p", "da")
    assert (rate["yaw"]["x_out"], rate["yaw"]["u_in"]) == ("r", "dr")
    assert all(sp["sign"] == -1.0 for sp in rate.values())


def test_미수렴_트림은_건너뛰고_경고한다(design_trim):
    ac, tr = design_trim
    bad = trim_level(ac, TrimCase("impossible", mach=0.05, alt=1000.0, fuel=200.0))
    if bad.converged:  # 데모 기체가 언젠가 수렴시키면 이 전제부터 다시 본다
        pytest.skip("미수렴 케이스 전제가 깨짐")
    out = openloop_delta(ac, [bad, tr], Shape(with_schedule=False),
                         ["fcl/ScasAxis.pitch.kp"])
    assert out["cases"] == ["design"]
    assert any("미수렴" in w for w in out["warnings"])


def test_알_수_없는_파라미터는_시끄럽게_거부한다(design_trim):
    ac, tr = design_trim
    with pytest.raises(ValueError):
        openloop_delta(ac, [tr], Shape(), ["없는.자리"])
