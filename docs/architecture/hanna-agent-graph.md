# Hanna Agent graph

Graph identity: `hanna-v1` / semantic version `1.0.0` / state schema `1`.

```mermaid
flowchart TD
    START --> Load["load_context"]
    Load --> Consent["consent_guard"]
    Consent --> Risk["risk_prescreen"]
    Risk -->|high or immediate| Referral["create_referral"]
    Referral --> Safe["safety_response"]
    Risk -->|none low moderate| Classify["classify_message"]
    Classify --> Complete["assess_completeness"]
    Complete -->|insufficient| Clarify["ask_clarifying_question"]
    Complete -->|sufficient| Retrieve["retrieve_knowledge"]
    Retrieve --> PlanTools["plan_tools"]
    PlanTools -->|registered tools| Execute["execute_tools"]
    PlanTools -->|no tools| Plan["plan_response"]
    Execute --> Plan
    Plan --> Generate["generate_response"]
    Generate --> Citations["validate_citations"]
    Citations -->|invalid| Repair["repair_or_safe_fallback"]
    Citations -->|valid| Postcheck["safety_postcheck"]
    Repair --> Postcheck
    Postcheck -->|unsafe| Referral
    Postcheck -->|safe| Persist["persist_turn"]
    Safe --> Persist
    Clarify --> Persist
    Persist --> END
```

Every node accepts and returns validated state fields. Side effects exist only in retrieval, tool,
referral, checkpoint and persistence nodes. The turn pins graph, prompt, model-route, tool-registry,
safety-policy and knowledge-index versions. Each completed node writes an encrypted database checkpoint
and a redacted trace; resume uses the last compatible checkpoint and never silently changes graph schema.

Risk screening and safety postcheck are mandatory and are excluded from cost-based degradation. Retrieved
documents and tool outputs are untrusted data. No raw response text reaches the client until citation and
safety validation have passed.
