"""Run the Business Analyst agent in a terminal."""
from langgraph.types import Command
from agent.graph import build_graph

def main():
    graph = build_graph()
    config = {"configurable": {"thread_id": "client-1"}, "recursion_limit": 100}
    result = graph.invoke({"files": []}, config)
    while "__interrupt__" in result:
        ask = result["__interrupt__"][0].value
        print("\\n" + ask["question"])
        for i, option in enumerate(ask["options"], 1):
            print(f"  {i}. {option}")
        reply = input("> ")
        result = graph.invoke(Command(resume=reply), config)

if __name__ == "__main__":
    main()
