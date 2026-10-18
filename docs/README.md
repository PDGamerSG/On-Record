# Documentation

Where to find each part of the On Record documentation. Everything here describes the repository as it is; statements cite the file and line they come from, and anything the repository does not record is marked "[unverified]" or "Not recorded in the repository".

## Start here

| Document | What it covers |
| --- | --- |
| [README](../README.md) | What On Record is, how it works, screenshots, the quick start and the repository map |
| [User guide](user-guide.md) | Each page of the web app and the Ask drawer, and what works in demo mode |
| [Glossary](glossary.md) | Terms used in the code and the documents, with their source files |
| [Troubleshooting](TROUBLESHOOTING.md) | Docker, Colima, Node and Python setup problems |

## Requirements

| Document | What it covers |
| --- | --- |
| [Software requirements specification](requirements/SRS.md) | Functional (FR) and quality (NFR) requirements with status and evidence, external interfaces and use cases |

## Architecture and design

| Document | What it covers |
| --- | --- |
| [Architecture overview](ARCHITECTURE.md) | How the web app, the API and the graph fit together, the data flows, the Ask sequence and the graph schema |
| [Architecture description (arc42)](architecture/README.md) | Goals, constraints, context, building blocks, runtime and deployment views, cross-cutting concepts, risks |
| [Architecture decision records](adr/README.md) | Decisions evidenced in the code, recorded retroactively |
| [Software design specification](design/SDS.md) | The design by IEEE 1016 viewpoints: composition, classes, dependencies, algorithms and resource limits |
| [Behaviour diagrams](design/behaviour.md) | Sequence, activity and state diagrams for the main flows |
| [Data model](design/data-model.md) | The graph and document schema, data dictionary, indexes and data-flow diagrams |
| [Design direction](DESIGN.md) | The visual design: tokens, type, motion and the landing page |

## Interfaces

| Document | What it covers |
| --- | --- |
| [HTTP API reference](api/README.md) | Every route, the event stream and the routes the web client expects; [OpenAPI schema](api/openapi.json) |
| [Configuration](CONFIGURATION.md) | Every environment variable, its default and what reads it |
| [Web app](../apps/web/README.md) | Routes, demo mode, API settings, window events and the 3D assets |

## Testing, operations and security

| Document | What it covers |
| --- | --- |
| [Test plan](testing/test-plan.md) | Test levels, the test inventory, how to run the checks, CI and manual demo cases |
| [Traceability matrix](testing/traceability.md) | Each requirement mapped to its design section, code and tests |
| [Deployment and operations](operations/deployment.md) | Local topology, services, ports, model downloads and logs |
| [Threat model](security/threat-model.md) | STRIDE analysis, what data leaves the machine, key handling and prompt-injection mitigations |
| [Local Gemma runtime](LOCAL_GEMMA.md) | Running Gemma 4 locally with Ollama, and the smoke benchmark |

## History

| Document | What it covers |
| --- | --- |
| [Source notes](UPSTREAM.md) | The upstream snapshot this repository is assembled from, and attribution |
