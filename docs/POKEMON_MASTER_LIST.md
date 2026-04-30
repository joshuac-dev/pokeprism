---

## FLAGGED_CARDS

Cards too complex for automatic handler generation. Requires manual implementation.

| Card | TCGDex ID | Attack/Ability | Reason |
|------|-----------|---------------|--------|
| Tyrantrum POR 45 | me03-045 | Tyrannically Gutsy (ability) | +150 HP if Special Energy attached — dynamic max HP not supported |
| Rotom ex PFL 29 | me02-029 | Multi Adapter (ability) | Each of your Pokémon that has 'Rotom' in its name may have up to 2 Tool cards attached — modifying the tool attachment limit in actions.py (currently hardcoded to 1) is too complex |
| Duosion BLK 38 | sv10.5b-038 | Cellular Evolution (atk0) | Evolve any of your Benched Pokémon from deck mid-battle — full in-battle multi-bench evolution not supported |
| Reuniclus BLK 39 | sv10.5b-039 | Cellular Ascension (atk0) | Evolve all of your in-play Pokémon from deck simultaneously — full simultaneous batch evolution not supported |
| Karrablast BLK 9 | sv10.5b-009 | Stimulated Evolution (ability) | First-turn evolution requires Shelmet in play — conditional evolution rule not supported in action validator |
| Meloetta ex BLK 44 | sv10.5b-044 | Debut Performance (ability) | Attack on first turn of the game — first-turn attack exception requires action validator change |
| Conkeldurr BLK 49 | sv10.5b-049 | Craftsmanship (ability) | +40 max HP per attached {F} Energy — dynamic max HP recalculation not supported |
| Crawdaunt MEG 85 | me01-085 | Cutting Riposte (atk1) | Cost reduction to {D} when already damaged — conditional energy cost requires action validator change |
| Latios MEG 101 | me01-101 | Lustrous Assist (ability) | Trigger when Mega Latias ex moves bench→active, move energy — complex event hook not supported |
| Shelmet WHT 8 | sv10.5w-008 | Stimulated Evolution (ability) | Evolve during first turn if Karrablast in play — modifies turn-1 evolution restriction rules, requires turn-counter and bench-scanning logic |
| Archeops WHT 51 | sv10.5w-051 | Ancient Wing (ability) | Devolve 1 of opp's Evolution Pokémon — requires engine to track and restore previous evolution forms, which are not preserved |
| Misty's Psyduck DRI 45 | sv10-045 | Flustered Leap (ability) | Discard bottom of deck then return this Pokémon to top of deck from bench — returning Pokémon from bench to deck not supported; bottom-of-deck access not supported |
| Huntail DRI 55 | sv10-055 | Diver's Catch (ability) | When a Water Pokémon of yours is KO'd, recover attached Basic Water Energy to hand — requires on-KO energy-salvage hook not in engine |
| Cetitan ex DRI 65 | sv10-065 | Snow Camouflage (ability) | Prevent all effects of opponent's Item/Supporter on this Pokémon — requires global hook on trainer play to intercept targeted effects |
| TR Nidorina DRI 115 | sv10-115 | Dark Awakening (atk0) | Evolve up to 2 Darkness Pokémon from deck during battle — requires mid-battle in-deck evolution not currently supported |
| TR Grimer DRI 123 | sv10-123 | Corrosive Sludge (atk0) | Schedule KO of opponent's active at end of opponent's next turn — requires deferred/scheduled KO hook not currently in engine |
| TR Persian ex DRI 150 | sv10-150 | Haughty Order (atk0) | Use an attack from a Pokémon in the opponent's deck — requires deck-scanning attack execution not currently supported |
| Ludicolo JTG 37 | sv09-037 | Vibrant Dance (ability) | All Pokémon in play get +40 HP permanently — dynamic max HP increase on all in-play Pokémon not supported |
| Lycanroc JTG 85 | sv09-085 | Spike-Clad (ability) | On evolve: attach Spiky Energy from discard — on-evolve attach from discard not currently supported |
| Noivern JTG 128 | sv09-128 | Tuning Echo (ability) | Reduce Frightening Howl cost when hand size equals opponent's — conditional energy cost modification requires action validator change |
| Dipplin PRE 10 | sv08.5-010 | Festival Lead (ability) | Attack twice if Festival Grounds is in play — second-attack in one turn requires complex turn-phase tracking |
| Goldeen PRE 20 | sv08.5-020 | Festival Lead (ability) | Attack twice if Festival Grounds is in play — second-attack in one turn not supported |
| Seaking PRE 21 | sv08.5-021 | Festival Lead (ability) | Attack twice if Festival Grounds is in play — second-attack in one turn not supported |
| Glaceon PRE 25 | sv08.5-025 | Permeating Chill (atk0) | Place 9 damage counters on opp's Active at end of opponent's next turn — deferred/scheduled damage not in engine |
| Espeon ex PRE 34 | sv08.5-034 | Amazez (atk1) | Devolve all of opponent's Evolved Pokémon — engine has no previous-evolution form tracking |
| Okidogi PRE 57 | sv08.5-057 | Adrena-Power (ability) | +150 HP if Darkness Energy attached — dynamic max HP not supported |
| Umbreon ex PRE 60 | sv08.5-060 | Onyx (atk1) | Discard all Energy and take an extra Prize card — extra prize card mechanics not supported |
| Eevee PRE 74 | sv08.5-074 | Boosted Evolution (ability) | Evolve on first turn of game — first-turn evolution exception requires action validator change |
| Eevee ex PRE 75 | sv08.5-075 | Rainbow DNA (ability) | Eeveelutions may evolve from this card — special multi-target evolution rule not supported |
| Dudunsparce PRE 80 | sv08.5-080 | Run Away Draw (ability) | Put this Pokémon into deck; draw 2 — returning Active to deck during Active position not supported |
| Exeggcute SSP 1 | sv08-001 | Precocious Evolution (atk0) | Search deck for Evolution and evolve a Benched Pokémon on first turn — first-turn mid-battle evolution not supported |
| Vivillon SSP 7 | sv08-007 | Evo-Powder (atk0) | Evolve all of your Benched Pokémon from deck simultaneously — mass in-battle evolution not supported |
| Castform Sunny Form SSP 20 | sv08-020 | Sunny Assist (atk1) | Redistribute all attached Energy to any of your Pokémon — arbitrary energy redistribution not supported |
| Magneton SSP 59 | sv08-059 | Overvolt Discharge (ability) | KO this Pokémon; attach multiple Energy from deck — self-KO + multi-energy attach from deck not supported |
| Azumarill SSP 74 | sv08-074 | Glistening Bubbles (ability) | Reduce cost of attacks by {W} for each Tera Pokémon in play — dynamic cost reduction based on Tera count not supported |
| Espathra SSP 95 | sv08-095 | Mystical Eyes (atk0) | Devolve all of opponent's Evolved Pokémon — engine has no previous-evolution form tracking |
| Annihilape SSP 100 | sv08-100 | Destined Fight (atk1) | Both Active Pokémon are Knocked Out — mutual-KO mechanic requires simultaneous prize resolution not in engine |
| Grapploct SSP 113 | sv08-113 | Raging Tentacles (atk1) | Cost reduced to {W} if this Pokémon has damage counters — conditional energy cost modification requires action validator change |
| Skeledirge SSP 31 | sv08-031 | Unaware (ability) | Not affected by opponent's attack effects — broad attack-effect prevention hook not in engine |
| Scovillain ex SSP 37 | sv08-037 | Double Type (ability) | This Pokémon is also a Grass-type — dual typing not supported in damage pipeline |
| Alcremie SCR 65 | sv07-065 | Colorful Confection (atk0) | Search deck for up to 5 Pokémon matching any attached Basic Energy type — search-by-energy-type not supported |
| Klinklang SCR 101 | sv07-101 | Emergency Rotation (ability) | When this Pokémon takes damage, you may retreat it for free — on-damage conditional retreat hook not in engine |
| Iron Moth SFA 9 | sv06.5-009 | Anachronism Repulsor (atk1) | Opponent's Ancient Pokémon take 100 damage next turn — type-based deferred damage on opponent's board not supported |
| Seadra SFA 11 | sv06.5-011 | Call for Backup (atk0) | Search deck for Evolution Pokémon of same type and evolve immediately — mid-battle in-deck evolution not supported |
| Revavroom ex SFA 15 | sv06.5-015 | Accelerator Flash (atk0) / Shattering Speed (atk1) | Both require attaching Energy from deck to self during attack — energy-from-deck-to-self not supported |
| Conkeldurr TWM 105 | sv06-105 | Gutsy Swing (atk1) | Ignore energy cost if Active has Special Condition — conditional energy-cost bypass not supported |
| Eevee TWM 135 | sv06-135 | Ascension (atk0) | Search deck for Eevee evolution and evolve — evolution-from-deck not supported |
| Brambleghast TEF 21 | sv05-021 | Resilient Soul (ability) | HP = 60 + 50 per prize remaining — dynamic HP based on prizes not supported |
| Magcargo TEF 29 | sv05-029 | Lava Zone (ability) | When this Pokémon retreats, opponent's Active is now Burned — on-retreat trigger not supported |
| Incineroar ex TEF 34 | sv05-034 | Hustle Play (ability) | This Pokémon can use attacks with 1 fewer Energy — dynamic attack-cost reduction not supported |
| Feraligatr TEF 41 | sv05-041 | Torrential Heart (ability) | Water Energy counts as 2 when paying retreat/attack costs — energy-doubling cost reduction not supported |
| Mr. Mime TEF 63 | sv05-063 | Look-Alike Show (atk0) | Reveal opponent's hand; use a Supporter effect found there — hand-reveal + Supporter mimicry not supported |
| Bronzong TEF 69 | sv05-069 | Evolution Jammer (atk0) | Opponent can't play Pokémon from hand to evolve next turn — play-from-hand evolution validator hook not in engine |
| Ribombee TEF 76 | sv05-076 | Plentiful Pollen (atk0) | If Defending Pokémon is KO'd during opponent's next turn, take 2 extra Prizes — deferred KO-triggered prize bonus not in engine |
| Iron Crown ex TEF 81 | sv05-081 | Twin Shotels (atk0) | 50 damage to 2 of opponent's Pokémon, ignoring W/R and effects — dual-target attack not in engine |
| Great Tusk TEF 97 | sv05-097 | Land Collapse (atk0) | Discard top of opponent's deck; if Ancient Supporter played this turn, discard top 5 — opponent deck manipulation + Ancient Supporter tracking not in engine |
| Iron Boulder ex TEF 99 | sv05-099 | Repulsor Axe (atk0) | If damaged by an attack this turn, may put attacker on opponent's bench — on-damage conditional counter-effect choice not in engine |
| Delcatty TEF 131 | sv05-131 | Energy Blender (atk1) | Move any amount of Energy from any of your Pokémon to any others — arbitrary multi-source energy redistribution not in engine |
| Relicanth TEF 84 | sv05-084 | Memory Dive (ability) | Evolved Pokémon can use attacks from previous evolutions — prior-form attack-access not in engine |
| Gengar ex TEF 104 | sv05-104 | Gnawing Curse (ability) | Place 2 damage counters on any Pokémon opponent attaches Energy to from hand — on-energy-attach trigger not in engine |
| Iron Treads TEF 118 | sv05-118 | Dual Core (ability) | Pokémon is F+M type when Future Booster Energy Capsule attached — tool-dependent dual typing not supported |
| Pidove TEF 133 | sv05-133 | Emergency Evolution (ability) | Evolve from deck when HP ≤ 30 — conditional HP-threshold evolution not in engine |
| Iron Jugulis TEF 139 | sv05-139 | Automated Combat (ability) | On being damaged, counter-attack with own attacks — on-damage counter-attack trigger not in engine |
| Meganium MEP 1 | mep-001 | Wild Growth (ability) | Each Basic G Energy counts as 2 — energy-value doubling fundamentally overrides cost system |
| Psyduck MEP 7 | mep-007 | Damp (ability) | Suppresses all abilities requiring KO while Pokémon is in play — global KO-trigger ability suppression not in engine |
| Golduck MEP 8 | mep-008 | Damp (ability) | Suppresses all abilities requiring KO while Pokémon is in play — global KO-trigger ability suppression not in engine |
| Iron Leaves ex PR-SV 128 | svp-128 | Rapid Vernier (ability) | On-play-to-bench: switch to Active + move any Energy from other Pokémon to self — on-bench-play promote + energy-redistribution hook not in engine |
| Reuniclus PR-SV 212 | svp-212 | Cellular Ascension (atk0) | Evolve each Benched Pokémon from deck simultaneously — mass in-battle bench evolution not supported |
| TR Persian ex PR-SV 218 | svp-218 | Haughty Order (atk0) | Copy an attack from a Pokémon in the opponent's top 10 deck cards — deck-scanning attack execution not currently supported |
| Energy Swatter POR 73 | me03-073 | (trainer effect) | Reveal opponent's hand; attach Basic Energy only to Pokémon whose type appears in opponent's hand — requires hand-reveal + type-matching energy attachment not supported |
| Lt. Surge's Bargain MEG 120 | me01-120 | (trainer effect) | Opponent chooses to discard 0, 1, or 2 of their own Pokémon — opponent-interactive decision with branching discard not supported |
| Wally's Compassion MEG 132 | me01-132 | (trainer effect) | Return Pokémon Tool + Energy to hand; then evolve attached Mega Evolution ex — Mega Evo detection and mid-battle multi-step evolution sequence not supported |
| Team Rocket's Bother-Bot DRI 172 | sv10-172 | (trainer effect) | Plays as face-up Prize card mechanic — prize zone manipulation not supported in engine |
| Redeemable Ticket JTG 156 | sv09-156 | (trainer effect) | Reveal top prizes until you find a Supporter; swap it into your hand — prize zone search/swap not supported |
| Amarys PRE 93 | sv08.5-093 | (trainer effect) | Move any number of Energy from your Benched Pokémon to another at end of turn — end-of-turn effect trigger not supported |
| Ogre's Mask PRE 118 | sv08.5-118 | (trainer effect) | Swap the Pokémon this Tool is attached to with one of your Benched Pokémon — mid-turn bench↔active swap via Tool not supported |
| TM: Fluorite SSP 188 | sv08-188 | (trainer effect) | Heal 30 from all your Tera Pokémon between turns — end-of-turn Tera-wide heal not supported |
| Tyme SSP 190 | sv08-190 | (trainer effect) | Opponent calls heads or tails; if wrong, discard 2 from hand — opponent-interactive guessing game not supported |
| Powerglass SFA 63 | sv06.5-063 | (trainer effect) | Attached Tool: at the end of your turn, deal 60 to opponent's Active — end-of-turn damage from Tool not supported |
| Lucky Helmet TWM 158 | sv06-158 | (trainer effect) | When the Pokémon this Tool is attached to is damaged by opponent's attack, draw 2 — on-damage trigger hook via Tool not in engine |
| Heavy Baton TEF 151 | sv05-151 | (trainer effect) | When the Pokémon this Tool is attached to retreats, attach a Basic Energy from discard to the retreating Pokémon — on-retreat trigger via Tool not in engine |
| Perilous Jungle TEF 156 | sv05-156 | (trainer effect) | Stadium: once per turn, when an opponent's Pokémon is damaged by your Pokémon's attacks, place 2 damage counters on that Pokémon — end-of-damage-event trigger per stadium not supported |
| Celebratory Fanfare MEP 28 | mep-028 | (trainer effect) | Stadium: when a player takes their last Prize card, that player draws 3 cards — prize-zone trigger hook not in engine |
| Boomerang Energy TWM 166 | sv06-166 | (energy effect) | When this Special Energy is discarded from a Pokémon, return it to hand — on-discard-from-play energy recycle not supported |
