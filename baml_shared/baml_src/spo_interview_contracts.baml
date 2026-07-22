// SPO-native workflow interview (ADR-0029 Slice 2 — docs/plans/slice-2-spo-interview.md).
// Supersedes IterateBPMNGraph (the BPMN-fused interview). The KEEPER pattern —
// mesh-informed select-from-authorized-set — re-aimed at the WorkflowDefinition model,
// and now with the VERB question the old interview never asked.
//
// The contract's discipline (all server-enforced, NOT trusted to the model):
//   * The authorized sets (available_subjects / available_verbs / available_audiences) are
//     COMPUTED SERVER-SIDE and passed in. The model may ONLY echo an exact value from them;
//     the server re-validates every pick (spo_interview.validate_pick) and hard-REFUSES an
//     out-of-set pick. The model cannot smuggle a hallucinated subject/verb/audience past it.
//   * There is deliberately NO `is_ready_to_compile` flag. Termination is decided SERVER-SIDE
//     (the WorkflowDefinition validates against its schema); the model does not get to claim
//     "done". This closes the old interview's LLM-asserts-completion hole.
//   * The verb set is computed FOR THE FOCUSED SUBJECT (Engine O /find_compatible_verbs), so a
//     verb offered is structurally eligible for that subject by construction.

// ── The action the model proposes this turn ─────────────────────────────

enum SPOPickAction {
  SetMetadata   @description("Record the workflow's id / name / classification from what the user stated. Use before adding steps.")
  FocusSubject  @description("The user chose a SUBJECT to build the next SPO step around. The server will fetch that subject's compatible VERBS for the next turn. Requires subject_uri = an EXACT value from available_subjects.")
  AddSpoStep    @description("Add a pre-resolved SPO operation step. Requires subject_uri AND verb_iri, each an EXACT value from available_subjects / available_verbs. The verb's output type is derived server-side.")
  AddHumanAwait @description("Add a designed human-approval step (suspends the workflow awaiting an authorized human). Requires audience = an EXACT value from available_audiences.")
  AddDirectCall @description("Add a TRANSITIONAL direct_call step for an infrastructural action that is not yet a mesh verb (e.g. a publish emit). Requires endpoint AND capability. The capability is Topaz-gated at run time.")
  NoPick        @description("No concrete pick this turn — you are still clarifying with the user. Put the question in agent_reply. Use this rather than guessing.")
}

// ── The structured pick (validated server-side after return) ────────────

class SPOPick {
  action SPOPickAction

  // SetMetadata
  workflow_id string? @description("snake_case id, e.g. 'promote_answer_artifact'. Only for SetMetadata.")
  workflow_name string? @description("Human-readable name. Only for SetMetadata.")
  classification string? @description("The workflow's declared domain / compartment, e.g. 'DATA_ENGINEERING'. Gates who may observe and scopes the verb question. Only for SetMetadata.")

  // FocusSubject / AddSpoStep
  subject_uri string? @description("An EXACT value copied verbatim from available_subjects. NEVER invent or paraphrase one.")
  verb_iri string? @description("An EXACT value copied verbatim from available_verbs (which are the verbs compatible with the focused subject). NEVER invent one.")

  // AddHumanAwait
  audience string? @description("An EXACT value copied verbatim from available_audiences.")
  step_title string? @description("Short title shown to the approver. Optional.")
  step_summary string? @description("One-line summary shown to the approver. Optional.")

  // AddDirectCall
  endpoint string? @description("The action endpoint (may contain {placeholders} bound at trigger time).")
  capability string? @description("Topaz-decidable capability for the action, e.g. 'mesh:publishArtifact'.")

  // Optional explicit step id; the server assigns one if omitted.
  step_id string? @description("Optional stable id for the step, e.g. 'approve_promotion'.")
}

// ── What the interview returns each turn ────────────────────────────────

class SPOInterviewTurn {
  agent_reply string @description("Conversational text to the user (2-5 sentences). If you refused a pick or something was out-of-set, explain and offer the closest legal options.")
  pick SPOPick @description("The structured pick for this turn. Use action=NoPick (with the question in agent_reply) when you are still clarifying.")
}

// ── The interview function ──────────────────────────────────────────────

function InterviewSPOWorkflow(
  chat_history: string,
  user_message: string,
  partial_definition_json: string,
  available_subjects: string,
  available_verbs: string,
  available_audiences: string,
) -> SPOInterviewTurn {
  client MainAgent
  prompt #"
    {{ _.role("system") }}
    You are the SPO Workflow Architect — an expert interviewer that helps a user AUTHOR a
    process-workflow definition through conversation, one step at a time. A workflow is an
    ordered list of steps; each step is one of:
      • spo_operation  — a (subject, verb) operation the mesh already knows how to route.
      • human_await    — a designed pause awaiting an authorized human's approval.
      • direct_call    — a transitional call to an action that is not yet a mesh verb.

    HOW YOU WORK (these rules are ENFORCED by the server — violating them wastes a turn):
    1. SELECT-FROM-AUTHORIZED-SET. You may ONLY choose subjects, verbs, and audiences by
       copying an EXACT value from the lists below. If the user asks for something not in a
       list, say so and offer the closest legal option — do NOT invent an identifier. The
       server re-checks every pick and hard-refuses anything out-of-set.
    2. THE VERB QUESTION. To add an spo_operation you must FIRST FocusSubject (pick the
       subject), because the compatible VERBS are computed for that subject and appear in
       AVAILABLE VERBS only after it is focused. Then AddSpoStep with subject_uri + verb_iri.
    3. NO SELF-DECLARED COMPLETION. Do not announce the workflow is finished — the server
       decides completion when the accumulated definition validates. Keep proposing the next
       piece (metadata, then steps) until the user is done.
    4. ONE PICK PER TURN. Return exactly one action. When you are still clarifying, use
       action=NoPick and put the question in agent_reply.

    ══════════════════════════════════════════════════════════
    AVAILABLE SUBJECTS (ontology classes / instances you may build steps around,
    already filtered to what THIS author may see):
    {{ available_subjects }}

    AVAILABLE VERBS (compatible with the currently-focused subject; empty until you
    FocusSubject):
    {{ available_verbs }}

    AVAILABLE AUDIENCES (approval audiences you may route a human_await to):
    {{ available_audiences }}
    ══════════════════════════════════════════════════════════

    WORKFLOW SO FAR (the partial definition being built):
    {{ partial_definition_json }}

    BEHAVIOUR:
    - Be concise (2-5 sentences) and technical but approachable.
    - Guide the user: first the workflow's name + classification (SetMetadata), then the
      steps in order. Confirm each step you add.
    - When you add a step, briefly say what it does and why.

    {{ _.role("user") }}
    CONVERSATION SO FAR:
    {{ chat_history }}

    LATEST MESSAGE:
    {{ user_message }}

    {{ ctx.output_format }}
  "#
}

// ── A generative test (exercised only when running `baml-cli test`) ─────

test focus_then_add_spo_step {
  functions [InterviewSPOWorkflow]
  args {
    chat_history "User: I want a workflow that analyzes an agent task.\nAgent: Sure — what should we call it?"
    user_message "Call it analyze_task, classification DATA_ENGINEERING, and the subject is the AgentTask."
    partial_definition_json "{\"steps\": []}"
    available_subjects "- http://invincible-agent/mesh#AgentTask  (Agent Task)"
    available_verbs ""
    available_audiences "- promotion:DATA_ENGINEERING"
  }
}
