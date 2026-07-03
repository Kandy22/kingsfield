import typing as tp
from collections import defaultdict

import numpy as np
from Levenshtein import distance as levenshtein_distance

import neuralset as ns

keyboard_layout = {
    'q': (0, 0), 'w': (1, 0), 'e': (2, 0), 'r': (3, 0), 't': (4, 0), 'y': (5, 0), 'u': (6, 0), 'i': (7, 0), 'o': (8, 0), 'p': (9, 0),
    'a': (0, 1), 's': (1, 1), 'd': (2, 1), 'f': (3, 1), 'g': (4, 1), 'h': (5, 1), 'j': (6, 1), 'k': (7, 1), 'l': (8, 1),
    'z': (0, 2), 'x': (1, 2), 'c': (2, 2), 'v': (3, 2), 'b': (4, 2), 'n': (5, 2), 'm': (6, 2), '<space>': (2,3), 
}

# Those characters are not present in standard QWERTY KEYBOARD
# "<number>", '<special>':(5,1),'ý': (10,0), '\x14': (10,0), 'ü': (10,0), 'û': (10,0), '£': (10,0), '¤': (10,0), '-': (5,1), '¿': (5,1), '\u0060': (5,1),

def shuffle_sentences(
    segments: tp.List[ns.segments.Segment],
) -> tp.List[ns.segments.Segment]:
    """
    Shuffles the segments by blocks of sentences.
    """
    segment_dict = defaultdict(list)
    for segment in segments:
        key = (segment._trigger["timeline"], segment._trigger["sequence_id"])
        segment_dict[key].append(segment)
    keys = list(segment_dict.keys())
    np.random.shuffle(keys)
    res = [segment for key in keys for segment in segment_dict[key]]
    return res

class ShuffledSegmentDataset(ns.SegmentDataset):
    def shuffle(self):
        self.segments = shuffle_sentences(self.segments)

def compute_levenshtein_distance(word, word_set, threshold = 3):
    closest_word = word
    min_distance = float('inf')
    
    for candidate in word_set:
        dist = levenshtein_distance(word, candidate)
        if dist < min_distance:
            min_distance = dist
            if dist <= threshold:
                closest_word = candidate
            
    return closest_word

def find_nearest(sentence, word_corpus):
    corrected_words = []
    for word in sentence.split():
        corrected_word = compute_levenshtein_distance(word, word_corpus)
        corrected_words.append(corrected_word)
    corrected_sentence = ' '.join(corrected_words)
    return corrected_sentence


def compute_accuracy(labeled, corrected):
    matches = sum(1 for a, b in zip(labeled, corrected) if a == b)
    max_length = max(len(labeled), len(corrected))
    return matches / max_length if max_length > 0 else 0

def calculate_distancekeyboard(key1, key2):
    if key1 in keyboard_layout and key2 in keyboard_layout:
        x1, y1 = keyboard_layout[key1]
        x2, y2 = keyboard_layout[key2]
        return np.sqrt((x2 - x1)**2 + (y2 - y1)**2)
    return 0
