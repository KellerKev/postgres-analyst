import { useState, useEffect } from 'preact/hooks'
import { SchemaExplorer } from './SchemaExplorer.jsx'
import { SemanticCanvas } from './SemanticCanvas.jsx'
import { ChatPanel } from './ChatPanel.jsx'

export function App() {
  const [models, setModels] = useState([])
  const [selectedModelId, setSelectedModelId] = useState(null)
  const [introspected, setIntrospected] = useState([])
  const [semantic, setSemantic] = useState([])
  const [dirty, setDirty] = useState(false)
  const [history, setHistory] = useState([])

  const loadModels = async () => {
    try {
      const res = await fetch('/api/models')
      const data = await res.json()
      setModels(data.models || [])
      if (data.models?.length && !selectedModelId) {
        setSelectedModelId(data.models[0].id)
      }
    } catch (e) {
      console.error('Failed to load models', e)
    }
  }

  const loadSemantic = async (modelId) => {
    const id = modelId ?? selectedModelId
    if (!id) return
    try {
      const res = await fetch(`/api/semantic?model_id=${id}`)
      const data = await res.json()
      setSemantic(data.tables || [])
    } catch (e) {
      console.error('Failed to load semantic model', e)
    }
  }

  const loadHistory = async () => {
    try {
      const res = await fetch('/api/history')
      const data = await res.json()
      setHistory(data.history || [])
    } catch (e) {
      console.error('Failed to load history', e)
    }
  }

  useEffect(() => {
    loadModels()
    loadHistory()
  }, [])

  useEffect(() => {
    if (selectedModelId) {
      loadSemantic(selectedModelId)
      setDirty(false)
    }
  }, [selectedModelId])

  const createModel = async () => {
    const name = window.prompt('Model name:')
    if (!name) return
    try {
      const res = await fetch('/api/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      const data = await res.json()
      await loadModels()
      setSelectedModelId(data.id)
    } catch (e) {
      console.error('Failed to create model', e)
    }
  }

  const deleteModel = async () => {
    if (!selectedModelId) return
    const current = models.find(m => m.id === selectedModelId)
    if (!window.confirm(`Delete model "${current?.name}"?`)) return
    try {
      await fetch(`/api/models/${selectedModelId}`, { method: 'DELETE' })
      setSelectedModelId(null)
      setSemantic([])
      await loadModels()
    } catch (e) {
      console.error('Failed to delete model', e)
    }
  }

  const currentModel = models.find(m => m.id === selectedModelId)

  return (
    <div class="app-root">
      <div class="model-bar">
        <label class="model-bar-label">Model</label>
        <select
          value={selectedModelId || ''}
          onChange={(e) => setSelectedModelId(Number(e.target.value))}
        >
          {models.map(m => (
            <option key={m.id} value={m.id}>{m.name}</option>
          ))}
        </select>
        <button onClick={createModel}>+ New</button>
        {models.length > 1 && (
          <button onClick={deleteModel}>Delete</button>
        )}
        {currentModel?.description && (
          <span class="model-desc">{currentModel.description}</span>
        )}
      </div>
      <div class="app-layout">
        <SchemaExplorer
          modelId={selectedModelId}
          introspected={introspected}
          setIntrospected={setIntrospected}
          semantic={semantic}
          setSemantic={setSemantic}
          dirty={dirty}
          setDirty={setDirty}
          onSaved={() => loadSemantic()}
        />
        <SemanticCanvas
          semantic={semantic}
          onRefresh={() => loadSemantic()}
        />
        <ChatPanel
          modelId={selectedModelId}
          history={history}
          onQueryDone={loadHistory}
        />
      </div>
    </div>
  )
}
