import { useState, useMemo, useCallback } from 'react'
import { useManifest, useRaceData, useSplits } from './hooks/useRaceData.js'
import { applyFilters } from './utils/stats.js'
import RaceSelector from './components/RaceSelector.jsx'
import Filters      from './components/Filters.jsx'
import SearchBar    from './components/SearchBar.jsx'
import MainChart    from './components/MainChart.jsx'
import RunnerPanel  from './components/RunnerPanel.jsx'

const DEFAULT_FILTERS = { gender: 'All', ageGroup: 'All', category: 'All' }

export default function App() {
  const manifest                        = useManifest()
  const [selectedRace, setSelectedRace] = useState(null)
  const [filters,  setFilters]          = useState(DEFAULT_FILTERS)
  const [activeBib, setActiveBib]       = useState('')

  const { data, loading, error }        = useRaceData(selectedRace)
  const meta                            = data?.meta ?? null
  const runners                         = data?.runners ?? []

  // Load splits lazily when the first runner is selected
  const { splits, loadingSplits } = useSplits(
    selectedRace,
    !!(activeBib && meta?.has_splits),
  )

  const handleRaceChange = useCallback(key => {
    setSelectedRace(key)
    setFilters(DEFAULT_FILTERS)
    setActiveBib('')
  }, [])

  const finishers = useMemo(() =>
    applyFilters(runners, filters, meta?.has_category),
  [runners, filters, meta])

  const activeRunner = useMemo(() =>
    activeBib ? runners.find(r => String(r.bib) === activeBib) ?? null : null,
  [activeBib, runners])

  return (
    <>
      <header className="header">
        <h1>Race Results</h1>
        <RaceSelector manifest={manifest} selected={selectedRace} onChange={handleRaceChange} />
      </header>

      {selectedRace && (
        <div className="controls">
          <Filters runners={runners} meta={meta} filters={filters} onChange={setFilters} />
          <SearchBar runners={runners} activeBib={activeBib} onBibChange={setActiveBib} />
        </div>
      )}

      {loading && <div className="loading">Loading race data…</div>}
      {error   && <div className="loading">Error: {error}</div>}

      {!loading && data && (
        <>
          <MainChart
            finishers={finishers}
            allRunners={runners}
            meta={meta}
            activeBib={activeBib}
            onBibClick={setActiveBib}
          />
          <div className="runner-panel-wrapper">
            <RunnerPanel
              runner={activeRunner}
              finishers={finishers}
              splits={splits}
              loadingSplits={loadingSplits}
              meta={meta}
            />
          </div>
        </>
      )}

      {!selectedRace && !loading && (
        <div className="loading">Select a race to get started.</div>
      )}

      <footer className="footer">
        &copy; {new Date().getFullYear()} Lloyd Maza. All rights reserved.
      </footer>
    </>
  )
}
