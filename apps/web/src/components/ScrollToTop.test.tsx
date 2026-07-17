import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ScrollToTop } from './ScrollToTop';

function Nav() {
  const navigate = useNavigate();
  return (
    <>
      <button onClick={() => navigate('/next')}>fwd</button>
      <button onClick={() => navigate(-1)}>back</button>
    </>
  );
}

function Harness() {
  return (
    <MemoryRouter initialEntries={['/']}>
      <ScrollToTop />
      <Nav />
      <Routes>
        <Route path="/" element={<p>home</p>} />
        <Route path="/next" element={<p>next</p>} />
      </Routes>
    </MemoryRouter>
  );
}

// Batch 137 — reset scroll on a forward navigation, but not on back (POP), so
// the browser's restored position pairs with the backward page transition.
describe('ScrollToTop', () => {
  afterEach(() => vi.restoreAllMocks());

  it('scrolls to top on PUSH and leaves POP alone', async () => {
    const scrollSpy = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
    render(<Harness />);

    // Initial render is a POP — no scroll reset.
    expect(scrollSpy).not.toHaveBeenCalled();

    await userEvent.click(screen.getByText('fwd'));
    expect(scrollSpy).toHaveBeenCalledWith(0, 0);

    scrollSpy.mockClear();
    await userEvent.click(screen.getByText('back'));
    expect(scrollSpy).not.toHaveBeenCalled();
  });
});
