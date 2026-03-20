import { useState } from 'preact/hooks'

const SQL_KEYWORDS = /\b(SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|ON|AND|OR|NOT|IN|AS|GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT|OFFSET|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|SET|VALUES|INTO|DISTINCT|COUNT|SUM|AVG|MIN|MAX|CASE|WHEN|THEN|ELSE|END|IS|NULL|BETWEEN|LIKE|EXISTS|UNION|ALL|DESC|ASC|WITH|CAST|COALESCE)\b/gi

function highlightSQL(sql) {
  if (!sql) return ''
  const escaped = sql.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  return escaped.replace(SQL_KEYWORDS, '<span style="color:var(--accent)">$1</span>')
}

export function ChatPanel({ modelId, history, onQueryDone }) {
  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const [showHistory, setShowHistory] = useState(false)

  const runQuery = async (body, msgIndex) => {
    const res = await fetch('/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    return await res.json()
  }

  const submit = async (overrideSql, msgIndex) => {
    const isRerun = overrideSql !== undefined
    const q = isRerun ? messages[msgIndex].question : question.trim()
    if (!q && !isRerun) return

    if (!isRerun) {
      setMessages(prev => [...prev, { question: q, loading: true }])
      setQuestion('')
    } else {
      setMessages(prev => prev.map((m, i) =>
        i === msgIndex ? { ...m, loading: true, error: null, result: null } : m
      ))
    }
    setLoading(true)

    try {
      const body = { question: q, model_id: modelId }
      if (isRerun) {
        body.sql = overrideSql
        body.was_edited = true
      }
      const data = await runQuery(body)

      setMessages(prev => prev.map((m, i) => {
        const target = isRerun ? msgIndex : prev.length - 1
        if (i !== target) return m
        if (data.pii_blocked) {
          return { ...m, loading: false, piiBlocked: data, sql: data.sql }
        }
        if (data.error) {
          return { ...m, loading: false, error: data.error, detail: data.detail, sql: data.sql || data.raw || '', editSql: data.sql || '' }
        }
        return { ...m, loading: false, sql: data.sql, editSql: data.sql, result: data, error: null }
      }))
      if (!data.pii_blocked) onQueryDone()
    } catch (e) {
      setMessages(prev => prev.map((m, i) => {
        const target = isRerun ? msgIndex : prev.length - 1
        return i === target ? { ...m, loading: false, error: e.message } : m
      }))
    } finally {
      setLoading(false)
    }
  }

  const acceptWithoutPii = async (msgIndex) => {
    setMessages(prev => prev.map((m, i) =>
      i === msgIndex ? { ...m, loading: true, piiBlocked: null } : m
    ))
    setLoading(true)

    try {
      const msg = messages[msgIndex]
      const data = await runQuery({
        question: msg.question,
        model_id: modelId,
        sql: msg.sql,
        accept_without_pii: true,
      })

      setMessages(prev => prev.map((m, i) => {
        if (i !== msgIndex) return m
        if (data.error) {
          return { ...m, loading: false, error: data.error, detail: data.detail }
        }
        return { ...m, loading: false, sql: data.sql, editSql: data.sql, result: data, error: null }
      }))
      onQueryDone()
    } catch (e) {
      setMessages(prev => prev.map((m, i) =>
        i === msgIndex ? { ...m, loading: false, error: e.message } : m
      ))
    } finally {
      setLoading(false)
    }
  }

  const declinePiiQuery = (msgIndex) => {
    setMessages(prev => prev.map((m, i) =>
      i === msgIndex ? { ...m, piiBlocked: null, sql: null, dismissed: true } : m
    ))
  }

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const copySQL = (sql) => {
    navigator.clipboard.writeText(sql).catch(() => {})
  }

  return (
    <div class="panel">
      <div class="panel-header">
        <span>Chat</span>
      </div>
      <div class="chat-input-area">
        <textarea
          placeholder="Ask a question about your data..."
          value={question}
          onInput={(e) => setQuestion(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={loading}
        />
      </div>
      <div class="chat-messages">
        {messages.map((msg, i) => (
          <div class="chat-message" key={i}>
            <div class="chat-question">{msg.question}</div>
            {msg.loading && <div class="loading">Thinking...</div>}
            {msg.error && (
              <div class="error-box">
                <strong>{msg.error}</strong>
                {msg.detail && <div style={{ marginTop: '4px' }}>{msg.detail}</div>}
              </div>
            )}
            {msg.piiBlocked && (
              <div class="pii-blocked-box">
                <div class="pii-blocked-title">PII Protection</div>
                <div>
                  This query returns PII columns that cannot be displayed:{' '}
                  <strong>{msg.piiBlocked.blocked_columns.join(', ')}</strong>
                </div>
                <div style={{ marginTop: '8px' }}>
                  I can run this query with only non-PII columns:
                </div>
                <ul class="pii-available-list">
                  {Object.entries(msg.piiBlocked.safe_columns).map(([table, cols]) => (
                    <li key={table}><strong>{table}</strong>: {cols.join(', ')}</li>
                  ))}
                </ul>
                <div class="pii-blocked-actions">
                  <button class="primary" onClick={() => acceptWithoutPii(i)}>
                    Run with suggested columns
                  </button>
                  <button onClick={() => declinePiiQuery(i)}>Something else</button>
                </div>
              </div>
            )}
            {msg.dismissed && (
              <div class="chat-system-msg">OK, what else can I help with?</div>
            )}
            {msg.sql && !msg.piiBlocked && (
              <>
                <div class="sql-block">
                  <textarea
                    value={msg.editSql}
                    onInput={(e) => {
                      const val = e.target.value
                      setMessages(prev => prev.map((m, j) =>
                        j === i ? { ...m, editSql: val } : m
                      ))
                    }}
                  />
                </div>
                <div class="sql-actions">
                  <button onClick={() => copySQL(msg.editSql)}>Copy</button>
                  {msg.editSql !== msg.sql && (
                    <button onClick={() => submit(msg.editSql, i)}>Re-run (edited)</button>
                  )}
                </div>
              </>
            )}
            {msg.result && (
              <>
                <div class="row-count">{msg.result.row_count} row{msg.result.row_count !== 1 ? 's' : ''}</div>
                <table class="result-table">
                  <thead>
                    <tr>{msg.result.columns.map(c => <th key={c}>{c}</th>)}</tr>
                  </thead>
                  <tbody>
                    {msg.result.rows.slice(0, 50).map((row, ri) => (
                      <tr key={ri}>
                        {row.map((val, ci) => (
                          <td key={ci}>{val === null ? 'NULL' : String(val)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {msg.result.row_count > 50 && (
                  <div class="row-count">Showing 50 of {msg.result.row_count}</div>
                )}
              </>
            )}
          </div>
        ))}
      </div>
      <div class="history-toggle" onClick={() => setShowHistory(!showHistory)}>
        {showHistory ? '▼' : '▶'} Query History ({history.length})
      </div>
      {showHistory && (
        <div style={{ maxHeight: '200px', overflowY: 'auto', padding: '0 12px 12px' }}>
          {history.map(item => (
            <div class="history-item" key={item.id}>
              <div class="hist-q">{item.question}</div>
              <div class="hist-meta">
                {item.result_rows} rows{item.was_edited ? ' (edited)' : ''} — {new Date(item.created_at).toLocaleString()}
              </div>
            </div>
          ))}
          {history.length === 0 && (
            <div class="empty-state">No queries yet.</div>
          )}
        </div>
      )}
    </div>
  )
}
