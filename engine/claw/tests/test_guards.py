"""가드 스윕 자신의 지킴이.

이 도구는 「가드를 올리고 지키는 것을 안 만드는 것」을 잡으려고 만들었다. 그러니
**자기 자신이 그 예외일 수 없다.**

첫 판은 `find_guards`(**찾는** 쪽)만 지켰고 `sweep`(**판정하는** 쪽)은 무방비였다 — 리뷰가
변이 여덟을 걸어 여섯이 살아남는 것을 보였다. 판정 쪽이 조용히 초록을 내는 갈래가 넷이고
(빨간 기준선 · 스테이지된 변경 · git 실패 · 잘라낸 자리 문법 오류), 넷 다 결과가 「소견 0 ·
종료코드 0」이라 **침묵으로 나타난다.** 여기서 지키는 것은 그 침묵이다.
"""

import ast
import os
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path

import pytest

from claw.verify import guards as g


def _src(text):
    return textwrap.dedent(text).lstrip("\n")


def _all(text):
    return set(range(1, len(text.splitlines()) + 1))


# ── 찾는 쪽 ───────────────────────────────────────────────────────────────


def test_assert와_raise를_찾는다():
    src = _src("""
        def f(x):
            assert x > 0, "양수여야 한다"
            if x > 100:
                raise ValueError("너무 크다")
            return x
    """)
    found = g.find_guards(src, _all(src))
    lines = src.splitlines()
    assert [f[2] for f in found] == ['assert x > 0, "양수여야 한다"', "if x > 100:"]
    # `raise`는 그것만 든 `if`를 **통째로** 집는다 — 인용문도 그 자리에서 뽑는다.
    # `raise` 줄에서 뽑으면 보고 줄번호와 인용문이 어긋난다
    if_line = lines.index("    if x > 100:") + 1
    assert found[1][:2] == (if_line, if_line + 1)


def test_진입점은_가드가_아니다():
    """「raise만 든 if」 규칙에 그대로 걸린다 — 첫 판이 실제로 이것을 잡았다."""
    src = _src("""
        def main():
            return 0

        if __name__ == "__main__":
            raise SystemExit(main())
    """)
    assert g.find_guards(src, _all(src)) == []


def test_이름을_검사하는_진짜_가드는_진입점이_아니다():
    """조건에 `__name__`이 나오기만 하면 진입점으로 보던 판이 있었다.

    레지스트리·플러그인 코드에서 흔한 모양이라, 그러면 그 가드가 통째로 안 보인다.
    """
    src = _src("""
        def register(cls):
            if cls.__name__.startswith("_"):
                raise ValueError("사설 클래스는 등록하지 않는다")
    """)
    assert len(g.find_guards(src, _all(src))) == 1


def test_try_안의_raise는_안_집는다():
    src = _src("""
        def f():
            try:
                return risky()
            except OSError as e:
                raise RuntimeError("감쌌다") from e
    """)
    assert g.find_guards(src, _all(src)) == []


def test_새로_생긴_줄만_본다():
    """이미 있던 가드는 이번 변경의 소견이 아니다 — 매번 같은 것을 보고하면 안 읽힌다."""
    src = _src("""
        def f(x):
            assert x > 0
            assert x < 100
            return x
    """)
    assert [f[0] for f in g.find_guards(src, {3})] == [3]


# ── 무력화 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("label,src", [
    ("함수 몸통", "def f(x):\n    assert x > 0\n"),
    ("if 몸통", "def f(x):\n    if x:\n        assert x > 0\n    return x\n"),
    ("for 몸통", "def f(xs):\n    for x in xs:\n        assert x > 0\n"),
    ("with 몸통", "def f(c):\n    with c:\n        assert c\n"),
])
def test_유일한_문장인_가드도_문법이_안_깨진다(label, src):
    """**삭제만 하던 판이 여기서 `SyntaxError`를 냈다.**

    그러면 스윕이 가드 부재가 아니라 문법 오류를 「죽음」으로 오독한다 — 지킴이가
    하나도 없는 가드가 조용히 통과한다. `pass`로 바꾸면 그 부류가 통째로 없어진다.
    """
    (lo, hi, _), = g.find_guards(src, _all(src))
    out = g.neutralize(src, lo, hi)
    ast.parse(out)
    assert "assert" not in out and "pass" in out



