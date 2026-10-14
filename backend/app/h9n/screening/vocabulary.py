"""
vocabulary.py

H9N Milestone 3.1 - the fixed lists of property types and markets a mandate
may use, plus the alias maps that turn free-text wording into them.

Why this exists: the extractor (M1.1) never rewrites a document's wording, so
a Deal Profile says "garden-style apartment community" or "Dallas, TX", while
a mandate says "Multifamily" or "Dallas-Fort Worth". Mandates are therefore
saved only with the canonical names below, and the same functions are used to
read a Deal Profile's wording (M3.2), so both sides meet on one value:

    normalize_asset_type("Garden-style apartment community")  -> "Multifamily"
    normalize_market("Dallas-Fort Worth-Arlington, TX MSA")  -> "Dallas-Fort Worth"
    normalize_market("123 Main St, Plano, TX 75024")          -> "Dallas-Fort Worth"

Anything not recognized returns None ("unknown"), never a guess. To support a
new type or market, add it (and its aliases) here; GET
/api/h9n/mandates/vocabulary lists the current values for a UI.
"""

from __future__ import annotations

import re
from typing import Any, Optional

# --- Property types ---------------------------------------------------------

# Canonical type -> phrases that mean it. Two tiers:
#   _SPECIFIC_TYPE_PHRASES win whenever they appear, because they qualify a
#   general word ("student apartments" is Student Housing, "multifamily
#   development site" is Land, "medical office" is Medical Office);
#   _GENERAL_TYPE_PHRASES are otherwise read by which is mentioned FIRST - the
#   main noun - so "Office building with ground-floor retail" is Office and
#   "apartment community with retail" is Multifamily.
_SPECIFIC_TYPE_PHRASES: dict[str, tuple[str, ...]] = {
    "Senior Housing": (
        "senior housing",
        "seniors housing",
        "senior living",
        "senior apartments",
        "assisted living",
        "independent living",
        "memory care",
        "age restricted",
        "active adult",
        "55 and over",
    ),
    "Student Housing": ("student housing", "student apartments", "student living", "purpose built student"),
    "Medical Office": ("medical office", "mob", "outpatient medical"),
    "Manufactured Housing": (
        "manufactured housing",
        "manufactured home",
        "mobile home",
        "mobile home park",
        "rv park",
    ),
    "Single-Family Rental": ("single family rental", "sfr", "build to rent", "btr", "single family homes"),
    "Data Center": ("data center", "data centre"),
    "Mixed-Use": ("mixed use",),
    "Land": (
        "development site",
        "development parcel",
        "land for development",
        "development land",
        "vacant land",
        "raw land",
        "entitled land",
        "industrial land",
        "land parcel",
        "land site",
        "vacant lot",
    ),
    "Cold Storage": ("cold storage",),  # resolved to Industrial below
    "Flex Office": ("flex office",),  # resolved to Office below
}
_SPECIFIC_RESOLVES_TO = {"Cold Storage": "Industrial", "Flex Office": "Office"}

_GENERAL_TYPE_PHRASES: dict[str, tuple[str, ...]] = {
    "Multifamily": (
        "multifamily",
        "multi family",
        "apartment",
        "apartments",
        "apartment community",
        "garden style",
        "residential rental",
    ),
    "Office": ("office", "office building"),
    "Industrial": ("industrial", "warehouse", "distribution", "logistics", "flex", "manufacturing"),
    "Retail": (
        "retail",
        "shopping center",
        "strip center",
        "strip mall",
        "mall",
        "power center",
        "neighborhood center",
    ),
    "Self-Storage": ("self storage", "mini storage", "storage facility", "storage units"),
    "Hospitality": ("hospitality", "hotel", "motel", "lodging", "resort"),
    "Land": ("land",),
}

_ASSET_TYPE_PHRASES: dict[str, tuple[str, ...]] = {}
for _tier in (_SPECIFIC_TYPE_PHRASES, _GENERAL_TYPE_PHRASES):
    for _name, _phrases in _tier.items():
        _canonical = _SPECIFIC_RESOLVES_TO.get(_name, _name)
        _ASSET_TYPE_PHRASES[_canonical] = _ASSET_TYPE_PHRASES.get(_canonical, ()) + _phrases

ASSET_TYPES: list[str] = sorted(_ASSET_TYPE_PHRASES)

# --- Markets ----------------------------------------------------------------

