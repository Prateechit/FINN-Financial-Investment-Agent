// Minimal offline shell: cache the app on install, serve API from network with a cached fallback.
const SHELL = 'finn-shell-v1'
const DATA = 'finn-data-v1'

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(['/', '/manifest.webmanifest', '/icon.svg'])))
  self.skipWaiting()
})

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => ![SHELL, DATA].includes(k)).map((k) => caches.delete(k)))))
  self.clients.claim()
})

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url)
  if (e.request.method !== 'GET') return
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(
      fetch(e.request)
        .then((r) => { const copy = r.clone(); caches.open(DATA).then((c) => c.put(e.request, copy)); return r })
        .catch(() => caches.match(e.request)),
    )
    return
  }
  if (url.origin === location.origin) {
    e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request).then((r) => {
      const copy = r.clone(); caches.open(SHELL).then((c) => c.put(e.request, copy)); return r
    })))
  }
})

self.addEventListener('push', (e) => {
  const d = e.data ? e.data.json() : { title: 'FINN', body: 'Something in your portfolio needs a look.' }
  e.waitUntil(self.registration.showNotification(d.title, { body: d.body, icon: '/icon-192.png', badge: '/icon-192.png', data: d.url || '/#/alerts' }))
})

self.addEventListener('notificationclick', (e) => {
  e.notification.close()
  e.waitUntil(self.clients.openWindow(e.notification.data || '/#/alerts'))
})
