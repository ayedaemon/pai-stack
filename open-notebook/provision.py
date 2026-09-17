#!/usr/bin/env python3
"""
Open Notebook auto-provisioning script for pai-stack.

Configures:
1. Cluster Embeddings: OpenAI-compatible endpoint at http://embeddings:8080/v1
   with model nomic-ai/nomic-embed-text-v1.5 and assigns as default embedding model.
2. OpenRouter: Fallback cloud key and popular language models.
3. Mistral: Fallback cloud key and models.
4. Default model assignments (chat and embedding).
"""

import asyncio
import os
import sys
from pydantic import SecretStr
from loguru import logger

from open_notebook.domain.credential import Credential
from open_notebook.ai.models import Model, DefaultModels
from open_notebook.database.repository import repo_query
from open_notebook.ai.connection_tester import test_individual_model


async def provision_cluster_embeddings():
    """Connect pai-stack cluster embedding service (embeddings:8080) to Open Notebook."""
    logger.info("--- Provisioning Cluster Embeddings ---")
    base_url = os.environ.get("OPENAI_COMPATIBLE_BASE_URL", "http://embeddings:8080/v1").rstrip("/")
    model_name = os.environ.get("OPENAI_EMBEDDING_MODEL", os.environ.get("EMBEDDING_MODEL", "nomic-ai/nomic-embed-text-v1.5"))

    # 1. Ensure Credential
    existing_creds = await repo_query(
        "SELECT * FROM credential WHERE base_url = $url",
        {"url": base_url},
    )
    if not existing_creds:
        cred = Credential(
            name="Cluster Embeddings",
            provider="openai_compatible",
            modalities=["embedding"],
            base_url=base_url,
            api_key=SecretStr("not-needed"),
        )
        await cred.save()
        cred_id = cred.id
        logger.info(f"Created Cluster Embeddings credential: {cred_id}")
    else:
        cred_id = existing_creds[0]["id"]
        logger.info(f"Found existing Cluster Embeddings credential: {cred_id}")

    # 2. Ensure Model
    existing_models = await repo_query(
        "SELECT * FROM model WHERE name = $name AND type = 'embedding'",
        {"name": model_name},
    )
    if not existing_models:
        model = Model(
            name=model_name,
            provider="openai_compatible",
            type="embedding",
            credential=cred_id,
        )
        await model.save()
        model_id = model.id
        logger.info(f"Created embedding model record: {model_id} ({model_name})")
    else:
        model_id = existing_models[0]["id"]
        m = Model(**existing_models[0])
        if m.credential != cred_id:
            m.credential = cred_id
            await m.save()
        logger.info(f"Found existing embedding model record: {model_id} ({model_name})")

    # 3. Test Model
    try:
        m_obj = await Model.get(model_id)
        success, msg = await test_individual_model(m_obj)
        logger.info(f"Cluster Embeddings test result: success={success}, msg={msg}")
    except Exception as e:
        logger.warning(f"Could not test embedding model: {e}")

    # 4. Set as Default Embedding Model
    defaults = await DefaultModels.get_instance()
    if defaults.default_embedding_model != model_id:
        defaults.default_embedding_model = model_id
        await defaults.update()
        logger.info(f"Assigned default_embedding_model = {model_id}")
    else:
        logger.info(f"default_embedding_model already set to {model_id}")


async def provision_openrouter():
    """Configure OpenRouter fallback key and models if key is present."""
    logger.info("--- Checking OpenRouter ---")
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not openrouter_key:
        logger.info("OPENROUTER_API_KEY not provided, skipping OpenRouter provisioning.")
        return

    existing_creds = await Credential.get_by_provider("openrouter")
    if not existing_creds:
        cred = Credential(
            name="OpenRouter (Fallback)",
            provider="openrouter",
            modalities=["language"],
            api_key=SecretStr(openrouter_key),
        )
        await cred.save()
        cred_id = cred.id
        logger.info(f"Created OpenRouter credential: {cred_id}")
    else:
        cred_id = existing_creds[0].id
        if not existing_creds[0].api_key or existing_creds[0].api_key.get_secret_value() != openrouter_key:
            existing_creds[0].api_key = SecretStr(openrouter_key)
            await existing_creds[0].save()
            logger.info("Updated OpenRouter API key.")
        logger.info(f"Found OpenRouter credential: {cred_id}")

    # Register popular language models
    models_to_ensure = [
        "openai/gpt-4o-mini",
        "anthropic/claude-3-haiku",
        "meta-llama/llama-3.3-70b-instruct",
        "deepseek/deepseek-chat",
        "mistralai/mistral-nemo",
        "openrouter/auto",
    ]
    for m_name in models_to_ensure:
        exists = await repo_query(
            "SELECT * FROM model WHERE name = $name AND provider = 'openrouter'",
            {"name": m_name},
        )
        if not exists:
            new_model = Model(
                name=m_name,
                provider="openrouter",
                type="language",
                credential=cred_id,
            )
            await new_model.save()
            logger.info(f"Registered OpenRouter model: {m_name}")


