"""Curated persona libraries and non-repeating draws."""
import json
from pathlib import Path
import random
import re
from core import CHARACTERS


class Library:
    def __init__(self, path, rng=random):
        self.data = json.loads(Path(path).read_text())
        for filename in ('trogdor.json', 'wizarding.json'):
            special = Path(path).with_name(filename)
            if special.exists():
                extra = json.loads(special.read_text())
                for kind in ('jokes', 'stories'):
                    self.data[kind].extend(extra[kind])
        self.rng = rng
        self.bags = {}
        self.last = {}
        for kind, limit in (('jokes', 35), ('stories', 65)):
            seen = set()
            for item in self.data[kind]:
                if (item['character'] not in CHARACTERS
                        or not 0 < len(item['text'].split()) <= limit or item['id'] in seen):
                    raise ValueError('Invalid entertainment library')
                seen.add(item['id'])

    def draw(self, kind, character):
        key = (kind, character)
        if not self.bags.get(key):
            pool = [i for i in self.data['jokes' if kind == 'joke' else 'stories']
                    if i['character'] == character]
            if not pool:
                raise ValueError('No material for this character')
            self.bags[key] = self.rng.sample(pool, len(pool))
            if len(pool) > 1 and self.bags[key][-1]['id'] == self.last.get(key):
                self.bags[key][0], self.bags[key][-1] = self.bags[key][-1], self.bags[key][0]
        item = self.bags[key].pop()
        self.last[key] = item['id']
        return item


def story_chunks(text):
    chunks = []
    current = ''
    for sentence in re.split(r'(?<=[.!?])\s+', text):
        if current and len((current + ' ' + sentence).split()) > 30:
            chunks.append(current)
            current = ''
        if len(sentence.split()) > 30:
            raise ValueError('Story sentence too long')
        current = (current + ' ' + sentence).strip()
    if current:
        chunks.append(current)
    return chunks
