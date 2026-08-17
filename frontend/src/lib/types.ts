export type LeadStatus =
  | "NEW"
  | "CALLED"
  | "NO_ANSWER"
  | "BUSY"
  | "GATEKEEPER"
  | "CALLBACK"
  | "INTERESTED"
  | "DESIGN_REQUESTED"
  | "DESIGN_SENT"
  | "FOLLOW_UP"
  | "NOT_INTERESTED"
  | "DO_NOT_CALL"
  | "QUALIFIED"
  | "HANDOFF_TO_MANAGEMENT";

export type PreferredContact = "EMAIL" | "WHATSAPP" | "UNKNOWN";

export interface Lead {
  id: number;
  unternehmen: string;
  ansprechpartner: string | null;
  branche: string | null;
  website_url: string | null;
  telefonnummer: string;
  email: string | null;
  notizen: string | null;
  online_auftritt_geprueft: boolean;
  entwurf_vorhanden: boolean;
  entwurf_link: string | null;
  status: LeadStatus;
  preferred_contact: PreferredContact;
  do_not_call: boolean;
  callback_note: string | null;
  callback_at: string | null;
}

export type CallStatusValue =
  | "CREATED"
  | "RINGING"
  | "ANSWERED"
  | "BUSY"
  | "NO_ANSWER"
  | "FAILED"
  | "HANGUP"
  | "COMPLETED";

export type CallResultValue =
  | "INTERESTED"
  | "NOT_INTERESTED"
  | "DESIGN_SENT"
  | "CALLBACK_REQUESTED"
  | "DO_NOT_CALL"
  | "GATEKEEPER_ONLY"
  | "NO_ANSWER"
  | "UNKNOWN";

export interface Call {
  id: number;
  lead_id: number;
  campaign_id: number | null;
  status: CallStatusValue;
  result: CallResultValue | null;
  started_at: string | null;
  ended_at: string | null;
  duration: number | null;
  summary: string | null;
  transcript: string | null;
  twilio_call_sid: string | null;
}

export type CampaignStatusValue = "DRAFT" | "RUNNING" | "PAUSED" | "STOPPED" | "COMPLETED";

export interface Campaign {
  id: number;
  name: string;
  status: CampaignStatusValue;
  total_count: number;
  processed_count: number;
  active_count: number;
  max_concurrent: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface PromptVersion {
  id: number;
  version_number: number;
  content: string;
  label: string | null;
  is_active: boolean;
  created_at: string;
}

export interface VoiceProfile {
  id: number;
  name: string;
  is_active: boolean;
  is_builtin: boolean;
  exaggeration: number;
  cfg_weight: number;
  temperature: number;
  created_at: string;
}

export interface DoNotCallEntry {
  id: number;
  telefonnummer: string;
  reason: string | null;
  created_at: string;
}

export interface TelephonyStatus {
  provider: string;
  configured: boolean;
  connected: boolean;
  detail: string;
  caller_id: string | null;
  account_sid_masked: string | null;
  public_base_url_configured: boolean;
}

export interface DashboardSettings {
  values: Record<string, string>;
  readonly_info: Record<string, string>;
}

export interface CsvPreviewRow {
  data: Record<string, string>;
  valid: boolean;
  errors: string[];
}

export interface CsvPreview {
  headers: string[];
  columns_detected: Record<string, string>;
  rows: CsvPreviewRow[];
  total: number;
  valid_count: number;
  invalid_count: number;
}

export interface ActiveCallStatus {
  call_id: number;
  campaign_id: number | null;
  lead_id: number;
  unternehmen: string | null;
  ansprechpartner: string | null;
  telefonnummer: string | null;
  status: CallStatusValue;
  status_label: string;
  started_at: string | null;
}
