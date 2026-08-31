"""M15 영향성 해석 — 구조적 영향 매핑이 정본(fcl/graphs.py)을 따라가는지 못박는다.

여기 적힌 매핑값들은 **기대치가 아니라 관측치**다. 손으로 정한 답이 아니라 재조립
diff가 실제로 낸 결과이고, 그래프가 바뀌면 이 테스트가 먼저 깨져서 알려 준다.
"""

import pytest

from claw.pipeline.influence import (
    Shape,
    apply_param,
    forward_reach,
    law_signature,
    make_law,
    node_depths,
    param_impacts,
    param_universe,
    structural_payload,
    probe_value,
)


@pytest.fixture(scope="module")
def base_shape():
    return Shape()


@pytest.fixture(scope="module")
def impacts(base_shape):
    return param_impacts(base_shape)


@pytest.fixture(scope="module")
def refs(base_shape):
    return {r.id: r for r in param_universe(base_shape)}


# ── 파라미터 목록 ──────────────────────────────────────────────────────────

def test_universe_covers_every_band(refs):
    bands = {r.band for r in refs.values()}
    assert bands == {"ap", "scas", "mix", "lim", "sched", "rate", "nav", "actuator", "guidance"}


def test_universe_reads_values_from_the_assembled_law(base_shape, refs):
    """값은 조립 결과에서 읽는다 — 웹도 해석도 엔진 기본값을 재기술하지 않는다 (02 §5.5)."""
    law = make_law(base_shape)
    assert refs["fcl/Autopilot.kp_alt"].value == pytest.approx(law.autopilot.cfg["kp_alt"])
    assert refs["fcl/ScasAxis.pitch.kp"].value == pytest.approx(law.scas.cfg["pitch"]["kp"])
    assert refs["fcl/AlphaLimiter.margin"].value == pytest.approx(law.alpha_limiter.margin)
    # 메타는 ParamDef에서 — 단위가 비어 있으면 폼도 화면도 단위를 잃는다
    assert refs["fcl/Autopilot.kp_alt"].unit == "rad/m"


def test_universe_follows_the_shape_not_a_fixed_list():
    """리미터·스케줄을 끄면 그 파라미터가 목록에서 **사라진다**."""
    off = {r.id for r in param_universe(Shape(with_schedule=False, with_limiter=False))}
    assert "fcl/AlphaLimiter.margin" not in off
    assert not [i for i in off if i.startswith("table.")]
    on = {r.id for r in param_universe(Shape())}
    assert "fcl/AlphaLimiter.margin" in on
    assert [i for i in on if i.startswith("table.")]


def test_nav_seed_is_not_a_design_parameter(refs):
    """시드를 흔든 결과는 영향이 아니라 잡음 바닥이다 — 3단 대조군의 몫."""
    assert "nav/ErrorModel.seed" not in refs


# ── 탐침 ───────────────────────────────────────────────────────────────────

def test_probe_is_relative_not_absolute(refs):
    """작은 값에 절대 바닥값을 먹이면 국소 민감도가 아니게 된다 (kp_alt=0.004)."""
    v, _ = probe_value(refs["fcl/Autopilot.kp_alt"], 0.01)
    assert v == pytest.approx(0.004 * 1.01)


def test_probe_uses_zero_step_only_at_exact_zero(refs):
    v, clip = probe_value(refs["fcl/Autopilot.k_thr_turn"], 0.01, zero_step=0.02)
    assert (v, clip) == (0.02, None)


def test_probe_respects_bounds(refs):
    """하한 0인 자리는 절대 음수로 가지 않는다."""
    tau = refs["fcl/Autopilot.tau_spd"]
    assert tau.lo == 0.0
    v, _ = probe_value(tau, 0.01)
    assert v > tau.value >= 0.0


# ── 서명 정규화 (없으면 전 노드 오탐) ──────────────────────────────────────

