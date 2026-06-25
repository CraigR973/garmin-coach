# CheckMark Brand Assets

## Concept

The CheckMark mark is a bold white **checkmark that doubles as an ECG /
heartbeat trace**: a short baseline, one clean heartbeat spike, a drop into the
tick valley, then a strong upward checkmark arm. It sits on a deep-teal →
fresh-green tile, with a faint **Green / Amber / Red verdict gauge arc** behind
it — a nod to the daily morning verdict (ARCHITECTURE §4). The tick reads as
"approved / all-clear / good to go", the heartbeat as the health data, and the
gauge as the readiness verdict. "Mark" is also the user (DECISIONS #89).

## Palette

- Deep teal (tile, top-left): `#0C5A63`
- Fresh green (tile, bottom-right): `#46C24E`
- Mark: `#FFFFFF`
- Verdict gauge: red `#FF4A3D` · amber `#FFB22E` · green `#43E06E`

## Source of truth

**Do not hand-edit these SVGs or the PNGs.** All assets are generated from
`apps/web/generate-icons.mjs`, which defines the master art (geometry, palette,
glow, arc) in one place. After any tweak, regenerate with Node 20:

```
~/.nvm/versions/node/v20.20.2/bin/node apps/web/generate-icons.mjs
```

(The default `node` on this machine is v14 and cannot run the resvg rasterizer.)

## Variants

- `checkmark-icon-primary.svg` — app icon: rounded tile + verdict arc + glow.
- `checkmark-icon-simple.svg` — arc-less art for crisp small/favicon sizes.
- `checkmark-icon-maskable.svg` — full-bleed, mark pulled into the ~80% safe zone.
- `checkmark-mark.svg` — transparent stroke-only mark (`currentColor`) for
  future in-app/wordmark use.

## Generated outputs (in `public/`)

`favicon.svg` (arc-less), `favicon.ico` (32), `apple-touch-icon.png` (180,
full-bleed), `icon-{32,64}.png` (arc-less), `icon-{128,192,384,512,1024}.png`
(with arc), `icon-maskable-512.png`. Manifest + `<link>` references live in
`apps/web/vite.config.ts` and `apps/web/index.html`.

## Usage rules

- Keep the white mark dominant; the verdict arc is always secondary.
- Drop the arc below ~128px — it muddies at small sizes (hence the arc-less
  favicon art).
- Keep exports generated from the script, not hand-edited.
