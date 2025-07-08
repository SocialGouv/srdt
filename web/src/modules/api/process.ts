import { Config, getFamilyModel } from "@/constants";
import { GenerateResponse, ChunkResult, LLMModel } from "../../types";
import { ApiResponse, AnalyzeResponse } from "@/types";
import { generate, generateStream } from "./client";
import {
  createChatHistory,
  createIdccChatHistory,
  createFollowupChatHistory,
  createFollowupIdccChatHistory,
} from "./prompt-builders";
import {
  PreparedQuestionData,
  PreparedFollowupQuestionData,
  prepareQuestionData,
  prepareFollowupQuestionData,
} from "./prepare";

// Helper to create final response
const createAnalyzeResponse = (
  preparedData: PreparedQuestionData,
  generatedData: GenerateResponse
): AnalyzeResponse => ({
  config: preparedData.config.toString(),
  anonymized: preparedData.anonymizeResult?.data || null,
  rephrased: preparedData.rephraseResult?.data || null,
  localSearchChunks: [
    ...preparedData.localSearchChunks,
    ...preparedData.idccChunks,
  ],
  generated: generatedData,
  modelName: preparedData.model.name,
  modelFamily: getFamilyModel(preparedData.model),
  answerType: preparedData.answerType,
});

async function getGenerateData(
  userQuestion: string,
  requiredConfig?: Config,
  idcc?: string
) {
  const preparedData = await prepareQuestionData(
    userQuestion,
    requiredConfig,
    idcc
  );

  // Determine chat history and system prompt based on whether IDCC is provided
  const generateInstruction =
    preparedData.answerType === "long"
      ? preparedData.instructions.generate_instruction
      : preparedData.instructions.generate_instruction_short_answer;

  const generateInstructionIdcc =
    preparedData.answerType === "long"
      ? preparedData.instructions.generate_instruction_idcc
      : preparedData.instructions.generate_instruction_idcc_short_answer;

  const { chatHistory, systemPrompt } = idcc
    ? {
        chatHistory: createIdccChatHistory(
          preparedData.query,
          preparedData.localSearchChunks,
          preparedData.idccChunks
        ),
        systemPrompt: generateInstructionIdcc?.replace(
          "[URL_convention_collective]",
          `https://code.travail.gouv.fr/convention-collective/${idcc}`
        ),
      }
    : {
        chatHistory: createChatHistory(
          preparedData.query,
          preparedData.localSearchChunks
        ),
        systemPrompt: generateInstruction,
      };

  return {
    preparedData,
    chatHistory,
    systemPrompt,
  };
}

