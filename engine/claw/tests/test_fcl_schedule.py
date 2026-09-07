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
    """'전부 끔'은 with_schedule=False와 같은 형상 — 스케줄 흔적이 남지 않는다.

    종전에는 "fcl_scas.c에 claw_lookup1d가 없다"로 봤다. 그때는 SCAS에 룩업을
    넣을 수 있는 것이 스케줄뿐이라 정확한 대리 지표였지만, 제어권한 배분의 트림
    테이블(plant/demo.py)이 **정당하게** 거기 룩업을 하나 넣으면서 어긋났다.
    스케줄 자체를 본다 — 대리 지표가 아니라.

    이 단정이 초록인 것은 배분이 스케줄과 독립이라는 증거이기도 하다: 배분은
    필터된 mach가 아니라 원 mach를 읽으므로 스케줄을 꺼도 그대로 산다
    (fcl/graphs.py `_roll_budget_nodes` 참조).
    """
    off = _module(with_schedule=False)
    assert "fcl_sched.c" not in off.files
    assert "fcl_sched.h" not in off.files
    assert "sched_" not in off.files["fcl_scas.c"], "스케줄 흔적이 SCAS에 남았다"
    # 배분의 룩업은 남아야 한다 — 없으면 배분이 스케줄에 딸려 꺼진 것이다
    assert "scas_alloc_trim" in off.files["fcl_scas.c"]
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
    # 지문이 움직이는 것이 곧 설계 변경이고, 안 움직였다면 그게 이상한 것이다.
    # 이번 갱신은 안티와인드업 판정을 축 출력 기준으로 바꾼 구조 변경 —
    # 감쇠항이 PID의 둘째 입력이 되었다(graphs.py scas_axis_nodes).
    # 앞선 갱신은 단발 전환(DEMO_K_DIFF_THR = 0)이었고, 프로펠러 추력 모델은
    # 순수 플랜트 변경이라 지문을 안 움직였다.
    # 앞선 갱신은 엘레본 제어권한 배분 — 선회 하중으로 피치 몫을 먼저 떼고 롤이
    # 나머지를 가져간다. 축 순서가 롤→피치로 바뀌었다 (graphs.py scas3_nodes).
    # 이번 갱신은 ki = 0 적분 경로 폴딩(emit_c.py _pid_has_integrator) — 헤딩·요축
    # 가드가 영구 도달 불가 분기라 방출을 멈췄고(DAL A 죽은 코드 논점), 출력식은
    # +0.0 소거뿐이라 법칙은 그대로지만 파라미터 목록(*_pid_ki)이 줄어 지문이
    # 움직였다. 정본 사슬은 test_parity.py::test_분할해도_지문은_그대로다와 같다.
    # 이번 갱신은 **축별 동압 상한**(fcl/demo.py _cap_for) — 롤 3자리만 상한 4.0이라
    # M0.42 아래 룩업 |값|이 커졌다(roll.k_rate는 −0.4 → −0.8로 부호가 음이다). 법칙도 자리 구성도 그대로이므로 구조가 아니라
    # **데이터** 변경이고, 그래도 지문은 움직인다(룩업 표가 탑재 C에 박힌다).
    assert _module().fingerprint == "2dd6835e50ae5869"


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


def test_게인_격자_범위는_자르면_안_된다():
    """상단 절단이 조용히 게인을 **올린다** — 이 가드가 없어서 실제로 한 번 놓쳤다.

    Table이 extrapolate="clip"이라 격자 밖은 경계값으로 고정된다. 프로펠러 전환으로
    수평비행 상단이 M0.60으로 내려왔다고 격자를 M0.6에서 끊으면, 그 위에서 1/q̄ 롤오프가
    사라지고 게인이 설계값에 붙박인다 — _F_CAP이 리밋사이클을 만든다고 실측한 바로 그
    방향이다. 게다가 M0.6 위는 **강하로 도달한다**(3000 m에서 스로틀 0으로도 M0.73).

    하단은 반대다: 상한이 이미 평평하게 만드는 구간이라 잘라도 값이 같다(평평해지는
    자리는 축별 상한을 따라 갈린다 — 피치 M0.424 아래, 롤 M0.300 아래).
    그래서 이 가드는 **상단만** 못박는다.
    """
    import numpy as np

    from claw.fcl.demo import _F_CAP, _M_DESIGN
    from claw.plant import make_demo_structural_limits

    # 자리를 **명시**한다 — 임의 테이블을 뽑아 기본 상한과 맞추면 축이 어긋난다
    tab = make_demo_gain_tables()["pitch.kp"]
    machs = np.asarray(tab.axes[0])
    # 구조 급강하 한계(V_D 상당)까지는 격자가 있어야 한다 — 거기가 실제 도달 상한이다
    assert machs[-1] >= make_demo_structural_limits()["mach_d"] - 1e-9, (
        f"격자 상단 {machs[-1]}이 mach_d 아래 — 그 위에서 스케줄이 clip으로 굳는다")
    # 그리고 상단 부근이 실제로 롤오프 중이어야 한다 (평평하면 자른 것과 같다)
    f = np.minimum((_M_DESIGN / machs) ** 2, _F_CAP)
    assert f[-1] < f[-2] < f[-3], "격자 상단이 평평하다 — 1/q̄ 법칙이 죽었다"


