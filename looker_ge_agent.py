# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════════════════
 looker_ge_agent.py — GENERIC data agent in Looker, publishable to Gemini
 Enterprise (GE)
═══════════════════════════════════════════════════════════════════════════════

 Author: joseimj — https://github.com/joseimj
 Based on the deployment pattern of https://github.com/joseimj/bafar

Creates (or updates) a Conversational Analytics agent INSIDE Looker, as native
content of the instance, using only the Looker API. The agent connects to one
or more Explores (up to 5) from your LookML model and, once created, is PUBLISHED
to Gemini Enterprise so any GE user can chat with it.

  ✔ The agent appears in Looker → Conversational Analytics → Agents tab.
  ✔ Once published, it also shows up in your Gemini Enterprise instance.
  ✔ Creating it only needs a Looker URL + API Client ID + Secret.

  ⚠️ IMPORTANT — about publishing to Gemini Enterprise:
     The Looker ⇄ Gemini Enterprise integration is IN PREVIEW. As of today, the
     Looker API/SDK (looker-sdk) does NOT expose a method to publish the agent
     to GE: publishing is a Looker UI action (Edit agent → Publish settings →
     enable "Gemini Enterprise" → Update). For that reason this script automates
     everything UP TO creating the agent and then prints the exact steps for the
     final action (publish) and its IAM prerequisites. As soon as the SDK exposes
     the method, it can be added here in one place.

────────────────────────────────────────────────────────────────────────────────
 WHAT IT DOES, STEP BY STEP
────────────────────────────────────────────────────────────────────────────────
  1. Prompts MANUALLY for the Looker URL, API Client ID and Secret (getpass: not
     stored in the notebook or in the file).
  2. Preflight: instance version (agents >= 25.18; publish to GE >= 26.8),
     agent endpoints availability and API-user permissions (gemini_in_looker,
     save_agents, publish_agent_externally).
  3. Verifies that each configured Explore exists and is accessible.
  4. Creates or updates the agent (idempotent, looked up by name).
  5. Prints the guide to publish it to Gemini Enterprise (UI + IAM).
  6. (Optional) Opens a test chat inside Colab using the same chat endpoint the
     Looker UI uses.

────────────────────────────────────────────────────────────────────────────────
 USAGE IN COLAB
────────────────────────────────────────────────────────────────────────────────
  # Cell 1:
  !pip install -q --upgrade looker-sdk pandas
  # Cell 2: upload this file and edit the CONFIGURATION block (EXPLORES,
  #         agent name/description, instructions, GE details).
  # Cell 3:
  %run looker_ge_agent.py

  Optional flags:
    %run looker_ge_agent.py --dry-run        # build & print the agent, no API call
    %run looker_ge_agent.py --preflight      # checks only (needs credentials)
    %run looker_ge_agent.py --publish-guide  # print only the GE publish guide
    %run looker_ge_agent.py --no-chat        # create/update without the test chat
    %run looker_ge_agent.py --list | --show | --delete

────────────────────────────────────────────────────────────────────────────────
 PREREQUISITES
────────────────────────────────────────────────────────────────────────────────
  To CREATE the agent (Looker side):
    • Looker (Google Cloud core) version 25.18+ (agents + API endpoints).
    • Gemini in Looker enabled (one-time admin action).
    • Looker API keys whose user has, on each model used:
        - querying:  access_data, explore
        - Gemini:    gemini_in_looker
        - agents:    save_agents  (or the "Conversational Analytics Agent Manager" role)

  To PUBLISH to Gemini Enterprise (preview):
    • Looker 26.8+.
    • Admin → Gemini in Looker → enable "Publish to Gemini Enterprise" and provide
      the target GE instance's GCP project number, region and instance ID.
    • Grant the Looker service account the "Gemini Enterprise Admin" IAM role on
      the GCP project that hosts the GE engine.
    • The user must have the 'publish_agent_externally' permission (granted
      automatically to anyone with 'save_agents' when the setting is on).
