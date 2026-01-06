# MCP Design and Architecture

### For Aspen Incident QA — Intelligent Technical Incident Search & QA Platform

---

## 📘 Overview

This document describes the internal **Model Context Protocol (MCP)** framework design implemented in the **Aspen Incident QA** system.

The MCP architecture provides a modular and transparent interface between:

* **The model and reasoning layer (Copilot Business API)**
* **The retrieval and context layer (RAG + TF-IDF + Mapping Index)**

By separating retrieval from reasoning, the system ensures:

* Data–model decoupling
* Safe context access
* Fast, reusable query execution
* A foundation for future enterprise MCP compatibility

---

## 🧩 High-Level Concept

<pre class="overflow-visible!" data-start="954" data-end="1478"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre!"><span><span>User</span><span> Query ──► MCP Client ──► Copilot (Intent Analysis)
                    │
                    ▼
              MCP </span><span>Server</span><span> (Data Layer)
         ┌──────────────────────────────┐
         │  • RAG semantic retrieval     │
         │  • TF-IDF keyword retrieval   │
         │  • </span><span>desc</span><span> → resolution </span><span>mapping</span><span>  │
         └──────────────────────────────┘
                    │
                    ▼
         Copilot (Phase II Reasoning)
                    │
                    ▼
               Final Synthesized Answer
</span></span></code></div></div></pre>

---

## 🏗 MCP Server Design

*(Files: `router.py`, `orchestrator.py`, `rag/*`, `utils/server.py`)*

### 1️⃣ Initialization and Pre-Build

When the server starts, it loads all pre-computed data into memory:

* **Vector index:** `embeddings.npy`, `vectorizer.pkl`, `embedder_meta.json`
* **Keyword index:** `tfidf_csr.npz`, `mapping.csv`
* **Metadata:** `incidents.csv` (including `incident_id`, `desc`, `resolution`, etc.)

These resources allow **millisecond-level top-k retrieval** via in-memory search.

---

### 2️⃣ Exposed Endpoints (MCP “tools”)

#### **`oneshot.search` — Phase-I retrieval**

**Input:**

<pre class="overflow-visible!" data-start="2091" data-end="2171"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-json"><span><span>{</span><span></span><span>"query"</span><span>:</span><span></span><span>"string"</span><span>,</span><span></span><span>"top_k"</span><span>:</span><span></span><span>8</span><span>,</span><span></span><span>"filters"</span><span>:</span><span></span><span>{</span><span></span><span>"product"</span><span>:</span><span></span><span>"HYSYS"</span><span></span><span>}</span><span></span><span>}</span><span>
</span></span></code></div></div></pre>

**Actions:**

1. Perform **semantic retrieval** via embeddings (RAG)
2. Perform **keyword retrieval** via TF-IDF
3. Merge and re-rank results
4. Map descriptions to resolutions

**Output:**

<pre class="overflow-visible!" data-start="2370" data-end="2638"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-json"><span><span>{</span><span>
  </span><span>"results"</span><span>:</span><span></span><span>[</span><span>
    </span><span>{</span><span>
      </span><span>"incident_id"</span><span>:</span><span></span><span>"INC123"</span><span>,</span><span>
      </span><span>"desc"</span><span>:</span><span></span><span>"..."</span><span>,</span><span>
      </span><span>"resolution"</span><span>:</span><span></span><span>"..."</span><span>,</span><span>
      </span><span>"score_sem"</span><span>:</span><span></span><span>0.83</span><span>,</span><span>
      </span><span>"score_kw"</span><span>:</span><span></span><span>0.72</span><span>,</span><span>
      </span><span>"source"</span><span>:</span><span></span><span>"embedding|tfidf"</span><span>,</span><span>
      </span><span>"meta"</span><span>:</span><span></span><span>{</span><span></span><span>"date"</span><span>:</span><span></span><span>"2024-10-12"</span><span>,</span><span></span><span>"product"</span><span>:</span><span></span><span>"HYSYS"</span><span></span><span>}</span><span>
    </span><span>}</span><span>
  </span><span>]</span><span>
</span><span>}</span><span>
</span></span></code></div></div></pre>

---

#### **`batch.search` — Batch mode**

* Handles multiple queries for evaluation or offline index validation.

#### **`health.ping` — Health check**

* Returns index version, memory usage, latency metrics, and uptime status.

---

### 3️⃣ Scoring and Deduplication

Multi-channel results are merged via weighted ranking:

<pre class="overflow-visible!" data-start="2964" data-end="3041"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre!"><span><span>final_score</span><span> = w1*semantic + w2*keyword + w3*recency + w4*productMatch
</span></span></code></div></div></pre>

Duplicate incident IDs are removed while preserving **context diversity** among snippets.

---

### 4️⃣ Observability and Logging

