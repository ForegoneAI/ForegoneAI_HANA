"""
vocabulary.py

H9N Milestone 3.1 - the fixed lists of property types and markets a mandate
may use, and the rules that turn wording into them.

The extractor (M1.1) never rewrites a document's wording, so a Deal Profile
says "garden-style apartment community" or "Dallas, TX" while a mandate says
"Multifamily" or "Dallas-Fort Worth". Both sides are brought to the same
canonical names here, with two deliberately different levels of strictness:

  * Mandate input (what a person types) is matched STRICTLY:
    canonical_asset_type() / canonical_market() accept only a canonical name
    or an exact alias ("Apartments", "DFW", "Dallas, TX"). Anything else -
    including "Office and Retail" or "Dallas and Houston" - is rejected, so a
    criterion is never silently dropped or merged.

  * Deal data (what a document says) is read LOOSELY: normalize_asset_type()
    and match_market() find the type or market inside longer text ("12 Elm
    St, Plano, TX 75024"). A market found only from a word inside the text
    ("Uptown Dallas") is marked confidence="partial" so screening (M3.2) can
    ask a reviewer to confirm it instead of passing or failing on it.

Unrecognized wording is None ("unknown"), never a guess. To add a market,
add one line to _MARKETS (its states and aliases together); to add a type,
add its phrases to the matching tier. Removing or renaming a canonical name
makes saved mandates that use it unreadable: pair that with a
CRITERIA_SCHEMA_VERSION bump and a migration (see mandate.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Optional

# --- Property types ---------------------------------------------------------
#
# Read in three tiers (deal data only):
#   1. _SPECIFIC_TYPE_PHRASES win whenever they appear, because they qualify a
#      general word ("student apartments", "multifamily development site").
#   2. _GENERAL_TYPE_PHRASES: the one mentioned FIRST wins - the main noun -
#      so "Office building with ground-floor retail" is Office.
#   3. A bare "land" counts only if nothing else matched, so "Land O Lakes
#      Apartments" is Multifamily but "Land" alone is Land.

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
    "Industrial": ("cold storage",),  # not Self-Storage
    "Office": ("flex office",),  # not Industrial
}

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
}

_FALLBACK_TYPE_PHRASES: dict[str, tuple[str, ...]] = {"Land": ("land",)}

_TIERS = (_SPECIFIC_TYPE_PHRASES, _GENERAL_TYPE_PHRASES, _FALLBACK_TYPE_PHRASES)

ASSET_TYPES: list[str] = sorted({name for tier in _TIERS for name in tier})

# --- Markets ----------------------------------------------------------------
#
# Canonical market -> (the states it spans, other names for it). City names
# shared by several metros (Arlington, Aurora, Columbia, ...) are only listed
# with their state ("arlington tx"), never bare. When a location names a
# state, a market in a different state is never matched ("Portland, ME").

_MARKETS: dict[str, tuple[str, tuple[str, ...]]] = {
    "Atlanta": ("ga", ("atlanta", "marietta", "alpharetta", "sandy springs", "decatur")),
    "Austin": ("tx", ("austin", "round rock", "san marcos", "georgetown tx")),
    "Baltimore": ("md", ("baltimore", "columbia md", "towson")),
    "Birmingham": ("al", ("birmingham al", "birmingham alabama")),
    "Boise": ("id", ("boise", "meridian id")),
    "Boston": ("ma nh", ("boston", "cambridge ma", "somerville")),
    "Charleston": ("sc", ("charleston sc", "charleston south carolina", "north charleston")),
    "Charlotte": ("nc sc", ("charlotte",)),
    "Chicago": ("il in", ("chicago", "chicagoland", "evanston", "naperville")),
    "Cincinnati": ("in ky oh", ("cincinnati",)),
    "Cleveland": ("oh", ("cleveland",)),
    "Columbus": ("oh", ("columbus oh", "columbus ohio")),
    "Dallas-Fort Worth": (
        "tx",
        ("dallas", "fort worth", "ft worth", "dfw", "plano", "irving", "frisco", "mckinney", "arlington tx"),
    ),
    "Denver": ("co", ("denver", "aurora co", "lakewood co", "boulder")),
    "Detroit": ("mi", ("detroit",)),
    "Greenville": ("sc", ("greenville sc", "greenville spartanburg", "spartanburg")),
    "Houston": ("tx", ("houston", "the woodlands", "sugar land", "katy", "pearland")),
    "Indianapolis": ("in", ("indianapolis", "carmel in")),
    "Jacksonville": ("fl", ("jacksonville",)),
    "Kansas City": ("ks mo", ("kansas city", "overland park")),
    "Las Vegas": ("nv", ("las vegas", "henderson nv", "north las vegas")),
    "Los Angeles": ("ca", ("los angeles", "long beach", "pasadena", "orange county", "irvine", "anaheim")),
    "Louisville": ("in ky", ("louisville",)),
    "Memphis": ("ar ms tn", ("memphis",)),
    "Miami": (
        "fl",
        ("miami", "south florida", "fort lauderdale", "ft lauderdale", "west palm beach", "boca raton"),
    ),
    "Minneapolis-St. Paul": ("mn wi", ("minneapolis", "st paul", "saint paul", "twin cities")),
    "Nashville": ("tn", ("nashville", "franklin tn", "murfreesboro")),
    "New Orleans": ("la", ("new orleans",)),
    "New York": (
        "ct nj ny pa",
        ("new york", "new york city", "nyc", "manhattan", "brooklyn", "queens", "bronx", "jersey city"),
    ),
    "Oklahoma City": ("ok", ("oklahoma city", "okc")),
    "Orlando": ("fl", ("orlando", "kissimmee")),
    "Philadelphia": ("de md nj pa", ("philadelphia", "philly")),
    "Phoenix": ("az", ("phoenix", "scottsdale", "tempe", "mesa", "chandler", "gilbert")),
    "Pittsburgh": ("pa", ("pittsburgh",)),
    "Portland": ("or wa", ("portland or", "portland oregon", "beaverton")),
    "Raleigh-Durham": ("nc", ("raleigh", "durham", "chapel hill", "research triangle", "cary nc")),
    "Richmond": ("va", ("richmond va", "richmond virginia")),
    "Sacramento": ("ca", ("sacramento",)),
    "Salt Lake City": ("ut", ("salt lake city", "slc", "provo", "ogden")),
    "San Antonio": ("tx", ("san antonio", "new braunfels")),
    "San Diego": ("ca", ("san diego",)),
    "San Francisco Bay Area": (
        "ca",
        (
            "san francisco",
            "sf bay area",
            "bay area",
            "san francisco bay area",
            "oakland",
            "san jose",
            "silicon valley",
        ),
    ),
    "Savannah": ("ga", ("savannah",)),
    "Seattle": ("wa", ("seattle", "bellevue wa", "tacoma", "puget sound")),
    "St. Louis": ("il mo", ("st louis", "saint louis")),
    "Tampa": ("fl", ("tampa", "tampa bay", "st petersburg", "saint petersburg", "clearwater")),
    "Tucson": ("az", ("tucson",)),
    "Washington, D.C.": (
        "dc md va wv",
        (
            "washington dc",
            "washington d c",
            "washington arlington alexandria",
            "dc",
            "district of columbia",
            "northern virginia",
            "nova",
            "dmv",
            "arlington va",
            "alexandria va",
        ),
    ),
}

MARKETS: list[str] = sorted(_MARKETS)

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

# A location in another country is never matched to a US market.
_FOREIGN = re.compile(
    r"\b(uk|u k|united kingdom|great britain|england|scotland|wales|ireland|canada|mexico|costa rica|"
    r"australia|new zealand|germany|france|spain|portugal|italy|netherlands|belgium|switzerland|austria|"
    r"poland|russia|russian federation|ukraine|turkey|greece|sweden|norway|denmark|finland|india|china|"
    r"japan|south korea|korea|singapore|hong kong|taiwan|philippines|vietnam|thailand|indonesia|israel|"
    r"uae|united arab emirates|dubai|saudi arabia|qatar|egypt|south africa|nigeria|kenya|brazil|argentina|"
    r"chile|colombia|peru|puerto rico|ontario|british columbia|quebec|alberta)\b"
)

# Words that only describe a market, never name it: "Greater Houston Metro
# Area" means Houston. ("county" is kept: "Orange County" is an alias.)
_MARKET_FILLER = re.compile(
    r"\b(greater|metropolitan statistical area|metropolitan area|metropolitan|metro area|metroplex|metro|msa|"
    r"region|submarket|market|city of)\b"
)
_ZIP = re.compile(r"\s*\b\d{5}(-\d{4})?$")
_TRAILING_STATE = re.compile(r"^(.*\S)\s+([a-z]{2})(?:\s+\d{5}(?:-\d{4})?)?$")

# Aliases this short are abbreviations ("dc", "dfw", "nova"): fine as a whole
# entry, but never searched for as a word inside longer text ("DC Ranch").
_MIN_PARTIAL_ALIAS_CHARS = 5


# --- Text helpers -------------------------------------------------------------


def _clean(text: Any) -> str:
    """Lowercase, ASCII dashes, punctuation to spaces, single-spaced."""
    text = str(text).casefold().replace("&", " and ")
    text = re.sub(r"[‐-―]", "-", text)
    text = re.sub(r"[^\w\s,/-]", " ", text)  # drops periods: "St. Louis" -> "st louis"
    return " ".join(text.split())


def _key(text: str) -> str:
    """A lookup key: cleaned, with dashes, slashes and commas as spaces."""
    return " ".join(_clean(text).replace("-", " ").replace("/", " ").replace(",", " ").split())


# --- Lookup tables, built and checked once at import --------------------------

_ASSET_TYPE_LOOKUP: dict[str, str] = {}
for _tier in _TIERS:
    for _name, _phrases in _tier.items():
        for _phrase in (_name, *_phrases):
            _ASSET_TYPE_LOOKUP.setdefault(_key(_phrase), _name)

# Each tier's phrases compiled once: (type, phrase length, pattern).
_COMPILED_TIERS = tuple(
    tuple(
        (name, len(phrase), re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)"))
        for name, phrases in tier.items()
        for phrase in phrases
    )
    for tier in _TIERS
)

_MARKET_STATES: dict[str, frozenset[str]] = {name: frozenset(states.split()) for name, (states, _) in _MARKETS.items()}
_MARKET_LOOKUP: dict[str, str] = {}
for _name, (_states, _aliases) in _MARKETS.items():
    if not _MARKET_STATES[_name] <= _STATE_CODES:
        raise RuntimeError(f"{_name} lists an unknown state code.")
    for _alias in (_name, *_aliases):
        if _MARKET_LOOKUP.get(_key(_alias), _name) != _name:
            raise RuntimeError(f"Market alias {_alias!r} is listed for two markets.")
        _MARKET_LOOKUP[_key(_alias)] = _name


# --- Mandate input: strict -----------------------------------------------------


def canonical_asset_type(text: Optional[str]) -> Optional[str]:
    """For mandate input: the canonical type if `text` IS a canonical name or
    an exact alias ("apartments"), else None. Never searches inside text, so
    "Office and Retail" is rejected rather than saved as Office."""
    if not text or not str(text).strip():
        return None
    return _ASSET_TYPE_LOOKUP.get(_key(text))


def canonical_market(text: Optional[str]) -> Optional[str]:
    """For mandate input: the canonical market if `text` IS a canonical name
    or an exact alias, optionally followed by its state ("DFW", "Dallas, TX",
    "Franklin, Tennessee"), else None. "Dallas and Houston" is rejected."""
    if not text or not str(text).strip():
        return None
    pieces = [piece.strip() for piece in _clean(text).split(",") if piece.strip()]
    whole = _MARKET_LOOKUP.get(_key(text))
    if whole:
        return whole
    if len(pieces) != 2:
        return None
    states = _as_states(pieces[1])
    if not states:
        return None
    for candidate in [f"{pieces[0]} {state}" for state in sorted(states)] + [pieces[0]]:
        market = _MARKET_LOOKUP.get(_key(candidate))
        if market and states & _MARKET_STATES[market]:
            return market
    return None


# --- Deal data: loose ----------------------------------------------------------


def normalize_asset_type(text: Optional[str]) -> Optional[str]:
    """For deal data: the canonical property type a description is about, or
    None (see the tiers above)."""
    if not text or not str(text).strip():
        return None
    key = _key(text)
    if key in _ASSET_TYPE_LOOKUP:
        return _ASSET_TYPE_LOOKUP[key]
    for tier in _COMPILED_TIERS:
        best: Optional[tuple[int, int, str]] = None
        for name, length, pattern in tier:
            found = pattern.search(key)
            if found and (best is None or (found.start(), -length) < best[:2]):
                best = (found.start(), -length, name)
        if best:
            return best[2]
    return None


@dataclass(frozen=True)
class MarketMatch:
    """A market read from deal data, and how sure the match is.

    confidence is "exact" when a whole place in the text is a known name
    ("Plano" in "12 Elm St, Plano, TX"), and "partial" when the market was
    only found as a word inside a longer place name ("Uptown Dallas",
    "Brooklyn Park") - screening should ask a reviewer to confirm those.
    """

    market: str
    confidence: Literal["exact", "partial"]
    matched_text: str
    field: Optional[str] = None


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
        trailing = _TRAILING_STATE.match(piece)  # no comma: "Dallas TX 75201"
        if trailing and trailing.group(2) in _STATE_CODES and trailing.group(1) not in _STATE_NAMES:
            states.add(trailing.group(2))
            piece = trailing.group(1)
        places.append(_ZIP.sub("", piece).strip())
    return [place for place in places if place], states


def _candidates(places: list[str], states: set[str]) -> list[tuple[str, bool]]:
    """(lookup string, is_partial), most specific first: each place with each
    state ("franklin tn"), the place, its dash/slash parts, and - only as a
    last resort, marked partial - the words inside it ("uptown dallas" ->
    "dallas"), skipping short abbreviations ("DC Ranch")."""
    candidates: list[tuple[str, bool]] = []
    seen: set[str] = set()

    def add(value: str, partial: bool) -> None:
        value = _key(value)
        if not value or value in seen:
            return
        if value in _STATE_NAMES and value not in _MARKET_LOOKUP:
            return
        if partial and len(value) < _MIN_PARTIAL_ALIAS_CHARS:
            return
        seen.add(value)
        candidates.append((value, partial))

    for place in places:
        for state in sorted(states):
            add(f"{place} {state}", False)
        add(place, False)
        for part in re.split(r"[-/]", place):
            add(part, False)
    for place in places:
        words = _key(place).split()
        for size in range(min(len(words), 4) - 1, 0, -1):
            for start in range(len(words) - size + 1):
                add(" ".join(words[start : start + size]), True)
    return candidates


def match_market(text: Optional[str], *, field: Optional[str] = None) -> Optional[MarketMatch]:
    """For deal data: the market a location string is in, with its confidence,
    or None. When a state is named, a market in a different state is never
    matched; a foreign country never matches."""
    if not text or not str(text).strip() or _FOREIGN.search(_clean(text)):
        return None
    places, states = _parse_location(str(text))
    for candidate, partial in _candidates(places, states):
        market = _MARKET_LOOKUP.get(candidate)
        if market and (not states or states & _MARKET_STATES[market]):
            return MarketMatch(market, "partial" if partial else "exact", candidate, field)
    return None


def normalize_market(text: Optional[str]) -> Optional[str]:
    """For deal data: just the market name from match_market(), or None."""
    match = match_market(text)
    return match.market if match else None


# Deal Profile fields read for a deal's market, best first (M3.2).
PROFILE_MARKET_FIELDS = ("market", "submarket", "location", "address")


def profile_market_match(profile: Any) -> Optional[MarketMatch]:
    """A Deal Profile's market and which field it came from: the first field
    with an exact match, else the first partial one, else None. M3.2 should
    show `field` and `confidence` to the reviewer and treat "partial" or
    None as "needs review", not as a pass or fail."""
    partial: Optional[MarketMatch] = None
    for field_name in PROFILE_MARKET_FIELDS:
        match = match_market(getattr(profile, field_name, None), field=field_name)
        if match and match.confidence == "exact":
            return match
        partial = partial or match
    return partial


def profile_market(profile: Any) -> Optional[str]:
    """Just the market name from profile_market_match(), or None."""
    match = profile_market_match(profile)
    return match.market if match else None


def profile_asset_type(profile: Any) -> Optional[str]:
    """The canonical property type of a Deal Profile, or None."""
    return normalize_asset_type(getattr(profile, "property_type", None))
