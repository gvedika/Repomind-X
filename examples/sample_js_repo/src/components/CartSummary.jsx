import React from "react";

function formatCurrency(cents) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

export default function CartSummary({ items }) {
  const total = items.reduce((sum, item) => sum + item.price * item.quantity, 0);
  return (
    <section className="cart">
      <h2>{items.length} items</h2>
      <p>Total: {formatCurrency(total)}</p>
    </section>
  );
}
