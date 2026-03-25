# QuikSocial — Gemini API Usage & Cost Report

**Prepared for:** Engineering & Product Management
**Date:** March 2026
**Exchange Rate:** $1 USD = ₹90 INR
**Environment:** Production (Paid Tier)

---

## 1. Model Configuration

| Role | Model ID | Purpose |
|---|---|---|
| Image Generation | `gemini-3.1-flash-image-preview` | Generates all marketing images with embedded text and logo |
| Text / Caption | `gemini-2.5-flash-lite` | Generates captions, hashtags, brand analysis, slide planning, scraping intelligence |

---

## 2. Gemini Pricing (Paid Tier)

### gemini-3.1-flash-image-preview

| Token Type | Price |
|---|---|
| Input (text + image) | $0.50 per 1M tokens |
| Output — Text | $3.00 per 1M tokens |
| Output — Image (512px) | $60.00 per 1M tokens → **$0.045 per image** (747 tokens) |
| Output — Image (1024px) | $60.00 per 1M tokens → **$0.067 per image** (1,120 tokens) |
| Output — Image (2048px) | $60.00 per 1M tokens → **$0.101 per image** (1,680 tokens) |
| Output — Image (4096px) | $60.00 per 1M tokens → **$0.151 per image** (2,520 tokens) |

### gemini-2.5-flash-lite

| Token Type | Price |
|---|---|
| Input (text / image / video) | $0.10 per 1M tokens |
| Output (text + thinking) | $0.40 per 1M tokens |

---

## 3. Average Token Consumption (from Production Logs)

### 3.1 Image Generation Call — `gemini-3.1-flash-image-preview`

| Token Category | Average Count |
|---|---|
| Input (prompt text + guards) | ~3,500 – 4,200 tokens |
| Output — Text (description) | ~1,400 – 1,600 tokens |
| Output — Image | **~1,500 tokens** (production average) |

> The large input token count (~3,800 avg) is driven by the injected prompt guards:
> `SPELLING_PRIORITY_PREAMBLE` + `NEGATIVE_PROMPT` + `REALISM_STANDARD` + `TYPOGRAPHY_PRECISION` + brand payload.
>
> Image output tokens average **1,500** in production — between the 1024px (1,120 tokens) and 2048px (1,680 tokens) tiers, reflecting variable generation complexity.

### 3.2 Caption / Text Call — `gemini-2.5-flash-lite`

| Token Category | Average Count |
|---|---|
| Input (brand payload + instructions) | ~900 – 1,100 tokens |
| Output (caption + hashtags) | ~150 – 200 tokens |

### 3.3 SmartPost Planner Call — `gemini-2.5-flash-lite`

| Token Category | Average Count |
|---|---|
| Input (brand payload + slide brief instructions) | ~900 – 1,000 tokens |
| Output (JSON plan: caption + slide briefs) | ~1,400 – 1,600 tokens |

> The planner output is larger because it returns a structured JSON plan covering all slides plus the final caption in one call.

### 3.4 Smart Scrape — Agent Calls — `gemini-2.5-flash-lite`

| Agent | Input Tokens | Output Tokens | Purpose |
|---|---|---|---|
| CrawlerAgent | 2,822 | 416 | Scrapes and extracts structured content from company website |
| BrandIntelligenceAgent | 1,678 | 999 | Analyses brand identity, tone, colors, and positioning |
| WebSearchAgent | 296 | 114 | Fills gaps via web search when direct scraping is insufficient |
| **Total per scrape run** | **4,796** | **1,529** | Full brand intelligence pipeline |

---

## 4. Cost Per API Call

### Image Generation Call *(revised — 1,500 image output tokens)*

| Cost Component | Tokens | Rate | Cost (USD) | Cost (INR) |
|---|---|---|---|---|
| Input text | ~3,800 | $0.50 / 1M | $0.0019 | ₹0.17 |
| Output text | ~1,500 | $3.00 / 1M | $0.0045 | ₹0.41 |
| Output image | **1,500** | $60.00 / 1M | **$0.0900** | **₹8.10** |
| **Total per image call** | | | **$0.0964** | **₹8.68** |

### Caption Call

| Cost Component | Tokens | Rate | Cost (USD) | Cost (INR) |
|---|---|---|---|---|
| Input text | ~1,000 | $0.10 / 1M | $0.0001 | ₹0.009 |
| Output text | ~175 | $0.40 / 1M | $0.00007 | ₹0.006 |
| **Total per caption call** | | | **$0.00017** | **₹0.015** |

### SmartPost Planner Call

| Cost Component | Tokens | Rate | Cost (USD) | Cost (INR) |
|---|---|---|---|---|
| Input text | ~950 | $0.10 / 1M | $0.000095 | ₹0.009 |
| Output text | ~1,500 | $0.40 / 1M | $0.0006 | ₹0.054 |
| **Total per planner call** | | | **$0.000695** | **₹0.063** |

### Smart Scrape — Full Pipeline (3 agents)

| Agent | Input Tokens | Output Tokens | Cost (USD) | Cost (INR) |
|---|---|---|---|---|
| CrawlerAgent | 2,822 | 416 | $0.000449 | ₹0.040 |
| BrandIntelligenceAgent | 1,678 | 999 | $0.000567 | ₹0.051 |
| WebSearchAgent | 296 | 114 | $0.000075 | ₹0.007 |
| **Total — full scrape run** | **4,796** | **1,529** | **$0.001091** | **₹0.098** |

