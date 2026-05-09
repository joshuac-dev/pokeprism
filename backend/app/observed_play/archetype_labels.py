"""Deterministic archetype/package/strategy label preview helpers.

Phase 7.1b is intentionally read-only: these helpers infer advisory labels but
do not persist them and do not affect Coach retrieval ranking.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import re
import unicodedata
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Card, Deck, DeckCard, ObservedCardMention, ObservedPlayEvent, ObservedPlayLog, ObservedPlayMemoryItem
from app.observed_play.schemas import ArchetypeLabel, DeckArchetypeLabelPreview, ObservedLogArchetypeLabelPreview


_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_DECK_LINE_RE = re.compile(r"^\s*(\d+)\s+(.+?)\s*$")


def canonicalize_label_key(label: str) -> str:
    """Return a stable key for user-facing labels."""
    normalized = unicodedata.normalize("NFKD", label.strip().lower())
    normalized = normalized.replace("'", "").replace("’", "").replace("`", "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    key = _NON_ALNUM_RE.sub("-", ascii_text).strip("-")
    return re.sub(r"-+", "-", key)


def _normalize_name(name: str | None) -> str:
    return canonicalize_label_key(name or "").replace("-", " ")


@dataclass(frozen=True)
class CardSignal:
    card_id: str | None
    name: str
    count: int = 1
    category: str | None = None
    types: tuple[str, ...] = ()
    attacks: tuple[str, ...] = ()
    abilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class ObservedCardSignal:
    player_alias: str
    card_id: str | None
    name: str | None
    resolution_status: str | None = None
    event_id: str | None = None
    memory_item_id: str | None = None
    action_name: str | None = None
    memory_type: str | None = None
    source_event_type: str | None = None


@dataclass(frozen=True)
class SeedRule:
    label: str
    core_names: tuple[str, ...]
    label_type: str = "archetype"
    strategy_labels: tuple[str, ...] = ()
    package_labels: tuple[str, ...] = ()

    @property
    def canonical_key(self) -> str:
        return canonicalize_label_key(self.label)


_SEED_RULES: tuple[SeedRule, ...] = (
    SeedRule(
        label="Dragapult ex",
        core_names=("Dragapult ex", "Drakloak", "Dreepy"),
        strategy_labels=("Spread damage",),
        package_labels=("Stage 2 setup",),
    ),
    SeedRule(
        label="Salazzle ex",
        core_names=("Salazzle ex", "Salazzle", "Salandit"),
        strategy_labels=("Poison/Burn strategy",),
    ),
    SeedRule(label="Crustle", core_names=("Crustle", "Dwebble")),
    SeedRule(
        label="Charizard ex",
        core_names=("Charizard ex", "Charmeleon", "Charmander"),
        package_labels=("Stage 2 setup",),
    ),
    SeedRule(
        label="Gardevoir ex",
        core_names=("Gardevoir ex", "Gardevoir", "Kirlia", "Ralts"),
        package_labels=("Psychic engine",),
    ),
)

_FIRE_NAMES = ("charizard", "charmander", "charmeleon", "armarouge", "ceruledge", "entei", "moltres", "salazzle", "salandit")
_POISON_BURN_TERMS = ("poison", "poisoned", "burn", "burned", "special condition", "pecharunt", "salazzle")
_SPREAD_TERMS = ("phantom dive", "damage counter", "damage counters", "spread", "dragapult")


@dataclass
class _RuleScore:
    rule: SeedRule
    count_by_name: Counter[str] = field(default_factory=Counter)
    ids_by_name: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    event_ids: set[str] = field(default_factory=set)
    memory_item_ids: set[str] = field(default_factory=set)

    @property
    def total_count(self) -> int:
        return sum(self.count_by_name.values())

    @property
    def unique_core_count(self) -> int:
        return len(self.count_by_name)

    @property
    def main_count(self) -> int:
        return self.count_by_name.get(_normalize_name(self.rule.core_names[0]), 0)


def _match_rule_name(rule: SeedRule, card_name: str | None) -> str | None:
    normalized = _normalize_name(card_name)
    if not normalized:
        return None
    for core in rule.core_names:
        core_norm = _normalize_name(core)
        if normalized == core_norm or core_norm in normalized:
            return core_norm
    return None


def _label_from_score(
    score: _RuleScore,
    *,
    source: str,
    confidence: float,
    player_alias: str | None = None,
    label_type: str | None = None,
    label: str | None = None,
    notes: str | None = None,
) -> ArchetypeLabel:
    evidence_ids: list[str] = []
    evidence_names: list[str] = []
    for core_name in score.count_by_name:
        evidence_names.append(core_name.title().replace(" Ex", " ex"))
        evidence_ids.extend(sorted(score.ids_by_name.get(core_name, set())))
    return ArchetypeLabel(
        label=label or score.rule.label,
        canonical_key=canonicalize_label_key(label or score.rule.label),
        label_type=label_type or score.rule.label_type,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
        confidence=round(min(1.0, max(0.0, confidence)), 2),
        review_status="suggested",
        player_alias=player_alias,
        evidence_card_ids=list(dict.fromkeys(evidence_ids)),
        evidence_card_names=list(dict.fromkeys(evidence_names)),
        evidence_counts={name: count for name, count in sorted(score.count_by_name.items())},
        evidence_event_ids=sorted(score.event_ids),
        evidence_memory_item_ids=sorted(score.memory_item_ids),
        notes=notes,
    )


def infer_deck_labels_from_cards(deck_id: str, deck_name: str | None, cards: list[CardSignal]) -> DeckArchetypeLabelPreview:
    scores = _score_card_signals(cards)
    labels: list[ArchetypeLabel] = []

    for score in scores:
        confidence = _deck_confidence(score)
        if confidence >= 0.5:
            labels.append(_label_from_score(score, source="deck_cards", confidence=confidence))
            labels.extend(_deck_secondary_labels(score, confidence))

    labels.extend(_deck_fire_toolbox_labels(cards, labels))
    labels = _dedupe_labels(labels)
    labels.sort(key=lambda l: (l.label_type != "archetype", -l.confidence, l.label))

    archetypes = [l for l in labels if l.label_type == "archetype"]
    primary = archetypes[0] if archetypes else (labels[0] if labels else None)
    ambiguous = _is_ambiguous(archetypes)
    no_label_reason = None if labels else "No deterministic archetype/package label met the preview confidence threshold."
    return DeckArchetypeLabelPreview(
        deck_id=deck_id,
        deck_name=deck_name,
        labels=labels,
        primary_label=primary,
        ambiguous=ambiguous,
        no_label_reason=no_label_reason,
    )


def infer_observed_log_labels_from_signals(log_id: str, signals: list[ObservedCardSignal]) -> ObservedLogArchetypeLabelPreview:
    by_player: dict[str, list[ObservedCardSignal]] = defaultdict(list)
    for signal in signals:
        by_player[signal.player_alias or "unknown"].append(signal)

    labels_by_player: dict[str, list[ArchetypeLabel]] = {}
    ambiguous = False
    for player_alias, player_signals in sorted(by_player.items()):
        scores = _score_observed_signals(player_signals)
        labels: list[ArchetypeLabel] = []
        for score in scores:
            confidence = _observed_confidence(score, player_signals)
            if confidence >= 0.5:
                labels.append(_label_from_score(
                    score,
                    source="observed_log",
                    confidence=confidence,
                    player_alias=player_alias,
                ))
                labels.extend(_observed_secondary_labels(score, player_signals, confidence, player_alias))
        labels = _dedupe_labels(labels)
        labels.sort(key=lambda l: (l.label_type != "archetype", -l.confidence, l.label))
        if labels:
            labels_by_player[player_alias] = labels
        ambiguous = ambiguous or _is_ambiguous([l for l in labels if l.label_type == "archetype"])

    no_label_reason = None if labels_by_player else "No repeated resolved observed-play evidence met the preview confidence threshold."
    return ObservedLogArchetypeLabelPreview(
        observed_play_log_id=log_id,
        labels_by_player=labels_by_player,
        global_labels=[],
        ambiguous=ambiguous,
        no_label_reason=no_label_reason,
    )


def _score_card_signals(cards: list[CardSignal]) -> list[_RuleScore]:
    scores = [_RuleScore(rule) for rule in _SEED_RULES]
    for card in cards:
        for score in scores:
            matched = _match_rule_name(score.rule, card.name)
            if matched:
                score.count_by_name[matched] += max(1, card.count)
                if card.card_id:
                    score.ids_by_name[matched].add(card.card_id)
    return scores


def _score_observed_signals(signals: list[ObservedCardSignal]) -> list[_RuleScore]:
    scores = [_RuleScore(rule) for rule in _SEED_RULES]
    for signal in signals:
        if signal.resolution_status == "unresolved":
            continue
        for score in scores:
            matched = _match_rule_name(score.rule, signal.name)
            if matched:
                score.count_by_name[matched] += 1
                if signal.card_id:
                    score.ids_by_name[matched].add(signal.card_id)
                if signal.event_id:
                    score.event_ids.add(str(signal.event_id))
                if signal.memory_item_id:
                    score.memory_item_ids.add(str(signal.memory_item_id))
    return scores


def _deck_confidence(score: _RuleScore) -> float:
    if score.main_count >= 2 and score.unique_core_count >= 2:
        return 0.92
    if score.main_count >= 1 and score.unique_core_count >= 2:
        return 0.86
    if score.main_count >= 2:
        return 0.82
    if score.unique_core_count >= 2:
        return 0.68
    if score.main_count == 1:
        return 0.55
    return 0.0


def _observed_confidence(score: _RuleScore, signals: list[ObservedCardSignal]) -> float:
    resolved_count = sum(1 for s in signals if s.resolution_status in (None, "resolved") and _match_rule_name(score.rule, s.name))
    if score.main_count >= 2 and score.unique_core_count >= 2:
        return 0.78
    if score.total_count >= 4 and score.unique_core_count >= 2:
        return 0.73
    if score.main_count >= 2:
        return 0.67
    if resolved_count >= 3 and score.unique_core_count >= 2:
        return 0.64
    if score.total_count == 1:
        return 0.0
    if score.total_count == 2:
        return 0.52
    return 0.0


def _deck_secondary_labels(score: _RuleScore, archetype_confidence: float) -> list[ArchetypeLabel]:
    labels: list[ArchetypeLabel] = []
    if score.unique_core_count >= 3:
        for package in score.rule.package_labels:
            labels.append(_label_from_score(
                score,
                source="deck_cards",
                confidence=min(0.78, archetype_confidence - 0.12),
                label_type="package",
                label=package,
                notes="Suggested from core evolution-line deck evidence.",
            ))
    for strategy in score.rule.strategy_labels:
        if score.main_count >= 1 and score.total_count >= 2:
            labels.append(_label_from_score(
                score,
                source="deck_cards",
                confidence=min(0.76, archetype_confidence - 0.14),
                label_type="strategy",
                label=strategy,
                notes="Suggested from known archetype strategy seed evidence.",
            ))
    return labels


def _observed_secondary_labels(
    score: _RuleScore,
    signals: list[ObservedCardSignal],
    archetype_confidence: float,
    player_alias: str,
) -> list[ArchetypeLabel]:
    labels: list[ArchetypeLabel] = []
    text = " ".join(
        " ".join(filter(None, [s.name or "", s.action_name or "", s.memory_type or "", s.source_event_type or ""]))
        for s in signals
    ).lower()
    for strategy in score.rule.strategy_labels:
        terms = _POISON_BURN_TERMS if "poison" in strategy.lower() else _SPREAD_TERMS
        if any(term in text for term in terms) and score.total_count >= 2:
            labels.append(_label_from_score(
                score,
                source="observed_log",
                confidence=min(0.66, archetype_confidence - 0.08),
                player_alias=player_alias,
                label_type="strategy",
                label=strategy,
                notes="Suggested from repeated observed-log strategy evidence.",
            ))
    return labels


def _deck_fire_toolbox_labels(cards: list[CardSignal], existing: list[ArchetypeLabel]) -> list[ArchetypeLabel]:
    strong_archetype = any(l.label_type == "archetype" and l.confidence >= 0.8 for l in existing)
    if strong_archetype:
        return []
    fire_cards: list[CardSignal] = []
    for card in cards:
        norm = _normalize_name(card.name)
        is_fire_type = any(t.lower() == "fire" for t in card.types)
        is_fire_name = any(term in norm for term in _FIRE_NAMES)
        if is_fire_type or is_fire_name:
            fire_cards.append(card)
    unique_fire = {c.name for c in fire_cards if (c.category or "").lower() == "pokemon" or not c.category}
    total_fire = sum(max(1, c.count) for c in fire_cards)
    if len(unique_fire) < 2 or total_fire < 4:
        return []
    score = _RuleScore(SeedRule(label="Fire toolbox", core_names=tuple(sorted(unique_fire)), label_type="archetype"))
    for card in fire_cards:
        name = _normalize_name(card.name)
        score.count_by_name[name] += max(1, card.count)
        if card.card_id:
            score.ids_by_name[name].add(card.card_id)
    return [_label_from_score(
        score,
        source="deck_cards",
        confidence=0.66,
        label="Fire toolbox",
        label_type="archetype",
        notes="Suggested from multiple Fire Pokemon without one dominant seeded archetype.",
    )]


def _dedupe_labels(labels: list[ArchetypeLabel]) -> list[ArchetypeLabel]:
    best: dict[tuple[str, str, str | None], ArchetypeLabel] = {}
    for label in labels:
        key = (label.canonical_key, label.label_type, label.player_alias)
        if key not in best or label.confidence > best[key].confidence:
            best[key] = label
    return list(best.values())


def _is_ambiguous(archetypes: list[ArchetypeLabel]) -> bool:
    if len(archetypes) < 2:
        return False
    ordered = sorted(archetypes, key=lambda l: l.confidence, reverse=True)
    return ordered[0].confidence - ordered[1].confidence <= 0.05


def _card_to_signal(card: Card, quantity: int = 1) -> CardSignal:
    attack_names = tuple(a.get("name", "") for a in (card.attacks or []) if isinstance(a, dict))
    ability_names = tuple(a.get("name", "") for a in (card.abilities or []) if isinstance(a, dict))
    return CardSignal(
        card_id=card.tcgdex_id,
        name=card.name,
        count=quantity,
        category=card.category,
        types=tuple(card.types or []),
        attacks=attack_names,
        abilities=ability_names,
    )


async def preview_deck_archetype_labels(db: AsyncSession, deck_id: UUID) -> DeckArchetypeLabelPreview | None:
    deck_result = await db.execute(select(Deck).where(Deck.id == deck_id))
    deck = deck_result.scalars().first()
    if deck is None:
        return None

    card_result = await db.execute(
        select(DeckCard, Card)
        .join(Card, DeckCard.card_tcgdex_id == Card.tcgdex_id)
        .where(DeckCard.deck_id == deck_id)
    )
    cards = [_card_to_signal(card, int(deck_card.quantity or 1)) for deck_card, card in card_result.all()]
    if not cards and deck.deck_text:
        cards = await _signals_from_deck_text(db, deck.deck_text)
    return infer_deck_labels_from_cards(str(deck.id), deck.name, cards)


async def _signals_from_deck_text(db: AsyncSession, deck_text: str) -> list[CardSignal]:
    parsed: list[tuple[int, str]] = []
    ids: list[str] = []
    for raw in deck_text.splitlines():
        match = _DECK_LINE_RE.match(raw)
        if not match:
            continue
        qty = int(match.group(1))
        token = match.group(2).strip()
        parsed.append((qty, token))
        if re.match(r"^[a-z0-9.]+-\d+", token, flags=re.IGNORECASE):
            ids.append(token)
    if not parsed:
        return []

    cards_by_id: dict[str, Card] = {}
    if ids:
        card_result = await db.execute(select(Card).where(Card.tcgdex_id.in_(ids)))
        cards_by_id = {card.tcgdex_id: card for card in card_result.scalars().all()}

    signals: list[CardSignal] = []
    for qty, token in parsed:
        card = cards_by_id.get(token)
        if card is not None:
            signals.append(_card_to_signal(card, qty))
        else:
            signals.append(CardSignal(card_id=token if token in ids else None, name=token, count=qty))
    return signals


async def preview_observed_log_archetype_labels(
    db: AsyncSession,
    log_id: UUID,
) -> ObservedLogArchetypeLabelPreview | None:
    log_result = await db.execute(select(ObservedPlayLog).where(ObservedPlayLog.id == log_id))
    log = log_result.scalars().first()
    if log is None:
        return None

    signals: list[ObservedCardSignal] = []

    item_result = await db.execute(
        select(ObservedPlayMemoryItem).where(ObservedPlayMemoryItem.observed_play_log_id == log_id)
    )
    for item in item_result.scalars().all():
        player_alias = item.player_alias or "unknown"
        for raw_name, card_id, status in (
            (item.actor_card_raw, item.actor_card_def_id, item.actor_resolution_status),
            (item.target_card_raw, item.target_card_def_id, item.target_resolution_status),
            (item.related_card_raw, item.related_card_def_id, item.related_resolution_status),
        ):
            if raw_name or card_id:
                signals.append(ObservedCardSignal(
                    player_alias=player_alias,
                    card_id=card_id,
                    name=raw_name,
                    resolution_status=status,
                    event_id=str(item.observed_play_event_id) if item.observed_play_event_id is not None else None,
                    memory_item_id=str(item.id),
                    action_name=item.action_name,
                    memory_type=item.memory_type,
                    source_event_type=item.source_event_type,
                ))

    mention_result = await db.execute(
        select(ObservedCardMention, ObservedPlayEvent.player_alias)
        .join(ObservedPlayEvent, ObservedCardMention.observed_play_event_id == ObservedPlayEvent.id)
        .where(ObservedCardMention.observed_play_log_id == log_id)
    )
    for mention, player_alias in mention_result.all():
        signals.append(ObservedCardSignal(
            player_alias=player_alias or "unknown",
            card_id=mention.resolved_card_def_id,
            name=mention.resolved_card_name or mention.raw_name,
            resolution_status=mention.resolution_status,
            event_id=str(mention.observed_play_event_id),
            source_event_type=mention.source_event_type,
        ))

    return infer_observed_log_labels_from_signals(str(log.id), signals)
