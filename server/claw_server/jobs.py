"""M13 작업 실행기 — 스레드 기반 배치 작업 + 진행률 + 협조적 취소.

단독 사용자·로컬 서버(02 §4) 전제 — 작업당 데몬 스레드, 큐·워커 풀 없음.
엔진 on_progress 콜백(trim_batch·Simulator.run)에 Job.report를 물리면
진행률 갱신과 취소 신호 전달이 한 경로로 처리된다.
"""

import threading
import time
import traceback
import uuid

TERMINAL_STATES = ("done", "error", "cancelled")


class Job:
    """단일 작업 — 상태 전이(queued→running→종단)는 실행 스레드가 단독 수행."""

    def __init__(self, job_id: str, kind: str):
        self.id = job_id
        self.kind = kind
        self.status = "queued"
        self.done = 0
        self.total = 0
        self.message = ""
        self.error = None
        self.result_id = None
        self.created = time.time()
        self.started = None
        self.finished = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._thread = None

    def report(self, done, total, message: str = "") -> bool:
        """엔진 on_progress 어댑터 — truthy 반환 = 취소 요청됨 (협조적 취소)."""
        with self._lock:
            self.done, self.total = int(done), int(total)
            if message:
                self.message = message
        return self._cancel.is_set()

    def request_cancel(self) -> None:
        self._cancel.set()

    @property
    def cancel_requested(self) -> bool:
        return self._cancel.is_set()

    def wait(self, timeout=None) -> bool:
        """실행 스레드 종료 대기 → 종단 상태 도달 여부 (테스트·동기 호출용)."""
        if self._thread is not None:
            self._thread.join(timeout)
        return self.status in TERMINAL_STATES

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "id": self.id,
                "kind": self.kind,
                "status": self.status,
                "progress": self.done / self.total if self.total else 0.0,
                "done": self.done,
                "total": self.total,
                "message": self.message,
                "error": self.error,
                "result_id": self.result_id,
                "created": self.created,
                "started": self.started,
                "finished": self.finished,
            }


class JobManager:
    def __init__(self):
        self._jobs = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, fn) -> Job:
        """fn(job)을 데몬 스레드로 실행 — 예외는 status='error'로 포착.

        fn이 취소 신호를 감지하고 정상 반환하면(부분 결과 저장 포함)
        status='cancelled'로 종결된다.
        """
        job = Job(uuid.uuid4().hex[:12], kind)
        with self._lock:
            self._jobs[job.id] = job
        t = threading.Thread(
            target=self._run, args=(job, fn), name=f"claw-job-{job.id}", daemon=True
        )
        job._thread = t
        t.start()
        return job

    def _run(self, job: Job, fn) -> None:
        # 종단 상태는 항상 마지막에 기록 — 폴링 스냅샷이 status=error인데
        # error 본문/finished가 비어 보이는 순서 역전 방지 (리뷰 S1)
        job.started = time.time()
        if job.cancel_requested:  # 실행 전 취소 fast-path — 계산 자체를 생략
            job.finished = time.time()
            job.status = "cancelled"
            return
        job.status = "running"
        try:
            fn(job)
        except Exception:
            job.error = traceback.format_exc(limit=8)
            job.finished = time.time()
            job.status = "error"
        else:
            # 완주(done==total) 직후 도착한 취소는 결과를 강등하지 않음 (리뷰 S3)
            completed = job.total > 0 and job.done == job.total
            job.finished = time.time()
            job.status = (
                "cancelled" if (job.cancel_requested and not completed) else "done"
            )

    def get(self, job_id: str):
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created)
