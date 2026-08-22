/* CLAW 생성 코드 — 손으로 고치지 말 것.
 * 산출물 공용 런타임 (MATLAB _sharedutils 대응). 제어법칙 형상과 무관하므로
 * 지문을 갖지 않는다 — 산출물이 여럿이어도 이 한 벌을 함께 쓴다.
 */
#include "claw_rt.h"

#include <math.h>

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

/* 1D 선형 보간, 외삽 clip — tables/table.py:54 interp()와 같은 구간 선택 */
double claw_lookup1d(const double *bp, const double *val, int n, double x)
{
    int i = 0;
    while (i < n - 2 && x >= bp[i + 1]) { i++; }
    const double t = claw_clip((x - bp[i]) / (bp[i + 1] - bp[i]), 0.0, 1.0);
    return (1.0 - t) * val[i] + t * val[i + 1];
}
