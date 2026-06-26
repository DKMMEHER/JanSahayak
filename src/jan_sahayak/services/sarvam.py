"""
Sarvam AI Service — Wrapper around the Sarvam AI SDK.

Provides clean helper methods for all 6 Sarvam AI APIs:
1. Speech-to-Text (Saaras STT v3)
2. Text-to-Speech (Bulbul TTS v3)
3. Chat / LLM (Sarvam-30B)
4. Translation (Mayura)
5. Language Detection
6. Document Digitization
"""

from typing import Any

import httpx
from langsmith import traceable

from jan_sahayak.config import get_settings
from jan_sahayak.logger import get_logger

logger = get_logger(__name__)

# Sarvam AI API base URL
SARVAM_BASE_URL = "https://api.sarvam.ai"

# Supported Indian languages with full names and ISO codes
SUPPORTED_LANGUAGES = {
    "hindi": "hi-IN",
    "english": "en-IN",
    "bengali": "bn-IN",
    "tamil": "ta-IN",
    "telugu": "te-IN",
    "marathi": "mr-IN",
    "gujarati": "gu-IN",
    "kannada": "kn-IN",
    "malayalam": "ml-IN",
    "odia": "or-IN",
    "punjabi": "pa-IN",
    "assamese": "as-IN",
    "urdu": "ur-IN",
}


