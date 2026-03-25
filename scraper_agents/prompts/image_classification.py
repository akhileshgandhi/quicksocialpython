"""ProductAgent prompt — classify candidate product images."""

IMAGE_CLASSIFICATION_PROMPT = """\
You are an image classifier for a product catalog scraper. For each image URL below, classify its type based on the URL pattern, filename, and context.

Product name context: {product_name}
Company: {company_name}

Image candidates:
{image_list}

For each image, return a JSON array:
[
  {{"url": "<image url>", "classification": "<one of: product_photo, banner, category_thumbnail, logo, icon, lifestyle, unknown>", "confidence": <0.0-1.0>}}
]

Classification rules:
- "product_photo": An actual photo of the specific product (packshot, product on white bg, product in use)
- "banner": Wide promotional banner, hero image, slider image (usually aspect ratio > 3:1)
- "category_thumbnail": Generic category/section icon or illustration (not a specific product)
- "logo": Brand logo or trademark
- "icon": Small UI icon, feature icon, checkmark, arrow
- "lifestyle": Lifestyle/mood photography not showing a specific product
- "unknown": Cannot determine

URL signals:
- "banner", "slider", "hero", "promo" in path → likely banner
- "icon", "sprite", "arrow", "check" in path → likely icon
- "thumb", "category", "collection" in path → likely category_thumbnail
- "logo", "brand" in path → likely logo
- Product slug in filename → likely product_photo

Return ONLY the JSON array, no markdown fences.
"""
