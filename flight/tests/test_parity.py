"""탑재 C 산출물 대조 — 설계 실행(Python 백엔드) ↔ 생성 C.

증분 C에서 `fcl/`이 IR 백엔드로 이관되면서 손으로 쓴 두 번째 구현은 사라졌다.
그래서 여기 남은 대조는 **같은 IR의 두 백엔드**다 — 이것이 이 저장소에서 유일하게
남은 진짜 이중 구현이고, 탑재 코드가 설계와 같은 답을 내는지의 근거다.

전부 배정밀도이고 연산 순서를 문자 그대로 맞췄으므로 목표는 근사가 아니라
**비트 일치**다. 허용오차를 두면 진짜 어긋남이 그 아래 숨는다.

컴파일러가 없으면 C 대조만 건너뛴다 — 폐쇄망·최소 환경에서도 Python 경로는
그대로 검증된다 (02 §1 의존성 최소화).
"""

import math
import shutil
import subprocess

import mission_trace
import pytest
from generate import DT, GEN_DIR, build, fcl_demo_runner, manifest, scas_yaw_runner

from claw.fcl.demo import DEMO_YAW, make_demo_fcl
from claw.fcl.scas import ScasAxis

CC = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
needs_cc = pytest.mark.skipif(CC is None, reason="C 컴파일러 없음 — Python 경로만 검증")

# -ffp-contract=off 는 장식이 아니다 — 측정으로 확인됨: contract=fast로 빌드하면
# 컴파일러가 `a*b + c`를 FMA 하나로 합쳐 중간 반올림이 사라지고, 같은 입력에서
# 2.8e-16 어긋난다(clang 14, -O2). 탑재 빌드에도 같은 지정이 필요하며,
# 그래서 생성 헤더가 이 요구를 빌드 조건으로 명시한다.
CFLAGS = [
    "-std=c99", "-O2", "-Wall", "-Wextra", "-pedantic", "-Werror", "-ffp-contract=off",
]


@pytest.fixture(scope="module")
def trace():
    """실제 데모 미션 1회 — 모드 전환·게인 스케줄·리미터·항법 무효가 모두 들어 있다."""
    return mission_trace.run()


