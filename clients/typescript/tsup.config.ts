// Dual-package build: emit both ESM (.js) and CJS (.cjs) from the same
// TypeScript sources, with shared .d.ts declarations.
//
// Why this exists: v0.7.3 shipped ESM-only, which broke CJS consumers like
// Node servers using `require('typedmem-client')`. tsup transparently handles
// the import-extension rewriting that plain tsc gets wrong when targeting both
// formats from the same .ts sources.

import { defineConfig } from "tsup";

export default defineConfig({
  entry: ["src/index.ts"],
  format: ["esm", "cjs"],
  dts: true,
  clean: true,
  sourcemap: true,
  target: "node18",
  // Keep the bundle small: no minification, no tree-shaking surprises, and
  // mark ourselves as zero-runtime-deps (native fetch on Node 18+).
  minify: false,
  splitting: false,
});
