import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { api } from './api'

const cache = new Map<string, unknown>()

/** Fetch with stale-while-revalidate from an in-memory cache, so tab switches feel instant. */
export function useApi<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | undefined>(() => (path ? (cache.get(path) as T | undefined) : undefined))
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const load = useCallback(async () => {
    if (!path) return
    setLoading(true)
    try {
      const d = await api<T>(path)
      cache.set(path, d)
      setData(d)
      setError(null)
    } catch (e) {
      setError(String((e as Error).message ?? e))
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps])
  useEffect(() => {
    if (path && cache.has(path)) setData(cache.get(path) as T)
    load()
  }, [load, path])
  return { data, error, loading, reload: load, setData }
}

// ---- tiny persistent store (per-viewer conveniences only) ----
function read<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key)
    return v ? (JSON.parse(v) as T) : fallback
  } catch {
    return fallback
  }
}
const listeners = new Set<() => void>()
const memo = new Map<string, unknown>()

export function usePersisted<T>(key: string, fallback: T): [T, (v: T) => void] {
  const get = () => {
    if (!memo.has(key)) memo.set(key, read(key, fallback))
    return memo.get(key) as T
  }
  const value = useSyncExternalStore((cb) => { listeners.add(cb); return () => listeners.delete(cb) }, get, get)
  const set = (v: T) => {
    memo.set(key, v)
    try { localStorage.setItem(key, JSON.stringify(v)) } catch { /* private mode */ }
    listeners.forEach((l) => l())
  }
  return [value, set]
}

export function useHashRoute(): [string[], (to: string) => void] {
  const parse = () => (location.hash.replace(/^#\/?/, '') || 'brief').split('/').map(decodeURIComponent)
  const [route, setRoute] = useState(parse)
  useEffect(() => {
    const on = () => { setRoute(parse()); window.scrollTo(0, 0) }
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return [route, (to: string) => { location.hash = `/${to}` }]
}

export function useInterval(fn: () => void, ms: number | null) {
  const ref = useRef(fn)
  ref.current = fn
  useEffect(() => {
    if (ms == null) return
    const id = setInterval(() => ref.current(), ms)
    return () => clearInterval(id)
  }, [ms])
}
