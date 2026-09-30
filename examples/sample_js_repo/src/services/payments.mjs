const GATEWAY_URL = process.env.PAYMENT_GATEWAY_URL ?? "https://payments.invalid";

export async function chargeCard(card, amountCents) {
  const response = await fetch(`${GATEWAY_URL}/charges`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ card, amount: amountCents }),
  });
  if (!response.ok) throw new Error(`charge failed: ${response.status}`);
  return response.json();
}

export function refund(chargeId) {
  return fetch(`${GATEWAY_URL}/charges/${chargeId}/refund`, { method: "POST" });
}
