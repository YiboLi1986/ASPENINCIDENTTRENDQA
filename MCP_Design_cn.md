# MCP 设计总览（本项目落地）

* **目标** ：把“检索与知识上下文（RAG + TF-IDF + 映射关系）”抽象成  **MCP Server 的可调用能力** ；把“用户对话、意图判断、答案合成”放在 **MCP Client + Copilot 模型** 侧。
* **好处** ：

1. 数据与模型解耦（Server 管数据与检索；Client 管推理与对话）；
2. 统一 RPC 协议，方便替换前端/接入其他代理；
3. 后续可把 MCP Server 部署到更靠近数据源的一侧（安全合规）。

---

# Server 侧设计（`src/agent/router.py` + `orchestrator.py` + `rag/*`）

## 1) 启动与预构建

* **预加载资源** （进程启动时一次性完成）：
* 向量索引：`embeddings/embeddings.npy`、`embeddings/vectorizer.pkl`、`data/processed/embedder_meta.json`
* 词袋索引：`data/index/tfidf_csr.npz`、`data/index/mapping.csv`
* 结构化数据：`data/incidents.csv`（含 `incident_id, desc, resolution, meta...`）
* **目的** ：Server 就绪后，检索调用为 **纯内存/内存映射** 查询，毫秒级返回 Top-K。

## 2) 对外能力（MCP “工具/路由”）

Server 暴露以下  **可调用路由** （可以是 HTTP/IPC/本地方法；项目里用轻量 server 封装在 `utils/server.py`，由 `router.py` 统一转发）：

1. `oneshot.search`（Phase-I 检索）
   * **输入** ：`{ query: str, top_k: int=8, filters?: {...} }`
   * **动作** ：并发执行
   * `rag/search.py`：embedding 相似度 → Top-K
   * `rag/search.py`：TF-IDF 关键词 → Top-K
   * `rule/map`：将 **desc → resolution 片段** 映射出来
   * **输出** ：

   <pre class="overflow-visible!" data-start="1167" data-end="1486"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-json"><span><span>{</span><span>
       </span><span>"results"</span><span>:</span><span></span><span>[</span><span>
         </span><span>{</span><span>
           </span><span>"incident_id"</span><span>:</span><span></span><span>"INC123"</span><span>,</span><span>
           </span><span>"desc"</span><span>:</span><span></span><span>"…"</span><span>,</span><span>
           </span><span>"resolution"</span><span>:</span><span></span><span>"…"</span><span>,</span><span>
           </span><span>"score_sem"</span><span>:</span><span></span><span>0.83</span><span>,</span><span>
           </span><span>"score_kw"</span><span>:</span><span></span><span>0.71</span><span>,</span><span>
           </span><span>"source"</span><span>:</span><span></span><span>"embedding|tfidf"</span><span>,</span><span>
           </span><span>"meta"</span><span>:</span><span></span><span>{</span><span>"date"</span><span>:</span><span>"…"</span><span>,</span><span>"product"</span><span>:</span><span>"…"</span><span>}</span><span>
         </span><span>}</span><span>,</span><span> …
       </span><span>]</span><span>
     </span><span>}</span><span>
     </span></span></code></div></div></pre>
2. `batch.search`（批量检索）
   * **输入** ：`{ queries: string[], top_k?: number }`
   * **用途** ：离线评估、回放、训练数据构建。
3. `health.ping`
   * 返回索引版本、可用性、载入时间、内存占用等。

> 说明： **Server 不做“答案生成”** ，只做召回/重排与“desc→resolution”映射拼装，保持职责单一。

## 3) 排序与去重（可选）

* 多通道召回后在 Server 端做  **轻量融合打分** ：
  * `score = w1*score_sem + w2*score_kw + w3*recencyBoost + w4*productMatch`
* `incident_id` 级别去重；保留  **不同片段的多样性** （如果一个 incident 有多段高分 resolution）。

## 4) 接口幂等与观测性

* 请求体中可带 `request_id`；Server 返回时原样回传，便于链路追踪。
* 每次检索记录 **query、Top-K、耗时、索引版本** 到 `utils/logger.py`。
* 在 `health.ping` 暴露基础指标（QPS、P95、命中率等），后续接入 Prometheus 也方便。

---

# Client 侧设计（`src/agent/mcp_client.py` + `orchestrator.py` + `synthesizer.py`）

## 1) 双阶段编排（核心）

**Phase-I：意图识别 + 检索**

