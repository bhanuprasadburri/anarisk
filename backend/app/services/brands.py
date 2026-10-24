from __future__ import annotations

import re
import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationFailure
from app.models import Brand, BrandReference, DigitalEntity, Organization, User
from app.models.base import utcnow
from app.models.enums import Provenance, ReferenceKind
from app.repositories.access import brand_scope, get_brand_for_user, is_admin
from app.schemas.brand import BrandCreate, BrandUpdate, ReferenceCreate
from app.services import audit
from app.services.official import normalize_reference
from app.utils.images import inspect_image, perceptual_hash, sha256_hex


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (s or "brand")[:100]


def create_brand(db: Session, actor: User, data: BrandCreate) -> Brand:
    if is_admin(actor):
        org_id = data.organization_id or actor.organization_id
        if org_id is None:
            raise ValidationFailure("organization_id is required")
    else:
        if actor.organization_id is None:
            raise ValidationFailure("Your account is not assigned to an organization")
        if data.organization_id and data.organization_id != actor.organization_id:
            raise NotFoundError("Organization not found")
        org_id = actor.organization_id
    if db.get(Organization, org_id) is None:
        raise NotFoundError("Organization not found")
    brand = Brand(organization_id=org_id, name=data.name.strip(), slug=data.slug or _slugify(data.name), description=data.description)
    db.add(brand)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ConflictError("A brand with this slug already exists in the organization", code="slug_taken")
    audit.record(db, actor, "brand.create", "brand", brand.id, details={"name": brand.name}, organization_id=org_id)
    db.commit()
    return brand


def list_brands(db: Session, actor: User, page: int, page_size: int, q: str | None = None):
    stmt = select(Brand).where(brand_scope(actor, Brand.id))
    if q:
        stmt = stmt.where(Brand.name.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Brand.name).offset((page - 1) * page_size).limit(page_size)).all()
    return rows, total


def brand_entity_count(db: Session, brand_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(DigitalEntity).where(DigitalEntity.brand_id == brand_id)) or 0


def update_brand(db: Session, actor: User, brand_id: uuid.UUID, data: BrandUpdate) -> Brand:
    brand = get_brand_for_user(db, actor, brand_id)
    changes = data.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(brand, k, v)
    audit.record(db, actor, "brand.update", "brand", brand.id, details=changes, organization_id=brand.organization_id)
    db.commit()
    return brand


def add_reference(db: Session, actor: User, brand_id: uuid.UUID, data: ReferenceCreate) -> BrandReference:
    brand = get_brand_for_user(db, actor, brand_id)
    ref = BrandReference(
        brand_id=brand.id, kind=data.kind, value=data.value.strip(), normalized_value=normalize_reference(data.kind, data.value),
        platform=data.platform, note=data.note, provenance=data.provenance,
        perceptual_hash=data.value.lower() if data.kind == ReferenceKind.IMAGE else None,
        verified_by=actor.id, verified_at=utcnow(), verification_source=data.verification_source,
    )
    return _save_reference(db, actor, brand, ref)


def add_image_reference(db: Session, actor: User, brand_id: uuid.UUID, data: bytes, note: str | None, provenance: Provenance = Provenance.MANUAL) -> BrandReference:
    brand = get_brand_for_user(db, actor, brand_id)
    info = inspect_image(data)
    sha, phash = sha256_hex(data), perceptual_hash(data)
    rel = Path("brand_refs") / str(brand.id) / f"{sha}.{info['extension']}"
    dest = Path(get_settings().upload_dir) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    ref = BrandReference(
        brand_id=brand.id, kind=ReferenceKind.IMAGE, value=phash, normalized_value=phash, perceptual_hash=phash, sha256=sha,
        file_path=str(rel), note=note, provenance=provenance,
        verified_by=actor.id, verified_at=utcnow(), verification_source=None,
    )
    return _save_reference(db, actor, brand, ref)


def _save_reference(db: Session, actor: User, brand: Brand, ref: BrandReference) -> BrandReference:
    db.add(ref)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ConflictError("This official reference is already registered for the brand", code="duplicate_reference")
    audit.record(db, actor, "brand.reference_add", "brand_reference", ref.id, details={"kind": ref.kind.value, "brand_id": str(brand.id)}, organization_id=brand.organization_id)
    db.commit()
    return ref


def delete_reference(db: Session, actor: User, brand_id: uuid.UUID, ref_id: uuid.UUID) -> None:
    brand = get_brand_for_user(db, actor, brand_id)
    ref = db.get(BrandReference, ref_id)
    if ref is None or ref.brand_id != brand.id:
        raise NotFoundError("Reference not found")
    audit.record(db, actor, "brand.reference_delete", "brand_reference", ref.id, details={"kind": ref.kind.value}, organization_id=brand.organization_id)
    db.delete(ref)
    db.commit()
