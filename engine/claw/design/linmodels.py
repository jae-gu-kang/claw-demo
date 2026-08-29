"""선형모델 캐시·직렬화 + 인접 운영점 간 플랜트 거리 지표.

LinearModel(A/B)은 지금까지 프로세스 내 중간물이었다 — 자동 설계 루프는
이터레이션마다 같은 앵커를 다시 보므로 (case_name, params_fingerprint) 키로
캐시하고, 세션 저장·재개를 위해 A(12×12)/B(12×4)를 JSON으로 왕복시킨다
(openloop.py 머리말의 "재선형화하지 않는다" 원칙의 확장).

model_distance()는 **adaptive refinement(refine)와 plant 급변 분류(classify)가
같은 수치를 공유**하는 거리 정본이다 — 기준이 두 군데 적히면 "리파인은 통과했는데
분류기는 급변이라 한다"는 모순이 생긴다. 전 성분 무차원 상대량이고 d_total은
성분 최대값이다 (한 성분이라도 크게 변하면 플랜트가 변한 것).
"""

import numpy as np

from claw.analysis.modes import classify_lat, classify_lon, damp
from claw.common.contracts import LinearModel, TrimCase
from claw.plant.aircraft import XE_NAMES
from claw.trim import U_NAMES, linearize, split_axes
from claw.trim.trim import CONTINUITY_STEP

_EPS = 1e-9


class LinearModelSet:
    """(케이스 이름, 지문) → 전체축 LinearModel 캐시. miss 시 linearize() 1회."""

    def __init__(self):
        self._models: dict[tuple, LinearModel] = {}

    def __len__(self):
        return len(self._models)

    def has(self, case_name: str, fingerprint: str = "") -> bool:
        return (case_name, fingerprint) in self._models

    def get(self, aircraft, tr) -> LinearModel:
        """TrimResult → 전체축 선형모델 (캐시). 미수렴 트림은 선형화 대상이 아니다."""
        if not tr.converged:
            raise ValueError(f"미수렴 트림은 선형화할 수 없다: {tr.case.name}")
        key = (tr.case.name, tr.params_fingerprint)
        if key not in self._models:
            self._models[key] = linearize(aircraft, tr)
        return self._models[key]

    def peek(self, case_name: str, fingerprint: str = "") -> LinearModel | None:
        return self._models.get((case_name, fingerprint))

    def to_dict(self) -> dict:
        entries = []
        for (name, fp), lm in self._models.items():
            entries.append({
                "name": name,
                "fingerprint": fp,
                "mach": lm.case.mach if lm.case else None,
                "alt": lm.case.alt if lm.case else None,
                "fuel": lm.case.fuel if lm.case else None,
                "A": lm.A.tolist(),
                "B": lm.B.tolist(),
            })
        return {"models": entries}

    @classmethod
    def from_dict(cls, d: dict) -> "LinearModelSet":
        out = cls()
        for e in d["models"]:
            case = None
            if e.get("mach") is not None:
                case = TrimCase(
                    name=e["name"], mach=float(e["mach"]), alt=float(e["alt"]),
                    fuel=float(e["fuel"]),
                )
            A = np.asarray(e["A"], dtype=float)
            B = np.asarray(e["B"], dtype=float)
            lm = LinearModel(
                A=A, B=B, C=np.eye(A.shape[0]), D=np.zeros(B.shape),
                x_names=XE_NAMES, u_names=U_NAMES, axis="full", dt=0.0,
                case=case, params_fingerprint=e.get("fingerprint", ""),
            )
            out._models[(e["name"], e.get("fingerprint", ""))] = lm
        return out


# ── 거리 지표 ────────────────────────────────────────────────────────────


def _trim_z(tr) -> np.ndarray:
    """트림해 [α, δe, thr] — trim_batch의 연속성 판정과 같은 추출."""
    return np.array([tr.state.euler()[1], tr.control.elevon[0], tr.control.throttle[0]])


def _rel_wn_zeta(mode_a: dict, mode_b: dict) -> float:
    wn = max(mode_a["wn"], mode_b["wn"], _EPS)
    return max(abs(mode_a["wn"] - mode_b["wn"]) / wn, abs(mode_a["zeta"] - mode_b["zeta"]))


