def split_text(text, size=500, overlap=100):
    """Split text into overlapping chunks that start and end on word boundaries."""
    text = " ".join(text.split())
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            space = text.rfind(" ", start, end)
            if space > start + size // 2:
                end = space
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap
        next_space = text.find(" ", start, end)
        if next_space != -1:
            start = next_space + 1
    return chunks
