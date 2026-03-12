import { useState, useEffect, useRef, useMemo } from 'react'

export default function SearchBar({ runners, activeBib, onBibChange }) {
  const [bibInput,  setBibInput]  = useState('')
  const [nameQuery, setNameQuery] = useState('')
  const [showDrop,  setShowDrop]  = useState(false)
  const dropRef = useRef(null)

  // Sync fields when activeBib changes externally (e.g. CDF click)
  useEffect(() => {
    if (!activeBib) { setBibInput(''); setNameQuery(''); return }
    const runner = runners?.find(r => String(r.bib) === activeBib)
    if (runner) {
      setBibInput(activeBib)
      setNameQuery(runner.full_name || '')
    }
  }, [activeBib, runners])

  // Close dropdown on outside click
  useEffect(() => {
    const handler = e => { if (!dropRef.current?.contains(e.target)) setShowDrop(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const matches = useMemo(() => {
    const q = nameQuery.trim().toLowerCase()
    if (q.length < 2 || !runners?.length) return []
    return runners.filter(r => r.full_name?.toLowerCase().includes(q)).slice(0, 20)
  }, [nameQuery, runners])

  function handleBibKeyDown(e) {
    if (e.key === 'Enter') onBibChange(bibInput.trim())
  }

  function handleNameChange(e) {
    setNameQuery(e.target.value)
    setShowDrop(true)
    // If name field is cleared, clear active bib too
    if (!e.target.value.trim()) onBibChange('')
  }

  function selectRunner(runner) {
    setBibInput(String(runner.bib))
    setNameQuery(runner.full_name || '')
    setShowDrop(false)
    onBibChange(String(runner.bib))
  }

  return (
    <div className="search-area">
      <div className="field">
        <label>Bib</label>
        <input
          type="text"
          value={bibInput}
          placeholder="e.g. 1234"
          style={{ width: 90 }}
          onChange={e => setBibInput(e.target.value)}
          onKeyDown={handleBibKeyDown}
          onBlur={() => onBibChange(bibInput.trim())}
        />
      </div>

      <div className="field search-results" ref={dropRef}>
        <label>Name search</label>
        <input
          type="text"
          value={nameQuery}
          placeholder="First or last name"
          style={{ width: 200 }}
          onChange={handleNameChange}
          onFocus={() => matches.length && setShowDrop(true)}
        />
        {showDrop && matches.length > 0 && (
          <div className="search-dropdown">
            {matches.map(r => (
              <button key={r.bib} onMouseDown={() => selectRunner(r)}>
                {r.full_name}  #{r.bib}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