* **意图识别** （Copilot Model API）：
* Prompt（`prompts/router.system.txt` + `router.user.txt`）：判断是否需要检索、需要哪些过滤（产品/版本/时间窗）、Top-K 建议值等。
* 输出一个  **路由计划** ：
  <pre class="overflow-visible!" data-start="2354" data-end="2461"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-json"><span><span>{</span><span></span><span>"need_search"</span><span>:</span><span></span><span>true</span><span></span><span>,</span><span></span><span>"top_k"</span><span>:</span><span></span><span>8</span><span>,</span><span></span><span>"filters"</span><span>:</span><span></span><span>{</span><span>"product"</span><span>:</span><span>"HYSYS"</span><span>}</span><span>,</span><span></span><span>"next"</span><span>:</span><span></span><span>"phase_II"</span><span></span><span>}</span><span>
  </span></span></code></div></div></pre>
* **触发检索** （MCP 调用 `oneshot.search`）：
* 将路由计划参数 + 原始 query 传给 Server，拿回 Top-K 候选集（desc+resolution）。

**Phase-II：适用性判断 + 合成回答**

* 将 **Top-K 候选集** 作为 **检索上下文** 传给 Copilot：
  * Prompt（`prompts/synth.system.txt` + `synth.user.txt`）：要求模型
    1. 说明哪些候选与本问题  **强相关/部分相关/不相关** （可打分）
    2. 直接给出  **可操作的回答步骤** ，并保留引用（incident_id）
    3. 标注不确定性与“需要用户补充的关键信息”
* `synthesizer.py` 接收模型输出，整理为前端可显示的结构化响应（含 “使用了哪些 incident 的 resolution”）。

## 2) Client 调用形态

* **`oneshot()`** ：单次问答（用于无对话记忆的 API/批处理场景）
* **`chat()`** ：多轮对话（`conversation_id` 维度缓存历史 Q/A、已使用的 incident 列表、用户偏好）
* **流式输出** ：若 Copilot API 支持流式，前端逐 token 展示，体验更好

## 3) 失败与降级

* Server 不可用 → Client 退化为  **纯关键词** （临时）或只做“澄清提问”；
* Copilot 限流/429 →  **指数退避 + 结果缓存** ；
* 上下文超长 → 只传 **Top-M** 条候选的  **缩略摘要** （desc / resolution 先在 Client 端裁剪）。

## 4) 安全与边界

* Server 不返回原始客户敏感字段（如个人信息/邮箱）；
* Client 对外只展示  **必要片段** ，并保留“查看原文”权限控制位；
* `config/github_models.local.json` 控制不同环境（dev/stage/prod）的基座模型与 URL。

---

# 时序图（简化）

<pre class="overflow-visible!" data-start="3414" data-end="3927"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre!"><span><span>User → </span><span>Client</span><span>.</span><span>chat</span><span>(): </span><span>"Why HYSYS crashes when importing stream data?"</span><span>
</span><span>Client</span><span> → </span><span>Copilot</span><span>(router): classify intent → {need_search:</span><span>true</span><span>, top_k:</span><span>8</span><span>, filters:{product:HYSYS}}
</span><span>Client</span><span> → </span><span>Server</span><span>.oneshot.</span><span>search</span><span>(query, top_k, filters)
</span><span>Server</span><span> → RAG & TF-IDF → </span><span>return</span><span> Top-</span><span>K</span><span> (desc+resolution snippets)
</span><span>Client</span><span> → </span><span>Copilot</span><span>(synth): </span><span>"here are Top-K; which fixes apply and why? produce final answer"</span><span>
Copilot → </span><span>Client</span><span>: structured answer + </span><span>citations</span><span>(incident_id) + unsure_points
</span><span>Client</span><span> → Frontend: stream response + allow follow-up
</span></span></code></div></div></pre>

---

# 关键数据契约（建议）

**检索请求**

<pre class="overflow-visible!" data-start="3957" data-end="4085"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-json"><span><span>{</span><span>
  </span><span>"request_id"</span><span>:</span><span></span><span>"uuid"</span><span>,</span><span>
  </span><span>"query"</span><span>:</span><span></span><span>"string"</span><span>,</span><span>
  </span><span>"top_k"</span><span>:</span><span></span><span>8</span><span>,</span><span>
  </span><span>"filters"</span><span>:</span><span></span><span>{</span><span>"product"</span><span>:</span><span>"HYSYS"</span><span>,</span><span>"since"</span><span>:</span><span>"2024-01-01"</span><span>}</span><span>
</span><span>}</span><span>
</span></span></code></div></div></pre>

**检索响应**

