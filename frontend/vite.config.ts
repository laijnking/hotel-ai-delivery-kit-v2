import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiProxyTarget = process.env.VITE_PROXY_TARGET || "http://127.0.0.1:8100";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: "0.0.0.0",
    proxy: {
      "/api": apiProxyTarget
    }
  },
  preview: {
    port: 3000,
    host: "0.0.0.0",
    proxy: {
      "/api": apiProxyTarget
    }
  }
});
