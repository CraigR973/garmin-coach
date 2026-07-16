import { describe, expect, it } from 'vitest';
import { workoutTypeLabel } from './workoutCategories';

describe('workoutTypeLabel', () => {
  it('maps known bike enums to a clean label without the discipline prefix', () => {
    // Batch 129: the old subtitle showed the raw de-underscored enum ("Bike sweet
    // spot", "Bike z2") beneath an already-friendly title.
    expect(workoutTypeLabel('bike_sweet_spot')).toBe('Sweet spot');
    expect(workoutTypeLabel('bike_z2')).toBe('Zone 2');
    expect(workoutTypeLabel('bike_vo2')).toBe('VO₂');
    expect(workoutTypeLabel('bike_endurance')).toBe('Endurance');
  });

  it('maps strength and mobility enums', () => {
    expect(workoutTypeLabel('strength')).toBe('Strength');
    expect(workoutTypeLabel('flexibility')).toBe('Mobility');
    expect(workoutTypeLabel('deliberate_walk')).toBe('Walk');
  });

  it('never leaks a raw "bike_" prefix for an unmapped bike enum', () => {
    const label = workoutTypeLabel('bike_something_new');
    expect(label.toLowerCase()).not.toContain('bike');
    expect(label).toBe('Something new');
  });

  it('falls back gracefully for empty or unknown input', () => {
    expect(workoutTypeLabel(null)).toBe('Session');
    expect(workoutTypeLabel('')).toBe('Session');
    expect(workoutTypeLabel('cross_training')).toBe('Cross training');
  });
});
