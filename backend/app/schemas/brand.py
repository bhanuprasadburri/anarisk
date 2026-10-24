from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.enums import Provenance, ReferenceKind
from app.schemas.common import ORM
from app.utils.images import is_valid_phash


class BrandCreate(BaseModel):
    organization_id: uuid.UUID | None = None  # admins may target any org; others default to their own
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(None, min_length=2, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")
    description: str | None = Field(None, max_length=4000)


class BrandUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=4000)
    is_active: bool | None = None


class ReferenceCreate(BaseModel):
    kind: ReferenceKind
    value: str = Field(min_length=1, max_length=4000, description="Text value, or a 16-hex-char perceptual hash for kind=image")
    platform: str | None = Field(None, max_length=64)
    note: str | None = Field(None, max_length=500)
    provenance: Provenance = Provenance.MANUAL
    verification_source: str | None = Field(
        None, max_length=500, description="How this official asset was verified, e.g. 'brand-owned domain'"
    )

    @model_validator(mode="after")
    def _check(self):
        if self.kind == ReferenceKind.IMAGE and not is_valid_phash(self.value):
            raise ValueError("kind=image requires a 16 hex character perceptual hash; or use the image upload endpoint")
        if self.provenance == Provenance.COLLECTED:
            raise ValueError("provenance 'collected' is reserved for connectors")
        return self


class ReferenceOut(ORM):
    id: uuid.UUID
    brand_id: uuid.UUID
    kind: ReferenceKind
    value: str
    platform: str | None
    perceptual_hash: str | None
    sha256: str | None
    note: str | None
    provenance: Provenance
    verified_by: uuid.UUID | None = None
    verified_at: datetime | None = None
    verification_source: str | None = None
    created_at: datetime


class BrandOut(ORM):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    slug: str
    description: str | None
    is_active: bool
    is_synthetic: bool
    created_at: datetime


class BrandDetail(BrandOut):
    references: list[ReferenceOut] = []
    entity_count: int = 0
