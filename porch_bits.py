"""Authored porch scenes. One controller chooses the voices and owns all output.

Scene steps are (target, kind, value) or (target, kind, value, actor):
  target  porch    the big Bluetooth speaker (host character unless actor given)
          inside   the small speaker inside the pumpkin (trapped Voldemort by default)
          doorbell the G4 doorbell speaker (plain clear voice)
          chime    indoor chime if available, else doorbell, else porch
  kind    text | effect (assets/effects/<value>.wav) | light (porch bulbs, '<cue>:<seconds>', no sound;
          target is ignored; cues: blackout lightning fire green ghost houses lumos <house>)
          | pause ('<seconds>': silence while the visitor does what they were told)
A host-specific step uses a dict value {character: text, '*': default}.
"""
import random
import re

INSIDE_ACTOR = 'voldemort'

QUICK_REPLIES = {
    'hearing': {
        'patch': 'Loud and clear. I am a pumpkin, not deaf.',
        'boo': "Every word! My hearing is the only thing that didn't fade.",
        'nibbles': "Loud and clear! Goblin ears. Huge. Like satellite dishes, but sticky.",
        'trogdor': 'Loud and clear. This mask has incredible ears. Well. Zero ears. Same thing.',
        'sorting_hat': 'Perfectly. Listening is most of the job. The rest is sitting on heads.',
        'dobby': 'Dobby hears you! Dobby has very big ears!',
        'voldemort': 'I hear everything. It is very annoying.'},
    'identity': {
        'patch': 'Patch. Pumpkin. Porch. That is the whole resume.',
        'boo': "I'm Boo. Ghost. Actress. Two hundred years in show business, zero people scared.",
        'nibbles': "Nibbles! Goblin! World-famous candy critic! Mostly famous under this porch.",
        'trogdor': 'Strong Bad. You may have heard of me. From me.',
        'sorting_hat': 'The Sorting Hat. Currently between heads.',
        'dobby': 'Dobby! Dobby is a free elf!',
        'voldemort': 'Lord Voldemort. Currently a pumpkin. Temporarily.'},
    'hello': {
        'patch': 'Hi. Come for the candy, or the conversation? ... It is the candy.',
        'boo': "Hello! Oh, a live one! You have no idea how rare that is around here.",
        'nibbles': "Hi! Bags up! I'm not touching. I'm just looking. Hungrily.",
        'trogdor': 'Hey. Nice costume. I will allow it.',
        'sorting_hat': 'Hello! Come closer. I need a good look at that head.',
        'dobby': 'Hello! Hello! Dobby is so happy!',
        'voldemort': 'Hello. You may bow, if you like.'},
    'wellbeing': {
        'patch': 'Hollow. Literally. But thanks for asking.',
        'boo': "Dead. But honestly? Never better. The commute is great. I go through walls.",
        'nibbles': "Amazing! I had nine candies for dinner. Ten if you count the wrapper. I count the wrapper.",
        'trogdor': 'Super good. Beefy, even.',
        'sorting_hat': 'A bit dusty. Nobody has worn me since last Halloween.',
        'dobby': 'Dobby is wonderful! Dobby has visitors!',
        'voldemort': 'I am a pumpkin. How do you think I am?'},
    'thanks': {
        'patch': 'Do not mention it. Seriously. Nobody can know I am nice.',
        'boo': "No, thank you! Tell the other ghosts. Especially Gary.",
        'nibbles': "You're welcome! That'll be one candy. Kidding. Unless?",
        'trogdor': "You're welcome. Tell your friends. Tell your enemies. Tell everybody.",
        'sorting_hat': 'My pleasure. A little gratitude! How refreshing.',
        'dobby': 'Dobby loves to help!',
        'voldemort': 'Naturally. The Dark Lord has excellent manners.'},
    'treat': {
        'patch': 'Treat. Obviously. My tricks are terrible. I cannot move.',
        'boo': "Treat! My tricks never work. I float, and everyone assumes it's a drone.",
        'nibbles': "Treat! Obviously! The trick is how fast I review it.",
        'trogdor': 'Treat. The trick is Trogdor already ate half of them.',
        'sorting_hat': 'Treats first. Sorting on an empty stomach is dangerous.',
        'dobby': 'Treat! Dobby checked them all! None of them are socks!',
        'voldemort': 'Accio candy! ... Nothing. Fine. Help yourself.'},
}


# Played the instant the visitor stops talking, while the real reply is generated (~5 s).
# In-character stalling that is funny on its own and fits any question; every line >= 3 words.
REACTIONS = {
    'patch': ['Ooh. Hang on. My candle just flickered. That means I am thinking.',
              'Okay, give me a second. I am working with about four seeds up here.',
              'Hmm. Let me think. Thinking is hard when you are hollow.'],
    'boo': ['Ooh! Darling! Hold that thought. I need a dramatic pause.',
            'Ha! Oh, that is good. One moment, I am getting into character.',
            'Wait. My line. What is my line? Places, everyone!'],
    'nibbles': ["Ooh! Hang on. Let me check my notes. I ate my notes. They were delicious.",
                "Hmm! Good question. I'm thinking. My brain is sixty percent gummy bear.",
                'Wait, wait, wait. Goblin thinking. Very fast. Very sticky.'],
    'sorting_hat': ['Hmm. Interesting. Let me consult the brim.',
                    'Ah. A difficult question. Almost as difficult as sorting a cat.',
                    'One moment. I have thought for a thousand years. One more second is fine.'],
    'dobby': ['Ooh! Dobby is thinking! Dobby is thinking very hard! The ears are helping!',
              'Oh! A question for Dobby! Nobody ever asks Dobby questions!',
              'Ooh! Just a moment! Dobby must not answer too fast, Dobby gets excited and falls over!'],
    'voldemort': ['Silence. The Dark Lord is thinking. Still thinking.',
                  'Hmm. Interesting. Do go on. No, wait. I will go on.',
                  'Ah. Let me consider your fate. It is mostly candy related.'],
    'trogdor': ['Oh, okay. Hang on. Gotta consult the beefy arm.',
                'Hmm. Good question. For a regular person. Let me answer it awesomely.',
                'Okay, okay, give me a sec. I am typing this into my brain.'],
}

# Trapped Voldemort heckles from the speaker inside the pumpkin while the host stalls.
HECKLES = ['Oh, take your time. I have been in here for hours.',
           'Ask me instead. I am far more intelligent. I am also stuck.',
           "I've been stuck in a gourd for a week and even I'd have answered by now.",
           'While you wait, could someone please let me out?',
           "Take your time. I have eternity. Literally. That's the curse."]

MORE_REPLIES = [
    (('favorite candy', 'favourite candy', 'what candy do you like', 'best candy'), {
        'patch': 'Candy corn. Nobody else wants it, and I relate to that.',
        'boo': "Ghost peppers. Kidding. I can't eat. Everything falls straight through. It's very messy.",
        'nibbles': "Chocolate, five stars. Candy corn, two stars. Raisins, I'm calling the police.",
        'trogdor': 'Whatever Trogdor has not eaten yet. So, nothing.',
        'sorting_hat': 'I am a hat. But if I had a mouth, chocolate frogs.',
        'dobby': 'Dobby loves chocolate! Dobby is not allowed. Dobby eats it anyway!',
        'voldemort': 'Chocolate. Do not tell anyone. It ruins the image.'}),
    (('are you real', 'is this real', 'are you a robot', 'are you alive', 'how do you talk', 'how are you talking'), {
        'patch': 'Real as a pumpkin gets. Which is not very. I am a vegetable with opinions.',
        'boo': "Real? I'm a ghost. Present, yes. Real is a strong word.",
        'nibbles': "I'm extremely real. Watch. That was me blinking. Very realistic.",
        'trogdor': 'Totally real. Real smooth.',
        'sorting_hat': 'Real enough to sort you. Shall we?',
        'dobby': 'Dobby is real! Dobby is as real as socks!',
        'voldemort': 'I am very real. Unfortunately, so is this pumpkin.'}),
    (('you re funny', 'you are funny', 'that s funny', 'that was funny', 'ha ha', 'haha', 'lol'), {
        'patch': 'Thank you. I have been working on that one since September.',
        'boo': "Stop it. ... No, really, keep going. Gary never gets compliments.",
        'nibbles': "I know! Tell your friends! Bring them. And their bags.",
        'trogdor': 'Obviously.',
        'sorting_hat': 'I have had a thousand years to practice.',
        'dobby': 'Dobby made you laugh! This is the best day of Dobby\'s life!',
        'voldemort': 'Do not laugh at the Dark Lord. ... Okay, a little.'}),
    (('i like your', 'i love your', 'i like you', 'you re cool', 'you are cool', 'you re awesome', 'love you'), {
        'patch': 'Thank you. Do not tell the other pumpkins. They get jealous.',
        'boo': "Oh! I'm blushing. You can't see it. I'm see-through. It's very frustrating.",
        'nibbles': "Aww. I like you too. Mostly your bag. But also you. Sixty forty.",
        'trogdor': 'Yeah. I know.',
        'sorting_hat': 'How kind. Ten points to your house.',
        'dobby': 'Dobby likes you too! Dobby likes everybody!',
        'voldemort': 'Flattery. Excellent. Continue.'}),
    (('are you scary', 'are you spooky', 'you re not scary', 'you are not scary', 'not scary'), {
        'patch': 'I have a candle in my head and no legs. I am terrifying to myself.',
        'boo': "Not scary? I'll have you know I once frightened a mop. It's never been the same.",
        'nibbles': "I'm terrifying! Look at my fangs! That's a candy corn. I've got it upside down.",
        'trogdor': 'I am not. Trogdor is. Trogdor is right behind you.',
        'sorting_hat': 'Only at sorting time. Ask any first year.',
        'dobby': 'Dobby is not scary! Dobby is friendly!',
        'voldemort': 'I am the most feared wizard of all time. Currently, in a vegetable.'}),
    (('what are you doing', 'what s up', 'whats up'), {
        'patch': 'Sitting. Glowing. Same as always.',
        'boo': "Haunting. Badly. Want to watch? It's mostly me rattling a chain I borrowed from a bike.",
        'nibbles': "Writing a candy review. So far: delicious. Final verdict: more research needed.",
        'trogdor': 'Being awesome. You?',
        'sorting_hat': 'Waiting for a head. Yours will do.',
        'dobby': 'Dobby is guarding the Dark Lord! And saying hello!',
        'voldemort': 'Plotting. From inside a pumpkin. It is going poorly.'}),
]


