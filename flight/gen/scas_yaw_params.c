/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR에서, 값은 파라미터 이미지에서 온다).
 * 그래프    : scas_yaw
 * 구조 지문 : 6ea96826a4e25a69
 * 엔진      : claw 0.2.0
 * 파라미터 로더 — 이미지 형식 v1 (07 §6.1)
 */

#include <string.h>

#include "scas_yaw_params.h"
#include "claw_rt.h"

int scas_yaw_params_pool_size(const unsigned char *img, size_t len, size_t *n_double)
{
    uint64_t total = SCAS_YAW_PARAMS_N_SCALARS;

    if (len < (size_t)SCAS_YAW_PARAMS_HEADER_BYTES + 8U) {
        return SCAS_YAW_PARAMS_E_SHORT;
    }
    if (claw_rd_u64(img) != CLAW_PRM_MAGIC) {
        return SCAS_YAW_PARAMS_E_MAGIC;
    }
    if (claw_rd_u32(img + 8) != SCAS_YAW_PARAMS_FORMAT) {
        return SCAS_YAW_PARAMS_E_FORMAT;
    }
    if (claw_rd_u32(img + 12) != SCAS_YAW_PARAMS_HEADER_BYTES) {
        return SCAS_YAW_PARAMS_E_HEADER;
    }
    if (claw_rd_u32(img + 60) != 0U) {
        return SCAS_YAW_PARAMS_E_HEADER;
    }
    if (claw_rd_u64(img + 16) != SCAS_YAW_STRUCTURE_FP) {
        return SCAS_YAW_PARAMS_E_STRUCTURE;
    }
    if (claw_rd_u64(img + 40) != claw_f64_bits(SCAS_YAW_DT)) {
        return SCAS_YAW_PARAMS_E_DT;
    }
    if (claw_rd_u32(img + 48) != SCAS_YAW_PARAMS_N_SCALARS) {
        return SCAS_YAW_PARAMS_E_LAYOUT;
    }
    if (claw_rd_u32(img + 52) != SCAS_YAW_PARAMS_N_ARRAYS) {
        return SCAS_YAW_PARAMS_E_LAYOUT;
    }
    if ((uint64_t)claw_rd_u32(img + 56) != total) {
        return SCAS_YAW_PARAMS_E_LAYOUT;
    }
    if ((uint64_t)len != (uint64_t)SCAS_YAW_PARAMS_HEADER_BYTES + 8U * total + 8U) {
        return SCAS_YAW_PARAMS_E_LENGTH;
    }
    if (claw_crc32(img, len - 8U) != claw_rd_u32(img + (len - 8U))) {
        return SCAS_YAW_PARAMS_E_CRC;
    }
    if (claw_rd_u32(img + (len - 4U)) != 0U) {
        return SCAS_YAW_PARAMS_E_CRC;
    }
    *n_double = (size_t)total;
    return SCAS_YAW_PARAMS_OK;
}

int scas_yaw_params_load(const unsigned char *img, size_t len, double *pool, size_t pool_n,
                         scas_yaw_params_t *out)
{
    scas_yaw_params_t v;
    size_t total = 0U;
    size_t k;
    const int st = scas_yaw_params_pool_size(img, len, &total);

    if (st != SCAS_YAW_PARAMS_OK) {
        return st;
    }
    if (pool_n < total) {
        return SCAS_YAW_PARAMS_E_POOL;
    }
    for (k = 0U; k < total; k++) {
        pool[k] = claw_rd_f64(img + SCAS_YAW_PARAMS_HEADER_BYTES + 8U * k);
    }
    /* NaN·Inf 거부 — x − x는 유한값에서만 0이다 (빠른 수학 금지 빌드 전제, scas_yaw.h) */
    for (k = 0U; k < total; k++) {
        if (pool[k] - pool[k] != 0.0) {
            return SCAS_YAW_PARAMS_E_NONFINITE;
        }
    }

    memset(&v, 0, sizeof v);
    v.wo_p = pool[0];
    v.wo_one_minus_p = pool[1];
    v.damp_k = pool[2];
    v.pid_kp = pool[3];
    v.pid_out_lo = pool[4];
    v.pid_out_hi = pool[5];
    v.pid_ki = pool[6];
    v.sat_lo = pool[7];
    v.sat_hi = pool[8];
    *out = v;
    return SCAS_YAW_PARAMS_OK;
}
