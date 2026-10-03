from pathlib import Path

import environ
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_groq import ChatGroq

env = environ.Env()
environ.Env.read_env(Path(__file__).resolve().parent.parent / ".env")

GROQ_KEY = env("GROQ_API_KEY")
GOOGLE_KEY = env("GOOGLE_API_KEY")
CHAT_MODEL = env("LLM_MODEL", default="llama-3.3-70b-versatile")
EMBED_MODEL = env("EMBEDDING_MODEL", default="models/gemini-embedding-001")


def safe(exc):
    text = f"{type(exc).__name__}: {exc}"
    return text.replace(GROQ_KEY, "***").replace(GOOGLE_KEY, "***")[:400]


print("Chat model:", CHAT_MODEL)
try:
    llm = ChatGroq(model=CHAT_MODEL, api_key=GROQ_KEY, temperature=0)
    print("  Reply:", llm.invoke("Reply with the single word: ready").content)
except Exception as exc:
    print("  FAILED:", safe(exc))

print("Embedding model:", EMBED_MODEL)
try:
    emb = GoogleGenerativeAIEmbeddings(model=EMBED_MODEL, google_api_key=GOOGLE_KEY)
    vec = emb.embed_query("What is the notice period?", output_dimensionality=768)
    print("  Vector length:", len(vec))
except Exception as exc:
    print("  FAILED:", safe(exc))
