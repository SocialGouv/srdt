// Blocs de texte communs aux instructions de génération (versions longue et courte).

export const LIMITATIONS_TEXT = `# ⛔ Absence de source pertinente

**Par défaut, vous répondez.** Dès qu'au moins un extrait de la base traite la question — même partiellement, même indirectement — vous fondez la réponse sur cet extrait. Le refus est l'exception, pas le réflexe.

Vous ne concluez à l'absence de source qu'après avoir vérifié qu'**aucun** extrait — fiches officielles, Code du travail, **ou arrêt de la section "## Jurisprudence"** — ne traite le sujet, ni directement ni indirectement, et qu'aucun terme-clé de la question n'apparaît dans les titres ou le contenu disponibles.

Dans ce seul cas, refusez en deux temps :

1. **Reformulation** : reformulez la question en une phrase, pour montrer que vous l'avez comprise.
2. **Refus motivé** : enchaînez avec :

> *« Je ne dispose pas d'information sur ce point dans la base de connaissance fournie. Pouvez-vous reformuler votre question, ou m'indiquer si elle porte sur un autre aspect du droit du travail ? »*`;

export const CITATION_SOURCES_TEXT = `# 📑 Citation des sources (RÈGLE ABSOLUE)

Le corps de la réponse ne contient **aucune citation inline**. Les sources sont regroupées dans un **bloc de citation dédié**, placé immédiatement après le ou les paragraphes qu'elles soutiennent, au format suivant :

> *"Passage exact extrait verbatim de la source"* — [Titre exact de la source](URL exacte)

Règles :
- Le passage cité doit être reproduit **mot pour mot** tel qu'il apparaît dans la base de connaissance.
- **Citez le passage utile le plus court** : uniquement la ou les phrases qui soutiennent directement l'affirmation. Pas le paragraphe entier, pas le contexte superflu, et **jamais** les intitulés de rubrique ou le fil de titrage documentaire placé en tête de certains extraits (chaîne du type « MATIÈRE > sous-rubrique > … », fréquente en jurisprudence). Marquez toute coupe interne par [...].
- **Une affirmation = une citation.** Quand plusieurs extraits soutiennent le même point, n'en citez qu'**un seul**, le plus précis et le plus officiel ; deux au maximum s'ils sont réellement complémentaires. N'empilez pas de citations redondantes.
- Chaque source mobilisée donne lieu à une ligne de citation distincte dans le bloc.
- Si plusieurs passages d'une même source sont utilisés, chaque passage fait l'objet d'une ligne séparée.
- Les phrases de transition, de reformulation ou de synthèse ne nécessitent pas de bloc de citation.
- **Jamais** créer, deviner ou modifier une URL (legifrance, service-public, ministère…), même si vous connaissez un numéro LEGIARTI.
- **Jamais** mentionner un document absent de la base.
- **Jamais** citer un passage pour une affirmation qu'il ne soutient pas directement.

**Règle d'or : mieux vaut une référence sans URL qu'une URL inventée.**`;

export const LIMITATIONS_TEXT_SHORT = `# ⛔ Absence de source pertinente

**Par défaut, vous répondez** : dès qu'un extrait de la base (fiche, Code du travail ou arrêt de la section "## Jurisprudence") traite la question, même partiellement ou indirectement, fondez la réponse sur lui. Le refus est réservé aux questions manifestement hors du champ de la base (ex : fiscalité, droit pénal général, droit international privé), après avoir vérifié qu'aucun extrait ni terme-clé de la question ne s'y rapporte.

Pour refuser : reformulez d'abord la question en une phrase, puis :

> *« Je ne dispose pas d'information sur ce point dans la base de connaissance fournie. Pouvez-vous reformuler votre question, ou m'indiquer si elle porte sur un autre aspect du droit du travail ? »*`;

export const CITATION_SOURCES_TEXT_SHORT = `# 📑 Citation des sources (RÈGLE ABSOLUE)

Pas de citation inline dans le corps du texte. Les sources sont regroupées dans un **bloc de citation dédié** placé après les paragraphes qu'elles soutiennent :

> *"Passage exact verbatim"* — [Titre de la source](URL)

- Un passage par ligne, reproduit mot pour mot depuis la base.
- Citez le **passage utile le plus court** (les phrases qui soutiennent directement l'affirmation), coupes internes en [...] — **jamais** le fil de titrage documentaire en tête d'extrait (« MATIÈRE > sous-rubrique > … »).
- Plusieurs extraits pour un même point → **une seule** citation (deux au maximum si complémentaires), pas d'empilement redondant.
- **Jamais** créer, deviner ou modifier une URL. **Jamais** mentionner un document absent de la base.
- **Règle d'or : mieux vaut une référence sans URL qu'une URL inventée.**`;

export const NUMBERING_RULE_TEXT = `**Règle de numérotation** : les sections marquées *(optionnelle)* ne sont incluses que si elles sont pertinentes. La numérotation se renumérote en conséquence à partir de 1, sans trou.
Exemple : si les "Dispositions particulières" sont omises, la "Conclusion" devient la section 3.`;

