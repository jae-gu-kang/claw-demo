"""스케줄 **자리** 검증 — 어떤 게인에 테이블을 붙일 수 있고, 붙이면 뭐가 달라지나.

값(테이블 조회·필터·불연속)은 test_fcl_law가 본다. 여기는 구성이 대상이다:
자리 목록의 정본성, 설계 상수 대응표, 자리를 켜고 끌 때 생성 C가 실제로 바뀌는지.
"""

import pytest

from claw.codegen.emit_c import emit_c
from claw.fcl.demo import (
    DEFAULT_SCHEDULED,
    DEMO_PITCH,
    demo_design_gains,
    make_demo_fcl,
    make_demo_gain_tables,
)
from claw.fcl.graphs import SCHEDULABLE, autopilot_nodes
from claw.fcl.schedule import design_gains
from claw.tables import Table

DT = 0.01


def _module(**kw):
    fcl = make_demo_fcl(**kw).init(DT)
    return emit_c(fcl.runner.graph, fcl.runner)


def test_스케줄_자리는_16개다():
    """6그룹 × 3키 = 18이 아니다 — 속도·헤딩은 rate 경로가 없어 k_rate가 빠진다."""
    slots = demo_design_gains()
    assert len(slots) == 16
    assert sum(len(v) for v in SCHEDULABLE.values()) == 16
    assert "alt.k_rate" in slots  # 승강률 댐핑 k_hdot 자리 — 유효하다
    assert "speed.k_rate" not in slots
    assert "heading.k_rate" not in slots
    # 기본 스케줄은 그중 6자리, 나머지 10자리는 설계점 고정
    assert set(DEFAULT_SCHEDULED) <= set(slots)
    assert len(DEFAULT_SCHEDULED) == 6


def test_자리표가_조립_거부와_일치한다():
    """SCHEDULABLE이 정본이라는 뜻은 '표에 없으면 거부된다'는 것 — 둘이 어긋나면
    웹이 '켤 수 있다'고 보여 준 자리가 실행 시점에 터진다."""
    srcs = {u: u for u in (
        "psi", "h", "hdot", "V", "cmd_speed", "cmd_alt", "cmd_heading",
        "cmd_pitch", "cmd_hdot",
        "speed_on", "alt_on", "heading_on", "pitch_on", "hdot_on",
    )}
    cfg = dict(
        kp_spd=0.15, ki_spd=0.03, tau_spd=2.0,
        kp_alt=0.004, ki_alt=0.0004, k_hdot=-0.008, tau_alt=5.0,
        kp_hdg=4.0, ki_hdg=0.0, tau_hdg=1.0,
        kp_vs=0.02, ki_vs=0.005, tau_vs=2.0,
        theta_lo=-0.3, theta_hi=0.3, phi_max=0.7, k_pitch_turn=0.05, k_thr_turn=0.0,
    )
    for group in ("speed", "alt", "heading"):
        for key in ("kp", "ki", "k_rate"):
            ports = {group: {key: f"g_{group}_{key}"}}
            allowed = key in SCHEDULABLE[group]
            if allowed:
                autopilot_nodes("ap", srcs=srcs, gain_ports=ports, **cfg)
            else:
                with pytest.raises(ValueError, match="스케줄 불가"):
                    autopilot_nodes("ap", srcs=srcs, gain_ports=ports, **cfg)


def test_설계_상수표가_그래프가_내는_상수와_같다():
    """`design_gains`는 '스케줄을 끄면 이 값으로 굳는다'는 약속이다. 이 표가 조용히
    낡으면 웹이 엉뚱한 고정값을 보여 주므로, 실제 방출된 파라미터와 대조해 못박는다."""
    design = demo_design_gains()
    # 아무 자리도 스케줄하지 않은 형상 = 전 자리가 상수
    fcl = make_demo_fcl(with_schedule=False).init(DT)
    params = {n.id: n.params for n in fcl.runner.graph.nodes if n.params}
    axis = {  # 자리 → (PID 노드, k_rate를 들고 있는 노드)
        "pitch": ("scas_pitch_pid", "scas_pitch_damp"),
        "roll": ("scas_roll_pid", "scas_roll_damp"),
        "yaw": ("scas_yaw_pid", "scas_yaw_damp"),
        "alt": ("ap_alt_pid", "ap_alt_damp"),
        "speed": ("ap_spd_pid", None),
        "heading": ("ap_hdg_pid", None),
    }
    for name, want in design.items():
        group, _, key = name.partition(".")
        pid_id, damp_id = axis[group]
        got = params[damp_id]["k"] if key == "k_rate" else params[pid_id][key]
        assert got == pytest.approx(want), f"{name}: 표 {want} ≠ 그래프 {got}"