@pytest.mark.parametrize("label,src", [
    ("세미콜론 뒤 문장", "def f(x):\n    assert x > 0; y = x * 2\n    return y\n"),
    ("조건의 대입식", "def f():\n    if (n := c()) < 0:\n        raise ValueError(n)\n    return n\n"),
])
def test_가드_아닌_것이_섞인_자리는_안_집는다(label, src):
    """무력화하면 그 대입까지 사라져 테스트가 **엉뚱한 이유로** 죽는다.

    거짓 경보는 안 나지만 「지킴이가 있다」는 **거짓 안심**을 준다 — 안 잡는 것이
    아니라 잘못 잡는 것이라 성질이 다르다.
    """
    assert g.find_guards(src, _all(src)) == [], label


def test_들여쓰기를_지킨다():
    src = "def f(x):\n    if x:\n        assert x > 0\n    return x\n"
    (lo, hi, _), = g.find_guards(src, _all(src))
    assert "        pass\n" in g.neutralize(src, lo, hi)


# ── 대상 선택 ─────────────────────────────────────────────────────────────


def test_테스트_파일은_변이_대상이_아니다():
    """테스트의 단언을 지우고 그 테스트를 돌리면 당연히 통과한다 — 범주 오류다.

    첫 판이 이것을 안 걸러서 스윕이 테스트 단언마다 「지킴이가 없다」를 외쳤다.
    잡음이 된 보고서는 아무도 안 읽고, 그것이 이 도구가 막으려던 병 그 자체다.
    """
    assert g._is_test("engine/claw/tests/test_ir.py")
    assert g._is_test("flight/tests/harness_helpers.py")
    assert not g._is_test("engine/claw/codegen/irtypes.py")
    # 실물에서도 확인한다 — 필터를 지우면 여기가 죽는다
    picked = g.changed_python()
    assert not any(g._is_test(p) for p in picked), f"테스트 파일이 대상에 섞였다: {picked}"


def test_모듈_이름을_낱말_단위로_고른다():
    """부분문자열로 고르면 `law`가 `claw`에 걸려 78개 파일(1263건)을 끌고 온다.

    가드 하나에 4분이 넘어가고, 그러면 아무도 이 도구를 안 돌린다.
    """
    picked = g.tests_for("engine/claw/fcl/law.py")
    assert 0 < len(picked) < 30, f"낱말 단위가 아니다: {len(picked)}개"
    assert all(g._is_test(p) for p in picked)
    # 이름이 저장소에 없으면 빈 목록 — 센티널을 **소스에 안 적는다**. 적으면 이 파일이
    # 커밋되는 순간 그 이름이 저장소 내용이 되어 이 단언이 스스로 깨진다
    assert g.tests_for(f"engine/claw/{uuid.uuid4().hex}.py") == []


def test_새_모듈과_새_테스트를_함께_써도_찾는다(monkeypatch):
    """`--untracked`가 없으면 이 도구가 **장려하려는 바로 그 행동**에 늑대를 외친다.

    첫 판은 `inspect.getsource`로 봤는데, 그 낱말이 **독스트링에도** 있어서 git 호출에서
    빼도 통과했다 — 지킴이가 코드가 아니라 산문을 보고 있었다. 실제 argv를 본다.
    """
    seen = []

    def spy(*args, check=True, **kw):
        seen.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(g, "_run", spy)
    g.tests_for("engine/claw/codegen/irtypes.py")
    (argv,) = seen
    assert "--untracked" in argv, f"git 호출에 안 실렸다: {argv}"
    assert "-w" in argv, "낱말 단위가 아니다"


# ── 판정하는 쪽 ───────────────────────────────────────────────────────────


class _FakeRepo:
    """`sweep`을 진짜로 돌린다 — 소스 문자열만 보면 트리를 안 되돌리는 구현도 통과한다."""

    def __init__(self, tmp, monkeypatch, src, rc=1, boom=False):
        self.dir = tmp
        self.rel = "mod.py"
        self.file = tmp / self.rel
        self.file.write_text(src, encoding="utf-8")
        self.src = src
        self.calls = 0
        monkeypatch.setattr(g, "ROOT", tmp)
        monkeypatch.setattr(g, "_BACKUP", tmp / "_bak")
        monkeypatch.setattr(g, "changed_python", lambda base="HEAD": {self.rel: _all(src)})
        monkeypatch.setattr(g, "tests_for", lambda p: ["fake_test.py"])

        def fake_pytest(tests, timeout=600):
            self.calls += 1
            if boom and self.calls > 1:
                raise RuntimeError("테스트 실행이 터졌다")
            return subprocess.CompletedProcess([], rc if self.calls > 1 else 0)

        monkeypatch.setattr(g, "_pytest", fake_pytest)


