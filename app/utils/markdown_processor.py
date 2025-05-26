import logging
import os
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def split_markdown_advanced(markdown_content: str, save_dir: str = None) -> List[Dict[str, Any]]:
    """
    「今週のざっくばらん」はh2ごとにchunk分割。
    「私の目に止まった記事」はリンク行ごとにchunk分割（リンク＋コメントのセットでchunk化）。
    その他のセクションは現状維持。
    save_dir: チャンクテキストを保存するディレクトリ（Noneなら保存しない）
    """
    # セクション検出
    zakkubaran_header = re.search(r"^# 今週のざっくばらん.*$", markdown_content, re.MULTILINE)
    articles_header = re.search(r"^# 私の目に止まった記事.*$", markdown_content, re.MULTILINE)

    if not zakkubaran_header or not articles_header:
        chunks = split_markdown_by_h2(markdown_content)
        if save_dir:
            os.makedirs(save_dir, exist_ok=True)
            for i, chunk in enumerate(chunks):
                fname = os.path.join(save_dir, f"chunk_{i}.txt")
                with open(fname, "w", encoding="utf-8") as f:
                    f.write(chunk["content"])
        return chunks

    zakkubaran_start = zakkubaran_header.start()
    articles_start = articles_header.start()
    # セクション分割
    zakkubaran_section = markdown_content[zakkubaran_start:articles_start]
    articles_section = markdown_content[articles_start:]

    # ざっくばらんはh2ごとにchunk
    zakkubaran_chunks = split_markdown_by_h2(zakkubaran_section)

    # 記事セクションはリンク行ごとにchunk
    article_chunks = []
    lines = articles_section.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        line = lines[i]
        link_match = re.match(r"^\s*\[.*?\]\(.*?\)\s*$", line)
        if link_match:
            chunk_lines = [line]
            # コメント行をまとめる
            j = i + 1
            while j < len(lines) and not re.match(r"^\s*\[.*?\]\(.*?\)\s*$", lines[j]) and not re.match(r"^# ", lines[j]):
                chunk_lines.append(lines[j])
                j += 1
            article_chunks.append({"index": f"ARTICLE_{len(article_chunks)}", "content": "".join(chunk_lines)})
            i = j
        else:
            i += 1
    # もしリンク行が1つもなければ、セクション全体を1chunkに
    if not article_chunks:
        article_chunks.append({"index": "ARTICLE_0", "content": articles_section})
    # index命名規則を統一して通し番号にする
    all_chunks = zakkubaran_chunks + article_chunks
    n = len(all_chunks)
    unified_chunks = []
    if n == 1:
        unified_chunks.append({"index": "START", "content": all_chunks[0]["content"]})
    elif n == 2:
        unified_chunks.append({"index": "START", "content": all_chunks[0]["content"]})
        unified_chunks.append({"index": "END", "content": all_chunks[1]["content"]})
    else:
        unified_chunks.append({"index": "START", "content": all_chunks[0]["content"]})
        for i in range(1, n - 1):
            unified_chunks.append({"index": str(i), "content": all_chunks[i]["content"]})
        unified_chunks.append({"index": "END", "content": all_chunks[-1]["content"]})
    if save_dir:
        os.makedirs(save_dir, exist_ok=True)
        for i, chunk in enumerate(unified_chunks):
            fname = os.path.join(save_dir, f"chunk_{i}.txt")
            with open(fname, "w", encoding="utf-8") as f:
                f.write(f"[index: {chunk['index']}]\n{chunk['content']}")
    return unified_chunks


def split_markdown_by_h2(markdown_content: str) -> List[Dict[str, Any]]:
    """
    Split markdown content by h2 headers.

    First chunk: beginning to second h2 (index: START)
    Subsequent chunks: between h2 headers (index: 1, 2, 3...)
    Last chunk gets index: END

    Args:
        markdown_content: The markdown content to split

    Returns:
        List of dictionaries with 'index' and 'content' keys
    """
    logger.info("Splitting markdown content by h2 headers")
    h2_pattern = r"^## .*$"
    h2_matches = list(re.finditer(h2_pattern, markdown_content, re.MULTILINE))

    if not h2_matches:
        logger.info("No h2 headers found in markdown content")
        return [{"index": "START", "content": markdown_content}]

    chunks = []

    if len(h2_matches) > 1:
        first_chunk_end = h2_matches[1].start()
        first_chunk = markdown_content[:first_chunk_end]
        chunks.append({"index": "START", "content": first_chunk})
        logger.info(f"First chunk created, length: {len(first_chunk)}")

        for i in range(1, len(h2_matches) - 1):
            chunk_start = h2_matches[i].start()
            chunk_end = h2_matches[i + 1].start()
            chunk = markdown_content[chunk_start:chunk_end]
            chunks.append({"index": str(i), "content": chunk})
            logger.info(f"Chunk {i} created, length: {len(chunk)}")

        last_chunk_start = h2_matches[-1].start()
        last_chunk = markdown_content[last_chunk_start:]
        chunks.append({"index": "END", "content": last_chunk})
        logger.info(f"Last chunk created, length: {len(last_chunk)}")
    else:
        first_chunk = markdown_content[: h2_matches[0].start()]
        if first_chunk.strip():  # Only add if not empty
            chunks.append({"index": "START", "content": first_chunk})
            logger.info(f"First chunk created, length: {len(first_chunk)}")

        last_chunk = markdown_content[h2_matches[0].start() :]
        chunks.append({"index": "END", "content": last_chunk})
        logger.info(f"Last chunk created, length: {len(last_chunk)}")

    return chunks
