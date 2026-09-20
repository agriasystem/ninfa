from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.validation import normalize_email
from app.modules.identity.models import User
from app.modules.identity.schemas import UserCreate


class UserRepository:
    """Users are global identities, not tenant-owned: this repository takes no tenant."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, data: UserCreate) -> User:
        user = User(email=data.email, display_name=data.display_name)
        self._session.add(user)
        self._session.flush()
        return user

    def get(self, user_id: UUID) -> User | None:
        return self._session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        return self._session.scalar(select(User).where(User.email == normalize_email(email)))

    def deactivate(self, user_id: UUID) -> User:
        user = self.get(user_id)
        if user is None:
            raise NotFoundError("User")
        user.is_active = False
        self._session.flush()
        return user
