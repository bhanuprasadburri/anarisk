from __future__ import annotations

import enum


class UserRole(str, enum.Enum):
    ADMIN = "administrator"
    INVESTIGATOR = "investigator"
    BRAND_OWNER = "brand_owner"
    PARTNER = "partner"


class EntityType(str, enum.Enum):
    SOCIAL_PROFILE = "social_profile"
    WEBSITE = "website"
    DOMAIN = "domain"
    IMAGE = "image"
    MOBILE_APP = "mobile_app"


class Provenance(str, enum.Enum):
    """Where the data came from. Never conflated in responses or confidence scoring."""

    COLLECTED = "collected"  # fetched by a configured connector from a public source
    MANUAL = "manual"  # typed/submitted by a human; unverified
    SYNTHETIC = "synthetic"  # demonstration / sample data


class SourceKind(str, enum.Enum):
    MANUAL = "manual"
    CONNECTOR = "connector"
    SYNTHETIC = "synthetic"


class ReferenceKind(str, enum.Enum):
    NAME = "name"
    HANDLE = "handle"
    DOMAIN = "domain"
    IMAGE = "image"
    APP_PACKAGE = "app_package"
    PUBLISHER = "publisher"
    BIO = "bio"


class EvidenceKind(str, enum.Enum):
    SCREENSHOT = "screenshot"
    IMAGE = "image"
    TEXT = "text"
    URL = "url"
    URL_INSPECTION = "url_inspection"
    WHOIS = "whois"
    OTHER = "other"


class SignalType(str, enum.Enum):
    BRAND_LOGO = "brand_logo"
    IMPERSONATION = "impersonation"
    URL_RISK = "url_risk"
    BEHAVIOR = "behavior"


class SignalStatus(str, enum.Enum):
    OK = "ok"
    UNAVAILABLE = "unavailable"  # required input missing: NOT zero risk
    FAILED = "failed"  # the detector raised an error


class Severity(str, enum.Enum):
    UNKNOWN = "unknown"  # no signal available
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RelationshipType(str, enum.Enum):
    SHARES_IMAGE = "shares_image"
    SHARES_DOMAIN = "shares_domain"
    SIMILAR_IDENTITY = "similar_identity"
    SAME_INFRASTRUCTURE = "same_infrastructure"
    COORDINATED_BEHAVIOR = "coordinated_behavior"


class CaseStatus(str, enum.Enum):
    DETECTED = "detected"
    TRIAGED = "triaged"
    UNDER_REVIEW = "under_review"
    ASSIGNED = "assigned"
    ESCALATED = "escalated"
    RESOLVED = "resolved"


class PartnerType(str, enum.Enum):
    LEGAL = "legal"
    MARKETING = "marketing"
    PLATFORM = "platform"


class ResolutionOutcome(str, enum.Enum):
    CONFIRMED_THREAT_ACTIONED = "confirmed_threat_actioned"
    CONFIRMED_THREAT_MONITORING = "confirmed_threat_monitoring"
    FALSE_POSITIVE = "false_positive"
    INCONCLUSIVE = "inconclusive"
    DUPLICATE = "duplicate"


class CaseEventType(str, enum.Enum):
    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    ASSIGNED = "assigned"
    REASSIGNED = "reassigned"
    NOTE_ADDED = "note_added"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    REOPENED = "reopened"
    ENTITY_ADDED = "entity_added"
    ENTITY_REMOVED = "entity_removed"


class FeedbackCategory(str, enum.Enum):
    """What kind of feedback a submission is (drives triage in the admin view)."""

    BUG = "bug"
    FEATURE = "feature"
    CONTENT = "content"
    OTHER = "other"


class FeedbackStatus(str, enum.Enum):
    OPEN = "open"
    RESOLVED = "resolved"
