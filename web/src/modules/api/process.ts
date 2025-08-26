import { Config, getFamilyModel } from "@/constants";
import { GenerateResponse, ChunkResult, LLMModel } from "../../types";
import { ApiResponse, AnswerResponse } from "@/types";
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

// Build answer response
const buildAnswer = (
  preparedData: PreparedQuestionData,
  generatedData: GenerateResponse
): AnswerResponse => ({
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
});

// Build follow-up answer response
const buildFollowupAnswer = (
  preparedData: PreparedFollowupQuestionData,
  generatedData: GenerateResponse,
  allGeneralChunks: ChunkResult[],
  allIdccChunks: ChunkResult[]
): AnswerResponse => ({
  config: preparedData.config.toString(),
  anonymized: null, // Follow-up doesn't use anonymization
  rephrased: null, // Follow-up doesn't use rephrasing
  localSearchChunks: [...allGeneralChunks, ...allIdccChunks],
  generated: generatedData,
  modelName: preparedData.model.name,
  modelFamily: getFamilyModel(preparedData.model),
});

// Get generate data for question
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
  const { chatHistory, systemPrompt } = idcc
    ? {
        chatHistory: createIdccChatHistory(
          preparedData.query,
          preparedData.localSearchChunks,
          preparedData.idccChunks
        ),
        systemPrompt:
          preparedData.instructions.generate_instruction_idcc?.replace(
            "[URL_convention_collective]",
            `https://code.travail.gouv.fr/convention-collective/${idcc}`
          ),
      }
    : {
        chatHistory: createChatHistory(
          preparedData.query,
          preparedData.localSearchChunks
        ),
        systemPrompt: preparedData.instructions.generate_instruction,
      };

  return {
    preparedData,
    chatHistory,
    systemPrompt,
  };
}

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

// Generate answer (non-streaming)
export const generateAnswer = async (
  userQuestion: string,
  requiredConfig?: Config,
  idcc?: string
): Promise<ApiResponse<AnswerResponse>> => {
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
      data: buildAnswer(preparedData, generateResult.data),
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
  query1: string,
  answer1: string,
  query2: string,
  requiredConfig?: Config,
  idcc?: string,
  providedModel?: LLMModel
): Promise<ApiResponse<AnswerResponse>> => {
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
      data: buildFollowupAnswer(
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

// Generate follow-up answer (streaming)
export const generateFollowupAnswerStream = async (
  query1: string,
  answer1: string,
  query2: string,
  onChunk: (chunk: string) => void,
  onComplete: (result: ApiResponse<AnswerResponse>) => void,
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
          data: buildFollowupAnswer(
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
