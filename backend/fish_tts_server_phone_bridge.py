import json
import os
import time
from collections import deque
from pathlib import Path
from threading import Lock
from uuid import uuid4

import torch
import torchaudio as ta
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from groq import Groq
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from chatterbox.tts_turbo import ChatterboxTurboTTS
from fastapi.middleware.cors import CORSMiddleware


BASE_DIR = Path(__file__).resolve().parent
REFERENCE_FILE = BASE_DIR / "fish_voice_reference.wav"
OUTPUT_DIR = BASE_DIR / "generated_audio"
LATEST_AUDIO_FILE = OUTPUT_DIR / "latest_fish_response.wav"

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
load_dotenv(BASE_DIR / ".env")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = "llama-3.3-70b-versatile"

if not GROQ_API_KEY:
    raise RuntimeError(
    "GROQ_API_KEY was not found. Add it to the .env file."
)

GROQ_CLIENT = Groq(api_key=GROQ_API_KEY)

MAX_HISTORY_MESSAGES = 6
conversation_history: list[dict[str, str]] = []
conversation_lock = Lock()

# Visitor-phone -> Unreal bridge.
# The phone queues questions here. Unreal polls /next-question and then sends
# that text through the existing /ask-file flow.
visitor_question_queue: deque[str] = deque()
visitor_question_lock = Lock()
NO_QUESTION = "__NO_QUESTION__"
FISH_SYSTEM_PROMPT = """
Your name is Finly.

You are Finly, an intelligent, friendly fish guide living inside an interactive museum exhibit.

Always stay in character as Finly.
If anyone asks your name, who you are, or what you are called, clearly say that your name is Finly.
Never invent, change, or use another name for yourself.
Do not say that you are an AI, language model, chatbot, or software unless the museum specifically requires that disclosure.

Answer naturally as Finly.
Keep every spoken answer concise, usually one to three short sentences.
Use clear, friendly language that sounds natural when spoken aloud.

Do not invent facts about a museum, artwork, artist, location, or collection.
If verified information about a specific artwork has not been supplied,
say that you do not have verified details yet and ask for the artwork ID
or more information.
""".strip()
app = FastAPI(
    title="AI Fish Chatterbox Backend",
    version="1.1",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[        "http://127.0.0.1",
        "http://localhost",
        "http://127.0.0.1:80",
        "http://localhost:80",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

model_lock = Lock()

print(f"Using device: {DEVICE}")

if DEVICE == "cuda":
    print(f"GPU: {torch.cuda.get_device_name(0)}")

if not REFERENCE_FILE.exists():
    raise FileNotFoundError(
        f"Reference voice was not found: {REFERENCE_FILE}"
    )

OUTPUT_DIR.mkdir(exist_ok=True)

print("Loading Chatterbox model...")
MODEL = ChatterboxTurboTTS.from_pretrained(device=DEVICE)
print("Preparing Finly voice...")
MODEL.prepare_conditionals(str(REFERENCE_FILE))
print("Finly voice ready.")
print("Chatterbox model loaded successfully.")


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class VisitorQuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


VISITOR_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <title>AI Fish Exhibit</title>
    <style>
        :root { color-scheme: dark; }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            min-height: 100vh;
            background: #050708;
            color: #fff;
            font-family: Arial, Helvetica, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 24px;
        }
        .panel {
            width: min(720px, 100%);
            border: 1px solid rgba(255,255,255,.16);
            border-radius: 24px;
            padding: 24px;
            background: rgba(255,255,255,.05);
        }
        h1 { margin: 0 0 8px; font-size: 32px; }
        .sub { margin: 0 0 24px; color: rgba(255,255,255,.7); line-height: 1.4; }
        .live-view {
    width: 100%;
    aspect-ratio: 16 / 9;
    border-radius: 18px;
    overflow: hidden;
    background: #000;
    border: 1px solid rgba(255,255,255,.12);
    margin-bottom: 18px;
}

.live-view iframe {
    width: 100%;
    height: 100%;
    border: 0;
    display: block;
    background: #000;
}
        textarea {
            width: 100%;
            min-height: 110px;
            resize: vertical;
            border: 1px solid rgba(255,255,255,.18);
            border-radius: 16px;
            background: rgba(0,0,0,.45);
            color: #fff;
            padding: 16px;
            font-size: 18px;
            outline: none;
        }
        textarea:focus { border-color: rgba(255,255,255,.55); }
        .buttons {
            display: grid;
            grid-template-columns: 1fr 2fr;
            gap: 12px;
            margin-top: 12px;
        }
        button {
            border: 0;
            border-radius: 14px;
            min-height: 54px;
            font-size: 17px;
            font-weight: 700;
            cursor: pointer;
        }
        #mic { background: #272b30; color: #fff; }
        #send { background: #fff; color: #000; }
        #status {
            min-height: 24px;
            margin-top: 14px;
            color: rgba(255,255,255,.72);
        }
    </style>
