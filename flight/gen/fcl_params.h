/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR에서, 값은 파라미터 이미지에서 온다).
 * 그래프    : fcl
 * 구조 지문 : bc5d7dc7d4ee4c60
 * 엔진      : claw 0.2.0
 * 파라미터 로더 — 이미지 형식 v1 (07 §6.1)
 */
#ifndef CLAW_FCL_PARAMS_H
#define CLAW_FCL_PARAMS_H

#include <stddef.h>

#include "fcl_types.h"

/* 이 로더가 받는 이미지의 모양 — 전부 구조에서 나온다(값·표 길이는 이미지가 정한다). */
#define FCL_STRUCTURE_FP 0xbc5d7dc7d4ee4c60ULL
#define FCL_PARAMS_FORMAT 1U
#define FCL_PARAMS_N_SCALARS 62U
#define FCL_PARAMS_N_ARRAYS 38U
#define FCL_PARAMS_HEADER_BYTES 216U

/* 적재 상태 — 0이 아니면 *out은 건드리지 않는다 */
#define FCL_PARAMS_OK 0            /* 적재 성공 */
#define FCL_PARAMS_E_SHORT 1       /* 길이가 헤더보다 짧다 */
#define FCL_PARAMS_E_MAGIC 2       /* CLAW 파라미터 이미지가 아니다 */
#define FCL_PARAMS_E_FORMAT 3      /* 형식 버전이 다르다 */
#define FCL_PARAMS_E_HEADER 4      /* 헤더 크기가 이 레이아웃과 다르다 */
#define FCL_PARAMS_E_STRUCTURE 5   /* 구조 지문이 다르다 — 다른 C 코드용 이미지 */
#define FCL_PARAMS_E_DT 6          /* 제어주기가 DT 매크로와 비트로 다르다 */
#define FCL_PARAMS_E_LAYOUT 7      /* 스칼라·배열 개수 또는 double 총수가 어긋난다 */
#define FCL_PARAMS_E_LENGTH 8      /* 전체 길이가 헤더와 어긋난다 */
#define FCL_PARAMS_E_CRC 9         /* CRC-32 불일치 — 손상 */
#define FCL_PARAMS_E_POOL 10       /* 호출자 pool이 double 총수보다 작다 */
#define FCL_PARAMS_E_NONFINITE 11  /* NaN·Inf 값 */
#define FCL_PARAMS_E_TABLE 12      /* 표 모양 위반 — 길이·순증가·다항 정합 */

/* 이미지를 검사하고 double 총수를 낸다 — 호출자가 그만큼의 pool을 마련한다 (동적 할당 없음). */
int fcl_params_pool_size(const unsigned char *img, size_t len, size_t *n_double);

/* 이미지 → pool에 값 복사 → *out 조립. 표 필드는 pool을 가리키므로 pool은 *out보다 오래
 * 살아야 한다. 이미지 버퍼는 반환 뒤 버려도 된다 (바이트로 읽어 복사 — 정렬·별칭 무관). */
int fcl_params_load(const unsigned char *img, size_t len, double *pool, size_t pool_n,
                    fcl_params_t *out);

#endif /* CLAW_FCL_PARAMS_H */
