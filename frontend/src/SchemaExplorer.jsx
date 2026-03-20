import { useState } from 'preact/hooks'

export function SchemaExplorer({ modelId, introspected, setIntrospected, semantic, setSemantic, dirty, setDirty, onSaved }) {
  const [expanded, setExpanded] = useState({})
  const [saving, setSaving] = useState(false)
  const [describing, setDescribing] = useState(false)

  const doIntrospect = async () => {
    try {
      const res = await fetch('/api/introspect')
      const data = await res.json()
      setIntrospected(data.tables || [])
    } catch (e) {
      console.error('Introspect failed', e)
    }
  }

  const doAutoDescribe = async () => {
    setDescribing(true)
    try {
      const res = await fetch('/api/introspect/describe', { method: 'POST' })
      const data = await res.json()
      if (data.error) {
        console.error('Auto-describe error:', data.error)
        return
      }
      if (data.tables) {
        setSemantic(data.tables)
        setDirty(true)
        // Expand all tables so user can review
        const exp = {}
        for (const tbl of data.tables) {
          exp[tbl.table_name] = true
        }
        setExpanded(exp)
      }
    } catch (e) {
      console.error('Auto-describe failed', e)
    } finally {
      setDescribing(false)
    }
  }

  const toggleExpand = (table) => {
    setExpanded(prev => ({ ...prev, [table]: !prev[table] }))
  }

  // Merge introspected + semantic data
  const getMerged = () => {
    return introspected.map(tbl => {
      const sem = semantic.find(s => s.table_name === tbl.table_name)
      return {
        table_name: tbl.table_name,
        description: sem?.description || '',
        columns: tbl.columns.map(col => {
          const sc = sem?.columns?.find(c => c.column_name === col.column_name)
          return {
            column_name: col.column_name,
            data_type: col.data_type,
            description: sc?.description || '',
            is_pii: sc?.is_pii || false,
            is_visible: sc?.is_visible ?? true,
          }
        })
      }
    })
  }

  const merged = getMerged()

  const updateTableDesc = (tableName, desc) => {
    const updated = merged.map(t =>
      t.table_name === tableName ? { ...t, description: desc } : t
    )
    setSemantic(updated)
    setDirty(true)
  }

  const updateColumn = (tableName, colName, field, value) => {
    const updated = merged.map(t => {
      if (t.table_name !== tableName) return t
      return {
        ...t,
        columns: t.columns.map(c =>
          c.column_name === colName ? { ...c, [field]: value } : c
        )
      }
    })
    setSemantic(updated)
    setDirty(true)
  }

  const save = async () => {
    setSaving(true)
    try {
      const payload = { model_id: modelId, tables: merged }
      await fetch('/api/semantic/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      setDirty(false)
      onSaved()
    } catch (e) {
      console.error('Save failed', e)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div class="panel">
      <div class="panel-header">
        <span>Schema Explorer</span>
        <div style={{ display: 'flex', gap: '6px' }}>
          <button onClick={doIntrospect}>Introspect</button>
          {introspected.length > 0 && (
            <button onClick={doAutoDescribe} disabled={describing}>
              {describing ? 'Describing...' : 'Auto-describe'}
            </button>
          )}
        </div>
      </div>
      {describing && (
        <div class="auto-describe-banner">
          Asking LLM to describe your schema — this may take a moment...
        </div>
      )}
      <div class="panel-body">
        {merged.map(tbl => (
          <div class="table-group" key={tbl.table_name}>
            <div class="table-header" onClick={() => toggleExpand(tbl.table_name)}>
              <span class="arrow">{expanded[tbl.table_name] ? '▼' : '▶'}</span>
              {tbl.table_name}
              {tbl.description && <span class="table-hint">— {tbl.description}</span>}
            </div>
            {expanded[tbl.table_name] && (
              <div>
                <input
                  class="desc-input table-desc-input"
                  placeholder="Table description..."
                  value={tbl.description}
                  onInput={(e) => updateTableDesc(tbl.table_name, e.target.value)}
                />
                {tbl.columns.map(col => (
                  <div key={col.column_name}>
                    <div class="column-row">
                      <span class="col-name">{col.column_name}</span>
                      <span class="col-type">{col.data_type}</span>
                      <span
                        class="toggle"
                        title={col.is_pii ? 'PII (hidden from LLM)' : 'Mark as PII'}
                        onClick={() => updateColumn(tbl.table_name, col.column_name, 'is_pii', !col.is_pii)}
                      >
                        {col.is_pii ? '🔴' : '⚪'}
                      </span>
                      <span
                        class="toggle"
                        title={col.is_visible ? 'Visible to LLM' : 'Hidden from LLM'}
                        onClick={() => updateColumn(tbl.table_name, col.column_name, 'is_visible', !col.is_visible)}
                      >
                        {col.is_visible ? '👁' : '🚫'}
                      </span>
                    </div>
                    <input
                      class="desc-input"
                      placeholder="Column description..."
                      value={col.description}
                      onInput={(e) => updateColumn(tbl.table_name, col.column_name, 'description', e.target.value)}
                    />
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
        {introspected.length === 0 && (
          <div class="empty-state">
            Click "Introspect" to discover tables in your database.
          </div>
        )}
      </div>
      {introspected.length > 0 && (
        <div style={{ padding: '12px', borderTop: '1px solid var(--border)' }}>
          <button class="primary" onClick={save} disabled={!dirty || saving} style={{ width: '100%' }}>
            {saving ? 'Saving...' : 'Save Semantic Model'}
          </button>
        </div>
      )}
    </div>
  )
}
