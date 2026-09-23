"""Run unmodified upstream Human loader + reduced HPT world/action training.

This checks data use, not released-checkpoint quality or the full training recipe.
No model download, cloud database, robot data, or fake upstream modules are used.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

from capego.contracts import sha256
from capego.exporting import EGOWAM_COMMIT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", type=Path, required=True)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--export", type=Path)
    inputs.add_argument("--demo-report", type=Path)
    parser.add_argument("--device", choices=["cpu", "cuda", "mps"], default="cpu")
    parser.add_argument("--steps", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.demo_report:
        args.export = Path(json.loads(args.demo_report.read_bytes())["exports"]["egowam"])
    if args.steps < 1:
        raise ValueError("At least one training step is required")
    upstream = args.upstream.resolve()
    commit = subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip()
    if commit != EGOWAM_COMMIT:
        raise ValueError(f"Expected upstream commit {EGOWAM_COMMIT}, got {commit}")
    if subprocess.check_output(["git", "-C", str(upstream), "diff", "--name-only", "HEAD"], text=True).strip():
        raise ValueError("Validation requires unchanged upstream tracked source")
    report = json.loads((args.export / "report.json").read_bytes())
    if report["format"] != "egowam.human.zarr":
        raise ValueError("Expected EgoWAM export")
    for file, digest in report["content_files"].items():
        if sha256((args.export / file).read_bytes()) != digest:
            raise ValueError("Export file checksum mismatch")
    sys.path.insert(0, str(upstream))
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch
    import torch.nn.functional as F
    from egowam.algo.hpt_wm import HPTModel
    from egowam.models.hpt_nets import MLPPolicyStem, MultiBlockTransformerDecoder
    from egowam.rldb.embodiment.human import Human
    from egowam.rldb.zarr.zarr_dataset_multi import ZarrDataset
    from omegaconf import OmegaConf

    torch.manual_seed(17)
    torch.set_num_threads(2)
    horizon, width, domain = 4, 32, "aria_bimanual"
    datasets = [ZarrDataset(args.export / e["path"], Human.get_keymap(action_horizon=horizon, use_future=True),
                           Human.get_transform_list(chunk_length=horizon, stride=1, use_future=True)) for e in report["episodes"]]
    # Exclude tail anchors that upstream would pad; every target here is observed.
    samples = [ds[i] for ds in datasets for i in range(min(4, max(0, len(ds)-horizon)))]
    if not samples:
        raise ValueError("Need an episode with more than four frames for unpadded future supervision")
    images = torch.stack([s[Human.VIZ_IMAGE_KEY] for s in samples]).float()
    future = torch.stack([s["future.observations.images.front_img_1"] for s in samples]).float()
    if images.shape[-1] == 3:
        images, future = images.permute(0, 3, 1, 2), future.permute(0, 3, 1, 2)
    images, future = images / 255., future / 255.
    # Small, explicit image representation keeps the smoke run independent of pretrained weights.
    images = F.adaptive_avg_pool2d(images, (8, 8)).flatten(1).unsqueeze(1)
    future = F.adaptive_avg_pool2d(future, (8, 8)).flatten(1).unsqueeze(1)
    actions = torch.stack([s["actions_cartesian"] for s in samples]).float()
    states = torch.stack([s["observations.state.ee_pose"] for s in samples]).float().unsqueeze(1)
    if not torch.isfinite(actions).all() or actions.abs().sum() == 0:
        raise ValueError("Invalid or all-zero action supervision")
    specs = OmegaConf.create({"random_horizon_masking": False, "cross_attn": {
        "crossattn_latent": 2, "crossattn_heads": 2, "crossattn_dim_head": 16,
        "crossattn_modality_dropout": 0., "modality_embed_dim": width}})
    model = HPTModel(embed_dim=width, num_blocks=1, num_heads=2, token_postprocessing="joint_token",
                     observation_horizon=1, action_horizon=horizon, future_horizon=1)
    model.init_domain_stem(domain, {
        "rgb": MLPPolicyStem(input_dim=192, output_dim=width, widths=[width], specs=specs),
        "state_ee_pose": MLPPolicyStem(input_dim=12, output_dim=width, widths=[width], specs=specs)})
    model.init_domain_head(domain, MultiBlockTransformerDecoder(input_dim=width, output_dim=12,
        action_horizon=horizon, latent_token_len=horizon, num_heads=2, dim_head=16, dropout=0., num_layers=1))
    model.init_domain_head(domain+"_future_rgb", MultiBlockTransformerDecoder(input_dim=width, output_dim=192,
        action_horizon=1, latent_token_len=1, num_heads=2, dim_head=16, dropout=0., num_layers=1))
    model.auxiliary_ac_keys = {domain: ["future_rgb"]}
    model.auxiliary_loss_weights = {"future_rgb": 1.}
    model.wm_prediction_mode = "joint"
    model.diffusion = False
    model.finalize_modules()
    model.to(args.device).train()
    model.device = torch.device(args.device)
    data = {"rgb": images, "state_ee_pose": states, "action": actions, "future_rgb": future}
    data = {k: v.to(args.device) for k, v in data.items()}
    before = {k: v.detach().clone() for k, v in model.named_parameters()}
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    losses = []
    for _ in range(args.steps):
        optimizer.zero_grad(set_to_none=True)
        loss = model.compute_loss({"domain": domain, "data": copy.deepcopy(data)})
        if not torch.isfinite(loss) or loss.item() <= 0:
            raise ValueError("Training loss must be finite and nonzero")
        loss.backward()
        gradients = [p.grad for p in model.parameters() if p.grad is not None]
        if not gradients or not all(torch.isfinite(g).all() for g in gradients) or not any(g.abs().sum() > 0 for g in gradients):
            raise ValueError("Training requires finite, nonzero gradients")
        optimizer.step()
        losses.append({"total": float(loss.detach()), "action": float(model._last_loss_breakdown["action"]),
                       "future_rgb": float(model._last_loss_breakdown["aux"])})
    changes = {key: sum(not torch.equal(before[n], p.detach()) for n, p in model.named_parameters() if n.startswith(prefix))
               for key, prefix in {"trunk": "trunk.", "action_head": f"heads.{domain}.", "world_head": f"heads.{domain}_future_rgb."}.items()}
    if not all(changes.values()):
        raise ValueError("Both action and world heads, and the trunk, must update")
    result = {"status": "passed", "upstream_commit": commit, "target": "EgoWAM HPTModel joint world/action loss",
              "scope": "reduced configuration smoke test; not released weights or full training recipe",
              "device": args.device, "torch": torch.__version__, "source_origins": report["origins"],
              "dataset_sha256": report["dataset_sha256"], "batch_size": len(samples), "action_shape": list(actions.shape),
              "future_rgb_shape": list(future.shape), "losses": losses, "updated_parameter_tensors": changes,
              "robot_samples": 0, "parameters": sum(p.numel() for p in model.parameters())}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
