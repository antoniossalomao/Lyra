import { useOrb } from '../useOrb';

interface OrbProps {
  size: number; // displayed CSS size (px)
  variant?: 'mini' | 'centerpiece';
}

// Internal canvas resolution is fixed regardless of display size so the
// point cloud stays crisp instead of pixelating when CSS shrinks it.
const MINI_RENDER_PX = 60;
const CENTER_RENDER_PX = 180;

export default function Orb({ size, variant = 'mini' }: OrbProps) {
  const isCenter = variant === 'centerpiece';
  const canvasRef = useOrb(
    isCenter
      ? { pointCount: 46, linkDist: 34, speed: 0.0035, dotRadius: 1.5, lineWidth: 0.6 }
      : { pointCount: 16, linkDist: MINI_RENDER_PX * 0.4, speed: 0.006, dotRadius: 3.6, lineWidth: 1.1 },
  );

  const renderPx = isCenter ? CENTER_RENDER_PX : MINI_RENDER_PX;

  return (
    <canvas
      ref={canvasRef}
      width={renderPx}
      height={renderPx}
      style={{ width: size, height: size, flexShrink: 0 }}
      className={isCenter ? 'orb-canvas' : 'mini-orb'}
    />
  );
}
