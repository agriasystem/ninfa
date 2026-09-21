"""Stable, machine-readable error codes of Supplier Resolution.

Callers branch on the *code*. Details name kinds, counts and supplier ids only: never a VAT
number, a tax code, an IBAN or a hash.
"""

from enum import StrEnum
from http import HTTPStatus
from typing import Any

from app.core.exceptions import AppError


class SupplierErrorCode(StrEnum):
    # Stable identifiers of one record point at DIFFERENT suppliers (or contradict one supplier).
    IDENTITY_CONFLICT = "SUPPLIER_IDENTITY_CONFLICT"
    # An exact name/alias fits more than one supplier and nothing else can tell them apart.
    NAME_AMBIGUOUS = "SUPPLIER_NAME_AMBIGUOUS"


class SupplierError(AppError):
    def __init__(
        self,
        code: SupplierErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status_code: int = HTTPStatus.UNPROCESSABLE_ENTITY,
    ) -> None:
        super().__init__(code.value, message, status_code=status_code, details=details)
        self.error_code = code
