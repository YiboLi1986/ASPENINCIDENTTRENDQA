# 🧠 English Version — Interview Interface Summary

> **Project name:** Aspen Incident QA
>
> **Core idea:** Build an MCP-based intelligent question-answering system that learns from past customer incident emails and generates accurate technical responses.

---

### 🚀 1. Project Overview

Aspen Incident QA is an **AI-powered knowledge assistant** for industrial customer support.

It collects historical **incident email threads** — each with a **problem description** and a **resolution** —

and builds a **hybrid search + reasoning platform** that can automatically retrieve, interpret, and answer new technical questions.

The main purpose is to help engineers and support teams quickly find **relevant historical cases** and reuse the  **right solutions** ,

instead of manually searching through old emails or ticket systems.

---

### ⚙️ 2. System Design (Top-Down)

1️⃣ **MCP Framework (Model Context Protocol)**

We implemented our own **MCP Server–Client** architecture because Copilot’s MCP API is not yet open.

* The **Server** prebuilds two search engines:
  * **RAG engine (embedding-based)** — finds semantically similar incident descriptions.
  * **TF-IDF engine (keyword-based)** — performs traditional inverted index retrieval.

    Both engines map `desc → resolution`.
* The **Client** uses the **Copilot Business model API** to understand user intent and orchestrate retrieval.
  * **Phase I:** Analyze intent → decide if a search is needed → call MCP server to fetch top-k results.
  * **Phase II:** Send the top-k incidents back to Copilot → model reasons which resolutions are truly applicable → synthesize the final structured answer.

2️⃣ **Copilot Business Model Integration**

The model handles  **intent classification** ,  **context evaluation** , and **natural-language synthesis** of responses.

It decides which retrieved resolutions are valid, which are partial, and generates a coherent answer with citations.

3️⃣ **Front-End Chat Interface**

A Streamlit-based UI allows engineers to ask questions naturally, view references, and follow up iteratively.

---

### 🧩 3. Technical Highlights

| Component                   | Function                                                         |
| --------------------------- | ---------------------------------------------------------------- |
| **RAG Search**        | Embedding-based semantic similarity retrieval                    |
| **TF-IDF Search**     | Keyword-based inverted index search                              |
| **Hybrid Fusion**     | Weighted combination of semantic and keyword scores              |
| **MCP Server**        | Provides `oneshot.search`,`batch.search`,`health.ping`APIs |
| **MCP Client**        | Coordinates Copilot calls, manages query context                 |
| **Copilot Model API** | Handles reasoning, ranking, and answer synthesis                 |

---

### 📈 4. Impact and Benefits

| Metric                  | Improvement |
| ----------------------- | ----------- |
| Response time           | ↓ 50%      |
| Knowledge reuse rate    | ↑ 3–4×   |
| New engineer onboarding | ↓ 35%      |
| Resolution accuracy     | ↑ 25%      |

---

### 🧠 5. Personal Contributions

* Designed and implemented the **entire MCP framework** (server, client, protocol interface).
* Developed the **hybrid search engine (RAG + TF-IDF)** and optimized retrieval ranking.
* Integrated Copilot Business APIs for  **two-phase reasoning and synthesis** .
* Built **structured prompts** and **output templates** for consistent, auditable answers.
* Designed **logging, health monitoring, and fallback mechanisms** for reliability.

---

### 💬 6. One-Sentence Summary

> We built an MCP-based intelligent search and QA platform that transforms historical customer incident emails into a  **self-learning technical support assistant** ,
>
> combining  **RAG retrieval** ,  **Copilot reasoning** , and  **hybrid contextual synthesis** .
>
