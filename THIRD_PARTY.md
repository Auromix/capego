# Third-party materials

The Apache-2.0 license covers CapEgo's original code and documentation. It does not relicense external data, weights or separately installed dependencies. No EgoDex source code, recordings, model weights or EgoWAM source is vendored here.

| Component | How CapEgo uses it | License/source boundary |
| --- | --- | --- |
| [EgoDex](https://github.com/apple-aiml-research/ml-egodex#license) | Optional local video/HDF5 inputs and integration validation | Upstream describes the dataset as CC-BY-NC-ND. Its example code has separate terms. Downloaded recordings and derived datasets are not distributed by CapEgo. |
| [EgoWAM](https://github.com/GaTech-RL2/EgoWAM) | External checkout for a pinned Human loader / reduced HPT training validation | Consult the upstream repository's license and any checkpoint/data terms before use. Only CapEgo's adapter and validation script are included here. |
| [Qwen2.5-VL-3B-Instruct](https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct) | Optional locally provisioned semantic annotation model | Model weights and tokenizer/config files retain their model-card terms; not included in this repository. |
| Python dependencies | Installed through extras in `pyproject.toml` | Each dependency retains its own license. Optional training dependencies are isolated from the base package. |

The public-data smoke run uses EgoDex test-split clips solely as integration fixtures. It discards training updates and produces no benchmark score or trained checkpoint. Published validation reports contain file hashes and numerical test outcomes, not recordings or converted datasets. Check upstream terms for your intended use, particularly redistribution or commercial use.

Please cite the original EgoDex and EgoWAM work when using their data or models in research. CapEgo's original synthetic fixtures and workbench demonstration are identified as synthetic wherever used.
