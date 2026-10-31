"""Generate original fantasy-character auditions on the host GPU."""
import json
import argparse
import os
from pathlib import Path
import time

import numpy as np
import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'runtime' / 'voice-auditions'
DESIGNS = {
    'patch': {
        'text': 'Well, well, well. Fresh visitors! Come closer, my little trick or treaters. I would offer you a hand, but somebody carved mine off. Happy Halloween!',
        'instruct': 'An original Halloween talking jack-o-lantern character. A very deep, gravelly, hoarse old male monster voice with strong audible rasp, creaky vocal fry, dry crackly growl and a crooked mischievous smile. Dark rounded resonant vowels, slightly slow and theatrical with playful pauses. Warmly wicked and funny rather than genuinely threatening. Every word clear. An expressive creature performance with a small raspy chuckle in the delivery. The rasp is an essential part of the voice, not a clean narrator.',
    },
    'boo': {
        'text': 'Boooo! Oh, do come in. I have been dying for some company. Well, technically, that part is finished. Tell me, what brings you to my haunted porch?',
        'instruct': 'An original eccentric haunted-house ghost character. An airy, breathy, eerie old theatrical female ghost with a hollow, wavering, spectral voice, delicate huskiness and a trembling creaky undertone. Slowly float between hushed words and melodramatic little rises in pitch. Draw out Boo as a playful ghostly moan, then sound deliciously amused by the joke. Crisp intelligible English, whimsical spooky storyteller, intimate and ethereal, with no added reverb or sound effects.',
    },
    'nibbles': {
        'text': 'Heh heh! What have we here? A suspicious shortage of chocolate! I am Nibbles, chief candy inspector. Open your treat bag. This is a very unofficial investigation!',
        'instruct': 'An original scruffy little Halloween goblin creature. A high-mid pitched male goblin voice with pronounced nasal twang, scratchy rasp, gravel in the throat, croaky squeaks and a sly impish cackle. Extremely expressive, quick playful bursts separated by conspiratorial little pauses, stretching suspicious words with glee. Comically greedy about candy, cheeky and mischievous, friendly enough for young trick-or-treaters. Clear articulate English. A distinct rough textured creature voice, not a polished announcer.',
    },
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--songs', action='store_true')
    parser.add_argument('--hammy', action='store_true')
    parser.add_argument('--astra', action='store_true')
    args = parser.parse_args()
    designs = DESIGNS
    output = OUT
    if args.astra:
        data = json.loads((ROOT / 'docs/VOICE_REFINEMENT.json').read_text())
        designs = {p['id']: {'text': p['audition_text'], 'instruct': p['voice_prompt']}
                   for p in data['profiles']}
        assert set(designs) == set(DESIGNS), 'Expected exactly three directed voices'
        output = ROOT / 'runtime' / 'voice-auditions-v3'
    if args.hammy:
        output = ROOT / 'runtime' / 'voice-auditions-v2'
        designs = {
            'patch': {
                'text': 'Well. I am an ancient terror of the night. Unfortunately, the squirrels have discovered I am seasonal. Come for the candy? Sensible. I came for the atmosphere. Now I am furniture.',
                'instruct': 'An extremely characterful elderly jack-o-lantern creature, theatrical Halloween comedy. Low-mid baritone with woody chest resonance, very audible dry gravel and a dried-leaf creak. Strong raspy, rough, hoarse vocal texture. Crisp consonants that carry outdoors. Ceremonial ancient dignity, slow dramatic pauses, then a dry crooked grin on the punchline. Big comic contrast: solemn monster proclamation collapses into a grumbled practical complaint. Warm, mischievous, deeply amused. Let amusement crackle in the rasp, with one short gruff chuckle. Exaggerated hammy acting, not clean narration, not muddy sub-bass. Sound like an actual strange old pumpkin creature.'},
            'boo': {
                'text': 'Beware the terror of the night! Oh, you waved. That is lovely. I have completely lost my doom. Boo! No, wait. I forgot to brood. Boo. Better. More eyebrows.',
                'instruct': 'A very hammy original haunted-theater ghost character, expressive adult lyric tenor. Hollow floating spectral resonance with a wispy breath and a creaky wavering undertone. Exaggerated rounded theatrical vowels and grand stage projection. Begin magnificently ominous with a drawn-out ghostly vowel, then suddenly become delighted, small and conspiratorial. Collapse into embarrassed backstage asides, then try grand spooky acting again. Clearly audible alternation between ghostly grandeur and comic embarrassment. Warm vocal center, precise diction, buoyant pitch changes. No screaming or added echo. A strange eerie character, not an ordinary announcer.'},
            'nibbles': {
                'text': 'Nibbles! Pretend candy inspector. Real goblin. Fake clipboard. My qualifications are mostly crumbs. Now, this raisin. Why is it dressed like a retired grape? Heh heh heh!',
                'instruct': 'An outrageously hammy little adult Halloween goblin creature. Wiry upper-middle voice, very strong forward nasal buzz, scruffy scratchy rasp and a papery throaty rattle. Croaky squeaks, pointed energetic consonants, gleeful cartoon-villain rhythm. Overpronounce the pretend official job, drop into a conspiratorial gravelly murmur, then pop back up with delighted disbelief. Clean pauses before punchlines. One short nasal cackle. Mischievous, crooked and absurdly self-important, unmistakably inhuman goblin texture but friendly and intelligible. No helium pitch, childlike voice, screeching or polished narration.'},
        }
    if args.songs:
        from games import GAMES
        output = ROOT / 'runtime' / 'songs'
        designs = {
            scene['clip']: {'text': scene['lyrics'],
                'instruct': DESIGNS[scene['performer']]['instruct'] +
                ' SING this short original Halloween jingle to a cheerful simple bouncy tune. '
                'Use clearly musical rising and falling sung notes, playful rhythm and an exaggerated theatrical performance. '
                'A tiny silly musical treat for children. No instrumental background, only the character singing.'}
            for scene in GAMES.values() if scene.get('clip')}
    output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(4)
    assert torch.cuda.is_available(), 'Host GPU required for this audition'
    model = Qwen3TTSModel.from_pretrained(
        'Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign', device_map='cuda:0',
        dtype=torch.bfloat16, attn_implementation='sdpa')
    for index, (name, design) in enumerate(designs.items()):
        torch.manual_seed(3100 + index)
        started = time.monotonic()
        waves, rate = model.generate_voice_design(
            text=design['text'], language='English', instruct=design['instruct'],
            max_new_tokens=1400)
        audio = np.asarray(waves[0], dtype=np.float32)
        assert audio.ndim == 1 and len(audio) > rate, 'Audition too short'
        assert np.isfinite(audio).all(), 'Invalid audio samples'
        peak = float(np.max(np.abs(audio)))
        assert peak > .01, 'Silent audition'
        audio = audio / peak * .7
        sf.write(output / (name + '.wav'), audio, rate, subtype='PCM_16')
        metadata = {**design, 'model': 'Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign',
                    'seed': 3100 + index, 'seconds': round(len(audio) / rate, 2),
                    'generation_seconds': round(time.monotonic() - started, 2)}
        (output / (name + '.json')).write_text(json.dumps(metadata, indent=2))
        print(json.dumps({'character': name, **{k: metadata[k] for k in ('seconds', 'generation_seconds')}}), flush=True)


if __name__ == '__main__':
    main()
