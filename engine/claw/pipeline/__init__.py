"""M15 pipeline — 설계 산출물 의존 DAG, 증분 재계산, 정량 Δ리포트 (구현 문서 §2.4).

구현됨: Pipeline(부분집합 지문 기반 선택적 무효화·캐시) / subset_fingerprint / delta_report.
영향성 3단(02 §2.4): influence(1단 구조 도달성) · openloop(2단 개루프 마진 Δ) ·
sweep(3단 폐루프 스윕 — 배치 실행 재사용) + metrics(지표 계산) · diagnose(진단 →
처방 — "얼마나" 전에 "무엇을"). 서버는 각 모듈을 직접 import한다(이 __init__은
DAG 삼인방만 공개 — 기존 소비자 계약 유지).
후속: 입력 데이터 파일 해시 계보 결합(02 §2.4).
"""

from claw.pipeline.pipeline import Pipeline, delta_report, subset_fingerprint

__all__ = ["Pipeline", "delta_report", "subset_fingerprint"]
