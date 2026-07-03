import ast
import math
import os

import kenlm
import Levenshtein
import numpy as np
import pandas as pd
import torch


def calculate_cer(true_sentence, model_prediction):
    distance = Levenshtein.distance(true_sentence, model_prediction)
    cer = distance / len(true_sentence)
    return cer

def calculate_wer(true_sentence, model_prediction):
    true_words = true_sentence.lower().split()
    pred_words = model_prediction.lower().split()
    distance = Levenshtein.distance(true_words, pred_words)
    wer = distance / max(len(true_words), 1)
    return wer

original_mapping = {
        's': 0, 'o': 1, 't': 2, 'e': 3, 'n': 4, 'c': 5, 'i': 6, 'a': 7, ' ': 8, 
        'd': 9, 'l': 10, 'r': 11, 'b': 12, '@': 13, 'z': 14, 'v': 15, 'f': 16, 
        'm': 17, 'u': 18, 'h': 19, 'p': 20, 'g': 21, 'q': 22, 'w': 23, 'x': 24, 'y': 25, 
        'j': 26, 'k': 27, '9': 28
                    }

inverted_mapping = {v: k for k, v in original_mapping.items()}

char2id = {
        's': 0, 'o': 1, 't': 2, 'e': 3, 'n': 4, 'c': 5, 'i': 6, 'a': 7, '&': 8, 
        'd': 9, 'l': 10, 'r': 11, 'b': 12, '@': 13, 'z': 14, 'v': 15, 'f': 16, 
        'm': 17, 'u': 18, 'h': 19, 'p': 20, 'g': 21, 'q': 22, 'w': 23, 'x': 24, 'y': 25, 
        'j': 26, 'k': 27, '9': 28
}
id2char = {v: k for k, v in char2id.items()}

def input_preprocessing(inputs):
    new_input = []
    for elem in inputs:
        # Convert string → Python object (list of lists)
        if isinstance(elem, str):
            elem = ast.literal_eval(elem)
        new_input.append(elem)

    # Optional sanity check
    for i in range(len(new_input)):
        for j in range(len(new_input[i])):
            assert len(new_input[i][j]) == 29

    return new_input

def df_preprocessing(df, n_samples=None):
    if n_samples:
        little_df = df.iloc[:n_samples]
    else:
        little_df = df
    inputs = little_df["Logits"].tolist()
    inputs = input_preprocessing(inputs)
    labels = little_df["True Sentences"].tolist()

    return inputs, labels

def decode_sentence(inputs):
    result = []
    for sublist in inputs:
        max_index = sublist.index(max(sublist))
        mapped_char = id2char[max_index]
        result.append(mapped_char)
    result = "".join(result)
    return result

import typing as tp


def logsumexp(*xs: float) -> float:
    """Stable log-sum-exp to sum probabilities in log-space.
    Ref for example http://gregorygundersen.com/blog/2020/02/09/log-sum-exp/.

    We could use `scipy.special.logsumexp`, but it's slower owing to implicit
    `numpy.ndarray` conversion."""
    x_max = max(xs)
    if x_max == -np.inf:
        return -np.inf
    return x_max + math.log(sum(math.exp(x - x_max) for x in xs))

class BeamState:

    def __init__(self, sentence: str, score: float, lm_state: kenlm.State = None):
        self.sentence = sentence
        self.score = score
        self.lm_state = lm_state or kenlm.State()

    def __repr__(self):
        return self.sentence