def _build(name, macro, tmp_path):
    # 컴파일 단위는 생성기가 낸다 — 기능축 파티션이 늘어도 목록이 새지 않는다
    exe = tmp_path / f"harness_{name}"
    cmd = [
        CC, *CFLAGS, f"-I{GEN_DIR}", f"-D{macro}",
        str(GEN_DIR.parent / "tests" / "harness.c"),
        *(str(GEN_DIR / src) for src in manifest()[name]),
        "-lm", "-o", str(exe),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"{name} 컴파일 실패:\n{res.stderr}"
    return exe


def _first_diff(a, b, label):
    for k, (x, y) in enumerate(zip(a, b, strict=True)):
        if x is None:
            continue
        if x != y:
            return f"{label} 스텝 {k} (t={k * DT:.2f}s): {x!r} vs {y!r} (차 {x - y!r})"
    return None


# ── 최상위 제어법칙 ───────────────────────────────────────────────────────


def _ir_runner(warm):
    runner = fcl_demo_runner()
    de0, th0, thr0 = warm
    # 손으로 쓴 법칙과 같은 트림 웜스타트 (law.py:61, autopilot.py:126, simulator.py:132)
    runner.reset(
        states={"scas_pitch_pid": de0, "ap_alt_pid": th0, "ap_spd_pid": thr0},
        hold={"elevon_l": de0, "elevon_r": de0, "rudder": 0.0,
              "throttle_l": thr0, "throttle_r": thr0},
    )
    return runner


def test_law_replays_deterministically(trace):
    """같은 입력·같은 웜스타트면 법칙이 같은 답을 낸다 — C 대조의 기준선.

    미션 중 기록한 출력과, 그 입력을 따로 세운 러너에 다시 흘린 출력이 같아야
    한다. 어댑터(항법→공학량)와 웜스타트 주입이 재현 가능한지를 여기서 잡는다.
    """
    inputs, refs, warm = trace
    runner = _ir_runner(warm)
    got = [runner.step(**row) for row in inputs]
    for i, name in enumerate(mission_trace.OUTPUT_ORDER):
        diff = _first_diff([r[i] for r in refs], [g[name] for g in got], name)
        assert diff is None, f"재생이 재현되지 않음 — {diff}"


def test_trace_exercises_the_hard_paths(trace):
    """대조가 통과해도 그 경로를 안 밟았으면 의미가 없다 — 커버리지를 단정한다."""
    inputs, refs, _warm = trace
    assert any(row["nav_valid"] == 0.0 for row in inputs), "항법 무효(홀드) 구간 없음"
    for flag in ("speed_on", "alt_on", "heading_on", "pitch_on", "hdot_on"):
        vals = {row[flag] for row in inputs}
        assert vals == {0.0, 1.0}, f"{flag}가 두 상태를 모두 밟지 않음: {vals}"
    assert len({row["mach"] for row in inputs}) > 100, "게인 스케줄이 움직이지 않음"
    assert any(abs(r[0]) >= 0.349 for r in refs), "엘레본 포화를 밟지 않음"
    # PID 조건부 적분의 **포화 가지**를 밟아야 C 대조가 반쪽이 아니다. 분기가 한쪽만
    # 실행되면 비트 일치는 통과하면서 나머지 가지는 검증되지 않은 채 탑재된다
    import claw.blocks.controllers as controllers

    hits = {"free": 0, "blocked": 0}
    orig = controllers.PID.step

    def counting_step(self, e, u_ext=0.0, kp=None, ki=None, kd=None,
                      out_lo=None, out_hi=None):
        # 조건식을 **복사하지 않는다** — 복사하면 구현이 바뀔 때 가드가 옛 공식으로
        # 세면서 "양쪽 다 밟았다"고 계속 통과한다. 대신 클램프-온리였다면 나왔을
        # 상태와 비교한다: 갈라졌으면 곧 조건부 적분이 일한 스텝이다.
        # u_ext(축 외부항)는 그대로 넘긴다 — 판정이 축 출력 기준이라 이걸 빠뜨리면
        # 가드가 세는 대상이 실제 구현과 달라진다
        ki_ = self.ki if ki is None else ki
        # 한계도 포트로 덮일 수 있다(제어권한 배분) — 클램프-온리 비교가 **같은 한계**를
        # 써야 한다. 정적 한계로 비교하면 배분이 걸린 스텝을 전부 "갈라졌다"고 세어
        # 가드가 거짓으로 통과한다
        lo_ = self.out_lo if out_lo is None else out_lo
        hi_ = self.out_hi if out_hi is None else out_hi
        before = self._i
        y = orig(self, e, u_ext, kp, ki, kd, out_lo, out_hi)
        clamp_only = min(max(before + self.dt * ki_ * e, lo_), hi_)
        hits["blocked" if self._i != clamp_only else "free"] += 1
        return y

    runner = _ir_runner(_warm)
    controllers.PID.step = counting_step
    try:
        for row in inputs:
            runner.step(**row)
    finally:
        controllers.PID.step = orig
    assert hits["free"] > 0 and hits["blocked"] > 0, (
        f"조건부 적분 분기가 한쪽만 실행됨: {hits} — C 대조가 반쪽이다")

    # 제어권한 배분도 같은 이유로 밟혀야 한다. 대조 미션에서 선회 기동이 빠지면
    # φ_cmd ≡ 0 → R이 상수 → 동적 한계가 한 번도 안 움직이고, 그래도 비트 일치는
    # 초록으로 통과한다 — 새 C 경로가 검증 없이 탑재되는 것이다.
    env_runner = _ir_runner(_warm)
    roll_his = []
    bound_roll = bound_pitch = 0
    integ_over = -math.inf
    for row in inputs:
        env_runner.step_all(**row)
        e = env_runner.last_env
        if "scas_alloc_roll_hi" not in e:
            continue  # 항법 무효 = 그래프 동결
        roll_his.append(e["scas_alloc_roll_hi"])
        if abs(abs(e["scas_roll_sat"]) - e["scas_alloc_roll_hi"]) < 1e-12:
            bound_roll += 1
        if abs(abs(e["scas_pitch_sat"]) - e["scas_alloc_pitch_hi"]) < 1e-12:
            bound_pitch += 1
        # 적분기가 **현재** 배분 한계 안에 갇혀 있어야 한다. 저장된 와인드업이
        # 0이라는 뜻이고, 한계가 줄어드는 순간이 그 시험대다 — 클램프가 포트가
        # 아니라 생성자 한계를 보면 여기서 넘친다. 실측: 두 축 모두 초과 0.
        #
        # "포화 중 적분기가 자랐나"로 세면 안 된다: 한계가 줄면 클램프가 범위 밖
        # 적분기를 되당기는데(크기는 줄지만 부호에 따라 값은 커진다) 그게 포화
        # 방향 증가로 잡힌다. 실제로 그 방식으로는 피치 4건이 걸렸고 전부
        # 와인드업이 아니라 복원이었다.
        for ax, lim in (("roll", "scas_alloc_roll_hi"),
                        ("pitch", "scas_alloc_pitch_hi")):
            integ = env_runner.instances[f"scas_{ax}_pid"]._i
            integ_over = max(integ_over, abs(integ) - e[lim])
    # **한계가 움직여야** 한다 — "0보다 크다"류는 단정이 못 된다. R ≥ k_load > 0이
    # 항상 성립하도록 설계했으므로 "예산이 좁혀졌다"는 전 스텝에서 참이고, 선회가
    # 빠져 φ_cmd ≡ 0이 돼도 그대로 통과한다. 봐야 할 것은 폭이다.
    spread = max(roll_his) - min(roll_his)
    assert spread > 1e-6, (
        f"롤 예산이 상수다 (폭 {spread:.3e} rad) — φ_cmd가 안 움직였나. "
        "동적 한계 경로의 C 대조가 반쪽이다")
    assert integ_over <= 0.0, (
        f"적분기가 배분 한계를 넘어섰다 (최대 초과 {integ_over:+.3e} rad) — "
        "클램프가 포트 한계가 아니라 생성자 한계를 보고 있다")
    assert bound_roll > 0 and bound_pitch > 0, (
        f"동적 한계에 실제로 걸린 스텝이 없다 (롤 {bound_roll}, 피치 {bound_pitch}) "
        "— 배분 경로의 C 대조가 반쪽이다")


@needs_cc
def test_generated_fcl_matches_ir(trace, tmp_path):
    """생성 C가 IR·oracle과 비트 일치. -Werror이므로 경고 0도 함께 보증한다."""
    inputs, refs, warm = trace
    exe = _build("fcl", "HARNESS_FCL", tmp_path)

    stdin = " ".join(repr(v) for v in warm) + "\n"
    stdin += "\n".join(
        " ".join(repr(row[k]) for k in mission_trace.INPUT_ORDER) for row in inputs
    ) + "\n"
    run = subprocess.run([str(exe)], input=stdin, capture_output=True, text=True)
    assert run.returncode == 0, f"하네스 실행 실패:\n{run.stderr}"

    rows = [[float(x) for x in line.split()] for line in run.stdout.splitlines()]
    assert len(rows) == len(inputs), f"출력 {len(rows)}행 ≠ 입력 {len(inputs)}행"

    runner = _ir_runner(warm)
    ir = [runner.step(**row) for row in inputs]
    for i, name in enumerate(mission_trace.OUTPUT_ORDER):
        c_vals = [row[i] for row in rows]
        assert _first_diff([r[i] for r in refs], c_vals, name) is None, (
            f"설계 실행 ≠ 생성 C — {_first_diff([r[i] for r in refs], c_vals, name)}"
        )
        assert _first_diff([g[name] for g in ir], c_vals, name) is None, (
            f"러너 ≠ 생성 C — {_first_diff([g[name] for g in ir], c_vals, name)}"
        )


# ── SCAS 요축 (단일 출력 반환 경로) ───────────────────────────────────────


def _yaw_sequence(n=1200):
    """포화 진입·적분기 와인드업·워시아웃 정상상태를 반드시 밟는 입력."""
    for k in range(n):
        t = k * DT
        if t < 2.0:  # 오차·각속도를 같은 부호로 크게 → 출력 포화 + 적분기 클램프
            yield 0.5, 0.5
        elif t < 4.0:  # 반대 계단 → 반대편 포화, 적분기 언와인드
            yield -0.5, -0.5
        elif t < 7.0:  # 상수 각속도 → 워시아웃 정상상태(출력이 0으로 감쇠)
            yield 0.0, 0.3
        else:
            yield 0.2 * math.sin(2.0 * t), 0.15 * math.cos(3.0 * t)


def _yaw_reference():
    oracle = ScasAxis(**DEMO_YAW).init(DT)
    oracle.reset()
    runner = scas_yaw_runner()
    runner.reset()
    ref, ir, lines = [], [], []
    for att_err, rate in _yaw_sequence():
        ref.append(oracle.step(att_err, rate))
        ir.append(runner.step(att_err=att_err, rate=rate))
        lines.append(f"{att_err!r} {rate!r}")
    return ref, ir, "\n".join(lines) + "\n"


def test_yaw_axis_adapter_matches_graph():
    ref, ir, _ = _yaw_reference()
    assert _first_diff(ref, ir, "u") is None
    assert any(abs(v) >= DEMO_YAW["out_hi"] for v in ref), "포화를 한 번도 밟지 않음"


@needs_cc
def test_generated_yaw_axis_matches_ir(tmp_path):
    """단일 출력 그래프는 구조체가 아니라 값을 반환한다 — 그 경로도 대조한다."""
    exe = _build("scas_yaw", "HARNESS_SCAS_YAW", tmp_path)
    ref, ir, stdin = _yaw_reference()
    run = subprocess.run([str(exe)], input=stdin, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    got = [float(x) for x in run.stdout.split()]
    assert _first_diff(ref, got, "u") is None
    assert _first_diff(ir, got, "u") is None


# ── 믹서: 차동추력 배분 ───────────────────────────────────────────────────
#
# 이 기체는 단발이라 mix_diff_k = 0이고, 그러면 배분식이 항상 ±0.0이라 좌우 스로틀이
# 같은 값으로 무너진다. 미션 대조는 그 형상만 밟으므로 **배분 경로를 전혀 못 본다** —
# 부호를 뒤집거나 좌우 출력을 맞바꿔도 비트 일치가 통과한다(리뷰에서 변이 주입으로
# 확인). 구조를 일부러 남겨 두었고 쌍발을 다시 켤 수 있게 해 둔 이상, 그때 탑재 C가
# 반대쪽 엔진을 올려도 "비트 일치"로 보고되면 안 된다.
#
# 믹서는 무상태라 미션 재생이 필요 없다 — 계수를 켜고 입력 격자만 쓸어도 충분하다.

MIX_K = 0.4  # 0이 아니기만 하면 된다 — 배분식이 실제로 값을 내는지가 요점


def _mixer_reference():
    """(oracle, IR, C 입력줄) — 데모 믹서에서 계수만 켠 형상."""
    from claw.fcl.mixer import Mixer

    cfg = dict(make_demo_fcl().mixer.cfg, k_diff_thr=MIX_K)
    oracle = Mixer(**cfg)
    ref, lines = [], [repr(MIX_K)]
    # 클립 안·상한·하한을 모두 밟는 격자. dr은 반드시 양·음 둘 다 — 배분이 좌우
    # 어느 쪽으로 가는지는 부호로만 드러난다
    for thr in (0.0, 0.3, 0.7, 1.0):
        for de in (-0.4, -0.1, 0.2):
            for da in (-0.3, 0.05, 0.3):
                for dr in (-0.35, -0.1, 0.0, 0.15, 0.4):
                    o = oracle.step(de, da, dr, thr)
                    ref.append((o.elevon[0], o.elevon[2], o.rudder,
                                o.throttle[0], o.throttle[1]))
                    lines.append(f"{thr!r} {de!r} {da!r} {dr!r}")
    return ref, "\n".join(lines) + "\n"


def test_mixer_reference_actually_splits_throttle():
    """대조 전에 격자가 배분을 실제로 켰는지부터 — 안 켜졌으면 대조가 무의미하다."""
    ref, _ = _mixer_reference()
    assert any(tl != tr for *_, tl, tr in ref), "좌우 스로틀이 갈린 적이 없다"
    # 좌우 어느 쪽이 올라가는지가 dr 부호를 따라 **뒤집혀야** 한다 — 한 방향만
    # 밟으면 좌우를 맞바꾼 구현이 그대로 통과한다
    assert any(tl > tr for *_, tl, tr in ref) and any(tl < tr for *_, tl, tr in ref), (
        "배분이 한 방향으로만 났다 — 좌우 맞바꿈을 못 잡는 격자다")


def test_mixer_harness_argument_order_matches_the_generated_header():
    """하네스가 넘기는 순서 = 생성 헤더가 선언한 순서.

    전부 double이라 순서가 어긋나도 **컴파일이 통과한다**. 실제로 어긋났다: 제어권한
    배분으로 축 선언이 롤→피치가 되면서 fcl_mix_step의 인자 순서도 뒤바뀌었는데,
    하네스는 옛 순서로 넘겨 δe와 δa를 맞바꾼 채 대조하고 있었다(패리티가 잡았다).
    다음엔 이 테스트가 먼저 잡는다 — 컴파일러도 패리티도 아닌 **이름**이 근거다.
    """
    hdr = (GEN_DIR / "fcl_mix.h").read_text(encoding="utf-8")
    sig = hdr[hdr.index("void fcl_mix_step"):hdr.index(");", hdr.index("void fcl_mix_step"))]
    # ap_spd_sat_y(집합 스로틀)도 _sat_y로 끝난다 — SCAS 축만 고른다
    axes = [a.split()[-1] for a in sig.split(",") if "scas_" in a and a.strip().endswith("_sat_y")]
    harness = (GEN_DIR.parent / "tests" / "harness.c").read_text(encoding="utf-8")
    line = next(ln for ln in harness.splitlines() if "fcl_mix_step(&prm" in ln)
    order = [a.strip() for a in line[line.index("(") + 1:].split(",")][2:6]
    want = {"scas_pitch_sat_y": "de", "scas_roll_sat_y": "da", "scas_yaw_sat_y": "dr"}
    assert order[0] == "thr", f"첫 인자는 집합 스로틀이어야 한다: {order}"
    assert [want[a] for a in axes] == order[1:], (
        f"헤더 순서 {axes} 인데 하네스는 {order[1:]} — δe·δa가 뒤바뀐 채 대조된다")


@needs_cc
def test_generated_mixer_matches_ir_with_diff_thrust(tmp_path):
    """차동추력을 켠 채 생성 C ↔ 설계가 비트 일치 — 단발 형상이 가리는 경로."""
    exe = _build("fcl", "HARNESS_FCL_MIX", tmp_path)
    ref, stdin = _mixer_reference()
    run = subprocess.run([str(exe)], input=stdin, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    got = [tuple(float(x) for x in line.split()) for line in run.stdout.split("\n") if line]
    assert len(got) == len(ref), f"출력 줄 수 불일치: {len(got)} vs {len(ref)}"
    names = ("elevon_l", "elevon_r", "rudder", "throttle_l", "throttle_r")
    for i, name in enumerate(names):
        diff = _first_diff([r[i] for r in ref], [g[i] for g in got], name)
        assert diff is None, f"믹서 차동추력 경로가 어긋남 — {diff}"


# ── 산출물 관리 ───────────────────────────────────────────────────────────


def test_committed_artifacts_match_generator():
    """커밋된 gen/이 즉석 생성본과 동일 — 산출물과 생성기가 어긋난 채 배포되지 않게.

    생성은 결정적(시각 미포함)이므로 차이가 나면 곧 실제 설계 변경이다.
    """
    for name, text in sorted(build().items()):
        path = GEN_DIR / name
        assert path.exists(), f"{name} 미커밋 — `python flight/generate.py` 실행 필요"
        assert path.read_text(encoding="utf-8") == text, (
            f"{name}이 생성기 출력과 다름 — 손으로 고쳤거나 재생성이 필요하다"
        )


def test_generation_is_deterministic():
    assert build() == build()


# ── 기능축 분할 (증분 D′) ─────────────────────────────────────────────────
#
# 비트 일치는 위에서 이미 봤다. 여기서 보는 것은 **분할이 실제로 됐는가**다 —
# FCC팀이 서브시스템 하나만 떼어 읽고 검증할 수 있어야 분할한 값을 한다.

GROUPS = ("sched", "ap", "lim", "scas", "mix")


def _gen(name):
    return (GEN_DIR / name).read_text(encoding="utf-8")


def test_진입점에는_조립부만_남는다():
    # 상태 구조체는 쪼개지 않으므로 fcl_reset은 그대로 여기 남는다 — step 본문만 본다
    step = _gen("fcl.c").split("void fcl_step(", 1)[1]
    for group in GROUPS:
        assert f"fcl_{group}_step(" in step, f"{group} 호출이 없다"
    for token in ("claw_lookup1d", "claw_clip", "claw_wrap_pi", "prm->", "sta->ap_"):
        assert token not in step, f"조립부에 블록 계산이 남았다: {token}"
    assert len(_gen("fcl.c").splitlines()) < 120, "조립부가 다시 부풀었다"


def test_신호_이름이_파티션_경계를_넘어_유지된다():
    """`rtb_Sum_p_idx_1` 류를 만들지 않는다는 요구가 경계에서도 지켜지는지."""
    top, scas = _gen("fcl.c"), _gen("fcl_scas.c")
    for signal in ("ap_hdg_sat_y", "lim_theta_lim_y", "sched_pitch_kp_y"):
        assert signal in top, f"{signal}이 조립부에 없다"
        assert signal in scas, f"{signal}이 SCAS 인자에서 이름을 잃었다"


def test_공용_헬퍼는_한_벌만_있다():
    """산출물마다 static으로 복제되면 같은 코드를 산출물 수만큼 검증하게 된다."""
    assert "double claw_clip(" in _gen("claw_rt.c")
    for name in ("fcl", "fcl_ap", "fcl_lim", "fcl_scas", "fcl_sched", "fcl_mix", "scas_yaw"):
        assert "double claw_clip(" not in _gen(f"{name}.c"), f"{name}.c에 헬퍼가 복제됐다"


def test_파티션은_types_h만_의존한다():
    """파티션 헤더가 진입점을 물면 포함 관계가 순환처럼 읽힌다 — DAG로 남긴다."""
    for group in GROUPS:
        text = _gen(f"fcl_{group}.h")
        assert '#include "fcl_types.h"' in text
        assert '#include "fcl.h"' not in text


def test_분할해도_지문은_그대로다():
    """지문은 형상의 신원이다 — 파일 배치가 아니라 제어법칙이 바뀔 때만 움직인다."""
    fps = set()
    for name in ("fcl.h", "fcl_types.h", "fcl_data.c", *(f"fcl_{g}.h" for g in GROUPS)):
        line = next(ln for ln in _gen(name).splitlines() if "지문" in ln)
        fps.add(line.split(":")[1].strip())
    # 지문이 움직이는 것이 곧 설계 변경이다. 이번 갱신은 **안티와인드업 판정을 축
    # 출력 기준으로 바꾼 구조 변경**이다 — 감쇠항이 PID의 둘째 입력이 되어 그래프
    # 위상이 달라졌다(graphs.py scas_axis_nodes). 출력식은 그대로라 제어법칙 자체는
    # 안 바뀌지만, 적분 궤적이 달라지므로 지문은 정직하게 움직여야 한다.
    # (앞선 갱신은 차동추력 계수 0 — 단발 전환. 프로펠러 추력 모델은 순수 플랜트
    # 변경이라 지문을 안 움직였다.)
    # 이번 갱신은 **엘레본 제어권한 배분**이다 — 선회 하중만큼 피치 몫을 먼저 떼고
    # 남은 것을 롤이 수요만큼 가져간다(graphs.py _roll_budget_nodes). 축 순서가
    # 롤→피치로 바뀌고 배분 노드 12개가 늘어 그래프 위상이 달라졌다.
    assert fps == {"3e032f9003b7cc9f"}, f"형상 지문이 움직였다: {fps}"
