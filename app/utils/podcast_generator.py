import asyncio
from dataclasses import dataclass
import logging
import mimetypes
import os
import random
import struct
import wave
from collections.abc import Awaitable, Callable
from typing import Any, Dict, List, TypeVar

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydub import AudioSegment

PODCAST_CONTEXT = """
ルールに従って、「## 原稿のもととなる内容」からエンジニアの中島聡さんのポッドキャスト「週刊Life is beautiful」の台本を作成してください。

## ポッドキャストの内容
- 中島聡さんにアナウンサーのMinamiがインタビューする形のポッドキャスト。タイトル「週刊Life is beautiful」
- スピーカーのキャラクター
	- Nakajima：中島聡(ナカジマ サトシ)さん（1960年生まれ）は、日本を代表するエンジニア・起業家・エンジェル投資家です。マイクロソフト本社でWindows 95やInternet Explorerの開発責任者を務め、「Windows 95の父」と呼ばれました。2000年に起業したソフトウェア会社Xevoを2019年に売却後、シンギュラリティ・ソサエティ代表として活動。投資家としても、NVIDIAなど将来有望な企業に早くから投資し、自身の著書で「メタトレンド投資」の手法を紹介しています
	- Minami：アナウンサー。若いが知性を感じる話し方。
- 『週刊Life is beautiful』は、中島聡(ナカジマ サトシ)さんが発行するポッドキャスト。主に「エンジニアのための経営学講座」を中心に、世界に通用するエンジニアになるための勉強法や時間の使い方、最新技術、ITビジネス、ベンチャー、キャリア設計、日米の違いなど幅広い話題を毎週火曜日に配信。冷静で分かりやすい思考と豊富な知見で、リスナー1万人超の人気を誇る

## 共通ルール
- 話者ラベルはMinami/Nakajimaの２名のみ
- フィラー（えーっと、うんうん、そうですね等）を適度に挿入する
- 区切りごとに[pause 0.6sec]を入れて間を取る
- 元の内容は一切割愛せず、すべての内容、発言をトランスクリプトに含める
- 最後の文章には[pause 1.0sec]の長めのpauseを入れる
"""

PODCAST_SCRIPT_PROMPT_START = """
{context}

## ルール（冒頭専用）
- ポッドキャストの開始挨拶を入れる。

## 出力例（冒頭）
```
Minami: さあ、今週もポッドキャスト「週刊Life is beautiful」が始まりますね。[pause 0.6sec]

Nakajima: はい、よろしくお願いします。[pause 0.6sec]

Minami: Nakajimaさん、今週の最初のトピックはXXですね？

~

Minami: 以上、XXについてでした。[pause 1.0sec]
```

## 原稿のもととなる内容
{content}
"""

PODCAST_SCRIPT_PROMPT_MID = """
{context}

## ルール（番組中間専用）
- すでに番組は開始しており、途中のコーナーであることを意識する。
- 「さあ、次のコーナーは～についてです。」から始める。
- 最後は「以上、XXについてでした。」で締める。
- 「今週もポッドキャスト「週刊Life is beautiful」が始まりますね。」や「よろしくお願いします。」などの開始挨拶は入れない。


## 出力例（途中）
```
Minami: さあ、次のコーナーは～についてです。[pause 0.6sec]

~

Minami: 以上、XXについてでした。[pause 1.0sec]
```

## 原稿のもととなる内容
{content}
"""

PODCAST_SCRIPT_PROMPT_END = """
{context}

## ルール（エンディング専用）
- すでに番組は開始しており、最後のコーナーであることを意識する。
- 「さて、最後のコーナーですが、～についてです。」から始める。
- 番組全体の締めくくりを行い、感謝と次回案内を入れる。

## 出力例（エンディング）
```
Minami: さあ、次のコーナーはXXについてです。[pause 0.6sec]

~

Minami: それでは、今週の「週刊Life is beautiful」はここまでとさせていただきます。[pause 0.6sec] リスナーの皆さん、最後までお聴きいただき、ありがとうございました。

Nakajima: ありがとうございました。

Minami: また来週、お会いしましょう。[pause 1.0sec]
```

## 原稿のもととなる内容
{content}
"""

