import { useState, useEffect, useRef } from 'react'
import { BookOpen, Search, ChevronRight, Menu } from 'lucide-react'
import { cn } from '@/lib/utils'
import { api } from '@/api/client'
import Spinner from '@/components/ui/Spinner'
import Input from '@/components/ui/Input'

export default function BareActsPage() {
  const [acts, setActs] = useState([])
  const [activeAct, setActiveAct] = useState(null)
  const [sections, setSections] = useState([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState(null)
  const [searching, setSearching] = useState(false)
  
  const contentRef = useRef(null)

  useEffect(() => {
    // Fetch acts
    api.bareActsList()
      .then(res => {
        setActs(res)
        if (res.length > 0) {
          setActiveAct(res[0])
        }
      })
      .catch(err => {
        console.error('Failed to load acts', err)
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (activeAct && !searchQuery) {
      setLoading(true)
      api.bareActsGet(activeAct)
        .then(res => setSections(res))
        .catch(console.error)
        .finally(() => setLoading(false))
    }
  }, [activeAct, searchQuery])

  useEffect(() => {
    if (!searchQuery) {
      setSearchResults(null)
      return
    }
    
    const delayDebounce = setTimeout(() => {
      setSearching(true)
      api.bareActsSearch(searchQuery, activeAct)
        .then(res => setSearchResults(res))
        .catch(console.error)
        .finally(() => setSearching(false))
    }, 400)

    return () => clearTimeout(delayDebounce)
  }, [searchQuery, activeAct])

  const handleSectionClick = (sectionNumber) => {
    const el = document.getElementById(`section-${sectionNumber}`)
    if (el && contentRef.current) {
      // scroll contentRef so el is at top
      contentRef.current.scrollTo({
        top: el.offsetTop - 20,
        behavior: 'smooth'
      })
    }
  }

  const displayedSections = searchQuery && searchResults ? searchResults : sections

  return (
    <div className="flex flex-col h-[calc(100vh-6rem)] -m-4 sm:-m-6 lg:-m-8">
      {/* Header */}
      <div className="flex-none p-4 border-b border-white/5 bg-ink-950/80 backdrop-blur flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 overflow-x-auto no-scrollbar">
          <BookOpen className="w-5 h-5 text-gold-400 shrink-0" />
          <h1 className="text-lg font-serif font-medium whitespace-nowrap">Bare Acts Reader</h1>
          <div className="w-px h-6 bg-white/10 mx-2 shrink-0" />
          <div className="flex gap-1 shrink-0">
            {acts.map(act => (
              <button
                key={act}
                onClick={() => {
                  setActiveAct(act)
                  setSearchQuery('')
                }}
                className={cn(
                  "px-3 py-1.5 rounded-lg text-sm transition-colors",
                  activeAct === act 
                    ? "bg-gold-500/20 text-gold-200" 
                    : "text-ink-300 hover:text-ink-100 hover:bg-white/5"
                )}
              >
                {act}
              </button>
            ))}
          </div>
        </div>
        <div className="w-64 shrink-0 relative hidden sm:block">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
          <input
            type="text"
            placeholder="Search acts..."
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
            {loading || searching ? (
              <div className="flex justify-center p-8"><Spinner className="w-5 h-5 text-gold-500" /></div>
            ) : (
              displayedSections.map(sec => (
                <button
                  key={sec.section_number}
                  onClick={() => handleSectionClick(sec.section_number)}
                  className="w-full text-left px-3 py-2 rounded-lg hover:bg-white/5 text-sm flex items-start gap-2 group transition"
                >
                  <span className="text-gold-500/70 font-medium shrink-0">
                    Sec {sec.section_number}
                  </span>
                  <span className="text-ink-200 line-clamp-2 group-hover:text-ink-50 transition">
                    {sec.section_title}
                  </span>
                </button>
              ))
            )}
            {!loading && !searching && displayedSections.length === 0 && (
              <div className="p-4 text-sm text-ink-400 text-center">No sections found.</div>
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
              placeholder="Search acts..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-xl py-2 pl-9 pr-3 text-sm focus:outline-none focus:border-gold-500/50"
            />
          </div>

          <div className="max-w-4xl mx-auto space-y-12">
            {loading || searching ? (
              <div className="flex justify-center items-center h-64">
                <Spinner className="w-8 h-8 text-gold-500" />
              </div>
            ) : (
              displayedSections.map(sec => (
                <div key={sec.section_number} id={`section-${sec.section_number}`} className="group">
                  <div className="mb-4">
                    <h2 className="text-xl font-serif text-gold-200 mb-1">
                      Section {sec.section_number}
                    </h2>
                    {sec.section_title && (
                      <h3 className="text-lg text-ink-100 font-medium leading-snug">
                        {sec.section_title}
                      </h3>
                    )}
                  </div>
                  
                  <div className="prose prose-invert prose-p:leading-relaxed max-w-none text-ink-200 whitespace-pre-wrap">
                    {sec.text}
                  </div>
                  
                  {sec.punishment && (
                    <div className="mt-6 p-4 rounded-xl bg-red-950/20 border border-red-900/30">
                      <div className="text-sm font-medium text-red-400 mb-1">Punishment</div>
                      <div className="text-sm text-ink-200">{sec.punishment}</div>
                    </div>
                  )}
                  
                  <div className="w-16 h-px bg-white/10 mt-12 mb-2 mx-auto opacity-0 group-last:opacity-0 transition group-hover:opacity-100" />
                </div>
              ))
            )}
            
            {!loading && !searching && displayedSections.length === 0 && (
              <div className="text-center py-20 text-ink-400">
                <BookOpen className="w-12 h-12 mx-auto mb-4 opacity-20" />
                <p>No results found for "{searchQuery}".</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
