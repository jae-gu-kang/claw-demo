"""올려놓은 가드에 지킴이가 있는지 — **가드를 무력화해 보고 아무도 안 죽으면 보고한다.**

이 저장소가 v0.83에서 이름을 붙이고 v0.87까지 되풀이한 결함이 있다: **가드를 올리고 그것을
지키는 것을 안 만드는 것.** 규율(손으로 돌리는 뮤테이션)이 잡은 것도 많지만 — v0.83 한
항목에서만 아홉 자리를 그렇게 잡았다 — 사람은 **자기가 떠올린 변이만** 돌린다. `_finite`를
쓰면서 `lo=False`를 떠올리지 못했고, 출처 표를 만들면서 그 표가 산문이 되는 경우를 떠올리지
못했다. 리뷰가 잡은 것들이 대체로 그 부류다. 그래서 기계가 대신 센다.

바뀐 파일의 **새로 생긴 줄**에 있는 가드(`assert`, 그리고 그것만 든 `if`의 `raise`)를 찾아
하나씩 `pass`로 바꾸고, 그 모듈을 보는 테스트를 돌린다. 초록이면 지킴이가 없다.

**못 하는 것을 먼저 적는다** — 안 적으면 이 도구 자체가 거짓 약속을 하는 가드가 된다.

- **무력화만 한다.** 가드를 무르는 변이(`if x is not None` → `if x`)는 안 만든다. v0.84가
  기록한 형태 — `lo="10", hi="9"`가 문자열 비교로 뒤집힘 가드를 그대로 지나간 것 — 이
  그 부류이고, 이 도구는 그것을 못 잡는다.
- **살아남은 것이 곧 결함은 아니다.** 겹겹이 둔 가드는 하나를 무력화해도 다른 것이 잡는다.
  보고서는 판정이 아니라 「봐야 할 자리」다. 그래서 기본 종료코드가 0이다(`--strict`가
  아니면). 판정을 내면 겹겹이 가드 하나로 CI가 빨개지고, 그러면 이 도구는 곧 무시된다.
- **테스트 선택이 어림이다.** 모듈 이름을 **낱말 단위로** 언급하는 테스트 파일을 고른다.
  고른 것이 없으면 그것 자체가 더 나쁜 소견이다.
- **안 보는 자리**: `match`/`case` 안의 `raise` · `else`가 딸린 `if`의 `raise` ·
  한 줄에 다른 문장이 붙은 `assert` · 조건에 대입식(`:=`)이 있는 `if`. 앞 둘은 규칙이
  안 닿는 자리이고, **뒤 둘은 일부러 뺀다** — 집는 자리에 가드 아닌 것이 섞이면 그
  대입까지 사라져 테스트가 엉뚱한 이유로 죽고, 그러면 「지킴이가 있다」는 거짓 안심을
  준다. 넷 다 거짓 경보는 안 낸다.

**공유 작업 트리에서 돈다.** 그래서 배타 락을 잡고, 원본을 트리 **밖**에 백업하고, 복원 전에
파일이 자기가 쓴 변이 그대로인지 확인한다. 이 셋 중 하나라도 없으면 두 세션이 동시에 돌 때
한쪽이 다른 쪽의 변이를 「원본」으로 읽어 가드가 **영구히 사라진다**(리뷰가 재현했다).
"""

import ast
import fcntl
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
# 리눅스의 `/tmp`는 전역 쓰기 가능이다 — `_restore_leftovers`가 그 파일의 헤더를 믿고
# 트리에 쓰므로, 남이 심은 파일이 들어올 수 있다. 사용자별로 가르고 권한을 좁힌다
_BACKUP = Path(tempfile.gettempdir()) / f"claw-guards-{os.getuid()}"


class SweepError(RuntimeError):
    """스윕이 판정을 낼 수 없는 상태 — 조용한 초록보다 시끄러운 실패가 낫다."""


def _run(*args, check=True, **kw):
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, **kw)
    if check and r.returncode not in (0, 1):  # git grep은 못 찾으면 1이다
        raise SweepError(f"{' '.join(args[:3])} 실패({r.returncode}): {r.stderr.strip()}")
    return r