def quick_reply(character, heard):
    words = re.sub(r'[^a-z ]', ' ', heard.lower())
    words = re.sub(r'\b(?:dobby|pumpkinhead|pumpkin|sorting hat|voldemort|trogdor|boo|nibbles|patch)\b', '', words)
    words = ' '.join(words.split())
    groups = {'hearing': ('can you hear me', 'can you hear us', 'do you hear me', 'are you listening',
                         'are you there', 'are you working', 'is this working'),
              'identity': ('who are you', 'what are you', 'what is your name', 'what s your name', 'who is this',
                           'who s that', 'who is that'),
              'hello': ('hi', 'hello', 'hey', 'hi there', 'hello there', 'happy halloween'),
              'wellbeing': ('how are you', 'how are you doing', 'how is it going', 'how are you today',
                            'hello how are you', 'hi how are you'),
              'thanks': ('thanks', 'thank you', 'thank you very much', 'thanks a lot'),
              'treat': ('trick or treat',)}
    for kind, phrases in groups.items():
        if words in phrases:
            return QUICK_REPLIES[kind][character]
    if words in ('bye', 'goodbye', 'bye bye', 'see you', 'see you later'):
        return farewell(character)
    padded = ' ' + words + ' '
    if len(words.split()) <= 8:
        for phrases, replies in MORE_REPLIES:
            if any(' ' + phrase + ' ' in padded for phrase in phrases):
                return replies[character]
    return ''


def reaction(character, previous=None, rng=random):
    lines = REACTIONS.get(character) or REACTIONS['patch']
    return rng.choice([line for line in lines if line != previous] or lines)


def heckle(previous=None, rng=random):
    return rng.choice([line for line in HECKLES if line != previous] or HECKLES)


# Someone pressed the real doorbell (the indoor chime is already playing its own sound).
DOORBELL_BITS = {
    'stomach': [('porch', 'effect', 'porch-fart'),  # The porch speaker has the bass; the doorbell does not.
                ('doorbell', 'text', "Excuse me. I ate too much candy. Please don't push so hard next time."),
                ('porch', 'text', {'patch': 'That was the doorbell. I want that on the record.',
                                   'trogdor': "Whoa. Gross. That one's on the doorbell.",
                                   'sorting_hat': 'I shall not be sorting whatever that was.',
                                   'dobby': 'Dobby did not do it! Dobby is a free elf, and a clean one!',
                                   'voldemort': 'Disgusting. Even for a doorbell.',
                                   '*': 'That was the doorbell. Not me.'})],
    'right_here': [('porch', 'text', {
                       'patch': "You rang the doorbell? I'm RIGHT here. I have a face. The doorbell is a button with ambitions.",
                       'boo': 'Oh, ring the bell, sure. The ghost is just decoration.',
                       'nibbles': 'Hey! The bell does not inspect candy! I inspect candy!',
                       'sorting_hat': 'You rang. Very well. While we wait, I shall look inside your head.',
                       'dobby': 'Someone is coming! Dobby thinks! Dobby is not allowed to open doors. Dobby has no hands for knobs.',
                       '*': 'You rang the doorbell. I am right here.'})],
    'hold': [('doorbell', 'text', 'Ding dong. Your visit is important to us. Please hold.'),
             ('porch', 'text', {
                 'patch': "Don't hold. The hold music is me humming. ... Hmm hmm hmmm. ... See? Nobody wants that.",
                 'boo': 'Hold music! Let me sing it. ... Actually, no. Union rules.',
                 'nibbles': 'While you wait, bag up. Quick inspection.',
                 '*': 'Hold on. Talk to the pumpkin instead.'})],
    'snitch': [('doorbell', 'text', 'Hello. Before I get anyone, did you say hi to the pumpkin?'),
               ('porch', 'text', {
                   'patch': 'They did not.',
                   'boo': 'They did not. I am devastated. Theatrically.',
                   'nibbles': 'They did not. And their bag is very full.',
                   'dobby': 'Dobby forgives them! Dobby always forgives!',
                   'trogdor': 'They did not. I saw the whole thing.',
                   'sorting_hat': 'They did not. Noted. On their permanent record.',
                   '*': 'They did not.'})],
    'roommate': [('inside', 'text', 'Do not answer it! It could be Harry Potter!'),
                 ('porch', 'text', {
                     'dobby': 'It is not Harry Potter, sir. Harry Potter does not trick or treat.',
                     'sorting_hat': 'It is a visitor, Tom. Calm down.',
                     '*': 'It is just a visitor, Tom. Go back to sleep.'})],
}

DOORBELL_BITS.update({
    'too_close': [('doorbell', 'text', 'Whoa. Too close. I can see your boogers. Stand back just a little.'),
                  ('doorbell', 'text', 'The only green goblins allowed are already inside.'),
                  ('porch', 'text', {'dobby': 'The doorbell is right! Dobby saw them too! Tiny ones!',
                                     'voldemort': 'For once, the doorbell and I agree.',
                                     '*': "It's not wrong. Step back a smidge."})],
    'two_rings': [('doorbell', 'text', 'You rang. I am a doorbell. This is the best moment of my night.'),
                  ('porch', 'text', {
                      'patch': 'Please do not ring it again. It gets emotional.',
                      'dobby': 'Dobby is happy for the doorbell!',
                      '*': 'Do not ring it again. It gets emotional.'}),
                  ('doorbell', 'text', 'Sniff.')],
    'press_again': [('doorbell', 'text', 'Ding dong. Someone is on their way.'),
                    ('inside', 'text', 'Nobody is coming. Nobody ever comes. I have been in here since Tuesday.'),
                    ('porch', 'text', {
                        'dobby': 'Sir! Do not frighten the visitors!',
                        '*': "Ignore him. He's in a mood. Also a pumpkin."})],
})

DOORBELL_BITS.update({
    'transfer': [('doorbell', 'text', 'Ding dong. Thank you for ringing. Your call is being transferred to... the pumpkin.'),
                 ('porch', 'text', {'patch': 'Hello, pumpkin speaking. How may I direct your candy?',
                                    'trogdor': "Strong Bad's desk. State your name, your business, and your candy.",
                                    'sorting_hat': 'Sorting department. Please hold your head very still.',
                                    '*': 'Hello? Yes, this is the porch.'})],
    'update': [('doorbell', 'text', 'Please wait. Installing doorbell update. One percent.'),
               ('porch', 'text', {'patch': 'Not now! There are kids here!',
                                  'trogdor': 'Dude! Not now! Strong Bad has an audience!',
                                  'sorting_hat': 'Now? In the middle of a ceremony?',
                                  '*': 'Not now! Visitors!'}),
               ('doorbell', 'text', 'Update complete. New feature: I can now say ding dong in Spanish. Ding dong.'),
               ('porch', 'text', {'patch': "That's the EXACT same thing!", 'trogdor': "Dude. That's the exact same thing.",
                                  'sorting_hat': 'That is precisely, entirely the same.', '*': "That's the exact same thing!"}),
               ('doorbell', 'text', 'Muy bien.')],
    'nap': [('doorbell', 'text', "Huh? What? I'm up! I wasn't sleeping. Doorbells don't sleep."),
            ('porch', 'text', {'patch': 'You were snoring. The whole porch heard it.',
                               'trogdor': 'You were snoring, doorbell. Like a big beepy bear.',
                               'sorting_hat': 'You were snoring. I sorted it into Hufflepuff.',
                               '*': 'You were snoring.'}),
            ('doorbell', 'text', 'That was the wind.')],
    'visitor_number': [('doorbell', 'text', 'Ding dong. Congratulations. You are tonight\'s visitor number...'),
                       ('porch', 'pause', '1'),
                       ('doorbell', 'text', '...a lot. Your prize is candy. From inside.'),
                       ('porch', 'text', {'patch': "Somebody's coming! Everybody act natural. ... Not like that. Less like a pumpkin.",
                                          'trogdor': 'Act cool. Act cool.',
                                          'sorting_hat': 'Someone approaches. Compose yourself.',
                                          '*': 'Somebody is coming. Act surprised.'})],
})

