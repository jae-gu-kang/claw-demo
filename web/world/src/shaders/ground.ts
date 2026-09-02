/** 지면 절차 재질 — 고도 램프 위에 **무늬**를 얹는다. 텍스처 0장.
 *
 * ## 무엇을 고치나
 *
 * 지형은 지금까지 고도 램프 단색이었고, 모든 와이드샷에서 찰흙 모형처럼 읽혔다 —
 * 실사와의 거리를 만드는 가장 큰 티였다. 위성 영상이 정답이지만 그것은 반입·라이선스
 * 문제라, 그 전까지는 절차 무늬가 메운다:
 *
 *     경사    가파르면 암반 — 채도를 죽이고 살짝 데운 회갈색
 *     식생    평평한 곳의 얼룩 — 85 m 규모 노이즈로 밭·숲 조각 느낌
 *     매크로  800 m 밝기 변조 — 단색 띠를 깬다
 *     근접    6 m 디테일 — 픽셀이 커지면 접는다(멀리서 지글거리지 않게)
 *
 * 전부 **표시용**이고 실제 지표 피복이 아니다 — 캡션이 말한다(terrain.ts의 문구 개정).
 *
 * ## 어디에 끼나
 *
 * `<metalnessmap_fragment>` 뒤 — 정점색(고도 램프)이 diffuseColor에 곱해진 뒤다. 그래서
 * 고도 정보는 램프가 계속 들고 있고, 여기는 그 위의 변조만 한다. 좌표는 월드를 쓴다 —
 * 지형은 움직이지도 커지지도 않아서 로컬과 월드가 같은 것이나 다름없고, 티어 두 장이
 * **같은 좌표계**에서 이어져야 경계에서 무늬가 끊기지 않는다.
 *
 * ## 구름 그림자도 여기서
 *
 * 알베도에 곱한다 — 램버트에서 알베도 배율은 직사·주변광 응답 배율과 같아서 가장 싼
 * 자리다. 주변광까지 어두워지는 과장은 cloudShadowAt의 바닥(0.45)이 되돌린다.
 * `CLOUD_UNIFORM_DECL`·`NOISE_GLSL`·`CLOUD_COVER_GLSL`·태양 방향이 앞에 있어야 한다.
 */

export const GROUND_VARYING_DECL = /* glsl */`
varying vec3 vGroundWorld;
varying vec3 vGroundNormal;
`;

/** 정점 — `<fog_vertex>` 뒤. */
export const GROUND_VERT_BODY = /* glsl */`
  vGroundWorld = (modelMatrix * vec4(transformed, 1.0)).xyz;
  vGroundNormal = normalize(mat3(modelMatrix) * objectNormal);
`;

/** 조각 — `<metalnessmap_fragment>` 뒤.
 *
 * `<color_fragment>` 뒤가 아니다 — 처음에 거기 뒀다가 컴파일이 깨졌다: roughnessFactor는
 * `<roughnessmap_fragment>`에서 선언되는데 color_fragment는 그보다 앞이다. 정점색(고도
 * 램프)은 color_fragment에서 이미 diffuseColor에 곱해져 있으므로 여기서 읽어도 같다. */
export const GROUND_FRAG_BODY = /* glsl */`
  {
    vec3 gp = vGroundWorld;
    vec3 gn = normalize(vGroundNormal);
    float slope = 1.0 - clamp(gn.y, 0.0, 1.0);
    vec3 col = diffuseColor.rgb;

    // 식생 얼룩 — 평평한 저지대에서만. 초록을 더하는 게 아니라 **초록 쪽으로 기울인다**
    // (램프가 이미 고도에 따라 색을 갖고 있다 — 그 위의 변조여야 고도 정보가 산다).
    float veg = fbm3(gp * (1.0 / 85.0) + 7.3);
    float flat_ = 1.0 - smoothstep(0.22, 0.45, slope);
    col = mix(col, col * vec3(0.74, 0.92, 0.58), smoothstep(0.42, 0.72, veg) * flat_ * 0.55);

    // 암반 — 가파른 곳. 채도를 죽이고 데운 회갈색으로.
    float lum = dot(col, vec3(0.333));
    vec3 rock = mix(vec3(lum), col, 0.35) * vec3(0.86, 0.80, 0.74);
    col = mix(col, rock, smoothstep(0.30, 0.60, slope));

    // 매크로 변조(800 m) + 근접 디테일(6 m — 픽셀이 커지면 접는다).
    float macro = fbm3(gp * (1.0 / 800.0) + 3.1) - 0.44;
    float pw = length(fwidth(gp));
    float detFade = 1.0 - smoothstep(2.0, 8.0, pw);
    float det = detFade > 0.01 ? (vnoise3(gp * (1.0 / 6.0)) - 0.5) * detFade : 0.0;
    col *= clamp(1.0 + macro * 0.34 + det * 0.26, 0.55, 1.45);

    // 구름 그림자 — 하늘 적분과 같은 덮임 함수를 읽는다.
    col *= cloudShadowAt(gp, uSunDirWorld);

    diffuseColor.rgb = clamp(col, 0.0, 1.0);
    // 암반은 매끈한 잔디보다 거칠다 — 거칠기도 경사를 따라간다.
    roughnessFactor = min(roughnessFactor + slope * 0.05, 1.0);
  }
`;
