from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

try:
    import requests
except Exception:  # noqa: BLE001
    requests = None  # type: ignore[assignment]

from storage.json_store import load_json, save_json
from storage.memory_lock import MEMORY_IO_LOCK
from utils.logger import get_logger
from utils.time_utils import now_iso


logger = get_logger(__name__)


DEFAULT_VECTOR_INDEX = {
    "schema_version": "1.0",
    "embedding_signature": "",
    "items": [],
    "last_synced_at": "",
    "last_semantic_merge_at": "",
}

DEFAULT_VECTOR_PRECISION = 6
DEFAULT_VECTOR_MIN_TEXT_LENGTH = 3
DEFAULT_VECTOR_MAX_ITEMS = 300


@dataclass(frozen=True)
class MemoryTextItem:
    id: str
    path: str
    text: str
    order: int


class MemoryEmbeddingClient:
    # 初始化当前对象及其依赖。
    def __init__(self, memory_config: dict[str, Any]) -> None:
        """初始化当前对象及其依赖。"""
        self.memory_config = memory_config
        self.api_key = self._dashscope_api_key(memory_config)
        self.base_url = str(
            memory_config.get(
                "dashscope_embedding_base_url",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            )
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ).strip()
        self.model = str(memory_config.get("dashscope_embedding_model", "text-embedding-v4") or "").strip()
        self.model = self.model or "text-embedding-v4"
        self.dimensions = self._positive_int(memory_config.get("dashscope_embedding_dimensions", 1024), 1024)
        self.encoding_format = str(memory_config.get("dashscope_embedding_encoding_format", "float") or "float")
        self.timeout_seconds = self._positive_int(
            memory_config.get("memory_embedding_timeout_seconds", 30),
            30,
        )

    # 判断必需配置是否完整，并返回客户端是否可以调用。
    def is_configured(self) -> bool:
        """判断必需配置是否完整，并返回客户端是否可以调用。"""
        return bool(self.api_key and self.base_url and self.model)

    # 用向量接口地址、模型、维度和编码格式生成配置签名。
    def signature(self) -> str:
        """用向量接口地址、模型、维度和编码格式生成配置签名。"""
        return "|".join([self.base_url, self.model, str(self.dimensions), self.encoding_format])

    # 把多段文本按批次提交给向量接口，并返回对应向量列表。
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """把多段文本按批次提交给向量接口，并返回对应向量列表。"""
        if not self.is_configured():
            return []

        embeddings: list[list[float]] = []
        batch_size = self._positive_int(self.memory_config.get("memory_embedding_batch_size", 8), 8)
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            embeddings.extend(self._embed_batch(batch))
        return embeddings

    # 根据 texts 调用 DashScope 向量接口，并按返回索引组装向量列表。
    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """根据 texts 调用 DashScope 向量接口，并按返回索引组装向量列表。"""
        if requests is None:
            raise RuntimeError("requests is not installed")
        response = requests.post(
            f"{self.base_url.rstrip('/')}/embeddings",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "input": texts,
                "dimensions": self.dimensions,
                "encoding_format": self.encoding_format,
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        raw_items = payload.get("data", [])
        if not isinstance(raw_items, list):
            raise ValueError("Embedding response data is not a list")

        ordered = sorted(raw_items, key=lambda item: int(item.get("index", 0)) if isinstance(item, dict) else 0)
        vectors: list[list[float]] = []
        for item in ordered:
            if not isinstance(item, dict) or not isinstance(item.get("embedding"), list):
                raise ValueError("Embedding response item is malformed")
            vectors.append([float(value) for value in item["embedding"]])
        if len(vectors) != len(texts):
            raise ValueError("Embedding response count does not match input count")
        return vectors

    # 根据 memory_config 从环境变量或配置中读取 DashScope API 密钥。
    def _dashscope_api_key(self, memory_config: dict[str, Any]) -> str:
        """根据 memory_config 从环境变量或配置中读取 DashScope API 密钥。"""
        configured_key = str(memory_config.get("dashscope_api_key", "") or "").strip()
        if configured_key:
            return configured_key

        env_name = str(memory_config.get("dashscope_api_key_env", "DASHSCOPE_API_KEY") or "").strip()
        env_name = env_name or "DASHSCOPE_API_KEY"
        return str(os.getenv(env_name, "") or "").strip()

    # 根据 value、default 转换为正整数，失败或小于等于零时返回默认值。
    def _positive_int(self, value: Any, default: int) -> int:
        """根据 value、default 转换为正整数，失败或小于等于零时返回默认值。"""
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default


class MemoryVectorStore:
    # 初始化当前对象及其依赖。
    def __init__(self, path: str | Path, app_config: dict[str, Any]) -> None:
        """初始化当前对象及其依赖。"""
        self.path = Path(path)
        self.app_config = app_config

    # 替换运行中的应用配置，供后续向量同步读取。
    def update_config(self, app_config: dict[str, Any]) -> None:
        """替换运行中的应用配置，供后续向量同步读取。"""
        self.app_config = app_config

    # 根据当前记忆内容刷新向量索引，并在配置缺失时跳过同步。
    def sync_memory(self, memory: dict[str, Any]) -> None:
        """根据当前记忆内容刷新向量索引，并在配置缺失时跳过同步。"""
        memory_config = self._memory_config()
        if not memory_config.get("enable_memory_vectors", True):
            return

        client = MemoryEmbeddingClient(memory_config)
        if not client.is_configured():
            logger.info("Skip memory vector sync because embedding configuration is incomplete.")
            return

        with MEMORY_IO_LOCK:
            index = self._load_index()
            embedding_signature = self._embedding_signature(client)
            if index.get("embedding_signature") != embedding_signature:
                index["embedding_signature"] = embedding_signature
                index["items"] = []

            text_items = self._iter_memory_texts(memory)
            existing = {
                str(item.get("id")): item
                for item in index.get("items", [])
                if isinstance(item, dict)
            }
            current_ids = {item.id for item in text_items}
            missing_items = [item for item in text_items if item.id not in existing]

        if missing_items:
            try:
                vectors = client.embed_texts([item.text for item in missing_items])
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to generate memory embeddings: %s", exc)
                return
        else:
            vectors = []

        with MEMORY_IO_LOCK:
            new_items = [
                {
                    "id": item.id,
                    "path": item.path,
                    "text": item.text,
                    "order": item.order,
                    "embedding": self._compress_embedding(vector),
                    "updated_at": now_iso(),
                }
                for item, vector in zip(missing_items, vectors)
            ]
            index = self._load_index()
            if index.get("embedding_signature") != embedding_signature:
                index["embedding_signature"] = embedding_signature
                index["items"] = new_items
            else:
                fresh_existing = {
                    str(item.get("id")): item
                    for item in index.get("items", [])
                    if isinstance(item, dict) and str(item.get("id")) in current_ids
                }
                ordered_items = []
                for item in text_items:
                    if item.id in fresh_existing:
                        stored = dict(fresh_existing[item.id])
                        stored["order"] = item.order
                        ordered_items.append(stored)
                ordered_items.extend(new_items)
                index["items"] = ordered_items
            index["items"] = self._limit_items(index["items"])
            index["last_synced_at"] = now_iso()
            self._save_index(index)

    # 到期时执行记忆语义去重，并保存合并后的记忆文件。
    def run_due_semantic_merge(self, memory_path: str | Path) -> dict[str, Any]:
        """到期时执行记忆语义去重，并保存合并后的记忆文件。"""
        memory_config = self._memory_config()
        if not memory_config.get("enable_semantic_memory_merge", True):
            return {"status": "disabled", "merged_count": 0}
        if not memory_config.get("enable_memory_vectors", True):
            return {"status": "vectors_disabled", "merged_count": 0}
        if not self.is_semantic_merge_due():
            return {"status": "not_due", "merged_count": 0}

        with MEMORY_IO_LOCK:
            memory = load_json(memory_path, {})
        self.sync_memory(memory)
        if not self._load_index().get("items"):
            return {"status": "no_vectors", "merged_count": 0}
        result = self._merge_semantic_duplicates(memory_path)
        self._mark_semantic_merge_finished()
        return result

    # 根据上次合并时间判断是否该执行语义去重。
    def is_semantic_merge_due(self) -> bool:
        """根据上次合并时间判断是否该执行语义去重。"""
        index = self._load_index()
        last_run = str(index.get("last_semantic_merge_at", "") or "").strip()
        if not last_run:
            return True

        try:
            last_dt = datetime.fromisoformat(last_run)
        except ValueError:
            return True
        interval_days = self._positive_int(
            self._memory_config().get("semantic_merge_interval_days", 60),
            60,
        )
        return datetime.now() - last_dt >= timedelta(days=interval_days)

    # 根据 memory_path 按语义相似度合并重复记忆，并保存精简结果。
    def _merge_semantic_duplicates(self, memory_path: str | Path) -> dict[str, Any]:
        """根据 memory_path 按语义相似度合并重复记忆，并保存精简结果。"""
        threshold = self._float_value(
            self._memory_config().get("semantic_duplicate_similarity_threshold", 0.96),
            0.96,
        )
        index = self._load_index()
        items = [item for item in index.get("items", []) if isinstance(item, dict)]
        duplicate_groups = self._duplicate_groups(items, threshold)
        if not duplicate_groups:
            return {"status": "completed", "merged_count": 0}

        with MEMORY_IO_LOCK:
            memory = load_json(memory_path, {})
            merged_count = self._apply_duplicate_groups(memory, duplicate_groups)
            if merged_count:
                memory["last_updated"] = now_iso()
                save_json(memory_path, memory)

        if merged_count:
            self.sync_memory(memory)
        return {"status": "completed", "merged_count": merged_count}

    # 根据 items、threshold 根据相似度阈值把重复记忆划分为分组。
    def _duplicate_groups(self, items: list[dict[str, Any]], threshold: float) -> list[list[dict[str, Any]]]:
        """根据 items、threshold 根据相似度阈值把重复记忆划分为分组。"""
        groups_by_path: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            path = str(item.get("path", "") or "")
            text = str(item.get("text", "") or "").strip()
            embedding = item.get("embedding")
            if path and text and isinstance(embedding, list):
                groups_by_path.setdefault(path, []).append(item)

        duplicate_groups: list[list[dict[str, Any]]] = []
        for path_items in groups_by_path.values():
            parent = list(range(len(path_items)))

            # 查找并返回并查集节点的根索引。
            def find(index: int) -> int:
                """查找并返回并查集节点的根索引。"""
                while parent[index] != index:
                    parent[index] = parent[parent[index]]
                    index = parent[index]
                return index

            # 合并两个并查集分组，保持语义重复项属于同一集合。
            def union(left: int, right: int) -> None:
                """合并两个并查集分组，保持语义重复项属于同一集合。"""
                left_root = find(left)
                right_root = find(right)
                if left_root != right_root:
                    parent[right_root] = left_root

            for left_index, left_item in enumerate(path_items):
                for right_index in range(left_index + 1, len(path_items)):
                    right_item = path_items[right_index]
                    if self._is_semantic_duplicate(left_item, right_item, threshold):
                        union(left_index, right_index)

            clusters: dict[int, list[dict[str, Any]]] = {}
            for index, item in enumerate(path_items):
                clusters.setdefault(find(index), []).append(item)
            duplicate_groups.extend(cluster for cluster in clusters.values() if len(cluster) > 1)
        return duplicate_groups

    # 根据 left_item、right_item、threshold 判断语义duplicate是否满足条件并返回布尔结果。
    def _is_semantic_duplicate(
        self,
        left_item: dict[str, Any],
        right_item: dict[str, Any],
        threshold: float,
    ) -> bool:
        """根据 left_item、right_item、threshold 判断语义duplicate是否满足条件并返回布尔结果。"""
        left_text = str(left_item.get("text", "") or "").strip()
        right_text = str(right_item.get("text", "") or "").strip()
        if not left_text or not right_text or left_text == right_text:
            return bool(left_text and left_text == right_text)
        if self._has_negation_mismatch(left_text, right_text):
            return False

        score = self._cosine_similarity(left_item.get("embedding"), right_item.get("embedding"))
        return score >= threshold

    # 根据 memory、duplicate_groups 整理apply duplicate groups，并把结果交给调用方或写回状态。
    def _apply_duplicate_groups(
        self,
        memory: dict[str, Any],
        duplicate_groups: list[list[dict[str, Any]]],
    ) -> int:
        """根据 memory、duplicate_groups 整理apply duplicate groups，并把结果交给调用方或写回状态。"""
        by_path: dict[str, list[list[dict[str, Any]]]] = {}
        for group in duplicate_groups:
            path = str(group[0].get("path", "") or "")
            if path:
                by_path.setdefault(path, []).append(group)

        merged_count = 0
        for path, groups in by_path.items():
            node = self._node_for_path(memory, path)
            if not isinstance(node, list):
                continue
            new_values: list[Any] = list(node)
            for items in groups:
                duplicate_texts = {str(item.get("text", "") or "").strip() for item in items}
                duplicate_texts.discard("")
                if len(duplicate_texts) < 2:
                    continue

                representative = self._representative_text(items)
                replaced = False
                next_values: list[Any] = []
                for value in new_values:
                    text = str(value).strip() if isinstance(value, str) else ""
                    if text in duplicate_texts:
                        if not replaced:
                            next_values.append(representative)
                            replaced = True
                        else:
                            merged_count += 1
                        continue
                    next_values.append(value)
                new_values = next_values
            if new_values != node:
                node[:] = new_values
        return merged_count

    # 根据 items 从重复分组中选择信息量最高的代表文本。
    def _representative_text(self, items: list[dict[str, Any]]) -> str:
        """根据 items 从重复分组中选择信息量最高的代表文本。"""
        ordered = sorted(
            items,
            key=lambda item: (
                -len(str(item.get("text", "") or "")),
                int(item.get("order", 0) or 0),
            ),
        )
        return str(ordered[0].get("text", "") or "").strip()

    # 记录语义合并完成时间，避免短时间内重复维护。
    def _mark_semantic_merge_finished(self) -> None:
        """记录语义合并完成时间，避免短时间内重复维护。"""
        with MEMORY_IO_LOCK:
            index = self._load_index()
            index["last_semantic_merge_at"] = now_iso()
            self._save_index(index)

    # 根据 memory 遍历嵌套数据中的文本项，过滤空值后逐条返回。
    def _iter_memory_texts(self, memory: dict[str, Any]) -> list[MemoryTextItem]:
        """根据 memory 遍历嵌套数据中的文本项，过滤空值后逐条返回。"""
        items: list[MemoryTextItem] = []
        seen: set[tuple[str, str]] = set()
        min_text_length = self._memory_vector_min_text_length()

        # 根据 node、path 整理visit，并把结果交给调用方或写回状态。
        def visit(node: Any, path: list[str]) -> None:
            """根据 node、path 整理visit，并把结果交给调用方或写回状态。"""
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in {"schema_version", "last_updated"}:
                        continue
                    visit(value, [*path, key])
            elif isinstance(node, list):
                list_path = ".".join(path)
                for value in node:
                    if not isinstance(value, str):
                        continue
                    text = value.strip()
                    if not text or len(text) < min_text_length:
                        continue
                    key = (list_path, text)
                    if key in seen:
                        continue
                    seen.add(key)
                    items.append(
                        MemoryTextItem(
                            id=self._item_id(list_path, text),
                            path=list_path,
                            text=text,
                            order=len(items),
                        )
                    )

        visit(memory, [])
        return items

    # 根据 memory、path 处理文件路径或 JSON 内容，保持读写结果稳定。
    def _node_for_path(self, memory: dict[str, Any], path: str) -> Any:
        """根据 memory、path 处理文件路径或 JSON 内容，保持读写结果稳定。"""
        node: Any = memory
        for part in path.split("."):
            if not isinstance(node, dict):
                return None
            node = node.get(part)
        return node

    # 读取记忆向量索引，缺失或损坏时返回默认索引。
    def _load_index(self) -> dict[str, Any]:
        """读取记忆向量索引，缺失或损坏时返回默认索引。"""
        index = load_json(self.path, DEFAULT_VECTOR_INDEX)
        if not isinstance(index, dict):
            return dict(DEFAULT_VECTOR_INDEX)
        index.setdefault("schema_version", "1.0")
        index.setdefault("embedding_signature", "")
        index.setdefault("items", [])
        index.setdefault("last_synced_at", "")
        index.setdefault("last_semantic_merge_at", "")
        return index

    # 把记忆向量索引写入 JSON 文件。
    def _save_index(self, index: dict[str, Any]) -> None:
        """把记忆向量索引写入 JSON 文件。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(f"{self.path.name}.tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as file:
                json.dump(index, file, ensure_ascii=False, separators=(",", ":"))
                file.flush()
                os.fsync(file.fileno())
            os.replace(tmp_path, self.path)
        except Exception:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError as exc:
                logger.warning("Failed to remove temporary memory vector file %s: %s", tmp_path, exc)
            raise

    # 根据 client 读取向量客户端签名，用于判断索引是否需要重建。
    def _embedding_signature(self, client: MemoryEmbeddingClient) -> str:
        """根据 client 读取向量客户端签名，用于判断索引是否需要重建。"""
        return f"{client.signature()}|precision={self._memory_vector_precision()}"

    # 根据 embedding 按配置精度压缩向量数值，减小 JSON 索引体积。
    def _compress_embedding(self, embedding: list[float]) -> list[float]:
        """根据 embedding 按配置精度压缩向量数值，减小 JSON 索引体积。"""
        precision = self._memory_vector_precision()
        return [round(float(value), precision) for value in embedding]

    # 根据 items 按重要度和时间排序裁剪向量索引条目。
    def _limit_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """根据 items 按重要度和时间排序裁剪向量索引条目。"""
        max_items = self._memory_vector_max_items()
        valid_items = [item for item in items if isinstance(item, dict)]
        if len(valid_items) <= max_items:
            return valid_items

        ranked = sorted(
            valid_items,
            key=lambda item: (
                self._memory_item_importance(str(item.get("path", "") or "")),
                self._timestamp_score(str(item.get("updated_at", "") or "")),
                -int(item.get("order", 0) or 0),
            ),
            reverse=True,
        )
        keep_ids = {str(item.get("id")) for item in ranked[:max_items]}
        return [item for item in valid_items if str(item.get("id")) in keep_ids]

    # 根据 path 处理记忆数据，保持本地记忆和外部索引一致。
    def _memory_item_importance(self, path: str) -> int:
        """根据 path 处理记忆数据，保持本地记忆和外部索引一致。"""
        if path.startswith("relationship_memory."):
            return 30
        if path.startswith("work_study.current_projects"):
            return 25
        if path.startswith("work_study.current_learning_topics"):
            return 20
        if path.startswith("user_profile.important_personal_notes"):
            return 20
        if path.startswith("user_profile.preferences"):
            return 15
        return 10

    # 根据 value 把 ISO 时间转换为排序分数，无法解析时返回零。
    def _timestamp_score(self, value: str) -> float:
        """根据 value 把 ISO 时间转换为排序分数，无法解析时返回零。"""
        try:
            return datetime.fromisoformat(value).timestamp()
        except ValueError:
            return 0.0

    # 处理记忆数据，保持本地记忆和外部索引一致。
    def _memory_vector_precision(self) -> int:
        """处理记忆数据，保持本地记忆和外部索引一致。"""
        return self._positive_int(
            self._memory_config().get("memory_vector_precision", DEFAULT_VECTOR_PRECISION),
            DEFAULT_VECTOR_PRECISION,
        )

    # 处理记忆数据，保持本地记忆和外部索引一致。
    def _memory_vector_min_text_length(self) -> int:
        """处理记忆数据，保持本地记忆和外部索引一致。"""
        return self._positive_int(
            self._memory_config().get("memory_vector_min_text_length", DEFAULT_VECTOR_MIN_TEXT_LENGTH),
            DEFAULT_VECTOR_MIN_TEXT_LENGTH,
        )

    # 处理记忆数据，保持本地记忆和外部索引一致。
    def _memory_vector_max_items(self) -> int:
        """处理记忆数据，保持本地记忆和外部索引一致。"""
        return self._positive_int(
            self._memory_config().get("memory_vector_max_items", DEFAULT_VECTOR_MAX_ITEMS),
            DEFAULT_VECTOR_MAX_ITEMS,
        )

    # 读取配置片段，缺失时返回安全默认配置。
    def _memory_config(self) -> dict[str, Any]:
        """读取配置片段，缺失时返回安全默认配置。"""
        return self.app_config.setdefault("memory", {})

    # 根据 path、text 用记忆路径和文本生成稳定哈希 ID。
    def _item_id(self, path: str, text: str) -> str:
        """根据 path、text 用记忆路径和文本生成稳定哈希 ID。"""
        raw = f"{path}\n{text}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    # 根据 left、right 计算两个向量的余弦相似度并返回分数。
    def _cosine_similarity(self, left: Any, right: Any) -> float:
        """根据 left、right 计算两个向量的余弦相似度并返回分数。"""
        if not isinstance(left, list) or not isinstance(right, list) or len(left) != len(right):
            return 0.0
        left_values = [float(value) for value in left]
        right_values = [float(value) for value in right]
        dot = sum(a * b for a, b in zip(left_values, right_values))
        left_norm = math.sqrt(sum(value * value for value in left_values))
        right_norm = math.sqrt(sum(value * value for value in right_values))
        if not left_norm or not right_norm:
            return 0.0
        return dot / (left_norm * right_norm)

    # 根据 left、right 判断negationmismatch是否满足条件并返回布尔结果。
    def _has_negation_mismatch(self, left: str, right: str) -> bool:
        """根据 left、right 判断negationmismatch是否满足条件并返回布尔结果。"""
        negations = ["不", "别", "不要", "不想", "不喜欢", "讨厌", "避免", "拒绝", "no", "not", "never"]
        left_has = any(word in left.lower() for word in negations)
        right_has = any(word in right.lower() for word in negations)
        return left_has != right_has

    # 根据 value、default 转换为正整数，失败或小于等于零时返回默认值。
    def _positive_int(self, value: Any, default: int) -> int:
        """根据 value、default 转换为正整数，失败或小于等于零时返回默认值。"""
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    # 根据 value、default 转换为浮点数，失败时返回默认值。
    def _float_value(self, value: Any, default: float) -> float:
        """根据 value、default 转换为浮点数，失败时返回默认值。"""
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if 0 < parsed <= 1 else default
