# Trogdor porch content pack

`../trogdor.json` contains 12 factual Q&As, six newly written jokes, two newly written stories, and an empty quote list. Trogdor, Strong Bad, and Homestar Runner are existing Homestar Runner characters. The porch scenes are invented fan content, not events from the cartoons.

## Delivery handoff

The requested reference is **Strong Bad's gravelly, nasal speaking delivery during the drawing lesson in dragon**, not the heavy metal singing. Use clipped sentences, smug comic authority, little pauses before absurd conclusions, and friendly candy-host energy. Treat these as performance direction; this content pack makes no voice cloning or fidelity claims. Implementation and voice work belong to the parent.

Recurring visual/comic cues: the consummate V, one beefy arm, an absurd doodle dragon, cardboard danger, and candy. Any porch burnination is explicitly imaginary. The jokes target the dragon's pomposity and props. There are no real fire instructions or cruelty.

## Verified sources

Checked on 2026-10-23 using web retrieval and Python `requests`, without installing dependencies or saving source media.

| JSON fact positions | Official evidence |
| --- | --- |
| 1–4 | [Sbemails index](https://homestarrunner.com/sbemails), entry 58: episode number, title, year, drawing instructor, and dragon name. |
| 5–7 | [Sbemails index](https://homestarrunner.com/sbemails), entries 57, 53, and 200: Stinkoman, Teen Girl Squad, and Homestar's email show. |
| 8–9 | [Toons index](https://homestarrunner.com/toons), entries Trogdor Con '97 and Happy 20th Trogday!: booth companions and birthday/year. The convention title's '97 is not used as a release date. |
| 10–12 | [Official board game site](https://trogdorboardgame.homestarrunner.com/): cooperative play, player count, and the named cartoon participants in its how-to video. |

All answers paraphrase official descriptions. Fact 3's second sentence is a comic aside, not an additional documented claim. Source URLs point to the text actually checked, rather than implying inaccessible dialogue was verified.

The [official dragon episode page](https://homestarrunner.com/sbemails/58-dragon) returned HTTP 200 and embeds the episode's Flash media. The [original official SWF](https://old.homestarrunner.com/sbemail58.swf) also returned HTTP 200 (637,145 bytes). File availability was verified; the cartoon's audio and complete animation were not played or transcribed during this task.

## Uncertainty and limits

- [HRWiki's dragon page](https://hrwiki.org/wiki/dragon) could not be checked: HTTPS connections to both bare and `www` hosts were refused; the HTTP request timed out. No fact relies on an unread HRWiki page or search snippet.
- Exact episode dialogue, drawing-step wording, and the precise original release day were not independently verified and are omitted from the factual Q&As. The requested drawing motifs are creative cues, not newly verified lore claims.
- The listed 2003 date is the official index's year. No stronger first-appearance or day/month claim is made.
- The official board game page names the how-to video's participants; the video itself was not watched. Its player count is trivia, not a recommendation about age suitability.
- `quotes` is deliberately empty: zero actual dialogue excerpts, zero quoted-source words or characters in that field, and no song lyrics or transcripts. Proper names, titles, and brief requested character motifs appear in the pack.

## Validation

Validate with Python's standard library: parse JSON; require exactly the four top-level arrays and the requested entry keys; check 12/6/2 counts, unique joke/story IDs, `character` equal to `trogdor`, and HTTPS source URLs. Count whitespace-separated words: each joke must have at most 30; each story at most 60; each story sentence at most 30. Quote limits are at most three entries, 30 total words, and 180 total characters. No app or voice integration is included.