PODCAST_CREATION_PROMPT = """
以下の内容をもとに、親しみやすいトーンで日本語の対話形式ポッドキャスト台本を作ってください。

{script}
"""

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


@dataclass(frozen=True)
class RetryConfig:
    max_retries: int = 8
    initial_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    backoff_factor: float = 2.0
    jitter_ratio: float = 0.2


T = TypeVar("T")


def _extract_status_code(exc: BaseException) -> int | None:
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    return None


def _is_retryable_exception(exc: BaseException) -> bool:
    if isinstance(exc, genai_errors.APIError):
        code = _extract_status_code(exc)
        if code in {429, 500, 502, 503, 504}:
            return True
    code = _extract_status_code(exc)
    if code in {429, 500, 502, 503, 504}:
        return True
    return isinstance(exc, (TimeoutError, OSError, ConnectionError, asyncio.TimeoutError))


def _extract_retry_delay_seconds(exc: BaseException) -> float | None:
    retry_delay = getattr(exc, "retry_delay", None) or getattr(exc, "retryDelay", None)
    if retry_delay is None:
        return None
    if isinstance(retry_delay, (int, float)):
        return float(retry_delay)
    total_seconds = getattr(retry_delay, "total_seconds", None)
    if callable(total_seconds):
        try:
            return float(total_seconds())
        except Exception:
            return None
    return None


async def _call_with_retry_async(
    *,
    operation: str,
    attempt_once: Callable[[], Awaitable[T]],
    retry: RetryConfig,
) -> T:
    delay = retry.initial_delay_seconds
    attempt = 0
    while True:
        try:
            return await attempt_once()
        except Exception as exc:
            attempt += 1
            if attempt > retry.max_retries or not _is_retryable_exception(exc):
                raise

            retry_after = _extract_retry_delay_seconds(exc)
            sleep_seconds = min(retry_after if retry_after is not None else delay, retry.max_delay_seconds)
            sleep_seconds += random.uniform(0.0, sleep_seconds * retry.jitter_ratio)

            code = _extract_status_code(exc)
            logger.warning(
                "%s failed (attempt %s/%s, code=%s). Retrying in %.2fs: %s",
                operation,
                attempt,
                retry.max_retries,
                code,
                sleep_seconds,
                exc,
            )
            await asyncio.sleep(sleep_seconds)
            delay = min(delay * retry.backoff_factor, retry.max_delay_seconds)


def save_binary_file(file_name: str, data: bytes) -> None:
    """Save binary data to a file."""
    with open(file_name, "wb") as f:
        f.write(data)
    logger.info(f"File saved to: {file_name}")


def convert_to_wav(audio_data: bytes, mime_type: str) -> bytes:
    """
    Generates a WAV file header for the given audio data and parameters.

    Args:
        audio_data: The raw audio data as a bytes object.
        mime_type: Mime type of the audio data.

    Returns:
        A bytes object representing the WAV file header.
    """
    parameters = parse_audio_mime_type(mime_type)
    bits_per_sample = parameters["bits_per_sample"]
    sample_rate = parameters["rate"]
    num_channels = 1
    data_size = len(audio_data)
    bytes_per_sample = bits_per_sample // 8
    block_align = num_channels * bytes_per_sample
    byte_rate = sample_rate * block_align
    chunk_size = 36 + data_size  # 36 bytes for header fields before data chunk size

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",  # ChunkID
        chunk_size,  # ChunkSize (total file size - 8 bytes)
        b"WAVE",  # Format
        b"fmt ",  # Subchunk1ID
        16,  # Subchunk1Size (16 for PCM)
        1,  # AudioFormat (1 for PCM)
        num_channels,  # NumChannels
        sample_rate,  # SampleRate
        byte_rate,  # ByteRate
        block_align,  # BlockAlign
        bits_per_sample,  # BitsPerSample
        b"data",  # Subchunk2ID
        data_size,  # Subchunk2Size (size of audio data)
    )
    return header + audio_data


