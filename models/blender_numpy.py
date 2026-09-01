"""블렌더 내장 numpy가 못 뜨는 환경을 위한 보정 — 생성 스크립트가 맨 처음 부른다.

## 왜 필요한가

glTF 내보내기(`bpy.ops.export_scene.gltf`)는 numpy를 쓴다. 그런데 블렌더가 번들한
numpy는 **블렌더를 빌드한 머신의 macOS SDK에 묶여** 있어, 그보다 낮은 OS에서 돌리면
dlopen이 실패한다. 실측 (Blender 5.2.1 / macOS 13.2.1):

    ImportError: dlopen(.../numpy/_core/_multiarray_umath.cpython-313-darwin.so):
      Symbol not found: _cblas_caxpy$NEWLAPACK
      (built for macOS 26.0 which is newer than running OS)

**이 실패는 늦게, 조용히 온다.** numpy는 내보내기가 실제로 정점을 쓸 때 처음 불리므로
`.blend`는 멀쩡히 저장되고 GLB만 안 나온다. 애드온 모듈 자체는 import되기 때문에
"애드온이 로드되니 괜찮겠지"로 넘어가기도 쉽다.

## 무엇을 하나

리포 venv에 **같은 파이썬 마이너 버전**용 numpy가 있으면 그것을 `sys.path` 맨 앞에
꽂는다. 엔진이 이미 numpy를 쓰므로 이 환경에는 반드시 도는 numpy가 하나 있다.

`PYTHONPATH`로는 안 된다 — 블렌더가 자기 site-packages를 그 앞에 두므로 번들본이
계속 이긴다(실측). 그래서 프로세스 안에서 `sys.path.insert(0, ...)` 해야 한다.

ABI가 맞아야 하므로 **파이썬 마이너 버전이 같을 때만** 갈아끼운다. 3.13용 확장을
3.12에 물리면 더 알아보기 어려운 실패가 된다.
"""

import os
import sys

ENV_OVERRIDE = "CLAW_BLENDER_NUMPY"  # site-packages 경로를 직접 지정하고 싶을 때


def _root_cause(exc):
    """사슬 맨 끝의 사유 한 줄.

    numpy는 C 확장 로드가 실패하면 그것을 **긴 일반 안내문으로 감싸서** 다시 던진다.
    바깥 것을 집으면 "you should not try to import numpy from its source directory"가
    나오는데, 그건 이 경우의 원인이 아니다 — 실제 원인(dlopen 심볼 불일치)은 `__cause__`
    안에 있다. 틀린 사유를 자신 있게 적는 것은 사유를 안 적는 것보다 나쁘므로 끝까지 간다.
    """
    seen = set()
    while getattr(exc, "__cause__", None) is not None and id(exc) not in seen:
        seen.add(id(exc))
        exc = exc.__cause__
    for line in str(exc).splitlines():
        if line.strip():
            return line.strip()[:160]
    return type(exc).__name__


def _purge_numpy():
    """sys.modules에서 numpy 계열을 걷어낸다 — 부분 import 잔해가 다음 시도를 오염시킨다."""
    for mod in [m for m in sys.modules if m == "numpy" or m.startswith("numpy.")]:
        del sys.modules[mod]


def candidate_site_packages(repo_root):
    """이 인터프리터와 ABI가 맞는 site-packages 후보 — 우선순위 순."""
    tag = "python%d.%d" % sys.version_info[:2]
    out = []
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        out.append(override)
    out.append(os.path.join(repo_root, ".venv", "lib", tag, "site-packages"))
    return out


def ensure_numpy(repo_root, verbose=True):
    """numpy를 쓸 수 있게 만든다. 반환 (ok, 설명 문장).

    이미 되면 아무것도 안 한다 — 도는 환경에서 경로를 흔들지 않는다.
    """
    try:
        import numpy  # noqa: F401
        return True, "번들 numpy %s" % numpy.__version__
    except Exception as first:
        detail = _root_cause(first)

    for sp in candidate_site_packages(repo_root):
        if not os.path.isdir(os.path.join(sp, "numpy")):
            continue
        sys.path.insert(0, sp)
        _purge_numpy()  # 실패한 부분 import가 남아 있으면 재시도가 그것을 본다
        try:
            import numpy  # noqa: F401
            msg = "numpy %s ← %s (번들본 실패: %s)" % (numpy.__version__, sp, detail)
            if verbose:
                print("[numpy] " + msg)
            return True, msg
        except Exception:
            sys.path.remove(sp)  # 안 되면 원상복구 — 남겨 두면 다른 import가 흔들린다

    # **잔해를 남기고 물러나지 않는다.** C 확장 로드가 깊은 곳에서 실패하면 파이썬은
    # `numpy` 자체는 등록 취소하지만 먼저 성공한 하위 모듈은 남긴다. 그 하위 모듈들은
    # 방금 sys.path에서 뺀 경로에서 온 것이라, 나중에 glTF 내보내기가 `import numpy`
    # 할 때 **이 모듈이 애써 정확히 보고한 dlopen 오류가 아니라** 알아보기 어려운
    # 다른 오류로 죽는다.
    _purge_numpy()

    msg = ("numpy를 못 쓴다 (%s). GLB 내보내기가 빠진다 — `.blend`는 정상 생성된다. "
           "%s 로 도는 site-packages를 지정하거나, 이 OS에 맞는 블렌더를 쓸 것."
           % (detail, ENV_OVERRIDE))
    if verbose:
        print("[numpy] " + msg, file=sys.stderr)
    return False, msg
