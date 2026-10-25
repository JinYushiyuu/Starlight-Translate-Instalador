import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="starlight-test-")
os.environ["STARLIGHT_CONFIG_DIR"] = os.path.join(_tmp, "cfg")
os.environ["STARLIGHT_CACHE_DIR"] = os.path.join(_tmp, "cache")
