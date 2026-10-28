# Studio IA — mobile conversation QA

## Visual target and evidence

- Selected source: option 3, `/home/koubyte/.codex/generated_images/01a163e0-ad3c-7b72-b1b2-5a911966c30d/exec-d30dfa19-ad4a-4b4a-b37f-382a51162eeb.png` (853 × 1844).
- Implementation: existing Postiz editorial UI, local fixture server `http://127.0.0.1:8768/editorial/#discussion` with the actual production HTML/CSS/JS; fixture mutations do not contact production.
- Mobile browser viewport requested: 390 × 844 CSS pixels. IAB capture: 389 × 844 pixels (fractional effective browser scaling). Comparison normalizes both panels to 390 × 844; this one-pixel difference is not a design finding.
- First capture: `/home/koubyte/.local/share/postiz/mobile-qa-first.png`.
- Revised capture: `/home/koubyte/.local/share/postiz/mobile-qa-second.png`.
- Combined source/implementation evidence: `/home/koubyte/.local/share/postiz/mobile-qa-comparison.png`.
- Reduced-height input state (360 × 420 viewport): `/home/koubyte/.local/share/postiz/mobile-qa-keyboard.png`.
- State: a user brief, assistant response, an inline generated post pending review, empty composer. Actual existing Hailun artwork is used in place of the mockup's illustrative piano. No live publication is created by QA.

## Comparison history and findings

1. Initial capture: [P2] The existing font called “Outfit” was actually a Black face; headings were visibly heavier than the selected target. Replaced the conversation heading face with real Outfit Semibold from Google Fonts. Weekly typography is preserved.
2. Initial capture: [P2] A 360px-tall portrait visual pushed the review action behind the persistent composer. Limited previews to 260px, preserving the complete artwork with contain instead of cropping product details. Revised capture shows the review action and correction action above the composer.
3. Initial capture: [P2] Date repeated “Paris”. Removed the duplicate suffix; revised capture shows one time-zone label.
4. Interactive test: [P2] Existing bottom toast obscured the composer temporarily. Conversation toasts now appear below the header and ignore pointer events; this affects only transient feedback. Post-fix evidence: `/home/koubyte/.local/share/postiz/mobile-qa-toast-fixed.png`.
5. Interaction review: an expanded brief must not prevent switching conversations. Render guards now apply only within the same conversation. Stale responses are discarded if the user switches during a poll.

## Required fidelity surfaces

- Fonts/typography: Outfit Semibold for headings and Inter for text; main body stays 16px for phone readability. Labels and clear text hierarchy match the target. No giant promotional heading in the active conversation.
- Spacing/layout: compact three-part header, a single scrollable conversation, inline post and bottom composer. No side panel or persistent settings form. Photo/microphone targets are at least 44px. Reduced-height viewport has no horizontal overflow; microphone and send remain visible.
- Colors/tokens: existing black, charcoal, muted white and mint retained. User bubble uses deep green; review action has mint outline. No decorative gradient or new brand system.
- Image quality: real generated product artwork displayed in full rather than substituting the concept's imaginary product. Different aspect ratio and resulting image width are intentional production constraints. Phosphor SVG assets are vendored unchanged; no emoji or handcrafted icon artwork in the new chat controls.
- Copy/content: short French labels, “Parler”, “Voir et valider”, a single approval reminder. Actual scheduled date replaces the mockup's unknown date. A quiet correction action is retained because single-post edits are a user requirement. Delivery/read checkmarks and fabricated message times from the mockup are deliberately omitted.

The full comparison at normalized mobile size is readable for this low-density screen; a separate focused crop is unnecessary. The reduced-height capture specifically verifies the composer and text input.

## Functional checks

- Mobile 390 × 844; narrow 360 × 640; reduced height 360 × 420; desktop 1280 × 800 (`/home/koubyte/.local/share/postiz/studio-qa-desktop.png`).
- Empty conversation, populated conversation, multiline text, visible send action, and target-correction chip.
- Opening a post preserves the existing review dialog; approval remains disabled until the existing explicit review checkbox is checked.
- Correction sends the exact selected item ID; the following message resets to new-post mode.
- Optional brief controls send the edited price (799) and correct Paris-to-UTC date. Hidden controls are not presented by default.
- Menu, conversation history, new-conversation entry, weekly navigation and return to chat.
- No browser console errors during the interaction checks.
- 85 backend/transcription/media tests passed. One existing time-dependent test was stabilized to a daytime slot; runtime spacing logic was not changed.

## Residual test gaps

- Real iPhone/Android keyboard behavior and physical microphone capture require an actual device. The browser viewport tests do not simulate phone hardware.
- Production verified after deployment: authenticated empty conversation and existing two-post conversation load, inline content is present, browser reports no errors, no horizontal overflow at 390 × 844, and the editorial container is healthy. Evidence: `/home/koubyte/.local/share/postiz/studio-mobile-live.png`. No real post was approved or published during this UI change.

## Implementation checklist

- [x] Selected chat layout integrated into the existing service.
- [x] Inline results, targeted edits, menu and composer wired to existing APIs.
- [x] Approval, weekly automation and spacing remain enforced by existing backend.
- [x] Mobile visual comparison and core UI flows checked.
- [x] P0/P1/P2 fixes applied; actual-media and readable-text differences documented.

final result: passed
