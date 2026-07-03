import ast
import os
import typing as tp

import kenlm
import Levenshtein as lev
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch

DATA_ROOT = os.environ.get("BRAINAI_DATA_ROOT", os.path.expanduser("~/brainai"))

# --- Configuration ---
OUTPUT_DIR = os.path.join(DATA_ROOT, "prediction_csv")
LM_WEIGHTS = [1.0, 2.0, 5.0, 6.0, 8.0, 10.0]
LM_PATH = os.path.join(DATA_ROOT, "lm_arpa_files", "news_9gram.arpa")
# ---------------------

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

# --- Helper Classes & Functions ---

def calculate_cer(true_sentence, model_prediction):
    distance = lev.distance(true_sentence, model_prediction)
    cer = distance / len(true_sentence)
    return cer

def calculate_wer(true_sentence, model_prediction):
    true_words = true_sentence.lower().split()
    pred_words = model_prediction.lower().split()
    distance = lev.distance(true_words, pred_words)
    wer = distance / max(len(true_words), 1)
    return wer

def input_preprocessing(inputs):
    new_input = []
    for elem in inputs:
        if isinstance(elem, str):
            elem = ast.literal_eval(elem)
        new_input.append(elem)
    
    # Sanity check
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
        wer_beam = lev.distance(true_words, beam_words) / max(len(true_words), 1)
        
        cers['cer_beam'].append(cer_beam)
        cers['wer_beam'].append(wer_beam)

    general_CER = np.mean(cers['cer_beam'])
    general_WER = np.mean(cers['wer_beam'])
    return decodeds, general_CER, general_WER


def evaluate_dataset(model, csv_path, dataset_name):
    """
    Handles loading, decoding, saving CSV results, and plotting for a single dataset.
    """
    print(f"\n=== Processing {dataset_name} ===")
    
    if not os.path.exists(csv_path):
        print(f"File not found: {csv_path}")
        return

    predictions_df = pd.read_csv(csv_path, index_col=0)
    inputs, labels = df_preprocessing(predictions_df, len(predictions_df))
    print(f"Loaded {len(inputs)} samples from {dataset_name}.")
    
    results_data = []

    for weight in LM_WEIGHTS:
        print(f"[{dataset_name}] Processing lm_weight: {weight}")
        
        decoder = Decoder(model, id2char=id2char, lm_weight=weight, beam_size=30, max_labels_per_timestep=50)
        decodeds, mean_cer, mean_wer = compute_cer_wer(decoder, inputs, labels)
        
        print(f"--> Result: CER={mean_cer:.4f}, WER={mean_wer:.4f}")
        
        results_data.append({
            "lm_weight": weight,
            "mean_cer": mean_cer,
            "mean_wer": mean_wer
        })

    # Save Results CSV
    results_df = pd.DataFrame(results_data)
    save_csv_path = os.path.join(OUTPUT_DIR, f"lm_weight_results_{dataset_name}.csv")
    results_df.to_csv(save_csv_path, index=False)
    print(f"Results saved to: {save_csv_path}")

    # Generate Plot
    plt.figure(figsize=(10, 6))
    plt.plot(results_df['lm_weight'], results_df['mean_cer'], marker='o', linestyle='-', color='b', label='CER')
    plt.title(f'{dataset_name} Performance: CER vs LM Weight')
    plt.xlabel('LM Weight')
    plt.ylabel('Character Error Rate (CER)')
    plt.grid(True)
    plt.xticks(LM_WEIGHTS)
    plt.legend()
    
    plot_path = os.path.join(OUTPUT_DIR, f"cer_vs_lm_weight_{dataset_name}.png")
    plt.savefig(plot_path)
    plt.close() # Close figure to free memory
    print(f"Plot saved to: {plot_path}")


if __name__ == "__main__":
    # Ensure output directory exists
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    # Load LM ONLY ONCE
    print(f"Loading KenLM Model from {LM_PATH}...")
    model = kenlm.Model(LM_PATH)
    
    # Process MEG
    evaluate_dataset(model, os.path.join(DATA_ROOT, "prediction_csv", "reviews_MEG_ConvTrans.csv"), "MEG")
    
    # Process EEG
    evaluate_dataset(model, os.path.join(DATA_ROOT, "prediction_csv", "reviews_EEG_ConvTrans.csv"), "EEG")

    print("\nAll processing complete.")