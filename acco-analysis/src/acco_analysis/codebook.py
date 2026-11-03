"""The codebook: what is recorded about each heat clause, and the allowed answers.

One definition feeds the prompt, the validation of the model's answers and the families,
so a code cannot be in the prompt and missing from the check. Codes are English
identifiers; labels and definitions are French, as the passages are.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Dimension:
    name: str
    label: str
    multi: bool
    values: dict[str, tuple[str, str]]  # code -> (label, definition)


MEASURES = Dimension(
    "measures",
    "Mesures",
    True,
    {
        "schedule_shift": (
            "horaires décalés ou aménagés",
            "heures d'arrivée ou de départ modifiées, plages horaires déplacées, équipes décalées",
        ),
        "summer_hours": (
            "horaires d'été fixes",
            "horaires particuliers prévus à l'avance pour une période de l'année "
            "(ex : 6h-13h du 1er juin au 30 septembre)",
        ),
        "shorter_day": (
            "journée raccourcie ou arrêt anticipé",
            "durée du travail réduite ce jour-là",
        ),
        "rest_derogation": (
            "dérogation au repos",
            "dérogation au repos hebdomadaire ou quotidien",
        ),
        "extra_breaks": ("pauses supplémentaires", "pauses ajoutées ou allongées"),
        "water": (
            "eau",
            "distribution d'eau, fontaines, bouteilles, boissons fraîches",
        ),
        "cooling": (
            "rafraîchissement",
            "climatisation, ventilateurs, brumisateurs, salle de repos fraîche, isolation",
        ),
        "protective_gear": (
            "équipement ou tenue de protection",
            "EPI, vêtements adaptés (short, pantacourt), chapeau, crème solaire",
        ),
        "telework": ("télétravail", "télétravail ou travail à distance"),
        "prime": ("prime ou indemnité", "somme versée à cause de la chaleur"),
        "time_off": (
            "congé ou temps libéré",
            "jour de congé, autorisation de s'absenter ou de quitter le poste",
        ),
        "collective_stoppage": (
            "interruption collective du travail",
            "arrêt du travail décidé pour tous, avec maintien de la rémunération ou récupération des heures",
        ),
        "same_day_change": (
            "modification d'horaires le jour même",
            "changement du programme de travail sans délai de prévenance (force majeure, intempéries)",
        ),
        "production_stop": (
            "arrêt ou suspension de l'activité",
            "arrêt d'un chantier, d'une tâche ou de la production à cause de la chaleur, décidé sur le moment ; "
            "pas une interruption collective avec maintien de rémunération ou récupération des heures (valeur ci-dessus)",
        ),
        "risk_assessment": (
            "diagnostic ou évaluation des risques",
            "identification des postes exposés, relevés de température, document unique",
        ),
        "action_plan": (
            "plan d'action ou procédure",
            "plan canicule, protocole, dispositif organisé ; pas une simple liste de mesures déjà codées par ailleurs",
        ),
        "prevention_info": (
            "information ou sensibilisation",
            "affichage, messages de prévention, formation, rappel des gestes",
        ),
        "health_follow_up": (
            "suivi médical ou de santé",
            "médecine du travail, surveillance de la santé",
        ),
        "reference_only": (
            "simple renvoi",
            "renvoi à une loi, un décret ou un plan, sans dire ce qui est fait",
        ),
        "other": (
            "autre mesure",
            "mesure qui ne rentre dans aucune des valeurs ci-dessus",
        ),
    },
)

TRIGGERS = Dimension(
    "triggers",
    "Déclencheur",
    True,
    {
        "vigilance_yellow": ("vigilance jaune", "vigilance Météo-France jaune"),
        "vigilance_orange": ("vigilance orange", "vigilance Météo-France orange"),
        "vigilance_red": ("vigilance rouge", "vigilance Météo-France rouge"),
        "vigilance_unspecified": (
            "vigilance sans couleur",
            "alerte ou vigilance canicule sans niveau précisé",
        ),
        "temperature_threshold": (
            "seuil de température",
            "température ou indice chiffré à partir duquel la mesure s'applique",
        ),
        "fixed_period": (
            "période fixe",
            "dates du calendrier (ex : du 1er juin au 15 septembre)",
        ),
        "employer_decision": (
            "décision de l'employeur",
            "la direction juge ou déclenche",
        ),
        "workplace_temperature": (
            "température relevée sur place",
            "mesure de la température du lieu de travail",
        ),
        "event_list": (
            "chaleur parmi une liste d'événements",
            "canicule citée avec neige, inondation, pollution...",
        ),
        "canicule_unqualified": (
            "canicule sans précision",
            "« en cas de canicule » ou « fortes chaleurs » SEULEMENT si le texte ne donne aucun autre déclencheur "
            "(ni vigilance, ni seuil, ni période, ni liste d'événements)",
        ),
        "none": ("aucun", "le texte ne dit pas ce qui déclenche"),
        "other": ("autre", "déclencheur qui ne rentre dans aucune valeur ci-dessus"),
    },
)

INITIATIVE = Dimension(
    "initiative",
    "Initiative",
    False,
    {
        "employer": ("employeur", "la direction décide ou impose"),
        "employee": ("demande du salarié", "à la demande du salarié"),
        "agreed_with_reps": (
            "accord avec les représentants",
            "décidé avec le CSE ou les syndicats",
        ),
        "automatic": ("automatique", "s'applique de plein droit dès le déclencheur"),
        "unspecified": ("non précisée", "le texte ne le dit pas"),
    },
)

SCOPE = Dimension(
    "scope",
    "Public concerné",
    True,
    {
        "all_staff": (
            "tous les salariés",
            "le texte dit expressément « tous les salariés » ou « l'ensemble du personnel » ; sinon « non précisé »",
        ),
        "site_outdoor": (
            "chantier ou extérieur",
            "salariés de chantier ou travaillant en extérieur",
        ),
        "production_shift": (
            "production ou équipes",
            "salariés de production, ateliers, équipes postées",
        ),
        "named_services": (
            "services ou métiers nommés",
            "services, sites ou métiers cités",
        ),
        "vulnerable": (
            "salariés vulnérables",
            "femmes enceintes, travailleurs handicapés, salariés fragiles",
        ),
        "eligible_only": (
            "salariés éligibles",
            "seulement ceux dont le poste le permet",
        ),
        "unspecified": ("non précisé", "le texte ne le dit pas"),
        "other": ("autre", "public qui ne rentre dans aucune valeur ci-dessus"),
    },
)

PAY = Dimension(
    "pay",
    "Effet sur la rémunération",
    False,
    {
        "maintained": ("maintenue", "la rémunération est maintenue"),
        "extra_pay": ("supplément", "rémunération supplémentaire ou prime"),
        "none_explicit": (
            "aucune",
            "le texte exclut toute majoration ou toute indemnité",
        ),
        "recovered_unpaid": (
            "récupération non rémunérée",
            "heures perdues récupérées sans nouveau paiement",
        ),
        "unspecified": ("non précisé", "le texte ne dit rien de la rémunération"),
    },
)

PROCEDURE = Dimension(
    "procedure",
    "Procédure",
    True,
    {
        "reps_consulted": (
            "CSE consulté ou informé",
            "la mesure suppose une consultation ou une information des représentants du personnel ; pas le dépôt ou la notification de l'accord lui-même",
        ),
        "notice_period": ("délai de prévenance", "délai à respecter avant d'appliquer"),
        "manager_approval": (
            "accord du responsable",
            "autorisation du manager ou de la direction",
        ),
        "employee_consent": (
            "consentement ou volontariat",
            "accord du salarié, volontariat",
        ),
        "written_note": (
            "note écrite",
            "la mesure se déclenche ou s'annonce par un écrit (note de service, mail, affichage) ; pas le dépôt de l'accord ni un planning",
        ),
        "fixed_duration": (
            "durée limitée",
            "le texte limite expressément la durée de la mesure (ex : « pour 2 mois », « temporairement », « pour l'année 2020 »)",
        ),
        "none": ("aucune", "pas de procédure"),
    },
)

STRENGTH = Dimension(
    "strength",
    "Portée de la clause",
    False,
    {
        "obligation": (
            "obligation",
            "« doit », « est mis en place », droit du salarié",
        ),
        "permission": ("simple faculté", "« peut », « pourra », sous réserve"),
        "principle": (
            "principe ou objectif",
            "intention, engagement général, thème à travailler",
        ),
        "reference_only": (
            "renvoi uniquement",
            "renvoie à un autre texte sans rien prévoir",
        ),
    },
)

DIMENSIONS = (MEASURES, TRIGGERS, INITIATIVE, SCOPE, PAY, PROCEDURE, STRENGTH)
NUMBER_KINDS = (
    "temperature_c",
    "amount_eur",
    "duration_minutes",
    "notice_days",
    "date",
    "time",
    "other",
)

# A passage belongs to every family one of whose measures it has. These are views over
# the codes, not clusters: a passage with a shifted schedule and a prime is in two.
FAMILIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "hours": (
        "Horaires et aménagement du temps de travail",
        ("schedule_shift", "summer_hours", "shorter_day"),
    ),
    "rest": ("Dérogations au repos", ("rest_derogation",)),
    "telework": ("Télétravail", ("telework",)),
    "prevention": (
        "Prévention matérielle et organisationnelle",
        (
            "extra_breaks",
            "water",
            "cooling",
            "protective_gear",
            "risk_assessment",
            "action_plan",
            "prevention_info",
            "health_follow_up",
        ),
    ),
    "stoppage": (
        "Interruption du travail et force majeure",
        ("collective_stoppage", "same_day_change", "production_stop"),
    ),
    "pay": ("Primes et temps libéré", ("prime", "time_off")),
}
NO_FAMILY = "reference_or_other"


def families_of(measures: set[str]) -> list[str]:
    """The families a passage belongs to; `NO_FAMILY` when none of its measures is in one
    (a bare reference, or only 'other')."""
    found = [name for name, (_, codes) in FAMILIES.items() if measures & set(codes)]
    return found or [NO_FAMILY]


def render_codebook() -> str:
    """The codebook as the prompt describes it to the model."""
    lines = []
    for d in DIMENSIONS:
        how = "plusieurs valeurs possibles" if d.multi else "une seule valeur"
        lines.append(f'- "{d.name}" ({d.label}, {how}) :')
        lines += [
            f'    "{code}" : {label} ({definition})'
            for code, (label, definition) in d.values.items()
        ]
    return "\n".join(lines)


def check_values(dimension: Dimension, raw: Any) -> tuple[list[str], list[str]]:
    """(valid codes, unknown values) of a model answer for one dimension. A single-valued
    dimension keeps its first valid value."""
    if raw is None:
        return [], []
    items = raw if isinstance(raw, list) else [raw]
    valid: list[str] = []
    unknown: list[str] = []
    for item in items:
        code = item.get("code") if isinstance(item, dict) else item
        if isinstance(code, str) and code in dimension.values:
            if code not in valid:
                valid.append(code)
        else:
            unknown.append(str(code))
    if not dimension.multi:
        valid = valid[:1]
    return valid, unknown
