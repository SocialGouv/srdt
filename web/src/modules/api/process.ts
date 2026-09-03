import { Config, getFamilyModel } from "@/constants";
import { GenerateResponse, ChunkResult, LLMModel } from "../../types";
import { ApiResponse, AnswerResponse } from "@/types";
import { generate, generateStream } from "./client";
import {
  createChatHistory,
  createIdccChatHistory,
  createFollowupChatHistory,
  createFollowupIdccChatHistory,
  createKnowledgeBaseContent,
  ConversationHistoryEntry,
} from "./prompt-builders";
import {
  PreparedQuestionData,
  PreparedFollowupQuestionData,
  prepareQuestionData,
  prepareFollowupQuestionData,
} from "./prepare";

// Build answer response
const buildAnswer = (
  preparedData: PreparedQuestionData,
  generatedData: GenerateResponse,
  debugInfo?: { systemPrompt: string; idcc?: string; totalTime: number }
): AnswerResponse => ({
  config: preparedData.config.toString(),
  anonymized: preparedData.anonymizeResult?.data || null,
  rephrased: preparedData.rephraseResult?.data || null,
  localSearchChunks: [
    ...preparedData.fichesOfficiellesChunks,
    ...preparedData.codeDuTravailChunks,
    ...preparedData.idccChunks,
    ...preparedData.jurisprudenceChunks,
  ],
  generated: generatedData,
  modelName: preparedData.model.name,
  modelFamily: getFamilyModel(preparedData.model),
  ...(debugInfo ? { debug: debugInfo } : {}),
});

// Build follow-up answer response
const buildFollowupAnswer = (
  preparedData: PreparedFollowupQuestionData,
  generatedData: GenerateResponse,
  allFichesOfficiellesChunks: ChunkResult[],
  allCodeDuTravailChunks: ChunkResult[],
  allIdccChunks: ChunkResult[],
  allJurisprudenceChunks: ChunkResult[]
): AnswerResponse => ({
  config: preparedData.config.toString(),
  anonymized: null, // Follow-up doesn't use anonymization
  rephrased: null, // Follow-up doesn't use rephrasing
  localSearchChunks: [
    ...allFichesOfficiellesChunks,
    ...allCodeDuTravailChunks,
    ...allIdccChunks,
    ...allJurisprudenceChunks,
  ],
  generated: generatedData,
  modelName: preparedData.model.name,
  modelFamily: getFamilyModel(preparedData.model),
});

// Ids of the documents given to the LLM, sent to the API so it can tell which
// rebuilt article links come from them (see AnswerReference.in_context).
const toContextIds = (chunks: ChunkResult[]): string[] =>
  Array.from(new Set(chunks.map((chunk) => chunk.metadata.id).filter(Boolean)));

// Get generate data for question
async function getGenerateData(
  userQuestion: string,
  requiredConfig?: Config,
  idcc?: string,
  idccName?: string
) {
  const preparedData = await prepareQuestionData(
    userQuestion,
    requiredConfig,
    idcc
  );

  // Create knowledge base content
  const knowledgeBaseContent = createKnowledgeBaseContent(
    preparedData.fichesOfficiellesChunks,
    preparedData.codeDuTravailChunks,
    idcc ? preparedData.idccChunks : undefined,
    preparedData.jurisprudenceChunks
  );

  // Determine chat history and system prompt based on whether IDCC is provided
  const { chatHistory, systemPrompt } = idcc
    ? {
        chatHistory: createIdccChatHistory(preparedData.query),
        systemPrompt:
          (preparedData.instructions.generate_instruction_idcc
            ?.replace("[URL_convention_collective]", `https://code.travail.gouv.fr/convention-collective/${idcc}`)
            .replace(/\$\{IDCC_NAME\}/g, idccName || "")
            .replace(/\$\{IDCC_NUMBER\}/g, idcc || "") || "") +
          "\n\n" +
          knowledgeBaseContent,
      }
    : {
        chatHistory: createChatHistory(preparedData.query),
        systemPrompt:
          (preparedData.instructions.generate_instruction || "") +
          "\n\n" +
          knowledgeBaseContent,
      };
  // console.log("systemPrompt", systemPrompt);

  const contextIds = toContextIds([
    ...preparedData.fichesOfficiellesChunks,
    ...preparedData.codeDuTravailChunks,
    ...(idcc ? preparedData.idccChunks : []),
  ]);

  return {
    preparedData,
    chatHistory,
    systemPrompt,
    contextIds,
  };
}

