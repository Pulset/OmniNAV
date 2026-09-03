import { useEffect, useState } from 'react'
import { api, setOnUnauthorized } from './api/client'
import type { User } from './api/types'
import { Layout, type PageKey } from './components/Layout'
import { Dashboard } from './pages/Dashboard'
import { Assets } from './pages/Assets'
import { Holdings } from './pages/Holdings'
import { Login } from './pages/Login'
import { Transactions } from './pages/Transactions'
import { Review } from './pages/Review'
import { Settings } from './pages/Settings'
import { Users } from './pages/Users'

const PAGES: Record<PageKey, () => React.JSX.Element> = {
  dashboard: Dashboard,
  assets: Assets,
  holdings: Holdings,
  transactions: Transactions,
  review: Review,
  settings: Settings,
  users: Users,
}

export default function App() {
  const [page, setPage] = useState<PageKey>('dashboard')
  const [user, setUser] = useState<User | null>(null)
  const [booting, setBooting] = useState(true)

  useEffect(() => {
    setOnUnauthorized(() => setUser(null))
    api
      .get<User>('/auth/me')
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setBooting(false))
  }, [])

  if (booting) return null
  if (!user) return <Login onLogin={(u) => { setUser(u); setPage('dashboard') }} />

  const Page = PAGES[page]

  return (
    <Layout
      page={page}
      onNavigate={setPage}
      user={user}
      onLogout={() => { setUser(null); setPage('dashboard') }}
    >
      <Page />
    </Layout>
  )
}
