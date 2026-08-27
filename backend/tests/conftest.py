"""pytest 共享配置：sys.path + 数据目录隔离助手。

历史教训：test_impact_analysis / test_analyzer / test_param_mapping 曾长期
无数据目录隔离，直接把测试数据（chain1/cyc1 等）写进真实 backend/data，
覆盖过线上数据。所有会触碰 store 的测试模块必须在 setup_module 里调用
redirect_store()、teardown_module 里 restore_store()（与 test_store/test_api
的内联重定向等价；此处提供共享实现避免三份拷贝）。
"""
import os
import pathlib
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import store  # noqa: E402

_FILES = {
    "TABLES_FILE": "tables.json",
    "EDGES_FILE": "edges.jsonl",
    "PREPROCESS_RULES_FILE": "preprocess_rules.json",
    "TAG_SCHEMA_FILE": "tag_schema.json",
    "PARAM_MAPPING_FILE": "param_mapping.json",
}

_saved: dict[str, object] = {}
_tmp_dir: pathlib.Path | None = None


def redirect_store() -> pathlib.Path:
    """把 store 的全部文件路径重定向到新临时目录（并清内存缓存）。"""
    global _tmp_dir
    _saved.clear()
    for attr in [*_FILES, "DATA_DIR", "SCRIPTS_DIR", "LOCK_FILE"]:
        _saved[attr] = getattr(store, attr)
    _tmp_dir = pathlib.Path(tempfile.mkdtemp(prefix="lineage-test-"))
    store.DATA_DIR = _tmp_dir
    for attr, fname in _FILES.items():
        setattr(store, attr, _tmp_dir / fname)
    store.SCRIPTS_DIR = _tmp_dir / "scripts"
    store.LOCK_FILE = _tmp_dir / "store.lock"
    store.reset_caches()
    return _tmp_dir


def restore_store() -> None:
    """恢复原始路径并删除临时目录。"""
    global _tmp_dir
    for attr, value in _saved.items():
        setattr(store, attr, value)
    _saved.clear()
    store.reset_caches()
    if _tmp_dir is not None:
        shutil.rmtree(str(_tmp_dir), ignore_errors=True)
        _tmp_dir = None
