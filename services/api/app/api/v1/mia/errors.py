"""Mia's own 404: a conversation that is not this person's, this property's or this workspace's is
the same answer as one that does not exist (the id is a handle, never a credential)."""

from app.core.exceptions import AppError


class MiaConversationNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__("MIA_CONVERSATION_NOT_FOUND", "Conversation not found", status_code=404)


__all__ = ["MiaConversationNotFoundError"]
