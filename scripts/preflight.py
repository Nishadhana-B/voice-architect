#!/usr/bin/env python3
"""Check everything the live voice test needs, with plain-language results.   python scripts/preflight.py"""
import os
import sys

os.environ.setdefault("AWS_PROFILE", "voice-chef")
os.environ.setdefault("AWS_REGION", "us-east-1")
OK, BAD = "[ ok ]", "[FAIL]"
failed = 0


def report(ok: bool, text: str) -> None:
    global failed
    failed += 0 if ok else 1
    print(f"{OK if ok else BAD} {text}")


# 1) AWS identity
try:
    import boto3
    s = boto3.Session()
    ident = s.client("sts").get_caller_identity()
    report(True, f"AWS profile '{os.environ['AWS_PROFILE']}' works (account ending {ident['Account'][-4:]}, {ident['Arn'].split('/')[-1]})")
except Exception as e:  # noqa: BLE001
    report(False, f"AWS credentials: {str(e)[:120]}  (run: aws configure --profile {os.environ['AWS_PROFILE']})")
    s = None

# 2) Nova Sonic available
if s:
    try:
        models = s.client("bedrock", region_name=os.environ["AWS_REGION"]).list_foundation_models()["modelSummaries"]
        sonic = [m["modelId"] for m in models if "sonic" in m["modelId"]]
        report("amazon.nova-2-sonic-v1:0" in sonic, f"Nova Sonic models in {os.environ['AWS_REGION']}: {', '.join(sonic) or 'none'}")
    except Exception as e:  # noqa: BLE001
        report(False, f"Bedrock: {str(e)[:120]}")

# 3) audio devices and microphone access
try:
    import pyaudio
    p = pyaudio.PyAudio()
    din, dout = p.get_default_input_device_info(), p.get_default_output_device_info()
    report(True, f"microphone: {din['name']}   |   speaker: {dout['name']}")
    try:
        st = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1024)
        data = st.read(4096, exception_on_overflow=False)
        st.close()
        silent = max(data) == 0 and min(data) == 0
        report(not silent, "microphone opened and returned audio" if not silent else
               "microphone opened but only silence: allow microphone access for your Terminal app in "
               "System Settings > Privacy & Security > Microphone")
    except Exception as e:  # noqa: BLE001
        report(False, f"cannot open the microphone: {str(e)[:100]}")
    p.terminate()
except Exception as e:  # noqa: BLE001
    report(False, f"pyaudio: {str(e)[:100]}  (run: brew install portaudio, then reinstall pyaudio)")

print("\nAll good. Start with ./run.sh" if not failed else f"\n{failed} problem(s) above. Fix them, then run this again.")
sys.exit(1 if failed else 0)
