"""Effect handler registration for the PokéPrism engine.

Importing this package registers all energy and trainer effect handlers with
the EffectRegistry singleton.  runner.py imports this package at module level
to ensure registration happens before any game is run.
"""

from app.engine.effects import abilities, attacks, energies, trainers
from app.engine.effects.registry import EffectRegistry

energies.register_all(EffectRegistry.instance())
trainers.register_all(EffectRegistry.instance())
abilities.register_all(EffectRegistry.instance())
attacks.register_all(EffectRegistry.instance())
attacks.register_batch15_attacks(EffectRegistry.instance())
