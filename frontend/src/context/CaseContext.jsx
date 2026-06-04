/**
 * CaseContext — single source of truth for the "current case" the user is
 * working on. Carries facts/FIR/investigation/judgments across pages so the
 * user doesn't have to re-paste the same scenario into every form.
 *
 * Persisted to localStorage so it survives page refresh / new tab.
 *
 * Per-user keying: the user's email is part of the storage key, so two users
 * on the same device don't see each other's draft case. Cleared on sign-out.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useAuth } from '@/context/AuthContext'

const CASE_KEY_PREFIX = 'nyaya-case:'

const EMPTY_CASE = {
  caseFacts:           '',     // shared free-text scenario (Police / Trial use this)
  firForm:             null,   // { complainantName, address, phone, ... } — last FIR form
  firText:             '',     // last drafted FIR body
  firRecordId:         null,
  investigationReport: null,   // last investigation JSON
  caseId:              null,   // backend case ID (created by first trial)
  lastCourtLevel:      null,   // 'district' | 'high' | 'supreme'
  updatedAt:           null,
}

const CaseContext = createContext({
  currentCase:   EMPTY_CASE,
  updateCase:    () => {},
  clearCase:     () => {},
})


function storageKey(email) {
  return CASE_KEY_PREFIX + (email || 'anonymous')
}


function readFromStorage(email) {
  try {
    const raw = localStorage.getItem(storageKey(email))
    if (!raw) return EMPTY_CASE
    return { ...EMPTY_CASE, ...JSON.parse(raw) }
  } catch {
    return EMPTY_CASE
  }
}


function writeToStorage(email, c) {
  try {
    localStorage.setItem(storageKey(email), JSON.stringify(c))
  } catch {/* localStorage may be unavailable in incognito */}
}


export function CaseProvider({ children }) {
  const { user } = useAuth()
  const email = user?.email || null

  const [currentCase, setCurrentCase] = useState(() => readFromStorage(email))

  // On sign-in / sign-out, swap to the right user's stored case (or clear).
  useEffect(() => {
    setCurrentCase(readFromStorage(email))
  }, [email])

  const updateCase = useCallback((patch) => {
    setCurrentCase((prev) => {
      const next = { ...prev, ...patch, updatedAt: new Date().toISOString() }
      writeToStorage(email, next)
      return next
    })
  }, [email])

  const clearCase = useCallback(() => {
    setCurrentCase(EMPTY_CASE)
    try { localStorage.removeItem(storageKey(email)) } catch {/* noop */}
  }, [email])

  const value = useMemo(
    () => ({ currentCase, updateCase, clearCase }),
    [currentCase, updateCase, clearCase],
  )

  return <CaseContext.Provider value={value}>{children}</CaseContext.Provider>
}


export function useCase() {
  return useContext(CaseContext)
}
