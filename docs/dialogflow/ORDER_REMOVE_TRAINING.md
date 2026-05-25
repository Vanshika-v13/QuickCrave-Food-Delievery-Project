# Dialogflow: `order.remove` training phrase fix

Apply in the [Dialogflow ES console](https://dialogflow.cloud.google.com/) for this agent. **Do not rename intents or change contexts.**

## `order.remove` — keep only explicit removal phrases

**Include (examples):**

- `remove @food-item`
- `delete @food-item`
- `cancel @food-item`
- `remove 2 pizzas`
- `delete vada pav`
- `cancel biryani`

**Remove from training (these cause false matches):**

- Standalone food names: `vada pav`, `pizza`, `biryani`
- Entity-only phrases: `@food-item` alone
- Any phrase that is only a dish name with no `remove` / `delete` / `cancel`

## `order.remove` fulfillment

- Use **webhook** fulfillment for `order.remove - context: ongoing-order`
- Remove static responses like `Removed @food-item` from the intent (the webhook returns `Removed …` only when keywords are present)

## Webhook safety (already in `main.py`)

Even if Dialogflow still mis-matches, the webhook:

1. Re-routes food-only queries to `order.add`
2. Blocks `remove_from_order` unless the user text contains `remove`, `delete`, or `cancel`
3. Asks for quantity when a dish is named without a number

No intent renames required.
