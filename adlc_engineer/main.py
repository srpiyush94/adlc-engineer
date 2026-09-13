from typing import TypedDict

from langgraph.graph import StateGraph, START, END


class ADLCState(TypedDict):
    user_request: str
    discovery: dict
    requirements: dict
    architecture: dict
    evaluation: dict
    approval: dict


def discover(state: ADLCState):
    print("\n[DISCOVER]")

    return {
        "discovery": {
            "problem": state["user_request"],
            "status": "discovered"
        }
    }


def define(state: ADLCState):
    print("[DEFINE]")

    return {
        "requirements": {
            "goal": state["discovery"]["problem"],
            "status": "defined"
        }
    }


def design(state: ADLCState):
    print("[DESIGN]")

    return {
        "architecture": {
            "approach": "Incremental modernization",
            "status": "designed"
        }
    }


def evaluate(state: ADLCState):
    print("[EVALUATE]")

    return {
        "evaluation": {
            "status": "passed",
            "risks": [
                "Repository evidence is not yet available",
                "Architecture decision requires validation"
            ]
        }
    }


def human_approval(state: ADLCState):
    print("[HUMAN APPROVAL]")

    return {
        "approval": {
            "required": True,
            "status": "pending"
        }
    }


def build_graph():
    graph = StateGraph(ADLCState)

    graph.add_node("discover", discover)
    graph.add_node("define", define)
    graph.add_node("design", design)
    graph.add_node("evaluate", evaluate)
    graph.add_node("human_approval", human_approval)

    graph.add_edge(START, "discover")
    graph.add_edge("discover", "define")
    graph.add_edge("define", "design")
    graph.add_edge("design", "evaluate")
    graph.add_edge("evaluate", "human_approval")
    graph.add_edge("human_approval", END)

    return graph.compile()


def main():
    agent = build_graph()

    result = agent.invoke({
        "user_request": "Modernize a Spring Boot application"
    })

    print("\n=== FINAL STATE ===")
    print(result)


if __name__ == "__main__":
    main()