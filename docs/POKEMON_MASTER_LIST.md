---

## FLAGGED_CARDS

Cards too complex for automatic handler generation. Requires manual implementation.

| Card | TCGDex ID | Attack/Ability | Reason |
|------|-----------|---------------|--------|
| Spewpa POR 8 | me03-008 | Hide (atk0) | Prevents all damage next turn — requires new persistent-state field + runner.py reset logic |
| Hippopotas POR 39 | me03-039 | Sand Attack (atk0) | Opponent's next attack may fail on tails — requires persistent attack-check hook in runner.py |
| Hippowdon POR 40 | me03-040 | Twister Spewing (atk0) | Conditional on Tarragon being played this turn — requires trainer-played-this-turn tracking |
| Tyrantrum POR 45 | me03-045 | Tyrannically Gutsy (ability) | +150 HP if Special Energy attached — dynamic max HP not supported |
| Gengar POR 50 | me03-050 | Infinite Shadow (ability) | Put into hand instead of discard on KO — requires on-KO hook not currently in engine |
| Klefki POR 59 | me03-059 | Memory Lock (atk0) | Locks a specific named attack on opponent — requires per-attack lock state |
| Turtonator POR 17 | me03-017 | Shell Spikes (ability) | Place counters on attacker when this Pokémon is damaged — requires on-damage trigger |
| Numel ASC 27 | me02.5-027 | Incandescent Body (ability) | Apply Burned to attacker when this Pokémon is damaged — requires on-damage trigger |
| Rotom ex PFL 29 | me02-029 | Multi Adapter (ability) | Each of your Pokémon that has 'Rotom' in its name may have up to 2 Tool cards attached — modifying the tool attachment limit in actions.py (currently hardcoded to 1) is too complex |
| Duosion BLK 38 | sv10.5b-038 | Cellular Evolution (atk0) | Evolve any of your Benched Pokémon from deck mid-battle — full in-battle multi-bench evolution not supported |
| Reuniclus BLK 39 | sv10.5b-039 | Cellular Ascension (atk0) | Evolve all of your in-play Pokémon from deck simultaneously — full simultaneous batch evolution not supported |
| Karrablast BLK 9 | sv10.5b-009 | Stimulated Evolution (ability) | First-turn evolution requires Shelmet in play — conditional evolution rule not supported in action validator |
| Meloetta ex BLK 44 | sv10.5b-044 | Debut Performance (ability) | Attack on first turn of the game — first-turn attack exception requires action validator change |
| Conkeldurr BLK 49 | sv10.5b-049 | Craftsmanship (ability) | +40 max HP per attached {F} Energy — dynamic max HP recalculation not supported |
| Crawdaunt MEG 85 | me01-085 | Cutting Riposte (atk1) | Cost reduction to {D} when already damaged — conditional energy cost requires action validator change |
| Latios MEG 101 | me01-101 | Lustrous Assist (ability) | Trigger when Mega Latias ex moves bench→active, move energy — complex event hook not supported |
| Shelmet WHT 8 | sv10.5w-008 | Stimulated Evolution (ability) | Evolve during first turn if Karrablast in play — modifies turn-1 evolution restriction rules, requires turn-counter and bench-scanning logic |
| Emboar WHT 13 | sv10.5w-013 | Inferno Fandango (ability) | Unlimited Basic Fire Energy attachment per turn — fundamentally overrides 1-energy-per-turn rule, requires special energy attachment hook |
| Jellicent ex WHT 45 | sv10.5w-045 | Oceanic Curse (ability) | Passive prevents opp from playing Item/Tool cards while in Active — requires action validator integration |
| Archeops WHT 51 | sv10.5w-051 | Ancient Wing (ability) | Devolve 1 of opp's Evolution Pokémon — requires engine to track and restore previous evolution forms, which are not preserved |
| Terrakion WHT 54 | sv10.5w-054 | Retaliate (atk0) | +50 damage if any of my Pokémon were KO'd during opponent's last turn — requires inter-turn KO tracking flag not currently in state |
| Hydreigon ex WHT 67 | sv10.5w-067 | Greedy Eater (ability) | Take extra prize on KO of Basic Pokémon — requires hooking into KO/prize resolution with per-attacker source tracking |
| Watchog WHT 73 | sv10.5w-073 | Focus Energy (atk0) | Buffs Hyper Fang base damage on next turn — requires per-attack state flag persisting across turns (not in current CardInstance) |
| Ethan's Pinsir DRI 1 | sv10-001 | Rallying Horn (atk1) | +100 damage if any of your Ethan's Pokémon were KO'd by opponent last turn — requires inter-turn Ethan's-KO tracking flag not currently in state |
| TR Moltres ex DRI 31 | sv10-031 | Evil Incineration (atk1) | Discard a TR Energy; if done, discard opponent's Active Pokémon and all attached cards — instant forced-KO discard mechanic not supported |
| Ethan's Magcargo DRI 36 | sv10-036 | Melt Away (ability) | No Retreat Cost when no Energy attached — dynamic retreat cost modification based on attached energy not supported |
| Misty's Psyduck DRI 45 | sv10-045 | Flustered Leap (ability) | Discard bottom of deck then return this Pokémon to top of deck from bench — returning Pokémon from bench to deck not supported; bottom-of-deck access not supported |
| Huntail DRI 55 | sv10-055 | Diver's Catch (ability) | When a Water Pokémon of yours is KO'd, recover attached Basic Water Energy to hand — requires on-KO energy-salvage hook not in engine |
| Cetitan ex DRI 65 | sv10-065 | Snow Camouflage (ability) | Prevent all effects of opponent's Item/Supporter on this Pokémon — requires global hook on trainer play to intercept targeted effects |
| TR Ampharos DRI 74 | sv10-074 | Darkest Impulse (ability) | Put 4 damage counters on a Pokémon when opponent evolves it — requires on-evolve trigger placing damage on the evolved Pokémon |
| TR Tyranitar DRI 96 | sv10-096 | Sand Stream (ability) | During Pokémon Checkup, place 2 damage counters on each opponent Basic Pokémon — requires a Checkup-phase damage hook not currently implemented |
| Yanmega ex DRI 3 | sv10-003 | Buzzing Boost (ability) | When this Pokémon moves from Bench to Active, search deck for up to 3 Basic {G} Energy — on-promote ability hook not supported in engine |
| TR Arbok DRI 113 | sv10-113 | Potent Glare (ability) | Prevents opponent from playing Pokémon with abilities from hand — requires play-from-hand validator hook not currently in engine |
| TR Nidorina DRI 115 | sv10-115 | Dark Awakening (atk0) | Evolve up to 2 Darkness Pokémon from deck during battle — requires mid-battle in-deck evolution not currently supported |
| TR Grimer DRI 123 | sv10-123 | Corrosive Sludge (atk0) | Schedule KO of opponent's active at end of opponent's next turn — requires deferred/scheduled KO hook not currently in engine |
| Forretress DRI 140 | sv10-140 | Iron Shake-Up (atk0) | Move any Metal energy freely between own Pokémon — requires arbitrary energy re-distribution not currently supported |
| Zamazenta DRI 146 | sv10-146 | Strong Bash (atk0) | Retaliatory damage equal to damage taken from attacks during opponent's last turn — requires inter-turn damage-received tracking not currently in state |
| TR Persian ex DRI 150 | sv10-150 | Haughty Order (atk0) | Use an attack from a Pokémon in the opponent's deck — requires deck-scanning attack execution not currently supported |
| Ludicolo JTG 37 | sv09-037 | Vibrant Dance (ability) | All Pokémon in play get +40 HP permanently — dynamic max HP increase on all in-play Pokémon not supported |
| Alolan Marowak JTG 57 | sv09-057 | Retaliate (atk0) | +90 damage if any of your Pokémon were KO'd during opponent's last turn — requires inter-turn KO tracking flag not currently in state |
| Weezing JTG 92 | sv09-092 | Crazy Blast (atk1) | +120 damage if Pervasive Gas was used last turn — requires per-turn last-used-attack tracking not currently in state |
| Pangoro JTG 99 | sv09-099 | Torment (atk0) | Opponent's Active can't use the same attack twice in a row — requires per-Pokémon last-used-attack tracking not in state |
| Lillie's Ribombee JTG 67 | sv09-067 | Inviting Wink (ability) | On evolve: put opponent's Basic Pokémon from hand onto their bench — on-evolve-from-hand trigger not currently hooked in transitions.py |
| Lycanroc JTG 85 | sv09-085 | Spike-Clad (ability) | On evolve: attach Spiky Energy from discard — on-evolve attach from discard not currently supported |
| Tyranitar JTG 95 | sv09-095 | Daunting Gaze (ability) | Opponent can't play Item cards while this is Active — requires play-from-hand item validator integration |
| Magearna JTG 107 | sv09-107 | Auto Heal (ability) | Heal 90 damage whenever energy attached — requires on-energy-attach heal hook not in engine |
| Noivern JTG 128 | sv09-128 | Tuning Echo (ability) | Reduce Frightening Howl cost when hand size equals opponent's — conditional energy cost modification requires action validator change |
| Komala JTG 129 | sv09-129 | Slumbering Smack (atk0) | +100 damage on next turn if this attack was used — requires inter-turn last-used-attack bonus tracking not in state |
| Lillie's Comfey JTG 68 | sv09-068 | Fade Out (atk1) | Return this Pokémon and all attached cards to hand — returning Active Pokémon to hand mid-battle not supported |
| Whimsicott PRE 8 | sv08.5-008 | Wafting Heal (ability) | Heal 30 from a Pokémon when this evolves — on-evolve heal hook not in engine |
| Dipplin PRE 10 | sv08.5-010 | Festival Lead (ability) | Attack twice if Festival Grounds is in play — second-attack in one turn requires complex turn-phase tracking |
| Goldeen PRE 20 | sv08.5-020 | Festival Lead (ability) | Attack twice if Festival Grounds is in play — second-attack in one turn not supported |
| Seaking PRE 21 | sv08.5-021 | Festival Lead (ability) | Attack twice if Festival Grounds is in play — second-attack in one turn not supported |
| Glaceon PRE 25 | sv08.5-025 | Permeating Chill (atk0) | Place 9 damage counters on opp's Active at end of opponent's next turn — deferred/scheduled damage not in engine |
| Espeon ex PRE 34 | sv08.5-034 | Amazez (atk1) | Devolve all of opponent's Evolved Pokémon — engine has no previous-evolution form tracking |
| Okidogi PRE 57 | sv08.5-057 | Adrena-Power (ability) | +150 HP if Darkness Energy attached — dynamic max HP not supported |
| Sylveon ex PRE 41 | sv08.5-041 | Angelite (atk1) | Return 2 of opponent's Benched Pokémon to their deck — mass bounce to deck not supported |
| Lucario ex PRE 51 | sv08.5-051 | Tornado Rush (atk1) | +100 damage on next turn if Tornado Rush was used — inter-turn last-used-attack bonus tracking not in state |
| Umbreon ex PRE 60 | sv08.5-060 | Onyx (atk1) | Discard all Energy and take an extra Prize card — extra prize card mechanics not supported |
| Archaludon ex PRE 70 | sv08.5-070 | Metal Bridge (ability) | Retreat for free if Metal Energy attached — dynamic retreat cost based on attachment not supported |
| Eevee PRE 74 | sv08.5-074 | Boosted Evolution (ability) | Evolve on first turn of game — first-turn evolution exception requires action validator change |
| Eevee ex PRE 75 | sv08.5-075 | Rainbow DNA (ability) | Eeveelutions may evolve from this card — special multi-target evolution rule not supported |
| Noctowl PRE 78 | sv08.5-078 | Jewel Seeker (ability) | On evolve: search deck for Terapagos ex — on-evolve deck search not implemented as hook |
| Dudunsparce PRE 80 | sv08.5-080 | Run Away Draw (ability) | Put this Pokémon into deck; draw 2 — returning Active to deck during Active position not supported |
| Miltank PRE 81 | sv08.5-081 | Moomoo Rolling (atk1) | +100 extra damage if Rollout was used last turn — inter-turn last-used-attack tracking not in state |
| Durant ex SSP 4 | sv08-004 | Sudden Shearing (ability) | On bench-play: discard top of opponent's deck — on-bench-play trigger hook not in engine |
| Exeggcute SSP 1 | sv08-001 | Precocious Evolution (atk0) | Search deck for Evolution and evolve a Benched Pokémon on first turn — first-turn mid-battle evolution not supported |
| Vivillon SSP 7 | sv08-007 | Evo-Powder (atk0) | Evolve all of your Benched Pokémon from deck simultaneously — mass in-battle evolution not supported |
| Castform Sunny Form SSP 20 | sv08-020 | Sunny Assist (atk1) | Redistribute all attached Energy to any of your Pokémon — arbitrary energy redistribution not supported |
| Armarouge SSP 34 | sv08-034 | Crimson Blaster (atk1) | Discard {R}{R} or {P}{P} from attacker, then 200 to any Pokémon — type-specific energy discard + bench targeting not supported |
| Ceruledge SSP 35 | sv08-035 | Cursed Edge (atk0) | Discard all Special Energy from each of opponent's Pokémon — mass Special-Energy discard not supported |
| Paldean Tauros SSP 39 | sv08-039 | Upthrusting Horns (atk0) | Return 2 Energy from opponent's Stage 2 Active to hand — stage-check + energy return to hand not supported |
| Walrein SSP 45 | sv08-045 | Frigid Fangs (atk0) | Opponent's Active can't attack next turn if 3+ Energy attached — energy-count-based cant-attack not supported |
| Pikachu ex SSP 57 | sv08-057 | Resolute Heart (ability) | Prevent KO from damage (leave at 10 HP instead) — OHKO prevention requires HP-floor hook not in engine |
| Magneton SSP 59 | sv08-059 | Overvolt Discharge (ability) | KO this Pokémon; attach multiple Energy from deck — self-KO + multi-energy attach from deck not supported |
| Magnezone SSP 60 | sv08-060 | Zap Cannon (atk1) | This Pokémon can't use Zap Cannon on next turn — attack-specific can't-use inter-turn tracking not supported |
| Rotom SSP 61 | sv08-061 | Crushing Pulse (atk0) | Look at opp's hand; discard all Items/Tools found — hand-reveal + selective discard of Items/Tools not supported |
| Kilowattrel SSP 67 | sv08-067 | Storm Bolt (atk1) | Move all Energy from this Pokémon to your Bench — arbitrary energy redistribution to bench not supported |
| Kilowattrel ex SSP 68 | sv08-068 | Return Charge (atk0) | Switch opp's Active with Benched; attach Basic Energy from hand to that Pokémon — forced switch + energy attach combo not supported |
| Miraidon SSP 69 | sv08-069 | C.O.D.E.: Protect (atk0) | Future Pokémon not affected by effects of opp's attacks next turn — future-type effect immunity requires persistent flag not in state |
| Togekiss SSP 72 | sv08-072 | Wonder Kiss (ability) | Take an extra Prize when this Pokémon KOs an ex/V — on-KO extra prize hook with source tracking not in engine |
| Azumarill SSP 74 | sv08-074 | Glistening Bubbles (ability) | Reduce cost of attacks by {W} for each Tera Pokémon in play — dynamic cost reduction based on Tera count not supported |
| Meowstic SSP 85 | sv08-085 | Beckoning Tail (ability) | Use if you have a Supporter in hand: put a Pokémon from opponent's Bench into their hand — requires Supporter-in-hand check + forced return not supported |
| Palossand ex SSP 91 | sv08-091 | Barite Jail (atk1) | Each of opp's Benched Pokémon that has more than 100 HP remaining has 100 HP remaining — arbitrary HP floor on multiple targets not supported |
| Indeedee SSP 93 | sv08-093 | Obliging Heal (ability) | When you play this from hand to Bench, heal 60 from one of your Pokémon — on-bench-play heal hook not in engine |
| Flittle SSP 94 | sv08-094 | Splashing Dodge (atk0) | Flip; if heads this Pokémon has no Weakness next turn — conditional per-turn Weakness removal not in state |
| Espathra SSP 95 | sv08-095 | Mystical Eyes (atk0) | Devolve all of opponent's Evolved Pokémon — engine has no previous-evolution form tracking |
| Flutter Mane SSP 96 | sv08-096 | Perplexing Transfer (atk0) | Move any number of damage counters from opponent's Bench to opponent's Active — arbitrary bench→active damage-counter move not supported |
| Annihilape SSP 100 | sv08-100 | Destined Fight (atk1) | Both Active Pokémon are Knocked Out — mutual-KO mechanic requires simultaneous prize resolution not in engine |
| Donphan SSP 103 | sv08-103 | Guarded Rolling (atk1) | Discard 2 Energy; this Pokémon takes 100 less damage during opponent's next turn — energy discard + deferred damage reduction not supported |
| Gastrodon SSP 107 | sv08-107 | Sticky Bind (ability) | Opponent's Benched Stage 2 Pokémon have no Abilities — opponent bench ability suppression not in engine |
| Grapploct SSP 113 | sv08-113 | Raging Tentacles (atk1) | Cost reduced to {W} if this Pokémon has damage counters — conditional energy cost modification requires action validator change |
| Koraidon SSP 116 | sv08-116 | Unrelenting Onslaught (atk0) | +50 if an Ancient Pokémon used Unrelenting Onslaught last turn — inter-turn Ancient-attack tracking not in state |
| Skeledirge SSP 31 | sv08-031 | Unaware (ability) | Not affected by opponent's attack effects — broad attack-effect prevention hook not in engine |
| Scovillain ex SSP 37 | sv08-037 | Double Type (ability) | This Pokémon is also a Grass-type — dual typing not supported in damage pipeline |
| Bruxish SSP 49 | sv08-049 | Counterattack (ability) | When damaged, place 3 counters on attacker — on-damage trigger not in engine |
| Alcremie SCR 65 | sv07-065 | Colorful Confection (atk0) | Search deck for up to 5 Pokémon matching any attached Basic Energy type — search-by-energy-type not supported |
| Dachsbun ex SCR 67 | sv07-067 | Time to Chow Down (ability) | On evolve: heal 100 from each of your Pokémon — on-evolve heal hook not in engine |
| Falinks SCR 88 | sv07-088 | All-Out Attack (atk1) | +90 damage if Form Ranks was used last turn — inter-turn last-used-attack tracking not in state |
| Grimmsnarl SCR 96 | sv07-096 | Goad 'n' Grab (atk0) | Forced switch opponent's bench + damage to new active — forced-switch-before-damage combo not supported |
| Jirachi SCR 98 | sv07-098 | Swelling Wish (atk0) | Attach a Basic Energy from discard to 1 of your Benched Pokémon — energy-from-discard-to-bench not yet wired |
| Orthworm ex SCR 110 | sv07-110 | Pummeling Payback (ability) | Place 3 damage counters on attacker when this Pokémon is damaged — on-damage trigger not in engine |
| Klinklang SCR 101 | sv07-101 | Emergency Rotation (ability) | When this Pokémon takes damage, you may retreat it for free — on-damage conditional retreat hook not in engine |
| Archaludon SCR 107 | sv07-107 | Metal Bridge (ability) | Retreat for free if Metal Energy attached — dynamic retreat cost based on attachment not supported |
| Noctowl SCR 115 | sv07-115 | Jewel Seeker (ability) | On evolve: search deck for Terapagos ex — on-evolve deck search not implemented as hook |
| Fletchling SCR 121 | sv07-121 | Send Back (atk0) | Shuffle opponent's hand and redraw — hand shuffle + redraw for opponent not supported |
| Wooloo SCR 124 | sv07-124 | Knock Over (atk0) | Discard all Items and Tools attached to opponent's Active Pokémon — mass tool/item discard not supported |
| Dubwool SCR 125 | sv07-125 | Knock Over (atk0) / Soft Wool (ability) | Knock Over: same as Wooloo; Soft Wool: reduce bench damage by 30 — bench damage reduction hook not in engine |
| Bouffalant SCR 119 | sv07-119 | Curly Wall (ability) | Reduce damage done to your Benched Pokémon by 20 — bench damage reduction hook not in engine |
| Dartrix SFA 4 | sv06.5-004 | United Wings (atk0) | 20× count of United Wings Pokémon in deck/discard/play — requires scanning multiple zones for named Pokémon |
| Decidueye SFA 5 | sv06.5-005 | Stock Up on Feathers (atk0) | Add feather counter to this Pokémon; each counter used in Power Shot — requires persistent multi-turn counter state |
| Iron Moth SFA 9 | sv06.5-009 | Anachronism Repulsor (atk1) | Opponent's Ancient Pokémon take 100 damage next turn — type-based deferred damage on opponent's board not supported |
| Seadra SFA 11 | sv06.5-011 | Call for Backup (atk0) | Search deck for Evolution Pokémon of same type and evolve immediately — mid-battle in-deck evolution not supported |
| Kingdra ex SFA 12 | sv06.5-012 | King's Order (atk0) | Shuffle all opponent's Pokémon with 200+ HP into deck — conditional mass-bounce requiring HP checks not supported |
| Revavroom ex SFA 15 | sv06.5-015 | Accelerator Flash (atk0) / Shattering Speed (atk1) | Both require attaching Energy from deck to self during attack — energy-from-deck-to-self not supported |
| Hypno SFA 17 | sv06.5-017 | Daydream (atk0) | Effect depends on last Trainer card played — requires tracking last Trainer type played this turn |
| Duskull SFA 18 | sv06.5-018 | Come and Get You (atk0) | Switch in opponent's Benched Pokémon then deal damage — forced gust before damage calc not supported |
| Cresselia SFA 21 | sv06.5-021 | Crescent Purge (atk1) | Heal 30 from each of your Pokémon — mass heal across all in-play Pokémon not supported |
| Sylveon SFA 22 | sv06.5-022 | Mystical Return (atk0) | Flip coin; heads = return opponent's Benched Pokémon to deck — conditional bench bounce not supported |
| Bloodmoon Ursaluna SFA 25 | sv06.5-025 | Battle-Hardened (ability) | Once per turn: place 2 counters on self to reduce incoming damage by 20 — active once-per-turn counter ability not supported |
| Galvantula SFA 2 | sv06.5-002 | Compound Eyes (ability) | Your attacks do 50 more damage to opponent's Active — bench passive damage bonus not in _apply_damage |
| Dusclops SFA 19 | sv06.5-019 | Cursed Blast (ability) | Once per turn: place 5 damage counters on a Pokémon — once-per-turn targeted counter placement not implemented |
| Dusknoir SFA 20 | sv06.5-020 | Cursed Blast (ability) | Once per turn: place 13 damage counters on a Pokémon — same as Dusclops variant |
| Crobat SFA 29 | sv06.5-029 | Shadowy Envoy (ability) | Counts as using Janine's Secret Art when playing this card — card-play-as-trainer-effect not supported |
| Zubat SFA 27 | sv06.5-027 | Lead (atk0) | Damage = 30× (Golbat + Crobat in hand/bench) — count-specific-named-Pokémon-in-zones not supported |
| Inkay SFA 33 | sv06.5-033 | Mischievous Tentacles (atk0) | Switch one of your Benched Pokémon with your Active — self-bench-swap from attack not supported |
| Malamar SFA 34 | sv06.5-034 | Colluding Tentacles (atk0) | Effect requires Janine's Secret Art to be in play — trainer-in-play conditional not supported |
| Alakazam TWM 82 | sv06-082 | Strange Hacking (atk0) | Move damage counters from opponent's Active to Bench — player-choice counter redistribution not supported |
| Chimecho TWM 85 | sv06-085 | Homeward Chime (atk1) | Shuffle all Benched Pokémon and attached cards into deck — mass-bounce of own bench not supported |
| Floette TWM 87 | sv06-087 | Minor Errand-Running (atk0) | Search deck for Basic Energy card to hand — deck-search-energy-to-hand not supported |
| Florges TWM 88 | sv06-088 | Captivating Invitation (ability) | Flip coin; heads = force opponent to switch Active — coin-flip-forced-switch ability not supported |
| Sandygast TWM 91 | sv06-091 | Sand Attack (atk0) | Flip coin; if tails, opponent can't use attacks next turn — conditional opponent attack lock not supported |
| Palossand TWM 92 | sv06-092 | Sand Attack (atk0) | Same as Sandygast Sand Attack — conditional opponent attack lock not supported |
| Scream Tail ex TWM 94 | sv06-094 | Scream (atk0) | Only usable if going-second + first turn; bench-targeted — going-second first-turn condition not supported |
| Conkeldurr TWM 105 | sv06-105 | Gutsy Swing (atk1) | Ignore energy cost if Active has Special Condition — conditional energy-cost bypass not supported |
| Scolipede TWM 117 | sv06-117 | Dastardly Jab (atk0) | Reduce opponent's HP to 10 — direct HP-set not supported |
| Tatsugiri TWM 131 | sv06-131 | Attract Customers (ability) | Look at top 3 cards; choose 1 to hand — top-deck look-and-choose ability not supported |
| Farfetch'd TWM 132 | sv06-132 | Impromptu Carrier (ability) | On-play-to-bench: attach Item from discard — on-bench-play trigger attach not supported |
| Blissey ex TWM 134 | sv06-134 | Happy Switch (ability) | Move Basic Energy between your Pokémon — energy-move-between-Pokémon ability not supported |
| Dipplin TWM 127 | sv06-127 | Syrup Catcher (atk0) | Force switch opponent's Benched Pokémon + 70 damage — force-switch before damage not supported |
| Eevee TWM 135 | sv06-135 | Ascension (atk0) | Search deck for Eevee evolution and evolve — evolution-from-deck not supported |
| Shiftry TEF 5 | sv05-005 | Expelling Tornado (atk0) | Shuffle chosen opponent's Benched Pokémon into deck — selective bench bounce not supported |
| Grubbin TEF 18 | sv05-018 | Flock (atk0) | Search deck for up to 3 Grubbin and put on Bench — bench-filling search from deck not supported |
| Brambleghast TEF 21 | sv05-021 | Resilient Soul (ability) | HP = 60 + 50 per prize remaining — dynamic HP based on prizes not supported |
| Ponyta TEF 26 | sv05-026 | Charge Energy (atk0) | Search deck for Basic Energy card to hand — deck-search-energy-to-hand not supported |
| Magcargo TEF 29 | sv05-029 | Lava Zone (ability) | When this Pokémon retreats, opponent's Active is now Burned — on-retreat trigger not supported |
| Incineroar ex TEF 34 | sv05-034 | Hustle Play (ability) | This Pokémon can use attacks with 1 fewer Energy — dynamic attack-cost reduction not supported |
| Feraligatr TEF 41 | sv05-041 | Torrential Heart (ability) | Water Energy counts as 2 when paying retreat/attack costs — energy-doubling cost reduction not supported |
| Scovillain ex TEF 22 | sv05-022 | Two-Headed Crushing (atk1) | Discard random card from opponent's hand + top of deck — double-discard secondary effect not supported |
| Victini TEF 30 | sv05-030 | Flippity Flap (atk0) | Shuffle hand into deck + draw 6 — shuffle-hand-draw not supported |
| Wiglett TEF 47 | sv05-047 | Lucky Find (atk0) | Search deck for Item card to hand — item-search not supported |
| Pikachu TEF 51 | sv05-051 | Random Spark (atk0) | Deals 10 damage to 1 of opponent's Pokémon (ignoring W/R) — arbitrary bench-target damage choice not in engine |
| Raichu TEF 52 | sv05-052 | Collateral Bolts (atk0) | 50 damage to each Pokémon with damage counters (W/R for Active only) — multi-target selective bench hit not supported |
| Boltund TEF 59 | sv05-059 | Electrifying Dash (atk0) | Search deck for up to 2 Basic L Energy, attach to Benched Pokémon — deck search + energy-to-bench attachment not in engine |
| Wugtrio ex TEF 60 | sv05-060 | Tricolor Pump (atk0) | Discard up to 3 Energy from hand; 60 damage per discard to any Pokémon — hand-discard loop + arbitrary bench targeting not in engine |
| Iron Thorns TEF 62 | sv05-062 | Destructo-Press (atk0) | Reveal top 5 of deck; 70 damage per Future Pokémon found — deck-reveal mechanic + future detection non-functional |
| Mr. Mime TEF 63 | sv05-063 | Look-Alike Show (atk0) | Reveal opponent's hand; use a Supporter effect found there — hand-reveal + Supporter mimicry not supported |
| Bronzong TEF 69 | sv05-069 | Evolution Jammer (atk0) | Opponent can't play Pokémon from hand to evolve next turn — play-from-hand evolution validator hook not in engine |
| Reuniclus TEF 72 | sv05-072 | Summoning Gate (atk0) | Look at top 8 of deck, put any Pokémon found onto Bench — deck-peek + bench-add choice loop not in engine |
| Ribombee TEF 76 | sv05-076 | Plentiful Pollen (atk0) | If Defending Pokémon is KO'd during opponent's next turn, take 2 extra Prizes — deferred KO-triggered prize bonus not in engine |
| Scream Tail TEF 77 | sv05-077 | Supportive Singing (atk0) | Heal 100 from one of your Benched Ancient Pokémon — Ancient detection non-functional + benched-target heal choice not in engine |
| Flutter Mane TEF 78 | sv05-078 | Hex Hurl (atk0) | Place 2 damage counters on opponent's Benched Pokémon in any way — arbitrary bench counter distribution not in engine |
| Iron Valiant TEF 80 | sv05-080 | Calculation (atk0) | Look at top 4 of deck, reorder freely — deck-peek reorder not in engine |
| Iron Valiant TEF 80 | sv05-080 | Majestic Sword (atk1) | +220 damage if a Future Supporter was played this turn — Future Supporter tracking + future detection non-functional |
| Iron Crown ex TEF 81 | sv05-081 | Twin Shotels (atk0) | 50 damage to 2 of opponent's Pokémon, ignoring W/R and effects — dual-target attack not in engine |
| Lycanroc TEF 90 | sv05-090 | Turbo Edge (atk0) | Attach up to 2 Basic F Energy from discard to Benched Pokémon — energy-to-bench choice loop not in engine |
| Mudsdale TEF 92 | sv05-092 | Mud Stock (atk0) | Attach Basic F Energy from discard to each Benched Pokémon — mass energy-to-bench attachment not in engine |
| Great Tusk TEF 97 | sv05-097 | Land Collapse (atk0) | Discard top of opponent's deck; if Ancient Supporter played this turn, discard top 5 — opponent deck manipulation + Ancient Supporter tracking not in engine |
| Iron Boulder ex TEF 99 | sv05-099 | Repulsor Axe (atk0) | If damaged by an attack this turn, may put attacker on opponent's bench — on-damage conditional counter-effect choice not in engine |
| Gengar ex TEF 104 | sv05-104 | Tricky Steps (atk0) | Move Energy from opponent's Active to one of their Benched — opponent energy movement not in engine |
| Mightyena TEF 106 | sv05-106 | Kick Away (atk0) | Switch out opponent's Active Pokémon; opponent chooses replacement — forced gust/switch-out not in engine |
| Sableye TEF 107 | sv05-107 | Damage Collection (atk1) | Move any damage counters from opponent's Benched to opponent's Active — arbitrary counter redistribution not in engine |
| Scizor ex TEF 111 | sv05-111 | Cross Breaker (atk1) | Discard up to 2 M Energy; 120 damage per discarded — ChoiceRequest loop + conditional discard-to-damage multiplier not in engine |
| Mawile TEF 112 | sv05-112 | Invite and Strike (atk0) | Switch in one of opponent's Benched Pokémon, then attack it — forced switch + attack-against-new-active not supported |
| Metagross TEF 115 | sv05-115 | Meteor Mash (atk0) | Next turn this attack does 60 more damage — inter-turn attack-specific damage bonus not in state |
| Iron Treads TEF 118 | sv05-118 | Wheel Pass (atk0) | Move Energy from this Pokémon to a Benched Pokémon — energy movement active→bench not in engine |
| Koraidon TEF 119 | sv05-119 | Primordial Beatdown (atk0) | 30 damage × count of Ancient Pokémon in play — Ancient detection non-functional (card_subtype always '') |
| Miraidon TEF 121 | sv05-121 | Peak Acceleration (atk0) | Search deck for up to 2 Basic Energy, attach to Future Pokémon — deck search + future-filtered bench attach + future detection non-functional |
| Lickitung TEF 124 | sv05-124 | Tongue Pull (atk0) | Reveal opponent's hand, put up to 2 Basic Pokémon from it onto opponent's Bench — placing opponent's Pokémon on their bench not supported |
| Noctowl TEF 127 | sv05-127 | Talon Hunt (atk0) | Search deck for up to 2 chosen cards to hand — free deck-search ChoiceRequest not in engine |
| Delcatty TEF 131 | sv05-131 | Energy Blender (atk1) | Move any amount of Energy from any of your Pokémon to any others — arbitrary multi-source energy redistribution not in engine |
| Chatot TEF 132 | sv05-132 | A Cappella (atk0) | Search deck for up to 3 Basic Pokémon and bench them — bench-add from deck search not in engine |
| Unfezant TEF 135 | sv05-135 | Opposing Winds (atk0) | Return 2 Energy from opponent's Active to their hand — Energy return to opponent's hand not supported |
| Minccino TEF 136 | sv05-136 | Cleaning Up (atk1) | Discard up to 2 Pokémon Tools from opponent's Pokémon — Tool removal from opponent's Pokémon not supported |
| Inteleon MEP 2 | mep-002 | Bring Down (atk0) | Choose a Pokémon in play with least HP remaining and KO it — instant arbitrary-target KO not supported |
| Drifloon MEP 5 | mep-005 | Pull (atk0) | Flip coin; heads: switch one of opponent's Benched Pokémon to Active — coin-flip forced gust not in engine |
| Drifblim MEP 6 | mep-006 | Balloon Return (atk1) | Return this Pokémon and all attached cards to hand — returning Active + attachments to hand not supported |
| Mega Latias ex MEP 11 | mep-011 | Strafe (atk0) | After attack, may switch this Pokémon with a Benched Pokémon — post-attack self-switch choice not in engine |
| Walking Wake ex TEF 50 | sv05-050 | Azure Seas (ability) | Damage from this Pokémon's attacks ignores effects on opponent's Active — complex passive requires damage application hook |
| Flutter Mane TEF 78 | sv05-078 | Midnight Fluttering (ability) | Suppresses opponent's Active Pokémon's abilities while this is Active — global ability suppression not in engine |
| Iron Crown ex TEF 81 | sv05-081 | Cobalt Command (ability) | Future Pokémon deal +20 damage — future detection non-functional (card_subtype always '') |
| Relicanth TEF 84 | sv05-084 | Memory Dive (ability) | Evolved Pokémon can use attacks from previous evolutions — prior-form attack-access not in engine |
| Drilbur TEF 85 | sv05-085 | Dig Dig Dig (ability) | On bench-play: search deck for up to 3 Basic F Energy and discard — on-play trigger hook not in engine |
| Gengar ex TEF 104 | sv05-104 | Gnawing Curse (ability) | Place 2 damage counters on any Pokémon opponent attaches Energy to from hand — on-energy-attach trigger not in engine |
| Farigiraf ex TEF 108 | sv05-108 | Armor Tail (ability) | Prevent all damage from Basic Pokémon ex attacks — conditional damage prevention not in damage pipeline |
| Metang TEF 114 | sv05-114 | Metal Maker (ability) | Once per turn, look at top 4 and attach any Basic M Energy found — deck-peek + selective attach not in engine |
| Iron Treads TEF 118 | sv05-118 | Dual Core (ability) | Pokémon is F+M type when Future Booster Energy Capsule attached — tool-dependent dual typing not supported |
| Pidove TEF 133 | sv05-133 | Emergency Evolution (ability) | Evolve from deck when HP ≤ 30 — conditional HP-threshold evolution not in engine |
| Iron Jugulis TEF 139 | sv05-139 | Automated Combat (ability) | On being damaged, counter-attack with own attacks — on-damage counter-attack trigger not in engine |
| Meganium MEP 1 | mep-001 | Wild Growth (ability) | Each Basic G Energy counts as 2 — energy-value doubling fundamentally overrides cost system |
| Alakazam MEP 3 | mep-003 | Psychic Draw (ability) | On evolve: discard a card from hand to draw cards — on-evolve draw hook not in engine |
| Lunatone MEP 4 | mep-004 | Lunar Cycle (ability) | If Solrock in play: discard Basic F Energy to attach Basic P Energy from deck — conditional cross-energy deck attach not in engine |
| Psyduck MEP 7 | mep-007 | Damp (ability) | Suppresses all abilities requiring KO while Pokémon is in play — global KO-trigger ability suppression not in engine |
| Golduck MEP 8 | mep-008 | Damp (ability) | Suppresses all abilities requiring KO while Pokémon is in play — global KO-trigger ability suppression not in engine |
| Alakazam MEP 9 | mep-009 | Psychic Draw (ability) | On evolve: discard a card from hand to draw cards — on-evolve draw hook not in engine |
| Mega Lucario ex MEP 12 | mep-012 | Aura Jab (atk0) | Attach up to 3 Basic {F} Energy from discard to Benched Pokémon in any way — energy-from-discard-to-bench choice loop not in engine |
| Ceruledge MEP 14 | mep-014 | Infernal Slash (atk0) | Discard 4 Basic {R} from hand; if you can't, attack does nothing — conditional 4-energy hand-discard with failure condition not in engine |
| Whimsicott MEP 19 | mep-019 | Healing Fluff (atk0) | Heal all damage from 1 of your Benched Pokémon — targeted full bench-heal with choice not in engine |
| Whimsicott MEP 19 | mep-019 | U-turn (atk1) | Switch this Pokémon with 1 of your Benched Pokémon after attack — post-attack self-switch choice not in engine |
| Meloetta MEP 26 | mep-026 | Soothing Melody (atk0) | Heal 120 from 1 of your Benched {P} Pokémon — type-filtered bench-heal with choice not in engine |
| Mega Kangaskhan ex MEP 25 | mep-025 | Run Errand (ability) | Once per turn draw 2 cards when Active — active once-per-turn draw ability requires in-turn hook not implemented |
| Teal Mask Ogerpon PR-SV 123 | svp-123 | Mountain Stroll (atk0) | Search deck for up to 2 Basic Energy to hand — deck-search-energy-to-hand not in engine |
| Raging Bolt ex PR-SV 145 | svp-145 | Bellowing Thunder (atk1) | Discard any amount of Basic Energy from own Pokémon; +70 damage per discarded — multi-source energy-discard loop + variable damage not in engine |
| Wooper PR-SV 155 | svp-155 | Scoop Water (atk0) | Shuffle up to 3 Basic {W} Energy from discard into deck — discard-to-deck energy shuffle not in engine |
| Quagsire PR-SV 156 | svp-156 | Drenched Headbutt (atk1) | Discard top 3 of deck; +80 damage per Energy discarded — deck-top discard + energy-count damage bonus not in engine |
| Pachirisu PR-SV 158 | svp-158 | Crackling Charge (atk0) | Flip 3 coins; attach Basic {L} Energy from discard to bench equal to heads — coin-flip-to-energy-attach loop not in engine |
| Iron Leaves ex PR-SV 128 | svp-128 | Rapid Vernier (ability) | On-play-to-bench: switch to Active + move any Energy from other Pokémon to self — on-bench-play promote + energy-redistribution hook not in engine |
| Sylveon PR-SV 172 | svp-172 | Mystical Return (atk0) | Flip coin; heads: shuffle 1 opponent's Benched Pokémon + attached cards into deck — coin-flip bench bounce not in engine |
| Chien-Pao PR-SV 152 | svp-152 | Snow Sink (ability) | On-play-to-bench: discard a Stadium in play — on-bench-play Stadium-discard hook not in engine |
| Kyogre ex PR-SV 178 | svp-178 | Winding Waves (atk0) | Opponent switches their Active to Bench; opponent chooses new Active — opponent-initiated forced switch not in engine |
| Yanmega PR-SV 187 | svp-187 | Gyro Shockwave (atk0) | Switch this Pokémon with 1 of your Benched Pokémon after attack — post-attack self-switch choice not in engine |
| Scrafty PR-SV 188 | svp-188 | Nab 'n' Dash (atk0) | Search deck for cards up to count of own Benched Pokémon and put to hand — bench-count-capped free deck search not in engine |
| Zarude PR-SV 199 | svp-199 | Pluck off (atk0) | Search deck for up to 3 Basic Grass Energy to hand — deck-search-energy-to-hand not in engine |
| Team Rocket's Wobbuffet PR-SV 203 | svp-203 | Rocket Mirror (atk0) | Move all damage counters from 1 Benched TR Pokémon to opponent's Active — cross-Pokémon counter transfer not in engine |
| Team Rocket's Mewtwo ex PR-SV 205 | svp-205 | Erasure Ball (atk0) | Discard up to 2 Energy from own Benched Pokémon; +60 per discarded — multi-Pokémon discard loop + conditional damage not in engine |
| Iono's Kilowattrel PR-SV 182 | svp-182 | Flashing Draw (ability) | Discard Basic {L} Energy from this Pokémon; draw until 6 in hand — active discard-for-draw ability with energy cost not implemented |
| Tornadus PR-SV 210 | svp-210 | Hurricane (atk1) | Move a Basic Energy from this Pokémon to 1 of your Benched Pokémon — energy movement active→bench not in engine |
| Reuniclus PR-SV 212 | svp-212 | Cellular Ascension (atk0) | Evolve each Benched Pokémon from deck simultaneously — mass in-battle bench evolution not supported |
| TR Persian ex PR-SV 218 | svp-218 | Haughty Order (atk0) | Copy an attack from a Pokémon in the opponent's top 10 deck cards — deck-scanning attack execution not currently supported |
| Energy Swatter POR 73 | me03-073 | (trainer effect) | Reveal opponent's hand; attach Basic Energy only to Pokémon whose type appears in opponent's hand — requires hand-reveal + type-matching energy attachment not supported |
| Lt. Surge's Bargain MEG 120 | me01-120 | (trainer effect) | Opponent chooses to discard 0, 1, or 2 of their own Pokémon — opponent-interactive decision with branching discard not supported |
| Wally's Compassion MEG 132 | me01-132 | (trainer effect) | Return Pokémon Tool + Energy to hand; then evolve attached Mega Evolution ex — Mega Evo detection and mid-battle multi-step evolution sequence not supported |
| Team Rocket's Bother-Bot DRI 172 | sv10-172 | (trainer effect) | Plays as face-up Prize card mechanic — prize zone manipulation not supported in engine |
| Levincia JTG 150 | sv09-150 | (trainer effect) | Attach Basic Energy to any of your Pokémon up to 3 times per turn — per-turn multi-energy counter with reset not supported |
| Redeemable Ticket JTG 156 | sv09-156 | (trainer effect) | Reveal top prizes until you find a Supporter; swap it into your hand — prize zone search/swap not supported |
| Amarys PRE 93 | sv08.5-093 | (trainer effect) | Move any number of Energy from your Benched Pokémon to another at end of turn — end-of-turn effect trigger not supported |
| Ogre's Mask PRE 118 | sv08.5-118 | (trainer effect) | Swap the Pokémon this Tool is attached to with one of your Benched Pokémon — mid-turn bench↔active swap via Tool not supported |
| Jasmine's Gaze SSP 178 | sv08-178 | (trainer effect) | Your Active takes 30 less damage from attacks during opponent's next turn — cross-turn damage reduction requires persistent state flag not currently in engine |
| TM: Fluorite SSP 188 | sv08-188 | (trainer effect) | Heal 30 from all your Tera Pokémon between turns — end-of-turn Tera-wide heal not supported |
| Tyme SSP 190 | sv08-190 | (trainer effect) | Opponent calls heads or tails; if wrong, discard 2 from hand — opponent-interactive guessing game not supported |
| Powerglass SFA 63 | sv06.5-063 | (trainer effect) | Attached Tool: at the end of your turn, deal 60 to opponent's Active — end-of-turn damage from Tool not supported |
| Community Center TWM 146 | sv06-146 | (trainer effect) | Caretaker synergy — when Community Center is active and Caretaker draws cards, Caretaker returns to deck instead of being discarded |
| Handheld Fan TWM 150 | sv06-150 | (trainer effect) | Discard a card from hand to heal 90 from Active — discard-for-heal supporter effect not modelled |
| Lucian TWM 157 | sv06-157 | (trainer effect) | Draw 3; attach a Basic Energy from hand to any Pokémon in play — combined draw+energy-attach in single supporter not supported |
| Lucky Helmet TWM 158 | sv06-158 | (trainer effect) | When the Pokémon this Tool is attached to is damaged by opponent's attack, draw 2 — on-damage trigger hook via Tool not in engine |
| Full Metal Lab TEF 148 | sv05-148 | (trainer effect) | Pokémon Tools attached to Pokémon in play can't be discarded by opponent's effects — per-tool protection from removal not supported |
| Hand Trimmer TEF 150 | sv05-150 | (trainer effect) | Attached Tool: this Pokémon's attacks do +30 for each card in opponent's hand ≥ 8 — conditional per-hand-count damage bonus not in engine |
| Heavy Baton TEF 151 | sv05-151 | (trainer effect) | When the Pokémon this Tool is attached to retreats, attach a Basic Energy from discard to the retreating Pokémon — on-retreat trigger via Tool not in engine |
| Perilous Jungle TEF 156 | sv05-156 | (trainer effect) | Stadium: once per turn, when an opponent's Pokémon is damaged by your Pokémon's attacks, place 2 damage counters on that Pokémon — end-of-damage-event trigger per stadium not supported |
| Celebratory Fanfare MEP 28 | mep-028 | (trainer effect) | Stadium: when a player takes their last Prize card, that player draws 3 cards — prize-zone trigger hook not in engine |
| Paradise Resort PR-SV 150 | svp-150 | (trainer effect) | Stadium: once per turn, heal 30 from 1 of your Pokémon without an Ability — per-turn optional heal via stadium not supported |
| Paradise Resort PR-SV 224 | svp-224 | (trainer effect) | Same as Paradise Resort (alt art) — per-turn optional heal via stadium not supported |
| Spiky Energy JTG 159 | sv09-159 | (energy effect) | When this Energy is attached to a Pokémon, your opponent's Active Pokémon takes 20 damage — on-attach damage trigger not currently supported |
| Boomerang Energy TWM 166 | sv06-166 | (energy effect) | When this Special Energy is discarded from a Pokémon, return it to hand — on-discard-from-play energy recycle not supported |
