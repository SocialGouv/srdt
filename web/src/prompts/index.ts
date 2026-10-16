import { Config } from "@/constants";
import { InstructionPrompts } from "../types";
import { GENERATE_INSTRUCTIONS } from "./generate";

export { JURISPRUDENCE_FILTER_INSTRUCTION } from "./jurisprudence-filter";

export const PROMPT_INSTRUCTIONS: Record<Config, InstructionPrompts> = {
  [Config.V2_0]: GENERATE_INSTRUCTIONS,
};