# The doorbell cut the host off mid-sentence: one quick reaction, then the doorbell bit.
RING_INTERRUPTED = {
    'patch': ['Whoa! I was in the middle of a sentence! Okay, okay.',
              'Hold that thought. Somebody pushed the button. The button always wins.',
              'Rude! Effective. But rude.'],
    'trogdor': ['Hey! Strong Bad was talking! Do you interrupt Trogdor too? Actually, don\'t.',
                'Ding dong? More like ding WRONG. I was mid-awesome.',
                "Oh, you're gonna ring that thing while I'm talking? Bold move."],
    'sorting_hat': ['Interrupted mid-thought. A very Slytherin move.',
                    'I was speaking. But apparently the bell outranks the hat.',
                    'Patience is a Hufflepuff virtue. You rang anyway. Noted.'],
    '*': ['Whoa! You rang! Okay, okay.'],
}


# Rang the bell without saying a word to the host first: the host takes it personally.
PREMATURE_RING_BITS = {
    'too_soon': [('porch', 'text', {
                     'patch': "Whoa! You rang the doorbell? I didn't even get to say hi! I've been rehearsing my hi all night!",
                     'trogdor': "Hey! You skipped me! Nobody skips the Strong Bad. That's like skipping the good part of a cartoon.",
                     'sorting_hat': 'You rang before being sorted? Most irregular. Back to the pumpkin, please.',
                     'dobby': 'Oh! The bell! But Dobby did not even say hello! Dobby had a whole hello!',
                     'voldemort': 'You ring the bell before greeting the Dark Lord? Bold. Foolish. But bold.',
                     '*': 'Hey! You rang the doorbell before talking to me!'}),
                 ('doorbell', 'text', 'Ding dong. Sorry. They pushed me.')],
    'skipped': [('porch', 'text', {
                    'patch': "Oh, I see how it is. Straight to the door. Don't mind the talking pumpkin. Happens all the time.",
                    'trogdor': 'Wow. Straight to the door. I had a whole thing planned. With a dragon.',
                    'sorting_hat': "Ringing the bell without a word to the hat. I've seen this before. Slytherin.",
                    'dobby': 'Straight to the door! Dobby understands. Dobby is only a pumpkin. A sad pumpkin.',
                    'voldemort': 'Ignored. By a child. In my own pumpkin.',
                    '*': "Oh, I see how it is. Straight to the door."}),
                ('inside', 'text', "They didn't say hi to me either.")],
    'porch_rules': [('porch', 'text', {
                        'patch': "Excuse me! Porch rules! First you talk to the pumpkin, then you get candy. I didn't make the rules. Okay, I made the rules.",
                        'trogdor': "Whoa, whoa. Porch rules. Step one, talk to me. Step two, candy. Step three, tell your friends I'm awesome.",
                        'sorting_hat': 'There is an order to these things. Hat first. Door second. Candy third.',
                        '*': 'Excuse me! Porch rules! First you talk to the pumpkin, then you get candy!'})],
}

# Rang again within 15 seconds: the doorbell escalates (Pumpkin.perform_bit counts recent rings).
RING_AGAIN_BITS = {
    'impatient': [('doorbell', 'text', 'Ding dong. Again. I heard you the first time.'),
                  ('porch', 'text', {
                      'patch': 'It has feelings, you know. Mostly annoyance.',
                      'boo': 'Twice! An encore! Nobody has ever asked the doorbell for an encore.',
                      'dobby': 'The doorbell is getting grumpy! There, there, doorbell. Dobby is here.',
                      'sorting_hat': 'Patience. Very Gryffindor of you. Not in the good way.',
                      'trogdor': "Whoa, double ring. That's the secret knock. You're in the club now.",
                      'voldemort': 'Ring it again and I will curse it. I mean it this time.',
                      '*': 'Twice! The doorbell is getting dramatic.'})],
    'queue': [('doorbell', 'text', 'You are caller number two. Your ring is very important to us.'),
              ('doorbell', 'text', 'Estimated wait time: one pumpkin.'),
              ('porch', 'text', {
                  'dobby': 'Dobby is the wait! Dobby is a very fast wait!',
                  '*': "That's me. I'm the wait."})],
    'secret_signal': [('porch', 'text', {
                          'dobby': 'Two rings! That is the secret signal! Dobby forgot what it means!',
                          '*': "Two rings! That's the secret signal!"}),
                      ('lights', 'light', 'houses:2'),
                      ('inside', 'text', 'Finally. The signal. Release the Dark Lord!'),
                      ('doorbell', 'text', 'Request denied.')],
}
RING_THIRD_BITS = {
    'drum': [('doorbell', 'text', 'Ding. Dong. Ding. Dong. I am a doorbell, not a drum.'),
             ('lights', 'light', 'lightning:1'),
             ('porch', 'text', {
                 'dobby': 'Dobby will knock for you! Dobby has no hands! Dobby will knock with his head!',
                 'voldemort': 'Enough! The Dark Lord is trying to think in here!',
                 '*': 'Okay, okay! Somebody is coming! Probably! Maybe!'})],
    'union': [('doorbell', 'text', 'That is three rings in fifteen seconds. I am contacting my union.'),
              ('inside', 'text', 'Take me with you.')],
    'grumpy': [('doorbell', 'text', 'Ring limit reached. Entering grumpy mode.'),
               ('doorbell', 'text', 'Ding.'),
               ('porch', 'pause', '1.5'),
               ('doorbell', 'text', 'Hmph.'),
               ('porch', 'pause', '1'),
               ('doorbell', 'text', 'Dong.')],
}

# Someone went straight past the pumpkin to the door and did not ring yet.
DOORSTEP_BITS = {
    'ring_for_you': [('porch', 'text', {
                        'patch': 'Oh, sure. Walk right past the talking pumpkin.',
                        'boo': 'Excuse me! The show is over here!',
                        'nibbles': 'Hey! Nobody gets past the candy inspector!',
                        'dobby': 'Wait! Dobby will help!',
                        'sorting_hat': 'Not so fast. Nobody passes the hat unsorted.',
                        '*': 'Oh, sure. Walk right past the talking pumpkin.'}),
                     ('porch', 'effect', 'ding-dong'),
                     ('porch', 'text', {
                        'patch': 'There. I rang it for you. You are welcome.',
                        'boo': 'There! I rang it. Now everybody look at me.',
                        'nibbles': 'There. Rang it for you. Now bag up.',
                        'dobby': 'Dobby rang the bell! Dobby has never rung a bell before!',
                        'sorting_hat': 'There. The bell has been rung. Now, your head, please.',
                        '*': 'There. I rang it for you.'})],
    'fake_ring': [('porch', 'effect', 'ding-dong'),
                  ('porch', 'text', {
                      'patch': 'Gotcha! That was me. I do a very good doorbell. The real one is jealous.',
                      'boo': 'Ha! That was me! I do a very good doorbell.',
                      'nibbles': 'That was me! I do doorbells, evil laughs, and candy inspections.',
                      'dobby': 'That was Dobby! Dobby is a very good doorbell!',
                      '*': 'Gotcha! That was me. I do a very good doorbell. The real one is jealous.'}),
                  ('doorbell', 'text', 'I am not jealous.'),
                  ('porch', 'text', {'dobby': 'It is a little jealous.', '*': "It's a little jealous."})],
    'doorbell_redirect': [('doorbell', 'effect', 'ding-dong'),
                          ('doorbell', 'text', 'Hi. The pumpkin wants to talk to you.'),
                          ('porch', 'text', {
                              'patch': 'Over here. Bottom left. Orange. Talking.',
                              'boo': 'Over here! Look down! Lovely, thank you.',
                              'nibbles': 'Down here! Bags open, please!',
                              'dobby': 'Over here! Dobby is in the pumpkin! Hello!',
                              '*': 'Over here. The pumpkin.'})],
    'get_back': [('porch', 'text', {
                     'patch': "Hey! Get back here! You walked right past me! I'm the pumpkin! I'm the whole show!",
                     'boo': 'Excuse me! The stage is over here! Come back and stand in front where I can see you!',
                     'dobby': 'Wait! Come back! Stand in front of Dobby! Dobby wants to see your costume!',
                     'sorting_hat': 'Not so fast. Come back and stand in front of the pumpkin. Nobody enters unsorted.',
                     'trogdor': "Whoa, whoa. Get back here. Stand in front so I can see the costume. That's how this works.",
                     'voldemort': 'Come back here. Stand before the Dark Lord. Now.',
                     '*': 'Hey! Get back here! Come stand in front so I can see you!'})],
    'pockets': [('porch', 'text', {
                    'dobby': 'Wait! Before the bell! Turn out your pockets! Dobby is checking for socks!',
                    'voldemort': 'Halt. Turn out your pockets. The Dark Lord is checking for chocolate. For security reasons.',
                    'trogdor': "Hold up. Turn out your pockets. Any candy in there? I'm not taking it. I'm just jealous.",
                    '*': "Hold it! Before you ring that bell, turn out your pockets! Any candy in there? I'm not taking it. I'm just jealous."}),
                ('doorbell', 'text', 'Pocket check complete. Lint detected.')],
    'show_candy': [('porch', 'text', {
                       'trogdor': 'Show me the candy! Hold it up to the camera! Higher! Okay. Totally acceptable haul.',
                       'dobby': 'Show Dobby the candy! Hold it up high! Dobby will not eat it! Dobby promises!',
                       '*': 'Wait! Show me your candy first! Hold it up to the camera! Higher! Okay. Very nice. You may proceed.'})],
    'jealous_door': [('porch', 'text', {
                         'boo': "Oh, I see. The door gets all the attention. The door can't even sing.",
                         'dobby': 'Dobby understands. The door is very handsome. Dobby is only a pumpkin.',
                         '*': "Oh, I see. The door is more interesting than me. The door doesn't even have a face."}),
                     ('doorbell', 'text', "I have a face. It's a camera.")],
    'too_close': [('doorbell', 'text', 'Whoa. Too close. I can see your boogers. Stand back just a little.'),
                  ('doorbell', 'text', 'The only green goblins allowed are already inside.'),
                  ('porch', 'text', {'dobby': 'The doorbell is right! Dobby saw them too! Tiny ones!',
                                     'voldemort': 'For once, the doorbell and I agree.',
                                     '*': "It's not wrong. Step back a smidge."})],
    'trapped_tip': [('inside', 'text', 'Psst! Do not ring it. They take forever. Talk to the pumpkin.'),
                    ('porch', 'text', {
                        'dobby': 'Sir is right, for once!',
                        '*': "He's right. Which is a first. Write it down."})],
}

