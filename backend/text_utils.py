import json
import re


def extract_json(text: str) -> dict | None:
    text = (text or "").strip()
    if "```" in text:
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            text = match.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


def unwrap_json_string(s: str) -> str:
    s = (s or "").strip()
    for _ in range(8):
        if not s:
            return s
        while s.endswith("}") and s.count("}") > s.count("{"):
            s = s[:-1].strip().rstrip('"')
        if s.startswith("{") and "corrected" in s:
            obj = extract_json(s)
            if isinstance(obj, dict) and isinstance(obj.get("corrected"), str):
                s = obj["corrected"].strip()
                continue
            match = re.search(r'"corrected"\s*:\s*"((?:[^"\\]|\\.)*)"', s)
            if match:
                s = match.group(1).replace('\\"', '"').strip()
                continue
        if s.startswith("{") and "feedback" in s:
            obj = extract_json(s)
            if isinstance(obj, dict) and isinstance(obj.get("feedback"), str):
                s = obj["feedback"].strip()
                continue
            match = re.search(r'"feedback"\s*:\s*"((?:[^"\\]|\\.)*)"', s)
            if match:
                s = match.group(1).replace('\\"', '"').strip()
                continue
        if s.startswith('"') and s.endswith('"') and len(s) >= 2:
            s = s[1:-1].replace('\\"', '"').strip()
            continue
        if s.startswith('\\"') and s.endswith('\\"') and len(s) >= 4:
            s = s[2:-2].replace('\\"', '"').strip()
            continue
        break
    return s


def normalize(s: str) -> str:
    return " ".join(s.strip().split()).lower().rstrip(".!? ")


def tokenize(phrase: str) -> list[str]:
    if not phrase or not phrase.strip():
        return []
    return re.findall(r"[A-Za-zÀ-ÿ0-9']+|[^\sA-Za-zÀ-ÿ0-9']", phrase.strip())


def edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1]


def has_tense_mismatch(s: str) -> bool:
    low = normalize(s)
    past_verbs = (" went ", " drove ", " was ", " had ", " did ")
    future_time = ("tomorrow", " next ", " next week")
    past_time = ("yesterday", " last ", " ago")
    if any(p in low for p in past_verbs) and any(f in low for f in future_time):
        return True
    if (" will " in low or " will go " in low) and any(t in low for t in past_time):
        return True
    return False


def suggest_feedback(phrase: str) -> str:
    low = normalize(phrase)
    if " go " in low and ("yesterday" in low or "last " in low or "ago" in low):
        return "Erreur de temps : avec le passe (yesterday, last...), utilisez 'went'. Exemple : She went to school yesterday."
    if (" went " in low or " drove " in low) and ("tomorrow" in low or "next " in low):
        return "Incoherence : passe (went/drove) avec 'tomorrow'. Utilisez 'will go' / 'will drive'. Exemple : She will go to school tomorrow."
    if " drive " in low or " drove " in low:
        if "tomorrow" in low or "next " in low:
            return "Erreur de temps : avec 'tomorrow' utilisez 'will drive'. Exemple : She will drive to school tomorrow."
    return "Le modele n'a pas propose de correction valide. Verifiez le temps verbal (passe avec yesterday, futur avec tomorrow). Exemple : She went to school yesterday."


def suggest_error_type(phrase: str) -> str:
    low = normalize(phrase)
    if has_tense_mismatch(phrase):
        return "tense"
    if any(p in low for p in (" she go ", " he go ", " it go ", " he have ", " she have ", " it have ")):
        return "agreement"
    # Plural / number hints
    if re.search(r'\b(paper|tax|book|car|dog|cat|student|teacher|friend)s?\b', low):
        # Heuristic: if there are bare plural nouns with singular verbs
        pass
    if " a " in low or " an " in low:
        return "article"
    return "other"


def make_prompt(sentence: str, blank: str) -> str:
    if not sentence or not blank:
        return sentence
    return sentence.replace(blank, "____", 1)


def fill_blank(sentence: str, blank: str, user_answer: str) -> str:
    if not sentence or not blank:
        return sentence
    return sentence.replace(blank, user_answer, 1)


def sanitize_hint_fr(hint_fr: str) -> str:
    hint = (hint_fr or "").strip().lower()
    if not hint:
        return ""
    if len(hint) > 20 or " " in hint:
        return ""
    banned = {"outil", "chose", "truc", "objet", "machin"}
    if hint in banned:
        return ""
    return hint


def same_meaning(original: str, corrected: str) -> bool:
    a, b = normalize(original), normalize(corrected)
    return a == b or a.split() == b.split()


def article_changed(original: str, corrected: str) -> bool:
    articles = {"a", "an", "the"}
    orig = set(re.findall(r"[a-zA-Z']+", original.lower()))
    corr = set(re.findall(r"[a-zA-Z']+", corrected.lower()))
    return bool(articles & (orig ^ corr))


def preposition_changed(original: str, corrected: str) -> bool:
    preps = {"in", "on", "at", "to", "for", "from", "with", "by", "of", "into", "onto", "about"}
    orig = set(re.findall(r"[a-zA-Z']+", original.lower()))
    corr = set(re.findall(r"[a-zA-Z']+", corrected.lower()))
    return bool(preps & (orig ^ corr))