def changed_python(base="HEAD"):
    """바뀐 .py와 **새로 생긴 줄 번호**.

    기본이 `HEAD`다 — `git diff`만 쓰면 **스테이지된 변경이 안 보인다.** 커밋 직전에
    돌리는 도구가 커밋 직전 상태에서 눈이 머는 셈이라, 그때 가장 잘 거짓말한다.
    """
    r = _run("git", "-c", "core.quotepath=false", "diff", "-U0", base, "--", "*.py")
    files, lines = {}, None
    for line in r.stdout.splitlines():
        if line.startswith("+++"):
            # **모든 `+++`에서 상태를 지운다.** `b/`로 시작하는 것만 보면 `/dev/null`(삭제)나
            # 따옴표로 감싼 경로에서 상태가 남아, **손대지 않은 옛 가드가 앞 파일의 새 줄로**
            # 보고된다. 경로 뒤의 탭도 뗀다 — 공백 든 이름에서 키가 어긋난다
            lines = None
            rest = line[4:].split("\t")[0]
            if rest.startswith("b/"):
                lines = files.setdefault(rest[2:], set())
        elif line.startswith("@@") and lines is not None:
            head = line.split("+", 1)[1].split("@@")[0].strip()
            start, _, count = head.partition(",")
            lines.update(range(int(start), int(start) + int(count or 1)))
    for rel in _run("git", "ls-files", "-o", "--exclude-standard", "*.py").stdout.split():
        n = len((ROOT / rel).read_text(encoding="utf-8").splitlines())
        files[rel] = set(range(1, n + 1))
    return {
        f: ln for f, ln in files.items()
        if ln and (ROOT / f).exists() and not _is_test(f)
    }


def _is_test(path):
    """**테스트 파일은 변이 대상이 아니다.** 테스트의 단언을 지우고 그 테스트를 돌리면
    당연히 통과한다 — 범주 오류다. 테스트는 지키는 쪽이지 지켜지는 쪽이 아니다.
    """
    p = Path(path)
    return p.name.startswith("test_") or "tests" in p.parts


def _parents(tree):
    out = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            out[child] = node
    return out


def _is_main_guard(node):
    """`if __name__ == "__main__":`인지 — 이름이 나오기만 하면 안 된다.

    조건에 `__name__`이 등장하는 **진짜 가드**(`if cls.__name__.startswith("_"): raise …`)를
    진입점으로 오인하면 레지스트리·플러그인 코드의 가드가 통째로 안 보인다.
    """
    test = getattr(node, "test", None)
    if not isinstance(test, ast.Compare) or len(test.comparators) != 1:
        return False
    left, right = test.left, test.comparators[0]
    return (
        isinstance(left, ast.Name) and left.id == "__name__"
        and isinstance(right, ast.Constant) and right.value == "__main__"
    )