def test_모든_자리를_하나씩_켤_수_있다():
    """16자리가 전부 조립·C 생성까지 간다 — 특히 alt.k_rate(k_hdot)는 모드 영역 안의
    Product로 배선되는 특수 경로다(graphs.py autopilot_nodes)."""
    for name in demo_design_gains():
        mod = _module(gain_tables=make_demo_gain_tables([name]))
        node = name.replace(".", "_")
        assert f"sched_{node}" in mod.files["fcl_sched.c"], name
    # alt.k_rate는 상수 곱이 아니라 신호 곱이 되어야 한다
    mod = _module(gain_tables=make_demo_gain_tables(["alt.k_rate"]))
    assert "sched_alt_k_rate_y * hdot" in mod.files["fcl_ap.c"]


def test_자리를_빼면_상수로_접히고_지문이_바뀐다():
    """스케줄 대상 선택은 표시 설정이 아니라 **형상**이다 — 탑재 C 구조가 달라진다."""
    base = _module()
    fewer = _module(gain_tables=make_demo_gain_tables(["pitch.kp", "roll.kp"]))
    assert base.files["fcl_sched.c"].count("claw_lookup1d") == 6
    assert fewer.files["fcl_sched.c"].count("claw_lookup1d") == 2
    # 빠진 ki는 설계 상수로 돌아온다 (포트 참조가 사라진다)
    assert "sched_pitch_ki" in base.files["fcl_scas.c"]
    assert "sched_pitch_ki" not in fewer.files["fcl_scas.c"]
    assert str(DEMO_PITCH["ki"]) in fewer.files["fcl_data.c"]
    assert base.fingerprint != fewer.fingerprint


def test_전부_끄면_스케줄_파일_자체가_사라진다():
    """'전부 끔'은 with_schedule=False와 같은 형상 — 룩업도 필터 상태도 남지 않는다."""
    off = _module(with_schedule=False)
    assert "fcl_sched.c" not in off.files
    assert "fcl_sched.h" not in off.files
    assert "claw_lookup1d" not in off.files["fcl_scas.c"]
    assert off.fingerprint != _module().fingerprint


def test_기본_테이블은_예전과_같다():
    """자리 선택을 도입해도 **기본 형상은 불변** — flight/gen 커밋 산출물이 걸려 있다."""
    tabs = make_demo_gain_tables()
    assert tuple(tabs) == DEFAULT_SCHEDULED
    design = demo_design_gains()
    for name, tab in tabs.items():
        assert tab.extrapolate == "clip"
        assert tab.axis_names == ("mach",)
        # 설계점 M0.6에서는 어느 자리든 설계 상수 그대로
        assert float(tab.interp(mach=0.6)) == pytest.approx(design[name])
    # 지문은 기체를 단발로 맞추면서 갱신됐다 — 차동추력 계수를 0으로 내린 설계 변경이
    # 믹서 파라미터를 바꿨다(fcl/demo.py DEMO_K_DIFF_THR, flight/gen 재생성 동반).
    # 지문이 움직이는 것이 곧 설계 변경이고, 안 움직였다면 그게 이상한 것이다.
    # (직전 갱신은 이륙·착륙 도입 — 종방향 축과 θ 출처 Switch가 그래프에 들어갔다.)
    assert _module().fingerprint == "a1a24ddcaf2e9fe3"


def test_없는_자리를_요구하면_거부한다():
    with pytest.raises(ValueError, match="스케줄 불가 자리"):
        make_demo_gain_tables(["speed.k_rate"])
    with pytest.raises(ValueError, match="스케줄 불가 자리"):
        make_demo_gain_tables(["pitch.washout_tau"])


def test_설계_상수표는_주입된_형상을_따른다():
    """`design_gains`는 데모 상수를 박아 두지 않는다 — 다른 기체 프로파일에서도
    '스케줄을 끄면 무엇이 되나'의 답이 그 기체의 설계값이어야 한다."""
    scas = {g: {"kp": 1.0, "ki": 2.0, "k_rate": 3.0} for g in ("pitch", "roll", "yaw")}
    ap = {"kp_spd": 9.0, "ki_spd": 8.0, "kp_alt": 7.0, "ki_alt": 6.0,
          "k_hdot": 5.0, "kp_hdg": 4.0, "ki_hdg": 3.0}
    got = design_gains(scas, ap)
    assert got["pitch.k_rate"] == 3.0
    assert got["alt.k_rate"] == 5.0  # k_hdot — 이름이 다른 자리
    assert got["speed.kp"] == 9.0
    assert "speed.k_rate" not in got


def test_스케줄된_자리는_주입_테이블을_그대로_쓴다():
    """자리 선택이 값 편집 경로를 막지 않는다 — 부분집합도 전체 교체 계약 그대로."""
    tab = Table({"mach": (0.2, 0.8)}, (-4.0, -1.0), name="pitch.kp", extrapolate="clip")
    fcl = make_demo_fcl(gain_tables={"pitch.kp": tab}).init(DT)
    assert fcl.schedule.step(0.2, 1000.0, 200.0)["pitch"]["kp"] == pytest.approx(-4.0)
