---
title: AskMyHuman Voice Telephony Options Decision Research
description: Decision research comparing three Azure voice telephony architectures for the AskMyHuman MVP
ms.date: 2026-09-15
ms.topic: research
---

## Research Scope

Evaluate the unresolved voice telephony options for AskMyHuman:

* Option A: Azure Communication Services Call Automation Play and Recognize with Azure Speech
* Option B: Azure Communication Services bidirectional media streaming bridged to Microsoft Foundry Voice Live
* Option C: Any documented native Microsoft Foundry Voice Live telephony integration

For each option, verify conversational approval and free-form input fit,
implementation complexity, audio format and protocol requirements, service status,
and regional or phone-number prerequisites. Select the fastest viable MVP approach.

## Evidence Standard

* Prefer current Microsoft Learn pages and Microsoft-owned GitHub samples.
* Record source titles, URLs, relevant sample paths, and stable GitHub links.
* Label documented facts separately from architectural inference.
* Treat missing first-party documentation as absence of a documented capability,
  not proof that an undocumented capability cannot exist.

## Decision

Select **Option A, ACS Call Automation Play and Recognize with Azure Speech**, for
the fastest AskMyHuman MVP.

Option A directly covers the two required response modes:

* Approval requests use `RecognizeInputType.CHOICES` with labels such as
    `Approve` and `Reject`. A DTMF tone can be attached to each choice as a fallback.
* Input requests use `RecognizeInputType.SPEECH`. The `RecognizeCompleted`
    webhook returns the free-form transcript in `speechResult.speech`.

The application creates the outbound PSTN call, waits for `CallConnected`, runs
one Play-and-Recognize action, persists the result, plays an acknowledgement, and
ends the call. Azure Communication Services (ACS) and Azure Speech manage the
call audio. The application does not need a media WebSocket, audio framing,
resampling, buffering, Voice Live session state, or barge-in synchronization.

This recommendation deliberately narrows the first release to a bounded
prompt-response interaction. It does not satisfy a stronger requirement for an
LLM-led, natural, multi-turn conversation that can clarify an ambiguous answer.
If that stronger requirement is mandatory for the first release, select Option B.

### Decision Rationale

Documented facts:

* Call Automation supports outbound calls, text-to-speech Play, voice input,
    choices, speech, and speech-or-DTMF recognition.
* The official Python outbound sample already implements a proactive phone call
    with Confirm/Cancel speech choices, callbacks, retry handling, and hang-up.
* Open-ended speech mode is separately documented and returns recognized text.
* The ACS and Foundry Tools connection explicitly avoids customer-managed media
    streams for Play and Recognize.

Decision inference:

* Reusing the official outbound sample and replacing its domain text and result
    persistence is the smallest implementation path. Option B introduces at least
    two persistent WebSocket protocols and an additional failure domain without
    being necessary for one-turn approval or answer capture.

## Comparison

### Option A Summary

* Feature fit: Complete for bounded Approve/Reject and one free-form spoken answer
* Conversation quality: Prompt-response, not LLM-led multi-turn dialogue
* Application media handling: None
* Complexity: Low
* Status: Treat the core Call Automation, Play, choices, and speech recognition
    surfaces as generally available. Current pages do not mark these core features
    as preview; optional language identification and sentiment additions are marked
    Preview.
* Primary risk: Recognition can yield no-match, timeout, or an imperfect
    transcript, so retry and confirmation policy must be explicit.

### Option B Summary

* Feature fit: Complete, including natural multi-turn conversation, semantic turn
    detection, interruption, transcripts, and function calling
* Conversation quality: Highest of the viable options
* Application media handling: Required in both directions
* Complexity: High
* Status: ACS bidirectional streaming is explicitly generally available. Current
    Voice Live overview, how-to, and quickstart pages do not display a service-wide
    preview warning, and the official accelerator uses the non-preview
    `azure-ai-voicelive>=1.1.0` package. Those facts support treating the core
    WebSocket API as a current production surface, but the reviewed Learn pages do
    not contain an explicit sentence declaring the whole Voice Live service GA.
    Individual models and features can still be Preview.
