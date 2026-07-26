import { Brand } from '@/components/Brand';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { brand } from '@/theme/tokens';

export function AccessPage() {
  return (
    <div className="min-h-screen bg-bg flex flex-col items-center justify-center p-4 pt-safe pb-safe">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center">
          <Brand variant="splash" size={96} />
          <p className="mt-4 font-sans text-lg font-semibold text-text-primary">{brand.tagline}</p>
          <p className="mt-1 font-sans text-sm italic text-text-secondary">{brand.taglineSub}</p>
        </div>

        <Card className="border-border-strong bg-surface shadow-md">
          <CardHeader>
            <CardTitle className="text-center text-text-primary">Set up this device</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-sans text-sm text-text-secondary text-center">
              Ask Craig for a one-time activation link and open it on this device. There is no PIN
              or password to remember.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
