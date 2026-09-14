/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR에서, 값은 파라미터 이미지에서 온다).
 * 그래프    : fcl
 * 구조 지문 : bc5d7dc7d4ee4c60
 * 엔진      : claw 0.2.0
 * lim — 기능축 분할, 6개 블록
 */
#include "fcl_lim.h"

#include "claw_rt.h"

void fcl_lim_step(const fcl_params_t *prm, fcl_state_t *sta,
                  double theta, double alpha, double mach, double ap_theta_out_y,
                  double *out_lim_a_margin, double *out_lim_theta_lim, double *out_lim_active)
{
    (void)sta;  /* 상태가 없다 */
    /* lim_stall — LookupBlock */
    const double lim_stall_y = claw_lookup1d(prm->lim_stall_bp, prm->lim_stall_val,
                                             prm->lim_stall_n, mach);

    /* lim_alpha_max — add_param */
    const double lim_alpha_max_y = lim_stall_y + prm->lim_alpha_max_c;

    /* lim_a_margin — Sum */
    const double lim_a_margin_y = lim_alpha_max_y - alpha;

    /* lim_cap — Sum */
    const double lim_cap_y = theta + lim_a_margin_y;

    /* lim_theta_lim — min2 */
    const double lim_theta_lim_y = ((lim_cap_y) < (ap_theta_out_y) ? (lim_cap_y) : (ap_theta_out_y));

    /* lim_active — gt */
    const double lim_active_y = ((ap_theta_out_y) > (lim_cap_y) ? 1.0 : 0.0);

    *out_lim_a_margin = lim_a_margin_y;
    *out_lim_theta_lim = lim_theta_lim_y;
    *out_lim_active = lim_active_y;
}
