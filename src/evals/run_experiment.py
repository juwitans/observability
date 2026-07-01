"""run_experiment.py — prompt v1 vs v2 over the golden-set dataset.

Uses the Langfuse Experiment SDK (`dataset.run_experiment`). For each item it
re-answers the stored question from the stored context using a given answer-prompt
variant, then scores the answer with the same faithfulness judge. Run both v1
(baseline) and v2 (strict grounding) and compare the delta in the Langfuse UI.

Run:  python -m src.evals.run_experiment
      python -m src.evals.run_experiment --dataset chat-hard-cases
"""
from __future__ import annotations

import argparse

from .. import obs, prompts
from ..chat.answer import generate_answer
from ..evals.faithfulness import judge_faithfulness
from ..schemas import ChatChunk


def _ensure_prompt_versions() -> None:
    # Make sure both managed answer prompts exist before experiments link them.
    prompts.managed("chat_answer", prompts.CHAT_ANSWER_V1)
    prompts.managed("chat_answer_v2", prompts.CHAT_ANSWER_V2)


def _format_context(chunks: list[dict]) -> str:
    if not chunks:
        return "(no context)"
    return "\n\n".join(f"[{c['slug']}] {c['title']}\n{c['text'][:2000]}" for c in chunks)


def _make_task(variant: str):
    def task(*, item, **kwargs) -> str:
        question = item.input["question"]
        chunks = [ChatChunk(**c) for c in item.input.get("chunks", [])]
        answer = generate_answer(question, chunks, variant=variant)
        return answer.answer

    return task


def faithfulness_evaluator(*, input, output, expected_output, metadata, **kwargs):
    question = input["question"]
    context = _format_context(input.get("chunks", []))
    verdict = judge_faithfulness(question, context, output, name="experiment_judge")
    return [
        obs.Evaluation(
            name="faithfulness",
            value=verdict.faithfulness,
            comment=verdict.reasoning[:300],
        ),
        obs.Evaluation(name="answer_relevance", value=verdict.answer_relevance),
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="chat-hard-cases")
    args = ap.parse_args()

    _ensure_prompt_versions()
    dataset = obs.lf().get_dataset(args.dataset)

    for variant in ("v1", "v2"):
        print(f"\n=== Running experiment: answer-{variant} ===")
        result = dataset.run_experiment(
            name=f"answer-{variant}",
            task=_make_task(variant),
            evaluators=[faithfulness_evaluator],
        )
        try:
            print(result.format())
        except Exception:
            print(result)

    obs.flush()
    print("\nDone. Compare answer-v1 vs answer-v2 in the Langfuse Datasets UI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
