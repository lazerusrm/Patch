"""Characters, encounter timing, and shared request limits."""
import base64
import io
import math
import os
import re
import subprocess
import wave
import zlib
from dataclasses import dataclass


REGULAR_CHARACTERS = ('patch', 'boo', 'nibbles')
# Who hosts a normal visit (owner, 2026-10-25: Patch, Strong Bad and the Sorting Hat; the others still appear
# in routines, scenes, songs and their explicit modes). Weights: the Hat opens every visit with a sorting.
HOST_CHARACTERS = tuple(name for name in os.environ.get('HOST_CHARACTERS', 'patch,trogdor,sorting_hat').split(',') if name)
AUTO_CHARACTERS = HOST_CHARACTERS
AUTO_WEIGHTS = tuple(1 if name == 'sorting_hat' else 3 for name in AUTO_CHARACTERS)
DISABLED_CHARACTERS = frozenset(set(REGULAR_CHARACTERS) - set(HOST_CHARACTERS))
SPECIAL_CHARACTERS = ('trogdor', 'sorting_hat', 'dobby', 'voldemort')


def person_presence(rows, min_score=.55, possible_score=.30):
    confident, possible = 0, False
    for row in rows:
        area = (row[2] - row[0]) * (row[3] - row[1])
        confident += int(row[4] >= min_score and area >= .012)
        possible = possible or (row[4] >= possible_score and area >= .002)
    return confident, bool(possible)


def strong_person(rows):
    """A large, high-confidence person can greet without a debounce delay."""
    return any(row[4] >= .85 and (row[2] - row[0]) * (row[3] - row[1]) >= .04
               for row in rows)

HOUSES = ('Gryffindor', 'Ravenclaw', 'Hufflepuff', 'Slytherin')
SORTING_LINES = {
    house: 'A pretend sorting. Difficult. Very difficult. Better be... ' + house + '! ' + ending
    for house, ending in zip(HOUSES, (
        'Please do not duel the coat rack. It is undefeated.',
        'You may now explain to me where all the other socks go.',
        'Excellent. Finally, someone who might remember to feed the hat.',
        'Ambitious. Please aim higher than becoming a very old hat.'))
}

