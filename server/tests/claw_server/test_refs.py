"""refs.retry_echo — 계산 실패 재시도 되울림(05 §11.3 · 05 §11.13 7단계). 라우트 배선은 routes/test_trim_store.py가 본다.

집계는 **최종 조건 상태**로 한다 — 풀이 쪽 라벨(retry.result)의 「limit」은 한계에 닿았다는 것일 뿐 불가인지 제약 도달인지,
근거를 재다 다시 계산 실패(trim_inside_limit)가 됐는지는 조건 상태가 말한다. 풀이 쪽 라벨은 by_result로 따로 싣는다.
"""

from types import SimpleNamespace

import pytest

from claw_server.refs import RETRY_POLICY_NAME, retry_counts, retry_echo

ZERO_RESULTS = {"converged": 0, "limit": 0, "alpha_bound": 0, "multi_limit": 0, "failed": 0}


def _tr(name, retry=None):
    tr = SimpleNamespace(case=SimpleNamespace(name=name))
    if retry is not None:
        tr.retry = retry
    return tr


def test_retry_echo_counts_by_final_state_and_keeps_batch_order():
    trs = [_tr("a"), _tr("b", {"attempts": 2, "result": "limit"}), _tr("c", {"attempts": 1, "result": "converged"}),
           _tr("d", {"attempts": 6, "result": "failed"}), _tr("e", {"attempts": 3, "result": "limit"}),
           _tr("f", {"attempts": 6, "result": "alpha_bound"}), _tr("g", {"attempts": 1, "result": "limit"})]
    # e는 한계에 닿았지만 근거를 재니 한계 안쪽에 트림이 있었다(trim_inside_limit — 계산 실패). f는 탐색 경계 — 제약 도달
    states = ["computable", "infeasible", "computable", "calc_failed", "calc_failed", "constraint_hit", "constraint_hit"]
    echo = retry_echo(trs, states)
    assert echo == {"policy": RETRY_POLICY_NAME, "retried": 6, "resolved_converged": 1, "resolved_infeasible": 1,
                    "resolved_constraint": 2, "still_calc_failed": 2,
                    "by_result": {"converged": 1, "limit": 3, "alpha_bound": 1, "multi_limit": 0, "failed": 1},
                    "names": ["b", "c", "d", "e", "f", "g"]}
    assert retry_counts(echo) == {"retried": 6, "resolved_converged": 1, "resolved_infeasible": 1,
                                  "resolved_constraint": 2, "still_calc_failed": 2}


def test_retry_echo_without_retried_points_and_off():
    trs = [_tr("a"), _tr("b")]
    assert retry_echo(trs, [None, None]) == {
        "policy": RETRY_POLICY_NAME, "retried": 0, "resolved_converged": 0, "resolved_infeasible": 0,
        "resolved_constraint": 0, "still_calc_failed": 0, "by_result": ZERO_RESULTS, "names": []}
    # 재시도를 끈 호출 — 기록이 붙어 있어도(저장소에서 온 옛 기록 등) 세지 않는다
    off = retry_echo([_tr("x", {"attempts": 1, "result": "converged"})], ["computable"], retry=None)
    assert off["policy"] == "off" and off["retried"] == 0 and off["names"] == []


def test_retry_echo_refuses_an_unassessed_retried_point():
    # 다시 푼 점의 최종 상태를 모르면 셀 칸이 없다 — 조용히 빠뜨리면 retried와 합이 어긋난다
    with pytest.raises(ValueError):
        retry_echo([_tr("b", {"attempts": 1, "result": "limit"})], [None])
    with pytest.raises(ValueError):
        retry_echo([_tr("b", {"attempts": 1, "result": "limit"})], [])
