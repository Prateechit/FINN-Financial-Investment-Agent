# FINN — frontend

The FINN mobile-first PWA: React 19, TypeScript, Vite and Tailwind CSS 4. All data comes from the FINN API. The project overview, the backend setup and the full API reference are in the [root README](../README.md).

Live app: https://finn-financial-investment-agent-eosin.vercel.app

## Run locally

Start the API first (see the root README, *Getting started*), so it listens on `http://127.0.0.1:8000`. Then:

```bash
npm install
npm run dev        # http://localhost:5173 — the dev server proxies /api to http://127.0.0.1:8000
```

| Script | What it does |
|---|---|
| `npm run dev` | Vite dev server with hot reload (`host: true`, so you can open it from a phone on the same network) |
| `npm run build` | TypeScript type-check (`tsc -b`) and production build into `dist/` |
| `npm run lint` | oxlint |
| `npm run preview` | Serve the production build locally |

## Configuration

One build-time variable:

| Variable | Purpose |
|---|---|
| `VITE_API_URL` | Base URL of the API, for example `https://finn-api-bbyo.onrender.com`. Leave it unset in development to use the `/api` proxy. It is baked into the bundle when the app is built. |

## Layout

```
src/
  App.tsx              hash-based routing between screens, tab bar, settings sheet
  screens/             Brief · Alerts · Research · Memo · Portfolio (with the company page) · SettingsSheet
  components/          Story (a Brief story card) · Charts · ui (shared primitives)
  lib/                 api.ts (typed API client and response types) · hooks.ts · format.ts
public/
  manifest.webmanifest, icons, sw.js   PWA manifest and service worker
```

In production builds, the service worker caches the app shell and keeps the last API responses as an offline fallback (`src/main.tsx` registers `public/sw.js`).

## Deployment

The app is deployed on Vercel from the `main` branch with `vercel.json` (Vite framework, output `dist/`, `sw.js` served without caching, hashed assets cached for a year). Set `VITE_API_URL` in the Vercel project's environment variables. The API allows cross-origin requests only from the origins configured in `FINN_CORS_ORIGINS`, so preview deployments need their origin added there before they can reach the API.
