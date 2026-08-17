(function () {

const API = "";
    function mountFinlyControls() {

        if (document.getElementById("finly-controls")) {
            return;
        }

        const style = document.createElement("style");

        style.textContent = `
            #finly-controls {
                position: fixed;
                left: 50%;
                bottom: 28px;
                transform: translateX(-50%);
                z-index: 999999;
                width: min(760px, calc(100vw - 32px));
                padding: 14px;
                border-radius: 18px;
                background: rgba(10,10,10,0.84);
                backdrop-filter: blur(18px);
                -webkit-backdrop-filter: blur(18px);
                box-sizing: border-box;
                font-family: Montserrat, Arial, sans-serif;
                box-shadow: 0 10px 40px rgba(0,0,0,0.35);
            }

            #finly-row {
                display: flex;
                gap: 10px;
                align-items: center;
            }

            #finly-question {
                flex: 1;
                min-width: 0;
                height: 52px;
                border: 1px solid rgba(255,255,255,0.20);
                border-radius: 13px;
                background: rgba(255,255,255,0.09);
                color: white;
                padding: 0 16px;
                box-sizing: border-box;
                font-size: 16px;
                outline: none;
            }

            #finly-question::placeholder {
                color: rgba(255,255,255,0.55);
            }

            #finly-mic,
            #finly-ask {
                height: 52px;
                border: 0;
                border-radius: 13px;
                padding: 0 20px;
                font-weight: 700;
                font-size: 15px;
                cursor: pointer;
                white-space: nowrap;
            }

            #finly-mic {
                background: rgba(255,255,255,0.14);
                color: white;
                border: 1px solid rgba(255,255,255,0.18);
            }

            #finly-mic.recording {
                background: white;
                color: black;
            }

            #finly-ask {
                background: white;
                color: black;
            }

            #finly-mic:disabled,
            #finly-ask:disabled {
                opacity: 0.45;
                cursor: default;
            }

            #finly-status {
                margin-top: 8px;
                padding-left: 3px;
                color: rgba(255,255,255,0.68);
                font-size: 12px;
                min-height: 15px;
            }

            @media (max-width: 650px) {
                #finly-controls {
                    bottom: 14px;
                }

                #finly-row {
                    flex-wrap: wrap;
                }

                #finly-question {
                    width: 100%;
                    flex-basis: 100%;
                }

                #finly-mic,
                #finly-ask {
                    flex: 1;
                }
            }
        `;

        document.head.appendChild(style);

        const panel = document.createElement("div");
        panel.id = "finly-controls";

        panel.innerHTML = `
            <div id="finly-row">

                <input
                    id="finly-question"
                    type="text"
                    maxlength="500"
                    autocomplete="off"
                    placeholder="Ask Finly something..."
                >

                <button id="finly-mic">
                    🎤 Speak
                </button>

                <button id="finly-ask">
                    Ask Finly
                </button>

            </div>

            <div id="finly-status">
                Finly is ready.
            </div>
        `;

        document.body.appendChild(panel);

        const input = document.getElementById("finly-question");
        const askButton = document.getElementById("finly-ask");
        const micButton = document.getElementById("finly-mic");
        const status = document.getElementById("finly-status");

        let mediaRecorder = null;
        let mediaStream = null;
        let audioChunks = [];
        let recordingStarted = 0;
        let recordingTimer = null;
let heartbeatTimer = null;

async function sendVisitorHeartbeat() {
    try {
        await fetch(API + "/visitor-heartbeat", {
            method: "POST",
            cache: "no-store"
        });

        console.log("Finly visitor heartbeat OK");
    } catch (error) {
        console.error("Finly heartbeat failed:", error);
    }
}

function startVisitorHeartbeat() {
    sendVisitorHeartbeat();

    if (heartbeatTimer) {
        clearInterval(heartbeatTimer);
    }

    heartbeatTimer = setInterval(sendVisitorHeartbeat, 10000);
}

startVisitorHeartbeat();

window.addEventListener("focus", sendVisitorHeartbeat);

document.addEventListener("visibilitychange", function () {
    if (!document.hidden) {
        sendVisitorHeartbeat();
    }
});

window.addEventListener("beforeunload", function () {
    if (heartbeatTimer) {
        clearInterval(heartbeatTimer);
        heartbeatTimer = null;
    }
});
        [
            "pointerdown",
            "pointerup",
            "mousedown",
            "mouseup",
            "click",
            "touchstart",
            "touchend"
        ].forEach(function (eventName) {

            panel.addEventListener(eventName, function (event) {
                event.stopPropagation();
            });

        });

        input.addEventListener("keydown", function (event) {

            event.stopPropagation();

            if (event.key === "Enter") {
                event.preventDefault();
                sendQuestion();
            }

        });


        async function sendQuestion() {

            const question = input.value.trim();

            if (!question) {
                status.textContent = "Type a question first.";
                return;
            }

            askButton.disabled = true;
            micButton.disabled = true;

            status.textContent = "Sending question to Finly...";

            try {

                const response = await fetch(
                    API + "/visitor-question",
                    {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json"
                        },
                        body: JSON.stringify({
                            question: question
                        })
                    }
                );

                if (!response.ok) {
                    throw new Error(await response.text());
                }

                const result = await response.json();

                input.value = "";

                status.textContent =
                    "Question queued. Queue: " +
                    (result.queue_size ?? "?");

            }
            catch (error) {

                console.error("Finly question error:", error);

                status.textContent =
                    "Could not reach Finly backend.";

            }
            finally {

                askButton.disabled = false;
                micButton.disabled = false;

            }
        }


        async function startRecording() {

            try {

                if (
                    !navigator.mediaDevices ||
                    !navigator.mediaDevices.getUserMedia ||
                    !window.MediaRecorder
                ) {
                    status.textContent =
                        "Microphone recording is not supported.";
                    return;
                }

                mediaStream =
                    await navigator.mediaDevices.getUserMedia({
                        audio: true
                    });

                const types = [
                    "audio/webm;codecs=opus",
                    "audio/webm",
                    "audio/ogg;codecs=opus"
                ];

                const supportedType =
                    types.find(function (type) {
                        return MediaRecorder.isTypeSupported(type);
                    });

                mediaRecorder = supportedType
                    ? new MediaRecorder(
                        mediaStream,
                        { mimeType: supportedType }
                    )
                    : new MediaRecorder(mediaStream);

                audioChunks = [];

                mediaRecorder.ondataavailable = function (event) {

                    if (event.data && event.data.size > 0) {
                        audioChunks.push(event.data);
                    }

                };

                mediaRecorder.onstop = uploadRecording;

                mediaRecorder.start();

                recordingStarted = Date.now();

                micButton.textContent = "■ Stop";
                micButton.classList.add("recording");

                askButton.disabled = true;
                input.disabled = true;

                status.textContent = "Listening... 0s";

                recordingTimer = setInterval(function () {

                    const seconds =
                        Math.floor(
                            (Date.now() - recordingStarted) / 1000
                        );

                    status.textContent =
                        "Listening... " + seconds + "s";

                    if (seconds >= 20) {
                        stopRecording();
                    }

                }, 1000);

            }
            catch (error) {

                console.error("Microphone error:", error);

                status.textContent =
                    "Microphone permission was not granted.";

                cleanupRecording();

            }
        }


        function stopRecording() {

            if (
                mediaRecorder &&
                mediaRecorder.state !== "inactive"
            ) {

                status.textContent =
                    "Processing voice question...";

                mediaRecorder.stop();

            }
        }


        async function uploadRecording() {

            if (recordingTimer) {
                clearInterval(recordingTimer);
                recordingTimer = null;
            }

            try {

                const mimeType =
                    mediaRecorder?.mimeType ||
                    "audio/webm";

                const extension =
                    mimeType.includes("ogg")
                    ? "ogg"
                    : "webm";

                const blob =
                    new Blob(
                        audioChunks,
                        { type: mimeType }
                    );

                if (!blob.size) {
                    throw new Error("Recorded audio is empty.");
                }

                const formData = new FormData();

                formData.append(
                    "audio",
                    blob,
                    "visitor_question." + extension
                );

                status.textContent =
                    "Finly is transcribing your question...";

                const response = await fetch(
                    API + "/visitor-voice",
                    {
                        method: "POST",
                        body: formData
                    }
                );

                if (!response.ok) {
                    throw new Error(await response.text());
                }

                status.textContent =
                    "Voice question sent to Finly.";

            }
            catch (error) {

                console.error(
                    "Voice upload error:",
                    error
                );

                status.textContent =
                    "Voice question failed. Try again.";

            }
            finally {

                cleanupRecording();

            }
        }


        function cleanupRecording() {

            if (recordingTimer) {
                clearInterval(recordingTimer);
                recordingTimer = null;
            }

            if (mediaStream) {

                mediaStream.getTracks().forEach(function (track) {
                    track.stop();
                });

                mediaStream = null;
            }

            mediaRecorder = null;
            audioChunks = [];

            micButton.textContent = "🎤 Speak";
            micButton.classList.remove("recording");

            micButton.disabled = false;
            askButton.disabled = false;
            input.disabled = false;
        }


        micButton.addEventListener(
            "click",
            function () {

                if (
                    mediaRecorder &&
                    mediaRecorder.state === "recording"
                ) {
                    stopRecording();
                }
                else {
                    startRecording();
                }

            }
        );

        askButton.addEventListener(
            "click",
            sendQuestion
        );

        console.log(
            "Finly text + microphone controls loaded."
        );
    }


    window.addEventListener(
        "load",
        function () {
            setTimeout(mountFinlyControls, 500);
        }
    );

})();