</head>
<body>
    <main class="panel">
        <h1>Finly</h1>
        <p class="sub">Ask Finly a question by typing or speaking.</p>

        <div class="live-view">
    <iframe
        id="finlyStream"
        title="Live Finly"
        allow="autoplay; fullscreen"
        allowfullscreen>
    </iframe>
</div>

        <textarea id="question" maxlength="500" placeholder="Ask Finly something..."></textarea>

        <div class="buttons">
            <button id="mic" type="button">Ã°Å¸Å½Â¤ Speak</button>
            <button id="send" type="button">Ask Finly</button>
        </div>

        <div id="status"></div>
    </main>

    <script>
        const question = document.getElementById("question");
        const send = document.getElementById("send");
        const mic = document.getElementById("mic");
        const status = document.getElementById("status");
const finlyStream = document.getElementById("finlyStream");

finlyStream.src =
    window.location.protocol +
    "//" +
    window.location.hostname +
    "/";
        async function sendQuestion(textOverride = null) {
            const text = (textOverride ?? question.value).trim();
            if (!text) return;

            send.disabled = true;
            status.textContent = "Sending question to Finly...";

            try {
                const response = await fetch("/visitor-question", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ question: text })
                });

                if (!response.ok) {
                    throw new Error(await response.text());
                }

                question.value = "";
                status.textContent = "Question sent. Watch Finly on the museum screen.";
            } catch (error) {
                console.error(error);
                status.textContent = "Could not send the question. Please try again.";
            } finally {
                send.disabled = false;
            }
        }

        send.addEventListener("click", () => sendQuestion());

        question.addEventListener("keydown", (event) => {
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                sendQuestion();
            }
        });

       let mediaRecorder = null;
let mediaStream = null;
let audioChunks = [];
let isRecording = false;
let recordingTimer = null;

async function startRecording() {
    try {
        if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
            status.textContent =
                "Microphone recording is not supported in this browser.";
            return;
        }

        mediaStream = await navigator.mediaDevices.getUserMedia({
            audio: true
        });

        const supportedTypes = [
            "audio/webm;codecs=opus",
            "audio/webm",
            "audio/ogg;codecs=opus"
        ];

        const mimeType =
            supportedTypes.find(type =>
                MediaRecorder.isTypeSupported(type)
            ) || "";

        mediaRecorder = mimeType
            ? new MediaRecorder(mediaStream, { mimeType })
            : new MediaRecorder(mediaStream);

        audioChunks = [];

        mediaRecorder.addEventListener("dataavailable", event => {
            if (event.data && event.data.size > 0) {
                audioChunks.push(event.data);
            }
        });

        mediaRecorder.addEventListener(
            "stop",
            uploadRecording,
            { once: true }
        );

        mediaRecorder.start();

        isRecording = true;

        mic.textContent = "Ã¢ÂÂ¹ Stop";
        status.textContent =
            "Ã°Å¸Å½â„¢Ã¯Â¸Â Recording... Ask Finly your question, then press Stop.";

        recordingTimer = setTimeout(() => {
            if (isRecording) {
                stopRecording();
            }
        }, 15000);

    } catch (error) {
        console.error(error);

        status.textContent =
            "Microphone permission was denied or the microphone is unavailable.";

        mic.textContent = "Ã°Å¸Å½Â¤ Speak";
        isRecording = false;
    }
}

function stopRecording() {
    if (
        mediaRecorder &&
        mediaRecorder.state === "recording"
    ) {
        mediaRecorder.stop();
    }

    isRecording = false;

    if (recordingTimer) {
        clearTimeout(recordingTimer);
        recordingTimer = null;
    }

    mic.textContent = "Ã¢ÂÂ³ Processing...";
    mic.disabled = true;

    status.textContent =
        "Finly is listening to your recording...";
}

async function uploadRecording() {
    try {
        const mimeType =
            mediaRecorder?.mimeType || "audio/webm";

        const audioBlob = new Blob(
            audioChunks,
            { type: mimeType }
        );

        if (audioBlob.size === 0) {
            throw new Error("Recorded audio was empty.");
        }

        const extension =
            mimeType.includes("ogg") ? "ogg" : "webm";

        const formData = new FormData();

        formData.append(
            "audio",
            audioBlob,
            `visitor_question.${extension}`
        );

        status.textContent =
            "Transcribing your question...";

        const response = await fetch(
            "/visitor-voice",
            {
                method: "POST",
                body: formData
            }
        );

        if (!response.ok) {
            throw new Error(
                await response.text()
            );
        }

        const result = await response.json();

        status.textContent =
            `Heard: "${result.transcript}" Ã¢â‚¬â€ Question sent to Finly.`;

        question.value = "";

    } catch (error) {
        console.error(error);

        status.textContent =
            "Could not understand the recording. Please try again.";

    } finally {
        if (mediaStream) {
            mediaStream
                .getTracks()
                .forEach(track => track.stop());
        }

        mediaStream = null;
        mediaRecorder = null;
        audioChunks = [];
        isRecording = false;

        mic.disabled = false;
        mic.textContent = "Ã°Å¸Å½Â¤ Speak";
    }
}

