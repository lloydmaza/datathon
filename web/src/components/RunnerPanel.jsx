import { useMemo } from 'react'
import Plot from '../PlotlyChart.jsx'
import {
  COLORS, BIN_WIDTH,
  fmtMs, fmtMinutes, fmtPace, toSpeed,
  computeHistogram, timeTicks, isFinisher,
} from '../utils/stats.js'

const PAPER = { paper_bgcolor: COLORS.paper, plot_bgcolor: COLORS.bg, template: 'plotly_dark' }

function paceSecPerMile(deltaMs, distM) {
  if (!deltaMs || deltaMs <= 0 || !distM || distM <= 0) return null
  return (deltaMs / 1000) / (distM / 1609.344)
}

function SplitsChart({ bib, splits, meta }) {
  const fig = useMemo(() => {
    if (!splits?.length) return null
    const runnerSplits = splits
      .filter(s => String(s.bib) === bib && s.distance_m > 0)
      .sort((a, b) => a.displayorder - b.displayorder)
    if (!runnerSplits.length) return null

    const labels   = runnerSplits.map(s => s.label)
    const cumDists = runnerSplits.map(s => s.distance_m)
    const segDists = cumDists.map((d, i) => i === 0 ? d : d - cumDists[i - 1])

    const runnerPaces = runnerSplits.map((s, i) => paceSecPerMile(s.delta_ms, segDists[i]))

    // Field median per label
    const labelToSegDist = Object.fromEntries(labels.map((l, i) => [l, segDists[i]]))
    const medianPaces = labels.map(label => {
      const segDist = labelToSegDist[label]
      const deltas  = splits
        .filter(s => s.label === label && s.delta_ms > 0)
        .map(s => s.delta_ms)
      if (!deltas.length || !segDist) return null
      deltas.sort((a, b) => a - b)
      const med = deltas[Math.floor(deltas.length / 2)]
      return paceSecPerMile(med, segDist)
    })

    const runnerSpeeds = runnerPaces.map(toSpeed)
    const medianSpeeds = medianPaces.map(toSpeed)

    const barColors = runnerSpeeds.map((rs, i) => {
      const ms = medianSpeeds[i]
      if (rs == null || ms == null) return 'rgba(120,120,120,0.5)'
      return rs > ms ? COLORS.cdf : COLORS.bib
    })

    // First / second half split
    const halfDist = meta.distance_m / 2
    const fhMs = runnerSplits.filter(s => s.distance_m <= halfDist).reduce((a, s) => a + (s.delta_ms || 0), 0)
    const shMs = runnerSplits.filter(s => s.distance_m >  halfDist).reduce((a, s) => a + (s.delta_ms || 0), 0)
    let splitNote = ''
    if (fhMs > 0 && shMs > 0) {
      const diffMs = shMs - fhMs
      const sign   = diffMs >= 0 ? '+' : '-'
      splitNote    = `  ·  1st ${fmtMs(fhMs)} / 2nd ${fmtMs(shMs)}  (${sign}${fmtMs(Math.abs(diffMs))} ${diffMs >= 0 ? 'positive' : 'negative'} split)`
    }

    const allSpeeds = [...runnerSpeeds, ...medianSpeeds].filter(Boolean)
    const speedRange = allSpeeds.length > 1 ? Math.max(...allSpeeds) - Math.min(...allSpeeds) : 1
    const yMax = Math.max(...allSpeeds) + speedRange * 0.45
    const yMin = Math.min(...allSpeeds) - speedRange * 0.05

    return {
      data: [
        {
          type: 'bar', x: labels, y: runnerSpeeds,
          marker: { color: barColors, line: { width: 0 } },
          text: runnerPaces.map(p => p ? fmtPace(p) : '—'),
          textposition: 'outside',
          textfont: { size: 10, color: 'rgba(255,255,255,0.85)' },
          hovertext: labels.map((l, i) => runnerPaces[i] ? `${l}: ${fmtPace(runnerPaces[i])}/mi` : `${l}: missing`),
          hoverinfo: 'text', showlegend: false,
        },
        {
          type: 'scatter', mode: 'lines+markers', x: labels, y: medianSpeeds,
          line: { color: COLORS.median, dash: 'dot', width: 1.5 },
          marker: { size: 5, color: COLORS.median },
          hovertext: labels.map((l, i) => medianPaces[i] ? `Median ${l}: ${fmtPace(medianPaces[i])}/mi` : ''),
          hoverinfo: 'text', showlegend: false,
        },
      ],
      layout: {
        ...PAPER,
        title: {
          text: `Pace by Segment${splitNote}`,
          font: { size: 12, color: 'rgba(255,255,255,0.65)' }, x: 0.01,
        },
        xaxis: { showgrid: false, tickfont: { size: 11 } },
        yaxis: { showticklabels: false, showgrid: false, zeroline: false, range: [yMin, yMax] },
        annotations: [{
          x: 1, y: 1.05, xref: 'paper', yref: 'paper',
          text: `<span style='color:${COLORS.cdf}'>▌</span> faster  <span style='color:${COLORS.bib}'>▌</span> slower  <span style='color:${COLORS.median}'>- - -</span> field median`,
          showarrow: false, xanchor: 'right', yanchor: 'bottom',
          font: { size: 10, color: 'rgba(255,255,255,0.5)' },
        }],
        hovermode: 'x unified',
        hoverlabel: { bgcolor: '#2C2E33', font: { color: 'white' } },
        showlegend: false, height: 290,
        margin: { t: 50, b: 20, l: 20, r: 20 },
      },
    }
  }, [bib, splits, meta])

  if (!fig) return <div className="empty">No split data available.</div>
  return (
    <Plot data={fig.data} layout={fig.layout}
      style={{ width: '100%' }} useResizeHandler
      config={{ displayModeBar: false, responsive: true }} />
  )
}

