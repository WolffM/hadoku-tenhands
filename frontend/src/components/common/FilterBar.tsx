/**
 * FilterBar Component
 *
 * Renders a row of labeled <select> dropdowns for filtering data.
 */

export interface FilterDefinition {
  label: string
  value: string
  onChange: (value: string) => void
  options: { value: string; label: string }[]
}

interface FilterBarProps {
  filters: FilterDefinition[]
}

export function FilterBar({ filters }: FilterBarProps) {
  return (
    <div className="filter-bar">
      {filters.map(filter => (
        <div className="filter-group" key={filter.label}>
          <label className="filter-label">{filter.label}</label>
          <select
            className="filter-select"
            value={filter.value}
            onChange={e => filter.onChange(e.target.value)}
          >
            {filter.options.map(opt => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      ))}
    </div>
  )
}
