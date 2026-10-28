import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch

from daw2bms.adaptive import cut, next_tail
from daw2bms.flp import FlpError
from daw2bms.keysounds import load_manifest, tick_to_frame
from test_flp import fixture, note
from test_keysounds import BankFixture, np, sf


class TailEstimationTests(unittest.TestCase):
    def test_prediction_uses_observed_level_and_decay(self):
        first = next_tail({"release_tail_seconds": 1, "tail_peak": 0.01, "decay_db_per_second": -20}, -60, 30)
        second = next_tail({"release_tail_seconds": 2, "tail_peak": 0.1, "decay_db_per_second": -10}, -60, 30)
        self.assertNotEqual(first, second)
        self.assertGreater(first, 1)
        self.assertGreater(second, 2)

    def test_flat_tail_grows_relatively_and_respects_cap(self):
        self.assertEqual(next_tail({"release_tail_seconds": 0.75, "tail_peak": 0.1, "decay_db_per_second": 0}, -60, 30), 1.5)
        self.assertEqual(next_tail({"release_tail_seconds": 20, "tail_peak": 0.1, "decay_db_per_second": None}, -60, 30), 30)


@unittest.skipIf(sf is None, "Install [audio] extra")
class AdaptiveTests(BankFixture):
    def fake_renderer(self, manifests):
        def render(manifest_path, exe, **kwargs):
            manifest = load_manifest(manifest_path)
            manifests.append(manifest)
            rate = 8000
            timing = manifest["timing"]
            frames = tick_to_frame(manifest["bank"]["length_ticks"], timing["ppq"], timing["bpm"], rate)
            output = np.zeros((frames, 2), dtype="float32")
            for key in manifest["keys"]:
                start = tick_to_frame(key["onset_ticks"], timing["ppq"], timing["bpm"], rate)
                times = np.arange(frames - start) / rate
                hold = key["length_ticks"] / timing["ppq"] * 60 / timing["bpm"]
                tau = 0.005 if key["key"] == 60 else 0.12
                envelope = 0.5 * np.exp(-np.maximum(0, times - hold) / tau)
                signal = envelope * np.sin(times * 2 * math.pi * 440)
                output[start:] += signal[:, None]
            sf.write(manifest_path.parent / "render_bank.wav", output, rate, subtype="FLOAT")
            return {"status": "rendered"}
        return render

    def test_only_failed_keys_are_retried_and_final_duration_follows_audio(self):
        self.source.write_bytes(fixture(notes=note() + note(96, key=61)))
        manifests = []
        with patch("daw2bms.adaptive.render", side_effect=self.fake_renderer(manifests)):
            result = cut(self.source, self.destination, self.root / "FL.exe", initial_tail=0.1,
                         max_tail=3, max_attempts=4, progress=lambda message: None)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(manifests[0]["keys"]), 2)
        self.assertTrue(all(len(m["keys"]) == 1 for m in manifests[1:]))
        self.assertTrue(all(m["keys"][0]["id"] == "k0002" for m in manifests[1:]))
        short = sf.info(self.destination / "keysounds/k0001.wav")
        long = sf.info(self.destination / "keysounds/k0002.wav")
        self.assertGreater(long.duration, short.duration)
        self.assertNotEqual(short.frames, long.frames)
        self.assertEqual(len(list((self.destination / "keysounds").glob("*.wav"))), 2)
        self.assertTrue((self.destination / "song.mid").exists())

    def test_attempt_limit_does_not_publish_a_complete_pack(self):
        self.source.write_bytes(fixture(notes=note(key=61)))
        with patch("daw2bms.adaptive.render", side_effect=self.fake_renderer([])):
            with self.assertRaisesRegex(FlpError, "attempt limit"):
                cut(self.source, self.destination, self.root / "FL.exe", initial_tail=0.1,
                    max_tail=2, max_attempts=1, progress=lambda message: None)
        self.assertFalse((self.destination / "keysounds").exists())
        status = json.loads((self.destination / "result.json").read_text())
        self.assertEqual(status["status"], "attempt_limit")
        self.assertTrue((self.destination / "song.mid").exists())


if __name__ == "__main__":
    unittest.main()