class Decoder:

    def __init__(self, lm: kenlm.Model, beam_size: int = 5, max_labels_per_timestep: int = 10, lm_weight: float = 1, id2char: tp.Dict[int, str] = None):
        self.lm = lm
        self.beam_size = beam_size
        self.id2char = id2char
        self.max_labels_per_timestep = max_labels_per_timestep
        self.lm_weight = lm_weight

    def text_preproc(self, text: str) -> str:
        text = text.lower()
        text = text.replace(" ", "&")
        text = " ".join(text)
        return text

    def decode_greedy(self, emissions: torch.Tensor) -> str:
            
        sentence = ""
        for logits in emissions:
            idx = logits.argmax()
            char = self.id2char[idx.item()]
            sentence += char
        sentence = sentence.replace("&", " ")
        return sentence

    def decode(self, emissions: torch.Tensor) -> str:

        self.beam = [BeamState(sentence = "", score = 0)]
        self.lm.BeginSentenceWrite(self.beam[0].lm_state)
        
        for logits in emissions:
            self.step(logits)

        return self.beam[0].sentence.replace("&", " ")
    
    def step(self, logits: torch.Tensor):

        new_beam = []
        logits = torch.softmax(logits, dim = 0)
        idx = logits.argsort(descending = True)
        top_indices = idx[:self.max_labels_per_timestep]

        for hyp in self.beam:
            sentence, score = hyp.sentence, hyp.score
            for idx in top_indices:
                char = self.id2char[idx.item()]
                if char.isdigit():
                    continue
                new_sentence = sentence + char

                new_state = kenlm.State()
                lm_score = self.lm.BaseScore(hyp.lm_state, char, new_state)
                lm_score *= self.lm_weight
                brain_score = torch.log(logits[idx])
                new_score = score + lm_score + brain_score
                new_beam.append(BeamState(sentence = new_sentence, score = new_score, lm_state = new_state))

        new_beam = sorted(new_beam, key = lambda x: x.score, reverse = True) 
        self.beam = new_beam[:self.beam_size]

def compute_cer_wer(decoder, inputs, labels):
    decodeds = []
    cers = {"cer_beam": [], "wer_beam": []}
    for i, (emissions, true) in enumerate(zip(inputs, labels)):
        emissions = torch.tensor(emissions)
        decoded = decoder.decode(emissions)
        decodeds.append(decoded)
        
        cer_beam = (lev.distance(true, decoded) / len(true))
        true_words, beam_words = true.split(" "), decoded.split(" ")
        wer_beam = lev.distance(true_words, beam_words) / len(true_words)
        
        cers['cer_beam'].append(cer_beam)
        cers['wer_beam'].append(wer_beam)

    general_CER = np.mean(cers['cer_beam'])
    general_WER = np.mean(cers['wer_beam'])
    print(f"CER: {general_CER:.3f}, WER: {general_WER:.3f}")
    return decodeds


if __name__ == "__main__":
    _brainai_root = os.environ.get("BRAINAI_ROOT", os.path.expanduser("~/brainai"))
    _data_root = os.environ.get("BRAINAI_DATA_ROOT", os.path.join(_brainai_root, "data"))
    _predictions_dir = os.path.join(_data_root, "prediction_csv")
    _lm_dir = os.path.join(_data_root, "lm_arpa_files")

    predictions_df = pd.read_csv(os.path.join(_predictions_dir, "reviews_MEG_ConvTrans.csv"), index_col=0)
    inputs, labels = df_preprocessing(predictions_df, len(predictions_df))
    print(len(inputs), len(labels))
    predictions_df['Subject'].unique().sort()
    print(predictions_df['Subject'].nunique())
    model = kenlm.Model(os.path.join(_lm_dir, "news_9gram.arpa"))
    decoder = Decoder(model, id2char = id2char, lm_weight=5, beam_size=30, max_labels_per_timestep=50)
    decodeds = compute_cer_wer(decoder, inputs, labels)
    predictions_df["best_LM_predictions"] = decodeds
    predictions_df['CER_LM'] = predictions_df.apply(lambda row: calculate_cer(row['True Sentences'], row['best_LM_predictions']), axis=1)
    predictions_df['WER_LM'] = predictions_df.apply(lambda row: calculate_wer(row['True Sentences'], row['best_LM_predictions']), axis=1)

    n_subjects = len(predictions_df['Subject'].unique())
    CER_results = []
    for subject in predictions_df['Subject'].unique():
        subject_df = predictions_df[predictions_df['Subject'] == subject]
        CER_results.append(subject_df['CER_LM'].mean())

    print(np.mean(CER_results))

    WER_results = []
    for subject in predictions_df['Subject'].unique():
        subject_df = predictions_df[predictions_df['Subject'] == subject]
        WER_results.append(subject_df['WER_LM'].mean())

    print(np.mean(WER_results))
    print(WER_results)

    predictions_df.to_csv(os.path.join(_predictions_dir, "reviews_MEG_Brain2Qwerty.csv"))