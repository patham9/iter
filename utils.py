import os

# --------------------------------------------------------------------
# LLM call with refusal fallback:
# Always tries the primary model first. If no usable message is returned
# (refusal, empty message, content filter, or API error), the same request
# is retried once with LLM_BACKUP_MODEL (if set).
# --------------------------------------------------------------------
BACKUP_MODEL = os.getenv("LLM_BACKUP_MODEL", "")

def is_refusal(response):
    """True if the response did not return a usable LLM message."""
    try:
        choice = response.choices[0]
        message = choice.message
    except (AttributeError, IndexError, TypeError):
        return True
    if message is None:
        return True
    if str(getattr(choice, "finish_reason", "") or "").lower() in ("refusal", "content_filter"):
        return True
    if getattr(message, "refusal", None):
        return True
    return not (getattr(message, "content", None) or getattr(message, "tool_calls", None))

def chat_completion(client, model, backup_model=None, **kwargs):
    """Returns (response, used_model). Primary first, backup if no message returned."""
    backup_model = BACKUP_MODEL if backup_model is None else backup_model
    use_backup = bool(backup_model) and backup_model != model
    try:
        response = client.chat.completions.create(model=model, **kwargs)
        if not use_backup or not is_refusal(response):
            return response, model
    except Exception as error:
        if not use_backup:
            raise
        try:
            return client.chat.completions.create(model=backup_model, **kwargs), backup_model
        except Exception:
            raise error
    return client.chat.completions.create(model=backup_model, **kwargs), backup_model