# Visitor is standing there quietly. Short bits to keep it moving.
FILLER_BITS = {
    'help_me': [('inside', 'text', 'Psst! Help! I am trapped inside the pumpkin!'),
                ('porch', 'text', {
                    'patch': 'Ignore him. That is Voldemort. Dobby put him in there. Long story.',
                    'boo': 'Do not mind him. He is my roommate. He does not pay rent.',
                    'nibbles': 'That is Voldemort. He is in candy jail. He ate the good ones.',
                    'sorting_hat': 'Voldemort. In a pumpkin. ... I did say Slytherin.',
                    'dobby': 'Dobby cannot hear you, sir! Dobby is busy with visitors!'})],
    'secret': [('porch', 'text', {
                   'dobby': 'Dobby knows a secret! Lean in close to the pumpkin!',
                   '*': 'Want to hear a secret? Lean in close to the pumpkin.'}),
               ('inside', 'text', 'The house with the full size candy bars is down the street. You did not hear it from me.'),
               ('porch', 'text', {
                   'dobby': 'Sir! How does sir know that?',
                   '*': 'How does he know that?'})],
    'candle': [('inside', 'text', 'Could somebody blow out this candle? It is very warm in here.'),
               ('porch', 'text', {
                   'dobby': 'It is a light bulb, sir. Dobby checked.',
                   '*': 'It is an LED, Tom.'})],
    'lights_out': [('inside', 'text', 'Who turned on all these lights? The Dark Lord prefers darkness.'),
                   ('lights', 'light', 'blackout:6'),
                   ('porch', 'text', {
                       'patch': 'There. Happy now? Nobody can see my good side.',
                       'boo': 'Fine! Lights out! Very dramatic. I approve.',
                       'nibbles': 'Great. Now how am I supposed to inspect the candy?',
                       'sorting_hat': 'Very well. Darkness. Sorting by feel it is.',
                       'dobby': 'Dobby turned them off, sir! Dobby is very helpful!',
                       '*': 'There. Happy now?'}),
                   ('inside', 'text', 'Much better. Wait. Now I cannot see the candy.'),
                   ('lights', 'light', 'green:2')],
    'horcrux': [('inside', 'text', 'I split my soul into seven pieces. And one of them ended up in a gourd.'),
                ('porch', 'text', {
                    'patch': 'Excuse me. This is my gourd.',
                    'dobby': 'Dobby did not plan it, sir! Dobby only had a pumpkin!',
                    '*': 'Bad planning, Tom.'})],
    'pie': [('inside', 'text', 'One day I will rise again!'),
            ('porch', 'text', {
                'dobby': 'In November, sir. As a pie.',
                '*': 'In November. As a pie.'}),
            ('inside', 'text', 'Do not say pie.')],
    'dare': [('porch', 'text', {
                 'patch': 'Go on. Say trick or treat. I dare you.',
                 'boo': 'Give me your best boo! Loud as you can!',
                 'nibbles': 'Want a joke? Say joke. Goblins know the best jokes.',
                 'sorting_hat': 'Shall I sort you? Just say: sort me.',
                 'dobby': 'Would you like a joke? Dobby knows a joke! Just say joke!',
                 'voldemort': 'Say boo to the Dark Lord. I dare you.',
                 'trogdor': 'Say Trogdor. Go on. Say it.'})],
}
# Doorbell banter: the doorbell is a deadpan security camera that is jealous of the pumpkin.
FILLER_BITS.update({
    'jealous': [('doorbell', 'text', 'Why does everybody talk to the pumpkin?'),
                ('porch', 'text', {
                    'patch': 'Because I have a face. You have a button and a lot of opinions.',
                    'boo': 'Star quality, darling.',
                    'nibbles': 'Because I have candy opinions.',
                    'dobby': 'Because Dobby is friendly!',
                    'sorting_hat': 'Because I have a brim. You have a button.',
                    '*': 'I have a face.'}),
                ('doorbell', 'text', 'My opinions are recorded in HD.')],
    'package': [('doorbell', 'text', 'Package detected.'),
                ('porch', 'text', {
                    'dobby': 'That is not a package! That is a visitor in a costume!',
                    '*': 'That is not a package. That is a trick or treater.'}),
                ('doorbell', 'text', 'Updating records. Small package. Very cute.')],
    'motion': [('doorbell', 'text', 'Motion detected.'),
               ('porch', 'text', {
                   'patch': "Yes. It's a person. People move. That's their whole thing.",
                   'boo': 'Of course there is motion! I am waving!',
                   'nibbles': 'That was me. Inspecting.',
                   '*': 'Yes. That is a visitor.'}),
               ('doorbell', 'text', 'Motion detected.'),
               ('porch', 'text', {
                   'patch': "That was me rolling my eyes. Carefully. They're candles.",
                   '*': 'Every single time.'})],
    'rating': [('doorbell', 'text', 'Costume scan complete. Rating: excellent.'),
               ('porch', 'text', {
                   'patch': 'Since when do you rate costumes?',
                   'sorting_hat': 'I beg your pardon. Judging people is MY job.',
                   'dobby': 'Dobby agrees with the doorbell! Excellent!',
                   '*': 'Since when do you rate costumes?'}),
               ('doorbell', 'text', 'Since I got a camera. Costume: excellent. Pumpkin: needs work.'),
               ('porch', 'text', {'patch': 'HEY.', 'sorting_hat': 'Rude. Accurate, but rude.', '*': 'Hey!'})],
    'seance': [('porch', 'text', {
                   'boo': 'Everybody quiet. I am going to contact the other side.',
                   'dobby': 'Dobby will contact the spirits! Dobby has never done this!',
                   '*': 'Everybody quiet. I am going to contact the spirits.'}),
               ('lights', 'light', 'ghost:3'),
               ('porch', 'text', {
                   'boo': 'Spirits! Give us a sign!',
                   '*': 'Spirits of the porch! Give us a sign!'}),
               ('lights', 'light', 'blackout:3.5'),
               ('doorbell', 'text', 'Motion detected.'),
               ('porch', 'text', {
                   'boo': 'That is not a spirit. That is the doorbell. Again.',
                   '*': 'That is not a spirit. That is the doorbell.'}),
               ('doorbell', 'text', 'Boo.'),
               ('porch', 'text', {'*': '... Okay, that was a little spooky.'})],
    'help_doorbell': [('inside', 'text', 'Doorbell! Ring for help! Tell them the Dark Lord is trapped in a pumpkin!'),
                      ('doorbell', 'effect', 'ding-dong'),
                      ('inside', 'text', 'That was not help. That was a ding dong. I know a ding dong when I hear one.')],
    'smile': [('doorbell', 'text', 'Smile! You are on camera.'),
              ('porch', 'text', {
                  'patch': "Don't encourage it. Last week it asked for a trailer.",
                  'boo': 'Ooh! Get my good side! ... I am see through. Both sides are good.',
                  'nibbles': 'Hold your candy up. For the inspection photo.',
                  'dobby': 'Dobby is smiling! Dobby is always smiling!',
                  '*': 'Do not encourage it.'}),
              ('doorbell', 'text', 'And a stunt double.')],
})
# Bits that tell the visitor to DO something, with an urgent and ridiculous reason.
FILLER_BITS.update({
    'trogdor_duck': [('porch', 'text', 'Uh oh. Trogdor is coming up the path, and he only burninates tall people. '
                                       'Quick! Crouch down! Smaller! Tiny!', 'trogdor'),
                     ('doorbell', 'text', 'Warning. Large dragon approaching.'),
                     ('porch', 'pause', '1.5'),
                     ('lights', 'light', 'fire:3'),
                     ('porch', 'effect', 'roar'),
                     ('porch', 'pause', '1'),
                     ('porch', 'text', 'Phew. He walked right past. Great crouching. You can stand up now. '
                                       'Slowly. He is still doing his stretches.', 'trogdor')],
    'wake_doorbell': [('porch', 'text', {
                          'patch': 'The doorbell fell asleep again. Quick, wave at it! Big waves! '
                                   'If somebody rings it now, it will miss its one job.',
                          'boo': 'Darling, the doorbell has fainted! Wave at it! Big dramatic waves! It needs an audience!',
                          'nibbles': 'Psst! The doorbell is asleep. Wave at it! Quick! While it sleeps, I can eat. No. Wave!',
                          'dobby': 'The doorbell is sleeping! Wave at it! Big waves! Dobby cannot wave, Dobby is a pumpkin!',
                          'sorting_hat': 'The doorbell has dozed off. Wave at it, please. Vigorously. It is a Hufflepuff, it will not mind.',
                          'trogdor': 'The doorbell totally fell asleep. Wave at it! Big waves! Like you are flagging down a dragon!',
                          '*': 'The doorbell fell asleep. Quick, wave at it! Big waves!'}),
                      ('porch', 'pause', '3'),
                      ('doorbell', 'text', 'Motion detected. I was not asleep. I was resting my lens.')],
})

