import { useState, useEffect, useRef } from 'react'

const BASE = import.meta.env.BASE_URL

const cache = {}

export function useManifest() {
  const [manifest, setManifest] = useState([])
  useEffect(() => {
    fetch(`${BASE}data/manifest.json`)
      .then(r => r.json())
      .then(setManifest)
      .catch(console.error)
  }, [])
  return manifest
}

export function useRaceData(raceKey) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)
  const prevKey = useRef(null)

  useEffect(() => {
    if (!raceKey) { setData(null); return }
    if (cache[raceKey]) { setData(cache[raceKey]); return }
    if (prevKey.current === raceKey) return
    prevKey.current = raceKey
    setLoading(true)
    setError(null)
    fetch(`${BASE}data/${raceKey}.json`)
      .then(r => { if (!r.ok) throw new Error(r.statusText); return r.json() })
      .then(d => { cache[raceKey] = d; setData(d); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [raceKey])

  return { data, loading, error }
}

// Splits are loaded lazily the first time any bib is selected for a race
export function useSplits(raceKey, hasSplits) {
  const [splits, setSplits]   = useState(null)
  const [loading, setLoading] = useState(false)
  const loadedFor = useRef(null)

  useEffect(() => {
    setSplits(null)
    loadedFor.current = null
  }, [raceKey])

  useEffect(() => {
    if (!raceKey || !hasSplits || splits !== null || loadedFor.current === raceKey) return
    loadedFor.current = raceKey
    setLoading(true)
    fetch(`${BASE}data/${raceKey}_splits.json`)
      .then(r => r.json())
      .then(d => { setSplits(d); setLoading(false) })
      .catch(() => { setSplits([]); setLoading(false) })
  }, [raceKey, hasSplits, splits])

  return { splits: splits ?? [], loadingSplits: loading }
}
