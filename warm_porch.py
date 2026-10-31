"""Render fixed porch lines before visitors arrive; never plays audio."""
import sys
import time
from types import SimpleNamespace

from pumpkin import ROOT, Speech
from core import CHARACTERS, BOO_REPLIES
from controls import CONTROL_LINES
from entertainment import Library
from games import GAMES
from porch_bits import ALL_SCENES, FAREWELLS, HECKLES, INSIDE_ACTOR, interactive_lines, LURES, MORE_REPLIES, REACTIONS, RING_FALLBACK, QUICK_REPLIES, scene_lines
from sorting_ceremonies import AUTHORED_SORTING


def fixed_lines():
    lines = {('sorting_hat', line) for line in AUTHORED_SORTING}
    for actor, details in CHARACTERS.items():
        lines.update((actor, line) for line in details['greetings'] + [details['fallback']]
                     + BOO_REPLIES[actor] + list(CONTROL_LINES))
        lines.add((actor, RING_FALLBACK))
    for replies in QUICK_REPLIES.values():
        lines.update(replies.items())
    for _, replies in MORE_REPLIES:
        lines.update(replies.items())
    for character, rows in REACTIONS.items():
        lines.update((character, line) for line in rows)
    lines.update((INSIDE_ACTOR, line) for line in HECKLES)
    lines.update(interactive_lines())
    lines.update((item['character'], item['text']) for item in Library(ROOT / 'entertainment.json').data['jokes'])
    for scene in GAMES.values():
        if scene.get('cast'):
            lines.update((actor.partition(':')[0], line) for actor, line in zip(scene['cast'], scene['lines'])
                         if not actor.startswith('fx'))
        else:
            lines.update((actor, line) for actor in CHARACTERS for line in scene['lines'])
    for character, rows in list(FAREWELLS.items()) + list(LURES.items()):
        lines.update((character, line) for line in rows)
    for scene in ALL_SCENES:
        lines.update(scene_lines(scene))
    return lines


def main():
    import os
    os.environ.setdefault('TTS_PRIORITY', 'low')  # Live visitor lines go first at the voice server.
    speech = Speech(SimpleNamespace(character='patch', level=None))
    lines = sorted(fixed_lines())
    only = set(sys.argv[1:])
    if only:
        lines = [row for row in lines if row[0] in only]
    failed = []
    for index, (character, text) in enumerate(lines):
        for attempt in range(2):
            try:
                if character == 'doorbell':
                    speech.render_doorbell(text)
                else:
                    speech.render(character, text)
                break
            except Exception as error:  # Keep going; report every failure at the end.
                if attempt:
                    failed.append((character, text, repr(error)))
                else:
                    time.sleep(3)  # The voice server returns 503 while busy; give it a moment.
        print(f'Rendered {index + 1}/{len(lines)}: {character}', flush=True)
    for row in failed:
        print('FAILED', *row, flush=True)
    # Stories are told in chunks; render them now so the first telling starts at once.
    for item in Library(ROOT / 'entertainment.json').data.get('stories', []):
        if not only or item['character'] in only:
            try:
                speech.render_story(item['character'], item['text'])
                print('Story ready:', item.get('title', ''), flush=True)
            except Exception as error:
                print('FAILED story', item.get('title', ''), repr(error), flush=True)
    # Pre-join cast routines so the first performance has no render pause.
    always = lambda: True
    for key, scene in GAMES.items():
        if scene.get('cast') and (not only or only & {a.partition(':')[0] for a in scene['cast']}):
            speech.render_routine(key, always)
            print('Routine ready:', key, flush=True)


if __name__ == '__main__':
    main()
