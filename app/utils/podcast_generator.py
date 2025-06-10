import concurrent.futures
import logging
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

## ポッドキャストの内容
- 中島聡さんにアナウンサーのMinamiがインタビューする形で中島聡さんのメルマガ「週刊Life is beautiful」を毎週詳しく、わかりやすく視聴者に紹介する番組
- スピーカーのキャラクター
	- Nakajima：中島聡(ナカジマ サトシ)さん（1960年生まれ）は、日本を代表するエンジニア・起業家・エンジェル投資家です。マイクロソフト本社でWindows 95やInternet Explorerの開発責任者を務め、「Windows 95の父」と呼ばれました。2000年に起業したソフトウェア会社Xevoを2019年に売却後、シンギュラリティ・ソサエティ代表として活動。投資家としても、NVIDIAなど将来有望な企業に早くから投資し、自身の著書で「メタトレンド投資」の手法を紹介しています
	- Minami：アナウンサー。若いが知性を感じる話し方。
- 『週刊Life is beautiful』とは
    - 『週刊Life is beautiful』は、中島聡(ナカジマ サトシ)さんが2011年から発行している有料メールマガジンです。主に「エンジニアのための経営学講座」を中心に、世界に通用するエンジニアになるための勉強法や時間の使い方、最新技術、ITビジネス、ベンチャー、キャリア設計、日米の違いなど幅広い話題を毎週火曜日に配信しています。冷静で分かりやすい筆致と豊富な知見で、読者1万人超の人気を誇ります

## ルール
- 話者ラベルはMinami/Nakajimaの２名のみ
- フィラー（えーっと、うんうん、そうですね等）を適度に挿入する 
- 区切りごとに[pause 0.6sec]を入れて間を取る 
- 中島聡さんのメルマガは量が多いため、分割して台本生成が依頼されます。
	- Index: STARTのときは番組冒頭の原稿をつくるときです。
        ポッドキャスト（番組）のオープニングトークから台本を生成してください。スムーズに次のコーナーに移るように余計な総括や、次コーナーへの導入は不要です。
	- Index: STARTでもENDではないときは、番組の途中部分の台本を作成するときです。
        「では、次は～の話題です。」のようにすでに始めっている番組前提で余計な前振りをせずにスムーズに始めてください。また、スムーズに次のコーナーに移るように余計な総括や、次コーナーへの導入は不要です。
	- Index: ENDのときは番組のラストパートの原稿を作る時です。
        ポッドキャスト（番組）全体のエンディングトークも生成してください。
- 最後の文章には[pause 1.0sec]の長めのpauseを入れる。

## 出力例

Index: START（番組冒頭の原稿をつくる）のとき
```
Minami: さあ、今週もポッドキャストが始まりますね。[pause 0.6sec]

Nakajima: はい、よろしくお願いします。[pause 0.6sec]

Minami: Nakajimaさん、今週も早速、中島聡さんのメルマガ「週刊Life is beautiful」を深掘りしていきましょう。[pause 0.6sec] 今週号、まず最初のトピックはXXですね？

~

Minami: 以上、XXについてでした。[pause 1.0sec]
```

IndexがSTARTでもENDでもなく番組途中の原稿の時
```
Minami: さあ、次のコーナーは～についてです。[pause 0.6sec]

~

Minami: 以上、XXについてでした。[pause 1.0sec]

```

IndexがENDのとき
```
Minami: さあ、次のコーナーはXXについてです。[pause 0.6sec]

~

Minami: それでは、今週の「週刊Life is beautiful拾い読みポッドキャスト」はここまでとさせていただきます。[pause 0.6sec] リスナーの皆さん、最後までお聴きいただき、ありがとうございました。

Nakajima: ありがとうございました。

Minami: また来週、お会いしましょう。[pause 1.0sec]
```


# 作成する原稿のIndex
Index: {index}

## 原稿のもととなるメルマガの内容
{content}
"""

PODCAST_CREATION_PROMPT = """
以下の内容をもとに、親しみやすいトーンで日本語の対話形式ポッドキャスト台本を作ってください。

