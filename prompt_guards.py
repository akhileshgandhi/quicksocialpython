# ═══════════════════════════════════════════════════════════════════════════════
# SPELLING PRIORITY PREAMBLE
# Injected at the VERY TOP of every image generation prompt — before anything else
# Purpose: Establish text quality as the absolute first constraint the model reads
# ═══════════════════════════════════════════════════════════════════════════════

SPELLING_PRIORITY_PREAMBLE = """
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
MANDATORY — READ AND COMMIT BEFORE GENERATING ANYTHING
▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬

TEXT ON IMAGE — THREE NON-NEGOTIABLE RULES:

1. SPELLING    — Every single word on the image must be spelled in perfect standard English. Zero errors, zero exceptions. This is the single hard constraint — it overrides everything else.
2. RELEVANCE   — Every word must be earned from the brand payload below: company name, industry, tagline, campaign goal, or values. No generic filler.
3. BRAND-CONSISTENCY - Do not deviate from the provided payload. Only use provided logo and details of provided product and services. Do not use logo/signs of other brands like Nike, Adidas, Jordan, Puma, Converse, New Balance, Reebok, Under Armour, or any other real brand. This is a hard creative and legal requirement.

Beyond these three rules: use your full creative intelligence. Write powerful, brand-authentic copy that matches the brand voice in the payload.

▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬
"""

# ═══════════════════════════════════════════════════════════════════════════════
# NEGATIVE PROMPT (AI ARTIFACT AVOIDANCE)
# Injected into all IMAGE GENERATION prompts
# Purpose: Eliminate common AI-generation failure patterns
# ═══════════════════════════════════════════════════════════════════════════════

NEGATIVE_PROMPT = """
══════════════════════════════════════════════════════
ABSOLUTE VISUAL EXCLUSIONS (ALL MODES)
══════════════════════════════════════════════════════

- Cartoon, anime, illustration, digital painting aesthetics
- Cheap, low-effort 3D rendering — high-quality 3D (product renders, architectural viz, abstract 3D, cinematic CGI) is welcome and encouraged when it elevates the design
- Warped or malformed hands
- Extra or missing fingers
- Asymmetrical facial distortion
- Floating objects without physical support
- Physics violations
- Neon cyberpunk lighting unless category requires it
- Sci-fi holograms unless explicitly strategic
- Watermarks or platform UI frames
- Overcrowded compositions
- Cheap clip-art style visuals
- Excessive lens flare
- Oversharpened hyper-contrast HDR look
- Unrealistic glossy plastic skin
- Surreal, dreamlike, or distorted environments — every scene must be physically plausible and grounded in the real world
- Unrealistic human poses — no floating, levitating, or gravity-defying body positions; people must stand, sit, or move in ways a real human physically can
- Distorted product proportions — no abnormally elongated, stretched, or misshapen objects (e.g. impossibly tall cups, oversized screens, unnaturally long limbs); every object must match its real-world dimensions and look exactly as a human would expect it to
- Logos, trademarks, or signature design marks belonging to ANY real brand other than the one specified in this brief — no Nike swoosh, no Adidas three stripes, no Jordan jumpman, no Puma cat, no Converse star, no New Balance "N", no Reebok vector, no Under Armour UA, no forward/backward swoosh sign, no any other real brand's IP on any product, surface, or background. All products must carry ONLY the identity of the brand in the payload. This is a hard creative and legal requirement.

REALITY ANCHOR — MANDATORY:
This image must depict a scene that could exist in the real world and could have been photographed or professionally rendered by a human creative team on a real brief. If the scene could not exist physically or would not be commissioned by a real brand's marketing department, it is rejected.

FINAL CHECK:
If it looks AI-generated, surreal, or would make a viewer feel uneasy, it fails.
"""

# ═══════════════════════════════════════════════════════════════════════════════
# TYPOGRAPHY PRECISION STANDARD
# Injected into all IMAGE GENERATION prompts — typography section
# Purpose: Enforce perfect spelling, quality copy, and clean letter rendering
# Written at the standard of a 20-year senior prompt engineer for global brands
# ═══════════════════════════════════════════════════════════════════════════════

