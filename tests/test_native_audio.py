"""Native audio conversion regression: runs AVAudioConverter, without microphone/speaker access."""
import json
import shutil
import subprocess
import sys

import pytest

from native_audio import build_helper


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("xcrun"), reason="macOS Swift helper")
def test_native_microphone_channel_conversion_preserves_signal():
    result = subprocess.run([str(build_helper()), "--check-conversion"], capture_output=True, text=True,
                            timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    cases = json.loads(result.stdout)["conversion_checks"]
    assert {(case["channels"], case["interleaved"]) for case in cases} == {
        (channels, interleaved) for channels in (1, 2, 9) for interleaved in (False, True)
    }
    assert all(case["samples"] > 1000 and 4000 < case["rms"] < 5000 for case in cases)
