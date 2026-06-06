import wave
import threading
import numpy as np
import alsaaudio
from pathlib import Path
from queue import Queue
import unittest
import atexit
import tempfile
import time
import signal
import sys

class Mixer:
    def __init__(self, samples: list[Path], input_queue: Queue, recorder_queue: Queue, device: str, output_file: Path = None):
        self.samples = samples
        self.input_queue = input_queue
        self.recorder_queue = recorder_queue
        self.device = device
        self.output_file = output_file
        self.wave_writer = None
        self.running = True
        
        self.loaded_samples = []
        print("Loading samples into memory...")
        for p in self.samples:
            self.loaded_samples.append(self.__load_wave_to_memory(p))
        print(f"Loaded {len(self.loaded_samples)} samples into memory successfully.")
            
        self.task_queue = Queue()
        self.active_sounds = []
        self.active_sounds_lock = threading.Lock()

        if self.output_file and len(self.loaded_samples) > 0:
            _, nchannels, sampwidth, framerate = self.loaded_samples[0]
            self.wave_writer = wave.open(str(self.output_file), 'wb')
            self.wave_writer.setnchannels(nchannels)
            self.wave_writer.setsampwidth(sampwidth)
            self.wave_writer.setframerate(framerate)
            print(f"Recorder initialized. Output file: {self.output_file}")
            
            atexit.register(self.cleanup)
            signal.signal(signal.SIGINT, self.__signal_handler)
            signal.signal(signal.SIGTERM, self.__signal_handler)

        print(f"Available devices: {alsaaudio.pcms()}")

    def __signal_handler(self, signum, frame) -> None:
        self.stop()
        sys.exit(0)

    def __load_wave_to_memory(self, path: Path) -> tuple[np.ndarray, int, int, int]:
        with wave.open(str(path), 'rb') as f:
            nchannels = f.getnchannels()
            sampwidth = f.getsampwidth()
            framerate = f.getframerate()
            frames = f.readframes(f.getnframes())
            
            if sampwidth == 1:
                dtype = np.uint8
                arr = np.frombuffer(frames, dtype=dtype).copy()
            elif sampwidth == 2:
                dtype = np.int16
                arr = np.frombuffer(frames, dtype=dtype).copy()
            elif sampwidth == 3:
                raw_data = np.frombuffer(frames, dtype=np.uint8)
                reshaped = raw_data.reshape(-1, 3)
                padded = np.pad(reshaped, ((0, 0), (0, 1)), mode='constant', constant_values=0)
                arr = padded.view(np.int32).reshape(-1)
            elif sampwidth == 4:
                dtype = np.int32
                arr = np.frombuffer(frames, dtype=dtype).copy()
            else:
                raise ValueError('Unsupported format')
                
            return arr, nchannels, sampwidth, framerate

    def __ndarray_to_bytes(self, arr: np.ndarray, sampwidth: int) -> bytes:
        if sampwidth == 3:
            reshaped = arr.view(np.uint8).reshape(-1, 4)
            return reshaped[:, :3].tobytes()
        return arr.tobytes()

    def __mix_audio_chunks(self, active_sounds: list[list], chunk_samples: int, sampwidth: int, clip_min: int, clip_max: int, dtype_out: type) -> tuple[np.ndarray, list[list]]:
        mixed_buffer = np.zeros(chunk_samples, dtype=np.int64)
        still_active = []

        for sound in active_sounds:
            arr, offset = sound
            
            if offset < 0:
                start_mixed_idx = abs(offset)
                start_sound_idx = 0
            else:
                start_mixed_idx = 0
                start_sound_idx = offset

            remaining_samples = len(arr) - start_sound_idx
            if remaining_samples <= 0:
                continue

            available_mixed_space = chunk_samples - start_mixed_idx
            if available_mixed_space <= 0:
                sound[1] += chunk_samples
                still_active.append(sound)
                continue

            take_samples = min(available_mixed_space, remaining_samples)
            sound_chunk = arr[start_sound_idx:start_sound_idx + take_samples]

            if sampwidth == 1:
                mixed_buffer[start_mixed_idx:start_mixed_idx + take_samples] += (sound_chunk.astype(np.int64) - 128)
            else:
                mixed_buffer[start_mixed_idx:start_mixed_idx + take_samples] += sound_chunk.astype(np.int64)

            new_offset = offset + chunk_samples
            if new_offset < len(arr):
                still_active.append([arr, new_offset])

        if sampwidth == 1:
            mixed_buffer += 128

        clipped = np.clip(mixed_buffer, clip_min, clip_max).astype(dtype_out)
        return clipped, still_active

    def stop(self) -> None:
        print("Closing...")
        self.running = False
        self.cleanup()

    def cleanup(self) -> None:
        if self.wave_writer:
            try:
                print("Closing program and flushing audio files...")
                self.wave_writer._patchheader()
                self.wave_writer.close()
                self.wave_writer = None
                print("Output audio file saved and finalized successfully.")
            except Exception:
                pass

    def start(self) -> None:
        for _ in range(5):
            threading.Thread(target=self.worker_process_audio, daemon=True).start()
            
        threading.Thread(target=self.playback_and_mix_worker, daemon=True).start()
        threading.Thread(target=self.command_listener, daemon=True).start()

    def command_listener(self) -> None:
        print("Command listener loop is active and monitoring input queue.")
        while self.running:
            try:
                cmd = self.input_queue.get(timeout=0.1)
                key_code = cmd["key_code"]

                if len(self.loaded_samples) > 0:
                    sample_idx = key_code % len(self.loaded_samples)
                    self.task_queue.put(self.loaded_samples[sample_idx])
            except Exception:
                continue

    def worker_process_audio(self) -> None:
        while self.running:
            try:
                arr, nchannels, sampwidth, framerate = self.task_queue.get(timeout=0.1)
                with self.active_sounds_lock:
                    self.active_sounds.append([arr, 0])
                self.task_queue.task_done()
            except Exception:
                continue

    def playback_and_mix_worker(self) -> None:
        _, nchannels, sampwidth, framerate = self.loaded_samples[0]
        
        periodsize = 512
        sleep_time = periodsize / framerate
        
        if sampwidth == 1:
            target_format = alsaaudio.PCM_FORMAT_U8
            clip_min, clip_max = 0, 255
            dtype_out = np.uint8
            silence_val = 128
        elif sampwidth == 2:
            target_format = alsaaudio.PCM_FORMAT_S16_LE
            clip_min, clip_max = -32768, 32767
            dtype_out = np.int16
            silence_val = 0
        elif sampwidth == 3:
            target_format = alsaaudio.PCM_FORMAT_S24_3LE
            clip_min, clip_max = -8388608, 8388607
            dtype_out = np.int32
            silence_val = 0
        elif sampwidth == 4:
            target_format = alsaaudio.PCM_FORMAT_S32_LE
            clip_min, clip_max = -2147483648, 2147483647
            dtype_out = np.int32
            silence_val = 0
        else:
            raise ValueError('Unsupported format')

        device_instance = alsaaudio.PCM(
            channels=nchannels,
            rate=framerate,
            format=target_format,
            periodsize=periodsize,
            device=self.device
        )

        chunk_samples = periodsize * nchannels
        chunk_bytes_len = periodsize * nchannels * sampwidth

        while self.running:
            with self.active_sounds_lock:
                current_active = list(self.active_sounds)

            if not current_active:
                silence_chunk = np.full(chunk_samples, silence_val, dtype=dtype_out)
                output_bytes = self.__ndarray_to_bytes(silence_chunk, sampwidth)
                
                if self.wave_writer:
                    try:
                        self.wave_writer.writeframes(output_bytes)
                        self.wave_writer._patchheader()
                        self.wave_writer._file.flush()
                    except Exception:
                        pass
                    
                device_instance.write(output_bytes)
                time.sleep(sleep_time)
                continue

            clipped, remaining_active = self.__mix_audio_chunks(
                current_active, 
                chunk_samples, 
                sampwidth, 
                clip_min, 
                clip_max, 
                dtype_out
            )
            
            with self.active_sounds_lock:
                for sound in current_active:
                    if sound in self.active_sounds:
                        self.active_sounds.remove(sound)
                for sound in remaining_active:
                    self.active_sounds.append(sound)

            output_bytes = self.__ndarray_to_bytes(clipped, sampwidth)

            if len(output_bytes) < chunk_bytes_len:
                if sampwidth == 1:
                    output_bytes += b'\x80' * (chunk_bytes_len - len(output_bytes))
                else:
                    output_bytes += b'\x00' * (chunk_bytes_len - len(output_bytes))

            if self.wave_writer:
                try:
                    self.wave_writer.writeframes(output_bytes)
                    self.wave_writer._patchheader()
                    self.wave_writer._file.flush()
                except Exception:
                    pass

            device_instance.write(output_bytes)