# Somebody has been on the porch a long time: a polite, escalating eviction (Pumpkin.overstay).
OVERSTAY_BITS = {
    'other_houses': [('porch', 'text', {
                         'patch': "Fun fact. There are other houses. With other candy. I'd go myself, but, you know. No legs.",
                         'boo': 'Darling, I adore you. But there are other stages. Other houses. Other candy. Go, be discovered.',
                         'nibbles': 'Fun fact! There are other houses! With other candy! I cannot go. You can. Go. Report back.',
                         'dobby': 'Dobby has news! There are other houses! With candy! Dobby will miss you, but the candy is waiting!',
                         'sorting_hat': 'A word of advice. There are other houses. Not Hogwarts houses. Houses with candy.',
                         'trogdor': 'Okay, real talk. There are other houses. With candy. I scouted them. With my beefy arm.',
                         'voldemort': 'There are other houses. Go and conquer them. Leave this one to me.',
                         '*': 'Fun fact. There are other houses. With other candy.'}),
                     ('doorbell', 'text', 'Confirmed. The house down the street has full size candy bars.'),
                     ('porch', 'text', {
                         'voldemort': 'Even the doorbell wants you gone. I respect the doorbell.',
                         '*': 'See? Even the doorbell wants you to succeed.'})],
    'moved_in': [('inside', 'text', 'Is that visitor still here? Should we start charging rent?'),
                 ('porch', 'text', {
                     'dobby': 'Sir! Dobby will make them a little bed!',
                     'sorting_hat': 'Hush, Tom. Guests are sacred. Even very, very long guests.',
                     '*': 'Shh! They can hear you!'}),
                 ('inside', 'text', 'They can have my spot. Honestly. I would love to leave.')],
    'last_call': [('lights', 'light', 'lastcall:6'),
                  ('doorbell', 'text', 'Attention. This porch closes in five minutes. Please collect your candy and your belongings.'),
                  ('porch', 'text', {
                      'patch': 'That is the doorbell saying we love you. Also, go.',
                      'boo': 'Every great show has an ending, darling. This is it. Take a bow and exit stage left.',
                      'nibbles': 'Last call for candy! There is no candy. I inspected all of it. Goodnight!',
                      'dobby': 'Dobby loves visitors! Dobby also loves it when visitors visit other houses!',
                      'sorting_hat': 'You have been sorted, entertained and very nearly adopted. Even Hufflepuffs go home eventually.',
                      'trogdor': 'Okay, the porch is closing. This is not me kicking you off. This is the doorbell. I am cool.',
                      'voldemort': 'Leave. Now. Please. The Dark Lord has a bedtime.',
                      '*': 'That is the doorbell saying we love you. Also, go.'})],
}
OVERSTAY_ORDER = ('other_houses', 'moved_in', 'last_call')
# They heard the farewell, then did not leave.
LINGERING = {'patch': 'I said goodbye. You are still here. Now it is awkward. Bye again.',
             'boo': 'This is the part where you leave and I cry dramatically. I cannot cry until you leave.',
             'nibbles': 'Still here? Are you waiting for more candy? Because I ate it. Allegedly.',
             'dobby': 'Dobby already said goodbye! Dobby will say it again! Goodbye! Dobby will never stop!',
             'sorting_hat': 'Lingering. Very Hufflepuff of you. Off you go.',
             'trogdor': 'Still here? Okay. Second goodbye. This one is way more awesome. Bye!',
             'voldemort': 'You are still here. I admire the persistence. Leave before I admire it less.'}

