/**
 * Generate PWA icon PNGs from the Concept 3 letterform SVG.
 *
 * Outputs to apps/web/public/:
 *   icon-192.png       — standard PWA icon
 *   icon-384.png       — mid-res PWA icon
 *   icon-512.png       — large PWA icon
 *   icon-maskable-512.png — Android adaptive icon (mark inset to 80 % safe zone)
 *   apple-touch-icon.png  — 180 × 180, padded, for iOS "Add to Home Screen"
 *   favicon.svg        — vector favicon (copied from source)
 *   favicon.ico        — 32 × 32 fallback, PNG-in-ICO wrapper
 *
 * Run with:
 *   node scripts/generate-icons.mjs
 */

import { Resvg } from '@resvg/resvg-js';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dir = dirname(fileURLToPath(import.meta.url));
const root = join(__dir, '..');
const src = join(root, 'docs/logo-concepts/concept-3-letterform.svg');
const out = join(root, 'apps/web/public');

mkdirSync(out, { recursive: true });

const darkSvg = readFileSync(src, 'utf8');

// ── Maskable variant ──────────────────────────────────────────────────────────
// Android adaptive icons crop to ~72 % of the image area. The "safe zone" for
// important content is the inner 80 % (409.6 px in a 512 px canvas).
// Strategy: full-bleed graphite background, S mark scaled to 80 % and centred.
//
// The original mark spans viewBox 0 0 512 512 with a 96 rx rounded rect.
// For maskable we strip the rounded rect and embed the whole original SVG as a
// nested <image> scaled to 80 % at (51.2, 51.2) — but <image> embedding SVG is
// unreliable in resvg. Instead we inline the same paths but wrapped in a
// transform that shrinks to 80 % around the 256,256 centre.

const maskableSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <!-- Full-bleed background — no rounded corners for maskable -->
  <rect width="512" height="512" fill="#0B0E13"/>
  <!-- Mark scaled to 80 % centred at (256, 256): translate(256,256) scale(0.8) translate(-256,-256) -->
  <g transform="translate(256,256) scale(0.8) translate(-256,-256)">
    <path d="
          M 380 158
          C 380 110, 322 96, 256 96
          C 188 96, 134 142, 134 200
          C 134 252, 178 282, 230 282
          L 282 282
          C 334 282, 378 312, 378 364
          C 378 422, 324 466, 256 466
          C 190 466, 132 446, 132 402
         "
         fill="none"
         stroke="#D4A24A"
         stroke-width="56"
         stroke-linecap="round"
         stroke-linejoin="round"/>
    <path d="M 256 218 L 226 244 L 238 282 L 274 282 L 286 244 Z"
          fill="#0B0E13"
          stroke="#0B0E13"
          stroke-width="2"
          stroke-linejoin="round"/>
    <path d="M 256 218 L 226 244 L 238 282 L 274 282 L 286 244 Z"
          fill="none"
          stroke="#D4A24A"
          stroke-width="6"
          stroke-linejoin="round"/>
  </g>
</svg>`;

// ── Apple touch icon variant ──────────────────────────────────────────────────
// 180 × 180 at 87.5 % scale centred — Apple applies its own squircle mask and
// does not honour the manifest maskable hint, so we give it a padded version.
const appleSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="96" ry="96" fill="#0B0E13"/>
  <g transform="translate(256,256) scale(0.875) translate(-256,-256)">
    <path d="
          M 380 158
          C 380 110, 322 96, 256 96
          C 188 96, 134 142, 134 200
          C 134 252, 178 282, 230 282
          L 282 282
          C 334 282, 378 312, 378 364
          C 378 422, 324 466, 256 466
          C 190 466, 132 446, 132 402
         "
         fill="none"
         stroke="#D4A24A"
         stroke-width="56"
         stroke-linecap="round"
         stroke-linejoin="round"/>
    <path d="M 256 218 L 226 244 L 238 282 L 274 282 L 286 244 Z"
          fill="#0B0E13"
          stroke="#0B0E13"
          stroke-width="2"
          stroke-linejoin="round"/>
    <path d="M 256 218 L 226 244 L 238 282 L 274 282 L 286 244 Z"
          fill="none"
          stroke="#D4A24A"
          stroke-width="6"
          stroke-linejoin="round"/>
  </g>
</svg>`;

/** Render an SVG string to a PNG Buffer at `size × size`. */
function render(svgStr, size) {
  const resvg = new Resvg(svgStr, {
    fitTo: { mode: 'width', value: size },
    font: { loadSystemFonts: false },
  });
  return resvg.render().asPng();
}

/** Wrap a PNG buffer in a minimal PNG-in-ICO container (single image). */
function pngToIco(pngBuf) {
  const pngLen = pngBuf.length;
  // ICO header: 6 bytes
  // Directory entry: 16 bytes
  // Then the PNG data
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0); // reserved
  header.writeUInt16LE(1, 2); // type: 1 = ICO
  header.writeUInt16LE(1, 4); // count: 1 image

  const entry = Buffer.alloc(16);
  entry.writeUInt8(32, 0);    // width  (0 = 256; 32 = 32 px)
  entry.writeUInt8(32, 1);    // height (0 = 256; 32 = 32 px)
  entry.writeUInt8(0, 2);     // colour count (0 = no palette)
  entry.writeUInt8(0, 3);     // reserved
  entry.writeUInt16LE(1, 4);  // colour planes
  entry.writeUInt16LE(32, 6); // bits per pixel
  entry.writeUInt32LE(pngLen, 8);  // size of image data
  entry.writeUInt32LE(22, 12);     // offset of image data (6 + 16)

  return Buffer.concat([header, entry, pngBuf]);
}

// ── Generate files ─────────────────────────────────────────────────────────────

console.log('Generating icon-192.png …');
writeFileSync(join(out, 'icon-192.png'), render(darkSvg, 192));

console.log('Generating icon-384.png …');
writeFileSync(join(out, 'icon-384.png'), render(darkSvg, 384));

console.log('Generating icon-512.png …');
writeFileSync(join(out, 'icon-512.png'), render(darkSvg, 512));

console.log('Generating icon-maskable-512.png …');
writeFileSync(join(out, 'icon-maskable-512.png'), render(maskableSvg, 512));

console.log('Generating apple-touch-icon.png (180 px) …');
writeFileSync(join(out, 'apple-touch-icon.png'), render(appleSvg, 180));

console.log('Generating favicon.svg (copy) …');
writeFileSync(join(out, 'favicon.svg'), darkSvg);

console.log('Generating favicon.ico (32 px PNG-in-ICO) …');
const ico32 = render(darkSvg, 32);
writeFileSync(join(out, 'favicon.ico'), pngToIco(ico32));

console.log('✓ All icons written to apps/web/public/');
