# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import logging
import typing as tp
from itertools import compress

import mne
import mne.io.brainvision
import numpy as np
import pandas as pd
import pydantic
import sklearn.preprocessing
import torch
from tqdm import tqdm

import neuralset as ns
from neuralset.base import Frequency, TimedArray
from neuralset.infra import MapInfra

from .base import BaseFeature, BaseStatic

logger = logging.getLogger(__name__)
Raw: tp.TypeAlias = mne.io.Raw | mne.io.brainvision.brainvision.RawBrainVision
DataframeOrEventsOrSegments = (
    pd.DataFrame | tp.Sequence[ns.events.Event] | tp.Sequence[ns.segments.Segment]
)

MOTOR_SENSORS = [
    "MEG0741",
    "MEG0711",
    "MEG0713",
    "MEG0742",
    "MEG0712",
    "MEG0743",
    "MEG0721",
    "MEG0731",
    "MEG0723",
    "MEG0732",
    "MEG0733",
    "MEG0722",
    "MEG2213",
    "MEG2211",
    "MEG2212",
    "MEG1821",
    "MEG1823",
    "MEG1822",
    "MEG1141",
    "MEG1142",
    "MEG1143",
    "MEG0433",
    "MEG0432",
    "MEG0431",
    "MEG1813",
    "MEG1812",
    "MEG1811",
    "MEG2221",
    "MEG2223",
    "MEG2222",
    "MEG1132",
    "MEG1133",
    "MEG1131",
    "MEG0442",
    "MEG0443",
    "MEG0441",
    "MEG1622",
    "MEG2411",
    "MEG1621",
    "MEG1623",
    "MEG2413",
    "MEG2412",
    "MEG1342",
    "MEG1341",
    "MEG1343",
    "MEG0231",
    "MEG0232",
    "MEG0233",
    "MEG1521",
    "MEG1522",
]

MOTOR_SENSORS = [
    "MEG0741",
    "MEG0711",
    "MEG0713",
    "MEG0742",
    "MEG0712",
    "MEG0743",
    "MEG0721",
    "MEG0731",
    "MEG0723",
    "MEG0732",
    "MEG0733",
    "MEG0722",
    "MEG2213",
    "MEG2211",
    "MEG2212",
    "MEG1821",
    "MEG1823",
    "MEG1822",
    "MEG1141",
    "MEG1142",
    "MEG1143",
    "MEG0433",
    "MEG0432",
    "MEG0431",
    "MEG0421",
    "MEG0422",
    "MEG0423",
    "MEG0631",
    "MEG0632",
    "MEG0633",
    "MEG1041",
    "MEG1042",
    "MEG1043",
    "MEG1111",
    "MEG1112",
    "MEG1113",
    "MEG1831",
    "MEG1832",
    "MEG1833",
    "MEG2241",
    "MEG2242",
    "MEG2243",
]


def _overlap(
    start1: float,
    duration1: float,
    start2: float,
    duration2: float,
) -> tuple[float, float]:
    """
    Computes the overlap times between two windows
    """
    starts = (start1, start2)
    stops = tuple(s + d for s, d in zip(starts, (duration1, duration2)))
    start = max(starts)
    stop = min(stops)
    return start, max(0, stop - start)


