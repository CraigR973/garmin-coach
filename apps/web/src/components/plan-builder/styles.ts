import { controlFieldClassName } from '@/components/ui/input';
import { cn } from '@/lib/utils';

/** The plan builder's native selects: the shared control field, sized for a thumb. */
export const selectClassName = cn(controlFieldClassName, 'min-h-11 px-3 py-2 text-base sm:text-sm');
