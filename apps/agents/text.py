def text_of(content):
    """Model replies are usually a string, but can be a list of parts."""
    if isinstance(content, str):
        return content.strip()
    parts = []
    for part in content or []:
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, dict) and part.get("type") == "text":
            parts.append(part.get("text", ""))
    return "".join(parts).strip()