> Scraping is triggered once per brand profile, not per image. Cost is effectively a one-time setup expense per company.

---

## 5. End-to-End Cost Per Feature

### 5.1 Campaign — Single Post

| Step | Model | API Calls | Cost (USD) | Cost (INR) |
|---|---|---|---|---|
| Caption generation | gemini-2.5-flash-lite | 1 | $0.00017 | ₹0.015 |
| Image generation | gemini-3.1-flash-image-preview | 1 | $0.0964 | ₹8.68 |
| **Total — 1 post** | | **2 calls** | **$0.09657** | **₹8.69** |

**By post count (parallel execution):**

| Posts | API Calls | Cost (USD) | Cost (INR) |
|---|---|---|---|
| 1 post | 2 | $0.097 | ₹8.69 |
| 5 posts | 10 | $0.483 | ₹43.47 |
| 10 posts | 20 | $0.966 | ₹86.94 |

---

### 5.2 SmartPost — Carousel

| Step | Model | API Calls | Cost (USD) | Cost (INR) |
|---|---|---|---|---|
| Planner call (caption + all slide briefs) | gemini-2.5-flash-lite | 1 | $0.000695 | ₹0.063 |
| Image generation × slides | gemini-3.1-flash-image-preview | N | $0.0964 × N | ₹8.68 × N |

**By slide count:**

| Slides | Total API Calls | Cost (USD) | Cost (INR) |
|---|---|---|---|
| 2 slides | 3 | $0.193 | ₹17.41 |
| 3 slides | 4 | $0.290 | ₹26.09 |
| 4 slides | 5 | $0.386 | ₹34.77 |

> Caption is generated inside the planner call — **no separate caption API call** for SmartPost.

---

### 5.3 MarketingPost — Single Post

| Step | Model | API Calls | Cost (USD) | Cost (INR) |
|---|---|---|---|---|
| Caption generation | gemini-2.5-flash-lite | 1 | $0.00017 | ₹0.015 |
| Image generation | gemini-3.1-flash-image-preview | 1 | $0.0964 | ₹8.68 |
| **Total — 1 post** | | **2 calls** | **$0.09657** | **₹8.69** |

---

### 5.4 Smart Scrape — Brand Intelligence Pipeline

| Step | Model | API Calls | Cost (USD) | Cost (INR) |
|---|---|---|---|---|
| CrawlerAgent | gemini-2.5-flash-lite | 1 | $0.000449 | ₹0.040 |
| BrandIntelligenceAgent | gemini-2.5-flash-lite | 1 | $0.000567 | ₹0.051 |
| WebSearchAgent | gemini-2.5-flash-lite | 1 | $0.000075 | ₹0.007 |
| **Total — full scrape** | | **3 calls** | **$0.001091** | **₹0.098** |

> Scraping runs once per brand onboarding. Per-generation cost is **$0.00** after the first run.

---

## 6. API Call Summary

| Feature | API Calls | Breakdown |
|---|---|---|
| Campaign (1 post) | **2 calls** | 1 caption + 1 image |
| Campaign (5 posts) | **10 calls** | 5 captions + 5 images (parallel) |
| SmartPost (2-slide carousel) | **3 calls** | 1 planner + 2 images |
| SmartPost (4-slide carousel) | **5 calls** | 1 planner + 4 images |
| MarketingPost (1 post) | **2 calls** | 1 caption + 1 image |
| Smart Scrape (brand profile) | **3 calls** | 1 crawler + 1 brand intel + 1 web search |

---

## 7. Cost at Scale

| Monthly Volume | Feature | Cost (USD) | Cost (INR) |
|---|---|---|---|
| 1,000 single posts | Campaign / MarketingPost | ~$96.57 | ~₹8,691 |
| 500 carousels (4 slides) | SmartPost | ~$193.00 | ~₹17,370 |
| 5,000 single posts | Campaign / MarketingPost | ~$482.85 | ~₹43,457 |
| 1,000 brand scrapes | Smart Scrape | ~$1.09 | ~₹98 |

---

## 8. Key Observations

1. **Image output now averages 1,500 tokens** — up from the 1,024px baseline of 1,120 tokens. This reflects real production output complexity and increases the per-image cost from $0.067 to **$0.090** (+34%).

2. **Image output dominates cost** — at $0.090 per image, the image token charge accounts for **~93%** of total cost per generation ($0.090 of $0.0964).

3. **Caption cost is negligible** — at $0.00017 per call, caption generation accounts for less than **0.2%** of total spend.

4. **SmartPost is the most cost-efficient per post** — the planner call replaces N separate caption calls, and all slide briefs are generated in a single structured response.

5. **Scraping pipeline is near-zero cost** — all three scraping agents combined cost **$0.001 per run** (₹0.10). This is a one-time cost per brand profile, not a per-generation cost.

6. **Prompt guard overhead** — the injected guards (`NEGATIVE_PROMPT`, `REALISM_STANDARD`, `TYPOGRAPHY_PRECISION`, `SPELLING_PRIORITY_PREAMBLE`) add approximately 1,500–2,000 input tokens per image call. This is an intentional trade-off for image quality and brand safety.

7. **Resolution choice directly controls image cost** — upgrading from the current average (~1,500 tokens, ~$0.090) to 2048px (1,680 tokens, $0.101) adds only ~12% to image cost. Downgrading to 1024px would reduce it to $0.067, saving ~26% per image.

---

*Report based on production log data. Token counts are averages across observed calls. Actual costs may vary ±10% depending on prompt size and brand payload length.*
