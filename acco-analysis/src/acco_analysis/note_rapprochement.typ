// Note de rapprochement avec la note DS2/DS1: prose, figures from data.json
// (note_rapprochement.py). The look is style.typ, the same as the report.
#import "style.typ": *
#let data = json("data.json")
#let f = figures(data.f)

#show: report.with(
  title: "Rapprochement avec la note DS2/DS1",
  footer: [Rapprochement · snapshot #data.snapshot · #data.generated],
)

#title-block(
  [Rapprochement avec la note DS2/DS1],
  [Adaptation au changement climatique : convergences et écarts avec l'analyse des accords chaleur. Note interne.],
)

// prose
= Objet

La note DS2/DS1 du 31 août 2026 étudie l’aménagement des conditions de travail face au changement climatique dans les accords d’entreprise et de branche. Nous avons rapproché ses constats de notre analyse des clauses chaleur, menée sur #f.collected accords d’entreprise. Cette note dit où les deux textes concordent, où ils semblent s’opposer et comment lire chaque écart.

= Deux périmètres différents

La note DS2/DS1 porte sur les accords d’entreprise signés entre 2023 et 2026. Un premier corpus de 72 textes traite du changement climatique ; une recherche sur les fortes chaleurs, pour les accords signés depuis 2025, en a identifié 459, dont un échantillon de 40 a été retenu. Ses pourcentages portent sur des « entreprises » ou des « accords du corpus » ; l’effectif de référence n’est pas précisé. Elle couvre aussi la transition écologique et les conventions de branche.

Notre analyse ne traite que de la chaleur. Elle porte sur #f.collected accords signés de #f.years, collectés à partir de termes liés à la chaleur, dont #f.heat_loose contiennent une clause chaleur. Elle compte des accords (#f.companies entreprises distinctes derrière les #f.heat_strict accords lus par les deux modèles). Pour comparer, nous reprenons les accords signés depuis 2025 : #f.recent_collected collectés, dont #f.recent_heat_loose avec une clause chaleur, soit le même ordre de grandeur que les 459 textes de la note DS2/DS1.

= Ce qui converge

Sur les accords signés depuis 2025, les ordres de grandeur sont proches pour la plupart des mesures. Le tableau les rapproche : nos pourcentages portent sur les #f.recent_n accords signés depuis 2025 qui contiennent une clause chaleur, puis sur les #f.ded_n d’entre eux qui prévoient un dispositif dédié.

#block(breakable: false, table(
  columns: (2.3fr, 1fr, 1.2fr, 1.2fr),
  align: (left, center, center, center),
  table.header([Mesure], [Note DS2/DS1], [Nos accords signés depuis 2025], [dont dispositif dédié]),
  [Adaptation des horaires], [33~%], [#f.recent_schedule_share], [#f.ded_schedule_share],
  [Rafraîchissement], [22~%], [#f.recent_cooling_share], [#f.ded_cooling_share],
  [Mesures graduées selon la vigilance ou la température], [38~%], [#f.recent_graded_share], [#f.ded_graded_share],
  [Télétravail], [17~%], [#f.recent_telework_share], [#f.ded_telework_share],
  [Maintien de la rémunération], [17~%], [#f.recent_pay_maintained_share], [#f.ded_pay_maintained_share],
))

Pour nous, une mesure est graduée lorsque le déclencheur est un niveau de vigilance ou un seuil de température ; la note DS2/DS1 parle de mesures adaptées aux différents niveaux de température. Les deux textes citent aussi le décret n° 2025-482 du 27 mai 2025, l’alerte rouge de fin juin 2026 et le télétravail comme réponse d’urgence aux aléas climatiques. Le maintien de la rémunération est la seule ligne où les chiffres s’écartent nettement ; il fait l’objet du deuxième écart ci-dessous.

= Quatre écarts apparents

*Part des clauses générales.* Notre analyse indique que, dans quatre accords sur dix, la chaleur n’est qu’un cas parmi d’autres dans une clause générale. Cette part porte sur l’ensemble du corpus. Dans les accords signés depuis 2025, elle tombe à #f.recent_generic_share (#f.recent_generic accords), ce qui rejoint le constat de la note DS2/DS1 d’un « nouveau facteur d’organisation du travail ». Les deux textes ne s’opposent donc pas : ils décrivent des périodes différentes.

*Rémunération.* La note DS2/DS1 relève que 17 % des entreprises étudiées maintiennent la rémunération en cas d’aléas climatiques. Notre analyse en compte #f.recent_pay_maintained (#f.recent_pay_maintained_share) parmi les accords signés depuis 2025, et #f.recent_pay_unspecified_share d’accords muets sur la rémunération. Deux raisons au moins expliquent l’écart : la note DS2/DS1 couvre tous les aléas climatiques (neige, intempéries, compteurs d’heures), alors que nous ne lisons que les clauses chaleur ; et son échantillon de 40 accords repose sur des critères de sélection que nous ne connaissons pas. Les deux chiffres ne se contredisent pas, mais ils ne se superposent pas : il faut les citer avec leur périmètre.

*Décret du 27 mai 2025.* La note DS2/DS1 écrit qu’il renforce la prise en compte des risques liés à la chaleur ; notre analyse écrit qu’il n’est cité que par #f.decree accords. Les deux énoncés sont compatibles. #f.recent_decree d’entre eux sont signés depuis 2025, soit #f.recent_decree_share des #f.recent_n accords de la période. Un décret peut peser sur les pratiques sans être cité dans les textes, et notre corpus ne mesure que ce que les textes citent.

*Secteurs et branches.* La note DS2/DS1 ne repère pas de logique sectorielle dans les conventions de branche : neuf branches mentionnent les fortes chaleurs, sans concentration nette. Notre analyse montre qu’au niveau des accords d’entreprise le secteur oriente la manière de traiter la chaleur (dispositifs dédiés dans l’industrie, les transports et la construction ; télétravail dans l’administration et les bureaux). Les deux constats portent sur des niveaux différents. La branche du paysage (IDCC 7018) ne figure pas parmi les neuf branches citées : ses #f.land accords reposent surtout sur des clauses types (#f.land_template accords), dont nous ne pouvons pas dire qu’elles proviennent de la convention de branche.

= Pour citer les deux textes ensemble

- *Préciser le périmètre.* Les accords signés depuis 2025 pour la comparaison, l’ensemble du corpus (#f.years) pour la note d’ensemble.
- *Ne pas additionner les pourcentages.* Les unités (entreprises, accords) et les effectifs de référence diffèrent.
- *Rémunération.* Rappeler que la note DS2/DS1 couvre tous les aléas climatiques, et nous seulement la chaleur.
- *Textes et pratiques.* Distinguer ce que les textes citent, comme le décret, de ce que les entreprises font.

#context [#metadata(counter(page).final().first()) <pages>]