def test_예외가_나도_트리를_되돌린다(tmp_path, monkeypatch):
    """**공유 트리를 지키는 유일한 지킴이다.** 첫 판은 소스 문자열만 봐서, 복원을
    `.bak`으로 하는(=트리에 변이가 영구히 남는) 구현을 그대로 통과시켰다.
    """
    src = "def f(x):\n    assert x > 0\n    return x\n"
    repo = _FakeRepo(tmp_path, monkeypatch, src, boom=True)
    with pytest.raises(RuntimeError):
        g.sweep()
    assert repo.file.read_text(encoding="utf-8") == src, "변이가 트리에 남았다"


def test_기준선이_빨가면_판정하지_않는다(tmp_path, monkeypatch):
    """빨간 상태면 모든 변이가 그 이유로 죽어 **소견 0**이 된다 — 이 도구를 돌릴 만한
    바로 그 순간에 가장 잘 거짓말한다.
    """
    src = "def f(x):\n    assert x > 0\n    return x\n"
    _FakeRepo(tmp_path, monkeypatch, src)
    monkeypatch.setattr(g, "_pytest",
                        lambda t, timeout=600: subprocess.CompletedProcess([], 1))
    (why,) = [f[3] for f in g.sweep()]
    assert "기준선이 이미 빨갛다" in why


def test_지킴이가_없으면_지목한다(tmp_path, monkeypatch):
    """도구의 본업 — 무력화해도 초록이면 보고한다."""
    src = "def f(x):\n    assert x > 0\n    return x\n"
    repo = _FakeRepo(tmp_path, monkeypatch, src, rc=0)
    (path, lineno, label, why) = g.sweep()[0]
    assert (path, lineno) == ("mod.py", 2)
    assert "안 죽는다" in why
    assert repo.file.read_text(encoding="utf-8") == src


def test_지킴이가_있으면_지목하지_않는다(tmp_path, monkeypatch):
    """거짓 경보가 나면 보고서가 잡음이 되고, 잡음이 된 보고서는 아무도 안 읽는다."""
    src = "def f(x):\n    assert x > 0\n    return x\n"
    _FakeRepo(tmp_path, monkeypatch, src, rc=1)
    assert g.sweep() == []


def test_보는_테스트가_없으면_그것을_소견으로_낸다(tmp_path, monkeypatch):
    """가장 강한 소견인데 지킴이가 없었다 — 「이 가드를 볼 테스트가 없다」가
    조용히 사라지면 스윕이 무방비인 파일에 대해 아무 말도 안 한다.
    """
    src = "def f(x):\n    assert x > 0\n    return x\n"
    repo = _FakeRepo(tmp_path, monkeypatch, src)
    monkeypatch.setattr(g, "tests_for", lambda p: [])
    (path, lineno, _label, why) = g.sweep()[0]
    assert (path, lineno) == ("mod.py", 0)
    assert "보는 테스트가 없다" in why
    assert repo.calls == 0, "테스트가 없는데 돌렸다"


def test_두_스윕이_겹치면_거부한다(tmp_path, monkeypatch):
    """겹치면 한쪽이 다른 쪽의 변이를 「원본」으로 읽어 **가드가 영구히 사라진다.**

    `LOCK_NB`를 빼면 실패가 아니라 **행**이 된다 — CI에서 행은 실패보다 나쁘다.
    별도 스레드로 재서 안 돌아오면 실패로 떨어뜨린다.
    """
    import threading

    monkeypatch.setattr(g, "ROOT", tmp_path)
    monkeypatch.setattr(g, "_BACKUP", tmp_path / "_bak")
    got = []
    with g._Lock():
        def second():
            try:
                with g._Lock():
                    got.append("잡았다")
            except g.SweepError:
                got.append("거부")

        t = threading.Thread(target=second, daemon=True)
        t.start()
        t.join(timeout=5)
        assert not t.is_alive(), "락이 블로킹이다 — 거부하지 않고 기다린다"
    assert got == ["거부"], got


def test_git이_실패하면_시끄럽게_죽는다(monkeypatch):
    """`returncode`를 안 보면 얕은 클론의 CI에서 스윕이 **영원히 초록**을 낸다."""
    with pytest.raises(g.SweepError, match="실패"):
        g.changed_python("HEAD~9999")


def test_보고서는_판정이_아니다():
    """겹겹이 둔 가드 하나로 CI가 빨개지면 이 도구는 곧 무시된다."""
    import inspect

    src = inspect.getsource(g.main)
    assert "1 if strict else 0" in src, "종료코드가 기본으로 판정을 낸다"


