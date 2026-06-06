import urllib.request
from pathlib import Path

def download_sound_if_missing(file_name: str, output_dir: Path) -> Path:
    output_file = output_dir / file_name
    if not output_file.exists():
        base_url = "https://raw.githubusercontent.com/nicholastay/mechanical-sound/master/Mechanical_Click/Resources/"
        file_url = f"{base_url}{file_name}"
        try:
            urllib.request.urlretrieve(file_url, output_file)
        except Exception as e:
            if output_file.exists():
                output_file.unlink()
            raise RuntimeError(f"Network download failed for asset target: {file_name}") from e
    return output_file