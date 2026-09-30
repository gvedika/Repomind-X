import React from "react";
import type { Invoice } from "../models/invoice";
import { formatMoney, subtotal } from "../utils/money";

type Props = { invoices: Invoice[]; onSelect: (id: string) => void };

export function InvoiceTable({ invoices, onSelect }: Props) {
  return (
    <table>
      <tbody>
        {invoices.map((inv) => (
          <tr key={inv.id} onClick={() => onSelect(inv.id)}>
            <td>{inv.id}</td>
            <td>{formatMoney(subtotal(inv.items), inv.currency)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
