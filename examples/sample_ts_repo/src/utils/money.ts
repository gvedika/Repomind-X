import type { Currency, LineItem } from "../models/invoice.js";

const RATES: Record<Currency, number> = { USD: 1, EUR: 0.92, INR: 83.1 };

/** Sum quantity times unit price for every line, in cents. */
export function subtotal(items: LineItem[]): number {
  return items.reduce((sum, item) => sum + item.quantity * item.unitPriceCents, 0);
}

export function convert(cents: number, from: Currency, to: Currency): number {
  return Math.round((cents / RATES[from]) * RATES[to]);
}

export function formatMoney(cents: number, currency: Currency): string;
export function formatMoney(cents: number, currency: Currency, locale?: string): string {
  return new Intl.NumberFormat(locale ?? "en-US", { style: "currency", currency }).format(cents / 100);
}
