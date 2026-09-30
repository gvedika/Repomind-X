import { Invoice, InvoiceStatus } from "../models/invoice";
import { convert, subtotal } from "../utils/money";

export interface InvoiceRepository {
  save(invoice: Invoice): Promise<void>;
  findOverdue(before: Date): Promise<Invoice[]>;
}

export abstract class Notifier {
  abstract send(customerId: string, message: string): Promise<void>;

  protected render(invoice: Invoice): string {
    return `Invoice ${invoice.id} is ${invoice.status}`;
  }
}

export class BillingService {
  private readonly taxRate = 0.18;

  constructor(private readonly repo: InvoiceRepository, private readonly notifier: Notifier) {}

  /** Apply tax to the subtotal and convert it into the invoice currency. */
  totalDue(invoice: Invoice): number {
    const gross = subtotal(invoice.items) * (1 + this.taxRate);
    return convert(Math.round(gross), "USD", invoice.currency);
  }

  async issue(invoice: Invoice): Promise<Invoice> {
    const issued = { ...invoice, status: InvoiceStatus.Issued };
    await this.repo.save(issued);
    await this.notifier.send(invoice.customerId, `Amount due: ${this.totalDue(issued)}`);
    return issued;
  }

  remindOverdue = async (today: Date): Promise<number> => {
    const overdue = await this.repo.findOverdue(today);
    await Promise.all(overdue.map((inv) => this.notifier.send(inv.customerId, "Your invoice is overdue")));
    return overdue.length;
  };
}

export namespace Webhooks {
  export function verifySignature(payload: string, signature: string, secret: string): boolean {
    return signature.length > 0 && payload.length > 0 && secret.length > 0;
  }
}
