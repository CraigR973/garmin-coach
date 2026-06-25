/**
 * Generate the "CheckMark" PWA icon set, favicons, and brand variants from a
 * single deterministic source of truth defined in this file.
 *
 * Concept (DECISIONS #89): a bold white checkmark that doubles as an ECG /
 * heartbeat trace — a short baseline, one clean heartbeat spike, a drop into
 * the tick valley, then a strong upward checkmark arm — set on a deep-teal →
 * fresh-green tile, with a faint Green/Amber/Red "verdict" gauge arc behind it
 * (a nod to the morning Green/Amber/Red verdict, ARCHITECTURE §4). The mark
 * stays dominant; the arc is low-opacity and secondary.
 *
 * Master art is defined here (not a hand-edited SVG) so every export — the
 * crisp favicon, the arc-bearing app icons, the full-bleed maskable + Apple
 * touch icons — is regenerated consistently. Re-run after any tweak:
 *
 *   node apps/web/generate-icons.mjs
 */

import { Resvg } from '@resvg/resvg-js';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dir = dirname(fileURLToPath(import.meta.url));
const publicDir = join(__dir, 'public');
const brandDir = join(publicDir, 'brand');
mkdirSync(brandDir, { recursive: true });

// --- Palette --------------------------------------------------------------
const TEAL = '#0C5A63'; // deep teal — top-left of the tile gradient
const TEAL_MID = '#157C5B';
const GREEN = '#46C24E'; // fresh green — bottom-right of the tile gradient
const WHITE = '#FFFFFF';
// Verdict gauge (Green / Amber / Red), drawn behind the mark. Kept vivid and
// at a fairly high opacity on purpose: low-opacity warm tones composite against
// the teal tile and turn muddy brown, so the gauge must stay saturated to read
// as Red→Amber→Green. It still reads as secondary — it is thin and sits behind
// the bold white mark.
const V_RED = '#FF4A3D';
const V_AMBER = '#FFB22E';
const V_GREEN = '#43E06E';

// The ECG-checkmark stroke as a single open polyline:
//   baseline (flat) → heartbeat spike (up) → tick valley (down) → long arm (up).
const MARK = 'M140 296 L186 296 L213 222 L262 338 L382 190';
const MARK_WIDTH = 32;

function defs() {
  return `  <defs>
    <linearGradient id="tile" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="512" y2="512">
      <stop offset="0" stop-color="${TEAL}" />
      <stop offset="0.55" stop-color="${TEAL_MID}" />
      <stop offset="1" stop-color="${GREEN}" />
    </linearGradient>
    <linearGradient id="verdict" gradientUnits="userSpaceOnUse" x1="110" y1="0" x2="402" y2="0">
      <stop offset="0" stop-color="${V_RED}" />
      <stop offset="0.5" stop-color="${V_AMBER}" />
      <stop offset="1" stop-color="${V_GREEN}" />
    </linearGradient>
    <filter id="glow" x="-40%" y="-40%" width="180%" height="180%" color-interpolation-filters="sRGB">
      <feGaussianBlur stdDeviation="7" />
    </filter>
  </defs>
`;
}

// A faint readiness gauge arched over the top, sitting behind the mark.
function verdictArc() {
  return `  <path d="M113 300 A150 150 0 0 1 399 300" fill="none" stroke="url(#verdict)" stroke-width="15" stroke-linecap="round" opacity="0.8" />
`;
}

// The hero mark: a soft white glow copy underneath, the crisp stroke on top.
function checkmark() {
  return `  <path d="${MARK}" fill="none" stroke="${WHITE}" stroke-width="${MARK_WIDTH}" stroke-linecap="round" stroke-linejoin="round" filter="url(#glow)" opacity="0.6" />
  <path d="${MARK}" fill="none" stroke="${WHITE}" stroke-width="${MARK_WIDTH}" stroke-linecap="round" stroke-linejoin="round" />
`;
}

