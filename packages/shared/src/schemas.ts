import { z } from 'zod';

export const PredictionSchema = z.object({
  matchId: z.string().uuid(),
  homeScore: z.number().int().min(0),
  awayScore: z.number().int().min(0),
});

export type Prediction = z.infer<typeof PredictionSchema>;
