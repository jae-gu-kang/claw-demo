"""M9 trim — 구속조건 트림(scipy SLSQP) + 수치섭동 선형화 (도메인 문서 §4).

구현됨: trim_level(수평정상비행) / trim_batch(인접 시드·연속성 판정).
후속: 정상선회·상승 트림 [확정 추후], linearize(수치섭동 → LinearModel, 증분 J).
"""

from claw.trim.trim import trim_batch, trim_level

__all__ = ["trim_level", "trim_batch"]
