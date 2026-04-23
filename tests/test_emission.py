from cisco_to_ansible import Task, render_task


def test_task_dataclass_renders_yaml():
    t = Task(
        name="Configure hostname",
        module="cisco.ios.ios_hostname",
        params=[("config", {"hostname": "SW01"}), ("state", "merged")],
    )
    lines = render_task(t, indent=4)
    joined = "\n".join(lines)
    assert "- name: " in joined
    assert "cisco.ios.ios_hostname:" in joined
    assert "hostname: SW01" in joined


def test_task_defaults():
    t = Task(name="x", module="cisco.ios.ios_config")
    assert t.params == []
    assert t.origin == []