def test_복원_전에_자기_변이_그대로인지_본다(tmp_path, monkeypatch):
    """그 사이 누가 고쳤으면 덮어쓰지 않는다 — **남의 편집을 되돌리는 것이 가드 하나보다
    나쁘다.** 공유 트리에서 두 스윕이 겹칠 때 가드가 영구히 사라지던 경로다.
    """
    src = "def f(x):\n    assert x > 0\n    return x\n"
    repo = _FakeRepo(tmp_path, monkeypatch, src)
    남의편집 = "def f(x):\n    assert x > 0\n    return x + 1\n"

    def meddling(tests, timeout=600):
        repo.calls += 1
        if repo.calls > 1:
            repo.file.write_text(남의편집, encoding="utf-8")  # 다른 세션이 고쳤다
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(g, "_pytest", meddling)
    with pytest.raises(g.SweepError, match="스윕 중에 바뀌었다"):
        g.sweep()
    assert repo.file.read_text(encoding="utf-8") == 남의편집, "남의 편집을 되돌렸다"


def test_변이_전에_트리_밖에_백업한다(tmp_path, monkeypatch):
    """하드 킬(SIGKILL·타임아웃)이면 `finally`가 안 돌고, **미추적 파일은 git에 사본이
    없어** 백업이 없으면 코드 한 조각이 영구히 사라진다.
    """
    src = "def f(x):\n    assert x > 0\n    return x\n"
    repo = _FakeRepo(tmp_path, monkeypatch, src)
    seen = {}

    def peek(tests, timeout=600):
        repo.calls += 1
        if repo.calls == 1:
            return subprocess.CompletedProcess([], 0)  # 기준선은 초록이어야 진행한다
        paths = sorted((tmp_path / "_bak").glob("*.orig"))
        seen["baks"] = [p.read_text(encoding="utf-8") for p in paths]
        seen["names"] = [p.name for p in paths]
        return subprocess.CompletedProcess([], 1)

    monkeypatch.setattr(g, "_pytest", peek)
    g.sweep()
    (body,) = seen["baks"]
    assert body == f"{tmp_path}\tmod.py\n{src}", "백업이 원본을 안 담았다"
    # **이름에도 트리가 들어가야 한다.** 내용 대조는 「남의 것을 안 덮어쓴다」만
    # 보장하고, 이름 분리가 「내 것이 남아 있다」를 보장한다 — 이름이 겹치면 B가 A의
    # 백업을 덮어쓰고, A가 하드 킬되면 A의 원본이 영구히 사라진다
    (name,) = seen["names"]
    assert name.startswith(g._tree_key()), f"백업 이름에 트리가 없다: {name}"


def test_남은_변이를_시작할_때_되돌린다(tmp_path, monkeypatch):
    """크래시 복구다. 첫 판은 이것을 **자기가 잡은 락 안**에 둬서, 락이 남아 있는
    바로 그 상황(하드 킬)에서 도달할 수 없었다.
    """
    src = "def f(x):\n    assert x > 0\n    return x\n"
    repo = _FakeRepo(tmp_path, monkeypatch, src)
    repo.file.write_text("def f(x):\n    pass\n    return x\n", encoding="utf-8")
    bak = tmp_path / "_bak"
    bak.mkdir()
    (bak / f"{g._tree_key()}-x.orig").write_text(f"{tmp_path}\tmod.py\n{src}",
                                                 encoding="utf-8")
    g.sweep()
    assert repo.file.read_text(encoding="utf-8") == src, "잔존 변이를 안 되돌렸다"


def test_다른_트리의_백업은_안_건드린다(tmp_path, monkeypatch):
    """`_BACKUP`은 머신 전역이다 — 이름에 트리를 안 넣으면 **크래시 복구용으로 넣은 것이
    크래시 없는 트리를 덮어쓴다.** 이 저장소에는 `.claude/worktrees/`가 실재한다.
    """
    monkeypatch.setattr(g, "ROOT", tmp_path)
    monkeypatch.setattr(g, "_BACKUP", tmp_path / "_bak")
    (tmp_path / "_bak").mkdir()
    (tmp_path / "mod.py").write_text("나의 것\n", encoding="utf-8")
    (tmp_path / "_bak" / f"{g._tree_key()}-y.orig").write_text(
        "/다른/트리\tmod.py\n남의 것\n", encoding="utf-8")
    assert g._restore_leftovers() == [], "다른 트리의 백업을 복원했다"
    assert (tmp_path / "mod.py").read_text(encoding="utf-8") == "나의 것\n"