def find_guards(src, added):
    """새로 생긴 줄에 걸린 가드 — `(시작줄, 끝줄, 인용문)`.

    **소스를 인자로 받는다** — 파일을 읽으면 이 함수를 시험하려고 저장소에 픽스처 파일을
    만들어야 하고, 그러면 시험이 트리를 흔든다.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    parent = _parents(tree)
    lines = src.splitlines()

    def in_entrypoint(node):
        up = parent.get(node)
        while up is not None:
            if isinstance(up, ast.If) and _is_main_guard(up):
                return True
            up = parent.get(up)
        return False

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assert, ast.Raise)) or in_entrypoint(node):
            continue
        target = node
        if isinstance(node, ast.Raise):
            up = parent.get(node)
            if isinstance(up, ast.If) and up.body == [node] and not up.orelse:
                target = up
            elif not isinstance(up, ast.Module):
                continue  # try/except의 재던짐 등 — 되돌림이 곧 가드 제거가 아니다
        if not added & set(range(target.lineno, target.end_lineno + 1)):
            continue
        if _carries_more(target, parent):
            continue
        # 인용문은 **집는 자리**에서 뽑는다 — `raise` 줄에서 뽑으면 보고 줄번호와 어긋난다
        found.append((target.lineno, target.end_lineno, lines[target.lineno - 1].strip()[:70]))
    return sorted(found)


def _carries_more(target, parent):
    """집는 자리에 **가드 아닌 것**이 섞여 있나 — 그러면 무력화가 거짓 음성을 낸다.

    두 부류다. `assert x > 0; y = x * 2`는 한 줄이라 `y` 대입까지 사라져 테스트가
    엉뚱한 이유로 죽고, `if (n := compute()) < 0: raise …`는 조건의 대입이 사라져
    같은 일이 난다. 둘 다 **안 잡는 것이 아니라 잘못 잡는 것**이라 성질이 다르다 —
    거짓 경보는 안 나지만 「지킴이가 있다」는 거짓 안심을 준다.
    """
    # `target` **전체**를 건다 — `test`만 보면 `assert x, (m := f"{x}")`의 msg 쪽
    # 대입식을 놓친다
    if any(isinstance(n, ast.NamedExpr) for n in ast.walk(target)):
        return True
    up = parent.get(target)
    if up is None:
        return False
    # `body` 한 리스트만 보면 `else`(`orelse`)·`finally`(`finalbody`) 블록의 같은 모양이
    # 그냥 통과한다 — **target이 실제로 든 리스트**를 찾아 센다
    for field, value in ast.iter_fields(up):
        if not isinstance(value, list) or target not in value:
            continue
        if len([n for n in value if getattr(n, "lineno", None) == target.lineno]) > 1:
            return True
    return False


def neutralize(src, lo, hi):
    """가드를 `pass`로 바꾼다 — **지우면 빈 블록이 되어 문법이 깨진다.**

    함수·`if`·`for` 몸통의 유일한 문장이 가드일 때가 그렇고, 그러면 스윕이 가드 부재가
    아니라 `SyntaxError`를 「죽음」으로 오독한다 — 지킴이가 하나도 없는 가드가 조용히
    통과한다. 삭제만 하던 첫 판이 실제로 그랬다.
    """
    lines = src.splitlines(keepends=True)
    indent = re.match(r"[ \t]*", lines[lo - 1]).group(0)
    out = "".join(lines[: lo - 1] + [f"{indent}pass\n"] + lines[hi:])
    ast.parse(out)  # 여기서 죽으면 스윕이 그 가드를 건너뛴다 — 오독보다 낫다
    return out


def tests_for(path):
    """이 모듈을 보는 테스트 파일 — 이름을 **낱말 단위로** 언급하는 것.

    부분문자열로 고르면 `law`가 `claw`에 걸려 78개 파일(1263건)을 끌고 온다. 그리고
    `--untracked`가 없으면 「새 모듈 + 그것을 지키는 새 테스트」를 함께 쓴 정직한 작업에
    대고 「이 파일을 보는 테스트가 없다」고 늑대를 외친다 — 이 도구가 장려하려는 바로
    그 행동에서.
    """
    module = Path(path).stem
    if module.startswith("test_"):
        return [path]
    r = _run("git", "grep", "-w", "-l", "--untracked", "-e", module,
             "--", "*/tests/*.py", "*/test_*.py")
    return sorted(set(r.stdout.split()))


def _pytest(tests, timeout=600):
    try:
        return _run(sys.executable, "-B", "-m", "pytest", *tests, "-q", "--no-header",
                    "-x", "-p", "no:cacheprovider", check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise SweepError(f"테스트가 {timeout}초를 넘었다: {' '.join(tests[:3])}…")


def _tree_key():
    """백업·락 이름에 **트리를 넣는다.** `_BACKUP`은 머신 전역이라, 상대경로만 쓰면
    다른 워크트리(이 저장소에는 `.claude/worktrees/phase1/`이 실재한다)나 다른 사용자의
    백업과 같은 이름이 된다 — 크래시 복구용으로 넣은 것이 **크래시 없는 트리를 덮어쓴다.**
    """
    return hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]


class _Lock:
    """공유 트리에서 두 스윕이 겹치면 한쪽이 다른 쪽의 변이를 원본으로 읽는다.

    **`flock`을 쓴다.** pid를 적어 두고 생사를 물어 뺏는 방식은 판정과 회수 사이가
    원자적이지 않아, 느린 프로세스가 **산 락을 죽은 줄 알고 치운다** — 여덟이 겨루게
    했더니 셋이 동시에 쥐었다. OS 락은 그 창이 없고, 덤으로 **하드 킬에서 자동으로
    풀린다**: pid 추측이 있던 이유(하드 킬 뒤 영구히 남는 락)가 통째로 사라진다.
    """

    def __init__(self):
        self.path = _BACKUP / f"{_tree_key()}.lock"
        self.fd = None

    def __enter__(self):
        _BACKUP.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self.fd)
            self.fd = None
            raise SweepError(f"다른 스윕이 이 트리에서 돌고 있다 ({self.path})")
        os.ftruncate(self.fd, 0)
        os.write(self.fd, str(os.getpid()).encode())  # 누가 쥐었는지 사람이 보라고
        return self

    def __exit__(self, *exc):
        # **락 파일은 지우지 않는다.** 언링크하면 「지워진 inode에 락을 쥔 쪽」과 「새로
        # 만든 inode에 락을 쥔 쪽」이 공존한다 — 배타가 통째로 깨진다. 남는 것은 pid만
        # 든 빈 파일이고 다음 실행이 그대로 재사용한다. 「정리」한다고 지우면 안 된다.
        # `close`가 곧 해제다 — `LOCK_UN`을 함께 두면 **둘이 서로를 가려** 어느 쪽을
        # 지워도 아무도 안 죽는다(실제로 그랬다). 하나만 두면 그 하나가 지킴이를 갖는다.
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def _restore_leftovers():
    """하드 킬(SIGKILL·타임아웃)로 남은 변이를 시작할 때 되돌린다.

    미추적 파일은 git에 사본이 없어, 백업이 없으면 코드 한 조각이 **영구히** 사라진다.
    """
    healed = []
    for bak in sorted(_BACKUP.glob(f"{_tree_key()}-*.orig")):
        head, _, body = bak.read_text(encoding="utf-8").partition("\n")
        root, _, rel = head.partition("\t")
        if root != str(ROOT):
            continue  # 다른 트리의 백업 — 이름이 겹쳐도 내용으로 한 번 더 가른다
        (ROOT / rel).write_text(body, encoding="utf-8")
        bak.unlink()
        healed.append(rel)
    return healed


def sweep(base="HEAD", quiet=False):
    """가드마다 무력화하고 테스트를 돌린다. 반환은 소견 목록."""
    findings = []
    with _Lock():
        for rel in _restore_leftovers():
            print(f"  이전 스윕이 남긴 변이를 되돌렸다: {rel}", file=sys.stderr)
        for path, added in sorted(changed_python(base).items()):
            src = (ROOT / path).read_text(encoding="utf-8")
            guards = find_guards(src, added)
            if not guards:
                continue
            tests = tests_for(path)
            if not tests:
                findings.append((path, 0, "(파일 전체)", "이 파일을 보는 테스트가 없다"))
                continue
            # **기준선을 먼저 본다.** 빨간 상태면 모든 변이가 그 이유로 죽어 소견 0이
            # 되는데, 그것은 이 도구를 돌릴 만한 바로 그 순간이다
            if _pytest(tests).returncode != 0:
                findings.append((path, 0, "(파일 전체)",
                                 f"기준선이 이미 빨갛다 — {' '.join(tests[:3])} 먼저 볼 것"))
                continue
            findings += _sweep_file(path, src, guards, tests, quiet)
    return findings


def _sweep_file(path, src, guards, tests, quiet):
    out = []
    target = ROOT / path
    bak = _BACKUP / f"{_tree_key()}-{hashlib.sha256(path.encode()).hexdigest()[:16]}.orig"
    for lo, hi, label in guards:
        try:
            mutated = neutralize(src, lo, hi)
        except SyntaxError:
            # 지금은 도달 불가인 그물이다 — `pass` 치환이 문법을 깨는 입력을 못 찾았다.
            # `find_guards`가 넓어질 때를 위해 남긴다
            out.append((path, lo, label, "무력화한 자리가 문법에 안 맞아 건너뛴다"))
            continue
        bak.write_text(f"{ROOT}\t{path}\n{src}", encoding="utf-8")
        target.write_text(mutated, encoding="utf-8")
        try:
            rc = _pytest(tests).returncode
        finally:
            # **자기가 쓴 변이 그대로인지 확인하고 되돌린다.** 그 사이 누가 고쳤으면
            # 덮어쓰지 않는다 — 남의 편집을 되돌리는 것이 가드 하나보다 나쁘다
            if target.read_text(encoding="utf-8") == mutated:
                target.write_text(src, encoding="utf-8")
                bak.unlink(missing_ok=True)
            else:
                # `.orig`로 두면 **다음 스윕이 복구랍시고 남의 편집을 덮어쓴다** —
                # 「복원하지 않는다」가 다음 실행에 깨지는 약속이 된다. 이름을 바꿔
                # `_restore_leftovers`의 시야 밖으로 옮긴다
                keep = bak.with_suffix(".conflict")
                bak.replace(keep)
                raise SweepError(
                    f"{path}가 스윕 중에 바뀌었다 — 복원하지 않는다. 원본은 {keep}에 있다"
                )
        if rc == 0:
            out.append((path, lo, label, "무력화해도 아무도 안 죽는다"))
        if not quiet:
            print(f"  {'살아남음' if rc == 0 else '죽음':8s} {path}:{lo}  {label}",
                  file=sys.stderr)
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    strict = "--strict" in argv
    argv = [a for a in argv if a != "--strict"]
    base = argv[0] if argv else "HEAD"
    print(f"가드 스윕: {ROOT} (기준 {base})", file=sys.stderr)
    try:
        findings = sweep(base)
    except SweepError as e:
        print(f"\n가드 스윕을 못 돌렸다: {e}")
        return 2
    print()
    if not findings:
        print("가드 스윕: 지킴이 없는 자리 없음")
        return 0
    print(f"가드 스윕: 봐야 할 자리 {len(findings)}곳")
    for path, lineno, label, why in findings:
        where = f"{path}:{lineno}" if lineno else path
        print(f"  {where}\n    {label}\n    → {why}")
    print("\n살아남은 것이 곧 결함은 아니다 — 겹겹이 둔 가드는 하나를 무력화해도 다른 것이")
    print("잡는다. 다만 「이 가드가 무엇을 지키는가」를 한 번은 물어야 하는 자리다.")
    return 1 if strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
