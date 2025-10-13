import React, { useEffect, useState, useMemo } from 'react';
import { AppBar, Toolbar, Typography, IconButton, Button, Box } from '@mui/material';
import DarkModeIcon from '@mui/icons-material/DarkMode';

export default function DailyGraph() {
  const API_BASE = process.env.REACT_APP_API_BASE || `${window.location.protocol}//${window.location.hostname}:8000`;
  const [data, setData] = useState([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [chartType, setChartType] = useState('bar'); // 'bar' | 'line'
  const [hover, setHover] = useState(null); // { x, y, day, label, value, color }
  const [show, setShow] = useState({ Total: true, Passed: true, Failed: true });

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const res = await fetch(`${API_BASE}/daily-stats`);
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.error || `Failed to load daily stats (${res.status})`);
        }
        const j = await res.json();
        if (alive) setData(Array.isArray(j?.stats) ? j.stats : []);
      } catch (e) {
        if (alive) setError(e.message || 'Failed to load');
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [API_BASE]);

  const dims = { w: 900, h: 320, pad: 40 };
  const series = useMemo(() => {
    const days = data.map(d => d.day);
    const totals = data.map(d => d.total);
    const failed = data.map(d => d.failed);
    const passed = data.map(d => d.passed);
    const minY = 0;
    const maxY = Math.max(10, ...totals);
    const scaleX = (i) => dims.pad + (i * (dims.w - 2 * dims.pad)) / Math.max(1, days.length - 1);
    const scaleY = (v) => dims.h - dims.pad - (v - minY) * (dims.h - 2 * dims.pad) / Math.max(1, (maxY - minY));
    const toPath = (arr) => arr.map((v, i) => `${i === 0 ? 'M' : 'L'} ${scaleX(i)} ${scaleY(v)}`).join(' ');
    return {
      days,
      maxY,
      totalsPath: toPath(totals),
      failedPath: toPath(failed),
      passedPath: toPath(passed),
      scaleX,
      scaleY
    };
  }, [data]);

  if (loading) return <div style={{ padding: 16 }}>Loading daily stats…</div>;
  if (error) return <div style={{ padding: 16, color: 'crimson' }}>{error}</div>;

  const rangeLabel = data && data.length > 0 ? `${data[0].day} → ${data[data.length - 1].day}` : '-';

  return (
    <div>
      <AppBar position="static" color="transparent" elevation={0} sx={{
        background: 'linear-gradient(90deg, #0EA5E9 0%, #2563EB 50%, #7C3AED 100%)'
      }}>
        <Toolbar>
          <Typography variant="h5" sx={{ flexGrow: 1 }}>
            Daily Submissions (Total / Passed / Failed)
          </Typography>
          <Typography variant="body1" sx={{ opacity: 0.9, mr: 1 }}>
            <strong>Range:</strong> {rangeLabel}
          </Typography>
          <IconButton color="inherit" size="small" aria-label="Toggle theme">
            <DarkModeIcon fontSize="small" />
          </IconButton>
        </Toolbar>
      </AppBar>
      <Box sx={{ p: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', mb: 1, gap: 1 }}>
          <Button onClick={() => setChartType('bar')} variant={chartType==='bar' ? 'contained' : 'outlined'} size="small" sx={{ textTransform: 'none' }}>Bar</Button>
          <Button onClick={() => setChartType('line')} variant={chartType==='line' ? 'contained' : 'outlined'} size="small" sx={{ textTransform: 'none' }}>Line</Button>
        </Box>
        
        <div style={{ padding: 0 }}>
          <svg width={dims.w} height={dims.h} style={{ border: '1px solid #e5e7eb', background: '#fff' }}>
        <defs>
          <filter id="barShadow" x="-20%" y="-20%" width="140%" height="140%">
            <feDropShadow dx="0" dy="2" stdDeviation="2" floodColor="#000000" floodOpacity="0.15" />
          </filter>
          <linearGradient id="gTotal" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#38bdf8" />
            <stop offset="100%" stopColor="#0ea5e9" />
          </linearGradient>
          <linearGradient id="gPassed" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#34d399" />
            <stop offset="100%" stopColor="#22c55e" />
          </linearGradient>
          <linearGradient id="gFailed" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#f87171" />
            <stop offset="100%" stopColor="#ef4444" />
          </linearGradient>
        </defs>
        {/* axes */}
        <line x1={dims.pad} y1={dims.h - dims.pad} x2={dims.w - dims.pad} y2={dims.h - dims.pad} stroke="#94a3b8" />
        <line x1={dims.pad} y1={dims.pad} x2={dims.pad} y2={dims.h - dims.pad} stroke="#94a3b8" />
        {/* grid + y labels */}
        {Array.from({ length: 5 }).map((_, i) => {
          const yv = Math.round((series.maxY * i) / 4);
          const y = series.scaleY(yv);
          return (
            <g key={i}>
              <line x1={dims.pad} y1={y} x2={dims.w - dims.pad} y2={y} stroke="#e5e7eb" />
              <text x={8} y={y + 4} fill="#64748b" fontSize={12}>{yv}</text>
            </g>
          );
        })}
        {chartType === 'line' ? (
          <>
            {show.Total && <path d={series.totalsPath} fill="none" stroke="#0ea5e9" strokeWidth={2} />}
            {show.Passed && <path d={series.passedPath} fill="none" stroke="#22c55e" strokeWidth={2} />}
            {show.Failed && <path d={series.failedPath} fill="none" stroke="#ef4444" strokeWidth={2} />}
          </>
        ) : (
          <>
            {/* alternate background bands per date for readability */}
            {data.map((d, i) => {
              const totalPlotW = (dims.w - 2 * dims.pad);
              const n = Math.max(1, data.length);
              const interGroupSpacing = 16;
              const avail = Math.max(1, totalPlotW - interGroupSpacing * (n - 1));
              const groupSlot = avail / n;
              const slotStart = dims.pad + i * (groupSlot + interGroupSpacing);
              const bandW = groupSlot;
              return (
                <rect key={`band-${d.day}`} x={slotStart} y={dims.pad} width={bandW} height={dims.h - 2 * dims.pad} fill={i % 2 === 0 ? '#f8fafc' : '#ffffff'} />
              );
            })}
            {data.map((d, i) => {
              // Compact grouped bars with explicit spacing between dates
              const totalPlotW = (dims.w - 2 * dims.pad);
              const n = Math.max(1, data.length);
              const interGroupSpacing = 16; // distance between dates
              const avail = Math.max(1, totalPlotW - interGroupSpacing * (n - 1));
              const groupSlot = avail / n; // width allocated for a group (excluding spacing)
              // Narrow bars kept adjacent
              const barGap = 2;
              const maxBarWidth = 28;
              const minBarWidth = 12;
              const barWidth = Math.max(minBarWidth, Math.min(maxBarWidth, Math.floor(groupSlot / 4)));
              const groupWidth = 3 * barWidth + 2 * barGap; // 3 bars per group
              // Start position for this group's slot (add spacing per index)
              const slotStart = dims.pad + i * (groupSlot + interGroupSpacing);
              // Center bars within the group's slot and keep a tad away from Y-axis
              const startX = slotStart + Math.max(0, (groupSlot - groupWidth) / 2) + 4;
              const bars = [
                { key: 'Total', label: 'Total', fill: 'url(#gTotal)', color: '#0ea5e9', value: d.total, x: startX + 0 * (barWidth + barGap) },
                { key: 'Passed', label: 'Passed', fill: 'url(#gPassed)', color: '#22c55e', value: d.passed, x: startX + 1 * (barWidth + barGap) },
                { key: 'Failed', label: 'Failed', fill: 'url(#gFailed)', color: '#ef4444', value: d.failed, x: startX + 2 * (barWidth + barGap) },
              ];
              return (
                <g key={d.day}>
                  {bars.filter(b => show[b.key]).map((b, idx) => {
                    const y = series.scaleY(b.value);
                    const h = Math.max(0, (dims.h - dims.pad) - y);
                    const active = hover && hover.day === d.day && hover.label === b.label;
                    return (
                      <rect
                        key={idx}
                        x={b.x}
                        y={y}
                        width={barWidth}
                        height={h}
                        fill={b.fill}
                        filter={active ? 'url(#barShadow)' : undefined}
                        onMouseEnter={() => setHover({ x: b.x + barWidth / 2, y, day: d.day, label: b.label, value: b.value, color: b.color })}
                        onMouseMove={() => setHover((prev) => prev ? { ...prev, x: b.x + barWidth / 2, y } : prev)}
                        onMouseLeave={() => setHover(null)}
                      />
                    );
                  })}
                  {/* date label under success bar (middle) */}
                  {(() => {
                    const mid = bars[1];
                    const x = mid.x + barWidth / 2;
                    return (
                      <text x={x} y={dims.h - dims.pad + 14} textAnchor="middle" fontSize={11} fill="#64748b">{String(d.day).slice(5)}</text>
                    );
                  })()}
                </g>
              );
            })}
          </>
        )}
        {/* x ticks (sparse) */}
        {chartType === 'line' && series.days.map((d, i) => (i % Math.max(1, Math.floor(series.days.length / 8)) === 0) ? (
          <g key={d}>
            <line x1={series.scaleX(i)} y1={dims.h - dims.pad} x2={series.scaleX(i)} y2={dims.h - dims.pad + 6} stroke="#94a3b8" />
            <text transform={`translate(${series.scaleX(i)}, ${dims.h - dims.pad + 24}) rotate(-35)`} textAnchor="end" fill="#64748b" fontSize={11}>{d.slice(5)}</text>
          </g>
        ) : null)}
        {/* legend (click to toggle series) */}
        <g>
          <rect x={dims.w - 260} y={10} width={14} height={14} rx={3} fill={show.Total ? '#0ea5e9' : '#cbd5e1'} style={{ cursor: 'pointer' }} onClick={() => setShow(s => ({ ...s, Total: !s.Total }))} />
          <text x={dims.w - 242} y={22} fontSize={12} fill="#0f172a" style={{ cursor: 'pointer' }} onClick={() => setShow(s => ({ ...s, Total: !s.Total }))}>Total</text>
          <rect x={dims.w - 200} y={10} width={14} height={14} rx={3} fill={show.Passed ? '#22c55e' : '#cbd5e1'} style={{ cursor: 'pointer' }} onClick={() => setShow(s => ({ ...s, Passed: !s.Passed }))} />
          <text x={dims.w - 182} y={22} fontSize={12} fill="#0f172a" style={{ cursor: 'pointer' }} onClick={() => setShow(s => ({ ...s, Passed: !s.Passed }))}>Passed</text>
          <rect x={dims.w - 140} y={10} width={14} height={14} rx={3} fill={show.Failed ? '#ef4444' : '#cbd5e1'} style={{ cursor: 'pointer' }} onClick={() => setShow(s => ({ ...s, Failed: !s.Failed }))} />
          <text x={dims.w - 122} y={22} fontSize={12} fill="#0f172a" style={{ cursor: 'pointer' }} onClick={() => setShow(s => ({ ...s, Failed: !s.Failed }))}>Failed</text>
        </g>
        {/* tooltip */}
        {hover && (
          <g pointerEvents="none" transform={`translate(${Math.min(Math.max(hover.x, dims.pad + 8), dims.w - dims.pad - 140)}, ${Math.max(hover.y - 36, 8)})`}>
            <rect width="140" height="44" rx="6" fill="#111827" opacity="0.92" />
            <text x="10" y="18" fill="#e5e7eb" fontSize="12">{hover.day}</text>
            <text x="10" y="34" fill="#ffffff" fontSize="12">
              <tspan fill={hover.color} fontWeight="700">{hover.label}:</tspan> {hover.value}
            </text>
          </g>
        )}
      </svg>
        </div>
      </Box>
    </div>
  );
}