def test_signature_is_stable_across_independent_builds(base_shape):
    """Table·ndarray를 값으로 환원하지 않으면 동일 형상의 두 조립이 **전부 다르게** 보인다.

    이게 이 모듈에서 가장 조용히 깨지는 자리다 — 오탐이 나면 모든 파라미터가
    모든 노드를 건드리는 것으로 보이고, 그림은 그럴듯하게 그려진다.
    """
    a, b = law_signature(make_law(base_shape)), law_signature(make_law(base_shape))
    assert a == b
    # 59 → 66: 종방향 축 도입으로 노드 7개가 늘었다 (ap_fvs·ap_vs_err·ap_vs_pid·
    # ap_vs_sat = 승강률 축, ap_pitch_sat = 피치 직접 지령, ap_theta_vs·ap_theta_src
    # = θ 출처 Switch 2단). 이 수가 움직이는 것이 곧 법칙 구조 변경이다.
    assert len([k for k in a if not k.startswith("__")]) == 66


# ── 구조적 영향: 관측된 매핑 ───────────────────────────────────────────────

@pytest.mark.parametrize(
    "pid, seeds",
    [
        ("fcl/Autopilot.kp_alt", {"ap_alt_pid"}),
        ("fcl/Autopilot.k_hdot", {"ap_alt_damp"}),
        ("fcl/Autopilot.tau_spd", {"ap_fv"}),
        ("fcl/Autopilot.phi_max", {"ap_hdg_pid", "ap_hdg_sat"}),
        # θ 한계는 세 종방향 갈래 전부의 포화 한계다 — 축이 늘면 씨앗도 는다
        ("fcl/Autopilot.theta_hi",
         {"ap_alt_pid", "ap_alt_sat", "ap_theta_out",
          "ap_vs_pid", "ap_vs_sat", "ap_pitch_sat"}),
        ("table.pitch.kp", {"sched_pitch_kp"}),
    ],
)
def test_param_seeds_exactly(impacts, pid, seeds):
    assert set(impacts[pid].seeds) == seeds


def test_structural_parameter_adds_nodes(impacts):
    """k_thr_turn 0→ε은 민감도가 아니라 **위상 변경**이다 — 안 쓰이는 경로는 생기지 않으므로."""
    imp = impacts["fcl/Autopilot.k_thr_turn"]
    assert imp.structural
    assert set(imp.added) == {"ap_ff_t_raw", "ap_ff_t", "ap_thr_ff", "ap_thr_out"}
    assert set(imp.changed) == {"mix_thr_l_raw", "mix_thr_r_raw"}


def test_reach_ends_at_the_right_outputs(impacts):
    """고도축 게인은 타면으로 가고 스로틀로는 가지 않는다."""
    assert set(impacts["fcl/Autopilot.kp_alt"].outputs) >= {"elevon_l", "elevon_r"}
    assert "throttle_l" not in impacts["fcl/Autopilot.kp_alt"].outputs
    assert set(impacts["fcl/Autopilot.kp_spd"].outputs) >= {"throttle_l", "throttle_r"}


# ── 게인 스케줄에 덮인 자리 (1단과 2단이 갈리는 지점) ──────────────────────

def test_scheduled_gain_is_flagged_overridden(impacts):
    """구조는 바뀌는데 실행은 안 바뀐다 — 실행기가 매 스텝 gains 포트로 덮어쓴다."""
    imp = impacts["fcl/ScasAxis.pitch.kp"]
    assert imp.seeds == ("scas_pitch_pid",)
    assert imp.overridden == ("scas_pitch_pid",)


def test_unscheduled_axis_is_not_overridden(impacts):
    """요축은 스케줄이 없어 상수가 그대로 먹는다 — 축마다 다른 것이 정상이다."""
    assert impacts["fcl/ScasAxis.yaw.kp"].overridden == ()
    assert impacts["fcl/ScasAxis.pitch.out_hi"].overridden == ()


def test_override_disappears_when_schedule_is_off():
    imp = param_impacts(Shape(with_schedule=False))["fcl/ScasAxis.pitch.kp"]
    assert imp.seeds == ("scas_pitch_pid",)
    assert imp.overridden == ()


# ── 제어주기 ───────────────────────────────────────────────────────────────

