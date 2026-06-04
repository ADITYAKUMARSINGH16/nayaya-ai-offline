import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import Spinner from '@/components/ui/Spinner'

export default function AdminRoute({ children }) {
  const { user, loading } = useAuth()
  const loc = useLocation()

  if (loading) {
    return (
      <div className="min-h-screen grid place-items-center">
        <Spinner label="Loading admin view…" />
      </div>
    )
  }
  
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />
  
  if (user.role !== 'admin') {
    return <Navigate to="/app" replace />
  }

  return children
}
