import { Component, type ErrorInfo, type ReactNode } from 'react';
import * as Sentry from '@sentry/react';
import { Button } from './ui/button';

interface Props {
  children: ReactNode;
  fallback?: (error: Error, reset: () => void) => ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    Sentry.captureException(error, { extra: { componentStack: info.componentStack } });
  }

  reset = (): void => {
    this.setState({ error: null });
  };

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    if (this.props.fallback) return this.props.fallback(error, this.reset);

    return (
      <div className="flex flex-col items-center justify-center gap-4 p-8 text-center">
        <p className="text-text-primary font-semibold">Something went wrong</p>
        <p className="text-text-secondary text-sm">
          An unexpected error occurred. Try reloading the page.
        </p>
        <div className="flex gap-2">
          <Button variant="outline" onClick={this.reset}>
            Try again
          </Button>
          <Button onClick={() => window.location.reload()}>Reload</Button>
        </div>
      </div>
    );
  }
}
