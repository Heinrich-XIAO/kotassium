// Kotassium service worker.
//
// Deliberately thin: it exists so the app is installable and so a dropped
// connection does not blank the window, not to cache the app. The page is the
// source of truth and must always come from the server, so everything goes
// network-first and only the shell falls back to cache when offline.
const SHELL = "kotassium-shell-v1";

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.add("/")).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  const u = new URL(e.request.url);
  if (u.origin !== self.location.origin) return;
  // Audio, covers and API answers are never cached: they are the live library.
  if (/^\/(api|lib|cover)\//.test(u.pathname)) return;
  e.respondWith(
    fetch(e.request).catch(() =>
      caches.match(e.request).then((r) => r || caches.match("/"))
    )
  );
});
