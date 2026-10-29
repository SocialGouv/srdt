import { LLMFamily, LLMModel, SearchOptions } from "./types";

const CHATGPT_BASE_URL = "https://api.openai.com";
const MISTRAL_BASE_URL = "https://api.mistral.ai";
const ALBERT_BASE_URL = "https://albert.api.etalab.gouv.fr";

// Email domain configuration - single source of truth for access control and department mapping
export const EMAIL_DOMAIN_CONFIG: { domain: string; department: string }[] = [
  { domain: "bouches-du-rhone.gouv.fr", department: "Bouches-du-Rhône" },
  { domain: "maine-et-loire.gouv.fr", department: "Maine-et-Loire" },
  { domain: "creuse.gouv.fr", department: "Creuse" },
  { domain: "nord.gouv.fr", department: "Nord" },
  { domain: "pas-de-calais.gouv.fr", department: "Pas-de-Calais" },
  { domain: "aisne.gouv.fr", department: "Aisne" },
  { domain: "oise.gouv.fr", department: "Oise" },
  { domain: "somme.gouv.fr", department: "Somme" },
  { domain: "calvados.gouv.fr", department: "Calvados" },
  { domain: "manche.gouv.fr", department: "Manche" },
  { domain: "orne.gouv.fr", department: "Orne" },
  { domain: "eure.gouv.fr", department: "Eure" },
  { domain: "seine-maritime.gouv.fr", department: "Seine-Maritime" },
  { domain: "charente.gouv.fr", department: "Charente" },
  { domain: "charente-maritime.gouv.fr", department: "Charente-Maritime" },
  { domain: "correze.gouv.fr", department: "Corrèze" },
  { domain: "dordogne.gouv.fr", department: "Dordogne" },
  { domain: "gironde.gouv.fr", department: "Gironde" },
  { domain: "landes.gouv.fr", department: "Landes" },
  { domain: "lot-et-garonne.gouv.fr", department: "Lot-et-Garonne" },
  {
    domain: "pyrenees-atlantiques.gouv.fr",
    department: "Pyrénées-Atlantiques",
  },
  { domain: "deux-sevres.gouv.fr", department: "Deux-Sèvres" },
  { domain: "vienne.gouv.fr", department: "Vienne" },
  { domain: "haute-vienne.gouv.fr", department: "Haute-Vienne" },
  { domain: "cher.gouv.fr", department: "Cher" },
  { domain: "eure-et-loir.gouv.fr", department: "Eure-et-Loir" },
  { domain: "indre.gouv.fr", department: "Indre" },
  { domain: "indre-et-loire.gouv.fr", department: "Indre-et-Loire" },
  { domain: "loir-et-cher.gouv.fr", department: "Loir-et-Cher" },
  { domain: "loiret.gouv.fr", department: "Loiret" },
  { domain: "travail.gouv.fr", department: "DGT" },
  { domain: "beta.gouv.fr", department: "Beta.gouv" },
  { domain: "fabrique.social.gouv.fr", department: "Fabrique Numérique" },
  { domain: "drieets.gouv.fr", department: "DRIEETS" },
  { domain: "dreets.gouv.fr", department: "DREETS" },
  { domain: "sg.social.gouv.fr", department: "SG Social" },
];

// Derived: list of allowed email domains for access control
export const ALLOWED_EMAIL_DOMAINS = EMAIL_DOMAIN_CONFIG.map((c) => c.domain);

// Derived: mapping from domain to department name for Matomo tracking
export const DOMAIN_TO_DEPARTMENT: Record<string, string> = Object.fromEntries(
  EMAIL_DOMAIN_CONFIG.map((c) => [c.domain, c.department])
);

export const MAX_RERANK = 64;
export const K_RERANK = 10;
export const K_RERANK_CODE = 5;
export const K_RERANK_IDCC = 5;
export const K_RERANK_JURISPRUDENCE = 5;

// Follow-up question limits
export const MAX_FOLLOWUP_QUESTIONS = 5;

// Conversations kept in the sidebar history (and in localStorage): the most
// recent ones win, older ones are dropped.
export const MAX_HISTORY_CONVERSATIONS = 12;

