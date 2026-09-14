/* CLAW 생성 코드 — 손으로 고치지 말 것.
 * 산출물 공용 런타임 (MATLAB _sharedutils 대응). 산출물이 여럿이어도 이 한 벌을 함께 쓴다 —
 * 각 산출물의 구조 지문이 자기가 부르는 헬퍼 본문을 함께 해시한다.
 */
#include "claw_rt.h"

#include <math.h>
#include <string.h>

/* double이 8바이트가 아니면 컴파일 오류 — 이미지 형식의 전제 (07 §6.1) */
typedef char claw_f64_is_8_bytes[(sizeof(double) == 8U) ? 1 : -1];

/* [lo, hi] 클램프 */
double claw_clip(double x, double lo, double hi)
{
    const double y = (x < lo) ? lo : x;
    return (y > hi) ? hi : y;
}

/* (-π, π] 래핑 — Python `%`는 나머지가 제수 부호를 따르므로 fmod 뒤 보정한다 */
double claw_wrap_pi(double a)
{
    double r = fmod(-a + CLAW_PI, 2.0 * CLAW_PI);
    if (r < 0.0) { r += 2.0 * CLAW_PI; }
    return -(r - CLAW_PI);
}

/* 1D 선형 보간, 외삽 clip — tables/table.py:54 interp()와 같은 구간 선택. n < 2면 값 하나(1점 표) */
double claw_lookup1d(const double *bp, const double *val, int n, double x)
{
    int i = 0;
    if (n < 2) { return val[0]; }
    while (i < n - 2 && x >= bp[i + 1]) { i++; }
    const double t = claw_clip((x - bp[i]) / (bp[i + 1] - bp[i]), 0.0, 1.0);
    return (1.0 - t) * val[i] + t * val[i + 1];
}

/* 리틀엔디언 u32 읽기 — 바이트 조립이라 호스트 엔디언·정렬과 무관하다 */
uint32_t claw_rd_u32(const unsigned char *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16)
           | ((uint32_t)p[3] << 24);
}

/* 리틀엔디언 u64 읽기 */
uint64_t claw_rd_u64(const unsigned char *p)
{
    return (uint64_t)claw_rd_u32(p) | ((uint64_t)claw_rd_u32(p + 4) << 32);
}

/* 리틀엔디언 IEEE-754 double 읽기 — 비트를 그대로 옮긴다(memcpy, 별칭 규칙 안전) */
double claw_rd_f64(const unsigned char *p)
{
    const uint64_t b = claw_rd_u64(p);
    double x;
    memcpy(&x, &b, sizeof x);
    return x;
}

/* double의 비트 표현 — 이미지 dt와 코드 DT 매크로를 비트로 대조한다 */
uint64_t claw_f64_bits(double x)
{
    uint64_t b;
    memcpy(&b, &x, sizeof b);
    return b;
}

/* CRC-32 (IEEE 802.3, zlib.crc32와 같은 값) — 분기 없는 비트 루프 */
uint32_t claw_crc32(const unsigned char *p, size_t n)
{
    uint32_t crc = 0xFFFFFFFFU;
    size_t i;
    int b;
    for (i = 0U; i < n; i++) {
        crc ^= (uint32_t)p[i];
        for (b = 0; b < 8; b++) {
            crc = (crc >> 1) ^ (0xEDB88320U & (0U - (crc & 1U)));
        }
    }
    return crc ^ 0xFFFFFFFFU;
}

/* 절점 표 모양 위반 여부 — 길이 ≥ 1, 격자점·값 길이 일치, 격자점 순증가 (분기 없음) */
int claw_prm_lookup_bad(const double *bp, uint32_t n_bp, uint32_t n_val)
{
    int bad = (n_bp < 1U) | (n_bp != n_val) | (n_bp > 2147483647U);
    uint32_t i;
    for (i = 1U; i < n_bp; i++) {
        bad = bad | (bp[i] <= bp[i - 1U]);
    }
    return bad;
}