# Canonical metro -> other names, main cities and abbreviations. City names
# shared by several metros (Arlington, Glendale, Columbia, Aurora, ...) are
# only listed with their state ("aurora co"), never bare.
_MARKET_ALIASES: dict[str, tuple[str, ...]] = {
    "Atlanta": ("atlanta", "marietta", "alpharetta", "sandy springs", "decatur"),
    "Austin": ("austin", "round rock", "san marcos", "georgetown tx"),
    "Baltimore": ("baltimore",),
    "Birmingham": ("birmingham al", "birmingham alabama"),
    "Boise": ("boise", "meridian id"),
    "Boston": ("boston", "cambridge ma", "somerville"),
    "Charleston": ("charleston sc", "charleston south carolina", "north charleston"),
    "Charlotte": ("charlotte",),
    "Chicago": ("chicago", "chicagoland", "evanston", "naperville"),
    "Cincinnati": ("cincinnati",),
    "Cleveland": ("cleveland",),
    "Columbus": ("columbus oh", "columbus ohio"),
    "Dallas-Fort Worth": ("dallas", "fort worth", "ft worth", "dfw", "plano", "irving", "frisco", "mckinney"),
    "Denver": ("denver", "aurora co", "lakewood co", "boulder"),
    "Detroit": ("detroit",),
    "Greenville": ("greenville sc", "greenville spartanburg", "spartanburg"),
    "Houston": ("houston", "the woodlands", "sugar land", "katy", "pearland"),
    "Indianapolis": ("indianapolis", "carmel in"),
    "Jacksonville": ("jacksonville",),
    "Kansas City": ("kansas city", "overland park"),
    "Las Vegas": ("las vegas", "henderson nv", "north las vegas"),
    "Los Angeles": ("los angeles", "long beach", "pasadena", "orange county", "irvine", "anaheim"),
    "Louisville": ("louisville",),
    "Memphis": ("memphis",),
    "Miami": ("miami", "south florida", "fort lauderdale", "ft lauderdale", "west palm beach", "boca raton"),
    "Minneapolis-St. Paul": ("minneapolis", "st paul", "saint paul", "twin cities"),
    "Nashville": ("nashville", "franklin tn", "murfreesboro"),
    "New Orleans": ("new orleans",),
    "New York": ("new york", "new york city", "nyc", "manhattan", "brooklyn", "queens", "bronx", "jersey city"),
    "Oklahoma City": ("oklahoma city", "okc"),
    "Orlando": ("orlando", "kissimmee"),
    "Philadelphia": ("philadelphia", "philly"),
    "Phoenix": ("phoenix", "scottsdale", "tempe", "mesa", "chandler", "gilbert"),
    "Pittsburgh": ("pittsburgh",),
    "Portland": ("portland or", "portland oregon", "beaverton"),
    "Raleigh-Durham": ("raleigh", "durham", "chapel hill", "research triangle", "cary nc"),
    "Richmond": ("richmond va", "richmond virginia"),
    "Sacramento": ("sacramento",),
    "Salt Lake City": ("salt lake city", "slc", "provo", "ogden"),
    "San Antonio": ("san antonio", "new braunfels"),
    "San Diego": ("san diego",),
    "San Francisco Bay Area": (
        "san francisco",
        "sf bay area",
        "bay area",
        "san francisco bay area",
        "oakland",
        "san jose",
        "silicon valley",
    ),
    "Savannah": ("savannah",),
    "Seattle": ("seattle", "bellevue wa", "tacoma", "puget sound"),
    "St. Louis": ("st louis", "saint louis"),
    "Tampa": ("tampa", "tampa bay", "st petersburg", "saint petersburg", "clearwater"),
    "Tucson": ("tucson",),
    "Washington, D.C.": (
        "washington dc",
        "washington d c",
        "washington arlington alexandria",
        "dc",
        "district of columbia",
        "northern virginia",
        "nova",
        "dmv",
    ),
}

MARKETS: list[str] = sorted(_MARKET_ALIASES)

# The states each market is in. When a location names a state, a market in a
# different state is never matched: "Portland, ME" is not Portland (OR), and
# "Charleston, WV" is not Charleston (SC).
_MARKET_STATES: dict[str, frozenset[str]] = {
    market: frozenset(states.split())
    for market, states in {
        "Atlanta": "ga", "Austin": "tx", "Baltimore": "md", "Birmingham": "al", "Boise": "id",
        "Boston": "ma nh", "Charleston": "sc", "Charlotte": "nc sc", "Chicago": "il in", "Cincinnati": "oh ky in",
        "Cleveland": "oh", "Columbus": "oh", "Dallas-Fort Worth": "tx", "Denver": "co", "Detroit": "mi",
        "Greenville": "sc", "Houston": "tx", "Indianapolis": "in", "Jacksonville": "fl", "Kansas City": "mo ks",
        "Las Vegas": "nv", "Los Angeles": "ca", "Louisville": "ky in", "Memphis": "tn ms ar", "Miami": "fl",
        "Minneapolis-St. Paul": "mn wi", "Nashville": "tn", "New Orleans": "la", "New York": "ny nj ct pa",
        "Oklahoma City": "ok", "Orlando": "fl", "Philadelphia": "pa nj de md", "Phoenix": "az",
        "Pittsburgh": "pa", "Portland": "or wa", "Raleigh-Durham": "nc", "Richmond": "va", "Sacramento": "ca",
        "Salt Lake City": "ut", "San Antonio": "tx", "San Diego": "ca", "San Francisco Bay Area": "ca",
        "Savannah": "ga", "Seattle": "wa", "St. Louis": "mo il", "Tampa": "fl", "Tucson": "az",
        "Washington, D.C.": "dc va md wv",
    }.items()
}

