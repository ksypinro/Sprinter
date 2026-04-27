import os
from pathlib import Path
import time

class FileLock:
    def __init__(self, path: Path):
        self.path = path

    def acquire(self, timeout: float = 10.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                os.makedirs(self.path)
                return True
            except FileExistsError:
                time.sleep(0.1)
        return False

    def release(self):
        try:
            os.removedirs(self.path)
        except OSError:
            pass
