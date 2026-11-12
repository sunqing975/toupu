import { useEffect, useState } from 'react'
import { getHealth, type Health } from './api'

type State = { health: Health | null; error: string | null }

export default function App() {
  const [state, setState] = useState<State>({ health: null, error: null })

  useEffect(() => {
    getHealth()
      .then((health) => setState({ health, error: null }))
      .catch((err: unknown) => setState({ health: null, error: String(err) }))
  }, [])

  return (
    <main style={{ fontFamily: 'sans-serif', padding: '2rem' }}>
      <h1>投谱 Toupu</h1>
      {state.health ? (
        <p>
          后端状态：<strong style={{ color: 'green' }}>{state.health.status}</strong>（{state.health.app}）
        </p>
      ) : state.error ? (
        <p style={{ color: 'red' }}>后端不可达：{state.error}</p>
      ) : (
        <p>连接中…</p>
      )}
    </main>
  )
}
