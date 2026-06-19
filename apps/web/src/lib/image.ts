import { apiFetch } from './api';

// Avatar image constraints — shared by the Settings and Signup avatar pickers.
export const ALLOWED_AVATAR_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'];
export const MAX_AVATAR_BYTES = 5 * 1024 * 1024; // 5 MB (matches backend + bucket limit)
export const AVATAR_TARGET_SIZE = 1024; // resize to at most 1024×1024 px

/** Resize a file to a centred square ≤1024px JPEG blob via OffscreenCanvas / canvas. */
export async function resizeAvatar(file: File): Promise<Blob> {
  const bitmap = await createImageBitmap(file);
  const side = Math.min(bitmap.width, bitmap.height, AVATAR_TARGET_SIZE);

  // Crop to a centred square first, then scale.
  const srcSize = Math.min(bitmap.width, bitmap.height);
  const srcX = (bitmap.width - srcSize) / 2;
  const srcY = (bitmap.height - srcSize) / 2;

  let canvas: OffscreenCanvas | HTMLCanvasElement;
  let ctx: OffscreenCanvasRenderingContext2D | CanvasRenderingContext2D | null;
  if (typeof OffscreenCanvas !== 'undefined') {
    canvas = new OffscreenCanvas(side, side);
    ctx = canvas.getContext('2d') as OffscreenCanvasRenderingContext2D | null;
  } else {
    canvas = document.createElement('canvas');
    canvas.width = side;
    canvas.height = side;
    ctx = (canvas as HTMLCanvasElement).getContext('2d');
  }
  if (!ctx) throw new Error('Canvas context unavailable');
  ctx.drawImage(bitmap, srcX, srcY, srcSize, srcSize, 0, 0, side, side);

  if ('convertToBlob' in canvas) {
    return (canvas as OffscreenCanvas).convertToBlob({ type: 'image/jpeg', quality: 0.88 });
  }
  return new Promise<Blob>((resolve, reject) =>
    (canvas as HTMLCanvasElement).toBlob(
      (b) => (b ? resolve(b) : reject(new Error('toBlob failed'))),
      'image/jpeg',
      0.88,
    ),
  );
}

/**
 * Upload a resized avatar blob to the backend, which stores it in Supabase
 * Storage using the service-role key (bypassing Storage RLS — the app uses
 * custom name+PIN JWT auth, not Supabase Auth, so the browser has no
 * `auth.uid()` to satisfy the bucket's owner-insert policy). Returns the new
 * public avatar URL persisted on the profile.
 */
export async function uploadAvatarImage(blob: Blob): Promise<string | null> {
  const res = await apiFetch<{ avatar_url: string | null }>('/api/v1/auth/me/avatar', {
    method: 'POST',
    body: blob,
    headers: { 'Content-Type': 'image/jpeg' },
  });
  return res.avatar_url;
}
