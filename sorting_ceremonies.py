"""The Hat conducts an assessment, then lands one short final verdict."""
import random

OPENINGS = [
    'Stop... Now let me have a good look at you. Hmm. Hold still while I assess the situation.',
    'One moment. The Hat has not yet formed an opinion. Enjoy this rare occasion.',
    'Ahh. Come closer... Yes. Interesting. You have arrived at a particularly judgmental hat.',
]
GROUP_OPENING = 'Stop... A whole delegation. Hold still. I must assess the situation.'
VERDICTS = {
    'Gryffindor': [
        ('Walking up to a talking pumpkin. A promising start.', 'I said brave. Not unsupervised.'),
        ('An adventure, then. Yes. I believe we can arrange that.', 'Try to survive the first staircase.'),
    ],
    'Ravenclaw': [
        ('Questions, I suspect. Well, curiosity has brought you this far.', 'Questions about my qualifications may be kept to yourself.'),
        ('A little mystery would suit this evening nicely.', 'You may now explain why a hat is in charge.'),
    ],
    'Hufflepuff': [
        ('You gave an old hat a moment of your evening. Much appreciated.', 'A fine house. I expect excellent manners at the candy bowl.'),
        ('There is always room for someone willing to listen.', 'Off you go. Being decent need not delay the chocolate.'),
    ],
    'Slytherin': [
        ('An ambitious evening of candy collection, perhaps. Very well.', 'You may join the house. You may not immediately take it over.'),
        ('Yes... I think a little cunning will serve this adventure.', 'Save the plans for world domination until after bedtime.'),
    ],
}


def opening(previous=None, group=False, rng=random):
    choices = OPENINGS + ([GROUP_OPENING] if group else [])
    return rng.choice([line for line in choices if line != previous])


def verdict(house, previous=None, assessment='', rng=random):
    choices = [pair for pair in VERDICTS[house] if pair[1] != previous]
    lead, ending = rng.choice(choices)
    return f'{assessment or lead} {house.upper()}! {ending}', ending


# Interactive "sort me": the Hat places the visitor in front of a camera, looks, comments, then sorts.
# Both cameras see the straight part of the path: the webcam sits on the path two feet in front of the
# pumpkin looking out, and the doorbell looks straight down it. Send everyone there, facing the house.
POSITION = {
    'doorbell': ['Not at the door! The door is in Slytherin, and it will influence you. '
                 'Back down the path to the corner where it turns, face the house, and quickly. It is already scheming.',
                 'Too close! From there I can only see your nose, and I refuse to sort a nose. '
                 'Back down the path to the corner where it turns, and face the house. Hurry.'],
    'webcam': ['Quickly! Stand at the corner of the path, where it turns, facing the house. '
               'The sorting magic only reaches that far, and I am a very old hat. It is fading as we speak.',
               'Urgent! Stand at the corner of the path, face the house, and look at the little camera by the pumpkin. '
               'That is my magic eye. The last child who stood on the grass was sorted into Shrubbery.'],
}
NUDGE = {
    'doorbell': 'Stay on the path, at the corner! Not the grass! The grass has not been sorted, and frankly it is a Hufflepuff.',
    'webcam': 'Over to the corner of the path, where I can see all of you! Hurry, my brim is beginning to droop.',
}
LOOKING = ['Freeze! Do not move a muscle. A hat this old needs a very long exposure.',
           'Perfect. Hold it. Hold it. Do not blink, it confuses me.']
NOT_FOUND = 'I cannot see you, but I can sense your ambition from here. That will have to do. The magic is wearing off.'
UNSURE = 'Hmm. A difficult decision. Very difficult.'


def house_line(house, previous=None, rng=random):
    """Just the announcement and the dry ending, said after a generated assessment."""
    choices = [pair for pair in VERDICTS[house] if pair[1] != previous]
    _, ending = rng.choice(choices or VERDICTS[house])
    return f'{house.upper()}! {ending}', ending


AUTHORED_SORTING = set(OPENINGS + [GROUP_OPENING])
AUTHORED_SORTING.update(line for lines in POSITION.values() for line in lines)
AUTHORED_SORTING.update(list(NUDGE.values()) + LOOKING + [NOT_FOUND, UNSURE])
AUTHORED_SORTING.update(f'{house.upper()}! {ending}' for house, pairs in VERDICTS.items() for _, ending in pairs)
AUTHORED_SORTING.update(f'{lead} {house.upper()}! {ending}'
                        for house, pairs in VERDICTS.items() for lead, ending in pairs)
