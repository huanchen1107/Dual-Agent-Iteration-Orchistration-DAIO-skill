"""Universal Chrome CDP Bridge for Dual-Agent Iteration Orchestrator (DAIO).

Supports connecting to any active Chrome tab by URL substring or title,
transmitting prompts, detecting streaming status, and extracting complete responses.
"""
from __future__ import annotations

import asyncio
import json
import logging
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
            const assistantEls = document.querySelectorAll('[data-message-author-role="assistant"], .font-claude-message, [data-is-streaming]');
            const markdowns = document.querySelectorAll('.markdown, .prose');
            
            let lastText = '';
            if (assistantEls.length > 0) {
                lastText = assistantEls[assistantEls.length - 1].innerText;
            } else if (markdowns.length > 0) {
                lastText = markdowns[markdowns.length - 1].innerText;
            }
            
            // Detection across ChatGPT, Claude, and generic web UIs
            const isStreaming = !!document.querySelector('button[aria-label="Stop streaming"], button[data-testid="stop-button"], .result-streaming, .streaming');
            const promptEl = document.querySelector('#prompt-textarea, [contenteditable="true"], textarea');
            
            return {
                assistantCount: assistantEls.length,
                lastText: lastText,
                isGenerating: isStreaming,
                hasInput: !!promptEl
            };
        })()
        """
        return await self.evaluate(check_js)

    async def send_message(self, message_text: str, timeout_seconds: int = 240) -> Dict[str, Any]:
        # 1. Fill Text Input
        input_js = f"""
        (() => {{
            const promptEl = document.querySelector('#prompt-textarea') || document.querySelector('[contenteditable="true"]') || document.querySelector('textarea');
            if (!promptEl) return {{ success: false, error: "Prompt input element not found" }};
            
            promptEl.focus();
            if (promptEl.tagName === 'TEXTAREA' || promptEl.tagName === 'INPUT') {{
                promptEl.value = {json.dumps(message_text)};
                promptEl.dispatchEvent(new Event('input', {{ bubbles: true }}));
                promptEl.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }} else {{
                promptEl.innerHTML = '<p>' + {json.dumps(message_text)}.replace(/\\n/g, '</p><p>') + '</p>';
                promptEl.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText' }}));
            }}
            return {{ success: true }};
        }})()
        """
        res = await self.evaluate(input_js)
        if not res or not res.get("success"):
            return res

        await asyncio.sleep(0.5)

        # 2. Click Send Button
        click_send_js = """
        (() => {
            const sendBtn = document.querySelector('button[data-testid="send-button"]') 
                || document.querySelector('button[aria-label="Send prompt"]')
                || document.querySelector('button[aria-label="傳送提示詞"]')
                || document.querySelector('button[aria-label="Send message"]')
                || document.querySelector('button[aria-label="Send Message"]')
                || document.querySelector('fieldset button:last-of-type')
                || document.querySelector('form button:last-of-type');
            if (sendBtn && !sendBtn.disabled) {
                sendBtn.click();
                return { clicked: true, method: "button_click" };
            }
            const promptEl = document.querySelector('#prompt-textarea') || document.querySelector('[contenteditable="true"]') || document.querySelector('textarea');
            if (promptEl) {
                promptEl.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
                return { clicked: true, method: "enter_key" };
            }
            return { clicked: false, error: "No send button found" };
        })()
        """
        click_res = await self.evaluate(click_send_js)
        logger.info(f"Send action dispatched: {click_res}")

        # 3. Wait for generation to finish
        logger.info("Waiting for Web LLM response stream to finish...")
        await asyncio.sleep(2.0)
        
        start_time = asyncio.get_event_loop().time()
        while True:
            status = await self.get_status()
            if not status.get("isGenerating"):
                reply = status.get("lastText", "").strip()
                if len(reply) > 0:
                    logger.info("Stream generation complete!")
                    return {
                        "success": True,
                        "reply": reply,
                        "assistant_count": status.get("assistantCount", 0)
                    }
            if asyncio.get_event_loop().time() - start_time > timeout_seconds:
                return {"success": False, "error": f"Timeout waiting for response after {timeout_seconds}s"}
            await asyncio.sleep(2.0)