<pre class="overflow-visible!" data-start="4096" data-end="4512"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-json"><span><span>{</span><span>
  </span><span>"request_id"</span><span>:</span><span></span><span>"uuid"</span><span>,</span><span>
  </span><span>"results"</span><span>:</span><span></span><span>[</span><span>
    </span><span>{</span><span>
      </span><span>"incident_id"</span><span>:</span><span></span><span>"INC-2024-00123"</span><span>,</span><span>
      </span><span>"desc"</span><span>:</span><span></span><span>"short snippet ..."</span><span>,</span><span>
      </span><span>"resolution"</span><span>:</span><span></span><span>"short snippet ..."</span><span>,</span><span>
      </span><span>"score_sem"</span><span>:</span><span></span><span>0.83</span><span>,</span><span>
      </span><span>"score_kw"</span><span>:</span><span></span><span>0.71</span><span>,</span><span>
      </span><span>"source"</span><span>:</span><span></span><span>"embedding|tfidf"</span><span>,</span><span>
      </span><span>"meta"</span><span>:</span><span></span><span>{</span><span>"date"</span><span>:</span><span>"2024-10-12"</span><span>,</span><span>"product"</span><span>:</span><span>"HYSYS"</span><span>,</span><span>"ver"</span><span>:</span><span>"v12"</span><span>}</span><span>
    </span><span>}</span><span>
  </span><span>]</span><span>,</span><span>
  </span><span>"index_meta"</span><span>:</span><span></span><span>{</span><span>"embed_model"</span><span>:</span><span>"nomic-embed-text"</span><span>,</span><span>"tfidf_version"</span><span>:</span><span>"2025-10-20"</span><span>}</span><span>
</span><span>}</span><span>
</span></span></code></div></div></pre>

**合成响应（前端消费）**

<pre class="overflow-visible!" data-start="4529" data-end="4857"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-json"><span><span>{</span><span>
  </span><span>"answer"</span><span>:</span><span></span><span>"final natural-language response ..."</span><span>,</span><span>
  </span><span>"applied_incidents"</span><span>:</span><span></span><span>[</span><span>
    </span><span>{</span><span>"incident_id"</span><span>:</span><span>"INC-2024-00123"</span><span>,</span><span>"why"</span><span>:</span><span>"root-cause and steps match"</span><span>}</span><span>,</span><span>
    </span><span>{</span><span>"incident_id"</span><span>:</span><span>"INC-2024-00456"</span><span>,</span><span>"why"</span><span>:</span><span>"partial overlap; step 2 relevant"</span><span>}</span><span>
  </span><span>]</span><span>,</span><span>
  </span><span>"followups"</span><span>:</span><span></span><span>[</span><span>"Please confirm the exact version ..."</span><span>,</span><span></span><span>"Attach crash logs ..."</span><span>]</span><span>
</span><span>}</span><span>
</span></span></code></div></div></pre>

---

# 与目录对应的落地映射

* `agent/mcp_client.py`：实现 `oneshot()` / `chat()`；封装 Copilot API；意图路由；失败与降级策略
* `agent/orchestrator.py`：Phase-I/II 的编排器（聚合搜索 + 合成）
* `agent/router.py`：Server 端统一入口（把 HTTP 或本地调用转到 `rag/search.py`）
* `agent/synthesizer.py`：对 Copilot 输出做结构化解析与格式化
* `rag/embedder.py` `rag/indexer.py` `rag/search.py`：嵌入生成、索引与检索
* `prompts/router.*` / `prompts/synth.*`：意图/合成的系统 + 用户提示词
* `utils/server.py`：Server 适配层（HTTP/本地调用），`utils/logger.py`：观测性

---

# 极简伪代码（便于你在面试时讲）

<pre class="overflow-visible!" data-start="5345" data-end="5654"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-python"><span><span># client (Phase-I)</span><span>
plan = copilot_router.classify(query)  </span><span># need_search?, top_k, filters</span><span>
</span><span>if</span><span> plan.need_search:
    hits = mcp_server.oneshot_search(query, plan.top_k, plan.filters)
</span><span>else</span><span>:
    hits = []

</span><span># client (Phase-II)</span><span>
final = copilot_synth.summarize(query=query, candidates=hits)
</span><span>return</span><span> final
</span></span></code></div></div></pre>

<pre class="overflow-visible!" data-start="5656" data-end="5898"><div class="contain-inline-size rounded-2xl relative bg-token-sidebar-surface-primary"><div class="sticky top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-python"><span><span># server</span><span>
</span><span>def</span><span></span><span>oneshot_search</span><span>(</span><span>query, top_k=8</span><span>, filters=</span><span>None</span><span>):
    sem = rag.search_semantic(query, top_k)
    kw  = rag.search_tfidf(query, top_k)
    fused = fuse_and_dedup(sem, kw)
    </span><span>return</span><span> map_desc_to_resolution(fused)[:top_k]
</span></span></code></div></div></pre>

---

# 你可以立刻落地/加固的点

* 在 `router.system.txt` 明确输出 JSON 计划（避免模型自由发挥）
* 在 `synth.system.txt` 固化“ **必须标注 applied_incidents** ”与“ **给出不确定点** ”
* 给 `server.oneshot.search` 增加 `product/version` 过滤，提高命中质量
* 为响应加  **缓存** （`(query_hash, top_k) → hits`），降低 429 风险
* 给前端加 **“显示引用 incident”** 的折叠卡片，便于审计与复现
