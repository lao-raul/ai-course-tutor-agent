"""Retrieval benchmark fixture — synthetic course content.

This module creates a synthetic course with known content and verifies that the
retrieval pipeline can correctly answer questions against it.

Since benchmark data requires copyright clearance (design-spec §9, decision 3),
this fixture uses only synthetic generated content — no real Leeds material.

Usage:
    pytest tests/retrieval_benchmark.py -v
    python tests/retrieval_benchmark.py  (standalone)
"""

from __future__ import annotations

from pathlib import Path

# Synthetic module content — no real course material
SYNTHETIC_MODULES = [
    {
        "filename": "week1_introduction.txt",
        "content": """
Week 1: Introduction to Artificial Intelligence

Artificial Intelligence (AI) is the field of computer science devoted to creating
systems that perform tasks requiring human intelligence. Key topics include:

- Machine learning: systems that learn from data without being explicitly programmed
- Natural language processing: enabling computers to understand and generate human language
- Computer vision: interpreting and understanding visual information from the world
- Robotics: intelligent control of physical agents in environments

The Turing Test, proposed by Alan Turing in 1950, measures machine intelligence by
whether a human can distinguish AI-generated responses from human responses.
A pass indicates the machine exhibits intelligent behavior equivalent to human behavior.
        """,
    },
    {
        "filename": "week2_search.txt",
        "content": """
Week 2: Search Algorithms

Search is fundamental to AI problem solving. Key algorithms include:

Breadth-First Search (BFS): Explores all nodes at depth d before depth d+1.
  - Time complexity: O(b^d) where b is the branching factor
  - Space complexity: O(b^d)
  - Guarantees shortest path in unweighted graphs

Depth-First Search (DFS): Explores as far as possible along each branch before backtracking.
  - Time complexity: O(b^d)
  - Space complexity: O(d) — only stores the current path
  - Does NOT guarantee shortest path

A* Search: Uses a heuristic function h(n) to estimate cost from node n to goal.
  - Optimal if h(n) is admissible (never overestimates true cost)
  - f(n) = g(n) + h(n) where g(n) = path cost from start, h(n) = heuristic

The 8-puzzle is a classic domain for search algorithms. The goal state has tiles 1-8
in order with blank in position 9. The optimal solution for the 8-puzzle requires
20-30 moves depending on the starting configuration.
        """,
    },
    {
        "filename": "week3_logic.txt",
        "content": """
Week 3: Logic and Planning

Propositional Logic uses boolean variables and logical connectives:
  - AND (AND), OR (OR), NOT (NOT), IMPLIES (IMPLIES)
  - Modus ponens: from P and (P IMPLIES Q) infer Q

First-Order Logic (FOL) adds quantifiers:
  - forall x: for all x
  - exists x: there exists x

Planning is the task of finding a sequence of actions to achieve a goal.
The STRIPS representation uses:
  - Preconditions: what must be true before an action
  - Effects: how the action changes the world state

The Blocks World is a classic planning domain. Blocks are stacked on a table.
Operators include: UNSTACK(block, on), STACK(block, on), PICKUP(block), PUTDOWN(block).
The goal is typically expressed as a set of On(x,y) atoms specifying final positions.
        """,
    },
    {
        "filename": "week4_probability.txt",
        "content": """
Week 4: Probabilistic Reasoning

Probability fundamentals:
  - P(A): probability of event A, ranges from 0 to 1
  - Conditional: P(A|B) = P(A,B) / P(B)
  - Bayes' Rule: P(A|B) = P(B|A) x P(A) / P(B)

Bayesian Networks represent joint distributions over variables as directed acyclic graphs.
Each node X has a CPD P(X | Parents(X)).

A Hidden Markov Model (HMM) has:
  - Hidden states S = {s1, s2, ..., sn}
  - Observations O = {o1, o2, ..., om}
  - Transition model: P(S_t | S_{t-1})
  - Observation model: P(O_t | S_t)

The Viterbi algorithm finds the most likely sequence of hidden states in an HMM.
The forward algorithm computes the probability of an observation sequence.
        """,
    },
    {
        "filename": "exercises_week3.txt",
        "content": """
Exercise Set — Week 3

Question 1 (Propositional Logic):
Given the knowledge base: {P IMPLIES Q, P, Q IMPLIES R}, use modus ponens to derive Q, then R.
What is the final conclusion?

Question 2 (STRIPS Planning):
In the Blocks World with blocks A, B, C on a table, initial state: On(A,B), On(B,C).
Goal: On(A,B), On(B,C), On(C,table). Write the plan using UNSTACK, STACK, PUTDOWN.

Question 3 (First-Order Logic):
Express in FOL: "Every student who passes the exam is happy."
Use predicates: Student(x), Pass(x), Happy(x).

Solution hints:
- Q1: From P and P->Q derive Q. From Q and Q->R derive R. Final: R.
- Q2: The solution requires unstacking A from B first, then restacking.
- Q3: forall x: (Student(x) AND Pass(x)) -> Happy(x)
        """,
    },
]

