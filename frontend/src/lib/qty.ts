/**
 * Quantity conversion utilities.
 *
 * All quantities are stored as integers ×100 in the DB and API.
 * - 10000 → "100.00" (toDisplay)
 * - 100.5 → 10050   (toStore)
 */

export const toDisplay = (n: number): string => (n / 100).toFixed(2);

export const toStore = (n: number): number => Math.round(n * 100);
