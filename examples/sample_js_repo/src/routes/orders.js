const express = require("express");
const { withRetry } = require("../utils/retry.cjs");
const { chargeCard } = require("../services/payments.mjs");

const router = express.Router();

function validateOrder(body) {
  const errors = [];
  if (!Array.isArray(body.items) || body.items.length === 0) errors.push("items required");
  if (typeof body.total !== "number" || body.total <= 0) errors.push("total must be positive");
  return errors;
}

router.post("/orders", async (req, res) => {
  const errors = validateOrder(req.body);
  if (errors.length) return res.status(400).json({ errors });
  const receipt = await withRetry(() => chargeCard(req.body.card, req.body.total));
  res.status(201).json({ id: receipt.id });
});

router.get("/orders/:id", (req, res) => {
  res.json({ id: req.params.id });
});

module.exports = router;
