/* CLAW 대조 하네스 — 생성 코드를 표준입력 시퀀스로 돌려 결과를 표준출력에 낸다.
 *
 * 이 파일은 **손으로 쓴다**. 생성기가 진입점 시그니처나 상태·파라미터 필드 이름을 잘못 내면
 * 여기서 컴파일이 깨지므로, 생성물끼리만 아귀가 맞는 채로 대조가 통과하는 일을 막는다.
 *
 * 파라미터는 코드에 없다(v1.12) — 첫 인자로 받은 **파라미터 이미지 파일**을 생성 로더로
 * 적재한다. 같은 실행 파일이 기체마다 다른 이미지로 돈다. 이미지 파일 읽기와 pool 할당은
 * 하네스(통합 계층)의 몫이라 동적 할당을 쓴다 — 생성 코드에는 없다.
 *
 * 출력은 %.17g — 배정밀도가 왕복하므로 비트 일치를 검사할 수 있다.
 */

#include <stdio.h>
#include <stdlib.h>

#if defined(HARNESS_FCL) || defined(HARNESS_FCL_MIX) || defined(HARNESS_SCAS_YAW)
/* 이미지 파일 → 버퍼. 실패하면 NULL */
static unsigned char *read_image(const char *path, size_t *len)
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
#endif

#if defined(HARNESS_FCL) || defined(HARNESS_FCL_MIX)
#include "fcl.h"

/* 이미지 파일 → fcl_params_t. pool은 프로세스 끝까지 산다(표 필드가 가리킨다) */
static int load_fcl(const char *path, fcl_params_t *prm)
{
    size_t len = 0, n = 0;
    unsigned char *img = read_image(path, &len);
    double *pool;
    int st;

    if (img == NULL) { fprintf(stderr, "이미지를 못 읽음: %s\n", path); return -1; }
    st = fcl_params_pool_size(img, len, &n);
    if (st != FCL_PARAMS_OK) { fprintf(stderr, "이미지 거부 %d\n", st); return st; }
    pool = malloc(n * sizeof *pool);
    st = fcl_params_load(img, len, pool, n, prm);
    free(img);
    if (st != FCL_PARAMS_OK) { fprintf(stderr, "적재 실패 %d\n", st); }
    return st;
}
#endif

#if defined(HARNESS_FCL)

/* 첫 줄: 트림 웜스타트 (de0 th0 thr0). 생성 코드에 별도 웜스타트 API는 없고
 * 리셋 후 상태 필드를 직접 쓰는 것이 계약이다 (fcl.h 주석) — 그 계약을 여기서 쓴다. */
int main(int argc, char **argv)
{
    fcl_params_t prm;
    fcl_state_t s;
    fcl_out_t out;
    double de0, th0, thr0;
    double nav_valid, theta, phi, psi, p, q, r, V, alpha, beta, h, hdot, mach;
    double cmd_speed, cmd_alt, cmd_heading, cmd_pitch, cmd_hdot;
    double speed_on, alt_on, heading_on, pitch_on, hdot_on;

    if (argc < 2 || load_fcl(argv[1], &prm) != FCL_PARAMS_OK) { return 2; }
    if (scanf("%lf %lf %lf", &de0, &th0, &thr0) != 3) { return 1; }
    fcl_reset(&s);
    s.scas_pitch_pid_i = de0;   /* law.py:71  scas.pitch.reset(de0) */
    s.ap_alt_pid_i = th0;       /* autopilot.py:134  _alt.reset(theta) */
    s.ap_spd_pid_i = thr0;      /* autopilot.py:132  _spd.reset(throttle) */
    s.hold.elevon_l = de0;      /* law.py:77  _hold = mixer.step(de0, 0, 0, thr0) */
    s.hold.elevon_r = de0;
    s.hold.rudder = 0.0;
    s.hold.throttle_l = thr0;
    s.hold.throttle_r = thr0;

    while (scanf("%lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf"
                 " %lf %lf %lf %lf %lf %lf %lf %lf %lf %lf",
                 &nav_valid, &theta, &phi, &psi, &p, &q, &r, &V, &alpha, &beta,
                 &h, &hdot, &mach, &cmd_speed, &cmd_alt, &cmd_heading,
                 &cmd_pitch, &cmd_hdot,
                 &speed_on, &alt_on, &heading_on, &pitch_on, &hdot_on) == 23) {
        fcl_step(&prm, &s, &out,
                 nav_valid, theta, phi, psi, p, q, r, V, alpha, beta, h, hdot, mach,
                 cmd_speed, cmd_alt, cmd_heading, cmd_pitch, cmd_hdot,
                 speed_on, alt_on, heading_on, pitch_on, hdot_on);
        printf("%.17g %.17g %.17g %.17g %.17g %.17g %.17g\n",
               out.elevon_l, out.elevon_r, out.rudder, out.throttle_l, out.throttle_r,
               out.limiter_active, out.alpha_margin);
    }
    return 0;
}

#elif defined(HARNESS_FCL_MIX)
#include "fcl_mix.h"

