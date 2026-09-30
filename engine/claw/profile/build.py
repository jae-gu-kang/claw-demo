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
from claw.profile.fingerprint import plant_fingerprint, profile_fingerprint, trim_fingerprint
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
        # 트림 결과의 키 — 플랜트 + 풀이 설정(solver). 트림을 저장·재사용하는 쪽은 이것으로 대조한다(05 §11.8)
        self.trim_fingerprint = trim_fingerprint(self.doc)

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
                        trim_bounds=self.trim_bounds, plant_fingerprint=self.plant_fingerprint,
                        dispersed=d != DispersionSet())

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

    def theta_hi_table(self, alpha_margin: float | None = None) -> Table:
        """피치 명령 상한 표 θ_hi(M) = α_stall(M) − margin — 실속표 축 그대로 (01 §3.5, v1.11).

        margin을 안 주면 리미터와 같은 `law.alpha_margin`이다. 조립이 주입한 마진(영향성 스윕)을 그대로 넘겨야 표와
        리미터가 같은 보호경계를 말한다 — 표가 문서 값에 묶여 있으면 마진을 흔드는 스윕에서 둘이 갈린다.
        유도식은 analysis/envelope.py `pitch_limit_table`이 정본이다(fcl이 analysis를 import하지 않도록 여기서 부른다).
        """
        from claw.analysis.envelope import pitch_limit_table

        margin = self.doc["law"]["alpha_margin"] if alpha_margin is None else float(alpha_margin)
        return pitch_limit_table(self.stall_table(), alpha_margin=margin)

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
    def solver(self) -> dict:
        """해석 설정(v3 solver 절)의 사본 — {"trim_alpha_bounds": [lo, hi], "resid_tol"}. 결과·도출 기록이 이것을 싣는다."""
        s = self.doc["solver"]
        return {"trim_alpha_bounds": list(s["trim_alpha_bounds"]), "resid_tol": s["resid_tol"]}

    @property
    def trim_alpha_bounds(self) -> tuple:
        return tuple(self.doc["solver"]["trim_alpha_bounds"])

    @property
    def trim_margin(self) -> dict:
        """트림 여유 판정선 적용값 {sat_frac, thr_margin, alpha_margin} — 문서 criteria.trim_margin 위 도구 기본값(이관 12단계)."""
        from dataclasses import asdict

        return {k: float(v) for k, v in asdict(self.eval_criteria.trim_margin).items()}

    @property
    def trim_bounds(self) -> dict:
        """트림 풀이·여유 판정에 드는 값 한 벌 — Aircraft.trim_bounds가 싣는다(trim/trim.py가 이것만 읽는다).

        물리 한계와 판정선을 섞지 않는다: 탐색 α 범위·잔차 허용치는 해석 설정(solver), δe는 엘레본 한계(믹서와 같은 값 — 중복
        정의 금지), 실속 표는 α 판정의 기준(trim.trim_reserve), 판정선 sat_frac·thr_margin·alpha_margin은 적용 기준
        (criteria.trim_margin — 없으면 도구 기본값)."""
        return {"alpha": self.trim_alpha_bounds, "de": tuple(self.doc["surfaces"]["elevon"]),
                "resid_tol": float(self.doc["solver"]["resid_tol"]), **self.trim_margin, "stall": self.stall_table()}

    @property
    def loadings_declared(self) -> int:
        """문서가 적은 탑재 구성 수 — 계산은 기본 질량 모델이라 조건 판정이 mass_condition으로 그렇다고 말한다."""
        return len(self.doc["mass"]["loadings"] or ())

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

    @property
    def gain_tables_stale(self) -> bool:
        """확정 게인 표가 낡았는가 — 반영 뒤 문서(플랜트·설계·한계 등)가 바뀌었으면 낡았다.

        기준은 provenance의 basis_fingerprint(반영 시점의, 표 절을 뺀 적용 문서 지문 —
        fingerprint.gain_tables_basis_fingerprint)와 지금 문서의 같은 지문 대조다. 기록이 없으면(손으로
        넣은 표) 근거 없는 표라 낡은 것으로 취급한다 — δe_trim과 달리 표가 설계에서만 나오기 때문이다.
        지문 밖 변경(표시 모델·미션 템플릿·출처 기록)은 낡음이 아니다."""
        gt = self.doc["law"]["gain_tables"]
        if gt is None:
            return False
        prov = gt.get("provenance")
        if not isinstance(prov, dict):
            return True
        from claw.profile.fingerprint import gain_tables_basis_fingerprint

        return prov.get("basis_fingerprint") != gain_tables_basis_fingerprint(self.doc)

    def confirmed_gain_tables(self) -> dict | None:
        """문서의 확정 게인 표(자동 설계 반영, v2) — {자리: Table} 또는 None(없음).

        낡은 표로는 조립하지 않는다(alloc_trim_table의 δe_trim 낡음 거부와 같은 원칙) — 게인이
        틀리면 마진·비행성 판정 전부가 그 틀린 형상을 말하게 된다. 조립 우선순위는 assemble_law:
        주입(gain_tables 인자) > 이 표 > 규칙 스케줄(gain_tables())."""
        gt = self.doc["law"]["gain_tables"]
        if gt is None:
            return None
        if self.gain_tables_stale:
            raise ProfileError("/law/gain_tables",
                               "확정 게인 표가 낡았다 — 반영한 뒤 문서(플랜트·설계·한계·풀이 설정 등)가 바뀌었거나,"
                               " 기준 지문 기록이 없거나, 문서를 바꾸는 형상 변형 위이거나(표는 기본 문서에서"
                               " 확정된 것이라 그 변형에서는 쓸 수 없다), 스키마 올림(v2 → v3)에서 v2 도장을 증명하지"
                               " 못해 다시 찍지 않은 표다. 자동 설계를 다시 돌려 반영하거나 표를 지운다")
        return {name: _mach_table(t, name) for name, t in gt["tables"].items()}

    @property
    def de_trim_stale(self) -> bool:
        """도출한 δe_trim 표가 이 플랜트를 덮지 않는가 — 도출이 요구를 잰 플랜트 지문 목록(기본 문서 + 그때의 형상
        변형들)에 지금 플랜트가 없으면 낡았다. 기본 문서 지문 하나만 대조하면 플랜트를 바꾸는 형상 변형이 전부
        막힌다(무게가 다른 변형은 1g 요구도 다르므로 도출은 변형까지 잰다).

        손으로 넣은 표(explicit)는 대조할 기록이 없어 낡았다고 하지 않는다."""
        alloc = self.doc["law"]["alloc"]
        if alloc is None or alloc["de_trim"] is None or alloc["de_trim"]["source"] != "derived":
            return False
        prov = alloc["de_trim"]["provenance"]
        if not isinstance(prov, dict):
            return True
        fps = prov.get("plant_fingerprints")
        if not isinstance(fps, list):
            fps = [prov.get("plant_fingerprint")]
        if self.plant_fingerprint not in fps:
            return True
        # 트림 설정이 바뀌어도 낡았다(05 §11.8 「트림 설정 → 결과 낡음」) — 도출이 잰 풀이 설정 기록(v3)과 대조한다. 기록이
        # 없는 옛 도출은 어느 설정으로 풀었는지 모르므로 낡은 것으로 본다(v2 도출은 플랜트 지문부터 이미 다르다)
        solvers = prov.get("solvers")
        if isinstance(solvers, list) and len(solvers) == len(fps):
            return not any(fp == self.plant_fingerprint and sv == self.solver for fp, sv in zip(fps, solvers))
        return prov.get("solver") != self.solver

    def alloc_trim_table(self) -> Table | None:
        alloc = self.doc["law"]["alloc"]
        if alloc is None or alloc["de_trim"] is None:
            return None
        if self.de_trim_stale:
            # 낡은 표로 조립하지 않는다 — 1g 몫이 틀리면 선회에서 롤 권한을 과하게 묶거나 피치 몫이 모자란다
            raise ProfileError("/law/alloc/de_trim",
                               "도출한 δe_trim 표가 낡았다 — 도출한 뒤 플랜트(공력·질량·추진 등)나 트림 풀이 설정"
                               "(solver)이 바뀌었거나, 풀이 설정 기록이 없는 옛 도출이거나, 스키마 올림(v2 → v3)에서"
                               " v2 도장을 증명하지 못해 다시 찍지 않은 표다(올림 알림이 까닭을 말한다). 표를 다시 도출한다")
        return _mach_table(alloc["de_trim"]["table"], "de_trim")

    @property
    def alloc_resv_frac(self) -> float | None:
        alloc = self.doc["law"]["alloc"]
        return None if alloc is None else alloc["resv_frac"]

    # ── 평가 기준 (기준 통합 ①) ─────────────────────────────────────────────
    @property
    def eval_criteria(self):
        """이 작업 단위의 적용 기준 한 벌 — /criteria(합격·권장선) + /tuning(목표·가중치), 없는 칸은 도구 기본값.
        형상 변형은 기준을 못 고치므로(schema.VARIANT_FORBIDDEN) 변형을 골라도 같은 기준이다."""
        from claw.pipeline.criteria import GainEvalCriteria

        return GainEvalCriteria.from_profile(self.doc)

    @property
    def criteria_source(self) -> str:
        """기준의 출처 — "profile"(문서가 한 칸이라도 적었다) | "default"(둘 다 없음 → 도구 기본값).
        기본값으로 대체한 것을 조용히 두지 않고 결과·화면이 말하게 한다."""
        written = [k for sec in ("criteria", "tuning") for grp in (self.doc.get(sec) or {}).values() for k in grp]
        return "profile" if written else "default"  # 빈 그룹({"margin": {}})은 적은 것이 없다


def build_profile(document: dict, variant: str | None = None, *, validated=False) -> BuiltProfile:
    """기체 문서(+형상 변형) → BuiltProfile. validated=False면 먼저 검증한다."""
    return BuiltProfile(document if validated else validate_document(document), variant)
