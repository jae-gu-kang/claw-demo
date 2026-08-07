"""M7 fcl — SCAS·오토파일럿·게인 스케줄·제어면 혼합·α 리미터 (도메인 문서 §3).

법칙은 NavOutput만 소비한다 — plant 참값 직접 참조 금지 (03 §4 핵심 계약).
구현됨: airdata(NavOutput→V·α·β), SCAS(피치/롤 PI+레이트, 요 −β+워시아웃 댐퍼).
"""

from claw.fcl.airdata import airdata_from_nav, vel_b_from_nav
from claw.fcl.scas import Scas, ScasAxis

__all__ = ["airdata_from_nav", "vel_b_from_nav", "Scas", "ScasAxis"]
