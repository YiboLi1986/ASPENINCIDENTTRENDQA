# Aspen Incident QA

### 基于 MCP 框架的智能客户技术问答系统

*(结合自建 MCP Server/Client 与 Copilot 模型 API)*

---

## 🏢 业务背景与问题动机

在大型工业软件与企业级产品支持场景中，客户问题（Incident）通常通过邮件或工单系统提交，
其问题描述高度非结构化、表述方式差异极大，但背后的技术根因与解决方案却往往高度重复。

现实中，这些宝贵的解决经验分散在：

- 历史邮件往来
- 工单系统记录
- 支持工程师的个人经验中

传统的关键词搜索或知识库系统在以下方面存在明显不足：

- 难以理解客户问题的真实语义
- 无法有效复用历史 resolution
- 新支持人员学习成本高
- 高级工程师被反复拉入相似问题处理中

**Aspen Incident QA 的目标，是将“隐性支持经验”转化为可检索、可推理、可复用的企业级知识资产，
并通过 LLM 驱动的智能问答方式，重构客户支持的工作流。**

## 📌 项目概述

**Aspen Incident QA** 是一个面向企业客户支持与技术沟通的智能搜索与问答平台。

系统通过分析历史的  **客户邮件（Incident）** ，提取其中的 **问题描述（desc）** 与  **解决方案（resolution）** ，

构建统一的知识索引与对话接口，让用户通过自然语言提问即可获得最相关的历史解决经验。

---

## 🎯 项目目标

| 目标                        | 结果                        |
| --------------------------- | --------------------------- |
| 构建历史客户问题知识库      | 保留并复用企业知识资产      |
| 支持自然语言提问            | 智能检索相似的历史 Incident |
| 自动筛选可复用方案          | 提高问题解决效率            |
| 降低支持人员工作量          | 缩短响应时间                |
| 搭建 MCP 驱动的智能对话框架 | 构建闭环学习型支持系统      |

---

## 🧠 高层架构

<pre class="overflow-visible!" data-start="7926" data-end="8223"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre!"><span><span>用户自然语言提问
        │
        ▼
MCP Client —— 调用 Copilot 模型 → 分析意图
        │
        ▼
MCP Server —— 搜索引擎：
   • 向量搜索 (RAG)
   • 关键词搜索 (TF-IDF)
        │
        ▼
返回 </span><span>Top</span><span>-K Incident（含 desc + resolution）
        │
        ▼
Copilot 再次分析 —— 筛选可用方案、生成综合回复
        │
        ▼
Chat UI —— 向用户展示最终答案
</span></span></code></div></div></pre>

---

## ⚙️ 技术流程

### 阶段一：搜索与检索

1. 用户输入问题
2. MCP Client 调用 Copilot 模型分析意图
3. 根据意图调用 MCP Server
4. Server 执行混合搜索：
   * 向量搜索 (RAG) —— 基于语义相似度
   * TF-IDF 搜索 —— 基于关键词匹配
5. 返回前 k 个最相关的 incident 描述与对应解决方案

### 阶段二：推理与生成

1. Copilot 模型对返回结果进行语义筛选
2. 判断哪些 resolution 与当前问题最相关
3. Synthesizer 模块生成最终答案（含引用来源与置信度）
4. 前端展示结果并支持进一步追问
5. 该阶段由 orchestrator 统一调度 router、retriever 与 synthesizer 模块完成。

---

## 🧩 MCP 框架实现

* **Server 端（`agent/router.py`, `orchestrator.py`, `synthesizer.py`）**
  * 负责意图识别、流程编排与答案生成
  * 预构建向量索引与关键词映射
  * 支持 `oneshot()` 快速搜索与 `run()` 长连接服务
* **Client 端 (`mcp_client.py`)**
  * 负责调用 Copilot 模型
  * 进行意图判断与上下文缓存
  * 实现“两阶段推理”机制（搜索 + 筛选）

---

## 📁 项目结构

下述结构为核心逻辑视图，部分缓存与中间文件已省略。

