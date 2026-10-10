#!/usr/bin/env python3
"""공개 표고 타일 → CLAW 지형 팩 (개발 환경 전용 도구 — 반입물 아님).

3D 월드가 실제 지형 위를 날려면 원점 기준 NED 격자의 표고가 필요하다. 이 스크립트가
그 격자를 굽는다.

## 왜 이 소스인가

국토지리정보원 수치표고모델(5 m)이 목표지만 다운로드가 로그인 + 대용량 전송 에이전트를
요구해 자동화가 불가능하다. 그동안 막히지 않으려고 **계정 없이 받아지는 공개 소스**를 쓴다:

    AWS Terrain Tiles (terrarium 인코딩) — https://registry.opendata.aws/terrain-tiles/

고흥 일대에서 z12 기준 지상 약 31.5 m/px다. NGII 5 m가 도착하면 `--src` 만 바꾸면 되도록
표고 표본 추출을 `sample_elevation` 하나로 모아 두었다.

**출처 표시 의무가 있다** — 팩 헤더의 `source`가 화면 캡션까지 실려 간다.

## 첨탑을 정리한다

원자료에는 **있을 수 없는 지형**이 섞여 있다 — 만·저수지·해안의 물 위에서 레이더 표고가 튄
자리다. 고흥 일대 실측: 폭 1픽셀(31 m)에 높이 300~500 m인 바늘, 만 한가운데의 1픽셀 폭
벽(10픽셀 길이, 최고 314 m), 해안의 2×2 덩어리, 저수지 수면(125 m) 위의 0 m 구멍, 그리고 해안
잡음 지대의 벽·도랑 짝(89 m 옆 0 m)과 높이 30~45 m의 좁은 원뿔. 화면에서는 바다와 논 위에 선
검은 첨탑, 해안 끝의 원뿔과 분화구로 보였다. 그래서 표본을 뜨기 **전에** 원본 픽셀에서 정리한다
(`clean_elevations` — 창 중앙값 판정 `despike`에 꼴로 잡는 세 단계를 잇는다; 판정식과 실측 근거는
각 절의 주석). 단계별로 몇 픽셀을 바꿨는지는 헤더 `cleaning`에 남고 화면 캡션이 그 수를 말한다.

## 의존성

numpy조차 쓰지 않는다. PNG 디코딩은 표준 라이브러리 zlib로 직접 한다(아래 `decode_png`) —
Pillow·GDAL·rasterio를 들이면 폐쇄망 반입 심사 대상이 늘고, 이 스크립트가 그 값을 하지
않는다. 좌표 변환은 **엔진 `claw.env.geodesy`를 그대로 쓴다**(정본이 하나여야 한다).

## 팩 포맷 `claw-terrain v1`

    "CLAWTER1"        8 B   매직 — 버전 불일치는 즉시 거부(조용한 오독 금지)
    u32 header_len    4 B   리틀엔디언
    header            UTF-8 JSON
    tier 데이터        헤더의 tiers 순서대로, rows*cols × u16 LE, row-major,
                      row 0 = n0 (남 → 북), col 0 = e0 (서 → 동)

    표고 = offset + raw * scale,  raw == nodata(65535) 이면 **결측**

    header.cleaning   첨탑 정리 기록(방법·단계·바꾼 원본 픽셀 수). 없으면 정리 전에 구운 팩이고,
                      spires_px가 없으면 꼴 단계 전(v1.86)에 구운 팩이다

사용:
    python3 scripts/terrain/build_terrain.py \\
        --origin-lat 34.601301 --origin-lon 127.212107 \\
        --tier core:radius=12000,step=30 --tier outer:radius=30000,step=90 \\
        --out data/geo/site-terrain-v1.bin
"""

import argparse
import json
import time
from array import array
import ssl
import math
import pathlib
import re
import struct
import sys
import urllib.request
import zlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "engine"))
from claw.env.constants import WGS84_A  # noqa: E402
from claw.env.geodesy import ned_to_geodetic  # noqa: E402  (경로 주입 뒤에 와야 한다)

TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
SOURCE_NOTE = ("AWS Terrain Tiles (terrarium) — SRTM/NED 등 공개 표고 집합. "
               "국토지리정보원 5 m DEM 도착 전까지의 대체 자료다.")
TILE_PX = 256
NODATA = 65535
SCALE = 0.05      # [m] 양자화 간격 — u16으로 3,276 m 범위, 오차 ±2.5 cm
OFFSET = -100.0   # [m] 최저 표현 표고

# terrarium은 바다에 수심을 담는다. 비행 시뮬의 지면으로는 해저를 그리는 것이 틀린
# 그림이라 해수면에서 자른다 — **자른 사실을 헤더에 남긴다**(캡션이 그것을 말한다).
SEA_LEVEL = 0.0


