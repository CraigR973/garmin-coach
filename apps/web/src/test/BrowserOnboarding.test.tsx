import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BrowserOnboarding } from '@/components/BrowserOnboarding';

vi.mock('@/hooks/useInstallPrompt', () => ({
  useInstallPrompt: () => ({
    isIos: false,
    isIosSafari: false,
    canInstall: false,
    prompt: vi.fn(),
  }),
}));

describe('BrowserOnboarding', () => {
  it('tells new users to create an account before joining by code', () => {
    render(<BrowserOnboarding />);

    expect(screen.getAllByText(/If you are new, tap/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Create account/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Leagues → Join by code/i).length).toBeGreaterThan(0);
  });
});
