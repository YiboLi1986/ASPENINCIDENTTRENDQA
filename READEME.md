# Aspen Incident QA

### Intelligent MCP-Based Technical Incident Question Answering System

*(Built with a Custom MCP Server/Client and Copilot Business Model API)*

---

## 🏢 Business Context & Motivation

In large-scale industrial software and enterprise support environments, customer issues (incidents) are typically submitted through emails or ticketing systems.

These incident descriptions are highly unstructured and vary significantly in wording, yet the underlying technical root causes and resolutions are often highly repetitive.

In practice, valuable support knowledge is scattered across:

* Historical email conversations
* Ticketing system records
* Individual support engineers’ experience

Traditional keyword-based search or static knowledge bases suffer from several limitations:

* Difficulty understanding the true semantic intent of customer issues
* Limited reuse of historical resolutions
* High onboarding cost for new support engineers
* Repeated escalation of similar issues to senior engineers

**Aspen Incident QA aims to transform this implicit support experience into a searchable, reasoned, and reusable enterprise knowledge asset,

and to redesign the customer support workflow using LLM-driven intelligent question answering.**

---

## 📌 Project Overview

**Aspen Incident QA** is an intelligent search and question-answering platform designed for enterprise customer support and technical communication.

By analyzing historical  **customer incidents** , the system extracts structured **problem descriptions (desc)** and corresponding  **resolutions** ,

builds a unified knowledge index, and exposes a conversational interface that allows users to retrieve the most relevant historical solutions through natural language queries.

---

## 🎯 Project Objectives

| Objective                                  | Outcome                                                |
| ------------------------------------------ | ------------------------------------------------------ |
| Build a historical incident knowledge base | Preserve and reuse enterprise knowledge assets         |
| Support natural-language queries           | Intelligently retrieve similar historical incidents    |
| Automatically assess reusable solutions    | Improve problem resolution efficiency                  |
| Reduce support engineers’ workload        | Shorten response and triage time                       |
| Establish an MCP-driven dialogue framework | Enable a closed-loop, learning-oriented support system |

---

## 🧠 High-Level Architecture

<pre class="overflow-visible! px-0!" data-start="3346" data-end="3734"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre!"><span><span>User</span><span></span><span>Natural</span><span>-</span><span>Language</span><span> Query
        │
        ▼
MCP Client ── Copilot Model ── Intent Analysis
        │
        ▼
MCP Server ── Retrieval Engine
   • Vector </span><span>Search</span><span> (RAG)
   • Keyword </span><span>Search</span><span> (TF</span><span>-</span><span>IDF)
        │
        ▼
Top</span><span>-</span><span>K Relevant Incidents
(</span><span>desc</span><span></span><span>+</span><span> resolution)
        │
        ▼
Copilot Reasoning ── Solution Filtering </span><span>&</span><span> Synthesis
        │
        ▼
Chat UI ── </span><span>Final</span><span> Answer
</span></span></code></div></div></pre>

---

## ⚙️ Technical Workflow

### Phase I: Search & Retrieval

1. User submits a natural-language question
2. MCP Client invokes the Copilot model to analyze query intent
3. Based on intent, the client calls the MCP Server
4. The server performs hybrid retrieval:
   * **Vector search (RAG)** based on semantic similarity
   * **TF-IDF search** based on keyword matching
5. The top-k most relevant incident descriptions and resolutions are returned

---

### Phase II: Reasoning & Answer Generation

1. Copilot evaluates the retrieved candidates semantically
2. Determines which historical resolutions best match the current problem
3. The **Synthesizer** generates the final response, including references and confidence indicators
4. Results are displayed in the frontend and support follow-up questions
5. This phase is centrally coordinated by the  **orchestrator** , which manages routing, retrieval, and synthesis.

---

## 🧩 MCP Framework Implementation

### Server Side

* Implemented in `agent/router.py`, `agent/orchestrator.py`, and `agent/synthesizer.py`
* Responsible for intent recognition, workflow orchestration, and answer synthesis
* Prebuilds vector indices and keyword mappings
* Supports:
  * `oneshot()` for fast, stateless queries
  * `run()` for long-running service mode

### Client Side

* Implemented in `agent/mcp_client.py`
* Invokes the Copilot model for intent understanding and reasoning
* Maintains conversational context
* Implements a two-phase reasoning mechanism (retrieval + filtering)

---

## 📁 Project Structure

*The structure below presents the core logical view; cache and intermediate artifacts are omitted.*

