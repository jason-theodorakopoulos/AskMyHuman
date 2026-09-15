---
title: Azure Voice Telephony Integration Research
description: Authoritative research on outbound Azure Communication Services telephony integration with Microsoft Foundry Voice Live API
ms.date: 2026-09-15
ms.topic: research
---

## Research Scope

Research current Microsoft and Azure documentation, accessed on 2026-09-15, to answer:

* What is the current service name and API for Microsoft Foundry Voice Live?
* Can Azure Communication Services Call Automation stream bidirectional audio directly to Voice Live?
* What media relay, WebSocket components, audio formats, events, controls, and authentication are required?
* What phone number, regional availability, latency, and session-limit constraints apply?
* Which official quickstarts and samples establish the supported implementation?
* How do direct Call Automation recognize/play, bidirectional media streaming plus Voice Live, and any native telephony integration compare?
* Which path is best for a very tight MVP?

## Working Hypothesis

A custom application relay is required because Azure Communication Services Call Automation and Voice Live expose separate WebSocket protocols. A direct service-to-service attachment or native telephony integration would disprove this hypothesis.

## Evidence Standard

* Prefer current Microsoft Learn, Azure reference, SDK, and Microsoft-owned sample repositories.
* Record source URLs and access context.
* Separate documented facts from architectural inference.
* Record preview status, regional caveats, contradictions, and unverified limits.

## Findings

### Decisive Architecture Answer

For an outbound PSTN call, the supported Microsoft architecture is:

1. The application uses Azure Communication Services (ACS) Call Automation to
	create the outbound call from an ACS phone number or a direct-routing
	endpoint.
2. After the call connects, Call Automation streams call media to an
	application-owned WebSocket endpoint.
3. That application opens a separate authenticated WebSocket session to the
	Foundry Voice Live API, translates the two services' event envelopes, and
	forwards audio in both directions.
4. Call Automation remains the call-control plane for answer, hang-up,
	transfer, and media-streaming lifecycle. Voice Live remains the
	conversational speech-to-speech plane.

A custom relay is therefore required for this architecture. The current
Microsoft telephony page identifies ACS Call Automation as the telephony
integration and links an application solution template, the Call Center Voice
Agent Accelerator. It does not document a Voice Live phone-number, SIP, or ACS
service-to-service attachment. The page also lists third-party audio connectors
as alternatives, which likewise require an integration component between the
telephony provider and Voice Live.

Evidence: Microsoft Learn, [Call Center Voice Agent Accelerator - Foundry
Tools](https://learn.microsoft.com/azure/ai-services/speech-service/voice-live-telephony),
updated 2026-08-26; Microsoft GitHub,
[Azure-Samples/call-center-voice-agent-accelerator](https://github.com/Azure-Samples/call-center-voice-agent-accelerator).

## Option Evaluation

Research in progress.

## Recommendation

Research in progress.

## Gaps and Clarifying Questions

Research in progress.

## Sources

Research in progress.
