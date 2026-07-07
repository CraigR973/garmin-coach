/// <reference types="vite/client" />
/// <reference types="vite-plugin-pwa/client" />

// Batch 62.1: build-time buster injected via vite `define`.
declare const __APP_BUSTER__: string;
