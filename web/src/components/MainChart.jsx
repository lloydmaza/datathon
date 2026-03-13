import { useMemo, useCallback, useState, useEffect } from 'react'
import Plot from '../PlotlyChart.jsx'
import {
  COLORS, BIN_WIDTH,
  computeHistogram, computeCDF, gaussianKDE, scottBandwidth, timeTicks,
  fmtMinutes,
} from '../utils/stats.js'

const isTouchDevice = typeof window !== 'undefined' && window.matchMedia('(pointer: coarse)').matches

const LAYOUT_BASE = {
  template:        'plotly_dark',
  paper_bgcolor:   COLORS.paper,
  plot_bgcolor:    COLORS.bg,
  showlegend:      false,
  hovermode:       'closest',
  hoverlabel:      { bgcolor: '#2C2E33', font: { color: 'white' }, bordercolor: '#555' },
  margin:          { t: 60, b: 20, l: 60, r: 20 },
}

export default function MainChart({ finishers, meta, activeBib, allRunners, onBibClick }) {
  const [revision, setRevision] = useState(0)
  const [viewH, setViewH] = useState(() => window.innerHeight)
  useEffect(() => {
    const handler = () => setViewH(window.innerHeight)
    window.addEventListener('resize', handler)
    return () => window.removeEventListener('resize', handler)
  }, [])
  const chartHeight = Math.min(680, Math.round(viewH * 0.85))

  const figData = useMemo(() => {
    if (!finishers.length) return null

    const times = finishers.map(r => r.chiptime_ms / 60_000).filter(t => t > 0)
    if (times.length < 2) return null

    // Histogram
    const { edges, centers, counts } = computeHistogram(times, BIN_WIDTH)
    const binHover = centers.map((c, i) =>
      `${fmtMinutes(edges[i])} – ${fmtMinutes(edges[i + 1])}: ${counts[i].toLocaleString()} runners`
    )

    // KDE
    const bw    = scottBandwidth(times)
    const kdeX  = Array.from({ length: 300 }, (_, i) => Math.min(...times) + i * (Math.max(...times) - Math.min(...times)) / 299)
    const kdeY  = gaussianKDE(times, bw, kdeX).map(y => y * times.length * BIN_WIDTH)

    // CDF
    const { sorted: sortedTimes, cdf } = computeCDF(times)

    // Per-runner CDF scatter
    const finSorted    = [...finishers].sort((a, b) => a.chiptime_ms - b.chiptime_ms)
    const runnerTimes  = finSorted.map(r => r.chiptime_ms / 60_000)
    const runnerCDF    = finSorted.map((_, i) => (i + 1) / finSorted.length)
    const runnerBibs   = finSorted.map(r => String(r.bib))
    const runnerHover  = finSorted.map((r, i) =>
      `<b>${r.full_name}</b>  ·  #${r.bib}<br>` +
      `Finish: ${fmtMinutes(runnerTimes[i])}  ·  ${(runnerCDF[i] * 100).toFixed(1)}th pct`
    )

    const median = sortedTimes[Math.floor(sortedTimes.length / 2)]
    const { vals: tickVals, text: tickText } = timeTicks(times)

    // Active bib marker
    let bibTraces = []
    if (activeBib) {
      const runner = allRunners?.find(r => String(r.bib) === activeBib)
      if (runner?.chiptime_ms) {
        const bibMin  = runner.chiptime_ms / 60_000
        const bibCDFv = sortedTimes.filter(t => t <= bibMin).length / sortedTimes.length
        const label   = runner.full_name ? `${runner.full_name} (#${activeBib})` : `#${activeBib}`
        bibTraces = [
          {
            type: 'scatter', mode: 'markers', xaxis: 'x2', yaxis: 'y2',
            x: [bibMin], y: [bibCDFv],
            marker: { color: COLORS.bib, size: 9, symbol: 'circle', line: { color: 'white', width: 1 } },
            hovertext: [`${label}<br>${fmtMinutes(bibMin)}  (${(bibCDFv * 100).toFixed(1)}th pct)`],
            hoverinfo: 'text', showlegend: false,
          }
        ]
      }
    }

    return {
      traces: [
        // Row 1 — histogram
        {
          type: 'bar', xaxis: 'x', yaxis: 'y',
          x: centers, y: counts, width: BIN_WIDTH,
          marker: { color: COLORS.hist, line: { width: 0 } },
          customdata: binHover,
          hovertemplate: '%{customdata}<extra></extra>',
          showlegend: false,
        },
        // Row 1 — KDE
        {
          type: 'scatter', mode: 'lines', xaxis: 'x', yaxis: 'y',
          x: kdeX, y: kdeY,
          line: { color: COLORS.kde, width: 2 },
          hoverinfo: 'skip', showlegend: false,
        },
        // Row 2 — CDF line
        {
          type: 'scatter', mode: 'lines', xaxis: 'x2', yaxis: 'y2',
          x: sortedTimes, y: cdf,
          line: { color: COLORS.cdf, width: 2 },
          hoverinfo: 'skip', showlegend: false,
        },
        // Row 2 — CDF scatter (clickable)
        {
          type: 'scattergl', mode: 'markers', xaxis: 'x2', yaxis: 'y2',
          x: runnerTimes, y: runnerCDF,
          marker: { size: 6, color: COLORS.cdf, opacity: 0.45 },
          customdata: runnerBibs,
          hovertext: runnerHover,
          hovertemplate: '%{hovertext}<extra></extra>',
          showlegend: false,
        },
        ...bibTraces,
      ],
      median,
      tickVals,
      tickText,
    }
  }, [finishers, activeBib, allRunners])

  const layout = useMemo(() => {
    if (!figData) return LAYOUT_BASE
    const { median, tickVals, tickText } = figData

    const axisStyle = {
      tickvals: tickVals, ticktext: tickText, tickangle: 45,
      showgrid: true, gridcolor: COLORS.grid, zeroline: false,
    }

    const shapes = []
    const annotations = []

    // Median vlines (both subplots)
    for (const xref of ['x', 'x2']) {
      shapes.push({
        type: 'line', xref, yref: xref === 'x' ? 'y domain' : 'y2 domain',
        x0: median, x1: median, y0: 0, y1: 1,
        line: { color: COLORS.median, dash: 'dot', width: 1.5 },
      })
    }
    annotations.push({
      x: median, y: 1.0, xref: 'x', yref: 'y domain',
      text: `Median ${fmtMinutes(median)}`,
      showarrow: false, xanchor: 'left', xshift: 6, yanchor: 'top',
      font: { size: 11, color: COLORS.median },
    })

    // Active bib vlines (both subplots) + annotation
    if (activeBib) {
      const runner = allRunners?.find(r => String(r.bib) === activeBib)
      if (runner?.chiptime_ms) {
        const bibMin  = runner.chiptime_ms / 60_000
        const bibName = runner.full_name ? `${runner.full_name} (#${activeBib})` : `#${activeBib}`
        for (const [xref, yref] of [['x', 'y domain'], ['x2', 'y2 domain']]) {
          shapes.push({
            type: 'line', xref, yref,
            x0: bibMin, x1: bibMin, y0: 0, y1: 1,
            line: { color: COLORS.bib, dash: 'dash', width: 1.5 },
          })
        }
        annotations.push({
          x: bibMin, y: 1.0, xref: 'x', yref: 'y domain',
          text: bibName, showarrow: false,
          xanchor: 'right', xshift: -6, yanchor: 'top',
          font: { size: 11, color: COLORS.bib },
        })
      }
    }

    return {
      ...LAYOUT_BASE,
      height: chartHeight,
      dragmode: isTouchDevice ? false : 'zoom',
      title: {
        text: `${meta?.display_name ?? ''} — Finish Time Distribution  ·  n=${finishers.length.toLocaleString()}`,
        font: { size: 15, color: 'rgba(255,255,255,0.85)' },
        x: 0.01, xanchor: 'left',
      },
      grid:  { rows: 2, columns: 1, subplots: [['xy'], ['x2y2']], roworder: 'top to bottom' },
      xaxis:  { ...axisStyle, domain: [0, 1] },
      xaxis2: { ...axisStyle, title: { text: 'Finish time', font: { size: 12 } }, matches: 'x' },
      yaxis:  { title: { text: 'Runners' }, showgrid: true, gridcolor: COLORS.grid, zeroline: false, domain: [0.54, 1.0] },
      yaxis2: { title: { text: '% of finishers' }, tickformat: '.0%', showgrid: true, gridcolor: COLORS.grid, zeroline: false, domain: [0.0, 0.46] },
      shapes,
      annotations: annotations.map(a => ({ ...a, font: { ...a.font } })),
    }
  }, [figData, meta, finishers.length, activeBib, allRunners, chartHeight])

  const handleClick = useCallback((evt) => {
    const pt = evt?.points?.[0]
    const bib = pt?.customdata
    if (typeof bib === 'string' && bib) onBibClick?.(bib)
  }, [onBibClick])

  if (!figData) return <div className="loading">Not enough data for selected filters.</div>

  return (
    <div className="main-chart" style={{ touchAction: 'pan-y' }}>
      <Plot
        data={figData.traces}
        layout={layout}
        revision={revision}
        style={{ width: '100%' }}
        useResizeHandler
        config={{ displayModeBar: false, responsive: true, scrollZoom: false }}
        onClick={handleClick}
      />
    </div>
  )
}
