/**
 * Sayad Pro 3.0 - High-Performance Fintech Progressive Web App (PWA) Service Worker
 * Dual Strategy:
 *  - Cache-First for static assets (fonts, stylesheets, scripts, icons, libraries)
 *  - Network-First with local fallback for API endpoints & initial dataset
 */

const CACHE_NAME = 'sayad-pro-v3.0.0-cache';
const DATA_CACHE_NAME = 'sayad-pro-v3.0.0-data';

const STATIC_ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './css/style.css',
  './js/app.js',
  './js/theme.js',
  './js/logger.js',
  './js/pasargad_engine.js',
  './data/initial_dataset.json',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/icon-maskable.png',
  './icons/icon.svg'
];

const CDN_PRECACHE = [
  'https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/Vazirmatn-font-face.css',
  'https://cdn.tailwindcss.com',
  'https://unpkg.com/lucide@latest',
  'https://cdn.jsdelivr.net/npm/chart.js'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async (cache) => {
      try {
        await cache.addAll(STATIC_ASSETS);
      } catch (err) {
        console.warn('[SW] Some local static assets could not be precached:', err);
      }
      for (const url of CDN_PRECACHE) {
        try {
          const res = await fetch(url, { mode: 'no-cors' });
          if (res) await cache.put(url, res);
        } catch (e) {
          // Silently ignore if offline during install
        }
      }
    }).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME && key !== DATA_CACHE_NAME) {
            console.log('[SW] Pruning legacy cache:', key);
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Only handle GET requests
  if (req.method !== 'GET') {
    return;
  }

  // 1. API Requests & Data -> Network-First with Cache Fallback
  if (url.pathname.startsWith('/api/') || url.pathname.includes('initial_dataset.json')) {
    event.respondWith(
      fetch(req)
        .then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            const copy = networkResponse.clone();
            caches.open(DATA_CACHE_NAME).then((cache) => {
              cache.put(req, copy);
            });
          }
          return networkResponse;
        })
        .catch(async () => {
          const cachedResponse = await caches.match(req);
          if (cachedResponse) {
            return cachedResponse;
          }
          return new Response(JSON.stringify({
            offline: true,
            message: "دسترسی به شبکه اینترنت شعب بانک قطع می‌باشد. اطلاعات از حافظه کش محلی بارگذاری شد."
          }), {
            headers: { 'Content-Type': 'application/json; charset=utf-8' }
          });
        })
    );
    return;
  }

  // 2. Static Assets (CSS, JS, Fonts, Images, Icons) -> Cache-First with Background Revalidation
  event.respondWith(
    caches.match(req).then((cachedResponse) => {
      if (cachedResponse) {
        fetch(req).then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            caches.open(CACHE_NAME).then((cache) => cache.put(req, networkResponse));
          }
        }).catch(() => {});
        return cachedResponse;
      }

      return fetch(req).then((networkResponse) => {
        if (!networkResponse || networkResponse.status !== 200) {
          return networkResponse;
        }
        const responseToCache = networkResponse.clone();
        caches.open(CACHE_NAME).then((cache) => {
          cache.put(req, responseToCache);
        });
        return networkResponse;
      }).catch(async () => {
        if (req.mode === 'navigate' || req.headers.get('accept')?.includes('text/html')) {
          const fallback = await caches.match('./index.html') || await caches.match('/');
          if (fallback) return fallback;
        }
        return new Response("حالت آفلاین صیاد پرو ۳.۰", { status: 503, statusText: "Offline" });
      });
    })
  );
});
