import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

// An inline script in index.html runs only if vercel.json's Content-Security-Policy
// lists its exact sha256. Batch 52 changed one colour in the pre-mount theme script
// on 4 Jul without updating the hash, so every browser blocked it until 26 Oct.
// Vite copies the script into the build byte for byte, so the source hash is the
// one that ships.
const indexHtml = readFileSync(resolve(__dirname, '../../index.html'), 'utf8');
const vercelConfig = JSON.parse(
  readFileSync(resolve(__dirname, '../../../../vercel.json'), 'utf8'),
) as { headers: { headers: { key: string; value: string }[] }[] };

function scriptSrc(): string {
  const policy = vercelConfig.headers
    .flatMap((rule) => rule.headers)
    .find((header) => header.key === 'Content-Security-Policy');
  const directive = policy?.value
    .split(';')
    .map((part) => part.trim())
    .find((part) => part.startsWith('script-src '));
  if (!directive) throw new Error('vercel.json has no script-src directive');
  return directive;
}

function inlineScriptHashes(html: string): string[] {
  return [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)].map(
    (match) => `'sha256-${createHash('sha256').update(match[1], 'utf8').digest('base64')}'`,
  );
}

describe('Content-Security-Policy', () => {
  it('allows every inline script in index.html by its exact hash', () => {
    const hashes = inlineScriptHashes(indexHtml);
    expect(hashes.length).toBeGreaterThan(0);
    for (const hash of hashes) expect(scriptSrc()).toContain(hash);
  });

  it('lists no hash for a script that no longer exists', () => {
    const listed = scriptSrc().match(/'sha256-[A-Za-z0-9+/=]+'/g) ?? [];
    expect(listed.sort()).toEqual(inlineScriptHashes(indexHtml).sort());
  });
});