* Primary risk: Relay lifecycle, latency, buffering, barge-in, and partial service
    failures become application responsibilities.

### Option C Summary

* Feature fit: Not available as a documented native integration
* Conversation quality: Not applicable
* Application media handling: No native path was found to evaluate
* Complexity: Not implementable from current first-party documentation
* Status: No documented Microsoft native Voice Live PSTN, phone-number, SIP, or
    ACS service-to-service attachment has a Preview or GA status.
* Primary risk: Treating the telephony solution template as a native connector
    would omit the application relay that the sample actually implements.

## Option A: Call Automation Play and Recognize

### Feature Fit

Documented facts:

* [Gathering user input](https://learn.microsoft.com/azure/communication-services/concepts/call-automation/recognize-action)
    lists DTMF, speech, and combined DTMF and speech as recognized input modes. It
    states that voice recognition transcribes caller audio to text for application
    business logic.
* [Gather user input with Recognize action](https://learn.microsoft.com/azure/communication-services/how-tos/call-automation/recognize-action)
    documents `dtmf`, `choices`, `speech`, and `speechordtmf`. Its open-question
    example uses `RecognizeInputType.SPEECH`, and its event example reads
    `event.data["speechResult"]["speech"]`.
* The same guide provides a Confirm/Cancel `RecognitionChoice` example and allows
    each choice to include both phrases and a DTMF tone.
* [Call Automation Overview](https://learn.microsoft.com/azure/communication-services/concepts/call-automation/call-automation)
    lists outbound call creation, text-to-speech Play, and voice recognition across
    the .NET, Java, JavaScript, and Python SDKs.

Inference for AskMyHuman:

* Approval should use choices, not raw transcript classification, because labels
    produce a constrained business result while still accepting spoken synonyms.
* Free-form input should use speech mode and return the transcript directly to the
    requesting agent. An optional confirmation prompt can reduce transcription risk.
* A sequence of separate Recognize actions can implement retries, but it is not a
    continuously listening conversational agent.

### Implementation Complexity

The minimum application path is one outbound call-control workflow:

1. Call `create_call` with the owner's E.164 phone number, an ACS calling-enabled
     source number, a public HTTPS callback URL, and the connected Azure AI endpoint.
2. On `CallConnected`, start recognition with a `TextSource` prompt.
3. On `RecognizeCompleted`, map the choice label or read `speechResult.speech`.
4. Persist Responded status and the value, play an acknowledgement, and hang up.
5. On `RecognizeFailed`, apply a bounded retry or persist Expired.

This requires normal HTTP callbacks but no real-time media server. The official
integration guide states that applications do not need to manage media streams or
send media back to Azure for these AI functions.

### Audio and Protocol Requirements

Documented facts:

* The application exchanges Call Automation SDK requests and receives CloudEvent
    callbacks over HTTPS.
* The application supplies text or SSML for speech output and receives structured
    recognition results. ACS and Azure Speech own the telephony audio conversion.
* Text-to-speech text prompts have a 4,000-character limit. The speech-mode initial
    silence timeout has a documented maximum of 20 seconds.

Inference for AskMyHuman:

* There is no application-level PCM, codec, packet size, or WebSocket requirement.
    This removes the most time-sensitive work in Options B and C.

### Status and Prerequisites

Documented facts:

* Core Play and Recognize pages carry no Preview warning. The current Recognize
    guide separately labels real-time language identification and sentiment analysis
    as Preview, which are not needed for the MVP.
* [Connect Azure Communication Services with Foundry Tools](https://learn.microsoft.com/azure/communication-services/concepts/call-automation/azure-communication-services-azure-cognitive-services-integration)
    requires an ACS resource, a multi-service Azure AI resource, managed identity,
    and the `Cognitive Services User` role. The integration follows Azure Speech
    regional availability.
* [Quickstart: Make an outbound call using Call Automation](https://learn.microsoft.com/azure/communication-services/quickstarts/call-automation/quickstart-make-an-outbound-call)
    requires an ACS phone number that can make outbound calls and a public callback.
* [Phone number types](https://learn.microsoft.com/azure/communication-services/concepts/numbers/number-types)
    says local and toll-free ACS numbers can make and receive calls.
* [Country/region availability of telephone numbers and subscription eligibility](https://learn.microsoft.com/azure/communication-services/concepts/numbers/sub-eligibility-number-capability)
    says number availability depends on operating country or region, use case,
    number type, regulatory rules, Azure subscription eligibility, and billing
    address. Trial numbers require a United States billing address.
* [Telephony concepts](https://learn.microsoft.com/azure/communication-services/concepts/telephony/telephony-concept)
    documents ACS-purchased PSTN numbers as the simplest path. Direct routing is the
    alternative when ACS PSTN is unavailable or an existing carrier must be retained,
    but it adds a supported session border controller and carrier contract.

Inference for AskMyHuman:

* Use an ACS-purchased, outbound-enabled local or toll-free number for the MVP when
    the subscription and country permit it. Direct routing is not the fastest MVP.

### Official Samples

The official Python outbound sample is unusually close to AskMyHuman. It creates
an outbound call, prompts for Confirm/Cancel, processes `RecognizeCompleted`,
retries recognition failures, and hangs up:

* `callautomation-outboundcalling/main.py` at
    [Azure-Samples/communication-services-python-quickstarts](https://github.com/Azure-Samples/communication-services-python-quickstarts/blob/052a2dca2f369631ed353a7d0cff9e4aec339280/callautomation-outboundcalling/main.py)
* `callautomation-outboundcalling/readme.md` at
    [Azure-Samples/communication-services-python-quickstarts](https://github.com/Azure-Samples/communication-services-python-quickstarts/blob/052a2dca2f369631ed353a7d0cff9e4aec339280/callautomation-outboundcalling/readme.md)

The free-form speech example is in the official documentation source at
`articles/communication-services/how-tos/call-automation/includes/recognize-how-to-python.md`:

* [MicrosoftDocs/azure-docs at the reviewed commit](https://github.com/MicrosoftDocs/azure-docs/blob/84f2b5f6f45dcac5533dec66cc35e46d44824597/articles/communication-services/how-tos/call-automation/includes/recognize-how-to-python.md)

## Option B: Media Streaming Bridge to Voice Live

### Feature Fit

Documented facts:

* [Voice Live API Overview](https://learn.microsoft.com/azure/ai-services/speech-service/voice-live)
    describes a managed speech-to-speech service combining speech recognition,
    generative AI, and text-to-speech. It includes advanced turn detection,
    interruption detection, transcripts, and function calling.
* [How to use the Voice Live API](https://learn.microsoft.com/azure/ai-services/speech-service/voice-live-how-to)
    documents server VAD and semantic VAD, automatic response creation, interruption,
    and configurable input transcription.
* The official function-calling quickstart configures tools and receives function
    calls during an ongoing audio conversation.

Inference for AskMyHuman:

* Option B is the correct architecture when the human must ask for clarification,
    revise an answer naturally, or converse with an LLM before a structured result
    is accepted.
* Voice Live function calling can submit the final approval or answer to the
    AskMyHuman request API, but the application must still validate request identity,
    allowed result shape, and one-time completion semantics.

### Implementation Complexity

The application owns three concurrent integration surfaces:

1. Call Automation REST operations and HTTPS lifecycle callbacks for outbound
     call creation and hang-up.
2. An application-hosted secure WebSocket to which ACS sends and receives call
     media.
3. A separately authenticated Voice Live WebSocket with session configuration,
     audio-buffer events, response audio, transcripts, VAD, and errors.

The relay must unwrap ACS JSON, base64-decode PCM, append audio to Voice Live,
receive Voice Live audio deltas, wrap and base64-encode them for ACS, and send
`StopAudio` to ACS on barge-in. It also needs bounded buffering, cancellation,
reconnect or fail-call policy, observability, and coordinated cleanup.

The official accelerator demonstrates this division in separate ACS event,
ACS media, Voice Live media, call loop, and call manager modules. Its ACS path
answers inbound calls. AskMyHuman must adapt it to create outbound calls and bind
each call to a pending request.

### Audio and Protocol Requirements

Documented facts:

* [Audio streaming overview](https://learn.microsoft.com/azure/communication-services/concepts/call-automation/audio-streaming-concept)
    says ACS exposes bidirectional call audio over WebSocket. ACS supports mixed and
    unmixed streams, sends 50 frames per second at 20 ms per packet, and uses 16-bit
    PCM mono at 16 kHz or 24 kHz. Packets are 640 bytes at 16 kHz and 960 bytes at
    24 kHz before base64 encoding.
* [Quickstart: Server-side Audio Streaming](https://learn.microsoft.com/azure/communication-services/how-tos/call-automation/audio-streaming-quickstart)
    requires an application WebSocket server. ACS sends `AudioMetadata`, then JSON
    `AudioData` messages containing base64 audio. The application returns JSON
    `AudioData` and can send `StopAudio`.
* Voice Live uses a separate authenticated WSS endpoint. The current endpoint form
    is `wss://<resource>.services.ai.azure.com/voice-live/realtime` with an API
    version and model or agent identifiers.
* Voice Live accepts `pcm16` input at 16 kHz or 24 kHz, with 24 kHz as the default.
    Audio is appended as base64 through input audio buffer events, and generated
    audio arrives through response audio delta events.

Inference for AskMyHuman:

* Configure both sides for PCM16, 24 kHz, mono. This matches the official
    accelerator and avoids resampling in the normal relay path.
* Matching audio formats does not remove protocol translation. ACS and Voice Live
    use different message envelopes, connection ownership, authentication, events,
    and playback interruption controls.

### Status and Prerequisites

Documented facts:

* [Call Automation and Azure OpenAI](https://learn.microsoft.com/azure/communication-services/samples/call-automation-azure-openai-sample)
    explicitly states that ACS bidirectional streaming is generally available.
* Current Voice Live overview, WebSocket how-to, and quickstart pages reviewed on
    2026-09-15 contain no service-wide Preview warning. They explicitly label
    specific Preview items, including `phi4-mm-realtime`, MAI Transcribe, MAI Voice,
    and Voice Live WebRTC.
* Voice Live requires a Microsoft Foundry resource or Azure Speech resource.
    Microsoft Entra authentication is recommended; the how-to requires the
    `Cognitive Services User` and `Foundry User` roles for the recommended keyless
    path. A Speech resource does not support Foundry Agent Service integration or
    bring-your-own-model.
* [Supported regions for Azure Speech](https://learn.microsoft.com/azure/ai-services/speech-service/regions?tabs=voice-live)
    provides a region-by-model matrix. Availability and deployment type differ by
    model. The official accelerator calls out East US 2, Sweden Central, West US 2,
    and Southeast Asia as common compatible choices, not as an exhaustive list.
* The same ACS phone-number, subscription, billing-address, and direct-routing
    prerequisites from Option A apply.

Status inference:

* The current absence of a global Preview notice, explicit per-feature Preview
    labels, and use of `azure-ai-voicelive>=1.1.0` by the official accelerator are
    consistent with a non-preview core WebSocket surface. Because the reviewed Learn
    pages do not explicitly say "Voice Live is generally available," production
    governance should verify the selected model, API version, SKU, and SLA rather
    than extending this inference to every Voice Live capability.

Deployment inference:

* Select the Voice Live model first, then choose a listed region that also meets
    Container Apps and organizational data-boundary requirements. Co-locating the
    relay and Voice Live resource should reduce avoidable network latency, although
    the reviewed documentation does not mandate co-location.

### Official Samples

The official telephony accelerator contains the complete custom bridge pattern:

* `server/app/providers/acs/event_handler.py` configures ACS bidirectional
    PCM24K media at
    [Azure-Samples/call-center-voice-agent-accelerator](https://github.com/Azure-Samples/call-center-voice-agent-accelerator/blob/162cef590787b3bcc0a051608a7981f2a01daf41/server/app/providers/acs/event_handler.py)
* `server/app/providers/acs/media_handler.py` translates ACS JSON/base64 audio at
    [Azure-Samples/call-center-voice-agent-accelerator](https://github.com/Azure-Samples/call-center-voice-agent-accelerator/blob/162cef590787b3bcc0a051608a7981f2a01daf41/server/app/providers/acs/media_handler.py)
* `server/app/handler/voicelive_media_handler.py` owns the Voice Live connection,
    session, input buffer, response audio, transcript events, and barge-in at
    [Azure-Samples/call-center-voice-agent-accelerator](https://github.com/Azure-Samples/call-center-voice-agent-accelerator/blob/162cef590787b3bcc0a051608a7981f2a01daf41/server/app/handler/voicelive_media_handler.py)
* `server/app/call_loop.py` and `server/app/call_manager.py` illustrate connection
    lifetime, capacity, idle timeout, and cleanup at
    [call_loop.py](https://github.com/Azure-Samples/call-center-voice-agent-accelerator/blob/162cef590787b3bcc0a051608a7981f2a01daf41/server/app/call_loop.py)
    and [call_manager.py](https://github.com/Azure-Samples/call-center-voice-agent-accelerator/blob/162cef590787b3bcc0a051608a7981f2a01daf41/server/app/call_manager.py)

The official Voice Live function-calling sample is:

* `python/voice-live-quickstarts/function-calling-quickstart.py` at
    [microsoft-foundry/voicelive-samples](https://github.com/microsoft-foundry/voicelive-samples/blob/49d6dee33e409dd4dcf56bd16f2c4267dcb35639/python/voice-live-quickstarts/function-calling-quickstart.py)

## Option C: Native Voice Live Telephony Integration

### Search Result

No documented native Microsoft Voice Live telephony integration was found.

Documented facts:

* [Use the Call Center Voice Agent Accelerator](https://learn.microsoft.com/azure/ai-services/speech-service/voice-live-telephony)
    says that Voice Live supplies the unified speech interface and that ACS Call
    Automation APIs provide the telephony integration. It links the application
    solution template evaluated under Option B.
* The page also lists third-party telephony audio connectors for Twilio, Infobip,
    Genesys, Sinch, and Bandwidth. These are provider media interfaces, not native
    Voice Live phone numbers or SIP termination.
* The linked accelerator implements provider-specific WebSocket handlers and a
    shared Voice Live handler. For ACS, it explicitly unwraps and rewraps audio in
    application code.
* The Voice Live overview and how-to document WebSocket and WebRTC clients. They
    do not document a Voice Live PSTN number, SIP trunk, ACS resource attachment,
    or direct service-to-service call-media setting.

Inference:

* Option C is not a currently implementable architecture from documented Microsoft
    interfaces. The phrase "telephony integration" on the Voice Live page describes
    an application integration using ACS or a third-party connector, not a managed
    native attachment.
* Absence from the reviewed first-party documentation is not proof that no private
    preview or partner-specific capability exists. It is sufficient to exclude the
    option from an MVP based on supported public documentation.

### Complexity, Status, and Prerequisites

There is no native implementation complexity, audio contract, Preview or GA
status, region list, or number prerequisite to evaluate because no such product
surface is documented. Following the official telephony page leads back to Option
B and therefore inherits its relay, Voice Live region, ACS number, and deployment
requirements.

### Official Samples

No native Voice Live telephony sample was found. The only Microsoft sample linked
from the telephony page is the custom application bridge:

* [Azure-Samples/call-center-voice-agent-accelerator at the reviewed commit](https://github.com/Azure-Samples/call-center-voice-agent-accelerator/tree/162cef590787b3bcc0a051608a7981f2a01daf41)

## Facts and Inferences

### Five Critical Facts

1. Call Automation speech mode returns free-form recognized text in
     `RecognizeCompleted`, while choices mode returns a constrained label suitable
     for Approve/Reject.
2. Option A does not require application media streaming. ACS and the connected
     Azure AI multi-service resource handle speech-to-text and text-to-speech.
3. ACS bidirectional media streaming is generally available and uses application-
     hosted WebSocket JSON messages carrying base64 PCM16 mono audio at 16 or 24 kHz.
4. Voice Live is a different authenticated real-time session protocol. The
     official ACS telephony accelerator contains code that translates between ACS
     and Voice Live, which proves the documented solution is a relay, not a direct
     attachment.
5. Microsoft documents ACS Call Automation or third-party provider connectors as
     Voice Live telephony integration. No native Voice Live PSTN number, SIP endpoint,
     or ACS service-to-service media attachment is documented.

### Decision-Bearing Inferences

* Option A is fastest because it reuses an official outbound approval sample and
    avoids every real-time audio responsibility.
* Option B is warranted only when "conversational" means natural multi-turn LLM
    interaction rather than a spoken prompt followed by one answer.
* Option C should not remain on the implementation shortlist unless Microsoft
    supplies additional product documentation or a supported private-preview offer.

## Sources

All sources were accessed on 2026-09-15.

### Azure Communication Services

* Microsoft Learn, [Call Automation Overview](https://learn.microsoft.com/azure/communication-services/concepts/call-automation/call-automation)
* Microsoft Learn, [Gathering user input](https://learn.microsoft.com/azure/communication-services/concepts/call-automation/recognize-action)
* Microsoft Learn, [Gather user input with Recognize action](https://learn.microsoft.com/azure/communication-services/how-tos/call-automation/recognize-action)
* Microsoft Learn, [Connect Azure Communication Services with Foundry Tools](https://learn.microsoft.com/azure/communication-services/concepts/call-automation/azure-communication-services-azure-cognitive-services-integration)
* Microsoft Learn, [Quickstart: Make an outbound call using Call Automation](https://learn.microsoft.com/azure/communication-services/quickstarts/call-automation/quickstart-make-an-outbound-call)
* Microsoft Learn, [Audio streaming overview](https://learn.microsoft.com/azure/communication-services/concepts/call-automation/audio-streaming-concept)
* Microsoft Learn, [Quickstart: Server-side Audio Streaming](https://learn.microsoft.com/azure/communication-services/how-tos/call-automation/audio-streaming-quickstart)
* Microsoft Learn, [Call Automation and Azure OpenAI](https://learn.microsoft.com/azure/communication-services/samples/call-automation-azure-openai-sample)
* Microsoft Learn, [Phone number types](https://learn.microsoft.com/azure/communication-services/concepts/numbers/number-types)
* Microsoft Learn, [Country/region availability of telephone numbers and subscription eligibility](https://learn.microsoft.com/azure/communication-services/concepts/numbers/sub-eligibility-number-capability)
* Microsoft Learn, [Telephony concepts](https://learn.microsoft.com/azure/communication-services/concepts/telephony/telephony-concept)

### Voice Live

* Microsoft Learn, [Voice Live API Overview](https://learn.microsoft.com/azure/ai-services/speech-service/voice-live)
* Microsoft Learn, [How to use the Voice Live API](https://learn.microsoft.com/azure/ai-services/speech-service/voice-live-how-to)
* Microsoft Learn, [Quickstart: Create a Voice Live real-time voice agent](https://learn.microsoft.com/azure/ai-services/speech-service/voice-live-quickstart)
* Microsoft Learn, [Supported regions for Azure Speech](https://learn.microsoft.com/azure/ai-services/speech-service/regions?tabs=voice-live)
* Microsoft Learn, [Use the Call Center Voice Agent Accelerator](https://learn.microsoft.com/azure/ai-services/speech-service/voice-live-telephony)

### Microsoft-Owned GitHub Repositories

* [Azure-Samples/communication-services-python-quickstarts](https://github.com/Azure-Samples/communication-services-python-quickstarts/tree/052a2dca2f369631ed353a7d0cff9e4aec339280)
* [Azure-Samples/call-center-voice-agent-accelerator](https://github.com/Azure-Samples/call-center-voice-agent-accelerator/tree/162cef590787b3bcc0a051608a7981f2a01daf41)
* [microsoft-foundry/voicelive-samples](https://github.com/microsoft-foundry/voicelive-samples/tree/49d6dee33e409dd4dcf56bd16f2c4267dcb35639)

## Unresolved Deployment Inputs

The architecture decision does not depend on these inputs, but deployment does:

* The owner's destination country or region and the Azure subscription billing
    address are not specified. Exact ACS number availability, regulatory documents,
    outbound capability, and trial-number eligibility must be checked for that pair.
* The Voice Live model and data-boundary requirement are not specified. They are
    needed only if Option B is selected and determine the eligible Foundry regions
    and deployment type.