"""models/blender_numpy.py 의 순수 부분 — 블렌더 없이 돈다.

실행: `pytest models`  (엔진·서버 스위트와 별개 — 이건 빌드 스크립트 유틸이다)
"""

import os
import sys

# **모듈 수준 import다.** `restore_numpy_modules`의 스냅샷이 비면 그 픽스처가 조용히
# 무력해지므로(독스트링 참조), 여기서 실물을 반드시 올려 둔다. `ensure_numpy`가 도는
# 환경인지 확인하는 뜻도 겸한다 — 이 파일의 테스트 하나는 그것을 전제한다.
import numpy  # noqa: F401
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from blender_numpy import (  # noqa: E402
    ENV_OVERRIDE, _purge_numpy, _root_cause, candidate_site_packages, ensure_numpy,
)


@pytest.fixture(autouse=True)
def restore_numpy_modules():
    """**numpy를 프로세스에 되돌려 놓는다.** 이 파일은 실패 경로를 재현하려고
    `sys.modules`에서 numpy 계열을 지우는데, `monkeypatch.setitem`은 최상위 `numpy`
    한 키만 복원한다. 하위 모듈은 사라진 채 남고, 다음에 누가 `import numpy.…`를 하면
    numpy 2.x가 재실행을 거부한다:

        ImportError: cannot load module more than once per process

    같은 프로세스에서 `pytest models server`를 돌리면 실제로 63개가 깨졌다(실측).
    리포 루트에서 `pytest`를 그냥 치면 models가 server보다 먼저 수집되므로 상시 위험이다.

    **스냅샷이 비어 있으면 이 픽스처는 아무것도 못 되돌린다.** 셋업 시점에 numpy가
    아직 안 올라와 있으면 `saved`가 비고, 티어다운은 테스트가 **정당하게 올린** 것까지
    지운 뒤 되돌릴 것이 없다 — 구멍이 좁아질 뿐 닫히지 않는다. 실측: `pytest models`
    뒤에 numpy를 쓰는 테스트를 붙이면 그 테스트가 깨진다. 그래서 이 파일은 위에서
    numpy를 **모듈 수준으로** import해 스냅샷이 언제나 실물을 담게 한다.
    """
    saved = {m: mod for m, mod in sys.modules.items()
             if m == "numpy" or m.startswith("numpy.")}
    assert saved, "numpy가 안 올라와 있다 — 이 픽스처가 조용히 무력해진다"
    yield
    for m in [m for m in sys.modules if m == "numpy" or m.startswith("numpy.")]:
        del sys.modules[m]
    sys.modules.update(saved)


def test_root_cause_walks_to_the_dlopen_error():
    """numpy가 감싼 일반 안내문이 아니라 **진짜 사유**를 집어야 한다.

    이 함수가 없으면 로그가 "you should not try to import numpy from its source
    directory"라고 자신 있게 틀린 말을 한다 — 실측으로 겪은 그 문장이다.
    """
    root = ImportError("dlopen(...): Symbol not found: _cblas_caxpy$NEWLAPACK")
    wrapped = ImportError("IMPORTANT: PLEASE READ THIS\n\nyou should not try to import")
    wrapped.__cause__ = root
    assert "_cblas_caxpy" in _root_cause(wrapped)


def test_root_cause_survives_a_cycle():
    """__cause__ 가 자기를 가리켜도 멈춘다 — 무한루프로 빌드를 세우지 않는다."""
    a = ImportError("a")
    b = ImportError("b")
    a.__cause__ = b
    b.__cause__ = a
    assert _root_cause(a) in {"a", "b"}


def test_root_cause_skips_leading_blank_lines():
    exc = ImportError("\n\n   \n실제 사유")
    assert _root_cause(exc) == "실제 사유"


def test_root_cause_falls_back_to_type_name_when_message_is_empty():
    assert _root_cause(ImportError("")) == "ImportError"