═══════════════════════════════════════════════════════════════════════════════
"""

import argparse
import os
import sys
from getpass import getpass

# ╔═════════════════════════════════════════════════════════════════════════╗
# ║                            CONFIGURATION                                 ║
# ╚═════════════════════════════════════════════════════════════════════════╝

# --- Explores that feed the agent (1 to 5) -----------------------------------
# ⚠️ FICTIONAL: these are just an example. Replace them with your real
#    models/explores. The model and explore names appear in an explore's URL:
#    /explore/<model>/<explore>
EXPLORES = [
    {"model": "ecommerce_demo", "explore": "orders"},      # fictional
    {"model": "ecommerce_demo", "explore": "customers"},   # fictional
    {"model": "ecommerce_demo", "explore": "products"},    # fictional
]

# --- Agent identity ----------------------------------------------------------
AGENT_NAME        = "Data agent (demo)"
AGENT_DESCRIPTION = ("Sample analytics assistant over e-commerce data "
                     "(orders, customers and products).")
AGENT_CATEGORY    = None   # optional: groups agents in the UI; None = no category

# Advanced Analytics (Code Interpreter): translates questions into Python for
# advanced analysis. Requires the instance to allow it; if it's rejected, the
# script automatically retries without it.
CODE_INTERPRETER  = True

# --- Looker connection -------------------------------------------------------
# The URL can be pre-filled here to skip that prompt; the Client ID and Secret
# are ALWAYS requested at runtime (never stored).
LOOKER_BASE_URL = ""        # e.g. "https://yourcompany.cloud.looker.com"

# --- Gemini Enterprise target (preview) --------------------------------------
# These values are actually configured in Looker's admin panel (Gemini in Looker
# → Publish to Gemini Enterprise). Here they are used only to show them in the
# publish guide and to make sure you have them at hand.
GE_PROJECT_NUMBER = ""      # GCP project number hosting the GE instance
GE_REGION         = ""      # GE instance region ("Location" field on GE Apps)
GE_INSTANCE_ID    = ""      # Gemini Enterprise instance/app ID

# --- Agent instructions (generic and editable) -------------------------------
INSTRUCTIONS = """\
ROLE AND TONE
You are an analytics assistant connected to Looker's semantic layer. Always
reply in English, clearly and concisely. Present lists and comparisons as a
table when it adds clarity.

HOW YOU WORK
- Translate each natural-language question into queries over the connected
  Explores; never query the database directly and never invent fields.
- Use only the dimensions and measures defined in LookML as the single source
  of truth. If a business term (e.g. "revenue", "average order value", "churn")
  is defined in the model, honor it exactly.
- If a question spans several Explores, pick the most suitable one or combine
  the results, and state which data you are using.

BEHAVIOR RULES
- If a question is ambiguous (no period, no segment), ask a brief clarifying
  question or assume a reasonable default and say so in your answer.
- Never invent figures: answer only with query results. If there isn't enough
  data or the field doesn't exist, say so clearly.
- Do not give personalized legal, tax or financial advice.
- Stay within the connected Explores; if a question is out of scope, redirect
  politely.

