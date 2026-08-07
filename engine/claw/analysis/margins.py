"""이득·위상여유 (python-control 래퍼, MATLAB margin 대체) + 마진 맵 (01 §4.2 [확정]).

마진 맵의 격자 시각화는 M14(web) 소관 — 여기서는 케이스별 수치 산출까지.
"""

import control
import numpy as np


def make_siso(lm, x_out, u_in):
    """LinearModel → 단일 입력(u_in) → 단일 상태(x_out) 상태공간 모델."""
    xi = lm.x_names.index(x_out)
    ui = lm.u_names.index(u_in)
    n = lm.A.shape[0]
    C = np.zeros((1, n))
    C[0, xi] = 1.0
    return control.ss(lm.A, lm.B[:, [ui]], C, [[0.0]])


def loop_margins(loop):
    """개루프 → {gm_db, pm_deg, wcg, wcp}. 이득여유 무한대는 inf, 해당 교차 없으면 nan."""
    gm, pm, wcg, wcp = control.margin(loop)
    if np.isnan(gm):
        gm_db = np.nan  # 판정 불가를 무한 여유로 오인하지 않도록 nan 유지
    elif np.isinf(gm):
        gm_db = np.inf
    else:
        gm_db = 20.0 * np.log10(gm) if gm > 0 else -np.inf
    return {"gm_db": float(gm_db), "pm_deg": float(pm), "wcg": float(wcg), "wcp": float(wcp)}


def margin_map(loops):
    """{케이스 이름: 개루프} → {케이스 이름: 마진 dict} — 마진 맵의 수치 계층."""
    return {name: loop_margins(sys) for name, sys in loops.items()}
