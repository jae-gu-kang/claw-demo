"""유닛 시험 — 탑재 파티션 파일 하나를 떼어 시험한다 (M12, VectorCAST unit 대응).

유닛 = **생성 C의 파티션**(fcl_sched·fcl_ap·fcl_lim·fcl_scas·fcl_mix)이다.
파티션 함수는 임포트가 인자, 익스포트가 out 포인터인 깨끗한 시그니처라 그대로
하네스 대상이고, "unit = 소스 파일"이라는 VectorCAST 문법과 일치한다.

**스텁이 없다 — 필요 없는 구조라서다.** 생성 법칙은 외부 의존이 0이고(플랜트·
항법·작동기는 법칙 밖, 수학은 libm뿐), 파티션의 상류·하류는 스텁이 아니라
임포트 값 그 자체다. 범용 툴이 스텁 자동 생성으로 푸는 문제를 이 구조는 생기지
않게 한다 — 그 사실이 검증 리포트의 주장 중 하나다.

Python 오라클은 **같은 IR의 파티션 실행**이다: `ir_exec.execute_node`(전체 실행과
공유 — 규칙이 두 곳에 적히지 않는다)로 그 파티션의 노드 부분열만 태운다.
인스턴스는 유닛 전용으로 새로 만들고 reset()한다 — C 쪽 `fcl_reset`과 같은
초기 상태다(적분기 0, 필터 미시드).
"""

from claw.codegen.emit_c import _interfaces
from claw.codegen.ir_exec import execute_node

UNIT_TITLES = {
    "sched": "게인 스케줄", "ap": "오토파일럿", "lim": "α 리미터",
    "scas": "SCAS 3축(+배분)", "mix": "엘레본 믹서",
}


def unit_specs(graph):
    """파티션 유닛 명세 [{group, title, imports, exports, nodes}].

    임포트·익스포트 순서는 emit_c가 함수 인자에 쓰는 순서 그대로다
    (`_interfaces` 재사용 — 여기서 다시 계산하면 하네스 인자 순서가 어긋난다.
    전부 double이라 컴파일러가 못 잡는 바로 그 사고다, test_parity 믹서 선례).
    이름표 없는 그래프(파티션 없음)는 빈 목록 — 유닛 시험 대상이 아니다.
    """
    return [
        {
            "group": p["group"],
            "title": UNIT_TITLES.get(p["group"], p["group"]),
            "imports": list(p["imports"]),
            "exports": list(p["exports"]),
            "nodes": list(p["nodes"]),
        }
        for p in _interfaces(graph)
    ]


# 이미지 파일 읽기 — 하네스(통합 계층)의 몫이라 동적 할당·표준입출력을 쓴다. 생성 코드에는 없다
IMAGE_READER = """static unsigned char *claw_read_image(const char *path, size_t *len)
{
    FILE *f = fopen(path, "rb");
    unsigned char *buf = NULL;
    long n;

    if (f == NULL) { return NULL; }
    if (fseek(f, 0, SEEK_END) == 0 && (n = ftell(f)) > 0 && fseek(f, 0, SEEK_SET) == 0) {
        buf = malloc((size_t)n);
        if (buf != NULL && fread(buf, 1, (size_t)n, f) != (size_t)n) { free(buf); buf = NULL; }
        *len = (size_t)n;
    }
    fclose(f);
    return buf;
}
"""


def load_params_c(base, indent="    "):
    """하네스 main 첫머리 — argv[1]의 이미지를 적재해 `prm`을 채운다. 실패하면 종료 코드 2."""
    return "\n".join(f"{indent}{ln}" if ln else "" for ln in [
        "len = 0;",
        "img = (argc > 1) ? claw_read_image(argv[1], &len) : NULL;",
        f"if (img == NULL || {base}_params_pool_size(img, len, &npool) != 0) {{ return 2; }}",
        "pool = malloc((npool + 1U) * sizeof *pool);",
        f"if (pool == NULL || {base}_params_load(img, len, pool, npool, &prm) != 0) {{ return 2; }}",
        "free(img);",
    ])


