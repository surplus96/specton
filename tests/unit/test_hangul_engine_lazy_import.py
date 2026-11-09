"""rhwp(한글 읽기 엔진)를 불러오지 못하는 환경에서도 앱·시험이 뜨는지 확인한다 (#24).

배경: rhwp-python 0.8.1의 리눅스 휠은 묶어 둔 FreeType에 함수가 빠져 있어, 시스템 FreeType을
먼저 불러오는 환경 변수(LD_PRELOAD)가 없으면 `import rhwp`가 ImportError로 실패한다(상류 이슈
DanMeon/rhwp-python #31). `import rhwp`가 모듈 맨 위에 있으면 이 한 줄 때문에
`specton.ingest.hangul`, `specton.parse_node`, `specton.api.main`을 불러오는 것 전부가
실패해 앱이 뜨지 않는다.
그래서 엔진은 쓰는 순간(`read_blocks` 호출 때) 불러오고, 실패하면 `EngineError`로 알린다.

`rhwp`를 일부러 불러올 수 없게 하려고 새 파이썬 프로세스에서 `sys.modules["rhwp"] = None`으로
막는다(None이면 import가 ImportError를 낸다). 이 프로세스의 다른 시험에는 영향이 없다.
"""

import subprocess
import sys
from pathlib import Path

_BLOCK_RHWP = "import sys; sys.modules['rhwp'] = None; "


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _BLOCK_RHWP + code],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
        check=False,
    )


def test_modules_import_even_when_rhwp_is_unavailable() -> None:
    """rhwp를 못 불러와도 한글 읽기 모듈과 이를 쓰는 parse 노드까지 import는 된다."""
    done = _run("import specton.ingest.hangul, specton.ingest.hangul_engine")
    assert done.returncode == 0, done.stderr


def test_read_blocks_reports_engine_error_when_rhwp_is_unavailable() -> None:
    """엔진을 쓰는 순간에는 EngineError로 알린다(파일 문제인 HangulFormatError가 아님)."""
    code = (
        "from pathlib import Path\n"
        "from specton.ingest.hangul_engine import EngineError, read_blocks\n"
        "try:\n"
        "    read_blocks(Path('없는파일.hwpx'))\n"
        "except EngineError as exc:\n"
        "    print('ENGINE_ERROR', exc)\n"
        "else:\n"
        "    raise SystemExit('EngineError가 나야 한다')\n"
    )
    done = _run(code)
    assert done.returncode == 0, done.stderr
    assert "ENGINE_ERROR" in done.stdout
    assert "rhwp" in done.stdout


def test_read_hangul_turns_missing_engine_into_file_level_notice() -> None:
    """parse 노드가 아는 UnsupportedInput으로 바뀌어, 실행이 안내 문구와 함께 끝난다."""
    code = (
        "from pathlib import Path\n"
        "from specton.ingest.hangul import read_hangul\n"
        "from specton.ingest.tabular import UnsupportedInput\n"
        "try:\n"
        "    read_hangul(Path('없는파일.hwpx'), 'doc')\n"
        "except UnsupportedInput as exc:\n"
        "    print('UNSUPPORTED', exc.notice)\n"
        "else:\n"
        "    raise SystemExit('UnsupportedInput이 나야 한다')\n"
    )
    done = _run(code)
    assert done.returncode == 0, done.stderr
    assert "UNSUPPORTED" in done.stdout