class Meg(BaseFeature):
    """If frequency is set to "native", the frequency used will be the one provided by the Meg event
    filter and resample preprocessing steps can be cached.

    Parameters
    ----------
    baseline :
        If provided as a tuple (start, end), corresponds to the start and end times (in seconds)
        relative to the **beginning of a window** (i.e. NOT relative to the epoch onset as opposed
        to MNE's convention) of the segment to use for baselining.

    Note
    ----
    Produces float32 Tensors
    """

    name: tp.Literal["Meg"] = "Meg"
    event_types: tp.Literal["Meg", "Eeg", "Emg", "Fnirs", "Ieeg"] = "Meg"

    frequency: tp.Literal["native"] | float = "native"
    offset: float = 0.0
    baseline: tuple[float, float] | None = None
    pick_types: tuple[str, ...] = pydantic.Field(("meg",), min_length=1)
    sensor_ablation: str | None = None
    apply_proj: bool = False
    filter: tuple[float | None, float | None] | None = None
    apply_hilbert: bool = False
    notch_filter: float | list[float] | None = None
    mne_cpus: int = -1
    infra: MapInfra = MapInfra(
        timeout_min=120,
        gpus_per_node=0,
        cpus_per_task=10,
        version="1",
    )
    scaler: None | tp.Literal["RobustScaler", "StandardScaler"] = None
    clamp: float | None = None

    _channels: tp.Dict[str, int] = {}

    @classmethod
    def _exclude_from_cls_uid(cls) -> list[str]:
        prev = super()._exclude_from_cls_uid()
        return prev + ["mne_cpus"]

    def _exclude_from_cache_uid(self) -> list[str]:
        prev = super()._exclude_from_cache_uid()
        return prev + ["baseline", "offset", "clamp"]

    def model_post_init(self, log__: tp.Any) -> None:
        super().model_post_init(log__)
        # Update channel mapping to be robust to mne.Raw
        self._channels = {}
        # check baseline
        if self.baseline is not None:
            issue = len(self.baseline) != 2
            issue |= not all(isinstance(b, float) for b in self.baseline)
            issue |= self.baseline[1] <= self.baseline[0]
            if issue:
                msg = f"baseline must be None or 2 floats, got {self.baseline}"
                raise ValueError(msg)

    def prepare(self, obj: DataframeOrEventsOrSegments) -> None:
        """specify how to load and preprocess the event.
        Can be overriden by user.
        """
        from neuralset import helpers

        events: list[ns.events.Meg]
        events = helpers.extract_events(obj, types=self._event_types_helper)  # type: ignore
        # avoid calling super().prepare to avoid loading a cache
        # (through missing preparation) without need:
        self._get_data(events)
        self._prepare_channels(events)
        if events:  # fill missing info manually
            self._missing_default = torch.zeros(len(self._channels))
            freq = self.frequency if self.frequency != "native" else events[0].frequency
            self._effective_frequency = freq

    # NOTE: We use the FIF format to cache MEG as we don't want to discard information such
    # as projectors and channel info which cannot be saved in the faster BrainVision format.
    # However, FIF files take a lot longer to read - if this becomes a bottleneck, we might need to
    # look into using another file format for MEG too.
    @infra.apply(
        item_uid=lambda e: str(e.filepath),
        exclude_from_cache_uid="method:_exclude_from_cache_uid",
        cache_type="MneRawFif",
    )
    def _get_data(self, events: list[ns.events.Meg]) -> tp.Iterator[mne.io.Raw]:
        # Initialize a variable to store the random selection
        random_pick_list = None

        for event in events:
            raw = event.read()
            pick_types = self.pick_types

            if self.sensor_ablation is not None:
                # 1. Logic for MOTOR (Fixed list)
                if self.sensor_ablation == "motor":
                    pick_list = MOTOR_SENSORS
                elif self.sensor_ablation == "without_motor":
                    # Convert motor list to set for faster lookup
                    motor_set = set(MOTOR_SENSORS)
                    # Keep the channel if it is NOT in the motor set
                    pick_list = [ch for ch in raw.ch_names if ch not in motor_set]
                # 2. Logic for RANDOM (Dynamic but consistent list)
                elif self.sensor_ablation == "random":
                    # Only generate the random list ONCE (for the first event)
                    if random_pick_list is None:
                        meg_channels = [ch for ch in raw.ch_names if ch.startswith("MEG")]

                        # Safety check: Ensure we have enough channels to pick from
                        if len(meg_channels) < len(MOTOR_SENSORS):
                            raise ValueError(
                                f"Not enough MEG channels to pick {len(MOTOR_SENSORS)}."
                            )

                        random_pick_list = np.random.choice(
                            meg_channels,
                            size=len(MOTOR_SENSORS),
                            replace=False,
                        ).tolist()

                    # Apply the cached list to the current raw object
                    pick_list = random_pick_list
                # --- 4. RANDOM WITHOUT MOTOR (50 random channels from NON-MOTOR MEG) ---
                elif self.sensor_ablation == "random_without_motor":
                    if random_pick_list is None:
                        # Pool: All MEG channels MINUS Motor channels
                        meg_channels = [ch for ch in raw.ch_names if "MEG" in ch]
                        motor_set = set(MOTOR_SENSORS)
                        available_pool = [
                            ch for ch in meg_channels if ch not in motor_set
                        ]

                        # Safety Check
                        if len(available_pool) < len(MOTOR_SENSORS):
                            raise ValueError(
                                f"Not enough non-motor channels to pick {len(MOTOR_SENSORS)}."
                            )

                        random_pick_list = np.random.choice(
                            available_pool,
                            size=len(MOTOR_SENSORS),
                            replace=False,
                        ).tolist()

                    pick_list = random_pick_list
                else:
                    raise ValueError(
                        f"Unknown sensor_ablation type: {self.sensor_ablation}"
                    )

                # Apply the pick
                # use 'ignore' to prevent crashing if a specific file is missing one of the random channels
                raw = raw.pick_channels(pick_list, ordered=False)

            else:
                raw = raw.pick(self.pick_types, verbose=False)

            if self.notch_filter is not None:
                raw.load_data()
                raw = self._notch_filter(raw, self.notch_filter, self.mne_cpus)

            if self.filter is not None:
                raw.load_data()
                l_freq, h_freq = self.filter
                # Ignore lowpass filter if cutoff is higher than Nyquist frequency
                if h_freq is not None and h_freq > raw.info["sfreq"] / 2:
                    logger.warning(
                        "Lowpass filter cutoff frequency is higher than Nyquist frequency. "
                        "Setting it to None."
                    )
                    h_freq = None

                raw.filter(
                    l_freq,
                    h_freq,
                    picks=("eeg", "emg", "meg"),
                    n_jobs=self.mne_cpus,
                    verbose=False,
                )
            if self.apply_hilbert:
                raw.load_data()
                raw = raw.apply_hilbert(envelope=True)

            freq = event.frequency if self.frequency == "native" else self.frequency
            if freq != event.frequency:
                raw.load_data()
                raw = raw.resample(freq, n_jobs=self.mne_cpus, verbose=False)

            if self.scaler is not None:
                raw.load_data()
                scaler = getattr(sklearn.preprocessing, self.scaler)()
                raw._data = scaler.fit_transform(raw._data.T).T

            if self.apply_proj:
                raw.apply_proj()

            yield raw

    def _get_timed_arrays(
        self, events: list[ns.events.Meg], start: float, duration: float
    ) -> tp.Iterable[TimedArray]:
        for event in events:
            yield self._get_timed_meg(event, start, duration)

    def _get_timed_meg(
        self, event: ns.events.Meg, start: float, duration: float
    ) -> TimedArray:
        start += self.offset

        # Extend window in case of disjoint baseline
        window_start, window_stop = start, start + duration
        if self.baseline is not None:
            if self.baseline[0] >= self.baseline[1]:
                msg = f"unexpected baseline:{self.baseline}"
                raise RuntimeError(msg)
            window_start = min(window_start, start + self.baseline[0])
            window_stop = max(window_stop, start + self.baseline[1])

        # cached_preprocessing
        # (copy to avoid corrupting cache)
        raw = next(self._get_data([event]))
        freq = Frequency(raw.info["sfreq"])

        if not isinstance(raw, mne.io.BaseRaw):  # for typing
            raise TypeError("Output of _get_preprocessed_data should be mne.io.BaseRaw")
        # safeguard for first_samp
        if raw.first_samp and not event.start:
            msg = "event.start should be raw.first_samp / freq for consistency"
            raise RuntimeError(msg)
        overlap_start, overlap_duration = _overlap(
            event.start, event.duration, window_start, window_stop - window_start
        )

        data_start = overlap_start - event.start  # time in the M/EEG referential
        # times in time_as_index are assumed to be relative to first_samp (cf doc)
        # time_as_index is slow, so let's do it manually
        # start_idx, stop_idx = raw.time_as_index([meg_start, meg_start + overlap_duration])
        start_idx = max(0, freq.to_ind(data_start))
        if start_idx == raw.n_times:
            start_idx -= 1
        # apply freq on overlap to keep always the same size, and minimum to 1
        stop_idx = start_idx + max(1, freq.to_ind(overlap_duration))
        try:
            npdata, _ = raw[:, start_idx:stop_idx]
        except ValueError:
            msg = (
                "Failed to read event %r (start=%s duration=%s)\n"
                "(start_idx=%s stop_idx=%s in %s)"
            )
            logger.warning(msg, event, start, duration, start_idx, stop_idx, raw)
            raise
        if npdata.shape[-1] == 0:  # border case
            npdata = np.zeros(npdata.shape[:-1] + (stop_idx - start_idx,))
        tdata = TimedArray(
            frequency=freq,
            duration=overlap_duration,
            start=overlap_start,
            data=np.asarray(npdata).astype(np.float32),
        )

        # Apply baseline to the data
        if self.baseline is not None:
            baseline_duration = self.baseline[1] - self.baseline[0]
            base = tdata.overlap(start + self.baseline[0], baseline_duration)
            if base.data.size:
                tdata.data -= base.data.mean(1, keepdims=True)
        tdata = tdata.overlap(start=start, duration=duration)

        # initialize output
        channel_idx = self._get_channels(raw.ch_names)
        timed_out = TimedArray(frequency=freq, start=start, duration=duration)
        out_shape = (len(self._channels), timed_out.data.shape[-1])
        out = np.zeros(out_shape, dtype=np.float32)
        if tdata.start == start and tdata.duration == duration:
            timed_out = tdata  # bypass copy for efficiency
        else:
            timed_out += tdata
        if self.clamp is not None:
            timed_out.data = np.clip(timed_out.data, a_min=-self.clamp, a_max=self.clamp)
        out[channel_idx, :] = timed_out.data
        timed_out.start -= self.offset
        timed_out.data = out
        return timed_out

    def _update_channels(self, ch_names: list[str]) -> None:
        channels = self._channels  # avoid calling pydantic attr too many times
        for ch in ch_names:
            if ch not in self._channels:
                channels[ch] = len(channels)

    def _prepare_channels(self, events: list[ns.events.Meg]) -> None:
        for raw in self._get_data(events):
            self._update_channels(raw.ch_names)

    def _get_channels(self, ch_names: list[str]) -> list[int]:
        if not self._channels:
            self._update_channels(ch_names)
        try:
            channel_idx = [self._channels[ch] for ch in ch_names]
        except KeyError as e:
            msg = f"Channel {e} not found in the channel mapping, likely because "
            msg += "this dataset contains recordings with different sets of channel "
            msg += "names. Try calling self.prepare on the whole events dataframe."
            raise KeyError(msg) from e
        return channel_idx

    @staticmethod
    def _notch_filter(
        raw: mne.io.Raw, notch_filter: float | list[float], mne_cpus: int
    ) -> mne.io.Raw:
        notch_filter = [notch_filter] if isinstance(notch_filter, float) else notch_filter
        notch_freqs: list[float] = []
        for freq in notch_filter:
            notch_freqs.extend(
                np.arange(freq, min(raw.info["sfreq"] / 2, 301), freq).tolist()  # type: ignore
            )

        if len(notch_freqs) == 0:
            logger.info("Not applying notch filter as no valid frequencies were found.")
        else:
            logger.info("Applying notch filter with notch_freqs=%s", sorted(notch_freqs))
            raw = raw.notch_filter(
                notch_freqs, phase="zero", filter_length="auto", n_jobs=mne_cpus
            )
        return raw


