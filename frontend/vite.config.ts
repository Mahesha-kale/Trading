import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// ponytail: dev proxy to backend; prod served by nginx which already proxies /api.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://localhost:8000" } },
});