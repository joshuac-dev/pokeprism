---

## FLAGGED_CARDS

Cards too complex for automatic handler generation. Requires manual implementation.

| Card | TCGDex ID | Attack/Ability | Reason |
|------|-----------|---------------|--------|
| Latios MEG 101 | me01-101 | Lustrous Assist (ability) | Trigger when Mega Latias ex moves bench→active, move energy — complex event hook not supported |
| Misty's Psyduck DRI 45 | sv10-045 | Flustered Leap (ability) | Discard bottom of deck then return this Pokémon to top of deck from bench — returning Pokémon from bench to deck not supported; bottom-of-deck access not supported |
| Cetitan ex DRI 65 | sv10-065 | Snow Camouflage (ability) | Prevent all effects of opponent's Item/Supporter on this Pokémon — requires global hook on trainer play to intercept targeted effects |
| TR Persian ex DRI 150 | sv10-150 | Haughty Order (atk0) | Use an attack from a Pokémon in the opponent's deck — requires deck-scanning attack execution not currently supported |
| Skeledirge SSP 31 | sv08-031 | Unaware (ability) | Not affected by opponent's attack effects — broad attack-effect prevention hook not in engine |
| Scovillain ex SSP 37 | sv08-037 | Double Type (ability) | This Pokémon is also a Grass-type — dual typing not supported in damage pipeline |
| Mr. Mime TEF 63 | sv05-063 | Look-Alike Show (atk0) | Reveal opponent's hand; use a Supporter effect found there — hand-reveal + Supporter mimicry not supported |
| Delcatty TEF 131 | sv05-131 | Energy Blender (atk1) | Move any amount of Energy from any of your Pokémon to any others — arbitrary multi-source energy redistribution not in engine |
| Relicanth TEF 84 | sv05-084 | Memory Dive (ability) | Evolved Pokémon can use attacks from previous evolutions — prior-form attack-access not in engine |
| Iron Treads TEF 118 | sv05-118 | Dual Core (ability) | Pokémon is F+M type when Future Booster Energy Capsule attached — tool-dependent dual typing not supported |
| Iron Jugulis TEF 139 | sv05-139 | Automated Combat (ability) | On being damaged, counter-attack with own attacks — on-damage counter-attack trigger not in engine |
| TR Persian ex PR-SV 218 | svp-218 | Haughty Order (atk0) | Copy an attack from a Pokémon in the opponent's top 10 deck cards — deck-scanning attack execution not currently supported |
| Energy Swatter POR 73 | me03-073 | (trainer effect) | Reveal opponent's hand; attach Basic Energy only to Pokémon whose type appears in opponent's hand — requires hand-reveal + type-matching energy attachment not supported |
| Lt. Surge's Bargain MEG 120 | me01-120 | (trainer effect) | Opponent chooses to discard 0, 1, or 2 of their own Pokémon — opponent-interactive decision with branching discard not supported |
| Wally's Compassion MEG 132 | me01-132 | (trainer effect) | Return Pokémon Tool + Energy to hand; then evolve attached Mega Evolution ex — Mega Evo detection and mid-battle multi-step evolution sequence not supported |
| Team Rocket's Bother-Bot DRI 172 | sv10-172 | (trainer effect) | Plays as face-up Prize card mechanic — prize zone manipulation not supported in engine |
| Redeemable Ticket JTG 156 | sv09-156 | (trainer effect) | Reveal top prizes until you find a Supporter; swap it into your hand — prize zone search/swap not supported |
| Ogre's Mask PRE 118 | sv08.5-118 | (trainer effect) | Swap the Pokémon this Tool is attached to with one of your Benched Pokémon — mid-turn bench↔active swap via Tool not supported |
| TM: Fluorite SSP 188 | sv08-188 | (trainer effect) | Heal 30 from all your Tera Pokémon between turns — end-of-turn Tera-wide heal not supported |
| Tyme SSP 190 | sv08-190 | (trainer effect) | Opponent calls heads or tails; if wrong, discard 2 from hand — opponent-interactive guessing game not supported |
| Boomerang Energy TWM 166 | sv06-166 | (energy effect) | When this Special Energy is discarded from a Pokémon, return it to hand — on-discard-from-play energy recycle not supported |
