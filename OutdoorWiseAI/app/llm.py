"""Small open-weights LM wrapper (<= 3B params). Default: Qwen2.5-1.5B-Instruct."""
import os
import threading

from .config import GGUF_FILE, GGUF_REPO, LLM_BACKEND, MODEL_ID

LLM_DTYPE = os.getenv("LLM_DTYPE", "float32")            # float32 is usually faster than bfloat16 on plain CPUs
LLM_MAX_SECONDS = float(os.getenv("LLM_MAX_SECONDS", "60"))  # hard cap per generation


class LLM:
    def __init__(self):
        self.backend = LLM_BACKEND
        self.model_id = MODEL_ID
        self._lock = threading.Lock()  # one generation at a time
        if self.backend == "transformers":
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            self.torch = torch
            torch.set_num_threads(max(1, os.cpu_count() or 1))
            self.tok = AutoTokenizer.from_pretrained(MODEL_ID)
            self.model = AutoModelForCausalLM.from_pretrained(MODEL_ID, torch_dtype=getattr(torch, LLM_DTYPE))
            self.model.eval()
        elif self.backend == "llama_cpp":
            from llama_cpp import Llama
            self.model = Llama.from_pretrained(repo_id=GGUF_REPO, filename=GGUF_FILE, n_ctx=4096, verbose=False)
            self.model_id = f"{GGUF_REPO} ({GGUF_FILE})"
        else:
            raise ValueError(f"Unsupported LLM_BACKEND={self.backend}")

    def generate(self, messages, max_new_tokens=300) -> str:
        if not self._lock.acquire(timeout=3):  # another request is generating: caller falls back to template
            raise RuntimeError("SLM busy")
        try:
            if self.backend == "llama_cpp":
                out = self.model.create_chat_completion(messages=messages, max_tokens=max_new_tokens, temperature=0.0)
                return out["choices"][0]["message"]["content"].strip()
            text = self.tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            inputs = self.tok(text, return_tensors="pt")
            with self.torch.inference_mode():
                out = self.model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False,
                                          repetition_penalty=1.05, max_time=LLM_MAX_SECONDS)
            return self.tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()
        finally:
            self._lock.release()
