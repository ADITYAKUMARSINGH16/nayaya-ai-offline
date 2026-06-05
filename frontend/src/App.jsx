import { Routes, Route, Navigate } from 'react-router-dom'

import AppShell from '@/components/layout/AppShell'
import ProtectedRoute from '@/components/ProtectedRoute'
import { CaseProvider } from '@/context/CaseContext'

import LandingPage from '@/pages/LandingPage'
import LoginPage from '@/pages/LoginPage'
import SignupPage from '@/pages/SignupPage'
import AdminLoginPage from '@/pages/AdminLoginPage'
import DashboardPage from '@/pages/DashboardPage'
import AssistantPage from '@/pages/AssistantPage'
import FIRPage from '@/pages/FIRPage'
import PolicePage from '@/pages/PolicePage'
import TrialPage from '@/pages/TrialPage'
import CaseHistoryPage from '@/pages/CaseHistoryPage'
import EvalDashboardPage from '@/pages/EvalDashboardPage'
import AdminDashboardPage from '@/pages/AdminDashboardPage'
import AdminRoute from '@/components/AdminRoute'
import LawyerRoute from '@/components/LawyerRoute'
import JudgeRoute from '@/components/JudgeRoute'
import AILawyerPage from '@/pages/lawyer/AILawyerPage'
import JudgeDashboardPage from '@/pages/judge/JudgeDashboardPage'
import AIJudgePage from '@/pages/judge/AIJudgePage'
import BareActsPage from '@/pages/BareActsPage'
import CaseLawsPage from '@/pages/judge/CaseLawsPage'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/admin-login" element={<AdminLoginPage />} />

      <Route
        path="/app"
        element={
          <ProtectedRoute>
            {/* CaseProvider lives inside the protected shell so unauthenticated
                pages don't waste localStorage cycles, and per-user keys are
                always tied to a known email. */}
            <CaseProvider>
              <AppShell />
            </CaseProvider>
          </ProtectedRoute>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="assistant" element={<AssistantPage />} />
        <Route path="fir" element={<FIRPage />} />
        <Route path="investigation" element={<PolicePage />} />
        <Route path="trial" element={<TrialPage />} />
        <Route path="cases" element={<CaseHistoryPage />} />
        <Route path="bare-acts" element={<BareActsPage />} />
        <Route path="eval" element={<EvalDashboardPage />} />
        
        <Route path="admin" element={
          <AdminRoute>
            <AdminDashboardPage />
          </AdminRoute>
        } />

        {/* Lawyer Routes */}
        <Route path="lawyer/ai" element={
          <LawyerRoute>
            <AILawyerPage />
          </LawyerRoute>
        } />

        {/* Judge Routes */}
        <Route path="judge" element={
          <JudgeRoute>
            <JudgeDashboardPage />
          </JudgeRoute>
        } />
        <Route path="judge/ai" element={
          <JudgeRoute>
            <AIJudgePage />
          </JudgeRoute>
        } />
        <Route path="judge/case-laws" element={
          <JudgeRoute>
            <CaseLawsPage />
          </JudgeRoute>
        } />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