/* 믹서만 떼어 돌린다 — 차동추력 배분(mix_diff_k)을 **켠 채로** 대조하기 위해서다.
 *
 * 이 기체는 단발이라 mix_diff_k = 0이고, 그러면 배분식이 항상 ±0.0이라 좌우 스로틀이
 * 같은 값으로 무너진다. 그 상태에서는 배분의 부호를 뒤집거나 좌우 출력을 맞바꿔도
 * 비트 일치가 그대로 통과한다(리뷰에서 변이 주입으로 재현). 쌍발 형상을 다시 물리는
 * 순간 그 결함이 탑재 코드에 그대로 실린다.
 *
 * 계수는 파라미터 필드라 적재한 구조체에 덮어쓰면 된다. 첫 줄이 mix_diff_k, 이후 각 줄이
 * (thr de da dr). */
int main(int argc, char **argv)
{
    fcl_params_t prm;
    fcl_state_t s;
    double thr, de, da, dr;
    double el, er, rud, tl, tr;

    if (argc < 2 || load_fcl(argv[1], &prm) != FCL_PARAMS_OK) { return 2; }
    if (scanf("%lf", &prm.mix_diff_k) != 1) { return 1; }
    fcl_reset(&s);
    while (scanf("%lf %lf %lf %lf", &thr, &de, &da, &dr) == 4) {
        /* 인자 순서는 **생성기가 정한다** — 축 선언 순서가 바뀌면 여기 순서도 바뀐다
         * (제어권한 배분으로 롤이 피치보다 먼저 선언되면서 실제로 뒤바뀌었다).
         * 전부 double이라 컴파일러가 안 잡아 주므로, 헤더의 인자 이름을 그대로
         * 옮겨 적어 사람이 보게 둔다: (thr, roll, pitch, yaw) */
        fcl_mix_step(&prm, &s, thr, da, de, dr, &el, &er, &rud, &tl, &tr);
        printf("%.17g %.17g %.17g %.17g %.17g\n", el, er, rud, tl, tr);
    }
    return 0;
}

#elif defined(HARNESS_FCL_PARAMS)
#include "fcl.h"

/* 로더 거부 경로 — 한 줄 = "pool_delta 16진이미지". 줄마다 적재 상태를 내고, 성공이면
 * 적재한 필드 몇 개를 함께 낸다(표 포인터·점 수가 이미지의 제자리를 가리키는지). */
int main(void)
{
    size_t cap = 1U << 16, len;
    unsigned char *img = malloc(cap);
    int delta, c, hi, lo;

    while (img != NULL && scanf("%d", &delta) == 1) {
        fcl_params_t prm;
        size_t n = 0;
        double *pool;
        int st;

        len = 0;
        while ((c = getchar()) == ' ') { }
        while (c != '\n' && c != EOF) {
            hi = (c <= '9') ? c - '0' : c - 'a' + 10;
            c = getchar();
            lo = (c <= '9') ? c - '0' : c - 'a' + 10;
            if (len == cap) { cap *= 2U; img = realloc(img, cap); if (img == NULL) { return 3; } }
            img[len++] = (unsigned char)(hi * 16 + lo);
            c = getchar();
        }
        (void)fcl_params_pool_size(img, len, &n);  /* pool 크기만 — 거부 판정은 load가 낸다 */
        pool = malloc((n + 1U) * sizeof *pool);
        st = fcl_params_load(img, len, pool, (size_t)((long)n + delta), &prm);
        if (st == FCL_PARAMS_OK) {
            printf("%d %d %.17g %.17g %.17g\n", st, prm.sched_pitch_kp_n,
                   prm.sched_pitch_kp_val[prm.sched_pitch_kp_n - 1], prm.lim_alpha_max_c,
                   prm.mix_diff_k);
        } else {
            printf("%d\n", st);
        }
        free(pool);
    }
    free(img);
    return 0;
}

#elif defined(HARNESS_SCAS_YAW)
#include "scas_yaw.h"

int main(int argc, char **argv)
{
    scas_yaw_params_t prm;
    scas_yaw_state_t s;
    double att_err, rate;
    size_t len = 0, n = 0;
    unsigned char *img = (argc > 1) ? read_image(argv[1], &len) : NULL;
    double *pool;

    if (img == NULL || scas_yaw_params_pool_size(img, len, &n) != SCAS_YAW_PARAMS_OK) { return 2; }
    pool = malloc(n * sizeof *pool);
    if (scas_yaw_params_load(img, len, pool, n, &prm) != SCAS_YAW_PARAMS_OK) { return 2; }
    scas_yaw_reset(&s);
    while (scanf("%lf %lf", &att_err, &rate) == 2) {
        printf("%.17g\n", scas_yaw_step(&prm, &s, att_err, rate));
    }
    return 0;
}

#else
#error "그래프 선택 매크로가 필요하다 (-DHARNESS_FCL / -DHARNESS_FCL_MIX / -DHARNESS_FCL_PARAMS / -DHARNESS_SCAS_YAW)"
#endif
