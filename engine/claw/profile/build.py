"""기체 문서 → 엔진 객체 (02 §5.6) — BuiltProfile.

검증된 문서(형상 변형 적용 뒤)를 받아 플랜트·표·한계·지상장치·법칙 데이터를 **요청할 때마다
새로** 만든다(Table·배열을 소비자끼리 공유하지 않는다 — 영향성 스케일이 새 Table을 만드는
관례와 같다). 값은 문서에만 있고 여기에는 산식과 조립 순서만 있다.
"""

import copy

import numpy as np

from claw.plant.aero import AeroModel
from claw.plant.aircraft import Aircraft
from claw.plant.dispersion import DispersionSet
from claw.plant.ground import LaunchRail, SkidGear
from claw.plant.mass import FuelMass
from claw.profile.aero_terms import dispersion_axes, make_coef_fn
from claw.profile.errors import ProfileError
from claw.profile.fingerprint import plant_fingerprint, profile_fingerprint
from claw.profile.schema import effective_document, validate_document
from claw.tables import Table


def _mach_table(doc_table, name):
    return Table({"mach": tuple(doc_table["axes"]["mach"])}, tuple(doc_table["data"]),
                 name=name, extrapolate=doc_table["extrapolate"])


class BuiltProfile:
    def __init__(self, document: dict, variant: str | None = None):
        self.variant = variant
        self.doc = effective_document(document, variant)
        self.id = self.doc["id"]
        self.name = self.doc["name"]
        self.is_example = self.doc["is_example"]
        self.fingerprint = profile_fingerprint(self.doc)
        self.plant_fingerprint = plant_fingerprint(self.doc)

    # ── 플랜트 ─────────────────────────────────────────────────────────────
    @property
    def dispersion_axes(self) -> tuple:
        return dispersion_axes(self.doc["aero"])

    def aircraft(self, ground=None, dispersion: DispersionSet | None = None) -> Aircraft:
        d = dispersion or DispersionSet()
        axes = self.dispersion_axes
        for ax in ("cmalpha", "cmq"):
            if getattr(d, ax) != 0.0 and ax not in axes:
                # 흔들 항이 없는데 흔든 척하면 "±20 % 통과"가 조용한 거짓 합격이 된다
                raise ProfileError("/aero/coefficients/Cm",
                                   f"섭동 축 {ax}에 태그된 공력 항이 없어 흔들 수 없음")
        g, m = self.doc["geometry"], self.doc["mass"]
        aero = AeroModel(S=g["S"], cbar=g["cbar"], b=g["b"],
                         coef_fn=make_coef_fn(self.doc["aero"], d))
        fuel_mass = FuelMass(
            m_empty=m["m_empty"] * (1.0 + d.mass),
            fuel_max=m["fuel_max"],
            J_empty=np.array(m["J_empty"]),
            J_full=np.array(m["J_full"]),
            cg_empty=np.array(m["cg_empty"]),
            cg_full=np.array(m["cg_full"]),
        )
        return Aircraft(fuel_mass, aero, self.engine(), ground=ground,
                        trim_bounds=self.trim_bounds, plant_fingerprint=self.plant_fingerprint)

    def engine(self):
        from claw.params.registry import REGISTRY

        p = self.doc["propulsion"]
        return REGISTRY.create("propulsion", p["type"], p["params"])

    def actuator_params(self) -> dict:
        return dict(self.doc["actuator"]["params"])

    def skid_gear(self) -> SkidGear | None:
        s = self.doc["ground"]["skid"]
        if s is None:
            return None
        return SkidGear(np.array(s["contacts"]), k=s["k"], c=s["c"], mu=s["mu"])

    def launch_rail(self) -> LaunchRail | None:
        r = self.doc["ground"]["rail"]
        if r is None:
            return None
        return LaunchRail(length=r["length"], elev_angle=r["elev_angle"],
                          exit_speed=r["exit_speed"],
                          origin_n=np.array([0.0, 0.0, -r["origin_height"]]))

    @property
    def rail_origin_height(self) -> float | None:
        r = self.doc["ground"]["rail"]
        return None if r is None else r["origin_height"]

    # ── 경계 데이터 ───────────────────────────────────────────────────────
    def stall_table(self) -> Table:
        return _mach_table(self.doc["stall"]["table"], "alpha_stall")

    @property
    def neg_alpha_ratio(self) -> float:
        return self.doc["stall"]["neg_alpha_ratio"]

    def db_ranges(self) -> dict:
        """없는 범위(null)는 키째 뺀다 — 소비자가 필요한 범위를 못 찾으면 거기서 말한다."""
        r = self.doc["aero"]["db_ranges"]
        return {k: tuple(r[k]) for k in ("alpha", "beta", "mach") if r[k] is not None}

    def structural_limits(self) -> dict:
        s = self.doc["structural"]
        return {k: s[k] for k in ("n_limit_pos", "n_limit_neg", "safety_factor",
                                  "mach_no", "mach_d", "n_x_launch")}

    @property
    def q_max(self) -> float | None:
        return self.doc["structural"]["q_max"]

    @property
    def operating(self) -> dict:
        return dict(self.doc["operating"])

    @property
    def trim_alpha_bounds(self) -> tuple:
        return tuple(self.doc["trim"]["alpha_bounds"])

    @property
    def trim_alpha_margin(self) -> float:
        return self.doc["trim"]["alpha_margin"]

    @property
    def trim_bounds(self) -> dict:
        """트림 탐색 범위 — α는 trim 섹션, δe는 엘레본 한계(믹서와 같은 값, 중복 정의 금지)."""
        return {"alpha": self.trim_alpha_bounds, "de": tuple(self.doc["surfaces"]["elevon"]),
                "alpha_margin": self.trim_alpha_margin}

    @property
    def surfaces(self) -> dict:
        s = self.doc["surfaces"]
        return {"layout": s["layout"], "elevon": tuple(s["elevon"]), "rudder": tuple(s["rudder"])}

    # ── 법칙 데이터 ───────────────────────────────────────────────────────
    @property
    def law(self) -> dict:
        """법칙 섹션의 **사본** — 고쳐도 이 조립 결과가 바뀌지 않는다."""
        return copy.deepcopy(self.doc["law"])

    def _design(self) -> dict:
        design = self.doc["law"]["design"]
        if design is None:
            raise ProfileError("/law/design", "게인 미설계 — 초기 게인 탐색 또는 자동 설계가 필요함")
        return design

    def scas_axis_params(self, axis: str) -> dict:
        """SCAS 축 kwargs — 설계 게인 + surfaces에서 온 출력 한계(피치·롤=엘레본, 요=러더)."""
        lo, hi = self.doc["surfaces"]["rudder" if axis == "yaw" else "elevon"]
        return {**self._design()["scas"][axis], "out_lo": lo, "out_hi": hi}

    def autopilot_params(self) -> dict:
        return dict(self._design()["autopilot"])

    @property
    def k_diff_thr(self) -> float:
        return self._design()["k_diff_thr"]

    def design_gains(self) -> dict:
        from claw.fcl.schedule import design_gains

        return design_gains({ax: self.scas_axis_params(ax) for ax in ("pitch", "roll", "yaw")},
                            self.autopilot_params())

    def rate_filters(self) -> dict:
        """레이트 경로 필터 {그룹: 스펙} — washout_tau 0은 "필터 없음"(fcl/graphs.py 관용)."""
        out = {}
        for group in ("pitch", "roll", "yaw"):
            tau = float(self._design()["scas"][group].get("washout_tau", 0.0))
            if tau > 0.0:
                out[group] = {"kind": "washout", "tau": tau}
        return out

    def mixer_params(self) -> dict:
        """믹서 kwargs — 타면 한계(surfaces)와 차동추력 설계값."""
        s = self.doc["surfaces"]
        return {"elevon_lo": s["elevon"][0], "elevon_hi": s["elevon"][1],
                "rudder_lo": s["rudder"][0], "rudder_hi": s["rudder"][1],
                "k_diff_thr": self.k_diff_thr}

    def cap_for(self, gain_name: str) -> float:
        caps = self.doc["law"]["schedule"]["caps"]
        return caps["by_group"].get(gain_name.split(".", 1)[0], caps["default"])

    def gain_tables(self, names=None) -> dict:
        """동압 역비 스케줄 표 — K(M) = K0·min((M_design/M)², 상한[축별])."""
        sched = self.doc["law"]["schedule"]
        if sched is None:
            raise ProfileError("/law/schedule", "게인 스케줄 없음")
        machs = np.asarray(sched["mach_grid"], dtype=float)
        ideal = (sched["m_design"] / machs) ** 2
        design = self.design_gains()
        wanted = tuple(sched["scheduled"]) if names is None else tuple(names)
        unknown = [n for n in wanted if n not in design]
        if unknown:
            raise ValueError(f"스케줄 불가 자리 {unknown} — 허용: {sorted(design)}")
        return {
            name: Table({"mach": machs}, design[name] * np.minimum(ideal, self.cap_for(name)),
                        name=name, extrapolate="clip")
            for name in wanted
        }

    def alloc_trim_table(self) -> Table | None:
        alloc = self.doc["law"]["alloc"]
        if alloc is None or alloc["de_trim"] is None:
            return None
        return _mach_table(alloc["de_trim"]["table"], "de_trim")

    @property
    def alloc_resv_frac(self) -> float | None:
        alloc = self.doc["law"]["alloc"]
        return None if alloc is None else alloc["resv_frac"]


def build_profile(document: dict, variant: str | None = None, *, validated=False) -> BuiltProfile:
    """기체 문서(+형상 변형) → BuiltProfile. validated=False면 먼저 검증한다."""
    return BuiltProfile(document if validated else validate_document(document), variant)
