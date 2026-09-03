import { useState } from 'react'
import { Layout, type PageKey } from './components/Layout'
import { Dashboard } from './pages/Dashboard'
import { Assets } from './pages/Assets'
import { Holdings } from './pages/Holdings'
import { Transactions } from './pages/Transactions'
import { Review } from './pages/Review'
import { Settings } from './pages/Settings'

const PAGES: Record<PageKey, () => React.JSX.Element> = {
  dashboard: Dashboard,
  assets: Assets,
  holdings: Holdings,
  transactions: Transactions,
  review: Review,
  settings: Settings,
}

export default function App() {
  const [page, setPage] = useState<PageKey>('dashboard')
  const Page = PAGES[page]

  return (
    <Layout page={page} onNavigate={setPage}>
      <Page />
    </Layout>
  )
}