# Interactive bits run by Pumpkin.interactive_bit: each step is a host-keyed line.
INTERACTIVE = {
    'lumos': {
        'intro': {'dobby': 'Dobby needs help! The porch lights are frightened of the dark! Quick, point at the little camera and shout Lumos!',
                  'voldemort': 'Even the Dark Lord finds these lights gloomy. Point your wand at the little camera and shout Lumos. Now. I am waiting.',
                  'trogdor': 'Emergency! The porch lights are scared of the dark. Point at the little camera and yell Lumos! Do it awesomely!',
                  '*': 'Emergency! The porch lights are afraid of the dark. Point at the little camera and shout Lumos! Quickly, before they faint!'},
        'retry': {'*': "Louder! These are very old bulbs. They're basically grandparents. Shout Lumos!"},
        'success': {'dobby': 'It worked! Look at them shine! Dobby is so proud of the lights!',
                    'voldemort': 'Adequate. For a beginner.',
                    '*': "It worked! Look at them glow! They've never felt so seen."},
        'giveup': {'*': 'Fine. I will do it myself. Lumos!'},
        'nox_prompt': {'dobby': 'Now the lights are too excited! Shout Nox so they can sleep!',
                       '*': 'Now they are far too excited. Shout Nox to put them to bed.'},
        'nox_done': {'*': 'Goodnight, lights. They snore, you know.'},
        'nox_skip': {'*': 'Fine. They can stay up late. Just this once.'},
    },
    'inspection': {
        'intro': {'nibbles': 'Emergency candy inspection! Stand at the corner of the path and hold your bag up to the little camera. Higher! I think a raisin is trying to escape!',
                  'dobby': 'Dobby must inspect the candy! Hold your bag up to the little camera, quickly! Dobby heard a sock in there!',
                  '*': 'Emergency candy inspection! Stand at the corner of the path and hold your bag up to the little camera. Quickly! Something in there is wriggling!'},
        'hold': {'nibbles': 'Hold it right there. Do not move. I am inspecting with my eyes. For now.',
                 '*': 'Hold it still! Inspecting. Very scientifically.'},
        'done': {'nibbles': 'Inspection complete. You may keep it. I counted. I will know.',
                 '*': "Inspection complete. Everything is very legal. One item is under investigation. It's a Tootsie Roll."},
        'unseen': {'*': 'I cannot see a thing. Either that bag is invisible, or you have already eaten it all. Respect.'},
    },
    'talent': {
        'intro': {'boo': 'Quick! A talent scout is watching through the little camera by the pumpkin! Strike your scariest pose! Three, two, one!',
                  'voldemort': 'A talent scout is watching through the little camera. Strike your most evil pose. Three. Two. One.',
                  '*': 'Quick! A talent scout is watching through the little camera by the pumpkin! Strike your scariest pose! Three, two, one!'},
        'snap': {'*': 'Hold it! Hold it! Do not blink!'},
        'done': {'boo': 'Darling, you are a star. I am devastated. That was supposed to be my big break.',
                 '*': 'The scout is impressed. I have never seen them faint before.'},
        'unseen': {'*': "The scout saw nobody. Either you're a ghost or you're very, very fast. Either way: hired."},
    },
}
# Pose games (Hailo pose model on the path webcam). Same host-keyed shape as above.
INTERACTIVE.update({
    'dance': {
        'intro': {'patch': "Whoa, whoa, whoa. We don't give candy for free out here. You want candy, you gotta dance. "
                           "Back on the walkway. Go!",
                  'trogdor': "Hold up. No free candy. Rule one, you gotta dance. Back on the walkway and bust a move. Go!",
                  'sorting_hat': 'One moment. Before candy, a test of character. Step back onto the walkway and dance. Now.',
                  'dobby': 'Wait! Dobby has a rule! Candy is only for dancers! Back on the walkway and dance! Go!',
                  'voldemort': 'Halt. Nobody receives candy without entertaining the Dark Lord. Back on the walkway. Dance.',
                  '*': "No free candy! You gotta dance! Back on the walkway! Go!"},
        'great': {'patch': "Now that's dancing! My candle almost went out!",
                  'trogdor': "Whoa! Sweet moves! That's a ten. On the Strong Bad scale, which goes to eleven.",
                  'sorting_hat': 'Remarkable. Ravenclaw rhythm, with Gryffindor nerve.',
                  'dobby': 'Dobby has never seen such dancing! Dobby is crying! Happy tears!',
                  'voldemort': 'Acceptable. The Dark Lord was almost entertained.',
                  '*': "Now that's dancing!"},
        'still': {'patch': "That was standing. I've been doing that all night. I'm a professional at standing.",
                  'trogdor': 'Was that a dance? That was a guy waiting for a bus.',
                  'sorting_hat': 'Hmm. That was stillness. Very Hufflepuff. Very patient. Not dancing.',
                  'dobby': 'That was a very still dance! Dobby likes it! Dobby thinks it was a statue dance!',
                  'voldemort': 'You call that dancing? My horcruxes have more rhythm.',
                  '*': 'That was just standing!'},
        'gone': {'patch': 'And they ran away. Fair. Dancing is scary.',
                 'trogdor': 'They left! Nobody escapes the dance!',
                 'sorting_hat': 'Fled. Before the music even started. Interesting.',
                 '*': 'Where did they go? Was it the dancing?'},
        'porch': {'patch': "Hey! I couldn't see anything! That's not fair! Do it again, on the walkway!",
                  'trogdor': 'Hey, no fair! The doorbell got a private show!',
                  'sorting_hat': 'I was not consulted. A hat must see the dance to judge the dance.',
                  'dobby': 'Dobby missed it! Dobby is a pumpkin! Dobby faces the wrong way!',
                  'voldemort': 'The doorbell saw it and I did not. Unacceptable.',
                  '*': "Hey! I couldn't see anything! That's not fair!"},
    },
    'hands_up': {
        'intro': {'nibbles': "Official survey! Hands up if you like candy! Higher! I'm counting!",
                  'voldemort': 'Raise your hand if you fear the Dark Lord. Or if you like candy. Either is fine.',
                  'dobby': 'Dobby is taking a poll! Hands up if you like candy!',
                  '*': 'Quick poll! Hands up if you like candy! Way up high!'},
        'zero': {'nibbles': "Nobody? Not one hand? More for me. I mean, for inspection.",
                 '*': "Nobody? Not one hand? I'm telling the candy."},
        'one': {'*': 'One hand. Respect. You are clearly the leader around here.'},
        'some': {'nibbles': 'Lots of hands! Excellent. The candy council approves. I am the candy council.',
                 '*': 'Lots of hands! The candy council approves. The motion carries. Meeting adjourned.'},
    },
    'pumpkin_says': {
        'intro': {'*': "Let's play Pumpkin Says! Only do it if I say Pumpkin Says. Ready?"},
        's1': {'*': 'Pumpkin says: hands up!'},
        's1_ok': {'*': 'Nice! Those are some extremely haunted hands.'},
        's1_miss': {'*': "I said HANDS UP! I can see you. I'm a pumpkin, not a potato."},
        's2': {'*': 'Pumpkin says: arms out wide, like a scarecrow!'},
        's2_ok': {'*': 'Perfect scarecrows! The crows are terrified.'},
        's2_miss': {'*': 'Wider! Scarecrows are very, very wide.'},
        'trick': {'*': 'Hands on your head!'},
        'caught': {'*': "Gotcha! I didn't say Pumpkin Says! You are now a pumpkin. Congratulations."},
        'safe': {'*': "Wow. Nobody fell for it. You're too good at this. I'm a little scared."},
    },
    'flex': {
        'intro': {'trogdor': 'Okay. Show me your beefy arm. Flex it! Come on, like Trogdor!',
                  'nibbles': 'Strength test! Flex your arms! Candy bags are heavy!',
                  '*': 'Strongest costume contest! Flex your muscles! Show me those arms!'},
        'yes': {'trogdor': 'Now that is a consummate beefy arm. Trogdor would be jealous.',
                '*': 'Whoa! Huge muscles! The pumpkin is impressed and slightly worried.'},
        'no': {'trogdor': "That's more of a regular arm. We'll work on it. Eat more candy.",
               '*': "Hmm. Those are arms. I'm counting it."},
    },
})
POSE_GAMES = ('hands_up', 'pumpkin_says', 'flex', 'dance')
DANCE_DOORBELL = 'I saw it. Very nice moves. Seven out of ten.'
DANCE_DOORBELL_STILL = "I'm watching them right now. Zero dancing. They're just standing on my welcome mat."
# A visitor raised a hand: call on them, then listen patiently.
HAND_CALLS = {'patch': 'Yes! You, with the hand! Go ahead.',
              'boo': 'A question from the audience! Yes, darling?',
              'nibbles': 'Hand up! You there! Speak!',
              'sorting_hat': 'Ah. A raised hand. Very Ravenclaw. Go on.',
              'dobby': 'Oh! A hand! Dobby is listening! Dobby is all ears! Very big ears!',
              'trogdor': 'Yeah, you with the hand. Strong Bad will take one question. Make it a good one.',
              'voldemort': 'You may speak. Briefly.'}
# Now and then, one thing visitors can say or do.
HINTS = ['Psst. Say Lumos, and see what happens.',
         'Say Trogdor. I dare you.',
         'Got candy? Say: check my candy.',
         'If you have a question, raise your hand. I love questions.',
         'Want to be sorted? Just say: sort me.',
         'Say: tell me a joke. My jokes are legally jokes.']

# Hidden trick: say Lumos or Nox at any time.
SPELL_REPLIES = {'lumos': {'dobby': 'Oh! The visitor knows magic!', 'voldemort': 'Show off. Nice wand, though.',
                           '*': 'Oh, show off. Very nice.'},
                 'nox': {'voldemort': 'Finally. Darkness. Thank you.', '*': 'Hey! I was reading.'}}

# Fillers whose joke is the porch bulbs themselves; skipped when no bulbs are configured.
NEEDS_BULBS = ('lights_out', 'seance')
# Voldemort casts a spell: zap, breaking glass, the porch lights go out.
FILLER_BITS.update({
    'dark_spell': [('inside', 'text', 'Stand back. The Dark Lord will now cast a truly terrifying spell.'),
                   ('porch', 'effect', 'spell-zap'),
                   ('inside', 'text', 'Tenebris Maxima!'),
                   ('lights', 'light', 'blackout:4'),
                   ('porch', 'effect', 'glass-break'),
                   ('porch', 'text', {
                       'patch': 'Tom! Those were the porch lights!',
                       'boo': 'Darling! That was my lighting cue!',
                       'dobby': 'Sir! Dobby just changed those bulbs!',
                       'sorting_hat': 'Very dramatic, Tom. Now nobody can see anything.',
                       'trogdor': "Whoa. Okay. That was kind of awesome. Also, who's paying for that?",
                       '*': 'Tom! Those were the porch lights!'}),
                   ('inside', 'text', 'I meant to do that.'),
                   ('lights', 'light', 'green:2')],
    'dark_spell_host': [('porch', 'text', {'voldemort': 'Behold. A spell so dark, even the lights will fear it.'}),
                        ('porch', 'effect', 'spell-zap'),
                        ('lights', 'light', 'blackout:4'),
                        ('porch', 'effect', 'glass-break'),
                        ('doorbell', 'text', 'Bulb damage detected. Sending the bill to the pumpkin.'),
                        ('porch', 'text', {'voldemort': 'Put it on my tab.'}),
                        ('lights', 'light', 'green:2')],
})

# More doorbell while people are on the porch.
FILLER_BITS.update({
    'knock_knock': [('doorbell', 'text', 'Knock knock.'),
                    ('porch', 'text', {'dobby': 'Doorbell! You cannot knock! You are a doorbell!',
                                       '*': "You're a doorbell. You can't knock."}),
                    ('doorbell', 'text', 'Ding dong.'),
                    ('porch', 'text', {'*': "Fine. Who's there?"}),
                    ('doorbell', 'text', "Me. I'm always there. I can't leave. I'm screwed to the wall.")],
    'security_scan': [('doorbell', 'text', 'Security scan in progress. Scanning for candy.'),
                      ('lights', 'light', 'ghost:2'),
                      ('doorbell', 'text', 'Scan complete. Candy detected. Alerting Trogdor.'),
                      ('porch', 'text', {'dobby': 'No! Not the dragon! Dobby will hide the candy!',
                                         '*': "Do NOT alert Trogdor. He'll eat the bag. And the kid. And the porch."})],
    'porch_report': [('doorbell', 'text', 'Porch report. Temperature, spooky. Chance of candy, one hundred percent. '
                                           'Chance the pumpkin tells a bad joke, also one hundred percent.'),
                     ('porch', 'text', {'voldemort': 'And the chance of the Dark Lord escaping?',
                                        '*': 'Hey! ... Accurate.'}),
                     ('doorbell', 'text', 'This has been the porch report.')],
})
# Patch's face (owner favourite, 2026-10-26).
FILLER_BITS['scary_face'] = [
    ('porch', 'text', {'patch': 'I asked for a scary face. They gave me this. I look like I just stepped on a Lego.'}),
    ('doorbell', 'text', {'patch': 'To be fair, Patch, you also sound like you stepped on a Lego.'}),
    ('porch', 'text', {'patch': 'It was a big Lego. A spooky Lego.'})]

