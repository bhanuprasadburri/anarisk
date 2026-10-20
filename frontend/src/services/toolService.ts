import { apiRequest, qs } from './apiClient';
import { ToolAnalysis } from '../types';

export interface ToolAnalysisListResponse {
  items: ToolAnalysis[];
  total: number;
  page: number;
  page_size: number;
}

export interface EmailAnalyzeInput {
  raw_email?: string;
  from_address?: string;
  from_name?: string;
  reply_to?: string;
  return_path?: string;
  subject?: string;
  body?: string;
  attachments?: Array<Record<string, unknown>>;
  claimed_brand?: string;
  claimed_domain?: string;
}

export interface JobAnalyzeInput {
  job_description?: string;
  offer_text?: string;
  employer_name?: string;
  employer_website?: string;
  recruiter_name?: string;
  recruiter_profile_url?: string;
  recruiter_email?: string;
  application_url?: string;
}

export interface SocialAnalyzeInput {
  platform?: string;
  profile_url?: string;
  handle?: string;
  display_name?: string;
  bio?: string;
  claimed_brand?: string;
}

export const toolService = {
  analyzeEmail(input: EmailAnalyzeInput): Promise<ToolAnalysis> {
    return apiRequest<ToolAnalysis>('/tools/email/analyze', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  analyzeJobOffer(input: JobAnalyzeInput): Promise<ToolAnalysis> {
    return apiRequest<ToolAnalysis>('/tools/job/analyze', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  analyzeSocialProfile(input: SocialAnalyzeInput): Promise<ToolAnalysis> {
    return apiRequest<ToolAnalysis>('/tools/social/analyze', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  analyzeUrl(input: { url: string; share_with_phishtank?: boolean }): Promise<ToolAnalysis> {
    return apiRequest<ToolAnalysis>('/tools/url/analyze', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  /** Multipart image review: content-validated upload + offline checks + optional AI review. */
  analyzeImage(file: File, context: 'email' | 'job_offer' | 'social_profile'): Promise<ToolAnalysis> {
    const form = new FormData();
    form.append('file', file);
    form.append('context', context);
    return apiRequest<ToolAnalysis>('/tools/image/analyze', { method: 'POST', body: form });
  },

  listAnalyses(params: { page?: number; page_size?: number; tool?: string } = {}): Promise<ToolAnalysisListResponse> {
    return apiRequest<ToolAnalysisListResponse>(`/tools/analyses${qs(params)}`);
  },

  getAnalysis(id: string): Promise<ToolAnalysis> {
    return apiRequest<ToolAnalysis>(`/tools/analyses/${id}`);
  },
};

export default toolService;