class Eeg(Meg):
    name: tp.Literal["Eeg"] = "Eeg"  # type: ignore
    event_types: tp.Literal["Eeg"] = "Eeg"
    pick_types: tuple[str, ...] = pydantic.Field(("eeg",), min_length=1)


class EegBrainVision(Eeg):
    """
    EEG feature, caching to BrainVision format.
    This yields up to 7x speed up when loading the timelines (useful for large datasets),
    but discards some information such as projectors and channel layout.
    """

    name: tp.Literal["EegBrainVision"] = "EegBrainVision"  # type: ignore
    infra: MapInfra = MapInfra(
        timeout_min=120,
        gpus_per_node=0,
        cpus_per_task=10,
        version="1",
    )
    requirements: tp.ClassVar[tuple[str, ...]] = ("pybv>=0.7.6",)

    def model_post_init(self, log__: tp.Any) -> None:
        super().model_post_init(log__)

        try:
            import pybv  # noqa # pylint: disable=unused-import
        except ModuleNotFoundError as err:
            msg = (
                "Caching EEG timelines in the BrainVision format requires the pybv package."
                "Please install it with `pip install pybv`."
            )
            raise ModuleNotFoundError(msg) from err

    @infra.apply(
        item_uid=lambda e: str(e.filepath),
        exclude_from_cache_uid="method:_exclude_from_cache_uid",
        cache_type="MneRawBrainVision",
    )
    def _get_data(self, events: list[ns.events.Meg]) -> tp.Iterator[Raw]:
        return super()._get_data(events)


