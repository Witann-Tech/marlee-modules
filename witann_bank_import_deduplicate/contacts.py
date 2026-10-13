"""Optional, conservative contact extraction/matching; no Odoo or writes."""
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher


MAX_PARTNERS = 20000
MAX_NAME_CANDIDATES = 1000
MIN_NAME_SCORE = .96
MIN_NAME_MARGIN = .05
GENERIC_RFCS = {'XAXX010101000', 'XEXX010101000'}
RFC = re.compile(r'\bR\.?\s*F\.?\s*C\.?\s*:?\s*([A-ZÑ&0-9]+)', re.I)
NAME_PATTERNS = (
    ('client', re.compile(
        r'\bDEL\s+CLIENTE\s+(.+?)(?=,?\s+DE\s+LA\s+CLABE\b|,\s*CON\s+RFC\b|,\s*CONCEPTO\s*:)', re.I)),
    ('beneficiary', re.compile(
        r'\bBENEF(?:ICIARIO)?\s*:\s*(.+?)(?=\s*\(DATO\s+NO\s+VERIFICADO|,\s*(?:CVE|RFC|IVA)\b)', re.I)),
    ('tef', re.compile(r'\bBEM\s+TEF\.BCO:\d+\s+(.+?)(?=,\s*CVE\.RASTREO:)', re.I)),
    ('direct_debit', re.compile(r'\bREF:[^,]+,\s*(.+?)(?=,\s*RFC:)', re.I)),
)
# Ignore connectors and conventional corporate suffix tokens, not surnames.
NAME_PARTICLES = {'DE', 'DEL', 'LA', 'LAS', 'LOS', 'Y', 'S', 'A', 'C', 'V', 'R', 'L',
                  'SA', 'CV', 'RL', 'SAPI', 'SC', 'AC', 'LLC', 'INC', 'LTD'}
GENERIC_NAMES = {'CLIENTE GENERAL', 'PUBLICO GENERAL', 'PUBLICO EN GENERAL',
                 'CONSUMIDOR FINAL', 'CLIENTES VARIOS', 'PROVEEDORES VARIOS',
                 'NO IDENTIFICADO', 'NO DISPONIBLE', 'SIN NOMBRE', 'SIN IDENTIFICAR',
                 'CLIENTE MOSTRADOR', 'VENTAS MOSTRADOR', 'NOMBRE NO DISPONIBLE'}


@dataclass(frozen=True)
class Contact:
    name: str = ''
    rfc: str = ''


@dataclass(frozen=True)
class Partner:
    id: int
    name: str
    vat: str = ''


def normalize_rfc(value):
    """Syntax/date check only, excluding CURP/generic IDs; not SAT validation."""
    raw = re.sub(r'[\s.-]', '', str(value or '').upper())
    if raw.startswith('MX') and len(raw) in (14, 15):
        raw = raw[2:]
    if raw in GENERIC_RFCS or not re.fullmatch(r'[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}', raw):
        return ''
    try:
        datetime.strptime(raw[-9:-3], '%y%m%d')
    except ValueError:
        return ''
    return raw


def normalize_name(value):
    # Preserve Ñ: Peña and Pena must not silently become the same surname.
    raw = unicodedata.normalize('NFC', str(value or '').upper())
    folded = ''.join(char if char == 'Ñ' else ''.join(
        item for item in unicodedata.normalize('NFKD', char)
        if not unicodedata.combining(item)
    ) for char in raw)
    return ' '.join(re.sub(r'[^A-ZÑ0-9]+', ' ', folded).split())


def name_tokens(name):
    normalized = normalize_name(name)
    for spaced, compact in (('S A P I', 'SAPI'), ('S A', 'SA'), ('C V', 'CV'), ('R L', 'RL')):
        normalized = re.sub(r'\b' + spaced + r'\b', compact, normalized)
    if normalized in GENERIC_NAMES or any(char.isdigit() for char in normalized):
        return ()
    return tuple(sorted(token for token in normalized.split() if token not in NAME_PARTICLES))


