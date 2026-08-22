/* CLAW 생성 코드 — 손으로 고치지 말 것 (구조는 IR, 값은 파라미터에서 나온다).
 * 그래프  : scas_yaw
 * 지문    : 19a1c5a4102ee3c3
 * 엔진    : claw 0.1.0
 * 자료형 (MATLAB _types.h 대응)
 */
#ifndef CLAW_SCAS_YAW_TYPES_H
#define CLAW_SCAS_YAW_TYPES_H

/* 파라미터 (MATLAB rtP 대응) — 실제로 참조되는 것만 있다:
 * 게인 스케줄로 신호가 된 값은 여기 남지 않는다. */
typedef struct {
    double wo_p;            /* exp(-dt/tau), tau=2.0 s — SCAS_YAW_DT로 구움 */
    double wo_one_minus_p;  /* 1 − p */
    double pid_kp;          /* 비례 게인 */
    double pid_ki;          /* 적분 게인 */
    double pid_out_lo;      /* 출력·적분기 클램프 하한 (안티와인드업) */
    double pid_out_hi;      /* 출력·적분기 클램프 상한 (안티와인드업) */
    double damp_k;          /* 게인 */
    double sat_lo;          /* 하한 */
    double sat_hi;          /* 상한 */
} scas_yaw_params_t;

/* 상태 (MATLAB rtDW 대응) — 범프리스 전환은 리셋 후 이 필드를 직접 쓴다. */
typedef struct {
    double wo_x;   /* 워시아웃 상태 */
    double pid_i;  /* 적분기 상태 */
} scas_yaw_state_t;

#endif /* CLAW_SCAS_YAW_TYPES_H */