* Each request carries a `request_id` for traceability.
* Server logs include query, Top-K results, index versions, and latency.
* The `health.ping` endpoint exposes live metrics (QPS, P95 latency, hit ratio).

---

## 💡 MCP Client Design

*(Files: `mcp_client.py`, `orchestrator.py`, `synthesizer.py`)*

### 1️⃣ Two-Phase Orchestration

#### **Phase I — Intent Analysis & Retrieval**

1. Copilot analyzes the user query via prompt templates (`router.system.txt`, `router.user.txt`).
2. The model outputs a routing plan:
   <pre class="overflow-visible!" data-start="3707" data-end="3836"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-json"><span><span>{</span><span>
     </span><span>"need_search"</span><span>:</span><span></span><span>true</span><span></span><span>,</span><span>
     </span><span>"top_k"</span><span>:</span><span></span><span>8</span><span>,</span><span>
     </span><span>"filters"</span><span>:</span><span></span><span>{</span><span>"product"</span><span>:</span><span></span><span>"HYSYS"</span><span>}</span><span>,</span><span>
     </span><span>"next"</span><span>:</span><span></span><span>"phase_II"</span><span>
   </span><span>}</span><span>
   </span></span></code></div></div></pre>
3. Client calls the MCP server (`oneshot.search`) with the provided parameters.
4. Top-K incident candidates (desc + resolution) are returned.

---

#### **Phase II — Applicability Reasoning & Synthesis**

1. The client sends the Top-K candidates to Copilot for deeper reasoning.
2. Copilot evaluates which resolutions are relevant or partially applicable.
3. `synthesizer.py` assembles a structured response including:
   * Ranked applicable incidents
   * Summarized solution steps
   * Confidence levels and uncertainty prompts

**Result example:**

<pre class="overflow-visible!" data-start="4400" data-end="4745"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-json"><span><span>{</span><span>
  </span><span>"answer"</span><span>:</span><span></span><span>"Likely caused by missing stream mapping. Re-import with proper units..."</span><span>,</span><span>
  </span><span>"applied_incidents"</span><span>:</span><span></span><span>[</span><span>
    </span><span>{</span><span>"incident_id"</span><span>:</span><span></span><span>"INC123"</span><span>,</span><span></span><span>"why"</span><span>:</span><span></span><span>"Identical root cause"</span><span>}</span><span>,</span><span>
    </span><span>{</span><span>"incident_id"</span><span>:</span><span></span><span>"INC456"</span><span>,</span><span></span><span>"why"</span><span>:</span><span></span><span>"Partial match on data import issue"</span><span>}</span><span>
  </span><span>]</span><span>,</span><span>
  </span><span>"followups"</span><span>:</span><span></span><span>[</span><span>"Please confirm your version"</span><span>,</span><span></span><span>"Attach log for validation"</span><span>]</span><span>
</span><span>}</span><span>
</span></span></code></div></div></pre>

---

### 2️⃣ Client Invocation Modes

| Method        | Description                                        |
| ------------- | -------------------------------------------------- |
| `oneshot()` | Single query–response; no chat memory.            |
| `chat()`    | Multi-turn dialogue with persistent context.       |
| `stream()`  | Streamed output for real-time front-end rendering. |

---

### 3️⃣ Fallback and Resilience

* If MCP server is unavailable → fallback to keyword-only mode.
* If Copilot rate-limits (HTTP 429) → exponential backoff + cached reuse.
* If context too large → truncate to top-M results and summary tokens.

---

### 4️⃣ Security and Boundary Rules

* Server strips all personal identifiers and sensitive fields.
* Client only exposes minimal context snippets with permission control.
* Configurations (`github_models.local.json`) define model endpoints and environments (dev/stage/prod).

---

## 🔄 Sequence Diagram

<pre class="overflow-visible!" data-start="5588" data-end="6116"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-mermaid"><span>sequenceDiagram
    participant U as User
    participant C as MCP Client
    participant S as MCP Server
    participant M as Copilot Model

    U->>C: "Why does HYSYS crash when importing data?"
    C->>M: Intent Classification (router)
    M-->>C: {"need_search": true, "top_k": 8}
    C->>S: oneshot.search(query, top_k=8)
    S-->>C: Top-K incidents (desc + resolution)
    C->>M: Contextual reasoning with Top-K
    M-->>C: Synthesized answer + applied_incidents
    C-->>U: Structured response + follow-ups
</span></code></div></div></pre>

---

## 📜 Data Contracts

**Search Request**

