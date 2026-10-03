"""The only place that talks to AI providers. Swap a provider by editing this file."""

import math

from django.conf import settings

EMBEDDING_DIMENSIONS = 768


def _fit(vector):
    """Cut a vector to the stored size and rescale it to length 1."""
    vector = list(vector)[:EMBEDDING_DIMENSIONS]
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def _embedder():
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    return GoogleGenerativeAIEmbeddings(
        model=settings.EMBEDDING_MODEL, google_api_key=settings.GOOGLE_API_KEY
    )


def embed_documents(texts):
    texts = list(texts)
    try:
        vectors = _embedder().embed_documents(texts, output_dimensionality=EMBEDDING_DIMENSIONS)
    except TypeError:
        vectors = _embedder().embed_documents(texts)
    return [_fit(vector) for vector in vectors]


def embed_query(text):
    try:
        vector = _embedder().embed_query(text, output_dimensionality=EMBEDDING_DIMENSIONS)
    except TypeError:
        vector = _embedder().embed_query(text)
    return _fit(vector)


def get_chat_model(temperature=0):
    from langchain_groq import ChatGroq

    return ChatGroq(
        model=settings.LLM_MODEL, api_key=settings.GROQ_API_KEY, temperature=temperature
    )
