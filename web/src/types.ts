export interface LLMModel {
  base_url: string;
  name: string;
  api_key: string;
}

// Anonymization types
export interface AnonymizeRequest {
  model: LLMModel;
  user_question: string;
  anonymization_prompt?: string;
}

export interface AnonymizeResponse {
  time: number;
  anonymized_question: string;
  nb_token_input: number;
  nb_token_output: number;
}

// Rephrase types
export interface RephraseRequest {
  model: LLMModel;
  question: string;
  rephrasing_prompt?: string;
  queries_splitting_prompt?: string;
}

export interface RephraseResponse {
  time: number;
  rephrased_question: string;
  queries?: string[];
  nb_token_input: number;
  nb_token_output: number;
}

// Search types
export interface SearchOptions {
  top_K?: number;
  threshold?: number;
  collections?: string[];
}

export interface SearchRequest {
  prompts: string[];
  options?: SearchOptions;
}

export interface ChunkMetadata {
  title: string;
  url: string;
  document_id: string;
  source: string;
}

export interface ChunkResult {
  score: number;
  content: string;
  id_chunk: string;
  metadata: ChunkMetadata;
}

export interface SearchResponse {
  time: number;
  top_chunks: ChunkResult[];
}

// Generate types
export interface UserLLMMessage {
  role: "user" | "assistant";
  content: string;
}

export interface GenerateRequest {
  model: LLMModel;
  chat_history: UserLLMMessage[];
  system_prompt?: string;
}

export interface GenerateResponse {
  time: number;
  text: string;
  nb_token_input: number;
  nb_token_output: number;
}

export interface InstructionPrompts {
  anonymisation: string;
  reformulation: string;
  split_multiple_queries: string;
  generate_instruction: string;
}