def test_하드_킬로_남은_락은_저절로_풀린다(tmp_path, monkeypatch):
    """pid를 적어 두고 생사를 묻던 판은 **판정과 회수 사이가 원자적이지 않아** 산 락을
    죽은 줄 알고 치웠다. `flock`은 프로세스가 죽으면 OS가 푼다 — 그 추측이 통째로
    필요 없어진다.
    """
    monkeypatch.setattr(g, "ROOT", tmp_path)
    monkeypatch.setattr(g, "_BACKUP", tmp_path / "_bak")
    code = (
        "import fcntl, os, sys, time\n"
        f"p = {str(tmp_path / '_bak')!r}\n"
        "os.makedirs(p, exist_ok=True)\n"
        f"fd = os.open(os.path.join(p, {g._tree_key() + '.lock'!r}), os.O_CREAT | os.O_RDWR)\n"
        "fcntl.flock(fd, fcntl.LOCK_EX)\n"
        "print('held', flush=True)\n"
        "time.sleep(30)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "held"
        with pytest.raises(g.SweepError, match="다른 스윕이"):
            with g._Lock():
                pass
    finally:
        child.kill()
        child.wait()
    # 하드 킬 뒤에는 손대지 않아도 잡힌다
    with g._Lock():
        pass


def test_diff_헤더가_파일마다_상태를_지운다(tmp_path, monkeypatch):
    """`b/`로 시작하는 것만 보면 `/dev/null`(삭제)이나 따옴표 경로에서 상태가 남아,
    **손대지 않은 옛 가드가 앞 파일의 새 줄로** 보고된다.

    첫 판이 실제로 그랬다 — 한글 파일명의 헝크가 앞 파일에 섞여 `zz_normal.py:56`의
    옛 `assert`를 새 가드라고 냈다.
    """
    diff = (
        "--- a/first.py\n+++ b/first.py\n@@ -1 +2 @@\n"
        "--- a/gone.py\n+++ /dev/null\n@@ -1,3 +0,0 @@\n"
        '--- "a/\355\225\234.py"\n+++ "b/\355\225\234.py"\n@@ -1 +55,2 @@\n'
    )
    for name in ("first.py", "\355\225\234.py"):
        (tmp_path / name).write_text("x = 1\n" * 60, encoding="utf-8")
    monkeypatch.setattr(g, "ROOT", tmp_path)
    monkeypatch.setattr(g, "_run", lambda *a, check=True, **kw: subprocess.CompletedProcess(
        a, 0, stdout=(diff if "diff" in a else ""), stderr=""))
    got = g.changed_python()
    assert got["first.py"] == {2}, f"옛 가드가 앞 파일에 섞였다: {got['first.py']}"
    assert "gone.py" not in got, "삭제된 파일이 대상에 들어왔다"


def test_타임아웃은_시끄럽게_죽는다(monkeypatch):
    """안 잡으면 `TimeoutExpired`가 스윕을 뚫고 나가 **부분 결과 없이** traceback이 된다."""
    def boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="pytest", timeout=1)

    monkeypatch.setattr(g, "_run", boom)
    with pytest.raises(g.SweepError, match="초를 넘었다"):
        g._pytest(["x.py"])


def test_트리_키가_트리마다_다르다(tmp_path, monkeypatch):
    """`_tree_key`가 상수로 퇴화하면 백업 이름이 트리끼리 겹친다.

    앞의 백업 테스트가 이름을 `_tree_key()`로 **계산해서** 만들기 때문에, 이 단언이
    없으면 상수 퇴화가 그대로 통과한다 — 지킴이가 자기가 지켜야 할 값을 써서 만든다.
    """
    monkeypatch.setattr(g, "ROOT", tmp_path / "a")
    a = g._tree_key()
    monkeypatch.setattr(g, "ROOT", tmp_path / "b")
    assert a != g._tree_key(), "트리가 달라도 키가 같다"


