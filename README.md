# Generic data agent in Looker → Gemini Enterprise 🔭🚀

**A conversational data agent, created as native content inside Looker (Google Cloud core) and publishable to Gemini Enterprise — deployed entirely from Google Colab using only the Looker API.**

_Author: [joseimj](https://github.com/joseimj)_

The agent connects to one or more Explores (up to 5) from your LookML model, appears under **Conversational Analytics → Agents tab** in Looker and, once published, is also available in your **Gemini Enterprise** instance for any authorized user to chat with:

```
"How many orders were placed last quarter and what was the average order value?"
"Which products had the highest month-over-month sales growth?"
"How many new customers came in by acquisition channel?"
```

> This repository is a **generic example**. The three included Explores (`ecommerce_demo::orders`, `::customers`, `::products`) are **fictional**: replace them with your own in the `EXPLORES` list.

It's the evolution of the [joseimj/bafar](https://github.com/joseimj/bafar) pattern (which deployed an HR agent over SAP): a single script, configuration up top, idempotent execution and a *preflight* check before deploying — but now with **no domain-specific logic** and with the added **Gemini Enterprise publishing** step.

---

## Architecture

```
Google Colab ───────────────► Looker (Google Cloud core) ──────► Gemini Enterprise
(this script)                  Looker API · ConversationalAnalytics       (GE instance)
     │                         endpoints                                        ▲
     │  • create/update the     POST /agents · /conversations · /chat           │
     │    (native) agent               │                                        │
     │  • verify the Explores          ▼                                  publish from the
     │  • print the GE          LookML Explores (semantic layer)          Looker UI
     │    publish guide                │                                  (Publish settings →
     │                                 ▼                                   Gemini Enterprise)
     └── (optional) test        BigQuery / your warehouse
         chat in Colab
```

Design decisions:

1. **Looker API only to create the agent.** It does not use GCP's Conversational Analytics API (`geminidataanalytics`) or IAM roles to *create* the agent. The only authentication for that part is a Looker URL + API Client ID + Secret, entered at runtime.
2. **The agent is Looker content.** It's managed like any other content and its governance is Looker's (per-model permissions, content access).
3. **Every query goes through the semantic layer.** The agent translates natural language into Explore queries; it never touches the database directly.
4. **Publishing to GE is a UI step (preview).** See the note below.

### ⚠️ About publishing to Gemini Enterprise (preview)

The **Looker ⇄ Gemini Enterprise integration is in preview with limited support**. As of today, **the Looker API/SDK does not expose a method to publish the agent to GE**: publishing is done from the Looker UI (Edit agent → *Publish settings* → enable **Gemini Enterprise** → *Update*).

That's why this script **automates everything up to creating/updating the agent** and then prints the exact steps for the final action and its IAM prerequisites. As soon as the SDK exposes a publish method, it can be added in `ge_publish_guide` / a new `publish_to_ge` function.

> Need **fully automated/programmatic** publishing? There's a heavier alternative: build an agent with **ADK + MCP Toolbox** and deploy it on **Vertex AI Agent Engine**, registering it in GE. That does require a GCP project, IAM and OAuth. This repo favors the simplicity of the "Looker API only + one UI step" flow.

---

## What the script does

| Step | Action |
| ---- | ------ |
| 1 | Manually prompts for the Looker URL, API Client ID and Secret (not stored) |
| 2 | **Preflight**: version (agents >= 25.18; publish to GE >= 26.8), agent endpoints and API-user permissions (`gemini_in_looker`, `save_agents`, `publish_agent_externally`) |
| 3 | Verifies that each configured Explore exists and returns visible fields |
| 4 | Creates or updates the agent — idempotent: looks it up by name before creating |
| 5 | Prints the guide to publish it to Gemini Enterprise (UI + IAM) |
| 6 | (Optional) Opens a test chat in Colab using the same endpoint the UI uses |

---

## Prerequisites

### To CREATE the agent (Looker side)

| You need | Where to get it |
| -------- | --------------- |
| Looker (Google Cloud core) version **25.18+** | Verifiable with `--preflight` |
| **Gemini in Looker** enabled | Admin with `roles/looker.admin` |
| Looker API keys (Client ID + Secret) | Looker → Admin → Users → your user → API Keys |
| Model and Explore name(s) | Visible in the URL: `/explore/<model>/<explore>` |

### To PUBLISH to Gemini Enterprise (preview)

| You need | Where to get it |
| -------- | --------------- |
| Looker **26.8+** | Verifiable with `--preflight` |
| **Publish to Gemini Enterprise** setting on (with GE GCP project number, region and instance ID) | Admin → Platform → Gemini in Looker |
| **Gemini Enterprise Admin** IAM role for the Looker service account | Google Cloud console, on the project hosting the GE engine |
| **`publish_agent_externally`** permission | Granted to anyone with `save_agents` when the setting is on |

### Looker permissions

| Who | Required permissions |
| --- | -------------------- |
| API user running the script | `access_data` and `explore` on each model; `gemini_in_looker`; `save_agents` (**Conversational Analytics Agent Manager** role); `publish_agent_externally` to publish |
| End users in Looker | `access_data` + `gemini_in_looker` (**Conversational Analytics User** role); **View** access to the agent |
| End users in Gemini Enterprise | **Gemini Enterprise User** IAM role + access to the specific agent in the GE console |

---

## Usage in Colab

```python
# Cell 1 — dependencies
!pip install -q --upgrade looker-sdk pandas

# Cell 2 — upload looker_ge_agent.py (files panel → upload) and edit the
#          CONFIGURATION block: EXPLORES, AGENT_NAME, AGENT_DESCRIPTION,
#          INSTRUCTIONS and, for the GE guide, GE_PROJECT_NUMBER / GE_REGION /
#          GE_INSTANCE_ID.

# Cell 3 — full run (preflight → verify explores → create → GE guide → chat)
%run looker_ge_agent.py
```

When it finishes, the agent is visible in **Looker → Conversational Analytics → Agents**. Follow the printed guide to publish it to **Gemini Enterprise**.

### Flags

| Flag | Effect |
| ---- | ------ |
| `--dry-run` | Build & print the agent definition **without** connecting to Looker (great for trying the example) |
| `--publish-guide` | Print only the Gemini Enterprise publish guide |
| `--preflight` | Run checks only (requires credentials) |
| `--no-chat` | Create/update the agent without opening the test chat |
| `--list` / `--show` / `--delete` | Agent management, all via API |

Tip: run `--dry-run` first (no credentials needed) to review the definition, then `--preflight` to validate permissions with your admin.

---

## Configuration

Everything editable lives at the top of `looker_ge_agent.py`:

- **`EXPLORES`** — list of 1 to 5 dicts `{"model": ..., "explore": ...}`. They can belong to different models.
- **`AGENT_NAME` / `AGENT_DESCRIPTION` / `AGENT_CATEGORY`** — agent identity.
- **`INSTRUCTIONS`** — the agent's "brain" (role, tone, rules, examples). Generic by default; tailor it to your domain.
- **`CODE_INTERPRETER`** — enables Advanced Analytics (if the instance allows it; if rejected, the script retries without it).
- **`GE_PROJECT_NUMBER` / `GE_REGION` / `GE_INSTANCE_ID`** — target GE instance details (used in the publish guide).
- **`LOOKER_BASE_URL`** — optional; if left empty, it's prompted at runtime.

---

## Troubleshooting

| Symptom | Most likely cause |
| ------- | ----------------- |
| `404` on the agent endpoints | Instance older than 25.18, or Gemini in Looker disabled |
| `403` when creating the agent | API user lacks `save_agents` / Agent Manager role |
| Chat fails with a data-access error | Missing `access_data`/`explore` or `gemini_in_looker` on the model |
| An Explore "returns no fields" | Wrong model/explore name, or not visible to the API user (expected if using the sample fictional values) |
| No "Publish settings" / GE option missing | Instance < 26.8, or "Publish to Gemini Enterprise" not enabled by the admin |
| `Failed to allocate quota for agent creation` when publishing | No GE licenses available for the Looker service account; a Gemini Enterprise Admin must assign/reassign one |
| SDK has no `create_agent` | Old `looker-sdk`: upgrade and restart the Colab session |

---

## Security

- Looker credentials are requested with `getpass`: they don't end up in the file, the Colab history or any resource.
- For production, use a dedicated Looker API user with a role limited to the needed models (querying + Gemini + agents + publishing).
- The Looker ConversationalAnalytics endpoints and the GE integration are recent and in preview: pin the `looker-sdk` version once you have a working combination.

---

## Repository structure

```
.
├── looker_ge_agent.py   # Single script: preflight + verification + agent + GE guide + chat
└── README.md
```

---

## References — official documentation

All technical decisions in this project are grounded in Google Cloud's official documentation. The Looker ⇄ Gemini Enterprise integration is in preview, so verify the latest details against these pages.

**Creating and publishing the agent**

- [Create and manage Explore data agents](https://docs.cloud.google.com/looker/docs/conversational-analytics-looker-data-agents) — the publish-to-Gemini-Enterprise flow, its prerequisites (Publish setting, `publish_agent_externally` permission, **Gemini Enterprise Admin** IAM role, license allocation), the UI steps (*Publish settings → Gemini Enterprise → Update*), and the preview/feedback note.
- [Conversational Analytics in Looker overview](https://docs.cloud.google.com/looker/docs/conversational-analytics-overview) — what a data agent is, the **up-to-5 Explores** limit, and publishing agents to other apps such as Gemini Enterprise.

**Admin settings and permissions**

- [Admin settings – Gemini in Looker](https://docs.cloud.google.com/looker/docs/admin-panel-platform-gil) — the **Publish to Gemini Enterprise** setting (with the GE GCP project number, region and instance ID), plus the *Conversational Analytics Agent Manager* / *Conversational Analytics User* roles.
- [Gemini in Looker overview](https://docs.cloud.google.com/looker/docs/gemini-overview-looker) — the permission model (`access_data`, `gemini_in_looker`, etc.) and feature availability.

**Versions and release history**

- [Looker release notes](https://docs.cloud.google.com/looker/docs/release-notes) — publishing CA agents to Gemini Enterprise (available in **Looker 26.8**; Explore-agent publishing in the **26.10** rollout) and the re-publish behavior when the connected GE instance changes.

**Looker API and SDK (used by the script)**

- [Looker API reference](https://docs.cloud.google.com/looker/docs/reference/available-apis) — the Looker API surface, including the ConversationalAnalytics endpoints (agents, conversations, chat).
- [Looker SDK for Python (`looker-sdk`)](https://pypi.org/project/looker-sdk/) — the official client used here; source at [looker-open-source/sdk-codegen](https://github.com/looker-open-source/sdk-codegen).

**The fully-automated alternative (CA API / ADK / MCP)**

- [Conversational Analytics API – Integration patterns](https://docs.cloud.google.com/gemini/data-agents/conversational-analytics-api/integration-patterns) — using the `geminidataanalytics` API to share a single data agent across surfaces, including Gemini Enterprise.
- [Gemini Enterprise Agent Platform – Deploy an agent](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/deploy-an-agent) — Agent Engine deployment options for the ADK path.
- [Use the MCP Toolbox for Databases (Looker)](https://docs.cloud.google.com/looker/docs/connect-ide-to-looker-using-mcp-toolbox) — connecting Looker's semantic layer over MCP.
- Google Cloud Blog (official, non-docs): [Connecting Looker to Gemini Enterprise with MCP Toolbox and ADK](https://cloud.google.com/blog/products/business-intelligence/connecting-looker-to-gemini-enterprise-with-mcp-toolbox-and-adk) — end-to-end walkthrough of the ADK + Agent Engine approach.

> Documentation accessed June 2026. Pages and preview features change frequently; treat the dates and version numbers above as a snapshot.

---

## Author

Created and maintained by **[joseimj](https://github.com/joseimj)**.

Built on the deployment pattern of [joseimj/bafar](https://github.com/joseimj/bafar).
