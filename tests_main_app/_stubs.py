
import sys
import types


def install_stubs():
    if "langgraph" in sys.modules and getattr(sys.modules["langgraph"], "_is_test_stub", False):
        return  # already installed this session

    langgraph_mod = types.ModuleType("langgraph")
    langgraph_mod._is_test_stub = True
    langgraph_types_mod = types.ModuleType("langgraph.types")

    def _interrupt_stub(*a, **k):
        raise RuntimeError(
            "interrupt() stub invoked — this test harness does not support "
            "exercising interrupt-based nodes; see delivery notes' limitations."
        )

    langgraph_types_mod.interrupt = _interrupt_stub
    langgraph_mod.types = langgraph_types_mod
    sys.modules["langgraph"] = langgraph_mod
    sys.modules["langgraph.types"] = langgraph_types_mod
