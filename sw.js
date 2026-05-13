const CACHE_NAME = 'po-receiving-v109'; // v86 allocate-from-awaiting: awaiting items now show Allocate from Stock button
const urlsToCache = [
  '/styles.css',
  '/storage-locations.json',
  '/pick_list_data.json',
  '/icons/icon-192.png',
  '/icons/icon-512.png'
];
// NOTE: index.html and app.js NOT cached - always fetch fresh to get latest code

// Install - cache static assets and activate immediately
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(urlsToCache))
      .then(() => self.skipWaiting()) // Don't wait — activate immediately
  );
});

// Activate - clean old caches and take control of all clients
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
    }).then(() => self.clients.claim()) // Take control of all open tabs
  );
});

// Listen for skip waiting messages from the app
self.addEventListener('message', event => {
  if (event.data === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

// Fetch - network first for HTML, JS, and API; cache fallback for static assets
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  
  // CRITICAL: Never intercept non-GET requests (POST, PUT, PATCH, DELETE)
  // iOS Safari has a known bug where service worker interception of POST requests
  // causes DOMException: "The string did not match the expected pattern"
  if (event.request.method !== 'GET') {
    return; // Let the browser handle it directly — do NOT call event.respondWith()
  }
  
  // API GET calls: network only, no cache fallback
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(event.request).catch(() => {
        return new Response(JSON.stringify({error: 'Network unavailable. Please check your connection and try again.'}), 
          {status: 503, headers: {'Content-Type': 'application/json'}});
      })
    );
    return;
  }
  
  // HTML, JS, SW: network first, cache fallback for assets only
  // app.js: ALWAYS network, never cache
  if (url.pathname === '/app.js') {
    event.respondWith(
      fetch(event.request).catch(() => {
        return new Response('Network unavailable - please refresh', {status: 503, headers: {'Content-Type': 'text/plain'}});
      })
    );
    return;
  }
  
  // index.html, sw.js: network first, no cache fallback
  if (url.pathname === '/' || 
      url.pathname === '/index.html' ||
      url.pathname === '/sw.js') {
    event.respondWith(
      fetch(event.request).catch(() => {
        return new Response('Network unavailable - please refresh', {status: 503, headers: {'Content-Type': 'text/plain'}});
      })
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

