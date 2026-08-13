// Минимальный service worker — нужен, чтобы сайт считался полноценным PWA
// и его можно было упаковать в .apk (например, через PWABuilder).
// Данные в приложении живые (логин, прогресс), поэтому НЕ кэшируем HTML/API —
// кэшируем только статику (css/иконки), чтобы не тормозить основные данные.

const CACHE_NAME = "vocab-school-static-v1";
const STATIC_ASSETS = [
  "/static/style.css",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const isStatic = STATIC_ASSETS.some((p) => url.pathname === p);

  if (isStatic) {
    // статика — сначала кэш, потом сеть
    event.respondWith(
      caches.match(event.request).then((cached) => cached || fetch(event.request))
    );
  }
  // всё остальное (страницы, формы, логин) — всегда идёт напрямую в сеть,
  // чтобы данные были актуальные
});