class Emg(Meg):
    name: tp.Literal["Emg"] = "Emg"  # type: ignore
    event_types: tp.Literal["Emg"] = "Emg"
    pick_types: tp.Tuple[str, ...] = pydantic.Field(("emg",), min_length=1)


class Ieeg(Meg):
    name: tp.Literal["Ieeg"] = "Ieeg"  # type: ignore
    event_types: tp.Literal["Ieeg"] = "Ieeg"
    pick_types: tp.Tuple[str, ...] = pydantic.Field(("seeg", "ecog", "eeg"), min_length=1)
    reference: tp.Literal["bipolar"] | None = None
    infra: MapInfra = MapInfra(
        timeout_min=120,
        gpus_per_node=0,
        cpus_per_task=10,
        version="1",
    )

    @infra.apply(
        item_uid=lambda e: str(e.filepath),
        exclude_from_cache_uid="method:_exclude_from_cache_uid",
    )
    def _get_data(self, events: tp.List[ns.events.Ieeg]) -> tp.Iterator[mne.io.Raw]:
        for event in events:
            raw = event.read()
            raw = raw.pick(self.pick_types, verbose=False)

            if self.reference == "bipolar":
                raw.load_data()
                raw = self._apply_bipolar_ref(raw)

            if self.notch_filter is not None:
                raw.load_data()
                raw = self._notch_filter(raw, self.notch_filter, self.mne_cpus)

            if self.filter is not None:
                raw.load_data()
                raw.filter(
                    self.filter[0], self.filter[1], n_jobs=self.mne_cpus, verbose=False
                )

            if self.apply_hilbert:
                raw.load_data()
                raw = raw.apply_hilbert(envelope=True)

            freq = event.frequency if self.frequency == "native" else self.frequency
            if freq != event.frequency:
                raw.load_data()
                raw = raw.resample(freq, n_jobs=self.mne_cpus, verbose=False)

            if self.scaler is not None:
                raw.load_data()
                scaler = getattr(sklearn.preprocessing, self.scaler)()
                raw._data = scaler.fit_transform(raw._data.T).T

            if self.apply_proj:
                raw.apply_proj()

            yield raw

    def _apply_bipolar_ref(self, raw: mne.io.Raw) -> mne.io.Raw:
        """
        Apply bipolar reference for EEG, i.e., uses neighboring electrode as reference.

        Parameters
        ----------
        raw : mne.io.Raw
            Raw instance that will be referenced.

        Returns
        -------
        raw : mne.io.Raw
            Referenced Raw object

        Notes
        ----------
        Expects that the channels in raw.ch_names are ordered by probe,
        and with ascending order for each probe, and the names consists of
        the probe name followed by the position on the probe.
        eg: ['OF1', 'OF2', 'OF3', 'OF4', 'OF5', 'OF6', 'OF7', 'OF8', 'OF9',
        'OF10', 'OF11', 'OF12', 'OF13', 'OF14', 'H1', 'H2', 'H3', 'H4', 'H5',
        'H6', 'H7', 'H8', 'H9', 'H10', 'H11', 'H12', 'H13', 'H14', 'H15', ...]

        WATCH-OUT: this will take the closest electrode on the probe,
        meaning that if the neighboring electrode is missing for some
        reason (eg: rejected before applying the reference) then the next
        electrode will be used for referencing.
        """
        logger.info("Applying bipolar reference")
        logger.warning(
            "Assumes raw.ch_names are ordered by probe, with ascending order for each probe, and the names consists of the probe name followed by the probe position."
        )
        logger.warning(
            "WATCH-OUT: Taking the closest electrode on the probe... If the neighboring electrode is missing (e.g., rejected before applying the reference) then the next electrode will be used as the reference."
        )

        reference_ch = list(raw.ch_names)

        anodes = reference_ch[0:-1]
        cathodes = reference_ch[1:]
        to_del = []
        # allow constructions that are on the same probe
        #  (e.g., HA 5-HA 6 or HA 5-HA 7 if contact HA 6 is turned off)
        # don't allow constructions across probes
        #  (e.g., HA 5 with FA 6)
        for i, (a, c) in enumerate(zip(anodes, cathodes)):
            if [j for j in a if not j.isdigit()] != [j for j in c if not j.isdigit()]:
                to_del.append(i)
        for idx in to_del[::-1]:
            del anodes[idx]
            del cathodes[idx]
        bipol = mne.set_bipolar_reference(raw, anodes, cathodes, verbose="WARNING")
        return bipol


