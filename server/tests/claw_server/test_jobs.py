"""JobManager 검증 — 수명주기·진행률, 협조적 취소, 예외 포착 (스레드 실행기)."""

import threading
import time

from claw_server.jobs import JobManager


def test_job_lifecycle_and_progress():
    mgr = JobManager()

    def work(job):
        for i in range(5):
            assert job.report(i + 1, 5, message=f"case{i}") is False

    job = mgr.submit("demo", work)
    assert job.wait(10.0)
    d = job.to_dict()
    assert d["status"] == "done"
    assert d["progress"] == 1.0 and d["done"] == 5 and d["total"] == 5
    assert d["message"] == "case4"
    assert job.finished >= job.started >= job.created
    assert mgr.get(job.id) is job
    assert [j.id for j in mgr.list()] == [job.id]
    assert mgr.get("no-such-job") is None


def test_job_cooperative_cancel():
    mgr = JobManager()
    started = threading.Event()
    stopped = []

    def work(job):
        started.set()
        n = 0
        while not job.report(n, 1000):
            n += 1
            time.sleep(0.002)
        stopped.append(n)  # 취소 신호를 보고 스스로 멈춤 (강제 종료 아님)

    job = mgr.submit("demo", work)
    assert started.wait(5.0)
    job.request_cancel()
    assert job.wait(10.0)
    assert job.status == "cancelled"
    assert stopped, "작업이 취소 신호를 감지하고 정상 반환해야 함"


def test_job_error_captured():
    def boom(job):
        raise RuntimeError("실패 데모")

    job = JobManager().submit("demo", boom)
    assert job.wait(10.0)
    assert job.status == "error"
    assert "실패 데모" in job.error
    assert job.to_dict()["error"] == job.error
