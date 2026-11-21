from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from qdrant_client import QdrantClient

from docint import config


def embeddings():
    return OpenAIEmbeddings(model=config.EMBED_MODEL)


def client():
    if config.QDRANT_URL:
        return QdrantClient(url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY)
    return QdrantClient(path=str(config.ROOT / "qdrant_data"))


def chat_llm(**kw):
    return ChatOpenAI(model=config.CHAT_MODEL, reasoning_effort=config.CHAT_REASONING, timeout=kw.pop("timeout", 40),
                      max_retries=kw.pop("max_retries", 1), **kw)