class Fnirs(Meg):
    requirements: tp.ClassVar[tp.Any] = ("mne-nirs",)
    name: tp.Literal["Fnirs"] = "Fnirs"  # type: ignore
    event_types: tp.Literal["Fnirs"] = "Fnirs"
    pick_types: tp.Tuple[str, ...] = pydantic.Field(("fnirs",), min_length=1)
    # Preprocessing
    distance_threshold: float | None = None
    compute_optical_density: bool = False
    scalp_coupling_index_threshold: float | None = None
    apply_tddr: bool = False  # Apply temporal derivative distribution repair
    compute_heamo_response: bool = False
    partial_pathlength_factor: float = 0.1
    enhance_negative_correlation: bool = False
    #
    infra: MapInfra = MapInfra(
        timeout_min=120,
        gpus_per_node=0,
        cpus_per_task=10,
        version="1",
    )

    def model_post_init(self, log__: tp.Any) -> None:
        super().model_post_init(log__)

        # Ensure preprocessing steps are consistent with one another
        if self.compute_heamo_response and not self.compute_optical_density:
            msg = "Computing haemodynamic response requires computing optical density first."
            raise ValueError(msg)
        if self.scalp_coupling_index_threshold is not None:
            if not self.compute_optical_density:
                raise ValueError(
                    "Thresholding with the SCI requires computing optical density first."
                )

        if self.enhance_negative_correlation and not self.compute_heamo_response:
            msg = "Applying negative correlation enhancement requires haemodynamic responses."
            raise ValueError(msg)

    @infra.apply(
        item_uid=lambda e: str(e.filepath),
        exclude_from_cache_uid="method:_exclude_from_cache_uid",
    )
    def _get_data(self, events: tp.List[ns.events.Fnirs]) -> tp.Iterator[mne.io.Raw]:
        for event in events:
            raw = event.read()
            raw = raw.pick(self.pick_types, verbose=False)

            if self.distance_threshold is not None:
                dists = mne.preprocessing.nirs.source_detector_distances(raw.info)
                if np.isnan(dists).any():
                    msg = "Some or all distances are nan, please fix montage information."
                    raise ValueError(msg)
                picks = compress(raw.ch_names, dists > self.distance_threshold)
                raw = raw.pick(list(picks))

            if self.compute_optical_density:
                raw = mne.preprocessing.nirs.optical_density(raw)

            if self.scalp_coupling_index_threshold is not None:
                sci = mne.preprocessing.nirs.scalp_coupling_index(raw)
                picks = compress(raw.ch_names, sci > self.scalp_coupling_index_threshold)
                raw = raw.pick(list(picks))

            if self.apply_tddr:
                raw = mne.preprocessing.nirs.temporal_derivative_distribution_repair(raw)

            if self.compute_heamo_response:
                raw = mne.preprocessing.nirs.beer_lambert_law(
                    raw, ppf=self.partial_pathlength_factor
                )

            if self.filter is not None:
                raw.load_data()
                raw.filter(
                    self.filter[0], self.filter[1], n_jobs=self.mne_cpus, verbose=False
                )

            if self.enhance_negative_correlation:
                import mne_nirs

                raw = mne_nirs.signal_enhancement.enhance_negative_correlation(raw)

            freq = event.frequency if self.frequency == "native" else self.frequency
            if freq != event.frequency:
                raw.load_data()
                raw = raw.resample(freq, n_jobs=self.mne_cpus, verbose=False)
            if self.scaler is not None:
                raw.load_data()
                scaler = getattr(sklearn.preprocessing, self.scaler)()
                raw._data = scaler.fit_transform(raw._data.T).T

            yield raw


