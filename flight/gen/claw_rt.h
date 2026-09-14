/* CLAW 생성 코드 — 손으로 고치지 말 것.
 * 산출물 공용 런타임 (MATLAB _sharedutils 대응). 산출물이 여럿이어도 이 한 벌을 함께 쓴다 —
 * 각 산출물의 구조 지문이 자기가 부르는 헬퍼 본문을 함께 해시한다.
 */
#ifndef CLAW_RT_H
#define CLAW_RT_H

#include <stddef.h>
#include <stdint.h>

#define CLAW_PI 3.141592653589793

/* 파라미터 이미지 표식 "CLAWPRM\0"을 리틀엔디언 u64로 읽은 값 (07 §6.1) */
#define CLAW_PRM_MAGIC 0x004D525057414C43ULL

/* [lo, hi] 클램프 */
double claw_clip(double x, double lo, double hi);

/* (-π, π] 래핑 — Python `%`는 나머지가 제수 부호를 따르므로 fmod 뒤 보정한다 */
double claw_wrap_pi(double a);

/* 1D 선형 보간, 외삽 clip — tables/table.py:54 interp()와 같은 구간 선택. n < 2면 값 하나(1점 표) */
double claw_lookup1d(const double *bp, const double *val, int n, double x);

/* 리틀엔디언 u32 읽기 — 바이트 조립이라 호스트 엔디언·정렬과 무관하다 */
uint32_t claw_rd_u32(const unsigned char *p);

/* 리틀엔디언 u64 읽기 */
uint64_t claw_rd_u64(const unsigned char *p);

/* 리틀엔디언 IEEE-754 double 읽기 — 비트를 그대로 옮긴다(memcpy, 별칭 규칙 안전) */
double claw_rd_f64(const unsigned char *p);

/* double의 비트 표현 — 이미지 dt와 코드 DT 매크로를 비트로 대조한다 */
uint64_t claw_f64_bits(double x);

/* CRC-32 (IEEE 802.3, zlib.crc32와 같은 값) — 분기 없는 비트 루프 */
uint32_t claw_crc32(const unsigned char *p, size_t n);

/* 절점 표 모양 위반 여부 — 길이 ≥ 1, 격자점·값 길이 일치, 격자점 순증가 (분기 없음) */
int claw_prm_lookup_bad(const double *bp, uint32_t n_bp, uint32_t n_val);

#endif /* CLAW_RT_H */
