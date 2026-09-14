"""파라미터 이미지 — 비행 전에 장입하는 제어법칙 값의 바이너리 형식 v1 (07 §6.1 정본).

생성 C에는 구조만 있고 값은 없다(codegen/emit_c.py 머리말). 이 모듈이 `emit_c`가 모은 값(`CModule.values`)을 이미지로 싸고,
생성 로더(`{base}_params_load`)가 같은 형식을 읽는다. 그래서 형식 상수(표식·버전·상태 코드·헤더 크기)는 emit_c에서
가져온다 — 두 곳에 적히면 팩커와 로더가 조용히 갈라진다.

형식 v1 (리틀엔디언, IEEE-754 double):

    0   8  표식 "CLAWPRM\\0"
    8   4  형식 버전 (1)            12  4  헤더 바이트
    16  8  구조 지문 (u64)           24  8  파라미터 지문 (u64)
    32  8  계보 — 프로파일 지문 (u64, 모르면 0)
    40  8  dt (double — 로더가 DT 매크로와 비트 대조)
    48  4  스칼라 수   52  4  배열 수   56  4  double 총수   60  4  예약 0 (로더가 요구)
    64  4×배열 수  배열 길이 (u32), 8바이트 경계까지 0
    …   8×총수     스칼라 → 배열(레이아웃 순서)
    끝  4+4        CRC-32(앞 전체) · 예약 0 (로더가 요구)

**의미 검사를 먼저 한다**(`checks`) — 유한값·표 모양·한계 순서·이산 계수 범위. 하나라도 어긋나면 이미지를 만들지
않는다(`pack`). 로더도 모양(유한값·표)은 다시 검사하지만 한계 순서·계수 범위는 보지 않는다 — 그건 서버가 계산한 값의
의미이고, 로더의 일은 전송·보관 중 손상과 다른 코드용 이미지를 거르는 것이다(02 §1 경계, 07 §10 백로그).
"""

import math
import struct
import zlib

from claw.codegen.emit_c import IMAGE_FORMAT, IMAGE_MAGIC, PARAM_STATUS, header_bytes

# 상태 이름 → 코드 (0 = 성공) — 로더 매크로 `{GUARD}_PARAMS_{이름}`과 같은 표
STATUS = {name: code for code, (name, _note) in enumerate(PARAM_STATUS)}
STATUS_NOTE = dict(PARAM_STATUS)


class ParamImageError(ValueError):
    """이미지를 읽을 수 없다 — status는 C 로더가 같은 이미지에 낼 상태 이름이다."""

    def __init__(self, status, message):
        super().__init__(f"{status}: {message}")
        self.status = status


def _u64(hexfp):
    return int(hexfp, 16) if hexfp else 0


def _flat(module, values=None):
    vals = module.values if values is None else values
    lay = module.layout
    scalars = [float(vals[s["name"]]) for s in lay["scalars"]]
    arrays = [[float(x) for x in vals[a["name"]]] for a in lay["arrays"]]
    return scalars, arrays


def _assemble(module, lineage, scalars, arrays, *, n_scalars=None, n_arrays=None, total=None,
              header=None, fmt=IMAGE_FORMAT, sfp=None, dt=None, lengths=None, crc=True, reserved=0, tail=0):
    """헤더 필드를 하나씩 덮어쓸 수 있는 조립 — 손상 이미지(`corruptions`)도 같은 길로 만든다."""
    hb = module.layout["header_bytes"] if header is None else header
    lens = [len(a) for a in arrays] if lengths is None else lengths
    count = len(scalars) + sum(len(a) for a in arrays)
    head = bytearray(IMAGE_MAGIC)
    head += struct.pack("<II", fmt, hb)
    head += struct.pack("<QQQ", _u64(module.structure_fingerprint) if sfp is None else sfp,
                        _u64(module.param_fingerprint), _u64(lineage))
    head += struct.pack("<d", module.dt if dt is None else dt)
    head += struct.pack("<IIII", len(scalars) if n_scalars is None else n_scalars,
                        len(arrays) if n_arrays is None else n_arrays,
                        count if total is None else total, reserved)
    head += b"".join(struct.pack("<I", n) for n in lens)
    head += b"\0" * max(0, module.layout["header_bytes"] - len(head))
    body = struct.pack(f"<{count}d", *scalars, *(x for a in arrays for x in a))
    data = bytes(head) + body
    return data + struct.pack("<II", zlib.crc32(data) & 0xFFFFFFFF if crc else 0, tail)


