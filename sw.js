const CACHE_NAME = 'po-receiving-v9';
const urlsToCache = [
  '/',
  '/index.html',
  '/styles.css',
  '/storage-locations.json',
  '/pick_list_data.json',
  '/icons/icon-192.png',
  '/icons/icon-512.png'
];
// NOTE: app.js NOT cached - always fetch fresh to get latest code

// Install - cache assets
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(urlsToCache))
  );
  self.skipWaiting();
});

// Activate - clean old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheName !== CACHE_NAME) {
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
  self.clients.claim();
});

// Fetch - network first for API and app.js, cache fallback for static assets
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  
  // Always fetch API calls and app.js from network
  if (url.pathname.startsWith('/api/') || url.pathname === '/app.js') {
    event.respondWith(fetch(event.request));
    return;
  }
  
  // For other resources, try cache first, then network
  event.respondWith(
    caches.match(event.request)
      .then(response => {
        if (response) {
          return response;
        }
        return fetch(event.request);
      })
  );
});