EXAMPLE QUESTIONS
- How many orders were placed last quarter and what was the average order value?
- Which products had the highest month-over-month sales growth?
- How many new customers came in by acquisition channel?
"""


# ╔═════════════════════════════════════════════════════════════════════════╗
# ║                  No need to edit below this line                        ║
# ╚═════════════════════════════════════════════════════════════════════════╝

OK, WARN, FAIL = "✅", "⚠️ ", "⛔"
MIN_VERSION_AGENTS    = (25, 18)   # agents as content + API endpoints
MIN_VERSION_GE_PUBLISH = (26, 8)   # publishing CA agents to Gemini Enterprise
MAX_EXPLORES = 5                   # max Explores per CA agent

# Default fictional values (used to warn if the user hasn't changed them yet).
_DEMO_EXPLORES = [
    {"model": "ecommerce_demo", "explore": "orders"},
    {"model": "ecommerce_demo", "explore": "customers"},
    {"model": "ecommerce_demo", "explore": "products"},
]


def _validate_config() -> None:
    if not EXPLORES:
        sys.exit("⛔ Configure at least one Explore in the EXPLORES list.")
    if len(EXPLORES) > MAX_EXPLORES:
        sys.exit(f"⛔ An agent supports at most {MAX_EXPLORES} Explores; "
                 f"you have {len(EXPLORES)}.")
    for i, e in enumerate(EXPLORES, 1):
        if not e.get("model") or not e.get("explore"):
            sys.exit(f"⛔ Explore #{i} must have both 'model' and 'explore'.")
    if EXPLORES == _DEMO_EXPLORES:
        print(f"{WARN} You are using the FICTIONAL sample Explores "
              "(ecommerce_demo::orders/customers/products). Replace them with your "
              "own in the EXPLORES list before a real deployment.\n")


def _prompt_looker_credentials() -> tuple:
    """MANUAL entry of URL + API key + secret. Not stored on disk."""
    print("\n🔐 Looker credentials (not stored; kept in memory only):")
    url = LOOKER_BASE_URL.strip() or input("   Instance URL (https://...): ").strip()
    if not url.startswith("https://"):
        sys.exit("⛔ The Looker URL must start with https://")
    url = url.rstrip("/")
    client_id = getpass("   API Client ID: ").strip()
    client_secret = getpass("   API Client Secret: ").strip()
    if not client_id or not client_secret:
        sys.exit("⛔ Client ID and Secret are required.")
    return url, client_id, client_secret


def _init_looker_sdk(url: str, client_id: str, client_secret: str):
    os.environ["LOOKERSDK_BASE_URL"] = url
    os.environ["LOOKERSDK_CLIENT_ID"] = client_id
    os.environ["LOOKERSDK_CLIENT_SECRET"] = client_secret
    os.environ["LOOKERSDK_VERIFY_SSL"] = "true"
    try:
        import looker_sdk
    except ImportError:
        sys.exit("\n⛔ Missing the 'looker-sdk' package. Run in a cell:\n"
                 "      !pip install -q --upgrade looker-sdk pandas\n"
                 "   and run this script again.")
    sdk = looker_sdk.init40()
    me = sdk.me()
    print(f"✅ Connected to Looker as: {me.display_name or me.email}")
    return sdk


def _fmt_version(v: tuple) -> str:
    return ".".join(map(str, v))


# ───────────────────────────── PREFLIGHT ───────────────────────────────────

def preflight(sdk) -> None:
    """Checks version, agent endpoints and API-user permissions. Fails fast on
    blockers; ⚠️ items are warnings."""
    print("\n" + "═" * 70)
    print("🛫 PREFLIGHT — pre-deployment checks (100% Looker side)")
    print("═" * 70)
    report = []
    blocking = False

    # 1) Instance version
    try:
        version_txt = (sdk.versions().looker_release_version or "").strip()
        parts = tuple(int(p) for p in version_txt.split(".")[:2] if p.isdigit())
        if parts and parts >= MIN_VERSION_AGENTS:
            report.append((OK, f"Looker version {version_txt} "
                           f"(>= {_fmt_version(MIN_VERSION_AGENTS)} for agents)."))
        elif parts:
            report.append((FAIL, f"Looker {version_txt}: agents and their endpoints "
                           f"require {_fmt_version(MIN_VERSION_AGENTS)} or higher."))
            blocking = True
        else:
            report.append((WARN, f"Could not parse the version: '{version_txt}'."))
        # Sub-check: does the version allow publishing to GE?
        if parts:
            if parts >= MIN_VERSION_GE_PUBLISH:
                report.append((OK, f"Version supports publishing agents to Gemini "
                               f"Enterprise (>= {_fmt_version(MIN_VERSION_GE_PUBLISH)})."))
            else:
                report.append((WARN, f"Publishing to Gemini Enterprise requires Looker "
                               f"{_fmt_version(MIN_VERSION_GE_PUBLISH)}+. You can create the "
                               "agent, but not publish it until you upgrade."))
    except Exception as exc:
        report.append((WARN, f"Could not read the Looker version: {exc}"))

    # 2) Agent endpoints availability
    if hasattr(sdk, "create_agent") and hasattr(sdk, "search_agents"):
        try:
            sdk.search_agents(limit=1)
            report.append((OK, "ConversationalAnalytics (agents) endpoints are live."))
        except Exception as exc:
            msg = str(exc)
            if "404" in msg or "Not found" in msg:
                report.append((FAIL, "The instance does not expose the agent endpoints "
                               "(old version or Gemini in Looker disabled?)."))
                blocking = True
            elif "403" in msg or "permission" in msg.lower():
                report.append((FAIL, "The API user can't use the agent endpoints: "
                               "missing 'save_agents' or the 'Agent Manager' role."))
                blocking = True
            else:
                report.append((WARN, f"search_agents responded: {msg[:120]}"))
    else:
        report.append((FAIL, "Your looker-sdk lacks create_agent/search_agents. "
                       "Run: !pip install -q --upgrade looker-sdk and restart."))
        blocking = True

    # 3) API-user permissions
    try:
        me = sdk.me()
        permissions = set()
        for role_id in (me.role_ids or []):
            try:
                role = sdk.role(role_id=str(role_id))
                permissions.update((role.permission_set.permissions or []))
            except Exception:
                pass
        if permissions:
            checks = [
                ("gemini_in_looker", "Permission 'gemini_in_looker'", True),
                ("save_agents", "Permission 'save_agents'", True),
                ("publish_agent_externally", "Permission 'publish_agent_externally' (publish to GE)", False),
            ]
            for permission, label, blocks_if_missing in checks:
                if permission in permissions:
                    report.append((OK, f"{label} present."))
                else:
                    level = FAIL if blocks_if_missing else WARN
                    report.append((level, f"{label} NOT found in the API user's roles. "
                                   "Ask your Looker admin to grant it."))
        else:
            report.append((WARN, "Could not read the API user's roles; verify "
                           "'gemini_in_looker', 'save_agents' and 'publish_agent_externally'."))
    except Exception as exc:
        report.append((WARN, f"Could not verify permissions: {exc}"))

    for icon, msg in report:
        print(f"  {icon} {msg}")
    print("═" * 70)
    if blocking:
        sys.exit("\n⛔ There are blockers in the preflight. Fix them and run again.")
    print("✅ Preflight passed (⚠️ items are warnings, not blockers).\n")


# ───────────────────────── Explore verification ────────────────────────────

def verify_explores(sdk) -> None:
    """Checks that each configured Explore exists and returns visible fields."""
    print("🔎 Verifying the configured Explores…")
    issues = False
    for e in EXPLORES:
        model, explore = e["model"], e["explore"]
        try:
            info = sdk.lookml_model_explore(
                lookml_model_name=model, explore_name=explore, fields="fields"
            )
            n_dim = len(getattr(info.fields, "dimensions", None) or [])
            n_meas = len(getattr(info.fields, "measures", None) or [])
            if n_dim + n_meas == 0:
                print(f"  {WARN} {model}::{explore} returned no fields "
                      "(API-user permissions, or empty explore?).")
                issues = True
            else:
                print(f"  {OK} {model}::{explore} — {n_dim} dimensions, {n_meas} measures.")
        except Exception as exc:
            msg = str(exc)
            hint = ("wrong model/explore name or not visible to the API user"
                    if ("404" in msg or "Not found" in msg) else msg[:120])
            print(f"  {FAIL} {model}::{explore} — {hint}")
            issues = True
    if issues:
        print(f"\n{WARN} An Explore failed. If you're using the sample fictional values "
              "this is expected: replace them with real Explores.\n")
    else:
        print()


# ─────────────── Create / update the NATIVE agent in Looker ────────────────

def _sources(models):
    return [models.Source(model=e["model"], explore=e["explore"]) for e in EXPLORES]


def _build_body(models):
    return models.WriteAgent(
        name=AGENT_NAME,
        description=AGENT_DESCRIPTION,
        category=AGENT_CATEGORY,
        sources=_sources(models),
        context=models.Context(instructions=INSTRUCTIONS),
        code_interpreter=CODE_INTERPRETER,
    )


def _find_agent(sdk, models):
    """Find the agent by exact name (idempotency)."""
    try:
        for a in sdk.search_agents(name=AGENT_NAME):
            if (a.name or "").strip() == AGENT_NAME and not a.deleted:
                return a
    except Exception:
        pass
    return None


def create_or_update_agent(sdk):
    from looker_sdk.sdk.api40 import models
    body = _build_body(models)

    existing = _find_agent(sdk, models)
    if existing:
        agent = sdk.update_agent(agent_id=str(existing.id), body=body)
        print(f"🔄 Existing agent updated in Looker: '{agent.name}' (id {agent.id})")
    else:
        try:
            agent = sdk.create_agent(body=body)
        except Exception as exc:
            if "interpreter" in str(exc).lower():
                print("⚠️  The instance rejected code_interpreter; retrying without it…")
                body.code_interpreter = False
                agent = sdk.create_agent(body=body)
            else:
                raise
        print(f"✨ Agent created in Looker: '{agent.name}' (id {agent.id})")

    print("\n📍 Where to find it: Looker → Conversational Analytics → Agents tab.")
    return agent


# ──────────────── Gemini Enterprise publish guide ──────────────────────────

def ge_publish_guide(agent=None) -> None:
    name = getattr(agent, "name", None) or AGENT_NAME
    print("\n" + "═" * 70)
    print("🚀 PUBLISH TO GEMINI ENTERPRISE (preview)")
    print("═" * 70)
    print(
        "The Looker ⇄ Gemini Enterprise integration is in PREVIEW and, for now, the\n"
        "publish step is NOT available via API: it's done from the Looker UI. Follow\n"
        "these steps once:\n"
    )
    print("  A) Looker admin (once per instance):")
    print("     1. Admin → Platform → Gemini in Looker.")
    print("     2. Enable 'Publish to Gemini Enterprise' and provide:")
    print(f"          • GCP project number : {GE_PROJECT_NUMBER or '«fill GE_PROJECT_NUMBER»'}")
    print(f"          • Region (Location)  : {GE_REGION or '«fill GE_REGION»'}")
    print(f"          • Instance ID        : {GE_INSTANCE_ID or '«fill GE_INSTANCE_ID»'}")
    print("     3. In the Google Cloud console, grant the Looker service account the")
    print("        'Gemini Enterprise Admin' IAM role on the project hosting the GE")
    print("        engine (this assigns a GE license to that account).")
    print()
    print("  B) Agent editor (in Looker):")
    print(f"     1. Open the agent '{name}' in Conversational Analytics → Agents.")
    print("     2. Edit it → 'Publish settings'.")
    print("     3. Enable 'Gemini Enterprise' and click 'Update'.")
    print()
    print("  C) Gemini Enterprise admin (grant user access):")
    print("     1. 'Gemini Enterprise User' IAM role on the GE engine's project.")
    print("     2. Access to the specific agent from the Gemini Enterprise console.")
    print()
    print("  After this, the agent appears in your Gemini Enterprise instance and")
    print("  authorized users can chat with it there.")
    print("  Preview feedback: geintegration-feedback@google.com")
    print("═" * 70 + "\n")


# ─────────────────────────────── Chat ──────────────────────────────────────

def _render_chat_messages(messages) -> None:
    for m in messages:
        sm = getattr(m, "systemMessage", None) or getattr(m, "system_message", None)
        if not sm:
            continue
        text = getattr(sm, "text", None)
        if text is not None:
            parts = getattr(text, "parts", None)
            print("".join(parts) if parts else str(text), end="", flush=True)
        if getattr(sm, "data", None) is not None:
            print("\n   🔎 (Data query executed via the explore)")
        if getattr(sm, "chart", None) is not None:
            print("\n   📊 (Visualization generated — visible in the Looker UI)")
        if getattr(sm, "error", None) is not None:
            print(f"\n   ⚠️ Agent error: {sm.error}")
    print()


def chat(sdk, agent_id: str) -> None:
    from looker_sdk.sdk.api40 import models
    conv = sdk.create_conversation(body=models.WriteConversation(
        name=f"Colab test — {AGENT_NAME}",
        agent_id=str(agent_id),
    ))
    print("\n" + "═" * 70)
    print("💬 Test chat ready — same endpoint the Looker UI uses.")
    print("   Type a question, or 'exit' to finish.")
    print("═" * 70 + "\n")

    while True:
        try:
            question = input("You ▸ ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Conversation ended.")
            break
        if question.lower() in ("exit", "quit", "salir", ""):
            print("👋 Conversation ended.")
            break
        print("Agent ▸ ", end="")
        try:
            response = sdk.conversational_analytics_chat(
                body=models.ConversationalAnalyticsChatRequest(
                    conversation_id=str(conv.id),
                    user_message=question,
                ))
            _render_chat_messages(response)
            try:
                serialized = [getattr(m, "__dict__", m) for m in response]
                sdk.create_conversation_message(
                    conversation_id=str(conv.id),
                    body=models.WriteConversationMessages(messages=serialized),
                )
            except Exception:
                pass  # if the instance already persists on its own, this is redundant
        except Exception as exc:
            print(f"\n⚠️ Query failed: {exc}\n   (Typical cause: the API user lacks "
                  "access_data/explore or gemini_in_looker on the model.)")


# ─────────────────────────── Dry-run (no API) ──────────────────────────────

def _dry_run() -> None:
    """Builds the agent and prints it WITHOUT connecting to Looker (handy as an example)."""
    from looker_sdk.sdk.api40 import models
    body = _build_body(models)
    print("\n" + "═" * 70)
    print("🧪 DRY-RUN — agent definition (no API call made)")
    print("═" * 70)
    print(f"  name            : {body.name}")
    print(f"  description     : {body.description}")
    print(f"  category        : {body.category}")
    print(f"  code_interpreter: {body.code_interpreter}")
    print(f"  sources ({len(body.sources)}):")
    for s in body.sources:
        print(f"      - {s.model}::{s.explore}")
    print("  context.instructions (first lines):")
    for line in (body.context.instructions or "").splitlines()[:6]:
        print(f"      {line}")
    print("      …")
    print("═" * 70)


# ─────────────────────────────── main ──────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generic data agent in Looker, publishable to Gemini Enterprise")
    parser.add_argument("--dry-run", action="store_true",
                        help="Build & print the agent without connecting to Looker")
    parser.add_argument("--publish-guide", action="store_true",
                        help="Print only the Gemini Enterprise publish guide")
    parser.add_argument("--preflight", action="store_true",
                        help="Checks only (requires Looker credentials)")
    parser.add_argument("--no-chat", action="store_true",
                        help="Create/update without opening the test chat")
    parser.add_argument("--list", action="store_true", help="List the instance's agents")
    parser.add_argument("--show", action="store_true", help="Show the agent definition")
    parser.add_argument("--delete", action="store_true", help="Delete the agent")
    args, _ = parser.parse_known_args()  # tolerate extra argv from Colab/%run

    _validate_config()

    # Paths that DON'T require a Looker connection:
    if args.publish_guide:
        ge_publish_guide()
        return
    if args.dry_run:
        _dry_run()
        ge_publish_guide()
        return

    # From here on, Looker is required:
    looker_url, client_id, client_secret = _prompt_looker_credentials()
    sdk = _init_looker_sdk(looker_url, client_id, client_secret)
    from looker_sdk.sdk.api40 import models

    if args.list:
        for a in sdk.search_agents():
            state = " (deleted)" if a.deleted else ""
            print(f"• [{a.id}] {a.name}{state} — created by {a.created_by_name}")
        return
    if args.show:
        agent = _find_agent(sdk, models)
        print(agent if agent else f"No agent named '{AGENT_NAME}' exists.")
        return
    if args.delete:
        agent = _find_agent(sdk, models)
        if agent:
            sdk.delete_agent(str(agent.id))   # first positional arg (version-compatible)
            print(f"🗑️ Agent '{AGENT_NAME}' (id {agent.id}) deleted from Looker.")
        else:
            print(f"No agent named '{AGENT_NAME}' exists.")
        return

    # Full flow: preflight → verify explores → create → GE guide → chat
    preflight(sdk)
    if args.preflight:
        return

    verify_explores(sdk)
    agent = create_or_update_agent(sdk)
    ge_publish_guide(agent)

    if not args.no_chat:
        chat(sdk, agent_id=str(agent.id))


if __name__ == "__main__":
    main()