def test_상한은_축별이고_모르는_축은_기본값을_따른다():
    """스케일 **법칙**은 자리마다 같고 **상한**만 축별이다 (fcl/demo.py _cap_for).

    롤이 예외인 것은 롤을 재 봤기 때문이지 롤이라서가 아니다 — 리밋사이클을 만든
    것은 pitch.kp·pitch.k_rate였고 롤 3개는 σ 3.3°(= 부스트 없음)로 무관했다.
    측정이 없는 축을 관대하게 열면 근거 없이 여는 것이라 **기본 상한**을 따른다.

    실측 근거 (18칸 기본 격자, 롤 자세 PM 합격선 45°):
      균일 2.0 → 39.6°(3칸 미달) · 피치2·롤3 → 44.8°(1칸) · 피치2·롤4 → 48.4°(통과)
    대가는 직진 순항 정착 de σ 1.1° → 1.7°(리밋사이클 문턱 6.0°의 28 %)다.
    """
    import numpy as np

    from claw.fcl.demo import (_F_CAP, _F_CAP_ROLL, _M_DESIGN, _cap_for,
                               demo_design_gains)

    # **값을 못박는다.** 아래 배분 단정은 전부 _F_CAP·_F_CAP_ROLL로 쓰여 있어
    # 상한을 어떤 값으로 바꿔도 자기들끼리는 일관된다 — 그래서 「축별」이라는
    # 이름이 지키는 것(균일로 되돌리지 않기)을 이 두 줄이 따로 지킨다. 값을
    # 고치려면 위 docstring의 PM·σ 표를 다시 재고 함께 고쳐야 한다.
    assert _F_CAP == 2.0, "기본(피치) 상한이 바뀌었다 — 리밋사이클 실측을 다시 하라"
    assert _F_CAP_ROLL == 4.0, "롤 상한이 바뀌었다 — 롤 PM·승강타 σ를 다시 재라"

    assert _cap_for("roll.kp") == _F_CAP_ROLL
    # 미측정 축은 기본값 — 이 단정이 죽으면 근거 없이 상한을 연 것이다
    for name in ("pitch.kp", "yaw.k_rate", "alt.kp", "무슨자리"):
        assert _cap_for(name) == _F_CAP, f"{name}이 기본 상한을 안 따른다"

    # 상한이 실제로 테이블에 반영된다. 표본은 **경계를 피한다** — 롤 상한이 물리기
    # 시작하는 M0.300에서는 이상 배수가 마침 4.0이라 min(ideal, cap)이 cap ≥ 4인
    # 어떤 값에서도 같아져, 그 자리만 보면 「상한 4」와 「상한 없음」이 구조적으로
    # 구분되지 않는다. M0.25는 이상 5.76이라 갈린다.
    tabs = make_demo_gain_tables()
    design = demo_design_gains()
    machs = np.asarray(tabs["roll.kp"].axes[0])
    i = int(np.argmin(np.abs(machs - 0.25)))
    assert machs[i] == pytest.approx(0.25)
    ideal = (_M_DESIGN / 0.25) ** 2
    assert ideal == pytest.approx(5.76)
    for name, tab in tabs.items():
        got = np.asarray(tab.data)[i]
        assert got / design[name] == pytest.approx(min(ideal, _cap_for(name))), name


