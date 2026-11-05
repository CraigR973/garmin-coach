import { expect, it } from 'vitest';
import { z } from 'zod';
import { dailyLoopDeliverySchema } from './schemas';

it('keeps old installed clients parsing while the current client drops liveOrigin', () => {
  const legacySchema = dailyLoopDeliverySchema.extend({ liveOrigin: z.string().nullable() });
  const delivery = {
    liveStatus: 'pushed', intervalsEventId: 'synthetic', changed: false, adjustment: null,
  };
  expect(legacySchema.safeParse(delivery).success).toBe(false);
  const compatibleResponse = { ...delivery, liveOrigin: null };
  expect(legacySchema.safeParse(compatibleResponse).success).toBe(true);
  expect(dailyLoopDeliverySchema.parse(compatibleResponse)).not.toHaveProperty('liveOrigin');
});