def checks(module, values=None):
    """의미 검사 [{key, title, ok, detail}] — 이미지를 쓰기 전에 한다(목록에 결과가 실린다)."""
    vals = module.values if values is None else values
    lay = module.layout
    rows = []

    bad = [n for n, v in vals.items()
           if not all(math.isfinite(float(x)) for x in (v if isinstance(v, list) else [v]))]
    rows.append({"key": "finite", "title": "유한값 — NaN·Inf 없음", "ok": not bad,
                 "detail": "전 값" if not bad else f"비유한: {', '.join(bad[:6])}"})

    shape = []
    for tab in lay["tables"]:
        if tab["kind"] == "lookup":
            bp, val = vals[tab["bp"]], vals[tab["val"]]
            if len(bp) < 1 or len(bp) != len(val):
                shape.append(f"{tab['id']} 길이 {len(bp)}/{len(val)}")
            elif any(not b > a for a, b in zip(bp, bp[1:])):
                shape.append(f"{tab['id']} 격자점 순증가 아님")
        else:
            kn, coef, c, h = (vals[tab[r]] for r in ("kn", "coef", "c", "h"))
            if (len(c) < 1 or len(h) != len(c) or len(kn) != len(c) + 1 or len(coef) < len(c)
                    or len(coef) % len(c)):
                shape.append(f"{tab['id']} 다항 길이 정합 실패")
            elif any(not b > a for a, b in zip(kn, kn[1:])) or any(not x > 0.0 for x in h):
                shape.append(f"{tab['id']} 경계 순증가·스케일 양수 아님")
    rows.append({"key": "tables", "title": "표 모양 — 길이 일치·격자점 순증가·다항 정합", "ok": not shape,
                 "detail": f"표 {len(lay['tables'])}개" if not shape else "; ".join(shape[:6])})

    names = {s["name"] for s in lay["scalars"]}
    pairs, order = 0, []
    for s in lay["scalars"]:
        name = s["name"]
        for lo_sfx, hi_sfx in (("_out_lo", "_out_hi"), ("_lo", "_hi")):
            if name.endswith(lo_sfx) and not (lo_sfx == "_lo" and name.endswith("_out_lo")):
                hi = name[: -len(lo_sfx)] + hi_sfx
                if hi in names:
                    pairs += 1
                    if not float(vals[name]) <= float(vals[hi]):
                        order.append(f"{name} > {hi}")
    rows.append({"key": "limits", "title": "한계 순서 — lo ≤ hi", "ok": not order,
                 "detail": f"{pairs}쌍" if not order else "; ".join(order[:6])})

    coef, off = 0, []
    for s in lay["scalars"]:
        name = s["name"]
        if name.endswith("_one_minus_p") or name.endswith("_p"):
            coef += 1
            if not 0.0 <= float(vals[name]) <= 1.0:
                off.append(f"{name} = {vals[name]!r}")
    rows.append({"key": "coeffs", "title": "이산 계수 — p·(1 − p) ∈ [0, 1]", "ok": not off,
                 "detail": f"{coef}개" if not off else "; ".join(off[:6])})
    return rows


def pack(module, *, lineage=None):
    """CModule → 이미지 bytes. 의미 검사가 하나라도 어긋나면 ValueError(이미지를 만들지 않는다).

    lineage: 이 값을 낸 기체 프로파일의 지문(16진) — 헤더의 계보 칸. 모르면 0.
    """
    failed = [r for r in checks(module) if not r["ok"]]
    if failed:
        raise ValueError("파라미터 이미지 의미 검사 실패 — " + "; ".join(
            f"{r['title']}: {r['detail']}" for r in failed))
    scalars, arrays = _flat(module)
    return _assemble(module, lineage, scalars, arrays)


