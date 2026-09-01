import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/** 가상환경 탭 빌드 설정.
 *
 * ## 왜 라이브러리 빌드인가
 *
 * 이 앱은 자기 페이지를 갖지 않는다. `web/index.html`이 여전히 진입점이고, 해시
 * 라우터(`web/js/main.js`)가 `#world`에서 이 번들을 동적 import해 컨테이너에 붙인다.
 * `<iframe>`을 쓰지 않는 이유는 기존 `dispose()` 훅(WebGL 컨텍스트 반납)이 그대로
 * 살아야 하기 때문이다 — 컨텍스트는 브라우저당 8~16개뿐이다.
 *
 * ## 왜 파일 이름에 해시가 없나
 *
 * `main.js`가 경로를 문자열로 들고 있어야 한다. 해시가 붙으면 빌드마다 그 문자열을
 * 고쳐야 하고, 안 고치면 404가 난다. 대신 서버가 `NoCacheStaticFiles`로 서빙하므로
 * 캐시 무효화는 해시가 아니라 헤더가 맡는다.
 *
 * ## 왜 미니파이를 끄나
 *
 * `web/js/vendor/three/VERSION`이 "비-미니파이드 — 사람이 읽을 수 있는 소스"를
 * 폐쇄망 반입 심사 요건으로 못박아 두었다. 산출물을 커밋해 반입하므로 그 조항이
 * 여기에도 걸린다. 크기는 반입본 three(2.0 MB)를 걷어내는 것으로 상쇄한다.
 */
export default defineConfig(({ mode }) => ({
  base: "/world/build/",
  plugins: [react()],
  // **라이브러리 모드는 이 치환을 안 해 준다** — 소비자 번들러가 할 것으로 보고 미룬다.
  // 그런데 이 번들의 소비자는 브라우저이고 `process`가 없어서, 안 박으면 화면이
  // `process is not defined`로 죽는다(실측).
  //
  // 모드로 가르는 이유: production을 박으면 React가 개발 전용 코드를 통째로 뺀다
  // (1.22 MB → 215 KB). 그런데 그 코드에 **StrictMode의 이중 마운트**가 들어 있어,
  // 항상 production으로 박으면 StrictMode가 아무 일도 안 하는 장식이 된다. 렌더러를
  // 두 번 만드는 버그는 정확히 그 이중 마운트가 잡아 주는 부류라, `npm run dev`는
  // development로 굽는다. **커밋하는 것은 production 빌드다.**
  define: {
    "process.env.NODE_ENV": JSON.stringify(mode === "development" ? "development" : "production"),
  },
  build: {
    outDir: "build",
    emptyOutDir: true,
    target: "es2022",
    minify: false,
    sourcemap: false,
    cssCodeSplit: false,
    lib: {
      entry: "src/main.tsx",
      formats: ["es"],
      fileName: () => "world.js",
    },
    rollupOptions: {
      // 아무것도 external로 두지 않는다 — 한 파일만 import하면 되게.
      output: { assetFileNames: "world.[ext]" },
    },
  },
}));
