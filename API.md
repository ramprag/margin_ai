# Margin AI - REST API Reference

Margin AI is a 100% transparent gateway. This means it implements the exact same REST API standard as OpenAI. Any library designed to interact with OpenAI can automatically use Margin AI by changing the Base URL.

## Base URL
Default local deployment: `http://localhost:8000/v1`

---

## 1. Chat Completions Gateway Endpoint

`POST /v1/chat/completions`

**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <your-margin-key>`

**Request Body (JSON):**
Matches the OpenAI API spec exactly.
*   `model` (string, required): Either set a hardcoded provider model (e.g. `gpt-4o`) or set to `"auto"` to allow Margin AI to dynamically route it to the cheapest capable model.
*   `messages` (array): Array of message objects (role/content).
*   `temperature` (float): Standard inference parameter.
*   `stream` (boolean): Optionally stream the response.

**Response (JSON):**
Matches the OpenAI spec, but Margin AI injects extra metadata into the `model_extra` (if supported) or under the root of the response for telemetry.

```json
{
  "id": "chatcmpl-123",
  "object": "chat.completion",
  "created": 1677652288,
  "model": "llama-3.1-8b-instant",
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "Hello! Margin AI routed this for you."
    },
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 9,
    "completion_tokens": 12,
    "total_tokens": 21
  },
  "margin_ai_optimized": true,
  "strategy": "efficiency_optimized",
  "estimated_cost": 0.000004
}
```

---

## 2. Analytics / Live Metrics

`GET /api/stats`

**Description:**
Returns real-time ROI and Savings metrics for the Margin AI CFO Dashboard.

**Response (JSON):**
```json
{
  "direct": {
    "queries": 1500,
    "tokens": 402000,
    "cost": 6.42
  },
  "margin": {
    "queries": 1500,
    "tokens": 402000,
    "cost": 0.32,
    "saved": 6.10,
    "cache_hits": 412
  }
}
```

---

## 3. PII Filtering (Internal Mechanism)

Margin AI does not currently expose a standalone PII checking endpoint. PII redaction happens asynchronously inside the core layer before the payload reaches the provider.

When a payload contains SSNs or CCs, the outbound `message[content]` is automatically swapped with `[REDACTED]` tokens to maintain format without exposing sensitive data to OpenAI/Anthropic.