def unpack(image, module=None):
    """이미지 → dict. C 로더와 **같은 순서로** 검사하고, 어긋나면 그 상태 이름으로 ParamImageError.

    module(CModule)을 주면 그 코드가 받을 이미지인지까지 본다 — 헤더 크기·구조 지문·dt·개수, 이름을 붙인 `values`,
    표 모양(E_TABLE). 없으면 헤더가 말하는 개수로만 자른다(구조를 모르는 도구가 이미지 머리를 읽을 때). E_POOL은 호출자
    버퍼 문제라 여기 없다.
    """
    img = bytes(image)
    layout = None if module is None else module.layout
    need = 72 if layout is None else layout["header_bytes"] + 8
    if len(img) < need:
        raise ParamImageError("E_SHORT", f"길이 {len(img)}바이트 — 헤더보다 짧다")
    if img[:8] != IMAGE_MAGIC:
        raise ParamImageError("E_MAGIC", "표식이 CLAWPRM이 아니다")
    fmt, hb = struct.unpack_from("<II", img, 8)
    if fmt != IMAGE_FORMAT:
        raise ParamImageError("E_FORMAT", f"형식 v{fmt} — 이 도구는 v{IMAGE_FORMAT}")
    if layout is not None and hb != layout["header_bytes"]:
        raise ParamImageError("E_HEADER", f"헤더 {hb}바이트 ≠ 레이아웃 {layout['header_bytes']}")
    if struct.unpack_from("<I", img, 60)[0] != 0:
        raise ParamImageError("E_HEADER", "예약 칸(오프셋 60)이 0이 아니다")
    sfp, pfp, lineage = struct.unpack_from("<QQQ", img, 16)
    if module is not None and sfp != _u64(module.structure_fingerprint):
        raise ParamImageError("E_STRUCTURE", f"구조 지문 {sfp:016x} ≠ 코드 {module.structure_fingerprint}")
    (dt,) = struct.unpack_from("<d", img, 40)
    if module is not None and struct.pack("<d", dt) != struct.pack("<d", module.dt):
        raise ParamImageError("E_DT", f"제어주기 {dt!r} ≠ 코드 {module.dt!r}")
    n_s, n_a, total = struct.unpack_from("<III", img, 48)
    if layout is not None and n_s != len(layout["scalars"]):
        raise ParamImageError("E_LAYOUT", f"스칼라 {n_s} ≠ 레이아웃 {len(layout['scalars'])}")
    if layout is not None and n_a != len(layout["arrays"]):
        raise ParamImageError("E_LAYOUT", f"배열 {n_a} ≠ 레이아웃 {len(layout['arrays'])}")
    if hb != header_bytes(n_a):
        raise ParamImageError("E_HEADER", f"헤더 {hb}바이트가 배열 {n_a}개와 맞지 않는다")
    if len(img) < hb + 8:
        raise ParamImageError("E_SHORT", f"길이 {len(img)}바이트 — 헤더보다 짧다")
    lens = list(struct.unpack_from(f"<{n_a}I", img, 64))
    if total != n_s + sum(lens):
        raise ParamImageError("E_LAYOUT", f"double 총수 {total} ≠ 스칼라 {n_s} + 배열 합 {sum(lens)}")
    if len(img) != hb + 8 * total + 8:
        raise ParamImageError("E_LENGTH", f"길이 {len(img)} ≠ {hb} + 8×{total} + 8")
    crc, tail = struct.unpack_from("<II", img, len(img) - 8)
    if zlib.crc32(img[:-8]) & 0xFFFFFFFF != crc:
        raise ParamImageError("E_CRC", "CRC-32 불일치")
    if tail != 0:
        raise ParamImageError("E_CRC", "CRC 레코드의 예약 칸이 0이 아니다")
    doubles = struct.unpack_from(f"<{total}d", img, hb)
    if not all(math.isfinite(x) for x in doubles):
        raise ParamImageError("E_NONFINITE", "NaN·Inf 값")
    scalars = list(doubles[:n_s])
    arrays, k = [], n_s
    for n in lens:
        arrays.append(list(doubles[k:k + n]))
        k += n
    out = {"format": fmt, "header_bytes": hb, "structure_fingerprint": f"{sfp:016x}",
           "param_fingerprint": f"{pfp:016x}", "lineage": f"{lineage:016x}" if lineage else None,
           "dt": dt, "scalars": scalars, "arrays": arrays, "crc32": crc, "bytes": len(img)}
    if layout is not None:
        values = {s["name"]: v for s, v in zip(layout["scalars"], scalars)}
        values.update({a["name"]: v for a, v in zip(layout["arrays"], arrays)})
        out["values"] = values
        shape = next(r for r in checks(_Shim(layout), values) if r["key"] == "tables")
        if not shape["ok"]:
            raise ParamImageError("E_TABLE", shape["detail"])
    return out