// Get generate data for follow-up questions
async function getFollowupGenerateData(
  originalQuery: string,
  conversationHistory: ConversationHistoryEntry[],
  newQuestion: string,
  requiredConfig?: Config,
  idcc?: string,
  idccName?: string,
  providedModel?: LLMModel
) {
  // RAG search still uses only original query + new question (2 queries)
  const preparedData = await prepareFollowupQuestionData(
    originalQuery,
    newQuestion,
    requiredConfig,
    idcc,
    providedModel
  );

  // Combine chunks from both queries
  const allFichesOfficiellesChunks = [
    ...preparedData.fichesOfficiellesChunksQuery1,
    ...preparedData.fichesOfficiellesChunksQuery2,
  ];

  const allCodeDuTravailChunks = [
    ...preparedData.codeDuTravailChunksQuery1,
    ...preparedData.codeDuTravailChunksQuery2,
  ];

  const allIdccChunks = [
    ...preparedData.idccChunksQuery1,
    ...preparedData.idccChunksQuery2,
  ];

  const allJurisprudenceChunks = preparedData.jurisprudenceChunks;

  // Create knowledge base content
  const knowledgeBaseContent = createKnowledgeBaseContent(
    allFichesOfficiellesChunks,
    allCodeDuTravailChunks,
    idcc ? allIdccChunks : undefined,
    allJurisprudenceChunks
  );

  // Determine system prompt based on whether IDCC is provided
  // LLM receives the full conversation history for coherent responses
  const { chatHistory, systemPrompt } = idcc
    ? {
        chatHistory: createFollowupIdccChatHistory(conversationHistory, newQuestion),
        systemPrompt:
          (preparedData.instructions.generate_followup_instruction_idcc
            ?.replace("[URL_convention_collective]", `https://code.travail.gouv.fr/convention-collective/${idcc}`)
            .replace(/\$\{IDCC_NAME\}/g, idccName || "")
            .replace(/\$\{IDCC_NUMBER\}/g, idcc || "") || "") +
          "\n\n" +
          knowledgeBaseContent,
      }
    : {
        chatHistory: createFollowupChatHistory(conversationHistory, newQuestion),
        systemPrompt:
          (preparedData.instructions.generate_followup_instruction || "") +
          "\n\n" +
          knowledgeBaseContent,
      };

  const contextIds = toContextIds([
    ...allFichesOfficiellesChunks,
    ...allCodeDuTravailChunks,
    ...(idcc ? allIdccChunks : []),
  ]);

  return {
    preparedData,
    chatHistory,
    systemPrompt,
    contextIds,
    allFichesOfficiellesChunks,
    allCodeDuTravailChunks,
    allIdccChunks,
    allJurisprudenceChunks,
  };
}

// Generate answer (non-streaming)
export const generateAnswer = async (
  userQuestion: string,
  requiredConfig?: Config,
  idcc?: string,
  idccName?: string,
  debug?: boolean
): Promise<ApiResponse<AnswerResponse>> => {
  const startedAt = Date.now();
  try {
    const { preparedData, chatHistory, systemPrompt, contextIds } =
      await getGenerateData(userQuestion, requiredConfig, idcc, idccName);

    const generateResult = await generate({
      model: preparedData.model,
      chat_history: chatHistory,
      system_prompt: systemPrompt,
      context_ids: contextIds,
    });

    if (generateResult.error) {
      throw new Error(
        `Erreur lors de la génération de la réponse: ${generateResult.error}. Pour information, le model utilisé lors de la génération est ${preparedData.model.name}`
      );
    }

    if (!generateResult.data) {
      throw new Error(
        `Erreur lors de la génération de la réponse. Pour information, le model utilisé lors de la génération est ${preparedData.model.name}`
      );
    }

    const debugInfo = debug
      ? {
          systemPrompt,
          idcc,
          totalTime: (Date.now() - startedAt) / 1000,
        }
      : undefined;

    return {
      success: true,
      data: buildAnswer(preparedData, generateResult.data, debugInfo),
    };
  } catch (error) {
    return {
      success: false,
      data: null,
      error: (error as Error).message,
    };
  }
};

