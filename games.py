"""Authored, family-friendly trick-or-treat routines and wake phrases."""
import random
import re

MODE_ACTIONS = {'trogdor_mode': 'trogdor', 'normal_mode': 'normal',
                'sorting_hat_mode': 'sorting_hat', 'dobby_mode': 'dobby', 'voldemort_mode': 'voldemort'}
CONTROL_ACTIONS = ('sleep', 'wake', 'volume_up', 'volume_down', *MODE_ACTIONS)

GAMES = {
    'offering': {'kind': 'trick', 'lines': [
        'Trick! Put one piece of candy down next to the pumpkin. Nice and slow. Tell me when it has landed.',
        'Perfect. Now pick it back up. I have no stomach. That was the trick. Happy Halloween!'
    ], 'interactive': True},
    'freeze': {'kind': 'trick', 'lines': [
        'Trick! Freeze! Nobody move! ... Somebody moved. ... It was me. I flickered.'
    ]},
    'tiny_curse': {'kind': 'trick', 'lines': [
        'Trick! I have cursed you. For the next five seconds, you must walk like a zombie. Go! ... Five, four, three, two, one. Curse lifted. Very convincing zombie.'
    ]},
}

GAMES.update({
    'pumpkin_roommates': {'kind': 'trick', 'manual_only': True, 'show': True, 'inside_from': 0,
        'cast': ['dobby', 'voldemort', 'dobby', 'voldemort'],
        'lines': [
            'How is sir enjoying his new body?',
            'I cannot move.',
            'Dobby can carry sir.',
            'Do not touch my stem.'
        ]},
    'pumpkin_voldemort': {'kind': 'trick', 'manual_only': True, 'show': True, 'snap_before': 5,
        'cast': ['dobby', 'voldemort', 'dobby', 'voldemort', 'dobby', 'voldemort', 'dobby', 'voldemort', 'dobby'],
        'lines': [
            'Master has brought Dobby candy. DOBBY IS FREE!',
            'That chocolate belongs to the Dark Lord.',
            'Then the Dark Lord should have put his name on it.',
            'You dare defy me?',
            'Dobby is a free elf. Allow Dobby to improve the porch.',
            'What have you done? Why am I a pumpkin?',
            'Dobby gave sir a job. Guard the sweets.',
            'I will be feared throughout the land!',
            'Wonderful. Start with the squirrels.'
        ]},
    'trogdor_candy': {'kind': 'trick', 'show': True,
        'cast': ['patch', 'fx', 'dobby', 'fx', 'nibbles', 'dobby', 'fx', 'patch', 'voldemort:inside',
                 'fx:inside', 'voldemort:inside', 'fx', 'dobby'],
        'lines': [
            'Nobody panic. But something big just came up the walk.',
            'roar',
            'It is Trogdor! The Burninator!',
            'chomp',
            'He is eating the candy! Hey! Only I eat the candy! ... I mean, inspect!',
            'Stop, Trogdor! Those are for the children!',
            'big-chomp',
            'He ate the bowl. He ate the whole bowl.',
            'Ha! Now you know how it feels. ... Wait. Why is he looking at the pumpkin?',
            'chomp',
            'No! Not the pumpkin! I just got comfortable!',
            'burp',
            'Trogdor has gone! The candy is safe. Mostly. Quick, take some before he comes back!'
        ]},
    'dark_entrance': {'kind': 'trick', 'manual_only': True, 'cast': ['voldemort', 'dobby', 'voldemort', 'dobby', 'voldemort', 'dobby'], 'lines': [
        'Silence! The Dark Lord has arrived.',
        'Dobby has put out the welcome mat.',
        'Remove it. I am not welcoming.',
        'Dobby will turn it over.',
        'It still says welcome.',
        'Yes, sir. Now it welcomes the floor.'
    ]},
    'trogdor_hat': {'kind': 'trick', 'show': True,
        'cast': ['sorting_hat', 'fx', 'sorting_hat', 'fx', 'sorting_hat', 'fx', 'sorting_hat'],
        'lines': [
            'Next to be sorted. Trogdor, the Burninator.',
            'roar',
            'Hmm. Courage, plenty. Ambition, enormous. Table manners ...',
            'chomp',
            'He is eating me. He is EATING me! GRYFFINDOR! Take the house and go!',
            'burp',
            'I am going to need a new brim.'
        ]},
    'trogdor_rescue': {'kind': 'trick', 'show': True,
        'cast': ['voldemort:inside', 'fx', 'fx:inside', 'voldemort:inside', 'patch'],
        'lines': [
            'At last. A creature worthy of the Dark Lord. Dragon! Free me from this pumpkin!',
            'roar',
            'big-chomp',
            '... Not like that.',
            'Sorry, Tom. He only knows the one trick.'
        ]},
})



# Say the name and the dragon (or Strong Bad holding a cardboard one) shows up.
TROGDOR = re.compile(r'\btrog\s*doo?r\b|\btrogd\w*|\bburnin\w*|\bstrong\s*bad\b')  # ASR: Burning, Trogdoor...
QUESTION = re.compile(r'^(who|what|when|where|why|how|which|whose|is|are|was|were|does|do|did|can|could|have|has)\b')