/**
 * Compose a full 512×512 icon.
 *   includeArc — draw the Green/Amber/Red verdict gauge behind the mark.
 *   rx         — tile corner radius (0 = full-bleed for maskable / Apple).
 *   scale      — shrink the mark+arc toward centre (maskable safe-zone).
 */
function iconSvg({ includeArc = true, rx = 112, scale = 1, label = 'CheckMark' } = {}) {
  const body = `${includeArc ? verdictArc() : ''}${checkmark()}`;
  const wrapped =
    scale === 1
      ? body
      : `  <g transform="translate(256 256) scale(${scale}) translate(-256 -256)">
${body}  </g>
`;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="${label}">
${defs()}  <rect width="512" height="512" rx="${rx}" fill="url(#tile)" />
${wrapped}</svg>
`;
}

// Transparent stroke-only mark (inherits CSS color) for future in-app wordmark use.
function markSvg() {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="CheckMark mark">
  <path d="${MARK}" fill="none" stroke="currentColor" stroke-width="${MARK_WIDTH}" stroke-linecap="round" stroke-linejoin="round" />
</svg>
`;
}

function render(svg, size) {
  const resvg = new Resvg(svg, {
    fitTo: { mode: 'width', value: size },
    font: { loadSystemFonts: false },
  });
  return resvg.render().asPng();
}

// Minimal single-image .ico wrapping a 32×32 PNG (same approach as the fork).
function pngToIco(pngBuf) {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(1, 4);

  const entry = Buffer.alloc(16);
  entry.writeUInt8(32, 0);
  entry.writeUInt8(32, 1);
  entry.writeUInt8(0, 2);
  entry.writeUInt8(0, 3);
  entry.writeUInt16LE(1, 4);
  entry.writeUInt16LE(32, 6);
  entry.writeUInt32LE(pngBuf.length, 8);
  entry.writeUInt32LE(22, 12);

  return Buffer.concat([header, entry, pngBuf]);
}

// --- Master variants ------------------------------------------------------
const primary = iconSvg({ includeArc: true }); // app icon, rounded tile + arc
const simple = iconSvg({ includeArc: false }); // arc-less, crisp at tiny sizes
const maskable = iconSvg({ includeArc: true, rx: 0, scale: 0.78 }); // safe-zone
const appleBleed = iconSvg({ includeArc: true, rx: 0 }); // full-bleed for iOS
const mark = markSvg();

writeFileSync(join(brandDir, 'checkmark-icon-primary.svg'), primary);
writeFileSync(join(brandDir, 'checkmark-icon-simple.svg'), simple);
writeFileSync(join(brandDir, 'checkmark-icon-maskable.svg'), maskable);
writeFileSync(join(brandDir, 'checkmark-mark.svg'), mark);

// favicon.svg → the simplified, arc-less art (legible in a browser tab).
writeFileSync(join(publicDir, 'favicon.svg'), simple);

// Square PNGs: small sizes use the arc-less art; ≥128 carry the verdict arc.
writeFileSync(join(publicDir, 'icon-32.png'), render(simple, 32));
writeFileSync(join(publicDir, 'icon-64.png'), render(simple, 64));
writeFileSync(join(publicDir, 'icon-128.png'), render(primary, 128));
writeFileSync(join(publicDir, 'icon-192.png'), render(primary, 192));
writeFileSync(join(publicDir, 'icon-384.png'), render(primary, 384));
writeFileSync(join(publicDir, 'icon-512.png'), render(primary, 512));
writeFileSync(join(publicDir, 'icon-1024.png'), render(primary, 1024));
writeFileSync(join(publicDir, 'apple-touch-icon.png'), render(appleBleed, 180));
writeFileSync(join(publicDir, 'icon-maskable-512.png'), render(maskable, 512));
writeFileSync(join(publicDir, 'favicon.ico'), pngToIco(render(simple, 32)));

console.log('CheckMark icon assets generated from generate-icons.mjs');
