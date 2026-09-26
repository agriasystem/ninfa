"""Authentication & Session V1 request/response DTOs.

`SessionContextResponse` is returned by BOTH a successful `POST /auth/login` and
`GET /auth/session` - the same shape, so a client never needs two parsers for "who is logged in
and what can they reach" (see docs/architecture/auth-session-v1.md, "Session context").
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):
    """No length/composition policy here: that is a PROVISIONING-time policy (`app.cli.auth`,
    min 14 / max 128 characters). Login must accept whatever password was once hashed, verbatim -
    rejecting a too-short string before even trying Argon2 would let a client distinguish "wrong
    length" from "wrong password", a shape enumeration channel this schema refuses to open."""

    model_config = ConfigDict(extra="forbid")

    email: str
    password: str


class PropertyAccess(BaseModel):
    """`timezone` (Gate 14): the Property's own canonical IANA zone (`app.modules.properties.
    models.Property.timezone`, non-nullable since Gate 1) - added additively here so a client can
    compute "today" in the property's own timezone without guessing the browser's."""

    id: UUID
    name: str
    slug: str
    timezone: str


class WorkspaceAccess(BaseModel):
    id: UUID
    name: str
    slug: str
    role: str
    properties: list[PropertyAccess]


class SessionUser(BaseModel):
    id: UUID
    email: str
    display_name: str | None


class SessionInfo(BaseModel):
    expires_at: datetime


class SessionContextResponse(BaseModel):
    user: SessionUser
    session: SessionInfo
    workspaces: list[WorkspaceAccess]


__all__ = [
    "LoginRequest",
    "PropertyAccess",
    "SessionContextResponse",
    "SessionInfo",
    "SessionUser",
    "WorkspaceAccess",
]
