"""Create the public Hugging Face repo (weights + tokenizer + model card).
Usage:  HF_TOKEN=hf_xxx python scripts/push_to_hf.py YOUR_USERNAME/outdoorwise-qwen2.5-1.5b
"""
import os
import sys

from huggingface_hub import HfApi
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE = "Qwen/Qwen2.5-1.5B-Instruct"
repo_id = sys.argv[1]
token = os.environ["HF_TOKEN"]

tok = AutoTokenizer.from_pretrained(BASE)
model = AutoModelForCausalLM.from_pretrained(BASE)
model.push_to_hub(repo_id, token=token)
tok.push_to_hub(repo_id, token=token)

card = open(os.path.join(os.path.dirname(__file__), "..", "huggingface", "MODEL_CARD.md"), encoding="utf-8").read()
card = card.replace("YOUR_USERNAME/outdoorwise-qwen2.5-1.5b", repo_id)
HfApi(token=token).upload_file(path_or_fileobj=card.encode("utf-8"), path_in_repo="README.md", repo_id=repo_id)
print("Done: https://huggingface.co/" + repo_id)
