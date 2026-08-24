const cache = new Map()
const prefetching = new Map()

export function buildListCacheKey(listType, params) {
  const p = { ...params }
  delete p.page
  delete p.page_size
  delete p.skip_total
  return `${listType}|${JSON.stringify(p)}`
}

export function buildPageCacheKey(listType, params, page, pageSize) {
  return `${buildListCacheKey(listType, params)}|p${page}|s${pageSize}`
}

export function getListCache(key) {
  const cached = cache.get(key)
  if (!cached) return null
  if (cached.total <= 61 && (cached.items?.length || 0) >= (cached.pageSize || 30)) {
    cache.delete(key)
    return null
  }
  return cached
}

export function setListCache(key, payload) {
  cache.set(key, payload)
}

export function hasListCache(key) {
  return cache.has(key)
}

export function isListPrefetching(key) {
  return prefetching.has(key)
}

export function getListPrefetchPromise(key) {
  return prefetching.get(key)
}

export function markListPrefetching(key, promise) {
  prefetching.set(key, promise)
}

export function unmarkListPrefetching(key) {
  prefetching.delete(key)
}

export function clearListCache() {
  cache.clear()
  prefetching.clear()
}
