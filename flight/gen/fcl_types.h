/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR에서, 값은 파라미터 이미지에서 온다).
 * 그래프    : fcl
 * 구조 지문 : bc5d7dc7d4ee4c60
 * 엔진      : claw 0.2.0
 * 자료형 (MATLAB _types.h 대응)
 */
#ifndef CLAW_FCL_TYPES_H
#define CLAW_FCL_TYPES_H

/* 이 주기로 이산 계수(파라미터 이미지)가 계산되어 있다 — 이미지 헤더의 dt를 로더가
 * 이 매크로와 비트로 대조한다. 주기를 바꾸려면 재생성하고 이미지도 다시 만든다. */
#define FCL_DT 0.01

/* 파라미터 (MATLAB rtP 대응) — 실제로 참조되는 것만 있다. 값은 코드에 없고 비행 전에
 * 파라미터 이미지에서 적재한다(fcl_params.h). 표는 포인터와 점 수로 잡혀 크기가 코드에
 * 박히지 않는다. 게인 스케줄로 신호가 된 값은 여기 남지 않는다. */
typedef struct {
    double sched_f_mach_one_minus_p;       /* 1 − exp(-dt/tau) (tau = 0이면 1 — 통과) */
    double ap_fpsi_one_minus_p;            /* 1 − exp(-dt/tau) (tau = 0이면 1 — 통과) */
    double ap_hdg_pid_out_lo;              /* 출력·적분기 클램프 하한 (안티와인드업) */
    double ap_hdg_pid_out_hi;              /* 출력·적분기 클램프 상한 (안티와인드업) */
    double ap_hdg_sat_lo;                  /* 하한 */
    double ap_hdg_sat_hi;                  /* 상한 */
    double ap_theta_hi_lo;                 /* 하한 */
    double ap_theta_hi_hi;                 /* 상한 */
    double ap_fh_one_minus_p;              /* 1 − exp(-dt/tau) (tau = 0이면 1 — 통과) */
    double ap_alt_pid_out_lo;              /* 출력·적분기 클램프 하한 (안티와인드업) */
    double ap_alt_sat_lo;                  /* 하한 */
    double ap_fvs_one_minus_p;             /* 1 − exp(-dt/tau) (tau = 0이면 1 — 통과) */
    double ap_vs_pid_kp;                   /* 비례 게인 */
    double ap_vs_pid_out_lo;               /* 출력·적분기 클램프 하한 (안티와인드업) */
    double ap_vs_pid_ki;                   /* 적분 게인 */
    double ap_vs_sat_lo;                   /* 하한 */
    double ap_pitch_sat_lo;                /* 하한 */
    double ap_theta_vs_threshold;          /* 전환 임계값 */
    double ap_theta_src_threshold;         /* 전환 임계값 */
    double ap_ff_p_k;                      /* 게인 */
    double ap_theta_out_lo;                /* 하한 */
    double ap_fv_one_minus_p;              /* 1 − exp(-dt/tau) (tau = 0이면 1 — 통과) */
    double ap_spd_pid_out_lo;              /* 출력·적분기 클램프 하한 (안티와인드업) */
    double ap_spd_pid_out_hi;              /* 출력·적분기 클램프 상한 (안티와인드업) */
    double ap_spd_sat_lo;                  /* 하한 */
    double ap_spd_sat_hi;                  /* 상한 */
    double ap_ff_t_k;                      /* 게인 */
    double ap_thr_out_lo;                  /* 하한 */
    double ap_thr_out_hi;                  /* 상한 */
    double lim_alpha_max_c;                /* 상수 편차 */
    double scas_alloc_resv_lo;             /* 하한 */
    double scas_alloc_resv_hi;             /* 상한 */
    double scas_alloc_resv_neg_k;          /* 게인 */
    double scas_alloc_roll_hi_c;           /* 상수 편차 */
    double scas_alloc_roll_lo_k;           /* 게인 */
    double scas_roll_wo_p;                 /* exp(-dt/tau) — FCL_DT로 계산 */
    double scas_roll_wo_one_minus_p;       /* 1 − p */
    double scas_roll_wo_sel_c;             /* 선택 — 0이 아니면 첫 입력, 0이면 둘째 입력 */
    double scas_alloc_da_neg_k;            /* 게인 */
    double scas_alloc_pitch_hi_c;          /* 상수 편차 */
    double scas_alloc_pitch_lo_k;          /* 게인 */
    double scas_pitch_wo_p;                /* exp(-dt/tau) — FCL_DT로 계산 */
    double scas_pitch_wo_one_minus_p;      /* 1 − p */
    double scas_pitch_wo_sel_c;            /* 선택 — 0이 아니면 첫 입력, 0이면 둘째 입력 */
    double scas_yaw_wo_p;                  /* exp(-dt/tau) — FCL_DT로 계산 */
    double scas_yaw_wo_one_minus_p;        /* 1 − p */
    double scas_yaw_wo_sel_c;              /* 선택 — 0이 아니면 첫 입력, 0이면 둘째 입력 */
    double scas_yaw_pid_out_lo;            /* 출력·적분기 클램프 하한 (안티와인드업) */
    double scas_yaw_pid_out_hi;            /* 출력·적분기 클램프 상한 (안티와인드업) */
    double scas_yaw_sat_lo;                /* 하한 */
    double scas_yaw_sat_hi;                /* 상한 */
    double mix_elevon_l_lo;                /* 하한 */
    double mix_elevon_l_hi;                /* 상한 */
    double mix_elevon_r_lo;                /* 하한 */
    double mix_elevon_r_hi;                /* 상한 */
    double mix_rudder_lo;                  /* 하한 */
    double mix_rudder_hi;                  /* 상한 */
    double mix_diff_k;                     /* 게인 */
    double mix_thr_l_lo;                   /* 하한 */
    double mix_thr_l_hi;                   /* 상한 */
    double mix_thr_r_lo;                   /* 하한 */
    double mix_thr_r_hi;                   /* 상한 */
    const double *sched_alt_k_rate_bp;     /* mach 격자점 (순증가) */
    const double *sched_alt_k_rate_val;    /* 값 */
    int sched_alt_k_rate_n;                /* 격자점 수 — 이미지의 배열 길이에서 적재 */
    const double *sched_alt_ki_bp;         /* mach 격자점 (순증가) */
    const double *sched_alt_ki_val;        /* 값 */
    int sched_alt_ki_n;                    /* 격자점 수 — 이미지의 배열 길이에서 적재 */
    const double *sched_alt_kp_bp;         /* mach 격자점 (순증가) */
    const double *sched_alt_kp_val;        /* 값 */
    int sched_alt_kp_n;                    /* 격자점 수 — 이미지의 배열 길이에서 적재 */
    const double *sched_heading_ki_bp;     /* mach 격자점 (순증가) */
    const double *sched_heading_ki_val;    /* 값 */
    int sched_heading_ki_n;                /* 격자점 수 — 이미지의 배열 길이에서 적재 */
    const double *sched_heading_kp_bp;     /* mach 격자점 (순증가) */
    const double *sched_heading_kp_val;    /* 값 */
    int sched_heading_kp_n;                /* 격자점 수 — 이미지의 배열 길이에서 적재 */
    const double *sched_pitch_k_rate_bp;   /* mach 격자점 (순증가) */
    const double *sched_pitch_k_rate_val;  /* 값 */
    int sched_pitch_k_rate_n;              /* 격자점 수 — 이미지의 배열 길이에서 적재 */
    const double *sched_pitch_ki_bp;       /* mach 격자점 (순증가) */
    const double *sched_pitch_ki_val;      /* 값 */
    int sched_pitch_ki_n;                  /* 격자점 수 — 이미지의 배열 길이에서 적재 */
    const double *sched_pitch_kp_bp;       /* mach 격자점 (순증가) */
    const double *sched_pitch_kp_val;      /* 값 */
    int sched_pitch_kp_n;                  /* 격자점 수 — 이미지의 배열 길이에서 적재 */
    const double *sched_roll_k_rate_bp;    /* mach 격자점 (순증가) */
    const double *sched_roll_k_rate_val;   /* 값 */
    int sched_roll_k_rate_n;               /* 격자점 수 — 이미지의 배열 길이에서 적재 */
    const double *sched_roll_ki_bp;        /* mach 격자점 (순증가) */
    const double *sched_roll_ki_val;       /* 값 */
    int sched_roll_ki_n;                   /* 격자점 수 — 이미지의 배열 길이에서 적재 */
    const double *sched_roll_kp_bp;        /* mach 격자점 (순증가) */
    const double *sched_roll_kp_val;       /* 값 */
    int sched_roll_kp_n;                   /* 격자점 수 — 이미지의 배열 길이에서 적재 */
    const double *sched_speed_ki_bp;       /* mach 격자점 (순증가) */
    const double *sched_speed_ki_val;      /* 값 */
    int sched_speed_ki_n;                  /* 격자점 수 — 이미지의 배열 길이에서 적재 */
    const double *sched_speed_kp_bp;       /* mach 격자점 (순증가) */
    const double *sched_speed_kp_val;      /* 값 */
    int sched_speed_kp_n;                  /* 격자점 수 — 이미지의 배열 길이에서 적재 */
    const double *sched_yaw_k_rate_bp;     /* mach 격자점 (순증가) */
    const double *sched_yaw_k_rate_val;    /* 값 */
    int sched_yaw_k_rate_n;                /* 격자점 수 — 이미지의 배열 길이에서 적재 */
    const double *sched_yaw_ki_bp;         /* mach 격자점 (순증가) */
    const double *sched_yaw_ki_val;        /* 값 */
    int sched_yaw_ki_n;                    /* 격자점 수 — 이미지의 배열 길이에서 적재 */
    const double *sched_yaw_kp_bp;         /* mach 격자점 (순증가) */
    const double *sched_yaw_kp_val;        /* 값 */
    int sched_yaw_kp_n;                    /* 격자점 수 — 이미지의 배열 길이에서 적재 */
    const double *ap_theta_hi_raw_bp;      /* mach 격자점 (순증가) */
    const double *ap_theta_hi_raw_val;     /* 값 */
    int ap_theta_hi_raw_n;                 /* 격자점 수 — 이미지의 배열 길이에서 적재 */
    const double *lim_stall_bp;            /* mach 격자점 (순증가) */
    const double *lim_stall_val;           /* 값 */
    int lim_stall_n;                       /* 격자점 수 — 이미지의 배열 길이에서 적재 */
    const double *scas_alloc_trim_bp;      /* mach 격자점 (순증가) */
    const double *scas_alloc_trim_val;     /* 값 */
    int scas_alloc_trim_n;                 /* 격자점 수 — 이미지의 배열 길이에서 적재 */
} fcl_params_t;

