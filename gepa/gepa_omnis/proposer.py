"""GEPA proposal step with guards: a proposal that drops a protected rule, names
a scenario, grows too much, or is empty/unchanged/unfenced is refused and asked
again; after three refusals the parent text is kept."""
import json
import time
from pathlib import Path

from gepa.strategies.instruction_proposal import InstructionProposalSignature

from . import guards

ATTEMPTS = 3

# GEPA's default template, minus its advice to copy "niche and domain specific
# factual information" from the examples into the instruction — that is how a
# prompt learns the bench — plus the three rules the guards enforce.
REFLECTION_TEMPLATE = """I provided an AI agent with the following text, part of its system instructions:
```
<curr_param>
```

Below are tasks the agent was given, what it did, and feedback on what went wrong:
```
<side_info>
```

Write an improved version of the text so the agent behaves better on tasks like these.
- Find the general behaviour behind each failure and fix that behaviour; do not describe these particular tasks.
- Never mention names of hosts, services, files, people or values that appear in the examples, nor their expected answers.
- Keep every rule of the current text unless the feedback shows it is wrong; reword freely.
- Stay concise: the text is sent to the model on every call. Do not make it much longer than it is.

Provide the new text within ``` blocks."""


class GuardedProposer:
    def __init__(self, reflection, keep_check, seeds, deny, keep, reach, log):
        self.reflection, self.keep_check = reflection, keep_check
        self.seeds, self.deny, self.keep, self.reach = seeds, deny, keep, reach
        self.log = Path(log)
        self.log.parent.mkdir(parents=True, exist_ok=True)

    def _note(self, **kw):
        with self.log.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": round(time.time(), 1), **kw}, ensure_ascii=False) + "\n")

    def _reject_reason(self, name, raw, text, candidate):
        if "```" not in raw:
            return "the reply had no ``` block"
        if not text.strip():
            return "the proposed text is empty"
        if text.strip() == candidate[name].strip():
            return "the proposed text is identical to the current one"
        hits = guards.leaks(text, self.deny)
        if hits:
            return "it names scenario details: " + ", ".join(hits[:10])
        if guards.too_long(text, self.seeds[name]):
            return (f"it is too long ({len(text)} characters; the limit is "
                    f"{int(1.3 * len(self.seeds[name]))})")
        trial = dict(candidate, **{name: text})
        scope = {k: v for k, v in trial.items() if self.reach.get(k, set()) & self.reach.get(name, set())}
        dropped = guards.dropped_rules(scope, self.keep.get(name, []), self.keep_check)
        if dropped:
            return "it no longer states these rules: " + " | ".join(dropped)
        return None

    def __call__(self, candidate, reflective_dataset, components_to_update):
        out = {}
        for name in components_to_update:
            records = list(reflective_dataset.get(name, []))
            reason = None
            for attempt in range(1, ATTEMPTS + 1):
                template = REFLECTION_TEMPLATE
                if reason:
                    template += f"\n\nYour previous proposal was refused because {reason}. Fix that."
                prompt = InstructionProposalSignature.prompt_renderer({
                    "current_instruction_doc": candidate[name],
                    "dataset_with_feedback": records, "prompt_template": template})
                raw = self.reflection(prompt)
                text = InstructionProposalSignature.output_extractor(raw)["new_instruction"]
                reason = self._reject_reason(name, raw, text, candidate)
                self._note(component=name, attempt=attempt,
                           verdict="accepted" if reason is None else "rejected",
                           reason=reason, text=text)
                if reason is None:
                    out[name] = text
                    break
            else:
                out[name] = candidate[name]
        return out
