def text_of(content):
    """Return a model reply as plain text.

    Replies are usually a string but can be a list of parts. The chat page shows
    plain text, so markdown bold markers are removed.
    """
    if isinstance(content, str):
        text = content
    else:
        parts = []
        for part in content or []:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
        text = "".join(parts)
    return text.replace("**", "").strip()
