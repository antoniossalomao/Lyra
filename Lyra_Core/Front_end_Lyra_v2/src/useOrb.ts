import { useEffect, useRef } from 'react';

interface OrbOptions {
  pointCount: number;
  linkDist: number;
  speed: number;
  dotRadius: number;
  lineWidth: number;
}

// Fibonacci point-cloud sphere, rotated and projected to 2D each frame.
// Shared by the sidebar/rail mini-orb and the Focus Mode centerpiece —
// only pointCount/scale differ, so one hook drives both.
export function useOrb(options: OrbOptions) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const size = canvas.width;
    const { pointCount, linkDist, speed, dotRadius, lineWidth } = options;
    const pts: { x: number; y: number; z: number }[] = [];
    for (let i = 0; i < pointCount; i++) {
      const y = 1 - (i / (pointCount - 1)) * 2;
      const r = Math.sqrt(1 - y * y);
      const theta = Math.PI * (1 + Math.sqrt(5)) * i;
      pts.push({ x: Math.cos(theta) * r, y, z: Math.sin(theta) * r });
    }

    let angle = Math.random() * Math.PI * 2;
    const half = size / 2;
    const scaleBase = half * 0.78;
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let raf = 0;

    function frame() {
      if (!ctx) return;
      ctx.clearRect(0, 0, size, size);
      const proj = pts.map((p) => {
        const cx = p.x * Math.cos(angle) - p.z * Math.sin(angle);
        const cz = p.x * Math.sin(angle) + p.z * Math.cos(angle);
        const scale = scaleBase / (2.6 - cz);
        return { x: half + cx * scale, y: half + p.y * scale, z: cz, s: scale / scaleBase };
      });
      proj.sort((a, b) => a.z - b.z);
      for (let i = 0; i < proj.length; i++) {
        for (let j = i + 1; j < proj.length; j++) {
          const dx = proj[i].x - proj[j].x;
          const dy = proj[i].y - proj[j].y;
          const d = Math.sqrt(dx * dx + dy * dy);
          if (d < linkDist) {
            ctx.strokeStyle = `rgba(0,221,255,${(1 - d / linkDist) * 0.14 * ((proj[i].z + 1) / 2)})`;
            ctx.lineWidth = lineWidth;
            ctx.beginPath();
            ctx.moveTo(proj[i].x, proj[i].y);
            ctx.lineTo(proj[j].x, proj[j].y);
            ctx.stroke();
          }
        }
      }
      for (const p of proj) {
        const op = 0.35 + ((p.z + 1) / 2) * 0.65;
        ctx.fillStyle = `rgba(0,221,255,${op})`;
        ctx.beginPath();
        ctx.arc(p.x, p.y, dotRadius * (0.75 + p.s * 0.4), 0, 7);
        ctx.fill();
      }
      if (!reduceMotion) angle += speed;
      raf = requestAnimationFrame(frame);
    }
    frame();

    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options.pointCount, options.linkDist, options.speed, options.dotRadius, options.lineWidth]);

  return canvasRef;
}