{script}
"""

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


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
        lines = script.split('\n')
        
        for line in lines:
            # Check if adding this line would exceed the limit
            if len(current_chunk) + len(line) + 1 > max_chars and current_chunk:
                chunks.append(current_chunk.rstrip())
                current_chunk = line + '\n'
            else:
                current_chunk += line + '\n'
        
        # Add the last chunk if it has content
        if current_chunk.strip():
            chunks.append(current_chunk.rstrip())
        
        return chunks

    def generate_script(self, chunk: Dict[str, Any]) -> str:
        """
        Generate a podcast script from a markdown chunk.

        Args:
            chunk: Dictionary with 'index' and 'content' keys

        Returns:
            Generated podcast script
        """
        prompt = PODCAST_SCRIPT_PROMPT.format(index=chunk["index"], content=chunk["content"])
        logger.info(f"Generating script for chunk index: {chunk['index']}")
        model = "gemini-2.5-flash-preview-05-20"
        response = self.client.models.generate_content(model=model, contents=[types.Content(parts=[types.Part(text=prompt)])])
        logger.info(f"Script generated for chunk index: {chunk['index']}")
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
        speakers = {"Minami", "Nakajima"}

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

        # スクリプトもtmp/scripts配下に保存する！
        scripts_dir = os.path.join("tmp", "scripts")
        os.makedirs(scripts_dir, exist_ok=True)
        # output_fileのファイル名部分を使って保存
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

        logger.info("Generating audio for podcast script")
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
                logger.info(f"Audio file generated: {output_file}{file_extension}")
                return f"{output_file}{file_extension}"
            else:
                logger.info(f"Text chunk: {chunk.text}")

        logger.error("Audio generation failed: No audio data returned")
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
            logger.error("No audio files provided for concatenation")
            return None

        logger.info(f"Concatenating {len(audio_files)} audio files")
        combined = AudioSegment.from_file(audio_files[0])

        for audio_file in audio_files[1:]:
            sound = AudioSegment.from_file(audio_file)
            combined += sound

        combined.export(output_file, format="wav")
        logger.info(f"Concatenated audio file saved: {output_file}")
        return output_file

    def process_markdown_chunks(self, chunks: List[Dict[str, Any]]) -> str:
        """
        Process markdown chunks to generate a complete podcast.

        Args:
            chunks: List of dictionaries with 'index' and 'content' keys

        Returns:
            Path to the final podcast file
        """
        base_output_dir = "tmp"
        scripts_dir = os.path.join(base_output_dir, "scripts")
        audio_chunks_dir = os.path.join(base_output_dir, "audio_chunks")
        final_audio_dir = os.path.join(base_output_dir, "final_audio")
        os.makedirs(scripts_dir, exist_ok=True)
        os.makedirs(audio_chunks_dir, exist_ok=True)
        os.makedirs(final_audio_dir, exist_ok=True)

        # スクリプト生成も並列でやる！
        def script_task(args):
            i, chunk = args
            script = self.generate_script(chunk)
            
            # スクリプトを分割
            script_chunks = self.split_script(script)
            
            # 分割されたスクリプトをファイル保存
            saved_scripts = []
            for j, script_chunk in enumerate(script_chunks):
                if len(script_chunks) == 1:
                    script_file = os.path.join(scripts_dir, f"chunk_{i}.txt")
                else:
                    script_file = os.path.join(scripts_dir, f"chunk_{i}_{j+1}.txt")
                    
                with open(script_file, "w", encoding="utf-8") as f:
                    f.write(script_chunk)
                saved_scripts.append((f"{i}_{j+1}" if len(script_chunks) > 1 else str(i), script_chunk))
            
            return saved_scripts

        with concurrent.futures.ThreadPoolExecutor() as executor:
            script_results = list(executor.map(script_task, [(i, chunk) for i, chunk in enumerate(chunks)]))
        
        # フラットな結果リストに変換
        all_scripts = []
        for result_list in script_results:
            all_scripts.extend(result_list)
        
        # インデックス順に並べ直す
        all_scripts.sort(key=lambda x: x[0])
        scripts = [s for _, s in all_scripts]

        # TTS（音声生成）も並列でやる！
        def tts_task(args):
            index, script = args
            temp_file = os.path.join(audio_chunks_dir, f"chunk_{index}")
            return (index, self.generate_audio(script, temp_file))

        with concurrent.futures.ThreadPoolExecutor() as executor:
            audio_results = list(executor.map(tts_task, [(all_scripts[i][0], scripts[i]) for i in range(len(scripts))]))
        # インデックス順に並べ直す
        audio_results.sort(key=lambda x: x[0])
        audio_files = [f for _, f in audio_results if f]

        if audio_files:
            final_podcast = os.path.join(final_audio_dir, "final_podcast.wav")
            return self.concatenate_audio_files(audio_files, final_podcast)
        return None