export const analyzeQuestion = async (
  userQuestion: string,
  requiredConfig?: Config,
  idcc?: string
): Promise<ApiResponse<AnalyzeResponse>> => {
  try {
    const { preparedData, chatHistory, systemPrompt } = await getGenerateData(
      userQuestion,
      requiredConfig,
      idcc
    );

    const generateResult = await generate({
      model: preparedData.model,
      chat_history: chatHistory,
      system_prompt: systemPrompt,
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

    return {
      success: true,
      data: createAnalyzeResponse(preparedData, generateResult.data),
    };
  } catch (error) {
    return {
      success: false,
      data: null,
      error: (error as Error).message,
    };
  }
};

export const analyzeQuestionStream = async (
  userQuestion: string,
  onChunk: (chunk: string) => void,
  onComplete: (result: ApiResponse<AnalyzeResponse>) => void,
  requiredConfig?: Config,
  idcc?: string
): Promise<void> => {
  try {
    const { preparedData, chatHistory, systemPrompt } = await getGenerateData(
      userQuestion,
      requiredConfig,
      idcc
    );

    await generateStream(
      {
        model: preparedData.model,
        chat_history: chatHistory,
        system_prompt: systemPrompt,
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
        };

        onComplete({
          success: true,
          data: createAnalyzeResponse(preparedData, generatedData),
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

// Get generate data for follow-up questions
async function getFollowupGenerateData(
  query1: string,
  answer1: string,
  query2: string,
  requiredConfig?: Config,
  idcc?: string,
  providedModel?: LLMModel
) {
  const preparedData = await prepareFollowupQuestionData(
    query1,
    query2,
    requiredConfig,
    idcc,
    providedModel
  );

  // Combine chunks from both queries
  const allGeneralChunks = [
    ...preparedData.generalChunksQuery1,
    ...preparedData.generalChunksQuery2,
  ];

  const allIdccChunks = [
    ...preparedData.idccChunksQuery1,
    ...preparedData.idccChunksQuery2,
  ];

  // Determine system prompt based on whether IDCC is provided
  const { chatHistory, systemPrompt } = idcc
    ? {
        chatHistory: createFollowupIdccChatHistory(
          query1,
          answer1,
          query2,
          allGeneralChunks,
          allIdccChunks
        ),
        systemPrompt:
          preparedData.instructions.generate_followup_instruction_idcc?.replace(
            "[URL_convention_collective]",
            `https://code.travail.gouv.fr/convention-collective/${idcc}`
          ),
      }
    : {
        chatHistory: createFollowupChatHistory(
          query1,
          answer1,
          query2,
          allGeneralChunks
        ),
        systemPrompt: preparedData.instructions.generate_followup_instruction,
      };

  return {
    preparedData,
    chatHistory,
    systemPrompt,
    allGeneralChunks,
    allIdccChunks,
  };
}

// Create follow-up analyze response
const createFollowupAnalyzeResponse = (
  preparedData: PreparedFollowupQuestionData,
  generatedData: GenerateResponse,
  allGeneralChunks: ChunkResult[],
  allIdccChunks: ChunkResult[]
): AnalyzeResponse => ({
  config: preparedData.config.toString(),
  anonymized: null, // Follow-up doesn't use anonymization
  rephrased: null, // Follow-up doesn't use rephrasing
  localSearchChunks: [...allGeneralChunks, ...allIdccChunks],
  generated: generatedData,
  modelName: preparedData.model.name,
  modelFamily: getFamilyModel(preparedData.model),
  answerType: "short", // Follow-up responses are always short
});

// Analyze follow-up question (non-streaming)
export const analyzeFollowupQuestion = async (
  query1: string,
  answer1: string,
  query2: string,
  requiredConfig?: Config,
  idcc?: string,
  providedModel?: LLMModel
): Promise<ApiResponse<AnalyzeResponse>> => {
  try {
    const {
      preparedData,
      chatHistory,
      systemPrompt,
      allGeneralChunks,
      allIdccChunks,
    } = await getFollowupGenerateData(
      query1,
      answer1,
      query2,
      requiredConfig,
      idcc,
      providedModel
    );

    const generateResult = await generate({
      model: preparedData.model,
      chat_history: chatHistory,
      system_prompt: systemPrompt,
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
      data: createFollowupAnalyzeResponse(
        preparedData,
        generateResult.data,
        allGeneralChunks,
        allIdccChunks
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

// Analyze follow-up question (streaming)
export const analyzeFollowupQuestionStream = async (
  query1: string,
  answer1: string,
  query2: string,
  onChunk: (chunk: string) => void,
  onComplete: (result: ApiResponse<AnalyzeResponse>) => void,
  requiredConfig?: Config,
  idcc?: string,
  providedModel?: LLMModel
): Promise<void> => {
  try {
    const {
      preparedData,
      chatHistory,
      systemPrompt,
      allGeneralChunks,
      allIdccChunks,
    } = await getFollowupGenerateData(
      query1,
      answer1,
      query2,
      requiredConfig,
      idcc,
      providedModel
    );

    await generateStream(
      {
        model: preparedData.model,
        chat_history: chatHistory,
        system_prompt: systemPrompt,
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
        };

        onComplete({
          success: true,
          data: createFollowupAnalyzeResponse(
            preparedData,
            generatedData,
            allGeneralChunks,
            allIdccChunks
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
