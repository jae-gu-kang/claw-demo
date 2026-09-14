/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR에서, 값은 파라미터 이미지에서 온다).
 * 그래프    : fcl
 * 구조 지문 : bc5d7dc7d4ee4c60
 * 엔진      : claw 0.2.0
 * 파라미터 로더 — 이미지 형식 v1 (07 §6.1)
 */

#include <string.h>

#include "fcl_params.h"
#include "claw_rt.h"

int fcl_params_pool_size(const unsigned char *img, size_t len, size_t *n_double)
{
    uint64_t total = FCL_PARAMS_N_SCALARS;
    uint32_t k;

    if (len < (size_t)FCL_PARAMS_HEADER_BYTES + 8U) {
        return FCL_PARAMS_E_SHORT;
    }
    if (claw_rd_u64(img) != CLAW_PRM_MAGIC) {
        return FCL_PARAMS_E_MAGIC;
    }
    if (claw_rd_u32(img + 8) != FCL_PARAMS_FORMAT) {
        return FCL_PARAMS_E_FORMAT;
    }
    if (claw_rd_u32(img + 12) != FCL_PARAMS_HEADER_BYTES) {
        return FCL_PARAMS_E_HEADER;
    }
    if (claw_rd_u32(img + 60) != 0U) {
        return FCL_PARAMS_E_HEADER;
    }
    if (claw_rd_u64(img + 16) != FCL_STRUCTURE_FP) {
        return FCL_PARAMS_E_STRUCTURE;
    }
    if (claw_rd_u64(img + 40) != claw_f64_bits(FCL_DT)) {
        return FCL_PARAMS_E_DT;
    }
    if (claw_rd_u32(img + 48) != FCL_PARAMS_N_SCALARS) {
        return FCL_PARAMS_E_LAYOUT;
    }
    if (claw_rd_u32(img + 52) != FCL_PARAMS_N_ARRAYS) {
        return FCL_PARAMS_E_LAYOUT;
    }
    for (k = 0U; k < FCL_PARAMS_N_ARRAYS; k++) {
        total += claw_rd_u32(img + 64U + 4U * k);
    }
    if ((uint64_t)claw_rd_u32(img + 56) != total) {
        return FCL_PARAMS_E_LAYOUT;
    }
    if ((uint64_t)len != (uint64_t)FCL_PARAMS_HEADER_BYTES + 8U * total + 8U) {
        return FCL_PARAMS_E_LENGTH;
    }
    if (claw_crc32(img, len - 8U) != claw_rd_u32(img + (len - 8U))) {
        return FCL_PARAMS_E_CRC;
    }
    if (claw_rd_u32(img + (len - 4U)) != 0U) {
        return FCL_PARAMS_E_CRC;
    }
    *n_double = (size_t)total;
    return FCL_PARAMS_OK;
}