class Fmri(BaseFeature):
    """
    Fmri feature, caching to numpy memmap.

    Parameters
    ----------
    mesh : str
        Project data to a fsaverage mesh.
    atlas : str
        Use an atlas to mask the data.
    atlas_dim : int
        Number of ROIs to use in the atlas.
    standardize : str
        Standardize the data.
    detrend : bool
        Detrend the data.
    high_pass : float
        High pass filter the data.
    frequency : str
        Frequency to use. Currently only supports "native".
    """

    requirements: tp.ClassVar[tp.Any] = ("nilearn",)
    name: tp.Literal["Fmri"] = "Fmri"
    offset: float = 0.0
    event_types: tp.Literal["Fmri"] = "Fmri"
    mesh: str | None = None  # fsaverage5
    atlas: tp.Literal["schaefer_2018", "difumo"] | None = None
    atlas_dim: int | None = None
    pre_masked: bool = False  # data masked to 2D (voxels x time)
    standardize: tp.Literal["zscore_sample", "zscore", "psc"] | bool = "zscore_sample"
    detrend: bool = False
    high_pass: float | None = None
    frequency: tp.Literal["native"] | float = "native"
    padding: int | tp.Literal["auto"] | None = None
    confounds_strategy: (
        tp.Literal["simple", "simple+gsr", "scrubbing", "compcor"] | None
    ) = None
    infra: MapInfra = MapInfra(
        timeout_min=120,
        gpus_per_node=0,
        cpus_per_task=10,
        version="2",
    )
    # internal effective padding
    _padding: int | None = None

    _masker: tp.Any = pydantic.PrivateAttr()

    def model_post_init(self, log__: tp.Any) -> None:
        super().model_post_init(log__)
        if self.frequency != "native":
            cls = self.__class__.__name__
            msg = f"{cls} only support frequency='native' (resampling not implemented)"
            raise ValueError(msg)
        if isinstance(self.padding, int):
            self._padding = self.padding
        if self.mesh is not None and self.atlas is not None:
            raise ValueError("Cannot specify both mesh and atlas")
        if self.atlas is not None:
            if self.atlas_dim is None:
                raise ValueError(f"Atlas dim must be specified for atlas {self.atlas}")
            atlas_dims = {
                "schaefer_2018": [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000],
                "difumo": [64, 128, 256, 512, 1024],
            }
            if self.atlas_dim not in atlas_dims[self.atlas]:
                raise ValueError(
                    f"Atlas dim must be one of {atlas_dims[self.atlas]} for atlas {self.atlas}, got {self.atlas_dim}"
                )

    def _exclude_from_cache_uid(self) -> list[str]:
        return super()._exclude_from_cache_uid() + ["offset", "padding"]

    def prepare(self, events: pd.DataFrame) -> None:
        if self.padding == "auto":
            # for padding, we first need everything to be preprocessed
            # but we need on an object without padding since missing_default filling
            # will apply the feature on 1 event, and we'll need the padding length for that
            self.infra.clone_obj(padding=None).prepare(events)
            events_ = self._events_from_dataframe(events)
            self._padding = max(a.shape[0] for a in self._get_data(events_))
            # (recompute prepare to just fill the missing default value)
        super().prepare(events)

    @property
    def masker(self) -> tp.Any:
        if not hasattr(self, "_masker"):
            from nilearn import datasets
            from nilearn.input_data import NiftiLabelsMasker, NiftiMapsMasker

            atlas_func = getattr(datasets, f"fetch_atlas_{self.atlas}")
            if self.atlas_dim is not None:
                if self.atlas == "schaefer_2018":
                    atlas = atlas_func(n_rois=self.atlas_dim)
                    masker = NiftiLabelsMasker(
                        labels_img=atlas["maps"],
                        standardize=self.standardize,
                        resampling_target="labels",
                    )
                elif self.atlas == "difumo":
                    atlas = atlas_func(dimension=self.atlas_dim)
                    masker = NiftiMapsMasker(
                        maps_img=atlas["maps"], standardize=self.standardize
                    )
                else:
                    raise ValueError(f"Unknown atlas {self.atlas}")
            self._masker = masker
        return self._masker

    def _preprocess_event(self, event: ns.events.Fmri) -> np.ndarray:
        rec = event.read()
        data_space = "volumetric" if len(rec.shape) == 4 else "surface"
        if self.confounds_strategy is not None:
            assert (
                hasattr(rec, "file_map") and rec.file_map["image"]
            ), f"No image file found for {rec}"
            assert data_space == "volumetric"
            from nilearn.interfaces.fmriprep import load_confounds_strategy

            if self.confounds_strategy == "simple+gsr":
                confounds_strategy, confounds_kwargs = "simple", {
                    "global_signal": "basic"
                }
            else:
                confounds_strategy, confounds_kwargs = self.confounds_strategy, {}
            confounds, _ = load_confounds_strategy(
                rec.file_map["image"].filename,
                denoise_strategy=confounds_strategy,
                **confounds_kwargs,
            )
        else:
            confounds = None

        if self.mesh is not None:
            if data_space == "volumetric":
                if confounds is not None:  # apply confounds before projection
                    from nilearn.image import clean_img

                    rec = clean_img(rec, confounds=confounds)
                from nilearn import datasets, surface

                fsaverage = datasets.fetch_surf_fsaverage(self.mesh)
                hemis = [
                    surface.vol_to_surf(
                        rec,
                        surf_mesh=fsaverage[f"pial_{hemi}"],
                        inner_mesh=fsaverage[f"white_{hemi}"],
                    )
                    for hemi in ("left", "right")
                ]
                data = np.vstack(hemis)
                data[np.isnan(data)] = 0
            else:
                if len(rec.shape) != 2:
                    raise ValueError(f"Unexpected shape for surface data {rec.shape}")
                voxels = rec.shape[0] // 2
                sizes = {
                    "fsaverage3": 642,
                    "fsaverage4": 2562,
                    "fsaverage5": 10242,
                    "fsaverage6": 40962,
                    "fsaverage7": 163842,
                }
                if self.mesh not in sizes:
                    raise NotImplementedError(f"Can only 2d project to {sizes} currently")
                if voxels not in list(sizes.values()) or rec.shape[0] % 2:
                    msg = f"Could not detect current 2d format from {sizes} with {rec.shape[0]} voxels"
                    msg += f" (for event {event!r})"
                    raise NotImplementedError(msg)
                data = rec.get_fdata()
                if voxels < sizes[self.mesh]:
                    msg = f"Cannot project from smaller {voxels} voxels to {self.mesh}"
                    msg += f" (for event {event!r})"
                    raise ValueError(msg)
                if voxels > sizes[self.mesh]:
                    left = data[: sizes[self.mesh], :]
                    right = data[voxels : voxels + sizes[self.mesh], :]
                    data = np.concatenate([left, right], axis=0)
        elif self.atlas is not None:
            input_spaces = {
                "schaefer_2018": "mni152nlin2009asym",
                "difumo": "mni152nlin6asym",
            }
            if input_spaces[self.atlas] not in str(event.filepath).lower():
                msg = "Atlas masking is only supported for MNI152 space. Please make sure that the images are in this space."
                logger.warning(msg)
            data = self.masker.fit_transform(rec, confounds=confounds).T
        else:
            if self.pre_masked:  # premasked volumetric data in 2D array, voxels x time
                if len(rec.shape) != 2:
                    raise ValueError(f"Unexpected shape for masked data {rec.shape}")
                data = rec
            else:
                data = rec.get_fdata()
        # data shape = featdim1 x [featdim2 x ...] x time

        if self.detrend or self.standardize or self.high_pass is not None:
            import nilearn.signal

            data = data.T  # set time as first dim
            shape = data.shape
            data = nilearn.signal.clean(
                # required shape: (instant number, features number)
                data.reshape(shape[0], -1),
                detrend=self.detrend,
                high_pass=self.high_pass,
                t_r=1 / event.frequency,
                standardize=self.standardize,
            )
            data = data.reshape(shape).T
        return data.astype(np.float32)  # no need to keep float64 precision

    @infra.apply(
        item_uid=lambda e: str(e.filepath),
        exclude_from_cache_uid=_exclude_from_cache_uid,
        cache_type="NumpyMemmapArray",
    )
    def _get_data(self, events: tp.List[ns.events.Fmri]) -> tp.Iterable[np.ndarray]:
        for event in tqdm(events, disable=len(events) < 2, desc="Computing fmri data"):
            yield self._preprocess_event(event)

    def _get_timed_arrays(
        self, events: list[ns.events.Fmri], start: float, duration: float
    ) -> tp.Iterable[TimedArray]:
        if self.padding == "auto" and self._padding is None:
            raise RuntimeError("Fmri.prepare needs to be called to compute auto padding")
        freq = events[0].frequency if self.frequency == "native" else self.frequency
        for event, data in zip(events, self._get_data(events)):
            if self._padding is not None:
                if data.ndim != 2:
                    raise ValueError(f"Only 1D+T FMRI can be padded, got {data.shape=}")
                padding = self._padding - data.shape[0]
                if padding < 0:
                    raise ValueError(
                        f"Padding to length {self._padding} but got {data.shape=}"
                    )
                data = np.pad(data, [(0, self._padding - data.shape[0]), (0, 0)])
            yield TimedArray(
                data=data,
                frequency=freq,
                start=event.start - self.offset,
                duration=event.duration,
            )


