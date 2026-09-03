export interface LLMModel {
  base_url: string;
  name: string;
  api_key: string;
}

export enum LLMFamily {
  CHATGPT = "chatgpt",
  MISTRAL = "mistral",
  ALBERT = "albert",
}

// Anonymization types
export interface AnonymizeRequest {
  user_question: string;
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
  hybrid?: boolean;
  top_K?: number;
  threshold?: number;
  collections?: string[];
}

export interface SearchRequest {
  prompts: string[];
  options?: SearchOptions;
  idcc?: string;
}

export interface RerankRequest {
  prompt: string;
  inputs: ChunkResult[];
}

export interface ChunkMetadata {
  id: string;
  title: string;
  url: string;
  source: string;
  idcc?: string;
  // Identifiant de la décision d'origine (collection judilibre) : présent car
  // metadata.id vaut "<decision_id>-<index>" pour les chunks de jurisprudence.
  initial_id?: string;
}

export interface ChunkResult {
  rerank_score?: number;
  score: number;
  content: string;
  id_chunk: number;
  metadata: ChunkMetadata;
}

export interface ContentResult {
  content: string;
  metadata: ChunkMetadata;
}

export interface SearchResponse {
  time: number;
  top_chunks: ChunkResult[];
}

export interface RetrieveResponse {
  time: number;
  contents: ContentResult[];
}

export interface RerankResult {
  rerank_score: number;
  chunk: ChunkResult;
}

export interface RerankResponse {
  time: number;
  results: RerankResult[];
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
  /** Ids of the documents given to the LLM, so the API can flag article links coming from elsewhere. */
  context_ids?: string[];
}

/** A link of the generated answer, as reported by the API URL post-processing. */
export interface AnswerReference {
  url: string;
  /** Link description as displayed in the answer. */
  text: string;
  /**
   * kept: written by the LLM and validated; rebuilt: created from an article
   * number found in the text; removed: stripped from the text.
   */
  status: "kept" | "rebuilt" | "removed";
  /** Rebuilt article links only: canonical article number ("L1226-1"). */
  num?: string | null;
  /** Rebuilt article links only: id of the Code du travail section holding the article. */
  section_id?: string | null;
  /** Rebuilt article links only: whether that section was given to the LLM. */
  in_context?: boolean | null;
}

export interface GenerateResponse {
  time: number;
  text: string;
  nb_token_input: number;
  nb_token_output: number;
  references?: AnswerReference[];
}

export interface InstructionPrompts {
  generate_instruction: string;
  generate_instruction_idcc: string;
  generate_followup_instruction: string;
  generate_followup_instruction_idcc: string;
}

export interface AnswerResponseDebug {
  systemPrompt: string;
  idcc?: string;
  totalTime: number;
}

export interface AnswerResponse {
  config: string;
  anonymized: AnonymizeResponse | null;
  rephrased: RephraseResponse | null;
  localSearchChunks: ChunkResult[];
  generated: GenerateResponse;
  modelName: string;
  modelFamily: LLMFamily;
  debug?: AnswerResponseDebug;
}

export interface ApiResponse<T> {
  success: boolean;
  data: T | null;
  error?: string;
}
