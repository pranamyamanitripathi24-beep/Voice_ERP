"""
Text-to-Speech — slide 3/4 ("closes the interaction loop"). Uses pyttsx3
(offline, no API key, works on Windows/Mac/Linux) by default. Swap in a
cloud TTS (e.g. ElevenLabs, Azure, Google) here for higher-quality voices
without touching any other module — `speak()` and `synthesize_to_file()`
are the only two entry points the rest of the app relies on.
"""


def speak(text: str):
    """Speaks text aloud immediately (blocking). Requires a real audio
    output device — use synthesize_to_file() in headless/server environments."""
    import pyttsx3
    engine = pyttsx3.init()
    engine.say(text)
    engine.runAndWait()


def synthesize_to_file(text: str, out_path: str = "response.wav"):
    """Renders speech to a .wav file instead of playing it directly — useful
    for a server (like the FastAPI app here) that streams audio back to a
    web/mobile client rather than owning the speaker itself."""
    import pyttsx3
    engine = pyttsx3.init()
    engine.save_to_file(text, out_path)
    engine.runAndWait()
    return out_path
