export type AgentStatus = "completed" | "needs_input" | "failed";

export interface UserFact {
  satisfied: boolean;
  amount_won?: number | null;
  months?: number | null;
  count?: number | null;
  channel?: string | null;
}

export interface UserProfile {
  monthly_deposit_won: number;
  term_months: number;
  facts: Record<string, UserFact>;
}

export interface BonusResult {
  bonus_id: string;
  label: string;
  rate_bps: number;
  satisfied: boolean;
  evidence_quote: string;
}

export interface ProductResult {
  product_key: string;
  institution_name: string;
  product_name: string;
  reserve_type: string;
  term_months: number;
  base_rate_bps: number;
  achieved_rate_bps: number;
  max_rate_bps: number;
  after_tax_interest_won: number;
  maturity_amount_won: number;
  eligibility_warning: boolean;
  bonuses: BonusResult[];
}

export interface AskResponse {
  thread_id: string;
  status: AgentStatus;
  answer: string;
  extracted_profile: UserProfile | null;
  products: ProductResult[];
  questions: string[];
  used_fallback: boolean;
  retry_count: number;
  verification_errors: string[];
  disclaimer: string;
}
