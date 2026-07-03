import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxy: forward the Consent Manager API to a local backend so the UI can
// run without CORS. The backend serves everything under /consent/v1, so we
// proxy that prefix verbatim (no rewrite). In production the UI is served by
// nginx and the API is reached via config.json.apiBaseUrl + Istio routing.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/consent": {
        target: process.env.CM_API_URL || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
