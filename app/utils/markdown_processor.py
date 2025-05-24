import re
from typing import List, Dict, Any, Tuple

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
    h2_pattern = r'^## .*$'
    h2_matches = list(re.finditer(h2_pattern, markdown_content, re.MULTILINE))
    
    if not h2_matches:
        return [{'index': 'START', 'content': markdown_content}]
    
    chunks = []
    
    if len(h2_matches) > 1:
        first_chunk_end = h2_matches[1].start()
        first_chunk = markdown_content[:first_chunk_end]
        chunks.append({'index': 'START', 'content': first_chunk})
        
        for i in range(1, len(h2_matches) - 1):
            chunk_start = h2_matches[i].start()
            chunk_end = h2_matches[i + 1].start()
            chunk = markdown_content[chunk_start:chunk_end]
            chunks.append({'index': str(i), 'content': chunk})
        
        last_chunk_start = h2_matches[-1].start()
        last_chunk = markdown_content[last_chunk_start:]
        chunks.append({'index': 'END', 'content': last_chunk})
    else:
        first_chunk = markdown_content[:h2_matches[0].start()]
        if first_chunk.strip():  # Only add if not empty
            chunks.append({'index': 'START', 'content': first_chunk})
        
        last_chunk = markdown_content[h2_matches[0].start():]
        chunks.append({'index': 'END', 'content': last_chunk})
    
    return chunks
