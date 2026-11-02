# RetinaScreen frontend

React + Vite + TypeScript. Calls the backend at the same origin (`/api/v1`).

```bash
cp .env.example .env     # VITE_DEMO_PASSWORD = backend DEMO_PASSWORD to pre-fill sign-in
npm ci
npm run build            # dist/ is served by the backend on http://127.0.0.1:7860
npm run dev              # http://localhost:5173 , API proxied to 127.0.0.1:7860
npm run lint
```
