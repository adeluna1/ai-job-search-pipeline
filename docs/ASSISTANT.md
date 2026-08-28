# Connection Assistant

## Capabilities

The Connection Assistant is a durable control surface, not a transient chat box. It supports:

- provider and model discovery;
- readiness and credential indicators;
- new conversations and transcript clearing;
- queued messages;
- queued-message editing and cancellation;
- assistant-response retry;
- local image attachments;
- tool request, completion, failure, and handoff events;
- automated queue draining while the page is open.

Conversation state remains in the local control data directory and survives app restarts.

## Message lifecycle

1. The renderer creates or selects a conversation.
2. A message is validated, persisted, and queued.
3. The assistant worker claims one queued message.
4. The provider can answer directly or request a registered tool.
5. Tool calls pass through policy and schema validation.
6. Tool results return to the provider as structured content.
7. The final assistant message and tool events are persisted.

The loop stops after eight tool rounds to prevent runaway conversations.

## Tool access

The assistant sees the same typed tool catalog as Web Workbench. Current registered families include:

- only-cli public reads, navigation, shortcuts, sessions, and cookie import;
- bounded recruiting pipeline runs;
- local application draft preparation.

Arbitrary shell execution is not a chatbot feature. Tools are registered individually with fixed schemas and policies.

## Images

Accepted images are validated by MIME type and size, then written under a content hash. The transcript stores metadata and a local reference, not an embedded unbounded payload.

Images are not sent to a provider unless that message opts in to image upload. When image sharing is off, the provider receives only a notice that local attachments were withheld.

## Provider configuration

OpenAI-compatible providers must use HTTPS unless they are loopback services. URL credentials are rejected. Remote credentials are read from a validated environment-variable name and never returned through the UI API.

The provider transport limits request duration and response size. Provider errors pass through secret redaction before they are stored or displayed.

### Installed FreeChain

The installed FreeChain contract uses `http://127.0.0.1:4853/v1` with bearer authentication. The assistant never displays, logs, or documents a credential value.

On first use, the desktop checks sources in this order: an existing encrypted record, the process `FREECHAIN_ACCESS_KEY`, an explicitly configured environment file, then the allowlisted per-user FreeChain environment file. A valid first source stops the search.

Manual re-import does not use the encrypted record as a replacement candidate. It checks only the process `FREECHAIN_ACCESS_KEY`, the explicitly configured environment file, then the allowlisted per-user FreeChain environment file. A valid first source replaces the saved encrypted record only after a successful protected write. When no valid replacement exists or replacement persistence fails, the prior encrypted credential remains visible and clearable. With no prior credential, status remains unavailable.

Electron `safeStorage` uses the current Windows user protection boundary. Electron user data contains ciphertext only. Plaintext is limited to Electron main-process memory and the environment of the Python control child owned by the application. Job-pipeline subprocesses explicitly remove the control provider environment and credential before launch. Provider response content and tool arguments have the active credential removed before execution or transcript persistence.

Clear removes the encrypted record only when deletion succeeds or the record is already absent. A deletion failure leaves the existing state intact, does not report success, and does not restart a service. The current IPC handler restarts only the application-owned control service after every manual re-import attempt, including when no candidate exists or protected persistence fails. It restarts after clear only when clear succeeds. These operations do not alter unrelated processes.

If another person will use the same Windows account, clear the saved key first.

### Readiness and recovery

The Assistant presents these states without inventing a model:

| State | Meaning and recovery |
| --- | --- |
| Credential missing | Re-import a local key, then refresh readiness. |
| Service unreachable | Start or reconnect the local service, then refresh readiness. |
| Authentication failed | Re-import the local key, then refresh readiness. |
| Invalid model response | Recover the provider, then refresh readiness. |
| Ready | Authentication and a model probe succeeded, and the displayed count is the real model count. |

The earlier chat failure came from targeting port 8000 without the required credential while the installed service uses port 4853 with bearer authentication. The prior interface also masked failed model loading by presenting a fake `auto` state. The current interface keeps model-dependent actions unavailable until readiness and a real model list recover.

When an advertised `auto` completion fails, the provider makes one authenticated model-list request and tries at most four advertised concrete recovery models. Preview and stealth routes are excluded from automatic selection. A working recovery model is cached for the current provider process so later tool rounds do not repeat the failed route.

Committed unit, React, Electron, lint, and build checks cover the documented contracts. Installed acceptance also proves an exact automatic-fallback response and an exact post-restart response while the original credential import file is unavailable. The protected record remains the only credential source during that restart.

## Queue controls

- **Edit** changes only a queued user message.
- **Cancel** prevents a queued message from being claimed.
- **Retry** creates a new queued request linked to the failed or completed assistant turn.
- **Clear transcript** removes messages from the selected conversation after confirmation in the UI.

Tool event history remains content-free and can be used for operational debugging without exposing the transcript.
