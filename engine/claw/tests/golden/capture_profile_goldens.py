"""예제 기체 엔진 골든 캡처 — `python engine/claw/tests/golden/capture_profile_goldens.py`

이관 전 HEAD에서 한 번 굳힌다. 캡처 시 같은 항목을 두 번 계산해 **결정론**을 먼저 확인한다
(비결정적인 값은 골든이 될 수 없다). 재생성은 동작 변경 단계(02 §5.6)에서만 --force로.
"""

import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import engine_goldens  # noqa: E402
import golden_io  # noqa: E402
import hexjson  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    out = HERE / "profile_example"
    out.mkdir(exist_ok=True)
    for name, (fn, mode) in engine_goldens.GOLDENS.items():
        if args.only and name not in args.only:
            continue
        value = fn()
        a, b = golden_io.render(value, mode), golden_io.render(fn(), mode)
        if hexjson.dumps(a) != hexjson.dumps(b):
            sys.exit(f"{name}: 비결정적 — {hexjson.first_diff(a, b)}")
        golden_io.save(out / f"{name}.json", name, value, mode, force=args.force)  # 확인한 그 값
        print(f"captured {name}")


if __name__ == "__main__":
    main()
