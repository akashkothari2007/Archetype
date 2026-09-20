"""Baseten server for TripoSplat: one image in, one Gaussian splat file out.

The response uses a `model_mesh.content` base64 blob so plancheck.services.splat
can decode the Gaussian without a second download.
"""

import base64
import binascii
import io
import time
import urllib.request
from pathlib import Path

WEIGHTS = Path("/models/triposplat")
MIN_GAUSSIANS = 32768
MAX_GAUSSIANS = 262144


def _decode_image(request: dict):
    from PIL import Image

    source = request.get("image") or request.get("image_url") or ""
    if not isinstance(source, str) or not source:
        raise ValueError("Provide an image as a data URI, a URL, or base64 in 'image'.")
    if source.startswith("http://") or source.startswith("https://"):
        with urllib.request.urlopen(source, timeout=60) as response:
            raw = response.read()
    else:
        payload = source.partition(",")[2] if source.startswith("data:") else source
        try:
            raw = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Image was neither a URL nor valid base64.") from exc
    return Image.open(io.BytesIO(raw)).convert("RGB")


class Model:
    def __init__(self, **kwargs):
        self._pipe = None
        self._device = "cpu"

    def load(self):
        import torch

        from tsplat import TripoSplatPipeline

        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self._pipe = TripoSplatPipeline(
            ckpt_path=str(WEIGHTS / "diffusion_models/triposplat_fp16.safetensors"),
            decoder_path=str(WEIGHTS / "vae/triposplat_vae_decoder_fp16.safetensors"),
            dinov3_path=str(WEIGHTS / "clip_vision/dino_v3_vit_h.safetensors"),
            flux2_vae_encoder_path=str(WEIGHTS / "vae/flux2-vae.safetensors"),
            rmbg_path=str(WEIGHTS / "background_removal/birefnet.safetensors"),
            device=self._device,
        )

    def predict(self, request: dict) -> dict:
        image = _decode_image(request)
        fmt = str(request.get("output_format") or "splat").lower()
        if fmt not in {"splat", "ply"}:
            raise ValueError("output_format must be 'splat' or 'ply'.")
        # The pipeline asserts on out-of-range counts, which would surface as a 500.
        count = int(request.get("num_gaussians") or 131072)
        count = max(MIN_GAUSSIANS, min(MAX_GAUSSIANS, count))
        started = time.time()
        gaussian, prepared = self._pipe.run(
            image,
            seed=int(request.get("seed") or 42),
            steps=int(request.get("num_inference_steps") or 20),
            guidance_scale=float(request.get("guidance_scale") or 3.0),
            num_gaussians=count,
        )
        raw = gaussian.to_splat_bytes() if fmt == "splat" else gaussian.to_ply_bytes()
        preview = io.BytesIO()
        prepared.save(preview, format="PNG")
        return {
            "model_mesh": {
                "content": base64.b64encode(raw).decode("ascii"),
                "file_name": f"output.{fmt}",
                "file_size": len(raw),
                "content_type": "application/octet-stream",
            },
            "preprocessed_image": {
                "content": base64.b64encode(preview.getvalue()).decode("ascii"),
                "content_type": "image/png",
            },
            "num_gaussians": count,
            "timings": {"inference": round(time.time() - started, 2)},
        }
