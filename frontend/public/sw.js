const CACHE_NAME = "jan-sahayak-v1";
const OFFLINE_URL = "/";

const ASSETS_TO_CACHE = [
  "/",
  "/favicon.ico",
  "/manifest.json"
];

// Install Event
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log("[Service Worker] Caching app shell and offline pages");
      return cache.addAll(ASSETS_TO_CACHE);
    })
  );
  self.skipWaiting();
});

// Activate Event
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cache) => {
          if (cache !== CACHE_NAME) {
            console.log("[Service Worker] Clearing old cache");
            return caches.delete(cache);
          }
        })
      );
    })
  );
  self.clients.claim();
});

// Fetch Event
self.addEventListener("fetch", (event) => {
  // Only intercept HTTP/S GET requests
  if (
    event.request.method !== "GET" || 
    !event.request.url.startsWith(self.location.origin)
  ) {
    return;
  }

  // Skip API requests (voice, chat, digitize should always go to network)
  if (event.request.url.includes("/api/")) {
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // Cache successful network responses
        if (response.status === 200) {
          const responseClone = response.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseClone);
          });
        }
        return response;
      })
      .catch(() => {
        // Network failed, load from cache
        return caches.match(event.request).then((cachedResponse) => {
          if (cachedResponse) {
            return cachedResponse;
          }
          // If a page/document fetch failed, return offline index
          if (event.request.headers.get("accept").includes("text/html")) {
            return caches.match(OFFLINE_URL);
          }
        });
      })
  );
});
