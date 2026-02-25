const CACHE_NAME = 'po-receiving-v33';
const urlsToCache = [
  '/styles.css',
  '/storage-locations.json',
  '/pick_list_data.json',
  '/icons/icon-192.png',
  '/icons/icon-512.png'
];
// NOTE: index.html and app.js NOT cached - always fetch fresh to get latest code

// Install - cache static assets only
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(urlsToCache))
  );
  self.skipWaiting();
});

// Activate - clean old caches immediately
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

// Fetch - network first for HTML, JS, and API; cache fallback for static assets
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  
  // Always fetch HTML, API calls, and JS from network
  if (url.pathname.startsWith('/api/') || 
      url.pathname === '/app.js' || 
      url.pathname === '/' || 
      url.pathname === '/index.html' ||
      url.pathname === '/sw.js') {
    event.respondWith(
      fetch(event.request).catch(() => caches.match(event.request))
    );
    return;
  }
  
  // For static assets (CSS, images, JSON), try cache first, then network
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
