/* ------------------------------------------------------------------ */
/* API response types — mirrors FastAPI Pydantic models                */
/* ------------------------------------------------------------------ */

export interface HealthResponse {
  status: string;
  version: string;
}

export interface EffectParam {
  type: string;
  default: unknown;
}

export interface EffectBlock {
  position: number;
  key: string;
  class_name: string;
  params: Record<string, EffectParam>;
  docstring: string;
}

export interface AskRequest {
  question: string;
  limit?: number;
  part_filter?: string | null;
}

export interface SourceRef {
  title: string;
  part: string;
  score: number;
}

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface AskResponse {
  answer: string;
  sources: SourceRef[];
  model: string;
  usage: TokenUsage;
}

export interface ComposeRequest {
  description: string;
  limit?: number;
}

export interface ComposeResponse {
  config: Record<string, unknown>;
  reasoning?: string;
  sources: SourceRef[];
  model: string;
  usage: TokenUsage;
}

export interface GenerateRequest {
  generator: string;
  generator_params?: Record<string, unknown>;
  chain_overrides?: Record<string, Record<string, unknown>>;
  chain_skip?: string[];
  bypass_chain?: boolean;
}

export * from "./codegen";
export * from "./tuning";
