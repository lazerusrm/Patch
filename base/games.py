"""Authored, family-friendly trick-or-treat routines and wake phrases."""
import random
import re

MODE_ACTIONS = {'trogdor_mode': 'trogdor', 'normal_mode': 'normal',
                'sorting_hat_mode': 'sorting_hat', 'dobby_mode': 'dobby', 'voldemort_mode': 'voldemort'}
CONTROL_ACTIONS = ('sleep', 'wake', 'volume_up', 'volume_down', *MODE_ACTIONS)

GAMES = {
    'offering': {'kind': 'trick', 'lines': [
        'Yesss, an offering! Have you one piece of chocolate for a terribly underpaid pumpkin?',
        'Set it down. Nice and easy. No sudden nibbling. Tell me when the chocolate has landed.',
        'Excellent. Now pick it back up! I am all mouth and no stomach. The chocolate was safer with you.'
    ], 'interactive': True},
    'invisible_hat': {'kind': 'trick', 'lines': [
        'Boo! I have put an invisible hat on your head. It is extremely stylish. Please do not lose it. Invisible hats are a nightmare to find.'
    ]},
    'tiny_curse': {'kind': 'trick', 'lines': [
        'Boo! I cast the tiniest Halloween spell. For the next three seconds, you must wiggle like spaghetti. One, two, three! Oh dear. You are cured.'
    ]},
    'jingle_bones': {'kind': 'treat', 'clip': 'jingle_bones', 'performer': 'nibbles', 'lines': [
        'A treat! Nibbles has prepared a very small song. A tiny musical snack.'
    ], 'lyrics': 'Rattle, rattle, dancing bones! Candy calls us from our homes. Wiggle left and wiggle right. Happy, happy Halloween night!'},
    'jingle_ghost': {'kind': 'treat', 'clip': 'jingle_ghost', 'performer': 'boo', 'lines': [
        'A treat! A little ghost has a song for you. She insists the high notes are haunted.'
    ], 'lyrics': 'Boo to you and boo to me! Friendly ghosts are all we see. Float along and sing it bright. Sweet dreams on this spooky night!'},
    'jingle_pumpkin': {'kind': 'treat', 'clip': 'jingle_pumpkin', 'performer': 'patch', 'lines': [
        'A treat! A song from a pumpkin with absolutely no formal musical qualifications.'
    ], 'lyrics': 'Orange grin and candle glow! Off to find the treats we go. Tiny feet and costumes bright. Crunchy leaves and sweet delight!'},
}

GAMES.update({
    'pumpkin_voldemort': {'kind': 'trick', 'manual_only': True, 'snap_before': 5,
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
    'scare_shift': {'kind': 'trick', 'cast': ['patch', 'boo', 'patch', 'nibbles'], 'lines': [
        'I shall scare the next visitor. I have centuries of experience.',
        'You screamed when a moth landed on you.',
        'A very menacing moth.',
        'Good. I will book the moth.'
    ]},
    'dark_entrance': {'kind': 'trick', 'manual_only': True, 'cast': ['voldemort', 'dobby', 'voldemort', 'dobby', 'voldemort', 'dobby'], 'lines': [
        'Silence! The Dark Lord has arrived.',
        'Dobby has put out the welcome mat.',
        'Remove it. I am not welcoming.',
        'Dobby will turn it over.',
        'It still says welcome.',
        'Yes, sir. Now it welcomes the floor.'
    ]},
    'dragon_upgrade': {'kind': 'trick', 'manual_only': True, 'cast': ['trogdor', 'boo', 'trogdor', 'boo'], 'lines': [
        'Behold! I have improved the dragon with a second beefy arm.',
        'Can it open a candy wrapper now?',
        'No thumbs.',
        'Two beefy arms. Defeated by a mini chocolate.'
    ]},
    'brave_vacuum': {'kind': 'trick', 'cast': ['sorting_hat', 'patch', 'sorting_hat', 'nibbles'], 'lines': [
        'Gryffindor! Bravery and courage!',
        'That is a vacuum cleaner.',
        'Yes. It went straight under the sofa.',
        'Braver than me. My biscuit went down there and never came back.'
    ]}
})



def intent(text):
    words = ' '.join(re.findall(r'[a-z]+', text.lower()))
    wake = re.search(r'\bhey pumpkin\s*head\b', words)
    if wake:
        command = words[wake.end():].strip()
        if re.search(r'\bsleep\b', command):
            return 'sleep'
        if 'pumpkin spell' in command or ('dobby' in command and 'voldemort' in command):
            return 'pumpkin_scene'
        if re.search(r'\btrog\s*dor mode\b', command):
            return 'trogdor_mode'
        if re.search(r'\bnormal mode\b', command):
            return 'normal_mode'
        if re.search(r'\bsorting hat mode\b', command):
            return 'sorting_hat_mode'
        if re.search(r'\bdobby mode\b', command):
            return 'dobby_mode'
        if re.search(r'\bvoldemort mode\b', command):
            return 'voldemort_mode'
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
        return 'wake'
    if re.search(r'\btrick or treat\b', words):
        return 'game'
    if words == 'boo':
        return 'boo'
    if words in ('sort me', 'sort us', 'sort next'):
        return 'sort'
    if words == 'voldemort mode':
        return 'voldemort_mode'
    return None


def choose_game(previous=None, rng=random, allow_cast=True):
    return rng.choice([key for key in GAMES if key != previous and not GAMES[key].get('manual_only') and (allow_cast or not GAMES[key].get('cast'))])
