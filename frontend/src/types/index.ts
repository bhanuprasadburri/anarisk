export type UserRole = 'administrator' | 'investigator' | 'brand_owner' | 'partner';

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  organization_id?: string;
  is_active: boolean;
  created_at: string;
  email_verified_at?: string | null;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export type EntityType = 'social_profile' | 'website' | 'domain' | 'image' | 'mobile_app';
export type Provenance = 'collected' | 'manual' | 'synthetic';
export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'unknown';
export type ReferenceKind = 'name' | 'handle' | 'domain' | 'image' | 'app_package' | 'publisher' | 'bio';
export type EvidenceKind = 'screenshot' | 'image' | 'text' | 'url' | 'url_inspection' | 'whois' | 'other';
export type SignalType = 'brand_logo' | 'impersonation' | 'url_risk' | 'behavior';
export type SignalStatus = 'ok' | 'unavailable' | 'failed';
export type RelationshipType = 'shares_image' | 'shares_domain' | 'similar_identity' | 'same_infrastructure' | 'coordinated_behavior';
export type CaseStatus = 'detected' | 'triaged' | 'under_review' | 'assigned' | 'escalated' | 'resolved';
export type PartnerType = 'legal' | 'marketing' | 'platform';
export type ResolutionOutcome =
  | 'confirmed_threat_actioned'
  | 'confirmed_threat_monitoring'
  | 'false_positive'
  | 'inconclusive'
  | 'duplicate';

/** Round 2 §7: the operational response to a threat, tracked separately from the disposition. */
export type ResponseOutcome = 'no_action' | 'report_drafted' | 'report_submitted' | 'removal_observed';

export interface BrandReference {
  id: string;
  brand_id: string;
  kind: ReferenceKind;
  value: string;
  platform?: string | null;
  perceptual_hash?: string | null;
  sha256?: string | null;
  note?: string | null;
  provenance: Provenance;
  created_at: string;
}

export interface Brand {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
  description?: string | null;
  is_active: boolean;
  is_synthetic: boolean;
  created_at: string;
  entity_count?: number;
  references?: BrandReference[];
}

export interface DetectionSignal {
  id: string;
  entity_id: string;
  assessment_id: string;
  signal_type: SignalType;
  status: SignalStatus;
  score: number | null;
  explanation: string;
  evidence_refs: Array<Record<string, any>>;
  metadata: Record<string, any>;
  created_at: string;
  /** Joined entity context (present on /detection/signals listings). */
  entity?: {
    id: string;
    display_name: string;
    entity_type: string;
    canonical_id: string;
    platform?: string | null;
    provenance: string;
  } | null;
}

export interface RiskAssessment {
  id: string;
  entity_id: string;
  model_version: string;
  configured_weights: Record<string, number>;
  effective_weights: Record<string, number>;
  component_scores: Record<string, number | null>;
  risk_score: number | null;
  confidence_score: number;
  confidence_breakdown: Record<string, any>;
  severity: Severity;
  thresholds: Record<string, number>;
  is_synthetic: boolean;
  notes?: string | null;
  assessed_at: string;
  signals: DetectionSignal[];
}

export interface DigitalEntity {
  id: string;
  brand_id: string;
  entity_type: EntityType;
  canonical_id: string;
  display_name: string;
  platform?: string | null;
  source_url?: string | null;
  provenance: Provenance;
  attributes: Record<string, any>;
  first_seen_at: string;
  last_seen_at: string;
  submission_count: number;
  current_risk_score: number | null;
  current_confidence: number | null;
  current_severity: Severity;
  last_assessed_at: string | null;
  created_at: string;
  latest_assessment?: RiskAssessment | null;
  evidence_count?: number;
  matches_official_reference?: string | null;
}

export interface EvidenceRecord {
  id: string;
  brand_id: string;
  entity_id?: string | null;
  kind: EvidenceKind;
  title: string;
  description?: string | null;
  source_url?: string | null;
  provenance: Provenance;
  content_type?: string | null;
  sha256?: string | null;
  size_bytes?: number | null;
  perceptual_hash?: string | null;
  has_file: boolean;
  file_name?: string | null;
  text_content?: string | null;
  metadata: Record<string, unknown>;
  verification_status: 'verified' | 'mismatch' | 'pending';
  case_ids: string[];
  collected_at: string;
  created_at: string;
}

