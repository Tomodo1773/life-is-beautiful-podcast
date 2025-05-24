import mimetypes
import os
import struct
from typing import Any, Dict, List

from google import genai
from google.genai import types
from pydub import AudioSegment

PODCAST_SCRIPT_PROMPT = """
エンジニアの中島聡さんのメルマガ「週刊Life is beautiful」からポッドキャスト用の台本を作成したいです。
以下のルールに従ってPodCast用の台本を生成してください 

- ベテランエンジニアであり、エンジェル投資家でもあるKaitoとアナウンサーのMinamiの二人がエンジニアの中島聡さんのメルマガ「週刊Life is beautiful」を毎週詳しく、わかりやすく視聴者に紹介する番組
- スピーカーのキャラクター
	- Kaito：ベテランエンジニアであり、エンジェル投資家。50代。ニュースでコメンテータなどでも活躍。落ち着いて聡明な話し方をする。
	- Minami：キー局のアナウンサー。若いが知的な感じ。


台本を生成するための基礎知識として以下を提供します。これを踏まえて作成してください。

『週刊Life is beautiful』は、中島聡さんが2011年から発行している有料メールマガジンです。主に「エンジニアのための経営学講座」を中心に、世界に通用するエンジニアになるための勉強法や時間の使い方、最新技術、ITビジネス、ベンチャー、キャリア設計、日米の違いなど幅広い話題を毎週火曜日に配信しています。冷静で分かりやすい筆致と豊富な知見で、読者1万人超の人気を誇ります

中島聡さん（1960年生まれ）は、日本を代表するエンジニア・起業家・エンジェル投資家です。マイクロソフト本社でWindows 95やInternet Explorerの開発責任者を務め、「Windows 95の父」と呼ばれました。2000年に起業したソフトウェア会社Xevoを2019年に売却後、シンギュラリティ・ソサエティ代表として活動。投資家としても、NVIDIAなど将来有望な企業に早くから投資し、自身の著書で「メタトレンド投資」の手法を紹介しています

- 話者ラベルはMinami/Kaitoの２名のみ
- フィラー（えーっと、うんうん、そうですね等）を適度に挿入する 
- 区切りごとに[pause 0.6sec]を入れて間を取る 
- 中島聡さんのメルマガは量が多いため、分割して台本生成が依頼されます。
	- {メルマガの内容}がindex: STARTのときはポッドキャスト（番組）のオープニングトークから台本を生成してください。「次のコーナーは〜です」みたいな受け渡しは不要です。
	- {メルマガの内容}がchunk: STARTではないときは、「では、次は～の話題です。」のようにポッドキャスト（番組）の途中に挟まる前提で生成してください。「次のコーナーは〜です」みたいな受け渡しは不要です
	- {メルマガの内容}がchunk: ENDのときはポッドキャスト（番組）全体のエンディングトークも生成してください。

Minami: さあ、今週もポッドキャストが始まりますね。[pause 0.6sec]

Kaito: そうですね。今週も盛りだくさんな内容ですね。[pause 0.6sec]


Index: {index}

contents
{content}
"""

PODCAST_CREATION_PROMPT = """
以下の内容をもとに、親しみやすいトーンで日本語の対話形式ポッドキャスト台本を作ってください。

{script}
"""


def save_binary_file(file_name: str, data: bytes) -> None:
    """Save binary data to a file."""
    with open(file_name, "wb") as f:
        f.write(data)
    print(f"File saved to: {file_name}")


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

    def generate_script(self, chunk: Dict[str, Any]) -> str:
        """
        Generate a podcast script from a markdown chunk.

        Args:
            chunk: Dictionary with 'index' and 'content' keys

        Returns:
            Generated podcast script
        """
        prompt = PODCAST_SCRIPT_PROMPT.format(index=chunk["index"], content=chunk["content"])

        model = "gemini-2.5-pro"
        response = self.client.models.generate_content(model=model, contents=[types.Content.from_text(prompt)])

        return response.text

    def generate_audio(self, script: str, output_file: str) -> str:
        """
        Generate audio from a podcast script using Gemini TTS.

        Args:
            script: The podcast script
            output_file: Path to save the audio file

        Returns:
            Path to the generated audio file
        """
        model = "gemini-2.5-flash-preview-tts"

        speaker_config = []
        speakers = {"Minami", "Kaito"}

        voice_mapping = {
            "Minami": "Puck",  # Female voice for Minami
            "Kaito": "Zephyr",  # Male voice for Kaito
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

        contents = [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])]

        generate_content_config = types.GenerateContentConfig(
            temperature=1,
            response_modalities=["audio"],
            speech_config=types.SpeechConfig(
                multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(speaker_voice_configs=speaker_config)
            ),
        )

        for chunk in self.client.models.generate_content_stream(
            model=model, contents=contents, config=generate_content_config
        ):
            if chunk.candidates is None or chunk.candidates[0].content is None or chunk.candidates[0].content.parts is None:
                continue

            if chunk.candidates[0].content.parts[0].inline_data:
                inline_data = chunk.candidates[0].content.parts[0].inline_data
                data_buffer = inline_data.data
                file_extension = mimetypes.guess_extension(inline_data.mime_type)

                if file_extension is None:
                    file_extension = ".wav"
                    data_buffer = convert_to_wav(inline_data.data, inline_data.mime_type)

                save_binary_file(f"{output_file}{file_extension}", data_buffer)
                return f"{output_file}{file_extension}"
            else:
                print(chunk.text)

        return None

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
            return None

        combined = AudioSegment.from_file(audio_files[0])

        for audio_file in audio_files[1:]:
            sound = AudioSegment.from_file(audio_file)
            combined += sound

        combined.export(output_file, format="mp3")
        return output_file

    def process_markdown_chunks(self, chunks: List[Dict[str, Any]], output_dir: str) -> str:
        """
        Process markdown chunks to generate a complete podcast.

        Args:
            chunks: List of dictionaries with 'index' and 'content' keys
            output_dir: Directory to save audio files

        Returns:
            Path to the final podcast file
        """
        os.makedirs(output_dir, exist_ok=True)

        audio_files = []
        for i, chunk in enumerate(chunks):
            script = self.generate_script(chunk)

            temp_file = os.path.join(output_dir, f"chunk_{i}")
            audio_file = self.generate_audio(script, temp_file)

            if audio_file:
                audio_files.append(audio_file)

        if audio_files:
            final_podcast = os.path.join(output_dir, "final_podcast.mp3")
            return self.concatenate_audio_files(audio_files, final_podcast)

        return None