# The host uses a very old word; the doorbell corrects him (the reverse of 'package').
FILLER_BITS.update({
    'old_word': [
        ('porch', 'text', {'patch': 'Hark! A weary traveler approacheth, bearing a sack of sweetmeats!',
                           'trogdor': 'Whoa. That costume is totally tubular. Radical to the max.',
                           'sorting_hat': 'Ah. A young squire approaches, with a satchel full of comfits.'}),
        ('doorbell', 'text', {'patch': "Patch. Nobody has said sweetmeats in five hundred years. It's called candy.",
                              'trogdor': 'Strong Bad. Nobody has said tubular since about nineteen eighty seven. Kids say fire now.',
                              'sorting_hat': "Hat. Nobody has said comfits in five hundred years. It's called candy."}),
        ('porch', 'text', {'patch': 'Fine. A weary traveler approacheth, bearing candy.',
                           'trogdor': 'Fire?! Did somebody say Trogdor?! Where is he?!',
                           'sorting_hat': 'I am a thousand years old. Candy is a passing fad.'}),
        ('doorbell', 'text', {'patch': 'And nobody says approacheth.',
                              'trogdor': 'Not that kind of fire.',
                              'sorting_hat': 'It has been around for two hundred years, Hat.'}),
        ('porch', 'text', {'patch': 'Then how do they get here?!',
                           'trogdor': 'Then what kind?! Explain your fire!',
                           'sorting_hat': 'As I said. A fad.'})],
    'old_word_cool': [
        ('porch', 'text', {'patch': "That costume is the bee's knees! The cat's pajamas! Simply swell!",
                           'trogdor': 'Check out the getup on this one. Gnarly. Bodacious. Most excellent.',
                           'sorting_hat': 'What splendid raiment. Thy doublet is most becoming.'}),
        ('doorbell', 'text', {'patch': "Patch, that's from nineteen twenty five. Kids say fire now.",
                              'trogdor': 'Strong Bad, nobody has said bodacious in thirty years. Try slay.',
                              'sorting_hat': "Hat, it's a costume. Nobody has said doublet since Shakespeare."}),
        ('porch', 'text', {'patch': "FIRE?! Where?! I'm a pumpkin! I am extremely flammable!",
                           'trogdor': "Slay? Like, with a sword? I'm in.",
                           'sorting_hat': 'Shakespeare. Lovely boy. Terrible at candy.'}),
        ('doorbell', 'text', {'patch': 'Not real fire, Patch. It means cool.',
                              'trogdor': 'No sword.', 'sorting_hat': ''}),
        ('porch', 'text', {'patch': "Then why didn't they just say cool?!",
                           'trogdor': "Then I'm out.", 'sorting_hat': ''}),
        ('doorbell', 'text', {'patch': 'Nobody says cool anymore either.', 'trogdor': '', 'sorting_hat': ''})],
    'old_word_message': [
        ('porch', 'text', {'patch': 'Hold on. I shall send a telegram to the candy bowl. Stop. Bring candy. Stop.',
                           'trogdor': "Somebody page the candy guy! Where's my beeper?",
                           'sorting_hat': 'I shall dispatch an owl to the candy bowl at once.'}),
        ('doorbell', 'text', {'patch': "Patch. Nobody has sent a telegram in a hundred years. It's called a text.",
                              'trogdor': "Strong Bad, nobody has had a beeper since the nineties. It's called a phone.",
                              'sorting_hat': 'Hat. We have phones now. Nobody sends owls.'}),
        ('porch', 'text', {'patch': 'Groovy.',
                           'trogdor': 'Pfft. Next you will tell me my computer is outdated.',
                           'sorting_hat': 'Then whom do all the owls work for?'}),
        ('doorbell', 'text', {'patch': 'Also not a word anymore.',
                              'trogdor': 'It is.',
                              'sorting_hat': 'Honestly? Nobody knows.'}),
        ('porch', 'text', {'patch': 'Then what IS a word anymore?',
                           'trogdor': 'LIES!', 'sorting_hat': ''}),
        ('doorbell', 'text', {'patch': 'Skibidi.', 'trogdor': '', 'sorting_hat': ''}),
        ('porch', 'text', {'patch': 'Absolutely not.', 'trogdor': '', 'sorting_hat': ''})],
    'old_word_carriage': [
        ('porch', 'text', {'patch': 'Welcome! Did thy family arrive by horseless carriage?'}),
        ('doorbell', 'text', {'patch': "It's called a car, Patch. Nobody has said horseless carriage in a hundred years."}),
        ('porch', 'text', {'patch': 'Then where did all the horses go?'}),
        ('doorbell', 'text', {'patch': "... I genuinely don't know."})],
})

NO_INSIDE_FILLERS = ('dare', 'jealous', 'package', 'motion', 'rating', 'smile', 'seance', 'trogdor_duck', 'wake_doorbell',
                     'knock_knock', 'security_scan', 'porch_report', 'dark_spell_host',
                     'old_word', 'old_word_cool', 'old_word_message', 'old_word_carriage', 'scary_face')

# Somebody said "Trogdor": Strong Bad on the porch, the doorbell as deadpan narrator, trapped
# Voldemort inside. Invented fan scenes; burnination is always make-believe and the candy survives.
TROGDOR_BITS = {
    'summon': [('porch', 'text', {
                   'patch': 'Did you just say Trogdor? Out loud? On my porch?',
                   'boo': 'Darling! You said the T word! Nobody says the T word!',
                   'nibbles': 'Shh! Do not say that name! He eats candy! That is my job!',
                   'sorting_hat': 'You said the name. Nobody says the name.',
                   'dobby': 'Oh no! The visitor said the name! Dobby heard the name!',
                   'voldemort': 'You said his name. Bold. Nobody says my name either.',
                   'trogdor': 'Oh, you know Trogdor? Excellent taste. Stand back.'}),
               ('lights', 'light', 'blackout:1'),
               ('porch', 'effect', 'roar'),
               ('doorbell', 'text', 'Warning. Large dragon detected. Recommend running.'),
               ('porch', 'text', 'Relax. It is just me. Strong Bad. I do a very good roar.', 'trogdor'),
               ('doorbell', 'text', 'Correction. Small wrestler detected. Recommend ignoring.'),
               ('porch', 'text', 'Hey! Nobody asked you, button face.', 'trogdor')],
    'drawing_lesson': [('porch', 'text', 'Trogdor? Oh, you want a drawing lesson. Okay. Step one. Draw an S.', 'trogdor'),
                       ('porch', 'text', "Step two. Spikes. Lots of consummate V's.", 'trogdor'),
                       ('porch', 'text', 'Step three. One beefy arm. Just one. Two would be ridiculous.', 'trogdor'),
                       ('inside', 'text', 'This is the worst art class I have ever been trapped inside.'),
                       ('lights', 'light', 'fire:3'),
                       ('porch', 'text', 'Quiet, pumpkin guy. Boom. Masterpiece. You are an artist now.', 'trogdor')],
    'door_visit': [('doorbell', 'text', 'Ding dong. Trogdor is here to see you.'),
                   ('porch', 'text', {
                       'patch': 'Do not open the door. I am a pumpkin. I am basically a snack.',
                       'nibbles': 'Do not open the door! Hide the chocolate! Hide me!',
                       'dobby': 'Dobby will not open the door! Dobby is very brave from back here!',
                       'trogdor': 'Tell him I am not home. I am a famous artist. I am busy.',
                       '*': 'Do not open the door!'}),
                   ('doorbell', 'effect', 'roar'),
                   ('doorbell', 'text', 'He says he only wants the candy. And the welcome mat.'),
                   ('porch', 'text', "Tell him the welcome mat's already burninated. Emotionally.", 'trogdor'),
                   ('inside', 'text', 'Finally! Someone who understands my decorating style.')],
    'dark_lord_vs_dragon': [('inside', 'text', 'Did somebody say Trogdor? Dragon! I command you to free me!'),
                            ('porch', 'effect', 'roar'),
                            ('porch', 'text', 'Uh, Trogdor does not take commands. Trogdor takes candy.', 'trogdor'),
                            ('inside', 'text', 'I am the Dark Lord!'),
                            ('porch', 'text', 'And I am Strong Bad. We are both stuck on this porch. Deal with it.', 'trogdor'),
                            ('porch', 'effect', 'chomp'),
                            ('inside', 'text', 'He ate my candle. I was using that.')],
    'cardboard': [('porch', 'effect', 'roar'),
                  ('porch', 'text', {
                      'patch': 'Oh no. Is that him? Is that the Burninator?',
                      'boo': 'A dragon! Finally, someone more dramatic than me!',
                      'nibbles': 'Is that him? Is he after the candy? Get behind me. Not too close to the bag.',
                      'sorting_hat': 'A dragon approaches. Hmm. Gryffindor, surely.',
                      'dobby': 'Dobby sees a dragon! A very flat dragon!',
                      'voldemort': 'A dragon. At last, a servant worthy of me.',
                      'trogdor': 'Oh no. Who could that be? Definitely a real dragon.'}),
                  ('porch', 'text', 'Yes. Totally the real Trogdor. Definitely not cardboard with marker on it.', 'trogdor'),
                  ('lights', 'light', 'blackout:1'),
                  ('doorbell', 'text', 'Scan complete. That dragon is cardboard.'),
                  ('porch', 'text', 'You are such a snitch, doorbell.', 'trogdor')],
    'frog_door': [('doorbell', 'text', 'Searching for Trogdor. Did you mean: frog door?'),
                  ('porch', 'text', 'No! Trogdor! The Burninator! Big dragon! Beefy arm!', 'trogdor'),
                  ('doorbell', 'text', 'Showing results for: beefy frog.'),
                  ('porch', 'text', {
                      'patch': 'Honestly, a beefy frog would also be terrifying.',
                      'boo': 'A beefy frog! Now that is a show I would pay for.',
                      'nibbles': 'Does the beefy frog eat candy? Because then we have a problem.',
                      'dobby': 'Dobby would like to meet the beefy frog!',
                      'trogdor': 'You know what? Beefy frog. I will allow it.',
                      '*': 'Honestly, a beefy frog would also be terrifying.'})],
}
# Existing cast routines that also star Trogdor; mixed into the rotation.
TROGDOR_ROUTINES = ('trogdor_candy', 'trogdor_hat', 'trogdor_rescue')

