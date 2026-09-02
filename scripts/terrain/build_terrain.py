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

사용:
    python3 scripts/terrain/build_terrain.py \\
        --origin-lat 34.601303 --origin-lon 127.212067 \\
        --tier core:radius=12000,step=30 --tier outer:radius=30000,step=90 \\
        --out data/geo/site-terrain-v1.bin
"""

import argparse
import json
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

    def elevation(self, lon_deg, lat_deg):
        """이중선형 보간 표고 [m]. 타일 경계를 넘어가도 이웃 타일에서 읽는다."""
        n = 2 ** self.zoom
        fx, fy = lonlat_to_tile_frac(lon_deg, lat_deg, self.zoom)
        gx, gy = fx * TILE_PX - 0.5, fy * TILE_PX - 0.5  # 픽셀 중심 보정
        x0, y0 = math.floor(gx), math.floor(gy)
        u, v = gx - x0, gy - y0
        acc = 0.0
        for dy in (0, 1):
            for dx in (0, 1):
                gxi, gyi = x0 + dx, y0 + dy
                tx, px = divmod(gxi, TILE_PX)
                ty, py = divmod(gyi, TILE_PX)
                if not (0 <= tx < n and 0 <= ty < n):
                    return None  # 세계 밖 — 조용히 0으로 메우지 않는다
                wgt = (u if dx else 1 - u) * (v if dy else 1 - v)
                acc += wgt * self._px(tx, ty, px, py)
        return acc


# ---------------------------------------------------------------- 팩 굽기

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

    metas, blobs = [], []
    for name, radius, step in tiers:
        print(f"{name}: 반경 {radius:.0f} m, 간격 {step:.0f} m", flush=True)
        m, b = build_tier(name, radius, step, origin, src)
        metas.append(m)
        blobs.append(b)
        print(f"  표고 {m['elev_min']} ~ {m['elev_max']} m, 커버리지 {m['coverage']:.1%}, "
              f"해면 표본 {m['sea_level_frac']:.1%}", flush=True)

    header = json.dumps({"origin": origin, "tiers": metas}, ensure_ascii=False).encode("utf-8")
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
