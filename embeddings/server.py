"""Lightweight, high-performance OpenAI-compatible Embeddings Service powered by FastEmbed (ONNX)."""

import logging
import os
import time
from typing import List, Union

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastembed import TextEmbedding
from pydantic import BaseModel, Field
import uvicorn

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
logger = logging.getLogger("embeddings-service")

MODEL_NAME = os.environ.get("EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v1.5")
PORT = int(os.environ.get("PORT", "8080"))

logger.info("Initializing embedding model: %s ...", MODEL_NAME)
embedding_model = TextEmbedding(model_name=MODEL_NAME)
logger.info("Model %s loaded successfully.", MODEL_NAME)

app = FastAPI(title="Pai-Stack Embeddings Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class EmbeddingRequest(BaseModel):
    input: Union[str, List[str]] = Field(..., description="The string or array of strings to embed.")
    model: str = Field(default=MODEL_NAME, description="Model identifier.")


class EmbeddingItem(BaseModel):
    object: str = "embedding"
    index: int
    embedding: List[float]


class UsageInfo(BaseModel):
    prompt_tokens: int = 0
    total_tokens: int = 0


class EmbeddingResponse(BaseModel):
    object: str = "list"
    data: List[EmbeddingItem]
    model: str
    usage: UsageInfo


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": MODEL_NAME,
    }


@app.post("/v1/embeddings", response_model=EmbeddingResponse)
def create_embeddings(req: EmbeddingRequest):
    started = time.time()
    inputs = [req.input] if isinstance(req.input, str) else req.input

    if not inputs:
        raise HTTPException(status_code=400, detail="Input cannot be empty")

    try:
        embeddings_generator = embedding_model.embed(inputs)
        data = []
        token_count_approx = 0

        for idx, emb in enumerate(embeddings_generator):
            data.append(
                EmbeddingItem(
                    index=idx,
                    embedding=emb.tolist(),
                )
            )
            token_count_approx += len(inputs[idx].split())

        elapsed_ms = (time.time() - started) * 1000
        logger.info("Embedded %d text(s) in %.2fms", len(inputs), elapsed_ms)

        return EmbeddingResponse(
            data=data,
            model=req.model or MODEL_NAME,
            usage=UsageInfo(
                prompt_tokens=token_count_approx,
                total_tokens=token_count_approx,
            ),
        )
    except Exception as e:
        logger.error("Failed to generate embeddings: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