def parse_audio_mime_type(mime_type: str) -> Dict[str, int]:
    """
    Parses bits per sample and rate from an audio MIME type string.

    Assumes bits per sample is encoded like "L16" and rate as "rate=xxxxx".

    Args:
        mime_type: The audio MIME type string (e.g., "audio/L16;rate=24000").

    Returns:
        A dictionary with "bits_per_sample" and "rate" keys.
    """
    bits_per_sample = 16
    rate = 24000

    parts = mime_type.split(";")
    for param in parts:  # Skip the main type part
        param = param.strip()
        if param.lower().startswith("rate="):
            try:
                rate_str = param.split("=", 1)[1]
                rate = int(rate_str)
            except (ValueError, IndexError):
                pass  # Keep rate as default
        elif param.startswith("audio/L"):
            from contextlib import suppress

            with suppress(ValueError, IndexError):
                bits_per_sample = int(param.split("L", 1)[1])

    return {"bits_per_sample": bits_per_sample, "rate": rate}


class PodcastGenerator:
    def __init__(self, api_key: str):
        """
        Initialize the podcast generator with the Gemini API key.

        Args:
            api_key: Gemini API key
        """
        self.client = genai.Client(api_key=api_key)

    def _select_prompt_template(self, index: str) -> str:
        """
        Select prompt template by index semantic type.
        """
        key = (index or "").strip().upper()
        if key == "START":
            return PODCAST_SCRIPT_PROMPT_START
        if key == "END":
            return PODCAST_SCRIPT_PROMPT_END
        return PODCAST_SCRIPT_PROMPT_MID

    def split_script(self, script: str, max_chars: int = 3000) -> List[str]:
        """
        Split a script into smaller chunks based on character count, breaking at newlines.

        Args:
            script: The script text to split
            max_chars: Maximum characters per chunk (default: 3000)

        Returns:
            List of script chunks
        """
        if not script or not script.strip():
            return []

        if len(script) <= max_chars:
            return [script]

        chunks = []
        current_chunk = ""
        lines = script.split("\n")

        for line in lines:
            # Check if adding this line would exceed the limit
            if len(current_chunk) + len(line) + 1 > max_chars and current_chunk:
                chunks.append(current_chunk.rstrip())
                current_chunk = line + "\n"
            else:
                current_chunk += line + "\n"

        # Add the last chunk if it has content
        if current_chunk.strip():
            chunks.append(current_chunk.rstrip())

        return chunks

    async def generate_script_async(self, chunk: Dict[str, Any], *, retry: RetryConfig | None = None) -> str:
        retry = retry or RetryConfig()

        prompt_template = self._select_prompt_template(chunk.get("index"))
        prompt = prompt_template.format(context=PODCAST_CONTEXT, content=chunk.get("content"))
        logger.info("Generating script (async) for chunk index: %s", chunk.get("index"))
        model = "gemini-3-pro-preview"

        async def attempt_once() -> str:
            response = await self.client.aio.models.generate_content(
                model=model, contents=[types.Content(parts=[types.Part(text=prompt)])]
            )
            if not getattr(response, "text", None):
                raise RuntimeError("Gemini generate_content returned empty text")
            return response.text

        script = await _call_with_retry_async(operation="generate_script", attempt_once=attempt_once, retry=retry)
        logger.info("Script generated (async) for chunk index: %s", chunk.get("index"))
        return script

    async def generate_audio_async(self, script: str, output_file: str, *, retry: RetryConfig | None = None) -> str:
        retry = retry or RetryConfig()

        model = "gemini-2.5-flash-preview-tts"

        speaker_config = []
        speakers = ["Minami", "Nakajima"]

        voice_mapping = {
            "Minami": "Zephyr",  # Female voice for Minami
            "Nakajima": "Enceladus",  # Male voice for Nakajima
        }

        for speaker in speakers:
            speaker_config.append(
                types.SpeakerVoiceConfig(
                    speaker=speaker,
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_mapping[speaker])
                    ),
                )
            )

        prompt = PODCAST_CREATION_PROMPT.format(script=script)

        scripts_dir = os.path.join("tmp", "scripts")
        os.makedirs(scripts_dir, exist_ok=True)
        script_filename = os.path.basename(output_file) + ".txt"
        script_path = os.path.join(scripts_dir, script_filename)
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script)

        contents = [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])]

        generate_content_config = types.GenerateContentConfig(
            temperature=1,
            response_modalities=["audio"],
            speech_config=types.SpeechConfig(
                multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(speaker_voice_configs=speaker_config)
            ),
        )

        async def attempt_once() -> str:
            logger.info("Generating audio (async) for podcast script")
            stream = await self.client.aio.models.generate_content_stream(
                model=model, contents=contents, config=generate_content_config
            )

            async for chunk in stream:
                if (
                    chunk.candidates is None
                    or chunk.candidates[0].content is None
                    or chunk.candidates[0].content.parts is None
                ):
                    continue

                if chunk.candidates[0].content.parts[0].inline_data:
                    inline_data = chunk.candidates[0].content.parts[0].inline_data
                    data_buffer = inline_data.data
                    file_extension = mimetypes.guess_extension(inline_data.mime_type)

                    if file_extension is None:
                        file_extension = ".wav"
                        data_buffer = convert_to_wav(inline_data.data, inline_data.mime_type)

                    save_binary_file(f"{output_file}{file_extension}", data_buffer)
                    logger.info("Audio file generated (async): %s%s", output_file, file_extension)
                    return f"{output_file}{file_extension}"

            raise RuntimeError("Audio generation failed: No audio data returned")

        return await _call_with_retry_async(operation="generate_audio", attempt_once=attempt_once, retry=retry)

    def concatenate_audio_files(self, audio_files: List[str], output_file: str) -> str:
        """
        Concatenate multiple audio files into one.

        Args:
            audio_files: List of audio file paths
            output_file: Path to save the concatenated audio file

        Returns:
            Path to the concatenated audio file
        """
        if not audio_files:
            logger.error("No audio files provided for concatenation")
            return None

        logger.info(f"Concatenating {len(audio_files)} audio files")

        # waveモジュールでストリーミング連結してメモリ使用を抑える
        try:
            with wave.open(audio_files[0], "rb") as first_wav:
                params = first_wav.getparams()
        except wave.Error:
            logger.exception("Failed to read first audio file: %s", audio_files[0])
            return None

        try:
            with wave.open(output_file, "wb") as out_wav:
                out_wav.setparams(params)

                for audio_file in audio_files:
                    try:
                        with wave.open(audio_file, "rb") as src:
                            if (
                                src.getnchannels() != params.nchannels
                                or src.getframerate() != params.framerate
                                or src.getsampwidth() != params.sampwidth
                            ):
                                logger.error(
                                    "Audio params mismatch in %s; expected %s", audio_file, params
                                )
                                return None

                            # 64KB相当のフレーム単位で読み書きして常時メモリを抑制
                            frames_per_chunk = 65536
                            while True:
                                chunk = src.readframes(frames_per_chunk)
                                if not chunk:
                                    break
                                out_wav.writeframes(chunk)
                    except wave.Error:
                        logger.exception("Failed to read audio file: %s", audio_file)
                        return None
        except wave.Error:
            logger.exception("Failed to write concatenated audio file: %s", output_file)
            return None

        logger.info(f"Concatenated audio file saved: {output_file}")
        return output_file
