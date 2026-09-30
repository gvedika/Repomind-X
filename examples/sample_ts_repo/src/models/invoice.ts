/** A billable line on an invoice. */
export interface LineItem {
  sku: string;
  quantity: number;
  unitPriceCents: number;
}

export type Currency = "USD" | "EUR" | "INR";

export enum InvoiceStatus {
  Draft = "draft",
  Issued = "issued",
  Paid = "paid",
}

export interface Invoice {
  id: string;
  customerId: string;
  currency: Currency;
  items: LineItem[];
  status: InvoiceStatus;
}
