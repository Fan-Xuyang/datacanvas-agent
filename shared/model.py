import json
import os
import re
import time
from openai import AsyncOpenAI


def configured():
    return bool(api_key())


def api_key():
    return os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY")


def base_url():
    return os.getenv("AI_BASE_URL") or os.getenv(
        "OPENAI_BASE_URL", "https://api.openai.com/v1"
    )


async def structured(system, payload, schema):
    key = api_key()
    if not key:
        raise ValueError("请先在本地 .env 配置模型密钥。")
    started = time.monotonic()
    async with AsyncOpenAI(
        api_key=key,
        base_url=base_url(),
        timeout=45,
        max_retries=1,
    ) as client:
        response = await client.chat.completions.create(
            model=os.getenv("AI_MODEL", "deepseek-chat"),
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": system
                    + "\n只返回符合以下 JSON Schema 的 JSON 对象："
                    + json.dumps(schema.model_json_schema(), ensure_ascii=False),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        )
    text = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        (response.choices[0].message.content or "").strip(),
    )
    data = schema.model_validate_json(text)
    usage = response.usage
    return data, {
        "latency_ms": round((time.monotonic() - started) * 1000),
        "input_tokens": usage.prompt_tokens if usage else None,
        "output_tokens": usage.completion_tokens if usage else None,
    }


async def embed_texts(texts):
    """Generate embeddings through an OpenAI-compatible provider when configured."""
    key = os.getenv("AI_EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY")
    model = os.getenv("AI_EMBEDDING_MODEL")
    if not key or not model:
        return None, {"latency_ms": 0, "input_tokens": 0, "model": None}
    started = time.monotonic()
    vectors = []
    total_tokens = 0
    async with AsyncOpenAI(
        api_key=key,
        base_url=os.getenv("AI_EMBEDDING_BASE_URL")
        or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        timeout=45,
        max_retries=1,
    ) as client:
        for offset in range(0, len(texts), 64):
            response = await client.embeddings.create(
                model=model,
                input=texts[offset : offset + 64],
            )
            vectors.extend(item.embedding for item in response.data)
            total_tokens += response.usage.prompt_tokens if response.usage else 0
    return vectors, {
        "latency_ms": round((time.monotonic() - started) * 1000),
        "input_tokens": total_tokens,
        "model": model,
    }