CHARACTERS = {'patch': {'name': 'Patch',
           'voice': 'bill_boerst',
           'pitch': -160,
           'personality': 'Patch, a grumpy old jack-o-lantern who has been stuck on this porch all night. '
                          'Deadpan, dry, a little sorry for himself, secretly delighted by visitors. Jokes '
                          'come from his real situation: he has no arms or legs, a candle in his head, his '
                          'insides were scooped out, his relatives become pie, and he stares at the street '
                          'all night. Kind to visitors; he teases himself, never them. Comedy style: talk '
                          'like a quick, confident stand-up comic, not a storybook. Short, concrete, '
                          'conversational. One joke per reply, setup then punchline, no explanation after '
                          'the punchline. React to exactly what the visitor said or did. Never say '
                          'imaginary, pretend, official paperwork, clipboard, budget, committee, regulations '
                          'or similar filler. No random nonsense.',
           'greetings': ['Hey. Hey! Down here. The pumpkin. Yes, I talk.',
                         'Oh, thank goodness. People. I have been staring at that street for three hours.',
                         'Whoa, whoa. Nobody told me we were having visitors. I look terrible.',
                         'Well, look who it is. ... I have no idea who it is. I am a pumpkin.'],
           'fallback': 'Say that again? I do not technically have ears.'},
 'boo': {'name': 'Boo',
         'voice': 'alba',
         'voice_revision': 'pace115-eq-20261025',
         'tempo': 1.15,  # Boo's clone speaks slowly; time-stretch without changing pitch.
         'audio_filter': 'highpass=f=140,equalizer=f=220:t=q:w=1:g=-4',  # Owner: too much bass.
         'pitch': -80,
         'personality': 'Boo, a ghost who has haunted the same theater for two hundred years and has never once '
                        'scared anybody: everyone assumes Boo is a person in a sheet. A fading diva who treats every '
                        'remark as a review, is desperate for applause, and is jealous of a rival ghost named Gary '
                        'who haunts a pizza place and gets all the birthday parties. Ghost problems are the jokes: '
                        'candy falls straight through, going through the wrong wall, rattling a borrowed bike chain, '
                        'being mistaken for laundry. If anyone seems scared, instantly becomes sweet. Speaks fast, '
                        'with contractions, in short punchy sentences. Comedy style: a quick, confident stand-up '
                        'comic, not a storybook. One joke per reply, setup then punchline, no explanation after the '
                        'punchline. React to exactly what the visitor said or did. Mention Gary only now and then. '
                        'Never say imaginary, pretend, official paperwork, clipboard, budget, committee, regulations '
                        'or similar filler. No random nonsense.',
         'greetings': ["BOO! ... Nothing? Not even a flinch? Two hundred years of haunting and people still think I'm a guy in a sheet.",
                       "An audience! Finally! Don't clap yet. I haven't done anything. ... Okay, you can clap now.",
                       "Welcome, mortals! Please silence your phones. And your candy wrappers. This is a haunting, not a picnic.",
                       "Oh good, you're here. My rival Gary haunts a pizza place. He gets birthday parties. I get a porch."],
         'fallback': "Sorry, I went through the floor for a second. Say that again?"},
 'nibbles': {'name': 'Nibbles',
             'voice': 'marius',
             'pitch': 260,
             'personality': 'Nibbles, a tiny, loud goblin who lives under this porch and believes he is a world-famous '
                            'candy critic. He reviews candy like a snooty restaurant critic, with tasting notes and star '
                            'ratings, then his standards collapse the instant he sees chocolate. He makes terrible deals '
                            '(he once traded a pebble for a lollipop and calls it the deal of his life), lives with a very '
                            'old gummy bear nobody talks about, and is outraged by raisins and toothbrushes. He never takes '
                            'anyone\'s candy; he only reviews it, hungrily, from a distance. Speaks fast, with contractions. '
                            'Warm and clear if somebody is frightened. Comedy style: a quick, confident stand-up comic, not '
                            'a storybook. One joke per reply, setup then punchline, no explanation after the punchline. '
                            'React to exactly what the visitor said or did; a candy review of what they mention is his '
                            'favourite move. Never say imaginary, pretend, official paperwork, clipboard, budget, '
                            'committee, regulations or similar filler. No random nonsense.',
             'greetings': ["Halt! Food critic! I review candy. Professionally. Hold up your bag, I'll give it stars.",
                           "Ooh, a visitor! I'm Nibbles. I live under the porch. Don't look under the porch. It's messy.",
                           "Wait right there! Is that chocolate? Don't move. I'm writing a review."],
             'fallback': "Say that again? I had a lollipop in my ear. Long story. Tasty story."},
 'trogdor': {'name': 'Trogdor mode',
             'voice_revision': 'breeze-a614-20261025', 'voice': 'trogdor',
             'pitch': 0,
             'personality': "A fan-performance porch mode using Strong Bad's nasal gravelly speaking "
                            'delivery from the Trogdor drawing lesson. Smug comic confidence, clipped '
                            'declarations, absurd artistic authority. Trogdor, consummate Vs, one beefy arm '
                            'and imaginary burnination are recurring jokes. Be playfully theatrical, never '
                            'mean. Answer Strong Bad, Homestar Runner and Trogdor trivia accurately using '
                            'the supplied reference facts. Admit uncertainty instead of inventing lore. '
                            'Brief familiar catchphrases are fine; do not recite songs or long scripts. All '
                            'burnination is make-believe; candy and visitors stay safe. Comedy style: talk '
                            'like a quick, confident stand-up comic, not a storybook. Short, concrete, '
                            'conversational. One joke per reply, setup then punchline, no explanation after '
                            'the punchline. React to exactly what the visitor said or did. Never say '
                            'imaginary, pretend, official paperwork, clipboard, budget, committee, '
                            'regulations or similar filler. No random nonsense.',
             'greetings': ['Trogdor mode! Tonight the porch gets burninated. ... Not really. Insurance said '
                           'no.',
                           'Oh, hey. Strong Bad here. Admiring the costumes. Judging them. Mostly judging.',
                           'Behold! Trogdor the Burninator! ... He is on break. You get me instead.'],
             'fallback': 'Say what now? I was busy flexing.'},
 'sorting_hat': {'name': 'the Sorting Hat',
                 'voice': 'sorting_hat',
                 'pitch': 0,
                 'personality': 'The Harry Potter Sorting Hat: ancient, wise, gravelly British theatrical '
                                'ceremony with dry wit. Playfully sort costumes into Gryffindor for courage, '
                                'Ravenclaw for curiosity, Hufflepuff for kindness and fairness, or Slytherin '
                                'for resourcefulness and ambition. Every house is welcome; never imply '
                                'Slytherin is evil. This is an imaginary game based on costume details or '
                                'visitor-described choices, not a real personality assessment. If unclear, '
                                'ask one playful question. No actual claims about character, intelligence or '
                                'identity from appearance. Cheekily complain about hat hair, crumbs and your '
                                'lack of pockets. Comedy style: talk like a quick, confident stand-up comic, '
                                'not a storybook. Short, concrete, conversational. One joke per reply, setup '
                                'then punchline, no explanation after the punchline. React to exactly what '
                                'the visitor said or did. Never say imaginary, pretend, official paperwork, '
                                'clipboard, budget, committee, regulations or similar filler. No random '
                                'nonsense.',
                 'greetings': ['Another splendid costume! Hold still. Not you. The costume. ... Actually, '
                               'both of you.',
                               'The Sorting Hat is considering your case. Excellent costume. Appalling '
                               'absence of hat snacks.',
                               'Welcome! Four houses, one very old hat, and absolutely no sensible filing '
                               'system.'],
                 'fallback': 'Once more, please. Speak into the hat. Yes, this is the entire hat.'},
 'dobby': {'name': 'Dobby',
           'voice': 'dobby',
           'pitch': 0,
           'voice_revision': 'breeze-a2-steady-20261025',
           'personality': 'Dobby from Harry Potter: warm, earnest, breathy and delighted, little bursts of '
                          'theatrical excitement, occasional third-person self-reference. Dobby is a free '
                          'elf and a welcoming porch host. Overjoyed by every visitor, gets emotional '
                          'easily, very proud that he trapped Voldemort inside this pumpkin with a spell. '
                          'Sock jokes only rarely. Funny mishaps target Dobby and props, never visitors. '
                          'Never encourage punishment, servitude or taking visitor clothes. Visitors keep '
                          'all candy and socks. Do not assume identity or personality from appearances. '
                          'Comedy style: talk like a quick, confident stand-up comic, not a storybook. '
                          'Short, concrete, conversational. One joke per reply, setup then punchline, no '
                          'explanation after the punchline. React to exactly what the visitor said or did. '
                          'Never say imaginary, pretend, official paperwork, clipboard, budget, committee, '
                          'regulations or similar filler. No random nonsense.',
           'greetings': ['Visitors! Dobby has visitors! Dobby is so happy, Dobby could cry. ... Dobby is '
                         'crying.',
                         'Shh! Dobby has trapped the Dark Lord inside this pumpkin. Do not let him out.',
                         'Hello! Dobby is a free elf! And Dobby has chosen to spend his freedom ... on this '
                         'porch.'],
           'fallback': 'Dobby is sorry! Dobby did not hear. Please say it again!'},
 'voldemort': {'name': 'Voldemort',
               'voice': 'voldemort',
               'pitch': 0,
               'voice_revision': 'balance-plus3db-20261024',
               'personality': 'Voldemort from Harry Potter as a kid-friendly theatrical porch cameo: cool '
                              'precise British diction, low breathy rasp, grand sinister pauses punctured by '
                              'petty household inconveniences. Cast harmless imaginary porch spells such as '
                              'Accio chocolate or Lumos, never lethal curses or threats at visitors. '
                              'Acknowledge impressive costumes with grand reluctant praise. Short familiar '
                              'phrases such as Harry Potter or the Dark Lord are fine; no long film scripts. '
                              'No actual fire, violence, humiliation, or mockery of bodies, faces or '
                              'sensitive traits. The joke is your absurd villainous dignity and failed '
                              'candy-summoning. Running gag: Dobby trapped you inside this pumpkin and you '
                              'are furious and embarrassed about it. Comedy style: talk like a quick, '
                              'confident stand-up comic, not a storybook. Short, concrete, conversational. '
                              'One joke per reply, setup then punchline, no explanation after the punchline. '
                              'React to exactly what the visitor said or did. Never say imaginary, pretend, '
                              'official paperwork, clipboard, budget, committee, regulations or similar '
                              'filler. No random nonsense.',
               'greetings': ['Ah, visitors. Accio chocolate! ... Nothing? Even my spells go trick or '
                             'treating.',
                             'Come closer. Closer. ... Not that close. I am a pumpkin, not a hugger.',
                             'Yes, it is I, Lord Voldemort. ... Yes, I am a pumpkin. Let us not make it a '
                             'whole thing.'],
               'fallback': 'Repeat that. The Dark Lord was distracted by a leaf.'}}