// Follow-up question constants
export const K_RERANK_FOLLOWUP_QUERY1 = 5; // Top 5 chunks for query_1
export const K_RERANK_FOLLOWUP_QUERY2 = 10; // Top 10 chunks for query_2
export const K_RERANK_IDCC_FOLLOWUP = 5; // Top 5 chunks for IDCC per query

export enum Config {
  V2_0 = "v2.0",
}

export enum Collection {
  CONVENTIONS = "conventions",
  CONTRIBUTIONS = "contributions",
  PAGE_FICHE_MINISTERE_TRAVAIL = "page_fiche_ministere_travail",
  FICHES_SERVICE_PUBLIC = "fiches_service_public",
  INFORMATION = "information",
  CODE_DU_TRAVAIL = "code_du_travail",
  JUDILIBRE = "judilibre",
}

// randomization factor to select configurations during A/B testing
// chance to select the latest config
export const AB_rand = 0;

export const SEARCH_OPTIONS_CONTENT: SearchOptions = {
  hybrid: true,
  top_K: 200,
  collections: [
    Collection.PAGE_FICHE_MINISTERE_TRAVAIL,
    Collection.FICHES_SERVICE_PUBLIC,
    Collection.INFORMATION,
  ],
};

export const SEARCH_OPTIONS_IDCC: SearchOptions = {
  hybrid: true,
  top_K: 64,
  collections: [Collection.CONVENTIONS],
};

export const SEARCH_OPTIONS_CODE: SearchOptions = {
  hybrid: true,
  top_K: 64,
  collections: [Collection.CODE_DU_TRAVAIL],
};

// Jurisprudence (Cour de cassation) : recherche large puis rerank (reranker Albert),
// on garde les K_RERANK_JURISPRUDENCE meilleurs, en parallèle de la recherche "historique"
export const SEARCH_OPTIONS_JURISPRUDENCE: SearchOptions = {
  hybrid: true,
  top_K: 64,
  collections: [Collection.JUDILIBRE],
};

// Filtre LLM des jurisprudences (après le rerank) : pour chaque arrêt retenu, on demande
// au LLM s'il permet de répondre à la question ; seuls les arrêts jugés "OUI" sont
// transmis au prompt generate (instructions : prompts/jurisprudence-filter.ts).
export const JURISPRUDENCE_FILTER_MODEL_NAME = "mistral-large-latest";

export const CHATGPT_LLM: LLMModel = {
  api_key: process.env.CHATGPT_LLM_API_KEY ?? "",
  name: process.env.CHATGPT_MODEL_NAME ?? "",
  base_url: CHATGPT_BASE_URL,
};

export const MISTRAL_LLM: LLMModel = {
  api_key: process.env.MISTRAL_LLM_API_KEY ?? "",
  name: process.env.MISTRAL_MODEL_NAME ?? "",
  base_url: MISTRAL_BASE_URL,
};

export const JURISPRUDENCE_FILTER_LLM: LLMModel = {
  ...MISTRAL_LLM,
  name: JURISPRUDENCE_FILTER_MODEL_NAME,
};

export const ALBERT_LLM: LLMModel = {
  api_key: process.env.ALBERT_LLM_API_KEY ?? "",
  name: process.env.ALBERT_MODEL_NAME ?? "",
  base_url: ALBERT_BASE_URL,
};

export const getModelByFamily = (family: LLMFamily): LLMModel => {
  switch (family) {
    case LLMFamily.MISTRAL:
      return MISTRAL_LLM;
    case LLMFamily.CHATGPT:
      return CHATGPT_LLM;
    case LLMFamily.ALBERT:
      return ALBERT_LLM;
    default:
      throw new Error(`Unknown family ${family}`);
  }
};

export const getModelByName = (modelName: string): LLMModel | null => {
  const models = [CHATGPT_LLM, MISTRAL_LLM, ALBERT_LLM];
  return models.find((model) => model.name === modelName) || null;
};

export const getFamilyModel = (llmModel: LLMModel): LLMFamily => {
  switch (llmModel.base_url) {
    case ALBERT_BASE_URL:
      return LLMFamily.ALBERT;
    case CHATGPT_BASE_URL:
      return LLMFamily.CHATGPT;
    case MISTRAL_BASE_URL:
      return LLMFamily.MISTRAL;
    default:
      throw new Error(`Unknown model: ${llmModel}`);
  }
};
