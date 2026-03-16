# Task: Add Ministry, Year, and Audit Type Filters to Landing Page

## Context
The landing page (`frontend/index.tsx`) currently has a search bar and sector dropdown for filtering reports. We need to add 3 more filters: Ministry dropdown, Year dropdown, and Audit Type toggle pills. All filtering is client-side (19 reports, no backend changes needed).

## Files to modify
1. `frontend/index.tsx` — new state, filter logic, JSX
2. `frontend/index.css` — styles for the new filter row

**No other files need changes.** The `AuditReport` type already has `ministry: string`, `year: number`, and `reportType?: string`.

---

## Implementation Details

### 1. New state variables in `App()` (near existing `filterSector`)

```ts
const [filterMinistry, setFilterMinistry] = useState('All');
const [filterYear, setFilterYear] = useState('All');
const [filterAuditType, setFilterAuditType] = useState<Set<string>>(new Set());
```

### 2. Memoized dropdown options (derive from full `reports` array, NOT filtered results)

Replace the existing `const sectors = [...]` line and add ministry/year lists. All three should be `useMemo`:

```ts
const sectors = useMemo(() => ['All', ...Array.from(new Set(reports.map(r => r.sector)))], [reports]);
const ministries = useMemo(() => ['All', ...Array.from(new Set(reports.map(r => r.ministry))).sort()], [reports]);
const years = useMemo(() => ['All', ...Array.from(new Set(reports.map(r => r.year))).sort((a, b) => b - a).map(String)], [reports]);
```

### 3. Audit type pill definitions (constant, outside component)

```ts
const AUDIT_TYPES = [
  { value: 'Financial Audit', label: 'Financial Audit' },
  { value: 'Compliance Audit', label: 'Compliance Audit' },
  { value: 'Performance Audit', label: 'Performance Audit' },
];
```

The `value` strings must match what's stored in `report.reportType`. Check `constants.ts` `getReportType()` to confirm these exact strings — they come from `metadata.get("report_type")` in the backend.

### 4. Toggle handler for audit type pills

```ts
const toggleAuditType = (type: string) => {
  setFilterAuditType(prev => {
    const next = new Set(prev);
    if (next.has(type)) next.delete(type);
    else next.add(type);
    return next;
  });
};
```

### 5. Replace the existing `filteredReports` computation with this `useMemo` version

Remove the existing `const filteredReports = reports.filter(...)` and replace with:

```ts
const filteredReports = useMemo(() => {
  return reports.filter(r => {
    // Search: substring match on title or ministry
    if (searchTerm !== '' &&
        !r.title.toLowerCase().includes(searchTerm.toLowerCase()) &&
        !r.ministry.toLowerCase().includes(searchTerm.toLowerCase())) {
      return false;
    }
    // Sector: exact match
    if (filterSector !== 'All' && r.sector !== filterSector) return false;
    // Ministry: exact match
    if (filterMinistry !== 'All' && r.ministry !== filterMinistry) return false;
    // Year: numeric comparison
    if (filterYear !== 'All' && r.year !== parseInt(filterYear)) return false;
    // Audit type: OR within selected types, reports with no type are excluded when pills active
    if (filterAuditType.size > 0 && (!r.reportType || !filterAuditType.has(r.reportType))) return false;
    return true;
  });
}, [reports, searchTerm, filterSector, filterMinistry, filterYear, filterAuditType]);
```

### 6. Computed: has active filters (for showing clear button and empty state)

```ts
const hasActiveFilters = searchTerm !== '' || filterSector !== 'All' ||
  filterMinistry !== 'All' || filterYear !== 'All' || filterAuditType.size > 0;

const clearAllFilters = () => {
  setSearchTerm('');
  setFilterSector('All');
  setFilterMinistry('All');
  setFilterYear('All');
  setFilterAuditType(new Set());
};
```

### 7. JSX changes in the landing view

Insert a new `<div className="filter-bar-secondary">` AFTER the existing `.filter-controls` div and BEFORE the `reportsLoading` check. Structure:

