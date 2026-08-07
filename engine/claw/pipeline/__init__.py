"""M15 pipeline — 설계 산출물 의존 DAG, 증분 재계산, 정량 Δ리포트 (구현 문서 §2.4).

구현됨: Pipeline(부분집합 지문 기반 선택적 무효화·캐시) / subset_fingerprint / delta_report.
후속: 파라미터 스윕/민감도 스터디(배치 실행 재사용), 입력 데이터 파일 해시 계보 결합(02 §2.4).
"""

from claw.pipeline.pipeline import Pipeline, delta_report, subset_fingerprint

__all__ = ["Pipeline", "delta_report", "subset_fingerprint"]