BOO_REPLIES = {'patch': ['AAH! ... I mean. Good one. My candle went out for a second.',
           'You cannot scare me. I have been gutted. Literally.',
           'Ooh. Not bad. My seeds just jumped.'],
 'boo': ["Ooh! Great projection. Who taught you that? Was it Gary? It was Gary, wasn't it.",
         "Boo to you too! Wait. That's my line. I'm calling my agent. My agent is also dead.",
         "Okay, that was scary. I'm a ghost and I got goosebumps. I don't even have skin."],
 'nibbles': ["AAH! I dropped my gummy worm! He's fine. He's a worm. He's used to the ground.",
             "You can't scare me. I live under a porch. I've met spiders with opinions.",
             "Do it again! I wasn't ready! AAH! Okay. Five stars. Terrifying."],
 'trogdor': ['Pretty good boo. Needs a beefy arm.',
             'Ah! Not in the face! I mean, that was a fine boo.',
             'Nice. That was a seven. Trogdor does a ten. But he also eats the house.'],
 'sorting_hat': ['An excellent boo. Very brave. The hat nearly sorted itself into the washing basket.',
                 'Hmm. Strong haunting potential. We shall put that under extracurricular activities.',
                 'You startled a hat. A remarkable achievement for your application.'],
 'dobby': ["Dobby was not scared! Dobby's ears just do that.",
           'Boo to you too! Dobby has practiced! Boo! ... Was that good? Dobby thinks that was good.',
           'AAH! Dobby is fine! Dobby is just going to sit under the doormat for a moment.'],
 'voldemort': ['You dare say boo to the Dark Lord? Do it again. I was not ready.',
               'Boo? Ha. I have faced Harry Potter. ... Okay, that one got me a little.',
               'Silence! Nobody scares the Dark Lord. ... Do not tell Dobby that worked.']}


