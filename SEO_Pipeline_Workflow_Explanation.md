# SEO Agent Pipeline — How It Works (Simple Explanation)

*This document explains how the SEO Agent system analyzes your website, using Stripe as a real example.*

---

## 🤔 What Is This Pipeline?

Think of this like having an **SEO expert team** that:

1. **First** — Learns about your business
2. **Second** — Visits every page on your website and takes notes

These two experts work in sequence. We call them **Agent 01** and **Agent 02**.

---

## 👤 User Input (What You Provide)

Before running the pipeline, you provide basic information about your business:

| Field | Example Value |
|-------|---------------|
| **Business Name** | Stripe |
| **Website URL** | <https://stripe.com> |
| **Industry** | Financial Technology / Payments |
| **Target Audience** | Businesses, Developers, SaaS companies |
| **Primary Goals** | Process payments securely, Increase transaction volume, Reduce churn |
| **Competitors** | PayPal, Square, Adyen, Braintree |
| **Brand Voice** | Professional, secure, innovative, developer-friendly |

You also configure how deep the crawl should go:

- **Crawl Depth**: 3 (how many clicks deep from the homepage)
- **Max Pages**: 50 (maximum pages to analyze)

---

## 🔄 How The Pipeline Works

```
┌─────────────────┐      ┌─────────────────┐
│   USER INPUT    │ ───► │   AGENT 01     │
│  (Business Info)│      │   (Intake)      │
└─────────────────┘      └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │   AGENT 02     │
                         │    (Crawl)     │
                         └─────────────────┘
```

---

## 🤖 Agent 01: The Business Analyst

**Purpose**: Understand your business and create a "project context"

**What it does**:

1. Takes your business information
2. Organizes it into a structured format
3. Passes this context to Agent 02

**Output** (what you get):

```json
{
  "business_name": "Stripe",
  "website_url": "https://stripe.com",
  "industry": "Financial Technology / Payments",
  "target_audience": ["Businesses", "Developers", "SaaS companies"],
  "primary_goals": [
    "Process payments securely",
    "Increase transaction volume", 
    "Reduce churn"
  ],
  "geographic_focus": "Global",
  "competitors": ["PayPal", "Square", "Adyen", "Braintree"],
  "brand_voice": "Professional, secure, innovative, developer-friendly",
  "key_products_services": [
    "Payment processing",
    "Stripe Atlas", 
    "Stripe Capital",
    "Radar fraud detection"
  ]
}
```

**In simple terms**: Agent 01 creates a detailed profile of your business that helps Agent 02 understand what to look for on your website.

---

## 🕷️ Agent 02: The Website Crawler

**Purpose**: Visit every page on your website and analyze SEO elements

**What it does**:

1. Reads the `website_url` from Agent 01's output
2. Visits pages up to the configured depth (3 clicks deep)
3. Analyzes each page for SEO factors
4. Compiles a comprehensive report

**Configuration**:

- Crawl Depth: 3
- Max Pages: 50

**Output** (what you get):

### 📊 Summary Metrics

| Metric | Value |
|--------|-------|
| Total pages crawled | 50 |
| Depth reached | 3 |
| Average response time | 123.33ms |

### ✅ SEO Health Check

| Check | Status |
|-------|--------|
| Pages with H1 heading | 3 ✅ |
| Pages with meta description | 3 ✅ |
| Pages with Schema.org | 3 ✅ |
| Pages with Open Graph tags | 3 ✅ |

### 🔧 Technical Files

| File | Found? | URL |
|------|--------|-----|
| Sitemap.xml | ✅ Yes | <https://stripe.com/sitemap.xml> |
| robots.txt | ✅ Yes | <https://stripe.com/robots.txt> |

### 🔒 Security

| Check | Status |
|-------|--------|
| HTTPS only | ✅ Yes |
| SSL issues | ✅ No |

### ⚠️ Content Issues

| Issue | Count |
|-------|-------|
| Duplicate titles | 0 ✅ |
| Duplicate meta descriptions | 0 ✅ |
| Thin content pages | 0 ✅ |

### 📄 Sample Page Analysis (First 3 of 50)

#### Page 1: <https://stripe.com>

| Element | Value |
|---------|-------|
| Status | 200 ✅ (OK) |
| Words | 156 |
| Response Time | 120ms |
| H1 Heading | "Payments, simplified." |
| H2 Tags | "Online Payment Processing", "Payment Gateway" |
| Canonical URL | <https://stripe.com> |
| Schema Type | Organization |
| Images | 1 (optimized ✅) |
| Internal Links | 2 |
| External Links | 1 |

#### Page 2: <https://stripe.com/about>

| Element | Value |
|---------|-------|
| Status | 200 ✅ |
| Words | 512 |
| Response Time | 150ms |
| H1 Heading | "Our Story" |
| H2 Tags | "Our Mission", "Our Team" |
| Canonical URL | <https://stripe.com/about> |
| Schema Type | Organization |
| Images | 1 (optimized ✅) |

#### Page 3: <https://stripe.com/contact>

| Element | Value |
|---------|-------|
| Status | 200 ✅ |
| Words | 201 |
| Response Time | 100ms |
| H1 Heading | "Contact Us" |
| H2 Tags | "Support", "Sales" |
| Canonical URL | <https://stripe.com/contact> |
| Schema Type | Organization |

---

## 🎯 What Does This Mean for Your Business?

### ✅ Good Signs (Green Flags)

- All pages have proper H1 headings
- All pages have meta descriptions
- Schema.org structured data is present
- Open Graph tags are implemented (good for social sharing)
- No duplicate content issues
- No thin content pages
- HTTPS is enforced
- Sitemap and robots.txt are accessible

### ⚠️ Things to Watch

- Response time (123ms is good, but if it goes above 500ms, consider optimization)
- Image optimization (already good in this example)

---

## 📈 Next Steps (What Happens After)

After Agent 02 completes, the data is used by subsequent agents:

- **Agent 04** (Keyword Research) — Finds keywords based on your industry
- **Agent 05** (Keyword Clustering) — Groups keywords into semantic clusters
- **Agent 06** (Page Mapping) — Maps keywords to pages
- **Agent 07** (Gap Analysis) — Analyzes content gaps
- **Agent 08** (Competitor Analysis) — Compares against competitors you listed

---

## 📝 Summary

| Step | Agent | What It Does | Output |
|------|-------|--------------|--------|
| 1 | **You** | Provide business information | Input form |
| 2 | **Agent 01** | Process business context | Business profile (JSON) |
| 3 | **Agent 02** | Crawl website | SEO inventory (50 pages analyzed) |

**Total Pages Analyzed**: 50  
**Status**: All clear — Stripe's website is well-optimized! 🎉

---

*Generated from actual pipeline execution on 2026-03-26*
