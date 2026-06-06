import argparse
import os
from pathlib import Path

class Config:
    def __init__(self):
        self.profile = os.environ.get("SOUND_PROFILE", "MXRed")
        self.alsa_device = os.environ.get("ALSA_DEVICE", "pulse")
        self.output_file = None

    @classmethod
    def parse(cls):
        parser = argparse.ArgumentParser()
        parser.add_argument("-p", "--profile", type=str)
        parser.add_argument("-d", "--device", type=str)
        parser.add_argument("-o", "--output", type=str)
        args, _ = parser.parse_known_args()
        
        config = cls()
        if args.profile:
            config.profile = args.profile
        if args.device:
            config.alsa_device = args.device
        if args.output:
            config.output_file = Path(args.output)
            
        return config