"""An OpenAI-compatible relay on Modal in front of Google's Gemini API, for the gateway's `pakka` endpoint.

Why: the Pydantic AI Gateway adds `safety_identifier` (and may add other OpenAI-only fields) to every request it
forwards to an OpenAI-type provider, and Google's OpenAI-compatible endpoint rejects unknown fields with a 400.
This relay strips what Google does not accept and forwards everything else unchanged, including the
`Authorization: Bearer <gemini key>` header the gateway sends, so no key lives here.

    modal deploy pydantic_challenge/modal_shim.py
    -> https://<workspace>--pakka-gemini-shim-web.modal.run

Then the gateway provider's base URL is `<that url>/v1`. Streaming and non-streaming are both relayed.
CPU only; no GPU and no payment method required.
"""

import modal

UPSTREAM = "https://generativelanguage.googleapis.com/v1beta/openai"
# Fields the gateway or an OpenAI client may send that Google's compatibility layer rejects.
DROP = {"safety_identifier", "prompt_cache_key", "service_tier", "store", "metadata", "parallel_tool_calls", "web_search_options"}

image = modal.Image.debian_slim(python_version="3.12").pip_install("fastapi", "httpx")
app = modal.App("pakka-gemini-shim")


@app.function(image=image, min_containers=1, timeout=300)
@modal.asgi_app()
def web():
    import json

    import httpx
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse, Response, StreamingResponse

    api = FastAPI(title="pakka gemini shim")

    def upstream_headers(request: Request) -> dict:
        h = {"Content-Type": "application/json"}
        auth = request.headers.get("authorization")
        if auth:
            h["Authorization"] = auth
        return h

    @api.get("/v1/models")
    async def models(request: Request):
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(f"{UPSTREAM}/models", headers=upstream_headers(request))
        return Response(content=r.content, status_code=r.status_code, media_type=r.headers.get("content-type", "application/json"))

    @api.post("/v1/chat/completions")
    async def chat(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": {"message": "body is not JSON"}}, status_code=400)
        if isinstance(body, dict):
            for k in list(body):
                if k in DROP:
                    body.pop(k)
        stream = bool(isinstance(body, dict) and body.get("stream"))
        headers = upstream_headers(request)
        url = f"{UPSTREAM}/chat/completions"
        if not stream:
            async with httpx.AsyncClient(timeout=300) as client:
                r = await client.post(url, headers=headers, content=json.dumps(body))
            return Response(content=r.content, status_code=r.status_code, media_type=r.headers.get("content-type", "application/json"))

        async def relay():
            async with httpx.AsyncClient(timeout=300) as client:
                async with client.stream("POST", url, headers=headers, content=json.dumps(body)) as r:
                    async for chunk in r.aiter_bytes():
                        yield chunk

        return StreamingResponse(relay(), media_type="text/event-stream")

    @api.get("/")
    async def root():
        return {"ok": True, "upstream": UPSTREAM, "drops": sorted(DROP)}

    return api
