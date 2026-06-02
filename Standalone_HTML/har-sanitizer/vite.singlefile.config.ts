// Build override used by build.sh. Augments upstream's vite.config.ts with
// vite-plugin-singlefile, which inlines all JS/CSS into one HTML file using
// plain inline <script> tags (not ES modules) so the result works when opened
// directly from the filesystem (file://). It is copied into the cloned
// har-sanitizer repo at build time and selected via `vite build --config`.
import { defineConfig, mergeConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";
import base from "./vite.config";

export default mergeConfig(base, defineConfig({ plugins: [viteSingleFile()] }));
