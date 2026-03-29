from enum import Enum


class Stage(Enum):
    FRAMES = "frames"
    FEATURE_EXTRACT = "feature_extract"
    FEATURE_MATCH = "feature_match"
    RECONSTRUCTION = "reconstruction"
    TRAINING = "training"
    EXPORT = "export"