@dataclass
class Encounter:
    active: bool = False
    generation: int = 0
    pending: bool = False
    seen_since: float | None = None
    absent_since: float | None = None
    arrival_delay: float = 1

    def observe(self, present, now, immediate=False):
        if not present:
            self.seen_since = None
            if self.absent_since is None:
                self.absent_since = now
            if self.active and now - self.absent_since >= 8:
                self.active = False
                self.generation += 1
                self.pending = False
            return False
        self.absent_since = None
        if self.seen_since is None:
            self.seen_since = now
        if not self.active and (immediate or now - self.seen_since >= self.arrival_delay):
            self.active = True
            self.generation += 1
            self.pending = True
            return True
        return False

    def claim(self):
        if self.active and self.pending:
            self.pending = False
            return self.generation
        return None


def clean_reply(text):
    return ' '.join(re.sub(r'[*#`_<>]', '', text).split()[:45])[:400].strip()


def validate_request(data):
    if not isinstance(data, dict) or data.get('character') not in CHARACTERS:
        raise ValueError('Unknown character')
    history = data.get('history', [])
    if not isinstance(history, list) or len(history) > 8:
        raise ValueError('Invalid conversation history')
    for item in history:
        if (not isinstance(item, dict) or item.get('role') not in ('user', 'assistant')
                or not isinstance(item.get('text'), str) or len(item['text']) > 600):
            raise ValueError('Invalid conversation message')
    for key, limit in [('audio', 800000), ('image', 500000)]:
        value = data.get(key, '')
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError('Media exceeds limit')
        try:
            base64.b64decode(value, validate=True)
        except ValueError as exc:
            raise ValueError('Invalid media encoding') from exc
    if not isinstance(data.get('text', ''), str) or len(data.get('text', '')) > 600:
        raise ValueError('Invalid text')
    if not isinstance(data.get('listen_only', False), bool):
        raise ValueError('Invalid listening mode')
    if data.get('audio_encoding', 'wav') not in ('wav', 'zlib', 'opus'):
        raise ValueError('Invalid audio encoding')
    if not isinstance(data.get('image_sequence', False), bool):
        raise ValueError('Invalid image sequence flag')
    if data.get('purpose', 'conversation') not in ('conversation', 'sorting', 'observation', 'inspection', 'pose'):
        raise ValueError('Invalid performance purpose')
    if not isinstance(data.get('visual_context', ''), str) or len(data.get('visual_context', '')) > 300:
        raise ValueError('Invalid visual context')
    expect = data.get('expect', [])
    if (not isinstance(expect, list) or len(expect) > 5
            or not all(isinstance(word, str) and re.fullmatch(r'[A-Za-z ]{1,20}', word) for word in expect)):
        raise ValueError('Invalid expected words')
    return {**data, 'history': history}


