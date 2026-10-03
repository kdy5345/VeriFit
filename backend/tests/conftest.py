"""테스트는 사용자 상품 DB와 대화 저장소를 건드리지 않는다."""
import os
import tempfile
from pathlib import Path

_test_data = tempfile.TemporaryDirectory(prefix="verifit-tests-")
os.environ["CHECKPOINT_PATH"] = str(Path(_test_data.name) / "conversations.sqlite")
os.environ["DB_PATH"] = str(Path(_test_data.name) / "products.db")
os.environ["CACHE_ENABLED"] = "false"
os.environ.pop("REDIS_URL", None)