class _Shim:
    """checks()가 레이아웃만으로 돌 수 있게 — unpack이 모듈 없이 표 모양을 본다."""

    def __init__(self, layout):
        self.layout = layout
        self.values = {}


def listing(module, image, *, title=None):
    """사람이 읽는 이미지 목록 — 헤더·의미 검사·스칼라·표. 값은 repr(최단 왕복)이라 비트까지 읽힌다."""
    info = unpack(image, module)
    lay, vals = module.layout, info["values"]
    lines = [
        f"CLAW 파라미터 이미지 — {title or 'fcl'}",
        f"형식 v{info['format']} · 구조 지문 {info['structure_fingerprint']} · "
        f"파라미터 지문 {info['param_fingerprint']}",
        f"계보(프로파일 지문) {info['lineage'] or '—'} · 제어주기 {info['dt']!r} s",
        f"스칼라 {len(lay['scalars'])}개 · 표 {len(lay['tables'])}개(배열 {len(lay['arrays'])}개) · "
        f"double {len(info['scalars']) + sum(len(a) for a in info['arrays'])}개 · "
        f"{info['bytes']}바이트 · CRC-32 0x{info['crc32']:08x}",
        "",
        "의미 검사",
    ]
    for r in checks(module, vals):
        lines.append(f"  {'통과' if r['ok'] else '실패'}  {r['title']} — {r['detail']}")
    lines += ["", "스칼라"]
    width = max((len(s["name"]) for s in lay["scalars"]), default=0)
    for s in lay["scalars"]:
        lines.append(f"  {s['name'].ljust(width)} = {vals[s['name']]!r}" + (f"   {s['comment']}" if s["comment"] else ""))
    lines += ["", "표"]
    for tab in lay["tables"]:
        if tab["kind"] == "lookup":
            n = len(vals[tab["bp"]])
            lines.append(f"  {tab['id']} — 절점 표 n = {n}")
            lines.append(f"    bp  = {', '.join(repr(x) for x in vals[tab['bp']])}")
            lines.append(f"    val = {', '.join(repr(x) for x in vals[tab['val']])}")
        else:
            nseg = len(vals[tab["c"]])
            lines.append(f"  {tab['id']} — 다항 표 구간 {nseg} · stride {len(vals[tab['coef']]) // max(nseg, 1)}")
            for role in ("kn", "coef", "c", "h"):
                lines.append(f"    {role:<4}= {', '.join(repr(x) for x in vals[tab[role]])}")
    return "\n".join(lines) + "\n"


