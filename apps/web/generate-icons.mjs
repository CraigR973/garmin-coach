/**
 * Generate Calcio PWA icons, favicons, and brand variants from the approved
 * primary target-ball logo.
 *
 * Master source of truth:
 *   apps/web/public/brand/calcio-icon-primary.svg
 *
 * Run with:
 *   node apps/web/generate-icons.mjs
 */

import { Resvg } from '@resvg/resvg-js';
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dir = dirname(fileURLToPath(import.meta.url));
const publicDir = join(__dir, 'public');
const brandDir = join(publicDir, 'brand');
const primarySvgPath = join(brandDir, 'calcio-icon-primary.svg');

const NAVY = '#071A3D';
const WHITE = '#F8F5ED';
const GOLD = '#D4A44B';

mkdirSync(brandDir, { recursive: true });

function targetMark({ ink, accent = ink, includeAccent = false }) {
  const accentPath = includeAccent
    ? `  <path d="M378.6 153.2a160 160 0 0 1 0 205.6l-68.9-57.8a70 70 0 0 0 0-90Z" fill="${accent}" />
`
    : '';

  return `${accentPath}  <circle cx="256" cy="256" r="160" fill="none" stroke="${ink}" stroke-width="30" />
  <circle cx="256" cy="256" r="98" fill="none" stroke="${ink}" stroke-width="18" />
  <path
    d="M256 217a39 39 0 1 0 0 78a39 39 0 1 0 0-78ZM256 240a16 16 0 1 1 0 32a16 16 0 1 1 0-32Z"
    fill="${ink}"
    fill-rule="evenodd"
  />
  <path
    d="M176 142l46 78M336 142l-46 78M118 276h92M394 276h-92M176 370l46-78M336 370l-46-78"
    fill="none"
    stroke="${ink}"
    stroke-linecap="round"
    stroke-width="18"
  />`;
}

function svgDocument(content, label = 'Calcio icon') {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="${label}">
${content}
</svg>
`;
}

function tileSvg({ background, ink, accent, includeAccent }) {
  return svgDocument(`  <rect width="512" height="512" rx="96" fill="${background}" />
${targetMark({ ink, accent, includeAccent })}`);
}

function render(svg, size) {
  const resvg = new Resvg(svg, {
    fitTo: { mode: 'width', value: size },
    font: { loadSystemFonts: false },
  });
  return resvg.render().asPng();
}

function pngToIco(pngBuf) {
  const pngLen = pngBuf.length;
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
  entry.writeUInt32LE(pngLen, 8);
  entry.writeUInt32LE(22, 12);

  return Buffer.concat([header, entry, pngBuf]);
}

const primarySvg = readFileSync(primarySvgPath, 'utf8');
const darkIconSvg = primarySvg;
const goldIconSvg = tileSvg({
  background: GOLD,
  ink: NAVY,
  accent: NAVY,
  includeAccent: false,
});
const markSvg = svgDocument(targetMark({ ink: WHITE, accent: GOLD, includeAccent: true }), 'Calcio mark');
const markMonoSvg = svgDocument(targetMark({ ink: WHITE }), 'Calcio mark');
const markGoldSvg = svgDocument(targetMark({ ink: GOLD }), 'Calcio mark');

writeFileSync(join(brandDir, 'calcio-icon-dark.svg'), darkIconSvg);
writeFileSync(join(brandDir, 'calcio-icon-gold.svg'), goldIconSvg);
writeFileSync(join(brandDir, 'calcio-mark.svg'), markSvg);
writeFileSync(join(brandDir, 'calcio-mark-mono.svg'), markMonoSvg);
writeFileSync(join(brandDir, 'calcio-mark-gold.svg'), markGoldSvg);

copyFileSync(primarySvgPath, join(publicDir, 'favicon.svg'));

for (const size of [32, 64, 128, 180, 192, 512, 1024]) {
  writeFileSync(join(brandDir, `calcio-icon-primary-${size}.png`), render(primarySvg, size));
}

writeFileSync(join(publicDir, 'icon-32.png'), render(primarySvg, 32));
writeFileSync(join(publicDir, 'icon-64.png'), render(primarySvg, 64));
writeFileSync(join(publicDir, 'icon-128.png'), render(primarySvg, 128));
writeFileSync(join(publicDir, 'icon-192.png'), render(primarySvg, 192));
writeFileSync(join(publicDir, 'icon-384.png'), render(primarySvg, 384));
writeFileSync(join(publicDir, 'icon-512.png'), render(primarySvg, 512));
writeFileSync(join(publicDir, 'icon-1024.png'), render(primarySvg, 1024));
writeFileSync(join(publicDir, 'apple-touch-icon.png'), render(primarySvg, 180));
writeFileSync(join(publicDir, 'favicon.ico'), pngToIco(render(primarySvg, 32)));

const maskableSvg = tileSvg({
  background: NAVY,
  ink: WHITE,
  accent: GOLD,
  includeAccent: true,
});
writeFileSync(join(publicDir, 'icon-maskable-512.png'), render(maskableSvg, 512));

console.log('Calcio primary icon assets generated from public/brand/calcio-icon-primary.svg');
