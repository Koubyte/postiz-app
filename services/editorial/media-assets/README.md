# Approved Planète Laser brand assets

The user approved the direction “Le matériel prend vie” and the weekly workflow on 23 October 2026. The renderer uses the existing site logo unchanged, the site’s Outfit and Inter fonts at weight 600, and the charcoal/white/laser-green palette.

The original WOFF2 fonts in `docs/planete-laser/assets` were decoded and statically instantiated using fontTools 4.67.0. Their OFL licenses are included. The manifest pins renderer asset hashes. The existing logo was copied byte-for-byte from that same directory.

Runtime dependency: Pillow. Source downloads use the service’s shared `net.public_bytes` public-address-pinned downloader.

Optional segmentation: install `rembg[cpu]` and provision `u2netp.onnx` in the directory set by `U2NET_HOME` (default `/models`) during image build. The model is never downloaded on a content request. Without that file, the renderer uses supplied transparency or a conservative edge-connected-white packshot mask; complex backgrounds block content. Both methods preserve source RGB and require human source/mask/output review.

A successful render does not constitute visual approval or verification of image licensing. Source, mask, background, final social and blog images, and SHA-256 provenance are retained. A provider `image_mask_required` flag blocks that source instead of removing a watermark or protective mask.