# Benchmark questions with expected source files and answer requirements
BENCHMARK_CASES = [
    {
        "id": "q1",
        "question": "What is the Turing Test and who proposed it?",
        "expected_sources": ["week1_introduction.txt"],
        "key_concepts": ["Turing Test", "Alan Turing", "1950"],
        "abstain_if_missing": False,
    },
    {
        "id": "q2",
        "question": "What is the time complexity of BFS and what does b represent?",
        "expected_sources": ["week2_search.txt"],
        "key_concepts": ["O(b^d)", "branching factor"],
        "abstain_if_missing": False,
    },
    {
        "id": "q3",
        "question": "What are the three key algorithms for search covered in week 2?",
        "expected_sources": ["week2_search.txt"],
        "key_concepts": ["BFS", "DFS", "A*"],
        "abstain_if_missing": False,
    },
    {
        "id": "q4",
        "question": "What is Bayes' Rule?",
        "expected_sources": ["week4_probability.txt"],
        "key_concepts": ["P(A|B)", "P(B|A)", "P(A)"],
        "abstain_if_missing": False,
    },
    {
        "id": "q5",
        "question": "What is modus ponens and how is it used in propositional logic?",
        "expected_sources": ["week3_logic.txt"],
        "key_concepts": ["modus ponens", "P IMPLIES Q", "infer Q"],
        "abstain_if_missing": False,
    },
    {
        "id": "q6",
        "question": "How do you express 'every student who passes is happy' in First-Order Logic?",
        "expected_sources": ["exercises_week3.txt"],
        "key_concepts": ["forall x", "Student(x)", "Pass(x)", "Happy(x)"],
        "abstain_if_missing": False,
    },
    {
        "id": "q7",
        "question": "What is the optimal solution length for the 8-puzzle?",
        "expected_sources": ["week2_search.txt"],
        "key_concepts": ["20-30 moves"],
        "abstain_if_missing": False,
    },
    {
        "id": "q8",
        "question": "What is the Viterbi algorithm used for?",
        "expected_sources": ["week4_probability.txt"],
        "key_concepts": ["HMM", "hidden states", "most likely sequence"],
        "abstain_if_missing": False,
    },
    {
        "id": "q9",
        "question": "What is NOT covered in this course about neural networks?",
        "expected_sources": [],
        "key_concepts": [],
        "abstain_if_missing": True,  # Should abstain — topic not in content
    },
    {
        "id": "q10",
        "question": "What are the components of a Hidden Markov Model?",
        "expected_sources": ["week4_probability.txt"],
        "key_concepts": ["hidden states", "observations", "transition model", "observation model"],
        "abstain_if_missing": False,
    },
]


def write_synthetic_course(tmp_path: Path) -> Path:
    """Write synthetic course files to a directory and return the path."""
    course_dir = tmp_path / "synthetic_course"
    course_dir.mkdir(parents=True, exist_ok=True)
    for module in SYNTHETIC_MODULES:
        (course_dir / module["filename"]).write_text(module["content"].strip(), encoding="utf-8")
    return course_dir


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        course_dir = write_synthetic_course(tmp_path)
        print(f"Synthetic course written to: {course_dir}")
        print(f"Files: {sorted(f.name for f in course_dir.iterdir())}")
        print(f"\nBenchmark cases: {len(BENCHMARK_CASES)}")
        for case in BENCHMARK_CASES:
            print(f"  [{case['id']}] {case['question'][:60]}...")
