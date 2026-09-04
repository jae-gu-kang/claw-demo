/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR, 값은 파라미터에서 나온다).
 * 그래프  : fcl
 * 지문    : 3e032f9003b7cc9f
 * 엔진    : claw 0.2.0
 * 자료형 (MATLAB _types.h 대응)
 */
#ifndef CLAW_FCL_TYPES_H
#define CLAW_FCL_TYPES_H

/* 이 주기로 이산 계수가 구워져 있다 — 주기를 바꾸려면 재생성해야 한다.
 * 이 값만 고치면 필터 계수가 조용히 틀린다. */
#define FCL_DT 0.01

/* 파라미터 (MATLAB rtP 대응) — 실제로 참조되는 것만 있다:
 * 게인 스케줄로 신호가 된 값은 여기 남지 않는다. */
typedef struct {
    double sched_f_mach_one_minus_p;    /* 1 − exp(-dt/tau), tau=0.5 s */
    double ap_fpsi_one_minus_p;         /* 1 − exp(-dt/tau), tau=1.0 s */
    double ap_hdg_pid_kp;               /* 비례 게인 */
    double ap_hdg_pid_ki;               /* 적분 게인 */
    double ap_hdg_pid_out_lo;           /* 출력·적분기 클램프 하한 (안티와인드업) */
    double ap_hdg_pid_out_hi;           /* 출력·적분기 클램프 상한 (안티와인드업) */
    double ap_hdg_sat_lo;               /* 하한 */
    double ap_hdg_sat_hi;               /* 상한 */
    double ap_fh_one_minus_p;           /* 1 − exp(-dt/tau), tau=5.0 s */
    double ap_alt_damp_k;               /* 게인 */
    double ap_alt_pid_kp;               /* 비례 게인 */
    double ap_alt_pid_ki;               /* 적분 게인 */
    double ap_alt_pid_out_lo;           /* 출력·적분기 클램프 하한 (안티와인드업) */
    double ap_alt_pid_out_hi;           /* 출력·적분기 클램프 상한 (안티와인드업) */
    double ap_alt_sat_lo;               /* 하한 */
    double ap_alt_sat_hi;               /* 상한 */
    double ap_fvs_one_minus_p;          /* 1 − exp(-dt/tau), tau=2.0 s */
    double ap_vs_pid_kp;                /* 비례 게인 */
    double ap_vs_pid_ki;                /* 적분 게인 */
    double ap_vs_pid_out_lo;            /* 출력·적분기 클램프 하한 (안티와인드업) */
    double ap_vs_pid_out_hi;            /* 출력·적분기 클램프 상한 (안티와인드업) */
    double ap_vs_sat_lo;                /* 하한 */
    double ap_vs_sat_hi;                /* 상한 */
    double ap_pitch_sat_lo;             /* 하한 */
    double ap_pitch_sat_hi;             /* 상한 */
    double ap_theta_vs_threshold;       /* 전환 임계값 */
    double ap_theta_src_threshold;      /* 전환 임계값 */
    double ap_ff_p_k;                   /* 게인 */
    double ap_theta_out_lo;             /* 하한 */
    double ap_theta_out_hi;             /* 상한 */
    double ap_fv_one_minus_p;           /* 1 − exp(-dt/tau), tau=2.0 s */
    double ap_spd_pid_kp;               /* 비례 게인 */
    double ap_spd_pid_ki;               /* 적분 게인 */
    double ap_spd_pid_out_lo;           /* 출력·적분기 클램프 하한 (안티와인드업) */
    double ap_spd_pid_out_hi;           /* 출력·적분기 클램프 상한 (안티와인드업) */
    double ap_spd_sat_lo;               /* 하한 */
    double ap_spd_sat_hi;               /* 상한 */
    double scas_alloc_resv_lo;          /* 하한 */
    double scas_alloc_resv_hi;          /* 상한 */
    double scas_alloc_resv_neg_k;       /* 게인 */
    double scas_alloc_roll_lo_k;        /* 게인 */
    double scas_alloc_da_neg_k;         /* 게인 */
    double scas_alloc_pitch_lo_k;       /* 게인 */
    double scas_yaw_wo_p;               /* exp(-dt/tau), tau=2.0 s — FCL_DT로 구움 */
    double scas_yaw_wo_one_minus_p;     /* 1 − p */
    double scas_yaw_damp_k;             /* 게인 */
    double scas_yaw_pid_kp;             /* 비례 게인 */
    double scas_yaw_pid_ki;             /* 적분 게인 */
    double scas_yaw_pid_out_lo;         /* 출력·적분기 클램프 하한 (안티와인드업) */
    double scas_yaw_pid_out_hi;         /* 출력·적분기 클램프 상한 (안티와인드업) */
    double scas_yaw_sat_lo;             /* 하한 */
    double scas_yaw_sat_hi;             /* 상한 */
    double mix_elevon_l_lo;             /* 하한 */
    double mix_elevon_l_hi;             /* 상한 */
    double mix_elevon_r_lo;             /* 하한 */
    double mix_elevon_r_hi;             /* 상한 */
    double mix_rudder_lo;               /* 하한 */
    double mix_rudder_hi;               /* 상한 */
    double mix_diff_k;                  /* 게인 */
    double mix_thr_l_lo;                /* 하한 */
    double mix_thr_l_hi;                /* 상한 */
    double mix_thr_r_lo;                /* 하한 */
    double mix_thr_r_hi;                /* 상한 */
    double sched_pitch_k_rate_bp[17];   /* mach 격자점 */
    double sched_pitch_k_rate_val[17];  /* pitch.k_rate 값 */
    double sched_pitch_ki_bp[17];       /* mach 격자점 */
    double sched_pitch_ki_val[17];      /* pitch.ki 값 */
    double sched_pitch_kp_bp[17];       /* mach 격자점 */
    double sched_pitch_kp_val[17];      /* pitch.kp 값 */
    double sched_roll_k_rate_bp[17];    /* mach 격자점 */
    double sched_roll_k_rate_val[17];   /* roll.k_rate 값 */
    double sched_roll_ki_bp[17];        /* mach 격자점 */
    double sched_roll_ki_val[17];       /* roll.ki 값 */
    double sched_roll_kp_bp[17];        /* mach 격자점 */
    double sched_roll_kp_val[17];       /* roll.kp 값 */
    double lim_stall_bp[5];             /* mach 격자점 */
    double lim_stall_val[5];            /* alpha_stall 값 */
    double scas_alloc_trim_bp[7];       /* mach 격자점 */
    double scas_alloc_trim_val[7];      /* de_trim 값 */
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
    double scas_roll_pid_i;   /* 적분기 상태 */
    double scas_pitch_pid_i;  /* 적분기 상태 */
    double scas_yaw_wo_x;     /* 워시아웃 상태 */
    double scas_yaw_pid_i;    /* 적분기 상태 */
    fcl_out_t hold;           /* nav_valid=0일 때 그대로 내보낼 직전 출력 */
} fcl_state_t;

#endif /* CLAW_FCL_TYPES_H */
