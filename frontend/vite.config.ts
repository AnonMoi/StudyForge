import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  // WorkBuddy's Windows safe-delete hook can block Vite's default dist cleanup.
  // Keep the output directory and let Vite overwrite generated assets safely.
  build: { emptyOutDir: false },
});