function CohortChart({ runner, finishers }) {
  const fig = useMemo(() => {
    if (!runner?.chiptime_ms) return null
    const sex      = runner.sex
    const ageGroup = runner.age_group
    let cohort = finishers.filter(r => r.sex === sex && r.age_group === ageGroup)
    let label  = `${sex} / ${ageGroup}`
    if (cohort.length < 5) { cohort = finishers.filter(r => r.sex === sex); label = sex }
    const times = cohort.map(r => r.chiptime_ms / 60_000).filter(Boolean)
    if (times.length < 2) return null

    const bibMin = runner.chiptime_ms / 60_000
    const { edges, centers, counts } = computeHistogram(times, BIN_WIDTH)
    const barColors = edges.slice(0, -1).map((lo, i) =>
      lo <= bibMin && bibMin < edges[i + 1] ? COLORS.bib : COLORS.hist
    )
    const cohortRank = times.filter(t => t < bibMin).length + 1
    const cohortPct  = ((times.length - cohortRank) / times.length * 100).toFixed(1)
    const { vals: tickVals, text: tickText } = timeTicks(times)

    return {
      data: [{
        type: 'bar', x: centers, y: counts, width: BIN_WIDTH,
        marker: { color: barColors, line: { width: 0 } },
        hoverinfo: 'skip', showlegend: false,
      }],
      layout: {
        ...PAPER,
        title: {
          text: `Peer Cohort: ${label}  ·  Rank ${cohortRank.toLocaleString()} / ${times.length.toLocaleString()}  (${cohortPct}th pct)`,
          font: { size: 12, color: 'rgba(255,255,255,0.65)' }, x: 0.01,
        },
        shapes: [{ type: 'line', x0: bibMin, x1: bibMin, y0: 0, y1: 1,
          yref: 'y domain', line: { color: COLORS.bib, dash: 'dash', width: 1.5 } }],
        xaxis: { tickvals: tickVals, ticktext: tickText, tickangle: 45,
          title: { text: 'Finish time' }, showgrid: true, gridcolor: COLORS.grid, zeroline: false },
        yaxis: { title: { text: 'Runners' }, showgrid: true, gridcolor: COLORS.grid, zeroline: false },
        showlegend: false, height: 290,
        margin: { t: 50, b: 60, l: 60, r: 20 },
      },
    }
  }, [runner, finishers])

  if (!fig) return null
  return (
    <Plot data={fig.data} layout={fig.layout}
      style={{ width: '100%' }} useResizeHandler
      config={{ displayModeBar: false, responsive: true }} />
  )
}

function pctBadge(pct) {
  if (pct == null) return null
  const label = `${pct.toFixed(1)}th pct`
  const cls   = pct >= 50 ? 'badge green' : 'badge red'
  return <span className={cls}>{label}</span>
}