_STATE_NAMES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar", "california": "ca", "colorado": "co",
    "connecticut": "ct", "delaware": "de", "district of columbia": "dc", "florida": "fl", "georgia": "ga",
    "hawaii": "hi", "idaho": "id", "illinois": "il", "indiana": "in", "iowa": "ia", "kansas": "ks",
    "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md", "massachusetts": "ma",
    "michigan": "mi", "minnesota": "mn", "mississippi": "ms", "missouri": "mo", "montana": "mt",
    "nebraska": "ne", "nevada": "nv", "new hampshire": "nh", "new jersey": "nj", "new mexico": "nm",
    "new york": "ny", "new york state": "ny", "north carolina": "nc", "north dakota": "nd", "ohio": "oh",
    "oklahoma": "ok", "oregon": "or", "pennsylvania": "pa", "rhode island": "ri", "south carolina": "sc",
    "south dakota": "sd", "tennessee": "tn", "texas": "tx", "utah": "ut", "vermont": "vt", "virginia": "va",
    "washington": "wa", "washington state": "wa", "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy",
}

_STATE_CODES = set(_STATE_NAMES.values())

# A location in another country is never matched to a US market
# ("Birmingham, UK" is not Birmingham, AL).
_FOREIGN = re.compile(
    r"\b(uk|u k|united kingdom|england|scotland|wales|ireland|canada|mexico|costa rica|australia|germany|"
    r"france|spain|india|china|japan|brazil|puerto rico|ontario|british columbia|quebec|alberta)\b"
)

# Words that only describe a market, never name it: "Greater Houston Metro
# Area" means Houston. ("county" is kept: "Orange County" is an alias.)
_MARKET_FILLER = re.compile(
    r"\b(greater|metropolitan statistical area|metropolitan area|metropolitan|metro area|metroplex|metro|msa|"
    r"region|submarket|market|city of)\b"
)

_ZIP = re.compile(r"\s*\b\d{5}(-\d{4})?$")


def _as_states(piece: str) -> set[str]:
    """The states a piece names if it is ONLY state names/codes ("TX",
    "Texas", "PA-NJ-DE-MD", "TX 75201"), else an empty set. A word like "or"
    inside ordinary text is not read as Oregon."""
    piece = _ZIP.sub("", piece).strip()
    if piece in _STATE_NAMES:
        return {_STATE_NAMES[piece]}
    words = [word for word in re.split(r"[\s/-]+", piece) if word]
    if words and all(word in _STATE_CODES for word in words):
        return set(words)
    return set()


def _clean(text: str) -> str:
    """Lowercase, ASCII dashes, punctuation to spaces, single-spaced."""
    text = str(text).casefold().replace("&", " and ")
    text = re.sub(r"[‐-―]", "-", text)
    text = re.sub(r"[^\w\s,/-]", " ", text)  # drops periods: "St. Louis" -> "st louis"
    return " ".join(text.split())


def _contains_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


# Every canonical name (cleaned) and alias, pointing at its canonical name.
_ASSET_TYPE_LOOKUP: dict[str, str] = {}
for _canonical, _phrases in _ASSET_TYPE_PHRASES.items():
    for _phrase in (_canonical, *_phrases):
        _ASSET_TYPE_LOOKUP[_clean(_phrase).replace("-", " ")] = _canonical

_MARKET_LOOKUP: dict[str, str] = {}
for _canonical, _aliases in _MARKET_ALIASES.items():
    for _alias in (_canonical, *_aliases):
        _key = " ".join(_clean(_alias).replace("-", " ").replace(",", " ").split())
        # An alias may only ever mean one market.
        if _MARKET_LOOKUP.get(_key, _canonical) != _canonical:
            raise RuntimeError(f"Market alias {_alias!r} is listed for two markets.")
        _MARKET_LOOKUP[_key] = _canonical