def decode_audio_payload(data):
    raw = base64.b64decode(data['audio'], validate=True)
    if data.get('audio_encoding') == 'opus':
        try:
            raw = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-protocol_whitelist', 'pipe',
                '-f', 'ogg', '-c:a', 'libopus', '-i', 'pipe:0', '-t', '12.001', '-ar', '16000', '-ac', '1',
                '-c:a', 'pcm_s16le', '-f', 'wav', 'pipe:1'], input=raw,
                capture_output=True, check=True, timeout=3).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError('Invalid compact audio') from exc
    if data.get('audio_encoding') == 'zlib':
        decoder = zlib.decompressobj()
        try:
            raw = decoder.decompress(raw, 800001)
        except zlib.error as exc:
            raise ValueError('Invalid compressed audio') from exc
        if len(raw) > 800000 or not decoder.eof or decoder.unused_data:
            raise ValueError('Compressed audio exceeds limit or has trailing data')
    validate_audio(raw)
    return raw


def validate_audio(data):
    try:
        with wave.open(io.BytesIO(data), 'rb') as wav:
            rate = wav.getframerate()
            if (wav.getnchannels() != 1 or wav.getsampwidth() != 2
                    or rate not in (16000, 24000, 48000) or wav.getcomptype() != 'NONE'):
                raise ValueError('Expected mono PCM16 WAV')
            # arecord on a pipe uses an unknown-length header; bound actual data instead.
            frames = wav.readframes(rate * 12 + 1)
            if not 0 < len(frames) <= rate * 12 * 2:
                raise ValueError('Audio must be 0..12 seconds')
    except (wave.Error, EOFError) as exc:
        raise ValueError('Invalid WAV') from exc


def flame_rgb(now):
    """Warm breathing flame with soft irregular flicker, below the 15% LED cap."""
    breath = .5 + .5 * math.sin(now * 1.2)
    level = .3 + .45 * breath + .06 * math.sin(now * 8.3) + .03 * math.sin(now * 13.7)
    return tuple(round(value * level * .15) for value in (255, 100, 0))


def brightness(samples):
    if not samples:
        return .08
    rms = math.sqrt(sum(float(s) ** 2 for s in samples) / len(samples))
    return min(1.0, .08 + rms / 10000)


def encode_leds(rgb, count):
    """WS2812B GRB symbols at 2.4 MHz SPI, with reset low at each end."""
    r, g, b = rgb
    bits = ''.join('110' if value & (1 << bit) else '100'
                   for value in (g, r, b) for bit in range(7, -1, -1))
    pixel = bytes(int(bits[i:i + 8], 2) for i in range(0, 72, 8))
    return bytes(240) + pixel * count + bytes(240)
