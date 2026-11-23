import os
import json
import subprocess
import base64
import asyncio
from io import BytesIO

import numpy as np
import sounddevice as sd
import speech_recognition as sr
import edge_tts
import pygame
import pyperclip
from PIL import ImageGrab
from dotenv import load_dotenv
from groq import Groq

from whatsapp_tool import send_whatsapp_message

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# --- 1. Startup par Mic aur Audio Setup ---
pygame.mixer.init()

def find_working_mic():
    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    for api_pref in ['Windows WASAPI', 'Windows DirectSound', 'MME']:
        for i, d in enumerate(devices):
            if d['max_input_channels'] > 0 and hostapis[d['hostapi']]['name'] == api_pref:
                try:
                    test_fs = int(d['default_samplerate'])
                    test_ch = min(int(d['max_input_channels']), 2)
                    with sd.InputStream(device=i, samplerate=test_fs, channels=test_ch, dtype='float32'):
                        return i, test_fs, test_ch
                except Exception:
                    continue
    return None, 44100, 1

MIC_ID, MIC_FS, MIC_CH = find_working_mic()

# --- 2. Fast Voice Output (Text-to-Speech) ---
async def generate_audio(text, filename="reply.mp3"):
    communicate = edge_tts.Communicate(text, voice="en-IN-NeerjaNeural", rate="+10%")
    await communicate.save(filename)

def speak(text):
    print(f"🤖 Assistant: {text}")
    asyncio.run(generate_audio(text))
    
    pygame.mixer.music.load("reply.mp3")
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(20)
    pygame.mixer.music.unload()
    
    if os.path.exists("reply.mp3"):
        os.remove("reply.mp3")

# --- 3. Smart Fast Voice Input (Speech-to-Text) ---
def listen():
    if MIC_ID is None:
        print("❌ Koi working mic nahi mila!")
        return ""

    print("\n🎙️ Sun raha hoon boss... (Bolo)")
    block_duration = 0.1
    block_size = int(MIC_FS * block_duration)
    
    frames = []
    started_speaking = False
    silent_chunks = 0
    max_silent_chunks = 10
    max_total_chunks = 80
    silence_threshold = 0.015

    with sd.InputStream(device=MIC_ID, samplerate=MIC_FS, channels=MIC_CH, dtype='float32') as stream:
        for _ in range(max_total_chunks):
            data, _ = stream.read(block_size)
            volume = np.abs(data).mean()

            if volume > silence_threshold:
                started_speaking = True
                silent_chunks = 0
                frames.append(data.copy())
            elif started_speaking:
                frames.append(data.copy())
                silent_chunks += 1
                if silent_chunks >= max_silent_chunks:
                    break

    if not frames:
        return ""

    recording = np.concatenate(frames, axis=0)
    if MIC_CH > 1:
        recording = np.mean(recording, axis=1)

    audio_int16 = (recording * 32767).astype(np.int16)
    audio = sr.AudioData(audio_int16.tobytes(), MIC_FS, 2)

    recognizer = sr.Recognizer()
    try:
        command = recognizer.recognize_google(audio, language="en-IN")
        print(f"👤 Tum: {command}")
        return command
    except sr.UnknownValueError:
        return ""
    except sr.RequestError:
        print("❌ Internet connection check karo.")
        return ""

# --- 4. Naye Features: Screen Vision & Clipboard ---
# --- 4. Naye Features: Screen Reader & Clipboard ---
def read_screen_ocr():
    img_path = os.path.abspath("temp_screen.png")
    screenshot = ImageGrab.grab()
    screenshot.save(img_path)

    ps_script = """
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
    Function Await($WinRtTask, $ResultType) {
        $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
        $netTask = $asTask.Invoke($null, @($WinRtTask))
        $netTask.Wait(-1) | Out-Null
        $netTask.Result
    }
    [Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
    [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
    [Windows.Graphics.Imaging.BitmapDecoder,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($env:OCR_IMG_PATH)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    Write-Output $result.Text
    """

    env = os.environ.copy()
    env["OCR_IMG_PATH"] = img_path
    res = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_script],
        capture_output=True, text=True, env=env
    )

    if os.path.exists(img_path):
        os.remove(img_path)

    return res.stdout.strip()