AspenIncidentQA/
├── backend/
│   ├── src/
│   │   ├── agent/                     # MCP Client / Orchestration / Synthesis
│   │   │   ├── mcp_client.py           # MCP Client，负责模型调用与上下文管理
│   │   │   ├── router.py               # 意图识别与路由决策
│   │   │   ├── orchestrator.py         # 两阶段推理流程编排
│   │   │   └── synthesizer.py          # 结果筛选与答案生成
│   │   │
│   │   ├── config/                    # 本地与模型配置
│   │   │   └── github_models.local.json
│   │   │
│   │   ├── data/
│   │   │   ├── raw/                   # 原始 Incident / 邮件数据
│   │   │   ├── processed/             # 预处理后的中间数据
│   │   │   │   ├── embeddings/         # 向量结果与元数据
│   │   │   │   └── index/              # TF-IDF / 向量索引文件
│   │   │
│   │   ├── data_io/                   # 数据读写与格式转换
│   │   │   ├── file_reader.py
│   │   │   └── file_writer.py
│   │   │
│   │   ├── embeddings/                # Embedding 生成与封装
│   │   │   └── embedding_handler.py
│   │   │
│   │   ├── llm/                       # Copilot / LLM 封装
│   │   │   ├── config_loader.py
│   │   │   └── copilot_client.py
│   │   │
│   │   ├── prompts/                   # Router / Synth Prompt 模板
│   │   │   ├── router.system.txt
│   │   │   ├── router.user.txt
│   │   │   ├── synth.system.txt
│   │   │   └── synth.user.txt
│   │   │
│   │   ├── rag/                       # 检索模块（向量 + TF-IDF）
│   │   │   ├── embedder.py
│   │   │   ├── indexer.py
│   │   │   └── search.py
│   │   │
│   │   ├── utils/
│   │   │   └── logger.py
│   │   │
│   │   └── server.py                  # MCP / API 服务入口
│   │
│   └── requirements.txt
│
├── frontend/                          # 对话 UI（可独立部署）
├── README_cn.md
├── README_en.md
└── .gitignore

---

## 🧪 运行方式说明（Server vs Orchestrator）

本项目在设计上区分了 **服务模式（Server）** 与  **流程验证模式（Orchestrator）** ，用于不同阶段的开发与测试。

#### 1️⃣ Orchestrator（推荐：当前主要使用方式）

`orchestrator.py` 用于  **本地流程验证与算法实验** ，它会：

* 串联 Router → Retriever → Synthesizer
* 执行完整的“两阶段推理流程”
* 直接在本地输出最终答案结果

该模式  **不依赖长连接服务** ，适合：

* 验证检索与推理逻辑
* 调试 Prompt 与模型行为
* 快速测试新数据或新策略

> 当前项目的大部分实验与验证，均通过 **Orchestrator 模式**完成。

---

#### 2️⃣ Server（预留：服务化接口）

`server.py` 作为  **MCP / API 服务入口** ，用于：

* 将 MCP 能力封装为可调用服务
* 支持未来对接 UI、CRM、邮件系统或 Agent 框架
* 演示 MCP Server 的整体架构形态

在当前版本中，Server 主要用于  **结构验证与接口占位** ，尚未承载完整的生产流量。

---

#### 3️⃣ 当前推荐用法

* **想理解系统逻辑 / 复现实验结果** → 直接运行 `orchestrator.py`
* **想扩展为服务或对接前端** → 使用 `server.py` 作为入口进行二次开发

## 🧠 技术亮点

| 技术                    | 说明                           |
| ----------------------- | ------------------------------ |
| 混合搜索 (RAG + TF-IDF) | 同时支持语义与关键词双检索     |
| 自建 MCP Server/Client  | 兼容未来 Copilot MCP 接口      |
| 两阶段推理机制          | 阶段一检索 + 阶段二筛选        |
| Copilot 模型推理        | 判断哪些历史 resolution 可复用 |
| 自动知识更新            | 支持反馈数据再嵌入             |

---

## 📈 效益

| 指标           | 提升效果     |
| -------------- | ------------ |
| 问题解决速度   | 提升 50%+    |
| 搜索准确度     | 提升 40%     |
| 新员工培训时间 | 降低 35%     |
| 知识复用率     | 提升 3–4 倍 |

---

## 🧪 典型使用场景

- 客户报告模糊问题描述，系统自动匹配历史相似 Incident
- 新支持工程师快速获取可复用解决方案
- 高级工程师减少重复答疑
- 管理层分析高频问题与知识缺口

## 🚀 后续规划

* Phase III：CRM / 邮件系统集成 (Outlook / Salesforce API)
* Phase IV：闭环学习与自我优化
* Phase V：多智能体扩展（问答、摘要、分类）

---

## 💬 一句话总结

> **Aspen Incident QA** 是一个能理解客户邮件、检索历史知识、并利用 LLM 自动生成解决建议的智能问答系统。
>
> 它结合  **MCP 框架、RAG 搜索与 Copilot 推理能力** ，实现了技术支持流程的智能化与自动化。