def plural_changed(original: str, corrected: str) -> bool:
    """Detect singular/plural noun changes (e.g. paper → papers)."""
    orig_words = set(tokenize(original.lower()))
    corr_words = set(tokenize(corrected.lower()))
    for o in orig_words:
        if o + "s" in corr_words or o + "es" in corr_words:
            return True
    for c in corr_words:
        if c + "s" in orig_words or c + "es" in orig_words:
            return True
    return False


def word_choice_changed(original: str, corrected: str) -> bool:
    """Detect lexical / collocation errors (e.g. do/make, say/tell)."""
    collocations = {
        ("do", "make"), ("make", "do"),
        ("say", "tell"), ("tell", "say"),
        ("listen", "hear"), ("hear", "listen"),
        ("watch", "look"), ("look", "watch"),
        ("funny", "fun"), ("fun", "funny"),
        ("borrow", "lend"), ("lend", "borrow"),
        ("win", "earn"), ("earn", "win"),
        ("job", "work"), ("work", "job"),
        ("advice", "advise"),
    }
    orig_words = set(tokenize(original.lower()))
    corr_words = set(tokenize(corrected.lower()))
    diff = orig_words ^ corr_words
    for o, c in collocations:
        if o in diff and c in diff:
            return True
    return False


def punctuation_changed(original: str, corrected: str) -> bool:
    """Detect punctuation-only or apostrophe changes."""
    import string

    orig_punct = set(c for c in original if c in string.punctuation)
    corr_punct = set(c for c in corrected if c in string.punctuation)
    if orig_punct != corr_punct:
        orig_words = set(tokenize(original.lower()))
        corr_words = set(tokenize(corrected.lower()))
        if orig_words == corr_words:
            return True
        if "'" in (orig_punct ^ corr_punct):
            return True
    return False


def syntax_changed(original: str, corrected: str) -> bool:
    """Detect word-order / syntax changes (same words, different order)."""
    orig_tokens = tokenize(original.lower())
    corr_tokens = tokenize(corrected.lower())
    return set(orig_tokens) == set(corr_tokens) and orig_tokens != corr_tokens


def redundancy_changed(original: str, corrected: str) -> bool:
    """Detect redundancy errors (e.g. return back -> return)."""
    orig_tokens = tokenize(original.lower())
    corr_tokens = tokenize(corrected.lower())
    if len(corr_tokens) < len(orig_tokens) and set(corr_tokens) <= set(orig_tokens):
        redundant_pairs = [
            ("return", "back"), ("repeat", "again"), ("free", "gift"),
            ("enter", "in"), ("meet", "with"), ("raise", "up"),
            ("close", "near"), ("final", "outcome"),
        ]
        orig_set = set(orig_tokens)
        corr_set = set(corr_tokens)
        for w1, w2 in redundant_pairs:
            if w1 in orig_set and w2 in orig_set and w2 not in corr_set:
                return True
    return False


def verb_form_changed(original: str, corrected: str) -> bool:
    """Detect verb form errors (same verb family, different form)."""
    verb_families = [
        {"make", "makes", "made", "making"},
        {"do", "does", "did", "done", "doing"},
        {"go", "goes", "went", "gone", "going"},
        {"have", "has", "had", "having"},
        {"eat", "eats", "ate", "eaten", "eating"},
        {"write", "writes", "wrote", "written", "writing"},
        {"take", "takes", "took", "taken", "taking"},
        {"give", "gives", "gave", "given", "giving"},
        {"see", "sees", "saw", "seen", "seeing"},
        {"run", "runs", "ran", "run", "running"},
    ]
    orig_tokens_set = set(tokenize(original.lower()))
    corr_tokens_set = set(tokenize(corrected.lower()))
    for family in verb_families:
        if (
            (orig_tokens_set & family)
            and (corr_tokens_set & family)
            and orig_tokens_set != corr_tokens_set
        ):
            return True
    return False


def is_spelling_error(original: str, corrected: str) -> bool:
    orig_words = re.findall(r"[a-zA-Z']+", original.lower())
    corr_words = re.findall(r"[a-zA-Z']+", corrected.lower())
    if len(orig_words) != len(corr_words):
        return False
    diffs = [(o, c) for o, c in zip(orig_words, corr_words) if o != c]
    if len(diffs) != 1:
        return False
    o, c = diffs[0]
    return edit_distance(o, c) <= 2


# Canonical set of error types used across the system
ERROR_TYPES = {
    "none", "tense", "agreement", "article", "preposition",
    "spelling", "word_choice", "punctuation", "syntax", "redundancy",
    "verb_form", "noun_number",
    "other", "unknown", "deletion", "insertion",
}


