"""Fallback: deploy a tool-calling open-weight model on Modal as an OpenAI-compatible endpoint.

Use Modal's model library first if it is available on the day; this script is the
same result done by hand, for when it is not.

    modal secret create pakka-model VLLM_API_KEY=<choose-a-key>
    modal deploy pydantic_challenge/modal_model.py
    #  -> https://<workspace>--pakka-model-serve.modal.run   (the endpoint)

Then in Logfire -> Gateway -> Routes -> add a route:
    provider: OpenAI-compatible · base URL: <endpoint>/v1 · API key: the VLLM_API_KEY you chose · name: pakka-modal
and in .env:
    PAKKA_MODEL=gateway/openai:Qwen/Qwen2.5-7B-Instruct
    PAKKA_GATEWAY_ROUTE=pakka-modal

The model must support tool calls: Tom's agent works entirely through tools. Qwen 2.5 Instruct
(hermes tool parser) and Llama 3.x Instruct (llama3_json) both do.

Written against Modal 1.5 (`modal.web_server`, `modal.concurrent`, `Volume.from_name`); not run in the
build sandbox, which has no Modal token.
"""

import modal

MODEL = "Qwen/Qwen2.5-7B-Instruct"
TOOL_PARSER = "hermes"  # "llama3_json" for Llama 3.x Instruct
GPU = "A100"
MINUTES = 60

image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install("vllm", "huggingface_hub[hf_transfer]")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
)

hf_cache = modal.Volume.from_name("pakka-hf-cache", create_if_missing=True)

app = modal.App("pakka-model")


@app.function(
    image=image,
    gpu=GPU,
    scaledown_window=15 * MINUTES,
    timeout=10 * MINUTES,
    volumes={"/root/.cache/huggingface": hf_cache},
    secrets=[modal.Secret.from_name("pakka-model")],
)
@modal.concurrent(max_inputs=32)
@modal.web_server(port=8000, startup_timeout=10 * MINUTES)
def serve() -> None:
    import subprocess

    cmd = [
        "vllm", "serve", MODEL,
        "--host", "0.0.0.0", "--port", "8000",
        "--served-model-name", MODEL,
        "--max-model-len", "16384",
        "--enable-auto-tool-choice", "--tool-call-parser", TOOL_PARSER,
    ]
    # VLLM_API_KEY from the `pakka-model` secret protects the endpoint; the gateway route carries it.
    subprocess.Popen(cmd)
