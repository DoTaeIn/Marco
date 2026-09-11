"""설치 직후 기본 런타임은 외부 모델 다운로드 없이 열려야 한다."""

import os
import subprocess
import sys
from pathlib import Path


def test_default_encoder_is_the_local_character_runtime():
    env = dict(os.environ)
    env.pop("KG_ENCODER", None)
    result = subprocess.run(
        [sys.executable, "-c", "import encoder; print(encoder.MODEL)"],
        cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, text=True, check=True,
    )

    assert result.stdout.strip().startswith("문자포함도")
