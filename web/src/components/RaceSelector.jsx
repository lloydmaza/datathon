export default function RaceSelector({ manifest, selected, onChange }) {
  if (!manifest.length) return <div className="field"><label>Race</label><select disabled><option>Loading…</option></select></div>
  return (
    <div className="field">
      <label>Race</label>
      <select value={selected ?? ''} onChange={e => onChange(e.target.value)}>
        {!selected && <option value="" disabled>Select a race…</option>}
        {manifest.map(r => (
          <option key={r.race_key} value={r.race_key}>
            {r.display_name}  ({r.runner_count?.toLocaleString()} finishers)
          </option>
        ))}
      </select>
    </div>
  )
}