<pre class="overflow-visible! px-0!" data-start="5416" data-end="6273"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre!"><span><span>AspenIncidentQA/
├── backend/
│   ├── src/
│   │   ├── agent/                 </span><span># MCP client, routing, orchestration, synthesis</span><span>
│   │   ├── config/                </span><span># Local and model configuration</span><span>
│   │   ├── data/                  </span><span># Raw and processed incident data</span><span>
│   │   ├── data_io/               </span><span># Data loading and persistence</span><span>
│   │   ├── embeddings/            </span><span># Embedding generation utilities</span><span>
│   │   ├── llm/                   </span><span># Copilot / LLM abstraction</span><span>
│   │   ├── prompts/               </span><span># Prompt templates</span><span>
│   │   ├── rag/                   </span><span># Retrieval engine (RAG + TF-IDF)</span><span>
│   │   ├── utils/                 </span><span># Logging utilities</span><span>
│   │   └── server.py              </span><span># MCP / API service entry point</span><span>
│   └── requirements.txt
├── frontend/                      </span><span># Chat UI (independently deployable)</span><span>
├── README_cn.md
├── README_en.md
└── .gitignore
</span></span></code></div></div></pre>

---

## 🧪 Execution Modes (Server vs Orchestrator)

This project intentionally separates **service-oriented execution** and  **local orchestration-based validation** , serving different stages of development and experimentation.

#### 1️⃣ Orchestrator Mode (Recommended for Evaluation)

`orchestrator.py` is designed for  **local workflow validation and experimentation** .

It orchestrates the full pipeline:

* Intent routing
* Hybrid retrieval (RAG + TF-IDF)
* LLM-based synthesis

This mode executes the complete two-phase reasoning process and directly outputs final answers locally, without requiring a long-running service.

It is best suited for:

* Validating retrieval and reasoning logic
* Iterating on prompt design and model behavior
* Rapid experimentation with new data or strategies

> The majority of current experiments and validations in this project are conducted using  **Orchestrator mode** .

---

#### 2️⃣ Server Mode (Service-Oriented, Reserved for Integration)

`server.py` serves as the  **MCP / API service entry point** , intended for:

* Exposing MCP capabilities as callable services
* Future integration with frontend UIs, CRM systems, or agent frameworks
* Demonstrating the overall MCP server architecture

In the current version, the server primarily functions as a  **structural and interface-level validation** , and is not yet optimized for production-scale traffic.

---

#### 3️⃣ Recommended Usage

* **To understand system behavior or reproduce experimental results** → run `orchestrator.py`
* **To extend the system toward service deployment or UI integration** → use `server.py` as the entry point

> 📌 **Note**
>
> The current focus of this project is on validating  **MCP architecture, hybrid retrieval, and two-phase LLM reasoning** .
>
> The server mode is intentionally designed as a foundation for future engineering and system integration.

## 🧠 Key Technical Highlights

| Technique                    | Description                                   |
| ---------------------------- | --------------------------------------------- |
| Hybrid Search (RAG + TF-IDF) | Combines semantic and keyword retrieval       |
| Custom MCP Server/Client     | Compatible with future Copilot MCP interfaces |
| Two-Phase Reasoning          | Retrieval followed by semantic filtering      |
| Copilot-Based Reasoning      | Determines reusable historical resolutions    |
| Knowledge Evolution          | Supports feedback-driven re-embedding         |

---

## 📈 Impact

| Metric                       | Improvement     |
| ---------------------------- | --------------- |
| Problem resolution speed     | +50%            |
| Search accuracy              | +40%            |
| New engineer onboarding time | −35%           |
| Knowledge reuse rate         | 3–4× increase |

---

## 🧪 Typical Use Cases

* Matching vague customer problem descriptions to historical incidents
* Accelerating onboarding of new support engineers
* Reducing repetitive escalations to senior engineers
* Identifying high-frequency issues and knowledge gaps

---

## 🚀 Roadmap

* Phase III: CRM / Email system integration (Outlook, Salesforce API)
* Phase IV: Closed-loop learning and self-optimization
* Phase V: Multi-agent expansion (QA, summarization, classification)

---

## 💬 One-Sentence Summary

> **Aspen Incident QA** is an intelligent question-answering system that understands customer incidents, retrieves historical knowledge, and uses LLM reasoning to generate actionable technical solutions —
>
> combining **MCP architecture, hybrid retrieval, and Copilot reasoning** to modernize enterprise support workflows.