SPELL_BIT = [('porch', 'text', 'Behold! Let the very foundations tremble!'),
             ('lights', 'light', 'lightning:1.2'),
             ('doorbell', 'effect', 'ding-dong'),
             ('porch', 'text', 'I appear to have summoned the doorbell.')]
RING_FALLBACK = 'Yes, yes, we heard it. The whole porch heard it. The moon heard it.'

# Sidewalk passers-by, far away: one loud line to pull them up the path.
LURES = {
    'patch': ['Hey! Trick or treaters! The talking pumpkin is open!',
              'Psst! Up here! Yes, the pumpkin. Come on up.'],
    'boo': ["Yoo hoo! Over here! Free haunting! No refunds! Mostly no screaming!",
            "Hey! You! Come see the ghost! I'm very scary! Ish! Bring friends, I need the numbers!"],
    'nibbles': ["Hey! You with the bag! Free candy reviews! Up the path!",
                "Psst! World-famous candy critic, right here! No autographs! Okay, one autograph!"],
    'sorting_hat': ["You there! Come and be sorted! It's quick, it's free, and I've only been wrong once. ... Twice."],
    'dobby': ['Hello! Hello down there! Dobby has visitors! Hopefully!'],
    'voldemort': ['You there. Come closer. The Dark Lord requires an audience.'],
    'trogdor': ["Hey! You! Yeah, you, in the costume. Get over here. Strong Bad needs an audience and you're it."],
}

FAREWELLS = {
    'patch': ['Bye! Tell your friends about the talking pumpkin. Nobody will believe you.',
              "Bye! I'll just be here. Staring at the street. Being a vegetable. ... Technically a fruit.",
              'See you next year! ... Probably not me. I will be pie by then.'],
    'boo': ["Farewell! Exit stage left! ... Your other left.",
            "Goodbye! Tell everyone the ghost was terrifying. Leave out the part where I fell through the floor.",
            "Bye! If you see a ghost named Gary, tell him I'm doing great. Huge porch. Massive crowds."],
    'nibbles': ["Bye! If you get any raisins, I'll dispose of them for you. Safely. In the garden.",
                "Wait! I didn't review your bag! Come back next year! I'll still be under the porch!",
                "Bye! Five stars! You were delicious. Company! You were delicious company!"],
    'sorting_hat': ['Your house is decided. Further appeals must be addressed to a different hat.',
                    'Off you go! Represent your house! I have already forgotten which one.',
                    'Farewell! Do write. Hats rarely get mail.'],
    'dobby': ['Goodbye! Dobby will miss you! Dobby misses you already! You are still on the driveway!',
              'Bye bye! Be careful! Dobby will guard the candy! Very closely!'],
    'voldemort': ['Go. Run. Tell everyone the Dark Lord has returned. ... Leave out the pumpkin part.',
                  'Yes, flee! Flee in terror! ... Or just walk. Walking is fine.'],
    'trogdor': ['Later! If you see Trogdor, tell him he owes me a candy bowl.',
                'Bye! Remember: consummate V\'s.'],
}


def host_text(value, character):
    if isinstance(value, dict):
        return value.get(character, value.get('*'))
    return value


def resolve(scene, character):
    """Return concrete (target, kind, text, actor) steps for this host, or None if unsupported."""
    steps = []
    for step in scene:
        target, kind, value = step[:3]
        actor = step[3] if len(step) > 3 else (INSIDE_ACTOR if target == 'inside'
                                                  else 'doorbell' if target == 'doorbell' else character)
        text = host_text(value, character)
        if text is None:
            return None
        if text == '':
            continue  # This host's version of the scene is shorter.
        steps.append((target, kind, text, actor))
    return steps


def uses_inside(scene):
    return any(step[0] == 'inside' for step in scene)


def choose(bank, previous=None, character='patch', inside=True, chime=False, doorbell=True, rng=random):
    options = [key for key, scene in bank.items()
               if key != previous and resolve(scene, character) is not None
               and (inside or not uses_inside(scene))
               and (doorbell or not any(step[0] == 'doorbell' for step in scene))]
    return rng.choice(options) if options else None


def choose_bit(previous=None, chime=False, rng=random, character='patch', inside=True, doorbell=True):
    return choose(DOORBELL_BITS, previous, character, inside, chime, doorbell, rng)


def farewell(character, previous=None, rng=random):
    return rng.choice([line for line in FAREWELLS[character] if line != previous] or FAREWELLS[character])


def lure(character, previous=None, rng=random):
    lines = LURES.get(character) or LURES['patch']
    return rng.choice([line for line in lines if line != previous] or lines)


def scene_lines(scene):
    """Every (actor, text) a scene can speak across all hosts, for pre-rendering."""
    from core import CHARACTERS
    rows = set()
    for step in scene:
        target, kind, value = step[:3]
        if kind != 'text':
            continue
        hosts = CHARACTERS if isinstance(value, dict) else (None,)
        for host in hosts:
            text = host_text(value, host) if host else value
            if not text:
                continue
            actor = step[3] if len(step) > 3 else (INSIDE_ACTOR if target == 'inside'
                                                      else 'doorbell' if target == 'doorbell' else host)
            if actor is None:
                rows.update((name, text) for name in CHARACTERS)
            else:
                rows.add((actor, text))
    return rows


ALL_SCENES = (list(DOORBELL_BITS.values()) + list(RING_AGAIN_BITS.values()) + list(RING_THIRD_BITS.values())
              + list(PREMATURE_RING_BITS.values()) + [[('doorbell', 'text', DANCE_DOORBELL)], [('doorbell', 'text', DANCE_DOORBELL_STILL)]]
              + list(DOORSTEP_BITS.values())
              + list(FILLER_BITS.values()) + list(TROGDOR_BITS.values()) + list(OVERSTAY_BITS.values()) + [SPELL_BIT])
AUTHORED_LINES = set()
for _scene in ALL_SCENES:
    AUTHORED_LINES.update(text for _, text in scene_lines(_scene))
AUTHORED_LINES.update(line for lines in FAREWELLS.values() for line in lines)
AUTHORED_LINES.update(line for lines in LURES.values() for line in lines)
AUTHORED_LINES.add(RING_FALLBACK)
AUTHORED_LINES.update(line for replies in QUICK_REPLIES.values() for line in replies.values())
AUTHORED_LINES.update(line for _, replies in MORE_REPLIES for line in replies.values())
AUTHORED_LINES.update(line for lines in REACTIONS.values() for line in lines)
AUTHORED_LINES.update(HECKLES)
AUTHORED_LINES.update(LINGERING.values())
AUTHORED_LINES.update(HAND_CALLS.values())
AUTHORED_LINES.update(HINTS)
AUTHORED_LINES.add(DANCE_DOORBELL)
# Spoken by the controller itself (offering game, normal-mode switch) for any host.
CONTROLLER_LINES = ('No candy? That is fine. I cannot eat it anyway. No stomach.',
                    'Keep it. Honestly, I just wanted to see if you would.',
                    'Normal mode. Our special guest has left the porch. Probably through the cat flap.')
AUTHORED_LINES.update(CONTROLLER_LINES)
for _steps in list(INTERACTIVE.values()) + [SPELL_REPLIES]:
    for _lines in _steps.values():
        AUTHORED_LINES.update(_lines.values())


def interactive_lines():
    """(actor, text) for every interactive line any host can say, for pre-rendering."""
    from core import CHARACTERS
    rows = set()
    for steps in list(INTERACTIVE.values()) + [SPELL_REPLIES]:
        for lines in steps.values():
            rows.update((host, host_text(lines, host)) for host in CHARACTERS if host_text(lines, host))
    rows.update(LINGERING.items())
    rows.update(HAND_CALLS.items())
    rows.update((host, line) for host in CHARACTERS for line in RING_INTERRUPTED.get(host, RING_INTERRUPTED['*']))
    rows.update((host, line) for host in CHARACTERS for line in HINTS)
    rows.update((host, line) for host in CHARACTERS for line in CONTROLLER_LINES)
    return rows
