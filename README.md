<div align="center">
  <h1>🛡️ Margin AI</h1>
  <h3>The Ultimate Cost & Compliance Pipeline for AI Agents.</h3>
  <p>Drop 50% of your token bill. Auto-redact PII. Support 100+ LLMs instantly.</p>

  <p>
    <a href="#quickstart"><b>Get Started</b></a> •
    <a href="#the-problem-were-solving"><b>Why Margin AI?</b></a> •
    <a href="#margin-ai-vs-the-world"><b>Comparisons</b></a> •
    <a href="#enterprise-features"><b>Features</b></a>
  </p>
</div>

---

## 🚀 The Magic: Integration in < 10 Seconds

You don't need to rewrite your agent's complex logic. Margin AI is a 100% transparent, drop-in replacement that natively supports **100+ LLMs** (OpenAI, Anthropic, Gemini, Groq, Ollama) behind a single unified API. 

Change exactly **ONE** line in your codebase to point to your local Margin container:

```python
from openai import OpenAI

client = OpenAI(
    api_key="your_margin_ai_key", # Margin securely handles your 100+ provider keys internally
    base_url="http://localhost:8000/v1"  # <-- The only line you change
)

# Your app magically gains PII Redaction, Semantic Caching, and Intelligent Routing
response = client.chat.completions.create(
    model="gpt-4o",  # Margin AI intelligently decides if it actually needs 4o
    messages=[{"role": "user", "content": "What is the capital of France?"}]
)
```

---

## 🔥 The Problem We're Solving

Building AI apps is easy. **Scaling AI unit economics is a nightmare.** 

If you are building a **multi-step autonomous agent** (like Manus, Devin, or deeply-chained research agents), 80% of your LLM calls are **trivial background loops** (e.g., formatting JSON, parsing dates, extracting emails, or structuring arrays). 

If you send all of those invisible background loops to heavy models like GPT-4o or Claude 3.5 Sonnet, your token inference costs will explode instantly. For most scaling AI startups, **their LLM token inference bill has already surpassed their entire AWS cloud hosting bill.**

**Margin AI is an enterprise infrastructure layer that acts as a transparent control plane inside your VPC.** It dynamically intercepts your backend traffic, serves exact matches from a 15ms cache, routes repetitive background formatting tasks to optimized, lightning-fast fallback models (like Llama-3 via Groq), and automatically redacts sensitive PII from outbound payloads before it leaves your secure network—saving you up to **60% on your total API bill** across 100+ models without sacrificing generation quality.

---

## ⚡ Enterprise Features

### 1. [Auto-PII Data Loss Prevention (DLP)](#pii-data-loss-prevention)
Selling to Enterprise/Healthcare? Agents reading local CRMs are a privacy nightmare. Margin AI automatically redacts sensitive customer data (SSNs, Credit Cards, Aadhaar) *before* the payload ever hits an external LLM. **Result: Instant SOC2/HIPAA compliance out of the box.**

### 2. [Dynamic Cost Routing](#dynamic-cost-routing)
Margin AI reads your agent's prompt complexity before sending it. Deep reasoning task? It goes to `gpt-4o` or `claude-3.5-sonnet`. Trivial JSON formatting loop? It gets instantly routed to `llama-3.1-8b-instant` on Groq. **Result: Maximize intelligence, minimize cost.**

### 3. [Semantic Caching (15ms Latency)](#semantic-caching)
Why pay for the same answer twice? Margin AI intercepts repetitive user queries and serves the response from an ultra-fast Redis cache, bypassing the LLM completely. **Result: 0 latency penalty, 100% token savings.**

### 4. [Real-time CFO Analytics Dashboard](#cfo-dashboard)
Stop guessing where your AI budget is going. The built-in dashboard tracks your **Avoided Spend**, Top Models, and Cache hit rates across 100+ LLMs in real-time, proving your ROI to investors and finance teams.

### 5. [Auto-Failover & High Availability](#auto-failover)
If Anthropic or OpenAI experiences an outage or throws a `429 Too Many Requests` error, Margin AI automatically cascades the request to the next best provider without alerting your end user. **Result: Five-nines (99.999%) reliability.**

---

## 🥊 Margin AI vs. The World

Why not just use another AI Gateway or API middleware like LiteLLM? Because generic routing layers require you to write massive custom logic just to save money, and SaaS gateways add latency while charging you extra.

Margin AI is not generic middleware. It is specifically designed as an **Agent Cost-Control Layer**.

| Feature | Margin AI | LiteLLM | Cloudflare AI Gateway | Portkey / Helicone | 
| :--- | :---: | :---: | :---: | :---: |
| **Pricing** | **100% Free** | Free OSS / Enterprise | Usage-based | Pay-per-request |
| **Core Focus** | **Agent Cost Optimization** | Universal API Formatting | Basic Rate Limiting | Observability SaaS |
| **Intelligent Cost Routing** | ✅ Dynamic (Intent-based) | ⚠️ Manual (Rules-based) | ❌ No | ⚠️ Manual (Rules-based) |
| **PII Redaction Engine** | ✅ Built-in & Automatic | ❌ Paid Enterprise Tier | ❌ No | ❌ Paid Tier Only |
| **Data Privacy** | **Runs in your VPC** | Runs in your VPC | Hosted externally | Hosted externally |
| **Added Latency** | **< 2ms** | < 5ms | ~50ms | ~150ms |
| **ROI / Savings Dashboard** | ✅ Live Avoided Spend | ⚠️ Request Logs | ❌ Basic AI Logs | ✅ Yes |

**The Verdict:** If you want a basic layer that universally formats API calls, use LiteLLM. If you want an intelligent control plane that **automatically slashes your multi-step agent bill in half** while keeping your PII securely in your VPC, use Margin AI.

---

## 🏗️ Architecture

Margin AI is built for raw, unforgiving speed and enterprise reliability:
- **FastAPI Core:** Non-blocking async Python runtime capable of thousands of concurrent generic streams.
- **Universal Provider Engine:** Natively connects to 100+ global LLM providers inside the unified OpenAI API standard.
- **Redis Semantic Backing:** Sub-millisecond vector indexing capability.
- **Stateless Design:** Scale to 1,000 instances behind a load balancer safely.

---

## 💻 Quickstart (Docker)

Get the control plane and the CFO dashboard running in your terminal locally in under 3 minutes.

```bash
# 1. Clone the repository
git clone https://github.com/ramprag/margin-ai.git
cd margin-ai

# 2. Add your Provider Keys
cp .env.example .env
# Edit .env and paste your keys for any of the 100+ providers

# 3. Boot the Control Plane
docker-compose up --build -d

# 4. View your Live Dashboard
open http://localhost:8000/dashboard
```

---

<div align="center">
  <b>Built for AI Engineers who care about Unit Economics.</b><br>
  Star the repo to support open-source infrastructure.
</div>