def _eig_migration(A_a, A_b) -> float:
    """분류 실패 폴백 — 고유치 최근접 매칭 이동거리 / wn (실패를 데이터로).

    a의 각 고유치를 b의 미사용 최근접 고유치와 짝지어(탐욕, wn 내림차순 — 지배
    모드 먼저) 상대 이동거리의 최대를 낸다.
    """
    modes_a = damp(A_a)
    eigs_b = [m["eig"] for m in damp(A_b)]
    worst = 0.0
    for m in modes_a:
        dists = [abs(m["eig"] - eb) for eb in eigs_b]
        j = int(np.argmin(dists))
        wn = max(m["wn"], abs(eigs_b[j]), _EPS)
        worst = max(worst, dists[j] / wn)
        eigs_b.pop(j)
    return worst


def _mode_distance(lon_a, lon_b, lat_a, lat_b) -> tuple:
    """제어 관련 모드(단주기·더치롤) 이동 — 비정형 구조는 고유치 이동 폴백."""
    detail = {}
    try:
        d_lon = _rel_wn_zeta(
            classify_lon(lon_a)["short_period"], classify_lon(lon_b)["short_period"]
        )
        detail["lon"] = {"kind": "short_period", "d": d_lon}
    except ValueError as e:
        d_lon = _eig_migration(lon_a.A, lon_b.A)
        detail["lon"] = {"kind": "eig_migration", "d": d_lon, "note": str(e)}
    try:
        d_lat = _rel_wn_zeta(
            classify_lat(lat_a)["dutch_roll"], classify_lat(lat_b)["dutch_roll"]
        )
        detail["lat"] = {"kind": "dutch_roll", "d": d_lat}
    except ValueError as e:
        d_lat = _eig_migration(lat_a.A, lat_b.A)
        detail["lat"] = {"kind": "eig_migration", "d": d_lat, "note": str(e)}
    return max(d_lon, d_lat), detail


# 조종효과 핵심 성분 — (부분모델 축, 상태(가속도 행), 입력). 게인 스케줄 필요성의
# 직접 지표다: 동압 역비 스케일(fcl/demo.py f∝1/M²)의 원인이 바로 B의 이 성분들이다.
_CTRL_ENTRIES = (("lon", "q", "de"), ("lat", "p", "da"), ("lat", "r", "dr"))


def _ctrl_distance(lon_a, lon_b, lat_a, lat_b) -> tuple:
    axes = {"lon": (lon_a, lon_b), "lat": (lat_a, lat_b)}
    worst = 0.0
    detail = {}
    for axis, x_out, u_in in _CTRL_ENTRIES:
        ma, mb = axes[axis]
        i, j = ma.x_names.index(x_out), ma.u_names.index(u_in)
        ba, bb = float(ma.B[i, j]), float(mb.B[i, j])
        d = abs(ba - bb) / max(abs(ba), abs(bb), _EPS)
        detail[f"{x_out}dot/{u_in}"] = {"a": ba, "b": bb, "d": d}
        worst = max(worst, d)
    return worst, detail


def model_distance(lm_a, lm_b, tr_a, tr_b) -> dict:
    """인접 운영점 간 플랜트 변화의 무차원 거리 — refine·classify 공용 정본.

    - d_trim: 트림해 기울기 |Δ[α, δe, thr]| / CONTINUITY_STEP 성분 최대
      (trim.py 상수 재사용 — 축간 정규화를 재발명하지 않는다)
    - d_mode: 단주기(lon)·더치롤(lat)의 max(|Δwn|/wn, |Δζ|), 분류 실패 시
      고유치 최근접 매칭 이동거리 폴백
    - d_ctrl: B행렬 핵심 성분(q̇/δe, ṗ/δa, ṙ/δr) 상대 변화
    - d_total = max(성분) — 한 성분이라도 크면 플랜트가 변한 것
    """
    d_trim = float(np.max(np.abs(_trim_z(tr_a) - _trim_z(tr_b)) / CONTINUITY_STEP))
    lon_a, lat_a = split_axes(lm_a)
    lon_b, lat_b = split_axes(lm_b)
    d_mode, mode_detail = _mode_distance(lon_a, lon_b, lat_a, lat_b)
    d_ctrl, ctrl_detail = _ctrl_distance(lon_a, lon_b, lat_a, lat_b)
    return {
        "d_trim": d_trim,
        "d_mode": float(d_mode),
        "d_ctrl": float(d_ctrl),
        "d_total": float(max(d_trim, d_mode, d_ctrl)),
        "detail": {"mode": mode_detail, "ctrl": ctrl_detail},
    }
