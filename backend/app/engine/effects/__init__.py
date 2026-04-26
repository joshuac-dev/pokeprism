"""Effect handler registration for the PokéPrism engine.

Importing this package registers all energy and trainer effect handlers with
the EffectRegistry singleton.  runner.py imports this package at module level
to ensure registration happens before any game is run.
"""

from app.engine.effects import energies, trainers
from app.engine.effects.registry import EffectRegistry

energies.register_all(EffectRegistry.instance())
trainers.register_all(EffectRegistry.instance())
