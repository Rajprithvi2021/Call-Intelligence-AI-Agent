"""Generate a two-speaker test recording from a sample transcript with Gemini TTS.

    python scripts/make_sample_audio.py data/samples/collections_wrong_number.txt data/samples/wrong_number.wav

Only for exercising the audio path; real deployments ingest real recordings.
"""
import argparse
import os
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.genai import types  # noqa: E402

from app import llm, transcript  # noqa: E402

TTS_MODEL = os.getenv("TTS_MODEL", "gemini-2.5-flash-preview-tts")
VOICES = ["Kore", "Puck", "Charon", "Aoede"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript", type=Path)
    ap.add_argument("out", type=Path)
    args = ap.parse_args()

    lines = transcript.parse_text(args.transcript.read_text(encoding="utf-8"))
    speakers = list(dict.fromkeys(l.speaker for l in lines))
    if len(speakers) > 2:
        sys.exit("Gemini multi-speaker TTS supports two speakers")
    script = "\n".join(f"{l.speaker}: {l.text}" for l in lines)

    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(speaker_voice_configs=[
                types.SpeakerVoiceConfig(
                    speaker=s,
                    voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICES[i])),
                )
                for i, s in enumerate(speakers)
            ])
        ),
    )
    resp = llm.client().models.generate_content(
        model=TTS_MODEL, contents=f"Read this phone call naturally:\n{script}", config=config)
    pcm = resp.candidates[0].content.parts[0].inline_data.data

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(args.out), "wb") as wf:  # Gemini TTS returns 24 kHz, 16-bit mono PCM
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(pcm)
    print(f"wrote {args.out} ({len(pcm) / 48000:.1f}s)")


if __name__ == "__main__":
    main()
