# Harry Potter porch content handoff

`../wizarding.json` contains eight elementary factual Q&As, four original jokes per character, and two original stories per character. The only top-level keys are `facts`, `jokes`, and `stories`. These invented porch scenes are fan content, not canonical events or film transcripts. No source dialogue, song lyrics, or quotations are included.

## Selection and cast handoff

The parent should expose **Sorting Hat** (`sorting_hat`) and **Dobby** (`dobby`) as separate, explicitly selectable characters. Both should also occasionally join the normal Patch/Boo/Nibbles rotation as guests. Keep the normal cast predominant; no frequency is prescribed by this content pack. Trogdor remains a separate special character. These are integration requirements for the parent, not implemented selection or scheduling behavior.

The Hat may offer warm, cheeky costume judgments based on visible costume details. Use a matching line only when its detail is actually visible; the cape joke is conditional on a cape with pockets. Otherwise choose a general joke. Praise props, craft, or playful ideas; never rank children's worth, mock bodies, or guess sensitive attributes. If a detail is unclear, skip it.

## Fictional sorting game

Introduce each live sorting interaction as a pretend game. Use only visible costume details or an answer to one optional playful question. A guest can skip, pick a house, or change the suggestion freely. No answer is required for participation or treats. A costume motif suggests a story theme, never a real personality, psychological assessment, identity, ability, destiny, or moral judgment. Do not claim to read a visitor's mind.

Suggested original opening: “Fancy a pretend Hogwarts house game? Pick a house, let your costume inspire a suggestion, or simply enjoy a joke.”

Optional original question: “For a pretend adventure, would you explore bravely, investigate a puzzle, help the team share fairly, or invent a clever plan?” Map the chosen activity to a temporary fictional theme, using the values below. Accept any preference without correction. With neither a usable costume detail nor a voluntary answer, offer a joke instead of assigning a house.

| House | Values to celebrate | Playful activity theme |
| --- | --- | --- |
| Gryffindor | Courage | Trying a brave adventure |
| Ravenclaw | Learning and curiosity | Exploring a question or puzzle |
| Hufflepuff | Fairness and loyalty | Sharing fairly and supporting the team |
| Slytherin | Resourcefulness and ambition | Inventing a clever plan and pursuing a goal |

All four houses are welcome and equally worthy. Slytherin is never an evil-house label. Every guest can enjoy every value. Keep official lore about the fictional Hat separate from what this porch game can do.

## Performance direction

**Sorting Hat:** dry, gravelly, wise old British bass; measured ceremony with a wry pause before the joke. Let the Hat's own pomposity and impractical headwear carry the comedy. Warmth comes through even when the verdict sounds grand. Never use cruelty or an intimidating verdict.

**Dobby:** bright, higher-register, breathy and lightly creaky English; earnest little bursts with clear consonants. Use occasional slightly tangled third-person references, as in the supplied text, while keeping every line intelligible. Enthusiastic practical magic, socks, gratitude, and kindness are the recurring themes. Avoid exaggerated broken-English caricature, offensive stereotypes, self-punishment, or demeaning servility.

Voice references, recordings, clones, and implementation belong to the parent. This handoff supplies performance direction only and makes no voice-fidelity claim.

Read one story per turn. Each is under 60 words and each sentence under 30 words; all depict harmless, fictional porch moments with no actual threats or fire. Target roughly 35–50 seconds including pauses, and cap the complete spoken turn at one minute. Rendered timing still needs verification by the parent because voice speed and pauses vary.

## Official source verification

Verified on 2026-10-23 using Python `requests.get` and readable HTML text extraction. Every link below returned HTTP 200 at its listed URL. Content was inspected for the stated claim; successful status alone was not treated as evidence. Answers are short paraphrases.

| JSON fact positions | Verified official source and support |
| --- | --- |
| 1–2 | [Sorting Hat encyclopedia entry](https://www.harrypotter.com/fact-file/objects/the-sorting-hat): sorts new Hogwarts students into four named houses; originally belonged to Godric Gryffindor, one of the founders. |
| 3–4 | [Hogwarts house meanings](https://www.harrypotter.com/features/hogwarts-house-meanings): Gryffindor courage/bravery; Ravenclaw learning, wisdom, and wit. |
| 5 | [Hufflepuff house page](https://www.harrypotter.com/house/hufflepuff): justice and loyalty, paraphrased for children as fairness and loyalty. No verse is reproduced. |
| 6 | [Famous Slytherins through the ages](https://www.harrypotter.com/features/famous-slytherins-through-the-ages): the founder prized resourcefulness and ambition. The answer's explanation of those words is an elementary gloss. |
| 7–8 | [Dobby encyclopedia entry](https://www.harrypotter.com/fact-file/characters-and-pets/dobby): identifies Dobby as a house-elf and lists collecting socks among his hobbies. |

Additional verified support: the [Ravenclaw house page](https://www.harrypotter.com/house/ravenclaw) associates the house with learning; [Why you should fall in love with a Ravenclaw](https://www.harrypotter.com/features/why-you-should-fall-in-love-with-a-ravenclaw) explicitly discusses intellectual curiosity. Only that lore association informs this handoff; its relationship framing is not used in the porch content. The [house meanings guide](https://www.harrypotter.com/features/hogwarts-house-meanings) also rejects treating all Slytherins as bad.

## Uncertainties and validation

No unresolved factual uncertainty was identified in the eight included answers against the retrieved official text. These are claims within Harry Potter fiction. The porch adventures, jokes, guest interactions, and optional sorting question are newly invented and carry no canon claim. House values are welcoming themes, not exclusive traits or evidence about real visitors.

Source availability was checked on the date above and can change. Actual voice duration and character selection/rotation remain parent integration checks; this content-only task cannot verify them.

Validation checks: parse the JSON; require exactly 8 facts, 8 jokes, and 4 stories; require the specified field sets and HTTPS official source URLs; require unique IDs and exactly 4 jokes/2 stories for each of `sorting_hat` and `dobby`; count whitespace-separated words (jokes at most 30, stories at most 60, each story sentence at most 30). Only `wizarding.json` and `docs/HARRY_POTTER.md` are deliverables.