def extract_contact(detail, amount):
    """Read explicit counterpart fields only; never guess from payment concepts."""
    if not detail or len(detail) > 8192 or not amount:
        return Contact()
    names = []
    for kind, pattern in NAME_PATTERNS:
        for match in pattern.finditer(detail):
            if (kind == 'client' and amount < 0) or (kind in ('beneficiary', 'tef', 'direct_debit') and amount > 0):
                return Contact()  # direction contradicts the explicit role
            name = ' '.join(match.group(1).strip(' ,').split())
            if len(name) <= 120 and not re.search(r'\b(?:CLABE|RFC|REFERENCIA|CONCEPTO)\b', name, re.I):
                names.append(name)
    # Conflicting names or RFCs in one detail are not safe to resolve silently.
    names = set(names)
    rfcs = {value for match in RFC.finditer(detail) if (value := normalize_rfc(match.group(1)))}
    if len(names) > 1 or len(rfcs) > 1:
        return Contact()
    return Contact(next(iter(names), ''), next(iter(rfcs), ''))


def _similarity(left, right):
    return SequenceMatcher(None, ' '.join(left), ' '.join(right), autojunk=False).ratio()


def _strong_name(left, right, score):
    if min(len(left), len(right)) < 2 or min(sum(map(len, left)), sum(map(len, right))) < 8:
        return False
    if left == right:
        return all(len(token) > 1 for token in left)
    if score < MIN_NAME_SCORE or len(left) != len(right) or len(left) < 3:
        return False
    # One small spelling/truncation difference, with at least two full tokens.
    shared = Counter(left) & Counter(right)
    remaining_left = list((Counter(left) - shared).elements())
    remaining_right = list((Counter(right) - shared).elements())
    return (
        sum(count for token, count in shared.items() if len(token) >= 4) >= 2
        and len(remaining_left) == len(remaining_right) == 1
        and min(len(remaining_left[0]), len(remaining_right[0])) >= 5
        and remaining_left[0].count('Ñ') == remaining_right[0].count('Ñ')
        and _similarity(remaining_left, remaining_right) >= .88
    )


class Matcher:
    """One complete visible catalogue; repeated counterpart lookups are cached."""

    def __init__(self, partners):
        self.partners = {partner.id: partner for partner in partners}
        self.rfcs = {partner.id: normalize_rfc(partner.vat) for partner in partners}
        self.tokens = {partner.id: name_tokens(partner.name) for partner in partners}
        self.by_rfc = defaultdict(set)
        self.by_token = defaultdict(set)
        self.cache = {}
        for partner_id in self.partners:
            if self.rfcs[partner_id]:
                self.by_rfc[self.rfcs[partner_id]].add(partner_id)
            for token in self.tokens[partner_id]:
                if len(token) >= 3:
                    self.by_token[token].add(partner_id)

    def match(self, contact):
        if contact not in self.cache:
            self.cache[contact] = self._match(contact)
        return self.cache[contact]

    def _match(self, contact):
        rfc, tokens = normalize_rfc(contact.rfc), name_tokens(contact.name)
        fiscal = self.by_rfc.get(rfc, set()) if rfc else set()
        if fiscal:
            if len(fiscal) != 1:
                return None
            partner_id = next(iter(fiscal))
            other = self.tokens[partner_id]
            common = len(set(tokens) & set(other))
            if tokens and other and common < min(2, len(set(tokens)), len(set(other))) and _similarity(tokens, other) < .65:
                return None  # strong name/RFC contradiction
            return partner_id
        if len(tokens) < 2:
            return None
        candidates = set()
        for token in tokens:
            candidates.update(self.by_token.get(token, ()))
        if not candidates or len(candidates) > MAX_NAME_CANDIDATES:
            return None
        ranked = sorted(((_similarity(tokens, self.tokens[pid]), pid) for pid in candidates), reverse=True)
        score, partner_id = ranked[0]
        if not _strong_name(tokens, self.tokens[partner_id], score):
            return None
        if len(ranked) > 1 and score - ranked[1][0] < MIN_NAME_MARGIN:
            return None
        if rfc and self.rfcs[partner_id] and rfc != self.rfcs[partner_id]:
            return None
        return partner_id