int fcl_params_load(const unsigned char *img, size_t len, double *pool, size_t pool_n,
                    fcl_params_t *out)
{
    fcl_params_t v;
    size_t total = 0U;
    size_t k;
    uint32_t alen[FCL_PARAMS_N_ARRAYS];
    size_t off = FCL_PARAMS_N_SCALARS;
    int bad = 0;
    const int st = fcl_params_pool_size(img, len, &total);

    if (st != FCL_PARAMS_OK) {
        return st;
    }
    if (pool_n < total) {
        return FCL_PARAMS_E_POOL;
    }
    for (k = 0U; k < total; k++) {
        pool[k] = claw_rd_f64(img + FCL_PARAMS_HEADER_BYTES + 8U * k);
    }
    /* NaN·Inf 거부 — x − x는 유한값에서만 0이다 (빠른 수학 금지 빌드 전제, fcl.h) */
    for (k = 0U; k < total; k++) {
        if (pool[k] - pool[k] != 0.0) {
            return FCL_PARAMS_E_NONFINITE;
        }
    }
    for (k = 0U; k < FCL_PARAMS_N_ARRAYS; k++) {
        alen[k] = claw_rd_u32(img + 64U + 4U * k);
    }

    memset(&v, 0, sizeof v);
    v.sched_f_mach_one_minus_p = pool[0];
    v.ap_fpsi_one_minus_p = pool[1];
    v.ap_hdg_pid_out_lo = pool[2];
    v.ap_hdg_pid_out_hi = pool[3];
    v.ap_hdg_sat_lo = pool[4];
    v.ap_hdg_sat_hi = pool[5];
    v.ap_theta_hi_lo = pool[6];
    v.ap_theta_hi_hi = pool[7];
    v.ap_fh_one_minus_p = pool[8];
    v.ap_alt_pid_out_lo = pool[9];
    v.ap_alt_sat_lo = pool[10];
    v.ap_fvs_one_minus_p = pool[11];
    v.ap_vs_pid_kp = pool[12];
    v.ap_vs_pid_out_lo = pool[13];
    v.ap_vs_pid_ki = pool[14];
    v.ap_vs_sat_lo = pool[15];
    v.ap_pitch_sat_lo = pool[16];
    v.ap_theta_vs_threshold = pool[17];
    v.ap_theta_src_threshold = pool[18];
    v.ap_ff_p_k = pool[19];
    v.ap_theta_out_lo = pool[20];
    v.ap_fv_one_minus_p = pool[21];
    v.ap_spd_pid_out_lo = pool[22];
    v.ap_spd_pid_out_hi = pool[23];
    v.ap_spd_sat_lo = pool[24];
    v.ap_spd_sat_hi = pool[25];
    v.ap_ff_t_k = pool[26];
    v.ap_thr_out_lo = pool[27];
    v.ap_thr_out_hi = pool[28];
    v.lim_alpha_max_c = pool[29];
    v.scas_alloc_resv_lo = pool[30];
    v.scas_alloc_resv_hi = pool[31];
    v.scas_alloc_resv_neg_k = pool[32];
    v.scas_alloc_roll_hi_c = pool[33];
    v.scas_alloc_roll_lo_k = pool[34];
    v.scas_roll_wo_p = pool[35];
    v.scas_roll_wo_one_minus_p = pool[36];
    v.scas_roll_wo_sel_c = pool[37];
    v.scas_alloc_da_neg_k = pool[38];
    v.scas_alloc_pitch_hi_c = pool[39];
    v.scas_alloc_pitch_lo_k = pool[40];
    v.scas_pitch_wo_p = pool[41];
    v.scas_pitch_wo_one_minus_p = pool[42];
    v.scas_pitch_wo_sel_c = pool[43];
    v.scas_yaw_wo_p = pool[44];
    v.scas_yaw_wo_one_minus_p = pool[45];
    v.scas_yaw_wo_sel_c = pool[46];
    v.scas_yaw_pid_out_lo = pool[47];
    v.scas_yaw_pid_out_hi = pool[48];
    v.scas_yaw_sat_lo = pool[49];
    v.scas_yaw_sat_hi = pool[50];
    v.mix_elevon_l_lo = pool[51];
    v.mix_elevon_l_hi = pool[52];
    v.mix_elevon_r_lo = pool[53];
    v.mix_elevon_r_hi = pool[54];
    v.mix_rudder_lo = pool[55];
    v.mix_rudder_hi = pool[56];
    v.mix_diff_k = pool[57];
    v.mix_thr_l_lo = pool[58];
    v.mix_thr_l_hi = pool[59];
    v.mix_thr_r_lo = pool[60];
    v.mix_thr_r_hi = pool[61];
    v.sched_alt_k_rate_bp = &pool[off];
    off += alen[0];
    v.sched_alt_k_rate_val = &pool[off];
    off += alen[1];
    v.sched_alt_ki_bp = &pool[off];
    off += alen[2];
    v.sched_alt_ki_val = &pool[off];
    off += alen[3];
    v.sched_alt_kp_bp = &pool[off];
    off += alen[4];
    v.sched_alt_kp_val = &pool[off];
    off += alen[5];
    v.sched_heading_ki_bp = &pool[off];
    off += alen[6];
    v.sched_heading_ki_val = &pool[off];
    off += alen[7];
    v.sched_heading_kp_bp = &pool[off];
    off += alen[8];
    v.sched_heading_kp_val = &pool[off];
    off += alen[9];
    v.sched_pitch_k_rate_bp = &pool[off];
    off += alen[10];
    v.sched_pitch_k_rate_val = &pool[off];
    off += alen[11];
    v.sched_pitch_ki_bp = &pool[off];
    off += alen[12];
    v.sched_pitch_ki_val = &pool[off];
    off += alen[13];
    v.sched_pitch_kp_bp = &pool[off];
    off += alen[14];
    v.sched_pitch_kp_val = &pool[off];
    off += alen[15];
    v.sched_roll_k_rate_bp = &pool[off];
    off += alen[16];
    v.sched_roll_k_rate_val = &pool[off];
    off += alen[17];
    v.sched_roll_ki_bp = &pool[off];
    off += alen[18];
    v.sched_roll_ki_val = &pool[off];
    off += alen[19];
    v.sched_roll_kp_bp = &pool[off];
    off += alen[20];
    v.sched_roll_kp_val = &pool[off];
    off += alen[21];
    v.sched_speed_ki_bp = &pool[off];
    off += alen[22];
    v.sched_speed_ki_val = &pool[off];
    off += alen[23];
    v.sched_speed_kp_bp = &pool[off];
    off += alen[24];
    v.sched_speed_kp_val = &pool[off];
    off += alen[25];
    v.sched_yaw_k_rate_bp = &pool[off];
    off += alen[26];
    v.sched_yaw_k_rate_val = &pool[off];
    off += alen[27];
    v.sched_yaw_ki_bp = &pool[off];
    off += alen[28];
    v.sched_yaw_ki_val = &pool[off];
    off += alen[29];
    v.sched_yaw_kp_bp = &pool[off];
    off += alen[30];
    v.sched_yaw_kp_val = &pool[off];
    off += alen[31];
    v.ap_theta_hi_raw_bp = &pool[off];
    off += alen[32];
    v.ap_theta_hi_raw_val = &pool[off];
    off += alen[33];
    v.lim_stall_bp = &pool[off];
    off += alen[34];
    v.lim_stall_val = &pool[off];
    off += alen[35];
    v.scas_alloc_trim_bp = &pool[off];
    off += alen[36];
    v.scas_alloc_trim_val = &pool[off];
    off += alen[37];
    v.sched_alt_k_rate_n = (int)alen[0];
    bad = bad | claw_prm_lookup_bad(v.sched_alt_k_rate_bp, alen[0], alen[1]);
    v.sched_alt_ki_n = (int)alen[2];
    bad = bad | claw_prm_lookup_bad(v.sched_alt_ki_bp, alen[2], alen[3]);
    v.sched_alt_kp_n = (int)alen[4];
    bad = bad | claw_prm_lookup_bad(v.sched_alt_kp_bp, alen[4], alen[5]);
    v.sched_heading_ki_n = (int)alen[6];
    bad = bad | claw_prm_lookup_bad(v.sched_heading_ki_bp, alen[6], alen[7]);
    v.sched_heading_kp_n = (int)alen[8];
    bad = bad | claw_prm_lookup_bad(v.sched_heading_kp_bp, alen[8], alen[9]);
    v.sched_pitch_k_rate_n = (int)alen[10];
    bad = bad | claw_prm_lookup_bad(v.sched_pitch_k_rate_bp, alen[10], alen[11]);
    v.sched_pitch_ki_n = (int)alen[12];
    bad = bad | claw_prm_lookup_bad(v.sched_pitch_ki_bp, alen[12], alen[13]);
    v.sched_pitch_kp_n = (int)alen[14];
    bad = bad | claw_prm_lookup_bad(v.sched_pitch_kp_bp, alen[14], alen[15]);
    v.sched_roll_k_rate_n = (int)alen[16];
    bad = bad | claw_prm_lookup_bad(v.sched_roll_k_rate_bp, alen[16], alen[17]);
    v.sched_roll_ki_n = (int)alen[18];
    bad = bad | claw_prm_lookup_bad(v.sched_roll_ki_bp, alen[18], alen[19]);
    v.sched_roll_kp_n = (int)alen[20];
    bad = bad | claw_prm_lookup_bad(v.sched_roll_kp_bp, alen[20], alen[21]);
    v.sched_speed_ki_n = (int)alen[22];
    bad = bad | claw_prm_lookup_bad(v.sched_speed_ki_bp, alen[22], alen[23]);
    v.sched_speed_kp_n = (int)alen[24];
    bad = bad | claw_prm_lookup_bad(v.sched_speed_kp_bp, alen[24], alen[25]);
    v.sched_yaw_k_rate_n = (int)alen[26];
    bad = bad | claw_prm_lookup_bad(v.sched_yaw_k_rate_bp, alen[26], alen[27]);
    v.sched_yaw_ki_n = (int)alen[28];
    bad = bad | claw_prm_lookup_bad(v.sched_yaw_ki_bp, alen[28], alen[29]);
    v.sched_yaw_kp_n = (int)alen[30];
    bad = bad | claw_prm_lookup_bad(v.sched_yaw_kp_bp, alen[30], alen[31]);
    v.ap_theta_hi_raw_n = (int)alen[32];
    bad = bad | claw_prm_lookup_bad(v.ap_theta_hi_raw_bp, alen[32], alen[33]);
    v.lim_stall_n = (int)alen[34];
    bad = bad | claw_prm_lookup_bad(v.lim_stall_bp, alen[34], alen[35]);
    v.scas_alloc_trim_n = (int)alen[36];
    bad = bad | claw_prm_lookup_bad(v.scas_alloc_trim_bp, alen[36], alen[37]);
    if (bad != 0) {
        return FCL_PARAMS_E_TABLE;
    }
    *out = v;
    return FCL_PARAMS_OK;
}
