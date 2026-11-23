import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // npm run dev: the API runs on the backend's port (python src/demo.py)
  server: { proxy: { '/api': 'http://127.0.0.1:7860' } },
})
