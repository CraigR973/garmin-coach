export function OfflinePage() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 text-center px-4">
      <div className="text-5xl" aria-hidden>
        📡
      </div>
      <h1 className="text-2xl sm:text-3xl font-semibold text-text-primary tracking-tight">You&apos;re offline</h1>
      <p className="text-text-secondary font-sans max-w-sm">
        No internet connection detected. Check your connection and try again.
      </p>
      <button
        onClick={() => window.location.reload()}
        className="mt-2 inline-flex items-center justify-center h-11 px-5 rounded-md bg-primary text-on-primary text-sm font-semibold font-sans hover:bg-primary-dark transition-colors press-down focus-visible:outline-none focus-visible:shadow-glow"
      >
        Retry
      </button>
    </div>
  );
}