class ChannelPositions(BaseStatic):
    """Channel positions in 2D, extracted from a Raw object's mne.Info.

    Parameters
    ----------
    neuro :
        Feature that defines the preprocessing steps applied to the Raw objects.
        This can either be specified in the config, or built with the `build` method.
    n_spatial_dims :
        Number of spatial dimensions (i.e. coordinates) to extract for each channel. For
        `n_spatial_dims=2`, the 2D projection of the channel positions as obtained through
        `mne.Layout` will be used. For `n_spatial_dims=3`, the 3D positions are extracted from
        `mne.Montage` instead.
    layout_or_montage_name :
        Name of the Layout or Montage to use. See `mne.channels.read_layout()` for a list of valid
        layouts and `mne.channels.get_builtin_montages()` for standard montages. If not provided,
        the function will look for a layout in the `Raw.info` object or for a montage in the `Raw`
        object.
        NOTE: MNE's standard montages are only for EEG systems; MEG montages must be loaded from
              the raw data.
    include_ref_eeg :
        If True, additionally try to extract the position of the anode of bipolar EEG channel (e.g.
        for the channel name "P3-Cz", return position of both "P3" and "Cz"), yielding and output
        of shape (n_channels, n_spatial_dims * 2). If True, `event_types` must be one of
        Eeg or Ieeg.
    normalize :
        If True, min-max normalize channel positions between 0 and 1 across each dimension. If
        False, 2D positions are in arbitrary units given by the mne.Layout projection, while 3D
        positions will be in decimeters (approximately in the range [-1, 1]).
    factor :
        Factor to scale the channel positions by. E.g. set it to 10.0 to get 3D coordinates in
        decimeters, which yields values approximately in the range [-1, 1].
    """

    name: tp.Literal["ChannelPositions"] = "ChannelPositions"
    event_types: tp.Literal["Meg"] = "Meg"
    neuro: (
        tp.Annotated[
            Meg | Eeg | EegBrainVision | Ieeg, pydantic.Field(discriminator="name")
        ]
        | None
    ) = None

    n_spatial_dims: tp.Literal[2, 3] = 2
    layout_or_montage_name: str | None = None
    include_ref_eeg: bool = False
    normalize: bool = True
    factor: float = 1.0

    _neuro: Meg | Eeg | EegBrainVision | Ieeg = pydantic.PrivateAttr()

    # Value to use for channels that are not found in the layout
    INVALID_VALUE: tp.ClassVar[float] = -0.1

    infra: MapInfra = MapInfra()

    def model_post_init(self, log__: tp.Any) -> None:
        super().model_post_init(log__)
        if self.neuro is not None:
            eegs = {"Eeg", "EegBrainVision", "Ieeg"}
            if self.include_ref_eeg and self.neuro.name not in eegs:
                msg = "include_ref_eeg=True is only supported for events_types "
                msg += f"Eeg, EegBrainVision, Ieeg, got {self.event_types}."
                raise ValueError(msg)
            self._neuro = self.neuro

    def build(self, neuro: Meg | Eeg | EegBrainVision | Ieeg) -> "ChannelPositions":
        config = self.model_dump()
        config["neuro"] = neuro
        return self.__class__(**config)

    def prepare(self, obj: DataframeOrEventsOrSegments) -> None:
        from neuralset import helpers

        events = helpers.extract_events(obj, types=self._event_types_helper)
        if not hasattr(self, "_neuro"):
            raise ValueError(
                "The neuro feature is not set. Either set it in the config or call build."
            )
        self._neuro.prepare(events)  # Ensure the Raw objects have been precomputed
        super().prepare(events)

    def _get_layout_positions(self, raw: mne.io.Raw) -> dict[str, list[float]]:
        if self.layout_or_montage_name is not None:
            layout = mne.channels.read_layout(self.layout_or_montage_name)
        else:
            try:
                layout = mne.find_layout(raw.info)
            except RuntimeError as err:
                msg = "No valid layout found. Please specify a layout to load with argument "
                msg += "`layout_name` or explicitly set a montage in the study class (e.g. with "
                msg += "`raw.set_montage()`)."
                raise ValueError(msg) from err

        mapping = {name: pos[:2].tolist() for name, pos in zip(layout.names, layout.pos)}
        return mapping

    def _get_montage_positions(self, raw: mne.io.Raw) -> dict[str, list[float]]:
        if self.layout_or_montage_name is not None:
            montage = mne.channels.make_standard_montage(self.layout_or_montage_name)
        else:
            montage = raw.get_montage()
        if montage is None:
            raise RuntimeError(
                "No montage found in the Raw object. Please set a montage in the study class."
            )
        mapping = montage.get_positions()["ch_pos"]
        mapping = {name: pos.tolist() for name, pos in mapping.items()}
        return mapping

    def _get_meg_3d_positions(self, raw: mne.io.Raw) -> dict[str, list[float]]:
        return {ch["ch_name"]: ch["loc"][:3] for ch in raw.info["chs"]}

    def _get_channel_positions_from_raw(self, raw: mne.io.Raw) -> torch.Tensor:
        """Get scaled channel positions for channels in Raw object.

        Returns
        -------
        torch.Tensor :
            Positions for each channel, of shape (n_channels, n_spatial_dims). When including
            reference channel (self.include_ref_eeg is True), output shape is
            (n_channels, n_spatial_dims * 2) where each row contains the coordinates of the cathode
            channel followed by the coordinates of the anode.
        """
        pos_mapping = {}
        if self.n_spatial_dims == 2:
            pos_mapping = self._get_layout_positions(raw)
        elif self.n_spatial_dims == 3:
            if self._neuro.name == "Meg":
                pos_mapping = self._get_meg_3d_positions(raw)
            else:
                pos_mapping = self._get_montage_positions(raw)

        ch_names: list[str] = []
        valid_inds: list[int] = []
        invalid_names: list[str] = []
        ch_index = 0
        for ch_name in raw.ch_names:
            if self.include_ref_eeg:  # Handle bipolar channel names
                names = ch_name.split("-", 1) if "-" in ch_name else [ch_name, None]
            else:
                names = ch_name.split("-")[:1]
            for name in names:
                ch_names.append(name)
                if name in pos_mapping.keys():
                    valid_inds.append(ch_index)
                elif name is not None:
                    invalid_names.append(name)
                ch_index += 1

        if not valid_inds:
            raise ValueError(f"No channel has valid positions: {raw.ch_names}.")

        if len(valid_inds) < 0.1 * ch_index:
            unique_invalid_names = set(invalid_names) - {None}
            msg = f"Fewer than 10% of the channels have valid positions: {unique_invalid_names}."
            logger.warning(msg)

        positions = np.array(
            [
                (
                    pos_mapping[name]
                    if name in pos_mapping
                    else [np.nan] * self.n_spatial_dims
                )
                for name in ch_names
            ]
        )

        if self.normalize:
            ptp = np.nanmax(positions, axis=0, keepdims=True) - np.nanmin(
                positions, axis=0, keepdims=True
            )
            if (ptp == 0.0).any():
                # Can happen if all electrodes are on a same horizontal and/or vertical line
                ptp[ptp == 0.0] = 1.0
            positions = (positions - np.nanmin(positions, axis=0, keepdims=True)) / ptp

        positions *= self.factor  # Scale positions by factor
        positions = np.nan_to_num(positions, nan=self.INVALID_VALUE)

        n_spatial_dims = self.n_spatial_dims
        if self.include_ref_eeg:
            n_spatial_dims *= 2  # type: ignore
            positions = positions.reshape(len(raw.ch_names), n_spatial_dims)

        channel_idx = self._neuro._get_channels(raw.ch_names)
        out = torch.full((len(self._neuro._channels), n_spatial_dims), self.INVALID_VALUE)
        out[channel_idx, :] = torch.from_numpy(positions).float()

        return out

    def _exclude_from_cache_uid(self) -> list[str]:
        ex = super()._exclude_from_cache_uid()
        if not hasattr(self, "_neuro"):
            raise RuntimeError("Should not happen")
        neuro_ex = self._neuro._exclude_from_cache_uid()
        return ex + [f"neuro.{n}" for n in neuro_ex]

    @infra.apply(
        item_uid=lambda e: str(e.filepath),
        exclude_from_cache_uid="method:_exclude_from_cache_uid",
    )
    def _get_data(self, events: list[ns.events.Meg]) -> tp.Iterator[torch.Tensor]:
        if not hasattr(self, "_neuro"):
            raise ValueError(
                "The neuro feature is not set. Either set it in the config or call build."
            )
        for raw in self._neuro._get_data(events):
            yield self._get_channel_positions_from_raw(raw)

    def get_static(self, event: ns.events.Meg) -> torch.Tensor:
        return next(self._get_data([event]))
