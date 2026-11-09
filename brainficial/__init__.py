"""BrainFicial: exploratory EEG research, never mind reading."""
from .loader import EEGLoader
from .signal import AnalEEG, GetFeature, CompSig
from .model import CompLike
from .experiment import EventLogger, ExperimentTemplate, ExperimentRunner

__all__ = ["EEGLoader", "AnalEEG", "GetFeature", "CompSig", "CompLike",
           "EventLogger", "ExperimentTemplate", "ExperimentRunner"]
