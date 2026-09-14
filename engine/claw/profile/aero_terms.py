"""공력 계수 항 합산 — 프로파일 문서의 계수 항 목록 → AeroModel.coef_fn (02 §5.6).

계수 = Σ 항, 항 = k × 입력₁ × 입력₂ × …. 동미계수(qhat·phat·rhat)와 타면 증분, 상수항이 모두
이 꼴이다. 형식은 둘:
- "lift_drag": CL·CD(입력에 CL 사용 가능)를 풍축에서 동체축으로 돌린다
  (plant/aero.wind_to_body_coeffs). CY는 그 변환이 준 −CD·sinβ에 항을 더한다
- "body": CX·CY·CZ·Cl·Cm·Cn을 직접 합산한다

**연산 순서가 계약이다.** 예제 기체(구 데모)의 산출을 비트 단위로 보존하기 위해:
- 합은 0.0이 아니라 **첫 항에서** 시작해 왼쪽부터 접는다 (0.0 + (−0.0) = +0.0이 된다)
- 곱은 k부터 입력 순서대로 곱한다 — (k·x₁)·x₂
- 섭동 태그 항은 k를 먼저 (k·(1+d))로 만든다
- 타면 입력이 없으면 0.0으로 읽되 **항을 건너뛰지 않는다** (건너뛰면 부호 있는 0이 달라진다)

k는 수치 또는 **표**다(공력 DB — 축은 schema.TABLE_AXES). 표 항의 값은 T(조건) × 입력들이고, 섭동 태그면
(T·(1+d))·입력 순서다(수치 k와 같은 꼴). 표는 스칼라 보간(tables/scalar.py)으로 부른다 — Table.interp와
산술이 같고 점 하나 질의에서 훨씬 빠르다. 고도 축은 계수 입력 `alt`로 들어온다(AeroModel.forces의 alt).
"""

from claw.plant.aero import wind_to_body_coeffs
from claw.tables.scalar import ScalarTable
from claw.tables.table import Table

CONTROL_INPUTS = ("de", "da", "dr")


class _TableK:
    """표로 준 k — 계수 입력에서 축 좌표를 읽어 값을 낸다."""

    __slots__ = ("table", "scale", "names")

    def __init__(self, doc_table, scale, label):
        self.table = ScalarTable(Table(doc_table["axes"], doc_table["data"], name=label,
                                       extrapolate=doc_table["extrapolate"]))
        self.scale = scale
        self.names = self.table.axis_names

    def __call__(self, inp):
        vals = []
        for name in self.names:
            if name in CONTROL_INPUTS:
                vals.append(inp.get(name, 0.0))  # 수치 항과 같은 규칙 — 없는 타면은 0.0
                continue
            try:
                vals.append(inp[name])
            except KeyError:
                raise ValueError(f"공력 표 {self.table.name}가 축 {name!r}을 쓰는데 계수 입력에 없다"
                                 + (" — 고도는 AeroModel.forces(alt=)로 넘겨야 한다" if name == "alt" else "")) from None
        v = self.table.at_values(vals)
        return v if self.scale is None else v * self.scale


def _compile(terms, dispersion, coef="coef"):
    out = []
    for i, t in enumerate(terms):
        k = t["k"]
        scale = None if t["dispersion"] is None else 1.0 + getattr(dispersion, t["dispersion"])
        if isinstance(k, dict):
            k = _TableK(k["table"], scale, f"{coef}[{i}]")
        elif scale is not None:
            k = k * scale
        out.append((k, tuple(t["inputs"])))
    return tuple(out)


def _value(name, inp, cl):
    if name == "CL":
        return cl
    if name in CONTROL_INPUTS:
        return inp.get(name, 0.0)
    return inp[name]


def _sum(terms, inp, start=None, cl=None):
    acc = start
    for k, names in terms:
        v = k(inp) if k.__class__ is _TableK else k
        for name in names:
            v = v * _value(name, inp, cl)
        acc = v if acc is None else acc + v
    return 0.0 if acc is None else acc


def make_coef_fn(aero_doc: dict, dispersion):
    """검증된 aero 섹션 + DispersionSet → coef_fn(inputs) → {CX, CY, CZ, Cl, Cm, Cn}."""
    c = {name: _compile(terms, dispersion, name) for name, terms in aero_doc["coefficients"].items()}
    if aero_doc["form"] == "lift_drag":
        CL, CD, CY, Cl, Cm, Cn = (c[n] for n in ("CL", "CD", "CY", "Cl", "Cm", "Cn"))

        def coef(inp):
            cl = _sum(CL, inp)
            cd = _sum(CD, inp, cl=cl)
            cx, cy_d, cz = wind_to_body_coeffs(cl, cd, inp["alpha"], inp["beta"])
            return {
                "CX": cx,
                "CY": _sum(CY, inp, start=cy_d),
                "CZ": cz,
                "Cl": _sum(Cl, inp),
                "Cm": _sum(Cm, inp),
                "Cn": _sum(Cn, inp),
            }
    else:
        CX, CY, CZ, Cl, Cm, Cn = (c[n] for n in ("CX", "CY", "CZ", "Cl", "Cm", "Cn"))

        def coef(inp):
            return {
                "CX": _sum(CX, inp), "CY": _sum(CY, inp), "CZ": _sum(CZ, inp),
                "Cl": _sum(Cl, inp), "Cm": _sum(Cm, inp), "Cn": _sum(Cn, inp),
            }
    return coef


def dispersion_axes(aero_doc: dict) -> tuple:
    """이 공력 문서가 흔들 수 있는 섭동 축 — 질량은 항상, Cmα·Cmq는 태그 항이 있을 때만."""
    tags = {t["dispersion"] for terms in aero_doc["coefficients"].values() for t in terms}
    return tuple(ax for ax in ("mass", "cmalpha", "cmq") if ax == "mass" or ax in tags)
