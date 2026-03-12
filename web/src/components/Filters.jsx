import { useMemo } from 'react'
import { AGE_GROUP_LABELS } from '../utils/stats.js'

export default function Filters({ runners, meta, filters, onChange }) {
  const genders = useMemo(() => {
    if (!runners?.length) return []
    return ['All', ...new Set(runners.map(r => r.sex).filter(Boolean))].sort()
  }, [runners])

  const ageGroups = ['All', ...AGE_GROUP_LABELS]

  const setFilter = (key, val) => onChange({ ...filters, [key]: val })

  return (
    <>
      <div className="field">
        <label>Gender</label>
        <select value={filters.gender} onChange={e => setFilter('gender', e.target.value)}>
          {genders.map(g => <option key={g} value={g}>{g}</option>)}
        </select>
      </div>

      <div className="field">
        <label>Age group</label>
        <select value={filters.ageGroup} onChange={e => setFilter('ageGroup', e.target.value)}>
          {ageGroups.map(g => <option key={g} value={g}>{g}</option>)}
        </select>
      </div>

      {meta?.has_category && (
        <div className="field">
          <label>Category</label>
          <select value={filters.category} onChange={e => setFilter('category', e.target.value)}>
            {['All', 'Runners', 'Adaptive'].map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
      )}
    </>
  )
}
