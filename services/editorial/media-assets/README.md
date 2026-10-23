# Approved Planète Laser brand assets

The user approved the direction “Le matériel prend vie” and the weekly workflow on 23 October 2026. The renderer uses the existing site logo unchanged, the site’s Outfit and Inter fonts at weight 600, and the charcoal/white/laser-green palette.

The original WOFF2 fonts in `docs/planete-laser/assets` were decoded and statically instantiated using fontTools 4.67.0. Their OFL licenses are included. The manifest pins renderer asset hashes. The existing logo was copied byte-for-byte from that same directory.

Runtime dependency: Pillow. Source downloads use the service’s shared `net.public_bytes` public-address-pinned downloader.

Segmentation uses direct ONNXRuntime CPU inference with U2netp. The Docker build provisions `/models/u2netp.onnx` from the official rembg model release and checks SHA-256 `309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8` (4,574,861 bytes). The renderer repeats that integrity check before loading and limits inference to one CPU thread. No rembg package or runtime download is used. Without a local model, supplied transparency or a conservative edge-connected-white packshot mask is used; complex backgrounds block content. All methods preserve source RGB and require human source/mask/output review.
