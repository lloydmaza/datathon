// ── Colors (matching Python Dash app) ────────────────────────────────────────
export const COLORS = {
  paper:   '#25262B',
  bg:      '#1A1B1E',
  card:    '#2C2E33',
  grid:    'rgba(255,255,255,0.07)',
  hist:    'rgba(64, 192, 255, 0.45)',
  kde:     '#40C0FF',
  cdf:     '#20D9A0',
  median:  'rgba(255,255,255,0.7)',
  bib:     '#FF6B6B',
}

export const BIN_WIDTH = 5 // minutes
export const ADAPTIVE_CATEGORIES = new Set(['Wheelchair', 'Handcycle'])

export const AGE_GROUP_BINS   = [0, 18, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, Infinity]
export const AGE_GROUP_LABELS = ['<18','18-24','25-29','30-34','35-39','40-44',
                                 '45-49','50-54','55-59','60-64','65-69','70-74','75-79','80+']

// ── Time formatting ───────────────────────────────────────────────────────────
export function fmtMinutes(mins) {
  if (mins == null || isNaN(mins)) return '—'
  const h = Math.floor(mins / 60)
  const m = Math.floor(mins % 60)
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}` : `${m}:00`
}

export function fmtMs(ms) {
  if (ms == null || isNaN(ms)) return '—'
  const total = Math.floor(ms / 1000)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export function fmtPace(secPerMile) {
  if (!secPerMile || secPerMile <= 0) return '—'
  const m = Math.floor(secPerMile / 60)
  const s = Math.round(secPerMile % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

// ── KDE ───────────────────────────────────────────────────────────────────────
function mean(arr) { return arr.reduce((a, b) => a + b, 0) / arr.length }
function variance(arr) {
  const m = mean(arr)
  return arr.reduce((a, b) => a + (b - m) ** 2, 0) / arr.length
}

export function scottBandwidth(arr) {
  return 1.06 * Math.sqrt(variance(arr)) * Math.pow(arr.length, -0.2)
}

export function gaussianKDE(data, bw, evalPoints) {
  const sqrt2pi = Math.sqrt(2 * Math.PI)
  return evalPoints.map(x => {
    let sum = 0
    for (const xi of data) {
      const u = (x - xi) / bw
      sum += Math.exp(-0.5 * u * u)
    }
    return sum / (data.length * bw * sqrt2pi)
  })
}

// ── Histogram ─────────────────────────────────────────────────────────────────
export function computeHistogram(times, binWidth = BIN_WIDTH) {
  if (!times.length) return { edges: [], centers: [], counts: [] }
  const xMin = Math.floor(Math.min(...times) / binWidth) * binWidth
  const xMax = (Math.floor(Math.max(...times) / binWidth) + 1) * binWidth
  const edges = []
  for (let e = xMin; e <= xMax + binWidth * 0.5; e += binWidth) edges.push(e)
  const counts = new Array(edges.length - 1).fill(0)
  const centers = edges.slice(0, -1).map((e, i) => (e + edges[i + 1]) / 2)
  for (const t of times) {
    const idx = Math.floor((t - xMin) / binWidth)
    if (idx >= 0 && idx < counts.length) counts[idx]++
  }
  return { edges, centers, counts }
}

// ── CDF ───────────────────────────────────────────────────────────────────────
export function computeCDF(times) {
  const sorted = [...times].sort((a, b) => a - b)
  const cdf = sorted.map((_, i) => (i + 1) / sorted.length)
  return { sorted, cdf }
}

// ── Tick labels ───────────────────────────────────────────────────────────────
export function timeTicks(times) {
  if (!times.length) return { vals: [], text: [] }
  const tickMin = Math.floor(Math.min(...times) / 30) * 30
  const tickMax = (Math.floor(Math.max(...times) / 30) + 1) * 30
  const vals = []
  for (let v = tickMin; v <= tickMax; v += 30) vals.push(v)
  return { vals, text: vals.map(fmtMinutes) }
}

// ── Pace / speed conversion ───────────────────────────────────────────────────
export function toSpeed(secPerMile) {
  return secPerMile > 0 ? 3600 / secPerMile : null
}

// ── Finisher filter ───────────────────────────────────────────────────────────
export function isFinisher(r) {
  return !r.dnf && !r.dq && !r.short_course
}

export function applyFilters(runners, { gender, ageGroup, category }, hasCat) {
  return runners.filter(r => {
    if (!isFinisher(r)) return false
    if (gender !== 'All' && r.sex !== gender) return false
    if (ageGroup !== 'All' && r.age_group !== ageGroup) return false
    if (hasCat && category !== 'All') {
      if (category === 'Runners'  &&  ADAPTIVE_CATEGORIES.has(r.category)) return false
      if (category === 'Adaptive' && !ADAPTIVE_CATEGORIES.has(r.category)) return false
    }
    return true
  })
}