<pre class="overflow-visible!" data-start="6164" data-end="6292"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-json"><span><span>{</span><span>
  </span><span>"request_id"</span><span>:</span><span></span><span>"uuid"</span><span>,</span><span>
  </span><span>"query"</span><span>:</span><span></span><span>"string"</span><span>,</span><span>
  </span><span>"top_k"</span><span>:</span><span></span><span>8</span><span>,</span><span>
  </span><span>"filters"</span><span>:</span><span></span><span>{</span><span>"product"</span><span>:</span><span>"HYSYS"</span><span>,</span><span>"since"</span><span>:</span><span>"2024-01-01"</span><span>}</span><span>
</span><span>}</span><span>
</span></span></code></div></div></pre>

**Search Response**

<pre class="overflow-visible!" data-start="6314" data-end="6468"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-json"><span><span>{</span><span>
  </span><span>"request_id"</span><span>:</span><span></span><span>"uuid"</span><span>,</span><span>
  </span><span>"results"</span><span>:</span><span></span><span>[</span><span>...</span><span>]</span><span>,</span><span>
  </span><span>"index_meta"</span><span>:</span><span></span><span>{</span><span>
    </span><span>"embed_model"</span><span>:</span><span></span><span>"nomic-embed-text"</span><span>,</span><span>
    </span><span>"tfidf_version"</span><span>:</span><span></span><span>"2025-10-20"</span><span>
  </span><span>}</span><span>
</span><span>}</span><span>
</span></span></code></div></div></pre>

**Synthesis Response**

<pre class="overflow-visible!" data-start="6493" data-end="6780"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-json"><span><span>{</span><span>
  </span><span>"answer"</span><span>:</span><span></span><span>"final natural-language response ..."</span><span>,</span><span>
  </span><span>"applied_incidents"</span><span>:</span><span></span><span>[</span><span>
    </span><span>{</span><span>"incident_id"</span><span>:</span><span>"INC-2024-00123"</span><span>,</span><span>"why"</span><span>:</span><span>"matches root-cause"</span><span>}</span><span>,</span><span>
    </span><span>{</span><span>"incident_id"</span><span>:</span><span>"INC-2024-00456"</span><span>,</span><span>"why"</span><span>:</span><span>"partial overlap"</span><span>}</span><span>
  </span><span>]</span><span>,</span><span>
  </span><span>"followups"</span><span>:</span><span></span><span>[</span><span>"Confirm software version"</span><span>,</span><span></span><span>"Attach crash logs"</span><span>]</span><span>
</span><span>}</span><span>
</span></span></code></div></div></pre>

---

## ⚙️ Implementation Pseudocode

**Client (simplified)**

<pre class="overflow-visible!" data-start="6846" data-end="7084"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-python"><span><span>plan = copilot_router.classify(query)
</span><span>if</span><span> plan.need_search:
    hits = mcp_server.oneshot_search(query, plan.top_k, plan.filters)
</span><span>else</span><span>:
    hits = []

final = copilot_synth.summarize(query=query, candidates=hits)
</span><span>return</span><span> final
</span></span></code></div></div></pre>

**Server (simplified)**

<pre class="overflow-visible!" data-start="7112" data-end="7345"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-python"><span><span>def</span><span></span><span>oneshot_search</span><span>(</span><span>query, top_k=8</span><span>, filters=</span><span>None</span><span>):
    sem = rag.search_semantic(query, top_k)
    kw  = rag.search_tfidf(query, top_k)
    fused = fuse_and_dedup(sem, kw)
    </span><span>return</span><span> map_desc_to_resolution(fused)[:top_k]
</span></span></code></div></div></pre>

---

## 🧠 Observations

* **MCP Server:** “Data-centric” — retrieval, mapping, caching.
* **MCP Client:** “Model-centric” — reasoning, orchestration, synthesis.
* **Copilot Model:** “Semantic intelligence” — understanding and contextual validation.

Together they form a  **closed-loop reasoning pipeline** :

> Retrieval → Understanding → Validation → Synthesis → Feedback

---

## 🚀 Future Enhancements

| Area                   | Planned Improvement                            |
| ---------------------- | ---------------------------------------------- |
| Multi-Agent Expansion  | Dedicated QA, Summarizer, Classifier modules   |
| Feedback Loop          | Use user corrections to refine ranking weights |
| Index Refresh          | Periodic auto-rebuild of embeddings and TF-IDF |
| CRM Integration        | Connect with Outlook / Salesforce incidents    |
| Full MCP Compatibility | Switch to official Copilot MCP API once public |

---

## ✅ Summary

The MCP framework in *Aspen Incident QA* serves as a **lightweight, enterprise-ready abstraction layer** between Copilot reasoning and historical incident data.

It allows engineers to:

* Retrieve the most relevant incidents rapidly,
* Let the model reason about applicability,
* Deliver safe, auditable, and context-aware technical responses.

> **In short:**
>
> *MCP bridges structured enterprise knowledge and Copilot’s generative reasoning — turning past incident data into actionable intelligence.*
>
