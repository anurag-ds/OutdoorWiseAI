FROM python:3.11-slim
WORKDIR /app
ARG MODEL_ID=Qwen/Qwen2.5-1.5B-Instruct
ENV MODEL_ID=$MODEL_ID LLM_BACKEND=transformers HF_HOME=/app/hf_cache PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /app/hf_cache && chmod -R 777 /app/hf_cache \
 && python -c "import os; from transformers import AutoModelForCausalLM, AutoTokenizer as T; m=os.environ['MODEL_ID']; T.from_pretrained(m); AutoModelForCausalLM.from_pretrained(m)"
COPY app app
RUN chmod -R a+rX /app
EXPOSE 7860
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
