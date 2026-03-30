from __future__ import annotations

from controltower.services.identity_reconciliation import (
    IdentityReconciliationService,
    slugify_code,
)


IdentityRegistry = IdentityReconciliationService

__all__ = ["IdentityRegistry", "IdentityReconciliationService", "slugify_code"]
