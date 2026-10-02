export type AgentStatus = "completed" | "needs_input" | "failed";
export type ConditionStatus = "satisfied" | "unsatisfied" | "unknown";

export interface UserFact {
  satisfied: boolean | null;
  amount_won?: number | null;
  months?: number | null;
  count?: number | null;
  channel?: string | null;
  age?: number | null;
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
  status: ConditionStatus;
  exclusion_reason: string | null;
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
  eligibility_status: ConditionStatus;
  eligibility_reasons: string[];
  potential_rate_bps: number;
  potential_after_tax_interest_won: number;
  disclosed_month: string;
  updated_at: string | null;
  source_hash: string;
}

export interface AskResponse {
  thread_id: string;
  status: AgentStatus;
  answer: string;
  extracted_profile: UserProfile | null;
  products: ProductResult[];
  questions: string[];
  next_question: NextQuestion | null;
  excluded_products: Array<{product_key: string; product_name: string; institution_name: string; eligibility_reasons: string[]}>;
  used_fallback: boolean;
  retry_count: number;
  verification_errors: string[];
  disclaimer: string;
}

export interface NextQuestion {
  code: string;
  question: string;
  interest_gain_won: number;
  affected_products: number;
  missing_fields: string[];
  explanation: string;
}

export interface EvaluationResult {
  results: Array<{product_key: string; product_name: string; institution_name: string; reserve_type: string; term_months: number; achieved_rate_bps: number; after_tax_interest_won: number; maturity_amount_won: number; eligibility_status: ConditionStatus}>;
  excluded_results: AskResponse["excluded_products"];
}

export interface ScenarioResponse {
  baseline: EvaluationResult;
  scenarios: Array<{name: string; evaluation: EvaluationResult; deltas: Array<{product_key: string; product_name: string; after_tax_interest_delta_won: number | null; baseline_rank: number | null; scenario_rank: number}>}>;
  disclaimer: string;
}
