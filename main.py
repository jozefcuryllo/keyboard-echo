import sys
import threading
import logging
from queue import Queue
from pathlib import Path
from config import Config
from downloader import download_sound_if_missing
from audio import Mixer
from input import discover_devices, poll_devices


class QueueHandler(logging.Handler):
    def __init__(self, log_queue: Queue):
        super().__init__()
        self.log_queue = log_queue
        self.setFormatter(logging.Formatter('%(message)s'))

    def emit(self, record):
        self.log_queue.put(self.format(record))


def run_app():
    log_queue = Queue()
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    handler = QueueHandler(log_queue)
    logger.addHandler(handler)

    config = Config.parse()

    sounds_dir = Path("sounds")
    sounds_dir.mkdir(parents=True, exist_ok=True)

    sound_paths = []
    for i in range(1, 11):
        file_name = f"{config.profile}.wav" if i == 1 else f"{config.profile}{i}.wav"
        path = download_sound_if_missing(file_name, sounds_dir)
        sound_paths.append(path)
        logger.info(f"Registered: {file_name}")

    devices = discover_devices()
    if not devices:
        raise RuntimeError("No input devices found")

    input_queue, stats_queue = Queue(), Queue()
    threading.Thread(target=poll_devices, args=(
        devices, input_queue, stats_queue), daemon=True).start()

    recorder_queue = None
    if config.output_file:
        recorder_queue = Queue()

    mixer = Mixer(sound_paths, input_queue, recorder_queue,
                  device=config.alsa_device, output_file=config.output_file)
    mixer.start()

    logger.info("Engine ready. Press 'q' and Enter to exit.")

    while True:
        try:
            user_input = input()
            if user_input.strip().lower() == 'q':
                break
        except (KeyboardInterrupt, EOFError):
            break
        finally:
            mixer.stop()


if __name__ == "__main__":
    run_app()

