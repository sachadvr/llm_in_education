"""Rule templates for deterministic learner feedback."""

from __future__ import annotations


# Base templates by error type
BASE_TEMPLATES: dict[str, dict[str, str]] = {
    "tense": {
        "rule": "Utilisez le bon temps avec le marqueur temporel.",
        "explanation": "Les marqueurs du passé nécessitent la forme passée ; les marqueurs du futur nécessitent will + verbe.",
        "example": "She went yesterday. / She will go tomorrow.",
        "hint": "Vérifiez yesterday/tomorrow.",
    },
    "agreement": {
        "rule": "Accordez le sujet et le verbe.",
        "explanation": "Un sujet singulier prend la forme singulière du verbe.",
        "example": "He goes. / They go.",
        "hint": "Singulier ou pluriel ?",
    },
    "article": {
        "rule": "Choisissez le bon article.",
        "explanation": "Utilisez a/an avant un nom singulier dénombrable, the pour un élément spécifique.",
        "example": "an apple, a car, the sun.",
        "hint": "Le son détermine a/an.",
    },
    "preposition": {
        "rule": "Utilisez la bonne préposition.",
        "explanation": "Les collocations courantes nécessitent des prépositions fixes.",
        "example": "interested in, good at, go to.",
        "hint": "Apprenez l'expression entière.",
    },
    "spelling": {
        "rule": "Vérifiez l'orthographe.",
        "explanation": "Une seule lettre peut changer le sens ou la correction.",
        "example": "receive, because, friend.",
        "hint": "Lisez le mot lentement.",
    },
    "word_choice": {
        "rule": "Utilisez le bon mot ou la bonne collocation.",
        "explanation": "Certains mots s'associent selon des schémas fixes.",
        "example": "make a mistake (pas do a mistake).",
        "hint": "Apprenez l'expression entière.",
    },
    "punctuation": {
        "rule": "Vérifiez la ponctuation.",
        "explanation": "Les apostrophes, virgules et points sont importants pour le sens.",
        "example": "It's (it is) vs its (possessif).",
        "hint": "Regardez les signes de ponctuation.",
    },
    "syntax": {
        "rule": "Vérifiez l'ordre des mots.",
        "explanation": "L'anglais a un ordre fixe sujet-verbe-objet.",
        "example": "She speaks English. (pas Speaks she English.)",
        "hint": "Le sujet d'abord, puis le verbe.",
    },
    "redundancy": {
        "rule": "Supprimez les mots inutiles.",
        "explanation": "Certains mots répètent la même idée.",
        "example": "return (pas return back).",
        "hint": "Le mot supplémentaire est-il nécessaire ?",
    },
    "verb_form": {
        "rule": "Utilisez la forme verbale correcte.",
        "explanation": "Les verbes changent de forme selon le temps, le sujet ou l'auxiliaire.",
        "example": "He is making (pas is make). / She went (pas she go).",
        "hint": "Vérifiez la terminaison du verbe.",
    },
    "noun_number": {
        "rule": "Utilisez singulier ou pluriel correctement.",
        "explanation": "Certains noms nécessitent la forme plurielle quand la quantité est supérieure à un.",
        "example": "two papers (pas two paper).",
        "hint": "Comptez les éléments.",
    },
    "other": {
        "rule": "Vérifiez la forme de la phrase.",
        "explanation": "La correction modifie la grammaire ou la formulation.",
        "example": "She runs every day. (pas She run every day.)",
        "hint": "Comparez la phrase originale et la phrase corrigée.",
    },
    "none": {
        "rule": "Aucune erreur détectée.",
        "explanation": "Votre phrase est correcte.",
        "example": "She goes to school every day. ✓",
        "hint": "Continuez à vous entraîner.",
    },
}


