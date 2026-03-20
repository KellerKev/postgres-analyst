export function SemanticCanvas({ semantic, onRefresh }) {
  if (!semantic || semantic.length === 0) {
    return (
      <div class="panel">
        <div class="panel-header">
          <span>Semantic Model</span>
          <button onClick={onRefresh}>Refresh</button>
        </div>
        <div class="panel-body">
          <div class="empty-state">
            No semantic model saved yet.<br />
            Use the Schema Explorer to add descriptions and save.
          </div>
        </div>
      </div>
    )
  }

  return (
    <div class="panel">
      <div class="panel-header">
        <span>Semantic Model</span>
        <button onClick={onRefresh}>Refresh</button>
      </div>
      <div class="panel-body">
        {semantic.map(tbl => (
          <div class="semantic-card" key={tbl.table_name}>
            <div class="semantic-card-header">{tbl.table_name}</div>
            {tbl.description && (
              <div class="semantic-card-desc">{tbl.description}</div>
            )}
            <div style={{ padding: '4px 0 8px' }}>
              {tbl.columns?.map(col => {
                if (col.is_pii) {
                  return (
                    <div class="semantic-col redacted" key={col.column_name}>
                      <span>&#x1f512;</span>
                      <span>{col.column_name}</span>
                      <span style={{ fontFamily: 'var(--font-mono)', letterSpacing: '2px' }}>
                        {'████████'}
                      </span>
                    </div>
                  )
                }
                if (!col.is_visible) {
                  return (
                    <div class="semantic-col hidden" key={col.column_name}>
                      <span>{col.column_name}</span>
                      {col.description && <span class="col-desc">— {col.description}</span>}
                    </div>
                  )
                }
                return (
                  <div class="semantic-col" key={col.column_name}>
                    <span>{col.column_name}</span>
                    <span class="col-desc">
                      {col.data_type || ''}
                      {col.description ? ` — ${col.description}` : ''}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