def test_control_rate_touches_every_stateful_node(impacts):
    """dt는 fcl_graph의 인자가 아니라 러너의 인자다 — 노드 인자만 보면 '아무것도
    안 건드린다'는 거짓말이 나온다. 이산 계수가 형상의 일부라는 것(02 §2.2)의 시각화."""
    imp = impacts["rate.control_hz"]
    assert len(imp.reach) == 66
    assert "sched_f_mach" in imp.seeds


# ── 법칙 밖 파라미터 ───────────────────────────────────────────────────────

def test_offgraph_params_have_no_seeds_but_are_not_no_influence(impacts, refs):
    """항법·작동기·유도는 IR 밖이라 개루프가 못 본다. '영향 없음'과 구분돼야 한다."""
    for pid in ("nav/ErrorModel.pos_std_h", "actuator/SecondOrderActuator.wn",
                "guidance/LOS.accept_radius"):
        assert impacts[pid].seeds == ()
        assert refs[pid].in_law is False
    assert refs["fcl/Autopilot.kp_alt"].in_law is True


# ── 그래프 유틸 ────────────────────────────────────────────────────────────

def test_node_depths_satisfy_the_recurrence(base_shape):
    graph = make_law(base_shape).runner.graph
    d = node_depths(graph)
    for node in graph.nodes:
        assert d[node.id] == 1 + max((d[r] for r in node.refs), default=0)
    assert max(d[n.id] for n in graph.nodes) == 16


def test_forward_reach_matches_brute_force(base_shape):
    graph = make_law(base_shape).runner.graph
    for seed in ("ap_alt_pid", "sched_f_mach", "mix_rudder"):
        got = forward_reach(graph, [seed])
        want, changed = {seed}, True
        while changed:  # 고정점까지 반복 — 위상 순서를 쓰지 않는 독립 구현
            changed = False
            for node in graph.nodes:
                if node.id not in want and any(r in want for r in node.refs):
                    want.add(node.id)
                    changed = True
        assert got == want


def test_apply_param_does_not_mutate_the_original(base_shape, refs):
    before = base_shape.fingerprint()
    apply_param(base_shape, refs["fcl/Autopilot.kp_alt"], 99.0)
    apply_param(base_shape, refs["fcl/ScasAxis.pitch.kp"], 99.0)
    assert base_shape.fingerprint() == before


# ── 세 번째 상태: 그래프에 방출되지 않는 상수 ──────────────────────────────

def test_scheduled_k_rate_is_inert_not_overridden(impacts):
    """스케줄 경로는 상수 대신 조회 노드를 쓴다 — 상수가 덮어써지는 게 아니라 **없다**.

    overridden(있지만 덮어써짐)과 구분된다. 폼에는 값이 보이는데 편집해도 아무 일이
    없는 자리라, 화면이 말해 주지 않으면 사용자가 혼자 알아내야 한다.
    """
    imp = impacts["fcl/ScasAxis.pitch.k_rate"]
    assert imp.inert
    assert imp.seeds == () and imp.overridden == ()
    assert not impacts["fcl/ScasAxis.yaw.k_rate"].inert  # 요축은 스케줄 없음


def test_offgraph_params_are_not_inert(impacts):
    """법칙 밖은 inert가 아니다 — inert는 '있어야 하는데 없다'는 뜻이라 의미가 다르다."""
    assert not impacts["nav/ErrorModel.pos_std_h"].inert


def test_inert_disappears_without_schedule():
    assert not param_impacts(Shape(with_schedule=False))["fcl/ScasAxis.pitch.k_rate"].inert


# ── 1단 payload ────────────────────────────────────────────────────────────

def test_structural_payload_shape(base_shape):
    from collections import Counter

    p = structural_payload(base_shape)
    kinds = Counter(n["kind"] for n in p["nodes"])
    # 입력 19 → 23: cmd_pitch·cmd_hdot·pitch_on·hdot_on
    assert kinds["ir"] == 66 and kinds["input"] == 23 and kinds["output"] == 7
    assert kinds["metric"] == len(p["metrics"]) and kinds["plant"] == 1
    assert p["topological_order"] is True
    assert "rank" not in p["nodes"][0]  # 층 번호는 소비자가 계산 — 두 곳에 정의하지 않는다