/* 출력 (MATLAB rtY 대응) */
typedef struct {
    double elevon_l;
    double elevon_r;
    double rudder;
    double throttle_l;
    double throttle_r;
    double limiter_active;
    double alpha_margin;
} fcl_out_t;

/* 상태 (MATLAB rtDW 대응) — 범프리스 전환은 리셋 후 이 필드를 직접 쓴다. */
typedef struct {
    double sched_f_mach_x;    /* 필터 상태(= 출력) */
    int sched_f_mach_seeded;  /* 시드 완료 여부 — 첫 스텝은 측정에서 출발 */
    double ap_fpsi_x;         /* 필터 상태(= 출력) */
    int ap_fpsi_seeded;       /* 시드 완료 여부 — 첫 스텝은 측정에서 출발 */
    double ap_hdg_pid_i;      /* 적분기 상태 */
    double ap_fh_x;           /* 필터 상태(= 출력) */
    int ap_fh_seeded;         /* 시드 완료 여부 — 첫 스텝은 측정에서 출발 */
    double ap_alt_pid_i;      /* 적분기 상태 */
    double ap_fvs_x;          /* 필터 상태(= 출력) */
    int ap_fvs_seeded;        /* 시드 완료 여부 — 첫 스텝은 측정에서 출발 */
    double ap_vs_pid_i;       /* 적분기 상태 */
    double ap_fv_x;           /* 필터 상태(= 출력) */
    int ap_fv_seeded;         /* 시드 완료 여부 — 첫 스텝은 측정에서 출발 */
    double ap_spd_pid_i;      /* 적분기 상태 */
    double scas_roll_wo_x;    /* 워시아웃 상태 */
    double scas_roll_pid_i;   /* 적분기 상태 */
    double scas_pitch_wo_x;   /* 워시아웃 상태 */
    double scas_pitch_pid_i;  /* 적분기 상태 */
    double scas_yaw_wo_x;     /* 워시아웃 상태 */
    double scas_yaw_pid_i;    /* 적분기 상태 */
    fcl_out_t hold;           /* nav_valid=0일 때 그대로 내보낼 직전 출력 */
} fcl_state_t;

#endif /* CLAW_FCL_TYPES_H */