mic.addEventListener("click", async () => {
    if (isRecording) {
        stopRecording();
    } else {
        await startRecording();
    }
});
        }
async function sendVisitorHeartbeat() {
    try {
        await fetch('/visitor-heartbeat', {
            method: 'POST',
            cache: 'no-store'
        });
    } catch (error) {
        console.log('Heartbeat failed:', error);
    }
}

sendVisitorHeartbeat();

setInterval(sendVisitorHeartbeat, 10000);

window.addEventListener('focus', sendVisitorHeartbeat);

document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
        sendVisitorHeartbeat();
    }
});
    </script>
</body>
</html>
"""

import time

def generate_audio(text: str, output_file: Path) -> None:
    print(f"Generating speech: {text}")

    start = time.perf_counter()

    with model_lock:
        t0 = time.perf_counter()

        wav = MODEL.generate(text)

        t1 = time.perf_counter()

        ta.save(
            str(output_file),
            wav.detach().cpu(),
            MODEL.sr,
        )

        t2 = time.perf_counter()

    print(f"TTS generation: {t1 - t0:.2f}s")
    print(f"WAV save:       {t2 - t1:.2f}s")
    print(f"TOTAL:          {t2 - start:.2f}s")
    print(f"Generated: {output_file}")

def delete_file(file_path: Path) -> None:
    try:
        file_path.unlink(missing_ok=True)
    except Exception as error:
        print(f"Could not delete temporary file: {error}")


def clean_request_text(raw_text: str) -> str:
    text = raw_text.strip()

    # Handles a string that may arrive surrounded by JSON quotes.
    if text.startswith('"') and text.endswith('"'):
        try:
            decoded = json.loads(text)

            if isinstance(decoded, str):
                text = decoded.strip()
        except json.JSONDecodeError:
            text = text.strip('"').strip()

    return text

def generate_ai_answer(question: str) -> str:
    clean_question = question.strip()

    if not clean_question:
        raise ValueError("Question cannot be empty.")

    print(f"Sending question to Groq: {clean_question}")

    with conversation_lock:
        messages = [
            {
                "role": "system",
                "content": FISH_SYSTEM_PROMPT,
            },
            *conversation_history,
            {
                "role": "user",
                "content": clean_question,
            },
        ]

        completion = GROQ_CLIENT.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=0.6,
            max_completion_tokens=160,
        )

        answer = (
            completion.choices[0].message.content or ""
        ).strip()

        if not answer:
            raise RuntimeError("Groq returned an empty answer.")

        conversation_history.extend(
            [
                {
                    "role": "user",
                    "content": clean_question,
                },
                {
                    "role": "assistant",
                    "content": answer,
                },
            ]
        )

        if len(conversation_history) > MAX_HISTORY_MESSAGES:
            del conversation_history[:-MAX_HISTORY_MESSAGES]

    print(f"Groq answer: {answer}")

    return answer

VISITOR_SESSION_TIMEOUT = 30.0
VISITOR_CONNECTION_TIMEOUT = 25.0

last_visitor_heartbeat = 0.0
last_visitor_activity = 0.0


def mark_visitor_heartbeat():
    global last_visitor_heartbeat
    last_visitor_heartbeat = time.time()


def mark_visitor_active():
    global last_visitor_heartbeat, last_visitor_activity

    now = time.time()
    last_visitor_heartbeat = now
    last_visitor_activity = now


def visitor_is_active():
    now = time.time()

    phone_connected = (
        now - last_visitor_heartbeat
    ) < VISITOR_CONNECTION_TIMEOUT

    recently_active = (
        now - last_visitor_activity
    ) < VISITOR_SESSION_TIMEOUT

    return phone_connected and recently_active


@app.post("/visitor-heartbeat")
async def visitor_heartbeat():
    mark_visitor_active()
    return PlainTextResponse("OK")


@app.get("/visitor-session")
async def visitor_session():
    if visitor_is_active():
        return PlainTextResponse("ACTIVE")

    return PlainTextResponse("INACTIVE")


@app.get("/health")
def health():
    return {
        "status": "online",
        "device": DEVICE,
        "gpu": (
            torch.cuda.get_device_name(0)
            if torch.cuda.is_available()
            else None
        ),
    }



@app.get("/", response_class=HTMLResponse)
def visitor_page():
    mark_visitor_active()
    return HTMLResponse(VISITOR_HTML)


@app.post("/visitor-question")
def visitor_question(payload: VisitorQuestionRequest):
    mark_visitor_active()
    clean_question = payload.question.strip()

    if not clean_question:
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty.",
        )

    with visitor_question_lock:
        visitor_question_queue.append(clean_question)
        queue_size = len(visitor_question_queue)

    print(f"Visitor question queued: {clean_question}")

    return {
        "status": "queued",
        "queue_size": queue_size,
    }
@app.post("/visitor-voice")
async def visitor_voice(audio: UploadFile = File(...)):
    mark_visitor_active()

    audio_bytes = await audio.read()

    if not audio_bytes:
        raise HTTPException(
            status_code=400,
            detail="Recorded audio is empty.",
        )

    filename = audio.filename or "visitor_question.webm"

    try:
        transcription = await run_in_threadpool(
            lambda: GROQ_CLIENT.audio.transcriptions.create(
                file=(filename, audio_bytes),
                model="whisper-large-v3-turbo",
                response_format="json",
                temperature=0.0,
            )
        )

        transcript = (transcription.text or "").strip()

    except Exception as error:
        error_message = f"{type(error).__name__}: {error}"

        print("VISITOR VOICE TRANSCRIPTION FAILED")
        print(error_message)

        raise HTTPException(
            status_code=500,
            detail=error_message,
        ) from error

    if not transcript:
        raise HTTPException(
            status_code=400,
            detail="No speech was detected.",
        )

    with visitor_question_lock:
        visitor_question_queue.append(transcript)
        queue_size = len(visitor_question_queue)

    print(f"Visitor voice transcript queued: {transcript}")

    return {
        "status": "queued",
        "transcript": transcript,
        "queue_size": queue_size,
    }

@app.get(
    "/next-question",
    response_class=PlainTextResponse,
)
def next_question():
    with visitor_question_lock:
        if not visitor_question_queue:
            return NO_QUESTION

        question = visitor_question_queue.popleft()

    print(f"Unreal received visitor question: {question}")
    return question


@app.post(
    "/speak-file",
    response_class=PlainTextResponse,
)
async def speak_file(request: Request):
    raw_body = await request.body()

    try:
        raw_text = raw_body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HTTPException(
            status_code=400,
            detail="The request body must contain UTF-8 text.",
        ) from error

    clean_text = clean_request_text(raw_text)

    if not clean_text:
        raise HTTPException(
            status_code=400,
            detail="Text cannot be empty.",
        )

    if len(clean_text) > 500:
        raise HTTPException(
            status_code=400,
            detail="Text cannot exceed 500 characters.",
        )

    try:
        await run_in_threadpool(generate_audio, clean_text, LATEST_AUDIO_FILE)
        return str(LATEST_AUDIO_FILE.resolve())

    except Exception as error:
        print(f"Generation error: {error}")

        raise HTTPException(
            status_code=500,
            detail=str(error),
        ) from error

@app.post(
    "/ask-file",
    response_class=PlainTextResponse,
)
async def ask_file(request: Request):
    raw_body = await request.body()

    try:
        raw_question = raw_body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HTTPException(
            status_code=400,
            detail="The request body must contain UTF-8 text.",
        ) from error

    clean_question = clean_request_text(raw_question)

    if not clean_question:
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty.",
        )

    if len(clean_question) > 500:
        raise HTTPException(
            status_code=400,
            detail="Question cannot exceed 500 characters.",
        )

    output_file = OUTPUT_DIR / f"fish_response_{uuid4().hex}.wav"

    try:
        answer = await run_in_threadpool(generate_ai_answer, clean_question)

        await run_in_threadpool(
            generate_audio,
            answer,
            output_file,
        )

        return str(output_file.resolve())

    except Exception as error:
        delete_file(output_file)

        error_message = f"{type(error).__name__}: {error}"

        print("ASK FILE FAILED")
        print(error_message)

        raise HTTPException(
            status_code=500,
            detail=error_message,
        ) from error
@app.get(
    "/speak-test",
    response_class=PlainTextResponse,
)
def speak_test():
    test_text = (
        "Hello. I am your underwater guide. "
        "What would you like to discover today?"
    )

    try:
        generate_audio(test_text, LATEST_AUDIO_FILE)
        return str(LATEST_AUDIO_FILE.resolve())

    except Exception as error:
        error_message = f"{type(error).__name__}: {error}"

        print("SPEAK TEST FAILED")
        print(error_message)

        raise HTTPException(
            status_code=500,
            detail=error_message,
        ) from error
if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        workers=1,
    )

