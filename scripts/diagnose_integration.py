import asyncio
import os
import sys

from dotenv import load_dotenv

# Load env variables
load_dotenv()

# Add src/ to Python path to import jan_sahayak modules
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))


async def run_diagnostics():
    print("==================================================")
    print("      JAN SAHAYAK INTEGRATION DIAGNOSTICS         ")
    print("==================================================")

    # 1. Check DB Connection
    print("\n[1/4] Checking database connection...")
    try:
        from sqlalchemy import text

        from jan_sahayak.database import async_session, close_db, init_db

        await init_db()
        async with async_session() as db:
            result = await db.execute(text("SELECT 1"))
            val = result.scalar()
            if val == 1:
                print("✅ Database connection successful.")
            else:
                print("❌ Unexpected database response.")
        await close_db()
    except Exception as e:
        print(f"❌ Database error: {e}")

    # 2. Check Sarvam AI API Key & Connection
    print("\n[2/4] Checking Sarvam AI connectivity...")
    sarvam_key = os.getenv("SARVAM_API_KEY")
    if not sarvam_key or sarvam_key == "your_sarvam_api_key_here":
        print("❌ SARVAM_API_KEY is not configured or using default placeholder.")
    else:
        print("💡 Found SARVAM_API_KEY. Running tests...")
        import httpx

        headers = {"api-subscription-key": sarvam_key}

        # 2a. Test Translation
        try:
            print("  -> Testing Translation (mayura:v1)...")
            url = "https://api.sarvam.ai/translate"
            payload = {
                "input": "Hello",
                "source_language_code": "en-IN",
                "target_language_code": "hi-IN",
                "model": "mayura:v1",
                "enable_preprocessing": True,
            }
            async with httpx.AsyncClient() as client:
                res = await client.post(url, json=payload, headers={**headers, "Content-Type": "application/json"}, timeout=8.0)
                if res.status_code == 200:
                    translated = res.json().get("translated_text")
                    print(f"  ✅ Translation OK: 'Hello' -> '{translated}'")
                else:
                    print(f"  ❌ Translation failed (status {res.status_code}): {res.text}")
        except Exception as e:
            print(f"  ❌ Translation exception: {e}")

        # 2b. Test TTS
        try:
            print("  -> Testing TTS (bulbul:v3)...")
            url = "https://api.sarvam.ai/text-to-speech"
            payload = {
                "inputs": ["नमस्ते"],
                "target_language_code": "hi-IN",
                "model": "bulbul:v3",
                "enable_preprocessing": True
            }
            async with httpx.AsyncClient() as client:
                res = await client.post(url, json=payload, headers={**headers, "Content-Type": "application/json"}, timeout=8.0)
                if res.status_code == 200:
                    audio = res.json().get("audios", [None])[0]
                    print(f"  ✅ TTS OK (received audio length: {len(audio) if audio else 0})")
                else:
                    print(f"  ❌ TTS failed (status {res.status_code}): {res.text}")
        except Exception as e:
            print(f"  ❌ TTS exception: {e}")

        # 2c. Test STT
        try:
            print("  -> Testing STT (saaras:v3)...")
            url = "https://api.sarvam.ai/speech-to-text"
            # Create dummy 1-second silent WAV audio bytes
            dummy_wav = b'RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x40\x1f\x00\x00\x40\x1f\x00\x00\x01\x00\x08\x00data\x00\x00\x00\x00'
            files = {"file": ("audio.wav", dummy_wav, "audio/wav")}
            data = {"model": "saaras:v3", "language_code": "hi-IN"}
            async with httpx.AsyncClient() as client:
                res = await client.post(url, files=files, data=data, headers=headers, timeout=8.0)
                if res.status_code == 200:
                    transcript = res.json().get("transcript", "")
                    print(f"  ✅ STT OK (transcript: '{transcript}')")
                else:
                    print(f"  ❌ STT failed (status {res.status_code}): {res.text}")
        except Exception as e:
            print(f"  ❌ STT exception: {e}")

    # 3. Check LiveKit Credentials & Server
    print("\n[3/4] Checking LiveKit credentials...")
    lk_url = os.getenv("LIVEKIT_URL")
    lk_key = os.getenv("LIVEKIT_API_KEY")
    lk_secret = os.getenv("LIVEKIT_API_SECRET")

    if not all([lk_url, lk_key, lk_secret]):
        print("❌ LiveKit variables are incomplete in .env.")
    else:
        print(f"💡 LiveKit URL: {lk_url}")
        print("Attempting to generate a dummy token...")
        try:
            from livekit import api

            token = (
                api.AccessToken(lk_key, lk_secret)
                .with_identity("test-runner")
                .with_name("Test Room")
                .with_grants(api.VideoGrants(room_join=True, room="Test Room"))
            )
            jwt_token = token.to_jwt()
            print(f"✅ Generated token successfully (length: {len(jwt_token)})")
            host = lk_url.replace("wss://", "").replace("ws://", "").split("/")[0]
            print(f"✅ LiveKit Host '{host}' configured.")
        except Exception as e:
            print(f"❌ LiveKit token generation error: {e}")

    # 4. Check LangSmith Traceability
    print("\n[4/4] Checking LangSmith Tracing config...")
    ls_key = os.getenv("LANGSMITH_API_KEY")
    ls_tracing = os.getenv("LANGSMITH_TRACING") or os.getenv("LANGSMITH_TRACING_V2")
    if ls_tracing == "true" and ls_key:
        print(f"✅ LangSmith Tracing active for project: {os.getenv('LANGSMITH_PROJECT', 'jan-sahayak')}")
        print(f"✅ Endpoint: {os.getenv('LANGSMITH_ENDPOINT')}")
    else:
        print("❌ LangSmith tracing is disabled or key is missing.")

    print("\n==================================================")


if __name__ == "__main__":
    asyncio.run(run_diagnostics())
