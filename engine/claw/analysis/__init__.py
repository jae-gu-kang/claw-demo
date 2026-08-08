"""M10 analysis — 고유치·감쇠비·모드 분류, 이득/위상여유, 마진 맵 (도메인 문서 §4.2).

구현됨: damp / classify_lon(단주기·장주기) / classify_lat(더치롤·롤·나선) /
make_siso / loop_margins / margin_map (python-control 기반).
후속: **작동기·지연 포함 선형모델 마진** (01 §4.2 [기본값] — 현재는 플랜트 단독이라
낙관적, Padé 차수 등 [TBD] 백로그), 보드선도 데이터 API, 100 vs 50 Hz 이산화 영향 비교.
"""

from claw.analysis.envelope import vn_envelope, vn_stall_boundary
from claw.analysis.margins import loop_margins, make_siso, margin_map, pi_loop
from claw.analysis.modes import classify_lat, classify_lon, damp

__all__ = [
    "damp",
    "classify_lon",
    "classify_lat",
    "make_siso",
    "pi_loop",
    "loop_margins",
    "margin_map",
    "vn_envelope",
    "vn_stall_boundary",
]