async def provision_mistral():
    """Configure Mistral fallback key and models if key is present."""
    logger.info("--- Checking Mistral ---")
    mistral_key = os.environ.get("MISTRAL_API_KEY", "").strip()
    if not mistral_key:
        logger.info("MISTRAL_API_KEY not provided, skipping Mistral provisioning.")
        return

    existing_creds = await Credential.get_by_provider("mistral")
    if not existing_creds:
        cred = Credential(
            name="Mistral (Fallback)",
            provider="mistral",
            modalities=["language"],
            api_key=SecretStr(mistral_key),
        )
        await cred.save()
        cred_id = cred.id
        logger.info(f"Created Mistral credential: {cred_id}")
    else:
        cred_id = existing_creds[0].id
        if not existing_creds[0].api_key or existing_creds[0].api_key.get_secret_value() != mistral_key:
            existing_creds[0].api_key = SecretStr(mistral_key)
            await existing_creds[0].save()
            logger.info("Updated Mistral API key.")
        logger.info(f"Found Mistral credential: {cred_id}")

    # Register popular Mistral models
    models_to_ensure = [
        "codestral-2508",
        "codestral-latest",
        "mistral-small-2603",
        "mistral-medium-latest",
        "mistral-large-latest",
    ]
    for m_name in models_to_ensure:
        exists = await repo_query(
            "SELECT * FROM model WHERE name = $name AND provider = 'mistral'",
            {"name": m_name},
        )
        if not exists:
            new_model = Model(
                name=m_name,
                provider="mistral",
                type="language",
                credential=cred_id,
            )
            await new_model.save()
            logger.info(f"Registered Mistral model: {m_name}")


async def provision_llm_gateway():
    """Connect pai-stack LiteLLM gateway service (http://llm-gateway:4000/v1) to Open Notebook."""
    logger.info("--- Provisioning LLM Gateway ---")
    base_url = os.environ.get("OPENAI_BASE_URL", "http://llm-gateway:4000/v1").rstrip("/")
    api_key = os.environ.get("OPENAI_API_KEY", "not-needed")
    default_model_name = os.environ.get("OPENAI_DEFAULT_MODEL", "default")

    # 1. Ensure Credential
    existing_creds = await repo_query(
        "SELECT * FROM credential WHERE base_url = $url",
        {"url": base_url},
    )
    if not existing_creds:
        cred = Credential(
            name="LLM Gateway",
            provider="openai_compatible",
            modalities=["language"],
            base_url=base_url,
            api_key=SecretStr(api_key),
        )
        await cred.save()
        cred_id = cred.id
        logger.info(f"Created LLM Gateway credential: {cred_id}")
    else:
        cred_id = existing_creds[0]["id"]
        c = Credential(**existing_creds[0])
        if not c.api_key or c.api_key.get_secret_value() != api_key:
            c.api_key = SecretStr(api_key)
            await c.save()
        logger.info(f"Found existing LLM Gateway credential: {cred_id}")

    # 2. Query models from gateway and ensure records
    models_to_ensure = [default_model_name]
    try:
        import urllib.request
        import json
        req = urllib.request.Request(f"{base_url}/models", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for item in data.get("data", []):
                mid = item.get("id")
                # Exclude embedding models from language model list
                if mid and mid not in models_to_ensure and not any(k in mid.lower() for k in ("embed", "ada-002")):
                    models_to_ensure.append(mid)
    except Exception as e:
        logger.warning(f"Could not query live models from gateway, using defaults: {e}")
        models_to_ensure.extend([
            "openrouter/openai/gpt-4o-mini",
            "mistral/codestral-latest",
            "kilo/kilo-auto/free",
        ])
    for m_name in models_to_ensure:
        existing_models = await repo_query(
            "SELECT * FROM model WHERE name = $name AND type = 'language'",
            {"name": m_name},
        )
        if not existing_models:
            model = Model(
                name=m_name,
                provider="openai_compatible",
                type="language",
                credential=cred_id,
            )
            await model.save()
            logger.info(f"Registered gateway model record: {m_name}")
        else:
            m = Model(**existing_models[0])
            if m.credential != cred_id:
                m.credential = cred_id
                await m.save()
            logger.info(f"Found existing model record: {m_name}")

    # 3. Set Default Chat Model
    defaults = await DefaultModels.get_instance()
    default_row = await repo_query(
        "SELECT * FROM model WHERE name = $name AND type = 'language' LIMIT 1",
        {"name": default_model_name},
    )
    if default_row:
        defaults.default_chat_model = default_row[0]["id"]
        await defaults.update()
        logger.info(f"Assigned default_chat_model = {defaults.default_chat_model} ({default_model_name})")


async def ensure_default_chat_model():
    """Ensure a working default chat model is selected if not already configured."""
    logger.info("--- Checking Default Chat Model ---")
    defaults = await DefaultModels.get_instance()
    if not defaults.default_chat_model:
        preferred = ["default", "codestral-2508", "openai/gpt-4o-mini", "codestral-latest", "mistral-small-2603"]
        for p in preferred:
            rows = await repo_query("SELECT * FROM model WHERE name = $name AND type = 'language' LIMIT 1", {"name": p})
            if rows:
                defaults.default_chat_model = rows[0]["id"]
                await defaults.update()
                logger.info(f"Assigned default_chat_model = {defaults.default_chat_model} ({p})")
                return

        any_lang = await repo_query("SELECT * FROM model WHERE type = 'language' LIMIT 1")
        if any_lang:
            defaults.default_chat_model = any_lang[0]["id"]
            await defaults.update()
            logger.info(f"Assigned default_chat_model = {defaults.default_chat_model}")


async def main():
    logger.info("Starting Open Notebook auto-provisioning...")
    try:
        await provision_cluster_embeddings()
    except Exception as e:
        logger.error(f"Cluster embeddings provisioning failed: {e}")

    try:
        await provision_llm_gateway()
    except Exception as e:
        logger.error(f"LLM Gateway provisioning failed: {e}")

    try:
        await provision_openrouter()
    except Exception as e:
        logger.error(f"OpenRouter provisioning failed: {e}")

    try:
        await provision_mistral()
    except Exception as e:
        logger.error(f"Mistral provisioning failed: {e}")

    try:
        await ensure_default_chat_model()
    except Exception as e:
        logger.error(f"Default chat model assignment failed: {e}")

    logger.info("Open Notebook auto-provisioning completed.")


if __name__ == "__main__":
    asyncio.run(main())
