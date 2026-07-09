<!--
  Page « Aide / FAQ » — éditable directement sur GitHub.
  Chaque question commence par « ## » ; le texte qui suit (jusqu'à la question
  suivante) en est la réponse. Exemple :

    ## Ma question ?

    Ma réponse, en **Markdown** :
    * une liste
    * [un lien](https://exemple.fr)

  Les réponses acceptent le Markdown classique (gras, listes, liens, retours à
  la ligne avec un « \ » en fin de ligne). L'ordre des questions ici définit
  l'ordre d'affichage (la première est ouverte par défaut).
-->

## Qui développe le projet d'assistant IA SRDT ? Quel est l'objectif et l'utilisation du service ?

Le projet est porté par un « intrapreneur » (David Rive, responsable du service « accès au droit », DDETS Seine-Maritime), financé par la DGT et développé par la Fabrique Numérique des Ministères Sociaux, en suivant l'approche beta.gouv (plus d'infos ici).

L'objectif identifié pendant la phase d'investigation de 2024 est d'améliorer la qualité des réponses écrites des Services de Renseignement en Droit du Travail, à l'aide d'une IA dédiée et co-construite avec les agents de ces services qui sont les principaux utilisateurs (plus d'infos ici).

Aujourd'hui le service est déployé dans 24 départements (125 utilisateurs). Les statistiques d'usage sont consultables ici.

## Quelle IA a été utilisée pour construire ce service ? Avec quelles sources de données ?

Le service s'appuie sur l'IA développée par Mistral (modèle Mistral Large) pour construire ses réponses. Mais l'originalité, et la valeur ajoutée du service, tient dans le fait que chaque réponse est préalablement sourcée dans une base de connaissance propre, constituée :

* des fiches pratiques Code du Travail Numérique, Service-Public, Ministère du Travail
* articles de loi Légifrance
* du contenu des conventions collectives (en cours de construction)
* des dernières jurisprudences en accès sur Judilibre (en cours de construction)

Le fait de sourcer chaque réponse sur une base de connaissance tenue à jour permet d'éviter les confusions et hallucinations que l'on peut retrouver sur des IA grand public, ainsi que de donner les références précises avec lesquelles l'assistant construit sa réponse.

## Comment utiliser le service ?

Une fois connecté·e via votre identité pro-connect, vous avez directement accès à l'interface de conversation dans laquelle vous pouvez rentrer directement la question telle que reçue par l'usager, ou alors poser une question de droit reformulée préalablement.

L'assistant va d'abord reformuler la question pour vérifier la bonne compréhension, puis répondre aux différents points de droit soulevés. Vous pouvez ensuite relancer l'assistant pour demander des précisions ou corriger la réponse jusqu'à 5 fois.

## Comment insérer la convention collective ?

L'import de la convention collective se fait en utilisant le moteur de recherche ou en renseignant l'IDCC de la convention collective. Le rajout de la convention collective n'est pas obligatoire, mais il permet la plupart du temps d'avoir une réponse plus adaptée.

## Comment être informé des nouveautés sur le produit ?

Via la page « Nouveauté » dans le menu de gauche, via les newsletters, ou en participant aux webinaires régulièrement organisés.

## Comment faire des retours ou suggérer des modifications sur le produit ?

Via le formulaire support (lien [ici](https://tally.so/r/jao5z4))\
Ou en contactant l'intrapreneur : [david.rive@seine-maritime.gouv.fr](mailto:david.rive@seine-maritime.gouv.fr)

## Que faire si la réponse n'est pas satisfaisante ?

Si la première réponse n'est pas satisfaisante, vous avez d'abord la possibilité d'obtenir des précisions ou des corrections de forme en relançant la réponse (jusqu'à 5 relances possibles).

À ce titre, 3 suggestions automatiques sont proposées, mais vous avez la main pour écrire les vôtres :

« Résumer la réponse »\
« Rédiger un mail prêt à être envoyé »\
« Citer les références utilisées »

Si malgré ces relances la réponse reste insatisfaisante — notamment en cas d'hallucination ou d'absence de la question dans la base de connaissance — pensez à le signaler avec le pouce bas (👎) en expliquant brièvement le problème rencontré. C'est ce retour qui permet à l'équipe produit d'identifier les lacunes et d'améliorer le service.

## Pourquoi faut-il vérifier la réponse ?

Même si chaque réponse s'appuie sur une base de connaissance sourcée (contrairement à une IA grand public), l'assistant reste un modèle de langage : il peut mal interpréter une source, faire une synthèse imprécise entre plusieurs textes, ou manquer une nuance propre à la situation de l'usager.

La vérification des sources citées et de la cohérence de la réponse reste indispensable avant tout envoi. **L'agent reste seul responsable de la réponse finale transmise à l'usager** — l'assistant est un outil d'aide à la rédaction, pas un outil de décision autonome.

Malgré la base de connaissance sourcée, aucune IA n'offre une fiabilité de 100 %. Deux cas de figure principaux peuvent se présenter :

* **Une hallucination** : l'assistant génère une information qui semble plausible mais qui est en réalité incorrecte, inventée, ou qui déforme le contenu d'une source réelle.
* **Une réponse absente de la base de connaissance** : la question porte sur un sujet non couvert (ou pas encore couvert) par les sources disponibles. L'assistant peut alors produire une réponse imprécise, incomplète, ou générique plutôt que de l'indiquer clairement.

**Dans ces deux cas, il est essentiel de le signaler en cliquant sur le pouce bas (👎)** au niveau de la réponse concernée, et d'expliquer brièvement le problème rencontré. Ce retour n'est pas une simple formalité : c'est ce qui permet à l'équipe produit d'identifier les lacunes de la base de connaissance, de corriger les sources concernées, et d'améliorer la fiabilité du service pour tous les utilisateurs.

👉 En résumé : une réponse non vérifiée ne doit jamais être transmise telle quelle à l'usager, et une réponse fausse ou incomplète doit toujours être signalée via le pouce bas.
