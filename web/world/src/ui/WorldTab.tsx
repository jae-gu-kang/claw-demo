import { useEffect, useRef, useState } from "react";

import type { MountDeps } from "../main.tsx";

const HINT = "font-size:12px; color:var(--muted); line-height:1.6;";

export function WorldTab({ deps }: { deps: MountDeps }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [note, setNote] = useState("초기화 중…");

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let disposed = false;
    setNote(`캔버스 준비됨 · 결과 ${deps.resultId ?? "(최신)"}`);
    return () => {
      disposed = true;
      void disposed;
    };
  }, [deps.resultId]);

  return (
    <section className="panel">
      <h2>가상환경</h2>
      <canvas
        ref={canvasRef}
        aria-label="가상환경 3D 캔버스"
        style={{ width: "100%", aspectRatio: "2 / 1", background: "#0d1117", borderRadius: "6px" }}
      />
      <div style={{ font: "12px/1.6 system-ui", color: "var(--muted)" }}>{note}</div>
    </section>
  );
}
