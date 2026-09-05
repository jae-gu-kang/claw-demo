"""analysis.schedule 검증 — 스케줄 매끄러움(항목 11)의 순수 계산.

상대 점프가 판정량인 이유(단위가 다른 테이블을 한 문턱에 세운다)와, 잴 수 없는
자리를 0으로 위장하지 않는다는 규약(격자점 1개 축·전부 0인 자리)을 핀한다.
"""

from claw.analysis.schedule import mach_midpoints, table_smoothness
from claw.tables import Table


def _t(name, mach, data):
    return Table({"mach": mach}, data, name=name)


def test_상대_점프_최대와_그_자리를_찾는다():
    t = _t("pitch.kp", [0.3, 0.5, 0.7], [1.0, 1.5, 0.8])
    s = table_smoothness({"pitch.kp": t})["pitch.kp"]
    # 1.5→0.8: |Δ|=0.7, 큰 쪽 1.5 기준 0.4667 — 1.0→1.5(0.3333)보다 크다
    assert abs(s["max_rel_step"] - 0.7 / 1.5) < 1e-12
    assert s["per_axis"]["mach"]["at"] == [0.5, 0.7]


def test_격자점_1개_축은_항목을_내지_않는다():
    # 0을 내면 "잴 것이 없다"가 "완벽히 매끄럽다"로 위장된다.
    # Table 생성자가 크기 1 축을 거부하므로(테이블 계약) 같은 인터페이스의 스텁으로
    # 방어 분기를 직접 찌른다 — 계약이 느슨해지는 날 이 분기가 최후의 선이다
    class OnePoint:
        axis_names = ("mach",)
        axes = ([0.5],)
        data = [2.0]

    s = table_smoothness({"one": OnePoint()})["one"]
    assert s["per_axis"] == {}
    assert s["max_rel_step"] is None


def test_꺼진_자리의_미세값은_급변이_아니다():
    s = table_smoothness({"z": _t("z", [0.3, 0.5], [0.0, 1e-12])})["z"]
    assert s["max_rel_step"] == 0.0


def test_2차원_테이블은_전_조합의_최대를_취한다():
    t = Table({"mach": [0.3, 0.5], "alt": [0.0, 1000.0]},
              [[1.0, 1.0], [1.0, 3.0]], name="kp2d")
    s = table_smoothness({"kp2d": t})["kp2d"]
    # mach 방향 alt=1000 열: 1.0→3.0 → 2/3
    assert abs(s["per_axis"]["mach"]["max_rel_step"] - 2.0 / 3.0) < 1e-12
    assert abs(s["per_axis"]["alt"]["max_rel_step"] - 2.0 / 3.0) < 1e-12


def test_mach_midpoints는_합집합_중간값을_창_안에서_낸다():
    tables = {
        "a": _t("a", [0.3, 0.5, 0.7], [1, 1, 1]),
        "b": _t("b", [0.5, 0.9], [1, 1]),
        # mach 축이 없는 테이블은 기여하지 않는다
        "c": Table({"alt": [0.0, 1000.0]}, [1.0, 1.0], name="c"),
    }
    mids = mach_midpoints(tables)
    assert mids == [0.4, 0.6, 0.8]
    assert mach_midpoints(tables, lo=0.45, hi=0.75) == [0.6]
