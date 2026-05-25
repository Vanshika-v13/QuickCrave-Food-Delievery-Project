# Dialogflow: `order.remove - context: ongoing-order`

Apply in the [Dialogflow ES console](https://dialogflow.cloud.google.com/) for agent `972b0ef9-d1df-4ae5-af60-04b1783caa76`. **Do not fix removal in the backend.**

## Intent setup

- **Display name:** `order.remove - context: ongoing-order`
- **Webhook:** enabled for this intent
- **Static responses:** disabled / removed (webhook only)
- **Input context:** `ongoing-order`

## Parameters

| Parameter | Entity | Required |
|-----------|--------|----------|
| `food-item` | `@food-item` | **Yes** |
| `number` | `@sys.number` | **No** |

Annotate in training phrases where supported:

- `[number]` → `@sys.number`
- `[biryani]` / dish name → `@food-item`

## Training phrases (add all)

```
remove 1 biryani
remove 2 biryani
remove 3 biryani
remove 1 vegetable biryani
remove 2 vegetable biryani
remove 1 mango lassi
remove 2 mango lassi
remove 1 pizza
remove 2 pizza
remove mango lassi
remove 2 mango lassi
remove 3 vada pav
delete mango lassi
delete 2 mango lassi
```

## Expected webhook payload

For user input `remove 1 biryani`:

```json
{
  "queryResult": {
    "intent": {
      "displayName": "order.remove - context: ongoing-order"
    },
    "parameters": {
      "food-item": "Vegetable Biryani",
      "number": 1
    }
  }
}
```

**Not** `Default Fallback Intent`.

## Verify (with `ongoing-order` active)

| User says | Expected intent |
|-----------|-----------------|
| `remove 1 biryani` | `order.remove - context: ongoing-order` |
| `remove 1 mango lassi` | `order.remove - context: ongoing-order` |
| `2 biryani` | `order.add - context: ongoing-order` |

Backend uses **only** `queryResult.intent.displayName` — no `queryText` parsing.
