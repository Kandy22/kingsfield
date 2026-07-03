import os

import pandas as pd

_BRAINAI_ROOT = os.environ.get("BRAINAI_ROOT", os.path.expanduser("~/brainai"))
_DATA_ROOT = os.environ.get("BRAINAI_DATA_ROOT", os.path.join(_BRAINAI_ROOT, "data"))
_TEMP_DATA_DIR = os.path.join(_DATA_ROOT, "temp_data")


def add_detected_buttons(events, study_name):
    if study_name == "Pinet2024Meg":
        val_detected_onsets = pd.read_json(os.path.join(_TEMP_DATA_DIR, "MEG_detected_onsets_seed1_val.json"), typ='series')
        test_detected_onsets = pd.read_json(os.path.join(_TEMP_DATA_DIR, "MEG_detected_onsets_seed1_test.json"), typ='series')
    elif study_name == "Pinet2024Eeg":
        val_detected_onsets = pd.read_json(os.path.join(_TEMP_DATA_DIR, "EEG_detected_onsets_seed1_val.json"), typ='series')
        test_detected_onsets = pd.read_json(os.path.join(_TEMP_DATA_DIR, "EEG_detected_onsets_seed1_test.json"), typ='series')
    else:
        raise ValueError(f"Study name {study_name} not supported")

    all_detected_onsets = pd.concat([val_detected_onsets, test_detected_onsets])
    buttons = events[events['type'] == 'Button']
    sentence_events = events[events['type'] == 'Sentence']
    segment_start_map = sentence_events.set_index('sentence_UID')['start'].to_dict()
    template_rows = buttons.drop_duplicates('sentence_UID').set_index('sentence_UID')

    new_rows = []
    for uid, onset_list in all_detected_onsets.items():
        if uid in segment_start_map and uid in template_rows.index:
            segment_start = segment_start_map[uid]
            template = template_rows.loc[uid].to_dict()
            template['type'] = 'DetectedButton' # Update type as requested
            
            for detected_onset in onset_list:
                row = template.copy()
                row['start'] = segment_start + detected_onset
                row['sentence_UID'] = uid 
                row['button'] = '-'
                new_rows.append(row)

    if new_rows:
        detected_df = pd.DataFrame(new_rows)
        events = pd.concat([events, detected_df], ignore_index=True)

    events = events.sort_values(by=["timeline","start"]).reset_index(drop=True)

    return events