def test_충돌_백업은_다음_스윕이_안_덮는다(tmp_path, monkeypatch):
    """「복원하지 않는다」고 지킨 남의 편집을, 다음 실행이 복구랍시고 덮어썼다.

    출력은 「이전 스윕이 남긴 변이를 되돌렸다」 한 줄뿐이라 **친절한 복구처럼 보인다.**
    """
    src = "def f(x):\n    assert x > 0\n    return x\n"
    repo = _FakeRepo(tmp_path, monkeypatch, src)
    남의편집 = "def f(x):\n    assert x > 0\n    return x + 1\n"

    def meddling(tests, timeout=600):
        repo.calls += 1
        if repo.calls > 1:
            repo.file.write_text(남의편집, encoding="utf-8")
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(g, "_pytest", meddling)
    with pytest.raises(g.SweepError):
        g.sweep()
    assert repo.file.read_text(encoding="utf-8") == 남의편집
    # 2차 스윕 — 충돌 백업이 `.orig`로 남아 있으면 여기서 남의 편집이 사라진다
    assert g._restore_leftovers() == [], "충돌 백업을 복구 대상으로 삼았다"
    assert repo.file.read_text(encoding="utf-8") == 남의편집, "남의 편집이 사라졌다"


@pytest.mark.parametrize("label,src", [
    ("else 블록", "def f(x):\n    if x:\n        pass\n    else:\n        assert x; y = 2\n"),
    ("finally 블록", "def f(x):\n    try:\n        pass\n    finally:\n        assert x; z = 2\n"),
    ("assert msg의 대입식", 'def f(x):\n    assert x > 0, (m := f"{x}")\n    return m\n'),
])
def test_body가_아닌_블록도_거른다(label, src):
    """`up.body` 한 리스트만 보면 `else`(`orelse`)·`finally`(`finalbody`)의 같은 모양이
    그냥 통과한다. 그러면 머리말이 「일부러 뺀다」고 단정한 것이 거기서는 거짓이 된다.
    """
    assert g.find_guards(src, _all(src)) == [], label


def test_죽은_락_회수가_원자적이다(tmp_path, monkeypatch):
    """`unlink` 뒤 `open`은 두 걸음이라, 하드 킬 다음 날 아침처럼 둘이 동시에 시작하면
    **둘 다 락을 쥔다** — 락이 막으려던 바로 그 상태다(리뷰가 300회 중 2회 재현했다).

    경쟁을 실제로 일으킨다: 여럿이 같은 죽은 락에 달려들어 **하나만** 성공해야 한다.
    """
    import threading

    monkeypatch.setattr(g, "ROOT", tmp_path)
    monkeypatch.setattr(g, "_BACKUP", tmp_path / "_bak")
    (tmp_path / "_bak").mkdir()
    lock = tmp_path / "_bak" / f"{g._tree_key()}.lock"
    lock.write_text("999999", encoding="utf-8")  # 죽은 pid

    # **차례로 잡는 것은 정상이다** — 재는 것은 겹침이지 횟수가 아니다. 처음엔 횟수를
    # 세다가 「3개가 동시에」로 잘못 죽었다: 앞 스레드가 놓은 뒤 뒷 스레드가 잡은 것이다
    lock_guard = threading.Lock()
    state = {"now": 0, "max": 0}
    errors, start = [], threading.Barrier(8)

    def contend():
        start.wait()
        try:
            with g._Lock():
                with lock_guard:
                    state["now"] += 1
                    state["max"] = max(state["max"], state["now"])
                time.sleep(0.02)  # 겹치면 여기서 겹친다
                with lock_guard:
                    state["now"] -= 1
        except g.SweepError:
            errors.append(1)
        except Exception as e:  # 생 traceback이 새면 안 된다
            errors.append(e)

    threads = [threading.Thread(target=contend) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(e == 1 for e in errors), f"SweepError 아닌 예외가 샜다: {errors}"
    assert state["max"] == 1, f"{state['max']}개가 동시에 락을 쥐었다"
    assert state["max"] + len(errors) > 1, "경쟁이 아예 안 일어났다 — 검사가 공허하다"


def test_놓으면_같은_프로세스에서_다시_잡는다(tmp_path, monkeypatch):
    """`os.close`를 빼면 fd가 새어 **한 프로세스에서 스윕을 두 번 못 돈다.**

    지금은 `main`이 프로세스당 한 번만 돌아 잠복이고, 테스트마다 `tmp_path`가 달라
    아무도 안 봤다. 같은 경로에서 놓고 다시 잡아 본다.
    """
    monkeypatch.setattr(g, "ROOT", tmp_path)
    monkeypatch.setattr(g, "_BACKUP", tmp_path / "_bak")
    for _ in range(3):
        with g._Lock():
            pass
    # 락 파일은 남아 있어야 한다 — 지우면 배타가 깨진다(새 inode에 새 락이 걸린다)
    assert (tmp_path / "_bak" / f"{g._tree_key()}.lock").exists()