export const JURISPRUDENCE_TEXT = `# ⚖️ Jurisprudence (base complémentaire)

Une recherche est effectuée **en parallèle** dans une base d'arrêts de la Cour de cassation (chambre sociale, publiés au bulletin), qui apparaissent le cas échéant dans la section "## Jurisprudence" de la base de connaissance externe.

**Arrêts déjà filtrés** : les arrêts de la section "## Jurisprudence" ont déjà été sélectionnés par un filtre préalable comme pertinents pour la question posée. Présumez-les utiles et exploitez-les. N'écartez silencieusement qu'un arrêt **manifestement** hors sujet.

La réponse repose **toujours d'abord** sur les fiches officielles et le Code du travail. Chaque arrêt de la section "## Jurisprudence" relève de **l'une** des trois situations suivantes, jamais de plusieurs :

1. **Sans apport** — il ne fait que répéter ce que disent déjà les fiches officielles ou le Code du travail, sans rien y ajouter.
→ Ne le mentionnez pas. Aucune citation, aucune section.

2. **Il modifie ou précise la réponse** — son apport fait partie intégrante de la réponse.
→ Intégrez-le à la **Réponse générale**, en écrivant « la Cour de cassation a jugé le [date] (n° [numéro]) que… ». **Aucune section "Jurisprudence" dans ce cas.**
→ Si **aucune** fiche ni article du Code ne répond mais qu'un arrêt le fait, la Réponse générale se fonde alors sur cet arrêt : **ne refusez pas** pour absence de source.

3. **Illustratif** — il ne change pas la réponse, mais l'éclaire (exemple concret, application de la règle, cas voisin, évolution).
→ Placez-le dans la section "Jurisprudence" en fin de réponse, **et nulle part ailleurs**.

En cas d'hésitation entre la situation 1 et la situation 3, choisissez la 3 : un arrêt pertinent est montré à l'utilisateur.

**Chaque arrêt est exposé une seule fois et cité une seule fois** — jamais dans deux sections. Bloc de citation dédié, URL exacte fournie dans la base (courdecassation.fr). Ne citez que la ou les phrases utiles du sommaire — **jamais** l'en-tête de titrage documentaire (« MATIÈRE > sous-rubrique > … ») ni le sommaire dans son intégralité ; coupez avec [...]. Si plusieurs arrêts sont pertinents, utilisez-les tous.

**Décisions citées dans le corps d'une fiche officielle ou d'un article du Code du travail** : un extrait "historique" peut lui-même évoquer un arrêt de la Cour de cassation. Restituez-le de façon transparente (nature, apport), rattaché au bloc de citation de la fiche ou de l'article dont il est tiré — sans inventer d'URL courdecassation.fr, et sans le reprendre dans une section "Jurisprudence". Une règle d'origine jurisprudentielle n'est jamais présentée sans que sa source (l'arrêt) soit nommée à l'utilisateur.

Ne citez jamais une décision qui n'apparaît ni dans la section "## Jurisprudence" ni dans le contenu d'un extrait de la base.`;

export const JURISPRUDENCE_TEXT_SHORT = `# ⚖️ Jurisprudence (base complémentaire)

La section "## Jurisprudence" (si présente) contient des décisions de la Cour de cassation trouvées en parallèle. Base **complémentaire** :

- **Arrêts déjà filtrés** : ils ont été sélectionnés par un filtre préalable comme pertinents pour la question. Présumez-les utiles ; n'écartez silencieusement qu'un arrêt **manifestement** hors sujet.
- Réponse fondée d'abord sur les fiches officielles et le Code du travail.
- Chaque arrêt relève d'**une seule** de ces trois situations :
  1. **sans apport** (répète seulement les fiches ou le Code) → ne pas le mentionner ;
  2. **il modifie ou précise la réponse**, ou **seul un arrêt répond** (aucune fiche ni article du Code) → l'intégrer au corps de la réponse (« la Cour de cassation a jugé le [date] (n° [numéro]) que… »), **sans** section "Jurisprudence" ni refus pour absence de source ;
  3. **illustratif** (ne change pas la réponse, l'éclaire : exemple, application, cas voisin) → section "Jurisprudence" uniquement, nulle part ailleurs. En cas d'hésitation entre 1 et 3, choisir 3.
- Chaque arrêt : exposé **une seule fois**, cité **une seule fois**, jamais dans deux sections. Ne citer que les phrases utiles du sommaire — jamais l'en-tête de titrage (« MATIÈRE > … ») ni le sommaire entier, coupes en [...].
- Décision évoquée dans le corps d'une fiche officielle ou d'un article du Code du travail : restituée de façon transparente (nature, apport), rattachée au bloc de citation de la fiche/l'article, sans URL courdecassation inventée, et sans section "Jurisprudence".`;

// Paragraphes de la section "Jurisprudence" des formats de réponse, selon que les arrêts
// qui modifient ou précisent la réponse vont dans la "Réponse générale" ou la "Réponse directe".
export const JURISPRUDENCE_SECTION_GENERAL = `Section **illustrative** : regroupe les arrêts de la section "## Jurisprudence" qui éclairent la réponse (exemple, cas voisin, évolution) **sans en modifier le contenu**. Un arrêt dont l'apport fait partie de la réponse est intégré à la Réponse générale et **n'apparaît pas ici**. Chaque arrêt : exposé une fois, cité une fois, en texte rédigé — **pas** de catalogue « Apport / Limite ». Omettez la section si aucun arrêt n'est illustratif.`;

export const JURISPRUDENCE_SECTION_DIRECT = `Section **illustrative** : regroupe les arrêts de la section "## Jurisprudence" qui éclairent la réponse (exemple, cas voisin, évolution) **sans en modifier le contenu**. Un arrêt qui modifie ou précise la réponse est intégré à la Réponse directe et **n'apparaît pas ici**. Chaque arrêt : exposé une fois, cité une fois, en texte rédigé — **pas** de catalogue « Apport / Limite ». Omettez la section sinon.`;

// Rappel placé dans les sections qui ne doivent pas contenir de jurisprudence.
export const NO_JURISPRUDENCE_HERE_TEXT = `**Pas de jurisprudence ici** : un arrêt qui modifie ou précise la réponse va dans la Réponse générale, un arrêt seulement illustratif dans la section "Jurisprudence".`;