def test_롤_상한이_저속_코너_위상여유를_지킨다():
    """이 변경이 **존재하는 이유**를 못박는다 — 값이 아니라 결과를.

    위 test는 상한 숫자를 못박지만 "그래서 무엇이 좋아지나"는 안 본다. 그 답이
    여기다: 저속 코너(M0.3/h3000)에서 롤 자세 위상여유가 합격선을 넘는가.
    균일 상한으로 되돌리면 39.6°로 떨어져 **실패한다** — 상한 값을 몰래 바꾸거나
    _cap_for를 무력화하면 이 단정이 먼저 죽는다.

    싸다: 트림 1점 + 선형화뿐이라 두 형상 합쳐 ~0.03 s다(리밋사이클을 보려면
    6DOF 미션이 필요하지만 **위상여유는 선형이라** 그럴 필요가 없다 — 실제로
    피치 리밋사이클은 선형 마진에 안 잡힌다, fcl/demo.py _F_CAP 주석).

    이 표를 다시 만들 때 쓰는 도구는 `evaluate(depth="linear")`다. 설계측
    `scheduled_margin_point`는 루프 조성(작동기·지연·레이트 폐쇄)이 달라 같은
    점에서 ~19° 높게 나온다 — 둘 다 맞지만 **같은 자가 아니다**.
    """
    # 상위 계층(pipeline)을 M7 테스트에서 부르는 **의도된 역전**이다 — 위 test가
    # 값을, 이 test가 그 값의 결과를 못박아 둘이 한 이야기라 갈라 두면 결과 쪽이
    # 고아가 된다. 함수 안에서 import해 나머지 테스트는 가볍게 둔다(이 파일 규약)
    import numpy as np

    from claw.common.contracts import TrimCase
    from claw.fcl.demo import (DEFAULT_SCHEDULED, _F_CAP, _M_DESIGN,
                               demo_design_gains)
    from claw.pipeline.criteria import GainEvalCriteria
    from claw.pipeline.evaluate import evaluate
    from claw.pipeline.influence import Shape
    from claw.plant.demo import make_demo_aircraft
    from claw.trim import trim_batch

    ac = make_demo_aircraft()
    trs = trim_batch(ac, [TrimCase(name="M0.3_h3000", mach=0.3, alt=3000.0, fuel=200.0)])
    assert trs[0].converged, "저속 코너가 트림이 안 된다 — 엔벨로프가 바뀌었다"

    def roll_pm(shape):
        out = evaluate(ac, trs, shape, GainEvalCriteria(), depth="linear")
        loops = out["cases"][0]["stages"]["margins"]["loops"]
        # roll_att가 없거나 마진이 없는 것은 **실재하는 상태**다(실효 게인이 전부 0이면
        # 자리가 zero로 보고된다 — design/schedmap.py). 그때 KeyError로 죽으면 "왜"가
        # 사라지므로 사유를 남긴다 (test_landing.py의 빈 순항 구간 가드와 같은 규약)
        lp = (loops or {}).get("roll_att")
        assert lp and lp.get("margins"), f"roll_att 마진을 못 쟀다 — 자리 상태 {lp}"
        return float(lp["margins"]["pm_deg"])

    limit = GainEvalCriteria().margin.pm_min_deg
    assert roll_pm(Shape()) > limit, "출하 형상이 저속 코너 위상여유를 못 지킨다"

    # 균일 상한(= 이 변경 이전)으로 되돌리면 떨어진다 — 그것이 이 상한의 이유다
    machs = np.round(np.arange(0.15, 0.951, 0.05), 4)
    design = demo_design_gains()
    uniform = {n: Table({"mach": machs},
                        design[n] * np.minimum((_M_DESIGN / machs) ** 2, _F_CAP),
                        name=n, extrapolate="clip")
               for n in DEFAULT_SCHEDULED}
    assert roll_pm(Shape(gain_tables=uniform)) < limit, (
        "균일 상한에서도 합격선을 넘는다 — 그렇다면 축별 상한의 근거가 사라진 것이라\n"
        "        _F_CAP_ROLL을 지우는 것이 맞다. 단 판정선(pm_min_deg)을 낮췄다면\n"
        "        상한이 아니라 그쪽부터 보라 — 이 단정은 둘 다에 반응한다.")