export interface GraphNode {
  id: string;
  entity_type: EntityType;
  label: string;
  brand_id: string;
  risk_score: number | null;
  confidence: number | null;
  severity: Severity;
  provenance: string;
  cluster_id?: string | null;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  relationship_type: RelationshipType;
  confidence: number;
  evidence_id?: string | null;
  evidence_note: string;
  created_at: string;
  auto_generated: boolean;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  node_count: number;
  edge_count: number;
  cluster_count: number;
}

export interface ClusterSummary {
  cluster_id: string;
  size: number;
  entity_ids: string[];
  entity_type_counts: Record<string, number>;
  relationship_type_counts: Record<string, number>;
  brand_ids: string[];
  max_risk_score: number | null;
  mean_risk_score: number | null;
  mean_edge_confidence: number;
  max_severity: Severity;
  propose_for_investigation: boolean;
  proposal_reasons: string[];
  existing_case_ids: string[];
  headline: string;
}

export interface RelatedEntity {
  entity: GraphNode;
  distance: number;
  path_confidence: number;
  via: string[];
}

export interface CaseUserRef {
  id: string;
  email: string;
  full_name: string;
}

export interface CaseNote {
  id: string;
  case_id: string;
  author?: CaseUserRef | null;
  body: string;
  created_at: string;
}

export interface CaseEvent {
  id: string;
  case_id: string;
  event_type: string;
  from_status?: CaseStatus | null;
  to_status?: CaseStatus | null;
  actor?: CaseUserRef | null;
  details: Record<string, any>;
  created_at: string;
}

export interface CaseEscalation {
  id: string;
  case_id: string;
  partner_type: PartnerType;
  partner_contact?: string | null;
  reason: string;
  requested_action?: string | null;
  created_by_id?: string | null;
  created_at: string;
}

export interface CaseAssignment {
  id: string;
  case_id: string;
  assignee?: CaseUserRef | null;
  assigned_by_id?: string | null;
  assigned_at: string;
  unassigned_at?: string | null;
  note?: string | null;
}

export interface CaseEntityDetail {
  role: string;
  entity: DigitalEntity;
  latest_assessment?: RiskAssessment | null;
  evidence: EvidenceRecord[];
}

export interface InvestigationCase {
  id: string;
  case_number: string;
  brand_id: string;
  title: string;
  summary?: string | null;
  status: CaseStatus;
  severity: Severity;
  confidence: number | null;
  risk_score: number | null;
  assigned_to?: CaseUserRef | null;
  entity_count: number;
  created_at: string;
  updated_at: string;
  resolved_at?: string | null;
  cluster_key?: string | null;
  risk_assessment?: RiskAssessment | null;
  escalated_at?: string | null;
  escalation_summary?: string | null;
  resolution_outcome?: ResolutionOutcome | null;
  resolution_summary?: string | null;
  resolved_by?: CaseUserRef | null;
  response_outcome?: ResponseOutcome | null;
  response_outcome_at?: string | null;
  response_outcome_by?: CaseUserRef | null;
  response_evidence_id?: string | null;
  created_by?: CaseUserRef | null;
  entities?: CaseEntityDetail[];
  notes?: CaseNote[];
  events?: CaseEvent[];
  escalations?: CaseEscalation[];
  assignments?: CaseAssignment[];
  allowed_transitions?: CaseStatus[];
  version?: number;
  platforms?: string[];
}

export interface AuditLog {
  id: string;
  organization_id?: string | null;
  actor_id?: string | null;
  actor_email?: string | null;
  action: string;
  resource_type: string;
  resource_id?: string | null;
  details: Record<string, any>;
  ip_address?: string | null;
  created_at: string;
}

export interface DashboardStats {
  totals: {
    monitored_entities: number;
    high_risk_entities: number;
    unassessed_entities: number;
    open_cases: number;
    escalated_cases: number;
    unassigned_open_cases: number;
    resolved_cases: number;
  };
  risk_distribution: Record<string, number>;
  entity_type_distribution: Record<string, number>;
  data_provenance: Record<string, number>;
  case_status_distribution: Record<string, number>;
  recent_detections: DigitalEntity[];
  top_risk_entities: DigitalEntity[];
  latest_activity: Array<{
    case_id: string;
    case_number: string;
    case_title: string;
    event_type: string;
    from_status?: string | null;
    to_status?: string | null;
    actor_id?: string | null;
    created_at: string;
  }>;
}

