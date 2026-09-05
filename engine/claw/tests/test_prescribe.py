"""pipeline.prescribe 검증 — 정량 처방(얼마나)의 계약.

전부 합성 스윕 행으로 순수 계산을 핀한다 — 6DOF는 안 돈다(저장된 스윕을 다시
세우는 것이 이 모듈의 정의다). 핵심 규약: ① mixed(비단조)는 외삽 금지 —
solvable=False+사유 ② 스팬 밖 교차는 참고 추정치만 내고 solvable=False 유지
③ 케이스 간 요구 방향이 상충하면 국소 문제로 거절 ④ 조합 해는 하드 문턱을
선형 예측으로 전부 만족해야 하고 변화 크기를 최소화한다.
"""

import math

import pytest

from claw.pipeline.criteria import GainEvalCriteria
from claw.pipeline.prescribe import (
    proposal_shape,
    slope_matrix,
    solve_joint,
    solve_single_knob,
)
from claw.pipeline.influence import Shape


def _rows(case, knob, base_metrics, by_span):
    """합성 스윕 행 — base + 단독 스팬 런들."""
    rows = [{"case": case, "label": "base", "role": "base", "overrides": {},
             "aborted": False, "metrics": dict(base_metrics)}]
    for s, metrics in sorted(by_span.items()):
        rows.append({"case": case, "label": f"{knob}@{s:+g}", "role": "single",
                     "overrides": {knob: 1.0 + s}, "aborted": False,
                     "metrics": dict(metrics)})
    return rows


K = "table.pitch.kp"


def test_단일_손잡이_교차_보간():
    """base 12 → +20%에서 8로 단조 감소, 문턱 10(이하 합격) — 교차는 +10%."""
    rows = _rows("A", K, {"alt_rms": 12.0},
                 {-0.2: {"alt_rms": 16.0}, -0.1: {"alt_rms": 14.0},
                  0.1: {"alt_rms": 10.0}, 0.2: {"alt_rms": 8.0}})
    out = solve_single_knob(rows, K, "alt_rms", 10.0, above_is_bad=True)
    assert out["solvable"] is True
    assert abs(out["required_span"] - 0.1) < 1e-9
    assert out["direction"] == "increase"


def test_이미_통과면_필요_변화_0():
    rows = _rows("A", K, {"alt_rms": 9.0}, {0.1: {"alt_rms": 8.0}})
    out = solve_single_knob(rows, K, "alt_rms", 10.0, above_is_bad=True)
    assert out["solvable"] is True and out["required_span"] == 0.0
    assert "이미" in out["reason"]


def test_비단조는_외삽_금지():
    """스팬 안에 극점 — 이 손잡이를 한쪽으로 밀면 안 된다는 사실이 답이다."""
    rows = _rows("A", K, {"alt_rms": 12.0},
                 {-0.1: {"alt_rms": 11.0}, 0.1: {"alt_rms": 11.0},
                  0.2: {"alt_rms": 13.0}})
    out = solve_single_knob(rows, K, "alt_rms", 10.0, above_is_bad=True)
    assert out["solvable"] is False
    assert "비단조" in out["reason"]


def test_스팬_밖_교차는_추정치만():
    rows = _rows("A", K, {"alt_rms": 12.0},
                 {0.1: {"alt_rms": 11.8}, 0.2: {"alt_rms": 11.6}})
    out = solve_single_knob(rows, K, "alt_rms", 10.0, above_is_bad=True)
    assert out["solvable"] is False
    assert "교차 없음" in out["reason"]
    # 기울기 −2/스팬1 → 필요 +1.0 (참고용)
    assert abs(out["extrapolated_span"] - 1.0) < 1e-6


def test_케이스_간_방향_상충은_국소_거절():
    rows = (_rows("A", K, {"alt_rms": 12.0}, {0.1: {"alt_rms": 9.0}})
            + _rows("B", K, {"alt_rms": 12.0}, {-0.1: {"alt_rms": 9.0},
                                                0.1: {"alt_rms": 15.0}}))
    out = solve_single_knob(rows, K, "alt_rms", 10.0, above_is_bad=True)
    assert out["solvable"] is False
    assert "상충" in out["reason"]