// Generate answer (streaming)
export const generateAnswerStream = async (
  userQuestion: string,
  onChunk: (chunk: string) => void,
  onComplete: (result: ApiResponse<AnswerResponse>) => void,
  requiredConfig?: Config,
  idcc?: string,
  idccName?: string
): Promise<void> => {
  try {
    const { preparedData, chatHistory, systemPrompt, contextIds } =
      await getGenerateData(userQuestion, requiredConfig, idcc, idccName);

    await generateStream(
      {
        model: preparedData.model,
        chat_history: chatHistory,
        system_prompt: systemPrompt,
        context_ids: contextIds,
      },
      onChunk,
      undefined, // onStart
      (endData) => {
        // onEnd - call completion callback with full result
        const generatedData: GenerateResponse = {
          time: endData.time,
          text: endData.text,
          nb_token_input: endData.nb_token_input,
          nb_token_output: endData.nb_token_output,
          references: endData.references,
        };

        onComplete({
          success: true,
          data: buildAnswer(preparedData, generatedData),
        });
      },
      (error) => {
        // onError
        onComplete({
          success: false,
          data: null,
          error,
        });
      }
    );
  } catch (error) {
    onComplete({
      success: false,
      data: null,
      error: (error as Error).message,
    });
  }
};

// Generate follow-up answer (non-streaming)
export const generateFollowupAnswer = async (
  originalQuery: string,
  conversationHistory: ConversationHistoryEntry[],
  newQuestion: string,
  requiredConfig?: Config,
  idcc?: string,
  idccName?: string,
  providedModel?: LLMModel
): Promise<ApiResponse<AnswerResponse>> => {
  try {
    const {
      preparedData,
      chatHistory,
      systemPrompt,
      contextIds,
      allFichesOfficiellesChunks,
      allCodeDuTravailChunks,
      allIdccChunks,
      allJurisprudenceChunks,
    } = await getFollowupGenerateData(
      originalQuery,
      conversationHistory,
      newQuestion,
      requiredConfig,
      idcc,
      idccName,
      providedModel
    );

    const generateResult = await generate({
      model: preparedData.model,
      chat_history: chatHistory,
      system_prompt: systemPrompt,
      context_ids: contextIds,
    });

    if (generateResult.error) {
      throw new Error(
        `Erreur lors de la génération de la réponse de suivi: ${generateResult.error}. Pour information, le model utilisé lors de la génération est ${preparedData.model.name}`
      );
    }

    if (!generateResult.data) {
      throw new Error(
        `Erreur lors de la génération de la réponse de suivi. Pour information, le model utilisé lors de la génération est ${preparedData.model.name}`
      );
    }

    return {
      success: true,
      data: buildFollowupAnswer(
        preparedData,
        generateResult.data,
        allFichesOfficiellesChunks,
        allCodeDuTravailChunks,
        allIdccChunks,
        allJurisprudenceChunks
      ),
    };
  } catch (error) {
    return {
      success: false,
      data: null,
      error: (error as Error).message,
    };
  }
};

// Generate follow-up answer (streaming)
export const generateFollowupAnswerStream = async (
  originalQuery: string,
  conversationHistory: ConversationHistoryEntry[],
  newQuestion: string,
  onChunk: (chunk: string) => void,
  onComplete: (result: ApiResponse<AnswerResponse>) => void,
  requiredConfig?: Config,
  idcc?: string,
  idccName?: string,
  providedModel?: LLMModel
): Promise<void> => {
  try {
    const {
      preparedData,
      chatHistory,
      systemPrompt,
      contextIds,
      allFichesOfficiellesChunks,
      allCodeDuTravailChunks,
      allIdccChunks,
      allJurisprudenceChunks,
    } = await getFollowupGenerateData(
      originalQuery,
      conversationHistory,
      newQuestion,
      requiredConfig,
      idcc,
      idccName,
      providedModel
    );

    await generateStream(
      {
        model: preparedData.model,
        chat_history: chatHistory,
        system_prompt: systemPrompt,
        context_ids: contextIds,
      },
      onChunk,
      undefined, // onStart
      (endData) => {
        // onEnd - call completion callback with full result
        const generatedData: GenerateResponse = {
          time: endData.time,
          text: endData.text,
          nb_token_input: endData.nb_token_input,
          nb_token_output: endData.nb_token_output,
          references: endData.references,
        };

        onComplete({
          success: true,
          data: buildFollowupAnswer(
            preparedData,
            generatedData,
            allFichesOfficiellesChunks,
            allCodeDuTravailChunks,
            allIdccChunks,
            allJurisprudenceChunks
          ),
        });
      },
      (error) => {
        // onError
        onComplete({
          success: false,
          data: null,
          error,
        });
      }
    );
  } catch (error) {
    onComplete({
      success: false,
      data: null,
      error: (error as Error).message,
    });
  }
};