def test_payload_edges_reference_existing_nodes(base_shape):
    p = structural_payload(base_shape)
    ids = {n["id"] for n in p["nodes"]}
    for e in p["edges"]:
        assert e["src"] in ids, e
        assert e["dst"] in ids, e


def test_payload_ir_edges_are_forward_only(base_shape):
    """선언 순서가 위상 순서 — 화면의 랭크 계산이 이 전제 위에 선다."""
    p = structural_payload(base_shape)
    order = {n["id"]: i for i, n in enumerate(p["nodes"]) if n["kind"] in ("input", "ir")}
    for e in p["edges"]:
        if e["kind"] == "ir" and e["src"] in order and e["dst"] in order:
            assert order[e["src"]] < order[e["dst"]], e


def test_payload_warns_about_dead_edits(base_shape):
    """무력화·미방출은 조용히 넘어가면 안 되는 것들이라 경고로 승격한다."""
    w = " ".join(structural_payload(base_shape)["warnings"])
    assert "게인 스케줄이 덮어써" in w
    assert "그래프에 방출되지 않는" in w


def test_payload_is_json_serializable(base_shape):
    """allow_nan=False가 진짜 검사다 — NaN이 섞이면 여기서 터진다 (브라우저 JSON.parse 보호)."""
    import json

    text = json.dumps(structural_payload(base_shape), allow_nan=False)
    assert '"nodes"' in text and '"edges"' in text


# ── 덮임 판정은 이름이 아니라 값 이동으로 유도한다 ─────────────────────────

def test_override_follows_the_schedule_slots_not_a_band_list():
    """AP 게인도 스케줄할 수 있다 (graphs.SCHEDULABLE 16칸) — SCAS만 보면 놓친다.

    파라미터 이름(`kp_alt`)과 포트 이름(`kp`)이 다르므로 이름 매칭으로는 못 잡는다.
    실제로 값이 움직인 인자가 전부 게인 포트인지로 판정한다.
    """
    from claw.fcl.demo import make_demo_gain_tables

    tables = make_demo_gain_tables(names=("alt.kp", "alt.ki", "pitch.kp"))
    imp = param_impacts(Shape(gain_tables=tables))
    assert imp["fcl/Autopilot.kp_alt"].overridden == ("ap_alt_pid",)
    assert imp["fcl/Autopilot.ki_alt"].overridden == ("ap_alt_pid",)
    # 스케줄하지 않은 자리는 그대로 먹는다 — 자리 단위로 갈린다
    assert imp["fcl/ScasAxis.pitch.kp"].overridden == ("scas_pitch_pid",)
    assert imp["fcl/ScasAxis.pitch.ki"].overridden == ()
    assert imp["fcl/Autopilot.k_hdot"].overridden == ()


def test_override_is_not_claimed_when_wiring_changes():
    """배선·enable만 바뀐 노드는 덮임이 아니다 — 인자가 안 움직였으면 판정하지 않는다."""
    imp = param_impacts(Shape())["fcl/Autopilot.k_thr_turn"]
    assert imp.structural
    assert imp.overridden == ()


# ── 모순 조합은 조용히 삼키지 않는다 ───────────────────────────────────────

def test_gain_tables_without_schedule_is_refused_like_codegen():
    """조립 함수의 가드가 실제로 울려야 한다 — 단락시키면 사용자가 기술한 것과
    **다른 법칙**을 분석해 놓고 지문은 맞다고 말하게 된다 (codegen 라우트는 422)."""
    from claw.fcl.demo import make_demo_gain_tables

    with pytest.raises(ValueError, match="with_schedule=True"):
        make_law(Shape(with_schedule=False, gain_tables=make_demo_gain_tables()))


def test_unknown_scas_axis_is_refused():
    """조용히 버리면 지문만 움직이고 그래프는 그대로다 — 무증상 거짓말."""
    with pytest.raises(ValueError, match="알 수 없는 SCAS 축"):
        make_law(Shape(scas={"badaxis": {"kp": 1.0}}))