def corruptions(module, *, lineage=None):
    """손상 이미지 [{id, title, image, pool_delta, status}] — C 로더의 거부 경로를 하나씩 태운다.

    status는 C 로더가 내야 할 상태 이름이다. 검사 순서상 앞 검사를 통과하도록 나머지 필드는 정상으로 둔다(CRC도 다시
    계산한다 — CRC 손상 경우만 빼고). pool_delta는 하네스가 pool을 double 총수보다 얼마나 작게 줄지(E_POOL).
    """
    scalars, arrays = _flat(module)
    good = _assemble(module, lineage, scalars, arrays)
    total = len(scalars) + sum(len(a) for a in arrays)
    hb = module.layout["header_bytes"]
    out = [{"id": "OK", "title": "정상 이미지", "image": good, "pool_delta": 0, "status": "OK"}]

    def add(cid, title, image, status, pool_delta=0):
        out.append({"id": cid, "title": title, "image": image, "pool_delta": pool_delta, "status": status})

    add("SHORT", "헤더보다 짧다", good[: hb], "E_SHORT")
    add("MAGIC", "표식 손상", b"X" + good[1:], "E_MAGIC")
    add("FORMAT", "형식 버전 2", _assemble(module, lineage, scalars, arrays, fmt=IMAGE_FORMAT + 1), "E_FORMAT")
    add("HEADER", "헤더 크기 +8", _assemble(module, lineage, scalars, arrays, header=hb + 8), "E_HEADER")
    add("RESERVED", "예약 칸 1", _assemble(module, lineage, scalars, arrays, reserved=1), "E_HEADER")
    sfp = _u64(module.structure_fingerprint) ^ 1
    add("STRUCTURE", "다른 구조 지문", _assemble(module, lineage, scalars, arrays, sfp=sfp), "E_STRUCTURE")
    add("DT", "제어주기 2배", _assemble(module, lineage, scalars, arrays, dt=module.dt * 2.0), "E_DT")
    add("N-SCALARS", "스칼라 수 +1", _assemble(module, lineage, scalars, arrays, n_scalars=len(scalars) + 1),
        "E_LAYOUT")
    add("N-ARRAYS", "배열 수 +1", _assemble(module, lineage, scalars, arrays, n_arrays=len(arrays) + 1),
        "E_LAYOUT")
    add("TOTAL", "double 총수 +1", _assemble(module, lineage, scalars, arrays, total=total + 1), "E_LAYOUT")
    add("LENGTH", "끝에 8바이트 더", good[:-8] + b"\0" * 8 + good[-8:], "E_LENGTH")
    flipped = bytearray(good)
    flipped[hb] ^= 0x01
    add("CRC", "값 한 비트 손상 (CRC 그대로)", bytes(flipped), "E_CRC")
    add("TAIL", "CRC 레코드 예약 칸 1", _assemble(module, lineage, scalars, arrays, tail=1), "E_CRC")
    add("POOL", "pool이 하나 모자란다", good, "E_POOL", pool_delta=-1)
    if scalars:
        nan = [math.nan] + scalars[1:]
        add("NONFINITE", "스칼라 NaN", _assemble(module, lineage, nan, arrays), "E_NONFINITE")
    lay = module.layout
    idx = {a["name"]: k for k, a in enumerate(lay["arrays"])}
    multi = next((t for t in lay["tables"] if t["kind"] == "lookup" and len(arrays[idx[t["bp"]]]) >= 2), None)
    if multi is not None:
        rev = [list(a) for a in arrays]
        rev[idx[multi["bp"]]][1] = rev[idx[multi["bp"]]][0]
        add("TABLE-ORDER", f"{multi['id']} 격자점 순증가 아님", _assemble(module, lineage, scalars, rev), "E_TABLE")
        uneven = [list(a) for a in arrays]
        moved = uneven[idx[multi["val"]]].pop()
        uneven[idx[multi["bp"]]].append(uneven[idx[multi["bp"]]][-1] + 1.0 + abs(moved))
        add("TABLE-LENGTH", f"{multi['id']} 격자점·값 길이 불일치",
            _assemble(module, lineage, scalars, uneven), "E_TABLE")
    poly = next((t for t in lay["tables"] if t["kind"] == "poly"), None)
    if poly is not None:
        neg = [list(a) for a in arrays]
        neg[idx[poly["h"]]][0] = -abs(neg[idx[poly["h"]]][0])
        add("POLY-SCALE", f"{poly['id']} 구간 스케일 음수", _assemble(module, lineage, scalars, neg), "E_TABLE")
    return out
