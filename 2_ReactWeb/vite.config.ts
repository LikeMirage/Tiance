import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

export default defineConfig(({ command }) => ({
  base: command === "build" ? "./" : "/",
  // The desktop server serves dist in place. Open windows may still lazy-load
  // chunks from the previous build, so retain their content-hashed assets.
  // Use `vite build --emptyOutDir` only when deliberately making a clean build.
  build: { emptyOutDir: false },
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      // These browser entries require DOM APIs unavailable in Markdown workers.
      "decode-named-character-reference": require.resolve("decode-named-character-reference"),
      "hast-util-from-html-isomorphic": require.resolve("hast-util-from-html-isomorphic"),
    },
  },
  server: {
    host: "127.0.0.1",
    port: 18100,
    strictPort: true,
  },
}));
