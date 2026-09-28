"""LangChain OpenAI bilesenleri: sohbet modeli ve embedding servisi."""

from __future__ import annotations

from functools import lru_cache

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from backend.config import get_settings


@lru_cache
def get_llm() -> ChatOpenAI:
    s = get_settings()
    return ChatOpenAI(model=s.llm_model, temperature=0, api_key=s.openai_api_key)


@lru_cache
def get_embeddings() -> OpenAIEmbeddings:
    """CV'ler ve ilanlar ayni model/boyut ile embed edilir."""
    return _embeddings()


@lru_cache
def get_store_embeddings() -> OpenAIEmbeddings:
    """PGVectorStore'lara verilen ayri istemci. Store'lar PGEngine'in kendi event loop'unda embed eder;
    istemcinin async baglantilari ilk kullanildigi loop'a baglandigi icin get_embeddings() ile paylasilirsa
    (ör. CV yukleyip ayni surecte eslestirince) 'bound to a different event loop' hatasi olusur."""
    return _embeddings()


def _embeddings() -> OpenAIEmbeddings:
    s = get_settings()
    return OpenAIEmbeddings(
        model=s.embedding_model,
        dimensions=s.embedding_dim,
        chunk_size=s.embedding_batch_size,
        api_key=s.openai_api_key,
    )