class SarvamService:
    """
    Unified service for interacting with all Sarvam AI APIs.
    Uses httpx for async HTTP calls to the Sarvam API.
    """

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.sarvam_api_key
        self.headers = {
            "api-subscription-key": self.api_key,
        }

    def _get_language_code(self, language: str) -> str:
        """Convert full language name to Sarvam AI language code."""
        return SUPPORTED_LANGUAGES.get(language.lower(), "hi-IN")

    # ========== 1. Speech-to-Text (Saaras STT v3) ==========

    @traceable(name="Sarvam STT")
    async def speech_to_text(self, audio_bytes: bytes, language: str = "hindi") -> dict[str, Any]:
        """
        Convert speech audio to text using Saaras STT v3.

        Args:
            audio_bytes: Raw audio file bytes (WAV, MP3, etc.)
            language: Language of the audio (e.g., "hindi", "tamil")

        Returns:
            {"transcript": "...", "language_code": "hi-IN"}
        """
        language_code = self._get_language_code(language)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{SARVAM_BASE_URL}/speech-to-text",
                headers=self.headers,
                files={"file": ("audio.wav", audio_bytes, "audio/wav")},
                data={
                    "model": "saaras:v3",
                    "language_code": language_code,
                },
            )
            response.raise_for_status()
            result = response.json()

        logger.info(f"STT result: {result.get('transcript', '')[:100]}...")
        return {
            "transcript": result.get("transcript", ""),
            "language_code": language_code,
        }

    # ========== 2. Text-to-Speech (Bulbul TTS v3) ==========

    @traceable(name="Sarvam TTS")
    async def text_to_speech(self, text: str, language: str = "hindi") -> str:
        """
        Convert text to speech audio using Bulbul TTS v3.

        Args:
            text: Text to convert to speech
            language: Target language (e.g., "hindi", "tamil")

        Returns:
            Base64-encoded audio string
        """
        language_code = self._get_language_code(language)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{SARVAM_BASE_URL}/text-to-speech",
                headers={**self.headers, "Content-Type": "application/json"},
                json={
                    "inputs": [text],
                    "target_language_code": language_code,
                    "model": "bulbul:v3",
                    "enable_preprocessing": True,
                },
            )
            response.raise_for_status()
            result = response.json()

        audio_base64 = result.get("audios", [None])[0]
        logger.info(f"TTS generated for {len(text)} chars in {language}")
        return audio_base64 or ""

    # ========== 3. Chat / LLM (Sarvam-30B) ==========

    @traceable(name="Sarvam Chat", run_type="llm")
    async def chat(self, messages: list[dict[str, str]], temperature: float = 0.7) -> str:
        """
        Chat with Sarvam-30B LLM for scheme matching and explanations.

        Args:
            messages: List of {"role": "user/assistant/system", "content": "..."}
            temperature: Creativity level (0.0 = focused, 1.0 = creative)

        Returns:
            Assistant's reply text
        """
        import asyncio
        max_retries = 3
        last_error = None

        for attempt in range(1, max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(
                        f"{SARVAM_BASE_URL}/v1/chat/completions",
                        headers={**self.headers, "Content-Type": "application/json"},
                        json={
                            "model": "sarvam-30b",
                            "messages": messages,
                            "temperature": temperature,
                            "max_tokens": 2048,
                            "reasoning_effort": "low",
                        },
                    )
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as e:
                        logger.error(f"Sarvam API Chat failed with status {response.status_code}. Response: {response.text}")
                        raise e
                    result = response.json()

                reply_raw = result["choices"][0]["message"].get("content") or ""
                import re

                # Strip <think>...</think> reasoning tags, keeping only the output after them
                reply = re.sub(r"<think>.*?</think>", "", reply_raw, flags=re.DOTALL).strip()
                
                # If stripping think tags left us with nothing, the answer was INSIDE the tags
                if not reply and "<think>" in reply_raw:
                    think_match = re.search(r"<think>(.*?)</think>", reply_raw, flags=re.DOTALL)
                    if think_match:
                        reply = think_match.group(1).strip()
                        logger.info(f"LLM reply was inside <think> tags, extracted {len(reply)} chars")
                
                # Last resort: if still empty, use the raw response
                if not reply:
                    reply = reply_raw.strip()
                
                logger.info(f"LLM reply ({len(reply)} chars): {reply[:200]}...")
                return reply

            except (httpx.ReadTimeout, httpx.ReadError, httpx.ConnectError) as e:
                last_error = e
                logger.warning(f"Chat attempt {attempt}/{max_retries} failed: {type(e).__name__}: {e}")
                if attempt < max_retries:
                    await asyncio.sleep(2 * attempt)
                else:
                    raise

    # ========== 4. Translation (Mayura) ==========

    @traceable(name="Sarvam Translate")
    async def translate(self, text: str, source_language: str = "english", target_language: str = "hindi") -> str:
        """
        Translate text between languages using Mayura.

        Args:
            text: Text to translate
            source_language: Source language name (e.g., "english")
            target_language: Target language name (e.g., "hindi")

        Returns:
            Translated text
        """
        source_code = self._get_language_code(source_language)
        target_code = self._get_language_code(target_language)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{SARVAM_BASE_URL}/translate",
                headers={**self.headers, "Content-Type": "application/json"},
                json={
                    "input": text,
                    "source_language_code": source_code,
                    "target_language_code": target_code,
                    "model": "mayura:v1",
                    "enable_preprocessing": True,
                },
            )
            response.raise_for_status()
            result = response.json()

        translated = result.get("translated_text", text)
        logger.info(f"Translated {source_language} → {target_language}: {translated[:100]}...")
        return translated

    # ========== 5. Language Detection ==========

    @traceable(name="Sarvam Language Detect")
    async def detect_language(self, text: str) -> dict[str, Any]:
        """
        Detect the language of input text.

        Args:
            text: Text to detect language for

        Returns:
            {"language_code": "hi-IN", "language_name": "hindi", "confidence": 0.95}
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{SARVAM_BASE_URL}/detect-language",
                headers={**self.headers, "Content-Type": "application/json"},
                json={"input": text},
            )
            response.raise_for_status()
            result = response.json()

        lang_code = result.get("language_code", "hi-IN")

        # Reverse lookup: code → name
        lang_name = "hindi"
        for name, code in SUPPORTED_LANGUAGES.items():
            if code == lang_code:
                lang_name = name
                break

        logger.info(f"Detected language: {lang_name} ({lang_code})")
        return {
            "language_code": lang_code,
            "language_name": lang_name,
            "confidence": result.get("confidence", 0.0),
        }

    # ========== 6. Document Digitization ==========

    @traceable(name="Sarvam Document Digitization")
    async def digitize_document(self, file_bytes: bytes, file_name: str = "document.pdf") -> dict[str, Any]:
        """
        Digitize a document (Aadhaar, PAN, income cert) using Sarvam Vision.

        Args:
            file_bytes: Raw document file bytes (PDF, PNG, JPG)
            file_name: Original file name

        Returns:
            Extracted structured data from the document
        """
        import tempfile
        import os
        import asyncio
        from sarvamai import AsyncSarvamAI
        import httpx

        api_key = self.headers.get("api-subscription-key") or os.getenv("SARVAM_API_KEY")

        # Determine correct file extension from the original filename
        ext = os.path.splitext(file_name)[1].lower() if "." in file_name else ".pdf"
        if ext not in (".pdf", ".png", ".jpg", ".jpeg", ".zip"):
            ext = ".pdf"

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_file:
            temp_path = temp_file.name
            temp_file.write(file_bytes)

        max_retries = 3
        last_error = None

        try:
            for attempt in range(1, max_retries + 1):
                try:
                    logger.info(f"Document digitization attempt {attempt}/{max_retries} for '{file_name}'")
                    client = AsyncSarvamAI(api_subscription_key=api_key)

                    # 1. Create Job
                    job = await client.document_intelligence.create_job(
                        language="hi-IN",
                        output_format="md"
                    )
                    logger.info(f"Job created: {job.job_id}")

                    # 2. Upload file
                    await job.upload_file(temp_path)
                    logger.info(f"File uploaded for job {job.job_id}")

                    # 3. Start processing
                    await job.start()
                    logger.info(f"Job {job.job_id} started, waiting for completion...")

                    # 4. Wait with timeout (120s max)
                    await job.wait_until_complete(timeout=120.0)
                    logger.info(f"Job {job.job_id} completed!")

                    # 5. Get download links
                    dl_res = await client.document_intelligence.get_download_links(job_id=job.job_id)
                    zip_url = None
                    json_url = None
                    if hasattr(dl_res, "download_urls") and dl_res.download_urls:
                        for file_key, details in dl_res.download_urls.items():
                            url = getattr(details, "file_url", "")
                            if file_key.endswith(".json") or ".json" in url:
                                json_url = url
                            if file_key.endswith(".zip") or ".zip" in url:
                                zip_url = url

                    target_url = zip_url or json_url
                    if not target_url:
                        available = list(getattr(dl_res, "download_urls", {}).keys())
                        raise Exception(f"No downloadable result found (Available: {available})")

                    # 6. Download the result
                    async with httpx.AsyncClient(timeout=60.0) as http_client:
                        res = await http_client.get(target_url)
                        res.raise_for_status()

                        if target_url == zip_url:
                            import zipfile
                            import io

                            with zipfile.ZipFile(io.BytesIO(res.content)) as z:
                                # Prefer .md, fallback to .json
                                md_files = [f for f in z.namelist() if f.endswith(".md")]
                                json_files = [f for f in z.namelist() if f.endswith(".json")]
                                logger.info(f"ZIP contents: {z.namelist()}")

                                if md_files:
                                    with z.open(md_files[0]) as mf:
                                        result = {"markdown": mf.read().decode("utf-8")}
                                elif json_files:
                                    import json as json_mod
                                    with z.open(json_files[0]) as jf:
                                        result = json_mod.load(jf)
                                else:
                                    raise Exception(f"ZIP has no .md or .json files: {z.namelist()}")
                        else:
                            result = res.json()

                    # Success — break out of retry loop
                    break

                except (httpx.ReadError, httpx.ConnectError, httpx.TimeoutException, TimeoutError) as e:
                    last_error = e
                    logger.warning(f"Attempt {attempt}/{max_retries} failed with network error: {e}")
                    if attempt < max_retries:
                        await asyncio.sleep(2 * attempt)  # exponential backoff
                    else:
                        raise Exception(f"Document digitization failed after {max_retries} attempts: {e}") from e

        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        # Log result summary
        import json
        result_str = json.dumps(result, ensure_ascii=False)
        logger.info(f"Document digitized via sarvamai SDK: {file_name}")
        logger.info(f"RAW RESULT (first 2000 chars): {result_str[:2000]}")
        return result


# Singleton instance
sarvam_service = SarvamService()
