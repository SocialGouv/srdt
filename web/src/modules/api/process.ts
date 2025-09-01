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
    ...preparedData.fichesOfficiellesChunks,
    ...preparedData.codeDuTravailChunks,
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
  allFichesOfficiellesChunks: ChunkResult[],
  allCodeDuTravailChunks: ChunkResult[],
  allIdccChunks: ChunkResult[]
): AnswerResponse => ({
  config: preparedData.config.toString(),
  anonymized: null, // Follow-up doesn't use anonymization
  rephrased: null, // Follow-up doesn't use rephrasing
  localSearchChunks: [
    ...allFichesOfficiellesChunks,
    ...allCodeDuTravailChunks,
    ...allIdccChunks,
  ],
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

  // Create knowledge base content
  const knowledgeBaseContent = createKnowledgeBaseContent(
    preparedData.fichesOfficiellesChunks,
    preparedData.codeDuTravailChunks,
    idcc ? preparedData.idccChunks : undefined
  );

  // Determine chat history and system prompt based on whether IDCC is provided
  const { chatHistory, systemPrompt } = idcc
    ? {
        chatHistory: createIdccChatHistory(preparedData.query),
        systemPrompt:
          (preparedData.instructions.generate_instruction_idcc?.replace(
            "[URL_convention_collective]",
            `https://code.travail.gouv.fr/convention-collective/${idcc}`
          ) || "") +
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
  console.log("systemPrompt", systemPrompt);

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

  // Create knowledge base content
  const knowledgeBaseContent = createKnowledgeBaseContent(
    allFichesOfficiellesChunks,
    allCodeDuTravailChunks,
    idcc ? allIdccChunks : undefined
  );

  // Determine system prompt based on whether IDCC is provided
  const { chatHistory, systemPrompt } = idcc
    ? {
        chatHistory: createFollowupIdccChatHistory(query1, answer1, query2),
        systemPrompt:
          (preparedData.instructions.generate_followup_instruction_idcc?.replace(
            "[URL_convention_collective]",
            `https://code.travail.gouv.fr/convention-collective/${idcc}`
          ) || "") +
          "\n\n" +
          knowledgeBaseContent,
      }
    : {
        chatHistory: createFollowupChatHistory(query1, answer1, query2),
        systemPrompt:
          (preparedData.instructions.generate_followup_instruction || "") +
          "\n\n" +
          knowledgeBaseContent,
      };

  return {
    preparedData,
    chatHistory,
    systemPrompt,
    allFichesOfficiellesChunks,
    allCodeDuTravailChunks,
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
      allFichesOfficiellesChunks,
      allCodeDuTravailChunks,
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
        allFichesOfficiellesChunks,
        allCodeDuTravailChunks,
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
      allFichesOfficiellesChunks,
      allCodeDuTravailChunks,
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
            allFichesOfficiellesChunks,
            allCodeDuTravailChunks,
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
