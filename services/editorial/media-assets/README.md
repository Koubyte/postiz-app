# Approved Planète Laser brand assets

The user approved the direction “Le matériel prend vie” and the weekly workflow on 23 October 2026. The renderer uses the existing site logo unchanged, the site’s Outfit and Inter fonts at weight 600, and the charcoal/white/laser-green palette.

The original WOFF2 fonts in `docs/planete-laser/assets` were decoded and statically instantiated using fontTools 4.67.0. Their OFL licenses are included. The manifest pins renderer asset hashes. The existing logo was copied byte-for-byte from that same directory.

Runtime dependency: Pillow. The generator downloads reference photos through the shared `net.public_bytes` public-address-pinned downloader before sending them to the image bridge. The renderer itself makes no network requests.

Product visuals are complete reference-guided scenes generated from the exact product photograph. The renderer applies the charter, logo, text and optional price over that scene, with no cutout, segmentation or product collage. It requires the exact reference bytes and the caller's explicit `reference_used=True` acknowledgment. Product reference, generated scene, final exports and SHA-256 provenance are retained for review. `image_mask_required` supplier restrictions remain blocking.

The generated product can differ from the reference. Final approval therefore includes visual comparison of the product identity, details and scene, plus media rights. Provenance records `image_mode=reference-guided-generation`, `product_rgb_repainted=true` and `requires_visual_approval=true`; it does not claim product pixels were preserved. The blog cover contains no overlaid logo or text. Advice scenes need no product reference.
