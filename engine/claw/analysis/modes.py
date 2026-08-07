"""고유치·감쇠비·모드 자동 분류 (01 §4.2, MATLAB damp/eig 대체)."""

import numpy as np


def damp(A):
    """행렬 A → [{eig, wn, zeta}] (wn 내림차순). λ=0은 wn=0, zeta=0."""
    out = []
    for lam in np.linalg.eigvals(np.asarray(A, dtype=float)):
        wn = abs(lam)
        zeta = float(-lam.real / wn) if wn > 0 else 0.0
        out.append({"eig": complex(lam), "wn": float(wn), "zeta": zeta})
    return sorted(out, key=lambda m: -m["wn"])


def _pairs_and_reals(modes):
    pairs = [m for m in modes if m["eig"].imag > 1e-9]  # 켤레쌍 중 상반평면 대표만
    reals = [m for m in modes if abs(m["eig"].imag) <= 1e-9]
    return pairs, reals


def classify_lon(lon):
    """종축 4상태 → {short_period, phugoid} — 복소쌍 2개를 주파수로 구분 (01 §4.2)."""
    pairs, _ = _pairs_and_reals(damp(lon.A))
    if len(pairs) != 2:
        raise ValueError(f"종축 복소쌍 {len(pairs)}개 — 단주기/장주기 분류 불가 (실근 분리 상태)")
    return {"short_period": pairs[0], "phugoid": pairs[1]}


def classify_lat(lat):
    """횡축 4상태 → {dutch_roll(복소쌍), roll(빠른 실근), spiral(느린 실근)}."""
    pairs, reals = _pairs_and_reals(damp(lat.A))
    if len(pairs) != 1 or len(reals) != 2:
        raise ValueError(f"횡축 모드 구조 비정형: 복소쌍 {len(pairs)}, 실근 {len(reals)}")
    reals = sorted(reals, key=lambda m: -abs(m["eig"].real))
    return {"dutch_roll": pairs[0], "roll": reals[0], "spiral": reals[1]}