export interface MobileAppRow extends DigitalEntity {
  app_name?: string | null;
  package_id?: string | null;
  store?: string | null;
  publisher_name?: string | null;
  publisher_verified: boolean;
  store_url?: string | null;
  permissions_status: 'collected_from_store_listing' | 'supplied_unverified' | 'not_provided';
  permissions_count: number;
  sensitive_permissions: string[];
  linked_websites: string[];
  cases: number;
}

export interface MobileAppsSummary {
  total_apps: number;
  by_severity: Record<string, number>;
  high_risk_apps: number;
  apps_with_cases: number;
  apps: MobileAppRow[];
  note?: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

/* ================= Extended types (Nimbus rebuild) ================= */

export interface NotificationItem {
  id: string;
  type: string;
  title: string;
  body?: string | null;
  link_url?: string | null;
  resource_type?: string | null;
  resource_id?: string | null;
  is_read: boolean;
  created_at: string;
}

export interface NotificationListResponse extends PaginatedResponse<NotificationItem> {
  unread_count: number;
}

export type FeedbackCategory = 'bug' | 'feature' | 'content' | 'other';
export type FeedbackStatus = 'open' | 'resolved';

export interface FeedbackItem {
  id: string;
  user_id: string;
  organization_id: string | null;
  brand_id: string | null;
  category: FeedbackCategory;
  message: string;
  page_ref?: string | null;
  related_case_id?: string | null;
  status: FeedbackStatus;
  user_email?: string | null;
  created_at: string;
  updated_at: string;
}

export interface IntegrationConfigField {
  key: string;
  label: string;
  type: 'text' | 'url' | 'secret' | 'select';
  required: boolean;
  placeholder?: string;
  options?: string[];
}

export interface IntegrationProvider {
  key: string;
  name: string;
  category: 'social' | 'app_store' | 'web' | 'infrastructure';
  description: string;
  requires_credentials: boolean;
  config_fields: IntegrationConfigField[];
  docs_url?: string | null;
  status: 'not_configured' | 'configured' | 'error';
  last_sync_at?: string | null;
  last_error?: string | null;
  config_preview?: Record<string, string> | null;
  connected_by?: { id: string; email: string; full_name: string } | null;
}

export interface IntegrationTestResult {
  ok: boolean;
  message: string;
  checked_at: string;
}

export interface MonitoringTarget {
  id: string;
  brand: { id: string; name: string };
  package_id: string;
  store: 'google_play' | 'app_store' | 'other';
  store_url?: string | null;
  monitoring_status: 'active' | 'paused';
  app_name?: string | null;
  publisher_name?: string | null;
  entity?: {
    id: string;
    display_name: string;
    risk_score: number | null;
    severity: Severity;
    confidence: number | null;
    provenance: Provenance;
    last_seen_at: string | null;
    source_url?: string | null;
  } | null;
  last_sync_at?: string | null;
  // background scheduler fields (DB-backed; -1/null when not scheduled)
  next_run_at?: string | null;
  retry_count?: number;
  last_run_status?: 'success' | 'failed' | null;
  created_at: string;
}

export interface MonitoringSyncResult {
  target: MonitoringTarget;
  entity: Record<string, unknown> | null;
  message: string;
}

export interface MonitoringCreateResult {
  target: MonitoringTarget;
  message: string;
}

export interface DetectionItem {
  id: string;
  entity: {
    id: string;
    display_name: string;
    entity_type: EntityType;
    canonical_id: string;
    platform?: string | null;
    provenance: Provenance;
    source_url?: string | null;
    first_seen_at?: string | null;
    last_seen_at?: string | null;
  };
  signal_type: SignalType;
  detection_type: string;
  risk_score: number | null;
  confidence: number | null;
  severity: Severity;
  status: 'analyzed' | 'partial' | 'unavailable';
  explanation: string;
  signals_summary: Array<{ signal_type: SignalType; status: SignalStatus; score: number | null }>;
  assessed_at: string;
  is_synthetic: boolean;
  /** Registered brand reference this detection was compared against, when matched. */
  matched_official_asset_id?: string | null;
}

export interface DetectionModelInfo {
  model_version: string;
  weights: Record<string, number>;
  severity_thresholds: Record<string, number>;
  confidence: Record<string, unknown>;
  rule_description?: Array<{ signal_type: string; label: string; rules: string }>;
  status?: string;
}

export interface EvidenceVerificationResult {
  sha256: string | null;
  stored_sha256: string | null;
  matches: boolean | null;
  verified_at: string;
}

export interface EvidenceListItem extends EvidenceRecord {
  verification_status: 'verified' | 'pending' | 'mismatch';
  case_ids: string[];
  entity?: { id: string; display_name: string; entity_type: EntityType } | null;
}

export interface ReportsOverview {
  generated_at: string;
  date_range: { from: string; to: string };
  totals: {
    entities: number;
    high_risk: number;
    critical: number;
    open_cases: number;
    escalated_cases: number;
    resolved_cases: number;
    detections: number;
    evidence: number;
    relationships: number;
  };
  threat_distribution: Record<string, number>;
  cases_by_status: Record<string, number>;
  risk_trend: Array<{ date: string; avg_risk: number | null; detections: number }>;
  threats_by_channel: Array<{ channel: string; count: number }>;
  top_connected_entities: Array<{
    entity_id: string;
    display_name: string;
    entity_type: EntityType;
    risk_score: number | null;
    relationship_count: number;
  }>;
  entity_type_distribution: Record<string, number>;
  severity_by_type: Array<{
    entity_type: EntityType;
    critical: number;
    high: number;
    medium: number;
    low: number;
    unknown: number;
  }>;
  mobile_apps: { total: number; high_risk: number; by_store: Array<{ store: string; count: number }> };
  evidence: {
    total: number;
    verified: number;
    pending: number;
    by_kind: Array<{ kind: string; count: number }>;
  };
  data_notes: string[];
}

export interface Organization {
  id: string;
  name: string;
  slug?: string;
  created_at?: string;
  member_count?: number;
  brand_count?: number;
}

export interface UserPreferences {
  notify_inapp?: boolean;
  notify_case_events?: boolean;
  notify_high_risk?: boolean;
  notify_evidence?: boolean;
  notify_digest?: boolean;
}

export interface CurrentUser extends User {
  preferences?: UserPreferences | null;
  organization?: Organization | null;
}

// ---- Investigation tools (email / job / social / url) ----
export type ToolKey = 'email' | 'job_offer' | 'social_profile' | 'url';
export type FindingStatus = 'verified' | 'suspicious' | 'inconclusive' | 'unable_to_verify' | 'info';
export type FindingSeverity = 'none' | 'low' | 'medium' | 'high' | 'critical' | 'unknown';

export interface ToolFinding {
  check: string;
  title: string;
  status: FindingStatus;
  severity: FindingSeverity;
  summary: string;
  evidence: string[];
  source: string;
  limitation?: string | null;
  weight: number;
}

export interface ToolAnalysis {
  id: string;
  organization_id?: string | null;
  created_by_id?: string | null;
  tool: ToolKey | 'image';
  subject: string;
  input_summary?: Record<string, unknown> | null;
  findings: ToolFinding[];
  risk_score?: number | null;
  severity: string;
  confidence?: number | null;
  methodology_version: string;
  created_at: string;
}

// ---- AI assistant ----
export interface AssistantCitation {
  type: string;
  id: string;
  title: string;
}

export interface AssistantAskResponse {
  answer: string;
  cited: AssistantCitation[];
  used_ai: boolean;
  provider: string;
  model: string;
  unsupported_citations: string[];
  limitation: string;
}

export interface AIStatus {
  provider: string;
  model?: string | null;
  configured: boolean;
  note: string;
}

// ---- Auth: email verification (OTP) ----
/**
 * Uniform registration result — the backend returns the same shape whether or not the
 * address already had an account (no enumeration). The account is NOT activated until
 * the emailed 6-digit code is confirmed.
 */
export interface RegisterResult {
  status?: string; // verification_required | delivery_failed
  email: string;
  verification_required?: boolean;
  email_sent?: boolean;
  /** Development-only fallback when no email provider is configured; never present in production. */
  dev_otp?: string | null;
  dev_only?: boolean;
}

/** Uniform resend result (accepted | cooldown); `dev_otp` only outside production. */
export interface ResendVerificationResult {
  status: string;
  email_sent?: boolean;
  retry_after_seconds?: number | null;
  dev_otp?: string | null;
  dev_only?: boolean;
}

export interface AuditLogEntry extends AuditLog {}