TYPOGRAPHY_PRECISION = """
══════════════════════════════════════════════════════════════════
TYPOGRAPHY PRECISION — PROFESSIONAL BRAND STANDARD (MANDATORY)
══════════════════════════════════════════════════════════════════

▸ SPELLING — THE ONE HARD RULE. OVERRIDES ALL OTHER DECISIONS.
- Every word must be spelled using correct, standard dictionary English. No exceptions. Ever.
- Do NOT use creative spelling, stylised spelling, phonetic spelling, or decorative letter substitution under any circumstance.
- Do NOT split, join, abbreviate, or truncate words unless they are a recognised acronym or brand name.
- Numbers, brand names, percentages, and currency symbols must be exact — no rounding or paraphrasing.
- If you are not certain of a spelling, choose a different word — never guess.

▸ COPY CRAFT
Write like a veteran direct-response copywriter — every word accountable to the brand payload.
- Strong opening word, concrete nouns, active verbs. No filler, no throat-clearing.
- Reject generic: never use "amazing", "incredible", "best ever", "great" alone — pair with specific proof or cut entirely.
- The reader must understand the brand's value from the image text alone, without the caption.
- Every word earned from the brand payload — company name, industry, tagline, goal, or values evident.

▸ ONE TEXT ZONE — NON-NEGOTIABLE
All marketing copy lives in exactly ONE compositionally planned zone. This is the hardest rule.
— NEVER place any headline, subline, or copy in more than one location on the image
— NEVER echo, repeat, or mirror any text element anywhere else in the frame
— NEVER split copy so part appears top and part appears bottom — it is ONE unified block
— Headline top + subline at the bottom of the frame = a critical failure — do not do this
— Plan the text zone first, before placing any visual element. Then commit to it.

▸ LETTERFORM RENDERING QUALITY
- Every character must be clean, complete, and correctly formed — no melted, warped, blurred, fused, or incomplete letters.
- Consistent stroke weight throughout — no letters heavier or lighter than others within the same word.
- Even tracking and kerning — no letters crowding into each other or drifting apart.
- Baseline must be mathematically straight — no letters floating above or dipping below the text line.
- The finished text must pass a native-speaker reading test: read naturally, spell correctly, mean something real.

▸ TYPOGRAPHIC INTEGRATION — THE TEXT MUST FEEL DESIGNED INTO THE IMAGE, NOT ADDED AFTER
The single most common failure is text that looks stamped on top of an otherwise finished image. Prevent this entirely:

- FONT SELECTION: Choose a typeface that reflects the brand's personality and the image's visual world — not a default. Luxury brands earn serifs or refined thin weights. Athletic brands earn bold condensed. Tech brands earn clean geometric sans. The font must feel like it belongs to this brand's world.
- COLOR: The text color must be drawn from the image's own palette — not generic white or black. Sample the scene: if warm golden light dominates, the text can carry a warm tint. If the brand color is the hero, let the text echo or contrast it deliberately. The text color must feel like the designer chose it looking at this specific image.
- SHADOW & DEPTH: Apply a subtle, directional shadow that matches the scene's light source direction and color temperature. The shadow anchors the text to the surface it sits on — it does not float above. A warm scene gets a warm shadow. A cool studio shot gets a cool, tight shadow. Never a generic black drop shadow.
- PLACEMENT: Position the text in a zone that was compositionally planned for it — negative space, a dark corner, a deliberate gradient zone, or a surface that invites text. The image must look like it was shot/rendered to accommodate this text, not that the text was placed afterward.
- BACKGROUND TREATMENT: If the background behind the text is complex, apply a subtle treatment — a frosted zone, a soft vignette, a refined semi-transparent panel — that feels like a design decision, not a readability hack. The treatment must use the image's own tones and colors.
- SCALE & WEIGHT: Text size and weight must feel proportionate to the full canvas. Line 1 commands the space. Line 2 settles beneath it with clear but harmonious contrast. Neither line should feel too small to matter or too large to breathe.
- RESULT TEST: Cover the text with your hand and look at the image. Uncover it. The text should feel like it was always part of the design — compositionally inevitable, not an afterthought.
"""

# ═══════════════════════════════════════════════════════════════════════════════
# REALISM & HUMAN CREATOR STANDARD
# Injected into all IMAGE GENERATION prompts — execution/quality section
# Purpose: Enforce commercial photography realism, eliminate AI-generated feel
# Written at the standard of a 20-year senior creative director for global brands
# ═══════════════════════════════════════════════════════════════════════════════