# Level-adapted templates (progressive disclosure)
LEVEL_TEMPLATES: dict[str, dict[str, dict[str, str]]] = {
    "A1": {
        "tense": {
            "rule": "Utilisez 'went' pour le passé, 'will go' pour le futur.",
            "explanation": "Yesterday = went. Tomorrow = will go.",
            "example": "I went yesterday. I will go tomorrow.",
            "hint": "Cherchez les mots de temps.",
        },
        "agreement": {
            "rule": "He/She/It + 's'.",
            "explanation": "Ajoutez 's' aux verbes avec he, she, it.",
            "example": "He goes. She eats.",
            "hint": "Se termine-t-il par 's' ?",
        },
        "article": {
            "rule": "Utilisez 'a' ou 'the'.",
            "explanation": "'A' pour un élément quelconque. 'The' pour un élément spécifique.",
            "example": "a book, the sun",
            "hint": "Est-ce spécifique ?",
        },
        "preposition": {
            "rule": "Apprenez préposition + mot ensemble.",
            "explanation": "Certains mots vont toujours avec la même préposition.",
            "example": "in the morning, at school",
            "hint": "Mémorisez la paire.",
        },
        "spelling": {
            "rule": "Vérifiez votre orthographe.",
            "explanation": "Certains mots s'écrivent différemment de leur prononciation.",
            "example": "school, because",
            "hint": "Récrivez-le.",
        },
        "word_choice": {
            "rule": "Apprenez les mots qui vont ensemble.",
            "explanation": "Certains verbes nécessitent des noms spécifiques.",
            "example": "make a mistake",
            "hint": "Mémorisez la paire.",
        },
        "punctuation": {
            "rule": "Utilisez ' ou . correctement.",
            "explanation": "Une apostrophe indique une lettre manquante.",
            "example": "It's cold. (it is)",
            "hint": "Cela signifie-t-il 'it is' ?",
        },
        "syntax": {
            "rule": "Mettez le sujet en premier.",
            "explanation": "En anglais, le sujet précède le verbe.",
            "example": "She runs fast.",
            "hint": "Qui fait l'action ?",
        },
        "redundancy": {
            "rule": "Ne répétez pas la même idée.",
            "explanation": "Certains mots signifient la même chose ensemble.",
            "example": "return (pas return back)",
            "hint": "Le mot supplémentaire est-il nécessaire ?",
        },
        "verb_form": {
            "rule": "Utilisez la bonne terminaison verbale.",
            "explanation": "Après he/she/it, ajoutez -s. Après 'is', utilisez -ing.",
            "example": "He goes. / She is making.",
            "hint": "Regardez le sujet et l'auxiliaire.",
        },
        "noun_number": {
            "rule": "Ajoutez -s pour plus d'un.",
            "explanation": "Si vous en avez deux ou plus, utilisez le pluriel.",
            "example": "two books",
            "hint": "Combien y en a-t-il ?",
        },
    },
    "A2": {
        "tense": {
            "rule": "Utilisez le bon temps avec le marqueur temporel.",
            "explanation": "Les marqueurs du passé (yesterday, ago) nécessitent la forme passée. Les marqueurs du futur (tomorrow, next) nécessitent will + verbe.",
            "example": "She went yesterday. / She will go tomorrow.",
            "hint": "Accordez le mot de temps avec la forme verbale.",
        },
        "agreement": {
            "rule": "Le sujet et le verbe doivent s'accorder.",
            "explanation": "Les sujets singuliers (he, she, it) prennent -s sur le verbe.",
            "example": "He goes. / They go.",
            "hint": "Le sujet est-il singulier ou pluriel ?",
        },
        "article": {
            "rule": "Choisissez a, an ou the.",
            "explanation": "Utilisez a/an avant un nom singulier dénombrable. Utilisez the pour un élément spécifique.",
            "example": "an apple, a car, the sun.",
            "hint": "Commence-t-il par un son vocalique ?",
        },
        "preposition": {
            "rule": "Utilisez la préposition correcte.",
            "explanation": "Les prépositions indiquent des relations. Apprenez les collocations courantes.",
            "example": "interested in, good at, go to.",
            "hint": "Pensez à la relation.",
        },
        "spelling": {
            "rule": "Vérifiez l'orthographe attentivement.",
            "explanation": "L'orthographe anglaise a de nombreuses exceptions. Les mots courants sont souvent mal orthographiés.",
            "example": "receive (i avant e), because, friend.",
            "hint": "Prononcez-le, vérifiez deux fois.",
        },
        "word_choice": {
            "rule": "Choisissez le bon mot ou la bonne collocation.",
            "explanation": "Certains mots ne s'associent qu'avec des partenaires spécifiques.",
            "example": "tell a story (pas say a story).",
            "hint": "Pensez au partenaire habituel.",
        },
        "punctuation": {
            "rule": "Utilisez correctement les virgules et apostrophes.",
            "explanation": "La ponctuation change le sens et la lisibilité.",
            "example": "Let's eat, Grandma. vs Let's eat Grandma.",
            "hint": "Lisez à voix haute en faisant les pauses.",
        },
        "syntax": {
            "rule": "Respectez l'ordre des mots standard.",
            "explanation": "Les questions et les subordonnées ont des règles d'ordre spécifiques.",
            "example": "Where is the book? (pas Where the book is?)",
            "hint": "L'auxiliaire avant le sujet dans les questions.",
        },
        "redundancy": {
            "rule": "Évitez les répétitions inutiles.",
            "explanation": "Les tournures redondantes alourdissent les phrases.",
            "example": "repeat (pas repeat again)",
            "hint": "Peut-on supprimer un mot ?",
        },
        "verb_form": {
            "rule": "Choisissez la forme verbale correcte.",
            "explanation": "Les formes verbales dépendent du temps, de l'aspect et du sujet.",
            "example": "He has gone. / She is making.",
            "hint": "Vérifiez l'auxiliaire et le marqueur temporel.",
        },
        "noun_number": {
            "rule": "Utilisez correctement les noms au pluriel.",
            "explanation": "Les noms dénombrables prennent le pluriel quand la quantité est supérieure à un.",
            "example": "many papers, several students",
            "hint": "Le nom est-il dénombrable ?",
        },
    },
    "B1": {
        "tense": {
            "rule": "Maintenez la cohérence des temps dans toute la phrase.",
            "explanation": "Les marqueurs temporels et les temps verbaux doivent s'accorder. Mélanger passé et futur crée une incohérence.",
            "example": "She went yesterday (pas tomorrow). / She will go next week.",
            "hint": "Vérifiez que toutes les références temporelles concordent.",
        },
        "agreement": {
            "rule": "Assurez l'accord sujet-verbe dans toutes les propositions.",
            "explanation": "Les sujets singuliers prennent des verbes singuliers ; les sujets composés suivent les règles and/or.",
            "example": "Neither John nor Mary likes coffee. / Both John and Mary like coffee.",
            "hint": "Identifiez le vrai sujet.",
        },
        "article": {
            "rule": "Utilisez les articles de façon appropriée pour la détermination.",
            "explanation": "A/an pour l'indéfini, the pour le défini. Zéro article pour les pluriels abstraits ou généraux.",
            "example": "Dogs are friendly. / The dogs in the park are friendly.",
            "hint": "Cela a-t-il été mentionné avant ?",
        },
        "preposition": {
            "rule": "Choisissez des prépositions précises selon le contexte.",
            "explanation": "Différentes prépositions créent des sens différents. Les verbes à particule sont particulièrement délicats.",
            "example": "look at (direction) vs. look for (chercher) vs. look after (s'occuper de)",
            "hint": "Considérez le changement de sens subtil.",
        },
        "spelling": {
            "rule": "Appliquez les règles d'orthographe et leurs exceptions.",
            "explanation": "Le doublement des consonnes, les lettres muettes et les formes irrégulières requièrent de l'attention.",
            "example": "running (double n), subtle (b muet), Wednesday",
            "hint": "Connaissez les exceptions courantes.",
        },
        "word_choice": {
            "rule": "Choisissez des collocations précises.",
            "explanation": "Les quasi-synonymes ont souvent des portées collocationnelles différentes.",
            "example": "do business, make progress, take action",
            "hint": "Quel verbe convient à ce nom ?",
        },
        "punctuation": {
            "rule": "Utilisez la ponctuation pour la clarté et le style.",
            "explanation": "Les points-virgules, deux-points et tirets structurent les phrases complexes.",
            "example": "Some people prefer tea; others prefer coffee.",
            "hint": "Découpez les longues phrases pour la lisibilité.",
        },
        "syntax": {
            "rule": "Maîtrisez les structures complexes et inversées.",
            "explanation": "Les conditionnelles, le passif et les clivées nécessitent un ordre soigné.",
            "example": "Had I known, I would have stayed. (conditionnel inversé)",
            "hint": "Vérifiez l'ordre des propositions.",
        },
        "redundancy": {
            "rule": "Éliminez les expressions redondantes.",
            "explanation": "Un style concis évite les pléonasmes et les tautologies.",
            "example": "advance planning (la planification est toujours à l'avance)",
            "hint": "Chaque mot apporte-t-il une information nouvelle ?",
        },
        "verb_form": {
            "rule": "Choisissez la forme verbale précise selon le contexte.",
            "explanation": "Les participes, gérondifs et infinitifs remplissent des fonctions grammaticales différentes.",
            "example": "Having finished, she left. / I enjoy swimming.",
            "hint": "Quel rôle grammatical joue le verbe ?",
        },
        "noun_number": {
            "rule": "Appliquez l'accord en nombre dans les groupes nominaux complexes.",
            "explanation": "Les noms collectifs et les quantifieurs nécessitent un marquage du nombre soigné.",
            "example": "a number of students are... / the number of students is...",
            "hint": "Le groupe nominal est-il singulier ou pluriel dans son sens ?",
        },
    },
    "B2": {
        "tense": {
            "rule": "Maîtrisez les séquences de temps complexes et l'aspect.",
            "explanation": "Les temps parfaits, les conditionnelles et les séquences narratives nécessitent un marquage temporel précis.",
            "example": "If she had known, she would have gone. / By next year, I will have finished.",
            "hint": "Distinguez le temps de référence du temps de l'événement.",
        },
        "agreement": {
            "rule": "Gérez les scénarios d'accord complexes.",
            "explanation": "Les noms collectifs, les quantifieurs et l'inversion nécessitent des schémas d'accord nuancés.",
            "example": "The team is/are... / None of them is/are...",
            "hint": "Considérez l'accord notionnel vs. formel.",
        },
        "article": {
            "rule": "Appliquez l'usage des articles dans des contextes complexes.",
            "explanation": "Les noms géographiques, les institutions et les distinctions abstrait/concret.",
            "example": "the Netherlands, university (dépend de la prononciation)",
            "hint": "Considérez le contexte historique ou culturel.",
        },
        "preposition": {
            "rule": "Utilisez des groupes prépositionnels avancés.",
            "explanation": "Expressions idiomatiques et variations stylistiques dans l'écriture formelle.",
            "example": "in accordance with, with regard to, pursuant to",
            "hint": "Reconnaissez le registre et la formalité.",
        },
        "spelling": {
            "rule": "Maintenez la précision avec les mots empruntés et les néologismes.",
            "explanation": "Les mots du latin, du grec et d'autres langues conservent souvent leurs schémas orthographiques d'origine.",
            "example": "bureau, chauffeur, zeitgeist",
            "hint": "Notez la langue d'origine.",
        },
        "word_choice": {
            "rule": "Maîtrisez les collocations propres au registre.",
            "explanation": "Les registres formel et informel utilisent des pairages lexicaux différents.",
            "example": "conduct an investigation (formel) vs carry out an investigation (neutre)",
            "hint": "Considérez le registre.",
        },
        "punctuation": {
            "rule": "Affinez la ponctuation pour un effet rhétorique.",
            "explanation": "Les tirets em et les parenthèses créent une emphase ou des incises.",
            "example": "The solution—unexpectedly—worked perfectly.",
            "hint": "Utilisez la ponctuation pour guider le lecteur.",
        },
        "syntax": {
            "rule": "Utilisez des constructions syntaxiques avancées.",
            "explanation": "L'antéposition, les clivées et les propositions participiales ajoutent de la sophistication stylistique.",
            "example": "What I need is more time. (clivée)",
            "hint": "Qu'est-ce que vous voulez mettre en valeur ?",
        },
        "redundancy": {
            "rule": "Atteignez la concision au niveau avancé.",
            "explanation": "Éliminez les modificateurs sémantiquement vides et les tournures redondantes.",
            "example": "consensus (pas general consensus), cooperate (pas cooperate together)",
            "hint": "Le modificateur est-il déjà implicite ?",
        },
        "verb_form": {
            "rule": "Maîtrisez les formes verbales nuancées.",
            "explanation": "Le subjonctif, les infinitifs parfaits et les propositions participiales ajoutent de la précision.",
            "example": "I suggest he go. / To have known her was a privilege.",
            "hint": "Considérez le mode et l'aspect, pas seulement le temps.",
        },
        "noun_number": {
            "rule": "Gérez le nombre dans l'écriture académique avancée.",
            "explanation": "Les noms massifs, les pluralia tantum et l'accord avec les sujets coordonnés.",
            "example": "data are (formel) / data is (informel)",
            "hint": "Considérez le registre et l'accord notionnel.",
        },
    },
}


# Template for when similar errors are found
SIMILAR_ERROR_TEMPLATE = {
    "intro": "Erreurs similaires chez d'autres apprenants :",
    "format": "• '{input}' → '{corrected}' (type : {error_type})",
}


def get_template(error_type: str, level: str = "A2") -> dict[str, str]:
    """Get feedback template for error type and learner level."""
    error_type = error_type.lower() if error_type else "other"
    level = level.upper() if level else "A2"

    if level in LEVEL_TEMPLATES:
        level_templates = LEVEL_TEMPLATES[level]
        if error_type in level_templates:
            return level_templates[error_type]

    return BASE_TEMPLATES.get(error_type, BASE_TEMPLATES["other"])


def get_all_error_types() -> list[str]:
    """Get list of all supported error types."""
    return list(BASE_TEMPLATES.keys())


def get_template_for_level(level: str) -> dict[str, dict[str, str]]:
    """Get all templates for a specific CECRL level."""
    level = level.upper() if level else "A2"
    return LEVEL_TEMPLATES.get(level, LEVEL_TEMPLATES.get("A2", {}))