def classify_error_type(original: str, corrected: str, model_error_type: str) -> str:
    if model_error_type in ERROR_TYPES and model_error_type not in {"unknown", "other"}:
        return model_error_type
    if same_meaning(original, corrected):
        return "none"
    if has_tense_mismatch(original) or has_tense_mismatch(corrected):
        return "tense"
    # Agreement BEFORE article/preposition — number is structurally dominant
    if suggest_error_type(original) == "agreement" or plural_changed(original, corrected):
        # Distinguish subject-verb agreement from simple noun number
        orig_tokens = tokenize(original.lower())
        corr_tokens = tokenize(corrected.lower())
        agreement_verbs = {
            "is", "are", "was", "were", "has", "have",
            "does", "do", "goes", "go", "eats", "eat",
            "makes", "make", "takes", "take", "writes", "write",
        }
        has_agreement_verb = any(
            (o != c and (o in agreement_verbs or c in agreement_verbs))
            for o, c in zip(orig_tokens, corr_tokens)
        )
        if has_agreement_verb:
            return "agreement"
        return "noun_number"
    if article_changed(original, corrected):
        return "article"
    if preposition_changed(original, corrected):
        return "preposition"
    if is_spelling_error(original, corrected):
        return "spelling"
    if punctuation_changed(original, corrected):
        return "punctuation"
    if word_choice_changed(original, corrected):
        return "word_choice"
    if syntax_changed(original, corrected):
        return "syntax"
    if redundancy_changed(original, corrected):
        return "redundancy"
    # Check for verb form errors (same verb family, different form)
    verb_families = [
        {"make", "makes", "made", "making"},
        {"do", "does", "did", "done", "doing"},
        {"go", "goes", "went", "gone", "going"},
        {"have", "has", "had", "having"},
        {"eat", "eats", "ate", "eaten", "eating"},
        {"write", "writes", "wrote", "written", "writing"},
        {"take", "takes", "took", "taken", "taking"},
        {"give", "gives", "gave", "given", "giving"},
        {"see", "sees", "saw", "seen", "seeing"},
        {"run", "runs", "ran", "run", "running"},
    ]
    orig_tokens_set = set(tokenize(original.lower()))
    corr_tokens_set = set(tokenize(corrected.lower()))
    for family in verb_families:
        if (
            (orig_tokens_set & family)
            and (corr_tokens_set & family)
            and orig_tokens_set != corr_tokens_set
        ):
            return "verb_form"
    # Structural length mismatch → syntax (last resort before other)
    if len(tokenize(original)) != len(tokenize(corrected)):
        return "syntax"
    return "other"


def ensure_example(feedback: str, corrected: str) -> str:
    if not feedback:
        return f"Exemple : {corrected}"
    low = feedback.lower()
    if "exemple" in low or "example" in low:
        return feedback
    return f"{feedback} Exemple : {corrected}"


def compute_diff(original: str, corrected: str) -> list[dict]:
    """
    Calcule la différence entre deux phrases au niveau token
    et retourne une liste de spans d'erreurs.
    """
    import difflib

    tokens_orig = tokenize(original)
    tokens_corr = tokenize(corrected)

    matcher = difflib.SequenceMatcher(None, tokens_orig, tokens_corr)
    spans = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue

        orig_chunk = " ".join(tokens_orig[i1:i2])
        corr_chunk = " ".join(tokens_corr[j1:j2])

        # Essayer de classifier le type d'erreur pour ce span
        span_type = "other"
        if tag == "replace":
            if is_spelling_error(orig_chunk, corr_chunk):
                span_type = "spelling"
            elif article_changed(orig_chunk, corr_chunk):
                span_type = "article"
            elif plural_changed(orig_chunk, corr_chunk):
                # Distinguish agreement vs noun_number
                orig_tokens_local = tokenize(orig_chunk.lower())
                corr_tokens_local = tokenize(corr_chunk.lower())
                agreement_verbs = {
                    "is", "are", "was", "were", "has", "have",
                    "does", "do", "goes", "go", "eats", "eat",
                    "makes", "make", "takes", "take", "writes", "write",
                }
                has_agreement_verb = any(
                    (o != c and (o in agreement_verbs or c in agreement_verbs))
                    for o, c in zip(orig_tokens_local, corr_tokens_local)
                )
                span_type = "agreement" if has_agreement_verb else "noun_number"
            elif preposition_changed(orig_chunk, corr_chunk):
                span_type = "preposition"
            elif punctuation_changed(orig_chunk, corr_chunk):
                span_type = "punctuation"
            elif word_choice_changed(orig_chunk, corr_chunk):
                span_type = "word_choice"
            elif syntax_changed(orig_chunk, corr_chunk):
                span_type = "syntax"
            elif redundancy_changed(orig_chunk, corr_chunk):
                span_type = "redundancy"
            elif verb_form_changed(orig_chunk, corr_chunk):
                span_type = "verb_form"
            elif len(tokens_orig[i1:i2]) != len(tokens_corr[j1:j2]):
                span_type = "syntax"
        elif tag == "delete":
            span_type = "deletion"
        elif tag == "insert":
            span_type = "insertion"

        spans.append(
            {
                "tag": tag,
                "original": orig_chunk,
                "corrected": corr_chunk,
                "type": span_type,
                "start": i1,
                "end": i2,
            }
        )

    return spans
