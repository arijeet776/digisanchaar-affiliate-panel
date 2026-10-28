interface Point { label: string; value: number }

export function LineChart({ points, color, format }: { points: Point[]; color: string; format?: (v: number) => string }) {
  if (points.length === 0) return <div className="qx-empty-state">No data for this period yet.</div>;
  const W = 320, H = 200, L = 34, R = 8, T = 10, B = 26;
  const max = Math.max(1, ...points.map((p) => p.value));
  const step = Math.pow(10, Math.floor(Math.log10(max)));
  const top = Math.ceil(max / step) * step;
  const x = (i: number) => L + (i * (W - L - R)) / Math.max(1, points.length - 1);
  const y = (v: number) => T + (1 - v / top) * (H - T - B);
  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(p.value)}`).join(" ");
  const area = `${path} L${x(points.length - 1)},${H - B} L${x(0)},${H - B} Z`;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => t * top);
  const gid = `g-${color.replace(/[^a-zA-Z0-9]/g, "")}`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="qx-linechart" role="img">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.25" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="var(--border)" strokeDasharray="3 4" />
          <text x={L - 6} y={y(t) + 3} textAnchor="end" fontSize="9" fill="var(--text-muted)">{format ? format(t) : Math.round(t)}</text>
        </g>
      ))}
      <path d={area} fill={`url(#${gid})`} />
      <path d={path} fill="none" stroke={color} strokeWidth="2.4" strokeLinejoin="round" strokeLinecap="round" />
      {points.map((p, i) => (i % 3 === 0 || i === points.length - 1) && (
        <text key={p.label} x={x(i)} y={H - 8} textAnchor="middle" fontSize="9" fill="var(--text-muted)">{p.label}</text>
      ))}
      {points.map((p, i) => <circle key={i} cx={x(i)} cy={y(p.value)} r="2.6" fill={color}><title>{`${p.label}: ${format ? format(p.value) : p.value}`}</title></circle>)}
    </svg>
  );
}