def ssl_context():
    """HTTPS 검증용 컨텍스트.

    macOS 프레임워크 파이썬은 CA 번들이 비어 있어 기본 컨텍스트가
    CERTIFICATE_VERIFY_FAILED로 죽는다(curl은 되는데 파이썬만 안 되는 그 증상).
    있는 번들을 순서대로 찾아 쓰고, **검증을 끄지는 않는다** — 개발 도구라도
    받은 파일이 진짜인지 확인하지 않을 이유가 없다.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    for path in ("/etc/ssl/cert.pem", "/usr/local/etc/openssl/cert.pem"):
        if pathlib.Path(path).exists():
            return ssl.create_default_context(cafile=path)
    raise SystemExit(
        "CA 번들을 찾지 못했다. 다음 중 하나로 해결한다:\n"
        "  pip install certifi\n"
        "  SSL_CERT_FILE=/etc/ssl/cert.pem python3 scripts/terrain/build_terrain.py ...\n"
        "  또는 '/Applications/Python 3.x/Install Certificates.command' 실행"
    )


# ---------------------------------------------------------------- PNG (stdlib만)

def decode_png(raw):
    """8비트 PNG → (width, height, channels, rows[bytes]). 표준 zlib만 쓴다."""
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("PNG 시그니처가 아니다")
    pos, idat, meta = 8, b"", None
    while pos < len(raw):
        ln = struct.unpack(">I", raw[pos:pos + 4])[0]
        typ = raw[pos + 4:pos + 8]
        body = raw[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            meta = struct.unpack(">IIBB", body[:10])
        elif typ == b"IDAT":
            idat += body
        pos += 12 + ln
    w, h, depth, color = meta
    if depth != 8:
        raise ValueError(f"8비트 PNG만 지원한다 (bitdepth={depth})")
    ch = {0: 1, 2: 3, 4: 2, 6: 4}[color]
    stride = w * ch
    data = zlib.decompress(idat)
    prev = bytearray(stride)
    rows, p = [], 0
    for _ in range(h):
        filt = data[p]
        p += 1
        line = bytearray(data[p:p + stride])
        p += stride
        for i in range(stride):
            a = line[i - ch] if i >= ch else 0
            b = prev[i]
            c = prev[i - ch] if i >= ch else 0
            if filt == 1:
                line[i] = (line[i] + a) & 255
            elif filt == 2:
                line[i] = (line[i] + b) & 255
            elif filt == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif filt == 4:
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        rows.append(bytes(line))
        prev = line
    return w, h, ch, rows


# ---------------------------------------------------------------- 첨탑 정리

# 판정은 **창 중앙값에서의 이탈**을 그 창의 강건 산포(MAD)와 견준다:
#
#     |z − med| > max(바닥 문턱, k · 1.4826 · MAD)      →  z를 med로 바꾼다
#
# 산지는 이 식에 걸리지 않는다. 실제 봉우리는 5×5 중앙값에서 최대 28 m만 벗어나고(고지대
# 99.9 백분위 17 m), 그 창의 산포도 커서 문턱이 함께 오른다. 첨탑은 물·평지 위에 서 있어
# 산포가 1 m 안팎인데 이탈이 수백 m다. 고흥 팩 실측: 표고 150 m 넘는 산지에서 바뀐 픽셀 0개,
# 바뀐 198픽셀은 전부 해안선·저수지 가장자리였다(그중 6개가 저수지 수면 위 125 m 고지).
#
# 창을 둘 쓴다. 5×5는 바늘·1픽셀 벽·2×2 덩어리까지 잡고, 9×9는 해안의 잡음 덩어리 —
# 5×5 중앙값을 오염시킬 만큼 큰 것 — 를 잡는다. 하나를 바꾸면 이웃 창의 산포가 줄어 덩어리
# 안쪽이 드러나므로, 바뀐 것이 없을 때까지 되풀이한다. 갱신은 회차 단위(야코비)라 순서와
# 무관하게 결정적이다 — 같은 캐시·같은 원점이면 같은 팩이 나온다는 약속(data/README.md)이 산다.
#
# **해수면 자르기 뒤에** 정리한다. 화면이 그리는 것이 자른 표고이고, 바다(0 m) 위의 첨탑은
# 산포 0인 평면 위에 서 있어 가장 확실하게 걸린다.
#
# 이 판정은 문턱 아래를 남긴다 — 바닥 20 m보다 낮은 1픽셀 돌출(바다 위 17 m 점 같은 것). 그것은 아래
# 「꼴로 잡는 결함」의 좁은 기둥 단계가 맡는다: 31 m 자료로는 그 크기의 실제 암초와 잡음을 가를 수 없고,
# 그대로 그리면 바다 위 바늘이 된다. 폭 3칸(약 95 m) 넘는 섬은 거기서도 남는다.
# 단 **지운 것에 맞닿은 꼬리**는 낮은 문턱(8 m)으로 한 번 더 본다(`DESPIKE_TAIL`) — 만의 벽을
# 지우고 나니 벽 끝 12 m가 바다 위 작은 섬으로 남았다. 지운 픽셀의 8이웃만 보므로 홀로 선
# 실제 암초는 이 단계에 닿지 않는다(경계 문턱 두 개를 쓰는 캐니 윤곽선의 이력 판정과 같다).

MAD_SIGMA = 1.4826  # 정규분포에서 MAD → 표준편차
DESPIKE_STAGES = (
    # (창 한 변 [px], 바닥 문턱 [m], MAD 배수)
    (5, 20.0, 5.0),
    (9, 40.0, 5.0),
    (5, 20.0, 5.0),
)
DESPIKE_TAIL = (5, 8.0, 5.0)  # 지운 픽셀의 8이웃에만 — 위 주석
DESPIKE_MAX_PASSES = 8


def _window_values(grid, width, height, r, c, half):
    """(r, c) 둘레 (2·half+1)² 창의 값 — 가장자리는 끝값을 되풀이한다(numpy pad "edge")."""
    vals = []
    for rr in range(r - half, r + half + 1):
        ri = 0 if rr < 0 else (height - 1 if rr >= height else rr)
        row = ri * width
        for cc in range(c - half, c + half + 1):
            ci = 0 if cc < 0 else (width - 1 if cc >= width else cc)
            vals.append(grid[row + ci])
    return vals


def _neighborhood(indices, width, height, half):
    """인덱스들의 ±half 창을 합친 집합 — 그 창 안 픽셀만 판정이 바뀔 수 있다."""
    out = set()
    for i in indices:
        r, c = divmod(i, width)
        for rr in range(max(r - half, 0), min(r + half, height - 1) + 1):
            row = rr * width
            for cc in range(max(c - half, 0), min(c + half, width - 1) + 1):
                out.add(row + cc)
    return out


def _screen(grid, width, height, thresh):
    """4이웃 평균과 thresh 넘게 다른 픽셀 — 강건 판정을 돌릴 후보의 씨앗."""
    cand = set()
    for r in range(1, height - 1):
        row = r * width
        up = row - width
        dn = row + width
        for c in range(1, width - 1):
            i = row + c
            z = grid[i]
            m4 = (grid[i - 1] + grid[i + 1] + grid[up + c] + grid[dn + c]) * 0.25
            if z - m4 > thresh or m4 - z > thresh:
                cand.add(i)
    return cand


def _replace_pass(grid, width, height, cand, half, floor, k_mad):
    """후보 각각을 창 중앙값과 견줘 바꿀 것을 모은다 — 갱신은 호출측이 한꺼번에(회차 단위)."""
    repl = {}
    for i in cand:
        r, c = divmod(i, width)
        vals = _window_values(grid, width, height, r, c, half)
        vals.sort()
        mid = len(vals) // 2
        med = vals[mid]
        devs = sorted(abs(v - med) for v in vals)
        if abs(grid[i] - med) > max(floor, k_mad * MAD_SIGMA * devs[mid]):
            repl[i] = med
    return repl


def despike(grid, width, height, stages=DESPIKE_STAGES, tail=DESPIKE_TAIL):
    """행 우선 표고 `grid`의 첨탑을 창 중앙값으로 바꾼다 — **제자리**에서.

    돌려주는 것: (바뀐 픽셀 인덱스 집합, 단계별 교체 횟수 목록 — 마지막이 꼬리 단계).

    전 픽셀에 중앙값을 내면 파이썬으로 수십 초라, 후보만 판정한다. 후보는 4이웃 평균과
    (가장 낮은 바닥 문턱)/4 넘게 다른 픽셀과 그 창 반경 안이다. **이것이 전면 탐색과 같은
    답을 내는 이유**: 바닥 문턱보다 높은 덩어리의 가장자리 픽셀은 4이웃 중 하나 이상이
    바탕이라 평균과 (높이)/4 이상 벌어져 반드시 씨앗이 되고, 창 반경만큼 넓히면 그 창에
    드는 안쪽까지 덮는다(창보다 큰 덩어리는 어차피 중앙값이 못 잡는다). 고흥 팩에서 numpy
    전면 탐색과 비트 단위로 같았다. 다음 회차는 바뀐 픽셀의 창 반경 안만 다시 본다 —
    그 밖은 창이 그대로라 판정도 그대로다.
    """
    seeds = _screen(grid, width, height, min(f for _, f, _ in stages) / 4.0)
    changed = set()
    per_stage = []
    for k, floor, k_mad in stages:
        half = k // 2
        cand = _neighborhood(seeds | changed, width, height, half)
        replaced = 0
        for _ in range(DESPIKE_MAX_PASSES):
            repl = _replace_pass(grid, width, height, cand, half, floor, k_mad)
            if not repl:
                break
            for i, med in repl.items():  # 회차 단위 갱신 — 순서와 무관하다
                grid[i] = med
            replaced += len(repl)
            changed.update(repl)
            cand = _neighborhood(repl, width, height, half)
        per_stage.append(replaced)
    # 꼬리 — 지운 픽셀의 8이웃만, 낮은 문턱으로. 지울 때마다 그 8이웃으로 번진다.
    k, floor, k_mad = tail
    replaced = 0
    frontier = changed
    for _ in range(DESPIKE_MAX_PASSES):
        repl = _replace_pass(grid, width, height,
                             _neighborhood(frontier, width, height, 1) - changed,
                             k // 2, floor, k_mad)
        if not repl:
            break
        for i, med in repl.items():
            grid[i] = med
        replaced += len(repl)
        changed.update(repl)
        frontier = set(repl)
    per_stage.append(replaced)
    return changed, per_stage


# ---- 꼴로 잡는 결함 — 벽·도랑, 좁은 기둥, 잡음 지대
#
# 위 판정(창 중앙값 이탈 > 산포의 5배)은 **산포가 큰 자리에서 눈이 먼다.** 해안의 잡음 지대에는
# 폭 1픽셀 벽(89 m)과 바로 옆 0 m 도랑이 짝으로 붙어 있는데, 도랑이 창의 산포를 키워 벽이 문턱을
# 빠져나갔다. 화면에서는 해안 끝의 뾰족한 원뿔과 바위색 분화구로 보였다(사용자 지적 「첨탑이 왜
# 남아 있나」, 2026-10-10). 그래서 산포가 아니라 **꼴**로 잡는 세 단계를 뒤에 잇는다:
#
#   벽·도랑   가로지르는 방향의 2차 차분이 35 m를 넘으면 — 산지 실측 최대 31.5 m(99.99 백분위
#             19.5 m), 결함은 100 m까지. 높이 70 m 넘는 절벽만 이 문턱에 닿는다(가장자리 차분이
#             단차의 절반) — 30 m 격자의 원자료에는 그런 절벽이 없다.
#   좁은 기둥 둘레 고리(5×5 테두리)보다 솟았는데 5×5 창 안에서 솟은 칸이 4칸 이하이고(폭 1~2칸),
#             고리는 평평하다 — 평지·바다 위에 혼자 선 기둥. 폭 3칸(약 95 m) 넘는 섬은 남는다. 처음엔
#             「3×3 중앙값보다 솟았나」로 좁음을 쟀는데, 정사각 섬의 귀퉁이가 그 판정에 걸려 되풀이할수록
#             섬이 통째로 깎였다(시험이 잡았다). 둘레가 기운 산지는 고리가 평평하지 않아 안 걸린다.
#   잡음 지대 위 단계들이 고친 자리와 저지대의 들쭉날쭉한 픽셀 둘레 3픽셀(약 95 m)만 5×5 중앙값으로 두 번
#             다듬는다 — 결함 옆의 잔해. 「들쭉날쭉」은 5×5 창의 고주파(|z − 3×3 중앙값|)의 **중앙값**이
#             3 m를 넘는 것이다 — 깨끗한 계단(섬 가장자리)은 귀퉁이 몇 칸만 고주파라 중앙값이 0이다.
#             처음엔 「3×3 중앙값과 10 m 넘게 다르다」로 씨앗을 뿌렸는데 작은 섬의 귀퉁이가 걸려 섬이
#             통째로 다듬어졌다(시험이 잡았다). 결함이 없는 곳은 원본 그대로다.
#
# 기둥·잡음 지대는 **저지대에서만**(둘레 고리 중앙값 60 m 아래) 돈다. 해안 잡음이 사는 곳이 거기고,
# 산지에서 돌리면 실제 언덕 꼭대기가 근처 웅덩이를 따라 다듬어졌다(고흥 외곽 223 m 봉우리가 10 m
# 깎인 것을 보고 막았다). 산지의 결함은 위의 창 중앙값 판정이 이미 잡는다(저수지 수면 위 354 m).

WALL_D2_M = 35.0
SPIRE_REL_M = 6.0          # 둘레 고리보다 이만큼은 솟아야(파여야) 기둥(구멍)이다
SPIRE_MAX_PX = 4           # 5×5 창에서 「솟은 칸」(고리보다 기둥 높이의 절반 넘게)이 이 이하면 좁다
SPIRE_FLAT_RATIO = 0.25    # 고리의 MAD가 기둥 높이의 이 비율 아래 — 둘레가 평평하다
ZONE_ROUGH_M = 3.0         # 잡음 지대 씨앗 — 5×5 창의 고주파 중앙값이 이만큼 넘는 픽셀이
SPIKY_LOW_M = 60.0         # 둘레 고리 중앙값이 이 아래인 저지대에 있으면
ZONE_RADIUS_PX = 3
ZONE_PASSES = 2
_DIRS = ((-1, 0, 1, 0), (0, -1, 0, 1), (-1, -1, 1, 1), (-1, 1, 1, -1))   # 세로·가로·두 대각


def _median(vals):
    """중앙값 — 짝수 개면 가운데 둘의 평균(numpy와 같은 정의). vals는 제자리에서 정렬된다."""
    vals.sort()
    n = len(vals)
    m = n // 2
    return vals[m] if n % 2 else 0.5 * (vals[m - 1] + vals[m])


def _at(grid, width, height, r, c):
    ri = 0 if r < 0 else (height - 1 if r >= height else r)
    ci = 0 if c < 0 else (width - 1 if c >= width else c)
    return grid[ri * width + ci]


def _d2_across(grid, width, height, i):
    """네 방향 2차 차분 중 절댓값이 가장 큰 것 — 벽이면 +, 도랑이면 −."""
    r, c = divmod(i, width)
    z = grid[i]
    best = 0.0
    for dr1, dc1, dr2, dc2 in _DIRS:
        v = z - 0.5 * (_at(grid, width, height, r + dr1, c + dc1)
                       + _at(grid, width, height, r + dr2, c + dc2))
        if abs(v) > abs(best):
            best = v
    return best


def _med3(grid, width, height, r, c):
    return _median([_at(grid, width, height, r + dr, c + dc)
                    for dr in (-1, 0, 1) for dc in (-1, 0, 1)])


def _ring(grid, width, height, r, c):
    """5×5에서 가운데 3×3을 뺀 고리 16칸의 (중앙값, MAD)."""
    vals = [_at(grid, width, height, r + dr, c + dc)
            for dr in range(-2, 3) for dc in range(-2, 3) if max(abs(dr), abs(dc)) == 2]
    med = _median(vals[:])
    return med, _median([abs(v - med) for v in vals])


def remove_walls(grid, width, height, seeds):
    """1픽셀 벽·도랑 — 가로지르는 2차 차분이 WALL_D2_M을 넘는 픽셀을, 걸린 픽셀을 뺀 5×5 중앙값으로.

    걸린 픽셀끼리는 서로의 중앙값에 넣지 않는다 — 벽과 도랑이 짝이라 서로를 끌어당긴다."""
    changed = set()
    cand = _neighborhood(seeds, width, height, 1)
    for _ in range(DESPIKE_MAX_PASSES):
        flagged = {i for i in cand if abs(_d2_across(grid, width, height, i)) > WALL_D2_M}
        if not flagged:
            break
        repl = {}
        for i in flagged:
            r, c = divmod(i, width)
            vals = []
            for rr in range(r - 2, r + 3):
                ri = 0 if rr < 0 else (height - 1 if rr >= height else rr)
                for cc in range(c - 2, c + 3):
                    ci = 0 if cc < 0 else (width - 1 if cc >= width else cc)
                    j = ri * width + ci
                    if j not in flagged:
                        vals.append(grid[j])
            if vals:
                repl[i] = _median(vals)
        if not repl:
            break
        for i, m in repl.items():  # 회차 단위 갱신
            grid[i] = m
        changed.update(repl)
        cand = _neighborhood(repl, width, height, 2)
    return changed


def remove_spires(grid, width, height, seeds):
    """평지·바다 위의 좁은 기둥(구멍) — 둘레 고리 중앙값으로. 판정은 위 「꼴로 잡는 결함」 절."""
    changed = set()
    cand = _neighborhood(seeds, width, height, 2)
    for _ in range(DESPIKE_MAX_PASSES):
        repl = {}
        for i in cand:
            r, c = divmod(i, width)
            z = grid[i]
            ring, rmad = _ring(grid, width, height, r, c)
            if ring >= SPIKY_LOW_M:
                continue  # 산지 — 위 절의 끝 문단
            rel = z - ring
            if abs(rel) <= SPIRE_REL_M or rmad >= SPIRE_FLAT_RATIO * abs(rel):
                continue
            half = ring + 0.5 * rel  # 기둥(구멍)의 허리 높이 — 이보다 솟은(파인) 칸을 센다
            win = _window_values(grid, width, height, r, c, 2)
            n_out = sum(1 for v in win if (v > half if rel > 0 else v < half))
            if n_out <= SPIRE_MAX_PX:
                repl[i] = ring
        if not repl:
            break
        for i, m in repl.items():
            grid[i] = m
        changed.update(repl)
        cand = _neighborhood(repl, width, height, 2)
    return changed


def smooth_zones(grid, width, height, fixed, screened):
    """결함 둘레만 다듬는다 — 고친 픽셀과 저지대의 뾰족한 픽셀에서 ZONE_RADIUS_PX 안을 5×5 중앙값으로.
    돌려주는 것은 다듬은 지대의 픽셀 집합."""
    seeds = set(fixed)
    hf = {}  # |z − 3×3 중앙값| 캐시 — 이웃 창들이 같은 칸을 여러 번 묻는다

    def high_freq(rr, cc):
        rr = 0 if rr < 0 else (height - 1 if rr >= height else rr)
        cc = 0 if cc < 0 else (width - 1 if cc >= width else cc)
        k = rr * width + cc
        if k not in hf:
            hf[k] = abs(grid[k] - _med3(grid, width, height, rr, cc))
        return hf[k]

    for i in screened:
        r, c = divmod(i, width)
        rough = _median([high_freq(r + dr, c + dc) for dr in range(-2, 3) for dc in range(-2, 3)])
        if rough > ZONE_ROUGH_M and _ring(grid, width, height, r, c)[0] < SPIKY_LOW_M:
            seeds.add(i)
    zone = {i for i in _neighborhood(seeds, width, height, ZONE_RADIUS_PX)
            if _ring(grid, width, height, *divmod(i, width))[0] < SPIKY_LOW_M}   # 저지대만
    for _ in range(ZONE_PASSES):
        repl = {}
        for i in zone:
            r, c = divmod(i, width)
            repl[i] = _median(_window_values(grid, width, height, r, c, 2))
        for i, m in repl.items():  # 회차 단위 갱신
            grid[i] = m
    return zone


def clean_elevations(grid, width, height):
    """정리 전 과정 — 창 중앙값(despike) → 벽·도랑 → 좁은 기둥 → 잡음 지대. 제자리에서.

    돌려주는 것: (바뀐 픽셀 집합, 단계별 수 dict). 순서가 의미를 갖는다 — 벽을 지워야 그 옆 기둥의
    둘레 고리가 평평해져 기둥 판정에 걸리고, 잡음 지대는 앞 단계들이 찾은 자리에서 자란다."""
    seeds = _screen(grid, width, height, 2.0)
    changed, per_stage = despike(grid, width, height)
    walls = remove_walls(grid, width, height, seeds | changed)
    spires = remove_spires(grid, width, height, seeds | changed | walls)
    fixed = changed | walls | spires
    zone = smooth_zones(grid, width, height, fixed, seeds)
    return fixed | zone, {
        "despike": per_stage, "walls": len(walls), "spires": len(spires), "zone_px": len(zone),
    }


# ---------------------------------------------------------------- 타일 격자

def lonlat_to_tile_frac(lon_deg, lat_deg, z):
    """(경도, 위도) → 세계 타일 좌표(소수). Web Mercator, terrarium 규약."""
    n = 2 ** z
    lat = math.radians(lat_deg)
    x = (lon_deg + 180.0) / 360.0 * n
    y = (1.0 - math.log(math.tan(lat) + 1.0 / math.cos(lat)) / math.pi) / 2.0 * n
    return x, y


def ground_m_per_px(lat_deg, z):
    """줌 z에서의 **지상** 해상도 [m/px] — 투영 해상도에 cos φ를 곱한 것.

    투영 미터와 지상 미터를 혼동하면 위도 34.6°에서 21.5% 어긋난다
    (웹 lib/geo.js가 같은 함정을 테스트로 못박아 두었다).

    z=0 해상도는 2πa/256에서 나온다 — 상수를 적어 넣지 않는다(규약 §3)."""
    z0 = 2.0 * math.pi * WGS84_A / TILE_PX
    return z0 * math.cos(math.radians(lat_deg)) / 2 ** z


class TileSource:
    """terrarium 타일을 받아 캐시하고 표고를 이중선형 보간해 낸다."""

    def __init__(self, zoom, cache_dir, quiet=False):
        self.zoom = zoom
        self.cache = pathlib.Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.tiles = {}
        self.fetched = 0
        self.quiet = quiet
        self.ssl = ssl_context()
        # 정리한 표고 창 (gx0, gy0, w, h, grid) — `prepare`가 채운다. 채운 뒤에는 표본을
        # **이 창에서만** 읽는다(창 밖 표본은 정리 안 된 값이라 조용히 섞지 않고 멈춘다).
        self.window = None

    def _tile(self, tx, ty):
        key = (tx, ty)
        if key in self.tiles:
            return self.tiles[key]
        path = self.cache / f"terrarium_{self.zoom}_{tx}_{ty}.png"
        if not path.exists():
            url = TILE_URL.format(z=self.zoom, x=tx, y=ty)
            # .part로 받고 rename — 중간에 끊기면 잘린 PNG가 캐시에 영구히 남아 이후
            # 모든 실행이 decode_png에서 죽는데, 파일 하나를 지우면 된다는 힌트가 없다.
            # 느린 회선에서 수십 장을 받는 동안이 바로 사람이 Ctrl-C를 누르는 때다.
            tmp = path.with_suffix(".part")
            with urllib.request.urlopen(url, timeout=60, context=self.ssl) as r:
                tmp.write_bytes(r.read())
            tmp.replace(path)
            self.fetched += 1
            if not self.quiet:
                print(f"  받음 {path.name}", flush=True)
        w, h, ch, rows = decode_png(path.read_bytes())
        self.tiles[key] = (w, h, ch, rows)
        return self.tiles[key]

    def _px(self, tx, ty, px, py):
        w, h, ch, rows = self._tile(tx, ty)
        o = px * ch
        r, g, b = rows[py][o], rows[py][o + 1], rows[py][o + 2]
        z = (r * 256 + g + b / 256.0) - 32768.0
        # **보간 전에** 자른다. 뒤에 자르면 해안 육지 표본이 이웃 수심(−30 m 같은 값)과
        # 섞여 낮은 쪽으로 끌려가는데, 그 결과는 양수라 "잘렸다"는 집계에도 안 잡힌다 —
        # 헤더가 기록하는 비율이 캡션이 말하는 뜻과 어긋나게 된다.
        return max(z, SEA_LEVEL)

    def prepare(self, gx0, gy0, gx1, gy1):
        """세계 픽셀 창 [gx0..gx1] × [gy0..gy1]을 읽어 첨탑을 정리해 둔다.

        창은 모든 티어의 표본을 덮어야 한다 — `sample_window`가 여유를 붙여 잡는다.
        돌려주는 것은 헤더 `cleaning`에 실을 기록이다."""
        w, h = gx1 - gx0 + 1, gy1 - gy0 + 1
        grid = array("d", bytes(8 * w * h))
        n = 2 ** self.zoom
        for ty in range(gy0 // TILE_PX, gy1 // TILE_PX + 1):
            for tx in range(gx0 // TILE_PX, gx1 // TILE_PX + 1):
                if not (0 <= tx < n and 0 <= ty < n):
                    raise SystemExit(f"표고 창이 세계 밖으로 나간다: 타일 {tx},{ty}")
                _, _, ch, rows = self._tile(tx, ty)
                px0, px1 = max(gx0 - tx * TILE_PX, 0), min(gx1 - tx * TILE_PX, TILE_PX - 1)
                py0, py1 = max(gy0 - ty * TILE_PX, 0), min(gy1 - ty * TILE_PX, TILE_PX - 1)
                for py in range(py0, py1 + 1):
                    row = rows[py]
                    base = (ty * TILE_PX + py - gy0) * w + (tx * TILE_PX - gx0)
                    for px in range(px0, px1 + 1):
                        o = px * ch
                        z = (row[o] * 256 + row[o + 1] + row[o + 2] / 256.0) - 32768.0
                        grid[base + px] = max(z, SEA_LEVEL)  # _px와 같은 자르기
        t0 = time.monotonic()
        changed, stages = clean_elevations(grid, w, h)
        self.window = (gx0, gy0, w, h, grid)
        return {
            "method": "창 중앙값·MAD 첨탑 → 벽·도랑(2차 차분) → 좁은 기둥 → 잡음 지대 다듬기",
            "replaced_px": len(changed),
            "per_stage": stages["despike"],
            "walls_px": stages["walls"],
            "spires_px": stages["spires"],
            "zone_px": stages["zone_px"],
            "stages": [{"window_px": k, "floor_m": f, "k_mad": m} for k, f, m in DESPIKE_STAGES],
            "tail": {"window_px": DESPIKE_TAIL[0], "floor_m": DESPIKE_TAIL[1],
                     "k_mad": DESPIKE_TAIL[2], "scope": "지운 픽셀의 8이웃"},
            "window_px": [w, h],
            "seconds": round(time.monotonic() - t0, 1),
        }

    def _z(self, gxi, gyi):
        """세계 픽셀 → 표고. 창이 있으면 정리한 값, 없으면 원본(해수면에서 자른 값)."""
        if self.window is None:
            n = 2 ** self.zoom
            tx, px = divmod(gxi, TILE_PX)
            ty, py = divmod(gyi, TILE_PX)
            if not (0 <= tx < n and 0 <= ty < n):
                return None  # 세계 밖 — 조용히 0으로 메우지 않는다
            return self._px(tx, ty, px, py)
        x0, y0, w, h, grid = self.window
        c, r = gxi - x0, gyi - y0
        if not (0 <= c < w and 0 <= r < h):
            raise SystemExit(f"표고 창 밖의 표본 ({gxi}, {gyi}) — 창 계산(sample_window)이 티어를 못 덮는다")
        return grid[r * w + c]

    def elevation(self, lon_deg, lat_deg):
        """이중선형 보간 표고 [m]. 타일 경계를 넘어가도 이웃 타일에서 읽는다."""
        fx, fy = lonlat_to_tile_frac(lon_deg, lat_deg, self.zoom)
        gx, gy = fx * TILE_PX - 0.5, fy * TILE_PX - 0.5  # 픽셀 중심 보정
        x0, y0 = math.floor(gx), math.floor(gy)
        u, v = gx - x0, gy - y0
        acc = 0.0
        for dy in (0, 1):
            for dx in (0, 1):
                z = self._z(x0 + dx, y0 + dy)
                if z is None:
                    return None
                acc += (u if dx else 1 - u) * (v if dy else 1 - v) * z
        return acc


# ---------------------------------------------------------------- 팩 굽기

# 표본 창의 여유 [px] — 이중선형 이웃 1 + 가장 큰 정리 창 반경 4 + 되풀이 몇 회차의 번짐.
# 창 가장자리 픽셀은 판정 창이 끝값으로 메워지므로, 실제 표본이 그 띠에 닿지 않게 넉넉히 둔다.
WINDOW_MARGIN_PX = 12


def sample_window(tiers, origin, zoom, margin=WINDOW_MARGIN_PX):
    """모든 티어 표본을 덮는 세계 픽셀 창 (gx0, gy0, gx1, gy1) — 양 끝 포함.

    NED 사각형의 변을 따라 점을 찍어 투영한다. 60 km 안에서 변은 메르카토르 픽셀 공간에서
    거의 곧지만, 모서리만 보면 휜 만큼 모자랄 수 있어 변마다 17점을 본다."""
    lat0, lon0 = math.radians(origin["lat_deg"]), math.radians(origin["lon_deg"])
    xs, ys = [], []
    for _, radius, step in tiers:
        ext = int(round(radius / step)) * step  # build_tier의 n0·e0와 같은 끝
        for k in range(17):
            f = -ext + 2.0 * ext * k / 16
            for n, e in ((f, -ext), (f, ext), (-ext, f), (ext, f)):
                lat, lon = ned_to_geodetic(n, e, lat0, lon0, origin["h_ref"])
                fx, fy = lonlat_to_tile_frac(math.degrees(lon), math.degrees(lat), zoom)
                xs.append(fx * TILE_PX - 0.5)
                ys.append(fy * TILE_PX - 0.5)
    return (math.floor(min(xs)) - margin, math.floor(min(ys)) - margin,
            math.ceil(max(xs)) + 1 + margin, math.ceil(max(ys)) + 1 + margin)

def build_tier(name, radius, step, origin, src):
    """원점 기준 정사각 NED 격자 하나를 굽는다. 남→북, 서→동 순."""
    half = int(round(radius / step))
    rows = cols = 2 * half + 1
    n0 = e0 = -half * step
    lat0, lon0 = math.radians(origin["lat_deg"]), math.radians(origin["lon_deg"])
    h_ref = origin["h_ref"]

    buf = bytearray()
    valid = sea = 0
    lo, hi = math.inf, -math.inf
    for r in range(rows):
        n = n0 + r * step
        for c in range(cols):
            e = e0 + c * step
            lat, lon = ned_to_geodetic(n, e, lat0, lon0, h_ref)
            z = src.elevation(math.degrees(lon), math.degrees(lat))
            if z is None:
                buf += struct.pack("<H", NODATA)
                continue
            if z <= SEA_LEVEL + 1e-9:
                sea += 1  # 해수면에 놓인 표본 (자르기는 _px에서 픽셀 단위로 이미 끝났다)
            raw = int(round((z - OFFSET) / SCALE))
            if not (0 <= raw < NODATA):
                buf += struct.pack("<H", NODATA)  # 표현 범위 밖 — 결측으로 둔다
                continue
            buf += struct.pack("<H", raw)
            valid += 1
            lo, hi = min(lo, z), max(hi, z)
        if r % 100 == 0:
            print(f"  {name}: {r}/{rows} 행", flush=True)

    total = rows * cols
    meta = {
        "name": name, "n0": float(n0), "e0": float(e0), "step": float(step),
        "rows": rows, "cols": cols,
        "encoding": "u16", "scale": SCALE, "offset": OFFSET, "nodata": NODATA,
        "coverage": valid / total,
        "elev_min": None if lo is math.inf else round(lo, 2),
        "elev_max": None if hi == -math.inf else round(hi, 2),
        # **표본이 해수면 높이(0 m)에 놓인 비율**이다 — "얼마나 잘렸나"도 "얼마가
        # 바다인가"도 아니다. 자르기는 _px에서 원본 픽셀마다 하므로 기여 픽셀 하나만
        # 바다인 해안 표본은 양수로 나와 빠지고, 반대로 **간척지처럼 표고가 정확히
        # 0인 육지는 들어간다**(고흥만에서 이 수가 8.7%→36.8%로 뛴 이유가 그것이다).
        # 이 자료만으로 바다와 0 m 육지를 가릴 수 없으므로 캡션도 그렇게 적는다.
        "sea_level_frac": sea / total,
        "source": SOURCE_NOTE,
        "source_res_m": round(ground_m_per_px(origin["lat_deg"], src.zoom), 2),
    }
    return meta, bytes(buf)


def main():
    ap = argparse.ArgumentParser(description="공개 표고 타일 → CLAW 지형 팩")
    ap.add_argument("--origin-lat", type=float, required=True)
    ap.add_argument("--origin-lon", type=float, required=True)
    ap.add_argument("--h-ref", type=float, default=0.0,
                    help="곡률반경 평가 기준 고도 [m] — 보통 활주로 표고")
    ap.add_argument("--tier", action="append", required=True,
                    metavar="NAME:radius=R,step=S", help="여러 번 줄 수 있다")
    ap.add_argument("--zoom", type=int, default=12, help="terrarium 줌 (기본 12 ≈ 31 m/px)")
    ap.add_argument("--cache", default="data/geo/raw", help="원본 타일 캐시")
    ap.add_argument("--out", required=True, help="*-terrain-*.bin (서버 인식 규약)")
    ap.add_argument("--budget-mb", type=float, default=8.0,
                    help="넘으면 굽지 않고 필요한 step을 역산해 알려준다")
    args = ap.parse_args()

    tiers = []
    for spec in args.tier:
        name, _, rest = spec.partition(":")
        kv = dict(p.split("=") for p in rest.split(","))
        tiers.append((name, float(kv["radius"]), float(kv["step"])))

    # 서버는 *-terrain-*.bin만 목록에 올리고(routes/world.py `_terrain_packs`), 그 위에
    # ASCII 화이트리스트(`_NAME_OK`)로 한 번 더 거른다. 패턴만 보면 `고흥-terrain-v1.bin`이
    # 구워지고 → 매니페스트에도 실리고 → 다운로드에서만 422가 난다. 두 조건을 여기서 같이
    # 건다 — 안 그러면 "방금 한 일을 다시 하라"는 안내를 받는 상황의 절반만 막는 셈이다.
    if not re.fullmatch(r"[A-Za-z0-9._-]*-terrain-[A-Za-z0-9._-]*\.bin",
                        pathlib.Path(args.out).name):
        print(f"--out 파일명은 ASCII로 *-terrain-*.bin 이어야 서버가 인식한다: {args.out}",
              file=sys.stderr)
        return 1

    est = sum((2 * int(round(r / s)) + 1) ** 2 * 2 for _, r, s in tiers) / 1e6
    if est > args.budget_mb:
        print(f"예산 초과: {est:.1f} MB > {args.budget_mb} MB", file=sys.stderr)
        for name, r, s in tiers:
            need = math.sqrt((2 * r) ** 2 * 2 / (args.budget_mb * 1e6 / len(tiers)))
            print(f"  {name}: step을 {need:.0f} m 이상으로", file=sys.stderr)
        return 1

    origin = {"lat_deg": args.origin_lat, "lon_deg": args.origin_lon,
              "h_ref": args.h_ref, "datum": "wgs84"}
    src = TileSource(args.zoom, args.cache)

    # 표본을 뜨기 **전에** 원본 픽셀에서 첨탑을 정리한다(위 「첨탑 정리」 절).
    gx0, gy0, gx1, gy1 = sample_window(tiers, origin, args.zoom)
    print(f"표고 창: {gx1 - gx0 + 1}×{gy1 - gy0 + 1} px — 읽고 첨탑을 정리하는 중", flush=True)
    cleaning = src.prepare(gx0, gy0, gx1, gy1)
    print(f"  첨탑 정리: 원본 픽셀 {cleaning['replaced_px']}개 — 바늘 {sum(cleaning['per_stage'])} "
          f"(단계별 {cleaning['per_stage']}) · 벽·도랑 {cleaning['walls_px']} · 좁은 기둥 {cleaning['spires_px']} "
          f"· 해안 잡음 지대 {cleaning['zone_px']} ({cleaning['seconds']} s)", flush=True)

    metas, blobs = [], []
    for name, radius, step in tiers:
        print(f"{name}: 반경 {radius:.0f} m, 간격 {step:.0f} m", flush=True)
        m, b = build_tier(name, radius, step, origin, src)
        metas.append(m)
        blobs.append(b)
        print(f"  표고 {m['elev_min']} ~ {m['elev_max']} m, 커버리지 {m['coverage']:.1%}, "
              f"해면 표본 {m['sea_level_frac']:.1%}", flush=True)

    header = json.dumps({"origin": origin, "cleaning": cleaning, "tiers": metas},
                        ensure_ascii=False).encode("utf-8")
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as f:
        f.write(b"CLAWTER1")
        f.write(struct.pack("<I", len(header)))
        f.write(header)
        for b in blobs:
            f.write(b)
    print(f"\n{out} — {out.stat().st_size / 1e6:.2f} MB (타일 {src.fetched}장 새로 받음)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