```tsx
<div className="filter-bar-secondary">
  <div className="secondary-dropdowns">
    <div className="dropdown-group">
      <label>Ministry:</label>
      <select value={filterMinistry} onChange={(e) => setFilterMinistry(e.target.value)}>
        {ministries.map(m => <option key={m} value={m}>{m}</option>)}
      </select>
    </div>
    <div className="dropdown-group">
      <label>Year:</label>
      <select value={filterYear} onChange={(e) => setFilterYear(e.target.value)}>
        {years.map(y => <option key={y} value={y}>{y}</option>)}
      </select>
    </div>
  </div>
  <div className="filter-divider" />
  <div className="audit-type-pills">
    {AUDIT_TYPES.map(type => (
      <button
        key={type.value}
        className={`audit-type-pill ${filterAuditType.has(type.value) ? 'active' : ''}`}
        onClick={() => toggleAuditType(type.value)}
      >
        {type.label}
      </button>
    ))}
  </div>
  {hasActiveFilters && (
    <button className="clear-filters-btn" onClick={clearAllFilters}>
      Clear all filters
    </button>
  )}
</div>
```

Also add an empty state after the report grid when `filteredReports.length === 0 && !reportsLoading`:

```tsx
{!reportsLoading && filteredReports.length === 0 && (
  <div className="no-results">
    <p>No reports match your current filters.</p>
    {hasActiveFilters && (
      <button className="clear-filters-link" onClick={clearAllFilters}>Clear all filters</button>
    )}
  </div>
)}
```

### 8. CSS additions in `frontend/index.css`

Add these styles. Match the existing design language (the app uses slate colors, subtle borders, clean spacing):

```css
/* Secondary filter bar */
.filter-bar-secondary {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 24px;
  margin: 0 auto;
  max-width: 1400px;
  flex-wrap: wrap;
}

.secondary-dropdowns {
  display: flex;
  align-items: center;
  gap: 12px;
}

.filter-divider {
  width: 1px;
  height: 28px;
  background: #e2e8f0;
  flex-shrink: 0;
}

/* Audit type pills */
.audit-type-pills {
  display: flex;
  gap: 8px;
}

.audit-type-pill {
  padding: 6px 16px;
  border-radius: 9999px;
  border: 1.5px solid #cbd5e1;
  background: white;
  color: #475569;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
}

.audit-type-pill:hover {
  border-color: #94a3b8;
  background: #f8fafc;
}

.audit-type-pill.active {
  background: #1a365d;
  color: white;
  border-color: #1a365d;
}

.audit-type-pill.active:hover {
  background: #1e3a5f;
  border-color: #1e3a5f;
}

/* Clear filters */
.clear-filters-btn {
  margin-left: auto;
  padding: 6px 12px;
  background: none;
  border: none;
  color: #64748b;
  font-size: 13px;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
  white-space: nowrap;
}

.clear-filters-btn:hover {
  color: #1a365d;
}

/* No results empty state */
.no-results {
  text-align: center;
  padding: 60px 20px;
  color: #64748b;
}

.no-results p {
  font-size: 16px;
  margin-bottom: 12px;
}

.clear-filters-link {
  background: none;
  border: none;
  color: #1a365d;
  font-size: 14px;
  cursor: pointer;
  text-decoration: underline;
  font-weight: 500;
}

/* Responsive: stack on narrow screens */
@media (max-width: 768px) {
  .filter-bar-secondary {
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
    padding: 10px 16px;
  }

  .secondary-dropdowns {
    flex-direction: column;
    gap: 8px;
  }

  .filter-divider {
    display: none;
  }

  .audit-type-pills {
    flex-wrap: wrap;
  }

  .clear-filters-btn {
    margin-left: 0;
    text-align: center;
  }
}
```

## Important constraints
- Do NOT modify any backend files
- Do NOT modify `types.ts`, `ReportCard.tsx`, `useReports.ts`, or `useReport.ts`
- Do NOT change the existing `.filter-controls` row (search + sector + view toggle) — keep it exactly as is
- The dropdown option lists (sectors, ministries, years) must derive from the FULL `reports` array, not from `filteredReports`
- The `filterAuditType` Set uses OR within the group (any selected type matches), AND with all other filters
- When `filterAuditType` is empty (no pills active), all audit types pass through
- Reports with `reportType` undefined/null are hidden when any audit type pill is active — this is intentional
- Wrap `filteredReports`, `sectors`, `ministries`, and `years` in `useMemo`
- The `hasActiveFilters` check and `clearAllFilters` handler must cover ALL 5 filters
- The secondary filter bar label styles for Ministry and Year dropdowns should match the existing Sector dropdown styling exactly (reuse the `.dropdown-group` class)