export default function RunnerPanel({ runner, allRunners, finishers, splits, meta }) {
  if (!runner) return null

  const bib      = String(runner.bib ?? '')
  const name     = runner.full_name || `Bib ${bib}`
  const chiptime = runner.chiptime || '—'
  const chipMs   = runner.chiptime_ms

  let paceStr = '—'
  if (chipMs > 0 && meta?.distance_m) {
    const spm = (chipMs / 1000) / (meta.distance_m / 1609.344)
    paceStr = `${fmtPace(spm)}/mi`
  }

  const nTotal  = finishers.length
  const sameSex = finishers.filter(r => r.sex === runner.sex)
  const sameAg  = finishers.filter(r => r.sex === runner.sex && r.age_group === runner.age_group)

  const overallRank = runner.overall
  const sexRank     = runner.oversex

  const agRank  = chipMs ? sameAg.filter(r => r.chiptime_ms < chipMs).length + 1 : null
  const agTotal = sameAg.length
  const agPct   = agRank && agTotal ? (agTotal - agRank) / agTotal * 100 : null

  const pct = (rank, total) => (rank != null && total > 0) ? (total - rank) / total * 100 : null

  const location = [runner.city, runner.state].filter(Boolean).join(', ')
  const hasSplits = splits?.some(s => String(s.bib) === bib && s.delta_ms != null)

  // Half splits + fastest/slowest segment (Xacte races only)
  let splitStats = null
  if (hasSplits && meta?.distance_m) {
    const runnerSplits = splits
      .filter(s => String(s.bib) === bib && s.distance_m > 0)
      .sort((a, b) => a.displayorder - b.displayorder)

    const cumDists = runnerSplits.map(s => s.distance_m)
    const segDists = cumDists.map((d, i) => i === 0 ? d : d - cumDists[i - 1])
    const half = meta.distance_m / 2

    const fhMs = runnerSplits
      .filter(s => s.distance_m <= half)
      .reduce((a, s) => a + (s.delta_ms || 0), 0)
    const shMs = runnerSplits
      .filter(s => s.distance_m > half)
      .reduce((a, s) => a + (s.delta_ms || 0), 0)

    const validSegs = runnerSplits
      .map((s, i) => ({ label: s.label, pace: paceSecPerMile(s.delta_ms, segDists[i]) }))
      .filter(s => s.pace != null)

    const fastest = validSegs.length ? validSegs.reduce((a, b) => a.pace < b.pace ? a : b) : null
    const slowest = validSegs.length ? validSegs.reduce((a, b) => a.pace > b.pace ? a : b) : null

    splitStats = { fhMs, shMs, fastest, slowest }
  }

  return (
    <div className="runner-panel">
      <div className="stats-card">
        <div className="name">{name}</div>
        <div className="badges">
          <span className="badge">#{bib}</span>
          {runner.sex      && <span className="badge">{runner.sex}</span>}
          {runner.age      && <span className="badge">Age {runner.age}</span>}
          {runner.age_group && <span className="badge">{runner.age_group}</span>}
          {location        && <span className="badge">{location}</span>}
        </div>
        <hr className="divider" />
        <div className="finish-time">{chiptime}</div>
        <div className="pace">{paceStr}</div>
        <hr className="divider" />
        <table className="rank-table">
          <tbody>
            <tr>
              <td>Overall</td>
              <td>{overallRank != null ? `${Number(overallRank).toLocaleString()} / ${nTotal.toLocaleString()}` : '—'}</td>
              <td>{pctBadge(pct(overallRank, nTotal))}</td>
            </tr>
            <tr>
              <td>{runner.sex ?? 'Gender'}</td>
              <td>{sexRank != null ? `${Number(sexRank).toLocaleString()} / ${sameSex.length.toLocaleString()}` : '—'}</td>
              <td>{pctBadge(pct(sexRank, sameSex.length))}</td>
            </tr>
            {agRank != null && (
              <tr>
                <td>{runner.age_group ?? 'Age group'}</td>
                <td>{`${agRank.toLocaleString()} / ${agTotal.toLocaleString()}`}</td>
                <td>{pctBadge(agPct)}</td>
              </tr>
            )}
          </tbody>
        </table>

        {splitStats && splitStats.fhMs > 0 && splitStats.shMs > 0 && (() => {
          const { fhMs, shMs, fastest, slowest } = splitStats
          const diffMs  = shMs - fhMs
          const isPos   = diffMs >= 0
          const diffStr = `${isPos ? '+' : '-'}${fmtMs(Math.abs(diffMs))}`
          return (
            <>
              <hr className="divider" />
              <table className="rank-table">
                <tbody>
                  <tr>
                    <td>1st half</td>
                    <td colSpan={2}>{fmtMs(fhMs)}</td>
                  </tr>
                  <tr>
                    <td>2nd half</td>
                    <td colSpan={2}>{fmtMs(shMs)}</td>
                  </tr>
                  <tr>
                    <td colSpan={3} style={{textAlign: 'center', paddingBottom: '4px'}}>
                      <span className={isPos ? 'badge red' : 'badge green'}>
                        {diffStr} {isPos ? 'positive' : 'negative'} split
                      </span>
                    </td>
                  </tr>
                  {fastest && (
                    <tr>
                      <td>Fastest</td>
                      <td colSpan={2}>{fastest.label}  <span style={{color:'var(--cdf)'}}>{fmtPace(fastest.pace)}/mi</span></td>
                    </tr>
                  )}
                  {slowest && slowest.label !== fastest?.label && (
                    <tr>
                      <td>Slowest</td>
                      <td colSpan={2}>{slowest.label}  <span style={{color:'var(--bib)'}}>{fmtPace(slowest.pace)}/mi</span></td>
                    </tr>
                  )}
                </tbody>
              </table>
            </>
          )
        })()}
      </div>

      <div>
        {hasSplits
          ? <SplitsChart bib={bib} splits={splits} meta={meta} />
          : <CohortChart runner={runner} finishers={finishers} />
        }
      </div>
    </div>
  )
}
