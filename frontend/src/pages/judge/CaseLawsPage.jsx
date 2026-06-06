import { useState, useEffect, useRef } from 'react'
import { Landmark, Search } from 'lucide-react'
import { api } from '@/api/client'
import Spinner from '@/components/ui/Spinner'

export default function CaseLawsPage() {
  const [loading, setLoading] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [searching, setSearching] = useState(false)
  
  const contentRef = useRef(null)

  useEffect(() => {
    if (!searchQuery) {
      // Fetch default TOC when query is empty
      setSearching(true)
      api.judgeSearchCaseLaws('')
        .then(res => setSearchResults(res))
        .catch(console.error)
        .finally(() => setSearching(false))
      return
    }
    
    const delayDebounce = setTimeout(() => {
      setSearching(true)
      api.judgeSearchCaseLaws(searchQuery)
        .then(res => setSearchResults(res))
        .catch(console.error)
        .finally(() => setSearching(false))
    }, 400)

    return () => clearTimeout(delayDebounce)
  }, [searchQuery])

  const handleSectionClick = (idx) => {
    const el = document.getElementById(`case-${idx}`)
    if (el && contentRef.current) {
      contentRef.current.scrollTo({
        top: el.offsetTop - 20,
        behavior: 'smooth'
      })
    }
  }

  return (
    <div className="flex flex-col h-[calc(100vh-6rem)] -m-4 sm:-m-6 lg:-m-8">
      {/* Header */}
      <div className="flex-none p-4 border-b border-white/5 bg-ink-950/80 backdrop-blur flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 overflow-x-auto no-scrollbar">
          <Landmark className="w-5 h-5 text-gold-400 shrink-0" />
          <h1 className="text-lg font-serif font-medium whitespace-nowrap">Supreme Court Case Laws</h1>
        </div>
        <div className="w-64 shrink-0 relative hidden sm:block">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input
            type="text"
            placeholder="Search cases (e.g. murder, theft)..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="w-full bg-white/5 border border-white/10 rounded-xl py-2 pl-9 pr-3 text-sm focus:outline-none focus:border-gold-500/50"
          />
        </div>
      </div>

      <div className="flex flex-1 min-h-0">
        {/* Sidebar TOC */}
        <div className="hidden md:flex w-72 flex-col border-r border-white/5 bg-ink-900/30">
          <div className="p-4 border-b border-white/5 text-sm font-medium text-ink-300">
            Table of Contents
          </div>
          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {searching ? (
              <div className="flex justify-center p-8"><Spinner className="w-5 h-5 text-gold-500" /></div>
            ) : searchResults.length > 0 ? (
              searchResults.map((c, idx) => (
                <button
                  key={idx}
                  onClick={() => handleSectionClick(idx)}
                  className="w-full text-left px-3 py-2 rounded-lg hover:bg-white/5 text-sm flex flex-col gap-1 group transition"
                >
                  <span className="text-gold-500/70 font-medium shrink-0 text-xs">
                    {c.year}
                  </span>
                  <span className="text-ink-200 line-clamp-2 group-hover:text-ink-50 transition">
                    {c.title}
                  </span>
                </button>
              ))
            ) : (
              <div className="p-4 text-sm text-ink-400 text-center">
                {searchQuery ? 'No cases found.' : 'Search to explore cases.'}
              </div>
            )}
          </div>
        </div>

        {/* Main Content Area */}
        <div 
          ref={contentRef}
          className="flex-1 overflow-y-auto bg-ink-950 p-6 md:p-10 scroll-smooth relative"
        >
          {/* Mobile search bar */}
          <div className="mb-6 sm:hidden relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
            <input
              type="text"
              placeholder="Search cases..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-xl py-2 pl-9 pr-3 text-sm focus:outline-none focus:border-gold-500/50"
            />
          </div>

          <div className="max-w-4xl mx-auto space-y-12">
            {searching ? (
              <div className="flex justify-center items-center h-64">
                <Spinner className="w-8 h-8 text-gold-500" />
              </div>
            ) : searchResults.length > 0 ? (
              searchResults.map((c, idx) => (
                <div key={idx} id={`case-${idx}`} className="group">
                  <div className="mb-4">
                    <div className="text-sm font-medium text-gold-500/80 mb-1">
                      {c.court} · {c.year}
                    </div>
                    <h2 className="text-xl font-serif text-ink-50 mb-3 leading-snug">
                      {c.title}
                    </h2>
                    {c.disposition && (
                      <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-md bg-white/5 border border-white/10 text-xs font-medium text-ink-200 mb-4">
                        <span className="text-gold-500">Verdict:</span> {c.disposition}
                      </div>
                    )}
                  </div>
                  
                  {c.source_pdf_s3_url && (
                    <div className="mb-4">
                      <a 
                        href={`${import.meta.env.VITE_API_URL || ''}/api/cases/pdf/proxy?url=${encodeURIComponent(c.source_pdf_s3_url)}`} 
                        target="_blank" 
                        rel="noreferrer" 
                        className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-gold-500/10 text-gold-500 hover:bg-gold-500/20 transition-colors text-sm font-medium border border-gold-500/20"
                      >
                        View Source PDF
                      </a>
                    </div>
                  )}

                  <div className="prose prose-invert prose-p:leading-relaxed max-w-none text-ink-200 whitespace-pre-wrap max-h-[500px] overflow-y-auto pr-4 border border-white/5 rounded-xl bg-white/5 p-6">
                    {c.text || c.snippet || 'No case text available.'}
                  </div>
                  
                  <div className="w-16 h-px bg-white/10 mt-12 mb-2 mx-auto opacity-0 group-last:opacity-0 transition group-hover:opacity-100" />
                </div>
              ))
            ) : (
              <div className="text-center py-20 text-ink-400">
                <Landmark className="w-12 h-12 mx-auto mb-4 opacity-20" />
                <p>{searchQuery ? `No cases found for "${searchQuery}".` : 'Search for a topic, keyword, or section to read Supreme Court cases.'}</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
