"""단위 변환 (conventions.md §3) — 내부 계산은 SI + rad.

경계(파일 입출력·UI)에서만 deg/ft/kt 허용. 인라인 환산계수 금지 — 반드시 이 모듈 사용.
"""

import math

DEG2RAD = math.pi / 180.0
RAD2DEG = 180.0 / math.pi
FT2M = 0.3048
M2FT = 1.0 / 0.3048
KT2MPS = 1852.0 / 3600.0
MPS2KT = 3600.0 / 1852.0
LB2KG = 0.45359237
KG2LB = 1.0 / 0.45359237
NM2M = 1852.0
M2NM = 1.0 / 1852.0


def deg2rad(x):
    return x * DEG2RAD


def rad2deg(x):
    return x * RAD2DEG


def ft2m(x):
    return x * FT2M


def m2ft(x):
    return x * M2FT


def kt2mps(x):
    return x * KT2MPS


def mps2kt(x):
    return x * MPS2KT


def lb2kg(x):
    return x * LB2KG


def kg2lb(x):
    return x * KG2LB


def hz2dt(f_hz):
    """주기 파라미터(Hz) → 이산 스텝 dt(s). 샘플레이트 파라미터화 원칙 (구현 문서 §2.3)."""
    if f_hz <= 0:
        raise ValueError(f"주기는 양수여야 함: {f_hz} Hz")
    return 1.0 / f_hz