def make_unit_harness(base, spec) -> str:
    """유닛 하네스 C — argv[1] = 파라미터 이미지, stdin 한 행 = 임포트, stdout 한 행 = 익스포트 (%.17g).

    상태는 `{base}_reset` 한 번 후 행 순서대로 흐른다 — 행 시퀀스가 곧 시나리오다. 같은 실행 파일이 파라미터 세트의
    이미지마다 돈다(v1.12). MC/DC 계측 빌드에서만 종료 시 덤프를 낸다 (CLAW_MCDC_ENABLED — 커버리지
    빌드가 -include claw_mcdc.h 로 매크로를 공급한다).
    """
    g = spec["group"]
    n = len(spec["imports"])
    args = ", ".join(f"u[{i}]" for i in range(n))
    exports = spec["exports"]
    if len(exports) == 1:
        call = (f"        printf(\"%.17g\\n\", "
                f"{base}_{g}_step(&prm, &s, {args}));")
        decls = ""
    else:
        outs = ", ".join(f"&y[{i}]" for i in range(len(exports)))
        fmt = " ".join(["%.17g"] * len(exports))
        prints = ", ".join(f"y[{i}]" for i in range(len(exports)))
        decls = f"    double y[{len(exports)}];\n"
        call = (f"        {base}_{g}_step(&prm, &s, {args}, {outs});\n"
                f"        printf(\"{fmt}\\n\", {prints});")
    return f"""/* CLAW 유닛 하네스 — {base}_{g} 파티션 단독 구동 (스텁 없음: 임포트가 곧 상류다). */
#include <stdio.h>
#include <stdlib.h>
#include "{base}.h"
#include "{base}_{g}.h"

{IMAGE_READER}
int main(int argc, char **argv)
{{
    {base}_params_t prm;
    {base}_state_t s;
    double u[{n}];
{decls}    int k;
    size_t len, npool = 0;
    unsigned char *img;
    double *pool;

{load_params_c(base)}
    {base}_reset(&s);
    for (;;) {{
        for (k = 0; k < {n}; k++) {{
            if (scanf("%lf", &u[k]) != 1) {{
#ifdef CLAW_MCDC_ENABLED
                claw_mcdc_dump();
#endif
                return 0;
            }}
        }}
{call}
    }}
}}
"""


def make_params_harness(base) -> str:
    """로더 유닛 하네스 C — stdin 한 행 = "pool_delta 바이트수 16진이미지", stdout 한 행 = 적재 상태 코드.

    생성 로더의 거부 경로(구조 지문·CRC·길이·표 모양·pool 부족·NaN…)를 손상 이미지로 하나씩 태운다
    (`codegen/param_image.corruptions`). pool은 double 총수 + pool_delta로 준다 — E_POOL 경로.
    """
    return f"""/* CLAW 유닛 하네스 — {base}_params 로더 거부 경로 (손상 이미지 → 상태 코드). */
#include <stdio.h>
#include <stdlib.h>
#include "{base}.h"

int main(void)
{{
    int delta;
    size_t want;

    while (scanf("%d %zu", &delta, &want) == 2) {{
        {base}_params_t prm;
        unsigned char *img = malloc(want + 1U);
        size_t k, npool = 0;
        unsigned int byte;
        double *pool;
        int st;

        if (img == NULL) {{ return 3; }}
        for (k = 0; k < want; k++) {{
            if (scanf("%2x", &byte) != 1) {{ return 3; }}
            img[k] = (unsigned char)byte;
        }}
        /* pool 크기만 pool_size로 잰다 — 거부 판정은 load가 낸다(load 안의 헤더 검사 분기까지 태운다) */
        (void){base}_params_pool_size(img, want, &npool);
        pool = malloc((npool + 1U) * sizeof *pool);
        st = {base}_params_load(img, want, pool, (size_t)((long)npool + delta), &prm);
        printf("%d\\n", st);
        free(pool);
        free(img);
    }}
#ifdef CLAW_MCDC_ENABLED
    claw_mcdc_dump();
#endif
    return 0;
}}
"""


def params_stdin(cases) -> str:
    """손상 이미지 케이스 → 로더 하네스 stdin."""
    return "".join(f"{c['pool_delta']} {len(c['image'])} {c['image'].hex()}\n" for c in cases)


def run_unit_oracle(spec, dt, rows):
    """유닛의 Python(IR) 기준 출력 — [{익스포트 이름: 값}].

    비활성 스텝의 노드 출력(disabled_output)·상태 대입(on_disable)까지
    `execute_node` 그대로다. 임포트 행이 참조를 다 못 채우면 KeyError로 시끄럽게
    죽는다 — 벡터 정책이 낡았다는 뜻이고, 조용히 0을 채우면 대조가 거짓말을 한다.
    """
    instances = {
        n.id: n.block(**n.params).init(dt)
        for n in spec["nodes"] if n.kind == "block"
    }
    for inst in instances.values():
        inst.reset(None)
    outs = []
    for row in rows:
        env = {u: float(row[u]) for u in spec["imports"]}
        for node in spec["nodes"]:
            execute_node(instances, env, node)
        outs.append({e: float(env[e]) for e in spec["exports"]})
    return outs


def unit_stdin(spec, cases) -> str:
    """유닛 케이스들 → 하네스 stdin (케이스 순서대로 이어 붙인 한 스트림)."""
    lines = []
    for case in cases:
        for row in case["rows"]:
            lines.append(" ".join(repr(float(row[u])) for u in spec["imports"]))
    return "\n".join(lines) + "\n"
