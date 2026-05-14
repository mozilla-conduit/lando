LOG_OUTPUT_HEAD_LIMIT = 500
LOG_OUTPUT_TAIL_LIMIT = 200


def truncate_text(text: str) -> str:
    """Trim long text to its head and tail.

    Useful for keeping log volume bounded for commands like `hg export` or
    `git format-patch` that emit an entire patch, while preserving the most
    diagnostically useful portions (commit metadata at the start, summary or
    error trailer at the end).
    """
    total = len(text)
    if total <= LOG_OUTPUT_HEAD_LIMIT + LOG_OUTPUT_TAIL_LIMIT:
        return text

    head = text[:LOG_OUTPUT_HEAD_LIMIT]
    tail = text[-LOG_OUTPUT_TAIL_LIMIT:]
    omitted = total - LOG_OUTPUT_HEAD_LIMIT - LOG_OUTPUT_TAIL_LIMIT
    return f"{head}\n...[{omitted} bytes omitted]...\n{tail}"
