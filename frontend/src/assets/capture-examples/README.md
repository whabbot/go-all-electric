# Fictional capture examples

These 12 images were generated with Codex's built-in image generation tool, without
reference photos or the project's Gemini API. They depict invented homes/equipment
and an invented supplier. They must remain labelled as illustrations in the UI.

All assets are 800 × 600 WebP, below 120 KB. The boiler's 24 kW output, fuse's
80 A rating, and bill's 12,450 kWh and 01 April 2025–31 March 2026 dates were
visually checked after optimisation. No text compositing was needed.

## Prompt set

Shared direction: photorealistic natural smartphone photograph for a fictional UK
home energy survey, landscape 4:3; no real brands or logos, people, faces, readable
house numbers, street names, addresses, postcodes, account, serial or meter numbers;
no captions, watermarks, collages or diagrams.

| Asset | Subject and framing direction |
| --- | --- |
| boiler-good | Sharp straight-on metal data plate filling the frame on white enamel. Exact text: FICTIONAL BOILER; Model H24; Central heating output: 24 kW. All plate edges visible. |
| boiler-bad | Generic boiler photographed across a utility room; tiny plate too far away to read. |
| radiators-good | White double-panel convector radiator viewed from a front corner looking down at about 45 degrees; front face, top grille with fins between the panels, and end profile visible; yellow metric tape across the full width. |
| radiators-bad | Same kind of white panel radiator photographed exactly straight on at radiator mid-height; front face and yellow tape across the width visible, but top, fins and end depth hidden so the panel count cannot be told. |
| fuse-good | Close-up of sealed black UK service fuse carrier, insulated cables, intact security seal, sharp 80 A marking; nothing opened. |
| fuse-bad | Unbranded consumer unit with closed translucent cover over breaker toggles; no service fuse cutout. |
| outdoor-good | Proposed heat-pump spot from a few steps back, showing brick wall, window, paving width/depth, fence, drainpipe and measuring tape; no unit installed. |
| outdoor-bad | Excessively tight crop of brickwork and a small strip of paving, surrounding space and obstacles outside frame. |
| loft-good | Clearly lit mineral wool, timber joists and rafters from hatch, metric tape inserted into wool. |
| loft-bad | Boarded loft with plain boxes, no visible insulation so depth cannot be judged. |
| bill-good | Sharp fictional annual gas statement on wood, all corners visible, large legible text: Hearthleaf Energy; FICTIONAL EXAMPLE; Annual gas statement; Usage period; 01 April 2025 - 31 March 2026; Gas used; 12,450 kWh. No personal identifiers. |
| bill-bad | Close crop of charges panel only: Hearthleaf Energy; FICTIONAL EXAMPLE; Gas charges; Energy charge GBP 842.10; Standing charge GBP 110.00; Total GBP 952.10. No kWh or dates. |

The two radiator assets were regenerated with Codex's built-in image generation
tool on 24 October 2026 to match the single-photo capture guidance. The radiator
prompts used the shared direction above, a pale wall, skirting board and neutral
floor, natural indoor daylight, an unbranded Type 22 double-panel convector, and
a taut yellow tape hooked across the full width without hands or people. Good
explicitly requested the elevated front-corner view and mechanically plausible
panels and fins; Avoid explicitly requested a level lens parallel to the front,
with no visible top or end depth. No reference photos or Gemini API calls were
used. Both were resized to 800 × 600 and encoded as WebP, then visually checked
for the camera angle, visible/hidden panel depth and tape measure. The UI retains
the “Illustration · fictional example” label for both images.
