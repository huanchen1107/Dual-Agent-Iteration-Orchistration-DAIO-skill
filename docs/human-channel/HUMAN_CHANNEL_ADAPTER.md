# DAIO Human Channel Adapter & Registry Architecture (Phase B6)

**Contract Standard**: `daio-agent/v1`  
**Milestone**: `PORTABILITY-PHASE-B6`  

---

## 1. Abstract HumanChannelAdapter Contract

```python
class HumanChannelAdapter(ABC):
    @abstractmethod
    def get_channel_type(self) -> HumanChannelType: ...

    @abstractmethod
    def get_descriptor(self) -> HumanChannelDescriptor: ...

    @abstractmethod
    async def send_interaction(self, request: HumanInteractionRequest) -> DeliveryStatus: ...

    @abstractmethod
    async def receive_response(self, response: HumanInteractionResponse) -> Tuple[bool, Optional[str]]: ...

    @abstractmethod
    async def send_command_acknowledgement(self, command_id: str, status: str, message: str) -> bool: ...
```

---

## 2. Concrete Adapters

### 2.1 CockpitChannelAdapter
- First concrete adapter.
- Wraps the existing, proven iPhone Cockpit WebAuthn / Passkey / Face ID path.
- Generates secure deep links containing Action Ticket references.
- Issues `STRONG_AUTHENTICATED` responses.

### 2.2 Mock Channel Adapters (Foundation Only)
- `MockChatGPTChannelAdapter`: Simulates ChatGPT command ingestion & review interaction.
- `MockTelegramChannelAdapter`: Simulates Telegram Bot notification & inline buttons.
- `MockLineChannelAdapter`: Simulates LINE Messaging API notification.
- `MockMessengerChannelAdapter`: Simulates Meta Messenger webhook interaction.

*Note: Phase B6 implements contracts and mocks only. Zero external bot tokens, webhooks, or third-party credentials are used or stored.*

---

## 3. Human Channel Registry & State Taxonomy

```text
NOT_CONFIGURED   -> Discovered in codebase but no credentials or active webhook configured.
DISCOVERED       -> Channel module present, awaiting verification.
AUTH_REQUIRED    -> Channel detected but requires account binding.
AVAILABLE        -> Operational and accepting commands / notifications.
DEGRADED         -> Operational with rate limit or transient network latency.
UNAVAILABLE      -> Channel webhook down or unreachable.
```
