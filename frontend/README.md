# Anarisk frontend

React, TypeScript, and Vite client for the Anarisk digital risk investigation platform.

## Requirements

- Node.js 20 or newer
- npm
- Anarisk API running locally, or a deployed API URL

## Run locally

```bash
npm install
Copy-Item .env.example .env.local
npm run dev
```

The Vite development server runs at http://localhost:3000. By default, requests to
`/api` are proxied to `http://localhost:8000`. Set `VITE_API_BASE_URL` in `.env.local`
to point the client at a separately hosted API, for example:

```env
VITE_API_BASE_URL=https://your-api.example.com/api/v1
```

The API must allow the frontend's origin in its `CORS_ORIGINS` setting.

## Build

```bash
npm run build
npm run preview
```

## GitHub repository

This directory is a self-contained frontend project. To publish it as its own
repository, create an empty GitHub repository, then run these commands from this
directory:

```bash
git init -b main
git add .
git commit -m "Initial frontend project"
git remote add origin https://github.com/YOUR-USER/YOUR-FRONTEND-REPO.git
git push -u origin main
```

Keep `.env.local` out of Git; `.env*` files are ignored except this example file.
