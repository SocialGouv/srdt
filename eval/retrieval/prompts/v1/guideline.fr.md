<!-- DRAFT written by the assistant from the retrieval-eval plan, NOT validated by a
domain expert. Replace with the annotation guideline: it is the contract for both the
LLM labeller and the human audit sample, so edit it before labelling anything. Bump the
prompt version (prompts/v2/) after any change, labels are tied to the version. -->

Barème de pertinence (une seule note par document) :

- **2 — répond directement.** Le document traite la situation décrite par l'usager et contient l'information qui répond à sa question principale (la règle applicable, ses conditions, la démarche à suivre), ou la règle de droit sur laquelle repose la réponse. Un professionnel pourrait s'appuyer sur ce seul document pour répondre l'essentiel.
- **1 — utile mais partiel.** Le document porte sur le même sujet et aide à répondre (contexte, règle générale, autre aspect de la question, cas voisin), mais ne suffit pas à répondre seul : il manque la partie qui concerne la situation précise, ou il ne traite qu'une des questions posées.
- **0 — inutile.** Le document est hors sujet, ou ne partage que le thème général sans information utile pour cette question : autre statut, autre type de contrat, autre situation dont la réponse est différente.

Cas particuliers :
- Si la question contient plusieurs demandes, la note 2 suppose que l'essentiel est couvert ; ne couvrir qu'une demande secondaire donne 1.
- Une règle générale alors que la situation relève d'une règle spécifique (ou l'inverse) vaut 1, sauf si le document renvoie explicitement à la règle spécifique et suffit à répondre : 2.
- Si une convention collective (IDCC) est indiquée, un document général reste noté sur son contenu ; il ne devient pas inutile parce qu'il ne cite pas la convention.
- Un document manifestement tronqué ou illisible est noté sur ce qui est lisible.
