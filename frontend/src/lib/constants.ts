export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

export const ENTITY_TYPE_LABELS: Record<string, string> = {
  social_profile: 'Social Profile',
  website: 'Website',
  domain: 'Domain',
  image: 'Image',
  mobile_app: 'Mobile App',
};

export const ENTITY_TYPE_COLORS: Record<string, string> = {
  social_profile: '#8B5CF6',
  website: '#4778F5',
  domain: '#10B981',
  image: '#F59E0B',
  mobile_app: '#20C5D7',
};

export const PLATFORM_LABELS: Record<string, string> = {
  x: 'X (Twitter)',
  twitter: 'X (Twitter)',
  instagram: 'Instagram',
  facebook: 'Facebook',
  tiktok: 'TikTok',
  youtube: 'YouTube',
  google_play: 'Google Play',
  app_store: 'App Store',
  linkedin: 'LinkedIn',
  reddit: 'Reddit',
  web: 'Web',
  other: 'Other',
};

export const SEVERITY_LABELS: Record<string, string> = {
  critical: 'Critical',
  high: 'High',
  medium: 'Medium',
  low: 'Low',
  unknown: 'Unknown',
};

export const CASE_STATUS_LABELS: Record<string, string> = {
  detected: 'Detected',
  triaged: 'Triaged',
  under_review: 'Under Review',
  assigned: 'Assigned',
  escalated: 'Escalated',
  resolved: 'Resolved',
};

export const RELATIONSHIP_LABELS: Record<string, string> = {
  shares_image: 'Shares Image',
  shares_domain: 'Shares Domain',
  similar_identity: 'Similar Identity',
  same_infrastructure: 'Shared Infrastructure',
  coordinated_behavior: 'Coordinated Behavior',
};

export const RELATIONSHIP_COLORS: Record<string, string> = {
  shares_image: '#F59E0B',
  shares_domain: '#4778F5',
  similar_identity: '#8B5CF6',
  same_infrastructure: '#10B981',
  coordinated_behavior: '#F04464',
};

export const SIGNAL_TYPE_LABELS: Record<string, string> = {
  brand_logo: 'Brand & Logo Similarity',
  impersonation: 'Impersonation',
  url_risk: 'Suspicious Links',
  behavior: 'Account Behavior',
};

export const SIGNAL_STATUS_LABELS: Record<string, string> = {
  ok: 'Analyzed',
  unavailable: 'Unavailable',
  failed: 'Failed',
};

export const DETECTION_STATUS_LABELS: Record<string, string> = {
  analyzed: 'Analyzed',
  partial: 'Partial',
  unavailable: 'Unavailable',
};

export const RESOLUTION_OUTCOME_LABELS: Record<string, string> = {
  confirmed_threat_actioned: 'Confirmed Threat (Actioned)',
  confirmed_threat_monitoring: 'Confirmed Threat (Monitoring)',
  false_positive: 'False Positive',
  inconclusive: 'Inconclusive',
  duplicate: 'Duplicate Case',
};

export const EVIDENCE_KIND_LABELS: Record<string, string> = {
  screenshot: 'Screenshot',
  image: 'Image',
  text: 'Text',
  url: 'URL',
  url_inspection: 'URL Inspection',
  whois: 'WHOIS',
  other: 'Other',
};

export const VERIFICATION_LABELS: Record<string, string> = {
  verified: 'Verified',
  pending: 'Pending',
  mismatch: 'Mismatch',
};

export const USER_ROLE_LABELS: Record<string, string> = {
  administrator: 'Administrator',
  investigator: 'Investigator',
  brand_owner: 'Brand Owner',
  partner: 'Partner',
};

export const STORE_LABELS: Record<string, string> = {
  google_play: 'Google Play',
  app_store: 'App Store',
  other: 'Other',
};