class TestMixerAllScenarios(unittest.TestCase):
    def test_recorded_file_matches_mixed_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dummy_sample_path = Path(tmpdir) / "dummy.wav"
            with wave.open(str(dummy_sample_path), 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(44100)
                dummy_signal = np.array([1000, 2000, 3000, 4000], dtype=np.int16)
                wf.writeframes(dummy_signal.tobytes())

            recorded_file_path = Path(tmpdir) / "recorded.wav"
            input_q = Queue()
            recorder_q = Queue()
            
            mixer = Mixer(
                samples=[dummy_sample_path], 
                input_queue=input_q, 
                recorder_queue=recorder_q, 
                device="default", 
                output_file=recorded_file_path
            )

            chunk_samples = 4
            active_sounds = [[mixer.loaded_samples[0][0], 0]]
            
            clipped, _ = mixer._Mixer__mix_audio_chunks(
                active_sounds, chunk_samples, 2, -32768, 32767, np.int16
            )
            
            bytes_sent_to_hardware = mixer._Mixer__ndarray_to_bytes(clipped, 2)
            mixer.wave_writer.writeframes(bytes_sent_to_hardware)
            mixer.cleanup()

            with wave.open(str(recorded_file_path), 'rb') as rf:
                recorded_frames = rf.readframes(chunk_samples)
                
            self.assertEqual(bytes_sent_to_hardware, recorded_frames)

    def test_mixing_logic_s16(self) -> None:
        mixer = Mixer.__new__(Mixer)
        chunk_samples = 4
        sound1 = np.array([100, 200, 300, 400], dtype=np.int16)
        sound2 = np.array([50, -50, 50, -50], dtype=np.int16)
        
        active_sounds = [[sound1, 0], [sound2, 0]]
        clipped, still_active = mixer._Mixer__mix_audio_chunks(
            active_sounds, chunk_samples, 2, -32768, 32767, np.int16
        )
        
        np.testing.assert_array_equal(clipped, np.array([150, 150, 350, 350], dtype=np.int16))
        self.assertEqual(len(still_active), 0)

    def test_mixing_with_offsets_and_clipping(self) -> None:
        mixer = Mixer.__new__(Mixer)
        chunk_samples = 2
        sound1 = np.array([30000, 30000, 1000], dtype=np.int16)
        sound2 = np.array([10000, -10000], dtype=np.int16)
        
        active_sounds = [[sound1, 0], [sound2, 0]]
        clipped, still_active = mixer._Mixer__mix_audio_chunks(
            active_sounds, chunk_samples, 2, -32768, 32767, np.int16
        )
        
        np.testing.assert_array_equal(clipped, np.array([32767, 20000], dtype=np.int16))
        self.assertEqual(len(still_active), 1)
        self.assertEqual(still_active[0][1], 2)

    def test_u8_bias_mixing(self) -> None:
        mixer = Mixer.__new__(Mixer)
        chunk_samples = 2
        sound1 = np.array([138, 128], dtype=np.uint8)
        sound2 = np.array([118, 138], dtype=np.uint8)
        
        active_sounds = [[sound1, 0], [sound2, 0]]
        clipped, still_active = mixer._Mixer__mix_audio_chunks(
            active_sounds, chunk_samples, 1, 0, 255, np.uint8
        )
        
        np.testing.assert_array_equal(clipped, np.array([128, 138], dtype=np.uint8))

    def test_sub_chunk_precision_mixing(self) -> None:
        mixer = Mixer.__new__(Mixer)
        chunk_samples = 10
        sound1 = np.array([10, 10, 10, 10, 10, 10, 10, 10, 10, 10], dtype=np.int16)
        sound2 = np.array([5, 5, 5, 5, 5], dtype=np.int16)
        
        active_sounds = [
            [sound1, 0],
            [sound2, -3]
        ]
        
        clipped, still_active = mixer._Mixer__mix_audio_chunks(
            active_sounds, chunk_samples, 2, -32768, 32767, np.int16
        )
        
        expected = np.array([10, 10, 10, 15, 15, 15, 15, 15, 10, 10], dtype=np.int16)
        np.testing.assert_array_equal(clipped, expected)

    def test_consecutive_calls_latency_drift(self) -> None:
        mixer = Mixer.__new__(Mixer)
        chunk_samples = 1000
        sound = np.array([10] * 2000, dtype=np.int16)
        
        active_sounds = [[sound, 0]]
        clipped_first, active_sounds = mixer._Mixer__mix_audio_chunks(
            active_sounds, chunk_samples, 2, -32768, 32767, np.int16
        )
        
        self.assertEqual(len(active_sounds), 1)
        self.assertEqual(active_sounds[0][1], 1000)
        
        clipped_second, active_sounds = mixer._Mixer__mix_audio_chunks(
            active_sounds, chunk_samples, 2, -32768, 32767, np.int16
        )
        self.assertEqual(len(active_sounds), 0)

    def test_small_period_mixing(self) -> None:
        mixer = Mixer.__new__(Mixer)
        chunk_samples = 4
        sound1 = np.array([100, 200, 300, 400, 500, 600], dtype=np.int16)
        sound2 = np.array([10, 20, 30, 40], dtype=np.int16)
        
        active_sounds = [[sound1, 0], [sound2, 0]]
        clipped, still_active = mixer._Mixer__mix_audio_chunks(
            active_sounds, chunk_samples, 2, -32768, 32767, np.int16
        )
        
        np.testing.assert_array_equal(clipped, np.array([110, 220, 330, 440], dtype=np.int16))
        self.assertEqual(len(still_active), 1)
        self.assertEqual(still_active[0][1], 4)

    def test_empty_active_sounds_returns_silence(self) -> None:
        mixer = Mixer.__new__(Mixer)
        chunk_samples = 4
        active_sounds = []
        clipped, still_active = mixer._Mixer__mix_audio_chunks(
            active_sounds, chunk_samples, 2, -32768, 32767, np.int16
        )
        np.testing.assert_array_equal(clipped, np.array([0, 0, 0, 0], dtype=np.int16))
        self.assertEqual(len(still_active), 0)


if __name__ == '__main__':
    unittest.main()