def test_candidates_are_abi_matched_to_this_interpreter(monkeypatch):
    """다른 마이너 버전의 site-packages를 제안하면 더 알아보기 어려운 실패가 된다."""
    monkeypatch.delenv(ENV_OVERRIDE, raising=False)  # 개발자 환경이 새어 들어오지 않게
    tag = "python%d.%d" % sys.version_info[:2]
    paths = candidate_site_packages("/repo")
    assert any(p == os.path.join("/repo", ".venv", "lib", tag, "site-packages")
               for p in paths)
    other = "python%d.%d" % (sys.version_info[0], sys.version_info[1] + 1)
    assert not any(other in p for p in paths)


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv(ENV_OVERRIDE, "/somewhere/sp")
    assert candidate_site_packages("/repo")[0] == "/somewhere/sp"


# ---------------------------------------------------------------- ensure_numpy
#
# 조용히 깨지기 가장 쉬운 셋이 여기 있다. 블렌더 없이도 전부 잰다.

def _numpy_modules():
    return {m for m in sys.modules if m == "numpy" or m.startswith("numpy.")}


def test_working_numpy_is_left_alone(monkeypatch):
    """이미 되면 sys.path를 흔들지 않는다 — 도는 환경을 건드리는 것이 가장 나쁘다."""
    before = list(sys.path)
    ok, msg = ensure_numpy(repo_root="/nonexistent", verbose=False)
    assert ok
    assert "번들" in msg
    assert sys.path == before


def test_total_failure_restores_sys_path(monkeypatch, tmp_path):
    """전부 실패해도 sys.path는 손대기 전과 **바이트 단위로 같아야** 한다.

    실패한 후보 경로를 남겨 두면 그 뒤의 모든 import가 엉뚱한 곳을 먼저 본다.
    """
    broken = tmp_path / "sp" / "numpy"
    broken.mkdir(parents=True)
    (broken / "__init__.py").write_text("raise ImportError('일부러 깨뜨림')\n")
    monkeypatch.setenv(ENV_OVERRIDE, str(tmp_path / "sp"))
    monkeypatch.setitem(sys.modules, "numpy", None)  # 첫 import를 실패시킨다

    before = list(sys.path)
    ok, msg = ensure_numpy(repo_root=str(tmp_path / "norepo"), verbose=False)
    assert not ok
    assert sys.path == before, "실패한 후보 경로가 sys.path에 남았다"
    assert ENV_OVERRIDE in msg, "복구 방법을 문장이 알려 줘야 한다"


def test_total_failure_leaves_no_numpy_debris(monkeypatch, tmp_path):
    """실패 후 sys.modules에 numpy 조각이 남으면, 나중의 import가 **다른 오류**로 죽는다.

    이 모듈이 애써 정확히 보고한 dlopen 오류 대신 알아보기 어려운 것이 나오는 자리다.
    """
    sp = tmp_path / "sp"
    (sp / "numpy").mkdir(parents=True)
    (sp / "numpy" / "__init__.py").write_text(
        "import sys\n"
        "sys.modules['numpy._core'] = object()\n"   # 부분 import를 흉내
        "raise ImportError('C 확장 로드 실패')\n")
    monkeypatch.setenv(ENV_OVERRIDE, str(sp))
    monkeypatch.setitem(sys.modules, "numpy", None)

    ok, _ = ensure_numpy(repo_root=str(tmp_path / "norepo"), verbose=False)
    assert not ok
    # 최상위 'numpy'는 monkeypatch가 되돌리므로 제외한다 — 나머지가 남으면 잔해다.
    # (프로세스 전체 복원은 autouse `restore_numpy_modules`가 맡는다.)
    leftovers = _numpy_modules() - {"numpy"}
    assert not leftovers, f"잔해가 남았다: {sorted(leftovers)}"


def test_purge_removes_submodules_too():
    sys.modules["numpy._fake_for_test"] = object()
    _purge_numpy()
    assert "numpy._fake_for_test" not in sys.modules