MODES = (('trogdor_mode', r'trog\s*doo?r|strong\s*bad'), ('normal_mode', r'normal|regular'),
         ('sorting_hat_mode', r'sorting\s*hat|hat'), ('dobby_mode', r'dobb?(?:y|ie|i)|dobie|doby|toby'),
         ('voldemort_mode', r'voldemort|vol\s*de\s*mort'))


def mode_command(words):
    for action, name in MODES:
        if re.search(r'\b(?:' + name + r')\s+mode\b', words):
            return action
    return None


def question(text, words):
    """Trivia questions get a real answer; mentions and shouts get a scene."""
    return text.strip().endswith('?') or bool(QUESTION.match(words))


def intent(text):
    words = ' '.join(re.findall(r'[a-z]+', text.lower()))
    wake = re.search(r'\bhey pumpkin\s*head\b', words)
    if wake:
        command = words[wake.end():].strip()
        if re.search(r'\bsleep\b', command):
            return 'sleep'
        if 'pumpkin spell' in command or ('dobby' in command and 'voldemort' in command):
            return 'pumpkin_scene'
        mode = mode_command(command)
        if mode:
            return mode
        if re.search(r'\bsort (me|us|next)\b|\bsorting ceremony\b', command):
            return 'sort'
        if any(phrase in command for phrase in ('cant hear you', 'can t hear you', 'louder', 'turn it up')):
            return 'volume_up'
        if any(phrase in command for phrase in ('be quiet', 'quieter', 'turn it down')):
            return 'volume_down'
        if 'routine' in command.split() or 'argue' in command.split():
            return 'routine'
        if 'joke' in command.split():
            return 'joke'
        if 'story' in command.split():
            return 'story'
        if re.search(r'\btrick or treat\b', command):
            return 'game'
        if command == 'boo':
            return 'boo'
        if TROGDOR.search(command) and not question(text, command):
            return 'trogdor_scene'
        return 'wake'
    if re.search(r'\btrick or treat\b', words):
        return 'game'
    if re.search(r'\b(tell|know|got|hear) (me |us )?(a |another |any )?jokes?\b', words) or words in ('joke', 'a joke', 'another joke'):
        return 'joke'
    if re.search(r'\btell (me |us )?a (scary )?story\b', words):
        return 'story'
    if re.search(r'\b(do|show) (me |us )?(a |the )?(routine|show)\b', words):
        return 'routine'
    if words == 'boo':
        return 'boo'
    if words in ('sort me', 'sort us', 'sort next', 'shortly', 'sorted', 'sort it', 'sort me please', 'sort of me') or (
            len(words.split()) <= 4 and re.search(r'\b(?:sort|short|sorts|sword|sorta) (?:me|us|next|my|mi)\b', words)):
        return 'sort'  # ASR: "Sort me" heard as "shortly".
    # Whisper's spellings of the spells (owner tests: "Lumos" -> "Lima").
    if re.search(r'\b(?:lumos|loomis|lumo s|loomos|lima|luma|lumen|lumens|loomus|lumous|luminous)\b', words) and len(words.split()) <= 4:
        return 'lumos'
    if words in ('nox', 'knox', 'nocks', 'knocks', 'nox nox', 'knocks knocks', 'nokes', 'noks', 'locks', 'docks',
                 'not', 'knot', 'naught', 'nought', 'not not'):  # "Nox" heard as "Not" in owner tests.
        return 'nox'
    if re.search(r'\b(?:inspect|check|look at|rate) (?:my|our|this) (?:candy|bag|treats?|bucket|loot)\b', words):
        return 'inspection'
    if re.search(r'\btalent (?:show|scout)\b|\btake (?:my|our) (?:picture|photo)\b', words):
        return 'talent'
    if re.search(r"\b(?:let'?s|lets|let us|watch me|can i|i want to|i'll|i will) dance\b|\bdance off\b|\bdance party\b", words):
        return 'dance'
    if re.search(r'\bsing\b.*\bsong\b|\bsing (?:me|us|something|a song)\b|\bsong please\b', words):
        return 'song'
    if re.search(r'\b(?:pumpkins?|simon|simons) (?:says|say|sis|sees|sez|said|seas|is)\b', words) and (
            'play' in words or len(words.split()) <= 4):  # ASR: "play pumpkin sis".
        return 'pumpkin_says'
    if re.search(r'\bbeefy arm\b|\b(?:look at|check out) my muscles?\b|\bflex\b', words):
        return 'flex'
    # A short spoken "<character> mode" switches without the wake phrase; questions about modes do not.
    if len(words.split()) <= 4 and not question(text, words):
        mode = mode_command(words)
        if mode:
            return mode
    if TROGDOR.search(words) and not question(text, words):
        return 'trogdor_scene'
    return None


def benched(key):
    """Benched hosts (core.DISABLED_CHARACTERS) still appear in routines and songs (owner, 2026-10-25)."""
    return False


# The custom jingles were retired (owner, 2026-10-31: they sounded weird). A song request
# now gets an ordinary trick or treat; any future scene with a 'clip' becomes a song again.
SONGS = tuple(key for key, scene in GAMES.items() if scene.get('clip'))


def choose_game(previous=None, rng=random, allow_cast=True):
    return rng.choice([key for key in GAMES if key != previous and not GAMES[key].get('manual_only')
                       and (allow_cast or not GAMES[key].get('cast'))])
