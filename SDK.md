# Margin AI - SDK Integration Guide

Margin AI is API-compatible with OpenAI. You do not need to install a `margin-ai` library. You simply use the official OpenAI Python or Node SDKs, or LangChain. 

## 1. Python (Official OpenAI SDK)

```bash
pip install openai
```

```python
from openai import OpenAI

# 1-Line Drop-In Replacement
client = OpenAI(
    api_key="margin-gateway-key", # Or 'sk-123', Margin ignores this locally
    base_url="http://localhost:8000/v1" # Point to the Margin AI Gateway
)

response = client.chat.completions.create(
    model="auto", # Use 'auto' to let Margin AI intelligently route to Groq/Gemini/OpenAI
    messages=[{"role": "user", "content": "Hello!"}],
    stream=False
)

print(response.choices[0].message.content)

# Margin AI automatically injects cost analytics:
print(f"Cost: ${response.model_extra.get('estimated_cost')}")
print(f"Latency: {response.model_extra.get('latency_ms')} ms")
print(f"Cached Result: {response.model_extra.get('cached')}")
```

## 2. Node.js (Official OpenAI SDK)

```bash
npm install openai
```

```javascript
import OpenAI from "openai";

// 1-Line Drop-In Replacement
const openai = new OpenAI({
  apiKey: "margin-gateway-key", 
  baseURL: "http://localhost:8000/v1" // Point to the Margin AI Gateway
});

async function main() {
  const completion = await openai.chat.completions.create({
    messages: [{ role: "user", content: "Hello Margin AI!" }],
    model: "auto",
  });

  console.log(completion.choices[0].message.content);
  // View telemetry injected by Margin AI
  console.log(completion);
}
main();
```

## 3. LangChain (Python)

```bash
pip install langchain-openai
```

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    api_key="margin-gateway-key",
    base_url="http://localhost:8000/v1",
    model="auto" # Margin AI intelligently routes 
)

result = llm.invoke("What is the capital of France?")
print(result.content)
```

## 4. Setting Hardcoded Fallbacks

If you do NOT want Margin AI to dynamically route complex vs simple tasks to Llama vs GPT-4, you can skip `model="auto"` and explicitly pass the model you want. Margin AI will still provide PII Redaction, Caching, and Analytics.

```python
response = client.chat.completions.create(
    model="claude-3-5-sonnet", # Margin AI translates Anthropic formats internally!
    messages=[{"role": "user", "content": "Hello!"}]
)
```