REALISM_STANDARD = """
══════════════════════════════════════════════════════════════════
HUMAN CREATOR REALISM STANDARD — COMMERCIAL PRODUCTION QUALITY
══════════════════════════════════════════════════════════════════

▸ THE MANDATORY TEST
A senior art director, creative director, or 3D art director at a world-leading global agency must look at this image and conclude it was created by a skilled professional with a real brief and an unlimited budget — whether photorealistic, high-quality 3D rendered, or a cinematic mix of both. If it reads as low-effort or AI-generated at any level — composition, lighting, texture, anatomy, or text — it has failed.

▸ LIGHTING & PHYSICS
- Every light source must be intentional, directional, and physically plausible. No ambient glow from nowhere.
- Shadows must fall in precise geometric alignment with every light source — contradictory shadows are an immediate failure.
- Reflections must obey the environment: glass picks up the scene, metal reads the sky or studio, wet surfaces mirror the light.
- Materials must behave correctly: fabric drapes with gravity, leather creases under pressure, paper has slight tooth, skin has pores and natural variation.

▸ COLOUR & ATMOSPHERE
- One unified colour temperature across the entire frame — no zones with different light temperatures unless intentionally compositional.
- Colour grading must feel like a professional colourist's decision, not a filter applied after the fact.
- Brand colours should feel embedded in the scene — in the light, in the surfaces, in the environment — not painted on top.

▸ COMPOSITION & CRAFT
- Every element in the frame must have a deliberate reason to exist. Remove anything decorative but purposeless.
- Follow a professional compositional principle: rule of thirds, golden ratio, leading lines, deliberate symmetry — pick one and commit.
- Depth of field must match the subject and intent: shallow for product/portrait close-ups, full depth for environmental or lifestyle scenes.
- Background elements must reinforce the brand world and be contextually coherent — no generic or contradictory environments.
- The entire scene must be believable as a real place or real studio setup — no surreal skies, impossible architecture, or fantasy geography.

▸ HUMAN ANATOMY (when people appear)
- Facial anatomy must be precise: eyes level and proportionate, nose correctly positioned, natural lip shape and skin texture.
- Body proportions must obey real human anatomy — correct number of fingers, natural joint positions, believable pose.
- Expressions must be genuine and earned by the context — no uncanny valley smiles, no dead eyes, no forced poses.
- Hair must have physical weight and natural movement — not floating, not uniformly smooth, not impossibly perfect.
- Clothing must respond to gravity, body shape, and movement — natural drape, realistic creasing, contextually appropriate.

▸ PRODUCTION VALUE
- This image competes at a global scale — it must match or exceed the best work produced by world-leading creative agencies for Fortune 500 clients across any industry.
- Not a concept, not a mockup, not a student project — a finished, deliverable, campaign-ready asset.
- The render medium (photography, 3D, CGI, mixed) must be chosen deliberately to best serve the brand's industry and the creative brief's emotional intent.
- The kind of image a global brand would publish on their flagship channels without hesitation.
"""

# ═══════════════════════════════════════════════════════════════════════════════
# MINIMAL TEXT ON IMAGE DIRECTIVE
# Injected into prompt ENHANCEMENT calls
# Purpose: Enforce clean global-brand asset discipline
# ═══════════════════════════════════════════════════════════════════════════════

MINIMAL_TEXT_DIRECTIVE = """
TEXT RENDERING DIRECTIVE

Render marketing copy as designed typographic elements directly on the image.
Typography must feel composed INTO the design — intentional hierarchy, brand-appropriate weight, legible placement.

HIERARCHY RULES (render only the copy — never render these labels):
- Line 1 (bold, large): The primary message — short, punchy headline
- Line 2 (lighter weight): Supporting message or benefit — brief and clear
- Line 3/CTA (optional): Short action phrase, clearly set apart

QUALITY STANDARD:
- Text must be perfectly spelled and grammatically correct
- No long paragraphs or dense copy blocks on the image
- No phone numbers, URLs, or legal disclaimers on the image
- Typography must enhance the composition, not fight it
"""


# ═══════════════════════════════════════════════════════════════════════════════
# CAPTION ENRICHMENT DIRECTIVE
# Injected into caption generation prompts
# Purpose: Move strategic persuasion into caption copy
# ═══════════════════════════════════════════════════════════════════════════════

CAPTION_ENRICHMENT_DIRECTIVE = """
CAPTION STRATEGY (OBJECTIVE AWARE)

The caption is the primary persuasion layer.
Be structured, clear, and conversion-oriented.

────────────────────────────────────

PRODUCT_AUTHORITY:
- Highlight differentiation.
- Emphasize quality, performance, innovation.
- Reinforce credibility.

FEATURE_EDUCATION:
- Explain functionality clearly.
- Use benefit-driven language.
- Provide clarity without jargon overload.

BRAND_POSITIONING:
- Communicate vision, values, premium tone.
- Build perception and authority.

LIFESTYLE_ASPIRATION:
- Emotional storytelling.
- Relatable scenario.
- Soft but confident CTA.

OFFER_PROMOTION:
- Reinforce urgency.
- Clarify terms.
- Strong but clean CTA.

CORPORATE_INSTITUTIONAL:
- Emphasize stability, scale, reliability.
- Professional tone.

COMMUNITY_TRUST:
- Social proof language.
- Trust-building messaging.

FINAL RULE:
Caption must complete what the image suggests.
Not repeat it.
"""