def analyze_screen(question):
    try:
        screen_text = read_screen_ocr()
        if not screen_text:
            return "Screen par koi readable text nahi dikh raha boss."

        ans = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {
                    "role": "system",
                    "content": "Tum ek smart assistant ho. Screen se nikla hua text padh kar user ke sawal ka jawab simple Hinglish mein max 2-3 sentences mein do."
                },
                {
                    "role": "user",
                    "content": f"Screen par yeh text likha hai:\n{screen_text[:4000]}\n\nUser ka sawal: {question}"
                }
            ]
        )
        return ans.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ Screen Read Error: {e}")
        return "ERROR: Screen read nahi ho payi."

def get_clipboard_text():
    text = pyperclip.paste()
    return text.strip() if text and text.strip() else "Clipboard abhi khali hai."

# --- 5. AI Brain (Tools Menu + Smart Thinking) ---
tools = [
    {
        "type": "function",
        "function": {
            "name": "send_whatsapp_message",
            "description": "WhatsApp par kisi contact ko message bhejne ke liye use karo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "contact_name": {
                        "type": "string",
                        "description": "Jis insaan ko message bhejna hai uska naam"
                    },
                    "message": {
                        "type": "string",
                        "description": "Jo message likh kar bhejna hai"
                    }
                },
                "required": ["contact_name", "message"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_screen",
            "description": "User ki laptop screen par kya likha hai, koi error ya code padhne ke liye use karo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "User screen ke baare mein kya jaanna chahta hai"
                    }
                },
                "required": ["question"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_clipboard_text",
            "description": "User ne jo text copy (Ctrl+C) kiya hua hai usko padhne ke liye use karo.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]

def ask_brain(command):
    print("🧠 Soch raha hoon...")
    messages = [
        {
            "role": "system",
            "content": (
                "Tum ek smart personal AI assistant ho jo Hinglish mein baat karta hai. "
                "User ko hamesha 'boss' bulao. "
                "WhatsApp bhejne ke liye send_whatsapp_message, screen padhne ke liye analyze_screen, "
                "aur copied text padhne ke liye get_clipboard_text tool use karo. "
                "Ek hi tool ko baar-baar retry mat karo. Normal baat par max 2 sentences mein reply do."
            )
        },
        {"role": "user", "content": command}
    ]

    for _ in range(3):
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            return msg.content.strip()

        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                } for tc in msg.tool_calls
            ]
        })

        for tool_call in msg.tool_calls:
            fn_name = tool_call.function.name
            args = json.loads(tool_call.function.arguments or "{}")

            if fn_name == "send_whatsapp_message":
                contact = args["contact_name"]
                text = args["message"]
                speak(f"okay boss, {contact} ko WhatsApp message bhej rahi hoon.")
                tool_result = send_whatsapp_message(contact, text)

            elif fn_name == "analyze_screen":
                speak("Screen padh rahi hoon boss...")
                tool_result = analyze_screen(args.get("question", "Screen par kya likha hai?"))
                if tool_result.startswith("ERROR:"):
                    return "Sorry boss, abhi screen padhne mein kuch dikkat aa gayi."

            elif fn_name == "get_clipboard_text":
                tool_result = get_clipboard_text()

            else:
                tool_result = "Unknown tool"

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": str(tool_result)
            })

    return "Sorry boss, yeh kaam abhi complete nahi ho paya."

# --- 6. Main Loop ---
if __name__ == "__main__":
    speak("Hello boss, kaise ho aap? Batao aaj kya karne ka plan hai?")
    
    while True:
        user_command = listen()
        if not user_command:
            continue
        
        if any(word in user_command.lower() for word in ["band ho ja", "exit", "bye", "stop"]):
            speak("okay boss, system sleep mode mein ja raha hai. Milte hain!")
            break
            
        reply = ask_brain(user_command)
        speak(reply)