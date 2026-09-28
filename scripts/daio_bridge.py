"""Universal Chrome CDP Bridge for Dual-Agent Iteration Orchestrator (DAIO).

Supports connecting to any active Chrome tab by URL substring or title,
transmitting prompts, detecting streaming status, and extracting complete responses.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from typing import Any, Dict, List, Optional, Tuple
import urllib.request
try:
    import websockets
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "websockets", "-q"], check=False)
    import websockets

logger = logging.getLogger("DAIO_Bridge")


def discover_tab_by_url(url_pattern: str, cdp_port: int = 9222) -> Tuple[str, str, str]:
    """Find a Chrome tab matching url_pattern via CDP endpoint."""
    try:
        req = urllib.request.urlopen(f"http://localhost:{cdp_port}/json/list", timeout=5)
        tabs = json.loads(req.read().decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"Could not connect to Chrome CDP at port {cdp_port}. Is Chrome running with --remote-debugging-port={cdp_port}? Error: {e}")

    for t in tabs:
        if t.get("type") == "page":
            tab_url = t.get("url", "")
            tab_title = t.get("title", "")
            if url_pattern.lower() in tab_url.lower() or url_pattern.lower() in tab_title.lower():
                return t["webSocketDebuggerUrl"], t["id"], tab_title

    # Fallback to first chatgpt or claude page if pattern generic
    for t in tabs:
        if t.get("type") == "page" and ("chatgpt.com" in t.get("url", "") or "claude.ai" in t.get("url", "")):
            return t["webSocketDebuggerUrl"], t["id"], t.get("title", "")

    available = [f"[{t.get('title')}] -> {t.get('url')}" for t in tabs if t.get("type") == "page"]
    raise RuntimeError(f"No tab matched URL pattern '{url_pattern}'. Available tabs:\n" + "\n".join(available))


class UniversalCDPClient:
    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.msg_id = 0
        self.ws = None

    async def connect(self):
        self.ws = await websockets.connect(self.ws_url, max_size=25 * 1024 * 1024)

    async def close(self):
        if self.ws:
            await self.ws.close()

    async def evaluate(self, expr: str) -> Any:
        self.msg_id += 1
        call = {
            "id": self.msg_id,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expr,
                "returnByValue": True,
                "awaitPromise": True
            }
        }
        await self.ws.send(json.dumps(call))
        while True:
            res = await self.ws.recv()
            data = json.loads(res)
            if data.get("id") == self.msg_id:
                result = data.get("result", {}).get("result", {})
                return result.get("value")

    async def get_status(self) -> Dict[str, Any]:
        check_js = """
        (() => {
            const assistantEls = document.querySelectorAll('[data-message-author-role="assistant"], .agent-turn, .font-claude-message, [data-is-streaming]');
            const markdowns = document.querySelectorAll('.markdown, .prose, article');
            
            let lastText = '';
            if (assistantEls.length > 0) {
                lastText = assistantEls[assistantEls.length - 1].innerText;
            } else if (markdowns.length > 0) {
                lastText = markdowns[markdowns.length - 1].innerText;
            }
            
            // Detection across ChatGPT, Claude, and generic web UIs
            const isStreaming = !!document.querySelector('button[aria-label="Stop streaming"], button[aria-label="停止串流"], button[aria-label="停止產生"], button[aria-label="停止"], button[data-testid="stop-button"], .result-streaming, .streaming');
            const promptEl = document.querySelector('#prompt-textarea, [contenteditable="true"], textarea');
            
            return {
                assistantCount: assistantEls.length > 0 ? assistantEls.length : markdowns.length,
                lastText: lastText,
                isGenerating: isStreaming,
                hasInput: !!promptEl
            };
        })()
        """
        return await self.evaluate(check_js)

    async def send_message(self, message_text: str, timeout_seconds: int = 240) -> Dict[str, Any]:
        # Capture initial state
        initial_status = await self.get_status() or {}
        initial_count = initial_status.get("assistantCount", 0)
        initial_text = (initial_status.get("lastText") or "").strip()

        # Step 0: Idempotency check on current conversation DOM
        norm_text = re.sub(r'\s+', ' ', message_text.strip())
        fingerprint = norm_text[:120] if len(norm_text) >= 120 else norm_text

        idempotency_js = f"""
        (() => {{
            const userArticles = document.querySelectorAll('[data-message-author-role="user"]');
            if (userArticles.length > 0) {{
                const lastUserText = userArticles[userArticles.length - 1].innerText.replace(/\\s+/g, ' ').trim();
                const targetFp = {json.dumps(fingerprint)};
                if (lastUserText.includes(targetFp) || (targetFp.length > 30 && targetFp.includes(lastUserText))) {{
                    return {{ alreadyCommitted: true, userCount: userArticles.length }};
                }}
            }}
            return {{ alreadyCommitted: false, userCount: userArticles.length }};
        }})()
        """
        idem_res = await self.evaluate(idempotency_js) or {}
        if idem_res.get("alreadyCommitted"):
            logger.info(f"🔁 Message fingerprint already committed in DOM ({idem_res.get('userCount')} user messages). Skipping duplicate input/send.")
        else:
            # 1. Fill Text Input
            input_js = f"""
            (() => {{
                const promptEl = document.querySelector('#prompt-textarea') || document.querySelector('[contenteditable="true"]') || document.querySelector('textarea');
                if (!promptEl) return {{ success: false, error: "Prompt input element not found" }};
                
                promptEl.focus();
                const text = {json.dumps(message_text)};
                if (promptEl.tagName === 'TEXTAREA' || promptEl.tagName === 'INPUT') {{
                    promptEl.value = text;
                    promptEl.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    promptEl.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }} else {{
                    document.execCommand('selectAll', false, null);
                    document.execCommand('delete', false, null);
                    try {{
                        const dt = new DataTransfer();
                        dt.setData('text/plain', text);
                        const pasteEvent = new ClipboardEvent('paste', {{
                            clipboardData: dt,
                            bubbles: true,
                            cancelable: true
                        }});
                        promptEl.dispatchEvent(pasteEvent);
                    }} catch (e) {{}}
                    if (!promptEl.innerText || promptEl.innerText.trim().length === 0) {{
                        document.execCommand('insertText', false, text);
                    }}
                    if (!promptEl.innerText || promptEl.innerText.trim().length === 0) {{
                        promptEl.innerHTML = '<p>' + text.replace(/\\n/g, '</p><p>') + '</p>';
                    }}
                    promptEl.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText' }}));
                }}
                return {{ success: true }};
            }})()
            """
            res = await self.evaluate(input_js)
            if not res or not res.get("success"):
                return res

            # 2. Poll for real send button to become enabled (bounded up to 4.0s)
            click_send_js = """
            (() => {
                const sendBtn = document.querySelector('button[data-testid="send-button"]') 
                    || document.querySelector('button[aria-label="Send prompt"]')
                    || document.querySelector('button[aria-label="傳送提示詞"]')
                    || document.querySelector('button[aria-label="傳送"]')
                    || document.querySelector('button[aria-label*="傳送"]')
                    || document.querySelector('button[aria-label="Send message"]')
                    || document.querySelector('button[aria-label="Send Message"]')
                    || document.querySelector('button[data-testid="fruitjuice-send-button"]')
                    || document.querySelector('fieldset button:last-of-type')
                    || document.querySelector('form button:last-of-type');
                if (sendBtn && !sendBtn.disabled) {
                    sendBtn.click();
                    return { clicked: true, method: "button_click" };
                }
                return { clicked: false, sendBtnFound: !!sendBtn, disabled: sendBtn ? sendBtn.disabled : null };
            })()
            """
            button_clicked = False
            send_attempt_start = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - send_attempt_start < 4.0:
                click_res = await self.evaluate(click_send_js) or {}
                if click_res.get("clicked"):
                    button_clicked = True
                    logger.info(f"Send action dispatched via button_click: {click_res}")
                    break
                await asyncio.sleep(0.2)

            if not button_clicked:
                return {
                    "success": False,
                    "status": "SUBMISSION_NOT_COMMITTED",
                    "error": "SUBMISSION_NOT_COMMITTED: Send button was not enabled within 4.0s after input injection."
                }

            # 3. Positive SEND_VERIFIED assertion (poll up to 4.0s)
            verify_send_js = f"""
            (() => {{
                const promptEl = document.querySelector('#prompt-textarea') || document.querySelector('[contenteditable="true"]') || document.querySelector('textarea');
                const promptText = promptEl ? (promptEl.innerText || promptEl.value || '').trim() : '';
                const userArticles = document.querySelectorAll('[data-message-author-role="user"]');
                let userMessageMatched = false;
                if (userArticles.length > 0) {{
                    const lastUserText = userArticles[userArticles.length - 1].innerText.replace(/\\s+/g, ' ').trim();
                    const targetFp = {json.dumps(fingerprint)};
                    if (lastUserText.includes(targetFp) || (targetFp.length > 30 && targetFp.includes(lastUserText))) {{
                        userMessageMatched = true;
                    }}
                }}
                const isCleared = (promptText.length === 0);
                return {{
                    verified: isCleared || userMessageMatched,
                    isCleared: isCleared,
                    userMessageMatched: userMessageMatched,
                    promptLength: promptText.length
                }};
            }})()
            """
            send_verified = False
            verify_start = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - verify_start < 4.0:
                v_res = await self.evaluate(verify_send_js) or {}
                if v_res.get("verified"):
                    send_verified = True
                    logger.info(f"✅ SEND_VERIFIED: Message confirmed committed to conversation DOM: {v_res}")
                    break
                await asyncio.sleep(0.2)

            if not send_verified:
                return {
                    "success": False,
                    "status": "SUBMISSION_NOT_COMMITTED",
                    "error": "SUBMISSION_NOT_COMMITTED: Send action dispatched but neither composer cleared nor matching user message appeared in DOM."
                }

        # 4. Wait for generation to start and finish
        logger.info("Waiting for Web LLM response stream to finish...")
        await asyncio.sleep(2.0)
        
        start_time = asyncio.get_event_loop().time()
        saw_generating = False

        while True:
            status = await self.get_status() or {}
            is_gen = status.get("isGenerating", False)
            curr_count = status.get("assistantCount", 0)
            curr_text = (status.get("lastText") or "").strip()

            if is_gen:
                saw_generating = True

            # If stream finished or new response text appeared
            if not is_gen and (saw_generating or curr_count > initial_count or (len(curr_text) > 0 and curr_text != initial_text)):
                if len(curr_text) > 0:
                    logger.info("Stream generation complete!")
                    return {
                        "success": True,
                        "reply": curr_text,
                        "assistant_count": curr_count,
                    }
            if asyncio.get_event_loop().time() - start_time > timeout_seconds:
                return {"success": False, "error": f"Timeout waiting for response after {timeout_seconds}s"}
            await asyncio.sleep(2.0)

    async def post_message_only(self, message_text: str) -> Dict[str, Any]:
        """Dispatch a one-way message/telemetry with SEND_VERIFIED confirmation without waiting for response."""
        norm_text = re.sub(r'\s+', ' ', message_text.strip())
        fingerprint = norm_text[:120] if len(norm_text) >= 120 else norm_text

        # 1. Fill Text Input
        input_js = f"""
        (() => {{
            const promptEl = document.querySelector('#prompt-textarea') || document.querySelector('[contenteditable="true"]') || document.querySelector('textarea');
            if (!promptEl) return {{ success: false, error: "Prompt input element not found" }};
            
            promptEl.focus();
            const text = {json.dumps(message_text)};
            if (promptEl.tagName === 'TEXTAREA' || promptEl.tagName === 'INPUT') {{
                promptEl.value = text;
                promptEl.dispatchEvent(new Event('input', {{ bubbles: true }}));
                promptEl.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }} else {{
                document.execCommand('selectAll', false, null);
                document.execCommand('delete', false, null);
                try {{
                    const dt = new DataTransfer();
                    dt.setData('text/plain', text);
                    const pasteEvent = new ClipboardEvent('paste', {{
                        clipboardData: dt,
                        bubbles: true,
                        cancelable: true
                    }});
                    promptEl.dispatchEvent(pasteEvent);
                }} catch (e) {{}}
                if (!promptEl.innerText || promptEl.innerText.trim().length === 0) {{
                    document.execCommand('insertText', false, text);
                }}
                if (!promptEl.innerText || promptEl.innerText.trim().length === 0) {{
                    promptEl.innerHTML = '<p>' + text.replace(/\\n/g, '</p><p>') + '</p>';
                }}
                promptEl.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText' }}));
            }}
            return {{ success: true }};
        }})()
        """
        res = await self.evaluate(input_js)
        if not res or not res.get("success"):
            return res or {"success": False, "error": "Input evaluation failed"}

        # 2. Poll for send button
        click_send_js = """
        (() => {
            const sendBtn = document.querySelector('button[data-testid="send-button"]') 
                || document.querySelector('button[aria-label="Send prompt"]')
                || document.querySelector('button[aria-label="傳送提示詞"]')
                || document.querySelector('button[aria-label="傳送"]')
                || document.querySelector('button[aria-label*="傳送"]')
                || document.querySelector('button[aria-label="Send message"]')
                || document.querySelector('button[aria-label="Send Message"]')
                || document.querySelector('fieldset button:last-of-type')
                || document.querySelector('form button:last-of-type');
            if (sendBtn && !sendBtn.disabled) {
                sendBtn.click();
                return { clicked: true, method: "button_click" };
            }
            return { clicked: false, sendBtnFound: !!sendBtn, disabled: sendBtn ? sendBtn.disabled : null };
        })()
        """
        button_clicked = False
        send_attempt_start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - send_attempt_start < 4.0:
            click_res = await self.evaluate(click_send_js) or {}
            if click_res.get("clicked"):
                button_clicked = True
                break
            await asyncio.sleep(0.2)

        if not button_clicked:
            return {"success": False, "status": "SUBMISSION_NOT_COMMITTED", "error": "SUBMISSION_NOT_COMMITTED: Send button was not enabled within timeout."}

        # 3. Verify
        verify_send_js = f"""
        (() => {{
            const promptEl = document.querySelector('#prompt-textarea') || document.querySelector('[contenteditable="true"]') || document.querySelector('textarea');
            const promptText = promptEl ? (promptEl.innerText || promptEl.value || '').trim() : '';
            return {{ verified: (promptText.length === 0), promptLength: promptText.length }};
        }})()
        """
        verify_start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - verify_start < 4.0:
            v_res = await self.evaluate(verify_send_js) or {}
            if v_res.get("verified"):
                logger.info("✅ SEND_VERIFIED: One-way telemetry confirmed committed.")
                return {"success": True, "click_result": click_res}
            await asyncio.sleep(0.2)

        return {"success": False, "status": "SUBMISSION_NOT_COMMITTED", "error": "SUBMISSION_NOT_COMMITTED: Telemetry input was not cleared."}

