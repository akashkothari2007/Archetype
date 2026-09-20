# TripoSplat on Baseten

Sparkles needs an image-to-3D-Gaussian endpoint. Baseten's model catalog has no such
model, so this Truss deploys [TripoSplat](https://github.com/VAST-AI-Research/TripoSplat)
(MIT, weights on [Hugging Face](https://huggingface.co/VAST-AI/TripoSplat)) into your own
workspace. Generations bill against Baseten GPU credits.

```
config.yaml                    L4 GPU, pinned weights mounted at /models/triposplat
model/model.py                 request -> Gaussian splat, returned as base64
packages/tsplat/               vendored upstream pipeline (pinned commit, MIT)
```

## Deploy

```bash
pip install --upgrade truss
truss login                    # API key from Baseten -> Settings -> API keys
cd deploy/triposplat-baseten
truss push --publish
```

The first push mirrors ~10 GB of checkpoints and builds the image, so expect 20–40
minutes before the deployment goes active. Watch it in the Baseten UI or with
`truss watch`.

## Point Archetype at it

Copy the model's predict URL from the Baseten dashboard, then in `.env`:

```
PLANCHECK_SPLAT_URL=https://model-<id>.api.baseten.co/environments/production/predict
PLANCHECK_SPLAT_API_KEY=<baseten api key>
```

Sparkles talks only to this Baseten endpoint (Flux stays on its own Baseten
deployment). Recreate the backend so the container picks up the new values:

```bash
docker compose up -d --force-recreate backend
```

## Contract

Request (what `plancheck/services/splat.py` sends):

```json
{ "image": "data:image/png;base64,...", "num_gaussians": 131072, "output_format": "splat" }
```

`image_url` also works with an `http(s)` URL. `num_gaussians` is clamped to
32768–262144. Response:

```json
{ "model_mesh": { "content": "<base64 .splat>", "file_name": "output.splat" } }
```

## Notes

Scaling from zero reloads ~10 GB onto the GPU, so a cold first splat can take a few
minutes; the client allows 15. Set a minimum replica of 1 in the Baseten UI while
demoing to avoid that wait.
