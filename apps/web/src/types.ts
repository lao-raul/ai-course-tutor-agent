// API contract types matching course_tutor_contracts

export interface ChatCitation {
  chunk_id: string;
  relative_path: string;
  anchor_type: string;
  anchor_value: string;
  text_excerpt: string;
}

export interface ChatRequest {
  query: string;
  access_label: AccessLabel;
  session_id?: string;
}

export type AccessLabel = 'public' | 'enrolled' | 'staff_only' | 'restricted';

export interface Course {
  id: string;
  code: string;
  name: string;
  level: string;
  tenant_id: string;
  active_content_version_id?: string;
}

export interface SourceRoot {
  id: string;
  tenant_id: string;
  absolute_path: string;
}

export interface ContentVersion {
  id: string;
  course_id: string;
  status: 'pending' | 'building' | 'ready' | 'published' | 'failed' | 'rolled_back';
}

export interface IngestResponse {
  tenant_id: string;
  course_id: string;
  source_root_id: string;
  version_id: string;
  job_id: string;
  resolved_path: string;
}

export interface IngestionStatusResponse {
  job_id: string;
  topic: string;
  status: 'pending' | 'processed' | 'dead_lettered';
  attempts: number;
  processed_at?: string;
  dead_lettered_at?: string;
  last_error?: string;
}
