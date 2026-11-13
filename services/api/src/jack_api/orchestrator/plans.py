"""Plan templates: the steps a task goes through after requirement discovery.

Plans are deterministic and built from the approved specification. Each step names its
executor, the agent role that will own it from Milestone 7 (Section 7), whether it is safe to
repeat after a crash (idempotent), and whether it needs the user's approval first. Steps whose
capability doesn't exist yet name it, and the workflow waits there honestly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SOFTWARE = {"website", "web_app", "windows_app", "android_app", "ios_app", "api", "crm", "erp",
            "hrms", "trading_app", "ai_platform"}


@dataclass(frozen=True)
class StepDef:
    key: str
    title: str
    kind: str
    role: str
    instructions: str = ""
    idempotent: bool = True
    needs_approval: bool = False


def doc(key: str, title: str, role: str, artifact: str, instructions: str) -> StepDef:
    return StepDef(key, title, "reasoning.document", role,
                   f"[artifact:{artifact}] {instructions}")


DELIVER = StepDef("deliver", "Deliver the result", "deliver", "Documentation Agent",
                  "Summarise what was produced and where it is.")


def build_plan(spec: dict[str, Any]) -> list[StepDef]:
    cat = spec.get("category", "")
    hosting = (spec.get("hosting") or {}).get("choice")
    if cat == "research":
        return [doc("research", "Research and write the answer", "Research Agent", "answer.md",
                    "Answer the research question from the specification. Compare options "
                    "where relevant, state assumptions, and say what should be checked against "
                    "current sources before relying on it."),
                DELIVER]
    if cat == "documentation":
        return [doc("outline", "Outline the document", "Documentation Agent", "outline.md",
                    "Produce a structured outline for the requested document and audience."),
                doc("write", "Write the document", "Documentation Agent", "document.md",
                    "Write the complete document following the outline from the previous step."),
                DELIVER]
    if cat in SOFTWARE:
        steps = [
            doc("architecture", "Solution architecture", "Solution Architect",
                "architecture.md",
                "Write the solution architecture for this specification: components, data "
                "model outline, integrations, hosting and deployment approach, security "
                "considerations, and a phased delivery plan."),
            StepDef("structure", "Create the project structure", "capability.build",
                    "Senior Developer"),
            StepDef("backend", "Build the back end", "capability.build", "Backend Developer"),
            StepDef("frontend", "Build the front end", "capability.build", "Frontend Developer"),
        ]
        if spec.get("integrations"):
            steps.append(StepDef("integrations", "Connect external services",
                                 "capability.build", "Backend Developer"))
        steps += [
            StepDef("testing", "Test and repair", "capability.test", "QA Automation Engineer"),
            StepDef("security", "Security review", "capability.test", "Cybersecurity Engineer"),
        ]
        if hosting in ("own_server", "managed"):
            steps += [
                StepDef("release", "Prepare the release", "capability.deploy",
                        "Release Manager"),
                StepDef("deploy", "Deploy to production", "capability.deploy", "DevOps Engineer",
                        idempotent=False, needs_approval=True),
            ]
        return [*steps, DELIVER]
    if cat in ("image_generation", "photo_editing", "video_production"):
        return [doc("brief", "Creative brief", "Creative Designer", "brief.md",
                    "Write a precise creative brief from the specification: subject, style, "
                    "formats, and prompts ready for an image or video provider."),
                StepDef("produce", "Produce the media", "capability.creative",
                        "Creative Designer"),
                DELIVER]
    if cat == "infrastructure":
        return [doc("plan", "Diagnostic plan", "System Administrator", "diagnostic-plan.md",
                    "Write a step-by-step, read-only-first diagnostic plan for the server and "
                    "goal in the specification, with the evidence to collect at each step."),
                StepDef("connect", "Connect over SSH and run the plan", "capability.ssh",
                        "System Administrator", idempotent=False),
                DELIVER]
    if cat == "security_audit":
        return [doc("plan", "Audit plan", "Cybersecurity Engineer", "audit-plan.md",
                    "Write the audit plan for the authorised scope: methodology, checks, "
                    "evidence to collect, and how findings will be rated."),
                StepDef("checks", "Run the checks", "capability.ssh", "Cybersecurity Engineer",
                        idempotent=False),
                DELIVER]
    if cat == "automation":
        return [doc("design", "Automation design", "Solution Architect",
                    "automation-design.md",
                    "Design the automation: trigger, steps, systems touched, error handling, "
                    "and what needs credentials or approval."),
                StepDef("implement", "Build the automation", "capability.windows",
                        "Senior Developer"),
                DELIVER]
    return [DELIVER]