def test_전_케이스_요구의_최댓값이_필요_변화다():
    rows = (_rows("A", K, {"alt_rms": 11.0}, {0.2: {"alt_rms": 7.0}})   # +5 %면 통과
            + _rows("B", K, {"alt_rms": 14.0}, {0.2: {"alt_rms": 6.0}}))  # +10 % 필요
    out = solve_single_knob(rows, K, "alt_rms", 10.0, above_is_bad=True)
    assert out["solvable"] is True
    assert abs(out["required_span"] - 0.1) < 1e-9
    assert out["binding_case"] == "B"


def test_기울기_행렬은_mixed를_아예_빼고_기록한다():
    K2 = "table.pitch.ki"
    rows = (_rows("A", K, {"alt_rms": 12.0, "spd_rms": 1.0},
                  {-0.1: {"alt_rms": 13.0, "spd_rms": 1.0},
                   0.1: {"alt_rms": 11.0, "spd_rms": 1.0}})
            + [r for r in _rows("A", K2, {"alt_rms": 12.0, "spd_rms": 1.0},
                                {-0.1: {"alt_rms": 11.5, "spd_rms": 1.0},
                                 0.1: {"alt_rms": 11.5, "spd_rms": 1.0}})
               if r["label"] != "base"])
    S, excluded = slope_matrix(rows, [K, K2], ["alt_rms", "spd_rms"])
    assert abs(S["A"]["alt_rms"][K] - (-10.0)) < 1e-9  # Δ-10/스팬1
    assert (K2, "alt_rms") in [(e["knob"], e["metric"]) for e in excluded]
    assert "비단조" in excluded[0]["reason"]


def test_조합_해는_문턱을_만족하는_최소_변화다():
    """alt_rms는 kp가, spd_rms는 ki가 고친다 — 해는 두 축을 조금씩."""
    K2 = "table.spd.kp"
    rows = (_rows("A", K, {"alt_rms": 12.0, "spd_rms": 2.4,
                           "worst_stall_margin": 0.2, "surf_sat_frac": 0.0},
                  {-0.1: {"alt_rms": 13.0, "spd_rms": 2.4,
                          "worst_stall_margin": 0.2, "surf_sat_frac": 0.0},
                   0.1: {"alt_rms": 11.0, "spd_rms": 2.4,
                         "worst_stall_margin": 0.2, "surf_sat_frac": 0.0}})
            + [r for r in _rows("A", K2, {"alt_rms": 12.0, "spd_rms": 2.4,
                                          "worst_stall_margin": 0.2,
                                          "surf_sat_frac": 0.0},
                                {-0.1: {"alt_rms": 12.0, "spd_rms": 2.6,
                                        "worst_stall_margin": 0.2,
                                        "surf_sat_frac": 0.0},
                                 0.1: {"alt_rms": 12.0, "spd_rms": 2.2,
                                       "worst_stall_margin": 0.2,
                                       "surf_sat_frac": 0.0}})
               if r["label"] != "base"])
    out = solve_joint(rows, [K, K2], GainEvalCriteria())
    assert out["solvable"] is True, out
    x = out["spans"]
    # alt: 12−10x_kp ≤ 10 → x_kp ≥ 0.2 (경계) · spd: 2.4−2x_ki ≤ 2 → x_ki ≥ 0.2
    assert abs(x[K] - 0.2) < 1e-3
    assert abs(x[K2] - 0.2) < 1e-3
    assert out["predicted"]["A"]["alt_rms"] <= 10.0 + 1e-6
    assert not out["violated"]


def test_조합_불가능이면_위반_목록과_함께_거절():
    rows = _rows("A", K, {"alt_rms": 30.0, "spd_rms": 1.0,
                          "worst_stall_margin": 0.2, "surf_sat_frac": 0.0},
                 {0.2: {"alt_rms": 29.0, "spd_rms": 1.0,
                        "worst_stall_margin": 0.2, "surf_sat_frac": 0.0}})
    out = solve_joint(rows, [K], GainEvalCriteria())
    assert out["solvable"] is False
    assert any(v["metric"] == "alt_rms" for v in out["violated"])


def test_proposal_shape는_클립을_삼키지_않는다():
    shape = Shape()
    shape2, notes = proposal_shape(shape, {"table.pitch.kp": 0.1})
    assert shape2.fingerprint() != shape.fingerprint()
    assert notes == []
    with pytest.raises(ValueError, match="알 수 없는"):
        proposal_shape(shape, {"없는.자리": 0.1})
