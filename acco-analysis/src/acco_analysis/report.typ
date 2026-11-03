// The note: prose written from a reading of the clauses. Its look is in style.typ (a copy of
// report_style.typ, made next to this file when building). Every figure and quoted
// clause comes from data.json (report_pdf.py), so the text cannot drift from the data.
#import "style.typ": *
#let data = json("data.json")
#let f = figures(data.f)
#let q(key) = quote-block(data.quotes.at(key), source: [Légifrance], ui: [Lire l'accord])

#show: report.with(
  title: "Les accords d'entreprise face à la chaleur",
  footer: [Clauses chaleur · snapshot #data.snapshot · #data.generated],
  home: data.ui_home,
)

#title-block(
  [Les accords d'entreprise face à la chaleur],
  [Ce que disent les clauses, et ce qu'elles laissent de côté. Note interne pour l'équipe
    d'analyse.],
)

#outline(title: [Sommaire], depth: 2, indent: 1em)

= L’essentiel

Sur les #f.collected accords d’entreprise collectés (signés de #f.years), #f.heat_loose contiennent une clause évoquant la chaleur. Cette note analyse ces clauses plutôt qu’elle ne les dénombre : que prévoient-elles, pour qui, décidées par qui, à quel coût. Cinq constats se dégagent.

+ *Dans quatre accords sur dix, la chaleur n’est qu’un cas parmi d’autres.* Dans #f.specific_share des cas (#f.specific accords), un dispositif spécifique à la chaleur est prévu : horaires « canicule », plan d’action, prime. Dans les #f.generic_share restants (#f.generic accords), elle n’apparaît que comme un cas parmi d’autres dans une clause générale sur les intempéries ou les circonstances exceptionnelles.

+ *Les deux logiques n’appellent pas les mêmes mesures.* Les dispositifs dédiés agissent d’abord sur les horaires (#f.specific_schedule des #f.specific accords), puis sur le rafraîchissement (#f.cooling), l’eau (#f.water) ou les pauses supplémentaires (#f.extra_breaks). Les clauses générales recourent surtout au télétravail (#f.generic_telework accords) et à la modification du planning le jour même (#f.generic_same_day). L’arrêt du travail reste rare (#f.production_stop).

+ *Le déclencheur est souvent imprécis.* « Canicule » ou « fortes chaleurs » sans définition dans #f.canicule_unqualified accords ; les seuils de température (#f.temperature_threshold) et les niveaux de vigilance Météo-France sont moins fréquents, mais le décret du 27 mai 2025 commence à inspirer ce vocabulaire (#f.decree accords le citent).

+ *L’employeur décide, et la rémunération est rarement précisée.* L’initiative revient à l’employeur dans #f.init_employer accords, au salarié dans #f.init_employee, et suppose l’accord des représentants dans #f.init_reps. L’effet sur la rémunération n’est pas abordé dans #f.pay_unspecified_share des accords.

+ *La chaleur sert aussi à assouplir les règles.* Modifier le planning le jour même (#f.same_day_change), déroger au repos (#f.rest_derogation) ou récupérer les heures perdues : la chaleur y figure comme un motif de flexibilité pour l’employeur, en plus du risque qu’elle représente.

= Ce qui a été lu

Deux modèles de langage ont lu chaque extrait et l’ont codé selon une grille commune. Les chiffres de cette note comptent des *accords* (et non des extraits) pour lesquels les *deux* modèles s’accordent, sauf indication contraire. Les accords ont été collectés à partir de termes liés à la chaleur, et seul le texte autour de « canicule », « chaleur » et variantes a été analysé : il s’agit donc de planchers. Le corpus décrit les entreprises qui encadrent la chaleur, non l’ensemble des entreprises françaises. Les réserves détaillées figurent en fin de note.

= Deux manières de parler de la chaleur

== Un dispositif conçu pour la chaleur

Dans #f.specific accords, le texte définit une mesure, un seuil ou une procédure propre à la chaleur : aménagement des horaires, plan d’action, prime. Ces dispositifs peuvent être adaptés à un métier ou à un site :

#q("hours_canicule")

== La chaleur comme cas particulier d’une règle générale

Dans les #f.generic autres accords, la chaleur n’est qu’un élément dans une liste (« pluie intense, neige, gel, forte chaleur… ») déclenchant une règle valable pour toutes les intempéries ou circonstances exceptionnelles : télétravail exceptionnel, modification du planning, récupération des heures perdues. Ces clauses sont souvent des modèles repris d’un accord à l’autre : #f.template_agreements accords (#f.template_share) partagent une clause avec au moins une autre entreprise, répartis en #f.template_groups groupes, le plus important comptant #f.template_largest accords. Le nombre de rédactions distinctes est donc bien inférieur au nombre d’accords.

= Les secteurs représentés

Les accords proviennent de presque tous les grands secteurs, mais de manière très inégale. L’industrie manufacturière en représente à elle seule #f.sec_c_share (#f.sec_c), suivie des services administratifs et de soutien (#f.sec_n_share), de l’administration publique, sécurité sociale comprise (#f.sec_o_share), des transports et de l’entreposage (#f.sec_h_share), puis de la construction (#f.sec_f_share). Ces proportions reflètent les données collectées, non le poids réel des secteurs dans l’économie.

Le secteur influence la manière d’aborder la chaleur. Dans l’industrie, les transports et la construction, celle-ci est traitée comme un risque professionnel par un dispositif dédié (#f.sec_c_dedicated, #f.sec_h_dedicated et #f.sec_f_dedicated des accords) : aménagement des horaires, pauses, eau, rafraîchissement. L’industrie concentre aussi #f.prime_industry_share des primes et #f.rest_industry_share des dérogations au repos. Dans l’administration, la sécurité sociale et les activités de bureau, la chaleur est considérée comme un événement exceptionnel parmi d’autres : #f.sec_o_telework des accords de l’administration publique prévoient le télétravail, et #f.sec_o_dedicated un dispositif dédié.

Le paysage constitue une exception. Ses #f.land accords, dont #f.land_idcc relèvent de la convention collective de branche, s’appuient majoritairement sur des clauses types (#f.land_template accords). Ces clauses d’annualisation assimilent la forte chaleur à une intempérie : le planning peut être modifié le jour même (#f.land_same_day accords) et l’interruption collective est assortie d’une récupération des heures (#f.land_collective). Ce secteur compte #f.land_same_day_share des modifications de planning le jour même et #f.land_collective des #f.collective_total interruptions collectives. Hors paysage, l’interruption collective n’apparaît que dans #f.other_collective accords, et la modification du planning le jour même dans #f.other_same_day.

= Les dispositifs propres à la chaleur

== Ce qui déclenche la mesure

Le point faible réside dans le déclencheur. Dans #f.canicule_unqualified accords, la clause mentionne « canicule » ou « fortes chaleurs » sans préciser de seuil : c’est à l’employeur ou au responsable d’apprécier. Lorsque le texte précise, il le fait de trois manières.

- *Un seuil de température* (#f.temperature_threshold accords). Parmi les #f.temperature_agreements accords citant une température, #f.threshold_30 indiquent 30~°C et #f.threshold_28 indiquent 28~°C (lecture large). Certains seuils sont composites et désignent la source de mesure :

#q("accuweather")

- *Un niveau de vigilance Météo-France* : jaune (#f.vigilance_yellow accords), orange (#f.vigilance_orange), rouge (#f.vigilance_red). La définition de la chaleur est alors déléguée à un tiers, ce qui évite de discuter du seuil.
- *Une période fixe* (#f.fixed_period accords) : horaires d’été du 1er~juin au 15~septembre, indépendamment de la température.

Depuis le décret n° 2025-482 du 27 mai 2025 sur la protection des travailleurs contre les risques liés à la chaleur, #f.decree accords y font référence, et plusieurs reprennent ses niveaux de vigilance pour définir la « forte chaleur » :

#q("decree")

== Ce que prévoit le dispositif

La mesure la plus courante concerne les horaires : décalage ou aménagement de la journée (#f.specific_schedule des #f.specific accords), par exemple journée continue ou prise de poste dès 6~h ou 7~h, ou horaires d’été fixes (#f.summer_hours). Viennent ensuite des mesures matérielles peu coûteuses : rafraîchissement (#f.cooling), eau (#f.water), pauses supplémentaires (#f.extra_breaks), équipement de protection (#f.protective_gear). La dimension organisationnelle est plus rare : information et sensibilisation (#f.prevention_info), évaluation des risques (#f.risk_assessment), souvent via le document unique et avec avis du CSE :

#q("plan_duerp")

Les plans les plus élaborés sont gradués selon les niveaux de vigilance : de l’affichage et de la distribution d’eau en vigilance jaune jusqu’à, aux niveaux supérieurs, l’évaluation quotidienne des salariés fragiles et la possibilité de télétravail pour les femmes enceintes :

#q("tiers")

Les mesures les plus lourdes sont les moins fréquentes : une prime n’est prévue que dans #f.prime accords, l’arrêt ou la suspension de l’activité dans #f.production_stop. Lorsqu’elle existe, la suspension peut être décidée a posteriori, comme ici après une alerte rouge :

#q("stop")

= Quand la chaleur assouplit les règles

Dans de nombreux accords, la chaleur n’est pas le sujet principal : elle sert de motif pour activer une règle plus générale, parfois favorable à l’employeur. Quatre situations reviennent.

#lead[*Modifier le planning le jour même.* Dans les clauses d’annualisation du temps de travail, le délai de prévenance (souvent de sept jours) peut être levé en cas d’« intempéries », forte chaleur incluse (#f.same_day_change accords) :]

#q("same_day")

#lead[*Récupérer les heures perdues.* Lorsque la chaleur empêche de travailler, le texte prévoit parfois que le temps perdu sera rattrapé : l’interruption collective du travail (#f.collective_stoppage accords) s’accompagne presque toujours d’une récupération (#f.collective_stoppage_recovery d’entre eux), et la récupération est notée comme non rémunérée dans #f.pay_unpaid_recovery accords :]

#q("recovery")

#lead[*Déroger au repos ou à la durée maximale.* Ici, la chaleur n’est plus un risque mais un pic d’activité : une « vague de chaleur », comme une « vague de froid », peut justifier une dérogation (#f.rest_derogation accords) :]

#q("rest12")

#lead[*Recourir au télétravail.* #f.telework_exceptional accords sur #f.telework (#f.telework_exceptional_share) classent le télétravail parmi les circonstances exceptionnelles (épidémie, pollution, grève, intempéries) : la chaleur n’y est qu’une cause parmi d’autres, et la direction en apprécie seule la pertinence.]

#q("telework")

La part du télétravail est maximale en #f.telework_peak_year (#f.telework_peak des accords collectés cette année-là) et recule à #f.telework_last en #f.last_year, tandis que la prévention progresse (#f.prevention_last en #f.last_year, #f.prevention_partial en #f.partial_year, année partielle). Ces évolutions décrivent le corpus collecté sans en expliquer les causes, et le décret de 2025 n’est cité que par #f.decree accords.

= Qui décide, avec quelle force, à quel prix

*Initiative.* L’employeur déclenche ou décide dans #f.init_employer accords ; le salarié peut en faire la demande dans #f.init_employee ; l’accord des représentants est prévu dans #f.init_reps. #f.init_unspecified accords ne précisent pas qui décide, et pour #f.init_disagree, les deux modèles divergent.

*Force.* Dans #f.faculty accords, la clause est une simple faculté (« pourra », « peut ») ; dans #f.obligation, une obligation ; dans #f.principle, un principe ou un objectif. Pour #f.strength_disagree accords, les modèles ne s’accordent pas. Les garanties de procédure restent minoritaires : consultation ou information du CSE dans #f.proc_cse accords, volontariat ou consentement du salarié dans #f.proc_consent.

*Rémunération.* #f.pay_unspecified_share des accords ne mentionnent aucun effet sur la rémunération. Lorsqu’ils le font : heures à récupérer sans solde (#f.pay_unpaid_recovery), supplément ou prime (#f.pay_extra), maintien de salaire (#f.pay_maintained), absence de compensation (#f.pay_none). Un exemple illustre cette logique : la compensation reste exceptionnelle et laissée à l’appréciation de la direction.

#q("discretion")

= Ce que les clauses ne disent pas

- *À partir de quand.* #f.canicule_unqualified accords ne définissent pas la chaleur qu’ils évoquent.
- *Que faire quand les mesures ne suffisent pas.* L’arrêt ou la suspension du travail n’est prévu que dans #f.production_stop accords, et l’interruption collective s’accompagne généralement d’une récupération. Dans les extraits lus, le droit de retrait n’est cité que par #f.withdrawal.
- *Qui est protégé.* #f.scope_unspecified accords ne précisent pas le champ d’application de la clause ; les salariés vulnérables ne sont visés que dans #f.scope_vulnerable accords, et un suivi médical que dans #f.health_follow_up.
- *Ce qui est appliqué.* L’analyse porte sur des textes : rien n’indique comment ils sont mis en œuvre.

= Réserves de lecture

- *Des planchers.* Seul le texte autour des mots liés à la chaleur a été lu ; des formulations comme « températures élevées » seules ont pu être omises.
- *Aucun codage validé manuellement.* L’initiative et la force des clauses figurent parmi les codes les moins fiables : il faut donc retenir les ordres de grandeur, non les écarts fins. Les accords où les deux modèles divergent ne sont pas comptabilisés ici.
- *Recherches par mots-clés.* Les accords citant le décret de 2025 ou le droit de retrait, ainsi que la part du télétravail pour circonstances exceptionnelles, relèvent de recherches de termes dans les extraits, non de codages.
- *Secteurs.* Ils sont les grandes sections de la nomenclature d’activités, d’après le code APE de l’entreprise ; #f.no_ape accords sans code exploitable ne sont pas classés.
- *Clauses types.* Les accords partageant un même modèle sont comptés individuellement ; le nombre de rédactions distinctes est donc plus faible.
- *Citations.* Chacune a été vérifiée mot à mot dans l’extrait de l’accord cité.
- *Évolution.* Les parts par année portent sur les accords collectés ; #f.partial_year est une année partielle.

#context [#metadata(counter(page).final().first()) <pages>]
