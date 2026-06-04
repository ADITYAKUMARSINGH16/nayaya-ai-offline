import { useEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import Topbar from './Topbar'
import MobileDrawer from '@/components/MobileDrawer'

const STORE_KEY = 'nyaya-sidebar-collapsed'

export default function AppShell() {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(
    () => (typeof window !== 'undefined' && localStorage.getItem(STORE_KEY) === '1'),
  )

  useEffect(() => {
    localStorage.setItem(STORE_KEY, collapsed ? '1' : '0')
  }, [collapsed])

  return (
    <div className="min-h-screen flex">
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((v) => !v)} />
      <MobileDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
      <div className="flex-1 flex flex-col min-w-0">
        <Topbar onMenu={() => setDrawerOpen(true)} />
        <main className="flex-1 p-4 sm:p-6 lg:p-8 w-full mx-auto max-w-[1600px]">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