if set(_MARKET_STATES) != set(_MARKET_ALIASES):
    raise RuntimeError("Every market needs its states in _MARKET_STATES.")


def _earliest(text: str, tier: dict[str, tuple[str, ...]]) -> Optional[str]:
    """The type in `tier` mentioned first in `text` (longest phrase on a tie)."""
    best: Optional[tuple[int, int, str]] = None
    for name, phrases in tier.items():
        for phrase in phrases:
            match = re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text)
            if match and (best is None or (match.start(), -len(phrase)) < best[:2]):
                best = (match.start(), -len(phrase), name)
    return None if best is None else _SPECIFIC_RESOLVES_TO.get(best[2], best[2])


def normalize_asset_type(text: Optional[str]) -> Optional[str]:
    """The canonical property type a piece of text describes, or None."""
    if not text or not str(text).strip():
        return None
    cleaned = _clean(text).replace("-", " ").replace("/", " ").replace(",", " ")
    cleaned = " ".join(cleaned.split())
    if cleaned in _ASSET_TYPE_LOOKUP:
        return _ASSET_TYPE_LOOKUP[cleaned]
    return _earliest(cleaned, _SPECIFIC_TYPE_PHRASES) or _earliest(cleaned, _GENERAL_TYPE_PHRASES)


def _words(value: str) -> str:
    return " ".join(value.replace("-", " ").replace("/", " ").replace(",", " ").split())


def _parse_location(text: str) -> tuple[list[str], set[str]]:
    """(place pieces to look up, most specific first; the states named)."""
    cleaned = _MARKET_FILLER.sub(" ", _clean(text))
    pieces = [piece.strip() for piece in cleaned.split(",") if piece.strip()]
    states: set[str] = set()
    places: list[str] = []
    for index, piece in enumerate(pieces):
        piece_states = _as_states(piece) if index > 0 else set()
        if piece_states:
            states |= piece_states
            continue
        # No comma before the state: "Dallas TX 75201".
        trailing = re.match(r"^(.*\S)\s+([a-z]{2})(?:\s+\d{5}(?:-\d{4})?)?$", piece)
        if trailing and trailing.group(2) in _STATE_CODES and trailing.group(1) not in _STATE_NAMES:
            states.add(trailing.group(2))
            piece = trailing.group(1)
        places.append(_ZIP.sub("", piece).strip())
    return [place for place in places if place], states


def _candidates(places: list[str], states: set[str]) -> list[str]:
    """Strings to look up, most specific first: each place with each state
    ("franklin tn"), the place, its dash/slash parts, and - only as a last
    resort - the words inside it ("uptown dallas" -> "dallas")."""
    candidates: list[str] = []

    def add(value: str) -> None:
        value = _words(value)
        if value and value not in candidates and (value not in _STATE_NAMES or value in _MARKET_LOOKUP):
            candidates.append(value)

    for place in places:
        for state in sorted(states):
            add(f"{place} {state}")
        add(place)
        for part in re.split(r"[-/]", place):
            add(part)
    for place in places:
        words = _words(place).split()
        for size in range(min(len(words), 4) - 1, 0, -1):
            for start in range(len(words) - size + 1):
                add(" ".join(words[start : start + size]))
    return candidates


def normalize_market(text: Optional[str]) -> Optional[str]:
    """The canonical market a location string is in, or None.

    Works on a mandate entry ("DFW"), a profile's market ("Dallas-Fort
    Worth-Arlington, TX MSA") or a street address ("12 Elm St, Plano, TX").
    A bare canonical name ("Portland") is read as that market; when a state
    is named, a market in a different state is never matched ("Portland, ME",
    "Buffalo, New York"), and a foreign country never matches."""
    if not text or not str(text).strip() or _FOREIGN.search(_clean(text)):
        return None
    places, states = _parse_location(str(text))
    for candidate in _candidates(places, states):
        market = _MARKET_LOOKUP.get(candidate)
        if market and (not states or states & _MARKET_STATES[market]):
            return market
    return None


# Deal Profile fields read for a deal's market, best first (M3.2).
PROFILE_MARKET_FIELDS = ("market", "submarket", "location", "address")


def profile_market(profile: Any) -> Optional[str]:
    """The canonical market of a Deal Profile, from the first of its location
    fields that names a known market, or None."""
    for field_name in PROFILE_MARKET_FIELDS:
        market = normalize_market(getattr(profile, field_name, None))
        if market:
            return market
    return None


def profile_asset_type(profile: Any) -> Optional[str]:
    """The canonical property type of a Deal Profile, or None."""
    return normalize_asset_type(getattr(profile, "property_type", None))
